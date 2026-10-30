//! Existing Research Run/Attempt operational authority. Semantic facts stay in immutable Stores.
mod source_history;
use crate::application::research_run::{
    InspectionOutcome, VerifiedCompletion, VerifiedInspection, VerifiedRun,
};
use onlyalpha_domain::time::OnlyUtcDateTime;
pub use source_history::validate_source_history_event;
use std::time::{Duration, SystemTime};
use tokio_postgres::{Client, Transaction};

type Result<T> = std::result::Result<T, &'static str>;
const UNAVAILABLE: &str = "RESEARCH_EXECUTION_STORE_UNAVAILABLE";
const LOST: &str = "RESEARCH_EXECUTION_OWNERSHIP_LOST";
const UNCERTAIN: &str = "RESEARCH_EXECUTION_OWNERSHIP_UNCERTAIN";
const INVALID: &str = "RESEARCH_EXECUTION_INPUT_INVALID";
const MISMATCH: &str = "RESEARCH_EXECUTION_PROOF_MISMATCH";

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
}
impl<'a> ResearchExecution<'a> {
    pub fn new(client: &'a mut Client) -> Self {
        Self { client }
    }
    pub async fn observe(&mut self, run: &VerifiedRun) -> Result<RunStatus> {
        let tx = self.client.transaction().await.map_err(|_| UNAVAILABLE)?;
        bounds(&tx).await?;
        let current = lock_run(
            &tx,
            run.run_id(),
            run.specification_fingerprint(),
            run.admission_resolution_fingerprint(),
            Some(run.canonical_specification_payload()),
            false,
        )
        .await?
        .ok_or(LOST)?;
        tx.commit().await.map_err(|_| UNAVAILABLE)?;
        Ok(current.status)
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
            Some(run.canonical_specification_payload()),
            true,
        )
        .await?
        else {
            tx.commit().await.map_err(|_| UNAVAILABLE)?;
            return Ok(None);
        };
        if !matches!(current.status.state, RunState::Queued | RunState::Running) {
            return Ok(None);
        }
        current.check_time(at)?;
        let row=tx.query_one("SELECT count(*)::bigint AS count, COALESCE(max(attempt_number),0)::integer AS number, count(*) FILTER(WHERE state='ACTIVE')::bigint AS active FROM research_run_attempt WHERE run_id=$1::text::uuid",&[&run.run_id()]).await.map_err(|_|UNAVAILABLE)?;
        let count: i64 = row.try_get("count").map_err(|_| MISMATCH)?;
        let active: i64 = row.try_get("active").map_err(|_| MISMATCH)?;
        let number: i32 = row.try_get("number").map_err(|_| MISMATCH)?;
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
            generation: run.runtime_generation_fingerprint().into(),
            certain: true,
        }))
    }
    pub async fn heartbeat(&mut self, claim: &mut Claim) -> Result<()> {
        let seconds = lease_seconds(Duration::from_secs(120))?;
        claim.certain = false;
        let tx = self.client.transaction().await.map_err(|_| UNCERTAIN)?;
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
        bounds(&tx).await?;
        let current = lock_claim_run(&tx, claim).await?;
        if !matches!(
            current.status.state,
            RunState::Running | RunState::CancelRequested
        ) {
            return Err(LOST);
        }
        current.check_time(at)?;
        let (attempt, target, completion, failure) = match outcome {
            Finalization::Complete(c) => ("SUCCEEDED", Some(RunState::Completed), Some(c), None),
            Finalization::Fail(f, r) => (
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
            Finalization::Cancel if current.status.state == RunState::CancelRequested => {
                ("CANCELLED", Some(RunState::Cancelled), None, None)
            }
            Finalization::Cancel => return Err(LOST),
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
        tx.commit().await.map_err(|_| UNCERTAIN)?;
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
        bounds(&tx).await?;
        let current = lock_run(
            &tx,
            inspection.run_id(),
            inspection.specification_fingerprint(),
            inspection.admission_resolution_fingerprint(),
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
        tx.commit().await.map_err(|_| UNAVAILABLE)?;
        Ok(status)
    }
}
enum Finalization<'a> {
    Complete(&'a VerifiedCompletion),
    Fail(&'a Failure, RetryDecision),
    Cancel,
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
async fn lock_claim_run(tx: &Transaction<'_>, claim: &Claim) -> Result<LockedRun> {
    lock_run(
        tx,
        &claim.run_id,
        &claim.specification,
        &claim.admission,
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
    payload: Option<&str>,
    skip: bool,
) -> Result<Option<LockedRun>> {
    let sql = if skip {
        "SELECT revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_fingerprint,origin_kind,authoring_provenance IS NULL AS native_authoring,queued_at,started_at,cancel_requested_at FROM research_run WHERE run_id=$1::text::uuid FOR UPDATE SKIP LOCKED"
    } else {
        "SELECT revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_fingerprint,origin_kind,authoring_provenance IS NULL AS native_authoring,queued_at,started_at,cancel_requested_at FROM research_run WHERE run_id=$1::text::uuid FOR UPDATE"
    };
    let Some(row) = tx.query_opt(sql, &[&id]).await.map_err(|_| UNAVAILABLE)? else {
        return Ok(None);
    };
    let schema: i32 = row
        .try_get("specification_schema_version")
        .map_err(|_| MISMATCH)?;
    let origin: String = row.try_get("origin_kind").map_err(|_| MISMATCH)?;
    let actual_spec: String = row
        .try_get("specification_fingerprint")
        .map_err(|_| MISMATCH)?;
    let actual_admission: String = row
        .try_get("admission_resolution_fingerprint")
        .map_err(|_| MISMATCH)?;
    let actual_payload: String = row.try_get("specification_payload").map_err(|_| MISMATCH)?;
    let native_authoring: bool = row.try_get("native_authoring").map_err(|_| MISMATCH)?;
    if schema != 4
        || origin != "GENERAL"
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
    let n=tx.execute("UPDATE research_run SET revision=$4,state=$5,started_at=$6,cancel_requested_at=$7,finished_at=$8,research_result_fingerprint=COALESCE($9,research_result_fingerprint),artifact_content_fingerprint=COALESCE($10,artifact_content_fingerprint),calculation_execution_evidence_fingerprints=COALESCE($11,calculation_execution_evidence_fingerprints),failure_phase=$12,failure_code=$13,failure_detail=$14 WHERE run_id=$1::text::uuid AND revision=$2 AND state=$3",&[&id,&current.status.revision,&current.status.state.as_str(),&revision,&target.as_str(),&start,&cancel,&finish,&result,&artifact,&evidence,&phase,&code,&detail]).await.map_err(|_|UNAVAILABLE)?;
    if n != 1 {
        return Err(LOST);
    }
    Ok(RunStatus {
        state: target,
        revision,
    })
}
