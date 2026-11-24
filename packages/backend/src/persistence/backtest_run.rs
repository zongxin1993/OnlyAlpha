//! Existing Backtest Run/Attempt tables and global Commands, on one guarded socket.
use crate::{
    application::{
        backtest_run::{
            self, CancelRequest, Context, CreateRequest, INVALID, Inputs, MISMATCH, Result,
            Specification, VerifiedRun, text,
        },
        command::{self, Admission, Binding, CommandKind, Outcome, OutcomeKind, Receipt},
        factor_content::hash,
    },
    bootstrap::deployment::{self, SemanticStoreId},
    persistence::{
        authority_session::AuthoritySession,
        postgres::{Commands, bounds, system_time},
    },
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_observability::{Correlation, Operation};
use serde_json::{Value, json};
use std::time::SystemTime;
use tokio_postgres::{Row, Transaction};
use tracing::Instrument;
const UNAVAILABLE: &str = "BACKTEST_RUN_STORE_UNAVAILABLE";
const PROOF_MISSING: &str = "BACKTEST_RUN_PROOF_MISSING";
const PROOF_CORRUPT: &str = "BACKTEST_RUN_PROOF_CORRUPT";
const UNCERTAIN: &str = "BACKTEST_RUN_OWNERSHIP_UNCERTAIN";
pub(crate) const LOST: &str = "BACKTEST_RUN_OWNERSHIP_LOST";
const CONFLICT: &str = "PRODUCT_COMMAND_CONFLICT";
fn db(_: impl std::fmt::Debug) -> &'static str {
    UNAVAILABLE
}
fn canonical(v: &Value) -> Result<String> {
    onlyalpha_metadata_json::canonical_json(&v.to_string(), 8 * 1024 * 1024).map_err(|_| INVALID)
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
            _ => Err(PROOF_CORRUPT),
        }
    }
    pub fn terminal(self) -> bool {
        matches!(self, Self::Completed | Self::Failed | Self::Cancelled)
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RunStatus {
    pub state: RunState,
    pub revision: i64,
}
/// Only this owning module can construct a verified immutable Run binding.
#[derive(Clone)]
pub(crate) struct RunBinding {
    run: String,
    specification: Specification,
    specification_fp: String,
    payload: String,
    resolution: Value,
    resolution_fp: String,
    namespace: SemanticStoreId,
    owner: String,
    generation: String,
    accepted: String,
    replayed: bool,
    status: RunStatus,
    started: bool,
    cancel_requested_at: Option<SystemTime>,
    pins: [Option<String>; 3],
}
impl RunBinding {
    pub(crate) fn state(&self) -> RunState {
        self.status.state
    }
    pub(crate) fn was_started(&self) -> bool {
        self.started
    }
    pub(crate) fn cancel_requested_at(&self) -> Option<SystemTime> {
        self.cancel_requested_at
    }
    pub(crate) fn completion_fingerprints(&self) -> Option<(&str, &str, &str)> {
        match (&self.pins[0], &self.pins[1], &self.pins[2]) {
            (Some(e), Some(r), Some(d)) => Some((e, r, d)),
            _ => None,
        }
    }
    pub(crate) fn run_id(&self) -> &str {
        &self.run
    }
    pub(crate) fn specification(&self) -> &Specification {
        &self.specification
    }
    pub(crate) fn specification_fingerprint(&self) -> &str {
        &self.specification_fp
    }
    pub(crate) fn admission_resolution_fingerprint(&self) -> &str {
        &self.resolution_fp
    }
    pub(crate) fn namespace(&self) -> &SemanticStoreId {
        &self.namespace
    }
    pub(crate) fn owner(&self) -> &str {
        &self.owner
    }
    pub(crate) fn resolution(&self) -> &Value {
        &self.resolution
    }
    pub(crate) fn canonical_specification_payload(&self) -> &str {
        &self.payload
    }
    pub(crate) fn runtime_generation_fingerprint(&self) -> &str {
        &self.generation
    }
    pub(crate) fn record(&self) -> Value {
        json!({"run_id":self.run,"specification":self.specification.record(),"specification_fingerprint":self.specification_fp,"admission_resolution_fingerprint":self.resolution_fp,"admission_resolution":self.resolution,"semantic_store_id":self.namespace.value(),"owner":self.owner,"accepted_at":self.accepted,"replayed":self.replayed})
    }
}
pub struct Claim {
    run: VerifiedRun,
    attempt: String,
    worker: String,
    number: i32,
    fence: i64,
    certain: bool,
}
impl Claim {
    pub fn run_id(&self) -> &str {
        self.run.run_id()
    }
    pub fn run(&self) -> &VerifiedRun {
        &self.run
    }
    pub fn attempt_id(&self) -> &str {
        &self.attempt
    }
    pub fn worker_instance_id(&self) -> &str {
        &self.worker
    }
    pub fn attempt_number(&self) -> i32 {
        self.number
    }
    pub fn fencing_token(&self) -> i64 {
        self.fence
    }
    pub fn ownership_certain(&self) -> bool {
        self.certain
    }
    pub fn runtime_generation_fingerprint(&self) -> &str {
        self.run.runtime_generation_fingerprint()
    }
}
struct Current {
    run: VerifiedRun,
    status: RunStatus,
    queued: SystemTime,
    started: Option<SystemTime>,
    cancel: Option<SystemTime>,
}
impl Current {
    fn matches(&self, run: &VerifiedRun) -> Result<()> {
        if self.run.run_id() != run.run_id()
            || self.run.specification_fingerprint() != run.specification_fingerprint()
            || self.run.admission_resolution_fingerprint() != run.admission_resolution_fingerprint()
            || self.run.canonical_specification_payload() != run.canonical_specification_payload()
            || self.run.namespace() != run.namespace()
            || self.run.resolution() != run.resolution()
        {
            return Err(MISMATCH);
        }
        Ok(())
    }
    fn check_time(&self, at: SystemTime) -> Result<()> {
        if at < self.queued
            || self.started.is_some_and(|t| at < t)
            || self.cancel.is_some_and(|t| at < t)
        {
            return Err(INVALID);
        }
        Ok(())
    }
}
const SELECT_RUN: &str = "SELECT run_id::text,revision,state,specification_schema_version,specification_fingerprint,specification_payload::text,admission_resolution_schema_version,admission_resolution_fingerprint,admission_resolution_payload::text,queued_at,started_at,cancel_requested_at,finished_at,evidence_fingerprint,result_fingerprint,determinism_fingerprint,failure_phase,failure_code,failure_detail FROM backtest_run WHERE run_id=$1::text::uuid";
async fn read_run(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    id: &str,
    lock: bool,
) -> Result<Option<Current>> {
    read_run_for_owner(tx, namespace, id, lock, None).await
}

async fn read_run_for_owner(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    id: &str,
    lock: bool,
    owner: Option<&str>,
) -> Result<Option<Current>> {
    deployment::verify_binding_in_transaction(tx, namespace)
        .await
        .map_err(|error| error.code())?;
    let mut query = SELECT_RUN.to_owned();
    if owner.is_some() {
        query.push_str(" AND admission_resolution_payload::jsonb->>'owner'=$2");
    }
    if lock {
        query.push_str(" FOR UPDATE");
    }
    let row = match owner {
        Some(owner) => tx.query_opt(&query, &[&id, &owner]).await,
        None => tx.query_opt(&query, &[&id]).await,
    };
    let Some(row) = row.map_err(|error| match error.code() {
        Some(&tokio_postgres::error::SqlState::INSUFFICIENT_PRIVILEGE) => "BACKTEST_RUN_STORE_DENIED",
        _ => UNAVAILABLE,
    })? else {
        return Ok(None);
    };
    let corrupt = |_| PROOF_CORRUPT;
    let specification_json: String = row.try_get("specification_payload").map_err(corrupt)?;
    let resolution_json: String = row.try_get("admission_resolution_payload").map_err(corrupt)?;
    let specification = Specification::from_record(
        &serde_json::from_str(&specification_json).map_err(|_| PROOF_CORRUPT)?,
    )
    .map_err(|_| PROOF_CORRUPT)?;
    let resolution: Value = serde_json::from_str(&resolution_json).map_err(|_| PROOF_CORRUPT)?;
    let spec_fp: String = row.try_get("specification_fingerprint").map_err(corrupt)?;
    let resolution_fp: String = row.try_get("admission_resolution_fingerprint").map_err(corrupt)?;
    if row.try_get::<_, i16>("specification_schema_version").map_err(corrupt)? != 3
        || row.try_get::<_, i16>("admission_resolution_schema_version").map_err(corrupt)? != 2
        || spec_fp != specification.fingerprint().map_err(|_| PROOF_CORRUPT)?
        || resolution_fp != hash(&resolution).map_err(|_| PROOF_CORRUPT)?
    {
        return Err(PROOF_CORRUPT);
    }
    backtest_run::validate_resolution(&specification, &resolution, namespace).map_err(|code| {
        if code == MISMATCH { MISMATCH } else { PROOF_CORRUPT }
    })?;
    if resolution["runtime_work_binding"]["work_id"] != id {
        return Err(MISMATCH);
    }
    let owner = text(&resolution, "owner")?.to_owned();
    let command = crate::application::command::CommandId::new(text(
        &resolution["runtime_work_binding"],
        "reason",
    )?)
    .map_err(|e| e.code())?;
    let request = CreateRequest::new(command.clone(), id, specification.clone())?;
    let expected = Admission::new(
        command.clone(),
        CommandKind::CreateBacktestRun,
        &request.fingerprint(&owner, &resolution_fp)?,
    )
    .map_err(|e| e.code())?;
    let receipt = match Commands::verify_binding_in_transaction(tx, &command)
        .await
        .map_err(|e| e.code())?
    {
        Binding::Accepted(r)
            if r.admission() == &expected
                && r.outcome().kind() == OutcomeKind::BacktestRun
                && r.outcome().id() == id =>
        {
            r
        }
        Binding::None | Binding::Admitted(_) => return Err(PROOF_MISSING),
        Binding::Accepted(_) => return Err(MISMATCH),
    };
    let queued: SystemTime = row.try_get("queued_at").map_err(corrupt)?;
    if system_time(receipt.accepted_at()).map_err(|_| PROOF_CORRUPT)? != queued {
        return Err(MISMATCH);
    }
    let state = RunState::parse(row.try_get::<_, &str>("state").map_err(corrupt)?)?;
    let revision: i64 = row.try_get("revision").map_err(corrupt)?;
    let started: Option<SystemTime> = row.try_get("started_at").map_err(corrupt)?;
    let cancel: Option<SystemTime> = row.try_get("cancel_requested_at").map_err(corrupt)?;
    validate_state(&row, state, revision, queued, started, cancel)?;
    let generation = text(&resolution, "runtime_generation_fingerprint")?.to_owned();
    let pins = [
        row.try_get("evidence_fingerprint").map_err(corrupt)?,
        row.try_get("result_fingerprint").map_err(corrupt)?,
        row.try_get("determinism_fingerprint").map_err(corrupt)?,
    ];
    Ok(Some(Current {
        run: VerifiedRun {
            binding: RunBinding {
                run: id.into(),
                payload: canonical(specification.record())?,
                specification,
                specification_fp: spec_fp,
                resolution,
                resolution_fp,
                namespace: namespace.clone(),
                owner,
                generation,
                accepted: receipt.accepted_at().to_string(),
                replayed: false,
                status: RunStatus { state, revision },
                started: started.is_some(),
                cancel_requested_at: cancel,
                pins,
            },
        },
        status: RunStatus { state, revision },
        queued,
        started,
        cancel,
    }))
}

/// Read projections retain the exact command/admission checks of the owning
/// loader and never acquire a mutation guard or create an execution claim.
pub(crate) async fn read_snapshot(
    client: &mut tokio_postgres::Client,
    namespace: &SemanticStoreId,
    id: &str,
    owner: Option<&str>,
) -> Result<(VerifiedRun, RunStatus)> {
    if !command::uuid4(id) {
        return Err(INVALID);
    }
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(db)?;
    bounds(&tx).await.map_err(db)?;
    let current = owned_snapshot(&tx, namespace, id, owner).await?;
    tx.commit().await.map_err(db)?;
    Ok((current.run, current.status))
}

async fn owned_snapshot(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    id: &str,
    owner: Option<&str>,
) -> Result<Current> {
    read_run_for_owner(tx, namespace, id, false, owner)
        .await?
        .ok_or("BACKTEST_RUN_NOT_FOUND")
}

pub(crate) async fn read_product_snapshot(
    client: &mut tokio_postgres::Client,
    namespace: &SemanticStoreId,
    id: &str,
    owner: &str,
) -> Result<(VerifiedRun, RunStatus, command::CommandId)> {
    if !command::uuid4(id) {
        return Err(INVALID);
    }
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(db)?;
    bounds(&tx).await.map_err(db)?;
    let current = owned_snapshot(&tx, namespace, id, Some(owner)).await?;
    let preparation = super::research_preparation::original_backtest_preparation(&tx, &current.run)
        .await?;
    tx.commit().await.map_err(db)?;
    Ok((current.run, current.status, preparation.command))
}

pub(crate) async fn recent_snapshots(
    client: &mut tokio_postgres::Client,
    namespace: &SemanticStoreId,
    owner: &str,
) -> Result<Vec<(VerifiedRun, RunStatus)>> {
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(db)?;
    bounds(&tx).await.map_err(db)?;
    deployment::verify_binding_in_transaction(&tx, namespace)
        .await
        .map_err(db)?;
    let rows=tx.query("SELECT run_id::text FROM backtest_run WHERE specification_schema_version=3 AND admission_resolution_payload::jsonb->>'owner'=$1 ORDER BY queued_at DESC,run_id DESC LIMIT 101",&[&owner]).await.map_err(db)?;
    if rows.len() > 100 {
        return Err("BACKTEST_RUN_HISTORY_BUDGET_EXCEEDED");
    }
    let mut result = Vec::with_capacity(rows.len());
    for row in rows {
        let id: String = row.try_get(0).map_err(db)?;
        let current = read_run(&tx, namespace, &id, false)
            .await?
            .ok_or(MISMATCH)?;
        if current.run.owner() != owner {
            return Err(MISMATCH);
        }
        result.push((current.run, current.status));
    }
    tx.commit().await.map_err(db)?;
    Ok(result)
}
fn validate_state(
    row: &Row,
    state: RunState,
    revision: i64,
    queued: SystemTime,
    started: Option<SystemTime>,
    cancel: Option<SystemTime>,
) -> Result<()> {
    let corrupt = |_| PROOF_CORRUPT;
    let finished: Option<SystemTime> = row.try_get("finished_at").map_err(corrupt)?;
    if revision < 0
        || state.terminal() != finished.is_some()
        || started.is_some_and(|t| t < queued)
        || cancel.is_some_and(|t| t < queued || started.is_some_and(|s| t < s))
        || finished.is_some_and(|t| {
            t < queued || started.is_some_and(|s| t < s) || cancel.is_some_and(|s| t < s)
        })
        || (state == RunState::CancelRequested) != (cancel.is_some() && finished.is_none())
    {
        return Err(PROOF_CORRUPT);
    }
    if (matches!(
        state,
        RunState::Running | RunState::CancelRequested | RunState::Completed | RunState::Failed
    ) || (state == RunState::Cancelled && started.is_some()))
        != started.is_some()
    {
        return Err(PROOF_CORRUPT);
    }
    if state == RunState::Queued && (revision != 0 || started.is_some() || cancel.is_some()) {
        return Err(PROOF_CORRUPT);
    }
    let mut pinned = 0;
    for field in [
        "evidence_fingerprint",
        "result_fingerprint",
        "determinism_fingerprint",
    ] {
        let value: Option<String> = row.try_get(field).map_err(corrupt)?;
        if let Some(value) = value {
            if !crate::is_sha256_hex(&value) {
                return Err(PROOF_CORRUPT);
            }
            pinned += 1;
        }
    }
    if (state == RunState::Completed && pinned != 3)
        || (state == RunState::Cancelled && pinned != 0 && (pinned != 3 || started.is_none()))
        || (!matches!(
            state,
            RunState::Completed | RunState::Failed | RunState::Cancelled
        ) && pinned != 0)
    {
        return Err(PROOF_CORRUPT);
    }
    for field in ["failure_phase", "failure_code", "failure_detail"] {
        let value: Option<String> = row.try_get(field).map_err(corrupt)?;
        if (state == RunState::Failed) != value.is_some() {
            return Err(PROOF_CORRUPT);
        }
    }
    Ok(())
}
fn publication_error(error:super::job_publication::PublicationError) -> &'static str {
    use super::job_publication::PublicationError as P;
    match error {
        P::OutcomeUnknown=>UNCERTAIN,
        P::Unavailable|P::Denied|P::OwnershipLost=>UNAVAILABLE,
        P::MissingEvidence=>"BACKTEST_PUBLICATION_MISSING_EVIDENCE",
        P::BudgetExceeded=>"BACKTEST_PUBLICATION_BUDGET_EXCEEDED",
        P::Integrity|P::Mismatch|P::Conflict=>MISMATCH,
    }
}
fn registration_error(error: super::job_publication::PublicationError) -> &'static str {
    use super::job_publication::PublicationError;
    match error {
        PublicationError::MissingEvidence => "BACKTEST_FROZEN_INPUT_BINDING_MISSING",
        PublicationError::BudgetExceeded => "BACKTEST_FROZEN_INPUT_BINDING_BUDGET_EXCEEDED",
        other => publication_error(other),
    }
}
async fn replay(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    request: &CreateRequest,
    owner: &str,
) -> Result<Option<VerifiedRun>> {
    match Commands::verify_binding_in_transaction(tx, request.command_id())
        .await
        .map_err(|e| e.code())?
    {
        Binding::None => Ok(None),
        Binding::Admitted(_) => Err(MISMATCH),
        Binding::Accepted(receipt) => {
            if receipt.admission().kind() != CommandKind::CreateBacktestRun
                || receipt.outcome().kind() != OutcomeKind::BacktestRun
                || receipt.outcome().id() != request.run_id()
            {
                return Err(CONFLICT);
            }
            let mut current = read_run(tx, namespace, request.run_id(), false)
                .await?
                .ok_or(MISMATCH)?;
            if current.run.owner() != owner
                || current.run.specification().record() != request.specification().record()
                || receipt.admission().fingerprint()
                    != request.fingerprint(owner, current.run.admission_resolution_fingerprint())?
            {
                return Err(CONFLICT);
            }
            current.run.binding.replayed = true;
            Ok(Some(current.run))
        }
    }
}
pub struct Backtests<'a> {
    session: &'a mut AuthoritySession,
    namespace: &'a SemanticStoreId,
}
impl<'a> Backtests<'a> {
    pub fn new(session: &'a mut AuthoritySession, namespace: &'a SemanticStoreId) -> Self {
        Self { session, namespace }
    }
    /// Restore the same socket only after a known result and a fresh lock proof.
    /// Cancellation drops the moved owner; uncertain commit never grants retry.
    async fn finish<T>(&mut self, mut owned: AuthoritySession, result: Result<T>) -> Result<T> {
        if result
            .as_ref()
            .err()
            .is_some_and(|e| matches!(*e, UNAVAILABLE | UNCERTAIN))
        {
            return result;
        }
        owned.verify().await.map_err(|e| e.code())?;
        self.session.restore_ownership(owned);
        result
    }
    pub async fn replay_create(
        &mut self,
        request: &CreateRequest,
        context: &Context<'_>,
    ) -> Result<Option<VerifiedRun>> {
        let owner = context.owner()?.to_owned();
        let mut owned = self.session.take_ownership();
        let result = async {
            let tx = owned
                .client_mut()
                .await
                .map_err(|e| e.code())?
                .transaction()
                .await
                .map_err(db)?;
            Commands::lock_command(&tx, request.command_id())
                .await
                .map_err(|e| e.code())?;
            let value = replay(&tx, self.namespace, request, &owner).await?;
            commit(tx).await?;
            Ok(value)
        }
        .await;
        self.finish(owned, result).await
    }
    #[cfg(test)]
    pub async fn create(
        &mut self,
        request: &CreateRequest,
        context: &Context<'_>,
        inputs: &Inputs<'_>,
        at: OnlyUtcDateTime,
    ) -> Result<VerifiedRun> {
        self.create_inner(request, context, inputs, None, at).await
    }
    pub(crate) async fn create_prepared(
        &mut self,
        request: &CreateRequest,
        context: &Context<'_>,
        inputs: &Inputs<'_>,
        operation: &crate::persistence::research_preparation::Operation,
        expected: &str,
        at: OnlyUtcDateTime,
    ) -> Result<VerifiedRun> {
        self.create_inner(request, context, inputs, Some((operation, expected)), at)
            .await
    }
    async fn create_inner(
        &mut self,
        request: &CreateRequest,
        context: &Context<'_>,
        inputs: &Inputs<'_>,
        preparation: Option<(&crate::persistence::research_preparation::Operation, &str)>,
        at: OnlyUtcDateTime,
    ) -> Result<VerifiedRun> {
        let owner = context.owner()?.to_owned();
        let mut owned = self.session.take_ownership();
        let roles=owned.control_roles().map_err(|e|e.code())?;
        let result=async {
            let tx=owned.client_mut().await.map_err(|e|e.code())?.transaction().await.map_err(db)?;
            Commands::lock_command(&tx,request.command_id()).await.map_err(|e|e.code())?;
            if let Some(run)=replay(&tx,self.namespace,request,&owner).await? {
                if preparation.is_some() {
                    let key = super::job_publication::RunLocator::new(crate::application::job_contract::JobKind::Backtest,run.run_id()).map_err(|_|MISMATCH)?;
                    super::job_publication::verify_registered_control_transaction(&tx,&roles,self.namespace,&owner,&key,run.specification_fingerprint(),run.admission_resolution_fingerprint()).await.map_err(registration_error)?;
                }
                commit(tx).await?; return Ok(run);
            }
            context.source()?;
            inputs.verify_transaction(&crate::persistence::build_fact_read::BuildFactRead::control(&tx,&roles),self.namespace).await?;
            if let Some((operation,expected))=preparation {
                if !operation.request.is_backtest() || operation.request.future_command()!=request.command_id().value()
                    || operation.request.reserved_run_id()!=request.run_id() || operation.outputs["ready"]["specification"]!=*request.specification().record() {return Err(MISMATCH);}
                crate::persistence::research_preparation::guard_submission(&tx,operation,expected).await?;
            }
            if inputs.namespace()!=self.namespace || inputs.specification().record()!=request.specification().record() {return Err(MISMATCH);}
            let resolution=inputs.resolve(&owner,context.selection)?;
            if resolution["runtime_work_binding"]["work_id"]!=request.run_id() || resolution["runtime_work_binding"]["reason"]!=request.command_id().value() {return Err(MISMATCH);}
            deployment::verify_binding_in_transaction(&tx,self.namespace).await.map_err(db)?;
            if tx.query_opt("SELECT run_id FROM backtest_run WHERE run_id=$1::text::uuid FOR UPDATE",&[&request.run_id()]).await.map_err(db)?.is_some() {return Err(CONFLICT);}
            let resolution_fp=hash(&resolution)?; let spec_fp=request.specification().fingerprint()?;
            let admission=Admission::new(request.command_id().clone(),CommandKind::CreateBacktestRun,&request.fingerprint(&owner,&resolution_fp)?).map_err(|e|e.code())?;
            Commands::admit_exact_in_transaction(&tx,&admission).await.map_err(|e|e.code())?;
            let payload=canonical(request.specification().record())?; let resolution_payload=canonical(&resolution)?; let at_db=system_time(at).map_err(db)?;
            let n=tx.execute("INSERT INTO backtest_run(run_id,revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_schema_version,admission_resolution_fingerprint,admission_resolution_payload,queued_at) VALUES($1::text::uuid,0,'QUEUED',3,$2,$3::text::jsonb,2,$4,$5::text::jsonb,$6)",&[&request.run_id(),&spec_fp,&payload,&resolution_fp,&resolution_payload,&at_db]).await.map_err(db)?;
            if n!=1{return Err(MISMATCH);}
            let receipt=Receipt::new(admission,Outcome::new(OutcomeKind::BacktestRun,request.run_id()).map_err(|e|e.code())?,&at.to_string()).map_err(|e|e.code())?;
            Commands::put_verified_receipt_in_transaction(&tx,&receipt).await.map_err(|e|e.code())?;
            flush_deferred(&tx).await?;
            let created=read_run(&tx,self.namespace,request.run_id(),false).await?.ok_or(MISMATCH)?;
            if created.status!=(RunStatus{state:RunState::Queued,revision:0}) || created.run.specification_fingerprint()!=spec_fp || created.run.admission_resolution_fingerprint()!=resolution_fp || created.run.resolution()!=&resolution {return Err(MISMATCH);}
            verify_receipt(&tx,&receipt).await?;
            let verified=created.run;
            context.source()?;
            inputs.verify_transaction(&crate::persistence::build_fact_read::BuildFactRead::control(&tx,&roles),self.namespace).await?;
            if let Some((operation,expected))=preparation {
                crate::persistence::research_preparation::guard_submission(&tx,operation,expected).await?;
            }
            if preparation.is_some() {
                let registration = super::job_publication::FrozenBindingRegistration::from_backtest(&crate::persistence::build_fact_read::BuildFactRead::control(&tx,&roles),inputs,request,context).await.map_err(registration_error)?;
                super::job_publication::register_control_transaction(&tx,&roles,self.namespace,&owner,&registration).await.map_err(registration_error)?;
            }
            commit(tx).await?;
            tracing::info!(target:"onlyalpha.observability",event_kind="summary",module="backend",operation="backtest.run.queued",run_id=verified.run_id(),command_id=request.command_id().value(),outcome="queued");
            post_commit(&mut owned,self.namespace,&verified,Some(RunStatus{state:RunState::Queued,revision:0})).await?; Ok(verified)
        }.await;
        self.finish(owned, result).await
    }
    pub async fn load(&mut self, id: &str) -> Result<VerifiedRun> {
        if !command::uuid4(id) {
            return Err(INVALID);
        }
        let mut owned = self.session.take_ownership();
        let result = async {
            let tx = owned
                .client_mut()
                .await
                .map_err(|e| e.code())?
                .transaction()
                .await
                .map_err(db)?;
            bounds(&tx).await.map_err(db)?;
            let run = read_run(&tx, self.namespace, id, false)
                .await?
                .ok_or(LOST)?
                .run;
            commit(tx).await?;
            Ok(run)
        }
        .await;
        self.finish(owned, result).await
    }
    pub async fn observe(&mut self, run: &VerifiedRun) -> Result<RunStatus> {
        let mut owned = self.session.take_ownership();
        let result = async {
            let tx = owned
                .client_mut()
                .await
                .map_err(|e| e.code())?
                .transaction()
                .await
                .map_err(db)?;
            bounds(&tx).await.map_err(db)?;
            let current = read_run(&tx, self.namespace, run.run_id(), false)
                .await?
                .ok_or(LOST)?;
            current.matches(run)?;
            commit(tx).await?;
            Ok(current.status)
        }
        .await;
        self.finish(owned, result).await
    }
    pub async fn request_cancel(
        &mut self,
        request: &CancelRequest,
        context: &Context<'_>,
        at: OnlyUtcDateTime,
    ) -> Result<Receipt> {
        let owner = context.owner()?.to_owned();
        let mut owned = self.session.take_ownership();
        let result = async {
            let tx = owned
                .client_mut()
                .await
                .map_err(|e| e.code())?
                .transaction()
                .await
                .map_err(db)?;
            Commands::lock_command(&tx, request.command_id())
                .await
                .map_err(|e| e.code())?;
            let admission = Admission::new(
                request.command_id().clone(),
                CommandKind::CancelBacktestRun,
                &request.fingerprint(&owner)?,
            )
            .map_err(|e| e.code())?;
            match Commands::verify_binding_in_transaction(&tx, request.command_id())
                .await
                .map_err(|e| e.code())?
            {
                Binding::Accepted(r) => {
                    if r.admission() != &admission
                        || r.outcome().kind() != OutcomeKind::BacktestRun
                        || r.outcome().id() != request.run_id()
                    {
                        return Err(CONFLICT);
                    }
                    let run = read_run(&tx, self.namespace, request.run_id(), false)
                        .await?
                        .ok_or(MISMATCH)?;
                    if run.run.owner() != owner {
                        return Err(CONFLICT);
                    }
                    commit(tx).await?;
                    return Ok(r);
                }
                Binding::Admitted(_) => return Err(MISMATCH),
                Binding::None => {}
            }
            let current = read_run(&tx, self.namespace, request.run_id(), true)
                .await?
                .ok_or(LOST)?;
            if current.run.owner() != owner {
                return Err("BACKTEST_HUMAN_AUTHORIZATION_REQUIRED");
            }
            let at_db = system_time(at).map_err(db)?;
            current.check_time(at_db)?;
            Commands::admit_exact_in_transaction(&tx, &admission)
                .await
                .map_err(|e| e.code())?;
            let expected = match current.status.state {
                RunState::Queued => {
                    transition(&tx, &current, RunState::Cancelled, at_db).await?
                }
                RunState::Running => {
                    transition(&tx, &current, RunState::CancelRequested, at_db).await?
                }
                _ => current.status,
            };
            let receipt = Receipt::new(
                admission,
                Outcome::new(OutcomeKind::BacktestRun, request.run_id()).map_err(|e| e.code())?,
                &at.to_string(),
            )
            .map_err(|e| e.code())?;
            Commands::put_verified_receipt_in_transaction(&tx, &receipt)
                .await
                .map_err(|e| e.code())?;
            flush_deferred(&tx).await?;
            verify_current(&tx, self.namespace, &current.run, Some(expected)).await?;
            verify_receipt(&tx, &receipt).await?;
            context.owner()?;
            commit(tx).await?;
            post_commit(&mut owned, self.namespace, &current.run, Some(expected)).await?;
            let observed = Commands::new(owned.client_mut().await.map_err(|_| UNCERTAIN)?)
                .load_verified_receipt(request.command_id())
                .await
                .map_err(|_| UNCERTAIN)?;
            if observed.as_ref() != Some(&receipt) {
                return Err(UNCERTAIN);
            }
            Ok(receipt)
        }
        .await;
        self.finish(owned, result).await
    }
    pub async fn claim_recompute(
        &mut self,
        run: &VerifiedRun,
        observation: &super::job_publication::ConfirmedUnpublished,
        worker: &str,
        attempt: &str,
        at: OnlyUtcDateTime,
    ) -> Result<Option<Claim>> {
        if !command::uuid4(worker) || !command::uuid4(attempt) {
            return Err(INVALID);
        }
        let mut owned = self.session.take_ownership();
        let roles=owned.control_roles().map_err(|e|e.code())?;
        let result=async {
            let tx=owned.client_mut().await.map_err(|e|e.code())?.transaction().await.map_err(db)?;bounds(&tx).await.map_err(db)?;
            let current=read_run(&tx,self.namespace,run.run_id(),true).await?.ok_or(LOST)?;current.matches(run)?;
            if !matches!(current.status.state, RunState::Queued | RunState::Running) {
                commit(tx).await?;
                return Ok(None);
            }
            let key = super::job_publication::RunLocator::new(
                crate::application::job_contract::JobKind::Backtest,
                run.run_id(),
            ).map_err(|_| MISMATCH)?;
            if !super::job_publication::recheck_control_transaction(
                &tx, &roles, observation, &key, self.namespace, run.owner(),
            ).await.map_err(publication_error)? {
                commit(tx).await?;
                return Ok(None);
            }
            let at_db=system_time(at).map_err(db)?;current.check_time(at_db)?;
            let previous = observation.attempts();
            if previous >= crate::application::job_recovery::RetryBudget::finite_job().max_attempts() {
                commit(tx).await?;
                return Ok(None);
            }
            let number=previous.checked_add(1).ok_or(MISMATCH)?;
            let fence = i64::from(number);
            let expected = if current.status.state == RunState::Queued {
                transition(&tx, &current, RunState::Running, at_db).await?
            } else {
                current.status
            };
            if tx.execute(
                "UPDATE public.backtest_run SET last_attempt_number=$3 WHERE run_id=$1::text::uuid AND last_attempt_number=$2",
                &[&run.run_id(), &previous, &number],
            ).await.map_err(db)? != 1 {
                return Err(MISMATCH);
            }
            let n=tx.execute("WITH lease AS MATERIALIZED (SELECT clock_timestamp() AS now) INSERT INTO backtest_run_attempt(attempt_id,run_id,attempt_number,state,worker_instance_id,fencing_token,claimed_at,last_heartbeat_at,lease_expires_at) SELECT $1::text::uuid,$2::text::uuid,$3,'ACTIVE',$4::text::uuid,$5,lease.now,lease.now,lease.now+interval '120 seconds' FROM lease",&[&attempt,&run.run_id(),&number,&worker,&fence]).await.map_err(db)?;
            if n!=1{return Err(MISMATCH);}
            flush_deferred(&tx).await?;
            if super::job_publication::backtest_attempt_history(&tx, run.run_id(), false).await.map_err(publication_error)? != (number, 1) {
                return Err(MISMATCH);
            }
            verify_current(&tx,self.namespace,run,Some(expected)).await?;
            verify_attempt(&tx,run.run_id(),attempt,worker,number,fence,"ACTIVE",true).await?;
            commit(tx).await?;
            post_commit(&mut owned,self.namespace,run,Some(expected)).await?;
            let claim=Claim{run:run.clone(),attempt:attempt.into(),worker:worker.into(),number,fence,certain:true};
            post_claim(&mut owned,&claim,"ACTIVE",true).await?;
            Ok(Some(claim))
        }.await;
        self.finish(owned, result).await
    }
    pub(crate) async fn observe_publication(
        &mut self,
        run: &VerifiedRun,
    ) -> Result<super::job_publication::PublicationObservation> {
        use crate::application::job_contract::JobKind;
        use super::job_publication::{PublicationObservation, PublicationRepository, RunLocator};

        let key = RunLocator::new(JobKind::Backtest, run.run_id()).map_err(publication_error)?;
        let observed = PublicationRepository::observe_guarded(self.session, self.namespace, run.owner(), &key)
            .await.map_err(publication_error)?;
        if let PublicationObservation::Published(result) = &observed {
            if result.specification_fingerprint() != run.specification_fingerprint()
                || result.admission_fingerprint() != run.admission_resolution_fingerprint()
            {
                return Err(MISMATCH);
            }
        }
        Ok(observed)
    }

    pub(crate) async fn finish_aborted(
        &mut self,
        claim: &mut Claim,
        proof: &crate::application::finite_job::AbortedPreparation,
        error: &'static str,
    ) -> Result<RunStatus> {
        proof.verify_attempt(&super::job_publication::AttemptClaim::from_backtest(claim))
            .map_err(|_| MISMATCH)?;
        self.finish_claimed_unpublished(claim, proof.binding(), Some(("ADMISSION", error))).await
    }

    pub(crate) async fn finish_drained(
        &mut self,
        claim: &mut Claim,
        proof: &crate::application::finite_job::DrainedFiniteJob,
        error: Option<&'static str>,
    ) -> Result<RunStatus> {
        proof.verify_attempt(&super::job_publication::AttemptClaim::from_backtest(claim))
            .map_err(|error| error.code())?;
        self.finish_claimed_unpublished(claim, proof.binding(), error.map(|code| ("EXECUTION", code))).await
    }

    async fn finish_claimed_unpublished(
        &mut self,
        claim: &mut Claim,
        binding: &crate::application::job_contract::FrozenJobBinding,
        failure: Option<(&str, &str)>,
    ) -> Result<RunStatus> {
        use crate::application::job_contract::JobKind;
        use super::job_publication::verify_unpublished_control_transaction;

        if !claim.certain {
            return Err(UNCERTAIN);
        }
        let run = &claim.run;
        if binding.kind() != JobKind::Backtest || binding.run_id() != run.run_id()
            || binding.owner() != run.owner() || binding.namespace() != self.namespace.value()
        {
            return Err(MISMATCH);
        }
        claim.certain = false;
        let mut owned = self.session.take_ownership();
        let roles = owned.control_roles().map_err(|e| e.code())?;
        let result = async {
            let tx = owned.client_mut().await.map_err(|_| UNCERTAIN)?.transaction().await.map_err(db)?;
            bounds(&tx).await.map_err(db)?;
            let current = read_run(&tx, self.namespace, run.run_id(), true).await?.ok_or(LOST)?;
            current.matches(run)?;
            let (target, phase, code, detail) = match (current.status.state, failure) {
                (RunState::CancelRequested, _) => (RunState::Cancelled, None, None, None),
                (RunState::Running, Some((phase, code))) => (
                    RunState::Failed, Some(phase), Some(code), Some("Finite Backtest work ended before publication"),
                ),
                _ => return Err(LOST),
            };
            verify_unpublished_control_transaction(&tx, &roles, self.namespace, binding,
                run.specification_fingerprint(), run.admission_resolution_fingerprint()).await.map_err(publication_error)?;
            let at_db: SystemTime = tx.query_one("SELECT clock_timestamp()", &[]).await.map_err(db)?.try_get(0).map_err(db)?;
            current.check_time(at_db)?;
            let changed = tx.execute(
                "UPDATE public.backtest_run_attempt SET state=$6,finished_at=$9,failure_code=$7,failure_detail=$8 WHERE run_id=$1::text::uuid AND attempt_id=$2::text::uuid AND worker_instance_id=$3::text::uuid AND attempt_number=$4 AND fencing_token=$5 AND state='ACTIVE' AND lease_expires_at>clock_timestamp()",
                &[&run.run_id(), &claim.attempt, &claim.worker, &claim.number, &claim.fence, &target.as_str(), &code, &detail, &at_db],
            ).await.map_err(db)?;
            if changed != 1 {
                return Err(LOST);
            }
            let revision = current.status.revision.checked_add(1).ok_or(MISMATCH)?;
            let changed = tx.execute(
                "UPDATE public.backtest_run SET state=$4,revision=$3,finished_at=$5,failure_phase=$6,failure_code=$7,failure_detail=$8 WHERE run_id=$1::text::uuid AND revision=$2",
                &[&run.run_id(), &current.status.revision, &revision, &target.as_str(), &at_db, &phase, &code, &detail],
            ).await.map_err(db)?;
            if changed != 1 {
                return Err(LOST);
            }
            let status = RunStatus { state: target, revision };
            flush_deferred(&tx).await?;
            verify_current(&tx, self.namespace, run, Some(status)).await?;
            verify_attempt(&tx, run.run_id(), &claim.attempt, &claim.worker, claim.number, claim.fence, target.as_str(), false).await?;
            verify_unpublished_control_transaction(&tx, &roles, self.namespace, binding,
                run.specification_fingerprint(), run.admission_resolution_fingerprint()).await.map_err(publication_error)?;
            commit(tx).await.map_err(|_| UNCERTAIN)?;
            post_commit(&mut owned, self.namespace, run, Some(status)).await?;
            post_claim(&mut owned, claim, target.as_str(), false).await?;
            Ok(status)
        }.await;
        self.finish(owned, result).await
    }

    /// Settle only an original Run with a current, locked absence proof and no
    /// active owner. Source access and a replacement Attempt are unnecessary.
    pub(crate) async fn finish_cancelled_unpublished(
        &mut self, run: &VerifiedRun, proof: &super::job_publication::ConfirmedUnpublished,
        at: OnlyUtcDateTime,
    ) -> Result<Option<RunStatus>> {
        self.finish_unpublished(run, proof, RunState::Cancelled, at).await
    }
    pub(crate) async fn finish_exhausted(
        &mut self, run: &VerifiedRun, proof: &super::job_publication::ConfirmedUnpublished,
        at: OnlyUtcDateTime,
    ) -> Result<Option<RunStatus>> {
        self.finish_unpublished(run, proof, RunState::Failed, at).await
    }
    async fn finish_unpublished(
        &mut self, run: &VerifiedRun, proof: &super::job_publication::ConfirmedUnpublished,
        target: RunState, at: OnlyUtcDateTime,
    ) -> Result<Option<RunStatus>> {
        let mut owned = self.session.take_ownership();
        let roles = owned.control_roles().map_err(|e|e.code())?;
        let result = async {
            let tx = owned.client_mut().await.map_err(|e|e.code())?.transaction().await.map_err(db)?;
            bounds(&tx).await.map_err(db)?;
            let current = read_run(&tx,self.namespace,run.run_id(),true).await?.ok_or(LOST)?;
            current.matches(run)?;
            let eligible = match target {
                RunState::Cancelled => current.status.state == RunState::CancelRequested,
                RunState::Failed => current.status.state == RunState::Running
                    && proof.attempts() == crate::application::job_recovery::RetryBudget::finite_job().max_attempts(),
                _ => return Err(INVALID),
            };
            let key = super::job_publication::RunLocator::new(crate::application::job_contract::JobKind::Backtest,run.run_id()).map_err(publication_error)?;
            if !eligible || !super::job_publication::recheck_control_transaction(&tx,&roles,proof,&key,self.namespace,run.owner()).await.map_err(publication_error)? {
                commit(tx).await?;
                return Ok(None);
            }
            let at_db = system_time(at).map_err(db)?;
            current.check_time(at_db)?;
            let status = if target == RunState::Cancelled {
                transition(&tx,&current,target,at_db).await?
            } else {
                let revision = current.status.revision.checked_add(1).ok_or(MISMATCH)?;
                let changed = tx.execute("UPDATE backtest_run SET state='FAILED',revision=$3,finished_at=$4,failure_phase='OPERATIONAL',failure_code='BACKTEST_ATTEMPTS_EXHAUSTED',failure_detail='Finite recomputation exhausted its three original Run Attempts without a publication' WHERE run_id=$1::text::uuid AND revision=$2 AND state='RUNNING'",&[&run.run_id(),&current.status.revision,&revision,&at_db]).await.map_err(db)?;
                if changed != 1 { return Err(LOST); }
                RunStatus { state: target, revision }
            };
            flush_deferred(&tx).await?;
            verify_current(&tx,self.namespace,run,Some(status)).await?;
            if super::job_publication::backtest_attempt_history(&tx, run.run_id(), false).await.map_err(publication_error)? != (proof.attempts(), 0) {
                return Err(MISMATCH);
            }
            let checked = super::job_publication::read_control_facts(&tx,&roles,|facts| async move {
                facts.query_one("SELECT evidence_fingerprint IS NULL AND result_fingerprint IS NULL AND determinism_fingerprint IS NULL,NOT EXISTS(SELECT 1 FROM public.job_publication p WHERE p.job_kind='BACKTEST' AND p.run_id=r.run_id),NOT EXISTS(SELECT 1 FROM public.job_result_member m WHERE m.job_kind='BACKTEST' AND m.run_id=r.run_id),failure_phase,failure_code,failure_detail FROM public.backtest_run r WHERE run_id=$1::text::uuid",&[&run.run_id()]).await.map_err(db)
            }).await.map_err(publication_error)??;
            if !checked.get::<_,bool>(0) || !checked.get::<_,bool>(1) || !checked.get::<_,bool>(2)
                || (target == RunState::Failed && (checked.get::<_,Option<String>>(3).as_deref()!=Some("OPERATIONAL")
                    || checked.get::<_,Option<String>>(4).as_deref()!=Some("BACKTEST_ATTEMPTS_EXHAUSTED")
                    || checked.get::<_,Option<String>>(5).as_deref()!=Some("Finite recomputation exhausted its three original Run Attempts without a publication"))) { return Err(MISMATCH); }
            commit(tx).await.map_err(|_|UNCERTAIN)?;
            post_commit(&mut owned,self.namespace,run,Some(status)).await?;
            Ok(Some(status))
        }.await;
        self.finish(owned,result).await
    }
    pub async fn heartbeat(&mut self, claim: &mut Claim) -> Result<Option<RunStatus>> {
        claim.certain = false;
        let mut owned = self.session.take_ownership();
        let result = async {
            let tx = owned.client_mut().await.map_err(|e| e.code())?
                .transaction().await.map_err(|_| UNCERTAIN)?;
            bounds(&tx).await.map_err(|_| UNCERTAIN)?;
            let current = read_run(&tx, self.namespace, claim.run_id(), true).await?.ok_or(LOST)?;
            current.matches(&claim.run)?;
            let active_run = matches!(current.status.state, RunState::Running | RunState::CancelRequested);
            let identity: [&(dyn tokio_postgres::types::ToSql + Sync); 5] =
                [&claim.run_id(), &claim.attempt, &claim.worker, &claim.number, &claim.fence];
            let renewed = active_run && tx.execute(
                "WITH lease AS MATERIALIZED (SELECT clock_timestamp() AS now) UPDATE backtest_run_attempt a SET last_heartbeat_at=lease.now,lease_expires_at=lease.now+interval '120 seconds' FROM lease WHERE a.run_id=$1::text::uuid AND a.attempt_id=$2::text::uuid AND a.worker_instance_id=$3::text::uuid AND a.attempt_number=$4 AND a.fencing_token=$5 AND a.state='ACTIVE' AND a.lease_expires_at>lease.now",
                &identity,
            ).await.map_err(|_| UNCERTAIN)? == 1;
            if !renewed {
                if !attempt_is_expired(&tx, claim, active_run).await? {
                    return Err(MISMATCH);
                }
                commit(tx).await?;
                return Ok(None);
            }
            flush_deferred(&tx).await?;
            verify_current(&tx, self.namespace, &claim.run, Some(current.status)).await?;
            verify_attempt(&tx, claim.run_id(), &claim.attempt, &claim.worker, claim.number, claim.fence, "ACTIVE", true).await?;
            commit(tx).await.map_err(|_| UNCERTAIN)?;
            post_commit(&mut owned, self.namespace, &claim.run, Some(current.status)).await?;
            post_claim(&mut owned, claim, "ACTIVE", true).await?;
            Ok(Some(current.status))
        }.await;
        let value = self.finish(owned, result).await;
        claim.certain = matches!(value, Ok(Some(_)));
        value
    }
    pub(crate) async fn confirm_attempt_expired(&mut self, claim: &Claim) -> Result<bool> {
        let mut owned = self.session.take_ownership();
        let result = async {
            let tx = owned.client_mut().await.map_err(|error| error.code())?
                .transaction().await.map_err(db)?;
            bounds(&tx).await.map_err(db)?;
            let current = read_run(&tx, self.namespace, claim.run_id(), true).await?.ok_or(MISMATCH)?;
            current.matches(&claim.run)?;
            let active_run = matches!(current.status.state, RunState::Running | RunState::CancelRequested);
            let expired = attempt_is_expired(&tx, claim, active_run).await?;
            commit(tx).await?;
            Ok(expired)
        }.await;
        self.finish(owned, result).await
    }
    /// Expiry relinquishes the original execution right. Publication is observed separately.
    pub async fn expire(
        &mut self,
        run: &VerifiedRun,
        at: OnlyUtcDateTime,
    ) -> Result<Option<RunStatus>> {
        let mut owned = self.session.take_ownership();
        let result=async {
            let tx=owned.client_mut().await.map_err(|e|e.code())?.transaction().await.map_err(db)?;bounds(&tx).await.map_err(db)?;
            let current=read_run(&tx,self.namespace,run.run_id(),true).await?.ok_or(LOST)?;current.matches(run)?;
            current.check_time(system_time(at).map_err(db)?)?;
            if !matches!(current.status.state,RunState::Running|RunState::CancelRequested){commit(tx).await?;return Ok(None);}
            let Some(row)=tx.query_opt("SELECT attempt_id::text,worker_instance_id::text,attempt_number,fencing_token FROM backtest_run_attempt WHERE run_id=$1::text::uuid AND state='ACTIVE' AND lease_expires_at<=clock_timestamp() FOR UPDATE",&[&run.run_id()]).await.map_err(db)? else {commit(tx).await?;return Ok(None);};
            let attempt:String=row.try_get("attempt_id").map_err(db)?;
            let worker:String=row.try_get("worker_instance_id").map_err(db)?;
            let number:i32=row.try_get("attempt_number").map_err(db)?;
            let fence:i64=row.try_get("fencing_token").map_err(db)?;
            let n=tx.execute("WITH lease AS MATERIALIZED (SELECT clock_timestamp() AS now) UPDATE backtest_run_attempt a SET state='EXPIRED',finished_at=lease.now,failure_code='LEASE_EXPIRED',failure_detail='Attempt lease expired before operational finalization' FROM lease WHERE a.run_id=$1::text::uuid AND a.attempt_id=$2::text::uuid AND a.worker_instance_id=$3::text::uuid AND a.attempt_number=$4 AND a.fencing_token=$5 AND a.state='ACTIVE' AND a.lease_expires_at<=lease.now",&[&run.run_id(),&attempt,&worker,&number,&fence]).await.map_err(db)?;
            if n!=1{return Err(LOST);}
            flush_deferred(&tx).await?;
            verify_current(&tx,self.namespace,run,Some(current.status)).await?;
            verify_attempt(&tx,run.run_id(),&attempt,&worker,number,fence,"EXPIRED",false).await?;
            commit(tx).await?;
            post_commit(&mut owned,self.namespace,run,Some(current.status)).await?;Ok(Some(current.status))
        }.await;
        self.finish(owned, result).await
    }
}
async fn transition(
    tx: &Transaction<'_>,
    current: &Current,
    target: RunState,
    at: SystemTime,
) -> Result<RunStatus> {
    let revision = current.status.revision.checked_add(1).ok_or(MISMATCH)?;
    let started = if target == RunState::Running {
        Some(at)
    } else {
        current.started
    };
    let cancel = if target == RunState::CancelRequested
        || (current.status.state == RunState::Queued && target == RunState::Cancelled)
    {
        Some(at)
    } else {
        current.cancel
    };
    let finished = if target.terminal() { Some(at) } else { None };
    let n = tx.execute("UPDATE backtest_run SET state=$4,revision=$5,started_at=$6,cancel_requested_at=$7,finished_at=$8 WHERE run_id=$1::text::uuid AND revision=$2 AND state=$3",&[&current.run.run_id(),&current.status.revision,&current.status.state.as_str(),&target.as_str(),&revision,&started,&cancel,&finished]).await.map_err(db)?;
    if n != 1 {
        return Err(LOST);
    }
    Ok(RunStatus {
        state: target,
        revision,
    })
}

/// The shared owner proves the guard in this transaction, after all writes and
/// before commit. It never acquires another socket or another lock authority.
async fn commit(tx: Transaction<'_>) -> Result<()> {
    let verify = Operation::start("backend", "sql.authority.verify", Correlation::default());
    let verified = AuthoritySession::verify_transaction(&tx)
        .instrument(verify.span().clone())
        .await
        .map_err(|e| e.code());
    verify.finish(if verified.is_ok() { "ok" } else { "failed" }, 1, 0);
    verified?;
    let operation = Operation::start("backend", "sql.commit", Correlation::default());
    let committed = tx
        .commit()
        .instrument(operation.span().clone())
        .await
        .map_err(db);
    operation.finish(if committed.is_ok() { "ok" } else { "failed" }, 1, 0);
    committed
}

/// Acknowledged commit alone does not certify deferred projection effects.
async fn post_commit(
    owned: &mut AuthoritySession,
    namespace: &SemanticStoreId,
    expected: &VerifiedRun,
    status: Option<RunStatus>,
) -> Result<()> {
    let tx = owned
        .client_mut()
        .await
        .map_err(|_| UNCERTAIN)?
        .transaction()
        .await
        .map_err(|_| UNCERTAIN)?;
    let current = read_run(&tx, namespace, expected.run_id(), false)
        .await
        .map_err(|_| UNCERTAIN)?
        .ok_or(UNCERTAIN)?;
    current.matches(expected).map_err(|_| UNCERTAIN)?;
    if status.is_some_and(|s| s != current.status) {
        return Err(UNCERTAIN);
    }
    commit(tx).await.map_err(|_| UNCERTAIN)
}
async fn attempt_is_expired(tx: &Transaction<'_>, claim: &Claim, active_run: bool) -> Result<bool> {
    let row = tx.query_opt(
        "SELECT (state='EXPIRED' AND finished_at>=lease_expires_at AND failure_code='LEASE_EXPIRED') OR ($6 AND state='ACTIVE' AND finished_at IS NULL AND failure_code IS NULL AND lease_expires_at<=clock_timestamp()) FROM public.backtest_run_attempt WHERE run_id=$1::text::uuid AND attempt_id=$2::text::uuid AND worker_instance_id=$3::text::uuid AND attempt_number=$4 AND fencing_token=$5",
        &[&claim.run_id(), &claim.attempt, &claim.worker, &claim.number, &claim.fence, &active_run],
    ).await.map_err(db)?.ok_or(MISMATCH)?;
    Ok(row.try_get::<_, Option<bool>>(0).map_err(db)? == Some(true))
}

async fn post_claim(
    owned: &mut AuthoritySession,
    claim: &Claim,
    state: &str,
    active: bool,
) -> Result<()> {
    let client = owned.client_mut().await.map_err(|_| UNCERTAIN)?;
    let row=client.query_opt("SELECT state,lease_expires_at>clock_timestamp() AS live FROM backtest_run_attempt WHERE run_id=$1::text::uuid AND attempt_id=$2::text::uuid AND worker_instance_id=$3::text::uuid AND attempt_number=$4 AND fencing_token=$5",&[&claim.run_id(),&claim.attempt,&claim.worker,&claim.number,&claim.fence]).await.map_err(|_|UNCERTAIN)?.ok_or(UNCERTAIN)?;
    if row.try_get::<_, &str>("state").map_err(|_| UNCERTAIN)? != state
        || (active && !row.try_get::<_, bool>("live").map_err(|_| UNCERTAIN)?)
    {
        return Err(UNCERTAIN);
    }
    Ok(())
}

// Deferred triggers execute before the final owning reads and physical guard.
// Every mutation path calls this after its last write; commit performs no write.
async fn flush_deferred(tx: &Transaction<'_>) -> Result<()> {
    tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
        .await
        .map_err(db)
}
async fn verify_current(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    expected: &VerifiedRun,
    status: Option<RunStatus>,
) -> Result<()> {
    let current = read_run(tx, namespace, expected.run_id(), false)
        .await?
        .ok_or(MISMATCH)?;
    current.matches(expected)?;
    if status.is_some_and(|s| s != current.status) {
        return Err(MISMATCH);
    }
    Ok(())
}
async fn verify_receipt(tx: &Transaction<'_>, expected: &Receipt) -> Result<()> {
    match Commands::verify_binding_in_transaction(tx, expected.admission().id())
        .await
        .map_err(|e| e.code())?
    {
        Binding::Accepted(actual) if &actual == expected => Ok(()),
        _ => Err(MISMATCH),
    }
}
#[allow(clippy::too_many_arguments)]
async fn verify_attempt(
    tx: &Transaction<'_>,
    run: &str,
    attempt: &str,
    worker: &str,
    number: i32,
    fence: i64,
    state: &str,
    live: bool,
) -> Result<()> {
    let row=tx.query_opt("SELECT state,lease_expires_at>clock_timestamp() AS live,finished_at IS NOT NULL AS finished,(finished_at>=lease_expires_at AND failure_code='LEASE_EXPIRED') IS TRUE AS valid_expiry,failure_code FROM backtest_run_attempt WHERE run_id=$1::text::uuid AND attempt_id=$2::text::uuid AND worker_instance_id=$3::text::uuid AND attempt_number=$4 AND fencing_token=$5",&[&run,&attempt,&worker,&number,&fence]).await.map_err(db)?.ok_or(MISMATCH)?;
    if row.try_get::<_, &str>("state").map_err(db)? != state
        || (live && !row.try_get::<_, bool>("live").map_err(db)?)
        || row.try_get::<_, bool>("finished").map_err(db)? != (state != "ACTIVE")
    {
        return Err(MISMATCH);
    }
    let failure: Option<&str> = row.try_get("failure_code").map_err(db)?;
    if (state == "EXPIRED" && !row.try_get::<_, bool>("valid_expiry").map_err(db)?)
        || (matches!(state, "ACTIVE" | "SUCCEEDED" | "CANCELLED") && failure.is_some())
    {
        return Err(MISMATCH);
    }
    Ok(())
}
/// Observation does not acquire a Command lock, Source grant or Runtime hold.
pub(crate) enum CreationOutcome {
    NotSubmitted,
    Pending,
    Accepted(Box<VerifiedRun>),
}
pub(crate) async fn creation_outcome_readonly(
    client: &mut tokio_postgres::Client,
    namespace: &SemanticStoreId,
    request: &CreateRequest,
    owner: &str,
) -> Result<CreationOutcome> {
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(db)?;
    bounds(&tx).await.map_err(db)?;
    deployment::verify_binding_in_transaction(&tx, namespace)
        .await
        .map_err(db)?;
    let value = match Commands::verify_binding_in_transaction(&tx, request.command_id())
        .await
        .map_err(db)?
    {
        Binding::None => {
            if read_run(&tx, namespace, request.run_id(), false)
                .await?
                .is_some()
            {
                return Err(MISMATCH);
            }
            CreationOutcome::NotSubmitted
        }
        Binding::Admitted(a) if a.kind() == CommandKind::CreateBacktestRun => {
            CreationOutcome::Pending
        }
        Binding::Accepted(_) => CreationOutcome::Accepted(Box::new(
            replay(&tx, namespace, request, owner)
                .await?
                .ok_or(MISMATCH)?,
        )),
        _ => return Err(MISMATCH),
    };
    tx.commit().await.map_err(db)?;
    Ok(value)
}

/// Original readonly transaction, same namespace/Command/receipt owner reads.
/// It grants no mutation session, current eligibility or new work.
pub(crate) async fn load_in_transaction(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    id: &str,
) -> Result<VerifiedRun> {
    if !command::uuid4(id) {
        return Err(INVALID);
    }
    read_run(tx, namespace, id, false)
        .await?
        .map(|row| row.run)
        .ok_or("BACKTEST_RUN_NOT_FOUND")
}

/// Durable pending inventory, not an in-memory queue or admission grant. Every
/// selected native row passes the existing immutable Command/admission reader.
pub(crate) async fn pending_native_run_ids(
    client: &mut tokio_postgres::Client,
    namespace: &SemanticStoreId,
) -> Result<Vec<String>> {
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(db)?;
    tx.batch_execute("SET LOCAL search_path=pg_catalog,public,pg_temp")
        .await
        .map_err(db)?;
    bounds(&tx).await.map_err(db)?;
    deployment::verify_binding_in_transaction(&tx, namespace)
        .await
        .map_err(db)?;
    let rows=tx.query("SELECT run_id::text FROM public.backtest_run WHERE specification_schema_version=3 AND state IN ('QUEUED','RUNNING','CANCEL_REQUESTED') ORDER BY queued_at,run_id LIMIT 10001",&[]).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err("BACKTEST_RECOVERY_INVENTORY_BUDGET_EXCEEDED");
    }
    let mut selected = Vec::with_capacity(rows.len());
    for row in rows {
        let id: String = row.try_get(0).map_err(db)?;
        let current = read_run(&tx, namespace, &id, false)
            .await?
            .ok_or(MISMATCH)?;
        if !matches!(
            current.status.state,
            RunState::Queued | RunState::Running | RunState::CancelRequested
        ) {
            return Err(MISMATCH);
        }
        selected.push(id);
    }
    tx.commit().await.map_err(db)?;
    Ok(selected)
}
