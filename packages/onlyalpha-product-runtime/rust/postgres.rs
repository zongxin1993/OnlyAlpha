//! Existing PostgreSQL Product Command authority, including caller-owned transactions.
use crate::command::{
    Admission, Binding, CommandId, CommandKind, Error, Outcome, OutcomeKind, Put, Receipt,
    verify_binding,
};
use onlyalpha_domain::time::{OnlyTimestamp, OnlyUtcDateTime};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio_postgres::{Client, Row, Transaction};

const ADMISSION: &str = "SELECT command_id::text AS a_id, command_kind AS a_kind, command_fingerprint AS a_fingerprint, schema_version AS a_schema FROM product_command_admission WHERE command_id=$1::text::uuid";
// Join only on ownership identity. Joining copied kind/fingerprint would hide corrupt relations.
const BINDING: &str = "SELECT a.command_id::text AS a_id, a.command_kind AS a_kind, a.command_fingerprint AS a_fingerprint, a.schema_version AS a_schema, r.command_id::text AS r_id, r.command_kind AS r_kind, r.command_fingerprint AS r_fingerprint, r.schema_version AS r_schema, r.outcome_kind, r.outcome_id, r.accepted_at FROM product_command_admission a FULL JOIN product_command_receipt r ON a.command_id=r.command_id WHERE COALESCE(a.command_id,r.command_id)=$1::text::uuid";

/// The node owns connection credentials, TLS, connection bounds and lifecycle.
/// This authority neither creates connections nor chooses a semantic store.
pub struct Commands<'a> {
    client: &'a mut Client,
}
impl<'a> Commands<'a> {
    pub fn new(client: &'a mut Client) -> Self {
        Self { client }
    }
    pub async fn load_admission(&mut self, id: &CommandId) -> Result<Option<Admission>, Error> {
        let tx = self
            .client
            .transaction()
            .await
            .map_err(|_| Error::Unavailable)?;
        let result = Self::load_admission_in_transaction(&tx, id).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(result)
    }
    pub async fn verify_binding(&mut self, id: &CommandId) -> Result<Binding, Error> {
        let tx = self
            .client
            .transaction()
            .await
            .map_err(|_| Error::Unavailable)?;
        let result = Self::verify_binding_in_transaction(&tx, id).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(result)
    }
    pub async fn load_verified_receipt(
        &mut self,
        id: &CommandId,
    ) -> Result<Option<Receipt>, Error> {
        Ok(match self.verify_binding(id).await? {
            Binding::Accepted(receipt) => Some(receipt),
            _ => None,
        })
    }
    pub async fn admit_exact(&mut self, admission: &Admission) -> Result<Put, Error> {
        let tx = self
            .client
            .transaction()
            .await
            .map_err(|_| Error::Unavailable)?;
        let result = Self::admit_exact_in_transaction(&tx, admission).await?;
        // A lost commit acknowledgement remains unavailable/uncertain, never an absent command.
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(result)
    }
    pub async fn put_verified_receipt(&mut self, receipt: &Receipt) -> Result<Put, Error> {
        let tx = self
            .client
            .transaction()
            .await
            .map_err(|_| Error::Unavailable)?;
        let result = Self::put_verified_receipt_in_transaction(&tx, receipt).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(result)
    }
    pub async fn lock_command(tx: &Transaction<'_>, id: &CommandId) -> Result<(), Error> {
        bounds(tx).await?;
        tx.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
            &[&id.value()],
        )
        .await
        .map_err(|_| Error::Unavailable)?;
        Ok(())
    }
    /// Admission remains independently readable: an optional downstream receipt is not its proof.
    pub async fn load_admission_in_transaction(
        tx: &Transaction<'_>,
        id: &CommandId,
    ) -> Result<Option<Admission>, Error> {
        bounds(tx).await?;
        let row = tx
            .query_opt(ADMISSION, &[&id.value()])
            .await
            .map_err(|_| Error::Unavailable)?;
        row.map(|row| decode_admission(&row, false, id)?.ok_or(Error::AdmissionCorrupt))
            .transpose()
    }
    pub async fn verify_binding_in_transaction(
        tx: &Transaction<'_>,
        id: &CommandId,
    ) -> Result<Binding, Error> {
        bounds(tx).await?;
        let Some(row) = tx
            .query_opt(BINDING, &[&id.value()])
            .await
            .map_err(|_| Error::Unavailable)?
        else {
            return Ok(Binding::None);
        };
        let admission = decode_admission(&row, false, id)?;
        let receipt = if let Some(copied) = decode_admission(&row, true, id)? {
            let kind: String = row
                .try_get("outcome_kind")
                .map_err(|_| Error::ReceiptCorrupt)?;
            let outcome_id: String = row
                .try_get("outcome_id")
                .map_err(|_| Error::ReceiptCorrupt)?;
            let accepted: SystemTime = row
                .try_get("accepted_at")
                .map_err(|_| Error::ReceiptCorrupt)?;
            let outcome = Outcome::new(
                kind.parse::<OutcomeKind>()
                    .map_err(|_| Error::ReceiptCorrupt)?,
                &outcome_id,
            )
            .map_err(|_| Error::ReceiptCorrupt)?;
            Some(
                Receipt::new(copied, outcome, &datetime(accepted)?.to_string())
                    .map_err(|_| Error::ReceiptCorrupt)?,
            )
        } else {
            None
        };
        // The SELECT already found a row. It cannot be interpreted as certified absence.
        if admission.is_none() && receipt.is_none() {
            return Err(Error::AdmissionCorrupt);
        }
        verify_binding(admission, receipt).map_err(|error| {
            if error == Error::BindingMismatch {
                Error::ReceiptCorrupt
            } else {
                error
            }
        })
    }
    pub async fn load_verified_receipt_in_transaction(
        tx: &Transaction<'_>,
        id: &CommandId,
    ) -> Result<Option<Receipt>, Error> {
        Ok(match Self::verify_binding_in_transaction(tx, id).await? {
            Binding::Accepted(receipt) => Some(receipt),
            _ => None,
        })
    }
    /// Returns tentative disposition; only the caller can commit its business transaction.
    pub async fn admit_exact_in_transaction(
        tx: &Transaction<'_>,
        admission: &Admission,
    ) -> Result<Put, Error> {
        Self::lock_command(tx, admission.id()).await?;
        let existing = Self::verify_binding_in_transaction(tx, admission.id()).await?;
        let bound = match &existing {
            Binding::None => None,
            Binding::Admitted(a) => Some(a),
            Binding::Accepted(r) => Some(r.admission()),
        };
        if let Some(bound) = bound {
            return if bound == admission {
                Ok(Put::Reused)
            } else {
                Err(Error::Conflict)
            };
        }
        let inserted=tx.execute("INSERT INTO product_command_admission(command_id,command_kind,command_fingerprint,schema_version) VALUES($1::text::uuid,$2,$3,1) ON CONFLICT(command_id) DO NOTHING",&[&admission.id().value(),&admission.kind().as_str(),&admission.fingerprint()]).await.map_err(|_|Error::Unavailable)?;
        let actual = Self::verify_binding_in_transaction(tx, admission.id()).await?;
        match actual {
            Binding::Admitted(actual) if actual == *admission && inserted == 1 => Ok(Put::Created),
            Binding::Admitted(actual) if actual != *admission => Err(Error::Conflict),
            Binding::Accepted(_) => Err(Error::ReceiptCorrupt),
            _ => Err(Error::AdmissionCorrupt),
        }
    }
    /// Receipt and same-database business facts share the caller's one commit boundary.
    pub async fn put_verified_receipt_in_transaction(
        tx: &Transaction<'_>,
        receipt: &Receipt,
    ) -> Result<Put, Error> {
        Self::lock_command(tx, receipt.admission().id()).await?;
        match Self::verify_binding_in_transaction(tx, receipt.admission().id()).await? {
            Binding::None => return Err(Error::ReceiptCorrupt),
            Binding::Admitted(a) if a != *receipt.admission() => return Err(Error::ReceiptCorrupt),
            Binding::Accepted(existing) => {
                return if existing == *receipt {
                    Ok(Put::Reused)
                } else if existing.admission() != receipt.admission() {
                    Err(Error::ReceiptCorrupt)
                } else {
                    Err(Error::Conflict)
                };
            }
            _ => {}
        }
        let accepted = system_time(receipt.accepted_at())?;
        let inserted=tx.execute("INSERT INTO product_command_receipt(command_id,command_kind,command_fingerprint,outcome_kind,outcome_id,accepted_at,schema_version) VALUES($1::text::uuid,$2,$3,$4,$5,$6,1) ON CONFLICT(command_id) DO NOTHING",&[&receipt.admission().id().value(),&receipt.admission().kind().as_str(),&receipt.admission().fingerprint(),&receipt.outcome().kind().as_str(),&receipt.outcome().id(),&accepted]).await.map_err(|_|Error::Unavailable)?;
        match Self::verify_binding_in_transaction(tx, receipt.admission().id()).await? {
            Binding::Accepted(actual) if actual == *receipt => Ok(if inserted == 1 {
                Put::Created
            } else {
                Put::Reused
            }),
            Binding::Accepted(_) => Err(Error::Conflict),
            _ => Err(Error::ReceiptCorrupt),
        }
    }
}
pub(crate) async fn bounds(tx: &Transaction<'_>) -> Result<(), Error> {
    // Preserve a stricter caller budget. PostgreSQL reports these GUCs in ms;
    // zero explicitly means unlimited, so it acquires this authority's cap.
    let row=tx.query_one("SELECT (SELECT setting::bigint FROM pg_settings WHERE name='statement_timeout' AND unit='ms'), (SELECT setting::bigint FROM pg_settings WHERE name='lock_timeout' AND unit='ms')",&[]).await.map_err(|_|Error::Unavailable)?;
    let statement: i64 = row
        .try_get::<_, Option<i64>>(0)
        .map_err(|_| Error::Unavailable)?
        .ok_or(Error::Unavailable)?;
    let lock: i64 = row
        .try_get::<_, Option<i64>>(1)
        .map_err(|_| Error::Unavailable)?
        .ok_or(Error::Unavailable)?;
    if statement < 0 || lock < 0 {
        return Err(Error::Unavailable);
    }
    let statement = if statement == 0 {
        5000
    } else {
        statement.min(5000)
    };
    let lock = (if lock == 0 { 2000 } else { lock.min(2000) }).min(statement);
    tx.query_one("SELECT set_config('timezone','UTC',true),set_config('statement_timeout',$1,true),set_config('lock_timeout',$2,true)",&[&format!("{statement}ms"),&format!("{lock}ms")]).await.map_err(|_|Error::Unavailable)?;
    Ok(())
}
fn decode_admission(
    row: &Row,
    copied: bool,
    expected: &CommandId,
) -> Result<Option<Admission>, Error> {
    let (keys, error) = if copied {
        (
            ["r_id", "r_kind", "r_fingerprint", "r_schema"],
            Error::ReceiptCorrupt,
        )
    } else {
        (
            ["a_id", "a_kind", "a_fingerprint", "a_schema"],
            Error::AdmissionCorrupt,
        )
    };
    let id: Option<String> = row.try_get(keys[0]).map_err(|_| error)?;
    let Some(id) = id else { return Ok(None) };
    let schema: i16 = row.try_get(keys[3]).map_err(|_| error)?;
    let kind: String = row.try_get(keys[1]).map_err(|_| error)?;
    let fingerprint: String = row.try_get(keys[2]).map_err(|_| error)?;
    let id = CommandId::new(&id).map_err(|_| error)?;
    if id != *expected || schema != 1 {
        return Err(error);
    }
    Admission::new(
        id,
        kind.parse::<CommandKind>().map_err(|_| error)?,
        &fingerprint,
    )
    .map(Some)
    .map_err(|_| error)
}
pub(crate) fn datetime(value: SystemTime) -> Result<OnlyUtcDateTime, Error> {
    let nanos = match value.duration_since(UNIX_EPOCH) {
        Ok(duration) => i128::try_from(duration.as_nanos()).map_err(|_| Error::ReceiptCorrupt)?,
        Err(error) => {
            -i128::try_from(error.duration().as_nanos()).map_err(|_| Error::ReceiptCorrupt)?
        }
    };
    OnlyTimestamp::from_unix_nanos(nanos.into())
        .to_datetime_exact()
        .map_err(|_| Error::ReceiptCorrupt)
}
pub(crate) fn system_time(value: OnlyUtcDateTime) -> Result<SystemTime, Error> {
    let nanos = value.timestamp().total_nanoseconds();
    let magnitude = nanos.unsigned_abs();
    let duration = Duration::new(
        u64::try_from(magnitude / 1_000_000_000).map_err(|_| Error::InvalidAcceptedAt)?,
        (magnitude % 1_000_000_000) as u32,
    );
    if nanos < 0 {
        UNIX_EPOCH.checked_sub(duration)
    } else {
        UNIX_EPOCH.checked_add(duration)
    }
    .ok_or(Error::InvalidAcceptedAt)
}
