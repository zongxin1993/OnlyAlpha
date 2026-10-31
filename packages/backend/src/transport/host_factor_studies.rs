//! Suggestions cross the Agent boundary; preparation and Research stay direct Human operations.
use crate::{
    application::{
        command::CommandId,
        factor_studies::{ContinuationInput, GrantInput, SelectionInput, StageInput},
    },
    persistence::{factor_proposals::Proposals, factor_studies::Studies},
    security::{
        human_access,
        ingress::{self, Release},
        proposal_access::Presented,
    },
    transport::host::{Failure, Host, invalid, now},
};
use axum::{
    Json,
    body::{Body, to_bytes},
    response::{IntoResponse, Response},
};
use http::{Method, Request, StatusCode};
use serde_json::{Value, json};
use std::time::Instant;

pub(crate) fn failed(code: &'static str) -> Failure {
    Failure::with_status(
        if code.ends_with("UNAUTHORIZED") {
            StatusCode::UNAUTHORIZED
        } else if code.ends_with("NOT_FOUND") {
            StatusCode::NOT_FOUND
        } else if code.ends_with("INVALID") {
            StatusCode::BAD_REQUEST
        } else if code.ends_with("UNAVAILABLE")
            || code.ends_with("CORRUPT")
            || code.ends_with("UNKNOWN")
        {
            StatusCode::SERVICE_UNAVAILABLE
        } else if code.ends_with("REQUIRED") || code.ends_with("DENIED") {
            StatusCode::FORBIDDEN
        } else {
            StatusCode::CONFLICT
        },
        code,
    )
}
pub(crate) async fn input(request: Request<Body>) -> Result<(CommandId, Value), Failure> {
    let mut headers = request.headers().get_all("idempotency-key").iter();
    let id = CommandId::new(
        headers
            .next()
            .and_then(|h| h.to_str().ok())
            .ok_or_else(invalid)?,
    )
    .map_err(|_| invalid())?;
    if headers.next().is_some() {
        return Err(invalid());
    }
    let bytes = to_bytes(request.into_body(), 65536)
        .await
        .map_err(|_| invalid())?;
    ingress::validate_json(&bytes).map_err(|_| invalid())?;
    Ok((id, serde_json::from_slice(&bytes).map_err(|_| invalid())?))
}
impl Host {
    pub(crate) async fn factor_studies(
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
        let (command, body) = if method == Method::POST {
            let (c, b) = input(request).await?;
            (Some(c), b)
        } else {
            (None, Value::Null)
        };
        let fence = self.proposal_fence.lock().await;
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
        let at = now()?.to_string();
        let owner = human
            .as_ref()
            .map(|h| h.subject_id())
            .transpose()?
            .unwrap_or("");
        let expiry = if let Some(p) = presented.as_ref() {
            Some(
                Proposals::new(client)
                    .expiry(p, &at)
                    .await
                    .map_err(failed)?,
            )
        } else {
            None
        };
        let mut store = Studies::new(client);
        let value = if method == Method::POST
            && path == "/api/v2/factor-study-grants"
            && human.is_some()
        {
            store
                .grant(
                    command.as_ref().ok_or_else(invalid)?,
                    owner,
                    serde_json::from_value::<GrantInput>(body).map_err(|_| invalid())?,
                    &at,
                )
                .await
        } else if method == Method::POST
            && path == "/api/v2/factor-study-continuations"
            && human.is_some()
        {
            store
                .continue_workflow(
                    command.as_ref().ok_or_else(invalid)?,
                    owner,
                    serde_json::from_value::<ContinuationInput>(body).map_err(|_| invalid())?,
                    &at,
                )
                .await
        } else if method == Method::GET && path.starts_with("/api/v2/factor-study-continuations/") {
            let c = CommandId::new(path.trim_start_matches("/api/v2/factor-study-continuations/"))
                .map_err(|_| invalid())?;
            store.read_continuation(&c, owner, presented.as_ref()).await
        } else if method == Method::POST && path.ends_with("/resolution") && presented.is_some() {
            let raw = path
                .strip_prefix("/api/v2/factor-studies/commands/")
                .and_then(|s| s.strip_suffix("/resolution"))
                .ok_or_else(invalid)?;
            let c = CommandId::new(raw).map_err(|_| invalid())?;
            if command.as_ref() != Some(&c) {
                return Err(invalid());
            }
            store
                .resolve_registration(
                    &c,
                    presented.as_ref().ok_or_else(invalid)?,
                    serde_json::from_value::<StageInput>(body).map_err(|_| invalid())?,
                    &at,
                )
                .await
        } else if method == Method::POST && path == "/api/v2/factor-studies" && presented.is_some()
        {
            store
                .stage(
                    command.as_ref().ok_or_else(invalid)?,
                    presented.as_ref().ok_or_else(invalid)?,
                    serde_json::from_value::<StageInput>(body).map_err(|_| invalid())?,
                    &at,
                )
                .await
        } else if method == Method::POST && path.ends_with("/withdrawal") && human.is_some() {
            let pin = path
                .strip_prefix("/api/v2/factor-studies/")
                .and_then(|s| s.strip_suffix("/withdrawal"))
                .ok_or_else(invalid)?;
            let b: SelectionInput = serde_json::from_value(body).map_err(|_| invalid())?;
            if b.schema_version != 1 || b.study_proposal_fingerprint != pin {
                return Err(invalid());
            }
            store
                .withdraw(command.as_ref().ok_or_else(invalid)?, owner, pin, &at)
                .await
        } else if method == Method::GET && path.starts_with("/api/v2/factor-studies/commands/") {
            let c = CommandId::new(path.trim_start_matches("/api/v2/factor-studies/commands/"))
                .map_err(|_| invalid())?;
            store.observe(&c, owner, presented.as_ref(), &at).await
        } else if method == Method::GET && path.starts_with("/api/v2/factor-studies/") {
            store
                .read(
                    path.trim_start_matches("/api/v2/factor-studies/"),
                    owner,
                    presented.as_ref(),
                    &at,
                )
                .await
        } else if method == Method::GET && path.starts_with("/api/v2/factor-study-context/") {
            let pin = path.trim_start_matches("/api/v2/factor-study-context/");
            if let Some(p) = presented.as_ref() {
                store.context(p, pin, &at).await
            } else if human.is_some() {
                store.human_context(pin, owner, &at).await
            } else {
                return Err(invalid());
            }
        } else {
            return Err(Failure::with_status(
                StatusCode::FORBIDDEN,
                "FACTOR_STUDY_OPERATION_DENIED",
            ));
        }
        .map_err(failed)?;
        drop(writer);
        let value = if path.starts_with("/api/v2/factor-study-context/") {
            let snapshots = self.snapshots().await?;
            let issuer = self.issuer.lock().await;
            let sources=issuer.authority.grants().iter().filter(|g| snapshots.iter().any(|s|{
                let r=s.integration().record();r.integration_id.value()==g.selection().reference().integration_id()
                    &&r.current_revision_fingerprint.as_deref()==Some(g.selection().reference().revision())
            })).map(|g|{let s=g.selection();json!({"integration_id":s.reference().integration_id(),"integration_revision_fingerprint":s.reference().revision(),"expected_type_id":s.reference().expected_type_id(),"source_id":s.source_id(),"environment":s.environment()})}).collect::<Vec<_>>();
            issuer.session.check_active()?;
            json!({"schema_version":1,"owner":value["owner"],"service_subject":value["service_subject"],"factor_proposal_fingerprint":value["factor_proposal_fingerprint"],"factor":value["factor"],"study_proposal_fingerprint":value["study_proposal_fingerprint"],"sources":sources,
                "supported_profile":{"schema_version":1,"kind":"TIME_SERIES_FACTOR_RESEARCH","study_grant_id":value["study_grant_id"],"study_grant_state":value["study_grant_state"],"remaining_proposals":value["remaining_proposals"],"suggested_timeframe_minutes":15,"suggested_horizon_bars":1,"expected_block_length":12,"replicates":4096,"confidence_bps":9500,"suggested_development_bars":256,"suggested_out_of_sample_bars":256,"minimum_blocks_per_sample":10,"maximum_input_window_days":7,"maximum_bars_per_sample":4096,"maximum_total_bar_replicates":8388608,"protected_access":"NO_PROTECTED_ACCESS_V1","metrics":["PEARSON","SPEARMAN"],"uncertainty":"PAIRED_STATIONARY_BOOTSTRAP_FAMILY_ADJUSTED","observed_at":at}})
        } else {
            value
        };
        if let Some(expiry) = expiry {
            Ok(ingress::attach(
                Json(value).into_response(),
                Release::Proposal(fence.session.clone(), expiry),
            ))
        } else {
            let session = human.ok_or_else(invalid)?.metadata_session();
            session.check_active()?;
            Ok(ingress::attach(
                Json(value).into_response(),
                Release::Generation(session),
            ))
        }
    }
}
