//! PostgreSQL finite-job content. Tokens have no public/raw-JSON constructor;
//! the real execution/admission owners are wired in later stages.
#[path = "job_publication/model.rs"]
mod model;
#[path = "job_publication/reader.rs"]
mod reader;
#[path = "job_publication/writer.rs"]
mod writer;
use crate::{
    application::job_contract::{FrozenJobBinding, JobKind, ResultMember},
    bootstrap::deployment::{self, SemanticStoreId},
};
pub use model::*;
use serde_json::Value;
use sha2::{Digest, Sha256};
use tokio_postgres::{Client, Transaction};
type Result<T> = std::result::Result<T, PublicationError>;
const CONTENT_LIMIT: usize = 128 * 1024 * 1024;
pub(super) fn digest(raw: &[u8]) -> String {
    Sha256::digest(raw)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
pub(super) fn encode(v: &Value, limit: usize) -> Result<String> {
    let raw = v.to_string();
    if raw.len() > limit {
        return Err(PublicationError::BudgetExceeded);
    }
    onlyalpha_metadata_json::canonical_json(&raw, limit.saturating_mul(4)).map_err(|e| match e {
        onlyalpha_metadata_json::Error::Unavailable => PublicationError::BudgetExceeded,
        onlyalpha_metadata_json::Error::Invalid => PublicationError::Integrity,
    })
}
fn document(raw: &str, limit: usize) -> Result<Value> {
    if raw.len() > limit {
        return Err(PublicationError::BudgetExceeded);
    }
    let value: Value = serde_json::from_str(raw).map_err(|_| PublicationError::Integrity)?;
    if encode(&value, limit)? != raw {
        return Err(PublicationError::Integrity);
    }
    Ok(value)
}
pub(super) fn db(e: tokio_postgres::Error) -> PublicationError {
    match e.code() {
        Some(c) if *c == tokio_postgres::error::SqlState::INSUFFICIENT_PRIVILEGE => {
            PublicationError::Denied
        }
        Some(c)
            if ["08", "40", "42", "53", "54", "55", "57", "58", "XX"]
                .iter()
                .any(|prefix| c.code().starts_with(prefix)) =>
        {
            PublicationError::Unavailable
        }
        Some(_) => PublicationError::Integrity,
        None => PublicationError::Unavailable,
    }
}
pub(super) fn deployment_error(e: deployment::Error) -> PublicationError {
    match e {
        deployment::Error::Unavailable => PublicationError::Unavailable,
        deployment::Error::Missing | deployment::Error::BindingMissing => {
            PublicationError::MissingEvidence
        }
        deployment::Error::Mismatch => PublicationError::Mismatch,
        deployment::Error::Corrupt | deployment::Error::Unsupported => PublicationError::Integrity,
    }
}
fn kind(k: JobKind) -> &'static str {
    match k {
        JobKind::Research => "RESEARCH",
        JobKind::Backtest => "BACKTEST",
    }
}
fn table(k: JobKind) -> &'static str {
    match k {
        JobKind::Research => "research_run",
        JobKind::Backtest => "backtest_run",
    }
}
fn attempt_table(k: JobKind) -> &'static str {
    match k {
        JobKind::Research => "research_run_attempt",
        JobKind::Backtest => "backtest_run_attempt",
    }
}
pub(super) async fn role(client: &Client, allowed: &[&str]) -> Result<String> {
    let identity=client.query_one("SELECT current_user::text, s.rolcanlogin AND NOT(s.rolsuper OR s.rolcreatedb OR s.rolcreaterole OR s.rolreplication OR s.rolbypassrls), NOT(g.rolcanlogin OR g.rolsuper OR g.rolcreatedb OR g.rolcreaterole OR g.rolreplication OR g.rolbypassrls OR g.rolinherit) FROM pg_catalog.pg_roles s CROSS JOIN pg_catalog.pg_roles g WHERE s.rolname=session_user AND g.rolname=current_user",&[]).await.map_err(db)?;
    let current: String = identity.get(0);
    if !allowed.contains(&current.as_str())
        || !identity.get::<_, bool>(1)
        || !identity.get::<_, bool>(2)
    {
        return Err(PublicationError::Denied);
    }
    Ok(current)
}
/// One borrowed physical connection; no reconnect/fallback or SQL access from Core.
pub struct PublicationRepository<'a> {
    client: &'a mut Client,
    namespace: SemanticStoreId,
    owner: String,
    writable: bool,
}
impl<'a> PublicationRepository<'a> {
    pub async fn new(
        client: &'a mut Client,
        namespace: &SemanticStoreId,
        owner: &str,
    ) -> Result<Self> {
        if owner.trim().is_empty() || owner.len() > 512 || owner.chars().any(char::is_control) {
            return Err(PublicationError::Integrity);
        }
        let r = role(client, &["onlyalpha_job_reader", "onlyalpha_job_publisher"]).await?;
        deployment::verify_binding(client, namespace)
            .await
            .map_err(deployment_error)?;
        Ok(Self {
            client,
            namespace: namespace.clone(),
            owner: owner.into(),
            writable: r == "onlyalpha_job_publisher",
        })
    }
}
pub(super) async fn bounded(tx: &Transaction<'_>) -> Result<()> {
    crate::persistence::postgres::bounds(tx)
        .await
        .map_err(|_| PublicationError::Unavailable)
}
pub(super) async fn durable(tx: &Transaction<'_>) -> Result<()> {
    bounded(tx).await?;
    let settings=tx.query_one("SELECT pg_catalog.current_setting('fsync')='on',pg_catalog.current_setting('full_page_writes')='on',pg_catalog.current_setting('synchronous_commit')",&[]).await.map_err(db)?;
    if !settings.get::<_, bool>(0) || !settings.get::<_, bool>(1) {
        return Err(PublicationError::Unavailable);
    }
    // Preserve remote_apply when the deployment already requires the stronger ack.
    if settings.get::<_, String>(2) != "remote_apply" {
        tx.batch_execute("SET LOCAL synchronous_commit=on")
            .await
            .map_err(db)?;
    }
    Ok(())
}
async fn commit(tx: Transaction<'_>) -> Result<()> {
    tx.commit().await.map_err(|e| {
        if e.code().is_some() {
            db(e)
        } else {
            PublicationError::OutcomeUnknown
        }
    })
}

#[cfg(test)]
#[path = "../tests/support/job_publication_fixture.rs"]
#[allow(dead_code)] // Shared by the explicit DB target; ordinary --lib has no DB tests.
pub(crate) mod fixture;
