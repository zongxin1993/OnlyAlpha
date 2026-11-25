//! PostgreSQL finite-job content. Tokens have no public/raw-JSON constructor;
//! the real execution/admission owners are wired in later stages.
#[path = "job_publication/model.rs"]
mod model;
#[path = "job_publication/reader.rs"]
mod reader;
#[path = "job_publication/writer.rs"]
mod writer;
mod backtest;
mod guarded;
pub(crate) use reader::backtest_attempt_history;
pub(crate) use guarded::{JobRole, read_control_facts, recheck_control_transaction, register_control_transaction, verify_registered_control_transaction, verify_unpublished_control_transaction, with_job_role};
use crate::{
    application::job_contract::{FrozenJobBinding, JobKind, MemberKind, ResultMember},
    bootstrap::deployment::{self, SemanticStoreId},
};
pub use model::*;
use serde_json::Value;
use sha2::{Digest, Sha256};
use tokio_postgres::{Client, Transaction};
type Result<T> = std::result::Result<T, PublicationError>;
pub(crate) const CONTENT_LIMIT: usize = 128 * 1024 * 1024;
pub(crate) fn digest(raw: &[u8]) -> String {
    Sha256::digest(raw)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
pub(crate) fn encode(v: &Value, limit: usize) -> Result<String> {
    let raw = v.to_string();
    if raw.len() > limit {
        return Err(PublicationError::BudgetExceeded);
    }
    onlyalpha_metadata_json::canonical_json(&raw, limit.saturating_mul(4)).map_err(|e| match e {
        onlyalpha_metadata_json::Error::Unavailable => PublicationError::BudgetExceeded,
        onlyalpha_metadata_json::Error::Invalid => PublicationError::Integrity,
    })
}
/// Content references use exactly the canonical payload format and budget of
/// the publication owner. This pure digest grants no completion or publication.
pub(crate) fn content_fingerprint(value: &Value) -> Result<String> {
    Ok(digest(encode(value, CONTENT_LIMIT)?.as_bytes()))
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
pub(crate) fn db(e: tokio_postgres::Error) -> PublicationError {
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
pub(crate) fn deployment_error(e: deployment::Error) -> PublicationError {
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
pub(crate) async fn role(client: &(impl tokio_postgres::GenericClient + Sync), allowed: &[&str]) -> Result<String> {
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
    mutation_guard: MutationGuard,
    control: Option<&'a crate::persistence::authority_session::ControlRoleOwner>,
}
#[derive(Clone, Copy)]
enum MutationGuard {
    Node,
    #[cfg(test)]
    StorageFixture,
}
impl<'a> PublicationRepository<'a> {
    /// Publish only the real joined candidate under its original opaque Claim,
    /// on the original Node session. Failed role restoration or unknown commit
    /// revokes that same connection; this opens no second writer.
    pub async fn publish_guarded(
        authority:&mut crate::persistence::authority_session::AuthoritySession,
        namespace:&SemanticStoreId,claim:&AttemptClaim<'_>,candidate:&CompletedJobCandidate,
    ) -> Result<PublishOutcome> {
        let mut original = authority.take_ownership();
        let control = original.control_roles().map_err(guarded::authority_error)?;
        let client = guarded::select_job_role(&mut original, JobRole::Publisher).await?;
        let outcome = async {
            let mut repository = PublicationRepository::new(client, namespace, candidate.binding().owner()).await?;
            repository.control = Some(&control);
            let outcome = repository.publish(claim, candidate).await;
            #[cfg(test)]
            if matches!(&outcome, Ok(PublishOutcome::Committed { .. })) {
                crate::workers::backtest_worker::tests::release_committed_guard(client, candidate.binding().run_id()).await;
            }
            outcome
        }.await;
        let restored = guarded::reset_job_role(client, matches!(&outcome, Err(PublicationError::OutcomeUnknown))).await;
        guarded::finish_job_role(authority, original, outcome, restored, true).await
    }
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
            mutation_guard: MutationGuard::Node,
            control: None,
        })
    }

    pub(crate) async fn observe_guarded(
        authority: &mut crate::persistence::authority_session::AuthoritySession,
        namespace: &SemanticStoreId,
        owner: &str,
        key: &RunLocator,
    ) -> Result<PublicationObservation> {
        let mut original = authority.take_ownership();
        let control = original.control_roles().map_err(guarded::authority_error)?;
        let client = guarded::select_job_role(&mut original, JobRole::Publisher).await?;
        let outcome = async {
            let mut repository = PublicationRepository::new(client, namespace, owner).await?;
            repository.control = Some(&control);
            repository.observe(key).await
        }.await;
        let restored = guarded::reset_job_role(client, matches!(&outcome, Err(PublicationError::OutcomeUnknown))).await;
        guarded::finish_job_role(authority, original, outcome, restored, false).await
    }
}
pub(crate) async fn bounded(tx: &Transaction<'_>) -> Result<()> {
    crate::persistence::postgres::bounds(tx)
        .await
        .map_err(|_| PublicationError::Unavailable)
}
pub(crate) async fn durable(tx: &Transaction<'_>) -> Result<()> {
    bounded(tx).await?;
    super::postgres::ensure_commit_durability(tx).await.map_err(|_| PublicationError::Unavailable)
}
pub(crate) async fn commit(tx: Transaction<'_>) -> Result<()> {
    tx.commit().await.map_err(|e| {
        if e.code().is_some() {
            db(e)
        } else {
            PublicationError::OutcomeUnknown
        }
    })
}

/// Called after deferred checks and exact readback, with no subsequent writes.
/// Shipping code has only Node mode; the storage-mechanics exception does not
/// exist outside the explicitly compiled test fixture owner.
async fn commit_mutation(tx: Transaction<'_>, guard: MutationGuard) -> Result<(u128,u128)> {
    let started = std::time::Instant::now();
    match guard {
        MutationGuard::Node => {
            use crate::persistence::authority_session::{AuthorityError,AuthoritySession};
            AuthoritySession::verify_transaction(&tx).await.map_err(|error| match error {
                AuthorityError::Lost => PublicationError::OwnershipLost,
                _ => PublicationError::Unavailable,
            })?;
        }
        #[cfg(test)]
        MutationGuard::StorageFixture => {}
    }
    let guard_ns = started.elapsed().as_nanos();
    let started = std::time::Instant::now();
    commit(tx).await?;
    Ok((guard_ns,started.elapsed().as_nanos()))
}

#[cfg(test)]
#[path = "../tests/support/job_publication_fixture.rs"]
#[allow(dead_code)] // Shared by the explicit DB target; ordinary --lib has no DB tests.
pub(crate) mod fixture;

/// Read the original registration through an authenticated fact-reader location.
pub(crate) async fn verify_frozen_identity(
    tx:&Transaction<'_>,namespace:&SemanticStoreId,run:&crate::application::research_run::VerifiedRun,
) -> Result<()> {
    let key=RunLocator::new(JobKind::Research,run.run_id())?;
    let (_,specification,admission)=reader::frozen(tx,namespace,run.owner(),&key).await?;
    if specification!=run.specification_fingerprint() || admission!=run.admission_resolution_fingerprint() {
        return Err(PublicationError::Mismatch);
    }
    Ok(())
}

/// A visible publication was committed atomically with its members and terminal
/// rows. The closure and immutability guards preserve that cut after the root
/// read, including on a READ COMMITTED fact reader.
pub(crate) async fn read_registered_research(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    run: &crate::application::research_run::VerifiedRun,
) -> Result<PublishedJobResult> {
    bounded(tx).await?;
    role(tx, &["onlyalpha_job_reader"]).await?;
    deployment::verify_binding_in_transaction(tx, namespace).await.map_err(deployment_error)?;
    let key = RunLocator::new(JobKind::Research, run.run_id())?;
    let (binding, spec, admission) = reader::frozen(tx, namespace, run.owner(), &key).await?;
    if spec != run.specification_fingerprint() || admission != run.admission_resolution_fingerprint() {
        return Err(PublicationError::Mismatch);
    }
    reader::load(tx, binding, &key, MutationGuard::Node, None).await?.ok_or(PublicationError::MissingEvidence)
}

/// 存储闭包与执行证明分开：只有恢复原元数据角色并完成执行核验，才能取出发布结果。
 pub(crate) struct BacktestStorage(PublishedJobResult, Vec<Value>);

pub(crate) async fn read_registered_backtest(
    tx: &Transaction<'_>, namespace: &SemanticStoreId, run: &crate::application::backtest_run::VerifiedRun,
) -> Result<BacktestStorage> {
    bounded(tx).await?;
    role(tx, &[JobRole::Reader.name()]).await?;
    deployment::verify_binding_in_transaction(tx, namespace).await.map_err(deployment_error)?;
    let key = RunLocator::new(JobKind::Backtest, run.run_id())?;
    let (binding, spec, admission) = reader::frozen(tx, namespace, run.owner(), &key).await?;
    if run.namespace() != namespace || spec != run.specification_fingerprint() || admission != run.admission_resolution_fingerprint() {
        return Err(PublicationError::Mismatch);
    }
    let (result, bodies) = reader::load_storage(tx, binding, &key, true).await?.ok_or(PublicationError::MissingEvidence)?;
    Ok(BacktestStorage(result, bodies))
}

/// Current PG causal members prove the actual calculation and joined execution.
/// References are member content identities, never old file-protocol wrappers.
fn research_execution_references(members:&[PreparedMember]) -> Result<Vec<String>> {
    let mut references=members.iter().filter(|m|m.descriptor.kind()==MemberKind::CausalEvidence)
        .map(|m|m.content_fingerprint.clone()).collect::<Vec<_>>();
    references.sort_unstable();
    references.dedup();
    if references.is_empty() { return Err(PublicationError::MissingEvidence); }
    Ok(references)
}
