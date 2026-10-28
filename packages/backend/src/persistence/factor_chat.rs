//! Append-only conversational provenance. Reuses global Commands and atomic Factor authoring.
use crate::application::{
    command::{Admission, Binding, CommandId, CommandKind, Outcome, OutcomeKind, Receipt},
    factor_chat::{INVALID, Result, hash, preview},
    private_assets::authoring::Draft,
};
use crate::persistence::{
    postgres::{Commands, bounds},
    private_factor_postgres::{self},
};
use serde_json::{Value, json};
use tokio_postgres::{Client, Transaction};
const UNAVAILABLE: &str = "FACTOR_CHAT_AUTHORITY_UNAVAILABLE";
fn db(_: impl std::fmt::Debug) -> &'static str {
    UNAVAILABLE
}
fn id(v: &Value, k: &str) -> Result<CommandId> {
    CommandId::new(v[k].as_str().ok_or(INVALID)?).map_err(|_| INVALID)
}
fn human_input(input: &Value) -> Value {
    let mut v = input.clone();
    if let Some(o) = v.as_object_mut() {
        for k in [
            "candidate_context",
            "workflow_fingerprint",
            "model_request",
            "_model_id",
            "_model_version",
            "abandon",
        ] {
            o.remove(k);
        }
    }
    v
}
fn intent(conversation: &str, actor: &str, input: &Value) -> Result<String> {
    hash(
        &json!({"contract":"ONLYALPHA_FACTOR_CHAT_INTENT_V1","conversation_id":conversation,"actor":actor,"input":human_input(input)}),
    )
}
async fn rejection(
    tx: &Transaction<'_>,
    conversation: &str,
    command: &CommandId,
    actor: &str,
    receipt: &Receipt,
) -> Result<bool> {
    let row=tx.query_opt("SELECT fingerprint,payload::text FROM factor_chat_abandonment WHERE command_id=$1::text::uuid",&[&command.value()]).await.map_err(db)?;
    let Some(row) = row else { return Ok(false) };
    let raw: String = row.try_get(1).map_err(db)?;
    let v: Value = serde_json::from_str(&raw).map_err(db)?;
    let fp: String = row.try_get(0).map_err(db)?;
    if v["conversation_id"] != conversation
        || v["actor"] != actor
        || v["command_id"] != command.value()
        || hash(&v)? != fp
        || receipt.admission().kind() != CommandKind::FactorChat
        || receipt.admission().fingerprint() != intent(conversation, actor, &v["input"])?
        || receipt.outcome().kind() != OutcomeKind::FactorChatEvent
        || receipt.outcome().id() != fp
    {
        return Err("FACTOR_CHAT_HISTORY_CORRUPT");
    }
    Ok(true)
}
pub fn factor_id(conversation: &str) -> String {
    format!("private.factor.chat_{}", conversation.replace('-', ""))
}
fn child(command: &CommandId, purpose: &str) -> Result<CommandId> {
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
pub struct Chats<'a> {
    client: &'a mut Client,
}
impl<'a> Chats<'a> {
    pub fn new(client: &'a mut Client) -> Self {
        Self { client }
    }
    pub async fn list(&mut self, actor: &str) -> Result<Value> {
        let rows=self.client.query("SELECT conversation_id::text FROM factor_chat_conversation WHERE owner_id=$1 ORDER BY created_at DESC,conversation_id LIMIT 101",&[&actor]).await.map_err(db)?;
        if rows.len() > 100 {
            return Err(UNAVAILABLE);
        }
        let mut items = vec![];
        for row in rows {
            let id: String = row.try_get(0).map_err(db)?;
            items.push(self.read(&id, actor).await?);
        }
        Ok(json!({"items":items}))
    }
    pub async fn observed(
        &mut self,
        conversation: &str,
        command: &CommandId,
        actor: &str,
    ) -> Result<Value> {
        CommandId::new(conversation).map_err(|_| INVALID)?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let (accepted, abandoned) = match Commands::verify_binding_in_transaction(&tx, command)
            .await
            .map_err(db)?
        {
            Binding::None => (false, false),
            Binding::Admitted(_) => return Err("FACTOR_CHAT_COMMAND_UNKNOWN"),
            Binding::Accepted(r) => {
                if rejection(&tx, conversation, command, actor, &r).await? {
                    (false, true)
                } else {
                    own(&tx, conversation, actor).await?;
                    view(&tx, conversation).await?;
                    let row=tx.query_opt("SELECT fingerprint FROM factor_chat_event WHERE conversation_id=$1::text::uuid AND command_id=$2::text::uuid",&[&conversation,&command.value()]).await.map_err(db)?.ok_or("FACTOR_CHAT_COMMAND_CONFLICT")?;
                    if r.outcome().id() != row.get::<_, String>(0) {
                        return Err("FACTOR_CHAT_HISTORY_CORRUPT");
                    }
                    (true, false)
                }
            }
        };
        tx.commit().await.map_err(db)?;
        Ok(json!({"accepted":accepted,"abandoned":abandoned}))
    }
    pub async fn replay(
        &mut self,
        conversation: &str,
        command: &CommandId,
        input: &Value,
        actor: &str,
    ) -> Result<Option<Value>> {
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let wanted = Admission::new(
            command.clone(),
            CommandKind::FactorChat,
            &intent(conversation, actor, input)?,
        )
        .map_err(db)?;
        let v = match Commands::verify_binding_in_transaction(&tx, command)
            .await
            .map_err(db)?
        {
            Binding::None => None,
            Binding::Admitted(_) => return Err("FACTOR_CHAT_COMMAND_UNKNOWN"),
            Binding::Accepted(r) => {
                if r.admission() != &wanted {
                    return Err("FACTOR_CHAT_COMMAND_CONFLICT");
                }
                if rejection(&tx, conversation, command, actor, &r).await? {
                    return Err("FACTOR_CHAT_COMMAND_ABANDONED");
                }
                own(&tx, conversation, actor).await?;
                Some(view(&tx, conversation).await?)
            }
        };
        tx.commit().await.map_err(db)?;
        Ok(v)
    }
    /// An explicit Human action fences a not-yet-accepted Command; no late arrival can take effect.
    pub async fn abandon(
        &mut self,
        conversation: &str,
        command: &CommandId,
        input: Value,
        actor: &str,
        at: &str,
    ) -> Result<Value> {
        CommandId::new(conversation).map_err(|_| INVALID)?;
        let a = Admission::new(
            command.clone(),
            CommandKind::FactorChat,
            &intent(conversation, actor, &input)?,
        )
        .map_err(db)?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        Commands::lock_command(&tx, command).await.map_err(db)?;
        let result = match Commands::verify_binding_in_transaction(&tx, command)
            .await
            .map_err(db)?
        {
            Binding::Admitted(_) => return Err("FACTOR_CHAT_COMMAND_UNKNOWN"),
            Binding::Accepted(r) => {
                if r.admission() != &a {
                    return Err("FACTOR_CHAT_COMMAND_CONFLICT");
                }
                if rejection(&tx, conversation, command, actor, &r).await? {
                    json!({"accepted":false,"abandoned":true})
                } else {
                    own(&tx, conversation, actor).await?;
                    view(&tx, conversation).await?;
                    json!({"accepted":true,"abandoned":false})
                }
            }
            Binding::None => {
                let v = json!({"schema_version":1,"conversation_id":conversation,"command_id":command.value(),"actor":actor,"input":human_input(&input),"abandoned_at":at});
                let fp = hash(&v)?;
                Commands::admit_exact_in_transaction(&tx, &a)
                    .await
                    .map_err(db)?;
                tx.execute("INSERT INTO factor_chat_abandonment(command_id,fingerprint,payload) VALUES($1::text::uuid,$2,$3::text::jsonb)",&[&command.value(),&fp,&v.to_string()]).await.map_err(db)?;
                let r = Receipt::new(
                    a,
                    Outcome::new(OutcomeKind::FactorChatEvent, &fp).map_err(db)?,
                    at,
                )
                .map_err(db)?;
                Commands::put_verified_receipt_in_transaction(&tx, &r)
                    .await
                    .map_err(db)?;
                json!({"accepted":false,"abandoned":true})
            }
        };
        tx.commit().await.map_err(db)?;
        Ok(result)
    }
    pub async fn model_request(
        &mut self,
        conversation: &str,
        command: &CommandId,
        actor: &str,
    ) -> Result<Value> {
        self.read(conversation, actor).await?;
        let row=self.client.query_one("SELECT payload::text FROM factor_chat_event WHERE conversation_id=$1::text::uuid AND command_id=$2::text::uuid",&[&conversation,&command.value()]).await.map_err(db)?;
        let v: Value = serde_json::from_str(&row.get::<_, String>(0)).map_err(db)?;
        if v["input"]["operation"] != "MESSAGE" || v["input"]["model_request"].is_null() {
            return Err(INVALID);
        }
        Ok(v["input"]["model_request"].clone())
    }
    pub async fn read(&mut self, conversation: &str, actor: &str) -> Result<Value> {
        CommandId::new(conversation).map_err(|_| INVALID)?;
        let tx = self
            .client
            .build_transaction()
            .read_only(true)
            .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
            .start()
            .await
            .map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        own(&tx, conversation, actor).await?;
        let view = view(&tx, conversation).await?;
        tx.commit().await.map_err(db)?;
        Ok(view)
    }
    /// Accept one Human event before external I/O. Same Command never dispatches again.
    pub async fn begin(
        &mut self,
        conversation: &str,
        command: &CommandId,
        mut input: Value,
        actor: &str,
        at: &str,
    ) -> Result<(Value, bool)> {
        CommandId::new(conversation).map_err(|_| INVALID)?;
        if input.to_string().len() > 16384 {
            return Err(INVALID);
        }
        let intent = intent(conversation, actor, &input)?;
        let admission =
            Admission::new(command.clone(), CommandKind::FactorChat, &intent).map_err(db)?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        Commands::lock_command(&tx, command).await.map_err(db)?;
        match Commands::verify_binding_in_transaction(&tx, command)
            .await
            .map_err(db)?
        {
            Binding::Accepted(r) => {
                if r.admission() != &admission {
                    return Err("FACTOR_CHAT_COMMAND_CONFLICT");
                }
                if rejection(&tx, conversation, command, actor, &r).await? {
                    return Err("FACTOR_CHAT_COMMAND_ABANDONED");
                }
                own(&tx, conversation, actor).await?;
                let v = view(&tx, conversation).await?;
                tx.commit().await.map_err(db)?;
                return Ok((v, false));
            }
            Binding::Admitted(_) => return Err("FACTOR_CHAT_COMMAND_UNKNOWN"),
            Binding::None => {}
        }
        let operation = input["operation"].as_str().ok_or(INVALID)?.to_owned();
        if operation == "CREATE" {
            if !input["expected"].is_null() {
                return Err(INVALID);
            }
            tx.execute("SELECT pg_advisory_xact_lock(hashtextextended('ONLYALPHA_FACTOR_CHAT_INVENTORY',0))",&[]).await.map_err(db)?;
            let count: i64 = tx
                .query_one("SELECT count(*) FROM factor_chat_conversation", &[])
                .await
                .map_err(db)?
                .get(0);
            if count >= 100 {
                return Err(UNAVAILABLE);
            }
            tx.execute("INSERT INTO factor_chat_conversation(conversation_id,owner_id,created_at) VALUES($1::text::uuid,$2,$3)",&[&conversation,&actor,&at]).await.map_err(|_|"FACTOR_CHAT_CONFLICT")?;
        }
        own(&tx, conversation, actor).await?;
        tx.query_one("SELECT conversation_id FROM factor_chat_conversation WHERE conversation_id=$1::text::uuid FOR UPDATE",&[&conversation]).await.map_err(db)?;
        let current = view(&tx, conversation).await?;
        if input["expected"] != current["head"] {
            return Err("FACTOR_CHAT_CONFLICT");
        }
        let mut effect = Value::Null;
        let mut display_effect = Value::Null;
        if operation == "CONFIRM" {
            let p = &current["preview"];
            if p.is_null() || input["preview_fingerprint"] != hash(p)? {
                return Err("FACTOR_CHAT_PREVIEW_CONFLICT");
            }
            let fid = factor_id(conversation);
            let save = child(command, "save")?;
            let display = child(command, "display")?;
            // All global child locks precede the Asset lock, just as standalone authoring does.
            Commands::lock_command(&tx, &save).await.map_err(db)?;
            Commands::lock_command(&tx, &display).await.map_err(db)?;
            let exists = tx
                .query_opt(
                    "SELECT factor_id FROM private_factor_asset WHERE factor_id=$1",
                    &[&fid],
                )
                .await
                .map_err(db)?
                .is_some();
            let before = if exists {
                private_factor_postgres::state(&tx, &fid)
                    .await
                    .map_err(|e| e.code())?
            } else {
                Value::Null
            };
            // Detect manual editing/publication since the last confirmed chat version.
            if before["display_fingerprint"] != current["saved_display_fingerprint"]
                || before["draft_fingerprint"] != current["saved_draft_fingerprint"]
                || !before["current_revision_fingerprint"].is_null()
            {
                return Err("FACTOR_CHAT_AUTHORING_CONFLICT");
            }
            let draft = Draft::new(p["draft"].clone()).map_err(|e| e.code())?;
            let names = json!({"display_name":p["name"],"usage_summary":p["purpose"]});
            let save_input = json!({"operation":"SAVE","factor_id":fid,"expected_draft_fingerprint":before["draft_fingerprint"],"draft":draft.record(),"initial_display":if exists{Value::Null}else{names.clone()}});
            effect = private_factor_postgres::apply_in_transaction(
                &tx,
                &save,
                &fid,
                save_input,
                Some(draft),
                at,
            )
            .await
            .map_err(|e| e.code())?;
            if exists
                && (before["display"]["display_name"] != names["display_name"]
                    || before["display"]["usage_summary"] != names["usage_summary"])
            {
                let d = json!({"operation":"DISPLAY","factor_id":fid,"expected_display_fingerprint":before["display_fingerprint"],"display_name":names["display_name"],"usage_summary":names["usage_summary"],"actor_id":actor});
                display_effect =
                    private_factor_postgres::apply_in_transaction(&tx, &display, &fid, d, None, at)
                        .await
                        .map_err(|e| e.code())?;
            }
        } else if operation == "MESSAGE" {
            let text = input["text"]
                .as_str()
                .filter(|s| !s.trim().is_empty() && s.len() <= 8000 && !s.contains('\0'))
                .ok_or(INVALID)?;
            if matches!(text.trim(), "确认因子" | "确认当前因子") {
                return Err(INVALID);
            }
        } else if operation != "CREATE" {
            return Err(INVALID);
        }
        if operation == "MESSAGE" {
            let mut messages =
                vec![json!({"role":"system","content":crate::application::factor_chat::PROMPT})];
            messages.extend(
                current["messages"]
                    .as_array()
                    .ok_or(UNAVAILABLE)?
                    .iter()
                    .cloned(),
            );
            if !current["preview"].is_null() {
                messages.push(json!({"role":"assistant","content":current["preview"].to_string()}));
            }
            messages.push(json!({"role":"user","content":input["text"]}));
            let model = input["_model_id"].as_str().ok_or(INVALID)?;
            let plan = json!({"model":model,"messages":messages,"response_format":{"type":"json_object"},"max_tokens":2000});
            if plan.to_string().len() > 65536 {
                return Err("FACTOR_CHAT_CAPACITY_REACHED");
            }
            input["model_request"] = plan;
        }
        let ordinal = current["event_count"].as_u64().ok_or(UNAVAILABLE)? + 1;
        if ordinal > 100 {
            return Err("FACTOR_CHAT_CAPACITY_REACHED");
        }
        let event = json!({"schema_version":1,"conversation_id":conversation,"ordinal":ordinal,"command_id":command.value(),"actor":actor,"input":input,"authoring":effect,"display_authoring":display_effect,"accepted_at":at});
        if event.to_string().len() > 131072 {
            return Err("FACTOR_CHAT_CAPACITY_REACHED");
        }
        let fp = hash(&event)?;
        Commands::admit_exact_in_transaction(&tx, &admission)
            .await
            .map_err(db)?;
        tx.execute("INSERT INTO factor_chat_event(conversation_id,ordinal,command_id,fingerprint,payload) VALUES($1::text::uuid,$2,$3::text::uuid,$4,$5::text::jsonb)",&[&conversation,&(ordinal as i32),&command.value(),&fp,&event.to_string()]).await.map_err(db)?;
        let receipt = Receipt::new(
            admission,
            Outcome::new(OutcomeKind::FactorChatEvent, &fp).map_err(db)?,
            at,
        )
        .map_err(db)?;
        Commands::put_verified_receipt_in_transaction(&tx, &receipt)
            .await
            .map_err(db)?;
        let v = view(&tx, conversation).await?;
        tx.commit().await.map_err(db)?;
        Ok((v, operation == "MESSAGE"))
    }
    pub async fn finish(
        &mut self,
        conversation: &str,
        command: &CommandId,
        response: Value,
        actor: &str,
    ) -> Result<Value> {
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        own(&tx, conversation, actor).await?;
        let event=tx.query_one("SELECT fingerprint FROM factor_chat_event WHERE conversation_id=$1::text::uuid AND command_id=$2::text::uuid",&[&conversation,&command.value()]).await.map_err(db)?;
        let fp: String = event.get(0);
        let result = json!({"schema_version":1,"event_fingerprint":fp,"outcome":response});
        let pin = hash(&result)?;
        tx.execute("INSERT INTO factor_chat_model_result(event_fingerprint,fingerprint,payload) VALUES($1,$2,$3::text::jsonb) ON CONFLICT DO NOTHING",&[&fp,&pin,&result.to_string()]).await.map_err(db)?;
        let stored: String = tx
            .query_one(
                "SELECT fingerprint FROM factor_chat_model_result WHERE event_fingerprint=$1",
                &[&fp],
            )
            .await
            .map_err(db)?
            .get(0);
        if stored != pin {
            return Err("FACTOR_CHAT_RESULT_CONFLICT");
        }
        let v = view(&tx, conversation).await?;
        tx.commit().await.map_err(db)?;
        Ok(v)
    }
}
async fn own(tx: &Transaction<'_>, conversation: &str, actor: &str) -> Result<()> {
    if tx.query_opt("SELECT owner_id FROM factor_chat_conversation WHERE conversation_id=$1::text::uuid AND owner_id=$2",&[&conversation,&actor]).await.map_err(db)?.is_none(){return Err("FACTOR_CHAT_NOT_FOUND")}
    Ok(())
}
async fn view(tx: &Transaction<'_>, conversation: &str) -> Result<Value> {
    let rows=tx.query("SELECT e.ordinal,e.command_id::text,e.fingerprint,e.payload::text AS event,r.fingerprint AS result_pin,r.payload::text AS result FROM factor_chat_event e LEFT JOIN factor_chat_model_result r ON r.event_fingerprint=e.fingerprint WHERE e.conversation_id=$1::text::uuid ORDER BY e.ordinal LIMIT 102",&[&conversation]).await.map_err(db)?;
    if rows.len() > 101 {
        return Err(UNAVAILABLE);
    }
    let mut head = Value::Null;
    let mut messages = vec![];
    let mut provider = Value::Null;
    let mut proposed = Value::Null;
    let mut saved = Value::Null;
    let mut saved_display = Value::Null;
    let mut confirmed = Value::Null;
    let mut confirmed_names = Value::Null;
    let mut status = "READY";
    for (i, row) in rows.iter().enumerate() {
        let raw: String = row.try_get("event").map_err(db)?;
        if raw.len() > 131072 {
            return Err(UNAVAILABLE);
        }
        let event: Value = serde_json::from_str(&raw).map_err(db)?;
        let pin: String = row.try_get("fingerprint").map_err(db)?;
        let command = id(&event, "command_id")?;
        let binding = Commands::verify_binding_in_transaction(tx, &command)
            .await
            .map_err(db)?;
        let intent = intent(
            conversation,
            event["actor"].as_str().ok_or(INVALID)?,
            &event["input"],
        )?;
        if hash(&event)? != pin
            || event["conversation_id"] != conversation
            || event["ordinal"] != i + 1
            || event["input"]["expected"] != head
        {
            return Err("FACTOR_CHAT_HISTORY_CORRUPT");
        }
        match binding {
            Binding::Accepted(r)
                if r.admission().kind() == CommandKind::FactorChat
                    && r.admission().fingerprint() == intent
                    && r.outcome().kind() == OutcomeKind::FactorChatEvent
                    && r.outcome().id() == pin => {}
            _ => return Err("FACTOR_CHAT_HISTORY_CORRUPT"),
        }
        head = json!(pin);
        match event["input"]["operation"].as_str() {
            Some("CREATE") if i == 0 => {
                provider = event["input"]["provider"].clone();
            }
            Some("MESSAGE") => {
                proposed = Value::Null;
                messages.push(json!({"role":"user","content":event["input"]["text"]}));
                let raw: Option<String> = row.try_get("result").map_err(db)?;
                if let Some(raw) = raw {
                    if raw.len() > 65536 {
                        return Err(UNAVAILABLE);
                    }
                    let result: Value = serde_json::from_str(&raw).map_err(db)?;
                    if result["event_fingerprint"] != pin
                        || Some(hash(&result)?)
                            != row.try_get::<_, Option<String>>("result_pin").map_err(db)?
                    {
                        return Err("FACTOR_CHAT_HISTORY_CORRUPT");
                    }
                    let response = &result["outcome"];
                    if let Some(error) = response["error"].as_str() {
                        status = if error == "FACTOR_CHAT_MODEL_OUTCOME_UNKNOWN" {
                            "OUTCOME_UNKNOWN"
                        } else {
                            "FAILED"
                        };
                        messages.push(json!({"role":"assistant","content":error}));
                    } else {
                        let response = &response["response"];
                        messages.push(json!({"role":"assistant","content":response["message"]}));
                        if !response["candidate"].is_null() {
                            proposed = preview(&response["candidate"], &factor_id(conversation))?;
                        }
                        status = "READY";
                    }
                } else {
                    status = "OUTCOME_UNKNOWN";
                }
            }
            Some("CONFIRM") => {
                if proposed.is_null() || event["input"]["preview_fingerprint"] != hash(&proposed)? {
                    return Err("FACTOR_CHAT_HISTORY_CORRUPT");
                }
                let result = &event["authoring"];
                let child_id = id(result, "command_id")?;
                let original =
                    private_factor_postgres::bound(tx, &factor_id(conversation), &child_id, None)
                        .await
                        .map_err(|e| e.code())?;
                if original.as_ref() != Some(result) {
                    return Err("FACTOR_CHAT_HISTORY_CORRUPT");
                }
                let accepted = Commands::verify_binding_in_transaction(tx, &child_id)
                    .await
                    .map_err(db)?;
                if !matches!(accepted,Binding::Accepted(ref r) if r.admission().kind()==CommandKind::SavePrivateFactorDraft)
                {
                    return Err("FACTOR_CHAT_HISTORY_CORRUPT");
                }
                if !event["display_authoring"].is_null() {
                    let display = &event["display_authoring"];
                    let did = id(display, "command_id")?;
                    let original =
                        private_factor_postgres::bound(tx, &factor_id(conversation), &did, None)
                            .await
                            .map_err(|e| e.code())?;
                    if original.as_ref() != Some(display) {
                        return Err("FACTOR_CHAT_HISTORY_CORRUPT");
                    }
                }
                saved_display = if event["display_authoring"].is_null() {
                    result["result"]["display_fingerprint"].clone()
                } else {
                    event["display_authoring"]["result"]["display_fingerprint"].clone()
                };
                saved = result["result"]["draft_fingerprint"].clone();
                if saved != proposed["draft_fingerprint"] {
                    return Err("FACTOR_CHAT_HISTORY_CORRUPT");
                }
                confirmed = json!(content_pin(&proposed)?);
                confirmed_names = json!({"name":proposed["name"],"purpose":proposed["purpose"]});
                messages.push(json!({"role":"user","content":"确认当前因子"}));
                messages.push(json!({"role":"assistant","content":"因子已确认并保存为草稿。尚未启动 Research。"}));
                status = "READY";
            }
            _ => return Err("FACTOR_CHAT_HISTORY_CORRUPT"),
        }
    }
    let is_confirmed = !proposed.is_null()
        && confirmed
            == content_pin(&proposed)
                .map(Value::String)
                .unwrap_or(Value::Null);
    Ok(
        json!({"schema_version":1,"conversation_id":conversation,"factor_id":factor_id(conversation),"head":head,"event_count":rows.len(),"provider":provider,"messages":messages,"preview":proposed,"preview_fingerprint":if proposed.is_null(){Value::Null}else{json!(hash(&proposed)?)},"confirmed":is_confirmed,"display_confirmed":confirmed_names==json!({"name":proposed["name"],"purpose":proposed["purpose"]}),"saved_draft_fingerprint":saved,"saved_display_fingerprint":saved_display,"status":status}),
    )
}
fn content_pin(p: &Value) -> Result<String> {
    hash(&json!({"draft_fingerprint":p["draft_fingerprint"],"dependencies":p["dependencies"]}))
}
