//! Human Strategy authoring; authoring publication grants no execution authority.
use crate::{
    application::command::CommandId,
    persistence::private_strategy_postgres::Strategies,
    security::{
        human_access,
        ingress::{self, Release},
    },
    transport::{
        host::{Failure, Host, invalid, now, parameters, required},
        host_factor_studies::failed,
        wire::{PublishPrivateStrategyRevisionDto, SavePrivateStrategyDraftDto},
    },
};
use axum::{
    Json,
    body::{Body, to_bytes},
    response::{IntoResponse, Response},
};
use http::{Method, Request};
use std::time::Instant;
impl Host {
    pub(crate) async fn strategy_authoring(
        &self,
        request: Request<Body>,
        human: &human_access::Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        let actor = human.subject_id()?;
        let session = human.metadata_session();
        let path = request.uri().path().to_owned();
        let parts: Vec<_> = path.trim_start_matches('/').split('/').collect();
        let method = request.method().clone();
        let query = parameters(request.uri())?;
        let value = if method == Method::GET {
            let mut read = self.reader.lock().await;
            if Instant::now() >= deadline {
                return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
            }
            let mut store = Strategies::new(
                read.as_mut()
                    .ok_or_else(|| Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?,
            );
            match parts.as_slice() {
                ["api", "v2", "private-assets", "strategies"] if query.is_empty() => {
                    store.list().await
                }
                ["api", "v2", "private-assets", "strategies", id] if query.is_empty() => {
                    store.read(id).await
                }
                [
                    "api",
                    "v2",
                    "private-assets",
                    "strategies",
                    id,
                    "commands",
                    command,
                ] if query.is_empty() => {
                    store
                        .command(id, actor, &CommandId::new(command).map_err(|_| invalid())?)
                        .await
                }
                [
                    "api",
                    "v2",
                    "private-assets",
                    "strategies",
                    id,
                    "revisions",
                    revision,
                ] if query.len() == 1 => {
                    store
                        .exact(id, revision, required(&query, "content_fingerprint")?)
                        .await
                }
                _ => return Err(invalid()),
            }
            .map_err(failed)?
        } else {
            if !query.is_empty() {
                return Err(invalid());
            }
            let mut keys = request.headers().get_all("idempotency-key").iter();
            let command = CommandId::new(
                keys.next()
                    .and_then(|h| h.to_str().ok())
                    .ok_or_else(invalid)?,
            )
            .map_err(|_| invalid())?;
            if keys.next().is_some() {
                return Err(invalid());
            }
            let bytes = to_bytes(request.into_body(), 262144)
                .await
                .map_err(|_| invalid())?;
            ingress::validate_json(&bytes).map_err(|_| invalid())?;
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or_else(|| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?
                .client_mut()
                .await
                .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
            if Instant::now() >= deadline {
                return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
            }
            human.subject_id()?;
            let mut store = Strategies::new(client);
            match (parts.as_slice(), method) {
                (["api", "v2", "private-assets", "strategies", id, "draft"], Method::PUT) => {
                    let dto: SavePrivateStrategyDraftDto =
                        serde_json::from_slice(&bytes).map_err(|_| invalid())?;
                    store
                        .save(
                            &command,
                            actor,
                            id,
                            serde_json::to_value(dto.draft).map_err(|_| invalid())?,
                            dto.expected_draft_fingerprint.as_deref(),
                            &now()?.to_string(),
                        )
                        .await
                }
                (["api", "v2", "private-assets", "strategies", id, "revisions"], Method::POST) => {
                    let dto: PublishPrivateStrategyRevisionDto =
                        serde_json::from_slice(&bytes).map_err(|_| invalid())?;
                    store
                        .publish(
                            &command,
                            actor,
                            id,
                            &dto.expected_draft_fingerprint,
                            &now()?.to_string(),
                        )
                        .await
                }
                _ => return Err(invalid()),
            }
            .map_err(failed)?
        };
        session.check_active()?;
        Ok(ingress::attach(
            Json(value).into_response(),
            Release::Generation(session),
        ))
    }
}
