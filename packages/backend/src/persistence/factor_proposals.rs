//! The backend owns snapshots, grants and acceptance; Authoring owns Factor facts.
use crate::application::{
    command::{Admission, Binding, CommandId, CommandKind, Outcome, OutcomeKind, Receipt},
    factor_content::{INVALID, hash},
    factor_proposals::{self as a, GrantInput, Result, StageInput},
    private_assets::authoring::Draft,
};
use crate::persistence::{
    postgres::{Commands, bounds},
    private_factor_postgres as factors,
};
use crate::security::proposal_access::Presented;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use subtle::ConstantTimeEq;
use tokio_postgres::{Client, Transaction};
const UNAVAILABLE: &str = "FACTOR_PROPOSAL_UNAVAILABLE";
fn db(_: impl std::fmt::Debug) -> &'static str {
    UNAVAILABLE
}
fn value(raw: String) -> Result<Value> {
    if raw.len() > 131072 {
        return Err(UNAVAILABLE);
    }
    serde_json::from_str(&raw).map_err(db)
}
pub struct Proposals<'a> {
    client: &'a mut Client,
}
impl<'a> Proposals<'a> {
    pub fn new(client: &'a mut Client) -> Self {
        Self { client }
    }
    pub async fn grant(
        &mut self,
        command: &CommandId,
        owner: &str,
        input: GrantInput,
        at: &str,
    ) -> Result<Value> {
        let body = serde_json::to_value(&input).map_err(db)?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let admission = admit(
            command,
            CommandKind::CreateProposalGrant,
            owner,
            "HUMAN",
            &body,
        )?;
        Commands::lock_command(&tx, command).await.map_err(db)?;
        if let Some(v) = replay(&tx, &admission, owner, "HUMAN").await? {
            tx.commit().await.map_err(db)?;
            return Ok(v);
        }
        input.validate(at)?;
        let record =
            json!({"schema_version":1,"owner":owner,"command_id":command.value(),"input":input});
        let fp = hash(&record)?;
        if tx
            .query_opt(
                "SELECT 1 FROM factor_proposal_grant WHERE grant_id=$1::text::uuid",
                &[&input.grant_id],
            )
            .await
            .map_err(db)?
            .is_some()
        {
            return Err("FACTOR_PROPOSAL_GRANT_CONFLICT");
        }
        tx.execute(
            "INSERT INTO factor_proposal_grant VALUES($1::text::uuid,$2,$3::text::jsonb)",
            &[&input.grant_id, &fp, &record.to_string()],
        )
        .await
        .map_err(db)?;
        let v = finish(
            &tx,
            admission,
            owner,
            "HUMAN",
            &body,
            json!({"grant_id":input.grant_id,"grant_fingerprint":fp}),
            at,
        )
        .await?;
        tx.commit().await.map_err(db)?;
        Ok(v)
    }
    pub async fn revoke(
        &mut self,
        command: &CommandId,
        owner: &str,
        grant_id: &str,
        at: &str,
    ) -> Result<Value> {
        a::id(grant_id)?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let admission = admit(
            command,
            CommandKind::RevokeProposalGrant,
            owner,
            "HUMAN",
            &json!({"grant_id":grant_id}),
        )?;
        Commands::lock_command(&tx, command).await.map_err(db)?;
        if let Some(v) = replay(&tx, &admission, owner, "HUMAN").await? {
            tx.commit().await.map_err(db)?;
            return Ok(v);
        }
        let (_, g) = load_grant(&tx, grant_id).await?;
        if g["owner"] != owner {
            return Err("FACTOR_PROPOSAL_NOT_FOUND");
        }
        tx.execute("INSERT INTO factor_proposal_revocation VALUES($1::text::uuid,$2::text::uuid) ON CONFLICT(grant_id) DO NOTHING",&[&grant_id,&command.value()]).await.map_err(db)?;
        let v = finish(
            &tx,
            admission,
            owner,
            "HUMAN",
            &json!({"grant_id":grant_id}),
            json!({"grant_id":grant_id}),
            at,
        )
        .await?;
        tx.commit().await.map_err(db)?;
        Ok(v)
    }
    pub async fn grant_state(
        &mut self,
        config: &crate::security::agent_browser::Connection,
        owner: &str,
        at: &str,
    ) -> Result<String> {
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        if tx
            .query_opt(
                "SELECT 1 FROM factor_proposal_grant WHERE grant_id=$1::text::uuid",
                &[&config.grant_id],
            )
            .await
            .map_err(db)?
            .is_none()
        {
            return Ok("ABSENT".into());
        }
        let (_, g) = load_grant(&tx, &config.grant_id).await?;
        if g["owner"] != owner
            || g["input"]["service_subject"] != config.service_subject
            || g["input"]["credential_sha256"] != config.credential_sha256
        {
            return Err("FACTOR_PROPOSAL_CORRUPT");
        }
        let revoked = tx
            .query_opt(
                "SELECT 1 FROM factor_proposal_revocation WHERE grant_id=$1::text::uuid",
                &[&config.grant_id],
            )
            .await
            .map_err(db)?
            .is_some();
        let state = if revoked {
            "REVOKED"
        } else if a::datetime(text(&g["input"], "expires_at")?)? <= a::datetime(at)? {
            "EXPIRED"
        } else {
            "ACTIVE"
        };
        tx.commit().await.map_err(db)?;
        Ok(state.into())
    }
    pub async fn context(
        &mut self,
        credential: &Presented,
        session: &str,
        at: &str,
    ) -> Result<Value> {
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let (_, g) = authorize(&tx, credential, at).await?;
        let owner = text(&g, "owner")?;
        let service = text(&g["input"], "service_subject")?;
        let fid = a::factor_id(owner, service, session)?;
        let state = state(&tx, &fid).await?;
        let head = head(&tx, &fid).await?;
        let v = json!({"schema_version":1,"owner":owner,"service_subject":service,"factor_id":fid,"draft_fingerprint":state["draft_fingerprint"],"display_fingerprint":state["display_fingerprint"],"proposal_fingerprint":head});
        tx.commit().await.map_err(db)?;
        Ok(v)
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
        let (grant_pin, g) = authorize(&tx, credential, at).await?;
        let owner = text(&g, "owner")?;
        let service = text(&g["input"], "service_subject")?;
        let snapshot = input.snapshot(owner, service, &grant_pin, command.value())?;
        let body = json!({"grant":grant_pin,"stage":input});
        let admission = admit(
            command,
            CommandKind::StageFactorProposal,
            owner,
            service,
            &body,
        )?;
        if let Some(v) = replay(&tx, &admission, owner, service).await? {
            tx.commit().await.map_err(db)?;
            return Ok(v);
        }
        let fid = text(&snapshot, "factor_id")?;
        lineage(&tx, fid).await?;
        if head(&tx, fid).await?
            != serde_json::to_value(&input.expected_proposal_fingerprint).map_err(db)?
        {
            return Err("FACTOR_PROPOSAL_STALE");
        }
        // Grant usage is a backend fact, separate from Agent model/tool usage.
        let count: i64 = tx
            .query_one(
                "SELECT count(*) FROM factor_proposal_snapshot WHERE grant_id=$1::text::uuid",
                &[&credential.grant_id],
            )
            .await
            .map_err(db)?
            .get(0);
        if count >= i64::from(g["input"]["proposal_limit"].as_u64().ok_or(a::INVALID)? as u32) {
            return Err("FACTOR_PROPOSAL_BUDGET_EXHAUSTED");
        }
        let current = state(&tx, fid).await?;
        expected(&snapshot, &current)?;
        let fp = hash(&snapshot)?;
        if tx.query_opt("SELECT 1 FROM factor_proposal_snapshot WHERE factor_id=$1 AND event_fingerprint=$2",&[&fid,&input.origin.event_fingerprint]).await.map_err(db)?.is_some(){return Err("FACTOR_PROPOSAL_ORIGIN_CONFLICT")}
        tx.execute("INSERT INTO factor_proposal_snapshot VALUES($1,$2,$3::text::uuid,$4::text::uuid,$5,$6::text::jsonb)",&[&fp,&fid,&credential.grant_id,&input.origin.session_id,&input.origin.event_fingerprint,&snapshot.to_string()]).await.map_err(db)?;
        tx.execute("INSERT INTO factor_proposal_head VALUES($1,$2) ON CONFLICT(factor_id) DO UPDATE SET fingerprint=excluded.fingerprint",&[&fid,&fp]).await.map_err(db)?;
        let v = finish(
            &tx,
            admission,
            owner,
            service,
            &body,
            json!({"proposal_fingerprint":fp}),
            at,
        )
        .await?;
        tx.commit().await.map_err(db)?;
        Ok(v)
    }
    pub async fn withdraw(
        &mut self,
        command: &CommandId,
        owner: &str,
        fp: &str,
        at: &str,
    ) -> Result<Value> {
        a::pin(fp)?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let body = json!({"proposal_fingerprint":fp});
        let admission = admit(
            command,
            CommandKind::WithdrawFactorProposal,
            owner,
            "HUMAN",
            &body,
        )?;
        Commands::lock_command(&tx, command).await.map_err(db)?;
        if let Some(v) = replay(&tx, &admission, owner, "HUMAN").await? {
            tx.commit().await.map_err(db)?;
            return Ok(v);
        }
        let s = snapshot(&tx, fp, owner, None).await?;
        let fid = text(&s, "factor_id")?;
        lineage(&tx, fid).await?;
        if head(&tx, fid).await? != json!(fp) {
            return Err("FACTOR_PROPOSAL_STALE");
        }
        if withdrawn(&tx, fp, owner).await? {
            return Err("FACTOR_PROPOSAL_ALREADY_WITHDRAWN");
        }
        tx.execute(
            "INSERT INTO factor_proposal_withdrawal VALUES($1,$2::text::uuid)",
            &[&fp, &command.value()],
        )
        .await
        .map_err(db)?;
        let v = finish(
            &tx,
            admission,
            owner,
            "HUMAN",
            &body,
            json!({"proposal_fingerprint":fp}),
            at,
        )
        .await?;
        tx.commit().await.map_err(db)?;
        Ok(v)
    }
    pub async fn confirm(
        &mut self,
        command: &CommandId,
        owner: &str,
        fp: &str,
        at: &str,
    ) -> Result<Value> {
        a::pin(fp)?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let admission = admit(
            command,
            CommandKind::ConfirmFactorProposal,
            owner,
            "HUMAN",
            &json!({"proposal_fingerprint":fp}),
        )?;
        Commands::lock_command(&tx, command).await.map_err(db)?;
        if let Some(v) = replay(&tx, &admission, owner, "HUMAN").await? {
            tx.commit().await.map_err(db)?;
            return Ok(v);
        }
        let s = snapshot(&tx, fp, owner, None).await?;
        let fid = text(&s, "factor_id")?;
        let save = authoring_child(command, "save")?;
        let display = authoring_child(command, "display")?;
        Commands::lock_command(&tx, &save).await.map_err(db)?;
        Commands::lock_command(&tx, &display).await.map_err(db)?;
        lineage(&tx, fid).await?;
        if head(&tx, fid).await? != json!(fp) {
            return Err("FACTOR_PROPOSAL_STALE");
        }
        if tx
            .query_opt(
                "SELECT 1 FROM factor_proposal_confirmation WHERE proposal_fingerprint=$1",
                &[&fp],
            )
            .await
            .map_err(db)?
            .is_some()
        {
            return Err("FACTOR_PROPOSAL_ALREADY_CONFIRMED");
        }
        if withdrawn(&tx, fp, owner).await? {
            return Err("FACTOR_PROPOSAL_STALE");
        }
        let before = state(&tx, fid).await?;
        expected(&s, &before)?;
        let draft = Draft::new(s["preview"]["draft"].clone()).map_err(|e| e.code())?;
        let names =
            json!({"display_name":s["preview"]["name"],"usage_summary":s["preview"]["purpose"]});
        let effect=factors::apply_in_transaction(&tx,&save,fid,json!({"operation":"SAVE","factor_id":fid,"expected_draft_fingerprint":before["draft_fingerprint"],"draft":draft.record(),"initial_display":if before.is_null(){names.clone()}else{Value::Null}}),Some(draft),at).await.map_err(|e|e.code())?;
        let mut display_effect = Value::Null;
        if !before.is_null()
            && (before["display"]["display_name"] != names["display_name"]
                || before["display"]["usage_summary"] != names["usage_summary"])
        {
            display_effect=factors::apply_in_transaction(&tx,&display,fid,json!({"operation":"DISPLAY","factor_id":fid,"expected_display_fingerprint":before["display_fingerprint"],"display_name":names["display_name"],"usage_summary":names["usage_summary"],"actor_id":owner}),None,at).await.map_err(|e|e.code())?;
        }
        tx.execute(
            "INSERT INTO factor_proposal_confirmation VALUES($1,$2::text::uuid)",
            &[&fp, &command.value()],
        )
        .await
        .map_err(db)?;
        let v=finish(&tx,admission,owner,"HUMAN",&json!({"proposal_fingerprint":fp}),json!({"proposal_fingerprint":fp,"authoring":effect,"display_authoring":display_effect}),at).await?;
        tx.commit().await.map_err(db)?;
        Ok(v)
    }
    pub async fn read(
        &mut self,
        fp: &str,
        owner: &str,
        credential: Option<&Presented>,
        at: &str,
    ) -> Result<Value> {
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let mut service = None;
        let mut actual_owner = owner.to_owned();
        if let Some(c) = credential {
            let (_, g) = authorize(&tx, c, at).await?;
            service = Some(text(&g["input"], "service_subject")?.to_owned());
            actual_owner = text(&g, "owner")?.into()
        }
        let s = snapshot(&tx, fp, &actual_owner, service.as_deref()).await?;
        let current = head(&tx, text(&s, "factor_id")?).await? == json!(fp);
        let confirmed=tx.query_opt("SELECT command_id::text FROM factor_proposal_confirmation WHERE proposal_fingerprint=$1",&[&fp]).await.map_err(db)?;
        let confirmation = if let Some(row) = confirmed {
            let id = CommandId::new(&row.get::<_, String>(0)).map_err(db)?;
            let raw = operation_payload(&tx, &id).await?;
            if raw["kind"] != "CONFIRM_FACTOR_PROPOSAL"
                || raw["request"]["proposal_fingerprint"] != fp
                || raw["effect"]["proposal_fingerprint"] != fp
            {
                return Err("FACTOR_PROPOSAL_CORRUPT");
            }
            operation(&tx, &id, &actual_owner, Some("HUMAN")).await?
        } else {
            Value::Null
        };
        let withdrawn = withdrawn(&tx, fp, &actual_owner).await?;
        let v = json!({"schema_version":1,"fingerprint":fp,"snapshot":s,"is_current":current,"withdrawn":withdrawn,"confirmation":confirmation});
        tx.commit().await.map_err(db)?;
        Ok(v)
    }
    pub async fn observe(
        &mut self,
        id: &CommandId,
        owner: &str,
        credential: Option<&Presented>,
        at: &str,
    ) -> Result<Value> {
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let mut service = None;
        let mut actual_owner = owner.to_owned();
        if let Some(c) = credential {
            let (_, g) = authorize(&tx, c, at).await?;
            service = Some(text(&g["input"], "service_subject")?.to_owned());
            actual_owner = text(&g, "owner")?.into()
        }
        let v = operation(&tx, id, &actual_owner, service.as_deref()).await?;
        tx.commit().await.map_err(db)?;
        Ok(v)
    }
    /// Permission expiry also fences physical response release; no secret or Source grant escapes.
    pub async fn expiry(
        &mut self,
        c: &Presented,
        at: &str,
    ) -> Result<onlyalpha_domain::time::OnlyUtcDateTime> {
        let tx = self.client.transaction().await.map_err(db)?;
        let (_, g) = authorize(&tx, c, at).await?;
        let expiry = a::datetime(text(&g["input"], "expires_at")?)?;
        tx.commit().await.map_err(db)?;
        Ok(expiry)
    }
}
fn text<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str().ok_or(UNAVAILABLE)
}
async fn withdrawn(tx: &Transaction<'_>, fp: &str, owner: &str) -> Result<bool> {
    let row = tx
        .query_opt(
            "SELECT command_id::text FROM factor_proposal_withdrawal WHERE proposal_fingerprint=$1",
            &[&fp],
        )
        .await
        .map_err(db)?;
    let expected = command_intent(
        CommandKind::WithdrawFactorProposal,
        owner,
        "HUMAN",
        &json!({"proposal_fingerprint":fp}),
    )?;
    let related = tx.query("SELECT command_id::text FROM product_command_admission WHERE command_kind='WITHDRAW_FACTOR_PROPOSAL' AND command_fingerprint=$1 UNION SELECT command_id::text FROM product_command_receipt WHERE command_kind='WITHDRAW_FACTOR_PROPOSAL' AND command_fingerprint=$1 UNION SELECT command_id::text FROM factor_proposal_operation WHERE payload->>'kind'='WITHDRAW_FACTOR_PROPOSAL' AND (payload->'request'->>'proposal_fingerprint'=$2 OR payload->'effect'->>'proposal_fingerprint'=$2) LIMIT 2",&[&expected,&fp]).await.map_err(db)?;
    let Some(row) = row else {
        return if related.is_empty() {
            Ok(false)
        } else {
            Err("FACTOR_PROPOSAL_CORRUPT")
        };
    };
    let id = CommandId::new(&row.get::<_, String>(0)).map_err(db)?;
    if related.len() != 1 || related[0].get::<_, String>(0) != id.value() {
        return Err("FACTOR_PROPOSAL_CORRUPT");
    }
    let record = operation_payload(tx, &id).await?;
    if record["kind"] != "WITHDRAW_FACTOR_PROPOSAL"
        || record["request"]["proposal_fingerprint"] != fp
        || record["effect"]["proposal_fingerprint"] != fp
    {
        return Err("FACTOR_PROPOSAL_CORRUPT");
    }
    operation(tx, &id, owner, Some("HUMAN")).await?;
    Ok(true)
}
/// Live authorization, budget and revocation serialize on this original parent row.
pub(crate) async fn load_grant(tx: &Transaction<'_>, id: &str) -> Result<(String, Value)> {
    let row=tx.query_opt("SELECT fingerprint,payload::text FROM factor_proposal_grant WHERE grant_id=$1::text::uuid FOR UPDATE",&[&id]).await.map_err(db)?.ok_or("FACTOR_PROPOSAL_UNAUTHORIZED")?;
    verify_grant_record(tx, id, row).await
}
/// Retained immutable fact only; this does not authorize new work or spend budget.
pub(crate) async fn read_grant(tx: &Transaction<'_>, id: &str) -> Result<(String, Value)> {
    let row=tx.query_opt("SELECT fingerprint,payload::text FROM factor_proposal_grant WHERE grant_id=$1::text::uuid",&[&id]).await.map_err(db)?.ok_or("FACTOR_PROPOSAL_UNAUTHORIZED")?;
    verify_grant_record(tx, id, row).await
}
async fn verify_grant_record(
    tx: &Transaction<'_>,
    id: &str,
    row: tokio_postgres::Row,
) -> Result<(String, Value)> {
    let fp: String = row.get(0);
    let g = value(row.get(1))?;
    if hash(&g)? != fp || g["input"]["grant_id"] != id {
        return Err("FACTOR_PROPOSAL_CORRUPT");
    }
    let command = CommandId::new(text(&g, "command_id")?).map_err(db)?;
    let original = operation(tx, &command, text(&g, "owner")?, Some("HUMAN")).await?;
    if original["effect"]["grant_fingerprint"] != fp {
        return Err("FACTOR_PROPOSAL_CORRUPT");
    }
    Ok((fp, g))
}
/// Retained credential identity only. Expiry/revocation still fence every new operation.
pub(crate) async fn authenticate_retained(
    tx: &Transaction<'_>,
    c: &Presented,
) -> Result<(String, Value)> {
    let (fp, g) = load_grant(tx, &c.grant_id).await?;
    let digest = text(&g["input"], "credential_sha256")?;
    if !bool::from(digest.as_bytes().ct_eq(c.digest.as_bytes())) {
        return Err("FACTOR_PROPOSAL_UNAUTHORIZED");
    }
    Ok((fp, g))
}
pub(crate) async fn authorize(
    tx: &Transaction<'_>,
    c: &Presented,
    at: &str,
) -> Result<(String, Value)> {
    let (fp, g) = authenticate_retained(tx, c).await?;
    if a::datetime(text(&g["input"], "expires_at")?)? <= a::datetime(at)?
        || tx
            .query_opt(
                "SELECT 1 FROM factor_proposal_revocation WHERE grant_id=$1::text::uuid",
                &[&c.grant_id],
            )
            .await
            .map_err(db)?
            .is_some()
    {
        return Err("FACTOR_PROPOSAL_UNAUTHORIZED");
    }
    Ok((fp, g))
}
async fn lineage(tx: &Transaction<'_>, fid: &str) -> Result<()> {
    tx.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1,619))",
        &[&fid],
    )
    .await
    .map_err(db)?;
    Ok(())
}
/// Read the original Human acceptance at the owning boundary, under its existing
/// lineage lock for a new submission; historical reads use immutable acceptance. This is not a Research grant or an automatic Revision publication.
pub(crate) async fn confirmed_research_input(
    tx: &Transaction<'_>,
    proposal: &str,
    owner: &str,
    current: bool,
) -> Result<Value> {
    let s = snapshot(tx, proposal, owner, None).await?;
    let fid = text(&s, "factor_id")?;
    if current {
        lineage(tx, fid).await?;
    }
    if current
        && (head(tx, fid).await? != json!(proposal) || withdrawn(tx, proposal, owner).await?)
    {
        return Err("FACTOR_PROPOSAL_STALE");
    }
    let row = tx.query_opt("SELECT command_id::text FROM factor_proposal_confirmation WHERE proposal_fingerprint=$1", &[&proposal])
        .await.map_err(db)?.ok_or("FACTOR_PROPOSAL_NOT_CONFIRMED")?;
    let command = CommandId::new(&row.try_get::<_, String>(0).map_err(db)?).map_err(db)?;
    let accepted = operation(tx, &command, owner, Some("HUMAN")).await?;
    let raw = operation_payload(tx, &command).await?;
    if raw["kind"] != "CONFIRM_FACTOR_PROPOSAL"
        || raw["request"]["proposal_fingerprint"] != proposal
        || raw["effect"]["proposal_fingerprint"] != proposal
        || accepted["effect"]["authoring"]["result"]["draft"] != s["preview"]["draft"]
    {
        return Err("FACTOR_PROPOSAL_CORRUPT");
    }
    Ok(json!({"snapshot":s,"confirmation":accepted,"confirmation_command_id":command.value()}))
}
async fn head(tx: &Transaction<'_>, fid: &str) -> Result<Value> {
    let pointer = tx
        .query_opt(
            "SELECT fingerprint FROM factor_proposal_head WHERE factor_id=$1",
            &[&fid],
        )
        .await
        .map_err(db)?
        .map(|r| r.get::<_, String>(0));
    let rows = tx
        .query(
            "SELECT fingerprint,payload::text FROM factor_proposal_snapshot WHERE factor_id=$1",
            &[&fid],
        )
        .await
        .map_err(db)?;
    if rows.is_empty() {
        return if pointer.is_none() {
            Ok(Value::Null)
        } else {
            Err("FACTOR_PROPOSAL_CORRUPT")
        };
    }
    let mut children = BTreeMap::new();
    let mut pins = BTreeSet::new();
    for row in rows {
        let fp: String = row.get(0);
        let v = value(row.get(1))?;
        let s = snapshot(tx, &fp, text(&v, "owner")?, None).await?;
        if s["factor_id"] != fid {
            return Err("FACTOR_PROPOSAL_CORRUPT");
        }
        let parent = if s["supersedes"].is_null() {
            None
        } else {
            Some(text(&s, "supersedes")?.to_owned())
        };
        if children.insert(parent, fp.clone()).is_some() || !pins.insert(fp) {
            return Err("FACTOR_PROPOSAL_CORRUPT");
        }
    }
    let mut last = None;
    let mut visited = BTreeSet::new();
    while let Some(next) = children.get(&last) {
        if !visited.insert(next.clone()) {
            return Err("FACTOR_PROPOSAL_CORRUPT");
        }
        last = Some(next.clone());
    }
    if visited != pins || pointer != last {
        return Err("FACTOR_PROPOSAL_CORRUPT");
    }
    Ok(json!(last))
}
async fn state(tx: &Transaction<'_>, fid: &str) -> Result<Value> {
    if tx
        .query_opt(
            "SELECT factor_id FROM private_factor_asset WHERE factor_id=$1 FOR UPDATE",
            &[&fid],
        )
        .await
        .map_err(db)?
        .is_none()
    {
        return Ok(Value::Null);
    }
    factors::state(tx, fid).await.map_err(|e| e.code())
}
fn expected(s: &Value, current: &Value) -> Result<()> {
    if s["expected_draft_fingerprint"] != current["draft_fingerprint"]
        || s["expected_display_fingerprint"] != current["display_fingerprint"]
        || !current["current_revision_fingerprint"].is_null()
    {
        return Err("FACTOR_PROPOSAL_AUTHORING_CONFLICT");
    }
    Ok(())
}
async fn snapshot(
    tx: &Transaction<'_>,
    fp: &str,
    owner: &str,
    service: Option<&str>,
) -> Result<Value> {
    a::pin(fp)?;
    let row = tx
        .query_opt(
            "SELECT payload::text FROM factor_proposal_snapshot WHERE fingerprint=$1",
            &[&fp],
        )
        .await
        .map_err(db)?
        .ok_or("FACTOR_PROPOSAL_NOT_FOUND")?;
    let v = value(row.get(0))?;
    if hash(&v)? != fp {
        return Err("FACTOR_PROPOSAL_CORRUPT");
    }
    if v["owner"] != owner || service.is_some_and(|s| v["service_subject"] != s) {
        return Err("FACTOR_PROPOSAL_NOT_FOUND");
    }
    let command = CommandId::new(text(&v, "command_id")?).map_err(db)?;
    let record = operation_payload(tx, &command).await?;
    if record["kind"] != "STAGE_FACTOR_PROPOSAL" {
        return Err("FACTOR_PROPOSAL_CORRUPT");
    }
    let input: StageInput = serde_json::from_value(record["request"]["stage"].clone())
        .map_err(|_| "FACTOR_PROPOSAL_CORRUPT")?;
    if input.snapshot(
        owner,
        text(&v, "service_subject")?,
        text(&record["request"], "grant")?,
        command.value(),
    )? != v
    {
        return Err("FACTOR_PROPOSAL_CORRUPT");
    }
    let original = operation(tx, &command, owner, Some(text(&v, "service_subject")?)).await?;
    if original["effect"]["proposal_fingerprint"] != fp {
        return Err("FACTOR_PROPOSAL_CORRUPT");
    }
    Ok(v)
}
fn command_intent(kind: CommandKind, owner: &str, actor: &str, body: &Value) -> Result<String> {
    hash(
        &json!({"contract":"ONLYALPHA_FACTOR_PROPOSAL_COMMAND_V1","owner":owner,"actor":actor,"kind":kind.as_str(),"body":body}),
    )
}
fn admit(
    command: &CommandId,
    kind: CommandKind,
    owner: &str,
    actor: &str,
    body: &Value,
) -> Result<Admission> {
    Admission::new(
        command.clone(),
        kind,
        &command_intent(kind, owner, actor, body)?,
    )
    .map_err(db)
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
        Binding::None => Ok(None),
        Binding::Admitted(_) => Err("FACTOR_PROPOSAL_COMMAND_UNKNOWN"),
        Binding::Accepted(r) if r.admission() == a => {
            Ok(Some(operation(tx, a.id(), owner, Some(actor)).await?))
        }
        _ => Err("FACTOR_PROPOSAL_COMMAND_CONFLICT"),
    }
}
async fn operation_payload(tx: &Transaction<'_>, id: &CommandId) -> Result<Value> {
    let row = tx
        .query_opt(
            "SELECT payload::text FROM factor_proposal_operation WHERE command_id=$1::text::uuid",
            &[&id.value()],
        )
        .await
        .map_err(db)?
        .ok_or("FACTOR_PROPOSAL_CORRUPT")?;
    value(row.get(0))
}
async fn operation(
    tx: &Transaction<'_>,
    id: &CommandId,
    owner: &str,
    actor: Option<&str>,
) -> Result<Value> {
    let row=tx.query_opt("SELECT fingerprint,payload::text FROM factor_proposal_operation WHERE command_id=$1::text::uuid",&[&id.value()]).await.map_err(db)?;
    let Some(row) = row else {
        let binding = Commands::verify_binding_in_transaction(tx, id)
            .await
            .map_err(db)?;
        return if matches!(binding,Binding::Accepted(ref receipt) if matches!(receipt.admission().kind(),CommandKind::CreateProposalGrant|CommandKind::RevokeProposalGrant|CommandKind::StageFactorProposal|CommandKind::ConfirmFactorProposal|CommandKind::WithdrawFactorProposal))
        {
            Err("FACTOR_PROPOSAL_CORRUPT")
        } else {
            Err("FACTOR_PROPOSAL_COMMAND_UNKNOWN")
        };
    };
    let fp: String = row.get(0);
    let v = value(row.get(1))?;
    if hash(&v)? != fp || v["command_id"] != id.value() {
        return Err("FACTOR_PROPOSAL_CORRUPT");
    }
    if v["owner"] != owner || actor.is_some_and(|s| v["actor"] != s) {
        return Err("FACTOR_PROPOSAL_NOT_FOUND");
    }
    let binding = Commands::verify_binding_in_transaction(tx, id)
        .await
        .map_err(db)?;
    if !matches!(binding,Binding::Accepted(ref r) if r.admission().fingerprint()==text(&v,"intent")? && r.outcome().kind()==OutcomeKind::FactorProposalOperation && r.outcome().id()==fp && r.admission().kind().as_str()==v["kind"])
    {
        return Err("FACTOR_PROPOSAL_CORRUPT");
    }
    let Binding::Accepted(receipt) = binding else {
        return Err("FACTOR_PROPOSAL_CORRUPT");
    };
    if !v["request"].is_object()
        || admit(
            id,
            receipt.admission().kind(),
            owner,
            text(&v, "actor")?,
            &v["request"],
        )? != *receipt.admission()
    {
        return Err("FACTOR_PROPOSAL_CORRUPT");
    }
    if v["kind"] == "WITHDRAW_FACTOR_PROPOSAL" {
        let proposal = text(&v["request"], "proposal_fingerprint")?;
        a::pin(proposal)?;
        if v["actor"] != "HUMAN"
            || v["request"] != json!({"proposal_fingerprint":proposal})
            || v["effect"] != json!({"proposal_fingerprint":proposal})
        {
            return Err("FACTOR_PROPOSAL_CORRUPT");
        }
        Box::pin(snapshot(tx, proposal, owner, None)).await?;
        let marker=tx.query_opt("SELECT command_id::text FROM factor_proposal_withdrawal WHERE proposal_fingerprint=$1",&[&proposal]).await.map_err(db)?.ok_or("FACTOR_PROPOSAL_CORRUPT")?;
        if marker.get::<_, String>(0) != id.value() {
            return Err("FACTOR_PROPOSAL_CORRUPT");
        }
    }
    if v["kind"] == "CONFIRM_FACTOR_PROPOSAL" {
        let proposal = text(&v["request"], "proposal_fingerprint")?;
        let row = tx
            .query_opt(
                "SELECT payload::text FROM factor_proposal_snapshot WHERE fingerprint=$1",
                &[&proposal],
            )
            .await
            .map_err(db)?
            .ok_or("FACTOR_PROPOSAL_CORRUPT")?;
        let s = value(row.get(0))?;
        if hash(&s)? != proposal
            || s["owner"] != owner
            || v["actor"] != "HUMAN"
            || v["effect"]["proposal_fingerprint"] != proposal
            || !v["effect"]["authoring"].is_object()
        {
            return Err("FACTOR_PROPOSAL_CORRUPT");
        }
        for key in ["authoring", "display_authoring"] {
            let effect = &v["effect"][key];
            if effect.is_null() {
                continue;
            }
            let child = CommandId::new(text(effect, "command_id")?).map_err(db)?;
            let purpose = if key == "authoring" {
                "save"
            } else {
                "display"
            };
            if child != authoring_child(id, purpose)?
                || effect["factor_id"] != s["factor_id"]
                || key == "authoring" && effect["result"]["draft"] != s["preview"]["draft"]
            {
                return Err("FACTOR_PROPOSAL_CORRUPT");
            }
            if factors::bound(tx, text(effect, "factor_id")?, &child, None)
                .await
                .map_err(|e| e.code())?
                .as_ref()
                != Some(effect)
            {
                return Err("FACTOR_PROPOSAL_CORRUPT");
            }
        }
    }
    Ok(
        json!({"schema_version":1,"command_id":id.value(),"operation_fingerprint":fp,"effect":v["effect"]}),
    )
}
async fn finish(
    tx: &Transaction<'_>,
    admission: Admission,
    owner: &str,
    actor: &str,
    request: &Value,
    effect: Value,
    at: &str,
) -> Result<Value> {
    let command = admission.id().clone();
    let v = json!({"schema_version":1,"owner":owner,"actor":actor,"command_id":command.value(),"kind":admission.kind().as_str(),"intent":admission.fingerprint(),"request":request,"effect":effect,"accepted_at":at});
    let fp = hash(&v)?;
    Commands::admit_exact_in_transaction(tx, &admission)
        .await
        .map_err(db)?;
    tx.execute(
        "INSERT INTO factor_proposal_operation VALUES($1::text::uuid,$2,$3::text::jsonb)",
        &[&command.value(), &fp, &v.to_string()],
    )
    .await
    .map_err(db)?;
    Commands::put_verified_receipt_in_transaction(
        tx,
        &Receipt::new(
            admission,
            Outcome::new(OutcomeKind::FactorProposalOperation, &fp).map_err(db)?,
            at,
        )
        .map_err(db)?,
    )
    .await
    .map_err(db)?;
    Ok(
        json!({"schema_version":1,"command_id":command.value(),"operation_fingerprint":fp,"effect":v["effect"]}),
    )
}

pub(crate) fn authoring_child(command: &CommandId, purpose: &str) -> Result<CommandId> {
    let h = hash(&json!({"parent":command.value(),"purpose":purpose}))?;
    let mut b = h.into_bytes();
    b[12] = b'4';
    b[16] = b'8';
    let s = String::from_utf8(b).map_err(|_| INVALID)?;
    CommandId::new(&format!(
        "{}-{}-{}-{}-{}",
        &s[..8],
        &s[8..12],
        &s[12..16],
        &s[16..20],
        &s[20..32]
    ))
    .map_err(|_| INVALID)
}
