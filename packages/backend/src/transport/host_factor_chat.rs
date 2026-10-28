//! Human-only conversational authoring. Existing autonomous Agent endpoints stay denied.
use crate::{
    adapters::agent_model,
    application::{command::CommandId, factor_chat},
    persistence::{credential_postgres::Credentials, factor_chat::Chats},
    security::{
        credentials::CredentialId,
        human_access,
        ingress::{self, Release},
    },
    transport::host::{Failure, Host, invalid, now},
};
use axum::{
    Json,
    body::{Body, to_bytes},
    response::{IntoResponse, Response},
};
use http::{Method, Request, StatusCode};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::time::Instant;
use utoipa::ToSchema;
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorChatProviderDto {
    pub integration_id: String,
    pub revision_fingerprint: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorChatCommandDto {
    pub schema_version: u8,
    #[serde(default)]
    pub abandon: bool,
    pub operation: String,
    pub expected: Option<String>,
    pub provider: Option<FactorChatProviderDto>,
    pub text: Option<String>,
    pub preview_fingerprint: Option<String>,
}
fn failure(code: &'static str) -> Failure {
    Failure::with_status(
        if code.ends_with("CONFLICT") || code == "FACTOR_CHAT_COMMAND_ABANDONED" {
            StatusCode::CONFLICT
        } else if code == factor_chat::INVALID {
            StatusCode::BAD_REQUEST
        } else if code.ends_with("NOT_FOUND") {
            StatusCode::NOT_FOUND
        } else {
            StatusCode::SERVICE_UNAVAILABLE
        },
        code,
    )
}
impl Host {
    pub(crate) async fn factor_chat(
        self: &std::sync::Arc<Self>,
        request: Request<Body>,
        human: human_access::Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        let actor = human.subject_id()?.to_owned();
        let session = human.metadata_session();
        let path = request.uri().path().to_owned();
        let parts: Vec<_> = path.trim_matches('/').split('/').collect();
        if path == "/api/v2/factor-chat/providers" {
            let items:Vec<_>=self.snapshots().await?.iter().filter_map(|s|{let o=s.integration().record();if o.type_id.value()!=agent_model::TYPE_ID{return None}Some(json!({"integration_id":o.integration_id.value(),"name":o.display_name,"revision_fingerprint":o.current_revision_fingerprint,"lifecycle":o.lifecycle.as_str()}))}).collect();
            session.check_active()?;
            return Ok(ingress::attach(
                Json(json!({"items":items})).into_response(),
                Release::Generation(session),
            ));
        }
        let result = if request.method() == Method::GET {
            let mut reader = self.reader.lock().await;
            let client = reader
                .as_mut()
                .ok_or_else(|| failure("FACTOR_CHAT_AUTHORITY_UNAVAILABLE"))?;
            let mut store = Chats::new(client);
            if parts.len() == 3 {
                store.list(&actor).await
            } else if parts.len() == 6 && parts[4] == "commands" {
                store
                    .observed(
                        parts[3],
                        &CommandId::new(parts[5]).map_err(|_| invalid())?,
                        &actor,
                    )
                    .await
            } else {
                store.read(parts.get(3).ok_or_else(invalid)?, &actor).await
            }
            .map_err(failure)?
        } else {
            let conversation = *parts.get(3).ok_or_else(invalid)?;
            let mut keys = request.headers().get_all("idempotency-key").iter();
            let command = CommandId::new(
                keys.next()
                    .and_then(|v| v.to_str().ok())
                    .ok_or_else(invalid)?,
            )
            .map_err(|_| invalid())?;
            if keys.next().is_some() {
                return Err(invalid());
            }
            let bytes = to_bytes(request.into_body(), 16384)
                .await
                .map_err(|_| invalid())?;
            let raw = std::str::from_utf8(&bytes).map_err(|_| invalid())?;
            onlyalpha_metadata_json::canonical_json(raw, 1024 * 1024).map_err(|_| invalid())?;
            let dto: FactorChatCommandDto =
                serde_json::from_slice(&bytes).map_err(|_| invalid())?;
            if dto.schema_version != 1 {
                return Err(invalid());
            }
            if dto.operation == "MESSAGE"
                && dto
                    .text
                    .as_deref()
                    .is_some_and(|s| matches!(s.trim(), "确认因子" | "确认当前因子"))
            {
                return Err(invalid());
            }
            let abandoning = dto.abandon;
            let mut input = serde_json::to_value(dto).map_err(|_| invalid())?;
            {
                let mut writer = self.writer.lock().await;
                let client = writer
                    .as_mut()
                    .ok_or_else(|| failure("PRODUCT_AUTHORITY_UNAVAILABLE"))?
                    .client_mut()
                    .await
                    .map_err(|_| failure("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
                human.subject_id()?;
                if deadline <= Instant::now() {
                    return Err(failure("REQUEST_DEADLINE_EXPIRED"));
                }
                let mut store = Chats::new(client);
                if abandoning {
                    let result = store
                        .abandon(conversation, &command, input, &actor, &now()?.to_string())
                        .await
                        .map_err(failure)?;
                    session.check_active()?;
                    return Ok(ingress::attach(
                        Json(result).into_response(),
                        Release::Generation(session),
                    ));
                }
                if let Some(result) = store
                    .replay(conversation, &command, &input, &actor)
                    .await
                    .map_err(failure)?
                {
                    session.check_active()?;
                    return Ok(ingress::attach(
                        Json(result).into_response(),
                        Release::Generation(session),
                    ));
                }
            }
            if input["operation"] == "CREATE" {
                self.model_config(&input["provider"]).await?;
            }
            input["workflow_fingerprint"] = json!(
                factor_chat::hash(&json!({"version":1,"prompt":factor_chat::PROMPT}))
                    .map_err(failure)?
            );
            if input["operation"] == "MESSAGE" {
                let prior = {
                    let mut reader = self.reader.lock().await;
                    let client = reader
                        .as_mut()
                        .ok_or_else(|| failure("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
                    Chats::new(client)
                        .read(conversation, &actor)
                        .await
                        .map_err(failure)?
                };
                let (config, _secret) = self.model_config(&prior["provider"]).await?;
                input["_model_id"] = config["model_id"].clone();
                input["_model_version"] = config["model_version"].clone();
            }
            let (mut view, dispatch) = {
                let mut writer = self.writer.lock().await;
                let client = writer
                    .as_mut()
                    .ok_or_else(|| failure("PRODUCT_AUTHORITY_UNAVAILABLE"))?
                    .client_mut()
                    .await
                    .map_err(|_| failure("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
                if deadline <= Instant::now() {
                    return Err(failure("REQUEST_DEADLINE_EXPIRED"));
                }
                human.subject_id()?;
                Chats::new(client)
                    .begin(conversation, &command, input, &actor, &now()?.to_string())
                    .await
                    .map_err(failure)?
            };
            if dispatch {
                let response = match self.model_config(&view["provider"]).await {
                    Ok((config, secret)) => {
                        let plan = {
                            let mut reader = self.reader.lock().await;
                            let client = reader
                                .as_mut()
                                .ok_or_else(|| failure("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
                            Chats::new(client)
                                .model_request(conversation, &command, &actor)
                                .await
                                .map_err(failure)?
                        };
                        match agent_model::invoke(&config, secret.expose(), &plan).await {
                            Ok(value) => {
                                let c = &value["response"]["candidate"];
                                if c.is_null()
                                    || factor_chat::preview(
                                        c,
                                        &crate::persistence::factor_chat::factor_id(conversation),
                                    )
                                    .is_ok()
                                {
                                    value
                                } else {
                                    json!({"error":"FACTOR_CHAT_MODEL_RESPONSE_INVALID"})
                                }
                            }
                            Err(e) => json!({"error":e}),
                        }
                    }
                    Err(_) => json!({"error":"FACTOR_CHAT_MODEL_BINDING_UNAVAILABLE"}),
                };
                let mut writer = self.writer.lock().await;
                let client = writer
                    .as_mut()
                    .ok_or_else(|| failure("PRODUCT_AUTHORITY_UNAVAILABLE"))?
                    .client_mut()
                    .await
                    .map_err(|_| failure("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
                view = Chats::new(client)
                    .finish(conversation, &command, response, &actor)
                    .await
                    .map_err(failure)?;
            }
            view
        };
        session.check_active()?;
        Ok(ingress::attach(
            Json(result).into_response(),
            Release::Generation(session),
        ))
    }
    async fn model_config(
        &self,
        pin: &Value,
    ) -> Result<(Value, crate::security::credentials::Secret), Failure> {
        let snapshots = self.snapshots().await?;
        let snapshot = snapshots
            .iter()
            .find(|s| {
                Some(s.integration().record().integration_id.value())
                    == pin["integration_id"].as_str()
            })
            .ok_or_else(|| failure("FACTOR_CHAT_MODEL_BINDING_UNAVAILABLE"))?;
        let owner = snapshot.integration().record();
        if owner.type_id.value() != agent_model::TYPE_ID
            || owner.lifecycle.as_str() != "ACTIVE"
            || owner.current_revision_fingerprint.as_deref() != pin["revision_fingerprint"].as_str()
        {
            return Err(failure("FACTOR_CHAT_MODEL_BINDING_UNAVAILABLE"));
        }
        let (revision, bindings) = snapshot
            .history()
            .iter()
            .find(|(r, _)| {
                Some(r.record().revision_fingerprint.as_str())
                    == pin["revision_fingerprint"].as_str()
            })
            .ok_or_else(invalid)?;
        let config: Value =
            serde_json::from_str(revision.record().configuration_document.raw().get())
                .map_err(|_| invalid())?;
        let binding = bindings
            .iter()
            .find(|b| b.field_id() == "api_credential")
            .ok_or_else(invalid)?;
        let mut reader = self.reader.lock().await;
        let client = reader
            .as_mut()
            .ok_or_else(|| failure("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
        let secret = Credentials::new(client, self.inputs.key())
            .read_secret(
                &CredentialId::new(binding.credential_id().value()).map_err(|_| invalid())?,
                binding.generation(),
                65536,
            )
            .await
            .map_err(|_| failure("FACTOR_CHAT_MODEL_CREDENTIAL_UNAVAILABLE"))?;
        Ok((config, secret))
    }
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorChatMessageDto {
    pub role: String,
    pub content: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorChatPreviewDto {
    pub name: String,
    pub purpose: String,
    pub hypothesis: String,
    pub formula: String,
    pub expression: Value,
    pub dependencies: std::collections::BTreeMap<String, Value>,
    pub draft: crate::transport::wire::PrivateFactorDraftDto,
    pub draft_fingerprint: String,
    pub execution_admitted: bool,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorChatStateDto {
    pub schema_version: u8,
    pub conversation_id: String,
    pub factor_id: String,
    pub head: Option<String>,
    pub event_count: u32,
    pub provider: Option<FactorChatProviderDto>,
    pub messages: Vec<FactorChatMessageDto>,
    pub preview: Option<FactorChatPreviewDto>,
    pub preview_fingerprint: Option<String>,
    pub confirmed: bool,
    pub display_confirmed: bool,
    pub saved_draft_fingerprint: Option<String>,
    pub saved_display_fingerprint: Option<String>,
    pub status: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorChatListDto {
    pub items: Vec<FactorChatStateDto>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorChatProviderSummaryDto {
    pub integration_id: String,
    pub name: String,
    pub revision_fingerprint: Option<String>,
    pub lifecycle: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorChatProvidersDto {
    pub items: Vec<FactorChatProviderSummaryDto>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorChatObservationDto {
    pub accepted: bool,
    pub abandoned: bool,
}

#[derive(Deserialize, Serialize, ToSchema)]
#[serde(untagged)]
pub enum FactorChatCommandOutcomeDto {
    State(Box<FactorChatStateDto>),
    Observation(FactorChatObservationDto),
}
