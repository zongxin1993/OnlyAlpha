//! Human Probe execution and original receipt observation, with no mutable client
//! held during provider waits and no current-code prerequisite for old receipts.
use crate::application::market_product::probe_attempts;
use crate::application::source_access::Reference;
use crate::security::human_access;
use crate::transport::host::{Failure, Host, ROWS, invalid, uuid};
use crate::transport::host_acquisition::{Operation, OwnerAdmission};
use crate::transport::wire::IntegrationProbeRequestDto;
use axum::{
    Json,
    body::{Body, to_bytes},
    response::{IntoResponse, Response},
};
use http::{Method, Request, StatusCode};
use serde_json::{Value, json};
use std::{sync::Arc, time::Instant};
impl Host {
    pub(crate) async fn probe(
        self: &Arc<Self>,
        request: Request<Body>,
        human: human_access::Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        let path = request.uri().path().to_owned();
        let method = request.method().clone();
        let pieces: Vec<_> = path.split('/').collect();
        let integration = pieces.get(4).ok_or_else(invalid)?;
        let snapshots = self.snapshots().await?;
        let snapshot = snapshots
            .iter()
            .find(|s| s.integration().record().integration_id.value() == *integration)
            .ok_or_else(|| Failure::with_status(StatusCode::NOT_FOUND, "INTEGRATION_NOT_FOUND"))?;
        if method == Method::POST {
            let dto: IntegrationProbeRequestDto = serde_json::from_slice(
                &to_bytes(request.into_body(), 65536)
                    .await
                    .map_err(|_| invalid())?,
            )
            .map_err(|_| invalid())?;
            let owner = snapshot.integration().record();
            if owner.current_revision_fingerprint.as_deref()
                != Some(&dto.expected_revision_fingerprint)
            {
                return Err(Failure::with_status(
                    StatusCode::CONFLICT,
                    "INTEGRATION_BASE_REVISION_CONFLICT",
                ));
            }
            let reference = Reference::new(
                integration,
                &dto.expected_revision_fingerprint,
                Some(owner.type_id.value()),
            )?;
            let attempt = uuid()?;
            let identity = Self::identity(snapshot, &reference)?;
            let selected = crate::application::source_access::Selection::new(
                reference.clone(),
                &identity.source_id,
                &identity.environment,
            )?;
            let admission = Arc::new(OwnerAdmission {
                human,
                operation: Operation::Probe(selected, attempt.clone()),
            });
            let resolved = Arc::new(self.resolver.resolve_for_probe(
                snapshot,
                &reference,
                admission.as_ref(),
                &attempt,
            )?);
            let completed = self
                .app
                .execute_probe(resolved, admission, &attempt, deadline)
                .await?;
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or_else(|| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?
                .client_mut()
                .await
                .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
            completed.persist(client).await?;
            let result = probe_attempts(client, snapshot, ROWS)
                .await?
                .into_iter()
                .find(|v| v["probe_attempt_id"] == attempt)
                .ok_or_else(|| Failure::unavailable("INTEGRATION_PROBE_RESULT_CORRUPT"))?;
            return Ok(Json(result).into_response());
        }
        let mut read = self.reader.lock().await;
        let client = read
            .as_mut()
            .ok_or_else(|| Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
        let attempts = probe_attempts(client, snapshot, ROWS).await?;
        match pieces.as_slice() {
            ["", "api", "v2", "integrations", _, "probe-attempts"] => {
                Ok(Json(json!({"items":attempts})).into_response())
            }
            ["", "api", "v2", "integrations", _, "probe-attempts", id] => Ok(Json(
                attempts
                    .into_iter()
                    .find(|v| v["probe_attempt_id"] == *id)
                    .ok_or_else(|| {
                        Failure::with_status(
                            StatusCode::NOT_FOUND,
                            "INTEGRATION_PROBE_ATTEMPT_NOT_FOUND",
                        )
                    })?,
            )
            .into_response()),
            ["", "api", "v2", "integrations", _, "operational-status"] => {
                let owner = snapshot.integration().record();
                let pin = owner.current_revision_fingerprint.as_deref();
                let current = if let Some(pin) = pin {
                    let reference = Reference::new(integration, pin, Some(owner.type_id.value()))?;
                    self.resolver
                        .resolve(snapshot, &reference, &self.source_session().await, None)
                        .is_ok()
                } else {
                    false
                };
                let last = if current {
                    attempts
                        .iter()
                        .find(|v| v["revision_fingerprint"].as_str() == pin)
                } else {
                    None
                };
                Ok(Json(json!({"schema_version":1,"integration_id":integration,"revision_fingerprint":pin,"probe_supported":current,"status":last.map(|v|v["overall_status"].clone()).unwrap_or(json!("UNKNOWN")),"probe_attempt_id":last.map(|v|v["probe_attempt_id"].clone()).unwrap_or(Value::Null),"checked_at":last.map(|v|v["completed_at"].clone()).unwrap_or(Value::Null)})).into_response())
            }
            _ => Err(invalid()),
        }
    }
}
