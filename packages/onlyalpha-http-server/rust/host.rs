//! The retained workstation resource owner. This module owns transport composition;
//! Product and plugin owners retain all canonical facts and provider semantics.
use crate::{
    human_access,
    ingress::{self, Release, RequestDeadline, SourceRevoker},
    startup::StorageInputs,
};
use axum::{
    Json, Router,
    body::{Body, to_bytes},
    response::{IntoResponse, Response},
};
use http::{Method, Request, StatusCode};
use hyper::service::Service;
use hyper_util::service::TowerToHyperService;
use onlyalpha_domain::base::OnlyDomainModel;
use onlyalpha_integration_contract::Descriptor;
use onlyalpha_product_runtime::{
    authority_session::AuthoritySession,
    chart::ChartQuery,
    integration_catalog::AuthoringCatalog,
    integration_postgres::{Integrations, Snapshot},
    market_data::{Catalog, ClickHouse, Storage},
    market_product::{
        Application, HistoryContext, InstrumentQuery, Resolved, Resolver, WindowRequest,
    },
    source_access::{Authority, Grant, Permission, Reference, Selection, Session},
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    sync::{
        Arc, OnceLock,
        atomic::{AtomicBool, Ordering},
    },
    time::Instant,
};
use tokio::sync::Mutex;
use tokio_postgres::Client;
pub(crate) const WORK: usize = 64 * 1024 * 1024;
pub(crate) const ROWS: usize = 10000;
/// Single compiled local development Owner role. Source grants are separately
/// issued exact selections and withdrawn on management changes.
pub struct Host {
    pub(crate) inputs: StorageInputs,
    pub(crate) database: crate::workstation_startup::Database,
    pub(crate) writer: Mutex<Option<AuthoritySession>>,
    pub(crate) writer_live: tokio::sync::watch::Receiver<bool>,
    pub(crate) reader: Arc<Mutex<Option<Client>>>,
    pub(crate) catalog: Arc<AuthoringCatalog>,
    pub(crate) resolver: Resolver,
    pub(crate) app: Arc<Application>,
    pub(crate) clickhouse: Arc<ClickHouse>,
    pub(crate) chart: Arc<ChartQuery>,
    pub(crate) chart_gate: Arc<tokio::sync::Semaphore>,
    pub(crate) metadata: Router,
    pub(crate) assets: Router,
    pub(crate) issuer: Mutex<Issuer>,
    pub(crate) revoker: OnceLock<SourceRevoker>,
    pub(crate) ready: AtomicBool,
    pub(crate) socket_slots: Arc<tokio::sync::Semaphore>,
    pub(crate) stream_tasks: tokio::sync::Mutex<tokio::task::JoinSet<Result<(), Failure>>>,
    pub(crate) stream_failure: std::sync::Mutex<Option<&'static str>>,
    pub(crate) previews: std::sync::Mutex<
        BTreeMap<String, onlyalpha_product_runtime::market_product::PreviewSource>,
    >,
}
pub(crate) struct Issuer {
    pub authority: Authority,
    pub session: Session,
}
pub(crate) fn issue(grants: Vec<Grant>) -> Result<Issuer, Failure> {
    let mut entropy = [0; 32];
    getrandom::fill(&mut entropy)
        .map_err(|_| Failure::unavailable("LOCAL_READ_PROOF_UNAVAILABLE"))?;
    let secret: String = entropy.iter().map(|b| format!("{b:02x}")).collect();
    let digest: String = Sha256::digest(secret.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    let authority = Authority::new("local-developer", &digest, grants)
        .map_err(|_| Failure::unavailable("SOURCE_GRANT_UNAVAILABLE"))?;
    let session = authority
        .authenticate(&format!("Bearer {secret}"))
        .map_err(|_| Failure::unavailable("SOURCE_GRANT_UNAVAILABLE"))?;
    Ok(Issuer { authority, session })
}
#[derive(Debug)]
pub struct Failure(StatusCode, &'static str);
impl Failure {
    pub(crate) fn with_status(status: StatusCode, code: &'static str) -> Self {
        Self(status, code)
    }
    pub(crate) fn unavailable(code: &'static str) -> Self {
        Self(StatusCode::SERVICE_UNAVAILABLE, code)
    }
}
impl IntoResponse for Failure {
    fn into_response(self) -> Response {
        failure(self.0, self.1)
    }
}
pub fn failure(status: StatusCode, code: &'static str) -> Response {
    let mut response = (
        status,
        Json(json!({"schema_version":1,"error":{"phase":"QUERY","code":code,"detail":code}})),
    )
        .into_response();
    response
        .headers_mut()
        .insert("cache-control", http::HeaderValue::from_static("no-store"));
    response
}
impl From<onlyalpha_product_runtime::market_product::Error> for Failure {
    fn from(e: onlyalpha_product_runtime::market_product::Error) -> Self {
        Self(
            match e {
                onlyalpha_product_runtime::market_product::Error::Invalid => {
                    StatusCode::BAD_REQUEST
                }
                onlyalpha_product_runtime::market_product::Error::Forbidden => {
                    StatusCode::FORBIDDEN
                }
                onlyalpha_product_runtime::market_product::Error::Conflict => StatusCode::CONFLICT,
                _ => StatusCode::SERVICE_UNAVAILABLE,
            },
            e.code(),
        )
    }
}
impl From<onlyalpha_product_runtime::market_data::Error> for Failure {
    fn from(e: onlyalpha_product_runtime::market_data::Error) -> Self {
        Self::unavailable(e.code())
    }
}
impl From<onlyalpha_product_runtime::source_access::Error> for Failure {
    fn from(e: onlyalpha_product_runtime::source_access::Error) -> Self {
        Self(StatusCode::FORBIDDEN, e.code())
    }
}
impl From<onlyalpha_product_runtime::integration_configuration::Error> for Failure {
    fn from(e: onlyalpha_product_runtime::integration_configuration::Error) -> Self {
        use onlyalpha_product_runtime::integration_configuration::Error::*;
        Self(
            match e {
                InvalidId | InvalidBinding | InvalidDocument => StatusCode::BAD_REQUEST,
                PersistenceConflict => StatusCode::CONFLICT,
                _ => StatusCode::SERVICE_UNAVAILABLE,
            },
            e.code(),
        )
    }
}
impl From<onlyalpha_product_runtime::watchlists::Error> for Failure {
    fn from(e: onlyalpha_product_runtime::watchlists::Error) -> Self {
        use onlyalpha_product_runtime::watchlists::Error::*;
        Self(
            match e {
                Invalid => StatusCode::BAD_REQUEST,
                CommandConflict | VersionConflict => StatusCode::CONFLICT,
                _ => StatusCode::SERVICE_UNAVAILABLE,
            },
            e.code(),
        )
    }
}
impl From<onlyalpha_product_runtime::workspace::Error> for Failure {
    fn from(e: onlyalpha_product_runtime::workspace::Error) -> Self {
        use onlyalpha_product_runtime::workspace::Error::*;
        Self(
            match e {
                Invalid => StatusCode::BAD_REQUEST,
                CommandConflict | VersionConflict => StatusCode::CONFLICT,
                _ => StatusCode::SERVICE_UNAVAILABLE,
            },
            e.code(),
        )
    }
}
// Admission follows the canonical shared capacity. Each permit is moved into
// actual blocking work; abandoning an HTTP future cannot release its owner.
pub(crate) async fn chart_permit(
    gate: Arc<tokio::sync::Semaphore>,
    deadline: Instant,
) -> Result<tokio::sync::OwnedSemaphorePermit, Failure> {
    if Instant::now() >= deadline {
        return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
    }
    let permit = tokio::time::timeout_at(deadline.into(), gate.acquire_owned())
        .await
        .map_err(|_| Failure::unavailable("REQUEST_DEADLINE_EXPIRED"))?
        .map_err(|_| Failure::unavailable("CHART_STUDY_CAPACITY_UNAVAILABLE"))?;
    if Instant::now() >= deadline {
        return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
    }
    Ok(permit)
}
impl Host {
    pub(crate) fn writer_active(&self) -> bool {
        crate::workstation_startup::driver_active(&self.writer_live)
    }
    pub(crate) fn admitted(&self) -> bool {
        self.ready.load(Ordering::Acquire) && self.writer_active()
    }
    pub fn router(self: &Arc<Self>) -> Router {
        let (router, _) = crate::routes::declaration();
        router.with_state(Arc::clone(self)).fallback({
            let host = Arc::clone(self);
            move |request| {
                let host = Arc::clone(&host);
                async move { host.presentation(request).await }
            }
        })
    }
    async fn presentation(&self, mut request: Request<Body>) -> Response {
        if request.method() == Method::GET
            && (crate::routes::navigation(request.method(), request.uri().path())
                || request.uri().path().starts_with("/assets/"))
        {
            if !request.uri().path().starts_with("/assets/") {
                *request.uri_mut() = "/".parse().expect("static URI");
            }
            return TowerToHyperService::new(self.assets.clone())
                .call(request)
                .await
                .unwrap_or_else(|_| {
                    failure(StatusCode::SERVICE_UNAVAILABLE, "WEB_ASSET_UNAVAILABLE")
                });
        }
        failure(StatusCode::NOT_FOUND, "PRODUCT_ROUTE_NOT_FOUND")
    }
    pub async fn dispatch(self: &Arc<Self>, request: Request<Body>) -> Response {
        let started = Instant::now();
        let startup_read = match request.uri().path() {
            "/api/v2/market-data/sources" => Some("SOURCES"),
            "/api/v2/market/instruments" => Some("INSTRUMENTS"),
            "/api/v2/watchlists" => Some("WATCHLISTS"),
            "/api/v2/workspace" => Some("WORKSPACE"),
            path if path.starts_with("/api/v2/integration") => Some("INTEGRATIONS"),
            _ => None,
        };
        let phase = if request.method() == Method::GET {
            "QUERY"
        } else {
            "COMMAND"
        };
        let response = match self.handle(request).await {
            Ok(r) => r,
            Err(e) => e.into_response(),
        };
        if let Some(category) = startup_read
            && started.elapsed() >= std::time::Duration::from_secs(1)
        {
            eprintln!(
                "WORKSPACE_STARTUP_HTTP category={category} status={} handler_ms={}",
                response.status().as_u16(),
                started.elapsed().as_millis()
            );
        }
        if !response.status().is_success() && response.status() != StatusCode::SWITCHING_PROTOCOLS {
            let (mut parts, body) = response.into_parts();
            let original = to_bytes(body, 65536)
                .await
                .ok()
                .and_then(|b| serde_json::from_slice::<Value>(&b).ok());
            let error = original.as_ref().and_then(|v| v.get("error"));
            let code = error
                .and_then(|v| v["code"].as_str())
                .unwrap_or("PRODUCT_RESPONSE_UNAVAILABLE");
            let detail = error.and_then(|v| v["detail"].as_str()).unwrap_or(code);
            let mut body = Json(
                json!({"schema_version":1,"error":{"phase":phase,"code":code,"detail":detail}}),
            )
            .into_response();
            parts
                .headers
                .insert("cache-control", http::HeaderValue::from_static("no-store"));
            parts.headers.insert(
                "content-type",
                http::HeaderValue::from_static("application/json"),
            );
            // The replacement JSON has a new representation length. Hyper
            // must frame these bytes, never the inner router's original body.
            parts.headers.remove(http::header::CONTENT_LENGTH);
            parts.headers.remove(http::header::TRANSFER_ENCODING);
            *body.status_mut() = parts.status;
            *body.headers_mut() = parts.headers;
            return body;
        }
        response
    }
    async fn handle(self: &Arc<Self>, request: Request<Body>) -> Result<Response, Failure> {
        let path = request.uri().path().to_owned();
        if path == "/health/live" {
            return Ok(Json(json!({"status":"LIVE"})).into_response());
        }
        if path == "/health/ready" {
            return if self.admitted() {
                Ok(Json(json!({"status":"READY"})).into_response())
            } else {
                Err(Failure::unavailable("PRODUCT_NODE_NOT_READY"))
            };
        }
        let human = request
            .extensions()
            .get::<human_access::Session>()
            .ok_or(Failure(StatusCode::UNAUTHORIZED, "LOCAL_READ_UNAUTHORIZED"))?
            .clone();
        if human.subject_id()? != "local-developer" {
            return Err(Failure(StatusCode::FORBIDDEN, "OWNER_OPERATION_DENIED"));
        }
        if !self.admitted() {
            return Err(Failure::unavailable("PRODUCT_NODE_NOT_READY"));
        }
        if path.starts_with("/api/v2/agent/")
            || path.starts_with("/api/v2/trading/")
            || path.starts_with("/api/v2/live/")
        {
            return Err(Failure(StatusCode::FORBIDDEN, "OWNER_OPERATION_DENIED"));
        }
        let deadline = request
            .extensions()
            .get::<RequestDeadline>()
            .ok_or(Failure::unavailable("REQUEST_DEADLINE_UNAVAILABLE"))?
            .0;
        if deadline <= Instant::now() {
            return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
        }
        match crate::routes::operation(request.method(), &path) {
            Some(crate::routes::Operation::Deferred) => {
                return Err(Failure(
                    StatusCode::NOT_IMPLEMENTED,
                    "PRODUCT_CAPABILITY_NOT_IMPLEMENTED",
                ));
            }
            Some(crate::routes::Operation::Denied) => {
                return Err(Failure(StatusCode::FORBIDDEN, "OWNER_OPERATION_DENIED"));
            }
            Some(crate::routes::Operation::Implemented) => {}
            None => return Err(Failure(StatusCode::NOT_FOUND, "PRODUCT_ROUTE_NOT_FOUND")),
        }

        if path == "/api/v2/market-data/acquisitions" && request.method() == Method::POST {
            return self.acquisition(request, human, deadline).await;
        }
        if path.starts_with("/api/v2/integrations/")
            && (path.ends_with("/probe")
                || path.contains("/probe-attempts")
                || path.ends_with("/operational-status"))
        {
            return self.probe(request, human, deadline).await;
        }
        if path.starts_with("/api/v2/integrations") && request.method() != Method::GET {
            return self.integration_command(request, deadline).await;
        }
        if path == "/api/v2/workspace" || path.starts_with("/api/v2/workspace/commands/") {
            return self.workspace(request, deadline).await;
        }
        if path.starts_with("/api/v2/watchlists") {
            return self.watchlists(request, deadline).await;
        }
        if request.method() == Method::GET
            && (path.starts_with("/api/v2/integrations")
                || path.starts_with("/api/v2/integration-types"))
        {
            // Start a fresh routing scope. Carrying outer Axum path captures
            // into this router duplicates its one/two parameter extraction.
            // Only the already-verified Human metadata identity crosses it.
            let (parts, body) = request.into_parts();
            let mut query = Request::new(body);
            *query.method_mut() = parts.method;
            *query.uri_mut() = parts.uri;
            *query.version_mut() = parts.version;
            *query.headers_mut() = parts.headers;
            query.extensions_mut().insert(human);
            return TowerToHyperService::new(self.metadata.clone())
                .call(query)
                .await
                .map_err(|_| Failure::unavailable("INTEGRATION_STORE_UNAVAILABLE"));
        }
        if matches!(
            path.as_str(),
            "/api/v2/chart/studies/capabilities" | "/api/v2/research/catalog/calculations"
        ) {
            let started = Instant::now();
            let permit = chart_permit(Arc::clone(&self.chart_gate), deadline).await?;
            let queued_ms = started.elapsed().as_millis();
            if !self.admitted() {
                return Err(Failure::unavailable("PRODUCT_NODE_NOT_READY"));
            }
            human.subject_id()?;
            let chart = Arc::clone(&self.chart);
            let catalog = path.ends_with("calculations");
            let value = tokio::task::spawn_blocking(move || {
                let _permit = permit;
                if catalog {
                    chart.registered_catalog_before(deadline)
                } else {
                    chart.registered_capabilities_before(deadline)
                }
            })
            .await
            .map_err(|_| Failure::unavailable("CHART_STUDY_QUERY_UNAVAILABLE"))?
            .map_err(|e| Failure::unavailable(e.code()))?;
            if started.elapsed() >= std::time::Duration::from_secs(1) {
                eprintln!(
                    "CHART_METADATA_HTTP catalog={catalog} queued_ms={queued_ms} total_ms={}",
                    started.elapsed().as_millis()
                );
            }
            return Ok(Json(value).into_response());
        }
        if matches!(
            path.as_str(),
            "/api/v2/market-data/stream" | "/api/v2/chart/market-data/stream"
        ) {
            return self.websocket(request, human).await;
        }
        if matches!(
            path.as_str(),
            "/api/v2/chart/temporary-studies/evaluate"
                | "/api/v2/chart/temporary-studies/evaluate-batch"
        ) {
            return self.temporary_chart_evaluate(request, deadline).await;
        }
        if path == "/api/v2/chart/studies/evaluate" {
            return self.chart_evaluate(request, deadline).await;
        }
        if path == "/api/v2/chart/market-data/bars" {
            return self.temporary_market(request, deadline).await;
        }
        if path.starts_with("/api/v2/private-assets") {
            return self.private_assets(request, &human).await;
        }
        if path.starts_with("/api/v2/market-data/") || path.starts_with("/api/v2/market/") {
            return self.market(request, deadline).await;
        }
        Err(Failure(
            StatusCode::NOT_IMPLEMENTED,
            "PRODUCT_CAPABILITY_NOT_IMPLEMENTED",
        ))
    }
    pub(crate) async fn snapshots(&self) -> Result<Vec<Snapshot>, Failure> {
        let mut read = self.reader.lock().await;
        Integrations::new(
            read.as_mut()
                .ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?,
        )
        .list_snapshots(None, None, ROWS, WORK)
        .await
        .map_err(Into::into)
    }
    pub(crate) async fn source_session(&self) -> Session {
        self.issuer.lock().await.session.clone()
    }
    pub(crate) fn identity(
        snapshot: &Snapshot,
        reference: &Reference,
    ) -> Result<onlyalpha_integration_contract::source::MarketIdentity, Failure> {
        let (revision, _) = snapshot
            .history()
            .iter()
            .find(|(r, _)| r.record().revision_fingerprint == reference.revision())
            .ok_or(Failure::with_status(
                StatusCode::NOT_FOUND,
                "MARKET_DATA_SOURCE_SELECTION_UNRESOLVED",
            ))?;
        let r = revision.record();
        let d = Descriptor::from_json(r.type_descriptor_document.raw().get(), WORK)
            .map_err(|_| Failure::unavailable("INTEGRATION_REVISION_CORRUPT"))?;
        onlyalpha_plugin_binance::spot_history_identity(&d, r.configuration_document.raw())
            .map_err(|_| Failure::unavailable("MARKET_DATA_HISTORY_CONTEXT_UNPROVABLE"))
    }
    pub(crate) async fn resolve(
        &self,
        reference: &Reference,
    ) -> Result<(Arc<Resolved>, Session), Failure> {
        let session = self.source_session().await;
        let snapshots = self.snapshots().await?;
        let snapshot = snapshots
            .iter()
            .find(|s| s.integration().record().integration_id.value() == reference.integration_id())
            .ok_or(Failure::with_status(
                StatusCode::NOT_FOUND,
                "MARKET_DATA_SOURCE_SELECTION_UNRESOLVED",
            ))?;
        Ok((
            Arc::new(self.resolver.resolve(snapshot, reference, &session, None)?),
            session,
        ))
    }
    async fn market(
        self: &Arc<Self>,
        request: Request<Body>,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        let path = request.uri().path();
        let p = parameters(request.uri())?;
        let session = self.source_session().await;
        let snapshots = self.snapshots().await?;
        if path == "/api/v2/market-data/sources" {
            let (_, batch) = self.source_descriptions(&snapshots, &session)?;
            let (value, fence) = batch.into_parts()?;
            return Ok(ingress::attach(
                Json(value).into_response(),
                Release::Batch(fence),
            ));
        }
        if path == "/api/v2/market/instruments/search" {
            let (sources, _) = self.source_descriptions(&snapshots, &session)?;
            let references = sources
                .iter()
                .filter(|source| {
                    snapshots.iter().any(|snapshot| {
                        let owner = snapshot.integration().record();
                        owner.integration_id.value()
                            == source.selection().reference().integration_id()
                            && owner.current_revision_fingerprint.as_deref()
                                == Some(source.selection().reference().revision())
                    })
                })
                .collect::<Vec<_>>();
            let query = InstrumentQuery {
                query: required(&p, "query")?.into(),
                asset_class: p.get("asset_class").cloned(),
                instrument_types: p
                    .get("instrument_types")
                    .map(|s| s.split(',').map(String::from).collect())
                    .unwrap_or_default(),
                instrument_ids: vec![],
                limit: instrument_limit(&p)?,
            };
            let (value, fence) = self
                .app
                .search(&references, &session, &query, deadline)
                .await?
                .into_parts()?;
            return Ok(ingress::attach(
                Json(value).into_response(),
                Release::Batch(fence),
            ));
        }
        let reference = reference(&p)?;
        let snapshot = snapshots
            .iter()
            .find(|s| s.integration().record().integration_id.value() == reference.integration_id())
            .ok_or(Failure::with_status(
                StatusCode::NOT_FOUND,
                "MARKET_DATA_SOURCE_SELECTION_UNRESOLVED",
            ))?;
        if matches!(
            path,
            "/api/v2/market-data/bars" | "/api/v2/market-data/latest-bar"
        ) {
            let instrument = required(&p, "instrument_id")?;
            let semantic = semantic(&p)?;
            let clock_ns = now_ns()?;
            let current = self.resolver.resolve(snapshot, &reference, &session, None);
            let mut read = self.reader.lock().await;
            let mut store = Storage::new(
                Catalog::new(
                    read.as_mut()
                        .ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?,
                    ROWS,
                    WORK,
                )?,
                &self.clickhouse,
                100000,
            )?;
            let history = match &current {
                Ok(_) => None,
                Err(_) => Some(
                    HistoryContext::select(
                        snapshot,
                        &reference,
                        &session,
                        &mut store,
                        Self::identity(snapshot, &reference)?,
                        onlyalpha_plugin_binance::spot_source::spot_calendar().map_err(|_| {
                            Failure::unavailable("MARKET_DATA_HISTORY_CONTEXT_UNPROVABLE")
                        })?,
                        instrument,
                        &semantic,
                    )
                    .await?,
                ),
            };
            let result = if path.ends_with("latest-bar") {
                match (&current, &history) {
                    (Ok(r), _) => {
                        self.app
                            .latest(r, &session, &mut store, instrument, &semantic)
                            .await?
                    }
                    (_, Some(h)) => {
                        self.app
                            .historical_latest(h, &session, &mut store, clock_ns)
                            .await?
                    }
                    _ => {
                        return Err(Failure::unavailable(
                            "MARKET_DATA_HISTORY_CONTEXT_UNPROVABLE",
                        ));
                    }
                }
            } else {
                let before = p.get("before_ns");
                match p.get("anchor_kind").map(String::as_str) {
                    Some("LATEST_CLOSED") if before.is_none() => {}
                    Some("BEFORE_TIME") if before.is_some() => {}
                    _ => return Err(invalid()),
                }
                let query = WindowRequest {
                    instrument_id: instrument.into(),
                    semantic,
                    before_ns: p
                        .get("before_ns")
                        .map(|s| s.parse().map_err(|_| invalid()))
                        .transpose()?,
                    bar_count: p
                        .get("target_bar_count")
                        .map(|s| s.parse().map_err(|_| invalid()))
                        .transpose()?
                        .unwrap_or(500),
                    clock_ns,
                };
                match (&current, &history) {
                    (Ok(r), _) => self.app.window(r, &session, &mut store, &query).await?,
                    (_, Some(h)) => {
                        self.app
                            .history_window(h, &session, &mut store, &query)
                            .await?
                    }
                    _ => {
                        return Err(Failure::unavailable(
                            "MARKET_DATA_HISTORY_CONTEXT_UNPROVABLE",
                        ));
                    }
                }
            };
            let (value, fence) = result.into_parts()?;
            return Ok(ingress::attach(
                Json(value).into_response(),
                Release::Source(fence),
            ));
        }
        let resolved = match self.resolver.resolve(snapshot, &reference, &session, None) {
            Ok(r) => r,
            Err(error) => {
                if path != "/api/v2/market/instruments" {
                    return Err(error.into());
                }
                let mut read = self.reader.lock().await;
                let client = read
                    .as_mut()
                    .ok_or_else(|| Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
                let mut store =
                    Storage::new(Catalog::new(client, ROWS, WORK)?, &self.clickhouse, 100000)?;
                let query = InstrumentQuery {
                    query: p.get("query").cloned().unwrap_or_default(),
                    asset_class: None,
                    instrument_types: vec![],
                    instrument_ids: p
                        .get("instrument_ids")
                        .map(|s| s.split(',').map(String::from).collect())
                        .unwrap_or_default(),
                    limit: 100,
                };
                let (value, fence) = self
                    .app
                    .historical_instruments(
                        snapshot,
                        &reference,
                        &session,
                        &mut store,
                        Self::identity(snapshot, &reference)?,
                        onlyalpha_plugin_binance::spot_source::spot_calendar().map_err(|_| {
                            Failure::unavailable("MARKET_DATA_HISTORY_CONTEXT_UNPROVABLE")
                        })?,
                        &query,
                    )
                    .await?
                    .into_parts()?;
                return Ok(ingress::attach(
                    Json(value).into_response(),
                    Release::Batch(fence),
                ));
            }
        };
        if let Some(id) = path.strip_prefix("/api/v2/market-data/acquisitions/") {
            let mut read = self.reader.lock().await;
            let client = read
                .as_mut()
                .ok_or_else(|| Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            let mut store =
                Storage::new(Catalog::new(client, ROWS, WORK)?, &self.clickhouse, 100000)?;
            let (value, fence) = self
                .app
                .acquisition_status(&resolved, &session, &mut store, id, None)
                .await?
                .into_parts()?;
            return Ok(ingress::attach(
                Json(value).into_response(),
                Release::Source(fence),
            ));
        }
        let result = match path {
            "/api/v2/market/instruments" | "/api/v2/market/instruments/search" => {
                let query = InstrumentQuery {
                    query: p.get("query").cloned().unwrap_or_default(),
                    asset_class: p.get("asset_class").cloned(),
                    instrument_types: vec![],
                    instrument_ids: p
                        .get("instrument_ids")
                        .map(|s| s.split(',').map(String::from).collect())
                        .unwrap_or_default(),
                    limit: instrument_limit(&p)?,
                };
                if path.ends_with("search") {
                    let (value, fence) = self
                        .app
                        .search(&[&resolved], &session, &query, deadline)
                        .await?
                        .into_parts()?;
                    return Ok(ingress::attach(
                        Json(value).into_response(),
                        Release::Batch(fence),
                    ));
                } else {
                    self.app
                        .instruments(&resolved, &session, &query, deadline)
                        .await?
                }
            }
            "/api/v2/market-data/quotes" => {
                self.app
                    .quotes(
                        &resolved,
                        &session,
                        &required(&p, "instrument_ids")?
                            .split(',')
                            .map(String::from)
                            .collect::<Vec<_>>(),
                        deadline,
                    )
                    .await?
            }
            _ => return Err(Failure::unavailable("MARKET_DATA_OPERATION_UNAVAILABLE")),
        };
        let (value, fence) = result.into_parts()?;
        Ok(ingress::attach(
            Json(value).into_response(),
            Release::Source(fence),
        ))
    }
}
pub(crate) fn invalid() -> Failure {
    Failure(StatusCode::BAD_REQUEST, "PRODUCT_REQUEST_INVALID")
}
pub(crate) fn required<'a>(
    p: &'a BTreeMap<String, String>,
    name: &str,
) -> Result<&'a str, Failure> {
    p.get(name)
        .map(String::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(invalid)
}
pub(crate) fn parameters(uri: &http::Uri) -> Result<BTreeMap<String, String>, Failure> {
    let mut p = BTreeMap::new();
    for pair in uri
        .query()
        .unwrap_or_default()
        .split('&')
        .filter(|s| !s.is_empty())
    {
        let (k, v) = pair.split_once('=').ok_or_else(invalid)?;
        let decode = |s: &str| {
            percent_encoding::percent_decode_str(&s.replace('+', " "))
                .decode_utf8()
                .map(|s| s.into_owned())
                .map_err(|_| invalid())
        };
        let key = decode(k)?;
        let value = decode(v)?;
        if matches!(key.as_str(), "instrument_ids" | "instrument_types") {
            p.entry(key)
                .and_modify(|v: &mut String| {
                    v.push(',');
                    v.push_str(&value)
                })
                .or_insert(value);
        } else if p.insert(key, value).is_some() {
            return Err(invalid());
        }
    }
    Ok(p)
}
pub(crate) fn reference(p: &BTreeMap<String, String>) -> Result<Reference, Failure> {
    Ok(Reference::new(
        required(p, "integration_id")?,
        required(p, "integration_revision_fingerprint")?,
        p.get("expected_type_id").map(String::as_str),
    )?)
}
fn instrument_limit(p: &BTreeMap<String, String>) -> Result<usize, Failure> {
    p.get("limit")
        .map(|value| value.parse().map_err(|_| invalid()))
        .transpose()
        .map(|limit| limit.unwrap_or(25))
}
#[cfg(test)]
mod instrument_query_tests {
    use super::*;
    #[test]
    fn omitted_instrument_limit_is_admitted_by_the_current_application_contract() {
        assert_eq!(instrument_limit(&BTreeMap::new()).unwrap(), 25);
        assert_eq!(
            instrument_limit(&BTreeMap::from([("limit".into(), "3".into())])).unwrap(),
            3
        );
        assert!(instrument_limit(&BTreeMap::from([("limit".into(), "invalid".into())])).is_err());
    }
}
pub(crate) fn semantic(
    p: &BTreeMap<String, String>,
) -> Result<onlyalpha_domain::market::OnlyBarSemantic, Failure> {
    let raw = required(p, "bar_semantic")?;
    ingress::validate_json(raw.as_bytes()).map_err(|_| invalid())?;
    OnlyBarSemantic::from_record(&serde_json::from_str(raw).map_err(|_| invalid())?)
        .map_err(|_| invalid())
}
use onlyalpha_domain::market::OnlyBarSemantic;
pub(crate) fn now_ns() -> Result<i64, Failure> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()
        .and_then(|d| i64::try_from(d.as_nanos()).ok())
        .ok_or_else(|| Failure::unavailable("CLOCK_UNAVAILABLE"))
}
// Durable wall observations sample the Domain's explicit microsecond precision.
// Market nanosecond facts continue through now_ns without quantization.
pub(crate) fn observation_time(
    at: std::time::SystemTime,
) -> Result<onlyalpha_domain::time::OnlyUtcDateTime, Failure> {
    let micros = at
        .duration_since(std::time::UNIX_EPOCH)
        .ok()
        .and_then(|d| i64::try_from(d.as_micros()).ok())
        .ok_or_else(|| Failure::unavailable("CLOCK_UNAVAILABLE"))?;
    onlyalpha_domain::time::OnlyTimestamp::from_unix_micros(micros.into())
        .to_datetime_exact()
        .map_err(|_| Failure::unavailable("CLOCK_UNAVAILABLE"))
}
pub(crate) fn now() -> Result<onlyalpha_domain::time::OnlyUtcDateTime, Failure> {
    observation_time(std::time::SystemTime::now())
}
#[cfg(test)]
mod clock_tests {
    #[test]
    fn wall_observation_samples_explicit_microseconds() {
        let at = std::time::UNIX_EPOCH + std::time::Duration::from_nanos(123_456_789);
        assert_eq!(
            super::observation_time(at).unwrap().to_string(),
            "1970-01-01T00:00:00.123456Z"
        );
        assert!(
            super::observation_time(std::time::UNIX_EPOCH - std::time::Duration::from_nanos(1))
                .is_err()
        );
        assert!(
            onlyalpha_domain::time::OnlyTimestamp::from_unix_nanos(123_456_789i64.into())
                .to_datetime_exact()
                .is_err()
        );
    }
}

impl std::fmt::Display for Failure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.1)
    }
}
impl std::error::Error for Failure {}

impl Host {
    pub(crate) async fn withdraw_sources(&self) -> Result<(), Failure> {
        let issuer = self.issuer.lock().await;
        self.revoker
            .get()
            .ok_or_else(|| Failure::unavailable("SOURCE_GATE_UNAVAILABLE"))?
            .withdraw(&issuer.authority)
            .map_err(|_| Failure::unavailable("SOURCE_GATE_UNAVAILABLE"))
    }
    pub(crate) async fn replace_sources(&self, snapshots: &[Snapshot]) -> Result<(), Failure> {
        let next = issue(grants(snapshots)?)?;
        let mut issuer = self.issuer.lock().await;
        self.revoker
            .get()
            .ok_or_else(|| Failure::unavailable("SOURCE_GATE_UNAVAILABLE"))?
            .withdraw(&issuer.authority)
            .map_err(|_| Failure::unavailable("SOURCE_GATE_UNAVAILABLE"))?;
        *issuer = next;
        Ok(())
    }
}
pub(crate) fn grants(snapshots: &[Snapshot]) -> Result<Vec<Grant>, Failure> {
    let mut grants = vec![];
    for snapshot in snapshots {
        let owner = snapshot.integration().record();
        if owner.lifecycle
            != onlyalpha_product_runtime::integration_configuration::Lifecycle::Active
            || owner.type_id.value() != "binance.spot.market_data"
        {
            continue;
        }
        for (revision, _) in snapshot.history() {
            let reference = Reference::new(
                owner.integration_id.value(),
                &revision.record().revision_fingerprint,
                Some(owner.type_id.value()),
            )?;
            let identity = Host::identity(snapshot, &reference)?;
            grants.push(Grant::new(
                Selection::new(reference, &identity.source_id, &identity.environment)?,
                vec![Permission::ClosedHistory, Permission::RealtimePreview],
            )?);
        }
    }
    Ok(grants)
}

pub(crate) fn uuid() -> Result<String, Failure> {
    let mut bytes = [0u8; 16];
    getrandom::fill(&mut bytes)
        .map_err(|_| Failure::unavailable("IDENTITY_ENTROPY_UNAVAILABLE"))?;
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    let h: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
    Ok(format!(
        "{}-{}-{}-{}-{}",
        &h[..8],
        &h[8..12],
        &h[12..16],
        &h[16..20],
        &h[20..]
    ))
}

#[cfg(test)]
mod command_error_tests {
    use super::*;
    use onlyalpha_product_runtime::{
        integration_commands::Error as IntegrationError, watchlists::Error as WatchlistError,
    };
    #[test]
    fn integration_intent_errors_preserve_public_status_and_unknown() {
        for error in [IntegrationError::NotFound, IntegrationError::DraftNotFound] {
            assert_eq!(Failure::from(error).0, StatusCode::NOT_FOUND);
        }
        for error in [
            IntegrationError::DraftVersion,
            IntegrationError::BaseRevision,
            IntegrationError::LifecycleConflict,
            IntegrationError::Command(onlyalpha_product_runtime::command::Error::Conflict),
        ] {
            assert_eq!(Failure::from(error).0, StatusCode::CONFLICT);
        }
        for error in [
            IntegrationError::InvalidConfiguration,
            IntegrationError::SecretField,
        ] {
            assert_eq!(Failure::from(error).0, StatusCode::BAD_REQUEST);
        }
        let unknown = Failure::from(IntegrationError::Unknown);
        assert_eq!(unknown.0, StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(unknown.1, "PRODUCT_COMMAND_OUTCOME_UNKNOWN");
    }
    #[test]
    fn watchlist_conflict_is_distinct_from_unknown_and_corrupt() {
        for error in [
            WatchlistError::CommandConflict,
            WatchlistError::VersionConflict,
        ] {
            assert_eq!(Failure::from(error).0, StatusCode::CONFLICT);
        }
        assert_eq!(
            Failure::from(WatchlistError::Invalid).0,
            StatusCode::BAD_REQUEST
        );
        for error in [
            WatchlistError::CommandUnknown,
            WatchlistError::HistoryCorrupt,
            WatchlistError::Unavailable,
        ] {
            let failure = Failure::from(error);
            assert_eq!(failure.0, StatusCode::SERVICE_UNAVAILABLE);
            assert_eq!(failure.1, error.code());
        }
    }
}

#[cfg(test)]
mod chart_admission_tests {
    use super::*;
    use std::{
        future::Future,
        task::{Context, Poll, Waker},
        time::Duration,
    };
    use tokio::sync::{Semaphore, oneshot};

    #[tokio::test(flavor = "current_thread")]
    async fn two_chart_owners_can_progress_but_a_third_keeps_its_bounded_queue() {
        let gate = Arc::new(Semaphore::new(ChartQuery::MAX_CONCURRENT_INVOCATIONS));
        let first = chart_permit(Arc::clone(&gate), Instant::now() + Duration::from_secs(10))
            .await
            .unwrap();
        let mut second = Box::pin(chart_permit(
            Arc::clone(&gate),
            Instant::now() + Duration::from_secs(10),
        ));
        let second = match second
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
        {
            Poll::Ready(Ok(permit)) => Some(permit),
            _ => None,
        };
        assert!(
            second.is_some(),
            "the second page must make progress without waiting for the first"
        );
        let mut third = Box::pin(chart_permit(
            Arc::clone(&gate),
            Instant::now() + Duration::from_secs(10),
        ));
        assert!(
            third
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop()))
                .is_pending()
        );
        drop(third);
        assert_eq!(
            gate.available_permits(),
            0,
            "queue cancellation cannot release either owner"
        );
        drop(first);
        assert_eq!(gate.available_permits(), 1);
        drop(second);
        assert_eq!(gate.available_permits(), 2);
    }

    async fn occupied() -> (
        Arc<Semaphore>,
        std::sync::mpsc::Sender<()>,
        tokio::task::JoinHandle<()>,
    ) {
        let gate = Arc::new(Semaphore::new(1));
        let permit = chart_permit(Arc::clone(&gate), Instant::now() + Duration::from_secs(10))
            .await
            .unwrap();
        let (started, observed) = oneshot::channel();
        let (release, wait) = std::sync::mpsc::channel();
        let worker = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            started.send(()).unwrap();
            wait.recv().unwrap();
        });
        observed.await.unwrap();
        (gate, release, worker)
    }

    #[tokio::test(flavor = "current_thread")]
    async fn another_chart_read_waits_for_the_original_blocking_worker() {
        let (gate, release, worker) = occupied().await;
        let mut request = Box::pin(chart_permit(
            Arc::clone(&gate),
            Instant::now() + Duration::from_secs(10),
        ));
        let pending = request
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending();
        let held = gate.available_permits() == 0;
        release.send(()).unwrap();
        worker.await.unwrap();
        drop(request);
        assert!(
            pending,
            "concurrent metadata read was rejected instead of awaiting its original deadline"
        );
        assert!(held);
        let next = chart_permit(Arc::clone(&gate), Instant::now() + Duration::from_secs(10))
            .await
            .unwrap();
        assert_eq!(gate.available_permits(), 0);
        drop(next);
        assert_eq!(gate.available_permits(), 1);
    }

    #[tokio::test(flavor = "current_thread")]
    async fn cancelling_a_queued_chart_read_cannot_release_the_active_owner() {
        let (gate, release, worker) = occupied().await;
        let mut cancelled = Box::pin(chart_permit(
            Arc::clone(&gate),
            Instant::now() + Duration::from_secs(10),
        ));
        let first_pending = cancelled
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending();
        drop(cancelled);
        let mut next = Box::pin(chart_permit(
            Arc::clone(&gate),
            Instant::now() + Duration::from_secs(10),
        ));
        let next_pending = next
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending();
        let held = gate.available_permits() == 0;
        release.send(()).unwrap();
        worker.await.unwrap();
        if next_pending {
            drop(next.await.unwrap());
        } else {
            drop(next);
        }
        assert!(
            first_pending && next_pending && held,
            "queue cancellation did not preserve the active owner"
        );
        assert_eq!(gate.available_permits(), 1);
    }

    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn chart_queue_uses_the_original_deadline_without_releasing_active_work() {
        let gate = Arc::new(Semaphore::new(1));
        let active = Arc::clone(&gate).acquire_owned().await.unwrap();
        let mut request = Box::pin(chart_permit(
            Arc::clone(&gate),
            Instant::now() + Duration::from_secs(10),
        ));
        let initial = request
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()));
        let pending = initial.is_pending();
        let result = match initial {
            Poll::Ready(result) => result,
            Poll::Pending => {
                tokio::time::advance(Duration::from_secs(10)).await;
                request.await
            }
        };
        let code = result.err().map(|error| error.1);
        let held = gate.available_permits() == 0;
        drop(active);
        assert!(pending && held);
        assert_eq!(code, Some("REQUEST_DEADLINE_EXPIRED"));
        assert_eq!(gate.available_permits(), 1);
    }

    #[tokio::test(flavor = "current_thread")]
    async fn an_expired_chart_request_never_acquires_an_idle_worker() {
        let gate = Arc::new(Semaphore::new(1));
        let result = chart_permit(Arc::clone(&gate), Instant::now() - Duration::from_secs(1)).await;
        let code = result.err().map(|error| error.1);
        assert_eq!(code, Some("REQUEST_DEADLINE_EXPIRED"));
        assert_eq!(gate.available_permits(), 1);
    }
}
