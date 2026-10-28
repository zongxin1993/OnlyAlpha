//! Technical infrastructure probe: never a Shipping Product endpoint.
mod market_storage_probe;
use onlyalpha_backend::application::command::{
    Admission, Binding, CommandId, CommandKind, Error, Outcome, OutcomeKind, Put, Receipt,
};
use onlyalpha_backend::persistence::postgres::Commands;
use serde_json::{Value, json};
use std::{
    error::Error as StdError,
    io::{self, Read, Write},
    time::Duration,
};
fn admission(value: &Value) -> Result<Admission, Box<dyn StdError>> {
    Ok(Admission::new(
        CommandId::new(value["command_id"].as_str().ok_or("command id")?)?,
        value["kind"]
            .as_str()
            .ok_or("kind")?
            .parse::<CommandKind>()?,
        value["fingerprint"].as_str().ok_or("fingerprint")?,
    )?)
}
fn receipt(value: &Value) -> Result<Receipt, Box<dyn StdError>> {
    Ok(Receipt::new(
        admission(value)?,
        Outcome::new(
            value["outcome_kind"]
                .as_str()
                .ok_or("outcome kind")?
                .parse::<OutcomeKind>()?,
            value["outcome_id"].as_str().ok_or("outcome id")?,
        )?,
        value["accepted_at"].as_str().ok_or("accepted at")?,
    )?)
}
fn record(value: &Admission) -> Value {
    json!({"schema_version":1,"command_id":value.id().value(),"command_kind":value.kind().as_str(),"command_fingerprint":value.fingerprint()})
}
fn binding(value: Binding) -> Value {
    match value {
        Binding::None => json!({"state":"NONE"}),
        Binding::Admitted(a) => json!({"state":"ADMITTED_NO_OUTCOME","admission":record(&a)}),
        Binding::Accepted(r) => {
            json!({"state":"VERIFIED_ACCEPTED","admission":record(r.admission()),"receipt":{"outcome_kind":r.outcome().kind().as_str(),"outcome_id":r.outcome().id(),"accepted_at":r.accepted_at().to_string()}})
        }
    }
}
fn put(value: Put) -> Value {
    json!({"result":match value {Put::Created=>"CREATED",Put::Reused=>"REUSED"}})
}
async fn watchlist(
    request: &Value,
    client: &mut tokio_postgres::Client,
) -> Result<Value, onlyalpha_backend::application::watchlists::Error> {
    use onlyalpha_backend::application::watchlists::{Book, Error};
    use onlyalpha_backend::persistence::watchlist_postgres::Watchlists;
    let mut owner = Watchlists::new(
        client,
        request["namespace_id"].as_str().ok_or(Error::Invalid)?,
    )?;
    let id = CommandId::new(request["command_id"].as_str().ok_or(Error::Invalid)?)
        .map_err(|_| Error::Invalid)?;
    let book = match request["op"].as_str() {
        Some("watchlist-read") => Some(owner.read().await?),
        Some("watchlist-command") => owner.command(&id).await?,
        Some("watchlist-save") => {
            let proposed = Book::from_record(
                &json!({"version":request["expected_version"],"lists":request["lists"]}),
                2,
            )?;
            Some(
                owner
                    .save(
                        &id,
                        &proposed,
                        request["accepted_at"].as_str().ok_or(Error::Invalid)?,
                    )
                    .await?,
            )
        }
        _ => return Err(Error::Invalid),
    };
    Ok(json!({"book":book.map(|value|value.to_record())}))
}
async fn workspace(
    request: &Value,
    client: &mut tokio_postgres::Client,
) -> Result<Value, onlyalpha_backend::application::workspace::Error> {
    use onlyalpha_backend::application::workspace::{Book, Error};
    use onlyalpha_backend::persistence::workspace_postgres::Workspaces;
    let mut owner = Workspaces::new(
        client,
        request["namespace_id"].as_str().ok_or(Error::Invalid)?,
    )?;
    let id = CommandId::new(request["command_id"].as_str().ok_or(Error::Invalid)?)
        .map_err(|_| Error::Invalid)?;
    let book = match request["op"].as_str() {
        Some("workspace-read") => Some(owner.read().await?),
        Some("workspace-command") => owner.command(&id).await?,
        Some("workspace-save") => {
            let proposed = Book::from_record(
                &json!({"version":request["expected_version"],"active_workspace_id":request["active_workspace_id"],"workspaces":request["workspaces"]}),
            )?;
            Some(
                owner
                    .save(
                        &id,
                        &proposed,
                        request["accepted_at"].as_str().ok_or(Error::Invalid)?,
                    )
                    .await?,
            )
        }
        _ => return Err(Error::Invalid),
    };
    Ok(json!({"book":book.map(|value|value.to_record())}))
}
async fn integration(
    request: &Value,
    client: &mut tokio_postgres::Client,
) -> Result<Value, Box<dyn StdError>> {
    use onlyalpha_backend::application::integration_configuration::IntegrationId;
    use onlyalpha_backend::persistence::integration_postgres::Integrations;
    let rows = usize::try_from(request["rows"].as_u64().ok_or("rows")?)?;
    if request["op"].as_str() == Some("integration-list") {
        use onlyalpha_backend::application::integration_configuration::Lifecycle;
        use onlyalpha_integration_contract::IntegrationTypeId;
        let type_id = request["type_id"]
            .as_str()
            .map(IntegrationTypeId::new)
            .transpose()?;
        let lifecycle = request["lifecycle"]
            .as_str()
            .map(str::parse::<Lifecycle>)
            .transpose()?;
        return Ok(
            match Integrations::new(client)
                .list_metadata(type_id.as_ref(), lifecycle, rows)
                .await
            {
                Err(error) => json!({"error":error.code()}),
                Ok(records) => {
                    json!({"integrations":records.iter().map(|item|{let item=item.record();json!({"id":item.integration_id.value(),"type_id":item.type_id.value(),"display_name":item.display_name,"lifecycle":item.lifecycle.as_str(),"current":item.current_revision_fingerprint})}).collect::<Vec<_>>()})
                }
            },
        );
    }
    let id = IntegrationId::new(request["integration_id"].as_str().ok_or("Integration id")?)?;
    let work = usize::try_from(request["work"].as_u64().ok_or("work")?)?;
    let snapshot = match Integrations::new(client).read(&id, rows, work).await {
        Ok(value) => value,
        Err(error) => return Ok(json!({"error":error.code()})),
    };
    Ok(match snapshot {
        None => json!({"integration":null}),
        Some(snapshot) => {
            let record = snapshot.integration().record();
            let draft=snapshot.draft().map(|(draft,bindings)|json!({"fingerprint":draft.record().draft_fingerprint,"version":draft.record().draft_version,"public":draft.record().public_configuration_document.raw().get(),"bindings":bindings.iter().map(|b|json!({"field":b.field_id(),"credential_id":b.credential_id().value(),"generation":b.generation()})).collect::<Vec<_>>()}));
            let history:Vec<_>=snapshot.history().iter().map(|(revision,bindings)|{let record=revision.record();json!({"fingerprint":record.revision_fingerprint,"sequence":record.revision_sequence,"public":record.configuration_document.raw().get(),"probe":record.probe_configuration_document.as_ref().map(|d|d.raw().get()),"bindings":bindings.iter().map(|b|json!({"field":b.field_id(),"credential_id":b.credential_id().value(),"generation":b.generation()})).collect::<Vec<_>>()})}).collect();
            json!({"integration":{"id":record.integration_id.value(),"type_id":record.type_id.value(),"display_name":record.display_name,"lifecycle":record.lifecycle.as_str(),"current":record.current_revision_fingerprint,"draft":draft,"history":history}})
        }
    })
}
static VALIDATOR_BARRIER_PATH: std::sync::OnceLock<String> = std::sync::OnceLock::new();
fn validator_barrier(
    raw: &serde_json::value::RawValue,
    _: usize,
) -> Result<(), onlyalpha_integration_contract::Error> {
    use onlyalpha_integration_contract::Error;
    let result = (|| -> Result<(), Box<dyn StdError>> {
        let path = VALIDATOR_BARRIER_PATH
            .get()
            .ok_or("missing validator barrier")?;
        let mut stream = std::os::unix::net::UnixStream::connect(path)?;
        stream.set_read_timeout(Some(Duration::from_secs(20)))?;
        stream.set_write_timeout(Some(Duration::from_secs(20)))?;
        let document = raw.get().as_bytes();
        stream.write_all(&u32::try_from(document.len())?.to_be_bytes())?;
        stream.write_all(document)?;
        let mut acknowledgement = [0u8; 1];
        stream.read_exact(&mut acknowledgement)?;
        if acknowledgement != [1] {
            return Err("validator barrier acknowledgement".into());
        }
        Ok(())
    })();
    result.map_err(|_| Error::Unavailable)
}
fn authoring_catalog(
    request: &Value,
    work: usize,
) -> Result<onlyalpha_backend::application::integration_catalog::AuthoringCatalog, Box<dyn StdError>>
{
    use onlyalpha_backend::application::integration_catalog::AuthoringCatalog;
    use onlyalpha_integration_contract::{
        Descriptor,
        authoring::{PluginProjection, Registration},
    };
    if request["installed"] == false {
        return Ok(AuthoringCatalog::new(vec![])?);
    }
    let descriptor =
        Descriptor::from_json(request["descriptor"].as_str().ok_or("descriptor")?, work)?;
    let document: Value = serde_json::from_str(descriptor.document().get())?;
    let projection = PluginProjection::new(
        descriptor.category(),
        document["implementation_id"]
            .as_str()
            .ok_or("implementation")?,
        document["implementation_version"]
            .as_str()
            .ok_or("implementation version")?,
        document["public_api_version"]
            .as_str()
            .ok_or("public api")?,
        serde_json::from_value(document["capabilities"].clone())?,
    )?;
    let validator: fn(
        &serde_json::value::RawValue,
        usize,
    ) -> Result<(), onlyalpha_integration_contract::Error> = match request["validator"].as_str() {
        None | Some("allow") => |_, _| Ok(()),
        Some("barrier") => {
            VALIDATOR_BARRIER_PATH
                .set(
                    request["barrier_path"]
                        .as_str()
                        .ok_or("barrier path")?
                        .into(),
                )
                .map_err(|_| "duplicate validator barrier")?;
            validator_barrier
        }
        Some("reject") => |_, _| Err(onlyalpha_integration_contract::Error::Configuration),
        Some("invalid-type") => |_, _| Err(onlyalpha_integration_contract::Error::Type),
        Some("invalid-probe") => |_, _| Err(onlyalpha_integration_contract::Error::Probe),
        Some("unavailable") => |_, _| Err(onlyalpha_integration_contract::Error::Unavailable),
        Some("require-empty") => |raw, _| {
            if raw.get() == "{}" {
                Ok(())
            } else {
                Err(onlyalpha_integration_contract::Error::Configuration)
            }
        },
        Some("require-defaults") => |raw, _| {
            let values: Value = serde_json::from_str(raw.get())
                .map_err(|_| onlyalpha_integration_contract::Error::Configuration)?;
            if values["count"] == 5
                && values["ratio"] == 1.5
                && values["choice"] == "a"
                && values["flag"] == true
                && values["delay"] == 2
                && values["text"] == "a"
                && values["path"] == "/tmp/input"
            {
                Ok(())
            } else {
                Err(onlyalpha_integration_contract::Error::Configuration)
            }
        },
        Some("require-normalized") => |raw, _| {
            let values = onlyalpha_metadata_json::object_fields(raw.get())
                .map_err(|_| onlyalpha_integration_contract::Error::Configuration)?;
            if values.get("ratio").is_some_and(|v| v.get() == "0") {
                Ok(())
            } else {
                Err(onlyalpha_integration_contract::Error::Configuration)
            }
        },
        Some("require-float") => |raw, _| {
            let values = onlyalpha_metadata_json::object_fields(raw.get())
                .map_err(|_| onlyalpha_integration_contract::Error::Configuration)?;
            if values.get("ratio").is_some_and(|v| v.get() == "-0.0") {
                Ok(())
            } else {
                Err(onlyalpha_integration_contract::Error::Configuration)
            }
        },
        _ => return Err("unknown test validator".into()),
    };
    Ok(AuthoringCatalog::new(vec![Registration::new(
        projection, descriptor, validator,
    )?])?)
}
async fn integration_write(
    request: &Value,
    client: &mut tokio_postgres::Client,
) -> Result<Value, Box<dyn StdError>> {
    use onlyalpha_backend::application::integration_commands::{CreateIntegration, SetLifecycle};
    use onlyalpha_backend::application::integration_configuration::{IntegrationId, Lifecycle};
    use onlyalpha_backend::persistence::integration_postgres::Integrations;
    use onlyalpha_integration_contract::IntegrationTypeId;
    let id = IntegrationId::new(request["integration_id"].as_str().ok_or("Integration id")?)?;
    let command_id = CommandId::new(request["command_id"].as_str().ok_or("command id")?)?;
    let work = 1_000_000;
    let result = match request["action"].as_str() {
        Some("replay") => {
            Integrations::new(client)
                .replay(
                    &admission(request)?,
                    &id,
                    usize::try_from(request["rows"].as_u64().unwrap_or(100))?,
                    work,
                )
                .await
        }
        Some("set-secret") => {
            use onlyalpha_backend::application::integration_commands::SetSecret;
            use onlyalpha_backend::security::credentials::Key;
            let command = SetSecret::new(
                command_id,
                id,
                i32::try_from(request["expected_version"].as_i64().ok_or("version")?)?,
                request["field_id"].as_str().ok_or("field")?,
                request["secret"].as_str().ok_or("secret")?,
            )?;
            let catalog = authoring_catalog(request, work)?;
            let key = Key::new(&[b'k'; 32])?;
            let now = request["accepted_at"].as_str().ok_or("time")?.parse()?;
            let rows = usize::try_from(request["rows"].as_u64().unwrap_or(100))?;
            Integrations::new(client)
                .set_secret(&command, &catalog, &key, now, rows, work)
                .await
                .map(Some)
        }
        Some("create") => {
            let command = CreateIntegration::new(
                command_id,
                id,
                IntegrationTypeId::new(request["type_id"].as_str().ok_or("type id")?)?,
                request["display_name"].as_str().ok_or("name")?,
            )?;
            let catalog = authoring_catalog(request, work)?;
            Integrations::new(client)
                .create(
                    &command,
                    &catalog,
                    request["accepted_at"].as_str().ok_or("time")?.parse()?,
                    work,
                )
                .await
                .map(Some)
        }
        Some("lifecycle") => {
            let command = SetLifecycle::new(
                command_id,
                id,
                request["expected"]
                    .as_str()
                    .ok_or("expected")?
                    .parse::<Lifecycle>()?,
                request["target"]
                    .as_str()
                    .ok_or("target")?
                    .parse::<Lifecycle>()?,
            );
            Integrations::new(client)
                .set_lifecycle(
                    &command,
                    request["accepted_at"].as_str().ok_or("time")?.parse()?,
                    work,
                )
                .await
                .map(Some)
        }
        Some("update") | Some("reset") => {
            use onlyalpha_backend::application::integration_commands::{
                ResetDraftContract, UpdateDraft,
            };
            use onlyalpha_backend::application::integration_configuration::ObjectDocument;
            let catalog = authoring_catalog(request, work)?;
            let version = i32::try_from(request["expected_version"].as_i64().ok_or("version")?)?;
            let rows = usize::try_from(request["rows"].as_u64().unwrap_or(100))?;
            let now = request["accepted_at"].as_str().ok_or("time")?.parse()?;
            if request["action"] == "update" {
                let public =
                    ObjectDocument::new(request["public"].as_str().ok_or("public")?, work)?;
                let probe = request["probe"]
                    .as_str()
                    .map(|v| ObjectDocument::new(v, work))
                    .transpose()?;
                let command = UpdateDraft::new(command_id, id, version, public, probe)?;
                Integrations::new(client)
                    .update_draft(&command, &catalog, now, rows, work)
                    .await
                    .map(Some)
            } else {
                let command = ResetDraftContract::new(command_id, id, version)?;
                Integrations::new(client)
                    .reset_draft_contract(&command, &catalog, now, rows, work)
                    .await
                    .map(Some)
            }
        }
        Some("clear") | Some("publish") => {
            use onlyalpha_backend::application::integration_commands::{
                ClearSecret, PublishRevision,
            };
            let catalog = authoring_catalog(request, work)?;
            let version = i32::try_from(request["expected_version"].as_i64().ok_or("version")?)?;
            let rows = usize::try_from(request["rows"].as_u64().unwrap_or(100))?;
            let now = request["accepted_at"].as_str().ok_or("time")?.parse()?;
            if request["action"] == "clear" {
                let command = ClearSecret::new(
                    command_id,
                    id,
                    version,
                    request["field_id"].as_str().ok_or("field")?,
                )?;
                Integrations::new(client)
                    .clear_secret(&command, &catalog, now, rows, work)
                    .await
                    .map(Some)
            } else {
                let command = PublishRevision::new(command_id, id, version)?;
                Integrations::new(client)
                    .publish_revision(&command, &catalog, now, rows, work)
                    .await
                    .map(Some)
            }
        }
        _ => return Err("action".into()),
    };
    Ok(match result {
        Err(error) => json!({"error":error.code()}),
        Ok(None) => json!({"result":null}),
        Ok(Some(result)) => {
            json!({"result":binding(Binding::Accepted(result.receipt)),"replayed":result.replayed})
        }
    })
}

async fn credential(
    request: &Value,
    client: &mut tokio_postgres::Client,
) -> Result<Value, Box<dyn StdError>> {
    use onlyalpha_backend::persistence::credential_postgres::{Credentials, Metadata};
    use onlyalpha_backend::security::credentials::{CredentialId, Error, Key, Secret, Slot};
    use onlyalpha_domain::time::OnlyUtcDateTime;
    use sha2::{Digest, Sha256};
    fn metadata(value: &Metadata) -> Value {
        let context = value.context();
        let slot = context.slot();
        json!({"credential_id":context.credential_id().value(),"credential_kind":slot.kind(),"subject_id":slot.subject(),"secret_name":slot.name(),"generation":context.generation(),"key_version":context.key_version(),"created_at":value.created_at().to_string(),"updated_at":value.updated_at().to_string(),"configured":true})
    }
    let key = Key::new(&[b'k'; 32])?;
    let work = usize::try_from(request["work"].as_u64().ok_or("work")?)?;
    let now = "2026-09-20T00:00:00+00:00".parse::<OnlyUtcDateTime>()?;
    let mut owner = Credentials::new(client, &key);
    let outcome: Result<Value,Error>=async {
        Ok(match request["action"].as_str() {
            Some("create")=> {
                let slot=Slot::new(request["credential_kind"].as_str().ok_or(Error::SlotInvalid)?,request["subject_id"].as_str().ok_or(Error::SlotInvalid)?,request["secret_name"].as_str().ok_or(Error::SlotInvalid)?)?;
                let secret=Secret::new(request["secret"].as_str().ok_or(Error::SlotInvalid)?)?;
                json!({"metadata":metadata(&owner.create(&slot,&secret,now,work).await?)})
            },
            Some("rotate")=> {
                let id=CredentialId::new(request["credential_id"].as_str().ok_or(Error::SlotInvalid)?)?;
                let generation=i32::try_from(request["generation"].as_i64().ok_or(Error::GenerationConflict)?).map_err(|_|Error::GenerationConflict)?;
                let secret=Secret::new(request["secret"].as_str().ok_or(Error::SlotInvalid)?)?;
                json!({"metadata":metadata(&owner.rotate(&id,generation,&secret,now,work).await?)})
            },
            Some("read")=> {
                let id=CredentialId::new(request["credential_id"].as_str().ok_or(Error::SlotInvalid)?)?;
                let generation=i32::try_from(request["generation"].as_i64().ok_or(Error::GenerationMismatch)?).map_err(|_|Error::GenerationMismatch)?;
                let secret=owner.read_secret(&id,generation,work).await?;
                json!({"secret_sha256":Sha256::digest(secret.expose().as_bytes()).iter().map(|byte|format!("{byte:02x}")).collect::<String>()})
            },
            Some("list")=> {
                let rows=usize::try_from(request["rows"].as_u64().ok_or(Error::Unavailable)?).map_err(|_|Error::Unavailable)?;
                json!({"metadata":owner.list_metadata(rows,work).await?.iter().map(metadata).collect::<Vec<_>>()})
            },
            _=>return Err(Error::SlotInvalid),
        })
    }.await;
    Ok(match outcome {
        Ok(value) => value,
        Err(error) => json!({"error":error.code()}),
    })
}

async fn factor_proposal(request:&Value,client:&mut tokio_postgres::Client)->Value {
 use onlyalpha_backend::{persistence::factor_proposals::Proposals,security::proposal_access::Presented};
 let result=async {
 let command=CommandId::new(request["command_id"].as_str().ok_or("command")?).map_err(|e|e.code())?;
 let actor=request["actor"].as_str().ok_or("actor")?;let at=request["at"].as_str().ok_or("at")?;
 let credential=request["token"].as_str().map(Presented::parse).transpose()?;
 let c=credential.as_ref();let body=request["body"].clone();let mut p=Proposals::new(client);
 match request["action"].as_str(){
 Some("grant") if c.is_none()=>p.grant(&command,actor,serde_json::from_value(body).map_err(|_|"input")?,at).await,
 Some("revoke") if c.is_none()=>p.revoke(&command,actor,body["grant_id"].as_str().ok_or("input")?,at).await,
 Some("stage")=>p.stage(&command,c.ok_or("credential")?,serde_json::from_value(body).map_err(|_|"input")?,at).await,
 Some("withdraw") if c.is_none()=>p.withdraw(&command,actor,body["proposal_fingerprint"].as_str().ok_or("input")?,at).await,
 Some("confirm") if c.is_none()=>p.confirm(&command,actor,body["proposal_fingerprint"].as_str().ok_or("input")?,at).await,
 Some("context")=>p.context(c.ok_or("credential")?,request["session_id"].as_str().ok_or("session")?,at).await,
 Some("read")=>p.read(request["fingerprint"].as_str().ok_or("fingerprint")?,actor,c,at).await,
 Some("observe")=>p.observe(&CommandId::new(request["observed_command"].as_str().ok_or("command")?).map_err(|e|e.code())?,actor,c,at).await,
 _=>Err("FACTOR_PROPOSAL_DENIED")}
 }.await;
 result.unwrap_or_else(|e|json!({"error":e}))
}
async fn factor_authoring(request: &Value, client: &mut tokio_postgres::Client) -> Value {
    use onlyalpha_backend::persistence::private_factor_postgres::Factors;
    if matches!(
        request["action"].as_str(),
        Some("registry" | "exact" | "registry-withdrawn")
    ) {
        use onlyalpha_backend::application::{
            private_assets::PrivateAssets, source_access::Authority,
        };
        use sha2::{Digest, Sha256};
        let token = "a".repeat(64);
        let owner = Authority::new(
            "technical-factor-reader",
            &Sha256::digest(token.as_bytes())
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>(),
            vec![],
        )
        .unwrap();
        let session = owner.authenticate(&format!("Bearer {token}")).unwrap();
        if request["action"] == "registry-withdrawn" {
            owner.withdraw();
        }
        let result = if request["action"] == "exact" {
            PrivateAssets::new(client)
                .factor_revision(
                    &session,
                    request["factor_id"].as_str().unwrap(),
                    request["revision_fingerprint"].as_str().unwrap(),
                    request["content_fingerprint"].as_str().unwrap(),
                )
                .await
        } else {
            PrivateAssets::new(client).current_registry(&session).await
        };
        return match result.and_then(|value| value.into_parts().map(|parts| parts.0)) {
            Ok(value) => value,
            Err(error) => json!({"error":error.code()}),
        };
    }
    let mut store = Factors::new(client);
    let id = request["factor_id"].as_str().unwrap();
    let command = CommandId::new(request["command_id"].as_str().unwrap()).unwrap();
    let value = match request["action"].as_str().unwrap() {
        "read" => store.read(id).await,
        "list" => store.list().await,
        "save" => {
            store
                .save(
                    &command,
                    id,
                    request["draft"].clone(),
                    request["expected"].as_str(),
                    (!request["initial_display"].is_null()).then(||request["initial_display"].clone()),
                    request["accepted_at"].as_str().unwrap(),
                )
                .await
        }
        "display"=>store.update_display(&command,id,request["expected"].as_str().unwrap(),json!({"display_name":request["display_name"],"usage_summary":request["usage_summary"]}),"technical-test",request["accepted_at"].as_str().unwrap()).await,
        "publish" => {
            store
                .publish(
                    &command,
                    id,
                    request["expected"].as_str().unwrap(),
                    request["accepted_at"].as_str().unwrap(),
                )
                .await
        }
        "command" => store.command(id, &command).await,
        _ => panic!("unsupported authoring test operation"),
    };
    match value {
        Ok(value) => value,
        Err(error) => json!({"error":error.code()}),
    }
}

fn main() -> Result<(), Box<dyn StdError>> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    runtime.block_on(async {
  let dsn=std::env::var("ONLYALPHA_POSTGRES_DSN")?;
  let mut config:tokio_postgres::Config=dsn.parse()?;
  if !config.get_dbname().is_some_and(|name|name.ends_with("_test")) { return Err("test database required".into()); }
  // The probe uses the one local canonical test DB. Production TLS is node-owned.
  config.connect_timeout(Duration::from_secs(5)).ssl_mode(tokio_postgres::config::SslMode::Disable).options("-c timezone=UTC -c statement_timeout=5000ms -c lock_timeout=2000ms");
  let (mut client,connection)=config.connect(tokio_postgres::NoTls).await?;
  let driver=tokio::spawn(connection);
  if std::env::args().any(|arg|arg=="--pid-barrier") {let pid:i32=client.query_one("SELECT pg_backend_pid()",&[]).await?.get(0);println!("{}",json!({"ready":true,"backend_pid":pid}));io::stdout().flush()?;}
  else if std::env::args().any(|arg|arg=="--barrier") {println!("{}",json!({"ready":true}));io::stdout().flush()?;}
  let mut raw=String::new();io::stdin().take(270337).read_to_string(&mut raw)?;
  if raw.len()>270336 {return Err("probe frame bound".into())}
  let request:Value=serde_json::from_str(&raw)?;
  // Factor Draft tests carry the 256 KiB Product input plus the probe envelope.
  // Other probe operations retain their existing 128 KiB frame guard.
  if raw.len()>131072 && request["op"]!="factor-authoring" {return Err("probe frame bound".into())}
  if request["op"]=="market-storage" {drop(client);driver.await??;let result=match market_storage_probe::run(&request["request"]).await{Ok(v)=>v,Err(e)=>json!({"error":e.to_string()})};println!("{result}");return Ok(());}
  let id=CommandId::new(request["command_id"].as_str().ok_or("command id")?)?;
  let op=request["op"].as_str().ok_or("operation")?;
  let a=if matches!(op,"admit"|"receipt"|"rollback"|"commit-no-reply"|"atomic-commit") {Some(admission(&request)?)} else {None};
  let r=if matches!(op,"receipt"|"rollback"|"commit-no-reply"|"atomic-commit") {Some(receipt(&request)?)} else {None};
  let outcome:Result<Value,Error>=async {
   Ok(match op {
    "factor-proposal"=>factor_proposal(&request,&mut client).await,
    "factor-authoring"=>factor_authoring(&request,&mut client).await,
    value if value.starts_with("workspace-")=>match workspace(&request,&mut client).await {Ok(value)=>value,Err(error)=>json!({"error":error.code()})},
    value if value.starts_with("watchlist-")=>match watchlist(&request,&mut client).await {Ok(value)=>value,Err(error)=>json!({"error":error.code()})},
    "credential"=>credential(&request,&mut client).await.map_err(|_|Error::Unavailable)?,
    "integration-write"=>integration_write(&request,&mut client).await.map_err(|_|Error::Unavailable)?,
    "integration-read"|"integration-list"=>integration(&request,&mut client).await.map_err(|_|Error::Unavailable)?,
    "schema"|"schema-lost-connection"=>{
     use onlyalpha_backend::persistence::schema::SchemaHistory;
     let work=usize::try_from(request["work"].as_u64().ok_or(Error::InvalidCommandId)?).map_err(|_|Error::Unavailable)?;
     let rows=usize::try_from(request["rows"].as_u64().ok_or(Error::InvalidCommandId)?).map_err(|_|Error::Unavailable)?;
     // Technical fixture inputs name frozen canonical SQL files; production uses its owning startup loader.
     let sources=request["migrations"].as_array().ok_or(Error::InvalidCommandId)?.iter().map(|item|{
      let sql=if let Some(sql)=item[1].as_str() {sql.as_bytes().to_vec()} else {std::fs::read(item[1]["path"].as_str().ok_or(Error::InvalidCommandId)?).map_err(|_|Error::Unavailable)?};
      Ok((item[0].as_str().ok_or(Error::InvalidCommandId)?.to_owned(),sql))
     }).collect::<Result<Vec<_>,Error>>()?;
     if let Some(path)=request["search_path"].as_str() {client.query_one("SELECT set_config('search_path',$1,false)",&[&path]).await.map_err(|_|Error::Unavailable)?;}
     if op=="schema-lost-connection" {assert!(client.simple_query("SELECT pg_terminate_backend(pg_backend_pid())").await.is_err());}
     match SchemaHistory::from_sql(sources,work) {Err(error)=>json!({"error":error.code()}),Ok(history)=>match history.inspect(&mut client,rows).await {Ok(verdict)=>json!({"verdict":verdict.as_str()}),Err(error)=>json!({"error":error.code()})}}
    },
    "deployment"|"deployment-lost-connection"=>{
     use onlyalpha_backend::bootstrap::deployment::{SemanticStoreId,verify_binding};
     let local=SemanticStoreId::new(request["local_id"].as_str().ok_or(Error::InvalidCommandId)?).map_err(|_|Error::InvalidCommandId)?;
     if let Some(path)=request["search_path"].as_str() {client.query_one("SELECT set_config('search_path',$1,false)",&[&path]).await.map_err(|_|Error::Unavailable)?;}
     if op=="deployment-lost-connection" {assert!(client.simple_query("SELECT pg_terminate_backend(pg_backend_pid())").await.is_err());}
     match verify_binding(&mut client,&local).await {Ok(())=>json!({"compatible":true}),Err(error)=>json!({"error":error.code()})}
    },
    "binding"=>binding(Commands::new(&mut client).verify_binding(&id).await?),
    "load-admission"=>json!({"admission":Commands::new(&mut client).load_admission(&id).await?.map(|a|record(&a))}),
    "admit"=>put(Commands::new(&mut client).admit_exact(a.as_ref().expect("validated admission")).await?),
    "receipt"=>put(Commands::new(&mut client).put_verified_receipt(r.as_ref().expect("validated receipt")).await?),
    "rollback"|"commit-no-reply"|"atomic-commit"=>{
     let tx=client.transaction().await.map_err(|_|Error::Unavailable)?;
     Commands::admit_exact_in_transaction(&tx,a.as_ref().expect("validated admission")).await?;
     tx.execute("INSERT INTO command_atomic_effect(command_id) VALUES($1::text::uuid)",&[&id.value()]).await.map_err(|_|Error::Unavailable)?;
     Commands::put_verified_receipt_in_transaction(&tx,r.as_ref().expect("validated receipt")).await?;
     if op=="rollback" {tx.rollback().await.map_err(|_|Error::Unavailable)?;json!({"result":"ROLLED_BACK"})}
     else {tx.commit().await.map_err(|_|Error::Unavailable)?;if op=="commit-no-reply" {std::process::exit(0)}json!({"result":"COMMITTED"})}
    },
    "bounds"=>{
     let tx=client.transaction().await.map_err(|_|Error::Unavailable)?;
     tx.batch_execute("SET LOCAL statement_timeout='1s'; SET LOCAL lock_timeout='500ms'").await.map_err(|_|Error::Unavailable)?;
     Commands::lock_command(&tx,&id).await?;
     let row=tx.query_one("SELECT current_setting('statement_timeout'),current_setting('lock_timeout')",&[]).await.map_err(|_|Error::Unavailable)?;
     let value=json!({"statement_timeout":row.get::<_,String>(0),"lock_timeout":row.get::<_,String>(1)});
     tx.rollback().await.map_err(|_|Error::Unavailable)?;value
    },
    "lost-connection"=>{
     assert!(client.simple_query("SELECT pg_terminate_backend(pg_backend_pid())").await.is_err());
     binding(Commands::new(&mut client).verify_binding(&id).await?)
    },
    _=>return Err(Error::InvalidCommandKind),
   })
  }.await;
  println!("{}",match outcome {Ok(value)=>value,Err(error)=>json!({"error":error.code()})});
  drop(client);let _closed=driver.await?;
  Ok(())
 })
}
