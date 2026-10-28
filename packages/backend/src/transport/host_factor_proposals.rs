//! Service staging and direct Human acceptance share no identity or credentials.
use crate::{
    application::{
        command::CommandId,
        factor_proposals::{ConfirmInput, GrantInput, RevokeInput, StageInput},
    },
    persistence::factor_proposals::Proposals,
    security::{
        human_access,
        ingress::{self, Release},
        proposal_access::Presented,
    },
    transport::host::{Failure, Host, invalid, issue, now},
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
        human: Option<human_access::Session>,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        if !self.admitted() || Instant::now() >= deadline {
            return Err(Failure::unavailable("PRODUCT_NODE_NOT_READY"));
        }
        let presented = request.extensions().get::<Presented>().cloned();
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
        // Lock order is fence -> retained writer -> global Commands -> grant -> proposal/Asset.
        // Revocation cuts off physical output under the same existing ingress write gate.
        let mut fence = self.proposal_fence.lock().await;
        if method == Method::POST
            && path == "/api/v2/factor-proposal-grants/revocations"
            && human.is_some()
        {
            self.revoker
                .get()
                .ok_or(Failure::unavailable(
                    "PROPOSAL_REVOCATION_FENCE_UNAVAILABLE",
                ))?
                .withdraw(&fence.authority)
                .map_err(|_| Failure::unavailable("PROPOSAL_REVOCATION_FENCE_UNAVAILABLE"))?;
            *fence = issue(Vec::new())?;
        }
        if presented.is_some() {
            fence.session.check_active()?;
        }
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
        let owner = if let Some(ref h) = human {
            h.subject_id()?
        } else {
            ""
        };
        let expiry = if let Some(ref p) = presented {
            Some(store.expiry(p, &at).await.map_err(failed)?)
        } else {
            None
        };
        let command = command.as_ref();
        let result = if method == Method::POST
            && path == "/api/v2/factor-proposal-grants"
            && human.is_some()
        {
            store
                .grant(
                    command.ok_or_else(invalid)?,
                    owner,
                    serde_json::from_value::<GrantInput>(body).map_err(|_| invalid())?,
                    &at,
                )
                .await
        } else if method == Method::POST
            && path == "/api/v2/factor-proposal-grants/revocations"
            && human.is_some()
        {
            let b: RevokeInput = serde_json::from_value(body).map_err(|_| invalid())?;
            if b.schema_version != 1 {
                return Err(invalid());
            }
            store
                .revoke(command.ok_or_else(invalid)?, owner, &b.grant_id, &at)
                .await
        } else if method == Method::POST
            && path == "/api/v2/factor-proposals"
            && presented.is_some()
        {
            store
                .stage(
                    command.ok_or_else(invalid)?,
                    presented.as_ref().ok_or_else(invalid)?,
                    serde_json::from_value::<StageInput>(body).map_err(|_| invalid())?,
                    &at,
                )
                .await
        } else if method == Method::POST
            && path.starts_with("/api/v2/factor-proposals/")
            && path.ends_with("/withdrawal")
            && human.is_some()
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
            && human.is_some()
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
        } else if method == Method::GET
            && path.starts_with("/api/v2/factor-proposal-context/")
            && presented.is_some()
        {
            store
                .context(
                    presented.as_ref().ok_or_else(invalid)?,
                    path.trim_start_matches("/api/v2/factor-proposal-context/"),
                    &at,
                )
                .await
        } else if method == Method::GET && path.starts_with("/api/v2/factor-proposals/commands/") {
            let id = CommandId::new(path.trim_start_matches("/api/v2/factor-proposals/commands/"))
                .map_err(|_| invalid())?;
            store.observe(&id, owner, presented.as_ref(), &at).await
        } else if method == Method::GET && path.starts_with("/api/v2/factor-proposals/") {
            store
                .read(
                    path.trim_start_matches("/api/v2/factor-proposals/"),
                    owner,
                    presented.as_ref(),
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
        let response = Json(result).into_response();
        if let Some(expiry) = expiry {
            Ok(ingress::attach(
                response,
                Release::Proposal(fence.session.clone(), expiry),
            ))
        } else {
            let session = human.ok_or_else(invalid)?.metadata_session();
            session.check_active()?;
            Ok(ingress::attach(response, Release::Generation(session)))
        }
    }
}
