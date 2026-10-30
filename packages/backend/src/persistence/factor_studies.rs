//! Explicit Human Study-registration grants and immutable unadmitted Agent Advice.
//! Neither these grants nor a proposal head authorize preparation, activation or Research.
use crate::{
    application::{
        command::{Admission, Binding, CommandId, CommandKind, Outcome, OutcomeKind, Receipt},
        factor_content::hash,
        factor_proposals as factor,
        factor_studies::{GrantInput, StageInput},
    },
    persistence::{
        factor_proposals as proposals,
        postgres::{Commands, bounds},
    },
    security::proposal_access::Presented,
};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use tokio_postgres::{Client, Transaction};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "FACTOR_STUDY_PROPOSAL_INVALID";
const CORRUPT: &str = "FACTOR_STUDY_PROPOSAL_CORRUPT";
const UNAVAILABLE: &str = "FACTOR_STUDY_PROPOSAL_UNAVAILABLE";
const NOT_FOUND: &str = "FACTOR_STUDY_PROPOSAL_NOT_FOUND";
fn db(_: impl std::fmt::Debug) -> &'static str {
    UNAVAILABLE
}
fn text<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key].as_str().ok_or(CORRUPT)
}
fn decoded(raw: String) -> Result<Value> {
    if raw.len() > 262144 {
        return Err(UNAVAILABLE);
    }
    serde_json::from_str(&raw).map_err(|_| CORRUPT)
}
fn intent(kind: CommandKind, owner: &str, actor: &str, body: &Value) -> Result<String> {
    hash(
        &json!({"contract":"ONLYALPHA_FACTOR_STUDY_COMMAND_V1","owner":owner,"actor":actor,"kind":kind.as_str(),"body":body}),
    )
}
fn admission(
    command: &CommandId,
    kind: CommandKind,
    owner: &str,
    actor: &str,
    body: &Value,
) -> Result<Admission> {
    let pin = intent(kind, owner, actor, body)?;
    Admission::new(command.clone(), kind, &pin).map_err(db)
}
fn recognized(kind: CommandKind) -> bool {
    matches!(
        kind,
        CommandKind::CreateFactorStudyGrant
            | CommandKind::StageFactorStudy
            | CommandKind::WithdrawFactorStudy
    )
}
fn operation_view(record: &Value, pin: &str) -> Value {
    json!({"schema_version":1,"command_id":record["command_id"],"operation_fingerprint":pin,"effect":record["effect"]})
}

pub struct Studies<'a> {
    client: &'a mut Client,
}
impl<'a> Studies<'a> {
    pub fn new(client: &'a mut Client) -> Self {
        Self { client }
    }
    /// Called only by authenticated Human ingress. It does not reuse Factor staging authority.
    pub async fn grant(
        &mut self,
        command: &CommandId,
        owner: &str,
        input: GrantInput,
        at: &str,
    ) -> Result<Value> {
        let body = serde_json::to_value(&input).map_err(db)?;
        let a = admission(
            command,
            CommandKind::CreateFactorStudyGrant,
            owner,
            "HUMAN",
            &body,
        )?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        Commands::lock_command(&tx, command).await.map_err(db)?;
        if let Some(original) = replay(&tx, &a, owner, "HUMAN").await? {
            tx.commit().await.map_err(db)?;
            return Ok(original);
        }
        validate_grant(&input)?;
        // Read historical immutable relation first; acquire parent lock before Factor lineage,
        // matching fresh Agent stage/revocation lock ordering.
        let accepted = proposals::confirmed_research_input(
            &tx,
            &input.factor_proposal_fingerprint,
            owner,
            false,
        )
        .await?;
        let parent_pin = text(&accepted["snapshot"], "grant_fingerprint")?;
        let row = tx
            .query_opt(
                "SELECT grant_id::text FROM factor_proposal_grant WHERE fingerprint=$1",
                &[&parent_pin],
            )
            .await
            .map_err(db)?
            .ok_or(CORRUPT)?;
        let parent_id: String = row.get(0);
        let (actual_pin, parent) = proposals::load_grant(&tx, &parent_id).await?;
        if actual_pin != parent_pin || parent["owner"] != owner {
            return Err(CORRUPT);
        }
        active_parent(&tx, &parent, at).await?;
        let current = proposals::confirmed_research_input(
            &tx,
            &input.factor_proposal_fingerprint,
            owner,
            true,
        )
        .await?;
        if current != accepted {
            return Err(CORRUPT);
        }
        let record = grant_record(command, owner, &input, &actual_pin, &parent, &accepted)?;
        if tx.query_opt("SELECT 1 FROM factor_study_grant WHERE grant_id=$1::text::uuid OR (factor_proposal_fingerprint=$2 AND parent_grant_id=$3::text::uuid)",&[&input.grant_id,&input.factor_proposal_fingerprint,&parent_id]).await.map_err(db)?.is_some(){return Err("FACTOR_STUDY_GRANT_CONFLICT");}
        let pin = hash(&record)?;
        tx.execute("INSERT INTO factor_study_grant VALUES($1::text::uuid,$2,$3,$4::text::uuid,$5::text::uuid,$6::text::jsonb)",&[&input.grant_id,&pin,&input.factor_proposal_fingerprint,&parent_id,&command.value(),&record.to_string()]).await.map_err(db)?;
        let result = finish(
            &tx,
            a,
            owner,
            "HUMAN",
            &body,
            json!({"study_grant_id":input.grant_id,"study_grant_fingerprint":pin}),
            at,
        )
        .await?;
        tx.commit().await.map_err(db)?;
        Ok(result)
    }
    pub async fn stage(
        &mut self,
        command: &CommandId,
        credential: &Presented,
        input: StageInput,
        at: &str,
    ) -> Result<Value> {
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        Commands::lock_command(&tx, command).await.map_err(db)?;
        let (parent_pin, parent) = proposals::authenticate_retained(&tx, credential).await?;
        let owner = text(&parent, "owner")?;
        let service = text(&parent["input"], "service_subject")?;
        let body = json!({"parent_grant_fingerprint":parent_pin,"stage":input});
        let a = admission(
            command,
            CommandKind::StageFactorStudy,
            owner,
            service,
            &body,
        )?;
        if let Some(original) = replay(&tx, &a, owner, service).await? {
            tx.commit().await.map_err(db)?;
            return Ok(original);
        }
        proposals::authorize(&tx, credential, at).await?;
        let accepted = proposals::confirmed_research_input(
            &tx,
            &input.factor_proposal_fingerprint,
            owner,
            true,
        )
        .await?;
        verify_origin(&input, &accepted, owner, service, &parent_pin)?;
        let grant = scope_grant(
            &tx,
            &input.factor_proposal_fingerprint,
            &credential.grant_id,
            owner,
        )
        .await?
        .ok_or("FACTOR_STUDY_GRANT_REQUIRED")?;
        let pointer = head(
            &tx,
            &input.factor_proposal_fingerprint,
            owner,
            Some(service),
        )
        .await?;
        if pointer != json!(input.expected_study_fingerprint) {
            return Err("FACTOR_STUDY_PROPOSAL_STALE");
        }
        let id = text(&grant["input"], "grant_id")?;
        let count: i64 = tx
            .query_one(
                "SELECT count(*) FROM factor_study_snapshot WHERE study_grant_id=$1::text::uuid",
                &[&id],
            )
            .await
            .map_err(db)?
            .get(0);
        if count >= grant["input"]["proposal_limit"].as_u64().ok_or(CORRUPT)? as i64 {
            return Err("FACTOR_STUDY_PROPOSAL_BUDGET_EXHAUSTED");
        }
        let record = snapshot_record(command, owner, service, &input, &accepted, &grant)?;
        let pin = hash(&record)?;
        if tx.query_opt("SELECT 1 FROM factor_study_snapshot WHERE factor_proposal_fingerprint=$1 AND event_fingerprint=$2",&[&input.factor_proposal_fingerprint,&input.origin.event_fingerprint]).await.map_err(db)?.is_some(){return Err("FACTOR_STUDY_ORIGIN_CONFLICT");}
        tx.execute("INSERT INTO factor_study_snapshot VALUES($1,$2,$3::text::uuid,$4::text::uuid,$5::text::uuid,$6,$7::text::jsonb)",&[&pin,&input.factor_proposal_fingerprint,&id,&command.value(),&input.origin.session_id,&input.origin.event_fingerprint,&record.to_string()]).await.map_err(db)?;
        tx.execute("INSERT INTO factor_study_head VALUES($1,$2) ON CONFLICT(factor_proposal_fingerprint) DO UPDATE SET fingerprint=excluded.fingerprint",&[&input.factor_proposal_fingerprint,&pin]).await.map_err(db)?;
        let result = finish(
            &tx,
            a,
            owner,
            service,
            &body,
            json!({"proposal_fingerprint":pin}),
            at,
        )
        .await?;
        tx.commit().await.map_err(db)?;
        Ok(result)
    }
    /// Withdraw only the unadmitted suggestion. Existing Research authorization and Runs are untouched.
    pub async fn withdraw(
        &mut self,
        command: &CommandId,
        owner: &str,
        pin: &str,
        at: &str,
    ) -> Result<Value> {
        factor::pin(pin)?;
        let body = json!({"schema_version":1,"study_proposal_fingerprint":pin});
        let a = admission(
            command,
            CommandKind::WithdrawFactorStudy,
            owner,
            "HUMAN",
            &body,
        )?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        Commands::lock_command(&tx, command).await.map_err(db)?;
        if let Some(original) = replay(&tx, &a, owner, "HUMAN").await? {
            tx.commit().await.map_err(db)?;
            return Ok(original);
        }
        let record = snapshot(&tx, pin, owner, None).await?;
        lock_parent_grant(&tx, &record, owner).await?;
        let factor_pin = text(&record, "factor_proposal_fingerprint")?;
        // Human may withdraw a stale Factor's suggestion, but cannot replace Study history.
        let fid = text(&record, "factor_id")?;
        tx.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,619))",
            &[&fid],
        )
        .await
        .map_err(db)?;
        if head(&tx, factor_pin, owner, None).await? != json!(pin) {
            return Err("FACTOR_STUDY_PROPOSAL_STALE");
        }
        if withdrawn(&tx, pin, owner).await? {
            return Err("FACTOR_STUDY_PROPOSAL_ALREADY_WITHDRAWN");
        }
        tx.execute(
            "INSERT INTO factor_study_withdrawal VALUES($1,$2::text::uuid)",
            &[&pin, &command.value()],
        )
        .await
        .map_err(db)?;
        let result = finish(
            &tx,
            a,
            owner,
            "HUMAN",
            &body,
            json!({"proposal_fingerprint":pin}),
            at,
        )
        .await?;
        tx.commit().await.map_err(db)?;
        Ok(result)
    }
    pub async fn context(
        &mut self,
        credential: &Presented,
        factor_pin: &str,
        at: &str,
    ) -> Result<Value> {
        factor::pin(factor_pin)?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let (parent_pin, parent) = proposals::authenticate_retained(&tx, credential).await?;
        let owner = text(&parent, "owner")?;
        let service = text(&parent["input"], "service_subject")?;
        let accepted = proposals::confirmed_research_input(&tx, factor_pin, owner, true).await?;
        verify_factor(&accepted, owner, service, &parent_pin)?;
        let result =
            context_projection(&tx, factor_pin, owner, service, &parent, &accepted, at).await?;
        match result["study_grant_state"].as_str() {
            Some("EXPIRED" | "REVOKED") => return Err("FACTOR_STUDY_GRANT_INACTIVE"),
            Some("ABSENT") => return Err("FACTOR_STUDY_GRANT_REQUIRED"),
            Some("ACTIVE") if !result["study_grant_id"].is_null() => {}
            _ => return Err(CORRUPT),
        }
        if result["remaining_proposals"].as_u64().ok_or(CORRUPT)? == 0 {
            return Err("FACTOR_STUDY_PROPOSAL_BUDGET_EXHAUSTED");
        }
        tx.commit().await.map_err(db)?;
        Ok(result)
    }
    /// Read an explicitly granted registration scope through authenticated Human ingress.
    /// No bearer token is reconstructed, exposed or needed for refresh recovery.
    pub async fn human_context(
        &mut self,
        factor_pin: &str,
        owner: &str,
        at: &str,
    ) -> Result<Value> {
        factor::pin(factor_pin)?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let accepted = proposals::confirmed_research_input(&tx, factor_pin, owner, false).await?;
        let parent_pin = text(&accepted["snapshot"], "grant_fingerprint")?;
        let row = tx
            .query_opt(
                "SELECT grant_id::text FROM factor_proposal_grant WHERE fingerprint=$1",
                &[&parent_pin],
            )
            .await
            .map_err(db)?
            .ok_or(CORRUPT)?;
        let (pin, parent) = proposals::load_grant(&tx, &row.get::<_, String>(0)).await?;
        let service = text(&parent["input"], "service_subject")?;
        if parent["owner"] != owner || pin != parent_pin {
            return Err(NOT_FOUND);
        }
        verify_factor(&accepted, owner, service, &pin)?;
        let current = proposals::confirmed_research_input(&tx, factor_pin, owner, true).await?;
        if current != accepted {
            return Err(CORRUPT);
        }
        let result =
            context_projection(&tx, factor_pin, owner, service, &parent, &accepted, at).await?;
        tx.commit().await.map_err(db)?;
        Ok(result)
    }
    pub async fn read(
        &mut self,
        pin: &str,
        owner: &str,
        credential: Option<&Presented>,
        _at: &str,
    ) -> Result<Value> {
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let (owner, service, parent_pin) = reader_identity(&tx, owner, credential).await?;
        let record = snapshot(&tx, pin, &owner, service.as_deref()).await?;
        if parent_pin
            .as_ref()
            .is_some_and(|p| record["parent_grant_fingerprint"] != *p)
        {
            return Err(NOT_FOUND);
        }
        let current = head(
            &tx,
            text(&record, "factor_proposal_fingerprint")?,
            &owner,
            service.as_deref(),
        )
        .await?
            == json!(pin);
        let withdrawn = withdrawn(&tx, pin, &owner).await?;
        let result = json!({"schema_version":1,"fingerprint":pin,"snapshot":record,"is_current":current,"withdrawn":withdrawn});
        tx.commit().await.map_err(db)?;
        Ok(result)
    }
    pub async fn observe(
        &mut self,
        command: &CommandId,
        owner: &str,
        credential: Option<&Presented>,
        _at: &str,
    ) -> Result<Value> {
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let (owner, service, parent_pin) = reader_identity(&tx, owner, credential).await?;
        let result = operation(&tx, command, &owner, service.as_deref()).await?;
        if let Some(parent_pin) = parent_pin {
            let s = snapshot(
                &tx,
                text(&result["effect"], "proposal_fingerprint")?,
                &owner,
                service.as_deref(),
            )
            .await?;
            if s["parent_grant_fingerprint"] != parent_pin {
                return Err(NOT_FOUND);
            }
        }
        tx.commit().await.map_err(db)?;
        Ok(result)
    }
}

async fn context_projection(
    tx: &Transaction<'_>,
    factor_pin: &str,
    owner: &str,
    service: &str,
    parent: &Value,
    accepted: &Value,
    at: &str,
) -> Result<Value> {
    let grant = scope_grant(tx, factor_pin, text(&parent["input"], "grant_id")?, owner).await?;
    let pointer = head(tx, factor_pin, owner, Some(service)).await?;
    let revoked = tx
        .query_opt(
            "SELECT 1 FROM factor_proposal_revocation WHERE grant_id=$1::text::uuid",
            &[&text(&parent["input"], "grant_id")?],
        )
        .await
        .map_err(db)?
        .is_some();
    let parent_state = registration_state(text(&parent["input"], "expires_at")?, at, revoked)?;
    let (id, pin, remaining, state) = if let Some(g) = grant {
        let id = text(&g["input"], "grant_id")?.to_owned();
        let used: i64 = tx
            .query_one(
                "SELECT count(*) FROM factor_study_snapshot WHERE study_grant_id=$1::text::uuid",
                &[&id],
            )
            .await
            .map_err(db)?
            .get(0);
        let limit = g["input"]["proposal_limit"].as_u64().ok_or(CORRUPT)?;
        let used = u64::try_from(used).map_err(|_| CORRUPT)?;
        if used > limit {
            return Err(CORRUPT);
        }
        (json!(id), json!(hash(&g)?), limit - used, parent_state)
    } else {
        (
            Value::Null,
            Value::Null,
            0,
            if parent_state == "ACTIVE" {
                "ABSENT"
            } else {
                parent_state
            },
        )
    };
    Ok(
        json!({"schema_version":1,"owner":owner,"service_subject":service,"factor_proposal_fingerprint":factor_pin,
        "factor":accepted["snapshot"]["preview"],"factor_id":accepted["snapshot"]["factor_id"],"session_id":accepted["snapshot"]["origin"]["session_id"],
        "workflow_fingerprint":accepted["snapshot"]["origin"]["workflow_fingerprint"],"study_grant_id":id,
        "study_grant_fingerprint":pin,"remaining_proposals":remaining,"study_grant_state":state,"study_proposal_fingerprint":pointer}),
    )
}
fn registration_state(expires: &str, at: &str, revoked: bool) -> Result<&'static str> {
    let expired = factor::datetime(expires)? <= factor::datetime(at)?;
    Ok(if revoked {
        "REVOKED"
    } else if expired {
        "EXPIRED"
    } else {
        "ACTIVE"
    })
}
fn validate_grant(input: &GrantInput) -> Result<()> {
    if input.schema_version != 1 || !(1..=100).contains(&input.proposal_limit) {
        return Err(INVALID);
    }
    factor::id(&input.grant_id)?;
    factor::pin(&input.factor_proposal_fingerprint)
}
fn verify_factor(accepted: &Value, owner: &str, service: &str, parent_pin: &str) -> Result<()> {
    let s = &accepted["snapshot"];
    if s["owner"] != owner
        || s["service_subject"] != service
        || s["grant_fingerprint"] != parent_pin
        || s["factor_id"] != factor::factor_id(owner, service, text(&s["origin"], "session_id")?)?
    {
        return Err("FACTOR_STUDY_SCOPE_MISMATCH");
    }
    Ok(())
}
fn verify_origin(
    input: &StageInput,
    accepted: &Value,
    owner: &str,
    service: &str,
    parent_pin: &str,
) -> Result<()> {
    if input.schema_version != 1 {
        return Err(INVALID);
    }
    factor::pin(&input.factor_proposal_fingerprint)?;
    factor::id(&input.origin.session_id)?;
    for pin in [
        &input.origin.event_fingerprint,
        &input.origin.result_fingerprint,
        &input.origin.workflow_fingerprint,
        &input.origin.model_revision,
    ] {
        factor::pin(pin)?;
    }
    if let Some(pin) = &input.expected_study_fingerprint {
        factor::pin(pin)?;
    }
    verify_factor(accepted, owner, service, parent_pin)?;
    if accepted["snapshot"]["origin"]["session_id"] != input.origin.session_id
        || accepted["snapshot"]["origin"]["workflow_fingerprint"]
            != input.origin.workflow_fingerprint
    {
        return Err("FACTOR_STUDY_ORIGIN_MISMATCH");
    }
    input.advice.study()?;
    Ok(())
}
async fn active_parent(tx: &Transaction<'_>, parent: &Value, at: &str) -> Result<()> {
    if factor::datetime(text(&parent["input"], "expires_at")?)? <= factor::datetime(at)?
        || tx
            .query_opt(
                "SELECT 1 FROM factor_proposal_revocation WHERE grant_id=$1::text::uuid",
                &[&text(&parent["input"], "grant_id")?],
            )
            .await
            .map_err(db)?
            .is_some()
    {
        return Err("FACTOR_STUDY_GRANT_INACTIVE");
    }
    Ok(())
}
fn grant_record(
    command: &CommandId,
    owner: &str,
    input: &GrantInput,
    parent_pin: &str,
    parent: &Value,
    accepted: &Value,
) -> Result<Value> {
    validate_grant(input)?;
    if parent["owner"] != owner {
        return Err(CORRUPT);
    }
    let service = text(&parent["input"], "service_subject")?;
    verify_factor(accepted, owner, service, parent_pin)?;
    Ok(
        json!({"schema_version":1,"owner":owner,"command_id":command.value(),"parent_grant_id":parent["input"]["grant_id"],
        "parent_grant_fingerprint":parent_pin,"factor_proposal_fingerprint":input.factor_proposal_fingerprint,
        "service_subject":service,"session_id":accepted["snapshot"]["origin"]["session_id"],
        "workflow_fingerprint":accepted["snapshot"]["origin"]["workflow_fingerprint"],"input":input}),
    )
}
fn snapshot_record(
    command: &CommandId,
    owner: &str,
    service: &str,
    input: &StageInput,
    accepted: &Value,
    grant: &Value,
) -> Result<Value> {
    verify_origin(
        input,
        accepted,
        owner,
        service,
        text(grant, "parent_grant_fingerprint")?,
    )?;
    if grant["factor_proposal_fingerprint"] != input.factor_proposal_fingerprint
        || grant["service_subject"] != service
        || grant["owner"] != owner
    {
        return Err(CORRUPT);
    }
    let study = input.advice.study()?;
    Ok(
        json!({"schema_version":1,"owner":owner,"service_subject":service,"command_id":command.value(),
        "factor_proposal_fingerprint":input.factor_proposal_fingerprint,"study_grant_id":grant["input"]["grant_id"],
        "study_grant_fingerprint":hash(grant)?,"parent_grant_fingerprint":grant["parent_grant_fingerprint"],
        "factor_id":accepted["snapshot"]["factor_id"],"origin":input.origin,"advice":input.advice,
        "study":study,"study_logical_fingerprint":study.logical_fingerprint()?,"supersedes":input.expected_study_fingerprint}),
    )
}
async fn reader_identity(
    tx: &Transaction<'_>,
    owner: &str,
    c: Option<&Presented>,
) -> Result<(String, Option<String>, Option<String>)> {
    if let Some(c) = c {
        let (pin, g) = proposals::authenticate_retained(tx, c).await?;
        return Ok((
            text(&g, "owner")?.into(),
            Some(text(&g["input"], "service_subject")?.into()),
            Some(pin),
        ));
    }
    Ok((owner.into(), None, None))
}

// Read operation/receipt identity separately from effect closure to avoid recursive facts.
async fn operation_record(
    tx: &Transaction<'_>,
    id: &CommandId,
    owner: &str,
    actor: Option<&str>,
) -> Result<(String, Value)> {
    let binding = Commands::verify_binding_in_transaction(tx, id)
        .await
        .map_err(db)?;
    let row=tx.query_opt("SELECT fingerprint,payload::text FROM factor_study_operation WHERE command_id=$1::text::uuid",&[&id.value()]).await.map_err(db)?;
    let Some(row) = row else {
        return match binding {
            Binding::Accepted(ref r) if recognized(r.admission().kind()) => Err(CORRUPT),
            _ => Err("FACTOR_STUDY_COMMAND_UNKNOWN"),
        };
    };
    let pin: String = row.get(0);
    let record = decoded(row.get(1))?;
    if record["owner"] != owner || actor.is_some_and(|s| record["actor"] != s) {
        return Err(NOT_FOUND);
    }
    let Binding::Accepted(receipt) = binding else {
        return Err(CORRUPT);
    };
    if hash(&record)? != pin
        || record["schema_version"] != 1
        || record["command_id"] != id.value()
        || !recognized(receipt.admission().kind())
        || receipt.outcome().kind() != OutcomeKind::FactorStudyOperation
        || receipt.outcome().id() != pin
        || record["kind"] != receipt.admission().kind().as_str()
        || record["intent"] != receipt.admission().fingerprint()
        || admission(
            id,
            receipt.admission().kind(),
            owner,
            text(&record, "actor")?,
            &record["request"],
        )? != *receipt.admission()
    {
        return Err(CORRUPT);
    }
    // Receipt construction verifies its own timestamp; operation time is the same committed fact.
    if factor::datetime(text(&record, "accepted_at")?)? != receipt.accepted_at() {
        return Err(CORRUPT);
    }
    let fields = [
        "schema_version",
        "owner",
        "actor",
        "command_id",
        "kind",
        "intent",
        "request",
        "effect",
        "accepted_at",
    ];
    if record
        .as_object()
        .is_none_or(|m| m.len() != fields.len() || fields.iter().any(|k| !m.contains_key(*k)))
    {
        return Err(CORRUPT);
    }
    Ok((pin, record))
}
async fn load_grant(tx: &Transaction<'_>, id: &str, owner: &str) -> Result<Value> {
    factor::id(id)?;
    let row=tx.query_opt("SELECT fingerprint,factor_proposal_fingerprint,parent_grant_id::text,command_id::text,payload::text FROM factor_study_grant WHERE grant_id=$1::text::uuid",&[&id]).await.map_err(db)?.ok_or(NOT_FOUND)?;
    let pin: String = row.get(0);
    let factor_pin: String = row.get(1);
    let parent_id: String = row.get(2);
    let command = CommandId::new(&row.get::<_, String>(3)).map_err(db)?;
    let g = decoded(row.get(4))?;
    let (_, op) = operation_record(tx, &command, owner, Some("HUMAN")).await?;
    if op["kind"] != "CREATE_FACTOR_STUDY_GRANT" {
        return Err(CORRUPT);
    }
    let input: GrantInput = serde_json::from_value(op["request"].clone()).map_err(|_| CORRUPT)?;
    let (parent_pin, parent) = proposals::read_grant(tx, &parent_id).await?;
    let accepted = proposals::confirmed_research_input(tx, &factor_pin, owner, false).await?;
    let expected = grant_record(&command, owner, &input, &parent_pin, &parent, &accepted)?;
    if g != expected
        || hash(&g)? != pin
        || input.grant_id != id
        || input.factor_proposal_fingerprint != factor_pin
        || g["parent_grant_id"] != parent_id
        || op["effect"] != json!({"study_grant_id":id,"study_grant_fingerprint":pin})
    {
        return Err(CORRUPT);
    }
    Ok(g)
}
// Mutation fences belong at the action boundary, not in recursive historical reads.
async fn lock_parent_grant(tx: &Transaction<'_>, snapshot: &Value, owner: &str) -> Result<()> {
    let expected = text(snapshot, "parent_grant_fingerprint")?;
    let row = tx
        .query_opt(
            "SELECT grant_id::text FROM factor_proposal_grant WHERE fingerprint=$1",
            &[&expected],
        )
        .await
        .map_err(db)?
        .ok_or(CORRUPT)?;
    let (pin, parent) = proposals::load_grant(tx, &row.get::<_, String>(0)).await?;
    if pin != expected || parent["owner"] != owner {
        return Err(CORRUPT);
    }
    Ok(())
}
async fn scope_grant(
    tx: &Transaction<'_>,
    factor_pin: &str,
    parent_id: &str,
    owner: &str,
) -> Result<Option<Value>> {
    let row=tx.query_opt("SELECT grant_id::text FROM factor_study_grant WHERE factor_proposal_fingerprint=$1 AND parent_grant_id=$2::text::uuid",&[&factor_pin,&parent_id]).await.map_err(db)?;
    match row {
        Some(row) => Ok(Some(load_grant(tx, &row.get::<_, String>(0), owner).await?)),
        None => {
            if tx.query_opt("SELECT 1 FROM factor_study_operation WHERE payload->>'kind'='CREATE_FACTOR_STUDY_GRANT' AND payload->>'owner'=$1 AND payload->'request'->>'factor_proposal_fingerprint'=$2 LIMIT 1",&[&owner,&factor_pin]).await.map_err(db)?.is_some(){return Err(CORRUPT);}
            Ok(None)
        }
    }
}
async fn snapshot(
    tx: &Transaction<'_>,
    pin: &str,
    owner: &str,
    service: Option<&str>,
) -> Result<Value> {
    factor::pin(pin)?;
    let row=tx.query_opt("SELECT factor_proposal_fingerprint,study_grant_id::text,command_id::text,session_id::text,event_fingerprint,payload::text FROM factor_study_snapshot WHERE fingerprint=$1",&[&pin]).await.map_err(db)?.ok_or(NOT_FOUND)?;
    let factor_pin: String = row.get(0);
    let grant_id: String = row.get(1);
    let command = CommandId::new(&row.get::<_, String>(2)).map_err(db)?;
    let s = decoded(row.get(5))?;
    if s["owner"] != owner || service.is_some_and(|v| s["service_subject"] != v) {
        return Err(NOT_FOUND);
    }
    let actor = text(&s, "service_subject")?;
    let (_, op) = operation_record(tx, &command, owner, Some(actor)).await?;
    if op["kind"] != "STAGE_FACTOR_STUDY" {
        return Err(CORRUPT);
    }
    let input: StageInput =
        serde_json::from_value(op["request"]["stage"].clone()).map_err(|_| CORRUPT)?;
    let grant = load_grant(tx, &grant_id, owner).await?;
    let accepted = proposals::confirmed_research_input(tx, &factor_pin, owner, false).await?;
    let expected = snapshot_record(&command, owner, actor, &input, &accepted, &grant)?;
    if expected != s
        || hash(&s)? != pin
        || input.factor_proposal_fingerprint != factor_pin
        || s["origin"]["session_id"] != row.get::<_, String>(3)
        || s["origin"]["event_fingerprint"] != row.get::<_, String>(4)
        || op["request"]
            != json!({"parent_grant_fingerprint":grant["parent_grant_fingerprint"],"stage":input})
        || op["effect"] != json!({"proposal_fingerprint":pin})
    {
        return Err(CORRUPT);
    }
    Ok(s)
}
async fn head(
    tx: &Transaction<'_>,
    factor_pin: &str,
    owner: &str,
    service: Option<&str>,
) -> Result<Value> {
    let pointer = tx
        .query_opt(
            "SELECT fingerprint FROM factor_study_head WHERE factor_proposal_fingerprint=$1",
            &[&factor_pin],
        )
        .await
        .map_err(db)?
        .map(|r| r.get::<_, String>(0));
    let rows=tx.query("SELECT fingerprint FROM factor_study_snapshot WHERE factor_proposal_fingerprint=$1 LIMIT 101",&[&factor_pin]).await.map_err(db)?;
    if rows.len() > 100 {
        return Err(UNAVAILABLE);
    }
    let operations:i64=tx.query_one("SELECT count(*) FROM factor_study_operation WHERE payload->>'kind'='STAGE_FACTOR_STUDY' AND payload->'request'->'stage'->>'factor_proposal_fingerprint'=$1",&[&factor_pin]).await.map_err(db)?.get(0);
    if operations != rows.len() as i64 {
        return Err(CORRUPT);
    }
    let mut children = BTreeMap::new();
    let mut pins = BTreeSet::new();
    for row in rows {
        let pin: String = row.get(0);
        let s = snapshot(tx, &pin, owner, service).await?;
        let parent = if s["supersedes"].is_null() {
            None
        } else {
            Some(text(&s, "supersedes")?.to_owned())
        };
        if children.insert(parent, pin.clone()).is_some() || !pins.insert(pin) {
            return Err(CORRUPT);
        }
    }
    let mut last = None;
    let mut visited = BTreeSet::new();
    while let Some(next) = children.get(&last) {
        if !visited.insert(next.clone()) {
            return Err(CORRUPT);
        }
        last = Some(next.clone());
    }
    if visited != pins || pointer != last {
        return Err(CORRUPT);
    }
    Ok(json!(last))
}
/// Historical owning relation only; never reinterprets accepted work through the current head.
pub(crate) async fn retained(tx: &Transaction<'_>, pin: &str, owner: &str) -> Result<Value> {
    snapshot(tx, pin, owner, None).await
}
/// Owning controller uses this after separate Human permission; a snapshot is not a Run grant.
pub(crate) async fn current(tx: &Transaction<'_>, pin: &str, owner: &str) -> Result<Value> {
    let record = snapshot(tx, pin, owner, None).await?;
    lock_parent_grant(tx, &record, owner).await?;
    let factor_pin = text(&record, "factor_proposal_fingerprint")?;
    proposals::confirmed_research_input(tx, factor_pin, owner, true).await?;
    if head(tx, factor_pin, owner, None).await? != json!(pin) || withdrawn(tx, pin, owner).await? {
        return Err("FACTOR_STUDY_PROPOSAL_STALE");
    }
    Ok(record)
}
async fn withdrawn(tx: &Transaction<'_>, pin: &str, owner: &str) -> Result<bool> {
    let body = json!({"schema_version":1,"study_proposal_fingerprint":pin});
    let intent = intent(CommandKind::WithdrawFactorStudy, owner, "HUMAN", &body)?;
    let related=tx.query("SELECT command_id::text FROM product_command_admission WHERE command_kind='WITHDRAW_FACTOR_STUDY' AND command_fingerprint=$1 UNION SELECT command_id::text FROM product_command_receipt WHERE command_kind='WITHDRAW_FACTOR_STUDY' AND command_fingerprint=$1 UNION SELECT command_id::text FROM factor_study_operation WHERE payload->>'kind'='WITHDRAW_FACTOR_STUDY' AND (payload->'request'->>'study_proposal_fingerprint'=$2 OR payload->'effect'->>'proposal_fingerprint'=$2) LIMIT 2",&[&intent,&pin]).await.map_err(db)?;
    let row=tx.query_opt("SELECT command_id::text FROM factor_study_withdrawal WHERE study_proposal_fingerprint=$1",&[&pin]).await.map_err(db)?;
    let Some(row) = row else {
        return if related.is_empty() {
            Ok(false)
        } else {
            Err(CORRUPT)
        };
    };
    let id = CommandId::new(&row.get::<_, String>(0)).map_err(db)?;
    let (_, record) = operation_record(tx, &id, owner, Some("HUMAN")).await?;
    if related.len() != 1
        || related[0].get::<_, String>(0) != id.value()
        || record["kind"] != "WITHDRAW_FACTOR_STUDY"
        || record["request"] != body
        || record["effect"] != json!({"proposal_fingerprint":pin})
    {
        return Err(CORRUPT);
    }
    Ok(true)
}
async fn operation(
    tx: &Transaction<'_>,
    id: &CommandId,
    owner: &str,
    actor: Option<&str>,
) -> Result<Value> {
    let (pin, record) = operation_record(tx, id, owner, actor).await?;
    match record["kind"].as_str() {
        Some("CREATE_FACTOR_STUDY_GRANT") => {
            load_grant(tx, text(&record["effect"], "study_grant_id")?, owner).await?;
        }
        Some("STAGE_FACTOR_STUDY") => {
            snapshot(
                tx,
                text(&record["effect"], "proposal_fingerprint")?,
                owner,
                Some(text(&record, "actor")?),
            )
            .await?;
        }
        Some("WITHDRAW_FACTOR_STUDY") => {
            let s = text(&record["effect"], "proposal_fingerprint")?;
            snapshot(tx, s, owner, None).await?;
            if !withdrawn(tx, s, owner).await? {
                return Err(CORRUPT);
            }
        }
        _ => return Err(CORRUPT),
    }
    Ok(operation_view(&record, &pin))
}
async fn replay(
    tx: &Transaction<'_>,
    a: &Admission,
    owner: &str,
    actor: &str,
) -> Result<Option<Value>> {
    match Commands::verify_binding_in_transaction(tx, a.id())
        .await
        .map_err(db)?
    {
        Binding::None => {
            if tx
                .query_opt(
                    "SELECT 1 FROM factor_study_operation WHERE command_id=$1::text::uuid",
                    &[&a.id().value()],
                )
                .await
                .map_err(db)?
                .is_some()
            {
                return Err(CORRUPT);
            }
            Ok(None)
        }
        Binding::Admitted(_) => Err("FACTOR_STUDY_COMMAND_UNKNOWN"),
        Binding::Accepted(r) if r.admission() == a => {
            Ok(Some(operation(tx, a.id(), owner, Some(actor)).await?))
        }
        _ => Err("FACTOR_STUDY_COMMAND_CONFLICT"),
    }
}
async fn finish(
    tx: &Transaction<'_>,
    a: Admission,
    owner: &str,
    actor: &str,
    body: &Value,
    effect: Value,
    at: &str,
) -> Result<Value> {
    factor::datetime(at)?;
    let command = a.id().clone();
    let record = json!({"schema_version":1,"owner":owner,"actor":actor,"command_id":command.value(),"kind":a.kind().as_str(),"intent":a.fingerprint(),"request":body,"effect":effect,"accepted_at":at});
    let pin = hash(&record)?;
    Commands::admit_exact_in_transaction(tx, &a)
        .await
        .map_err(db)?;
    tx.execute(
        "INSERT INTO factor_study_operation VALUES($1::text::uuid,$2,$3::text::jsonb)",
        &[&command.value(), &pin, &record.to_string()],
    )
    .await
    .map_err(db)?;
    Commands::put_verified_receipt_in_transaction(
        tx,
        &Receipt::new(
            a,
            Outcome::new(OutcomeKind::FactorStudyOperation, &pin).map_err(db)?,
            at,
        )
        .map_err(db)?,
    )
    .await
    .map_err(db)?;
    Ok(operation_view(&record, &pin))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn input() -> StageInput {
        serde_json::from_value(json!({"schema_version":1,"factor_proposal_fingerprint":"a".repeat(64),
            "origin":{"session_id":"00000000-0000-4000-8000-000000000001","event_fingerprint":"b".repeat(64),
            "result_fingerprint":"c".repeat(64),"workflow_fingerprint":"d".repeat(64),"model_revision":"e".repeat(64)},
            "expected_study_fingerprint":null,"advice":{"source":{"integration_id":"00000000-0000-4000-8000-000000000002",
            "integration_revision_fingerprint":"f".repeat(64),"expected_type_id":"binance.spot.source","source_id":"spot","environment":"public","instrument_id":"BTCUSDT.BINANCE"},
            "timeframe_minutes":1,"start_at":"1970-01-01T00:02:00Z","development_end_at":"1970-01-01T01:06:00Z","end_at":"1970-01-01T02:10:00Z",
            "protected_start_at":"1970-01-01T02:10:00Z","protected_end_at":"1970-01-01T03:14:00Z","horizon_bars":1,"expected_block_length":4,
            "replicates":4096,"confidence_bps":9500,"seed":"0".repeat(64),"rationale":"固定开发、样本外及隔离保留样本。"}})).unwrap()
    }
    fn accepted(input: &StageInput) -> Value {
        json!({"snapshot":{"owner":"owner","service_subject":"agent","grant_fingerprint":"1".repeat(64),
            "factor_id":factor::factor_id("owner","agent",&input.origin.session_id).unwrap(),"origin":input.origin}})
    }
    #[test]
    fn study_origin_cannot_cross_parent_credential_session_or_workflow() {
        let original = input();
        let accepted = accepted(&original);
        verify_origin(&original, &accepted, "owner", "agent", &"1".repeat(64)).unwrap();
        assert!(verify_origin(&original, &accepted, "owner", "other", &"1".repeat(64)).is_err());
        assert!(verify_origin(&original, &accepted, "owner", "agent", &"2".repeat(64)).is_err());
        let mut changed = original.clone();
        changed.origin.session_id = "00000000-0000-4000-8000-000000000003".into();
        assert!(verify_origin(&changed, &accepted, "owner", "agent", &"1".repeat(64)).is_err());
        let mut changed = original.clone();
        changed.origin.workflow_fingerprint = "3".repeat(64);
        assert!(verify_origin(&changed, &accepted, "owner", "agent", &"1".repeat(64)).is_err());
        let mut changed = original;
        changed.advice.replicates = 10;
        assert!(verify_origin(&changed, &accepted, "owner", "agent", &"1".repeat(64)).is_err());
    }
    #[test]
    fn human_registration_observation_preserves_expiry_boundary_and_revocation() {
        let expires = "2027-01-01T00:00:00Z";
        assert_eq!(
            registration_state(expires, "2026-10-28T00:00:00Z", false).unwrap(),
            "ACTIVE"
        );
        assert_eq!(
            registration_state(expires, expires, false).unwrap(),
            "EXPIRED"
        );
        assert_eq!(
            registration_state(expires, "2028-01-01T00:00:00Z", true).unwrap(),
            "REVOKED"
        );
        assert!(registration_state(expires, "invalid", false).is_err());
    }
    #[test]
    fn grant_is_separate_finite_registration_scope() {
        let mut grant = GrantInput {
            schema_version: 1,
            factor_proposal_fingerprint: "a".repeat(64),
            grant_id: "00000000-0000-4000-8000-000000000004".into(),
            proposal_limit: 1,
        };
        validate_grant(&grant).unwrap();
        grant.proposal_limit = 0;
        assert!(validate_grant(&grant).is_err());
        grant.proposal_limit = 101;
        assert!(validate_grant(&grant).is_err());
        grant.proposal_limit = 1;
        grant.schema_version = 2;
        assert!(validate_grant(&grant).is_err());
    }
    #[test]
    fn global_intent_separates_registration_withdrawal_and_research_authority() {
        let body = json!({"schema_version":1,"study_proposal_fingerprint":"a".repeat(64)});
        let original = intent(CommandKind::WithdrawFactorStudy, "owner", "HUMAN", &body).unwrap();
        for kind in [
            CommandKind::StageFactorStudy,
            CommandKind::CreateFactorStudyGrant,
            CommandKind::CreateResearchRun,
        ] {
            assert_ne!(original, intent(kind, "owner", "HUMAN", &body).unwrap());
        }
        assert_ne!(
            original,
            intent(CommandKind::WithdrawFactorStudy, "other", "HUMAN", &body).unwrap()
        );
        assert_ne!(
            original,
            intent(CommandKind::WithdrawFactorStudy, "owner", "agent", &body).unwrap()
        );
    }
}
