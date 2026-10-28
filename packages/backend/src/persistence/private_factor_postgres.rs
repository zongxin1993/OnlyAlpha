//! Existing Private Asset tables own authoring; global Commands own retries.
use crate::application::command::{
    Admission, Binding, CommandId, CommandKind, Outcome, OutcomeKind, Receipt,
};
use crate::application::private_assets::authoring::{
    Draft, fingerprint, validate_id, validate_revision,
};
use crate::application::private_assets::display::{self, Display};
use crate::application::private_assets::{Error, row};
use crate::persistence::postgres::{Commands, bounds};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use tokio_postgres::{Client, IsolationLevel, Transaction};
type Result<T> = std::result::Result<T, Error>;
const WORK: usize = 8 * 1024 * 1024;
fn unavailable(_: impl std::fmt::Debug) -> Error {
    Error::Unavailable
}
fn command_error(e: crate::application::command::Error) -> Error {
    if e == crate::application::command::Error::Conflict {
        Error::CommandConflict
    } else {
        Error::Unavailable
    }
}
fn payload(raw: &str) -> Result<Value> {
    if raw.len() > WORK {
        return Err(Error::Unavailable);
    }
    serde_json::from_str(raw).map_err(|_| Error::Corrupt)
}
pub struct Factors<'a> {
    client: &'a mut Client,
}
impl<'a> Factors<'a> {
    pub fn new(client: &'a mut Client) -> Self {
        Self { client }
    }
    pub async fn read(&mut self, id: &str) -> Result<Value> {
        validate_id(id)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(unavailable)?;
        bounds(&tx).await.map_err(command_error)?;
        let result = state(&tx, id).await?;
        tx.commit().await.map_err(unavailable)?;
        Ok(result)
    }
    pub async fn list(&mut self) -> Result<Value> {
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(unavailable)?;
        bounds(&tx).await.map_err(command_error)?;
        let rows = tx
            .query(
                "SELECT factor_id FROM private_factor_asset ORDER BY factor_id LIMIT 201",
                &[],
            )
            .await
            .map_err(unavailable)?;
        if rows.len() > 200 {
            return Err(Error::Unavailable);
        }
        let count = rows.len();
        let mut entries = vec![];
        for row in rows {
            let id: String = row.try_get(0).map_err(|_| Error::Corrupt)?;
            let value = state(&tx, &id).await?;
            entries.push(json!({"factor_id":id,"display":value["display"],"display_fingerprint":value["display_fingerprint"],"has_draft":!value["draft"].is_null(),"current_revision_fingerprint":value["current_revision_fingerprint"],"current_display_version":value["revisions"].as_array().and_then(|v|v.last()).map(|v|v["display_version"].clone())}));
        }
        tx.commit().await.map_err(unavailable)?;
        Ok(
            json!({"schema_version":1,"factor_api_version":1,"factor_api_contract_fingerprint":crate::application::private_assets::authoring::API_FINGERPRINT,"entries":entries,"new_factor_defaults":display::defaults(count+1)}),
        )
    }
    pub async fn command(&mut self, id: &str, command: &CommandId) -> Result<Value> {
        validate_id(id)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(unavailable)?;
        Commands::lock_command(&tx, command)
            .await
            .map_err(command_error)?;
        let result = bound(&tx, id, command, None).await?.unwrap_or(Value::Null);
        tx.commit().await.map_err(unavailable)?;
        Ok(result)
    }
    pub async fn save(
        &mut self,
        command: &CommandId,
        id: &str,
        value: Value,
        expected: Option<&str>,
        initial_display: Option<Value>,
        at: &str,
    ) -> Result<Value> {
        let draft = Draft::new(value)?;
        if draft.factor_id() != id || expected.is_some_and(|v| !crate::is_sha256_hex(v)) {
            return Err(Error::Invalid);
        }
        if let Some(names) = &initial_display {
            Display::create(id, names)?;
        }
        let input = json!({"operation":"SAVE","factor_id":id,"expected_draft_fingerprint":expected,"draft":draft.record(),"initial_display":initial_display});
        self.apply(command, id, input, Some(draft), at).await
    }
    pub async fn publish(
        &mut self,
        command: &CommandId,
        id: &str,
        expected: &str,
        at: &str,
    ) -> Result<Value> {
        validate_id(id)?;
        if !crate::is_sha256_hex(expected) {
            return Err(Error::Invalid);
        }
        let input =
            json!({"operation":"PUBLISH","factor_id":id,"expected_draft_fingerprint":expected});
        self.apply(command, id, input, None, at).await
    }
    pub async fn update_display(
        &mut self,
        command: &CommandId,
        id: &str,
        expected: &str,
        names: Value,
        actor_id: &str,
        at: &str,
    ) -> Result<Value> {
        validate_id(id)?;
        Display::create(id, &names)?;
        if !crate::is_sha256_hex(expected)
            || actor_id.is_empty()
            || actor_id.len() > 512
            || actor_id.chars().any(char::is_control)
        {
            return Err(Error::Invalid);
        }
        let input = json!({"operation":"DISPLAY","factor_id":id,"expected_display_fingerprint":expected,"display_name":names["display_name"],"usage_summary":names["usage_summary"],"actor_id":actor_id});
        self.apply(command, id, input, None, at).await
    }
    async fn apply(
        &mut self,
        command: &CommandId,
        id: &str,
        input: Value,
        proposed: Option<Draft>,
        at: &str,
    ) -> Result<Value> {
        let kind = match input["operation"].as_str() {
            Some("SAVE") => CommandKind::SavePrivateFactorDraft,
            Some("PUBLISH") => CommandKind::PublishPrivateFactorRevision,
            Some("DISPLAY") => CommandKind::UpdatePrivateFactorDisplay,
            _ => return Err(Error::Invalid),
        };
        let intent = fingerprint(
            &json!({"contract":"ONLYALPHA_PRIVATE_FACTOR_AUTHORING_INTENT_V1","input":input}),
        )?;
        let admission =
            Admission::new(command.clone(), kind, &intent).map_err(|_| Error::Invalid)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(unavailable)?;
        Commands::lock_command(&tx, command)
            .await
            .map_err(command_error)?;
        if let Some(result) = bound(&tx, id, command, Some(&admission)).await? {
            tx.commit().await.map_err(unavailable)?;
            return Ok(result);
        }
        if proposed.is_some() {
            let mut next_number = 0;
            // Serialize only creation capacity checks, after the global Command
            // lock and before any Asset row lock. Existing Assets need no slot.
            if tx
                .query_opt(
                    "SELECT factor_id FROM private_factor_asset WHERE factor_id=$1",
                    &[&id],
                )
                .await
                .map_err(unavailable)?
                .is_none()
            {
                tx.execute("SELECT pg_advisory_xact_lock(hashtextextended('ONLYALPHA_PRIVATE_FACTOR_INVENTORY',0))", &[]).await.map_err(unavailable)?;
                let slots = tx
                    .query(
                        "SELECT factor_id FROM private_factor_asset ORDER BY factor_id LIMIT 200",
                        &[],
                    )
                    .await
                    .map_err(unavailable)?;
                next_number = slots.len() + 1;
                if slots.len() == 200 && !slots.iter().any(|row| row.get::<_, String>(0) == id) {
                    return Err(Error::Unavailable);
                }
            }
            let created=tx.query_opt("INSERT INTO private_factor_asset(factor_id,schema_version) VALUES($1,1) ON CONFLICT DO NOTHING RETURNING factor_id",&[&id]).await.map_err(unavailable)?.is_some();
            if created {
                let names = if input["initial_display"].is_null() {
                    display::defaults(next_number)
                } else {
                    input["initial_display"].clone()
                };
                let label = Display::create(id, &names)?;
                let raw = label.record().to_string();
                let pin = label.fingerprint()?;
                tx.execute("INSERT INTO private_factor_display(factor_id,payload,fingerprint,schema_version) VALUES($1,$2::text::jsonb,$3,1)",&[&id,&raw,&pin]).await.map_err(unavailable)?;
            } else if !input["initial_display"].is_null() {
                return Err(Error::Invalid);
            }
        }
        tx.query_opt(
            "SELECT factor_id FROM private_factor_asset WHERE factor_id=$1 FOR UPDATE",
            &[&id],
        )
        .await
        .map_err(unavailable)?
        .ok_or(Error::NotFound)?;
        let current = state(&tx, id).await?;
        let result = if kind == CommandKind::UpdatePrivateFactorDisplay {
            if current["display_fingerprint"] != input["expected_display_fingerprint"] {
                return Err(Error::DisplayConflict);
            }
            let previous = Display::new(current["display"].clone()).map_err(|_| Error::Corrupt)?;
            let label = previous.update(
                input["display_name"].as_str().ok_or(Error::Invalid)?,
                input["usage_summary"].as_str().ok_or(Error::Invalid)?,
            )?;
            let pin = label.fingerprint()?;
            let raw = label.record().to_string();
            tx.execute("UPDATE private_factor_display SET payload=$2::text::jsonb,fingerprint=$3 WHERE factor_id=$1",&[&id,&raw,&pin]).await.map_err(unavailable)?;
            state(&tx, id).await?;
            json!({"draft":null,"draft_fingerprint":null,"revision":null,"display":label.record(),"display_fingerprint":pin,"display_version":null})
        } else {
            if current["draft_fingerprint"] != input["expected_draft_fingerprint"] {
                return Err(Error::DraftConflict);
            }
            let draft = match proposed {
                Some(draft) => draft,
                None => Draft::new(current["draft"].clone()).map_err(|_| Error::Corrupt)?,
            };
            if current["current_revision_fingerprint"].as_str() != draft.base() {
                return Err(Error::DraftConflict);
            }
            let pin = draft.fingerprint()?;
            let revision = if kind == CommandKind::PublishPrivateFactorRevision {
                draft.revision()?
            } else {
                Value::Null
            };
            if revision.is_null() {
                let raw = draft.record().to_string();
                let base = draft.base();
                tx.execute("INSERT INTO private_factor_draft(factor_id,base_revision_fingerprint,payload,schema_version) VALUES($1,$2,$3::text::jsonb,1) ON CONFLICT(factor_id) DO UPDATE SET base_revision_fingerprint=EXCLUDED.base_revision_fingerprint,payload=EXCLUDED.payload",&[&id,&base,&raw]).await.map_err(unavailable)?;
            } else {
                let fp = revision["revision_fingerprint"]
                    .as_str()
                    .ok_or(Error::Corrupt)?;
                let source = revision["source_text"].as_str().ok_or(Error::Corrupt)?;
                let sha = revision["source_sha256"].as_str().ok_or(Error::Corrupt)?;
                let base = draft.base();
                let raw = revision.to_string();
                tx.execute("INSERT INTO private_factor_revision(revision_fingerprint,factor_id,parent_revision_fingerprint,source_text,source_sha256,payload,schema_version) VALUES($1,$2,$3,$4,$5,$6::text::jsonb,1)",&[&fp,&id,&base,&source,&sha,&raw]).await.map_err(unavailable)?;
                tx.execute("UPDATE private_factor_asset SET current_revision_fingerprint=$2 WHERE factor_id=$1",&[&id,&fp]).await.map_err(unavailable)?;
            }
            // Acceptance must never commit a state that the owning reader rejects.
            // This also checks PostgreSQL's expanded JSONB representation, not just
            // the compact request bytes. Any failure rolls back the whole effect.
            let after = state(&tx, id).await?;
            json!({"draft":draft.record(),"draft_fingerprint":pin,"revision":revision,"display":after["display"],"display_fingerprint":after["display_fingerprint"],"display_version":if kind==CommandKind::PublishPrivateFactorRevision {after["revisions"].as_array().and_then(|v|v.last()).map(|v|v["display_version"].clone())}else{None}})
        };
        let record = json!({"schema_version":1,"command_id":command.value(),"factor_id":id,"input":input,"result":result});
        let identity = outcome_fingerprint(&record)?;
        Commands::admit_exact_in_transaction(&tx, &admission)
            .await
            .map_err(command_error)?;
        let raw = record.to_string();
        tx.execute("INSERT INTO private_factor_authoring_outcome(command_id,factor_id,fingerprint,payload,schema_version) VALUES($1::text::uuid,$2,$3,$4::text::jsonb,1)",&[&command.value(),&id,&identity,&raw]).await.map_err(unavailable)?;
        let receipt = Receipt::new(
            admission,
            Outcome::new(OutcomeKind::PrivateFactorAuthoring, &identity)
                .map_err(|_| Error::Invalid)?,
            at,
        )
        .map_err(|_| Error::Invalid)?;
        Commands::put_verified_receipt_in_transaction(&tx, &receipt)
            .await
            .map_err(command_error)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(public(&record))
    }
}
fn outcome_fingerprint(record: &Value) -> Result<String> {
    fingerprint(
        &json!({"contract":"ONLYALPHA_PRIVATE_FACTOR_AUTHORING_OUTCOME_V1","outcome":record}),
    )
}
fn public(record: &Value) -> Value {
    json!({"schema_version":1,"command_id":record["command_id"],"factor_id":record["factor_id"],"result":record["result"]})
}
async fn bound(
    tx: &Transaction<'_>,
    id: &str,
    command: &CommandId,
    expected: Option<&Admission>,
) -> Result<Option<Value>> {
    let binding = Commands::verify_binding_in_transaction(tx, command)
        .await
        .map_err(command_error)?;
    let record=tx.query_opt("SELECT factor_id,fingerprint,payload::text AS payload,schema_version FROM private_factor_authoring_outcome WHERE command_id=$1::text::uuid",&[&command.value()]).await.map_err(unavailable)?;
    let receipt = match binding {
        Binding::None => {
            if record.is_some() {
                return Err(Error::Corrupt);
            }
            return Ok(None);
        }
        Binding::Admitted(admission) => {
            if expected.is_some_and(|value| value != &admission) {
                return Err(Error::CommandConflict);
            }
            if record.is_some() {
                return Err(Error::Corrupt);
            }
            if !matches!(
                admission.kind(),
                CommandKind::SavePrivateFactorDraft
                    | CommandKind::PublishPrivateFactorRevision
                    | CommandKind::UpdatePrivateFactorDisplay
            ) {
                return Err(Error::CommandConflict);
            }
            return Err(Error::CommandUnknown);
        }
        Binding::Accepted(receipt) => receipt,
    };
    if !matches!(
        receipt.admission().kind(),
        CommandKind::SavePrivateFactorDraft
            | CommandKind::PublishPrivateFactorRevision
            | CommandKind::UpdatePrivateFactorDisplay
    ) || expected.is_some_and(|e| e != receipt.admission())
    {
        return Err(Error::CommandConflict);
    }
    let row = record.ok_or(Error::Corrupt)?;
    let owner: String = row.try_get("factor_id").map_err(|_| Error::Corrupt)?;
    if owner != id {
        return Err(Error::CommandConflict);
    }
    let raw: String = row.try_get("payload").map_err(|_| Error::Corrupt)?;
    let value = payload(&raw)?;
    let identity: String = row.try_get("fingerprint").map_err(|_| Error::Corrupt)?;
    if row
        .try_get::<_, i32>("schema_version")
        .map_err(|_| Error::Corrupt)?
        != 1
        || value.as_object().is_none_or(|v| v.len() != 5)
        || value["schema_version"] != 1
        || value["factor_id"] != id
        || value["command_id"] != command.value()
        || outcome_fingerprint(&value)? != identity
        || receipt.outcome().kind() != OutcomeKind::PrivateFactorAuthoring
        || receipt.outcome().id() != identity
    {
        return Err(Error::Corrupt);
    }
    let input = &value["input"];
    let result = &value["result"];
    if input["factor_id"] != id
        || fingerprint(
            &json!({"contract":"ONLYALPHA_PRIVATE_FACTOR_AUTHORING_INTENT_V1","input":input}),
        )? != receipt.admission().fingerprint()
    {
        return Err(Error::Corrupt);
    }
    let label = Display::new(result["display"].clone()).map_err(|_| Error::Corrupt)?;
    let label_pin = label.fingerprint()?;
    if label.record()["factor_id"] != id || result["display_fingerprint"] != label_pin {
        return Err(Error::Corrupt);
    }
    if receipt.admission().kind() == CommandKind::UpdatePrivateFactorDisplay {
        if input["operation"] != "DISPLAY"
            || input["display_name"] != label.record()["display_name"]
            || input["usage_summary"] != label.record()["usage_summary"]
            || !input["expected_display_fingerprint"]
                .as_str()
                .is_some_and(crate::is_sha256_hex)
            || input["actor_id"]
                .as_str()
                .is_none_or(|v| v.is_empty() || v.len() > 512 || v.chars().any(char::is_control))
            || label.record()["edit_number"].as_u64().is_none_or(|n| n < 2)
            || result
                != &json!({"draft":null,"draft_fingerprint":null,"revision":null,"display":label.record(),"display_fingerprint":label_pin,"display_version":null})
        {
            return Err(Error::Corrupt);
        }
        return Ok(Some(public(&value)));
    }
    let draft = Draft::new(result["draft"].clone()).map_err(|_| Error::Corrupt)?;
    let pin = draft.fingerprint()?;
    let publish = receipt.admission().kind() == CommandKind::PublishPrivateFactorRevision;
    if draft.factor_id() != id
        || result
            != &json!({"draft":draft.record(),"draft_fingerprint":pin,"revision":if publish{draft.revision()?}else{Value::Null},"display":label.record(),"display_fingerprint":label_pin,"display_version":result["display_version"]})
        || input["operation"] != if publish { "PUBLISH" } else { "SAVE" }
        || (publish
            && (input["expected_draft_fingerprint"] != pin
                || !result["display_version"]
                    .as_u64()
                    .is_some_and(|n| (1..=200).contains(&n))))
        || (!publish && (input["draft"] != *draft.record() || !result["display_version"].is_null()))
    {
        return Err(Error::Corrupt);
    }
    if !publish && !input["initial_display"].is_null() {
        let initial = Display::create(id, &input["initial_display"]).map_err(|_| Error::Corrupt)?;
        if initial.record() != label.record() {
            return Err(Error::Corrupt);
        }
    }
    if publish {
        let revision = &result["revision"];
        let pin = revision["revision_fingerprint"]
            .as_str()
            .ok_or(Error::Corrupt)?;
        let owning = tx.query_opt("SELECT factor_id AS asset_id,revision_fingerprint,parent_revision_fingerprint,CASE WHEN octet_length(source_text)<=65536 THEN source_text ELSE NULL END AS source_text,source_sha256,CASE WHEN octet_length(payload::text)<=8388608 THEN payload::text ELSE NULL END AS payload,octet_length(payload::text) AS payload_bytes,schema_version FROM private_factor_revision WHERE factor_id=$1 AND revision_fingerprint=$2", &[&id,&pin]).await.map_err(unavailable)?.ok_or(Error::Corrupt)?;
        let history = state(tx, id).await?;
        if !history["revisions"]
            .as_array()
            .ok_or(Error::Corrupt)?
            .iter()
            .any(|v| {
                v["revision"]["revision_fingerprint"] == pin
                    && v["display_version"] == result["display_version"]
            })
        {
            return Err(Error::Corrupt);
        }
        if owning
            .try_get::<_, i32>("payload_bytes")
            .map_err(|_| Error::Corrupt)?
            > WORK as i32
            || crate::application::private_assets::row("FACTOR", &owning)? != *revision
        {
            return Err(Error::Corrupt);
        }
    }
    Ok(Some(public(&value)))
}
async fn state(tx: &Transaction<'_>, id: &str) -> Result<Value> {
    let asset=tx.query_opt("SELECT current_revision_fingerprint,schema_version FROM private_factor_asset WHERE factor_id=$1",&[&id]).await.map_err(unavailable)?.ok_or(Error::NotFound)?;
    if asset
        .try_get::<_, i32>("schema_version")
        .map_err(|_| Error::Corrupt)?
        != 1
    {
        return Err(Error::Corrupt);
    }
    let display=tx.query_opt("SELECT CASE WHEN octet_length(payload::text)<=8192 THEN payload::text ELSE NULL END AS payload,fingerprint,schema_version FROM private_factor_display WHERE factor_id=$1",&[&id]).await.map_err(unavailable)?.ok_or(Error::DisplayUnavailable)?;
    let raw: Option<String> = display.try_get("payload").map_err(|_| Error::Corrupt)?;
    let label =
        Display::new(payload(&raw.ok_or(Error::Unavailable)?)?).map_err(|_| Error::Corrupt)?;
    let label_pin = label.fingerprint()?;
    if label.record()["factor_id"] != id
        || display
            .try_get::<_, i32>("schema_version")
            .map_err(|_| Error::Corrupt)?
            != 1
        || display
            .try_get::<_, String>("fingerprint")
            .map_err(|_| Error::Corrupt)?
            != label_pin
    {
        return Err(Error::Corrupt);
    }
    let head: Option<String> = asset.try_get(0).map_err(|_| Error::Corrupt)?;
    // Reject aggregate history capacity before materializing payloads in the
    // application. source_text is also bounded if a stored row is corrupt.
    let size = tx.query_one("SELECT count(*) AS revisions,COALESCE(sum(octet_length(payload::text)),0)::bigint AS bytes FROM private_factor_revision WHERE factor_id=$1", &[&id]).await.map_err(unavailable)?;
    if size
        .try_get::<_, i64>("revisions")
        .map_err(|_| Error::Corrupt)?
        > 200
        || size
            .try_get::<_, i64>("bytes")
            .map_err(|_| Error::Corrupt)?
            > WORK as i64
    {
        return Err(Error::Unavailable);
    }
    let rows=tx.query("SELECT factor_id AS asset_id,revision_fingerprint,parent_revision_fingerprint,CASE WHEN octet_length(source_text)<=65536 THEN source_text ELSE NULL END AS source_text,source_sha256,CASE WHEN octet_length(payload::text)<=8388608 THEN payload::text ELSE NULL END AS payload,octet_length(payload::text) AS payload_bytes,schema_version FROM private_factor_revision WHERE factor_id=$1 ORDER BY revision_fingerprint LIMIT 201",&[&id]).await.map_err(unavailable)?;
    if rows.len() > 200 {
        return Err(Error::Unavailable);
    }
    let mut history = BTreeMap::new();
    let mut bytes = 0usize;
    for item in rows {
        let size: i32 = item.try_get("payload_bytes").map_err(|_| Error::Corrupt)?;
        bytes = bytes
            .checked_add(usize::try_from(size).map_err(|_| Error::Corrupt)?)
            .ok_or(Error::Unavailable)?;
        if bytes > WORK {
            return Err(Error::Unavailable);
        }
        let value = row("FACTOR", &item)?;
        validate_revision(&value)?;
        history.insert(
            value["revision_fingerprint"]
                .as_str()
                .ok_or(Error::Corrupt)?
                .to_owned(),
            value,
        );
    }
    let mut next = head.as_deref();
    let mut seen = BTreeSet::new();
    let mut revisions = vec![];
    while let Some(pin) = next {
        if !seen.insert(pin.to_owned()) {
            return Err(Error::Corrupt);
        }
        let value = history.get(pin).ok_or(Error::Corrupt)?;
        revisions.push(value.clone());
        next = value["parent_revision_fingerprint"].as_str();
    }
    if seen.len() != history.len() {
        return Err(Error::Corrupt);
    }
    revisions.reverse();
    let revisions: Vec<Value> = revisions
        .into_iter()
        .enumerate()
        .map(|(index, revision)| json!({"display_version":index+1,"revision":revision}))
        .collect();
    let saved=tx.query_opt("SELECT base_revision_fingerprint,CASE WHEN octet_length(payload::text)<=262144 THEN payload::text ELSE NULL END AS payload,schema_version FROM private_factor_draft WHERE factor_id=$1",&[&id]).await.map_err(unavailable)?;
    let (draft, pin) = if let Some(saved) = saved {
        let raw: Option<String> = saved.try_get("payload").map_err(|_| Error::Corrupt)?;
        let value = payload(&raw.ok_or(Error::Unavailable)?)?;
        let parsed = Draft::new(value.clone()).map_err(|_| Error::Corrupt)?;
        let base: Option<String> = saved
            .try_get("base_revision_fingerprint")
            .map_err(|_| Error::Corrupt)?;
        if saved
            .try_get::<_, i32>("schema_version")
            .map_err(|_| Error::Corrupt)?
            != 1
            || parsed.record() != &value
            || parsed.factor_id() != id
            || parsed.base() != base.as_deref()
            || base.as_ref().is_some_and(|b| !history.contains_key(b))
        {
            return Err(Error::Corrupt);
        }
        (value, json!(parsed.fingerprint()?))
    } else {
        (Value::Null, Value::Null)
    };
    Ok(
        json!({"schema_version":1,"factor_id":id,"current_revision_fingerprint":head,"draft":draft,"draft_fingerprint":pin,"revisions":revisions,"display":label.record(),"display_fingerprint":label_pin}),
    )
}

// Product presentation is a projection of the same verified owner state, never a new identity.
pub(crate) async fn catalog_presentation(
    tx: &Transaction<'_>,
    id: &str,
    locator: &Value,
) -> Result<Value> {
    let value = state(tx, id).await?;
    let published = value["revisions"]
        .as_array()
        .and_then(|rows| rows.last())
        .ok_or(Error::Corrupt)?;
    if locator["private_asset_kind"] != "FACTOR"
        || locator["private_asset_id"] != id
        || published["revision"]["revision_fingerprint"] != locator["revision_fingerprint"]
        || published["revision"]["source_sha256"] != locator["content_fingerprint"]
    {
        return Err(Error::Corrupt);
    }
    Ok(
        json!({"locator":locator,"display":value["display"],"display_fingerprint":value["display_fingerprint"],"display_version":published["display_version"]}),
    )
}
