//! Existing Integration Product metadata routes; no authoring or Source permission.
use crate::{
    human_access::Session,
    integration_types::{document, response},
};
use axum::{
    Extension, Json, Router,
    extract::{Path, State},
    response::{IntoResponse, Response},
    routing::get,
};
use http::{StatusCode, Uri};
use onlyalpha_integration_contract::{Category, ValueKind};
use onlyalpha_product_runtime::{
    integration_configuration::{
        Error, Integration, IntegrationId, Lifecycle, Revision, SecretBinding,
    },
    integration_postgres::{Integrations, Snapshot},
};
use percent_encoding::percent_decode_str;
use serde::{Serialize, de::DeserializeOwned};
use serde_json::{json, value::RawValue};
use std::{collections::BTreeMap, sync::Arc, time::Duration};
use tokio::sync::Mutex;
use tokio_postgres::Client;

struct Queries {
    client: Arc<Mutex<Option<Client>>>,
    rows: usize,
    work: usize,
}
/// Node startup owns the connection/driver and deployment readiness. This router
/// owns the handed-off session exclusively and freezes canonical relation lookup;
/// no DSN, connection, initialization, alternate schema or readiness is invented.
pub async fn query_router(client: Client, rows: usize, work: usize) -> Result<Router, Error> {
    query_router_shared(Arc::new(Mutex::new(Some(client))), rows, work).await
}
pub async fn query_router_shared(
    client: Arc<Mutex<Option<Client>>>,
    rows: usize,
    work: usize,
) -> Result<Router, Error> {
    tokio::time::timeout(
        Duration::from_secs(5),
        client
            .lock()
            .await
            .as_ref()
            .ok_or(Error::Unavailable)?
            .batch_execute("SET search_path TO pg_catalog, public, pg_temp"),
    )
    .await
    .map_err(|_| Error::Unavailable)?
    .map_err(|_| Error::Unavailable)?;
    Ok(Router::new()
        .route("/api/v2/integrations", get(list).head(method_not_allowed))
        .route(
            "/api/v2/integrations/{id}",
            get(owner).head(method_not_allowed),
        )
        .route(
            "/api/v2/integrations/{id}/draft",
            get(draft).head(method_not_allowed),
        )
        .route(
            "/api/v2/integrations/{id}/revisions",
            get(history).head(method_not_allowed),
        )
        .route(
            "/api/v2/integrations/{id}/revisions/{fingerprint}",
            get(revision).head(method_not_allowed),
        )
        .with_state(Arc::new(Queries { client, rows, work })))
}
async fn method_not_allowed() -> StatusCode {
    StatusCode::METHOD_NOT_ALLOWED
}
enum Failure {
    Invalid,
    Unauthorized,
    NotFound,
    DraftNotFound,
    RevisionNotFound,
    Store(Error),
}
impl From<Error> for Failure {
    fn from(error: Error) -> Self {
        Self::Store(error)
    }
}
impl IntoResponse for Failure {
    fn into_response(self) -> Response {
        let (status, code, detail) = match self {
            Self::Invalid => (
                StatusCode::BAD_REQUEST,
                "INTEGRATION_REQUEST_INVALID",
                "HTTP request validation failed",
            ),
            Self::Unauthorized => (
                StatusCode::UNAUTHORIZED,
                "LOCAL_READ_UNAUTHORIZED",
                "Human identity is required",
            ),
            Self::NotFound => (
                StatusCode::NOT_FOUND,
                "INTEGRATION_NOT_FOUND",
                "Integration resource not found",
            ),
            Self::DraftNotFound => (
                StatusCode::NOT_FOUND,
                "INTEGRATION_DRAFT_NOT_FOUND",
                "Integration resource not found",
            ),
            Self::RevisionNotFound => (
                StatusCode::NOT_FOUND,
                "INTEGRATION_REVISION_NOT_FOUND",
                "Integration resource not found",
            ),
            Self::Store(error) => (
                if error == Error::RevisionCorrupt {
                    StatusCode::INTERNAL_SERVER_ERROR
                } else {
                    StatusCode::SERVICE_UNAVAILABLE
                },
                error.code(),
                if error == Error::RevisionCorrupt {
                    "Verified Integration Product authority is corrupt"
                } else {
                    "Required Integration Product authority is unavailable"
                },
            ),
        };
        (
            status,
            Json(json!({"schema_version":1,"error":{"code":code,"detail":detail}})),
        )
            .into_response()
    }
}
fn identity(session: Option<Extension<Session>>) -> Result<(), Failure> {
    session
        .ok_or(Failure::Unauthorized)?
        .0
        .subject_id()
        .map_err(|_| Failure::Unauthorized)?;
    Ok(())
}
fn query(uri: &Uri) -> BTreeMap<String, String> {
    uri.query()
        .unwrap_or_default()
        .split('&')
        .map(|pair| {
            let (key, value) = pair.split_once('=').unwrap_or((pair, ""));
            (
                percent_decode_str(&key.replace('+', " "))
                    .decode_utf8_lossy()
                    .into_owned(),
                percent_decode_str(&value.replace('+', " "))
                    .decode_utf8_lossy()
                    .into_owned(),
            )
        })
        .collect()
}
async fn snapshot(state: &Queries, id: &str) -> Result<Option<Snapshot>, Failure> {
    let id = IntegrationId::new(id).map_err(|_| Failure::Invalid)?;
    let mut client = state.client.lock().await;
    Integrations::new(client.as_mut().ok_or(Error::Unavailable)?)
        .read(&id, state.rows, state.work)
        .await
        .map_err(Failure::from)
}
#[derive(Serialize)]
struct Owner<'a> {
    schema_version: u8,
    integration_id: &'a str,
    type_id: &'a str,
    display_name: &'a str,
    lifecycle_state: &'static str,
    current_revision_fingerprint: Option<&'a str>,
    created_at: String,
    updated_at: String,
}
fn owner_dto(integration: &Integration) -> Owner<'_> {
    let r = integration.record();
    Owner {
        schema_version: 1,
        integration_id: r.integration_id.value(),
        type_id: r.type_id.value(),
        display_name: &r.display_name,
        lifecycle_state: r.lifecycle.as_str(),
        current_revision_fingerprint: r.current_revision_fingerprint.as_deref(),
        created_at: r.created_at.to_string(),
        updated_at: r.updated_at.to_string(),
    }
}
#[derive(Serialize)]
struct Summary<'a> {
    #[serde(flatten)]
    owner: Owner<'a>,
    category: &'static str,
    draft_version: i32,
    pinned_type_descriptor_fingerprint: &'a str,
}
async fn list(
    State(state): State<Arc<Queries>>,
    session: Option<Extension<Session>>,
    uri: Uri,
) -> Result<Response, Failure> {
    identity(session)?;
    let parameters = query(&uri);
    let lifecycle = parameters
        .get("lifecycle_state")
        .map(|s| s.parse::<Lifecycle>().map_err(|_| Failure::Invalid))
        .transpose()?;
    let mut client = state.client.lock().await;
    let snapshots = Integrations::new(client.as_mut().ok_or(Error::Unavailable)?)
        .list_snapshots(
            parameters.get("type_id").map(String::as_str),
            lifecycle,
            state.rows,
            state.work,
        )
        .await?;
    let items = snapshots
        .iter()
        .map(|snapshot| {
            let (draft, _) = snapshot.draft().ok_or(Failure::DraftNotFound)?;
            let r = draft.record();
            let (_, category) = snapshot_type(
                r.type_descriptor_document.raw(),
                &r.type_descriptor_fingerprint,
            )?;
            Ok(Summary {
                owner: owner_dto(snapshot.integration()),
                category: category.as_str(),
                draft_version: r.draft_version,
                pinned_type_descriptor_fingerprint: &r.type_descriptor_fingerprint,
            })
        })
        .collect::<Result<Vec<_>, Failure>>()?;
    Ok(response(&BTreeMap::from([("items", items)])))
}
async fn owner(
    State(state): State<Arc<Queries>>,
    session: Option<Extension<Session>>,
    Path(id): Path<String>,
) -> Result<Response, Failure> {
    identity(session)?;
    let s = snapshot(&state, &id).await?.ok_or(Failure::NotFound)?;
    Ok(response(&owner_dto(s.integration())))
}
#[derive(Serialize)]
struct SecretStatus<'a> {
    field_id: &'a str,
    configured: bool,
    generation: i32,
}
fn statuses(bindings: &[SecretBinding]) -> Vec<SecretStatus<'_>> {
    bindings
        .iter()
        .map(|b| SecretStatus {
            field_id: b.field_id(),
            configured: true,
            generation: b.generation(),
        })
        .collect()
}
#[derive(Serialize)]
struct DraftDto<'a> {
    schema_version: u8,
    integration_id: &'a str,
    base_revision_fingerprint: Option<&'a str>,
    pinned_type_descriptor_fingerprint: &'a str,
    type_descriptor: Box<RawValue>,
    public_configuration: &'a RawValue,
    probe_configuration: Option<&'a RawValue>,
    draft_version: i32,
    draft_fingerprint: &'a str,
    secret_statuses: Vec<SecretStatus<'a>>,
    created_at: String,
    updated_at: String,
}
async fn draft(
    State(state): State<Arc<Queries>>,
    session: Option<Extension<Session>>,
    Path(id): Path<String>,
) -> Result<Response, Failure> {
    identity(session)?;
    let s = snapshot(&state, &id).await?.ok_or(Failure::DraftNotFound)?;
    let (draft, bindings) = s.draft().ok_or(Failure::DraftNotFound)?;
    let r = draft.record();
    Ok(response(&DraftDto {
        schema_version: 1,
        integration_id: r.integration_id.value(),
        base_revision_fingerprint: r.base_revision_fingerprint.as_deref(),
        pinned_type_descriptor_fingerprint: &r.type_descriptor_fingerprint,
        type_descriptor: snapshot_type(
            r.type_descriptor_document.raw(),
            &r.type_descriptor_fingerprint,
        )?
        .0,
        public_configuration: r.public_configuration_document.raw(),
        probe_configuration: r.probe_configuration_document.as_ref().map(|d| d.raw()),
        draft_version: r.draft_version,
        draft_fingerprint: &r.draft_fingerprint,
        secret_statuses: statuses(bindings),
        created_at: r.created_at.to_string(),
        updated_at: r.updated_at.to_string(),
    }))
}
#[derive(Serialize)]
struct RevisionSummary<'a> {
    revision_fingerprint: &'a str,
    revision_sequence: i32,
    type_id: &'a str,
    type_descriptor_fingerprint: &'a str,
    configuration_fingerprint: &'a str,
    runtime_configuration_fingerprint: &'a str,
    probe_configuration_fingerprint: Option<&'a str>,
    secret_binding_fingerprint: &'a str,
    created_at: String,
}
fn revision_summary(revision: &Revision) -> RevisionSummary<'_> {
    let r = revision.record();
    RevisionSummary {
        revision_fingerprint: &r.revision_fingerprint,
        revision_sequence: r.revision_sequence,
        type_id: r.type_id.value(),
        type_descriptor_fingerprint: &r.type_descriptor_fingerprint,
        configuration_fingerprint: &r.configuration_fingerprint,
        runtime_configuration_fingerprint: &r.runtime_configuration_fingerprint,
        probe_configuration_fingerprint: r.probe_configuration_fingerprint.as_deref(),
        secret_binding_fingerprint: &r.secret_binding_fingerprint,
        created_at: r.created_at.to_string(),
    }
}
async fn history(
    State(state): State<Arc<Queries>>,
    session: Option<Extension<Session>>,
    Path(id): Path<String>,
) -> Result<Response, Failure> {
    identity(session)?;
    let s = snapshot(&state, &id).await?;
    Ok(response(&BTreeMap::from([(
        "items",
        s.as_ref()
            .map_or(&[][..], |s| s.history())
            .iter()
            .map(|(r, _)| revision_summary(r))
            .collect::<Vec<_>>(),
    )])))
}
#[derive(Serialize)]
struct RevisionDto<'a> {
    #[serde(flatten)]
    summary: RevisionSummary<'a>,
    schema_version: u8,
    integration_id: &'a str,
    type_descriptor: Box<RawValue>,
    configuration: &'a RawValue,
    probe_configuration: Option<&'a RawValue>,
    secret_bindings: Vec<SecretStatus<'a>>,
}
async fn revision(
    State(state): State<Arc<Queries>>,
    session: Option<Extension<Session>>,
    Path((id, fingerprint)): Path<(String, String)>,
) -> Result<Response, Failure> {
    identity(session)?;
    let s = snapshot(&state, &id)
        .await?
        .ok_or(Failure::RevisionNotFound)?;
    let (revision, bindings) = s
        .history()
        .iter()
        .find(|(r, _)| r.record().revision_fingerprint == fingerprint)
        .ok_or(Failure::RevisionNotFound)?;
    let r = revision.record();
    Ok(response(&RevisionDto {
        summary: revision_summary(revision),
        schema_version: 1,
        integration_id: r.integration_id.value(),
        type_descriptor: snapshot_type(
            r.type_descriptor_document.raw(),
            &r.type_descriptor_fingerprint,
        )?
        .0,
        configuration: r.configuration_document.raw(),
        probe_configuration: r.probe_configuration_document.as_ref().map(|d| d.raw()),
        secret_bindings: statuses(bindings),
    }))
}

// Historical DTO shape is distinct from current authoring admission. Preserve
// raw scalar kinds/defaults and the original snapshot pin, including old metadata
// that no longer passes a current Field validator. No current catalog is consulted.
type Fields<'a> = BTreeMap<String, &'a RawValue>;
fn fields(raw: &RawValue) -> Result<Fields<'_>, Failure> {
    serde_json::from_str(raw.get()).map_err(|_| Error::RevisionCorrupt.into())
}
fn value<T: DeserializeOwned>(map: &Fields<'_>, key: &str) -> Result<T, Failure> {
    serde_json::from_str(map.get(key).ok_or(Error::RevisionCorrupt)?.get())
        .map_err(|_| Error::RevisionCorrupt.into())
}
fn closed(map: &Fields<'_>, names: &[&str]) -> Result<(), Failure> {
    if map.len() != names.len() || names.iter().any(|key| !map.contains_key(*key)) {
        return Err(Error::RevisionCorrupt.into());
    }
    Ok(())
}
fn number_or_null(raw: &RawValue) -> bool {
    let text = raw.get().trim();
    text == "null"
        || (matches!(text.as_bytes().first(), Some(b'-' | b'0'..=b'9'))
            && serde_json::from_str::<serde_json::Number>(text).is_ok())
}
fn scalar(raw: &RawValue) -> bool {
    number_or_null(raw)
        || serde_json::from_str::<String>(raw.get()).is_ok()
        || matches!(raw.get(), "true" | "false")
}
fn snapshot_type(raw: &RawValue, fingerprint: &str) -> Result<(Box<RawValue>, Category), Failure> {
    let mut top = fields(raw)?;
    top.remove("fingerprint");
    closed(
        &top,
        &[
            "schema_version",
            "type_id",
            "category",
            "display_name",
            "description",
            "provider_id",
            "implementation_id",
            "implementation_version",
            "public_api_version",
            "capabilities",
            "configuration_contract",
            "probe_contract",
        ],
    )?;
    if value::<u8>(&top, "schema_version")? != 1 {
        return Err(Error::RevisionCorrupt.into());
    }
    for key in [
        "type_id",
        "display_name",
        "description",
        "provider_id",
        "implementation_id",
        "implementation_version",
        "public_api_version",
    ] {
        value::<String>(&top, key)?;
    }
    let category = value::<String>(&top, "category")?
        .parse::<Category>()
        .map_err(|_| Error::RevisionCorrupt)?;
    value::<Vec<String>>(&top, "capabilities")?;
    let contract = fields(top["configuration_contract"])?;
    closed(&contract, &["schema_version", "fields", "fingerprint"])?;
    if value::<u8>(&contract, "schema_version")? != 1
        || !sha(&value::<String>(&contract, "fingerprint")?)
    {
        return Err(Error::RevisionCorrupt.into());
    }
    for raw in value::<Vec<Box<RawValue>>>(&contract, "fields")? {
        let field = fields(&raw)?;
        closed(
            &field,
            &[
                "field_id",
                "value_kind",
                "required",
                "default",
                "secret",
                "advanced",
                "display_name",
                "description",
                "enum_values",
                "minimum",
                "maximum",
                "exclusive_minimum",
            ],
        )?;
        for key in ["field_id", "display_name", "description"] {
            value::<String>(&field, key)?;
        }
        value::<String>(&field, "value_kind")?
            .parse::<ValueKind>()
            .map_err(|_| Error::RevisionCorrupt)?;
        for key in ["required", "secret", "advanced", "exclusive_minimum"] {
            value::<bool>(&field, key)?;
        }
        value::<Vec<String>>(&field, "enum_values")?;
        if !scalar(field["default"])
            || !number_or_null(field["minimum"])
            || !number_or_null(field["maximum"])
        {
            return Err(Error::RevisionCorrupt.into());
        }
    }
    if top["probe_contract"].get() != "null" {
        let probe = fields(top["probe_contract"])?;
        closed(
            &probe,
            &[
                "probe_version",
                "probe_mode",
                "default_probe_instrument",
                "user_selectable_probe_instrument",
                "probe_checks",
                "fingerprint",
            ],
        )?;
        if value::<u8>(&probe, "probe_version")? != 1
            || !sha(&value::<String>(&probe, "fingerprint")?)
            || !matches!(
                value::<String>(&probe, "probe_mode")?.as_str(),
                "DEFAULT_INSTRUMENT"
            )
        {
            return Err(Error::RevisionCorrupt.into());
        }
        value::<Option<String>>(&probe, "default_probe_instrument")?;
        value::<bool>(&probe, "user_selectable_probe_instrument")?;
        for check in value::<Vec<String>>(&probe, "probe_checks")? {
            if !matches!(
                check.as_str(),
                "CONNECTIVITY"
                    | "AUTHENTICATION"
                    | "REFERENCE_DATA"
                    | "HISTORICAL_DATA"
                    | "REALTIME_DATA"
                    | "MODEL_DISCOVERY"
            ) {
                return Err(Error::RevisionCorrupt.into());
            }
        }
    }
    Ok((
        document(raw, fingerprint).map_err(|_| Error::RevisionCorrupt)?,
        category,
    ))
}
fn sha(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
