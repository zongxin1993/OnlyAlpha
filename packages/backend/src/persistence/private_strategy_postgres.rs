//! Existing Private Strategy tables own authoring; global Commands own accepted effects.
//! These records grant no Research, Freeze, Promotion or Runtime authority.
use crate::{
    application::{
        command::{Admission, Binding, CommandId, CommandKind, Outcome, OutcomeKind, Receipt},
        factor_content::hash,
        private_assets,
        private_strategy::Draft,
    },
    persistence::postgres::{Commands, bounds},
};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use tokio_postgres::{Client, Transaction};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "PRIVATE_STRATEGY_INVALID";
const CORRUPT: &str = "PRIVATE_STRATEGY_CORRUPT";
const UNAVAILABLE: &str = "PRIVATE_STRATEGY_AUTHORITY_UNAVAILABLE";
const UNKNOWN: &str = "PRIVATE_STRATEGY_COMMAND_UNKNOWN";
const CONFLICT: &str = "PRIVATE_STRATEGY_COMMAND_CONFLICT";
const DRAFT_CONFLICT: &str = "PRIVATE_STRATEGY_DRAFT_CONFLICT";
const MISSING: &str = "PRIVATE_STRATEGY_NOT_FOUND";
const DENIED: &str = "PRIVATE_STRATEGY_ACCESS_DENIED";
const WORK: usize = 8 * 1024 * 1024;
fn db(_: impl std::fmt::Debug) -> &'static str {
    UNAVAILABLE
}
fn command_error(error: crate::application::command::Error) -> &'static str {
    if error == crate::application::command::Error::Conflict {
        CONFLICT
    } else {
        UNAVAILABLE
    }
}
fn decode(raw: &str) -> Result<Value> {
    if raw.len() > WORK {
        return Err(UNAVAILABLE);
    }
    serde_json::from_str(raw).map_err(|_| CORRUPT)
}
fn fields(value: &Value, expected: &[&str]) -> Result<()> {
    let object = value.as_object().ok_or(CORRUPT)?;
    if object.len() != expected.len() || expected.iter().any(|key| !object.contains_key(*key)) {
        return Err(CORRUPT);
    }
    Ok(())
}
fn valid_id(id: &str) -> Result<()> {
    private_assets::id(id, "STRATEGY").map_err(|_| INVALID)
}
fn owner(value: &str) -> Result<()> {
    if value.trim().is_empty() || value.len() > 512 || value.chars().any(char::is_control) {
        return Err(INVALID);
    }
    Ok(())
}
fn recognized(kind: CommandKind) -> bool {
    matches!(
        kind,
        CommandKind::SavePrivateStrategyDraft | CommandKind::PublishPrivateStrategyRevision
    )
}
fn intent(owner: &str, input: &Value) -> Result<String> {
    hash(
        &json!({"contract":"ONLYALPHA_PRIVATE_STRATEGY_AUTHORING_INTENT_V1","owner":owner,"input":input}),
    )
}
fn outcome(record: &Value) -> Result<String> {
    hash(&json!({"contract":"ONLYALPHA_PRIVATE_STRATEGY_AUTHORING_OUTCOME_V1","outcome":record}))
}
fn public(record: &Value) -> Value {
    json!({"schema_version":1,"command_id":record["command_id"],"strategy_id":record["strategy_id"],"result":record["result"]})
}
pub struct Strategies<'a> {
    client: &'a mut Client,
}
impl<'a> Strategies<'a> {
    pub fn new(client: &'a mut Client) -> Self {
        Self { client }
    }
    pub async fn exact(&mut self, id: &str, revision: &str, content: &str) -> Result<Value> {
        valid_id(id)?;
        if !crate::is_sha256_hex(revision) || !crate::is_sha256_hex(content) {
            return Err(INVALID);
        }
        let tx = self
            .client
            .build_transaction()
            .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(db)?;
        bounds(&tx).await.map_err(command_error)?;
        let value = private_assets::strategy_revision_in_transaction(&tx, id, revision)
            .await
            .map_err(|e| match e {
                private_assets::Error::Unavailable => UNAVAILABLE,
                private_assets::Error::NotFound => "PRIVATE_ASSET_EXACT_REVISION_UNAVAILABLE",
                private_assets::Error::Invalid => INVALID,
                _ => CORRUPT,
            })?;
        if value["definition_fingerprint"] != content {
            return Err("PRIVATE_ASSET_EXACT_READ_MISMATCH");
        }
        tx.commit().await.map_err(db)?;
        Ok(value)
    }
    pub async fn read(&mut self, id: &str) -> Result<Value> {
        valid_id(id)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(db)?;
        bounds(&tx).await.map_err(command_error)?;
        let result = state(&tx, id).await?;
        tx.commit().await.map_err(db)?;
        Ok(result)
    }
    pub async fn list(&mut self) -> Result<Value> {
        let tx = self
            .client
            .build_transaction()
            .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(db)?;
        bounds(&tx).await.map_err(command_error)?;
        let rows = tx
            .query(
                "SELECT strategy_id FROM private_strategy_asset ORDER BY strategy_id LIMIT 201",
                &[],
            )
            .await
            .map_err(db)?;
        if rows.len() > 200 {
            return Err(UNAVAILABLE);
        }
        let mut entries = vec![];
        let mut work = 0usize;
        for row in rows {
            let id: String = row.try_get(0).map_err(|_| CORRUPT)?;
            let value = state(&tx, &id).await?;
            work = work
                .checked_add(value.to_string().len())
                .ok_or(UNAVAILABLE)?;
            if work > WORK {
                return Err(UNAVAILABLE);
            }
            entries.push(json!({"strategy_id":id,"current_revision_fingerprint":value["current_revision_fingerprint"],"has_draft":!value["draft"].is_null(),"description":value["draft"]["description"]}));
        }
        tx.commit().await.map_err(db)?;
        Ok(json!({"schema_version":1,"entries":entries}))
    }
    pub async fn command(&mut self, id: &str, actor: &str, command: &CommandId) -> Result<Value> {
        valid_id(id)?;
        owner(actor)?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(command_error)?;
        Commands::lock_command(&tx, command)
            .await
            .map_err(command_error)?;
        let value = bound(&tx, id, actor, command, None)
            .await?
            .unwrap_or(Value::Null);
        tx.commit().await.map_err(db)?;
        Ok(value)
    }
    pub async fn save(
        &mut self,
        command: &CommandId,
        actor: &str,
        id: &str,
        value: Value,
        expected: Option<&str>,
        at: &str,
    ) -> Result<Value> {
        valid_id(id)?;
        owner(actor)?;
        let draft = Draft::new(value)?;
        if draft.strategy_id() != id || expected.is_some_and(|s| !crate::is_sha256_hex(s)) {
            return Err(INVALID);
        }
        let input = json!({"operation":"SAVE","strategy_id":id,"expected_draft_fingerprint":expected,"draft":draft.record()});
        self.apply(command, actor, id, input, Some(draft), at).await
    }
    pub async fn publish(
        &mut self,
        command: &CommandId,
        actor: &str,
        id: &str,
        expected: &str,
        at: &str,
    ) -> Result<Value> {
        valid_id(id)?;
        owner(actor)?;
        if !crate::is_sha256_hex(expected) {
            return Err(INVALID);
        }
        let input =
            json!({"operation":"PUBLISH","strategy_id":id,"expected_draft_fingerprint":expected});
        self.apply(command, actor, id, input, None, at).await
    }
    async fn apply(
        &mut self,
        command: &CommandId,
        actor: &str,
        id: &str,
        input: Value,
        proposed: Option<Draft>,
        at: &str,
    ) -> Result<Value> {
        let kind = if proposed.is_some() {
            CommandKind::SavePrivateStrategyDraft
        } else {
            CommandKind::PublishPrivateStrategyRevision
        };
        let admission =
            Admission::new(command.clone(), kind, &intent(actor, &input)?).map_err(|_| INVALID)?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(command_error)?;
        Commands::lock_command(&tx, command)
            .await
            .map_err(command_error)?;
        if let Some(value) = bound(&tx, id, actor, command, Some(&admission)).await? {
            tx.commit().await.map_err(db)?;
            return Ok(value);
        }
        if proposed.is_some() {
            // Existing assets only take their own row lock; creation also protects capacity.
            if tx
                .query_opt(
                    "SELECT strategy_id FROM private_strategy_asset WHERE strategy_id=$1",
                    &[&id],
                )
                .await
                .map_err(db)?
                .is_none()
            {
                tx.execute("SELECT pg_advisory_xact_lock(hashtextextended('ONLYALPHA_PRIVATE_STRATEGY_INVENTORY',0))",&[]).await.map_err(db)?;
                let count: i64 = tx
                    .query_one("SELECT count(*) FROM private_strategy_asset", &[])
                    .await
                    .map_err(db)?
                    .try_get(0)
                    .map_err(|_| CORRUPT)?;
                if count >= 200 {
                    return Err(UNAVAILABLE);
                }
            }
            tx.execute("INSERT INTO private_strategy_asset(strategy_id,schema_version) VALUES($1,1) ON CONFLICT DO NOTHING",&[&id]).await.map_err(db)?;
        }
        tx.query_opt(
            "SELECT strategy_id FROM private_strategy_asset WHERE strategy_id=$1 FOR UPDATE",
            &[&id],
        )
        .await
        .map_err(db)?
        .ok_or(MISSING)?;
        let current = state(&tx, id).await?;
        if current["draft_fingerprint"] != input["expected_draft_fingerprint"] {
            return Err(DRAFT_CONFLICT);
        }
        let draft = match proposed {
            Some(d) => d,
            None => Draft::new(current["draft"].clone()).map_err(|_| CORRUPT)?,
        };
        if draft.base() != current["current_revision_fingerprint"].as_str() {
            return Err(DRAFT_CONFLICT);
        }
        let base = draft.base();
        let draft_pin = draft.fingerprint()?;
        // Exact authoring dependencies are checked by their owner, never by current/latest.
        for dependency in draft.record()["definition"]["factor_revision_dependencies"]
            .as_array()
            .ok_or(CORRUPT)?
        {
            let factor = dependency["factor_id"].as_str().ok_or(CORRUPT)?;
            let pin = dependency["revision_fingerprint"].as_str().ok_or(CORRUPT)?;
            let revision = private_assets::factor_revision_in_transaction(&tx, factor, pin)
                .await
                .map_err(|error| match error {
                    private_assets::Error::Unavailable => UNAVAILABLE,
                    private_assets::Error::NotFound => {
                        "PRIVATE_STRATEGY_FACTOR_REVISION_UNAVAILABLE"
                    }
                    _ => CORRUPT,
                })?;
            if revision["factor_id"] != factor || revision["revision_fingerprint"] != pin {
                return Err(CORRUPT);
            }
            for calculation in draft.record()["definition"]["calculations"]
                .as_array()
                .ok_or(CORRUPT)?
            {
                if calculation["type_reference"]["type_id"] == factor
                    && calculation["type_reference"]["semantic_version"]
                        != revision["semantic_version"]
                {
                    return Err("PRIVATE_STRATEGY_FACTOR_REVISION_MISMATCH");
                }
            }
        }
        let revision = if kind == CommandKind::SavePrivateStrategyDraft {
            tx.execute("INSERT INTO private_strategy_draft(strategy_id,base_revision_fingerprint,payload,schema_version) VALUES($1,$2,$3::text::jsonb,1) ON CONFLICT(strategy_id) DO UPDATE SET base_revision_fingerprint=EXCLUDED.base_revision_fingerprint,payload=EXCLUDED.payload",&[&id,&base,&draft.record().to_string()]).await.map_err(db)?;
            Value::Null
        } else {
            let revision = draft.revision()?;
            let pin = revision["revision_fingerprint"].as_str().ok_or(CORRUPT)?;
            let definition = revision["definition_fingerprint"].as_str().ok_or(CORRUPT)?;
            tx.execute("INSERT INTO private_strategy_revision(revision_fingerprint,strategy_id,parent_revision_fingerprint,definition_fingerprint,payload,schema_version) VALUES($1,$2,$3,$4,$5::text::jsonb,1)",&[&pin,&id,&base,&definition,&revision.to_string()]).await.map_err(db)?;
            tx.execute("UPDATE private_strategy_asset SET current_revision_fingerprint=$2 WHERE strategy_id=$1",&[&id,&pin]).await.map_err(db)?;
            revision
        };
        state(&tx, id).await?;
        let record = json!({"schema_version":1,"command_id":command.value(),"strategy_id":id,"owner":actor,"input":input,"result":{"draft":draft.record(),"draft_fingerprint":draft_pin,"revision":revision}});
        let pin = outcome(&record)?;
        Commands::admit_exact_in_transaction(&tx, &admission)
            .await
            .map_err(command_error)?;
        tx.execute("INSERT INTO private_strategy_authoring_outcome(command_id,strategy_id,owner,fingerprint,payload,schema_version) VALUES($1::text::uuid,$2,$3,$4,$5::text::jsonb,1)",&[&command.value(),&id,&actor,&pin,&record.to_string()]).await.map_err(db)?;
        let receipt = Receipt::new(
            admission,
            Outcome::new(OutcomeKind::PrivateStrategyAuthoring, &pin).map_err(|_| INVALID)?,
            at,
        )
        .map_err(|_| INVALID)?;
        Commands::put_verified_receipt_in_transaction(&tx, &receipt)
            .await
            .map_err(command_error)?;
        let response = bound(&tx, id, actor, command, Some(receipt.admission()))
            .await?
            .ok_or(CORRUPT)?;
        tx.commit().await.map_err(|_| UNKNOWN)?;
        Ok(response)
    }
}
async fn bound(
    tx: &Transaction<'_>,
    id: &str,
    actor: &str,
    command: &CommandId,
    expected: Option<&Admission>,
) -> Result<Option<Value>> {
    let binding = Commands::verify_binding_in_transaction(tx, command)
        .await
        .map_err(command_error)?;
    let row=tx.query_opt("SELECT strategy_id,owner,fingerprint,CASE WHEN octet_length(payload::text)<=8388608 THEN payload::text ELSE NULL END AS payload,schema_version FROM private_strategy_authoring_outcome WHERE command_id=$1::text::uuid",&[&command.value()]).await.map_err(db)?;
    let receipt = match binding {
        Binding::None => {
            if row.is_some() {
                return Err(CORRUPT);
            }
            return Ok(None);
        }
        Binding::Admitted(a) => {
            if !recognized(a.kind()) || expected.is_some_and(|e| e != &a) {
                return Err(CONFLICT);
            }
            if row.is_some() {
                return Err(CORRUPT);
            }
            return Err(UNKNOWN);
        }
        Binding::Accepted(r) => r,
    };
    if !recognized(receipt.admission().kind()) || expected.is_some_and(|e| e != receipt.admission())
    {
        return Err(CONFLICT);
    }
    let row = row.ok_or(CORRUPT)?;
    if row.try_get::<_, String>("owner").map_err(|_| CORRUPT)? != actor {
        return Err(DENIED);
    }
    if row
        .try_get::<_, String>("strategy_id")
        .map_err(|_| CORRUPT)?
        != id
    {
        return Err(CONFLICT);
    }
    let raw: Option<String> = row.try_get("payload").map_err(|_| CORRUPT)?;
    let record = decode(&raw.ok_or(UNAVAILABLE)?)?;
    let pin: String = row.try_get("fingerprint").map_err(|_| CORRUPT)?;
    fields(
        &record,
        &[
            "schema_version",
            "command_id",
            "strategy_id",
            "owner",
            "input",
            "result",
        ],
    )?;
    fields(
        &record["result"],
        &["draft", "draft_fingerprint", "revision"],
    )?;
    let keys = if receipt.admission().kind() == CommandKind::SavePrivateStrategyDraft {
        &[
            "operation",
            "strategy_id",
            "expected_draft_fingerprint",
            "draft",
        ][..]
    } else {
        &["operation", "strategy_id", "expected_draft_fingerprint"][..]
    };
    fields(&record["input"], keys)?;
    let prior = &record["input"]["expected_draft_fingerprint"];
    if !prior.is_null() && !prior.as_str().is_some_and(crate::is_sha256_hex) {
        return Err(CORRUPT);
    }

    if row
        .try_get::<_, i32>("schema_version")
        .map_err(|_| CORRUPT)?
        != 1
        || record["schema_version"] != 1
        || record["command_id"] != command.value()
        || record["strategy_id"] != id
        || record["owner"] != actor
        || outcome(&record)? != pin
        || receipt.outcome().kind() != OutcomeKind::PrivateStrategyAuthoring
        || receipt.outcome().id() != pin
        || intent(actor, &record["input"])? != receipt.admission().fingerprint()
    {
        return Err(CORRUPT);
    }
    let result = &record["result"];
    let draft = Draft::new(result["draft"].clone()).map_err(|_| CORRUPT)?;
    if draft.record() != &result["draft"]
        || draft.strategy_id() != id
        || result["draft_fingerprint"] != draft.fingerprint()?
        || record["input"]["strategy_id"] != id
    {
        return Err(CORRUPT);
    }
    if receipt.admission().kind() == CommandKind::SavePrivateStrategyDraft {
        if record["input"]["operation"] != "SAVE"
            || record["input"]["draft"] != *draft.record()
            || !result["revision"].is_null()
        {
            return Err(CORRUPT);
        }
    } else {
        if record["input"]["operation"] != "PUBLISH"
            || record["input"]["expected_draft_fingerprint"] != result["draft_fingerprint"]
            || draft.revision()? != result["revision"]
        {
            return Err(CORRUPT);
        }
        let pin = result["revision"]["revision_fingerprint"]
            .as_str()
            .ok_or(CORRUPT)?;
        let owning=tx.query_opt("SELECT payload::text FROM private_strategy_revision WHERE strategy_id=$1 AND revision_fingerprint=$2",&[&id,&pin]).await.map_err(db)?.ok_or(CORRUPT)?;
        if decode(&owning.try_get::<_, String>(0).map_err(|_| CORRUPT)?)? != result["revision"] {
            return Err(CORRUPT);
        }
    }
    Ok(Some(public(&record)))
}
async fn state(tx: &Transaction<'_>, id: &str) -> Result<Value> {
    let asset=tx.query_opt("SELECT current_revision_fingerprint,schema_version FROM private_strategy_asset WHERE strategy_id=$1",&[&id]).await.map_err(db)?.ok_or(MISSING)?;
    if asset.try_get::<_, i32>(1).map_err(|_| CORRUPT)? != 1 {
        return Err(CORRUPT);
    }
    let head: Option<String> = asset.try_get(0).map_err(|_| CORRUPT)?;
    let size=tx.query_one("SELECT count(*),COALESCE(sum(octet_length(payload::text)),0)::bigint FROM private_strategy_revision WHERE strategy_id=$1",&[&id]).await.map_err(db)?;
    if size.try_get::<_, i64>(0).map_err(|_| CORRUPT)? > 200
        || size.try_get::<_, i64>(1).map_err(|_| CORRUPT)? > WORK as i64
    {
        return Err(UNAVAILABLE);
    }
    let rows=tx.query("SELECT revision_fingerprint,parent_revision_fingerprint,definition_fingerprint,payload::text,schema_version FROM private_strategy_revision WHERE strategy_id=$1 ORDER BY revision_fingerprint LIMIT 201",&[&id]).await.map_err(db)?;
    let mut history = BTreeMap::new();
    for row in rows {
        let value = decode(&row.try_get::<_, String>(3).map_err(|_| CORRUPT)?)?;
        private_assets::revision("STRATEGY", &value).map_err(|error| {
            if error == private_assets::Error::Unavailable {
                UNAVAILABLE
            } else {
                CORRUPT
            }
        })?;
        let pin: String = row.try_get(0).map_err(|_| CORRUPT)?;
        let parent: Option<String> = row.try_get(1).map_err(|_| CORRUPT)?;
        let definition: String = row.try_get(2).map_err(|_| CORRUPT)?;
        if row.try_get::<_, i32>(4).map_err(|_| CORRUPT)? != 1
            || value["strategy_id"] != id
            || value["revision_fingerprint"] != pin
            || value["parent_revision_fingerprint"].as_str() != parent.as_deref()
            || value["definition_fingerprint"] != definition
        {
            return Err(CORRUPT);
        }
        history.insert(pin, value);
    }
    let mut next = head.as_deref();
    let mut seen = BTreeSet::new();
    let mut revisions = vec![];
    while let Some(pin) = next {
        if !seen.insert(pin.to_owned()) {
            return Err(CORRUPT);
        }
        let value = history.get(pin).ok_or(CORRUPT)?;
        revisions.push(value.clone());
        next = value["parent_revision_fingerprint"].as_str();
    }
    if seen.len() != history.len() {
        return Err(CORRUPT);
    }
    revisions.reverse();
    let saved=tx.query_opt("SELECT base_revision_fingerprint,CASE WHEN octet_length(payload::text)<=262144 THEN payload::text ELSE NULL END,schema_version FROM private_strategy_draft WHERE strategy_id=$1",&[&id]).await.map_err(db)?;
    let (draft, pin) = if let Some(row) = saved {
        let raw: Option<String> = row.try_get(1).map_err(|_| CORRUPT)?;
        let value = decode(&raw.ok_or(UNAVAILABLE)?)?;
        let draft = Draft::new(value.clone()).map_err(|_| CORRUPT)?;
        let base: Option<String> = row.try_get(0).map_err(|_| CORRUPT)?;
        if row.try_get::<_, i32>(2).map_err(|_| CORRUPT)? != 1
            || draft.record() != &value
            || draft.strategy_id() != id
            || draft.base() != base.as_deref()
            || base.as_ref().is_some_and(|p| !history.contains_key(p))
        {
            return Err(CORRUPT);
        }
        (value, json!(draft.fingerprint()?))
    } else {
        (Value::Null, Value::Null)
    };
    Ok(
        json!({"schema_version":1,"strategy_id":id,"current_revision_fingerprint":head,"draft":draft,"draft_fingerprint":pin,"revisions":revisions}),
    )
}
