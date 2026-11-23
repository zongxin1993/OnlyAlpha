//! Existing Research Run/Attempt operational authority. Semantic facts stay in immutable Stores.
mod source_history;
use crate::application::research_run::{
    InspectionOutcome, VerifiedCompletion, VerifiedInspection, VerifiedRun,
};
use onlyalpha_domain::time::OnlyUtcDateTime;
pub use source_history::validate_source_history_event;
pub(crate) use source_history::verify_run_source_history;
use std::time::{Duration, SystemTime};
use tokio_postgres::{Client, Transaction};

type Result<T> = std::result::Result<T, &'static str>;
const UNAVAILABLE: &str = "RESEARCH_EXECUTION_STORE_UNAVAILABLE";
const LOST: &str = "RESEARCH_EXECUTION_OWNERSHIP_LOST";
const UNCERTAIN: &str = "RESEARCH_EXECUTION_OWNERSHIP_UNCERTAIN";
const INVALID: &str = "RESEARCH_EXECUTION_INPUT_INVALID";
const MISMATCH: &str = "RESEARCH_EXECUTION_PROOF_MISMATCH";

fn publication_error(error: super::job_publication::PublicationError) -> &'static str {
    use super::job_publication::PublicationError as E;
    match error {
        E::OutcomeUnknown => UNCERTAIN,
        E::OwnershipLost => LOST,
        E::Unavailable => UNAVAILABLE,
        E::Denied => "RESEARCH_EXECUTION_ACCESS_DENIED",
        E::MissingEvidence => "RESEARCH_INPUT_BINDING_MISSING",
        E::BudgetExceeded => "RESEARCH_INPUT_BINDING_BUDGET_EXCEEDED",
        E::Integrity | E::Mismatch | E::Conflict => MISMATCH,
    }
}
/// The original prepared input hold stays live while the claim is attempted.
pub struct AuthoringClaim {
    run_id: String,
    specification: String,
    generation: String,
    runtime: std::sync::Arc<super::research_runtime::RuntimeInputHold>,
    installation: onlyalpha_calculation_bridge::ChartInstallation,
}
impl AuthoringClaim {
    pub fn verify(
        run: &VerifiedRun,
        inputs: &crate::application::research_admission::PreparedInputs,
        installation: &onlyalpha_calculation_bridge::ChartInstallation,
        native_version: &str,
    ) -> Result<Self> {
        crate::application::research_run_execution::verify_inputs(run, inputs)?;
        let spec = run.factor_specification()?;
        let generation = spec
            .authoring_generation_fingerprint
            .as_deref()
            .ok_or(MISMATCH)?;
        let image = crate::workers::algorithm::describe_research_runtime(native_version)
            .map_err(|_| "RESEARCH_EXECUTOR_IMAGE_UNAVAILABLE")?;
        crate::application::research_run_execution::verify_executor_image(
            &image,
            &spec.execution_binding,
        )?;
        installation.verify().map_err(|_| MISMATCH)?;
        if installation.artifact_fingerprint() != spec.algorithm_artifact_fingerprint {
            return Err(MISMATCH);
        }
        Ok(Self {
            run_id: run.run_id().into(),
            specification: run.specification_fingerprint().into(),
            generation: generation.into(),
            runtime: inputs.runtime_hold(),
            installation: onlyalpha_calculation_bridge::ChartInstallation::open(
                installation.root(),
                installation.artifact_fingerprint(),
            )
            .map_err(|_| MISMATCH)?,
        })
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RunState {
    Queued,
    Running,
    CancelRequested,
    Completed,
    Failed,
    Cancelled,
}
impl RunState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "QUEUED",
            Self::Running => "RUNNING",
            Self::CancelRequested => "CANCEL_REQUESTED",
            Self::Completed => "COMPLETED",
            Self::Failed => "FAILED",
            Self::Cancelled => "CANCELLED",
        }
    }
    fn parse(s: &str) -> Result<Self> {
        match s {
            "QUEUED" => Ok(Self::Queued),
            "RUNNING" => Ok(Self::Running),
            "CANCEL_REQUESTED" => Ok(Self::CancelRequested),
            "COMPLETED" => Ok(Self::Completed),
            "FAILED" => Ok(Self::Failed),
            "CANCELLED" => Ok(Self::Cancelled),
            _ => Err(MISMATCH),
        }
    }
    pub fn terminal(self) -> bool {
        matches!(self, Self::Completed | Self::Failed | Self::Cancelled)
    }
}
/// Observation only. This summary is never an execution or semantic-completion permit.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RunStatus {
    pub state: RunState,
    pub revision: i64,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FailurePhase {
    Admission,
    Execution,
    ResultCommit,
    ArtifactCommit,
    Operational,
}
impl FailurePhase {
    fn as_str(self) -> &'static str {
        match self {
            Self::Admission => "ADMISSION",
            Self::Execution => "EXECUTION",
            Self::ResultCommit => "RESULT_COMMIT",
            Self::ArtifactCommit => "ARTIFACT_COMMIT",
            Self::Operational => "OPERATIONAL",
        }
    }
}
#[derive(Clone, Debug)]
pub struct Failure {
    phase: FailurePhase,
    code: String,
    detail: String,
}
impl Failure {
    pub fn new(phase: FailurePhase, code: &str, detail: &str) -> Result<Self> {
        if code.is_empty()
            || !code
                .bytes()
                .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'_')
            || detail.is_empty()
        {
            return Err(INVALID);
        }
        Ok(Self {
            phase,
            code: code.into(),
            detail: detail.into(),
        })
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RetryDecision {
    Retry,
    FinalFail,
}
/// Only a committed claim can construct this token. Never serializable or caller-forgeable.
/// A lost heartbeat acknowledgement invalidates local certainty until a new successful heartbeat.
pub struct Claim {
    run_id: String,
    attempt_id: String,
    worker_id: String,
    number: i32,
    max_attempts: i32,
    specification: String,
    admission: String,
    payload: String,
    generation: String,
    schema: i32,
    composition: Option<String>,
    certain: bool,
}
impl Claim {
    pub fn run_id(&self) -> &str {
        &self.run_id
    }
    pub fn attempt_id(&self) -> &str {
        &self.attempt_id
    }
    pub fn worker_instance_id(&self) -> &str {
        &self.worker_id
    }
    pub fn attempt_number(&self) -> i32 {
        self.number
    }
    pub fn runtime_generation_fingerprint(&self) -> &str {
        &self.generation
    }
    pub(crate) fn revoke_certainty(&mut self) {
        self.certain = false;
    }
    pub fn ownership_certain(&self) -> bool {
        self.certain
    }
}
struct LockedRun {
    status: RunStatus,
    queued: SystemTime,
    started: Option<SystemTime>,
    cancel: Option<SystemTime>,
}
impl LockedRun {
    fn check_time(&self, at: SystemTime) -> Result<()> {
        if at < self.queued
            || self.started.is_some_and(|t| at < t)
            || self.cancel.is_some_and(|t| at < t)
        {
            Err(INVALID)
        } else {
            Ok(())
        }
    }
}
pub struct ResearchExecution<'a> {
    client: &'a mut Client,
    guarded: bool,
}
impl<'a> ResearchExecution<'a> {
    pub fn new(client: &'a mut Client) -> Self {
        Self {
            client,
            guarded: false,
        }
    }
    /// Owning Strategy5 completion on the original physical mutation session.
    /// Direct technical Client users retain their existing separate behavior.
    pub async fn complete_guarded(
        session: &mut super::authority_session::AuthoritySession,
        claim: &mut Claim,
        completion: &VerifiedCompletion,
        at: OnlyUtcDateTime,
    ) -> Result<RunStatus> {
        if claim.schema != 5
            || claim.composition.is_none()
            || !matches!(
                completion.run.specification(),
                crate::application::research_run::NativeSpecification::Strategy(_)
            )
        {
            return Err(INVALID);
        }
        completion_matches(
            completion,
            &claim.run_id,
            &claim.specification,
            &claim.admission,
        )?;
        if !claim.certain {
            return Err(LOST);
        }
        claim.certain = false;
        let mut owned = session.take_ownership();
        let result = tokio::time::timeout(Duration::from_secs(5), async {
            let client = owned.client_mut().await.map_err(|_| UNCERTAIN)?;
            claim.certain = true;
            let mut execution = ResearchExecution::new(client);
            execution.guarded = true;
            execution.complete(claim, completion, at).await
        })
        .await
        .map_err(|_| UNCERTAIN)
        .and_then(|r| r);
        claim.certain = false;
        match result {
            Ok(status) => {
                owned.verify().await.map_err(|_| UNCERTAIN)?;
                session.restore_ownership(owned);
                Ok(status)
            }
            Err(LOST) => {
                if owned.verify().await.is_ok() {
                    session.restore_ownership(owned);
                }
                Err(LOST)
            }
            Err(error) => Err(error),
        }
    }
    pub async fn reconcile_guarded(
        session: &mut super::authority_session::AuthoritySession,
        inspection: &VerifiedInspection,
        at: OnlyUtcDateTime,
    ) -> Result<RunStatus> {
        if !matches!(
            inspection.run.specification(),
            crate::application::research_run::NativeSpecification::Strategy(_)
        ) {
            return Err(INVALID);
        }
        let mut owned = session.take_ownership();
        let result = tokio::time::timeout(Duration::from_secs(5), async {
            let client = owned.client_mut().await.map_err(|_| UNCERTAIN)?;
            let mut execution = ResearchExecution::new(client);
            execution.guarded = true;
            execution.reconcile(inspection, at).await
        })
        .await
        .map_err(|_| UNCERTAIN)
        .and_then(|r| r);
        match result {
            Ok(status) => {
                owned.verify().await.map_err(|_| UNCERTAIN)?;
                session.restore_ownership(owned);
                Ok(status)
            }
            Err(LOST) => {
                if owned.verify().await.is_ok() {
                    session.restore_ownership(owned);
                }
                Err(LOST)
            }
            Err(error) => Err(error),
        }
    }
    /// A guarded status observation preserves no ambiguous physical session.
    pub async fn observe_guarded(
        session: &mut super::authority_session::AuthoritySession,
        run: &VerifiedRun,
    ) -> Result<RunStatus> {
        let mut owned = session.take_ownership();
        let result = tokio::time::timeout(Duration::from_secs(5), async {
            ResearchExecution::new(owned.client_mut().await.map_err(|_| UNCERTAIN)?)
                .observe(run)
                .await
        })
        .await
        .map_err(|_| UNCERTAIN)
        .and_then(|result| result);
        match result {
            Ok(status) => {
                owned.verify().await.map_err(|_| UNCERTAIN)?;
                session.restore_ownership(owned);
                Ok(status)
            }
            Err(error) => Err(error),
        }
    }
    pub async fn observe(&mut self, run: &VerifiedRun) -> Result<RunStatus> {
        let tx = self.client.transaction().await.map_err(|_| UNAVAILABLE)?;
        bounds(&tx).await?;
        let current = lock_run(
            &tx,
            run.run_id(),
            run.specification_fingerprint(),
            run.admission_resolution_fingerprint(),
            run_lineage(run)?,
            Some(run.canonical_specification_payload()),
            false,
        )
        .await?
        .ok_or(LOST)?;
        tx.commit().await.map_err(|_| UNAVAILABLE)?;
        Ok(current.status)
    }
    /// Observe publication on the original AuthoritySession, then recheck that
    /// same absence proof under the original Run lock before minting a Claim.
    /// This performs no input loading and grants no Source or READY permission.
    pub async fn claim_recompute(
        session: &mut super::authority_session::AuthoritySession,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
        run: &VerifiedRun,
        worker: &str,
        attempt: &str,
        at: OnlyUtcDateTime,
    ) -> Result<Option<Claim>> {
        use super::job_publication::{
            JobRole, PublicationObservation, PublicationRepository, RunLocator, with_job_role,
        };
        run.strategy_specification().map_err(|_| INVALID)?;
        let mut owned = session.take_ownership();
        let result = async {
            let key = RunLocator::new(
                crate::application::job_contract::JobKind::Research,
                run.run_id(),
            )
            .map_err(publication_error)?;
            let observed = with_job_role(&mut owned, JobRole::Publisher, async |client| {
                PublicationRepository::new(client, namespace, run.owner())
                    .await?
                    .observe(&key)
                    .await
            })
            .await
            .map_err(publication_error)?;
            let proof = match observed {
                PublicationObservation::ConfirmedUnpublished(proof)
                    if matches!(proof.run_state(), "QUEUED" | "RUNNING")
                        && proof.active_attempts() == 0
                        && proof.attempts() < 3 =>
                {
                    proof
                }
                _ => return Ok(None),
            };
            let roles = owned.control_roles().map_err(|e| e.code())?;
            ResearchExecution::new(owned.client_mut().await.map_err(|e| e.code())?)
                .claim_bound(
                    run,
                    worker,
                    attempt,
                    at,
                    None,
                    Some((&roles, namespace, &proof)),
                )
                .await
        }
        .await;
        match result {
            Ok(value) => {
                owned.verify().await.map_err(|_| UNCERTAIN)?;
                session.restore_ownership(owned);
                Ok(value)
            }
            Err(error) => Err(error),
        }
    }
    /// PG-only recovery: publication takes priority over inputs; expiry ends
    /// operational ownership only, then fresh absence proof settles control.
    pub async fn recover_finite_guarded(
        session: &mut super::authority_session::AuthoritySession,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
        run: &VerifiedRun,
        at: OnlyUtcDateTime,
    ) -> Result<crate::application::job_recovery::RecoveryDecision> {
        use super::job_publication::PublicationObservation;
        use crate::application::job_recovery::{
            JobRecovery, RecoveryDecision, RecoveryRefusal, RetryBudget,
        };
        run.strategy_specification().map_err(|_| INVALID)?;
        let mut owned = session.take_ownership();
        let result = tokio::time::timeout(Duration::from_secs(5), async {
            let mut observation = observe_finite(&mut owned, namespace, run).await?;
            if let PublicationObservation::ConfirmedUnpublished(proof) = &observation {
                if proof.active_attempts() == 1 {
                    expire_finite(&mut owned, namespace, run, proof).await?;
                    observation = observe_finite(&mut owned, namespace, run).await?;
                }
            }
            // Unresolved never enters expiry or an absence-controlled write.
            let decision = JobRecovery::decide(observation, RetryBudget::finite_job())
                .map_err(publication_error)?;
            match decision {
                RecoveryDecision::FinishCancellation(proof) => {
                    finish_unpublished_finite(
                        &mut owned,
                        namespace,
                        run,
                        &proof,
                        RunState::Cancelled,
                        at,
                    )
                    .await?;
                    JobRecovery::decide(
                        observe_finite(&mut owned, namespace, run).await?,
                        RetryBudget::finite_job(),
                    )
                    .map_err(publication_error)
                }
                RecoveryDecision::Refused(RecoveryRefusal::RetryExhausted, proof) => {
                    finish_unpublished_finite(
                        &mut owned,
                        namespace,
                        run,
                        &proof,
                        RunState::Failed,
                        at,
                    )
                    .await?;
                    JobRecovery::decide(
                        observe_finite(&mut owned, namespace, run).await?,
                        RetryBudget::finite_job(),
                    )
                    .map_err(publication_error)
                }
                decision => Ok(decision),
            }
        })
        .await
        .map_err(|_| UNCERTAIN)
        .and_then(|result| result);
        match result {
            Ok(decision) => {
                owned.verify().await.map_err(|_| UNCERTAIN)?;
                session.restore_ownership(owned);
                Ok(decision)
            }
            Err(error) => Err(error),
        }
    }
    /// The caller first re-verifies this exact immutable specification and Runtime binding.
    /// No semantic work runs while this transaction is open.
    pub async fn claim(
        &mut self,
        run: &VerifiedRun,
        worker_id: &str,
        attempt_id: &str,
        at: OnlyUtcDateTime,
    ) -> Result<Option<Claim>> {
        self.claim_bound(run, worker_id, attempt_id, at, None, None)
            .await
    }

    pub async fn claim_authoring(
        &mut self,
        run: &VerifiedRun,
        proof: &AuthoringClaim,
        worker_id: &str,
        attempt_id: &str,
        at: OnlyUtcDateTime,
    ) -> Result<Option<Claim>> {
        proof.runtime.verify()?;
        proof.installation.verify().map_err(|_| MISMATCH)?;
        self.claim_bound(run, worker_id, attempt_id, at, Some(proof), None)
            .await
    }

    async fn claim_bound(
        &mut self,
        run: &VerifiedRun,
        worker_id: &str,
        attempt_id: &str,
        at: OnlyUtcDateTime,
        authoring: Option<&AuthoringClaim>,
        observation: Option<(
            &super::authority_session::ControlRoleOwner,
            &crate::bootstrap::deployment::SemanticStoreId,
            &super::job_publication::ConfirmedUnpublished,
        )>,
    ) -> Result<Option<Claim>> {
        if !crate::application::command::uuid4(worker_id)
            || !crate::application::command::uuid4(attempt_id)
        {
            return Err(INVALID);
        }
        let max_attempts = 3;
        let seconds = lease_seconds(Duration::from_secs(120))?;
        let at = time(at)?;
        let tx = self.client.transaction().await.map_err(|_| UNAVAILABLE)?;
        bounds(&tx).await?;
        let Some(current) = lock_run(
            &tx,
            run.run_id(),
            run.specification_fingerprint(),
            run.admission_resolution_fingerprint(),
            run_lineage(run)?,
            Some(run.canonical_specification_payload()),
            true,
        )
        .await?
        else {
            tx.commit().await.map_err(|_| UNAVAILABLE)?;
            return Ok(None);
        };
        if let Some((roles, namespace, proof)) = observation {
            super::job_publication::durable(&tx)
                .await
                .map_err(publication_error)?;
            let key = super::job_publication::RunLocator::new(
                crate::application::job_contract::JobKind::Research,
                run.run_id(),
            )
            .map_err(publication_error)?;
            if !super::job_publication::recheck_control_transaction(
                &tx,
                roles,
                proof,
                &key,
                namespace,
                run.owner(),
            )
            .await
            .map_err(publication_error)?
            {
                tx.commit().await.map_err(|_| UNCERTAIN)?;
                return Ok(None);
            }
        }
        let generation = match run.specification() {
            crate::application::research_run::NativeSpecification::Factor(spec) => {
                spec.authoring_generation_fingerprint.as_deref()
            }
            crate::application::research_run::NativeSpecification::Strategy(_) => None,
        };
        match (generation, authoring) {
            (None, None) => {}
            (Some(expected), Some(proof))
                if proof.generation == expected
                    && proof.run_id == run.run_id()
                    && proof.specification == run.specification_fingerprint() => {}
            _ => return Err(MISMATCH),
        }
        if !matches!(current.status.state, RunState::Queued | RunState::Running) {
            return Ok(None);
        }
        current.check_time(at)?;
        let row=tx.query_one("SELECT count(*)::bigint AS count, COALESCE(max(attempt_number),0)::integer AS number, count(*) FILTER(WHERE state='ACTIVE')::bigint AS active FROM research_run_attempt WHERE run_id=$1::text::uuid",&[&run.run_id()]).await.map_err(|_|UNAVAILABLE)?;
        let count: i64 = row.try_get("count").map_err(|_| MISMATCH)?;
        let active: i64 = row.try_get("active").map_err(|_| MISMATCH)?;
        let number: i32 = row.try_get("number").map_err(|_| MISMATCH)?;
        if observation.is_some() && count != i64::from(number) {
            return Err(MISMATCH);
        }
        if active != 0 || count >= i64::from(max_attempts) {
            return Ok(None);
        }
        let number = number.checked_add(1).ok_or(MISMATCH)?;
        if current.status.state == RunState::Queued {
            update_run(
                &tx,
                run.run_id(),
                &current,
                RunState::Running,
                at,
                None,
                None,
            )
            .await?;
        }
        let n=tx.execute("WITH lease AS MATERIALIZED (SELECT clock_timestamp() AS now) INSERT INTO research_run_attempt(attempt_id,run_id,attempt_number,state,worker_instance_id,claimed_at,last_heartbeat_at,lease_expires_at) SELECT $1::text::uuid,$2::text::uuid,$3,'ACTIVE',$4::text::uuid,now,now,now+$5::double precision*interval '1 second' FROM lease",&[&attempt_id,&run.run_id(),&number,&worker_id,&seconds]).await.map_err(|_|UNAVAILABLE)?;
        if n != 1 {
            return Err(LOST);
        }
        if let Some((roles, namespace, _)) = observation {
            tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
                .await
                .map_err(|_| UNAVAILABLE)?;
            let checked = lock_run(
                &tx,
                run.run_id(),
                run.specification_fingerprint(),
                run.admission_resolution_fingerprint(),
                run_lineage(run)?,
                Some(run.canonical_specification_payload()),
                false,
            )
            .await?
            .ok_or(LOST)?;
            let expected = current
                .status
                .revision
                .checked_add(i64::from(current.status.state == RunState::Queued))
                .ok_or(MISMATCH)?;
            if checked.status.state != RunState::Running || checked.status.revision != expected {
                return Err(LOST);
            }
            let checked=tx.query_one("SELECT count(*)::bigint,COALESCE(max(attempt_number),0)::integer,count(*) FILTER(WHERE state='ACTIVE')::bigint,count(*) FILTER(WHERE attempt_id=$2::text::uuid AND worker_instance_id=$3::text::uuid AND attempt_number=$4 AND state='ACTIVE' AND lease_expires_at>clock_timestamp())::bigint FROM research_run_attempt WHERE run_id=$1::text::uuid",&[&run.run_id(),&attempt_id,&worker_id,&number]).await.map_err(|_|UNAVAILABLE)?;
            if checked.get::<_, i64>(0) != i64::from(number)
                || checked.get::<_, i32>(1) != number
                || checked.get::<_, i64>(2) != 1
                || checked.get::<_, i64>(3) != 1
            {
                return Err(LOST);
            }
            let key = super::job_publication::RunLocator::new(
                crate::application::job_contract::JobKind::Research,
                run.run_id(),
            )
            .map_err(publication_error)?;
            super::job_publication::verify_registered_control_transaction(
                &tx,
                roles,
                namespace,
                run.owner(),
                &key,
                run.specification_fingerprint(),
                run.admission_resolution_fingerprint(),
            )
            .await
            .map_err(publication_error)?;
            super::authority_session::AuthoritySession::verify_transaction(&tx)
                .await
                .map_err(|e| e.code())?;
        }
        // Lost commit acknowledgement grants no token and must never be treated as no claim.
        tx.commit().await.map_err(|_| UNCERTAIN)?;
        Ok(Some(Claim {
            run_id: run.run_id().into(),
            attempt_id: attempt_id.into(),
            worker_id: worker_id.into(),
            number,
            max_attempts,
            specification: run.specification_fingerprint().into(),
            admission: run.admission_resolution_fingerprint().into(),
            payload: run.canonical_specification_payload().into(),
            generation: run.runtime_generation_fingerprint()?.into(),
            schema: run_lineage(run)?.0,
            composition: run_lineage(run)?.1.map(str::to_owned),
            certain: true,
        }))
    }
    /// Retain the original guard socket and driver across the complete lease
    /// acknowledgement. Cancellation or an unknown commit revokes this owner.
    pub async fn heartbeat_guarded(
        session: &mut super::authority_session::AuthoritySession,
        claim: &mut Claim,
    ) -> Result<()> {
        claim.certain = false;
        let mut owned = session.take_ownership();
        let outcome = tokio::time::timeout(Duration::from_secs(5), async {
            let client = owned.client_mut().await.map_err(|_| UNCERTAIN)?;
            let mut execution = ResearchExecution::new(client);
            execution.guarded = true;
            execution.heartbeat(claim).await
        })
        .await
        .map_err(|_| UNCERTAIN)
        .and_then(|value| value);
        // The SQL operation alone cannot acknowledge the original physical
        // AuthoritySession. Keep uncertainty until its final proof succeeds.
        claim.certain = false;
        match outcome {
            Ok(()) => {
                owned.verify().await.map_err(|_| UNCERTAIN)?;
                session.restore_ownership(owned);
                claim.certain = true;
                Ok(())
            }
            Err(error) => Err(error),
        }
    }
    pub async fn heartbeat(&mut self, claim: &mut Claim) -> Result<()> {
        let seconds = lease_seconds(Duration::from_secs(120))?;
        claim.certain = false;
        let tx = self.client.transaction().await.map_err(|_| UNCERTAIN)?;
        if self.guarded {
            tx.batch_execute("SET LOCAL search_path=pg_catalog,public,pg_temp")
                .await
                .map_err(|_| UNCERTAIN)?;
            super::authority_session::AuthoritySession::verify_transaction(&tx)
                .await
                .map_err(|_| UNCERTAIN)?;
        }
        bounds(&tx).await.map_err(|_| UNCERTAIN)?;
        let current = lock_claim_run(&tx, claim).await?;
        if !matches!(
            current.status.state,
            RunState::Running | RunState::CancelRequested
        ) {
            return Err(LOST);
        }
        let n=tx.execute("WITH lease AS MATERIALIZED (SELECT clock_timestamp() AS now) UPDATE research_run_attempt a SET last_heartbeat_at=lease.now,lease_expires_at=lease.now+$5::double precision*interval '1 second' FROM lease WHERE a.run_id=$1::text::uuid AND a.attempt_id=$2::text::uuid AND a.worker_instance_id=$3::text::uuid AND a.attempt_number=$4 AND a.state='ACTIVE' AND a.lease_expires_at>lease.now",&[&claim.run_id,&claim.attempt_id,&claim.worker_id,&claim.number,&seconds]).await.map_err(|_|UNCERTAIN)?;
        if n != 1 {
            return Err(LOST);
        }
        if self.guarded {
            // Run deferred work while rollback is still possible, then prove
            // that this exact transaction still owns the original Node guard.
            tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
                .await
                .map_err(|_| UNCERTAIN)?;
            super::authority_session::AuthoritySession::verify_transaction(&tx)
                .await
                .map_err(|_| UNCERTAIN)?;
        }
        tx.commit().await.map_err(|_| UNCERTAIN)?;
        claim.certain = true;
        Ok(())
    }
    /// Expiry ends ownership only. CANCEL_REQUESTED remains pending semantic inspection.
    pub async fn expire(
        &mut self,
        run: &VerifiedRun,
        at: OnlyUtcDateTime,
    ) -> Result<Option<RunStatus>> {
        let at = time(at)?;
        let tx = self.client.transaction().await.map_err(|_| UNAVAILABLE)?;
        bounds(&tx).await?;
        let current = lock_run(
            &tx,
            run.run_id(),
            run.specification_fingerprint(),
            run.admission_resolution_fingerprint(),
            run_lineage(run)?,
            Some(run.canonical_specification_payload()),
            false,
        )
        .await?
        .ok_or(LOST)?;
        if !matches!(
            current.status.state,
            RunState::Running | RunState::CancelRequested
        ) {
            return Err(LOST);
        }
        current.check_time(at)?;
        let row=tx.query_opt("SELECT attempt_id::text,worker_instance_id::text,attempt_number FROM research_run_attempt WHERE run_id=$1::text::uuid AND state='ACTIVE' AND lease_expires_at<=clock_timestamp() FOR UPDATE SKIP LOCKED",&[&run.run_id()]).await.map_err(|_|UNAVAILABLE)?;
        let Some(row) = row else { return Ok(None) };
        let attempt: String = row.try_get("attempt_id").map_err(|_| MISMATCH)?;
        let worker: String = row.try_get("worker_instance_id").map_err(|_| MISMATCH)?;
        let number: i32 = row.try_get("attempt_number").map_err(|_| MISMATCH)?;
        let n=tx.execute("WITH lease AS MATERIALIZED (SELECT clock_timestamp() AS now) UPDATE research_run_attempt a SET state='EXPIRED',finished_at=lease.now,failure_phase='OPERATIONAL',failure_code='LEASE_EXPIRED',failure_detail='Attempt lease expired before operational finalization' FROM lease WHERE a.run_id=$1::text::uuid AND a.attempt_id=$2::text::uuid AND a.worker_instance_id=$3::text::uuid AND a.attempt_number=$4 AND a.state='ACTIVE' AND a.lease_expires_at<=lease.now",&[&run.run_id(),&attempt,&worker,&number]).await.map_err(|_|UNAVAILABLE)?;
        if n != 1 {
            return Err(LOST);
        }
        let status = if current.status.state == RunState::Running && number >= 3 {
            let failure = Failure::new(
                FailurePhase::Operational,
                "ATTEMPT_LIMIT_EXHAUSTED",
                "Attempt budget exhausted after lease expiry",
            )?;
            update_run(
                &tx,
                run.run_id(),
                &current,
                RunState::Failed,
                at,
                None,
                Some(&failure),
            )
            .await?
        } else {
            current.status
        };
        tx.commit().await.map_err(|_| UNAVAILABLE)?;
        Ok(Some(status))
    }
    pub async fn complete(
        &mut self,
        claim: &mut Claim,
        completion: &VerifiedCompletion,
        at: OnlyUtcDateTime,
    ) -> Result<RunStatus> {
        completion.verify_cut()?;
        completion_matches(
            completion,
            &claim.run_id,
            &claim.specification,
            &claim.admission,
        )?;
        self.finalize(claim, Finalization::Complete(completion), at)
            .await
    }
    pub async fn fail(
        &mut self,
        claim: &mut Claim,
        failure: &Failure,
        retry: RetryDecision,
        at: OnlyUtcDateTime,
    ) -> Result<RunStatus> {
        self.finalize(claim, Finalization::Fail(failure, retry), at)
            .await
    }
    /// A healthy ACTIVE cancellation requires actual task reclamation evidence.
    pub async fn cancel_finite_guarded(
        session: &mut super::authority_session::AuthoritySession,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
        run: &VerifiedRun,
        claim: &mut Claim,
        drained: &crate::application::finite_job::DrainedFiniteJob,
        at: OnlyUtcDateTime,
    ) -> Result<RunStatus> {
        if !claim.certain {
            return Err(UNCERTAIN);
        }
        drained
            .verify_attempt(&super::job_publication::AttemptClaim::from_research(claim))
            .map_err(|_| INVALID)?;
        Self::finish_finite_bound(
            session,
            namespace,
            run,
            claim,
            drained.binding(),
            FiniteFinish::Cancel,
            at,
        )
        .await
    }
    pub(crate) async fn cancel_preparation_guarded(
        session: &mut super::authority_session::AuthoritySession,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
        run: &VerifiedRun,
        claim: &mut Claim,
        aborted: &crate::application::finite_job::AbortedPreparation,
        at: OnlyUtcDateTime,
    ) -> Result<RunStatus> {
        if !claim.certain {
            return Err(UNCERTAIN);
        }
        aborted
            .verify_attempt(&super::job_publication::AttemptClaim::from_research(claim))
            .map_err(|_| INVALID)?;
        Self::finish_finite_bound(
            session,
            namespace,
            run,
            claim,
            aborted.binding(),
            FiniteFinish::Cancel,
            at,
        )
        .await
    }
    pub(crate) async fn fail_preparation_guarded(
        session: &mut super::authority_session::AuthoritySession,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
        run: &VerifiedRun,
        claim: &mut Claim,
        aborted: &crate::application::finite_job::AbortedPreparation,
        failure: &Failure,
        retry: RetryDecision,
        at: OnlyUtcDateTime,
    ) -> Result<RunStatus> {
        if !claim.certain {
            return Err(UNCERTAIN);
        }
        aborted
            .verify_attempt(&super::job_publication::AttemptClaim::from_research(claim))
            .map_err(|_| INVALID)?;
        Self::finish_finite_bound(
            session,
            namespace,
            run,
            claim,
            aborted.binding(),
            FiniteFinish::Fail(failure, retry),
            at,
        )
        .await
    }
    pub(crate) async fn fail_finite_guarded(
        session: &mut super::authority_session::AuthoritySession,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
        run: &VerifiedRun,
        claim: &mut Claim,
        drained: &crate::application::finite_job::DrainedFiniteJob,
        failure: &Failure,
        retry: RetryDecision,
        at: OnlyUtcDateTime,
    ) -> Result<RunStatus> {
        if !claim.certain {
            return Err(UNCERTAIN);
        }
        drained
            .verify_attempt(&super::job_publication::AttemptClaim::from_research(claim))
            .map_err(|_| INVALID)?;
        Self::finish_finite_bound(
            session,
            namespace,
            run,
            claim,
            drained.binding(),
            FiniteFinish::Fail(failure, retry),
            at,
        )
        .await
    }
    async fn finish_finite_bound(
        session: &mut super::authority_session::AuthoritySession,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
        run: &VerifiedRun,
        claim: &mut Claim,
        binding: &crate::application::job_contract::FrozenJobBinding,
        finish: FiniteFinish<'_>,
        at: OnlyUtcDateTime,
    ) -> Result<RunStatus> {
        use crate::application::job_contract::JobKind;
        if !claim.certain {
            return Err(UNCERTAIN);
        }
        if binding.kind() != JobKind::Research
            || binding.run_id() != run.run_id()
            || binding.namespace() != namespace.value()
            || binding.owner() != run.owner()
            || claim.run_id != run.run_id()
            || claim.specification != run.specification_fingerprint()
            || claim.admission != run.admission_resolution_fingerprint()
            || claim.payload != run.canonical_specification_payload()
            || (claim.schema, claim.composition.as_deref()) != run_lineage(run)?
            || claim.generation != run.runtime_generation_fingerprint()?
            || run.strategy_specification().is_err()
        {
            return Err(INVALID);
        }
        claim.certain = false;
        let mut owned = session.take_ownership();
        let roles = owned.control_roles().map_err(|_| UNCERTAIN)?;
        let result = tokio::time::timeout(Duration::from_secs(5), async {
            let client = owned.client_mut().await.map_err(|_| UNCERTAIN)?;
            claim.certain = true;
            let mut execution = ResearchExecution::new(client);
            execution.guarded = true;
            let cut = UnpublishedControlCut {
                roles: &roles,
                namespace,
                binding,
            };
            let outcome = match finish {
                FiniteFinish::Cancel => Finalization::FiniteCancel(cut),
                FiniteFinish::Fail(failure, retry) => Finalization::FiniteFail(failure, retry, cut),
            };
            execution.finalize(claim, outcome, at).await
        })
        .await
        .map_err(|_| UNCERTAIN)
        .and_then(|result| result);
        claim.certain = false;
        match result {
            Ok(status) => {
                owned.verify().await.map_err(|_| UNCERTAIN)?;
                session.restore_ownership(owned);
                Ok(status)
            }
            Err(error) => Err(error),
        }
    }
    pub async fn cancel(&mut self, claim: &mut Claim, at: OnlyUtcDateTime) -> Result<RunStatus> {
        self.finalize(claim, Finalization::Cancel, at).await
    }
    async fn finalize(
        &mut self,
        claim: &mut Claim,
        outcome: Finalization<'_>,
        at: OnlyUtcDateTime,
    ) -> Result<RunStatus> {
        if !claim.certain {
            return Err(UNCERTAIN);
        }
        let at = time(at)?;
        claim.certain = false;
        let tx = self.client.transaction().await.map_err(|_| UNCERTAIN)?;
        if self.guarded {
            tx.batch_execute("SET LOCAL search_path=pg_catalog,public,pg_temp")
                .await
                .map_err(|_| UNCERTAIN)?;
        }
        bounds(&tx).await?;
        let current = lock_claim_run(&tx, claim).await?;
        if !matches!(
            current.status.state,
            RunState::Running | RunState::CancelRequested
        ) {
            return Err(LOST);
        }
        current.check_time(at)?;
        if let Finalization::FiniteCancel(cut) | Finalization::FiniteFail(_, _, cut) = outcome {
            cut.verify(&tx, claim).await?;
        }
        let (attempt, target, completion, failure) = match outcome {
            Finalization::Complete(c) => ("SUCCEEDED", Some(RunState::Completed), Some(c), None),
            Finalization::FiniteFail(_, _, _)
                if current.status.state == RunState::CancelRequested =>
            {
                ("CANCELLED", Some(RunState::Cancelled), None, None)
            }
            Finalization::Fail(f, r) | Finalization::FiniteFail(f, r, _) => (
                "FAILED",
                if r == RetryDecision::Retry
                    && current.status.state == RunState::Running
                    && claim.number < claim.max_attempts
                {
                    None
                } else {
                    Some(RunState::Failed)
                },
                None,
                Some(f),
            ),
            Finalization::Cancel | Finalization::FiniteCancel(_)
                if current.status.state == RunState::CancelRequested =>
            {
                ("CANCELLED", Some(RunState::Cancelled), None, None)
            }
            Finalization::Cancel | Finalization::FiniteCancel(_) => return Err(LOST),
        };
        // Re-evaluate the server clock in the final write, after all row-lock waits.
        // Run-first lock order is shared by claim, heartbeat, expiry and cancellation.
        let phase = failure.map(|f| f.phase.as_str());
        let code = failure.map(|f| f.code.as_str());
        let detail = failure.map(|f| f.detail.as_str());
        let n=tx.execute("UPDATE research_run_attempt SET state=$5,finished_at=clock_timestamp(),failure_phase=$6,failure_code=$7,failure_detail=$8 WHERE run_id=$1::text::uuid AND attempt_id=$2::text::uuid AND worker_instance_id=$3::text::uuid AND attempt_number=$4 AND state='ACTIVE' AND lease_expires_at>clock_timestamp()",&[&claim.run_id,&claim.attempt_id,&claim.worker_id,&claim.number,&attempt,&phase,&code,&detail]).await.map_err(|_|UNCERTAIN)?;
        if n != 1 {
            return Err(LOST);
        }
        let status = if let Some(target) = target {
            update_run(
                &tx,
                &claim.run_id,
                &current,
                target,
                at,
                completion,
                failure,
            )
            .await?
        } else {
            current.status
        };
        if let Some(completion) = completion {
            completion.verify_cut()?;
        }
        if self.guarded {
            let expected_run = guarded_document(&tx, &claim.run_id, None).await?;
            let expected_attempt =
                guarded_document(&tx, &claim.run_id, Some(&claim.attempt_id)).await?;
            tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
                .await
                .map_err(|_| UNCERTAIN)?;
            guarded_run_readback(
                &tx,
                RunReadbackIdentity {
                    id: &claim.run_id,
                    spec: &claim.specification,
                    admission: &claim.admission,
                    lineage: (claim.schema, claim.composition.as_deref()),
                    payload: &claim.payload,
                },
                &status,
                completion,
                &expected_run,
            )
            .await?;
            guarded_attempt_readback(&tx, claim, attempt, &expected_attempt).await?;
            if let Finalization::FiniteCancel(cut) | Finalization::FiniteFail(_, _, cut) = outcome {
                cut.verify(&tx, claim).await?;
            }
            super::authority_session::AuthoritySession::verify_transaction(&tx)
                .await
                .map_err(|_| UNCERTAIN)?;
        }
        tx.commit().await.map_err(|_| UNCERTAIN)?;
        if let Some(completion) = completion {
            completion.verify_cut()?;
        }
        Ok(status)
    }
    pub async fn request_cancel(
        &mut self,
        run: &VerifiedRun,
        at: OnlyUtcDateTime,
    ) -> Result<RunStatus> {
        let tx = self.client.transaction().await.map_err(|_| UNAVAILABLE)?;
        let status = Self::request_cancel_in_transaction(&tx, run, at).await?;
        tx.commit().await.map_err(|_| UNAVAILABLE)?;
        Ok(status)
    }
    /// Caller commits Cancel Command, this effect and its Receipt in one transaction.
    pub async fn request_cancel_in_transaction(
        tx: &Transaction<'_>,
        run: &VerifiedRun,
        at: OnlyUtcDateTime,
    ) -> Result<RunStatus> {
        bounds(tx).await?;
        let current = lock_run(
            tx,
            run.run_id(),
            run.specification_fingerprint(),
            run.admission_resolution_fingerprint(),
            run_lineage(run)?,
            Some(run.canonical_specification_payload()),
            false,
        )
        .await?
        .ok_or(LOST)?;
        let target = match current.status.state {
            RunState::Queued => RunState::Cancelled,
            RunState::Running => RunState::CancelRequested,
            RunState::Completed | RunState::Failed => return Err("RESEARCH_CANCEL_CONFLICT"),
            _ => return Ok(current.status),
        };
        update_run(tx, run.run_id(), &current, target, time(at)?, None, None).await
    }
    /// The inspection was produced by non-mutating exact immutable fact reads.
    /// This transaction never calculates or fills in missing semantic work.
    pub async fn reconcile(
        &mut self,
        inspection: &VerifiedInspection,
        at: OnlyUtcDateTime,
    ) -> Result<RunStatus> {
        inspection.verify_cut()?;
        let tx = self.client.transaction().await.map_err(|_| UNAVAILABLE)?;
        if self.guarded {
            tx.batch_execute("SET LOCAL search_path=pg_catalog,public,pg_temp")
                .await
                .map_err(|_| UNCERTAIN)?;
        }
        bounds(&tx).await?;
        let current = lock_run(
            &tx,
            inspection.run_id(),
            inspection.specification_fingerprint(),
            inspection.admission_resolution_fingerprint(),
            run_lineage(&inspection.run)?,
            None,
            false,
        )
        .await?
        .ok_or(LOST)?;
        if current.status.state != RunState::CancelRequested
            || current.status.revision != inspection.expected_revision()
        {
            return Err(LOST);
        }
        if tx
            .query_opt(
                "SELECT 1 FROM research_run_attempt WHERE run_id=$1::text::uuid AND state='ACTIVE'",
                &[&inspection.run_id()],
            )
            .await
            .map_err(|_| UNAVAILABLE)?
            .is_some()
        {
            return Err(LOST);
        }
        let corrupt = Failure::new(
            FailurePhase::Operational,
            "RESEARCH_SEMANTIC_AUTHORITY_CORRUPT",
            "Exact semantic completion inspection found corrupt or conflicting authority",
        )?;
        let (target, completion, failure) = match inspection.outcome() {
            InspectionOutcome::Complete(c) => {
                completion_matches(
                    c,
                    inspection.run_id(),
                    inspection.specification_fingerprint(),
                    inspection.admission_resolution_fingerprint(),
                )?;
                (RunState::Completed, Some(c.as_ref()), None)
            }
            InspectionOutcome::Absent => (RunState::Cancelled, None, None),
            InspectionOutcome::Corrupt => (RunState::Failed, None, Some(&corrupt)),
        };
        let status = update_run(
            &tx,
            inspection.run_id(),
            &current,
            target,
            time(at)?,
            completion,
            failure,
        )
        .await?;
        inspection.verify_cut()?;
        if self.guarded {
            let expected_run = guarded_document(&tx, inspection.run_id(), None).await?;
            tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
                .await
                .map_err(|_| UNCERTAIN)?;
            guarded_run_readback(
                &tx,
                RunReadbackIdentity {
                    id: inspection.run_id(),
                    spec: inspection.specification_fingerprint(),
                    admission: inspection.admission_resolution_fingerprint(),
                    lineage: run_lineage(&inspection.run)?,
                    payload: inspection.run.canonical_specification_payload(),
                },
                &status,
                completion,
                &expected_run,
            )
            .await?;
            let active=tx.query_opt("SELECT 1 FROM public.research_run_attempt WHERE run_id=$1::pg_catalog.text::pg_catalog.uuid AND state='ACTIVE'",&[&inspection.run_id()]).await.map_err(|_|UNCERTAIN)?;
            if active.is_some() {
                return Err(MISMATCH);
            }
            inspection.verify_cut()?;
            super::authority_session::AuthoritySession::verify_transaction(&tx)
                .await
                .map_err(|_| UNCERTAIN)?;
        }
        tx.commit().await.map_err(|_| UNAVAILABLE)?;
        if self.guarded {
            inspection.verify_cut()?;
        }
        Ok(status)
    }
}
#[derive(Clone, Copy)]
enum FiniteFinish<'a> {
    Cancel,
    Fail(&'a Failure, RetryDecision),
}
#[derive(Clone, Copy)]
struct UnpublishedControlCut<'a> {
    roles: &'a super::authority_session::ControlRoleOwner,
    namespace: &'a crate::bootstrap::deployment::SemanticStoreId,
    binding: &'a crate::application::job_contract::FrozenJobBinding,
}
impl UnpublishedControlCut<'_> {
    async fn verify(&self, tx: &Transaction<'_>, claim: &Claim) -> Result<()> {
        super::job_publication::verify_unpublished_control_transaction(
            tx,
            self.roles,
            self.namespace,
            self.binding,
            &claim.specification,
            &claim.admission,
        )
        .await
        .map_err(publication_error)
    }
}
#[derive(Clone, Copy)]
enum Finalization<'a> {
    Complete(&'a VerifiedCompletion),
    Fail(&'a Failure, RetryDecision),
    Cancel,
    FiniteCancel(UnpublishedControlCut<'a>),
    FiniteFail(&'a Failure, RetryDecision, UnpublishedControlCut<'a>),
}
fn time(at: OnlyUtcDateTime) -> Result<SystemTime> {
    super::postgres::system_time(at).map_err(|_| INVALID)
}
fn lease_seconds(lease: Duration) -> Result<f64> {
    // PostgreSQL timestamps resolve microseconds; a smaller lease would expire on insertion.
    if lease < Duration::from_micros(1) {
        return Err(INVALID);
    }
    Ok(lease.as_secs_f64())
}
async fn bounds(tx: &Transaction<'_>) -> Result<()> {
    super::postgres::bounds(tx).await.map_err(|_| UNAVAILABLE)
}
fn run_lineage(run: &VerifiedRun) -> Result<(i32, Option<&str>)> {
    match run.specification() {
        crate::application::research_run::NativeSpecification::Factor(spec) => {
            Ok((spec.schema_version as i32, None))
        }
        crate::application::research_run::NativeSpecification::Strategy(_) => {
            let composition = run.prepared_inputs["composition"]["composition_fingerprint"]
                .as_str()
                .filter(|p| crate::is_sha256_hex(p))
                .ok_or(MISMATCH)?;
            Ok((5, Some(composition)))
        }
    }
}
async fn lock_claim_run(tx: &Transaction<'_>, claim: &Claim) -> Result<LockedRun> {
    lock_run(
        tx,
        &claim.run_id,
        &claim.specification,
        &claim.admission,
        (claim.schema, claim.composition.as_deref()),
        Some(&claim.payload),
        false,
    )
    .await?
    .ok_or(LOST)
}
async fn lock_run(
    tx: &Transaction<'_>,
    id: &str,
    spec: &str,
    admission: &str,
    lineage: (i32, Option<&str>),
    payload: Option<&str>,
    skip: bool,
) -> Result<Option<LockedRun>> {
    let sql = if skip {
        "SELECT revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_fingerprint,origin_kind,strategy_research_composition_fingerprint,authoring_provenance IS NULL AS native_authoring,queued_at,started_at,cancel_requested_at FROM research_run WHERE run_id=$1::text::uuid FOR UPDATE SKIP LOCKED"
    } else {
        "SELECT revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_fingerprint,origin_kind,strategy_research_composition_fingerprint,authoring_provenance IS NULL AS native_authoring,queued_at,started_at,cancel_requested_at FROM research_run WHERE run_id=$1::text::uuid FOR UPDATE"
    };
    let Some(row) = tx.query_opt(sql, &[&id]).await.map_err(|_| UNAVAILABLE)? else {
        return Ok(None);
    };
    let schema: i32 = row
        .try_get("specification_schema_version")
        .map_err(|_| MISMATCH)?;
    let origin: String = row.try_get("origin_kind").map_err(|_| MISMATCH)?;
    let composition: Option<String> = row
        .try_get("strategy_research_composition_fingerprint")
        .map_err(|_| MISMATCH)?;
    let actual_spec: String = row
        .try_get("specification_fingerprint")
        .map_err(|_| MISMATCH)?;
    let actual_admission: String = row
        .try_get("admission_resolution_fingerprint")
        .map_err(|_| MISMATCH)?;
    let actual_payload: String = row.try_get("specification_payload").map_err(|_| MISMATCH)?;
    let native_authoring: bool = row.try_get("native_authoring").map_err(|_| MISMATCH)?;
    if schema != lineage.0
        || !matches!(
            (schema, origin.as_str()),
            (4 | 6, "GENERAL") | (5, "PRIVATE_STRATEGY")
        )
        || composition.as_deref() != lineage.1
        || (schema == 5) != composition.is_some()
        || !native_authoring
        || actual_spec != spec
        || actual_admission != admission
        || payload.is_some_and(|p| p != actual_payload)
    {
        return Err(MISMATCH);
    }
    let revision: i64 = row.try_get("revision").map_err(|_| MISMATCH)?;
    let state: String = row.try_get("state").map_err(|_| MISMATCH)?;
    if revision < 0 {
        return Err(MISMATCH);
    }
    Ok(Some(LockedRun {
        status: RunStatus {
            state: RunState::parse(&state)?,
            revision,
        },
        queued: row.try_get("queued_at").map_err(|_| MISMATCH)?,
        started: row.try_get("started_at").map_err(|_| MISMATCH)?,
        cancel: row.try_get("cancel_requested_at").map_err(|_| MISMATCH)?,
    }))
}
fn completion_matches(c: &VerifiedCompletion, id: &str, spec: &str, admission: &str) -> Result<()> {
    let evidence = c.calculation_execution_evidence_fingerprints();
    if c.run_id() != id
        || c.specification_fingerprint() != spec
        || c.admission_resolution_fingerprint() != admission
        || !crate::is_sha256_hex(c.research_result_fingerprint())
        || !crate::is_sha256_hex(c.artifact_content_fingerprint())
        || evidence.is_empty()
        || evidence.iter().any(|f| !crate::is_sha256_hex(f))
        || evidence.windows(2).any(|w| w[0] >= w[1])
    {
        return Err(MISMATCH);
    }
    Ok(())
}
async fn update_run(
    tx: &Transaction<'_>,
    id: &str,
    current: &LockedRun,
    target: RunState,
    at: SystemTime,
    completion: Option<&VerifiedCompletion>,
    failure: Option<&Failure>,
) -> Result<RunStatus> {
    let legal = matches!(
        (current.status.state, target),
        (RunState::Queued, RunState::Running | RunState::Cancelled)
            | (
                RunState::Running,
                RunState::CancelRequested | RunState::Completed | RunState::Failed
            )
            | (
                RunState::CancelRequested,
                RunState::Completed | RunState::Failed | RunState::Cancelled
            )
    );
    if !legal
        || (target == RunState::Completed) != completion.is_some()
        || (target == RunState::Failed) != failure.is_some()
    {
        return Err(LOST);
    }
    current.check_time(at)?;
    let revision = current.status.revision.checked_add(1).ok_or(MISMATCH)?;
    let start = if target == RunState::Running {
        Some(at)
    } else {
        current.started
    };
    let cancel = if target == RunState::CancelRequested {
        Some(at)
    } else {
        current.cancel
    };
    let finish = target.terminal().then_some(at);
    let result = completion.map(VerifiedCompletion::research_result_fingerprint);
    let artifact = completion.map(VerifiedCompletion::artifact_content_fingerprint);
    let evidence = completion.map(|c| c.calculation_execution_evidence_fingerprints().to_vec());
    let phase = failure.map(|f| f.phase.as_str());
    let code = failure.map(|f| f.code.as_str());
    let detail = failure.map(|f| f.detail.as_str());
    let changed = if completion.is_some() {
        tx.execute("UPDATE research_run SET revision=$4,state=$5,started_at=$6,cancel_requested_at=$7,finished_at=$8,research_result_fingerprint=$9,artifact_content_fingerprint=$10,calculation_execution_evidence_fingerprints=$11,failure_phase=$12,failure_code=$13,failure_detail=$14 WHERE run_id=$1::text::uuid AND revision=$2 AND state=$3",&[&id,&current.status.revision,&current.status.state.as_str(),&revision,&target.as_str(),&start,&cancel,&finish,&result,&artifact,&evidence,&phase,&code,&detail]).await
    } else {
        tx.execute("UPDATE research_run SET revision=$4,state=$5,started_at=$6,cancel_requested_at=$7,finished_at=$8,failure_phase=$9,failure_code=$10,failure_detail=$11 WHERE run_id=$1::text::uuid AND revision=$2 AND state=$3",&[&id,&current.status.revision,&current.status.state.as_str(),&revision,&target.as_str(),&start,&cancel,&finish,&phase,&code,&detail]).await
    };
    let n = changed.map_err(|error| {
        tracing::error!(target:"onlyalpha.observability", operation="research_execution.update_run", phase=if completion.is_some() {"result"} else {"control"}, sqlstate=error.code().map(|code|code.code()), "Research state transition failed");
        UNAVAILABLE
    })?;
    if n != 1 {
        return Err(LOST);
    }
    Ok(RunStatus {
        state: target,
        revision,
    })
}

struct RunReadbackIdentity<'a> {
    id: &'a str,
    spec: &'a str,
    admission: &'a str,
    lineage: (i32, Option<&'a str>),
    payload: &'a str,
}

async fn guarded_run_readback(
    tx: &Transaction<'_>,
    identity: RunReadbackIdentity<'_>,
    expected: &RunStatus,
    completion: Option<&VerifiedCompletion>,
    expected_document: &serde_json::Value,
) -> Result<()> {
    let RunReadbackIdentity {
        id,
        spec,
        admission,
        lineage,
        payload,
    } = identity;
    let current = lock_run(tx, id, spec, admission, lineage, Some(payload), false)
        .await?
        .ok_or(MISMATCH)?;
    if current.status.state != expected.state || current.status.revision != expected.revision {
        return Err(MISMATCH);
    }
    let row=tx.query_one("SELECT pg_catalog.row_to_json(r)::pg_catalog.text FROM public.research_run r WHERE run_id=$1::pg_catalog.text::pg_catalog.uuid",&[&id]).await.map_err(|_|UNCERTAIN)?;
    let raw: String = row.try_get(0).map_err(|_| MISMATCH)?;
    if raw.len() > 8 * 1024 * 1024 {
        return Err(MISMATCH);
    }
    let value: serde_json::Value = serde_json::from_str(&raw).map_err(|_| MISMATCH)?;
    validate_source_history_event("RESEARCH_RUN", &value)?;
    if &value != expected_document {
        return Err(MISMATCH);
    }
    let document_limit: i64 = 8 * 1024 * 1024;
    let history = tx.query_opt("SELECT CASE WHEN pg_catalog.octet_length(h.source_row::pg_catalog.text) OPERATOR(pg_catalog.<=) $2::pg_catalog.int8 THEN h.source_row::pg_catalog.text ELSE NULL END FROM (SELECT source_row FROM public.research_source_history WHERE source_family OPERATOR(pg_catalog.=) 'RESEARCH_RUN'::pg_catalog.text AND native_locator OPERATOR(pg_catalog.=) $1::pg_catalog.text ORDER BY event_index DESC LIMIT 1) h",&[&id, &document_limit]).await.map_err(|_|UNCERTAIN)?;
    let history: Option<String> = history
        .map(|row| row.try_get::<_, Option<String>>(0))
        .transpose()
        .map_err(|_| UNCERTAIN)?
        .flatten();
    verify_run_source_history(&value, history.as_deref()).map_err(|error| {
        if error == "NOVELTY_PROOF_UNAVAILABLE" {
            UNCERTAIN
        } else {
            MISMATCH
        }
    })?;
    if let Some(proof) = completion {
        if value["state"] != "COMPLETED"
            || value["research_result_fingerprint"] != proof.research_result_fingerprint()
            || value["artifact_content_fingerprint"] != proof.artifact_content_fingerprint()
            || value["calculation_execution_evidence_fingerprints"]
                != serde_json::json!(proof.calculation_execution_evidence_fingerprints())
            || value["finished_at"].is_null()
            || !value["failure_phase"].is_null()
            || !value["failure_code"].is_null()
            || !value["failure_detail"].is_null()
        {
            return Err(MISMATCH);
        }
        proof.verify_cut()?;
    }
    Ok(())
}
async fn guarded_attempt_readback(
    tx: &Transaction<'_>,
    claim: &Claim,
    expected: &str,
    expected_document: &serde_json::Value,
) -> Result<()> {
    guarded_attempt_identity_readback(
        tx,
        AttemptReadbackIdentity {
            run_id: &claim.run_id,
            attempt_id: &claim.attempt_id,
            worker_id: &claim.worker_id,
            number: claim.number,
        },
        expected,
        expected_document,
    )
    .await
}
struct AttemptReadbackIdentity<'a> {
    run_id: &'a str,
    attempt_id: &'a str,
    worker_id: &'a str,
    number: i32,
}
async fn guarded_attempt_identity_readback(
    tx: &Transaction<'_>,
    identity: AttemptReadbackIdentity<'_>,
    expected: &str,
    expected_document: &serde_json::Value,
) -> Result<()> {
    let row=tx.query_one("SELECT pg_catalog.row_to_json(a)::pg_catalog.text FROM public.research_run_attempt a WHERE run_id=$1::pg_catalog.text::pg_catalog.uuid AND attempt_id=$2::pg_catalog.text::pg_catalog.uuid FOR UPDATE",&[&identity.run_id,&identity.attempt_id]).await.map_err(|_|UNCERTAIN)?;
    let raw: String = row.try_get(0).map_err(|_| MISMATCH)?;
    if raw.len() > 8 * 1024 * 1024 {
        return Err(MISMATCH);
    }
    let value: serde_json::Value = serde_json::from_str(&raw).map_err(|_| MISMATCH)?;
    validate_source_history_event("RESEARCH_ATTEMPT", &value)?;
    if &value != expected_document {
        return Err(MISMATCH);
    }
    if value["worker_instance_id"] != identity.worker_id
        || value["attempt_number"] != identity.number
        || value["state"] != expected
        || (expected == "ACTIVE") != value["finished_at"].is_null()
    {
        return Err(MISMATCH);
    }
    let history:String=tx.query_one("SELECT source_row::pg_catalog.text FROM public.research_source_history WHERE source_family='RESEARCH_ATTEMPT' AND source_row->>'attempt_id'=$1 ORDER BY event_index DESC LIMIT 1",&[&identity.attempt_id]).await.map_err(|_|UNCERTAIN)?.try_get(0).map_err(|_|MISMATCH)?;
    if history.len() > 8 * 1024 * 1024 {
        return Err(MISMATCH);
    }
    let history: serde_json::Value = serde_json::from_str(&history).map_err(|_| MISMATCH)?;
    if history != value {
        return Err(MISMATCH);
    }
    Ok(())
}

async fn guarded_document(
    tx: &Transaction<'_>,
    id: &str,
    attempt: Option<&str>,
) -> Result<serde_json::Value> {
    let row=if let Some(attempt)=attempt {
        tx.query_one("SELECT pg_catalog.row_to_json(a)::pg_catalog.text FROM public.research_run_attempt a WHERE run_id=$1::pg_catalog.text::pg_catalog.uuid AND attempt_id=$2::pg_catalog.text::pg_catalog.uuid",&[&id,&attempt]).await
    }else{
        tx.query_one("SELECT pg_catalog.row_to_json(r)::pg_catalog.text FROM public.research_run r WHERE run_id=$1::pg_catalog.text::pg_catalog.uuid",&[&id]).await
    }.map_err(|_|UNCERTAIN)?;
    let raw: String = row.try_get(0).map_err(|_| MISMATCH)?;
    if raw.len() > 8 * 1024 * 1024 {
        return Err(MISMATCH);
    }
    serde_json::from_str(&raw).map_err(|_| MISMATCH)
}

async fn observe_finite(
    session: &mut super::authority_session::AuthoritySession,
    namespace: &crate::bootstrap::deployment::SemanticStoreId,
    run: &VerifiedRun,
) -> Result<super::job_publication::PublicationObservation> {
    use super::job_publication::{JobRole, PublicationRepository, RunLocator, with_job_role};
    let key = RunLocator::new(
        crate::application::job_contract::JobKind::Research,
        run.run_id(),
    )
    .map_err(publication_error)?;
    with_job_role(session, JobRole::Publisher, async |client| {
        PublicationRepository::new(client, namespace, run.owner())
            .await?
            .observe(&key)
            .await
    })
    .await
    .map_err(publication_error)
}
async fn verify_finite_unpublished(
    tx: &Transaction<'_>,
    roles: &super::authority_session::ControlRoleOwner,
    namespace: &crate::bootstrap::deployment::SemanticStoreId,
    run: &VerifiedRun,
    proof: &super::job_publication::ConfirmedUnpublished,
) -> Result<()> {
    let binding = proof.binding();
    if binding.kind() != crate::application::job_contract::JobKind::Research
        || binding.run_id() != run.run_id()
        || binding.owner() != run.owner()
        || binding.namespace() != namespace.value()
    {
        return Err(MISMATCH);
    }
    super::job_publication::verify_unpublished_control_transaction(
        tx,
        roles,
        namespace,
        binding,
        run.specification_fingerprint(),
        run.admission_resolution_fingerprint(),
    )
    .await
    .map_err(publication_error)
}
/// Expiry relinquishes only this expired operational owner. It never creates
/// a semantic failure/cancellation or changes the finite three-Attempt budget.
async fn expire_finite(
    session: &mut super::authority_session::AuthoritySession,
    namespace: &crate::bootstrap::deployment::SemanticStoreId,
    run: &VerifiedRun,
    proof: &super::job_publication::ConfirmedUnpublished,
) -> Result<()> {
    let roles = session.control_roles().map_err(|_| UNCERTAIN)?;
    let tx = session
        .client_mut()
        .await
        .map_err(|_| UNCERTAIN)?
        .transaction()
        .await
        .map_err(|_| UNCERTAIN)?;
    tx.batch_execute("SET LOCAL search_path=pg_catalog,public,pg_temp")
        .await
        .map_err(|_| UNCERTAIN)?;
    bounds(&tx).await?;
    let current = lock_run(
        &tx,
        run.run_id(),
        run.specification_fingerprint(),
        run.admission_resolution_fingerprint(),
        run_lineage(run)?,
        Some(run.canonical_specification_payload()),
        false,
    )
    .await?
    .ok_or(LOST)?;
    if proof.active_attempts() != 1
        || current.status.revision != proof.run_revision()
        || current.status.state.as_str() != proof.run_state()
        || !matches!(
            current.status.state,
            RunState::Running | RunState::CancelRequested
        )
    {
        tx.commit().await.map_err(|_| UNCERTAIN)?;
        return Ok(());
    }
    verify_finite_unpublished(&tx, &roles, namespace, run, proof).await?;
    let row=tx.query_opt("SELECT attempt_id::text,worker_instance_id::text,attempt_number FROM public.research_run_attempt WHERE run_id=$1::text::uuid AND attempt_number=$2 AND state='ACTIVE' AND lease_expires_at<=clock_timestamp() FOR UPDATE",&[&run.run_id(),&proof.attempts()]).await.map_err(|_|UNAVAILABLE)?;
    let Some(row) = row else {
        tx.commit().await.map_err(|_| UNCERTAIN)?;
        return Ok(());
    };
    let attempt: String = row.try_get(0).map_err(|_| MISMATCH)?;
    let worker: String = row.try_get(1).map_err(|_| MISMATCH)?;
    let number: i32 = row.try_get(2).map_err(|_| MISMATCH)?;
    let before = guarded_document(&tx, run.run_id(), Some(&attempt)).await?;
    guarded_attempt_identity_readback(
        &tx,
        AttemptReadbackIdentity {
            run_id: run.run_id(),
            attempt_id: &attempt,
            worker_id: &worker,
            number,
        },
        "ACTIVE",
        &before,
    )
    .await?;
    let changed=tx.execute("UPDATE public.research_run_attempt SET state='EXPIRED',finished_at=clock_timestamp(),failure_phase='OPERATIONAL',failure_code='LEASE_EXPIRED',failure_detail='Attempt lease expired before operational finalization' WHERE run_id=$1::text::uuid AND attempt_id=$2::text::uuid AND worker_instance_id=$3::text::uuid AND attempt_number=$4 AND state='ACTIVE' AND lease_expires_at<=clock_timestamp()",&[&run.run_id(),&attempt,&worker,&number]).await.map_err(|_|UNCERTAIN)?;
    if changed != 1 {
        return Err(LOST);
    }
    let expected = guarded_document(&tx, run.run_id(), Some(&attempt)).await?;
    let expected_run = guarded_document(&tx, run.run_id(), None).await?;
    tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
        .await
        .map_err(|_| UNCERTAIN)?;
    guarded_attempt_identity_readback(
        &tx,
        AttemptReadbackIdentity {
            run_id: run.run_id(),
            attempt_id: &attempt,
            worker_id: &worker,
            number,
        },
        "EXPIRED",
        &expected,
    )
    .await?;
    guarded_run_readback(
        &tx,
        RunReadbackIdentity {
            id: run.run_id(),
            spec: run.specification_fingerprint(),
            admission: run.admission_resolution_fingerprint(),
            lineage: run_lineage(run)?,
            payload: run.canonical_specification_payload(),
        },
        &current.status,
        None,
        &expected_run,
    )
    .await?;
    verify_finite_unpublished(&tx, &roles, namespace, run, proof).await?;
    roles.verify_transaction(&tx).await.map_err(|_| UNCERTAIN)?;
    tx.commit().await.map_err(|_| UNCERTAIN)?;
    Ok(())
}
async fn finish_unpublished_finite(
    session: &mut super::authority_session::AuthoritySession,
    namespace: &crate::bootstrap::deployment::SemanticStoreId,
    run: &VerifiedRun,
    proof: &super::job_publication::ConfirmedUnpublished,
    target: RunState,
    at: OnlyUtcDateTime,
) -> Result<()> {
    use super::job_publication::{RunLocator, read_control_facts, recheck_control_transaction};
    let roles = session.control_roles().map_err(|_| UNCERTAIN)?;
    let tx = session
        .client_mut()
        .await
        .map_err(|_| UNCERTAIN)?
        .transaction()
        .await
        .map_err(|_| UNCERTAIN)?;
    tx.batch_execute("SET LOCAL search_path=pg_catalog,public,pg_temp")
        .await
        .map_err(|_| UNCERTAIN)?;
    bounds(&tx).await?;
    let current = lock_run(
        &tx,
        run.run_id(),
        run.specification_fingerprint(),
        run.admission_resolution_fingerprint(),
        run_lineage(run)?,
        Some(run.canonical_specification_payload()),
        false,
    )
    .await?
    .ok_or(LOST)?;
    let eligible = match target {
        RunState::Cancelled => current.status.state == RunState::CancelRequested,
        RunState::Failed => {
            current.status.state == RunState::Running
                && proof.attempts()
                    == crate::application::job_recovery::RetryBudget::finite_job().max_attempts()
        }
        _ => return Err(INVALID),
    };
    let key = RunLocator::new(
        crate::application::job_contract::JobKind::Research,
        run.run_id(),
    )
    .map_err(publication_error)?;
    if !eligible
        || !recheck_control_transaction(&tx, &roles, proof, &key, namespace, run.owner())
            .await
            .map_err(publication_error)?
    {
        tx.commit().await.map_err(|_| UNCERTAIN)?;
        return Ok(());
    }
    let failure = if target == RunState::Failed {
        Some(Failure::new(
            FailurePhase::Operational,
            "ATTEMPT_LIMIT_EXHAUSTED",
            "Finite recomputation exhausted its three original Run Attempts without a publication",
        )?)
    } else {
        None
    };
    let status = update_run(
        &tx,
        run.run_id(),
        &current,
        target,
        time(at)?,
        None,
        failure.as_ref(),
    )
    .await?;
    let expected_run = guarded_document(&tx, run.run_id(), None).await?;
    tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
        .await
        .map_err(|_| UNCERTAIN)?;
    guarded_run_readback(
        &tx,
        RunReadbackIdentity {
            id: run.run_id(),
            spec: run.specification_fingerprint(),
            admission: run.admission_resolution_fingerprint(),
            lineage: run_lineage(run)?,
            payload: run.canonical_specification_payload(),
        },
        &status,
        None,
        &expected_run,
    )
    .await?;
    verify_finite_unpublished(&tx, &roles, namespace, run, proof).await?;
    let checked=read_control_facts(&tx,&roles,|reader| async move {
        reader.query_one("SELECT COALESCE(max(attempt_number),0)::integer,count(*) FILTER(WHERE state='ACTIVE')::bigint FROM public.research_run_attempt WHERE run_id=$1::text::uuid",&[&run.run_id()]).await.map_err(|_|UNAVAILABLE)
    }).await.map_err(publication_error)??;
    if checked.get::<_, i32>(0) != proof.attempts() || checked.get::<_, i64>(1) != 0 {
        return Err(MISMATCH);
    }
    roles.verify_transaction(&tx).await.map_err(|_| UNCERTAIN)?;
    tx.commit().await.map_err(|_| UNCERTAIN)?;
    Ok(())
}
