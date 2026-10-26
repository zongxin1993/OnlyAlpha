//! Canonical Credential persistence on the node-owned PostgreSQL connection.
use crate::persistence::postgres;
use crate::security::credentials::{Context, CredentialId, Error, Key, Secret, Slot};
use onlyalpha_domain::time::OnlyUtcDateTime;
use tokio_postgres::{Client, IsolationLevel, Row, Transaction};
const COLUMNS: &str = "credential_id::text,credential_kind,subject_id,secret_name,generation,key_version,created_at,updated_at";
pub struct Metadata {
    context: Context,
    created_at: OnlyUtcDateTime,
    updated_at: OnlyUtcDateTime,
}
impl Metadata {
    pub fn context(&self) -> &Context {
        &self.context
    }
    pub fn created_at(&self) -> OnlyUtcDateTime {
        self.created_at
    }
    pub fn updated_at(&self) -> OnlyUtcDateTime {
        self.updated_at
    }
}
pub struct Credentials<'a> {
    client: &'a mut Client,
    key: &'a Key,
}
impl<'a> Credentials<'a> {
    pub fn new(client: &'a mut Client, key: &'a Key) -> Self {
        Self { client, key }
    }
    pub async fn create(
        &mut self,
        slot: &Slot,
        secret: &Secret,
        now: OnlyUtcDateTime,
        work: usize,
    ) -> Result<Metadata, Error> {
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        let result = create_in_transaction(&tx, self.key, slot, secret, now, work).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(result)
    }
    pub async fn rotate(
        &mut self,
        id: &CredentialId,
        expected: i32,
        secret: &Secret,
        now: OnlyUtcDateTime,
        work: usize,
    ) -> Result<Metadata, Error> {
        if expected < 1 {
            return Err(Error::GenerationConflict);
        }
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        bounds(&tx).await?;
        let row=tx.query_opt(&format!("SELECT {COLUMNS} FROM product_credential WHERE credential_id=$1::text::uuid FOR UPDATE"),&[&id.value()]).await.map_err(|_|Error::Unavailable)?.ok_or(Error::NotFound)?;
        let current = restore(&row, &mut { work })?;
        if current.context.generation() != expected {
            return Err(Error::GenerationConflict);
        }
        let result = rotate_locked(&tx, self.key, current, secret, now, work).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(result)
    }
    pub async fn read_secret(
        &mut self,
        id: &CredentialId,
        expected: i32,
        work: usize,
    ) -> Result<Secret, Error> {
        let limit = i64::try_from(work).map_err(|_| Error::Unavailable)?;
        let tx = self
            .client
            .build_transaction()
            .read_only(true)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        bounds(&tx).await?;
        let row=tx.query_opt(&format!("SELECT {COLUMNS},CASE WHEN octet_length(ciphertext)<=$2::bigint THEN ciphertext END AS ciphertext FROM product_credential WHERE credential_id=$1::text::uuid"),&[&id.value(),&limit]).await.map_err(|_|Error::Unavailable)?.ok_or(Error::NotFound)?;
        let metadata = restore(&row, &mut { work })?;
        if metadata.context.generation() != expected {
            return Err(Error::GenerationMismatch);
        }
        let ciphertext = row
            .try_get::<_, Option<Vec<u8>>>("ciphertext")
            .map_err(|_| Error::PersistenceConflict)?
            .ok_or(Error::Unavailable)?;
        let result = self.key.decrypt(&metadata.context, &ciphertext, work)?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(result)
    }
    pub async fn list_metadata(
        &mut self,
        max_rows: usize,
        work: usize,
    ) -> Result<Vec<Metadata>, Error> {
        let limit = max_rows
            .checked_add(1)
            .and_then(|n| i64::try_from(n).ok())
            .ok_or(Error::Unavailable)?;
        let tx = self
            .client
            .build_transaction()
            .read_only(true)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        bounds(&tx).await?;
        let rows=tx.query(&format!("SELECT {COLUMNS} FROM product_credential ORDER BY credential_kind,subject_id,secret_name LIMIT $1"),&[&limit]).await.map_err(|_|Error::Unavailable)?;
        if rows.len() > max_rows {
            return Err(Error::Unavailable);
        }
        let mut budget = work;
        let result = rows
            .iter()
            .map(|row| restore(row, &mut budget))
            .collect::<Result<Vec<_>, _>>()?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(result)
    }
    pub(crate) async fn set_slot_in_transaction(
        tx: &Transaction<'_>,
        key: &Key,
        slot: &Slot,
        secret: &Secret,
        now: OnlyUtcDateTime,
        work: usize,
    ) -> Result<Metadata, Error> {
        bounds(tx).await?;
        let row=tx.query_opt(&format!("SELECT {COLUMNS} FROM product_credential WHERE credential_kind=$1 AND subject_id=$2 AND secret_name=$3 FOR UPDATE"),&[&slot.kind(),&slot.subject(),&slot.name()]).await.map_err(|_|Error::Unavailable)?;
        match row {
            Some(row) => {
                rotate_locked(tx, key, restore(&row, &mut { work })?, secret, now, work).await
            }
            None => create_in_transaction(tx, key, slot, secret, now, work).await,
        }
    }
}
async fn bounds(tx: &Transaction<'_>) -> Result<(), Error> {
    postgres::bounds(tx).await.map_err(|_| Error::Unavailable)
}
async fn create_in_transaction(
    tx: &Transaction<'_>,
    key: &Key,
    slot: &Slot,
    secret: &Secret,
    now: OnlyUtcDateTime,
    work: usize,
) -> Result<Metadata, Error> {
    bounds(tx).await?;
    let context = Context::new(CredentialId::generate()?, slot.clone(), 1, 1)?;
    let ciphertext = key.encrypt(&context, secret, work)?;
    let timestamp = postgres::system_time(now).map_err(|_| Error::SlotInvalid)?;
    let row=tx.query_one(&format!("INSERT INTO product_credential (credential_id,credential_kind,subject_id,secret_name,generation,key_version,ciphertext,created_at,updated_at) VALUES($1::text::uuid,$2,$3,$4,1,1,$5,$6,$6) RETURNING {COLUMNS},ciphertext"),&[&context.credential_id().value(),&slot.kind(),&slot.subject(),&slot.name(),&ciphertext,&timestamp]).await.map_err(|e|if e.code()==Some(&tokio_postgres::error::SqlState::UNIQUE_VIOLATION){Error::GenerationConflict}else{Error::Unavailable})?;
    verified_write(
        &row,
        Metadata {
            context,
            created_at: now,
            updated_at: now,
        },
        &ciphertext,
        work,
    )
}
async fn rotate_locked(
    tx: &Transaction<'_>,
    key: &Key,
    current: Metadata,
    secret: &Secret,
    now: OnlyUtcDateTime,
    work: usize,
) -> Result<Metadata, Error> {
    let previous = &current.context;
    let generation = previous
        .generation()
        .checked_add(1)
        .ok_or(Error::GenerationConflict)?;
    let context = Context::new(
        previous.credential_id().clone(),
        previous.slot().clone(),
        generation,
        previous.key_version(),
    )?;
    let ciphertext = key.encrypt(&context, secret, work)?;
    let timestamp = postgres::system_time(now).map_err(|_| Error::SlotInvalid)?;
    let row=tx.query_opt(&format!("UPDATE product_credential SET generation=$2,ciphertext=$3,updated_at=$4 WHERE credential_id=$1::text::uuid AND generation=$5 RETURNING {COLUMNS},ciphertext"),&[&context.credential_id().value(),&generation,&ciphertext,&timestamp,&previous.generation()]).await.map_err(|_|Error::Unavailable)?.ok_or(Error::GenerationConflict)?;
    verified_write(
        &row,
        Metadata {
            context,
            created_at: current.created_at,
            updated_at: now,
        },
        &ciphertext,
        work,
    )
}
fn restore(row: &Row, budget: &mut usize) -> Result<Metadata, Error> {
    let id = row
        .try_get::<_, String>("credential_id")
        .map_err(|_| Error::PersistenceConflict)?;
    let kind = row
        .try_get::<_, String>("credential_kind")
        .map_err(|_| Error::PersistenceConflict)?;
    let subject = row
        .try_get::<_, String>("subject_id")
        .map_err(|_| Error::PersistenceConflict)?;
    let name = row
        .try_get::<_, String>("secret_name")
        .map_err(|_| Error::PersistenceConflict)?;
    let size = [id.len(), kind.len(), subject.len(), name.len(), 100]
        .into_iter()
        .try_fold(0usize, usize::checked_add)
        .ok_or(Error::Unavailable)?;
    *budget = budget.checked_sub(size).ok_or(Error::Unavailable)?;
    let generation = row
        .try_get("generation")
        .map_err(|_| Error::PersistenceConflict)?;
    let version = row
        .try_get("key_version")
        .map_err(|_| Error::PersistenceConflict)?;
    let id = CredentialId::new(&id).map_err(|_| Error::PersistenceConflict)?;
    let slot = Slot::new(&kind, &subject, &name).map_err(|_| Error::PersistenceConflict)?;
    let context = Context::new(id, slot, generation, version)?;
    let created_at = postgres::datetime(
        row.try_get("created_at")
            .map_err(|_| Error::PersistenceConflict)?,
    )
    .map_err(|_| Error::PersistenceConflict)?;
    let updated_at = postgres::datetime(
        row.try_get("updated_at")
            .map_err(|_| Error::PersistenceConflict)?,
    )
    .map_err(|_| Error::PersistenceConflict)?;
    Ok(Metadata {
        context,
        created_at,
        updated_at,
    })
}

fn verified_write(
    row: &Row,
    expected: Metadata,
    ciphertext: &[u8],
    work: usize,
) -> Result<Metadata, Error> {
    let actual = restore(row, &mut { work }).map_err(|error| {
        if error == Error::Unavailable {
            error
        } else {
            Error::PersistenceConflict
        }
    })?;
    if actual.context != expected.context
        || actual.created_at != expected.created_at
        || actual.updated_at != expected.updated_at
        || row
            .try_get::<_, Vec<u8>>("ciphertext")
            .map_err(|_| Error::PersistenceConflict)?
            != ciphertext
    {
        return Err(Error::PersistenceConflict);
    }
    Ok(actual)
}
