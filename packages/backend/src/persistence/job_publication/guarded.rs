//! A temporary role on the original Node mutation socket, never another writer.
use super::*;
use crate::persistence::authority_session::{AuthoritySession, ControlRoleOwner};

#[derive(Clone, Copy)]
pub(crate) enum JobRole {
    Reader,
    Publisher,
}
impl JobRole {
    pub(super) fn name(self) -> &'static str {
        match self {
            Self::Reader => "onlyalpha_job_reader",
            Self::Publisher => "onlyalpha_job_publisher",
        }
    }
    fn select(self) -> &'static str {
        match self {
            Self::Reader => "SET ROLE onlyalpha_job_reader",
            Self::Publisher => "SET ROLE onlyalpha_job_publisher",
        }
    }
    pub(super) fn select_local(self) -> &'static str {
        match self {
            Self::Reader => "SET LOCAL ROLE onlyalpha_job_reader",
            Self::Publisher => "SET LOCAL ROLE onlyalpha_job_publisher",
        }
    }
}

pub(super) fn authority_error(
    error: crate::persistence::authority_session::AuthorityError,
) -> PublicationError {
    match error {
        crate::persistence::authority_session::AuthorityError::Lost => {
            PublicationError::OwnershipLost
        }
        _ => PublicationError::Unavailable,
    }
}
async fn enter_transaction_role(tx: &Transaction<'_>, selected: JobRole) -> Result<()> {
    AuthoritySession::verify_transaction(tx)
        .await
        .map_err(authority_error)?;
    if !tx
        .query_one("SELECT current_user=session_user", &[])
        .await
        .map_err(db)?
        .get::<_, bool>(0)
    {
        return Err(PublicationError::Denied);
    }
    tx.batch_execute(selected.select_local())
        .await
        .map_err(db)?;
    role(tx, &[selected.name()]).await?;
    Ok(())
}
async fn restore_control_role(tx: &Transaction<'_>) -> Result<()> {
    // A failed SQL operation can abort the transaction before RESET is sent.
    // Until restoration is acknowledged the scope must revoke its driver;
    // the secondary SQL error proves neither content corruption nor mismatch.
    tx.batch_execute("SET LOCAL ROLE NONE")
        .await
        .map_err(|_| PublicationError::OutcomeUnknown)?;
    if !tx
        .query_one("SELECT current_user=session_user", &[])
        .await
        .map_err(|_| PublicationError::OutcomeUnknown)?
        .get::<_, bool>(0)
    {
        return Err(PublicationError::OutcomeUnknown);
    }
    AuthoritySession::verify_transaction(tx)
        .await
        .map_err(authority_error)
}

/// Adds the immutable input binding to the caller's original admission tx.
/// It never commits. The owner must take the AS before awaiting and revoke it
/// on any error/cancellation; all control writes precede this finalization.
pub(crate) async fn register_control_transaction(
    tx: &Transaction<'_>,
    owner_scope: &ControlRoleOwner,
    namespace: &SemanticStoreId,
    owner: &str,
    registration: &FrozenBindingRegistration,
) -> Result<()> {
    let scope = owner_scope.enter();
    owner_scope
        .verify_transaction(tx)
        .await
        .map_err(authority_error)?;
    durable(tx).await?;
    enter_transaction_role(tx, JobRole::Publisher).await?;
    let cut = writer::write_registration(tx, namespace, owner, registration).await?;
    if cut.state != "QUEUED" || cut.revision != 0 {
        return Err(PublicationError::OwnershipLost);
    }
    restore_control_role(tx).await?;
    // Other admission/receipt constraints retain their control permissions.
    tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
        .await
        .map_err(db)?;
    enter_transaction_role(tx, JobRole::Publisher).await?;
    writer::verify_registration(tx, namespace, owner, &cut).await?;
    restore_control_role(tx).await?;
    owner_scope
        .verify_transaction(tx)
        .await
        .map_err(authority_error)?;
    scope.restored();
    Ok(())
}

/// Read immutable build facts without changing the owning control transaction.
/// The caller must already own the AS driver before awaiting. Any failed role
/// restoration/guard proof must discard that original owner, including cancel.
/// The inner result preserves the fact owner's precise rejection predicate.
pub(crate) async fn read_control_facts<'a, 't, T: Send, E: Send, F, Fut>(
    tx: &'a Transaction<'t>,
    owner_scope: &ControlRoleOwner,
    operation: F,
) -> Result<std::result::Result<T, E>>
where
    F: FnOnce(&'a Transaction<'t>) -> Fut + Send,
    Fut: std::future::Future<Output = std::result::Result<T, E>> + Send,
{
    let scope = owner_scope.enter();
    owner_scope
        .verify_transaction(tx)
        .await
        .map_err(authority_error)?;
    enter_transaction_role(tx, JobRole::Reader).await?;
    let outcome = operation(tx).await;
    restore_control_role(tx).await?;
    owner_scope
        .verify_transaction(tx)
        .await
        .map_err(authority_error)?;
    scope.restored();
    Ok(outcome)
}

/// The caller holds the original Run lock and a real active Claim. This is
/// deliberately separate from no-active recovery's ConfirmedUnpublished proof.
pub(crate) async fn verify_unpublished_control_transaction(
    tx: &Transaction<'_>,
    owner_scope: &ControlRoleOwner,
    namespace: &SemanticStoreId,
    binding: &FrozenJobBinding,
    specification: &str,
    admission: &str,
) -> Result<()> {
    let scope = owner_scope.enter();
    owner_scope
        .verify_transaction(tx)
        .await
        .map_err(authority_error)?;
    enter_transaction_role(tx, JobRole::Reader).await?;
    let outcome = async {
        let key = RunLocator::new(binding.kind(), binding.run_id())?;
        let (stored, spec, adm) = reader::frozen(tx, namespace, binding.owner(), &key).await?;
        if stored.fingerprint() != binding.fingerprint() || spec != specification || adm != admission {
            return Err(PublicationError::Mismatch);
        }
        let row = tx.query_one(
            "SELECT EXISTS(SELECT 1 FROM public.job_publication WHERE job_kind=$1 AND run_id=$2::text::uuid),EXISTS(SELECT 1 FROM public.job_result_member WHERE job_kind=$1 AND run_id=$2::text::uuid)",
            &[&kind(key.kind), &key.run],
        ).await.map_err(db)?;
        if row.get::<_, bool>(0) { return Err(PublicationError::Conflict); }
        if row.get::<_, bool>(1) { return Err(PublicationError::Integrity); }
        reader::unpublished_attempts(tx, &key).await?;
        Ok(())
    }.await;
    restore_control_role(tx).await?;
    owner_scope
        .verify_transaction(tx)
        .await
        .map_err(authority_error)?;
    scope.restored();
    outcome
}

/// Validate the original immutable registration during command replay. Missing
/// evidence stays missing: this read cannot fill it from current preparation.
/// The caller owns the original AS driver before awaiting this transaction.
pub(crate) async fn verify_registered_control_transaction(
    tx: &Transaction<'_>,
    owner_scope: &ControlRoleOwner,
    namespace: &SemanticStoreId,
    owner: &str,
    key: &RunLocator,
    specification: &str,
    admission: &str,
) -> Result<()> {
    let scope = owner_scope.enter();
    owner_scope
        .verify_transaction(tx)
        .await
        .map_err(authority_error)?;
    enter_transaction_role(tx, JobRole::Reader).await?;
    let observed = async {
        let (_,s,a) = reader::frozen(tx,namespace,owner,key).await?;
        let sql = format!("SELECT specification_fingerprint,admission_resolution_fingerprint FROM public.{} WHERE run_id=$1::text::uuid",table(key.kind));
        let row = tx.query_opt(&sql,&[&key.run]).await.map_err(db)?.ok_or(PublicationError::MissingEvidence)?;
        if s!=specification || a!=admission || row.get::<_,String>(0)!=s || row.get::<_,String>(1)!=a {
            return Err(PublicationError::Mismatch);
        }
        Ok(())
    }.await;
    restore_control_role(tx).await?;
    owner_scope
        .verify_transaction(tx)
        .await
        .map_err(authority_error)?;
    scope.restored();
    observed
}

/// The claim/cancellation owner has already taken exclusive AuthoritySession
/// ownership before awaiting this transaction. Any error must discard that
/// owner; cancelling the outer operation drops its original connection driver.
/// The Run lock spans both this reader role and the following control CAS.
pub(crate) async fn recheck_control_transaction(
    tx: &Transaction<'_>,
    owner_scope: &ControlRoleOwner,
    proof: &ConfirmedUnpublished,
    run: &RunLocator,
    namespace: &SemanticStoreId,
    owner: &str,
) -> Result<bool> {
    let scope = owner_scope.enter();
    owner_scope
        .verify_transaction(tx)
        .await
        .map_err(authority_error)?;
    enter_transaction_role(tx, JobRole::Publisher).await?;
    let accepted = proof.recheck(tx, run, namespace, owner).await?;
    restore_control_role(tx).await?;
    owner_scope
        .verify_transaction(tx)
        .await
        .map_err(authority_error)?;
    scope.restored();
    Ok(accepted)
}

/// Exclusive ownership includes the connection driver before the first await.
/// Cancellation, panic, unknown COMMIT or failed restoration drops that original
/// driver. A known rejected operation may return the verified original session.
pub(crate) async fn with_job_role<T>(
    authority: &mut AuthoritySession,
    selected: JobRole,
    operation: impl for<'a> AsyncFnOnce(&'a mut Client) -> Result<T>,
) -> Result<T> {
    let mut original = authority.take_ownership();
    let client = select_job_role(&mut original, selected).await?;
    let outcome = operation(client).await;
    let restored = reset_job_role(client, matches!(&outcome, Err(PublicationError::OutcomeUnknown))).await;
    finish_job_role(authority, original, outcome, restored, false).await
}

pub(super) async fn select_job_role(
    original: &mut AuthoritySession,
    selected: JobRole,
) -> Result<&mut Client> {
    let client = original
        .client_mut()
        .await
        .map_err(|_| PublicationError::Unavailable)?;
    // Only the ordinary login baseline may enter this scope. Nested or
    // externally changed roles are not silently restored to another owner.
    let baseline = client
        .query_one("SELECT current_user=session_user", &[])
        .await
        .map_err(db)?;
    if !baseline.get::<_, bool>(0) {
        return Err(PublicationError::Denied);
    }
    client.batch_execute(selected.select()).await.map_err(db)?;
    role(client, &[selected.name()]).await?;
    Ok(client)
}

pub(super) async fn reset_job_role(client: &Client, outcome_unknown: bool) -> Result<()> {
    if outcome_unknown {
        return Err(PublicationError::OutcomeUnknown);
    }
    // The acknowledgement observes any queued rollback before reuse.
    client.batch_execute("RESET ROLE").await.map_err(db)?;
    if !client
        .query_one("SELECT current_user=session_user", &[])
        .await
        .map_err(db)?
        .get::<_, bool>(0)
    {
        return Err(PublicationError::OutcomeUnknown);
    }
    Ok(())
}

pub(super) async fn finish_job_role<T>(
    authority: &mut AuthoritySession,
    mut original: AuthoritySession,
    outcome: Result<T>,
    role_restored: Result<()>,
    preserve_success: bool,
) -> Result<T> {
    let restoration = match role_restored {
        Ok(()) => original.verify().await.map_err(authority_error),
        Err(error) => Err(error),
    };
    match restoration {
        Ok(()) => {
            authority.restore_ownership(original);
            outcome
        }
        Err(error) if preserve_success && outcome.is_ok() => {
            tracing::warn!(?error, "Revoked original Authority session after confirmed publication");
            outcome
        }
        Err(error) => Err(error),
    }
}
