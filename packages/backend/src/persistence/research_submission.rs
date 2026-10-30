//! Same-database Human authorization, existing Run + Novelty Admission + global Receipt.
//! Study staging seals a Novelty decision separately; submission never fabricates ADMIT.
use crate::application::{
    command::{Admission, Binding, CommandId, CommandKind, Outcome, OutcomeKind, Receipt},
    factor_content::hash,
    private_assets::authoring::Draft,
    research_admission::PreparedInputs,
    research_run::{Specification, VerifiedRun},
    source_access::{self, Permission, Selection},
};
use crate::persistence::{
    factor_proposals as proposals,
    postgres::{Commands, bounds, system_time},
    private_factor_postgres as factors,
    research_dataset::Store as Datasets,
    research_novelty::{ActionProof, Authority},
};
use crate::security::human_access;
use onlyalpha_domain::time::OnlyUtcDateTime;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use tokio_postgres::{Client, Transaction};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "RESEARCH_SUBMISSION_INVALID";
const UNAVAILABLE: &str = "RESEARCH_SUBMISSION_UNAVAILABLE";
fn db(_: impl std::fmt::Debug) -> &'static str {
    UNAVAILABLE
}
fn canonical(v: &Value) -> Result<String> {
    onlyalpha_metadata_json::canonical_json(&v.to_string(), 8 * 1024 * 1024).map_err(|_| INVALID)
}
fn text<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str().ok_or(INVALID)
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub schema_version: u32,
    pub factor_proposal_fingerprint: String,
    pub parent_run_id: Option<String>,
    pub policy_id: String,
    pub policy_version: String,
    pub specification: Specification,
}
impl Request {
    pub fn record(&self) -> Result<Value> {
        serde_json::to_value(self).map_err(|_| INVALID)
    }
    fn validate(&self) -> Result<()> {
        if self.schema_version != 1
            || !crate::is_sha256_hex(&self.factor_proposal_fingerprint)
            || self.policy_id.is_empty()
            || self.policy_version.is_empty()
        {
            return Err(INVALID);
        }
        if let Some(parent) = &self.parent_run_id {
            CommandId::new(parent).map_err(db)?;
        }
        self.specification.validate()
    }
    fn command_fingerprint(&self, owner: &str, group: &str) -> Result<String> {
        hash(
            &json!({"contract":"ONLYALPHA_FACTOR_RESEARCH_COMMAND_V1","owner":owner,"request":self.record()?,"decision_group_fingerprint":group}),
        )
    }
}
/// Issuer-bound, independently authenticated Human and Source sessions, not Agent credentials.
pub struct Context<'a> {
    pub human_authority: &'a human_access::Access,
    pub human: &'a human_access::Session,
    pub source_authority: &'a source_access::Authority,
    pub source: &'a source_access::Session,
    pub selection: &'a Selection,
}
impl Context<'_> {
    fn owner(&self) -> Result<&str> {
        self.human_authority
            .check_session(self.human)
            .map_err(|_| "RESEARCH_HUMAN_AUTHORIZATION_REQUIRED")?;
        self.human.subject_id().map_err(db)
    }
    fn source(&self) -> Result<()> {
        self.source_authority
            .check_session(self.source)
            .map_err(|_| "RESEARCH_SOURCE_ACCESS_DENIED")?;
        if self.source.subject_id().map_err(db)? != self.owner()? {
            return Err("RESEARCH_SOURCE_ACCESS_DENIED");
        }
        self.source
            .require_selection(self.selection, Permission::ClosedHistory)
            .map_err(|_| "RESEARCH_SOURCE_ACCESS_DENIED")
    }
}
/// Immutable decision reference produced by the actual owning writer; not permission to run.
pub struct PreparedStudy {
    owner: String,
    command: CommandId,
    request: Request,
    group: String,
}
/// Same-call result from the owning sealer, not a deserializable permission or replay proof.
pub struct StudyPreparationOutcome {
    study: PreparedStudy,
    actionable: bool,
}
impl StudyPreparationOutcome {
    pub fn into_parts(self) -> (PreparedStudy, bool) {
        (self.study, self.actionable)
    }
}
impl PreparedStudy {
    pub fn record(&self) -> Result<Value> {
        Ok(
            json!({"schema_version":1,"command_id":self.command.value(),"owner":self.owner,"request":self.request.record()?,"decision_group_fingerprint":self.group}),
        )
    }
    pub fn fingerprint(&self) -> Result<String> {
        hash(&self.record()?)
    }
}
pub fn run_id(command: &CommandId) -> String {
    let mut bytes = Sha256::digest(
        [
            b"ONLYALPHA_NOVELTY_GATED_RESEARCH_RUN_ID_V4\x1f".as_slice(),
            command.value().as_bytes(),
        ]
        .concat(),
    );
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    let s = bytes[..16]
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    format!(
        "{}-{}-{}-{}-{}",
        &s[..8],
        &s[8..12],
        &s[12..16],
        &s[16..20],
        &s[20..32]
    )
}
fn check_inputs(request: &Request, command: &CommandId, inputs: &PreparedInputs) -> Result<()> {
    request.validate()?;
    let spec = &request.specification;
    let factor = spec.factor()?;
    let w = factor.window(crate::application::research_factor::Window {
        start_ns: spec.study.samples[0].start_ns,
        end_ns: spec.study.samples[1].end_ns,
        bar_ns: spec.study.bar_ns,
        horizon_bars: spec.study.horizon_bars,
    })?;
    inputs.verify_runtime()?;
    let p = inputs.record();
    if p["runtime_work_binding"]["work_id"] != run_id(command)
        || p["dataset_snapshot_fingerprint"] != spec.dataset_snapshot_fingerprint
        || p["runtime_generation_fingerprint"] != spec.runtime_generation_fingerprint
        || p["execution_binding"] != spec.execution_binding
        || p["factor_preparation_fingerprint"] != factor.fingerprint()
        || p["input_window"] != w.to_record()
        || p["algorithm_resolution"]["algorithm_artifact"] != spec.algorithm_artifact_fingerprint
        || inputs.runtime_manifest()["catalog_generation_fingerprint"]
            != spec.catalog_generation_fingerprint
    {
        return Err(INVALID);
    }
    Ok(())
}
fn check_source(context: &Context<'_>, spec: &Specification, datasets: &Datasets) -> Result<()> {
    context.source()?;
    let dataset = datasets.load(&spec.dataset_snapshot_fingerprint)?;
    let provenance = &dataset.manifest()["provenance"];
    if provenance.as_array().map(Vec::len) != Some(1) {
        return Err("RESEARCH_SOURCE_ACCESS_DENIED");
    }
    let scope = &provenance[0]["source_metadata"]["sealed_input"]["scope"];
    if scope["source_id"] != context.selection.source_id()
        || scope["bar_construction"]["plan"]["integration_revision_fingerprint"]
            != context.selection.reference().revision()
    {
        return Err("RESEARCH_SOURCE_ACCESS_DENIED");
    }
    Ok(())
}
/// This slice consumes an already materialized Dataset and an existing eligible Runtime.
/// It never acquires/widens data or creates/activates a Generation while staging.
pub async fn prepare_study(
    client: &mut Client,
    authority: &Authority,
    context: &Context<'_>,
    command: CommandId,
    request: Request,
    inputs: &PreparedInputs,
    datasets: &Datasets,
) -> Result<StudyPreparationOutcome> {
    let owner = context.owner()?.to_owned();
    check_inputs(&request, &command, inputs)?;
    check_source(context, &request.specification, datasets)?;
    let tx = client.transaction().await.map_err(db)?;
    bounds(&tx).await.map_err(db)?;
    let accepted = proposals::confirmed_research_input(
        &tx,
        &request.factor_proposal_fingerprint,
        &owner,
        true,
    )
    .await?;
    content(&accepted, &request.specification)?;
    tx.commit().await.map_err(db)?;
    let projection = authority.refresh_projection(client).await?;
    let group = authority
        .seal(
            client,
            &command,
            &[request.specification.subject()?],
            &request.policy_id,
            &request.policy_version,
            &projection,
        )
        .await?;
    let actionable = match text(&group, "disposition")? {
        "ACTIONABLE" => true,
        "BLOCKED" => false,
        _ => return Err(INVALID),
    };
    Ok(StudyPreparationOutcome {
        study: PreparedStudy {
            owner,
            command,
            request,
            group: text(&group, "group_fingerprint")?.into(),
        },
        actionable,
    })
}
fn content(accepted: &Value, spec: &Specification) -> Result<()> {
    let preview = &accepted["snapshot"]["preview"];
    if preview["draft"] != spec.draft
        || preview["expression"] != spec.candidate["expression"]
        || preview["hypothesis"] != spec.candidate["hypothesis"]
    {
        return Err("RESEARCH_FACTOR_CONFIRMATION_MISMATCH");
    }
    Ok(())
}
/// Explicit second Human confirmation. All durable operational effects share one commit.
/// The hosting ingress retains its physical write gate and deadline around this call.
pub async fn submit(
    client: &mut Client,
    authority: &Authority,
    context: &Context<'_>,
    selection: (&PreparedStudy, &str),
    inputs: &PreparedInputs,
    datasets: &Datasets,
    at: OnlyUtcDateTime,
) -> Result<VerifiedRun> {
    submit_checked(
        client,
        authority,
        context,
        (selection.0, selection.1, None),
        inputs,
        datasets,
        at,
    )
    .await
}
pub(crate) async fn submit_prepared(
    client: &mut Client,
    authority: &Authority,
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
    let preparation = selection.2;
    if preparation.request.research_command_id != selection.0.command.value()
        || preparation.outputs["ready"]["prepared_study"] != selection.0.record()?
        || preparation.outputs["ready"]["prepared_inputs"] != *inputs.record()
    {
        return Err("RESEARCH_PREPARATION_STALE");
    }
    submit_checked(
        client,
        authority,
        context,
        (selection.0, selection.1, Some(preparation)),
        inputs,
        datasets,
        at,
    )
    .await
}
async fn submit_checked(
    client: &mut Client,
    authority: &Authority,
    context: &Context<'_>,
    selection: (
        &PreparedStudy,
        &str,
        Option<&crate::persistence::research_preparation::Operation>,
    ),
    inputs: &PreparedInputs,
    datasets: &Datasets,
    at: OnlyUtcDateTime,
) -> Result<VerifiedRun> {
    let (proposal, expected_proposal_fingerprint, preparation) = selection;
    let owner = context.owner()?;
    if owner != proposal.owner || proposal.fingerprint()? != expected_proposal_fingerprint {
        return Err("RESEARCH_PROPOSAL_STALE");
    }
    let request = &proposal.request;
    let command = &proposal.command;
    let command_fp = request.command_fingerprint(owner, &proposal.group)?;
    let admission =
        Admission::new(command.clone(), CommandKind::CreateResearchRun, &command_fp).map_err(db)?;
    // Successful replay consults original facts before source/runtime/current-authoring checks.
    {
        let tx = client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        Commands::lock_command(&tx, command).await.map_err(db)?;
        match Commands::verify_binding_in_transaction(&tx, command)
            .await
            .map_err(db)?
        {
            Binding::Accepted(r) => {
                if r.admission() != &admission
                    || r.outcome().kind() != OutcomeKind::ResearchRun
                    || r.outcome().id() != run_id(command)
                {
                    return Err("RESEARCH_COMMAND_CONFLICT");
                }
                let result = load_in_transaction(&tx, r.outcome().id(), Some(owner)).await?;
                tx.commit().await.map_err(db)?;
                return Ok(result);
            }
            Binding::Admitted(a) if a != admission => return Err("RESEARCH_COMMAND_CONFLICT"),
            _ => {}
        }
        tx.commit().await.map_err(db)?;
    }
    check_inputs(request, command, inputs)?;
    check_source(context, &request.specification, datasets)?;
    let projection = authority.refresh_projection(client).await?;
    let action = authority
        .authorize_action(
            client,
            command,
            &[request.specification.subject()?],
            &projection,
        )
        .await?;
    if !action.policy_matches(&request.policy_id, &request.policy_version)
        || action.group_fingerprint() != proposal.group
    {
        return Err("RESEARCH_PROPOSAL_STALE");
    }
    let tx = client.transaction().await.map_err(db)?;
    bounds(&tx).await.map_err(db)?;
    Commands::lock_command(&tx, command).await.map_err(db)?;
    // A concurrent winner after preflight is replayed without any second effect.
    if let Binding::Accepted(receipt) = Commands::verify_binding_in_transaction(&tx, command)
        .await
        .map_err(db)?
    {
        if receipt.admission() != &admission
            || receipt.outcome().kind() != OutcomeKind::ResearchRun
            || receipt.outcome().id() != run_id(command)
        {
            return Err("RESEARCH_COMMAND_CONFLICT");
        }
        let result = load_in_transaction(&tx, receipt.outcome().id(), Some(owner)).await?;
        tx.commit().await.map_err(db)?;
        return Ok(result);
    }
    if let Some(preparation) = preparation {
        crate::persistence::research_preparation::guard_submission(
            &tx,
            preparation,
            expected_proposal_fingerprint,
        )
        .await?;
    }
    action.recheck_in_transaction(&tx).await?;
    let accepted =
        proposals::confirmed_research_input(&tx, &request.factor_proposal_fingerprint, owner, true)
            .await?;
    content(&accepted, &request.specification)?;
    let id = text(&request.specification.revision, "factor_id")?;
    tx.query_one(
        "SELECT factor_id FROM private_factor_asset WHERE factor_id=$1 FOR UPDATE",
        &[&id],
    )
    .await
    .map_err(db)?;
    let before = factors::state(&tx, id).await.map_err(|e| e.code())?;
    let draft = Draft::new(request.specification.draft.clone()).map_err(|e| e.code())?;
    if before["draft_fingerprint"] != draft.fingerprint().map_err(|e| e.code())?
        || draft.revision().map_err(|e| e.code())? != request.specification.revision
    {
        return Err("RESEARCH_FACTOR_CONFIRMATION_STALE");
    }
    if before["current_revision_fingerprint"]
        != request.specification.revision["revision_fingerprint"]
    {
        if before["current_revision_fingerprint"].as_str() != draft.base() {
            return Err("RESEARCH_FACTOR_CONFIRMATION_STALE");
        }
        let child = proposals::authoring_child(command, "research-publish")?;
        factors::apply_in_transaction(&tx,&child,id,json!({"operation":"PUBLISH","factor_id":id,"expected_draft_fingerprint":before["draft_fingerprint"]}),None,&at.to_string()).await.map_err(|e|e.code())?;
    }
    let state = factors::state(&tx, id).await.map_err(|e| e.code())?;
    if !state["revisions"]
        .as_array()
        .ok_or(INVALID)?
        .iter()
        .any(|r| r["revision"] == request.specification.revision)
    {
        return Err("RESEARCH_FACTOR_REVISION_UNAVAILABLE");
    }
    let expected_run = run_id(command);
    let spec_fp = request.specification.fingerprint()?;
    let parent = action.parent_record(&command_fp, &expected_run)?;
    let prior=tx.query("SELECT run_id::text FROM research_factor_study_authorization WHERE payload::jsonb->>'actor_id'=$1 AND payload::jsonb->>'factor_id'=$2 ORDER BY run_id LIMIT 1025",&[&owner,&id]).await.map_err(db)?;
    if prior.len() > 1024 {
        return Err("RESEARCH_TRIAL_HISTORY_BUDGET_EXCEEDED");
    }
    let mut prior_ids = Vec::new();
    for row in prior {
        let id: String = row.try_get(0).map_err(db)?;
        load_in_transaction(&tx, &id, Some(owner)).await?;
        prior_ids.push(id);
    }
    if let Some(previous) = &request.parent_run_id {
        let previous = load_in_transaction(&tx, previous, Some(owner)).await?;
        if previous.run_id() == expected_run
            || previous.specification().revision["factor_id"]
                != request.specification.revision["factor_id"]
            || !prior_ids.iter().any(|id| id == previous.run_id())
        {
            return Err(INVALID);
        }
    }
    let snapshot = json!({"factor_name":state["display"]["display_name"],"usage_summary":state["display"]["usage_summary"],
        "display_version":state["revisions"].as_array().ok_or(INVALID)?.iter().find(|r|r["revision"]==request.specification.revision).ok_or(INVALID)?["display_version"]});
    let authorization = json!({"schema_version":1,"contract":"ONLYALPHA_FACTOR_RESEARCH_AUTHORIZATION_V1","actor_id":owner,
        "command_id":command.value(),"command_fingerprint":command_fp,"run_id":expected_run,"factor_id":id,
        "factor_proposal_fingerprint":request.factor_proposal_fingerprint,
        "factor_confirmation_command_id":accepted["confirmation_command_id"],"factor_revision_fingerprint":request.specification.revision["revision_fingerprint"],
        "specification_fingerprint":spec_fp,"novelty_admission_fingerprint":parent["admission_fingerprint"],"request":request.record()?,
        "decision_group_fingerprint":proposal.group,"name_snapshot":snapshot,"prior_trial_run_ids":prior_ids,
        "parent_run_id":request.parent_run_id,"max_attempts":3,"lease_seconds":120,"heartbeat_seconds":30,
        "protected_access_policy":"NO_PROTECTED_ACCESS_V1","accepted_at":at.to_string(),"prepared_inputs":inputs.record()});
    let raw_auth = canonical(&authorization)?;
    let auth_fp = hash(&authorization)?;
    let payload = canonical(&request.specification.record()?)?;
    let accepted_at = system_time(at).map_err(db)?;
    Commands::admit_exact_in_transaction(&tx, &admission)
        .await
        .map_err(db)?;
    tx.execute("INSERT INTO research_run(run_id,revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_fingerprint,queued_at,calculation_execution_evidence_fingerprints,origin_kind) VALUES($1::text::uuid,0,'QUEUED',4,$2,$3,$4,$5,ARRAY[]::text[],'GENERAL')",&[&expected_run,&spec_fp,&payload,&text(&parent,"admission_fingerprint")?,&accepted_at]).await.map_err(db)?;
    insert_action(&tx, &parent, &action).await?;
    tx.execute("INSERT INTO research_factor_study_authorization VALUES($1::text::uuid,$2::text::uuid,$3,$4)",&[&expected_run,&command.value(),&auth_fp,&raw_auth]).await.map_err(db)?;
    let receipt = Receipt::new(
        admission,
        Outcome::new(OutcomeKind::ResearchRun, &expected_run).map_err(db)?,
        &at.to_string(),
    )
    .map_err(db)?;
    Commands::put_verified_receipt_in_transaction(&tx, &receipt)
        .await
        .map_err(db)?;
    context
        .human_authority
        .check_session(context.human)
        .map_err(|_| "RESEARCH_HUMAN_AUTHORIZATION_REQUIRED")?;
    context.source()?;
    inputs.verify_runtime()?;
    let verified = load_in_transaction(&tx, &expected_run, Some(owner)).await?;
    // A lost commit acknowledgement is UNKNOWN. Same Command queries the original outcome.
    tx.commit()
        .await
        .map_err(|_| "RESEARCH_COMMAND_OUTCOME_UNKNOWN")?;
    Ok(verified)
}
async fn insert_action(tx: &Transaction<'_>, parent: &Value, action: &ActionProof) -> Result<()> {
    let mut row = parent.clone();
    row.as_object_mut().ok_or(INVALID)?.remove("members");
    tx.execute("INSERT INTO research_novelty_admission SELECT (jsonb_populate_record(NULL::research_novelty_admission,$1::text::jsonb)).*",&[&row.to_string()]).await.map_err(db)?;
    for m in action.member_records() {
        let mut r = m.clone();
        let o = r.as_object_mut().ok_or(INVALID)?;
        o.insert("command_id".into(), parent["command_id"].clone());
        o.insert(
            "admission_fingerprint".into(),
            parent["admission_fingerprint"].clone(),
        );
        tx.execute("INSERT INTO research_novelty_admission_subject SELECT (jsonb_populate_record(NULL::research_novelty_admission_subject,$1::text::jsonb)).*",&[&r.to_string()]).await.map_err(db)?;
    }
    Ok(())
}
pub async fn load(client: &mut Client, id: &str, owner: Option<&str>) -> Result<VerifiedRun> {
    let tx = client.transaction().await.map_err(db)?;
    bounds(&tx).await.map_err(db)?;
    let run = load_in_transaction(&tx, id, owner).await?;
    tx.commit().await.map_err(db)?;
    Ok(run)
}
async fn load_in_transaction(
    tx: &Transaction<'_>,
    id: &str,
    owner: Option<&str>,
) -> Result<VerifiedRun> {
    CommandId::new(id).map_err(db)?;
    let row = tx
        .query_opt(
            "SELECT row_to_json(r)::text FROM research_run r WHERE run_id=$1::text::uuid",
            &[&id],
        )
        .await
        .map_err(db)?
        .ok_or("RESEARCH_RUN_NOT_FOUND")?;
    let raw: String = row.try_get(0).map_err(db)?;
    if raw.len() > 8 * 1024 * 1024 {
        return Err(UNAVAILABLE);
    }
    let row: Value = serde_json::from_str(&raw).map_err(db)?;
    crate::persistence::research_execution::validate_source_history_event("RESEARCH_RUN", &row)?;
    let auth = verify_authorization(tx, &row).await?;
    if owner.is_some_and(|o| auth["actor_id"] != o) {
        return Err("RESEARCH_RUN_NOT_FOUND");
    }
    let payload = text(&row, "specification_payload")?.to_owned();
    let spec: Specification = serde_json::from_str(&payload).map_err(db)?;
    // The immutable member set was verified above, including its Admission V2 hash.
    // Carry its exact original leaves into the read composition, not a copied Group claim.
    let command = CommandId::new(text(&auth, "command_id")?).map_err(db)?;
    let member = tx.query_one("SELECT row_to_json(s)::text FROM research_novelty_admission_subject s WHERE command_id=$1::text::uuid AND ordinal=0", &[&command.value()]).await.map_err(db)?;
    let member: Value =
        serde_json::from_str(&member.try_get::<_, String>(0).map_err(db)?).map_err(db)?;
    let decision_reference = crate::application::research_run::DecisionReference::from_member(
        command,
        text(&auth, "decision_group_fingerprint")?,
        text(&auth["request"], "policy_id")?,
        text(&auth["request"], "policy_version")?,
        &member,
    )?;
    Ok(VerifiedRun {
        run_id: id.into(),
        payload,
        specification: spec,
        specification_fingerprint: text(&row, "specification_fingerprint")?.into(),
        admission_fingerprint: text(&row, "admission_resolution_fingerprint")?.into(),
        prepared_inputs: auth["prepared_inputs"].clone(),
        name_snapshot: auth["name_snapshot"].clone(),
        accepted_at: text(&auth, "accepted_at")?.into(),
        decision_reference,
        completion: if row["state"] == "COMPLETED" {
            Some((
                text(&row, "research_result_fingerprint")?.into(),
                text(&row, "artifact_content_fingerprint")?.into(),
                row["calculation_execution_evidence_fingerprints"]
                    .as_array()
                    .ok_or(INVALID)?
                    .iter()
                    .map(|v| v.as_str().map(str::to_owned).ok_or(INVALID))
                    .collect::<Result<Vec<_>>>()?,
            ))
        } else {
            None
        },
    })
}
/// Immutable relation proof for current or historical Run occurrences; no current-head substitution.
async fn verify_authorization_record(tx: &Transaction<'_>, row: &Value) -> Result<Value> {
    let id = text(row, "run_id")?;
    let a=tx.query_opt("SELECT command_id::text,fingerprint,payload FROM research_factor_study_authorization WHERE run_id=$1::text::uuid",&[&id]).await.map_err(db)?.ok_or("RESEARCH_AUTHORIZATION_UNAVAILABLE")?;
    let command = CommandId::new(&a.try_get::<_, String>(0).map_err(db)?).map_err(db)?;
    let raw: String = a.try_get(2).map_err(db)?;
    if raw.len() > 8 * 1024 * 1024 {
        return Err(UNAVAILABLE);
    }
    let v: Value = serde_json::from_str(&raw).map_err(db)?;
    if canonical(&v)? != raw || hash(&v)? != a.try_get::<_, String>(1).map_err(db)? {
        return Err("RESEARCH_AUTHORIZATION_CORRUPT");
    }
    let keys = [
        "schema_version",
        "contract",
        "actor_id",
        "command_id",
        "command_fingerprint",
        "run_id",
        "factor_id",
        "factor_proposal_fingerprint",
        "factor_confirmation_command_id",
        "factor_revision_fingerprint",
        "specification_fingerprint",
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
    ];
    if v.as_object()
        .is_none_or(|o| o.len() != keys.len() || keys.iter().any(|k| !o.contains_key(*k)))
    {
        return Err("RESEARCH_AUTHORIZATION_CORRUPT");
    }
    let req: Request = serde_json::from_value(v["request"].clone()).map_err(db)?;
    req.validate()?;
    if v["parent_run_id"] != json!(req.parent_run_id)
        || v["accepted_at"]
            .as_str()
            .ok_or(INVALID)?
            .parse::<OnlyUtcDateTime>()
            .map_err(db)?
            != text(row, "queued_at")?
                .parse::<OnlyUtcDateTime>()
                .map_err(db)?
    {
        return Err("RESEARCH_AUTHORIZATION_CORRUPT");
    }
    let prior = v["prior_trial_run_ids"].as_array().ok_or(INVALID)?;
    if prior.len() > 1024
        || prior
            .iter()
            .any(|id| !id.as_str().is_some_and(crate::application::command::uuid4))
        || prior.windows(2).any(|w| w[0].as_str() >= w[1].as_str())
        || prior.iter().any(|p| p == id)
        || req
            .parent_run_id
            .as_ref()
            .is_some_and(|p| !prior.iter().any(|r| r == p))
    {
        return Err("RESEARCH_AUTHORIZATION_CORRUPT");
    }
    let names = &v["name_snapshot"];
    if names.as_object().is_none_or(|o| {
        o.len() != 3
            || ["factor_name", "usage_summary", "display_version"]
                .iter()
                .any(|k| !o.contains_key(*k))
    }) || !names["factor_name"]
        .as_str()
        .is_some_and(|s| !s.is_empty() && s.len() <= 400)
        || !names["usage_summary"]
            .as_str()
            .is_some_and(|s| s.len() <= 4000)
        || names["display_version"].as_u64().is_none_or(|n| n == 0)
    {
        return Err("RESEARCH_AUTHORIZATION_CORRUPT");
    }
    let prepared = &v["prepared_inputs"];
    let factor = req.specification.factor()?;
    let window = factor
        .window(crate::application::research_factor::Window {
            start_ns: req.specification.study.samples[0].start_ns,
            end_ns: req.specification.study.samples[1].end_ns,
            bar_ns: req.specification.study.bar_ns,
            horizon_bars: req.specification.study.horizon_bars,
        })?
        .to_record();
    if prepared["schema_version"] != 1
        || prepared["contract"] != "ONLYALPHA_RESEARCH_PREPARED_INPUTS_V1"
        || prepared["runtime_work_binding"]["work_id"] != id
        || prepared["input_window"] != window
        || prepared["factor_preparation_fingerprint"] != factor.fingerprint()
        || prepared["dataset_snapshot_fingerprint"]
            != req.specification.dataset_snapshot_fingerprint
        || prepared["runtime_generation_fingerprint"]
            != req.specification.runtime_generation_fingerprint
        || prepared["execution_binding"] != req.specification.execution_binding
        || prepared["factor_revision_fingerprint"]
            != req.specification.revision["revision_fingerprint"]
        || prepared["algorithm_resolution"]["algorithm_artifact"]
            != req.specification.algorithm_artifact_fingerprint
    {
        return Err("RESEARCH_AUTHORIZATION_CORRUPT");
    }

    let owner = text(&v, "actor_id")?;
    let expected = req.command_fingerprint(owner, text(&v, "decision_group_fingerprint")?)?;
    let Some(receipt) = Commands::load_verified_receipt_in_transaction(tx, &command)
        .await
        .map_err(db)?
    else {
        return Err("RESEARCH_AUTHORIZATION_CORRUPT");
    };
    if v["schema_version"] != 1
        || v["contract"] != "ONLYALPHA_FACTOR_RESEARCH_AUTHORIZATION_V1"
        || v["command_id"] != command.value()
        || v["run_id"] != id
        || run_id(&command) != id
        || v["specification_fingerprint"] != row["specification_fingerprint"]
        || req.specification.fingerprint()? != row["specification_fingerprint"]
        || canonical(&req.specification.record()?)? != text(row, "specification_payload")?
        || v["command_fingerprint"] != expected
        || receipt.admission().fingerprint() != expected
        || receipt.admission().kind() != CommandKind::CreateResearchRun
        || receipt.outcome().kind() != OutcomeKind::ResearchRun
        || receipt.outcome().id() != id
        || receipt.accepted_at()
            != text(row, "queued_at")?
                .parse::<OnlyUtcDateTime>()
                .map_err(db)?
        || v["novelty_admission_fingerprint"] != row["admission_resolution_fingerprint"]
        || v["max_attempts"] != 3
        || v["lease_seconds"] != 120
        || v["heartbeat_seconds"] != 30
        || v["protected_access_policy"] != "NO_PROTECTED_ACCESS_V1"
    {
        return Err("RESEARCH_AUTHORIZATION_CORRUPT");
    }
    let accepted =
        proposals::confirmed_research_input(tx, &req.factor_proposal_fingerprint, owner, false)
            .await?;
    content(&accepted, &req.specification)?;
    if v["factor_proposal_fingerprint"] != req.factor_proposal_fingerprint
        || v["factor_confirmation_command_id"] != accepted["confirmation_command_id"]
        || v["factor_revision_fingerprint"] != req.specification.revision["revision_fingerprint"]
        || v["factor_id"] != req.specification.revision["factor_id"]
    {
        return Err("RESEARCH_AUTHORIZATION_CORRUPT");
    }
    let factor = factors::state(tx, text(&v, "factor_id")?)
        .await
        .map_err(|e| e.code())?;
    if !factor["revisions"]
        .as_array()
        .ok_or(INVALID)?
        .iter()
        .any(|r| r["revision"] == req.specification.revision)
    {
        return Err("RESEARCH_FACTOR_REVISION_UNAVAILABLE");
    }
    let n=tx.query_opt("SELECT row_to_json(n)::text FROM research_novelty_admission n WHERE run_id=$1::text::uuid",&[&id]).await.map_err(db)?.ok_or("RESEARCH_AUTHORIZATION_CORRUPT")?;
    let parent: Value =
        serde_json::from_str(&n.try_get::<_, String>(0).map_err(db)?).map_err(db)?;
    if parent["command_id"] != command.value()
        || parent["command_fingerprint"] != expected
        || parent["admission_fingerprint"] != row["admission_resolution_fingerprint"]
        || parent["decision_group_fingerprint"] != v["decision_group_fingerprint"]
        || parent["schema_version"] != 2
    {
        return Err("RESEARCH_AUTHORIZATION_CORRUPT");
    }
    // Complete member set and exact original canonical Admission V2 identity.
    let members=tx.query("SELECT row_to_json(s)::text FROM research_novelty_admission_subject s WHERE command_id=$1::text::uuid ORDER BY ordinal LIMIT 33",&[&command.value()]).await.map_err(db)?;
    if members.len() != 1 {
        return Err("RESEARCH_AUTHORIZATION_CORRUPT");
    }
    let mut member: Value =
        serde_json::from_str(&members[0].try_get::<_, String>(0).map_err(db)?).map_err(db)?;
    if member["command_id"] != command.value()
        || member["admission_fingerprint"] != parent["admission_fingerprint"]
        || member["ordinal"] != 0
        || member["evaluation_subject_fingerprint"] != req.specification.subject()?.fingerprint()?
    {
        return Err("RESEARCH_AUTHORIZATION_CORRUPT");
    }
    member.as_object_mut().ok_or(INVALID)?.remove("command_id");
    member
        .as_object_mut()
        .ok_or(INVALID)?
        .remove("admission_fingerprint");
    let rebuilt = json!({"domain":"onlyalpha.research.novelty-admission-v2","schema_version":2,"command_id":command.value(),"command_fingerprint":expected,
        "decision_group_fingerprint":parent["decision_group_fingerprint"],"subject_set_fingerprint":parent["subject_set_fingerprint"],
        "action_source_manifest_fingerprint":parent["action_source_manifest_fingerprint"],"runtime_work_id":id,"run_id":id,"members":[member]});
    if hash(&rebuilt)? != row["admission_resolution_fingerprint"] {
        return Err("RESEARCH_AUTHORIZATION_CORRUPT");
    }
    Ok(v)
}

/// Restore the exact review document after refresh/restart. This grants no execution:
/// submission must still prove the original owning Decision and Human confirmation.
pub fn restore_study(
    context: &Context<'_>,
    record: &Value,
    expected: &str,
) -> Result<PreparedStudy> {
    if record.as_object().is_none_or(|o| {
        o.len() != 5
            || [
                "schema_version",
                "command_id",
                "owner",
                "request",
                "decision_group_fingerprint",
            ]
            .iter()
            .any(|k| !o.contains_key(*k))
    }) || record["schema_version"] != 1
        || hash(record)? != expected
        || record["owner"] != context.owner()?
    {
        return Err("RESEARCH_PROPOSAL_STALE");
    }
    let request: Request = serde_json::from_value(record["request"].clone()).map_err(db)?;
    request.validate()?;
    let group = text(record, "decision_group_fingerprint")?;
    if !crate::is_sha256_hex(group) {
        return Err(INVALID);
    }
    Ok(PreparedStudy {
        owner: context.owner()?.into(),
        command: CommandId::new(text(record, "command_id")?).map_err(db)?,
        request,
        group: group.into(),
    })
}

/// Human cancellation is an idempotent global Command, never an Agent write or new Run.
pub async fn cancel(
    client: &mut Client,
    human: (&human_access::Access, &human_access::Session),
    command: CommandId,
    id: &str,
    at: OnlyUtcDateTime,
) -> Result<VerifiedRun> {
    human
        .0
        .check_session(human.1)
        .map_err(|_| "RESEARCH_HUMAN_AUTHORIZATION_REQUIRED")?;
    let owner = human.1.subject_id().map_err(db)?;
    let fingerprint = hash(
        &json!({"contract":"ONLYALPHA_FACTOR_RESEARCH_CANCEL_V1","actor_id":owner,"run_id":id}),
    )?;
    let admission = Admission::new(
        command.clone(),
        CommandKind::CancelResearchRun,
        &fingerprint,
    )
    .map_err(db)?;
    let tx = client.transaction().await.map_err(db)?;
    bounds(&tx).await.map_err(db)?;
    Commands::lock_command(&tx, &command).await.map_err(db)?;
    let run = load_in_transaction(&tx, id, Some(owner)).await?;
    match Commands::verify_binding_in_transaction(&tx, &command)
        .await
        .map_err(db)?
    {
        Binding::Accepted(r) => {
            if r.admission() != &admission
                || r.outcome().kind() != OutcomeKind::ResearchRun
                || r.outcome().id() != id
            {
                return Err("RESEARCH_COMMAND_CONFLICT");
            }
        }
        Binding::Admitted(a) if a != admission => return Err("RESEARCH_COMMAND_CONFLICT"),
        _ => {
            Commands::admit_exact_in_transaction(&tx, &admission)
                .await
                .map_err(db)?;
            crate::persistence::research_execution::ResearchExecution::request_cancel_in_transaction(&tx,&run,at).await?;
            let receipt = Receipt::new(
                admission,
                Outcome::new(OutcomeKind::ResearchRun, id).map_err(db)?,
                &at.to_string(),
            )
            .map_err(db)?;
            Commands::put_verified_receipt_in_transaction(&tx, &receipt)
                .await
                .map_err(db)?;
        }
    }
    human
        .0
        .check_session(human.1)
        .map_err(|_| "RESEARCH_HUMAN_AUTHORIZATION_REQUIRED")?;
    tx.commit()
        .await
        .map_err(|_| "RESEARCH_COMMAND_OUTCOME_UNKNOWN")?;
    Ok(run)
}

pub enum SubmissionOutcome {
    NotSubmitted,
    Pending,
    Accepted(Box<VerifiedRun>),
}
/// Reconcile the original Command without requiring an available executable, current
/// Source grant or mutable authoring head. Missing completion never triggers a retry.
pub async fn submission_outcome(
    client: &mut Client,
    context: &Context<'_>,
    proposal: &PreparedStudy,
) -> Result<SubmissionOutcome> {
    let owner = context.owner()?;
    if owner != proposal.owner {
        return Err("RESEARCH_RUN_NOT_FOUND");
    }
    let admission = Admission::new(
        proposal.command.clone(),
        CommandKind::CreateResearchRun,
        &proposal
            .request
            .command_fingerprint(owner, &proposal.group)?,
    )
    .map_err(db)?;
    let tx = client.transaction().await.map_err(db)?;
    bounds(&tx).await.map_err(db)?;
    Commands::lock_command(&tx, &proposal.command)
        .await
        .map_err(db)?;
    let outcome = match Commands::verify_binding_in_transaction(&tx, &proposal.command)
        .await
        .map_err(db)?
    {
        Binding::None => {
            if tx
                .query_opt(
                    "SELECT 1 FROM research_run WHERE run_id=$1::text::uuid",
                    &[&run_id(&proposal.command)],
                )
                .await
                .map_err(db)?
                .is_some()
            {
                return Err("RESEARCH_AUTHORIZATION_CORRUPT");
            }
            SubmissionOutcome::NotSubmitted
        }
        Binding::Admitted(a) => {
            if a != admission {
                return Err("RESEARCH_COMMAND_CONFLICT");
            }
            SubmissionOutcome::Pending
        }
        Binding::Accepted(r) => {
            if r.admission() != &admission
                || r.outcome().kind() != OutcomeKind::ResearchRun
                || r.outcome().id() != run_id(&proposal.command)
            {
                return Err("RESEARCH_COMMAND_CONFLICT");
            }
            SubmissionOutcome::Accepted(Box::new(
                load_in_transaction(&tx, r.outcome().id(), Some(owner)).await?,
            ))
        }
    };
    tx.commit().await.map_err(db)?;
    Ok(outcome)
}

/// Complete trial occurrence relation, bounded to the retained same-factor prefix.
/// Each predecessor is verified once; its ancestor list is not recursively traversed.
pub(crate) async fn verify_authorization(tx: &Transaction<'_>, row: &Value) -> Result<Value> {
    let v = verify_authorization_record(tx, row).await?;
    let id = text(row, "run_id")?;
    let first:Option<i64>=tx.query_one("SELECT min(event_index) FROM research_source_history WHERE source_family='RESEARCH_RUN' AND source_row->>'run_id'=$1",&[&id]).await.map_err(db)?.try_get(0).map_err(db)?;
    let first = first.ok_or("RESEARCH_AUTHORIZATION_UNAVAILABLE")?;
    let owner = text(&v, "actor_id")?;
    let factor = text(&v, "factor_id")?;
    let prior=tx.query("SELECT a.run_id::text,min(h.event_index) FROM research_factor_study_authorization a LEFT JOIN research_source_history h ON h.source_family='RESEARCH_RUN' AND h.source_row->>'run_id'=a.run_id::text WHERE a.payload::jsonb->>'actor_id'=$1 AND a.payload::jsonb->>'factor_id'=$2 AND a.run_id!=$3::text::uuid GROUP BY a.run_id HAVING min(h.event_index)<$4 OR min(h.event_index) IS NULL ORDER BY a.run_id LIMIT 1025",&[&owner,&factor,&id,&first]).await.map_err(db)?;
    if prior.len() > 1024 {
        return Err("RESEARCH_TRIAL_HISTORY_BUDGET_EXCEEDED");
    }
    let mut identities = Vec::new();
    for predecessor in prior {
        let previous: String = predecessor.try_get(0).map_err(db)?;
        let index: Option<i64> = predecessor.try_get(1).map_err(db)?;
        index.ok_or("RESEARCH_AUTHORIZATION_UNAVAILABLE")?;
        let raw: String = tx
            .query_one(
                "SELECT row_to_json(r)::text FROM research_run r WHERE run_id=$1::text::uuid",
                &[&previous],
            )
            .await
            .map_err(db)?
            .try_get(0)
            .map_err(db)?;
        if raw.len() > 8 * 1024 * 1024 {
            return Err(UNAVAILABLE);
        }
        let previous_row: Value = serde_json::from_str(&raw).map_err(db)?;
        crate::persistence::research_execution::validate_source_history_event(
            "RESEARCH_RUN",
            &previous_row,
        )?;
        let grant = verify_authorization_record(tx, &previous_row).await?;
        if grant["actor_id"] != owner
            || grant["factor_id"] != factor
            || text(&grant, "accepted_at")?
                .parse::<OnlyUtcDateTime>()
                .map_err(db)?
                > text(&v, "accepted_at")?
                    .parse::<OnlyUtcDateTime>()
                    .map_err(db)?
        {
            return Err("RESEARCH_AUTHORIZATION_CORRUPT");
        }
        identities.push(previous);
    }
    if v["prior_trial_run_ids"] != json!(identities) {
        return Err("RESEARCH_AUTHORIZATION_CORRUPT");
    }
    Ok(v)
}
