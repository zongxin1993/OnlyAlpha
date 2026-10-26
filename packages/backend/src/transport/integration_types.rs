//! Existing Product Type metadata routes. Node ingress owns human admission;
//! these projections confer no Probe, Source or Runtime permission.
use crate::application::integration_catalog::AuthoringCatalog;
use axum::{
    Json, Router,
    body::Body,
    extract::{Path, State},
    response::{IntoResponse, Response},
    routing::get,
};
use http::{StatusCode, Uri};
use onlyalpha_integration_contract::{Category, IntegrationTypeId};
use percent_encoding::percent_decode_str;
use serde::Serialize;
use serde_json::{json, value::RawValue};
use std::{collections::BTreeMap, sync::Arc};

/// Compose into the single node router behind its explicit Human ingress.
/// The same immutable catalog also serves the owning authoring commands.
pub fn router(catalog: Arc<AuthoringCatalog>) -> Router {
    Router::new()
        .route(
            "/api/v2/integration-types",
            get(list).head(method_not_allowed),
        )
        .route(
            "/api/v2/integration-types/{type_id}",
            get(read).head(method_not_allowed),
        )
        .with_state(catalog)
}
async fn method_not_allowed() -> StatusCode {
    StatusCode::METHOD_NOT_ALLOWED
}
fn error(status: StatusCode, code: &str, detail: &str) -> Response {
    (status, Json(json!({"error":{"code":code,"detail":detail}}))).into_response()
}
fn unavailable() -> Response {
    error(
        StatusCode::SERVICE_UNAVAILABLE,
        onlyalpha_integration_contract::Error::Unavailable.code(),
        "Integration Type projection is unavailable",
    )
}
// Keep raw JSON scalar kinds, arbitrary integers and ordinary marker keys intact.
// Callers prove the owning descriptor or historical snapshot and its pin; this
// serializer neither reinterprets historical authoring nor recomputes identity.
pub(crate) fn document(
    raw: &RawValue,
    fingerprint: &str,
) -> Result<Box<RawValue>, serde_json::Error> {
    let mut fields: BTreeMap<String, Box<RawValue>> = serde_json::from_str(raw.get())?;
    fields.insert(
        "fingerprint".into(),
        RawValue::from_string(serde_json::to_string(fingerprint)?)?,
    );
    RawValue::from_string(serde_json::to_string(&fields)?)
}
pub(crate) fn response<T: Serialize>(value: &T) -> Response {
    match serde_json::to_vec(value) {
        Ok(bytes) => (
            [(http::header::CONTENT_TYPE, "application/json")],
            Body::from(bytes),
        )
            .into_response(),
        Err(_) => unavailable(),
    }
}
async fn list(State(catalog): State<Arc<AuthoringCatalog>>, uri: Uri) -> Response {
    // Existing scalar query semantics select the last category, ignoring unrelated
    // parameters. Decode '+' before percent escapes, preserving encoded literal '+'.
    let mut selected = None;
    for pair in uri.query().unwrap_or_default().split('&') {
        let (key, value) = pair.split_once('=').unwrap_or((pair, ""));
        if percent_decode_str(&key.replace('+', " ")).decode_utf8_lossy() == "category" {
            selected = Some(value);
        }
    }
    let category = match selected {
        None => None,
        Some(value) => match percent_decode_str(&value.replace('+', " "))
            .decode_utf8()
            .ok()
            .and_then(|value| value.parse::<Category>().ok())
        {
            Some(category) => Some(category),
            None => {
                return error(
                    StatusCode::BAD_REQUEST,
                    "INTEGRATION_TYPE_CONTRACT_INVALID",
                    "Unknown Integration Type category",
                );
            }
        },
    };
    let items = catalog
        .iter()
        .filter(|registration| {
            category.is_none_or(|category| category == registration.descriptor().category())
        })
        .map(|registration| {
            document(
                registration.descriptor().document(),
                registration.descriptor().fingerprint(),
            )
        })
        .collect::<Result<Vec<_>, _>>();
    match items {
        Ok(items) => response(&BTreeMap::from([("items", items)])),
        Err(_) => unavailable(),
    }
}
async fn read(State(catalog): State<Arc<AuthoringCatalog>>, Path(id): Path<String>) -> Response {
    let registration = IntegrationTypeId::new(&id)
        .ok()
        .and_then(|id| catalog.get(&id));
    match registration {
        Some(registration) => match document(
            registration.descriptor().document(),
            registration.descriptor().fingerprint(),
        ) {
            Ok(dto) => response(&dto),
            Err(_) => unavailable(),
        },
        None => error(
            StatusCode::NOT_FOUND,
            "INTEGRATION_TYPE_NOT_FOUND",
            "Integration Type is not available",
        ),
    }
}
