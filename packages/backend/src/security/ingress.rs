//! Private Source REST ingress. The supplied router retains all Product authority.
use crate::application::chart::ChartFence;
use crate::application::market_product::{BatchFence, SendFence};
use crate::application::private_assets::AssetFence;
use crate::application::source_access::Authority as SourceAuthority;
use crate::application::source_access::Session;
use crate::bootstrap::configuration::Configuration;
use crate::security::human_access::{
    Access as HumanAccess, Admission as HumanAdmission, Session as HumanSession,
};
use crate::transport::endpoint::Transport;
use axum::{
    Json, Router,
    body::{Body, to_bytes},
    response::{IntoResponse, Response},
};
use http::{HeaderMap, Method, Request, StatusCode, Uri};
use hyper::{
    body::Incoming,
    server::conn::http1,
    service::{Service, service_fn},
};
use hyper_util::{
    rt::{TokioIo, TokioTimer},
    service::TowerToHyperService,
};
use percent_encoding::percent_decode_str;
use serde::{
    Deserialize, Deserializer,
    de::{MapAccess, SeqAccess, Visitor},
};
use serde_json::json;
use std::{
    collections::{BTreeMap, HashSet},
    convert::Infallible,
    fmt, io,
    pin::Pin,
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, AtomicUsize, Ordering},
    },
    task::{Context, Poll},
    time::Duration,
};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, ReadBuf},
    net::TcpStream,
    sync::{OwnedSemaphorePermit, Semaphore, oneshot, watch},
    time::{Instant, sleep_until, timeout_at},
};
const READS: usize = 4;
const WORKSTATION_WAITERS: usize = 16;
const RESPONSE_LIMIT: usize = 8 * 1024 * 1024;
const HEADER_LIMIT: usize = 64 * 1024;
const HEADER_COUNT: usize = 64;
const SEND_BUDGET: Duration = Duration::from_secs(5);
const CHART_BUDGET: Duration = Duration::from_secs(10);
const CAPABILITIES: &str = "/api/v2/chart/studies/capabilities";
const EVALUATE: &str = "/api/v2/chart/studies/evaluate";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    UnsupportedTransport,
    ConnectionUnavailable,
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::UnsupportedTransport => "LOCAL_READ_TRANSPORT_INVALID",
            Self::ConnectionUnavailable => "LOCAL_READ_RESPONSE_UNAVAILABLE",
        })
    }
}
impl std::error::Error for Error {}
/// Only actual owning output values can be attached to a physical connection.
/// No request field, deserializer or caller boolean constructs a release proof.
// Releases are retained only behind Arc; boxing a fence adds a second allocation.
#[allow(clippy::large_enum_variant)]
pub(crate) enum Release {
    Source(SendFence),
    Batch(BatchFence),
    Chart(ChartFence),
    Asset(AssetFence),
    Generation(Session),
    Proposal(Session, onlyalpha_domain::time::OnlyUtcDateTime),
}
impl Release {
    fn active(&self) -> bool {
        match self {
            Self::Source(p) => p.check().is_ok(),
            Self::Batch(p) => p.check().is_ok(),
            Self::Chart(p) => p.check().is_ok(),
            Self::Asset(p) => p.check().is_ok(),
            Self::Generation(s) => s.check_active().is_ok(),
            Self::Proposal(s, expiry) => s.check_active().is_ok() && crate::transport::host::now().is_ok_and(|at|at<*expiry),
        }
    }
    pub(crate) fn attach(self, response: &mut Response) {
        response.extensions_mut().insert(Arc::new(self));
    }
}
#[derive(Clone, Copy)]
pub(crate) struct RequestDeadline(pub std::time::Instant);
/// Retains the actual physical connection after a Hyper upgrade; it cannot be
/// reconstructed by a route from a session ID or by a browser request.
#[derive(Clone)]
pub(crate) struct PhysicalConnection {
    state: Arc<State>,
    id: u64,
    _owner: Arc<ConnectionGuard>,
}
impl PhysicalConnection {
    /// Only called after Hyper's actual upgrade future completed: the HTTP
    /// headers have left its buffers, and the bounded WS owner is retained.
    pub(crate) fn upgraded(&self, proof: Arc<Release>) -> Result<(), Error> {
        let mut gate = self
            .state
            .gate
            .lock()
            .map_err(|_| Error::ConnectionUnavailable)?;
        if gate.shutdown || !proof.active() {
            return Err(Error::ConnectionUnavailable);
        }
        let entry = gate
            .connections
            .get_mut(&self.id)
            .ok_or(Error::ConnectionUnavailable)?;
        entry.release = Some(proof);
        entry.permit = None;
        entry.send_deadline = None;
        self.state.signal.send_replace(());
        Ok(())
    }

    pub(crate) fn frame(&self, proof: Arc<Release>) -> Result<(), Error> {
        let mut gate = self
            .state
            .gate
            .lock()
            .map_err(|_| Error::ConnectionUnavailable)?;
        if gate.shutdown || !proof.active() {
            return Err(Error::ConnectionUnavailable);
        }
        let entry = gate
            .connections
            .get_mut(&self.id)
            .ok_or(Error::ConnectionUnavailable)?;
        if entry
            .session
            .as_ref()
            .is_none_or(|p| !self.state.mode.active(p))
        {
            return Err(Error::ConnectionUnavailable);
        }
        entry.release = Some(proof);
        entry.send_deadline = Some(Instant::now() + SEND_BUDGET);
        self.state.signal.send_replace(());
        Ok(())
    }
    pub(crate) fn idle(&self, proof: Arc<Release>) -> Result<(), Error> {
        let mut gate = self
            .state
            .gate
            .lock()
            .map_err(|_| Error::ConnectionUnavailable)?;
        if gate.shutdown {
            return Err(Error::ConnectionUnavailable);
        }
        let entry = gate
            .connections
            .get_mut(&self.id)
            .ok_or(Error::ConnectionUnavailable)?;
        if !proof.active() {
            return Err(Error::ConnectionUnavailable);
        }
        entry.release = Some(proof);
        entry.send_deadline = None;
        self.state.signal.send_replace(());
        Ok(())
    }
    // Completes one already-admitted frame while retaining its physical owner.
    pub(crate) async fn complete_frame<E>(
        &self,
        writing: impl std::future::Future<Output = Result<(), E>>,
    ) -> Result<(), Error> {
        // Reuse frame()'s original budget; never start a fresh timeout after
        // the sink has queued bytes or entered a Pending flush.
        let deadline = self
            .state
            .gate
            .lock()
            .map_err(|_| Error::ConnectionUnavailable)?
            .connections
            .get(&self.id)
            .and_then(|entry| entry.send_deadline)
            .ok_or(Error::ConnectionUnavailable)?;
        tokio::select! { biased;
            _ = self.closed() => Err(Error::ConnectionUnavailable),
            _ = sleep_until(deadline) => Err(Error::ConnectionUnavailable),
            result = writing => result.map_err(|_| Error::ConnectionUnavailable),
        }
    }
    pub(crate) async fn closed(&self) {
        let mut signal = self.state.signal.subscribe();
        loop {
            let active = self.state.gate.lock().is_ok_and(|gate| {
                !gate.shutdown
                    && gate.connections.get(&self.id).is_some_and(|e| {
                        e.session
                            .as_ref()
                            .is_some_and(|p| self.state.mode.active(p))
                            && e.release.as_ref().is_none_or(|p| p.active())
                    })
            });
            if !active || signal.changed().await.is_err() {
                return;
            }
        }
    }
}

struct ConnectionEntry {
    session: Option<Proof>,
    permit: Option<Arc<OwnedSemaphorePermit>>,
    send_deadline: Option<Instant>,
    release: Option<Arc<Release>>,
}
struct Gate {
    shutdown: bool,
    connections: BTreeMap<u64, ConnectionEntry>,
}
struct State {
    mode: Mode,
    app: Router,
    chart: bool,
    workstation: bool,
    transport: Transport,
    gate: Mutex<Gate>,
    signal: watch::Sender<()>,
    slots: Arc<Semaphore>,
    waiters: Arc<Semaphore>,
    next: AtomicU64,
    work: AtomicUsize,
}
// Only the owning ingress can bind these proofs to a connection. Bootstrap is
// an anonymous response fence, never an identity supplied to an application.
#[derive(Clone)]
enum Proof {
    Source(Session),
    Human(HumanSession),
    Bootstrap,
    // Route/body-capacity context only, not an authenticated principal. Owning DB grants decide.
    Proposal(crate::security::proposal_access::Presented),
}
enum Mode {
    Private(Configuration),
    Developer(HumanAccess),
}
impl Mode {
    fn origin(&self) -> &str {
        match self {
            Self::Private(config) => config.origin(),
            Self::Developer(_) => crate::security::human_access::ORIGIN,
        }
    }
    fn active(&self, proof: &Proof) -> bool {
        match (self, proof) {
            (Self::Private(config), Proof::Source(session)) => {
                config.authority().check_session(session).is_ok()
            }
            (Self::Developer(access), Proof::Human(session)) => {
                access.check_session(session).is_ok()
            }
            (Self::Developer(access), Proof::Bootstrap | Proof::Proposal(_)) => access.check_active().is_ok(),
            _ => false,
        }
    }
    fn withdraw(&self) {
        match self {
            Self::Private(config) => config.authority().withdraw(),
            Self::Developer(access) => access.withdraw(),
        }
    }
}
struct RequestPlan {
    proof: Proof,
    size: usize,
    chart: bool,
    cookie: Option<http::HeaderValue>,
}

#[derive(Clone)]
pub struct LocalIngress {
    state: Arc<State>,
}
/// Weak physical gate handle; avoids a Host/router/ingress ownership cycle.
#[derive(Clone)]
pub(crate) struct SourceRevoker(std::sync::Weak<State>);
impl SourceRevoker {
    pub(crate) fn withdraw(&self, authority: &SourceAuthority) -> Result<(), Error> {
        let state = self.0.upgrade().ok_or(Error::ConnectionUnavailable)?;
        let _gate = state
            .gate
            .lock()
            .map_err(|_| Error::ConnectionUnavailable)?;
        authority.withdraw();
        state.signal.send_replace(());
        Ok(())
    }
}
impl LocalIngress {
    pub(crate) fn source_revoker(&self) -> SourceRevoker {
        SourceRevoker(Arc::downgrade(&self.state))
    }
    /// Clear HTTP is restricted to verified loopback sockets. HTTPS needs its own
    /// TLS composition with the write gate below the TLS buffers; never downgrade.
    pub fn new(configuration: Configuration, app: Router, chart: bool) -> Result<Self, Error> {
        let scheme = configuration
            .origin()
            .split_once("://")
            .map(|value| value.0);
        if !scheme.is_some_and(|value| value.eq_ignore_ascii_case("http")) {
            return Err(Error::UnsupportedTransport);
        }
        Ok(Self::compose(Mode::Private(configuration), app, chart))
    }
    /// Explicit local Human read composition. No Source, Command or bridge
    /// permission is implied; actual sockets still require loopback and port5173.
    pub fn new_developer(access: HumanAccess, app: Router) -> Self {
        Self::compose(Mode::Developer(access), app, false)
    }
    pub fn new_workstation(access: HumanAccess, app: Router, transport: Transport) -> Self {
        let mut ingress = Self::compose(Mode::Developer(access), app, true);
        let state = Arc::get_mut(&mut ingress.state).expect("new unshared ingress");
        state.workstation = true;
        state.transport = transport;
        ingress
    }
    pub fn withdraw_source(&self, authority: &SourceAuthority) -> Result<(), Error> {
        let _gate = self
            .state
            .gate
            .lock()
            .map_err(|_| Error::ConnectionUnavailable)?;
        authority.withdraw();
        self.state.signal.send_replace(());
        Ok(())
    }
    fn compose(mode: Mode, app: Router, chart: bool) -> Self {
        let (signal, _) = watch::channel(());
        let port = match &mode {
            Mode::Developer(_) => 5173,
            Mode::Private(c) => c
                .origin()
                .parse::<Uri>()
                .ok()
                .and_then(|u| u.port_u16())
                .unwrap_or(80),
        };
        Self {
            state: Arc::new(State {
                mode,
                app,
                chart,
                workstation: false,
                transport: Transport::Loopback { port },
                gate: Mutex::new(Gate {
                    shutdown: false,
                    connections: BTreeMap::new(),
                }),
                signal,
                slots: Arc::new(Semaphore::new(READS)),
                waiters: Arc::new(Semaphore::new(WORKSTATION_WAITERS)),
                next: AtomicU64::new(0),
                work: AtomicUsize::new(0),
            }),
        }
    }
    /// Server-side cutoff: no subsequent old-session write can be accepted by the
    /// underlying transport. Previously accepted OS bytes cannot be retracted.
    pub fn withdraw(&self) -> Result<(), Error> {
        let _gate = self
            .state
            .gate
            .lock()
            .map_err(|_| Error::ConnectionUnavailable)?;
        self.state.mode.withdraw();
        self.state.signal.send_replace(());
        Ok(())
    }
    pub fn shutdown(&self) -> Result<(), Error> {
        let mut gate = self
            .state
            .gate
            .lock()
            .map_err(|_| Error::ConnectionUnavailable)?;
        gate.shutdown = true;
        self.state.signal.send_replace(());
        Ok(())
    }
    /// Close admission/writes and wait for this ingress's actual connections
    /// and retained work. The Host separately owns its listener, query drivers
    /// and mutation authority. Cancellation leaves shutdown permanently closed;
    /// it is not a drain acknowledgement or permission to release the guard.
    pub async fn shutdown_and_drain(&self) -> Result<(), Error> {
        let mut signal = self.state.signal.subscribe();
        self.shutdown()?;
        loop {
            {
                let gate = self
                    .state
                    .gate
                    .lock()
                    .map_err(|_| Error::ConnectionUnavailable)?;
                if gate.connections.is_empty()
                    && self.active_work() == 0
                    && self.retained_reads() == 0
                {
                    return Ok(());
                }
            }
            signal
                .changed()
                .await
                .map_err(|_| Error::ConnectionUnavailable)?;
        }
    }
    pub fn active_work(&self) -> usize {
        self.state.work.load(Ordering::Acquire)
    }
    pub fn retained_reads(&self) -> usize {
        READS - self.state.slots.available_permits()
    }
    pub async fn serve_connection(&self, stream: TcpStream) -> Result<(), Error> {
        let local = stream
            .local_addr()
            .map_err(|_| Error::ConnectionUnavailable)?;
        let peer = stream
            .peer_addr()
            .map_err(|_| Error::ConnectionUnavailable)?;
        let origin: Uri = self
            .state
            .mode
            .origin()
            .parse()
            .map_err(|_| Error::UnsupportedTransport)?;
        if !self.state.transport.permits(local, peer)
            || local.port() != origin.port_u16().unwrap_or(80)
        {
            return Err(Error::UnsupportedTransport);
        }
        self.serve_stream(stream).await
    }
    async fn serve_stream<I: AsyncRead + AsyncWrite + Unpin + Send + 'static>(
        &self,
        io: I,
    ) -> Result<(), Error> {
        let id = self
            .state
            .next
            .try_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                value.checked_add(1)
            })
            .map_err(|_| Error::ConnectionUnavailable)?;
        let mut signal = self.state.signal.subscribe();
        {
            let mut gate = self
                .state
                .gate
                .lock()
                .map_err(|_| Error::ConnectionUnavailable)?;
            if gate.shutdown {
                return Err(Error::ConnectionUnavailable);
            }
            gate.connections.insert(
                id,
                ConnectionEntry {
                    session: None,
                    permit: None,
                    send_deadline: None,
                    release: None,
                },
            );
        }
        let connection_owner = Arc::new(ConnectionGuard {
            state: Arc::clone(&self.state),
            id,
        });
        let mut io = WriteGate {
            io,
            state: Arc::clone(&self.state),
            id,
        };
        let header_deadline = Instant::now() + SEND_BUDGET;
        let (prefix, duplicate_length) = {
            let headers = timeout_at(header_deadline, preflight(&mut io));
            tokio::pin!(headers);
            loop {
                if self
                    .state
                    .gate
                    .lock()
                    .map_err(|_| Error::ConnectionUnavailable)?
                    .shutdown
                {
                    return Err(Error::ConnectionUnavailable);
                }
                tokio::select! { biased;
                    _ = signal.changed() => {},
                    result = &mut headers => break result.map_err(|_| Error::ConnectionUnavailable)??,
                }
            }
        };
        let owned = self.clone();
        let retained_owner = Arc::clone(&connection_owner);
        let service = service_fn(move |request: Request<Incoming>| {
            let owned = owned.clone();
            let owner = Arc::clone(&retained_owner);
            async move {
                let mut request = request;
                request.extensions_mut().insert(PhysicalConnection {
                    state: Arc::clone(&owned.state),
                    id,
                    _owner: owner,
                });
                Ok::<_, Infallible>(owned.request(id, request, duplicate_length).await)
            }
        });
        let mut builder = http1::Builder::new();
        builder
            .keep_alive(false)
            .half_close(false)
            .ignore_invalid_headers(false)
            .allow_multiple_spaces_in_request_line_delimiters(false)
            .max_headers(HEADER_COUNT)
            .max_header_size(HEADER_LIMIT)
            .max_buf_size(HEADER_LIMIT)
            .auto_date_header(false)
            .timer(TokioTimer::new())
            .header_read_timeout(header_deadline.saturating_duration_since(Instant::now()));
        let connection = builder
            .serve_connection(
                TokioIo::new(PrefixIo {
                    io,
                    prefix,
                    offset: 0,
                }),
                service,
            )
            .with_upgrades();
        tokio::pin!(connection);
        loop {
            let deadline = {
                let gate = self
                    .state
                    .gate
                    .lock()
                    .map_err(|_| Error::ConnectionUnavailable)?;
                let entry = gate
                    .connections
                    .get(&id)
                    .ok_or(Error::ConnectionUnavailable)?;
                if gate.shutdown
                    || entry
                        .session
                        .as_ref()
                        .is_some_and(|proof| !self.state.mode.active(proof))
                    || entry.release.as_ref().is_some_and(|proof| !proof.active())
                {
                    return Err(Error::ConnectionUnavailable);
                }
                entry.send_deadline
            };
            if let Some(deadline) = deadline {
                tokio::select! { biased;
                    _ = signal.changed() => {},
                    _ = sleep_until(deadline) => return Err(Error::ConnectionUnavailable),
                    result = &mut connection => return result.map_err(|_| Error::ConnectionUnavailable),
                }
            } else {
                tokio::select! { biased;
                    _ = signal.changed() => {},
                    result = &mut connection => return result.map_err(|_| Error::ConnectionUnavailable),
                }
            }
        }
    }
    fn ready(&self, id: u64, ready_at: Instant, query_deadline: Option<Instant>) {
        let deadline = ready_at + SEND_BUDGET;
        let deadline = query_deadline.map_or(deadline, |query| deadline.min(query));
        if let Ok(mut gate) = self.state.gate.lock() {
            if let Some(entry) = gate.connections.get_mut(&id) {
                entry.send_deadline.get_or_insert(deadline);
            }
            self.state.signal.send_replace(());
        }
    }
    async fn request(
        &self,
        id: u64,
        request: Request<Incoming>,
        duplicate_length: bool,
    ) -> Response {
        let mut response = self.prepare_request(id, request, duplicate_length).await;
        if matches!(self.state.mode, Mode::Developer(_)) {
            let headers = response.headers_mut();
            headers.insert("cache-control", http::HeaderValue::from_static("no-store"));
            headers.insert("x-frame-options", http::HeaderValue::from_static("DENY"));
            headers.insert(
                "content-security-policy",
                http::HeaderValue::from_static("frame-ancestors 'none'"),
            );
        }
        if let Some(release) = response.extensions_mut().remove::<Arc<Release>>() {
            let Ok(mut gate) = self.state.gate.lock() else {
                return deny(
                    "LOCAL_READ_RESPONSE_UNAVAILABLE",
                    StatusCode::SERVICE_UNAVAILABLE,
                );
            };
            let Some(entry) = gate.connections.get_mut(&id) else {
                return deny(
                    "LOCAL_READ_RESPONSE_UNAVAILABLE",
                    StatusCode::SERVICE_UNAVAILABLE,
                );
            };
            if !release.active() {
                return deny("LOCAL_READ_FORBIDDEN", StatusCode::FORBIDDEN);
            }
            entry.release = Some(release);
        }
        self.ready(id, Instant::now(), None);
        response
    }
    async fn prepare_request(
        &self,
        id: u64,
        mut request: Request<Incoming>,
        duplicate_length: bool,
    ) -> Response {
        let entered_at = Instant::now();
        let configuration = match &self.state.mode {
            Mode::Private(configuration) => configuration,
            Mode::Developer(access) => {
                return self
                    .prepare_developer(id, request, duplicate_length, access)
                    .await;
            }
        };
        let Some(path) = decoded_path(request.uri()) else {
            return deny("LOCAL_READ_FORBIDDEN", StatusCode::FORBIDDEN);
        };
        let health = request.method() == Method::GET
            && matches!(path.as_str(), "/health/live" | "/health/ready");
        if health {
            let Ok(uri) = normalized_uri(request.uri(), &path) else {
                return deny("LOCAL_READ_FORBIDDEN", StatusCode::FORBIDDEN);
            };
            *request.uri_mut() = uri;
            return match timeout_at(
                Instant::now() + SEND_BUDGET,
                capture(self.state.app.clone(), request.map(Body::new)),
            )
            .await
            {
                Ok(Some(response)) => response,
                _ => deny(
                    "LOCAL_READ_RESPONSE_UNAVAILABLE",
                    StatusCode::SERVICE_UNAVAILABLE,
                ),
            };
        }
        let chart = self.state.chart
            && ((request.method() == Method::GET && path == CAPABILITIES)
                || (request.method() == Method::POST && path == EVALUATE));
        let read = request.method() == Method::GET && private_read(&path);
        if (!chart && !read) || duplicate_length || !valid_headers(configuration, &request, chart) {
            return deny("LOCAL_READ_FORBIDDEN", StatusCode::FORBIDDEN);
        }
        let size = one(request.headers(), "content-length")
            .and_then(|value| value.parse::<usize>().ok())
            .unwrap_or(0);
        let post = request.method() == Method::POST;
        if chart && (size > 65536 || (post && size == 0)) {
            return deny("CHART_STUDY_REQUEST_INVALID", StatusCode::BAD_REQUEST);
        }
        let session = match one(request.headers(), "authorization")
            .and_then(|value| configuration.authority().authenticate(value).ok())
        {
            Some(session) => session,
            None => return deny("LOCAL_READ_UNAUTHORIZED", StatusCode::UNAUTHORIZED),
        };
        self.dispatch(
            id,
            request,
            RequestPlan {
                proof: Proof::Source(session),
                size,
                chart,
                cookie: None,
            },
            entered_at,
        )
        .await
    }
    async fn workstation_permit(&self, deadline: Instant) -> Result<OwnedSemaphorePermit, ()> {
        if Instant::now() >= deadline {
            return Err(());
        }
        // A normal workstation opens several independent metadata queries at
        // once. Bound their queue separately from the four actual workers and
        // retain the original ingress deadline through queueing and execution.
        let queued = Arc::clone(&self.state.waiters)
            .try_acquire_owned()
            .map_err(|_| ())?;
        let permit = timeout_at(deadline, Arc::clone(&self.state.slots).acquire_owned())
            .await
            .map_err(|_| ())?
            .map_err(|_| ())?;
        drop(queued);
        if Instant::now() >= deadline {
            return Err(());
        }
        Ok(permit)
    }
    async fn dispatch(
        &self,
        id: u64,
        mut request: Request<Incoming>,
        plan: RequestPlan,
        entered_at: Instant,
    ) -> Response {
        let RequestPlan {
            proof: session,
            size,
            chart,
            cookie,
        } = plan;
        let Some(path) = decoded_path(request.uri()) else {
            return deny("LOCAL_READ_FORBIDDEN", StatusCode::FORBIDDEN);
        };
        {
            let Ok(mut gate) = self.state.gate.lock() else {
                return deny(
                    "LOCAL_READ_RESPONSE_UNAVAILABLE",
                    StatusCode::SERVICE_UNAVAILABLE,
                );
            };
            if gate.shutdown || !self.state.mode.active(&session) {
                return deny("LOCAL_READ_UNAUTHORIZED", StatusCode::UNAUTHORIZED);
            }
            let Some(entry) = gate.connections.get_mut(&id) else {
                return deny(
                    "LOCAL_READ_RESPONSE_UNAVAILABLE",
                    StatusCode::SERVICE_UNAVAILABLE,
                );
            };
            entry.session = Some(session.clone());
        }
        let deadline = if chart || self.state.workstation {
            entered_at + CHART_BUDGET
        } else {
            Instant::now() + SEND_BUDGET
        };
        let permit = if self.state.workstation {
            match self.workstation_permit(deadline).await {
                Ok(permit) => permit,
                Err(()) => {
                    return deny(
                        "LOCAL_READ_RESPONSE_UNAVAILABLE",
                        StatusCode::SERVICE_UNAVAILABLE,
                    );
                }
            }
        } else {
            match Arc::clone(&self.state.slots).try_acquire_owned() {
                Ok(permit) => permit,
                Err(_) => {
                    return if chart {
                        deny(
                            "CHART_STUDY_CAPACITY_UNAVAILABLE",
                            StatusCode::SERVICE_UNAVAILABLE,
                        )
                    } else {
                        deny(
                            "LOCAL_READ_CAPACITY_EXCEEDED",
                            StatusCode::TOO_MANY_REQUESTS,
                        )
                    };
                }
            }
        };
        let Ok(uri) = normalized_uri(request.uri(), &path) else {
            return deny("LOCAL_READ_FORBIDDEN", StatusCode::FORBIDDEN);
        };
        *request.uri_mut() = uri;
        match &session {
            Proof::Source(session) => {
                request.extensions_mut().insert(session.clone());
            }
            Proof::Human(session) => {
                request.extensions_mut().insert(session.clone());
            }
            Proof::Proposal(presented) => {request.extensions_mut().insert(presented.clone());}
            Proof::Bootstrap => {}
        }
        let permit = Arc::new(permit);
        {
            let Ok(mut gate) = self.state.gate.lock() else {
                return deny(
                    "LOCAL_READ_RESPONSE_UNAVAILABLE",
                    StatusCode::SERVICE_UNAVAILABLE,
                );
            };
            let Some(entry) = gate.connections.get_mut(&id) else {
                return deny(
                    "LOCAL_READ_RESPONSE_UNAVAILABLE",
                    StatusCode::SERVICE_UNAVAILABLE,
                );
            };
            entry.permit = Some(Arc::clone(&permit));
        }
        let owned = self.clone();
        let (sender, receiver) = oneshot::channel();
        self.state.work.fetch_add(1, Ordering::AcqRel);
        let work = WorkGuard {
            state: Arc::clone(&self.state),
        };
        // One permit stays owned until both actual work and the connection end.
        // A dropped receiver, panic or late result cannot release the other owner.
        tokio::spawn(async move {
            let _work = work;
            let _permit = permit;
            let response = owned
                .compute(request, session, size, chart, deadline, cookie)
                .await;
            let _ = sender.send((response, Instant::now()));
        });
        if chart || self.state.workstation {
            match timeout_at(deadline, receiver).await {
                Ok(Ok((response, ready_at))) if Instant::now() < deadline => {
                    self.ready(id, ready_at, Some(deadline));
                    response
                }
                _ => deny(
                    "CHART_STUDY_QUERY_UNAVAILABLE",
                    StatusCode::SERVICE_UNAVAILABLE,
                ),
            }
        } else {
            match receiver.await {
                Ok((response, ready_at)) => {
                    self.ready(id, ready_at, None);
                    response
                }
                Err(_) => deny(
                    "LOCAL_READ_RESPONSE_UNAVAILABLE",
                    StatusCode::SERVICE_UNAVAILABLE,
                ),
            }
        }
    }
    async fn prepare_developer(
        &self,
        id: u64,
        request: Request<Incoming>,
        duplicate_length: bool,
        access: &HumanAccess,
    ) -> Response {
        let entered_at = Instant::now();
        let admission = match access.admit(&request) {
            Ok(admission) => admission,
            Err(error) => {
                return deny(
                    error.code(),
                    match error {
                        crate::application::source_access::Error::Unauthorized => {
                            StatusCode::UNAUTHORIZED
                        }
                        crate::application::source_access::Error::ProofUnavailable => {
                            StatusCode::SERVICE_UNAVAILABLE
                        }
                        _ => StatusCode::FORBIDDEN,
                    },
                );
            }
        };
        let size = if request.headers().contains_key("content-length") {
            match one(request.headers(), "content-length")
                .and_then(|value| value.parse::<usize>().ok())
            {
                Some(size) => size,
                None => return deny("LOCAL_READ_FORBIDDEN", StatusCode::FORBIDDEN),
            }
        } else {
            0
        };
        if duplicate_length
            || size > 65536
            || request.headers().contains_key("transfer-encoding")
            || (!self.state.workstation && size != 0)
            || (size > 0 && one(request.headers(), "content-type") != Some("application/json"))
        {
            return deny("LOCAL_READ_FORBIDDEN", StatusCode::FORBIDDEN);
        }
        let Some(path) = decoded_path(request.uri()) else {
            return deny("LOCAL_READ_FORBIDDEN", StatusCode::FORBIDDEN);
        };
        // Identity is not operation permission. Add capabilities only with their
        // actual owning implementation; no blanket Human POST or Source grant.
        let native = self.state.workstation
            && crate::transport::routes::operation(request.method(), &path).is_some();
        if !developer_read(request.method(), &path)
            && !native
            && !(self.state.workstation
                && crate::transport::routes::navigation(request.method(), &path))
        {
            return if self.state.workstation {
                deny("PRODUCT_ROUTE_NOT_FOUND", StatusCode::NOT_FOUND)
            } else {
                deny("LOCAL_READ_FORBIDDEN", StatusCode::FORBIDDEN)
            };
        }
        let (proof, cookie) = match admission {
            HumanAdmission::Owner(session) => (Proof::Human(session), None),
            HumanAdmission::Navigation(cookie) => (Proof::Bootstrap, Some(cookie)),
            HumanAdmission::Health => (Proof::Bootstrap, None),
            HumanAdmission::Proposal(presented) => (Proof::Proposal(presented),None),
        };
        self.dispatch(
            id,
            request,
            RequestPlan {
                proof,
                size,
                chart: self.state.workstation
                    && matches!(
                        path.as_str(),
                        CAPABILITIES | EVALUATE | "/api/v2/research/catalog/calculations"
                    ),
                cookie,
            },
            entered_at,
        )
        .await
    }
    async fn compute(
        &self,
        request: Request<Incoming>,
        session: Proof,
        size: usize,
        chart: bool,
        deadline: Instant,
        cookie: Option<http::HeaderValue>,
    ) -> Response {
        let post = matches!(
            *request.method(),
            Method::POST | Method::PUT | Method::PATCH
        );
        let (mut parts, body) = request.into_parts();
        let bytes = match timeout_at(
            deadline,
            to_bytes(Body::new(body), if post { 65536 } else { 0 }),
        )
        .await
        {
            Ok(Ok(bytes)) if bytes.len() == size => bytes,
            Err(_) => {
                return deny(
                    if chart {
                        "CHART_STUDY_QUERY_UNAVAILABLE"
                    } else {
                        "LOCAL_READ_RESPONSE_UNAVAILABLE"
                    },
                    StatusCode::SERVICE_UNAVAILABLE,
                );
            }
            _ => {
                return deny(
                    if chart {
                        "CHART_STUDY_REQUEST_INVALID"
                    } else {
                        "LOCAL_READ_FORBIDDEN"
                    },
                    if chart {
                        StatusCode::BAD_REQUEST
                    } else {
                        StatusCode::FORBIDDEN
                    },
                );
            }
        };
        if size > 0 {
            let mut deserializer = serde_json::Deserializer::from_slice(&bytes);
            if UniqueJson::deserialize(&mut deserializer).is_err() || deserializer.end().is_err() {
                return deny("CHART_STUDY_REQUEST_INVALID", StatusCode::BAD_REQUEST);
            }
        }
        if !self.state.mode.active(&session) {
            return deny("LOCAL_READ_UNAUTHORIZED", StatusCode::UNAUTHORIZED);
        }
        parts
            .extensions
            .insert(RequestDeadline(deadline.into_std()));
        let mut response = capture(
            self.state.app.clone(),
            Request::from_parts(parts, Body::from(bytes)),
        )
        .await
        .unwrap_or_else(|| {
            deny(
                "LOCAL_READ_RESPONSE_UNAVAILABLE",
                StatusCode::SERVICE_UNAVAILABLE,
            )
        });
        if matches!(self.state.mode, Mode::Developer(_)) {
            response.headers_mut().remove(http::header::SET_COOKIE);
            if response.status().is_success()
                && let Some(cookie) = cookie
            {
                response
                    .headers_mut()
                    .insert(http::header::SET_COOKIE, cookie);
            }
        }
        response
    }
}
struct WorkGuard {
    state: Arc<State>,
}
impl Drop for WorkGuard {
    fn drop(&mut self) {
        self.state.work.fetch_sub(1, Ordering::AcqRel);
        self.state.signal.send_replace(());
    }
}
struct ConnectionGuard {
    state: Arc<State>,
    id: u64,
}
impl Drop for ConnectionGuard {
    fn drop(&mut self) {
        // Only release this connection's resources. Poison stays set: admission
        // and every outward write continue to refuse the damaged composition.
        let mut gate = self
            .state
            .gate
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        gate.connections.remove(&self.id);
        self.state.signal.send_replace(());
    }
}
async fn capture(app: Router, request: Request<Body>) -> Option<Response> {
    let response = TowerToHyperService::new(app).call(request).await.ok()?;
    let (parts, body) = response.into_parts();
    let bytes = to_bytes(body, RESPONSE_LIMIT).await.ok()?;
    Some(Response::from_parts(parts, Body::from(bytes)))
}
fn deny(code: &'static str, status: StatusCode) -> Response {
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
fn one<'a>(headers: &'a HeaderMap, key: &str) -> Option<&'a str> {
    let mut values = headers.get_all(key).iter();
    let value = values.next()?.to_str().ok()?;
    if values.next().is_some() {
        None
    } else {
        Some(value)
    }
}
pub(crate) fn decoded_path(uri: &Uri) -> Option<String> {
    let path = percent_decode_str(uri.path())
        .decode_utf8()
        .ok()?
        .into_owned();
    if !path.is_ascii() || path.contains('%') {
        return None;
    }
    Some(path)
}
fn developer_read(method: &Method, path: &str) -> bool {
    let read = matches!(*method, Method::GET | Method::HEAD);
    (read
        && (path == "/"
            || path.starts_with("/assets/")
            || path == "/api/v2/integrations"
            || path.strip_prefix("/api/v2/integrations/").is_some_and(|tail| {
                let parts: Vec<_> = tail.split('/').collect();
                matches!(parts.as_slice(), [id] if !id.is_empty())
                    || matches!(parts.as_slice(), [id, "draft" | "revisions"] if !id.is_empty())
                    || matches!(parts.as_slice(), [id, "revisions", fingerprint] if !id.is_empty() && !fingerprint.is_empty())
            })
            || path == "/api/v2/integration-types"
            || path
                .strip_prefix("/api/v2/integration-types/")
                .is_some_and(|id| !id.is_empty() && !id.contains('/'))))
        || (*method == Method::GET && matches!(path, "/health/live" | "/health/ready"))
}

fn private_read(path: &str) -> bool {
    matches!(
        path,
        "/api/v2/market-data/sources"
            | "/api/v2/market/instruments"
            | "/api/v2/market/instruments/search"
            | "/api/v2/market-data/quotes"
            | "/api/v2/market-data/bars"
            | "/api/v2/market-data/latest-bar"
    ) || path
        .strip_prefix("/api/v2/market-data/acquisitions/")
        .is_some_and(|id| {
            !id.is_empty()
                && id.len() <= 128
                && id
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b':' | b'-'))
        })
}
fn normalized_uri(uri: &Uri, path: &str) -> Result<Uri, http::uri::InvalidUri> {
    // This is only called after a closed ASCII route grammar (with no %) succeeds.
    if let Some(query) = uri.query() {
        format!("{path}?{query}").parse()
    } else {
        path.parse()
    }
}
fn valid_headers(config: &Configuration, request: &Request<Incoming>, chart: bool) -> bool {
    let headers = request.headers();
    if request.uri().scheme().is_some()
        || request.uri().authority().is_some()
        || one(headers, "host") != Some(config.host_header())
        || (headers.contains_key("origin") && one(headers, "origin") != Some(config.origin()))
        || [
            "x-user",
            "forwarded",
            "x-forwarded-for",
            "x-forwarded-proto",
            "transfer-encoding",
        ]
        .iter()
        .any(|key| headers.contains_key(*key))
    {
        return false;
    }
    let query = request.uri().query().unwrap_or("");
    if chart {
        let post = request.method() == Method::POST;
        let length = one(headers, "content-length").or(if post { None } else { Some("0") });
        query.is_empty()
            && length.is_some_and(|value| {
                !value.is_empty()
                    && value.len() <= 6
                    && value.bytes().all(|byte| byte.is_ascii_digit())
                    && (value == "0" || !value.starts_with('0'))
            })
            && (!post || one(headers, "content-type") == Some("application/json"))
            && (post || length == Some("0"))
    } else {
        query.len() <= 4096 && one(headers, "content-length").unwrap_or("0") == "0"
    }
}

// Only the maintained parser understands wire syntax. Keep the exact original bytes.
async fn preflight<I: AsyncRead + Unpin>(io: &mut I) -> Result<(Vec<u8>, bool), Error> {
    let mut prefix = Vec::new();
    loop {
        let mut headers = [httparse::EMPTY_HEADER; HEADER_COUNT];
        let mut request = httparse::Request::new(&mut headers);
        match request
            .parse(&prefix)
            .map_err(|_| Error::ConnectionUnavailable)?
        {
            httparse::Status::Complete(_) => {
                let duplicate_length = request
                    .headers
                    .iter()
                    .filter(|header| header.name.eq_ignore_ascii_case("content-length"))
                    .count()
                    > 1;
                return Ok((prefix, duplicate_length));
            }
            httparse::Status::Partial => {}
        }
        if prefix.len() == HEADER_LIMIT {
            return Err(Error::ConnectionUnavailable);
        }
        let mut chunk = [0u8; 4096];
        let limit = chunk.len().min(HEADER_LIMIT - prefix.len());
        let count = io
            .read(&mut chunk[..limit])
            .await
            .map_err(|_| Error::ConnectionUnavailable)?;
        if count == 0 {
            return Err(Error::ConnectionUnavailable);
        }
        prefix.extend_from_slice(&chunk[..count]);
    }
}
struct PrefixIo<I> {
    io: I,
    prefix: Vec<u8>,
    offset: usize,
}
impl<I: AsyncRead + Unpin> AsyncRead for PrefixIo<I> {
    fn poll_read(
        mut self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffer: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        if self.offset < self.prefix.len() {
            let count = buffer.remaining().min(self.prefix.len() - self.offset);
            buffer.put_slice(&self.prefix[self.offset..self.offset + count]);
            self.offset += count;
            Poll::Ready(Ok(()))
        } else {
            Pin::new(&mut self.io).poll_read(context, buffer)
        }
    }
}
impl<I: AsyncWrite + Unpin> AsyncWrite for PrefixIo<I> {
    fn poll_write(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        bytes: &[u8],
    ) -> Poll<io::Result<usize>> {
        Pin::new(&mut self.io).poll_write(cx, bytes)
    }
    fn poll_write_vectored(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        bytes: &[io::IoSlice<'_>],
    ) -> Poll<io::Result<usize>> {
        Pin::new(&mut self.io).poll_write_vectored(cx, bytes)
    }
    fn is_write_vectored(&self) -> bool {
        self.io.is_write_vectored()
    }
    fn poll_flush(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.io).poll_flush(cx)
    }
    fn poll_shutdown(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.io).poll_shutdown(cx)
    }
}
struct WriteGate<I> {
    io: I,
    state: Arc<State>,
    id: u64,
}
impl<I> WriteGate<I> {
    fn poll_outbound<T>(
        &mut self,
        poll: impl FnOnce(&mut I) -> Poll<io::Result<T>>,
    ) -> Poll<io::Result<T>> {
        let Ok(gate) = self.state.gate.lock() else {
            return Poll::Ready(Err(io::ErrorKind::PermissionDenied.into()));
        };
        let active = gate.connections.get(&self.id).is_some_and(|entry| {
            if entry
                .send_deadline
                .is_some_and(|deadline| Instant::now() >= deadline)
            {
                return false;
            }
            entry.release.as_ref().is_none_or(|proof| proof.active())
                && entry
                    .session
                    .as_ref()
                    .is_none_or(|proof| self.state.mode.active(proof))
        });
        if gate.shutdown || !active {
            return Poll::Ready(Err(io::ErrorKind::PermissionDenied.into()));
        }
        // One nonblocking underlying poll while holding the same lock as withdrawal.
        poll(&mut self.io)
    }
}
impl<I: AsyncRead + Unpin> AsyncRead for WriteGate<I> {
    fn poll_read(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buffer: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        Pin::new(&mut self.io).poll_read(cx, buffer)
    }
}
impl<I: AsyncWrite + Unpin> AsyncWrite for WriteGate<I> {
    fn poll_write(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        bytes: &[u8],
    ) -> Poll<io::Result<usize>> {
        self.poll_outbound(|io| Pin::new(io).poll_write(cx, bytes))
    }
    fn poll_write_vectored(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        bytes: &[io::IoSlice<'_>],
    ) -> Poll<io::Result<usize>> {
        self.poll_outbound(|io| Pin::new(io).poll_write_vectored(cx, bytes))
    }
    fn is_write_vectored(&self) -> bool {
        self.io.is_write_vectored()
    }
    fn poll_flush(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        self.poll_outbound(|io| Pin::new(io).poll_flush(cx))
    }
    fn poll_shutdown(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        self.poll_outbound(|io| Pin::new(io).poll_shutdown(cx))
    }
}

// A Serde visitor checks duplicate keys without implementing JSON syntax or first
// converting to Value (which would erase duplicates). Parser recursion limits apply.
struct UniqueJson;
impl<'de> Deserialize<'de> for UniqueJson {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct Check;
        impl<'de> Visitor<'de> for Check {
            type Value = UniqueJson;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("JSON")
            }
            fn visit_map<M: MapAccess<'de>>(self, mut map: M) -> Result<UniqueJson, M::Error> {
                let mut keys = HashSet::new();
                while let Some(key) = map.next_key::<String>()? {
                    if !keys.insert(key) {
                        return Err(serde::de::Error::custom("duplicate key"));
                    }
                    map.next_value::<UniqueJson>()?;
                }
                Ok(UniqueJson)
            }
            fn visit_seq<S: SeqAccess<'de>>(self, mut sequence: S) -> Result<UniqueJson, S::Error> {
                while sequence.next_element::<UniqueJson>()?.is_some() {}
                Ok(UniqueJson)
            }
            fn visit_bool<E: serde::de::Error>(self, _: bool) -> Result<UniqueJson, E> {
                Ok(UniqueJson)
            }
            fn visit_i64<E: serde::de::Error>(self, _: i64) -> Result<UniqueJson, E> {
                Ok(UniqueJson)
            }
            fn visit_u64<E: serde::de::Error>(self, _: u64) -> Result<UniqueJson, E> {
                Ok(UniqueJson)
            }
            fn visit_f64<E: serde::de::Error>(self, _: f64) -> Result<UniqueJson, E> {
                Ok(UniqueJson)
            }
            fn visit_str<E: serde::de::Error>(self, _: &str) -> Result<UniqueJson, E> {
                Ok(UniqueJson)
            }
            fn visit_unit<E: serde::de::Error>(self) -> Result<UniqueJson, E> {
                Ok(UniqueJson)
            }
        }
        deserializer.deserialize_any(Check)
    }
}

pub(crate) fn attach(mut response: Response, release: Release) -> Response {
    release.attach(&mut response);
    response
}

pub(crate) fn validate_json(bytes: &[u8]) -> Result<(), ()> {
    let mut d = serde_json::Deserializer::from_slice(bytes);
    UniqueJson::deserialize(&mut d).map_err(|_| ())?;
    d.end().map_err(|_| ())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::source_access::Authority;
    use std::future::Future;
    use std::{fs::OpenOptions, io::Write, os::unix::fs::OpenOptionsExt};
    use tokio::io::AsyncWriteExt;
    const TOKEN: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const DIGEST: &str = "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb";
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    fn ingress(app: Router, chart: bool) -> LocalIngress {
        let path = std::env::temp_dir().join(format!(
            "oa-ingress-unit-{}-{}.json",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)
            .unwrap();
        write!(file, "{}", json!({"schema_version":1,"subject_id":"human","bearer_sha256":DIGEST,"origin":"http://localhost:1234","grants":[{"integration_id":"integration","integration_revision_fingerprint":"b".repeat(64),"expected_type_id":"provider","source_id":"bars","environment":"BACKTEST","permissions":["CLOSED_HISTORY"]}]})).unwrap();
        let config = Configuration::load(&path, &[]).unwrap();
        std::fs::remove_file(path).unwrap();
        LocalIngress::new(config, app, chart).unwrap()
    }

    struct PendingFrameSink;
    impl futures_util::Sink<()> for PendingFrameSink {
        type Error = io::Error;
        fn poll_ready(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<io::Result<()>> {
            Poll::Ready(Ok(()))
        }
        fn start_send(self: Pin<&mut Self>, _: ()) -> io::Result<()> {
            Ok(())
        }
        fn poll_flush(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<io::Result<()>> {
            Poll::Pending
        }
        fn poll_close(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<io::Result<()>> {
            Poll::Pending
        }
    }
    struct FrameWake(AtomicUsize);
    impl std::task::Wake for FrameWake {
        fn wake(self: Arc<Self>) {
            self.0.fetch_add(1, Ordering::AcqRel);
        }
        fn wake_by_ref(self: &Arc<Self>) {
            self.0.fetch_add(1, Ordering::AcqRel);
        }
    }
    async fn pending_upgraded_frame(flush: bool, cutoff: u8) {
        use futures_util::SinkExt;
        let ingress = if cutoff >= 3 {
            developer(Router::new())
        } else {
            ingress(Router::new(), false)
        };
        let source = Authority::new("separate-source", DIGEST, vec![]).unwrap();
        let (session, owner) = match &ingress.state.mode {
            Mode::Private(config) => {
                let session = config
                    .authority()
                    .authenticate(&format!("Bearer {TOKEN}"))
                    .unwrap();
                (session.clone(), Proof::Source(session))
            }
            Mode::Developer(access) => {
                let request = Request::builder()
                    .uri("/api/v2/integration-types")
                    .header("host", "127.0.0.1:5173")
                    .header("cookie", format!("onlyalpha_dev_session={TOKEN}"))
                    .body(())
                    .unwrap();
                let HumanAdmission::Owner(human) = access.admit(&request).unwrap() else {
                    unreachable!()
                };
                (
                    source.authenticate(&format!("Bearer {TOKEN}")).unwrap(),
                    Proof::Human(human),
                )
            }
        };
        let proof = Arc::new(Release::Generation(session.clone()));
        ingress.state.gate.lock().unwrap().connections.insert(
            42,
            ConnectionEntry {
                session: Some(owner.clone()),
                permit: None,
                send_deadline: None,
                release: None,
            },
        );
        let physical = PhysicalConnection {
            state: ingress.state.clone(),
            id: 42,
            _owner: Arc::new(ConnectionGuard {
                state: ingress.state.clone(),
                id: 42,
            }),
        };
        physical.upgraded(proof.clone()).unwrap();
        physical.frame(proof).unwrap();
        if cutoff == 2 {
            // Half the original frame budget is already spent before the sink
            // is polled: completion must not start a replacement budget.
            tokio::time::advance(SEND_BUDGET / 2).await;
        }
        let wake = Arc::new(FrameWake(AtomicUsize::new(0)));
        let waker = std::task::Waker::from(wake.clone());
        let mut sink = PendingFrameSink;
        let (woken, completed) = {
            let writing = physical.complete_frame(async {
                if flush {
                    sink.flush().await
                } else {
                    sink.send(()).await
                }
            });
            tokio::pin!(writing);
            assert!(
                writing
                    .as_mut()
                    .poll(&mut Context::from_waker(&waker))
                    .is_pending()
            );
            match cutoff {
                0 => ingress.withdraw().unwrap(),
                1 => ingress.shutdown().unwrap(),
                2 => tokio::time::advance(SEND_BUDGET / 2).await,
                3 => {
                    ingress.withdraw().unwrap();
                    assert!(session.check_active().is_ok());
                }
                4 => {
                    ingress.source_revoker().withdraw(&source).unwrap();
                    assert!(ingress.state.mode.active(&owner));
                    assert!(session.check_active().is_err());
                }
                _ => unreachable!(),
            }
            let woken = wake.0.load(Ordering::Acquire) > 0;
            let completed = matches!(
                writing.as_mut().poll(&mut Context::from_waker(&waker)),
                Poll::Ready(Err(Error::ConnectionUnavailable))
            );
            (woken, completed)
        };
        // The sink future completing does not acknowledge stream resource drain:
        // its existing connection owner is retained until owning cleanup returns.
        assert_eq!(ingress.state.gate.lock().unwrap().connections.len(), 1);
        drop(physical);
        ingress.shutdown_and_drain().await.unwrap();
        assert!(ingress.state.gate.lock().unwrap().connections.is_empty());
        assert!(woken, "pending frame must be woken by its own cutoff");
        assert!(completed, "pending frame must complete on its own cutoff");
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn upgraded_pending_send_revocation() {
        pending_upgraded_frame(false, 0).await;
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn upgraded_pending_flush_revocation() {
        pending_upgraded_frame(true, 0).await;
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn upgraded_pending_send_shutdown() {
        pending_upgraded_frame(false, 1).await;
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn upgraded_pending_flush_shutdown() {
        pending_upgraded_frame(true, 1).await;
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn upgraded_pending_send_deadline() {
        pending_upgraded_frame(false, 2).await;
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn upgraded_pending_flush_deadline() {
        pending_upgraded_frame(true, 2).await;
    }

    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn upgraded_pending_send_human_revocation() {
        pending_upgraded_frame(false, 3).await;
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn upgraded_pending_flush_human_revocation() {
        pending_upgraded_frame(true, 3).await;
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn upgraded_pending_send_source_revoker() {
        pending_upgraded_frame(false, 4).await;
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn upgraded_pending_flush_source_revoker() {
        pending_upgraded_frame(true, 4).await;
    }

    #[tokio::test(flavor = "current_thread")]
    async fn shutdown_drain_waits_for_disconnected_owned_work_and_can_resume_after_cancellation() {
        let release = Arc::new(Semaphore::new(0));
        let (entered, event) = oneshot::channel();
        let entered = Arc::new(Mutex::new(Some(entered)));
        let app = Router::new().route(
            "/api/v2/market-data/sources",
            axum::routing::get({
                let release = release.clone();
                move || {
                    let release = release.clone();
                    let entered = entered.clone();
                    async move {
                        entered.lock().unwrap().take().unwrap().send(()).unwrap();
                        release.acquire().await.unwrap().forget();
                        Json(json!({"complete":true}))
                    }
                }
            }),
        );
        let ingress = ingress(app, false);
        let (mut client, io) = tokio::io::duplex(65536);
        client.write_all(raw_read().as_bytes()).await.unwrap();
        let owned = ingress.clone();
        let connection = tokio::spawn(async move { owned.serve_stream(io).await });
        event.await.unwrap();
        assert_eq!(ingress.active_work(), 1);
        {
            let drain = ingress.shutdown_and_drain();
            tokio::pin!(drain);
            std::future::poll_fn(|cx| {
                assert!(drain.as_mut().poll(cx).is_pending());
                Poll::Ready(())
            })
            .await;
            assert!(connection.await.unwrap().is_err());
            drop(client);
            assert_eq!(ingress.active_work(), 1);
            assert_eq!(ingress.retained_reads(), 1);
            std::future::poll_fn(|cx| {
                assert!(drain.as_mut().poll(cx).is_pending());
                Poll::Ready(())
            })
            .await;
        }
        assert!(ingress.serve_stream(tokio::io::duplex(16).1).await.is_err());
        assert_eq!(ingress.active_work(), 1);
        release.add_permits(1);
        ingress.shutdown_and_drain().await.unwrap();
        assert_eq!(ingress.active_work(), 0);
        assert_eq!(ingress.retained_reads(), 0);
        assert!(ingress.state.gate.lock().unwrap().connections.is_empty());
        ingress.shutdown_and_drain().await.unwrap();
    }

    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn shutdown_drain_wakes_an_incomplete_header_without_waiting_for_its_deadline() {
        let ingress = ingress(Router::new(), false);
        let (mut client, io) = tokio::io::duplex(65536);
        client.write_all(b"GET /").await.unwrap();
        let connection = ingress.serve_stream(io);
        tokio::pin!(connection);
        std::future::poll_fn(|cx| {
            assert!(connection.as_mut().poll(cx).is_pending());
            Poll::Ready(())
        })
        .await;
        assert_eq!(ingress.state.gate.lock().unwrap().connections.len(), 1);
        let before = Instant::now();
        let drain = ingress.shutdown_and_drain();
        tokio::pin!(drain);
        std::future::poll_fn(|cx| {
            assert!(drain.as_mut().poll(cx).is_pending());
            Poll::Ready(())
        })
        .await;
        assert!(connection.await.is_err());
        drain.await.unwrap();
        assert_eq!(Instant::now(), before);
        assert_eq!(ingress.active_work(), 0);
        assert_eq!(ingress.retained_reads(), 0);
    }

    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn shutdown_drain_waits_for_a_queued_response_and_wakes_after_connection_cleanup() {
        let ingress = ingress(data_router(), false);
        let (io, probe, blocked) = probe(0, raw_read().into_bytes());
        let owned = ingress.clone();
        let connection = tokio::spawn(async move { owned.serve_stream(io).await });
        blocked.await.unwrap();
        assert_eq!(ingress.active_work(), 0);
        assert_eq!(ingress.retained_reads(), 1);
        let owned = ingress.clone();
        let (pending, observed) = oneshot::channel();
        let draining = tokio::spawn(async move {
            let mut pending = Some(pending);
            let drain = owned.shutdown_and_drain();
            tokio::pin!(drain);
            std::future::poll_fn(|cx| {
                let result = drain.as_mut().poll(cx);
                if result.is_pending()
                    && let Some(pending) = pending.take()
                {
                    pending.send(()).unwrap();
                }
                result
            })
            .await
        });
        observed.await.unwrap();
        assert!(connection.await.unwrap().is_err());
        tokio::time::timeout(Duration::from_secs(1), draining)
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        assert_eq!(ingress.retained_reads(), 0);
        assert!(probe.lock().unwrap().accepted.is_empty());
    }

    #[tokio::test(flavor = "current_thread")]
    async fn shutdown_drain_never_certifies_a_poisoned_gate() {
        let ingress = ingress(Router::new(), false);
        let state = ingress.state.clone();
        assert!(
            std::thread::spawn(move || {
                let _gate = state.gate.lock().unwrap();
                panic!("controlled gate poison");
            })
            .join()
            .is_err()
        );
        assert_eq!(
            ingress.shutdown_and_drain().await,
            Err(Error::ConnectionUnavailable)
        );
        assert!(ingress.serve_stream(tokio::io::duplex(16).1).await.is_err());
    }
    #[tokio::test(flavor = "current_thread")]
    async fn final_write_gate_rejects_a_complete_foreign_issuer_session() {
        let ingress = ingress(Router::new(), false);
        let foreign = Authority::new("human", DIGEST, vec![])
            .unwrap()
            .authenticate(&format!("Bearer {TOKEN}"))
            .unwrap();
        ingress.state.gate.lock().unwrap().connections.insert(
            42,
            ConnectionEntry {
                session: Some(Proof::Source(foreign)),
                release: None,
                permit: None,
                send_deadline: None,
            },
        );
        let mut io = WriteGate {
            io: tokio::io::sink(),
            state: ingress.state.clone(),
            id: 42,
        };
        assert!(io.write_all(b"private response").await.is_err());
    }
    #[test]
    fn recursive_json_validation_preserves_duplicate_key_proofs() {
        for text in [
            r#"{"x":1,"x":2}"#,
            r#"{"nested":[{"x":1,"\u0078":2}]}"#,
            r#"{"x":{"a":1,"a":2}}"#,
            "NaN",
            "Infinity",
            "{}{}",
        ] {
            let mut decoder = serde_json::Deserializer::from_str(text);
            assert!(
                UniqueJson::deserialize(&mut decoder).is_err() || decoder.end().is_err(),
                "{text}"
            );
        }
        for text in [
            r#"{"x":1,"nested":[{"x":2}]}"#,
            "1234567890123456789012345678901234567890",
            "1e99999",
            "null",
            "[true,false,\"value\"]",
        ] {
            let mut decoder = serde_json::Deserializer::from_str(text);
            assert!(UniqueJson::deserialize(&mut decoder).is_ok(), "{text}");
            assert!(decoder.end().is_ok());
        }
    }
    async fn memory_request(ingress: &LocalIngress, raw: &[u8]) -> Vec<u8> {
        use tokio::io::AsyncReadExt;
        let (mut client, server) = tokio::io::duplex(65536);
        let owned = ingress.clone();
        let task = tokio::spawn(async move { owned.serve_stream(server).await });
        client.write_all(raw).await.unwrap();
        let mut response = Vec::new();
        client.read_to_end(&mut response).await.unwrap();
        let _ = task.await.unwrap();
        response
    }
    fn raw_read() -> String {
        format!(
            "GET /api/v2/market-data/sources HTTP/1.1\r\nHost: localhost:1234\r\nAuthorization: Bearer {TOKEN}\r\n\r\n"
        )
    }
    async fn never_called() -> Json<serde_json::Value> {
        panic!("incomplete body must not invoke handler")
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn incomplete_chart_body_expires_with_the_formal_query_error() {
        let app = Router::new().route(
            EVALUATE,
            axum::routing::post(|| async { never_called().await }),
        );
        let ingress = ingress(app, true);
        let raw = format!(
            "POST {EVALUATE} HTTP/1.1\r\nHost: localhost:1234\r\nAuthorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\nContent-Length: 1\r\n\r\n"
        );
        let response = memory_request(&ingress, raw.as_bytes()).await;
        assert!(
            response.starts_with(b"HTTP/1.1 503"),
            "{}",
            String::from_utf8_lossy(&response)
        );
        assert!(String::from_utf8_lossy(&response).contains("CHART_STUDY_QUERY_UNAVAILABLE"));
        assert_eq!(ingress.active_work(), 0);
        assert_eq!(ingress.retained_reads(), 0);
    }
    #[tokio::test(flavor = "current_thread")]
    async fn caller_disconnect_retains_all_four_actual_workers_until_completion() {
        let release = Arc::new(Semaphore::new(0));
        let (entered, mut events) = tokio::sync::mpsc::unbounded_channel();
        let app = Router::new().route(
            "/api/v2/market-data/sources",
            axum::routing::get({
                let release = release.clone();
                move |axum::Extension(session): axum::Extension<Session>| {
                    let release = release.clone();
                    let entered = entered.clone();
                    async move {
                        session.check_active().unwrap();
                        entered.send(()).unwrap();
                        release.acquire().await.unwrap().forget();
                        Json(json!({"complete":true}))
                    }
                }
            }),
        );
        let ingress = ingress(app, false);
        let mut clients = Vec::new();
        let mut drivers = Vec::new();
        for _ in 0..4 {
            let (mut client, server) = tokio::io::duplex(4096);
            let owned = ingress.clone();
            drivers.push(tokio::spawn(
                async move { owned.serve_stream(server).await },
            ));
            client.write_all(raw_read().as_bytes()).await.unwrap();
            clients.push(client);
        }
        for _ in 0..4 {
            events.recv().await.unwrap();
        }
        drop(clients);
        assert_eq!(ingress.active_work(), 4);
        assert_eq!(ingress.retained_reads(), 4);
        let response = memory_request(&ingress, raw_read().as_bytes()).await;
        assert!(response.starts_with(b"HTTP/1.1 429"));
        assert!(String::from_utf8_lossy(&response).contains("LOCAL_READ_CAPACITY_EXCEEDED"));
        assert_eq!(ingress.active_work(), 4);
        let mut signal = ingress.state.signal.subscribe();
        release.add_permits(4);
        while ingress.active_work() != 0 {
            signal.changed().await.unwrap();
        }
        for driver in drivers {
            let _ = driver.await.unwrap();
        }
        assert_eq!(ingress.retained_reads(), 0);
    }
    struct Probe {
        accepted: Vec<u8>,
        quota: Option<usize>,
        blocked: Option<oneshot::Sender<()>>,
        waker: Option<std::task::Waker>,
        calls: usize,
    }
    struct ProbeIo {
        input: Vec<u8>,
        offset: usize,
        probe: Arc<Mutex<Probe>>,
    }
    impl AsyncRead for ProbeIo {
        fn poll_read(
            mut self: Pin<&mut Self>,
            _: &mut Context<'_>,
            buffer: &mut ReadBuf<'_>,
        ) -> Poll<io::Result<()>> {
            if self.offset == self.input.len() {
                return Poll::Pending;
            }
            let count = buffer.remaining().min(self.input.len() - self.offset);
            buffer.put_slice(&self.input[self.offset..self.offset + count]);
            self.offset += count;
            Poll::Ready(Ok(()))
        }
    }
    impl AsyncWrite for ProbeIo {
        fn poll_write(
            self: Pin<&mut Self>,
            cx: &mut Context<'_>,
            bytes: &[u8],
        ) -> Poll<io::Result<usize>> {
            let mut probe = self.probe.lock().unwrap();
            probe.calls += 1;
            let count = bytes.len().min(probe.quota.unwrap_or(bytes.len()));
            if count == 0 && !bytes.is_empty() {
                probe.waker = Some(cx.waker().clone());
                if let Some(sender) = probe.blocked.take() {
                    let _ = sender.send(());
                }
                return Poll::Pending;
            }
            probe.accepted.extend_from_slice(&bytes[..count]);
            if let Some(quota) = &mut probe.quota {
                *quota -= count;
            }
            Poll::Ready(Ok(count))
        }
        fn poll_write_vectored(
            self: Pin<&mut Self>,
            cx: &mut Context<'_>,
            slices: &[io::IoSlice<'_>],
        ) -> Poll<io::Result<usize>> {
            let bytes: Vec<u8> = slices
                .iter()
                .flat_map(|slice| slice.iter().copied())
                .collect();
            self.poll_write(cx, &bytes)
        }
        fn is_write_vectored(&self) -> bool {
            true
        }
        fn poll_flush(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<io::Result<()>> {
            self.probe.lock().unwrap().calls += 1;
            Poll::Ready(Ok(()))
        }
        fn poll_shutdown(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<io::Result<()>> {
            self.probe.lock().unwrap().calls += 1;
            Poll::Ready(Ok(()))
        }
    }
    fn probe(quota: usize, raw: Vec<u8>) -> (ProbeIo, Arc<Mutex<Probe>>, oneshot::Receiver<()>) {
        let (blocked, receiver) = oneshot::channel();
        let shared = Arc::new(Mutex::new(Probe {
            accepted: Vec::new(),
            quota: Some(quota),
            blocked: Some(blocked),
            waker: None,
            calls: 0,
        }));
        (
            ProbeIo {
                input: raw,
                offset: 0,
                probe: shared.clone(),
            },
            shared,
            receiver,
        )
    }
    fn data_router() -> Router {
        Router::new().route(
            "/api/v2/market-data/sources",
            axum::routing::get(
                |axum::Extension(session): axum::Extension<Session>| async move {
                    session.subject_id().unwrap();
                    Json(json!({"value":"x".repeat(256)}))
                },
            ),
        )
    }
    #[tokio::test(flavor = "current_thread")]
    async fn withdrawal_fences_queued_headers_body_and_partial_writes_at_the_socket() {
        let baseline = memory_request(&ingress(data_router(), false), raw_read().as_bytes()).await;
        let body = baseline
            .windows(4)
            .position(|bytes| bytes == b"\r\n\r\n")
            .unwrap()
            + 4;
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&baseline[body..]).unwrap(),
            json!({"value":"x".repeat(256)})
        );
        for quota in [0, 1, body, body + 2] {
            let ingress = ingress(data_router(), false);
            let (io, probe, blocked) = probe(quota, raw_read().into_bytes());
            let owned = ingress.clone();
            let driver = tokio::spawn(async move { owned.serve_stream(io).await });
            blocked.await.unwrap();
            assert_eq!(ingress.active_work(), 0);
            assert_eq!(ingress.retained_reads(), 1);
            let before = probe.lock().unwrap().accepted.clone();
            ingress.withdraw().unwrap();
            let waker = {
                let mut probe = probe.lock().unwrap();
                probe.quota = None;
                probe.waker.take()
            };
            if let Some(waker) = waker {
                waker.wake();
            }
            assert!(driver.await.unwrap().is_err());
            assert_eq!(probe.lock().unwrap().accepted, before);
            assert_eq!(ingress.retained_reads(), 0);
        }
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn queued_send_budget_discards_driver_without_graceful_flush() {
        let ingress = ingress(data_router(), false);
        let (io, probe, blocked) = probe(0, raw_read().into_bytes());
        let owned = ingress.clone();
        let driver = tokio::spawn(async move { owned.serve_stream(io).await });
        blocked.await.unwrap();
        tokio::time::advance(SEND_BUDGET).await;
        assert!(driver.await.unwrap().is_err());
        assert!(probe.lock().unwrap().accepted.is_empty());
        assert_eq!(ingress.retained_reads(), 0);
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn partial_header_budget_is_cumulative_and_never_starts_product_work() {
        let ingress = ingress(data_router(), false);
        let (mut client, server) = tokio::io::duplex(1024);
        client.write_all(b"GET /api/v2/").await.unwrap();
        let owned = ingress.clone();
        let task = tokio::spawn(async move { owned.serve_stream(server).await });
        assert!(task.await.unwrap().is_err());
        assert_eq!(ingress.active_work(), 0);
        assert_eq!(ingress.retained_reads(), 0);
    }
    #[tokio::test(flavor = "current_thread")]
    async fn all_raw_write_operations_share_the_same_withdrawal_and_poison_gate() {
        for poison in [false, true] {
            let ingress = ingress(Router::new(), false);
            let Mode::Private(configuration) = &ingress.state.mode else {
                panic!("expected private Source mode")
            };
            let session = configuration
                .authority()
                .authenticate(&format!("Bearer {TOKEN}"))
                .unwrap();
            ingress.state.gate.lock().unwrap().connections.insert(
                42,
                ConnectionEntry {
                    session: Some(Proof::Source(session)),
                    permit: None,
                    send_deadline: None,
                    release: None,
                },
            );
            let (raw, observed, _) = probe(usize::MAX, Vec::new());
            let mut writer = WriteGate {
                io: raw,
                state: ingress.state.clone(),
                id: 42,
            };
            assert_eq!(
                writer
                    .write_vectored(&[io::IoSlice::new(b"ab"), io::IoSlice::new(b"cd")])
                    .await
                    .unwrap(),
                4
            );
            writer.flush().await.unwrap();
            if poison {
                let state = ingress.state.clone();
                let fault = std::panic::catch_unwind(std::panic::AssertUnwindSafe(move || {
                    let _gate = state.gate.lock().unwrap();
                    panic!("controlled write gate poison");
                }));
                assert!(fault.is_err());
                assert!(ingress.withdraw().is_err());
            } else {
                ingress.withdraw().unwrap();
            }
            let calls = observed.lock().unwrap().calls;
            assert!(writer.write(b"e").await.is_err());
            assert!(
                writer
                    .write_vectored(&[io::IoSlice::new(b"f")])
                    .await
                    .is_err()
            );
            assert!(writer.flush().await.is_err());
            assert!(writer.shutdown().await.is_err());
            let observed = observed.lock().unwrap();
            assert_eq!(observed.calls, calls);
            assert_eq!(observed.accepted, b"abcd");
        }
    }
    #[tokio::test(flavor = "current_thread")]
    async fn node_shutdown_denies_public_connections_too() {
        let ingress = ingress(Router::new(), false);
        ingress.state.gate.lock().unwrap().connections.insert(
            42,
            ConnectionEntry {
                session: None,
                release: None,
                permit: None,
                send_deadline: None,
            },
        );
        let mut writer = WriteGate {
            io: tokio::io::sink(),
            state: ingress.state.clone(),
            id: 42,
        };
        writer.write_all(b"public health").await.unwrap();
        ingress.shutdown().unwrap();
        assert!(writer.write_all(b"more health").await.is_err());
        assert!(
            ingress
                .serve_stream(tokio::io::duplex(1024).1)
                .await
                .is_err()
        );
    }
    struct Fragments {
        bytes: Vec<u8>,
        offset: usize,
    }
    impl AsyncRead for Fragments {
        fn poll_read(
            mut self: Pin<&mut Self>,
            _: &mut Context<'_>,
            buffer: &mut ReadBuf<'_>,
        ) -> Poll<io::Result<()>> {
            let count = 3
                .min(buffer.remaining())
                .min(self.bytes.len() - self.offset);
            buffer.put_slice(&self.bytes[self.offset..self.offset + count]);
            self.offset += count;
            Poll::Ready(Ok(()))
        }
    }
    #[tokio::test(flavor = "current_thread")]
    async fn fragmented_preflight_preserves_every_body_byte_and_bounds_headers() {
        use tokio::io::AsyncReadExt;
        let raw = b"POST /api/v2/chart/studies/evaluate HTTP/1.1\r\nHost: localhost:1234\r\nContent-Length: 7\r\n\r\n{\"x\":1}";
        let mut fragments = Fragments {
            bytes: raw.to_vec(),
            offset: 0,
        };
        let (prefix, duplicate) = preflight(&mut fragments).await.unwrap();
        assert!(!duplicate);
        let mut replay = PrefixIo {
            io: fragments,
            prefix,
            offset: 0,
        };
        let mut bytes = Vec::new();
        replay.read_to_end(&mut bytes).await.unwrap();
        assert_eq!(bytes, raw);
        let mut coalesced = raw.as_slice();
        let (prefix, duplicate) = preflight(&mut coalesced).await.unwrap();
        assert!(!duplicate);
        assert_eq!(prefix, raw);
        let duplicate = b"GET / HTTP/1.1\r\nContent-Length: 0\r\ncontent-length: 0\r\n\r\n";
        assert!(preflight(&mut duplicate.as_slice()).await.unwrap().1);
        let header_count = format!(
            "GET / HTTP/1.1\r\n{}\r\n",
            "X-Test: value\r\n".repeat(HEADER_COUNT + 1)
        );
        assert!(preflight(&mut header_count.as_bytes()).await.is_err());
        let header_size = format!(
            "GET / HTTP/1.1\r\nX-Test: {}\r\n\r\n",
            "x".repeat(HEADER_LIMIT)
        );
        assert!(preflight(&mut header_size.as_bytes()).await.is_err());
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn every_actual_write_checks_its_deadline_inside_the_gate() {
        let ingress = ingress(Router::new(), false);
        ingress.state.gate.lock().unwrap().connections.insert(
            42,
            ConnectionEntry {
                session: None,
                release: None,
                permit: None,
                send_deadline: Some(Instant::now()),
            },
        );
        let (raw, observed, _) = probe(usize::MAX, Vec::new());
        let mut writer = WriteGate {
            io: raw,
            state: ingress.state.clone(),
            id: 42,
        };
        assert!(writer.write_all(b"expired response").await.is_err());
        assert!(
            writer
                .write_vectored(&[io::IoSlice::new(b"expired")])
                .await
                .is_err()
        );
        assert!(writer.flush().await.is_err());
        assert!(writer.shutdown().await.is_err());
        assert_eq!(observed.lock().unwrap().calls, 0);
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn chart_success_at_nine_point_nine_seconds_keeps_the_original_wire_deadline() {
        let release = Arc::new(Semaphore::new(0));
        let (entered, mut events) = tokio::sync::mpsc::unbounded_channel();
        let app = Router::new().route(
            EVALUATE,
            axum::routing::post({
                let release = release.clone();
                move || {
                    let release = release.clone();
                    let entered = entered.clone();
                    async move {
                        entered.send(()).unwrap();
                        release.acquire().await.unwrap().forget();
                        Json(json!({"success":true}))
                    }
                }
            }),
        );
        let ingress = ingress(app, true);
        let raw = format!(
            "POST {EVALUATE} HTTP/1.1\r\nHost: localhost:1234\r\nAuthorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{{}}"
        );
        let (io, observed, blocked) = probe(0, raw.into_bytes());
        let owned = ingress.clone();
        let task = tokio::spawn(async move { owned.serve_stream(io).await });
        events.recv().await.unwrap();
        tokio::time::advance(Duration::from_millis(9900)).await;
        release.add_permits(1);
        blocked.await.unwrap();
        tokio::time::advance(Duration::from_millis(100)).await;
        let waker = {
            let mut probe = observed.lock().unwrap();
            probe.quota = None;
            probe.waker.take()
        };
        if let Some(waker) = waker {
            waker.wake();
        }
        assert!(task.await.unwrap().is_err());
        assert!(observed.lock().unwrap().accepted.is_empty());
        assert_eq!(ingress.retained_reads(), 0);
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn timed_out_caller_and_late_work_keep_capacity_until_the_error_is_sent() {
        let release = Arc::new(Semaphore::new(0));
        let (entered, mut events) = tokio::sync::mpsc::unbounded_channel();
        let app = Router::new().route(
            EVALUATE,
            axum::routing::post({
                let release = release.clone();
                move || {
                    let release = release.clone();
                    let entered = entered.clone();
                    async move {
                        entered.send(()).unwrap();
                        release.acquire().await.unwrap().forget();
                        Json(json!({"late_success":true}))
                    }
                }
            }),
        );
        let ingress = ingress(app, true);
        let raw = format!(
            "POST {EVALUATE} HTTP/1.1\r\nHost: localhost:1234\r\nAuthorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{{}}"
        );
        let (io, observed, blocked) = probe(0, raw.into_bytes());
        let owned = ingress.clone();
        let task = tokio::spawn(async move { owned.serve_stream(io).await });
        events.recv().await.unwrap();
        blocked.await.unwrap(); // paused clock advances to the caller deadline
        assert_eq!(ingress.active_work(), 1);
        assert_eq!(ingress.retained_reads(), 1);
        let mut signal = ingress.state.signal.subscribe();
        release.add_permits(1);
        while ingress.active_work() != 0 {
            signal.changed().await.unwrap();
        }
        assert_eq!(ingress.retained_reads(), 1);
        let waker = {
            let mut probe = observed.lock().unwrap();
            probe.quota = None;
            probe.waker.take()
        };
        if let Some(waker) = waker {
            waker.wake();
        }
        task.await.unwrap().unwrap();
        let bytes = observed.lock().unwrap().accepted.clone();
        assert!(bytes.starts_with(b"HTTP/1.1 503"));
        let text = String::from_utf8(bytes).unwrap();
        assert!(text.contains("CHART_STUDY_QUERY_UNAVAILABLE"));
        assert!(!text.contains("late_success"));
        assert_eq!(ingress.retained_reads(), 0);
    }
    async fn panic_handler() -> Json<serde_json::Value> {
        panic!("controlled infrastructure handler failure")
    }
    #[tokio::test(flavor = "current_thread")]
    async fn panic_and_oversized_output_keep_the_connection_lease_through_error_delivery() {
        for panic in [false, true] {
            let app = if panic {
                Router::new().route(
                    "/api/v2/market-data/sources",
                    axum::routing::get(panic_handler),
                )
            } else {
                Router::new().route(
                    "/api/v2/market-data/sources",
                    axum::routing::get(|| async { Body::from(vec![b'x'; RESPONSE_LIMIT + 1]) }),
                )
            };
            let ingress = ingress(app, false);
            let (io, observed, blocked) = probe(0, raw_read().into_bytes());
            let owned = ingress.clone();
            let task = tokio::spawn(async move { owned.serve_stream(io).await });
            blocked.await.unwrap();
            assert_eq!(ingress.active_work(), 0);
            assert_eq!(ingress.retained_reads(), 1);
            let waker = {
                let mut probe = observed.lock().unwrap();
                probe.quota = None;
                probe.waker.take()
            };
            if let Some(waker) = waker {
                waker.wake();
            }
            task.await.unwrap().unwrap();
            assert!(
                observed
                    .lock()
                    .unwrap()
                    .accepted
                    .starts_with(b"HTTP/1.1 503")
            );
            assert_eq!(ingress.retained_reads(), 0);
        }
    }

    #[tokio::test(flavor = "current_thread")]
    async fn poisoned_connection_cleanup_returns_capacity_without_restoring_admission() {
        let ingress = ingress(Router::new(), false);
        let permit = Arc::new(ingress.state.slots.clone().try_acquire_owned().unwrap());
        ingress.state.gate.lock().unwrap().connections.insert(
            42,
            ConnectionEntry {
                session: None,
                release: None,
                permit: Some(permit),
                send_deadline: None,
            },
        );
        let connection = ConnectionGuard {
            state: ingress.state.clone(),
            id: 42,
        };
        let state = ingress.state.clone();
        assert!(
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(move || {
                let _gate = state.gate.lock().unwrap();
                panic!("controlled connection cleanup poison");
            }))
            .is_err()
        );
        drop(connection);
        assert_eq!(ingress.retained_reads(), 0);
        assert!(ingress.state.gate.lock().is_err());
        assert!(
            ingress
                .serve_stream(tokio::io::duplex(1024).1)
                .await
                .is_err()
        );
    }
    fn developer(app: Router) -> LocalIngress {
        LocalIngress::new_developer(HumanAccess::new(TOKEN).unwrap(), app)
    }
    #[tokio::test(flavor = "current_thread")]
    async fn workstation_fifth_request_waits_without_increasing_execution_capacity() {
        let ingress = developer(Router::new());
        let held = Arc::clone(&ingress.state.slots)
            .acquire_many_owned(READS as u32)
            .await
            .unwrap();
        let mut waiting = Box::pin(ingress.workstation_permit(Instant::now() + CHART_BUDGET));
        assert!(
            waiting
                .as_mut()
                .poll(&mut Context::from_waker(std::task::Waker::noop()))
                .is_pending()
        );
        assert_eq!(ingress.state.slots.available_permits(), 0);
        drop(held);
        let admitted = waiting.await.unwrap();
        assert_eq!(ingress.state.slots.available_permits(), READS - 1);
        drop(admitted);
        assert_eq!(ingress.state.slots.available_permits(), READS);
        assert_eq!(
            ingress.state.waiters.available_permits(),
            WORKSTATION_WAITERS
        );
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn workstation_queue_preserves_deadline_and_cancellation_ownership() {
        let ingress = developer(Router::new());
        let held = Arc::clone(&ingress.state.slots)
            .acquire_many_owned(READS as u32)
            .await
            .unwrap();
        let deadline = Instant::now() + CHART_BUDGET;
        let mut waiting = Box::pin(ingress.workstation_permit(deadline));
        assert!(
            waiting
                .as_mut()
                .poll(&mut Context::from_waker(std::task::Waker::noop()))
                .is_pending()
        );
        tokio::time::advance(CHART_BUDGET).await;
        assert!(waiting.await.is_err());
        assert!(ingress.workstation_permit(deadline).await.is_err());
        assert_eq!(ingress.state.slots.available_permits(), 0);
        let mut cancelled = Box::pin(ingress.workstation_permit(Instant::now() + CHART_BUDGET));
        assert!(
            cancelled
                .as_mut()
                .poll(&mut Context::from_waker(std::task::Waker::noop()))
                .is_pending()
        );
        drop(cancelled);
        assert_eq!(ingress.state.slots.available_permits(), 0);
        assert_eq!(
            ingress.state.waiters.available_permits(),
            WORKSTATION_WAITERS
        );
        drop(held);
    }
    #[tokio::test(flavor = "current_thread")]
    async fn workstation_queue_is_bounded_without_releasing_active_work() {
        let ingress = developer(Router::new());
        let held = Arc::clone(&ingress.state.slots)
            .acquire_many_owned(READS as u32)
            .await
            .unwrap();
        let deadline = Instant::now() + CHART_BUDGET;
        let mut queued = Vec::new();
        for _ in 0..WORKSTATION_WAITERS {
            let mut request = Box::pin(ingress.workstation_permit(deadline));
            assert!(
                request
                    .as_mut()
                    .poll(&mut Context::from_waker(std::task::Waker::noop()))
                    .is_pending()
            );
            queued.push(request);
        }
        assert!(ingress.workstation_permit(deadline).await.is_err());
        assert_eq!(ingress.state.slots.available_permits(), 0);
        assert_eq!(ingress.state.waiters.available_permits(), 0);
        drop(queued);
        assert_eq!(
            ingress.state.waiters.available_permits(),
            WORKSTATION_WAITERS
        );
        drop(held);
    }
    fn developer_raw(bootstrap: bool) -> String {
        if bootstrap {
            "GET / HTTP/1.1\r\nHost: 127.0.0.1:5173\r\nSec-Fetch-Mode: navigate\r\nSec-Fetch-Dest: document\r\n\r\n".into()
        } else {
            format!(
                "GET /api/v2/integration-types HTTP/1.1\r\nHost: 127.0.0.1:5173\r\nCookie: onlyalpha_dev_session={TOKEN}\r\n\r\n"
            )
        }
    }
    fn human_proof(ingress: &LocalIngress) -> Proof {
        let Mode::Developer(access) = &ingress.state.mode else {
            panic!("expected developer")
        };
        let request = Request::builder()
            .uri("/api/v2/integration-types")
            .header("host", "127.0.0.1:5173")
            .header("cookie", format!("onlyalpha_dev_session={TOKEN}"))
            .body(())
            .unwrap();
        match access.admit(&request).unwrap() {
            HumanAdmission::Owner(session) => Proof::Human(session),
            _ => panic!("expected Human identity"),
        }
    }
    #[tokio::test(flavor = "current_thread")]
    async fn developer_owner_and_bootstrap_fence_headers_and_partial_writes() {
        for bootstrap in [false, true] {
            for quota in [0, 1, 80, 300, 700] {
                let path = if bootstrap {
                    "/"
                } else {
                    "/api/v2/integration-types"
                };
                let app = Router::new().route(
                    path,
                    axum::routing::get(|| async { Body::from(vec![b'x'; 1024]) }),
                );
                let ingress = developer(app);
                let (io, observed, blocked) = probe(quota, developer_raw(bootstrap).into_bytes());
                let owned = ingress.clone();
                let task = tokio::spawn(async move { owned.serve_stream(io).await });
                blocked.await.unwrap();
                let before = observed.lock().unwrap().accepted.clone();
                assert_eq!(before.len(), quota);
                if quota == 700 {
                    assert!(
                        before.windows(4).any(|bytes| bytes == b"\r\n\r\n"),
                        "body cutoff must follow the complete header"
                    );
                }
                assert_eq!(ingress.retained_reads(), 1);
                ingress.withdraw().unwrap();
                let waker = {
                    let mut probe = observed.lock().unwrap();
                    probe.quota = None;
                    probe.waker.take()
                };
                if let Some(waker) = waker {
                    waker.wake();
                }
                assert!(task.await.unwrap().is_err());
                assert_eq!(observed.lock().unwrap().accepted, before);
                assert_eq!(ingress.active_work(), 0);
                assert_eq!(ingress.retained_reads(), 0);
            }
        }
    }
    #[tokio::test(flavor = "current_thread")]
    async fn every_developer_proof_and_raw_write_operation_share_the_cutoff() {
        for bootstrap in [false, true] {
            let ingress = developer(Router::new());
            let proof = if bootstrap {
                Proof::Bootstrap
            } else {
                human_proof(&ingress)
            };
            ingress.state.gate.lock().unwrap().connections.insert(
                42,
                ConnectionEntry {
                    session: Some(proof),
                    permit: None,
                    send_deadline: None,
                    release: None,
                },
            );
            let (raw, observed, _) = probe(usize::MAX, vec![]);
            let mut writer = WriteGate {
                io: raw,
                state: ingress.state.clone(),
                id: 42,
            };
            ingress.withdraw().unwrap();
            assert!(writer.write_all(b"withheld").await.is_err());
            assert!(
                writer
                    .write_vectored(&[io::IoSlice::new(b"withheld")])
                    .await
                    .is_err()
            );
            assert!(writer.flush().await.is_err());
            assert!(writer.shutdown().await.is_err());
            assert_eq!(observed.lock().unwrap().calls, 0);
        }
    }
    #[tokio::test(flavor = "current_thread")]
    async fn foreign_human_issuer_and_transport_mode_never_substitute_a_proof() {
        let foreign = developer(Router::new());
        let private = ingress(Router::new(), false);
        let Mode::Private(configuration) = &private.state.mode else {
            panic!("expected private")
        };
        let source = configuration
            .authority()
            .authenticate(&format!("Bearer {TOKEN}"))
            .unwrap();
        for (target, proof) in [
            (developer(Router::new()), human_proof(&foreign)),
            (developer(Router::new()), Proof::Source(source)),
            (ingress(Router::new(), false), human_proof(&foreign)),
            (ingress(Router::new(), false), Proof::Bootstrap),
        ] {
            target.state.gate.lock().unwrap().connections.insert(
                42,
                ConnectionEntry {
                    session: Some(proof),
                    permit: None,
                    send_deadline: None,
                    release: None,
                },
            );
            let (raw, observed, _) = probe(usize::MAX, vec![]);
            let mut writer = WriteGate {
                io: raw,
                state: target.state.clone(),
                id: 42,
            };
            assert!(writer.write_all(b"wrong authority").await.is_err());
            assert_eq!(observed.lock().unwrap().calls, 0);
        }
    }
    #[tokio::test(flavor = "current_thread")]
    async fn developer_late_work_after_withdrawal_retains_its_lease_without_output() {
        for bootstrap in [false, true] {
            let release = Arc::new(Semaphore::new(0));
            let (entered, mut events) = tokio::sync::mpsc::unbounded_channel();
            let path = if bootstrap {
                "/"
            } else {
                "/api/v2/integration-types"
            };
            let app = Router::new().route(
                path,
                axum::routing::get({
                    let release = release.clone();
                    move |request: Request<Body>| {
                        let release = release.clone();
                        let entered = entered.clone();
                        async move {
                            entered.send(()).unwrap();
                            assert_eq!(
                                request.extensions().get::<HumanSession>().is_none(),
                                bootstrap
                            );
                            assert!(request.extensions().get::<Session>().is_none());
                            release.acquire().await.unwrap().forget();
                            Body::from("late sensitive result")
                        }
                    }
                }),
            );
            let ingress = developer(app);
            let (io, observed, _) = probe(0, developer_raw(bootstrap).into_bytes());
            let owned = ingress.clone();
            let mut task = tokio::spawn(async move { owned.serve_stream(io).await });
            tokio::select! { event = events.recv() => assert!(event.is_some()), result = &mut task => panic!("driver ended before application barrier: {result:?}") }
            ingress.withdraw().unwrap();
            assert!(task.await.unwrap().is_err());
            assert_eq!(ingress.active_work(), 1);
            assert_eq!(ingress.retained_reads(), 1);
            assert!(observed.lock().unwrap().accepted.is_empty());
            let mut signal = ingress.state.signal.subscribe();
            release.add_permits(1);
            while ingress.active_work() != 0 {
                signal.changed().await.unwrap();
            }
            assert_eq!(ingress.retained_reads(), 0);
            assert!(observed.lock().unwrap().accepted.is_empty());
        }
    }
    #[tokio::test(flavor = "current_thread")]
    async fn developer_disconnect_and_late_work_keep_all_four_capacity_slots() {
        for bootstrap in [false, true] {
            let release = Arc::new(Semaphore::new(0));
            let (entered, mut events) = tokio::sync::mpsc::unbounded_channel();
            let path = if bootstrap {
                "/"
            } else {
                "/api/v2/integration-types"
            };
            let app = Router::new().route(
                path,
                axum::routing::get({
                    let release = release.clone();
                    move || {
                        let release = release.clone();
                        let entered = entered.clone();
                        async move {
                            entered.send(()).unwrap();
                            release.acquire().await.unwrap().forget();
                            "complete"
                        }
                    }
                }),
            );
            let ingress = developer(app);
            let mut clients = Vec::new();
            let mut drivers = Vec::new();
            for _ in 0..4 {
                let (mut client, server) = tokio::io::duplex(4096);
                let owned = ingress.clone();
                drivers.push(tokio::spawn(
                    async move { owned.serve_stream(server).await },
                ));
                client
                    .write_all(developer_raw(bootstrap).as_bytes())
                    .await
                    .unwrap();
                clients.push(client);
            }
            for _ in 0..4 {
                events.recv().await.unwrap();
            }
            drop(clients);
            assert_eq!(ingress.active_work(), 4);
            assert_eq!(ingress.retained_reads(), 4);
            let response = memory_request(&ingress, developer_raw(bootstrap).as_bytes()).await;
            assert!(response.starts_with(b"HTTP/1.1 429"));
            assert!(!String::from_utf8_lossy(&response).contains("set-cookie"));
            let mut signal = ingress.state.signal.subscribe();
            release.add_permits(4);
            while ingress.active_work() != 0 {
                signal.changed().await.unwrap();
            }
            for driver in drivers {
                let _ = driver.await.unwrap();
            }
            assert_eq!(ingress.retained_reads(), 0);
        }
    }
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn developer_owner_and_bootstrap_use_the_original_send_deadline() {
        for bootstrap in [false, true] {
            let path = if bootstrap {
                "/"
            } else {
                "/api/v2/integration-types"
            };
            let app = Router::new().route(path, axum::routing::get(|| async { "complete" }));
            let ingress = developer(app);
            let (io, observed, blocked) = probe(0, developer_raw(bootstrap).into_bytes());
            let owned = ingress.clone();
            let task = tokio::spawn(async move { owned.serve_stream(io).await });
            blocked.await.unwrap();
            tokio::time::advance(SEND_BUDGET).await;
            let waker = {
                let mut probe = observed.lock().unwrap();
                probe.quota = None;
                probe.waker.take()
            };
            if let Some(waker) = waker {
                waker.wake();
            }
            assert!(task.await.unwrap().is_err());
            assert!(observed.lock().unwrap().accepted.is_empty());
            assert_eq!(ingress.retained_reads(), 0);
        }
    }
}
