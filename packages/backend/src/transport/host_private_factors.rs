//! Formal Human authoring, using the retained Product mutation Authority.
use crate::application::command::CommandId;
use crate::persistence::private_factor_postgres::Factors;
use crate::security::{
    human_access,
    ingress::{self, Release},
};
use crate::transport::host::{Failure, Host, invalid, now};
use crate::transport::wire::{
    PublishPrivateFactorRevisionDto, SavePrivateFactorDraftDto, UpdatePrivateFactorDisplayDto,
};
use axum::{
    Json,
    body::{Body, to_bytes},
    response::{IntoResponse, Response},
};
use http::{Method, Request};
use serde_json::Value;
use std::time::Instant;
impl Host {
    pub(crate) async fn factor_authoring(
        &self,
        request: Request<Body>,
        human: &human_access::Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        human.subject_id()?;
        let session = human.metadata_session();
        let path = request.uri().path().to_owned();
        let parts: Vec<_> = path.trim_start_matches('/').split('/').collect();
        let method = request.method().clone();
        let result = if method == Method::GET {
            let mut read = self.reader.lock().await;
            if Instant::now() >= deadline {
                return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
            }
            let mut store = Factors::new(
                read.as_mut()
                    .ok_or_else(|| Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?,
            );
            match parts.as_slice() {
                ["api", "v2", "private-assets", "factors"] => store.list().await?,
                ["api", "v2", "private-assets", "factors", id] => store.read(id).await?,
                [
                    "api",
                    "v2",
                    "private-assets",
                    "factors",
                    id,
                    "commands",
                    command,
                ] => {
                    store
                        .command(id, &CommandId::new(command).map_err(|_| invalid())?)
                        .await?
                }
                _ => return Err(invalid()),
            }
        } else {
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
            let bytes = to_bytes(request.into_body(), 262144)
                .await
                .map_err(|_| invalid())?;
            // Reject duplicate JSON keys and invalid primitive kinds before typed decoding.
            let raw = std::str::from_utf8(&bytes).map_err(|_| invalid())?;
            onlyalpha_metadata_json::canonical_json(
                raw,
                bytes.len().checked_mul(32).ok_or_else(invalid)?,
            )
            .map_err(|_| invalid())?;
            let mut writer = self.writer.lock().await;
            let authority = writer
                .as_mut()
                .ok_or_else(|| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
            let client = authority
                .client_mut()
                .await
                .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
            if Instant::now() >= deadline {
                return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
            }
            human.subject_id()?;
            let mut store = Factors::new(client);
            match (parts.as_slice(), method) {
                (["api", "v2", "private-assets", "factors", id, "draft"], Method::PUT) => {
                    let dto: SavePrivateFactorDraftDto =
                        serde_json::from_slice(&bytes).map_err(|_| invalid())?;
                    let draft: Value = serde_json::to_value(dto.draft).map_err(|_| invalid())?;
                    store
                        .save(
                            &command,
                            id,
                            draft,
                            dto.expected_draft_fingerprint.as_deref(),
                            dto.initial_display
                                .map(serde_json::to_value)
                                .transpose()
                                .map_err(|_| invalid())?,
                            &now()?.to_string(),
                        )
                        .await?
                }
                (["api", "v2", "private-assets", "factors", id, "display"], Method::PUT) => {
                    let dto: UpdatePrivateFactorDisplayDto =
                        serde_json::from_slice(&bytes).map_err(|_| invalid())?;
                    store.update_display(&command,id,&dto.expected_display_fingerprint,serde_json::json!({"display_name":dto.display_name,"usage_summary":dto.usage_summary}),human.subject_id()?,&now()?.to_string()).await?
                }
                (["api", "v2", "private-assets", "factors", id, "revisions"], Method::POST) => {
                    let dto: PublishPrivateFactorRevisionDto =
                        serde_json::from_slice(&bytes).map_err(|_| invalid())?;
                    store
                        .publish(
                            &command,
                            id,
                            &dto.expected_draft_fingerprint,
                            &now()?.to_string(),
                        )
                        .await?
                }
                _ => return Err(invalid()),
            }
        };
        session.check_active()?;
        Ok(ingress::attach(
            Json(result).into_response(),
            Release::Generation(session),
        ))
    }
}
