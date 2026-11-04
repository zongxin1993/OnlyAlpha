//! Human access to retained factor proposals.
use crate::{
    application::{
        command::CommandId,
        factor_proposals::ConfirmInput,
    },
    persistence::factor_proposals::Proposals,
    security::{
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
use serde_json::Value;
use std::time::Instant;
fn failed(code: &'static str) -> Failure {
    let status = if code.ends_with("UNAUTHORIZED") {
        StatusCode::UNAUTHORIZED
    } else if code.ends_with("NOT_FOUND") {
        StatusCode::NOT_FOUND
    } else if code.ends_with("INVALID") {
        StatusCode::BAD_REQUEST
    } else if code.ends_with("UNAVAILABLE") || code.ends_with("CORRUPT") {
        StatusCode::SERVICE_UNAVAILABLE
    } else {
        StatusCode::CONFLICT
    };
    Failure::with_status(status, code)
}
impl Host {
    pub(crate) async fn factor_proposals(
        &self,
        request: Request<Body>,
        human: human_access::Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        if !self.admitted() || Instant::now() >= deadline {
            return Err(Failure::unavailable("PRODUCT_NODE_NOT_READY"));
        }
        let path = request.uri().path().to_owned();
        let method = request.method().clone();
        let command = if method == Method::POST {
            let mut h = request.headers().get_all("idempotency-key").iter();
            let v = h.next().and_then(|v| v.to_str().ok()).ok_or_else(invalid)?;
            if h.next().is_some() {
                return Err(invalid());
            }
            Some(CommandId::new(v).map_err(|_| invalid())?)
        } else {
            None
        };
        let body = if method == Method::POST {
            let b = to_bytes(request.into_body(), 65536)
                .await
                .map_err(|_| invalid())?;
            ingress::validate_json(&b).map_err(|_| invalid())?;
            serde_json::from_slice::<Value>(&b).map_err(|_| invalid())?
        } else {
            Value::Null
        };
        let mut writer = self.writer.lock().await;
        let client = writer
            .as_mut()
            .ok_or(Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?
            .client_mut()
            .await
            .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
        if Instant::now() >= deadline {
            return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
        }
        let at = now()?.to_string();
        let mut store = Proposals::new(client);
        let owner = human.subject_id()?;
        let command = command.as_ref();
        let result = if method == Method::POST
            && path.starts_with("/api/v2/factor-proposals/")
            && path.ends_with("/withdrawal")
        {
            let fp = path
                .trim_start_matches("/api/v2/factor-proposals/")
                .trim_end_matches("/withdrawal");
            let b: ConfirmInput = serde_json::from_value(body).map_err(|_| invalid())?;
            if b.schema_version != 1 || b.proposal_fingerprint != fp {
                return Err(invalid());
            }
            store
                .withdraw(command.ok_or_else(invalid)?, owner, fp, &at)
                .await
        } else if method == Method::POST
            && path.starts_with("/api/v2/factor-proposals/")
            && path.ends_with("/confirmation")
        {
            let fp = path
                .trim_start_matches("/api/v2/factor-proposals/")
                .trim_end_matches("/confirmation");
            let b: ConfirmInput = serde_json::from_value(body).map_err(|_| invalid())?;
            if b.schema_version != 1 || b.proposal_fingerprint != fp {
                return Err(invalid());
            }
            store
                .confirm(command.ok_or_else(invalid)?, owner, fp, &at)
                .await
        } else if method == Method::GET && path.starts_with("/api/v2/factor-proposals/commands/") {
            let id = CommandId::new(path.trim_start_matches("/api/v2/factor-proposals/commands/"))
                .map_err(|_| invalid())?;
            store.observe(&id, owner, None, &at).await
        } else if method == Method::GET && path.starts_with("/api/v2/factor-proposals/") {
            store
                .read(
                    path.trim_start_matches("/api/v2/factor-proposals/"),
                    owner,
                    None,
                    &at,
                )
                .await
        } else {
            return Err(Failure::with_status(
                StatusCode::FORBIDDEN,
                "FACTOR_PROPOSAL_DENIED",
            ));
        }
        .map_err(failed)?;
        let session = human.metadata_session();
        session.check_active()?;
        Ok(ingress::attach(
            Json(result).into_response(),
            Release::Generation(session),
        ))
    }
}
