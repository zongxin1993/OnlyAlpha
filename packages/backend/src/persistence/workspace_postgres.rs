//! Named workspace library Authority. Node owns store/TLS/Client lifecycle.
use crate::application::command::{
    Admission, Binding, CommandId, CommandKind, Error as CommandError, Outcome, OutcomeKind,
    Receipt,
};
use crate::application::workspace::{Book, Error, namespace_id};
use crate::persistence::postgres::{Commands, bounds};
use serde_json::Value;
use tokio_postgres::{Client, IsolationLevel, Row, Transaction};

pub struct Workspaces<'a> {
    client: &'a mut Client,
    namespace: String,
}
impl<'a> Workspaces<'a> {
    pub fn new(client: &'a mut Client, namespace: &str) -> Result<Self, Error> {
        namespace_id(namespace)?;
        Ok(Self {
            client,
            namespace: namespace.into(),
        })
    }
    pub async fn read(&mut self) -> Result<Book, Error> {
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        bounds(&tx).await.map_err(command_error)?;
        let book = current(&tx, &self.namespace).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(book)
    }
    pub async fn command(&mut self, id: &CommandId) -> Result<Option<Book>, Error> {
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        Commands::lock_command(&tx, id)
            .await
            .map_err(command_error)?;
        let result = match Commands::verify_binding_in_transaction(&tx, id)
            .await
            .map_err(command_error)?
        {
            Binding::None => None,
            Binding::Admitted(admission) => {
                if admission.kind() != CommandKind::SaveWorkspace {
                    return Err(Error::CommandConflict);
                }
                return Err(Error::CommandUnknown);
            }
            Binding::Accepted(receipt) => Some(from_receipt(&tx, &self.namespace, &receipt).await?),
        };
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(result)
    }
    /// Proposed.version is the expected head version. The only committed outcome
    /// is the next immutable revision. Caller supplies operational receipt time.
    /// Application must prove Owner permission
    /// before exposing this persistence port through the Product API. Saving intent does not authorize Source reads.
    pub async fn save(
        &mut self,
        id: &CommandId,
        proposed: &Book,
        accepted_at: &str,
    ) -> Result<Book, Error> {
        let next =
            proposed.with_version(proposed.version().checked_add(1).ok_or(Error::Invalid)?)?;
        let intent = proposed.intent_fingerprint(&self.namespace)?;
        let admission = Admission::new(id.clone(), CommandKind::SaveWorkspace, &intent)
            .map_err(|_| Error::Invalid)?;
        // READ COMMITTED is explicit: namespace lock wait must not pin a stale head.
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        Commands::lock_command(&tx, id)
            .await
            .map_err(command_error)?;
        let bound = Commands::verify_binding_in_transaction(&tx, id)
            .await
            .map_err(command_error)?;
        match bound {
            Binding::Accepted(receipt) => {
                let replay = from_receipt(&tx, &self.namespace, &receipt).await?;
                if replay.fingerprint(&self.namespace)? != next.fingerprint(&self.namespace)? {
                    return Err(Error::CommandConflict);
                }
                tx.commit().await.map_err(|_| Error::Unavailable)?;
                return Ok(replay);
            }
            Binding::Admitted(bound) => {
                if bound.kind() != CommandKind::SaveWorkspace {
                    return Err(Error::CommandConflict);
                }
                if bound.fingerprint() != intent {
                    return Err(Error::CommandConflict);
                }
                // An exact reservation is not evidence of an effect or permission to repeat it.
                return Err(Error::CommandUnknown);
            }
            Binding::None => {}
        }
        let fingerprint = next.fingerprint(&self.namespace)?;
        let receipt = Receipt::new(
            admission.clone(),
            Outcome::new(OutcomeKind::WorkspaceRevision, &fingerprint)
                .map_err(|_| Error::Invalid)?,
            accepted_at,
        )
        .map_err(|_| Error::Invalid)?;
        Commands::admit_exact_in_transaction(&tx, &admission)
            .await
            .map_err(command_error)?;
        let namespace_lock = format!("workspaces:{}", self.namespace);
        tx.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
            &[&namespace_lock],
        )
        .await
        .map_err(|_| Error::Unavailable)?;
        if current(&tx, &self.namespace).await?.version() != proposed.version() {
            return Err(Error::VersionConflict);
        }
        let version = i64::try_from(next.version()).map_err(|_| Error::Invalid)?;
        let payload = next.to_record().to_string();
        tx.execute("INSERT INTO workspace_library_revision(namespace_id,version,fingerprint,library_json,command_id) VALUES($1::text::uuid,$2,$3,$4::text::jsonb,$5::text::uuid)",&[&self.namespace,&version,&fingerprint,&payload,&id.value()]).await.map_err(|_|Error::Unavailable)?;
        tx.execute("INSERT INTO workspace_library_head(namespace_id,version) VALUES($1::text::uuid,$2) ON CONFLICT(namespace_id) DO UPDATE SET version=EXCLUDED.version",&[&self.namespace,&version]).await.map_err(|_|Error::Unavailable)?;
        Commands::put_verified_receipt_in_transaction(&tx, &receipt)
            .await
            .map_err(command_error)?;
        // Neither caller disconnect nor loss of COMMIT ACK proves rollback/absence.
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(next)
    }
}
async fn current(tx: &Transaction<'_>, namespace: &str) -> Result<Book, Error> {
    // One head/history snapshot, including the genuinely empty namespace. A dangling
    // head cannot disappear through an inner join and become an empty configuration.
    let row=tx.query_one("SELECT h.version AS head_version,r.fingerprint,r.command_id::text AS command_id,s.maximum,s.minimum,s.count FROM (SELECT $1::text::uuid AS namespace_id) n CROSS JOIN LATERAL (SELECT max(version) AS maximum,min(version) AS minimum,count(*) AS count FROM workspace_library_revision WHERE namespace_id=n.namespace_id) s LEFT JOIN workspace_library_head h ON h.namespace_id=n.namespace_id LEFT JOIN workspace_library_revision r ON r.namespace_id=h.namespace_id AND r.version=h.version",&[&namespace]).await.map_err(|_|Error::Unavailable)?;
    let head: Option<i64> = row
        .try_get("head_version")
        .map_err(|_| Error::HistoryCorrupt)?;
    let count: i64 = row.try_get("count").map_err(|_| Error::HistoryCorrupt)?;
    let maximum: Option<i64> = row.try_get("maximum").map_err(|_| Error::HistoryCorrupt)?;
    let minimum: Option<i64> = row.try_get("minimum").map_err(|_| Error::HistoryCorrupt)?;
    if head.is_none() && count == 0 && maximum.is_none() && minimum.is_none() {
        return Book::new(0, None, vec![]);
    }
    if head.is_none() || head != maximum || head != Some(count) || minimum != Some(1) {
        return Err(Error::HistoryCorrupt);
    }
    let id: String = row
        .try_get("command_id")
        .map_err(|_| Error::HistoryCorrupt)?;
    let id = CommandId::new(&id).map_err(|_| Error::HistoryCorrupt)?;
    let Binding::Accepted(receipt) = Commands::verify_binding_in_transaction(tx, &id)
        .await
        .map_err(command_error)?
    else {
        return Err(Error::HistoryCorrupt);
    };
    // The head's own receipt must select this exact revision, not just some book.
    let selected_fingerprint: String = row
        .try_get("fingerprint")
        .map_err(|_| Error::HistoryCorrupt)?;
    if receipt.admission().kind() != CommandKind::SaveWorkspace
        || receipt.outcome().kind() != OutcomeKind::WorkspaceRevision
        || receipt.outcome().id() != selected_fingerprint
    {
        return Err(Error::HistoryCorrupt);
    }
    let verified = from_receipt(tx, namespace, &receipt)
        .await
        .map_err(|error| {
            if error == Error::CommandConflict {
                Error::HistoryCorrupt
            } else {
                error
            }
        })?;
    if Some(i64::try_from(verified.version()).map_err(|_| Error::HistoryCorrupt)?) != head {
        return Err(Error::HistoryCorrupt);
    }
    Ok(verified)
}
async fn from_receipt(
    tx: &Transaction<'_>,
    namespace: &str,
    receipt: &Receipt,
) -> Result<Book, Error> {
    if receipt.admission().kind() != CommandKind::SaveWorkspace
        || receipt.outcome().kind() != OutcomeKind::WorkspaceRevision
    {
        return Err(Error::CommandConflict);
    }
    let row=tx.query_opt("SELECT version,fingerprint,library_json::text AS payload,(jsonb_typeof(library_json->'version')='number' AND library_json->>'version'=version::text) AS exact_version FROM workspace_library_revision WHERE namespace_id=$1::text::uuid AND fingerprint=$2 AND command_id=$3::text::uuid",&[&namespace,&receipt.outcome().id(),&receipt.admission().id().value()]).await.map_err(|_|Error::Unavailable)?.ok_or(Error::HistoryCorrupt)?;
    let (version, payload) = original_record(namespace, &row)?;
    let expected = Book::from_record(&payload)
        .and_then(|book| book.with_version(version.checked_sub(1).ok_or(Error::HistoryCorrupt)?))
        .and_then(|book| book.intent_fingerprint(namespace))
        .map_err(|_| Error::HistoryCorrupt)?;
    if receipt.admission().fingerprint() != expected {
        return Err(Error::HistoryCorrupt);
    }
    // All original identity and Command evidence is complete before projection.
    Book::from_record(&payload).map_err(|_| Error::HistoryCorrupt)
}
fn original_record(namespace: &str, row: &Row) -> Result<(u64, Value), Error> {
    let version: i64 = row.try_get("version").map_err(|_| Error::HistoryCorrupt)?;
    let fingerprint: String = row
        .try_get("fingerprint")
        .map_err(|_| Error::HistoryCorrupt)?;
    let raw: String = row.try_get("payload").map_err(|_| Error::HistoryCorrupt)?;
    // Prove the original JSONB primitive before arbitrary-precision Value decoding.
    // Its reserved number marker can otherwise turn a JSON object into a number.
    if row
        .try_get::<_, Option<bool>>("exact_version")
        .map_err(|_| Error::HistoryCorrupt)?
        != Some(true)
    {
        return Err(Error::HistoryCorrupt);
    }
    // Every valid representation has fixed shallow shape and scalar leaves.
    // Sixteen traversals cover that shape regardless of text lengths. A deeper
    // invalid/unproved document may exhaust work; that is unavailable, not absence.
    let work = raw.len().checked_mul(16).ok_or(Error::Unavailable)?;
    let original =
        onlyalpha_metadata_json::integral_float_json(&raw, work).map_err(|error| match error {
            onlyalpha_metadata_json::Error::Invalid => Error::HistoryCorrupt,
            onlyalpha_metadata_json::Error::Unavailable => Error::Unavailable,
        })?;
    let payload: Value = serde_json::from_str(&raw).map_err(|_| Error::HistoryCorrupt)?;
    // Value's private Number/RawValue keys must not change a primitive or object
    // anywhere in the original record, including a name or nested Source field.
    let projected = serde_json::to_string(&payload).map_err(|_| Error::HistoryCorrupt)?;
    let projected = onlyalpha_metadata_json::integral_float_json(&projected, work)
        .map_err(|_| Error::HistoryCorrupt)?;
    if projected != original {
        return Err(Error::HistoryCorrupt);
    }
    if version <= 0
        || Book::record_fingerprint(namespace, &payload).map_err(|_| Error::HistoryCorrupt)?
            != fingerprint
    {
        return Err(Error::HistoryCorrupt);
    }
    if payload.get("version").and_then(Value::as_u64) != Some(version as u64) {
        return Err(Error::HistoryCorrupt);
    }
    Ok((version as u64, payload))
}
fn command_error(error: CommandError) -> Error {
    match error {
        CommandError::Unavailable => Error::Unavailable,
        CommandError::Conflict => Error::CommandConflict,
        _ => Error::HistoryCorrupt,
    }
}
