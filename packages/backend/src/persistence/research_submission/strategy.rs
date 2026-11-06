//! Human Strategy5 admission on the existing Run/Novelty/Command authorities.
//! Review values grant no execution; a new admission requires actual PreparedInputs.
use super::{
    Context, INVALID, Result, SubmissionOutcome, UNAVAILABLE, canonical, hash, insert_action,
    load_in_transaction, run_id, text,
};
use crate::{
    application::{
        command::{Admission, Binding, CommandId, CommandKind, Outcome, OutcomeKind, Receipt},
        private_assets,
        private_strategy::Definition,
        research_admission::PreparedInputs,
        research_run::VerifiedRun,
        strategy_research::{
            Context as ResearchContext, DecisionGraph, RunSpecification, Specification,
        },
    },
    persistence::{
        authority_session::AuthoritySession,
        postgres::{Commands, bounds, system_time},
        research_dataset::Store as Datasets,
        research_novelty::Authority,
    },
    security::human_access,
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use tokio_postgres::Transaction;
const CORRUPT: &str = "RESEARCH_AUTHORIZATION_CORRUPT";
const UNKNOWN: &str = "RESEARCH_COMMAND_OUTCOME_UNKNOWN";
#[derive(Clone)]
pub struct Request {
    specification: RunSpecification,
    parent: Option<String>,
    policy: String,
    version: String,
}
impl Request {
    /// Pure intent, never a PreparedInputs or Run grant.
    pub fn new(
        specification: RunSpecification,
        parent: Option<String>,
        policy: &str,
        version: &str,
    ) -> Result<Self> {
        crate::persistence::research_novelty::validate_policy_reference(policy, version)
            .map_err(|_| INVALID)?;
        if let Some(id) = &parent {
            CommandId::new(id).map_err(|_| INVALID)?;
        }
        Ok(Self {
            specification,
            parent,
            policy: policy.into(),
            version: version.into(),
        })
    }
    pub fn from_record(v: &Value) -> Result<Self> {
        fields(
            v,
            &[
                "schema_version",
                "parent_run_id",
                "policy_id",
                "policy_version",
                "specification",
            ],
        )
        .map_err(|_| INVALID)?;
        if v["schema_version"] != 1 {
            return Err(INVALID);
        }
        let parent = if v["parent_run_id"].is_null() {
            None
        } else {
            Some(text(v, "parent_run_id")?.into())
        };
        Self::new(
            RunSpecification::from_record(&v["specification"])?,
            parent,
            text(v, "policy_id")?,
            text(v, "policy_version")?,
        )
    }
    pub fn record(&self) -> Value {
        json!({"schema_version":1,"parent_run_id":self.parent,"policy_id":self.policy,"policy_version":self.version,"specification":self.specification.record()})
    }
    pub fn specification(&self) -> &RunSpecification {
        &self.specification
    }
    pub fn parent_run_id(&self) -> Option<&str> {
        self.parent.as_deref()
    }
    pub fn policy(&self) -> (&str, &str) {
        (&self.policy, &self.version)
    }
    fn command_fingerprint(&self, owner: &str, group: &str) -> Result<String> {
        hash(
            &json!({"contract":"ONLYALPHA_STRATEGY_RESEARCH_COMMAND_V1","owner":owner,"request":self.record(),"decision_group_fingerprint":group}),
        )
    }
}
pub struct PreparedStudy {
    owner: String,
    command: CommandId,
    request: Request,
    composition: String,
    group: String,
}
impl PreparedStudy {
    pub fn record(&self) -> Result<Value> {
        Ok(
            json!({"schema_version":1,"command_id":self.command.value(),"owner":self.owner,"request":self.request.record(),"composition_fingerprint":self.composition,"decision_group_fingerprint":self.group}),
        )
    }
    pub fn fingerprint(&self) -> Result<String> {
        hash(&self.record()?)
    }
    pub fn command_id(&self) -> &CommandId {
        &self.command
    }
    pub fn request(&self) -> &Request {
        &self.request
    }
}
pub struct StudyPreparationOutcome {
    study: PreparedStudy,
    actionable: bool,
}
impl StudyPreparationOutcome {
    pub fn into_parts(self) -> (PreparedStudy, bool) {
        (self.study, self.actionable)
    }
}

// Failure class belongs to the operation that observed it. It is never inferred
// from a suffix or a successful later reconnect. Cancellation drops owned session.
enum Failure {
    Rejected(&'static str),
    Authority(&'static str),
}
type Work<T> = std::result::Result<T, Failure>;
fn rejected(code: &'static str) -> Failure {
    Failure::Rejected(code)
}
fn authority(_: impl std::fmt::Debug) -> Failure {
    Failure::Authority(UNAVAILABLE)
}
fn retained(code: &'static str) -> Failure {
    Failure::Authority(code)
}
fn command_error(error: crate::application::command::Error) -> Failure {
    if error == crate::application::command::Error::Conflict {
        rejected("RESEARCH_COMMAND_CONFLICT")
    } else {
        Failure::Authority(error.code())
    }
}
fn novelty_error(code: &'static str) -> Failure {
    match code {
        "NOVELTY_DECISION_CONFLICT"
        | "NOVELTY_DECISION_NOT_ADMIT"
        | "NOVELTY_DECISION_STALE"
        | "NOVELTY_DECISION_NOT_FOUND" => rejected(code),
        _ => retained(code),
    }
}
async fn finish<T>(
    session: &mut AuthoritySession,
    mut owned: AuthoritySession,
    result: Work<T>,
) -> Result<T> {
    if let Err(Failure::Authority(code)) = &result {
        return Err(*code);
    }
    let successful = result.is_ok();
    owned
        .verify()
        .await
        .map_err(|e| if successful { UNKNOWN } else { e.code() })?;
    session.restore_ownership(owned);
    match result {
        Ok(value) => Ok(value),
        Err(Failure::Rejected(code)) => Err(code),
        Err(Failure::Authority(_)) => unreachable!(),
    }
}
async fn transaction_bounds(tx: &Transaction<'_>) -> Work<()> {
    tx.batch_execute("SET LOCAL search_path=pg_catalog,public,pg_temp")
        .await
        .map_err(authority)?;
    bounds(tx).await.map_err(authority)
}
fn fields(v: &Value, keys: &[&str]) -> Result<()> {
    crate::application::private_strategy::exact(v, keys).map_err(|_| CORRUPT)
}
fn check_inputs(request: &Request, command: &CommandId, inputs: &PreparedInputs) -> Work<()> {
    let spec = request.specification.record();
    let p = inputs.record();
    if p["schema_version"] != 1
        || p["contract"] != "ONLYALPHA_STRATEGY_RESEARCH_PREPARED_INPUTS_V1"
        || p["run_specification_fingerprint"]
            != request.specification.fingerprint().map_err(rejected)?
        || p["runtime_work_binding"]["work_id"] != run_id(command)
        || p["runtime_generation_fingerprint"] != spec["runtime_generation_fingerprint"]
        || p["execution_binding"] != spec["execution_binding"]
        || p["input_window"] != spec["input_window"]
        || p["dataset_snapshot_fingerprint"]
            != spec["scientific_specification"]["dataset_snapshot_fingerprint"]
        || p["algorithm_resolution"]["algorithm_artifact"] != spec["algorithm_artifact_fingerprint"]
        || inputs.runtime_manifest()["catalog_generation_fingerprint"]
            != spec["catalog_generation_fingerprint"]
        || p["composition"]["catalog_generation_fingerprint"]
            != spec["catalog_generation_fingerprint"]
    {
        return Err(rejected(INVALID));
    }
    inputs.verify_runtime().map_err(retained)
}
fn check_source(context: &Context<'_>, inputs: &PreparedInputs, datasets: &Datasets) -> Work<()> {
    context.source().map_err(rejected)?;
    let p = inputs.record();
    let materialized = crate::application::research_dataset::MaterializedDataset::load(
        datasets,
        text(&p["dataset_materialization"], "materialization_id").map_err(retained)?,
    )
    .map_err(retained)?;
    if materialized.lineage() != &p["dataset_materialization"]
        || materialized.verified().dataset().snapshot_fingerprint()
            != p["dataset_snapshot_fingerprint"]
    {
        return Err(retained(CORRUPT));
    }
    let provenance = materialized.verified().manifest()["provenance"]
        .as_array()
        .filter(|p| p.len() == 1)
        .ok_or_else(|| retained(CORRUPT))?;
    let scope = &provenance[0]["source_metadata"]["sealed_input"]["scope"];
    if scope["source_id"] != context.selection.source_id()
        || scope["bar_construction"]["plan"]["integration_revision_fingerprint"]
            != context.selection.reference().revision()
    {
        return Err(rejected("RESEARCH_SOURCE_ACCESS_DENIED"));
    }
    Ok(())
}
/// Staging seals a source-backed decision. No Run, Command receipt or permission is created.
pub async fn prepare_study(
    session: &mut AuthoritySession,
    novelty: &Authority,
    context: &Context<'_>,
    command: CommandId,
    request: Request,
    inputs: &PreparedInputs,
    datasets: &Datasets,
) -> Result<StudyPreparationOutcome> {
    let mut owned = session.take_ownership();
    let result = async {
        let owner = context.owner().map_err(rejected)?.to_owned();
        check_inputs(&request, &command, inputs)?;
        check_source(context, inputs, datasets)?;
        let client = owned.client_mut().await.map_err(authority)?;
        let tx = client.transaction().await.map_err(authority)?;
        transaction_bounds(&tx).await?;
        verify_origin(&tx, inputs.record(), &request.specification)
            .await
            .map_err(retained)?;
        AuthoritySession::verify_transaction(&tx)
            .await
            .map_err(authority)?;
        tx.commit().await.map_err(authority)?;
        let projection = novelty
            .refresh_projection(owned.client_mut().await.map_err(authority)?)
            .await
            .map_err(novelty_error)?;
        let group = novelty
            .seal(
                owned.client_mut().await.map_err(authority)?,
                &command,
                &[request.specification.subject().map_err(rejected)?],
                &request.policy,
                &request.version,
                &projection,
            )
            .await
            .map_err(novelty_error)?;
        let actionable = match text(&group, "disposition").map_err(retained)? {
            "ACTIONABLE" => true,
            "BLOCKED" => false,
            _ => return Err(retained(CORRUPT)),
        };
        context.owner().map_err(rejected)?;
        context.source().map_err(rejected)?;
        inputs.verify_runtime().map_err(retained)?;
        Ok(StudyPreparationOutcome {
            study: PreparedStudy {
                owner,
                command,
                request,
                composition: text(&inputs.record()["composition"], "composition_fingerprint")
                    .map_err(retained)?
                    .into(),
                group: text(&group, "group_fingerprint").map_err(retained)?.into(),
            },
            actionable,
        })
    }
    .await;
    finish(session, owned, result).await
}
pub fn restore_study(
    context: &Context<'_>,
    record: &Value,
    expected: &str,
) -> Result<PreparedStudy> {
    fields(
        record,
        &[
            "schema_version",
            "command_id",
            "owner",
            "request",
            "composition_fingerprint",
            "decision_group_fingerprint",
        ],
    )?;
    if record["schema_version"] != 1
        || hash(record)? != expected
        || record["owner"] != context.owner()?
    {
        return Err("RESEARCH_PROPOSAL_STALE");
    }
    for key in ["composition_fingerprint", "decision_group_fingerprint"] {
        if !crate::is_sha256_hex(text(record, key)?) {
            return Err(INVALID);
        }
    }
    Ok(PreparedStudy {
        owner: context.owner()?.into(),
        command: CommandId::new(text(record, "command_id")?).map_err(|_| INVALID)?,
        request: Request::from_record(&record["request"])?,
        composition: text(record, "composition_fingerprint")?.into(),
        group: text(record, "decision_group_fingerprint")?.into(),
    })
}
fn admission(study: &PreparedStudy, owner: &str) -> Work<Admission> {
    Admission::new(
        study.command.clone(),
        CommandKind::CreateResearchRun,
        &study
            .request
            .command_fingerprint(owner, &study.group)
            .map_err(rejected)?,
    )
    .map_err(command_error)
}
async fn accepted(
    tx: &Transaction<'_>,
    study: &PreparedStudy,
    owner: &str,
    admission: &Admission,
) -> Work<Option<VerifiedRun>> {
    match Commands::verify_binding_in_transaction(tx, &study.command)
        .await
        .map_err(command_error)?
    {
        Binding::Accepted(r) => {
            if r.admission() != admission
                || r.outcome().kind() != OutcomeKind::ResearchRun
                || r.outcome().id() != run_id(&study.command)
            {
                return Err(rejected("RESEARCH_COMMAND_CONFLICT"));
            }
            let run = load_in_transaction(tx, r.outcome().id(), Some(owner))
                .await
                .map_err(retained)?;
            if run.specification().as_strategy().is_err() {
                return Err(retained(CORRUPT));
            }
            Ok(Some(run))
        }
        Binding::Admitted(a) if a != *admission => Err(rejected("RESEARCH_COMMAND_CONFLICT")),
        _ => Ok(None),
    }
}
/// Same-database Run + original Novelty action + Human authorization + Receipt.
/// Original accepted Commands are resolved before any current Source or Runtime preflight.
pub async fn submit(
    session: &mut AuthoritySession,
    novelty: &Authority,
    context: &Context<'_>,
    selection: (&PreparedStudy, &str),
    inputs: &PreparedInputs,
    datasets: &Datasets,
    at: OnlyUtcDateTime,
) -> Result<VerifiedRun> {
    submit_inner(
        session,
        novelty,
        context,
        SubmissionSelection {
            study: selection.0,
            expected: selection.1,
            preparation: None,
        },
        inputs,
        datasets,
        at,
    )
    .await
}
pub(crate) async fn submit_prepared(
    session: &mut AuthoritySession,
    novelty: &Authority,
    context: &Context<'_>,
    selection: (
        &PreparedStudy,
        &str,
        &crate::persistence::research_preparation::Operation,
    ),
    inputs: &PreparedInputs,
    datasets: &Datasets,
    at: OnlyUtcDateTime,
) -> Result<VerifiedRun> {
    let (study, expected, operation) = selection;
    submit_inner(
        session,
        novelty,
        context,
        SubmissionSelection {
            study,
            expected,
            preparation: Some(operation),
        },
        inputs,
        datasets,
        at,
    )
    .await
}
struct SubmissionSelection<'a> {
    study: &'a PreparedStudy,
    expected: &'a str,
    preparation: Option<&'a crate::persistence::research_preparation::Operation>,
}

async fn submit_inner(
    session: &mut AuthoritySession,
    novelty: &Authority,
    context: &Context<'_>,
    selection: SubmissionSelection<'_>,
    inputs: &PreparedInputs,
    datasets: &Datasets,
    at: OnlyUtcDateTime,
) -> Result<VerifiedRun> {
    let SubmissionSelection {
        study,
        expected,
        preparation,
    } = selection;
    let mut owned = session.take_ownership();
    let result=async {
        let owner=context.owner().map_err(rejected)?;
        if study.owner!=owner||study.fingerprint().map_err(rejected)?!=expected {return Err(rejected("RESEARCH_PROPOSAL_STALE"));}
        if let Some(operation)=preparation
            && (!operation.request.is_strategy() || operation.owner!=owner || operation.request.research_command()!=study.command.value()) {return Err(rejected("RESEARCH_PREPARATION_COMMAND_CONFLICT"));}
        let admission=admission(study,owner)?;
        {
            let tx=owned.client_mut().await.map_err(authority)?.transaction().await.map_err(authority)?;
            transaction_bounds(&tx).await?;
            Commands::lock_command(&tx,&study.command).await.map_err(command_error)?;
            let original=accepted(&tx,study,owner,&admission).await?;
            AuthoritySession::verify_transaction(&tx).await.map_err(authority)?;
            tx.commit().await.map_err(authority)?;
            if let Some(run)=original {return Ok(run);}
        }
        check_inputs(&study.request,&study.command,inputs)?;
        if inputs.record()["composition"]["composition_fingerprint"]!=study.composition {return Err(rejected(INVALID));}
        check_source(context,inputs,datasets)?;
        let projection=novelty.refresh_projection(owned.client_mut().await.map_err(authority)?).await.map_err(novelty_error)?;
        let action=novelty.authorize_action(owned.client_mut().await.map_err(authority)?,&study.command,&[study.request.specification.subject().map_err(rejected)?],&projection).await.map_err(novelty_error)?;
        if !action.policy_matches(&study.request.policy,&study.request.version)||action.group_fingerprint()!=study.group {return Err(rejected("RESEARCH_PROPOSAL_STALE"));}
        let tx=owned.client_mut().await.map_err(authority)?.build_transaction().isolation_level(tokio_postgres::IsolationLevel::Serializable).start().await.map_err(authority)?;
        transaction_bounds(&tx).await?;
        Commands::lock_command(&tx,&study.command).await.map_err(command_error)?;
        if let Some(run)=accepted(&tx,study,owner,&admission).await? {
            AuthoritySession::verify_transaction(&tx).await.map_err(authority)?;
            tx.commit().await.map_err(authority)?;
            return Ok(run);
        }
        if let Some(operation)=preparation {
            crate::persistence::research_preparation::guard_submission(&tx,operation,expected).await.map_err(|code|match code {"RESEARCH_PREPARATION_STALE"|"RESEARCH_PREPARATION_STUDY_STALE"|"RESEARCH_PREPARATION_STRATEGY_MISMATCH"|"FACTOR_PROPOSAL_STALE"|"RESEARCH_PREPARATION_CANCEL_REQUESTED"=>rejected(code),_=>retained(code)})?;
        }
        action.recheck_in_transaction(&tx).await.map_err(novelty_error)?;
        let revision=verify_origin(&tx,inputs.record(),&study.request.specification).await.map_err(retained)?;
        let strategy_id=text(&revision,"strategy_id").map_err(retained)?;
        let id=run_id(&study.command);
        let prior=trial_prefix(&tx,owner,strategy_id,None).await.map_err(retained)?;
        let mut prior_ids=Vec::new();
        for (prior_id,index) in prior {
            index.ok_or_else(||retained("RESEARCH_AUTHORIZATION_UNAVAILABLE"))?;
            let previous=run_row(&tx,&prior_id).await.map_err(retained)?;
            let grant=verify_authorization_record(&tx,&previous).await.map_err(retained)?;
            if grant["actor_id"]!=owner||grant["strategy_id"]!=strategy_id {return Err(retained(CORRUPT));}
            prior_ids.push(prior_id);
        }
        if study.request.parent.as_ref().is_some_and(|p|!prior_ids.contains(p)||p==&id) {return Err(rejected(INVALID));}
        let parent=action.parent_record(admission.fingerprint(),&id).map_err(retained)?;
        let native=study.request.specification.fingerprint().map_err(rejected)?;
        let science=study.request.specification.scientific_specification_fingerprint().map_err(rejected)?;
        let names=name_snapshot(&revision);
        let authorization=json!({"schema_version":1,"contract":"ONLYALPHA_STRATEGY_RESEARCH_AUTHORIZATION_V1","actor_id":owner,
            "command_id":study.command.value(),"command_fingerprint":admission.fingerprint(),"run_id":id,
            "strategy_id":strategy_id,"strategy_revision_fingerprint":revision["revision_fingerprint"],"composition_fingerprint":study.composition,
            "specification_fingerprint":native,"scientific_specification_fingerprint":science,"novelty_admission_fingerprint":parent["admission_fingerprint"],
            "request":study.request.record(),"decision_group_fingerprint":study.group,"name_snapshot":names,"prior_trial_run_ids":prior_ids,
            "parent_run_id":study.request.parent,"max_attempts":3,"lease_seconds":120,"heartbeat_seconds":30,
            "protected_access_policy":"NO_PROTECTED_ACCESS_V1","accepted_at":at.to_string(),"prepared_inputs":inputs.record()});
        let payload=canonical(study.request.specification.record()).map_err(rejected)?;
        let raw_auth=canonical(&authorization).map_err(retained)?;
        let auth_fp=hash(&authorization).map_err(retained)?;
        let timestamp=system_time(at).map_err(command_error)?;
        Commands::admit_exact_in_transaction(&tx,&admission).await.map_err(command_error)?;
        tx.execute("INSERT INTO research_run(run_id,revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_fingerprint,queued_at,calculation_execution_evidence_fingerprints,origin_kind,strategy_research_composition_fingerprint) VALUES($1::text::uuid,0,'QUEUED',5,$2,$3,$4,$5,ARRAY[]::text[],'PRIVATE_STRATEGY',$6)",&[&id,&native,&payload,&text(&parent,"admission_fingerprint").map_err(retained)?,&timestamp,&study.composition]).await.map_err(authority)?;
        insert_action(&tx,&parent,&action).await.map_err(retained)?;
        tx.execute("INSERT INTO research_strategy_study_authorization(run_id,command_id,fingerprint,payload) VALUES($1::text::uuid,$2::text::uuid,$3,$4)",&[&id,&study.command.value(),&auth_fp,&raw_auth]).await.map_err(authority)?;
        let receipt=Receipt::new(admission,Outcome::new(OutcomeKind::ResearchRun,&id).map_err(command_error)?,&at.to_string()).map_err(command_error)?;
        Commands::put_verified_receipt_in_transaction(&tx,&receipt).await.map_err(command_error)?;
        tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE").await.map_err(authority)?;
        let verified=load_in_transaction(&tx,&id,Some(owner)).await.map_err(retained)?;
        action.verify_cut().map_err(retained)?;
        context.owner().map_err(rejected)?;
        context.source().map_err(rejected)?;
        inputs.verify_runtime().map_err(retained)?;
        AuthoritySession::verify_transaction(&tx).await.map_err(authority)?;
        tx.commit().await.map_err(|_|retained(UNKNOWN))?;
        Ok(verified)
    }.await;
    finish(session, owned, result).await
}
/// Outcome recovery needs the original Human/Command, never a new Source grant,
/// mutable head, executable availability, or replacement PreparedInputs.
pub(crate) async fn submission_outcome_readonly(
    client: &mut tokio_postgres::Client,
    context: &Context<'_>,
    study: &PreparedStudy,
) -> Result<SubmissionOutcome> {
    let result = async {
        let owner = context.owner().map_err(rejected)?;
        if study.owner != owner {
            return Err(rejected("RESEARCH_RUN_NOT_FOUND"));
        }
        let admission = admission(study, owner)?;
        let tx = client
            .build_transaction()
            .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(authority)?;
        transaction_bounds(&tx).await?;
        let outcome = if let Some(run) = accepted(&tx, study, owner, &admission).await? {
            SubmissionOutcome::Accepted(Box::new(run))
        } else {
            match Commands::verify_binding_in_transaction(&tx, &study.command)
                .await
                .map_err(command_error)?
            {
                Binding::None => {
                    if tx
                        .query_opt(
                            "SELECT 1 FROM research_run WHERE run_id=$1::text::uuid",
                            &[&run_id(&study.command)],
                        )
                        .await
                        .map_err(authority)?
                        .is_some()
                    {
                        return Err(retained(CORRUPT));
                    }
                    SubmissionOutcome::NotSubmitted
                }
                Binding::Admitted(_) => SubmissionOutcome::Pending,
                Binding::Accepted(_) => return Err(retained(CORRUPT)),
            }
        };
        context.owner().map_err(rejected)?;
        tx.commit().await.map_err(authority)?;
        Ok(outcome)
    }
    .await;
    result.map_err(|e| match e {
        Failure::Rejected(code) | Failure::Authority(code) => code,
    })
}
pub async fn submission_outcome(
    session: &mut AuthoritySession,
    context: &Context<'_>,
    study: &PreparedStudy,
) -> Result<SubmissionOutcome> {
    let mut owned = session.take_ownership();
    let result = async {
        let owner = context.owner().map_err(rejected)?;
        if study.owner != owner {
            return Err(rejected("RESEARCH_RUN_NOT_FOUND"));
        }
        let admission = admission(study, owner)?;
        let tx = owned
            .client_mut()
            .await
            .map_err(authority)?
            .transaction()
            .await
            .map_err(authority)?;
        transaction_bounds(&tx).await?;
        Commands::lock_command(&tx, &study.command)
            .await
            .map_err(command_error)?;
        let outcome = if let Some(run) = accepted(&tx, study, owner, &admission).await? {
            SubmissionOutcome::Accepted(Box::new(run))
        } else {
            match Commands::verify_binding_in_transaction(&tx, &study.command)
                .await
                .map_err(command_error)?
            {
                Binding::None => {
                    if tx
                        .query_opt(
                            "SELECT 1 FROM research_run WHERE run_id=$1::text::uuid",
                            &[&run_id(&study.command)],
                        )
                        .await
                        .map_err(authority)?
                        .is_some()
                    {
                        return Err(retained(CORRUPT));
                    }
                    SubmissionOutcome::NotSubmitted
                }
                Binding::Admitted(_) => SubmissionOutcome::Pending,
                Binding::Accepted(_) => return Err(retained(CORRUPT)),
            }
        };
        AuthoritySession::verify_transaction(&tx)
            .await
            .map_err(authority)?;
        tx.commit().await.map_err(authority)?;
        Ok(outcome)
    }
    .await;
    finish(session, owned, result).await
}
pub async fn cancel(
    session: &mut AuthoritySession,
    human: (&human_access::Access, &human_access::Session),
    command: CommandId,
    id: &str,
    at: OnlyUtcDateTime,
) -> Result<VerifiedRun> {
    let mut owned = session.take_ownership();
    let result=async {
        human.0.check_session(human.1).map_err(|_|rejected("RESEARCH_HUMAN_AUTHORIZATION_REQUIRED"))?;
        let owner=human.1.subject_id().map_err(|_|rejected("RESEARCH_HUMAN_AUTHORIZATION_REQUIRED"))?;
        let fp=hash(&json!({"contract":"ONLYALPHA_STRATEGY_RESEARCH_CANCEL_V1","actor_id":owner,"run_id":id})).map_err(rejected)?;
        let admission=Admission::new(command.clone(),CommandKind::CancelResearchRun,&fp).map_err(command_error)?;
        let tx=owned.client_mut().await.map_err(authority)?.transaction().await.map_err(authority)?;
        transaction_bounds(&tx).await?;
        Commands::lock_command(&tx,&command).await.map_err(command_error)?;
        let run=load_in_transaction(&tx,id,Some(owner)).await.map_err(retained)?;
        run.specification().as_strategy().map_err(rejected)?;
        match Commands::verify_binding_in_transaction(&tx,&command).await.map_err(command_error)? {
            Binding::Accepted(r)=>if r.admission()!=&admission||r.outcome().kind()!=OutcomeKind::ResearchRun||r.outcome().id()!=id {return Err(rejected("RESEARCH_COMMAND_CONFLICT"));},
            Binding::Admitted(a) if a!=admission=>return Err(rejected("RESEARCH_COMMAND_CONFLICT")),
            _=> {
                Commands::admit_exact_in_transaction(&tx,&admission).await.map_err(command_error)?;
                crate::persistence::research_execution::ResearchExecution::request_cancel_in_transaction(&tx,&run,at).await.map_err(|code|if code=="RESEARCH_CANCEL_CONFLICT"{rejected(code)}else{retained(code)})?;
                let receipt=Receipt::new(admission,Outcome::new(OutcomeKind::ResearchRun,id).map_err(command_error)?,&at.to_string()).map_err(command_error)?;
                Commands::put_verified_receipt_in_transaction(&tx,&receipt).await.map_err(command_error)?;
            }
        }
        tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE").await.map_err(authority)?;
        let run=load_in_transaction(&tx,id,Some(owner)).await.map_err(retained)?;
        human.0.check_session(human.1).map_err(|_|rejected("RESEARCH_HUMAN_AUTHORIZATION_REQUIRED"))?;
        AuthoritySession::verify_transaction(&tx).await.map_err(authority)?;
        tx.commit().await.map_err(|_|retained(UNKNOWN))?;
        Ok(run)
    }.await;
    finish(session, owned, result).await
}
fn name_snapshot(revision: &Value) -> Value {
    json!({"strategy_id":revision["strategy_id"],"semantic_version":revision["semantic_version"],"description":revision["description"]})
}
async fn run_row(tx: &Transaction<'_>, id: &str) -> Result<Value> {
    let row=tx.query_opt("SELECT CASE WHEN octet_length(row_to_json(r)::text)<=8388608 THEN row_to_json(r)::text ELSE NULL END FROM research_run r WHERE run_id=$1::text::uuid",&[&id]).await.map_err(super::db)?.ok_or(CORRUPT)?;
    let raw: String = row.try_get(0).map_err(super::db)?;
    let row: Value = serde_json::from_str(&raw).map_err(super::db)?;
    crate::persistence::research_execution::validate_source_history_event("RESEARCH_RUN", &row)?;
    Ok(row)
}
async fn trial_prefix(
    tx: &Transaction<'_>,
    owner: &str,
    strategy: &str,
    boundary: Option<(&str, i64)>,
) -> Result<Vec<(String, Option<i64>)>> {
    let rows = if let Some((id, first)) = boundary {
        tx.query("SELECT a.run_id::text,min(h.event_index) FROM research_strategy_study_authorization a LEFT JOIN research_source_history h ON h.source_family='RESEARCH_RUN' AND h.source_row->>'run_id'=a.run_id::text WHERE a.payload::jsonb->>'actor_id'=$1 AND a.payload::jsonb->>'strategy_id'=$2 AND a.run_id!=$3::text::uuid GROUP BY a.run_id HAVING min(h.event_index)<$4 OR min(h.event_index) IS NULL ORDER BY a.run_id LIMIT 1025",&[&owner,&strategy,&id,&first]).await.map_err(super::db)?
    } else {
        tx.query("SELECT a.run_id::text,min(h.event_index) FROM research_strategy_study_authorization a LEFT JOIN research_source_history h ON h.source_family='RESEARCH_RUN' AND h.source_row->>'run_id'=a.run_id::text WHERE a.payload::jsonb->>'actor_id'=$1 AND a.payload::jsonb->>'strategy_id'=$2 GROUP BY a.run_id ORDER BY a.run_id LIMIT 1025",&[&owner,&strategy]).await.map_err(super::db)?
    };
    if rows.len() > 1024 {
        return Err("RESEARCH_TRIAL_HISTORY_BUDGET_EXCEEDED");
    }
    rows.iter()
        .map(|r| {
            Ok((
                r.try_get(0).map_err(super::db)?,
                r.try_get(1).map_err(super::db)?,
            ))
        })
        .collect()
}
/// Re-derive source/graph/scientific value closure from original immutable DB
/// revisions. Reading historical authorization never needs current Runtime files.
async fn verify_origin(tx: &Transaction<'_>, p: &Value, spec: &RunSpecification) -> Result<Value> {
    fields(
        p,
        &[
            "schema_version",
            "contract",
            "composition",
            "runtime_generation_fingerprint",
            "runtime_work_binding",
            "execution_binding",
            "input_window",
            "dataset_snapshot_fingerprint",
            "dataset_materialization",
            "dataset_construction_fingerprint",
            "run_specification_fingerprint",
            "algorithm_resolution_request",
            "algorithm_resolution",
            "native_implementations",
        ],
    )?;
    let s = spec.record();
    let composition = &p["composition"];
    let pin = text(composition, "composition_fingerprint")?;
    let stored=tx.query_opt("SELECT CASE WHEN octet_length(to_jsonb(p)::text)<=8388608 THEN (to_jsonb(p)-'research_context_payload')::text ELSE NULL END,CASE WHEN octet_length(research_context_payload::text)<=8388608 THEN research_context_payload::text ELSE NULL END FROM private_strategy_research_composition p WHERE composition_fingerprint=$1",&[&pin]).await.map_err(super::db)?.ok_or(CORRUPT)?;
    let raw: String = stored.try_get(0).map_err(super::db)?;
    let actual: Value = serde_json::from_str(&raw).map_err(super::db)?;
    if actual != *composition {
        return Err(CORRUPT);
    }
    let context: Value = serde_json::from_str(&stored.try_get::<_, String>(1).map_err(super::db)?)
        .map_err(super::db)?;
    let context = ResearchContext::new(context)?;
    let revision = private_assets::strategy_revision_in_transaction(
        tx,
        text(composition, "private_strategy_id")?,
        text(composition, "private_strategy_revision_fingerprint")?,
    )
    .await
    .map_err(|_| CORRUPT)?;
    let definition = Definition::from_record(&revision["definition"])?;
    let source = definition.to_record();
    let research = context.definition(&definition)?;
    let mut identity = composition.clone();
    identity
        .as_object_mut()
        .ok_or(CORRUPT)?
        .remove("composition_fingerprint");
    identity["contract"] = json!("ONLYALPHA_PRIVATE_STRATEGY_RESEARCH_COMPOSITION_V1");
    if hash(&identity)? != pin
        || composition["schema_version"] != 1
        || composition["private_strategy_definition_fingerprint"]
            != revision["definition_fingerprint"]
        || composition["research_context_fingerprint"] != context.fingerprint()?
        || composition["research_definition_fingerprint"] != research.fingerprint()?
        || composition["factor_revision_bindings"] != source["factor_revision_dependencies"]
        || composition["catalog_generation_fingerprint"] != s["catalog_generation_fingerprint"]
    {
        return Err(CORRUPT);
    }
    let mut factors = BTreeMap::new();
    for dependency in source["factor_revision_dependencies"]
        .as_array()
        .ok_or(CORRUPT)?
    {
        let factor = private_assets::factor_revision_in_transaction(
            tx,
            text(dependency, "factor_id")?,
            text(dependency, "revision_fingerprint")?,
        )
        .await
        .map_err(|_| CORRUPT)?;
        if factors
            .insert(text(dependency, "factor_id")?.to_owned(), factor)
            .is_some()
        {
            return Err(CORRUPT);
        }
    }
    let request = &p["algorithm_resolution_request"];
    fields(
        request,
        &[
            "schema_version",
            "contract",
            "sources",
            "instances",
            "core_artifact",
            "operator_artifact",
            "target_artifact",
        ],
    )?;
    let mut instances = source["calculations"].as_array().ok_or(CORRUPT)?.clone();
    instances.extend(
        context.record()["targets"]
            .as_array()
            .ok_or(CORRUPT)?
            .iter()
            .cloned(),
    );
    let mut sources = Vec::new();
    for factor in factors.values() {
        let mut projection = serde_json::Map::new();
        for key in [
            "factor_id",
            "semantic_version",
            "revision_fingerprint",
            "source_text",
            "source_sha256",
            "factor_api_version",
            "factor_api_contract_fingerprint",
            "input_contract",
            "parameter_contract",
            "output_contract",
        ] {
            projection.insert(key.into(), factor[key].clone());
        }
        sources.push(Value::Object(projection));
    }
    let observed = &p["algorithm_resolution"];
    if request["schema_version"] != 1
        || request["contract"] != "ONLYALPHA_CALCULATION_INSTANCES_RESOLVE_V1"
        || request["sources"] != json!(sources)
        || request["instances"] != json!(instances)
        || observed["contract"] != request["contract"]
        || observed["schema_version"] != 1
        || observed["algorithm_artifact"] != s["algorithm_artifact_fingerprint"]
        || observed["isolation"] != "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    {
        return Err(CORRUPT);
    }
    for name in ["core", "operator", "target"] {
        if request[format!("{name}_artifact")]["sha256"]
            != observed[format!("{name}_artifact_sha256")]
            || !observed[format!("{name}_resources_fingerprint")]
                .as_str()
                .is_some_and(crate::is_sha256_hex)
        {
            return Err(CORRUPT);
        }
    }
    let nodes = observed["nodes"].as_array().ok_or(CORRUPT)?;
    if nodes.len() != instances.len() {
        return Err(CORRUPT);
    }
    let project = |declarations: &Value| -> Result<Value> {
        let mut result = Vec::new();
        for declaration in declarations.as_array().ok_or(CORRUPT)? {
            let mut found = nodes
                .iter()
                .filter(|n| n["instance_key"] == declaration["instance_key"]);
            let n = found.next().ok_or(CORRUPT)?;
            if found.next().is_some() {
                return Err(CORRUPT);
            }
            result.push(json!({"instance_key":n["instance_key"],"definition":n["definition"],"definition_fingerprint":n["definition_fingerprint"],"type_declaration":n["type_declaration"]}));
        }
        Ok(json!(result))
    };
    let decision = DecisionGraph::derive(&definition, &project(&source["calculations"])?)?;
    let targets = DecisionGraph::target_graph(&context, &project(&context.record()["targets"])?)?;
    let science = Specification::derive(
        &research,
        &decision,
        &targets,
        text(p, "dataset_snapshot_fingerprint")?,
    )?;
    let mut window = decision.input_window(
        &context,
        s["input_window"]["bar_ns"]
            .as_str()
            .ok_or(CORRUPT)?
            .parse()
            .map_err(|_| CORRUPT)?,
    )?;
    window
        .as_object_mut()
        .ok_or(CORRUPT)?
        .remove("research_context_fingerprint");
    if p["schema_version"] != 1
        || p["contract"] != "ONLYALPHA_STRATEGY_RESEARCH_PREPARED_INPUTS_V1"
        || p["run_specification_fingerprint"] != spec.fingerprint()?
        || p["runtime_generation_fingerprint"] != s["runtime_generation_fingerprint"]
        || p["runtime_work_binding"]["generation_fingerprint"]
            != s["runtime_generation_fingerprint"]
        || p["runtime_work_binding"]["kind"] != "RuntimeWorkBound"
        || p["runtime_work_binding"]["reason"] != "research"
        || p["execution_binding"] != s["execution_binding"]
        || p["input_window"] != window
        || window != s["input_window"]
        || p["dataset_snapshot_fingerprint"]
            != s["scientific_specification"]["dataset_snapshot_fingerprint"]
        || p["dataset_materialization"]["dataset_snapshot_fingerprint"]
            != p["dataset_snapshot_fingerprint"]
        || !p["dataset_construction_fingerprint"]
            .as_str()
            .is_some_and(crate::is_sha256_hex)
        || science.record() != &s["scientific_specification"]
        || decision.record() != s["decision"]
        || targets.to_record() != s["target_graph"]
    {
        return Err(CORRUPT);
    }
    let natives = p["native_implementations"].as_array().ok_or(CORRUPT)?;
    let mut used = BTreeMap::new();
    let native_bindings = s["implementation_bindings"].as_array().ok_or(CORRUPT)?;
    for node in decision
        .graph()
        .ordered_nodes()
        .chain(targets.ordered_nodes())
    {
        let d = node.to_record();
        let pin = node.fingerprint();
        let manifests = if d["kind"] == "PREDICATE" {
            natives
        } else {
            let mut found = nodes
                .iter()
                .filter(|n| n["definition_fingerprint"] == pin && n["definition"] == d);
            let actual = found.next().ok_or(CORRUPT)?;
            if found.next().is_some() {
                return Err(CORRUPT);
            }
            actual["implementations"].as_array().ok_or(CORRUPT)?
        };
        let backends: &[&str] = if d["kind"] == "TARGET" {
            &["RESEARCH"]
        } else {
            &["RESEARCH", "TRADING"]
        };
        if d["kind"] == "TARGET" && manifests.len() != 1 {
            return Err(CORRUPT);
        }
        for backend in backends {
            let mut found = manifests.iter().filter(|m| {
                m["backend_kind"] == *backend
                    && ["kind", "type_id", "semantic_version"]
                        .iter()
                        .all(|key| m["calculation_type_reference"][*key] == d[*key])
            });
            let manifest = found.next().ok_or(CORRUPT)?;
            if found.next().is_some() {
                return Err(CORRUPT);
            }
            crate::application::research_admission::implementation_projection(manifest)?;
            if d["kind"] != "TARGET" {
                let binding = native_bindings
                    .iter()
                    .find(|b| b["node_fingerprint"] == pin)
                    .ok_or(CORRUPT)?;
                let key = if *backend == "RESEARCH" {
                    "research_implementation_fingerprint"
                } else {
                    "trading_implementation_fingerprint"
                };
                if binding[key] != manifest["implementation_fingerprint"] {
                    return Err(CORRUPT);
                }
            }
            if d["kind"] == "PREDICATE" {
                used.insert(
                    text(manifest, "implementation_fingerprint")?.to_owned(),
                    manifest.clone(),
                );
            }
        }
    }
    if json!(used.into_values().collect::<Vec<_>>()) != p["native_implementations"] {
        return Err(CORRUPT);
    }
    Ok(revision)
}
async fn verify_authorization_record(tx: &Transaction<'_>, row: &Value) -> Result<Value> {
    let id = text(row, "run_id")?;
    let a=tx.query_opt("SELECT command_id::text,fingerprint,payload FROM research_strategy_study_authorization WHERE run_id=$1::text::uuid",&[&id]).await.map_err(super::db)?.ok_or("RESEARCH_AUTHORIZATION_UNAVAILABLE")?;
    let raw: String = a.try_get(2).map_err(super::db)?;
    if raw.len() > 8 * 1024 * 1024 {
        return Err(UNAVAILABLE);
    }
    let v: Value = serde_json::from_str(&raw).map_err(super::db)?;
    if canonical(&v)? != raw || hash(&v)? != a.try_get::<_, String>(1).map_err(super::db)? {
        return Err(CORRUPT);
    }
    fields(
        &v,
        &[
            "schema_version",
            "contract",
            "actor_id",
            "command_id",
            "command_fingerprint",
            "run_id",
            "strategy_id",
            "strategy_revision_fingerprint",
            "composition_fingerprint",
            "specification_fingerprint",
            "scientific_specification_fingerprint",
            "novelty_admission_fingerprint",
            "request",
            "decision_group_fingerprint",
            "name_snapshot",
            "prior_trial_run_ids",
            "parent_run_id",
            "max_attempts",
            "lease_seconds",
            "heartbeat_seconds",
            "protected_access_policy",
            "accepted_at",
            "prepared_inputs",
        ],
    )?;
    let request = Request::from_record(&v["request"])?;
    let command =
        CommandId::new(&a.try_get::<_, String>(0).map_err(super::db)?).map_err(|_| CORRUPT)?;
    let owner = text(&v, "actor_id")?;
    let expected = request.command_fingerprint(owner, text(&v, "decision_group_fingerprint")?)?;
    let receipt = Commands::load_verified_receipt_in_transaction(tx, &command)
        .await
        .map_err(|_| CORRUPT)?
        .ok_or(CORRUPT)?;
    let accepted = text(&v, "accepted_at")?
        .parse::<OnlyUtcDateTime>()
        .map_err(|_| CORRUPT)?;
    if row["specification_schema_version"] != 5
        || row["origin_kind"] != "PRIVATE_STRATEGY"
        || !row["authoring_provenance"].is_null()
        || v["schema_version"] != 1
        || v["contract"] != "ONLYALPHA_STRATEGY_RESEARCH_AUTHORIZATION_V1"
        || owner.trim().is_empty()
        || owner.len() > 512
        || v["command_id"] != command.value()
        || v["command_fingerprint"] != expected
        || v["run_id"] != id
        || run_id(&command) != id
        || v["specification_fingerprint"] != row["specification_fingerprint"]
        || request.specification.fingerprint()? != row["specification_fingerprint"]
        || canonical(request.specification.record())? != text(row, "specification_payload")?
        || v["scientific_specification_fingerprint"]
            != request
                .specification
                .scientific_specification_fingerprint()?
        || v["composition_fingerprint"] != row["strategy_research_composition_fingerprint"]
        || v["prepared_inputs"]["composition"]["composition_fingerprint"]
            != v["composition_fingerprint"]
        || v["prepared_inputs"]["runtime_work_binding"]["work_id"] != id
        || receipt.admission().kind() != CommandKind::CreateResearchRun
        || receipt.admission().fingerprint() != expected
        || receipt.outcome().kind() != OutcomeKind::ResearchRun
        || receipt.outcome().id() != id
        || receipt.accepted_at() != accepted
        || accepted
            != text(row, "queued_at")?
                .parse::<OnlyUtcDateTime>()
                .map_err(|_| CORRUPT)?
        || v["novelty_admission_fingerprint"] != row["admission_resolution_fingerprint"]
        || v["parent_run_id"] != json!(request.parent)
        || v["max_attempts"] != 3
        || v["lease_seconds"] != 120
        || v["heartbeat_seconds"] != 30
        || v["protected_access_policy"] != "NO_PROTECTED_ACCESS_V1"
    {
        return Err(CORRUPT);
    }
    let revision = verify_origin(tx, &v["prepared_inputs"], &request.specification).await?;
    if v["strategy_id"] != revision["strategy_id"]
        || v["strategy_revision_fingerprint"] != revision["revision_fingerprint"]
        || v["name_snapshot"] != name_snapshot(&revision)
    {
        return Err(CORRUPT);
    }
    let prior = v["prior_trial_run_ids"].as_array().ok_or(CORRUPT)?;
    if prior.len() > 1024
        || prior
            .iter()
            .any(|p| !p.as_str().is_some_and(crate::application::command::uuid4))
        || prior.windows(2).any(|w| w[0].as_str() >= w[1].as_str())
        || prior.iter().any(|p| p == id)
        || request
            .parent
            .as_ref()
            .is_some_and(|p| !prior.iter().any(|r| r == p))
    {
        return Err(CORRUPT);
    }
    super::verify_novelty_member(
        tx,
        row,
        &command,
        &expected,
        text(&v, "decision_group_fingerprint")?,
        &request.specification.subject()?,
    )
    .await?;
    Ok(v)
}
pub(super) async fn verify_authorization(tx: &Transaction<'_>, row: &Value) -> Result<Value> {
    let v = verify_authorization_record(tx, row).await?;
    let id = text(row, "run_id")?;
    let first:Option<i64>=tx.query_one("SELECT min(event_index) FROM research_source_history WHERE source_family='RESEARCH_RUN' AND source_row->>'run_id'=$1",&[&id]).await.map_err(super::db)?.try_get(0).map_err(super::db)?;
    let first = first.ok_or("RESEARCH_AUTHORIZATION_UNAVAILABLE")?;
    let owner = text(&v, "actor_id")?;
    let strategy = text(&v, "strategy_id")?;
    let mut identities = Vec::new();
    for (previous, index) in trial_prefix(tx, owner, strategy, Some((id, first))).await? {
        index.ok_or("RESEARCH_AUTHORIZATION_UNAVAILABLE")?;
        let row = run_row(tx, &previous).await?;
        let grant = verify_authorization_record(tx, &row).await?;
        if grant["actor_id"] != owner
            || grant["strategy_id"] != strategy
            || text(&grant, "accepted_at")?
                .parse::<OnlyUtcDateTime>()
                .map_err(|_| CORRUPT)?
                > text(&v, "accepted_at")?
                    .parse::<OnlyUtcDateTime>()
                    .map_err(|_| CORRUPT)?
        {
            return Err(CORRUPT);
        }
        identities.push(previous);
    }
    if v["prior_trial_run_ids"] != json!(identities) {
        return Err(CORRUPT);
    }
    Ok(v)
}
