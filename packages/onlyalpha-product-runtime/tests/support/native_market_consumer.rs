//! Frozen technical consumer of the exact installed Source and Product owners.
#![cfg(test)]
#[path = "../plugs/onlyalpha-plugin-binance/rust/spot_normalize.rs"]
mod spot_normalize;
#[path = "../plugs/onlyalpha-plugin-binance/rust/spot_rest.rs"]
mod spot_rest;
#[path = "../plugs/onlyalpha-plugin-binance/rust/spot_source.rs"]
mod spot_source;
use futures_util::{SinkExt, StreamExt};
use onlyalpha_domain::market::OnlyBarSemantic;
use onlyalpha_integration_contract::{
    IntegrationTypeId,
    source::{Clock, SourceError},
};
pub use onlyalpha_plugin_binance::spot_authoring;
use onlyalpha_product_runtime::{
    authority_session::AuthoritySession,
    chart::ChartQuery,
    command::CommandId,
    integration_catalog::AuthoringCatalog,
    integration_commands::{CreateIntegration, PublishRevision, UpdateDraft},
    integration_configuration::{IntegrationId, ObjectDocument},
    integration_postgres::Integrations,
    market_data::*,
    market_data_wal::Wal,
    market_product::*,
    source_access::*,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    future::Future,
    io::{Read, Write},
    path::Path,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};
use tokio_tungstenite::tungstenite::Message;
const AT: &str = "2026-10-22T00:00:00Z";
const NOW: i64 = 1_792_627_200_000_000_000;
const WORK: usize = 64 * 1024 * 1024;
fn emit(kind: &str, value: &Value) {
    let mut file = std::fs::OpenOptions::new()
        .append(true)
        .create(true)
        .open(std::env::var("ONLYALPHA_NATIVE_MARKET_OUTPUT").unwrap())
        .unwrap();
    writeln!(file, "{}", json!({"kind":kind,"value":value})).unwrap();
}
fn chart_query() -> ChartQuery {
    let root =
        std::path::PathBuf::from(std::env::var("ONLYALPHA_NATIVE_CHART_INSTALLATION").unwrap());
    let artifact = std::env::var("ONLYALPHA_NATIVE_CHART_ARTIFACT").unwrap();
    ChartQuery::new(
        onlyalpha_calculation_worker::ChartInstallation::open(&root, &artifact).unwrap(),
    )
    .unwrap()
}
fn chart_request(window: &Value, capability: &Value, preview: Option<&str>) -> Value {
    let mut typed = serde_json::Map::new();
    for (name, value) in capability["presentation"]["default_parameters"]
        .as_object()
        .unwrap()
    {
        let spec = capability["descriptor"]["parameters"]
            .as_array()
            .unwrap()
            .iter()
            .find(|p| p["name"] == *name)
            .unwrap();
        typed.insert(
            name.clone(),
            json!({"type":spec["parameter_type"],"value":value}),
        );
    }
    json!({"schema_version":2,"source_reference":{"integration_id":window["source_selection"]["integration_id"],"integration_revision_fingerprint":window["source_selection"]["integration_revision_fingerprint"],"expected_type_id":window["source_selection"]["type_id"]},"instrument_id":window["instrument_id"],"bar_semantic":window["bar_semantic"],"window":{"anchor_kind":"BEFORE_TIME","before_ns":window["resolved_end_ns"],"target_bar_count":window["requested_bar_count"]},"expected_history_projection_fingerprint":window["history_projection_fingerprint"],"calculation":{"kind":"INDICATOR","type_id":capability["type_id"],"semantic_version":capability["semantic_version"],"typed_parameters":typed,"output_members":capability["output_members"],"expected_descriptor_fingerprint":capability["descriptor_fingerprint"],"expected_implementation_fingerprint":capability["implementation_fingerprint"],"expected_capability_projection_fingerprint":capability["capability_projection_fingerprint"]},"include_unclosed_preview":preview.is_some(),"preview_stream_id":preview})
}
async fn evaluate_chart(
    query: &ChartQuery,
    app: &Application,
    resolved: &Resolved,
    session: &Session,
    business: &mut AuthoritySession,
    ch: &ClickHouse,
    request: &Value,
    stream: Option<&ProductStream>,
) -> onlyalpha_product_runtime::chart::ChartResult {
    let preview = stream.map(ProductStream::preview_source);
    let started = Instant::now();
    let prepared = query
        .prepare(
            app,
            resolved,
            session,
            &mut store(business.client_mut().await.unwrap(), ch),
            onlyalpha_product_runtime::chart::ChartInput {
                raw: &request.to_string(),
                preview_stream: preview.as_ref(),
                clock_ns: NOW,
            },
        )
        .await
        .unwrap_or_else(|error| panic!("native chart prepare code={}", error.code()));
    eprintln!(
        "native-chart: input_prepare_elapsed_ms={} default_budget_ms=10000",
        started.elapsed().as_millis()
    );
    prepared
        .execute()
        .unwrap_or_else(|error| panic!("native chart execute code={}", error.code()))
}
fn installation_mutations() {
    use std::{
        fs,
        os::unix::fs::{PermissionsExt, symlink},
    };
    let root =
        std::path::PathBuf::from(std::env::var("ONLYALPHA_NATIVE_CHART_INSTALLATION").unwrap());
    let artifact = std::env::var("ONLYALPHA_NATIVE_CHART_ARTIFACT").unwrap();
    let open = || onlyalpha_calculation_worker::ChartInstallation::open(&root, &artifact);
    open().unwrap();
    let manifest = root.join("algorithm-installation.json");
    let bytes = fs::read(&manifest).unwrap();
    let metadata: Value = serde_json::from_slice(&bytes).unwrap();
    let resource = root.join(
        metadata["files"]
            .as_object()
            .unwrap()
            .keys()
            .find(|n| n.ends_with(".py"))
            .unwrap(),
    );
    for path in [&manifest, &resource] {
        let original = fs::read(path).unwrap();
        let held = path.with_extension("retained");
        fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o755)).unwrap();
        fs::rename(path, &held).unwrap();
        fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o555)).unwrap();
        assert!(open().is_err());
        fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o755)).unwrap();
        fs::rename(&held, path).unwrap();
        fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o555)).unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(0o644)).unwrap();
        fs::write(path, b"changed").unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(0o444)).unwrap();
        assert!(open().is_err());
        fs::set_permissions(path, fs::Permissions::from_mode(0o644)).unwrap();
        fs::write(path, &original).unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(0o444)).unwrap();
    }
    for name in ["injected.pth", "injected.py"] {
        let path = resource.parent().unwrap().join(name);
        fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o755)).unwrap();
        fs::write(&path, b"import onlyalpha.application").unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o444)).unwrap();
        fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o555)).unwrap();
        assert!(open().is_err());
        fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o755)).unwrap();
        fs::remove_file(&path).unwrap();
        fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o555)).unwrap();
    }
    for path in [&resource, &root.join("bin/python")] {
        let held = path.with_extension("retained");
        fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o755)).unwrap();
        fs::rename(path, &held).unwrap();
        symlink(&held, path).unwrap();
        fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o555)).unwrap();
        assert!(open().is_err());
        fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o755)).unwrap();
        fs::remove_file(path).unwrap();
        fs::rename(held, path).unwrap();
        fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o555)).unwrap();
    }
    let interpreter = root.join("bin/python");
    let original = fs::read(&interpreter).unwrap();
    fs::set_permissions(&interpreter, fs::Permissions::from_mode(0o744)).unwrap();
    fs::write(&interpreter, b"wrong interpreter").unwrap();
    fs::set_permissions(&interpreter, fs::Permissions::from_mode(0o555)).unwrap();
    assert!(open().is_err());
    fs::set_permissions(&interpreter, fs::Permissions::from_mode(0o744)).unwrap();
    fs::write(&interpreter, original).unwrap();
    fs::set_permissions(&interpreter, fs::Permissions::from_mode(0o555)).unwrap();
    open().unwrap();
}
struct ConstantClock;
impl Clock for ConstantClock {
    fn now_ns(&self) -> Result<i64, SourceError> {
        Ok(NOW)
    }
}
struct FixedClock(std::sync::atomic::AtomicI64);
impl Clock for FixedClock {
    fn now_ns(&self) -> Result<i64, SourceError> {
        Ok(self.0.fetch_add(1000, Ordering::SeqCst))
    }
}
fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(10)
}
fn semantic(minutes: u16) -> OnlyBarSemantic {
    spot_source::semantic(minutes).unwrap()
}
fn sha(b: &[u8]) -> String {
    Sha256::digest(b)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
fn uid(n: u32) -> String {
    format!("10000000-0000-4000-8000-{n:012x}")
}
fn symbol(s: &str) -> Value {
    json!({"symbol":s,"baseAsset":s.trim_end_matches("USDT"),"quoteAsset":"USDT","status":"TRADING","filters":[{"filterType":"PRICE_FILTER","tickSize":"0.01"},{"filterType":"LOT_SIZE","stepSize":"0.00001","minQty":"0.00001"}]})
}
fn row(start: i64, stride: i64) -> Value {
    json!([
        start,
        "10",
        "11",
        "9",
        "10.5",
        "1.23",
        start + stride - 1,
        "12.915",
        3,
        "0",
        "0",
        "0"
    ])
}
struct Http {
    url: String,
    requests: Arc<Mutex<Vec<String>>>,
    repeat: Arc<AtomicBool>,
    changed: Arc<AtomicBool>,
    gate: Arc<(Mutex<bool>, std::sync::Condvar)>,
    task: Option<std::thread::JoinHandle<()>>,
}
impl Http {
    fn start() -> Self {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let requests = Arc::new(Mutex::new(vec![]));
        let log = requests.clone();
        let repeat = Arc::new(AtomicBool::new(false));
        let mode = repeat.clone();
        let changed = Arc::new(AtomicBool::new(false));
        let prices = changed.clone();
        let gate = Arc::new((Mutex::new(false), std::sync::Condvar::new()));
        let barrier = gate.clone();
        let task = std::thread::spawn(move || {
            for incoming in listener.incoming() {
                let mut client = incoming.unwrap();
                let mut b = [0];
                let mut bytes = vec![];
                while !bytes.ends_with(b"\r\n\r\n") {
                    if client.read_exact(&mut b).is_err() {
                        return;
                    }
                    bytes.extend(b);
                    assert!(bytes.len() < 16384)
                }
                let request = String::from_utf8(bytes).unwrap();
                let path = request.split_whitespace().nth(1).unwrap();
                if path == "/__stop" {
                    break;
                }
                log.lock().unwrap().push(path.into());
                let u = reqwest::Url::parse(&format!("http://fixture{path}")).unwrap();
                let params = u
                    .query_pairs()
                    .into_owned()
                    .collect::<std::collections::BTreeMap<_, _>>();
                let body = match u.path() {
                    "/api/v3/ping" => json!({}),
                    "/api/v3/time" => json!({"serverTime":NOW/1_000_000}),
                    "/api/v3/exchangeInfo" => {
                        let wanted = params
                            .get("symbols")
                            .map(|s| serde_json::from_str::<Vec<String>>(s).unwrap());
                        json!({"symbols":(["BTCUSDT","ETHUSDT","LTCUSDT"].iter().filter(|s|wanted.as_ref().is_none_or(|a|a.iter().any(|v|v==**s))).map(|s|symbol(s)).collect::<Vec<_>>())})
                    }
                    "/api/v3/ticker/24hr" => {
                        json!([{"symbol":"BTCUSDT","lastPrice":"10.5000","priceChangePercent":"2.50","closeTime":NOW/1_000_000}])
                    }
                    "/api/v3/klines" => {
                        let (lock, ready) = &*barrier;
                        let mut blocked = lock.lock().unwrap();
                        while *blocked {
                            blocked = ready.wait(blocked).unwrap();
                        }
                        drop(blocked);
                        let interval = params["interval"].as_str();
                        let minutes = match interval {
                            "1m" => 1,
                            "3m" => 3,
                            "5m" => 5,
                            "15m" => 15,
                            "30m" => 30,
                            "1h" => 60,
                            "2h" => 120,
                            "4h" => 240,
                            _ => panic!("bad interval"),
                        };
                        let stride = minutes * 60000;
                        let start = params["startTime"].parse::<i64>().unwrap();
                        let end = params["endTime"].parse::<i64>().unwrap();
                        let count = params["limit"].parse::<usize>().unwrap();
                        if mode.load(Ordering::SeqCst) && start == 60000 {
                            json!([row(0, stride)])
                        } else {
                            json!(
                                (start..=end)
                                    .step_by(stride as usize)
                                    .take(count)
                                    .map(|n| {
                                        let mut bar = row(n, stride);
                                        if prices.load(Ordering::SeqCst) {
                                            bar[4] = "10.6".into();
                                        }
                                        bar
                                    })
                                    .collect::<Vec<_>>()
                            )
                        }
                    }
                    _ => panic!("unexpected {path}"),
                };
                let body = body.to_string();
                write!(client,"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body).ok();
            }
        });
        Self {
            url,
            requests,
            repeat,
            changed,
            gate,
            task: Some(task),
        }
    }
    fn calls(&self) -> Vec<String> {
        self.requests.lock().unwrap().clone()
    }
}
impl Drop for Http {
    fn drop(&mut self) {
        if let Ok(mut s) = std::net::TcpStream::connect(self.url.trim_start_matches("http://")) {
            let _ = s.write_all(b"GET /__stop HTTP/1.1\r\nHost: fixture\r\n\r\n");
        }
        if let Some(t) = self.task.take() {
            t.join().unwrap();
        }
    }
}
struct Ws {
    url: String,
    send: tokio::sync::broadcast::Sender<Message>,
    stop: Option<tokio::sync::oneshot::Sender<()>>,
    task: tokio::task::JoinHandle<()>,
    pongs: Arc<std::sync::atomic::AtomicUsize>,
    connections: Arc<std::sync::atomic::AtomicUsize>,
    closed: Arc<std::sync::atomic::AtomicUsize>,
    sent: Arc<std::sync::atomic::AtomicUsize>,
    changed: Arc<tokio::sync::Notify>,
}
impl Ws {
    async fn start() -> Self {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("ws://{}", listener.local_addr().unwrap());
        let (send, _) = tokio::sync::broadcast::channel::<Message>(512);
        let messages = send.clone();
        let (stop, mut stopped) = tokio::sync::oneshot::channel();
        let pongs = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let counts = pongs.clone();
        let changed = Arc::new(tokio::sync::Notify::new());
        let changes = changed.clone();
        let connections = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let accepted = connections.clone();
        let closed = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let finished = closed.clone();
        let sent = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let writes = sent.clone();
        let task = tokio::spawn(async move {
            let mut tasks = vec![];
            loop {
                let incoming = tokio::select! {_= &mut stopped=>break,incoming=listener.accept()=>incoming.unwrap()};
                let mut commands = messages.subscribe();
                let pongs = counts.clone();
                let changed = changes.clone();
                let connections = accepted.clone();
                let closed = finished.clone();
                let sent = writes.clone();
                tasks.push(tokio::spawn(async move {let path=Arc::new(Mutex::new(String::new()));let selected=path.clone();let mut socket=tokio_tungstenite::accept_hdr_async(incoming.0,move|request:&tokio_tungstenite::tungstenite::handshake::server::Request,response|{*selected.lock().unwrap()=request.uri().path().into();Ok(response)}).await.unwrap();connections.fetch_add(1,Ordering::SeqCst);changed.notify_waiters();let depth=path.lock().unwrap().contains("depth5");if depth {socket.send(Message::Text(json!({"lastUpdateId":1,"bids":[["10","1"]],"asks":[["11","1"]]}).to_string().into())).await.unwrap();}loop {tokio::select! {message=socket.next()=>match message {Some(Ok(Message::Pong(_)))=>{pongs.fetch_add(1,Ordering::SeqCst);changed.notify_waiters();},Some(Ok(Message::Close(_)))|None=>{let _=socket.flush().await;break},Some(Err(_))=>break,_=>{}},command=commands.recv(),if !depth=>match command {Ok(message)=>{if socket.send(message).await.is_err(){break}sent.fetch_add(1,Ordering::SeqCst);},Err(_)=>break}}}closed.fetch_add(1,Ordering::SeqCst);changed.notify_waiters();}));
            }
            for task in tasks {
                task.await.unwrap();
            }
        });
        Self {
            url,
            send,
            stop: Some(stop),
            task,
            pongs,
            connections,
            closed,
            sent,
            changed,
        }
    }
    async fn wait_connections(&self, target: usize) {
        loop {
            let wait = self.changed.notified();
            tokio::pin!(wait);
            wait.as_mut().enable();
            if self.connections.load(Ordering::SeqCst) >= target {
                break;
            }
            tokio::time::timeout(Duration::from_secs(5), wait)
                .await
                .unwrap();
        }
    }
    async fn wait_closed(&self, target: usize, stream: Option<&ProductStream>) {
        loop {
            let wait = self.changed.notified();
            tokio::pin!(wait);
            wait.as_mut().enable();
            if self.closed.load(Ordering::SeqCst) >= target {
                break;
            }
            if tokio::time::timeout(Duration::from_secs(5), wait)
                .await
                .is_err()
            {
                let path =
                    std::path::PathBuf::from(std::env::var("ONLYALPHA_NATIVE_MARKET_WAL").unwrap())
                        .with_file_name("overflow");
                let files = std::fs::read_dir(&path)
                    .map(|entries| {
                        entries
                            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                panic!(
                    "REMOTE_CLOSE_TIMEOUT target={target} stream={stream:?} sent={} closed={} accepted={} sealed={} opens={} files={}",
                    self.sent.load(Ordering::SeqCst),
                    self.closed.load(Ordering::SeqCst),
                    self.connections.load(Ordering::SeqCst),
                    files
                        .iter()
                        .filter(|s| s.ends_with(".segment.json"))
                        .count(),
                    files.iter().filter(|s| s.ends_with(".open.wal")).count(),
                    files.len()
                );
            }
        }
    }
    async fn barrier(&self) {
        let target = self.pongs.load(Ordering::SeqCst) + 1;
        self.send.send(Message::Ping(vec![1].into())).unwrap();
        loop {
            let wait = self.changed.notified();
            tokio::pin!(wait);
            wait.as_mut().enable();
            if self.pongs.load(Ordering::SeqCst) >= target {
                break;
            }
            tokio::time::timeout(Duration::from_secs(5), wait)
                .await
                .unwrap();
        }
    }
    async fn close(mut self) {
        self.stop.take().unwrap().send(()).unwrap();
        self.task.await.unwrap();
    }
}
fn kline(start: i64, closed: bool) -> Message {
    Message::Text(json!({"e":"kline","E":start+60000,"s":"BTCUSDT","k":{"s":"BTCUSDT","i":"1m","t":start,"T":start+59999,"o":"10","h":"11","l":"9","c":"10.5","v":"1.23","q":"12.915","n":3,"V":"0","Q":"0","x":closed}}).to_string().into())
}
async fn delivery(
    stream: &mut ProductStream,
    business: &mut AuthoritySession,
    ch: &ClickHouse,
) -> Authorized<Value> {
    let pending = tokio::time::timeout(Duration::from_secs(5), stream.next())
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    stream
        .release(
            pending,
            &mut store(business.client_mut().await.unwrap(), ch),
            AT,
        )
        .await
        .unwrap()
}
async fn ready(stream: &mut ProductStream, business: &mut AuthoritySession, ch: &ClickHouse) {
    loop {
        let event = delivery(stream, business, ch).await.into_parts().unwrap().0;
        emit("stream", &event);
        if event["state"] == "READY" {
            break;
        }
    }
}
struct Human {
    selection: Selection,
    active: AtomicBool,
}
impl MutationAdmission for Human {
    fn require_acquisition(
        &self,
        s: &Selection,
        _: &Scope,
    ) -> Result<(), onlyalpha_product_runtime::market_product::Error> {
        if s == &self.selection && self.active.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err(onlyalpha_product_runtime::market_product::Error::Forbidden)
        }
    }
}
impl ProbeAdmission for Human {
    fn require_probe(
        &self,
        s: &Selection,
        _: &str,
    ) -> Result<(), onlyalpha_product_runtime::market_product::Error> {
        if s == &self.selection && self.active.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err(onlyalpha_product_runtime::market_product::Error::Forbidden)
        }
    }
}
async fn session() -> AuthoritySession {
    let dsn = std::env::var("ONLYALPHA_POSTGRES_DSN").unwrap();
    let config: tokio_postgres::Config = dsn.parse().unwrap();
    assert!(config.get_dbname().unwrap().ends_with("_test"));
    let (c, d) = tokio_postgres::connect(&dsn, tokio_postgres::NoTls)
        .await
        .unwrap();
    AuthoritySession::acquire(c, tokio::spawn(d)).await.unwrap()
}
async fn lease(id: &str) -> ExecutionLease {
    let (c, d) = tokio_postgres::connect(
        &std::env::var("ONLYALPHA_POSTGRES_DSN").unwrap(),
        tokio_postgres::NoTls,
    )
    .await
    .unwrap();
    ExecutionLease::acquire(c, tokio::spawn(d), id)
        .await
        .unwrap()
}
fn store<'a>(s: &'a mut tokio_postgres::Client, ch: &'a ClickHouse) -> Storage<'a> {
    Storage::new(Catalog::new(s, 100_000, WORK).unwrap(), ch, 100_000).unwrap()
}
#[test]
fn native_source_application_real_pg_ch() {
    // Keep this complete integration scenario's large async state off the
    // test thread stack; owned child calls still use the normal stack budget.
    let scenario = Box::pin(native_source_application());
    eprintln!(
        "NATIVE_CONSUMER_FUTURE_BYTES {}",
        std::mem::size_of_val(scenario.as_ref().get_ref())
    );
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap()
        .block_on(scenario);
}
async fn native_source_application() {
    let http = Http::start();
    let ws = Ws::start().await;
    let mut business = session().await;
    let authoring = AuthoringCatalog::new(vec![spot_authoring(WORK).unwrap()]).unwrap();
    let id = IntegrationId::new(&uid(1)).unwrap();
    Integrations::new(business.client_mut().await.unwrap())
        .create(
            &CreateIntegration::new(
                CommandId::new(&uid(2)).unwrap(),
                id.clone(),
                IntegrationTypeId::new("binance.spot.market_data").unwrap(),
                "Native Spot",
            )
            .unwrap(),
            &authoring,
            AT.parse().unwrap(),
            WORK,
        )
        .await
        .unwrap();
    Integrations::new(business.client_mut().await.unwrap())
        .publish_revision(
            &PublishRevision::new(CommandId::new(&uid(3)).unwrap(), id.clone(), 1).unwrap(),
            &authoring,
            AT.parse().unwrap(),
            1000,
            WORK,
        )
        .await
        .unwrap();
    let snapshot = Integrations::new(business.client_mut().await.unwrap())
        .read(&id, 1000, WORK)
        .await
        .unwrap()
        .unwrap();
    let revision = snapshot
        .integration()
        .record()
        .current_revision_fingerprint
        .clone()
        .unwrap();
    let reference =
        Reference::new(id.value(), &revision, Some("binance.spot.market_data")).unwrap();
    let selection =
        Selection::new(reference.clone(), "binance.spot.market_data.live", "GLOBAL").unwrap();
    let authority = Authority::new(
        "native-human",
        &sha(b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
        vec![
            Grant::new(
                selection.clone(),
                vec![Permission::ClosedHistory, Permission::RealtimePreview],
            )
            .unwrap(),
        ],
    )
    .unwrap();
    let source_session = authority
        .authenticate("Bearer aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        .unwrap();
    let expected_factor: Value =
        serde_json::from_str(&std::env::var("ONLYALPHA_NATIVE_FACTOR_METADATA").unwrap()).unwrap();
    let registry = onlyalpha_product_runtime::private_assets::PrivateAssets::new(
        business.client_mut().await.unwrap(),
    )
    .current_registry(&source_session)
    .await
    .unwrap()
    .into_parts()
    .unwrap()
    .0;
    emit("private_registry", &registry);
    assert!(registry["entries"].as_array().unwrap().iter().any(|v| {
        v["locator"]["revision_fingerprint"]
            == serde_json::from_str::<Value>(
                &std::env::var("ONLYALPHA_NATIVE_FACTOR_HEAD").unwrap(),
            )
            .unwrap()["revision_fingerprint"]
    }));
    let factor_id = expected_factor["factor_id"].as_str().unwrap();
    let factor_revision = expected_factor["revision_fingerprint"].as_str().unwrap();
    let factor_content = expected_factor["source_sha256"].as_str().unwrap();
    let (factor, asset_fence) = onlyalpha_product_runtime::private_assets::PrivateAssets::new(
        business.client_mut().await.unwrap(),
    )
    .factor_revision(&source_session, factor_id, factor_revision, factor_content)
    .await
    .unwrap()
    .into_parts()
    .unwrap();
    assert_eq!(factor, expected_factor);
    emit("private_factor", &factor);
    assert!(matches!(
        onlyalpha_product_runtime::private_assets::PrivateAssets::new(
            business.client_mut().await.unwrap()
        )
        .factor_revision(&source_session, factor_id, factor_revision, &"0".repeat(64))
        .await,
        Err(onlyalpha_product_runtime::private_assets::Error::Mismatch)
    ));
    assert!(matches!(
        onlyalpha_product_runtime::private_assets::PrivateAssets::new(
            business.client_mut().await.unwrap()
        )
        .factor_revision(&source_session, factor_id, &"0".repeat(64), factor_content)
        .await,
        Err(onlyalpha_product_runtime::private_assets::Error::NotFound)
    ));
    let corrupt_id = format!(
        "private.factor.corrupt_{}_{}",
        std::env::var("ONLYALPHA_DEV_VERIFICATION_OPERATION_ID")
            .unwrap()
            .replace('-', ""),
        if cfg!(debug_assertions) {
            "debug"
        } else {
            "release"
        }
    );
    let mut payload = expected_factor.clone();
    payload["factor_id"] = json!(corrupt_id);
    payload["parent_revision_fingerprint"] = Value::Null;
    let mut identity = payload.as_object().unwrap().clone();
    identity.remove("revision_fingerprint");
    identity.insert(
        "contract".into(),
        json!("ONLYALPHA_PRIVATE_FACTOR_REVISION_V1"),
    );
    let canonical = onlyalpha_metadata_json::canonical_json(
        &Value::Object(identity).to_string(),
        8 * 1024 * 1024,
    )
    .unwrap();
    let corrupt_revision = sha(canonical.as_bytes());
    payload["revision_fingerprint"] = json!(corrupt_revision);
    let client = business.client_mut().await.unwrap();
    client
        .execute(
            "INSERT INTO private_factor_asset(factor_id,schema_version) VALUES($1,1)",
            &[&corrupt_id],
        )
        .await
        .unwrap();
    let corrupt_payload = payload.to_string();
    client.execute("INSERT INTO private_factor_revision(revision_fingerprint,factor_id,source_text,source_sha256,payload,schema_version) VALUES($1,$2,'changed',$3,$4::text::jsonb,1)",&[&corrupt_revision,&corrupt_id,&factor_content,&corrupt_payload]).await.unwrap();
    client
        .execute(
            "UPDATE private_factor_asset SET current_revision_fingerprint=$1 WHERE factor_id=$2",
            &[&corrupt_revision, &corrupt_id],
        )
        .await
        .unwrap();
    assert!(matches!(
        onlyalpha_product_runtime::private_assets::PrivateAssets::new(client)
            .current_registry(&source_session)
            .await,
        Err(onlyalpha_product_runtime::private_assets::Error::Corrupt)
    ));
    assert!(matches!(
        onlyalpha_product_runtime::private_assets::PrivateAssets::new(client)
            .factor_revision(
                &source_session,
                &corrupt_id,
                &corrupt_revision,
                factor_content
            )
            .await,
        Err(onlyalpha_product_runtime::private_assets::Error::Corrupt)
    ));
    client
        .execute(
            "UPDATE private_factor_asset SET current_revision_fingerprint=NULL WHERE factor_id=$1",
            &[&corrupt_id],
        )
        .await
        .unwrap();
    onlyalpha_product_runtime::private_assets::PrivateAssets::new(client)
        .current_registry(&source_session)
        .await
        .unwrap();
    let factory = spot_source::test_support::controlled_factory(&http.url, &ws.url, 1000);
    let executable = std::fs::read(std::env::current_exe().unwrap()).unwrap();
    let resolver = Resolver::new(
        vec![Installed::from_executable(factory, &executable).unwrap()],
        spot_source::test_support::trust(),
        Arc::new(FixedClock(std::sync::atomic::AtomicI64::new(NOW))),
    )
    .unwrap();
    let resolved = Arc::new(
        resolver
            .resolve(&snapshot, &reference, &source_session, None)
            .unwrap(),
    );
    println!(
        "NATIVE_INSTALLATION {}",
        json!({"current_exe":std::env::current_exe().unwrap(),"debug_assertions":cfg!(debug_assertions),"artifact":resolved.artifact_fingerprint(),"implementation":resolved.implementation_fingerprint(),"binding":resolved.binding_fingerprint()})
    );
    let human = Arc::new(Human {
        selection,
        active: AtomicBool::new(true),
    });
    let app = Application::default();
    let ch = ClickHouse::new(ClickHouseConfig {
        url: std::env::var("ONLYALPHA_TEST_CLICKHOUSE_URL").unwrap(),
        database: "onlyalpha_test_native_market_source".into(),
        user: std::env::var("ONLYALPHA_TEST_CLICKHOUSE_USER").unwrap_or("default".into()),
        password: std::env::var("ONLYALPHA_TEST_CLICKHOUSE_PASSWORD").unwrap_or_default(),
        timeout: Duration::from_secs(5),
        tls_roots_pem: vec![],
        max_bytes: WORK,
        max_rows: 100_000,
    })
    .unwrap();
    ch.assert_server().await.unwrap();
    let root = std::env::var("ONLYALPHA_NATIVE_MARKET_WAL").unwrap();
    let mut wal = Wal::new(Path::new(&root), WORK).unwrap();
    if std::env::var("ONLYALPHA_NATIVE_REBUILD_SECOND").is_ok() {
        let original: Value = serde_json::from_slice(
            &std::fs::read(Path::new(&root).with_file_name("rebuild-original.json")).unwrap(),
        )
        .unwrap();
        assert_ne!(original["artifact"], resolved.artifact_fingerprint());
        assert_ne!(
            original["implementation"],
            resolved.implementation_fingerprint()
        );
        assert_eq!(original["binding"], resolved.binding_fingerprint());
        let path = Path::new(&root).with_file_name("rebuilt-stream");
        std::fs::create_dir(&path).unwrap();
        let wal = Wal::new(&path, WORK).unwrap();
        let retained = wal.sealed_handle().unwrap();
        let instrument = app
            .reference(&resolved, &source_session, "BTCUSDT.BINANCE", deadline())
            .await
            .unwrap();
        let mut stream = app
            .open_stream(
                resolved.clone(),
                instrument,
                &mut store(business.client_mut().await.unwrap(), &ch),
                StreamRequest {
                    stream_id: uid(250),
                    semantic: semantic(1),
                    resume_after_sequence: None,
                    resume_plan_fingerprint: None,
                    clock_ns: NOW,
                    deadline: deadline(),
                    segment_id: "rebuilt".into(),
                    capture_id: "rebuilt".into(),
                    created_at: AT.into(),
                },
                wal,
            )
            .await
            .unwrap();
        let mut compared = false;
        loop {
            let pending = stream.next().await.unwrap().unwrap();
            let ids = retained.published_sealed().unwrap();
            if !compared && !ids.is_empty() {
                let occurrence = retained.read_sealed(&ids[0]).unwrap();
                let fact = &occurrence[0]["canonical_facts"][0];
                assert_eq!(
                    fact["canonical_fact_id"],
                    original["fact"]["canonical_fact_id"]
                );
                assert_eq!(
                    fact["canonical_payload"],
                    original["fact"]["canonical_payload"]
                );
                assert_eq!(
                    fact["normalizer_version"],
                    resolved.implementation_fingerprint()
                );
                assert_ne!(
                    fact["normalizer_version"],
                    original["fact"]["normalizer_version"]
                );
                assert_ne!(
                    fact["capture_session_id"],
                    original["fact"]["capture_session_id"]
                );
                assert_eq!(
                    fact["canonical_payload_hash"],
                    original["fact"]["canonical_payload_hash"]
                );
                compared = true;
            }
            let event = stream
                .release(
                    pending,
                    &mut store(business.client_mut().await.unwrap(), &ch),
                    "2026-10-22T00:00:01Z",
                )
                .await
                .unwrap()
                .into_parts()
                .unwrap()
                .0;
            emit("stream", &event);
            if event["state"] == "READY" {
                break;
            }
        }
        assert!(compared);
        let result = app
            .window(
                &resolved,
                &source_session,
                &mut store(business.client_mut().await.unwrap(), &ch),
                &WindowRequest {
                    instrument_id: "BTCUSDT.BINANCE".into(),
                    semantic: semantic(1),
                    before_ns: Some(NOW),
                    bar_count: 1,
                    clock_ns: NOW,
                },
            )
            .await
            .unwrap()
            .into_parts()
            .unwrap()
            .0;
        emit("window", &result);
        assert_eq!(result["coverage"]["status"], "COMPLETE");
        assert_eq!(result["bars"].as_array().unwrap().len(), 1);
        let query = chart_query();
        let caps = query.capabilities(&source_session).unwrap();
        emit("chart_capabilities", &caps);
        let request = chart_request(&result, &caps["capabilities"][0], None);
        let value = evaluate_chart(
            &query,
            &app,
            &resolved,
            &source_session,
            &mut business,
            &ch,
            &request,
            None,
        )
        .await
        .into_parts()
        .unwrap()
        .0;
        emit("chart_evaluation", &value);
        assert_eq!(value["query_status"], "DISPLAYABLE");
        stream.close().await.unwrap();
        drop(stream);
        drop(retained);
        // The newly executing artifact still cannot change this canonical payload.
        let path = Path::new(&root).with_file_name("rebuilt-conflict");
        std::fs::create_dir(&path).unwrap();
        let wal = Wal::new(&path, WORK).unwrap();
        let retained = wal.sealed_handle().unwrap();
        let instrument = app
            .reference(&resolved, &source_session, "BTCUSDT.BINANCE", deadline())
            .await
            .unwrap();
        http.changed.store(true, Ordering::SeqCst);
        let mut stream = app
            .open_stream(
                resolved.clone(),
                instrument,
                &mut store(business.client_mut().await.unwrap(), &ch),
                StreamRequest {
                    stream_id: uid(251),
                    semantic: semantic(1),
                    resume_after_sequence: None,
                    resume_plan_fingerprint: None,
                    clock_ns: NOW,
                    deadline: deadline(),
                    segment_id: "rebuilt-bad".into(),
                    capture_id: "rebuilt-bad".into(),
                    created_at: AT.into(),
                },
                wal,
            )
            .await
            .unwrap();
        loop {
            let pending = stream.next().await.unwrap().unwrap();
            match stream
                .release(
                    pending,
                    &mut store(business.client_mut().await.unwrap(), &ch),
                    "2026-10-22T00:00:02Z",
                )
                .await
            {
                Err(onlyalpha_product_runtime::market_product::Error::Store(
                    onlyalpha_product_runtime::market_data::Error::Conflict,
                )) => break,
                Ok(event) => {
                    let event = event.into_parts().unwrap().0;
                    assert!(event["event"] != "BAR_CLOSED" && event["state"] != "READY");
                }
                Err(error) => panic!("unexpected {error:?}"),
            }
        }
        assert_eq!(retained.published_sealed().unwrap().len(), 1);
        stream.close().await.unwrap();
        drop(stream);
        drop(retained);
        ws.close().await;
        business.close().await.unwrap();
        return;
    }
    let (_, projection) = resolver.sources(&[snapshot], &source_session).unwrap();
    let sources = projection.into_parts().unwrap().0;
    emit("sources", &sources);
    assert_eq!(sources["sources"].as_array().unwrap().len(), 1);
    let instruments = app
        .instruments(
            &resolved,
            &source_session,
            &InstrumentQuery {
                query: "BTC".into(),
                asset_class: Some("CRYPTOCURRENCY".into()),
                instrument_types: vec!["CRYPTO_SPOT".into()],
                instrument_ids: vec![],
                limit: 10,
            },
            deadline(),
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    emit("instruments", &instruments);
    assert_eq!(instruments["instruments"].as_array().unwrap().len(), 1);
    let quotes = app
        .quotes(
            &resolved,
            &source_session,
            &["BTCUSDT.BINANCE".into(), "ETHUSDT.BINANCE".into()],
            deadline(),
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    emit("quotes", &quotes);
    assert_eq!(quotes["quotes"][0]["last_price"], "10.5000");
    assert_eq!(quotes["quotes"][1]["status"], "UNAVAILABLE");
    let search = app
        .search(
            &[resolved.as_ref()],
            &source_session,
            &InstrumentQuery {
                query: "USDT".into(),
                asset_class: None,
                instrument_types: vec![],
                instrument_ids: vec![],
                limit: 1,
            },
            deadline(),
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    emit("search", &search);
    assert_eq!(search["results"].as_array().unwrap().len(), 1);
    assert_eq!(search["truncated"], true);
    for minutes in [1, 3, 5, 15, 30, 60, 120, 240, 7] {
        let end = i64::from(minutes) * 2 * 60_000_000_000;
        let request = WindowRequest {
            instrument_id: "BTCUSDT.BINANCE".into(),
            semantic: semantic(minutes),
            before_ns: Some(end),
            bar_count: 2,
            clock_ns: NOW,
        };
        let initial = app
            .window(
                &resolved,
                &source_session,
                &mut store(business.client_mut().await.unwrap(), &ch),
                &request,
            )
            .await
            .unwrap()
            .into_parts()
            .unwrap()
            .0;
        emit("window", &initial);
        assert_eq!(initial["coverage"]["status"], "INCOMPLETE");
        let before = http.calls().len();
        let mut work = app
            .prepare_acquisition(
                resolved.clone(),
                source_session.clone(),
                human.clone(),
                &mut store(business.client_mut().await.unwrap(), &ch),
                AcquisitionRequest {
                    instrument_id: "BTCUSDT.BINANCE",
                    semantic: &semantic(minutes),
                    start_ns: 0,
                    end_ns: end,
                    clock_ns: NOW,
                    admitted_at: AT,
                },
            )
            .await
            .unwrap();
        assert_eq!(http.calls().len(), before);
        let mut stale = if minutes == 1 {
            Some(
                app.prepare_acquisition(
                    resolved.clone(),
                    source_session.clone(),
                    human.clone(),
                    &mut store(business.client_mut().await.unwrap(), &ch),
                    AcquisitionRequest {
                        instrument_id: "BTCUSDT.BINANCE",
                        semantic: &semantic(minutes),
                        start_ns: 0,
                        end_ns: end,
                        clock_ns: NOW,
                        admitted_at: "2026-10-22T00:00:01Z",
                    },
                )
                .await
                .unwrap(),
            )
        } else {
            None
        };
        let execution = lease(work.id()).await;
        if minutes == 1 {
            let other = app
                .prepare_acquisition(
                    resolved.clone(),
                    source_session.clone(),
                    human.clone(),
                    &mut store(business.client_mut().await.unwrap(), &ch),
                    AcquisitionRequest {
                        instrument_id: "ETHUSDT.BINANCE",
                        semantic: &semantic(1),
                        start_ns: 0,
                        end_ns: 60_000_000_000,
                        clock_ns: NOW,
                        admitted_at: AT,
                    },
                )
                .await
                .unwrap();
            let wrong = lease(other.id()).await;
            let before = http.calls().len();
            assert!(matches!(
                work.start(
                    &mut store(business.client_mut().await.unwrap(), &ch),
                    &wrong,
                    AT
                )
                .await,
                Err(onlyalpha_product_runtime::market_product::Error::Conflict)
            ));
            assert!(matches!(
                app.acquisition_status(
                    &resolved,
                    &source_session,
                    &mut store(business.client_mut().await.unwrap(), &ch),
                    work.id(),
                    Some(&wrong)
                )
                .await,
                Err(onlyalpha_product_runtime::market_product::Error::Conflict)
            ));
            assert_eq!(http.calls().len(), before);
            wrong.close().await.unwrap();
        }
        work.start(
            &mut store(business.client_mut().await.unwrap(), &ch),
            &execution,
            AT,
        )
        .await
        .unwrap();
        let segments = work
            .capture(
                &app,
                &mut wal,
                CaptureRequest {
                    segment_id: &format!("native-{minutes}"),
                    capture_id: &format!("capture-{minutes}"),
                    created_at: AT,
                    deadline: deadline(),
                },
                &execution,
            )
            .await
            .unwrap();
        if let Some(other) = stale.as_ref() {
            assert!(matches!(
                other
                    .publish(
                        &mut store(business.client_mut().await.unwrap(), &ch),
                        &wal,
                        &segments,
                        AT
                    )
                    .await,
                Err(onlyalpha_product_runtime::market_product::Error::Conflict)
            ));
        }
        let output = work
            .publish(
                &mut store(business.client_mut().await.unwrap(), &ch),
                &wal,
                &segments,
                AT,
            )
            .await
            .unwrap()
            .into_parts()
            .unwrap()
            .0;
        emit("acquisition", &output);
        assert_eq!(output["status"], "COMPLETE");
        drop(segments);
        execution.close().await.unwrap();
        let result = app
            .window(
                &resolved,
                &source_session,
                &mut store(business.client_mut().await.unwrap(), &ch),
                &request,
            )
            .await
            .unwrap()
            .into_parts()
            .unwrap()
            .0;
        emit("window", &result);
        assert_eq!(result["coverage"]["status"], "COMPLETE");
        assert_eq!(result["bars"].as_array().unwrap().len(), 2);
        assert_eq!(
            result["resolution_mode"],
            if minutes == 7 {
                "DERIVED"
            } else {
                "PROVIDER_NATIVE"
            }
        );
        let latest = app
            .latest(
                &resolved,
                &source_session,
                &mut store(business.client_mut().await.unwrap(), &ch),
                "BTCUSDT.BINANCE",
                &semantic(minutes),
            )
            .await;
        if minutes == 7 {
            assert!(latest.is_err());
        } else {
            let latest = latest.unwrap().into_parts().unwrap().0;
            emit("window", &latest);
            assert_eq!(latest["bars"].as_array().unwrap().len(), 1);
        }
        if let Some(mut stale) = stale.take() {
            let before = http.calls().len();
            let execution = lease(stale.id()).await;
            stale
                .start(
                    &mut store(business.client_mut().await.unwrap(), &ch),
                    &execution,
                    AT,
                )
                .await
                .unwrap();
            let extra = stale
                .capture(
                    &app,
                    &mut wal,
                    CaptureRequest {
                        segment_id: "stale",
                        capture_id: "stale",
                        created_at: AT,
                        deadline: deadline(),
                    },
                    &execution,
                )
                .await
                .unwrap();
            assert!(
                extra.segment_ids().next().is_none(),
                "a pre-lease snapshot must refresh sealed readiness"
            );
            assert_eq!(http.calls().len(), before);
            let completed = stale
                .publish(
                    &mut store(business.client_mut().await.unwrap(), &ch),
                    &wal,
                    &extra,
                    AT,
                )
                .await
                .unwrap()
                .into_parts()
                .unwrap()
                .0;
            emit("acquisition", &completed);
            assert_eq!(completed["status"], "COMPLETE");
            drop(extra);
            execution.close().await.unwrap();
        }
    }
    // Current installed factory -> native catalog/admission -> original durable Storage
    // proof -> actual isolated mathematics -> atomic Product schema, no acquisition.
    installation_mutations();
    let query = chart_query();
    let caps = query.capabilities(&source_session).unwrap();
    emit("chart_capabilities", &caps);
    emit("chart_catalog", &query.catalog(&source_session).unwrap());
    assert_eq!(caps["capabilities"].as_array().unwrap().len(), 14);
    let original = app
        .window(
            &resolved,
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            &WindowRequest {
                instrument_id: "BTCUSDT.BINANCE".into(),
                semantic: semantic(1),
                before_ns: Some(180_000_000_000),
                bar_count: 2,
                clock_ns: NOW,
            },
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    assert_eq!(original["coverage"]["status"], "COMPLETE");
    assert_eq!(original["resolved_start_ns"], "60000000000");
    let before_calculation = http
        .calls()
        .iter()
        .filter(|call| call.contains("klines"))
        .count();
    for capability in caps["capabilities"].as_array().unwrap() {
        let request = chart_request(&original, capability, None);
        let result = evaluate_chart(
            &query,
            &app,
            &resolved,
            &source_session,
            &mut business,
            &ch,
            &request,
            None,
        )
        .await;
        let (value, fence) = result.into_parts().unwrap();
        fence.check().unwrap();
        emit("chart_evaluation", &value);
        assert_eq!(value["query_status"], "DISPLAYABLE");
        assert_eq!(value["authority"], "DISPLAY_ONLY");
        assert_eq!(
            value["series"].as_array().unwrap().len(),
            capability["output_members"].as_array().unwrap().len()
        );
    }
    assert_eq!(
        http.calls()
            .iter()
            .filter(|call| call.contains("klines"))
            .count(),
        before_calculation,
        "evaluate never acquires history"
    );
    let baseline = chart_request(&original, &caps["capabilities"][0], None);
    for mutation in 0..5 {
        let mut invalid = baseline.clone();
        match mutation {
            0 => invalid["extra"] = json!(true),
            1 => invalid["schema_version"] = json!(true),
            2 => {
                invalid["calculation"]["output_members"] = json!(["value", "value"]);
            }
            3 => invalid["window"]["before_ns"] = json!("120000000000"),
            _ => {
                invalid["include_unclosed_preview"] = json!(true);
                invalid["preview_stream_id"] = json!("a".repeat(32));
            }
        }
        assert!(matches!(
            query
                .prepare(
                    &app,
                    resolved.as_ref(),
                    &source_session,
                    &mut store(business.client_mut().await.unwrap(), &ch),
                    onlyalpha_product_runtime::chart::ChartInput {
                        raw: &invalid.to_string(),
                        preview_stream: None,
                        clock_ns: NOW
                    },
                )
                .await,
            Err(onlyalpha_product_runtime::chart::Error::Invalid)
        ));
    }
    let pending_request = chart_request(&original, &caps["capabilities"][0], None);
    let pending = query
        .prepare(
            &app,
            resolved.as_ref(),
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            onlyalpha_product_runtime::chart::ChartInput {
                raw: &pending_request.to_string(),
                preview_stream: None,
                clock_ns: NOW,
            },
        )
        .await
        .unwrap();
    query.capabilities(&source_session).unwrap();
    let second_pending = query
        .prepare(
            &app,
            resolved.as_ref(),
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            onlyalpha_product_runtime::chart::ChartInput {
                raw: &pending_request.to_string(),
                preview_stream: None,
                clock_ns: NOW,
            },
        )
        .await
        .unwrap();
    assert!(matches!(
        query.capabilities(&source_session),
        Err(onlyalpha_product_runtime::chart::Error::Capacity)
    ));
    let cancellation = pending.cancellation().unwrap();
    cancellation.cancel().unwrap();
    assert_eq!(
        cancellation.state(),
        onlyalpha_calculation_worker::ProcessState::Joined
    );
    query.capabilities(&source_session).unwrap(); // Actual cancel wait released capacity.

    assert!(
        pending.execute().is_err(),
        "cancelled invocation cannot retry a fresh process"
    );
    let second_cancellation = second_pending.cancellation().unwrap();
    assert_eq!(
        second_cancellation.state(),
        onlyalpha_calculation_worker::ProcessState::Running
    );
    second_cancellation.cancel().unwrap();
    assert!(second_pending.execute().is_err());
    let dropped_request = chart_request(&original, &caps["capabilities"][0], None).to_string();
    let dropped = query
        .prepare(
            &app,
            resolved.as_ref(),
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            onlyalpha_product_runtime::chart::ChartInput {
                raw: &dropped_request,
                preview_stream: None,
                clock_ns: NOW,
            },
        )
        .await
        .unwrap();
    let control = dropped.cancellation().unwrap();
    drop(dropped);
    assert_eq!(
        control.state(),
        onlyalpha_calculation_worker::ProcessState::Joined
    );
    query.capabilities(&source_session).unwrap();
    let closing = chart_query();
    let prepared = closing
        .prepare(
            &app,
            resolved.as_ref(),
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            onlyalpha_product_runtime::chart::ChartInput {
                raw: &dropped_request,
                preview_stream: None,
                clock_ns: NOW,
            },
        )
        .await
        .unwrap();
    let control = prepared.cancellation().unwrap();
    drop(closing);
    assert_eq!(
        control.state(),
        onlyalpha_calculation_worker::ProcessState::Joined
    );
    assert!(prepared.execute().is_err());
    let mut invalid = chart_request(&original, &caps["capabilities"][0], None);
    invalid["calculation"]["expected_implementation_fingerprint"] = json!("0".repeat(64));
    assert!(matches!(
        query
            .prepare(
                &app,
                resolved.as_ref(),
                &source_session,
                &mut store(business.client_mut().await.unwrap(), &ch),
                onlyalpha_product_runtime::chart::ChartInput {
                    raw: &invalid.to_string(),
                    preview_stream: None,
                    clock_ns: NOW
                },
            )
            .await,
        Err(onlyalpha_product_runtime::chart::Error::Changed)
    ));
    let mut invalid = chart_request(&original, &caps["capabilities"][0], None);
    invalid["expected_history_projection_fingerprint"] = json!("0".repeat(64));
    assert!(matches!(
        query
            .prepare(
                &app,
                resolved.as_ref(),
                &source_session,
                &mut store(business.client_mut().await.unwrap(), &ch),
                onlyalpha_product_runtime::chart::ChartInput {
                    raw: &invalid.to_string(),
                    preview_stream: None,
                    clock_ns: NOW
                },
            )
            .await,
        Err(onlyalpha_product_runtime::chart::Error::InputChanged)
    ));
    let mut incomplete = chart_request(&original, &caps["capabilities"][0], None);
    incomplete["window"]["before_ns"] = json!(NOW.to_string());
    incomplete["window"]["target_bar_count"] = json!(3);
    let gap = app
        .window(
            &resolved,
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            &WindowRequest {
                instrument_id: "BTCUSDT.BINANCE".into(),
                semantic: semantic(1),
                before_ns: Some(NOW),
                bar_count: 3,
                clock_ns: NOW,
            },
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    assert_eq!(gap["coverage"]["status"], "INCOMPLETE");
    emit("window", &gap);
    let before_incomplete = http
        .calls()
        .iter()
        .filter(|call| call.contains("klines"))
        .count();
    let value = evaluate_chart(
        &query,
        &app,
        &resolved,
        &source_session,
        &mut business,
        &ch,
        &incomplete,
        None,
    )
    .await
    .into_parts()
    .unwrap()
    .0;
    emit("chart_evaluation", &value);
    assert_eq!(value["query_status"], "INPUT_INCOMPLETE");
    assert!(value["series"].as_array().unwrap().is_empty());
    assert_eq!(
        http.calls()
            .iter()
            .filter(|call| call.contains("klines"))
            .count(),
        before_incomplete
    );
    // A later malformed page preserves the first original durable occurrence, then
    // a fresh Work/lease reads that exact sealed prefix and requests only the gap.
    let partial_factory =
        spot_source::test_support::controlled_factory(&http.url, "ws://127.0.0.1:1", 1);
    let partial_resolver = Resolver::new(
        vec![Installed::from_executable(partial_factory, &executable).unwrap()],
        spot_source::test_support::trust(),
        Arc::new(FixedClock(std::sync::atomic::AtomicI64::new(NOW))),
    )
    .unwrap();
    let snapshot = Integrations::new(business.client_mut().await.unwrap())
        .read(&id, 1000, WORK)
        .await
        .unwrap()
        .unwrap();
    let partial_resolved = Arc::new(
        partial_resolver
            .resolve(&snapshot, &reference, &source_session, None)
            .unwrap(),
    );
    let mut partial = app
        .prepare_acquisition(
            partial_resolved.clone(),
            source_session.clone(),
            human.clone(),
            &mut store(business.client_mut().await.unwrap(), &ch),
            AcquisitionRequest {
                instrument_id: "ETHUSDT.BINANCE",
                semantic: &semantic(1),
                start_ns: 0,
                end_ns: 120_000_000_000,
                clock_ns: NOW,
                admitted_at: AT,
            },
        )
        .await
        .unwrap();
    let original = partial.id().to_owned();
    let execution = lease(partial.id()).await;
    partial
        .start(
            &mut store(business.client_mut().await.unwrap(), &ch),
            &execution,
            AT,
        )
        .await
        .unwrap();
    http.repeat.store(true, Ordering::SeqCst);
    let captured = partial
        .capture(
            &app,
            &mut wal,
            CaptureRequest {
                segment_id: "partial",
                capture_id: "partial",
                created_at: AT,
                deadline: deadline(),
            },
            &execution,
        )
        .await
        .unwrap();
    assert!(captured.failure().is_some());
    let raw = wal.read_sealed("partial").unwrap();
    assert_eq!(raw.len(), 2);
    assert_eq!(raw[0]["canonical_facts"].as_array().unwrap().len(), 1);
    assert!(raw[1]["canonical_facts"].as_array().unwrap().is_empty());
    assert!(
        matches!(partial.publish(&mut store(business.client_mut().await.unwrap(),&ch),&wal,&captured,AT).await,Err(e) if Some(e)==captured.failure())
    );
    drop(captured);
    execution.close().await.unwrap();
    assert!(
        store(business.client_mut().await.unwrap(), &ch)
            .catalog()
            .latest_attempt(&original)
            .await
            .unwrap()
            .unwrap()
            .is_unknown()
    );
    let prefix = app
        .window(
            &resolved,
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            &WindowRequest {
                instrument_id: "ETHUSDT.BINANCE".into(),
                semantic: semantic(1),
                before_ns: Some(60_000_000_000),
                bar_count: 1,
                clock_ns: NOW,
            },
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    assert_eq!(prefix["coverage"]["status"], "COMPLETE");
    let partial_status = app
        .acquisition_status(
            &resolved,
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            &original,
            None,
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    emit("acquisition", &partial_status);
    assert_eq!(
        partial_status["coverage"]["gaps"].as_array().unwrap().len(),
        1
    );
    assert_eq!(
        partial_status["coverage"]["gaps"][0]["start_ns"],
        "60000000000"
    );
    drop(wal);
    let mut wal = Wal::new(Path::new(&root), WORK).unwrap();
    http.repeat.store(false, Ordering::SeqCst);
    let mut resumed = app
        .prepare_acquisition(
            partial_resolved,
            source_session.clone(),
            human.clone(),
            &mut store(business.client_mut().await.unwrap(), &ch),
            AcquisitionRequest {
                instrument_id: "ETHUSDT.BINANCE",
                semantic: &semantic(1),
                start_ns: 0,
                end_ns: 120_000_000_000,
                clock_ns: NOW,
                admitted_at: "2026-10-22T00:00:02Z",
            },
        )
        .await
        .unwrap();
    assert_eq!(resumed.id(), original);
    let execution = lease(resumed.id()).await;
    resumed
        .start(
            &mut store(business.client_mut().await.unwrap(), &ch),
            &execution,
            AT,
        )
        .await
        .unwrap();
    let before = http.calls().len();
    let captured = resumed
        .capture(
            &app,
            &mut wal,
            CaptureRequest {
                segment_id: "resumed",
                capture_id: "resumed",
                created_at: AT,
                deadline: deadline(),
            },
            &execution,
        )
        .await
        .unwrap();
    assert!(captured.failure().is_none());
    let new_requests = http.calls()[before..].to_vec();
    let klines = new_requests
        .iter()
        .filter(|p| p.contains("/klines"))
        .collect::<Vec<_>>();
    assert_eq!(klines.len(), 1);
    assert!(klines[0].contains("startTime=60000"));
    let result = resumed
        .publish(
            &mut store(business.client_mut().await.unwrap(), &ch),
            &wal,
            &captured,
            AT,
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    assert_eq!(result["status"], "COMPLETE");
    drop(captured);
    execution.close().await.unwrap();
    let status = app
        .acquisition_status(
            &resolved,
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            &original,
            None,
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    emit("acquisition", &status);
    assert_eq!(status["status"], "COMPLETE");
    let intent = store(business.client_mut().await.unwrap(), &ch)
        .catalog()
        .intent(&original)
        .await
        .unwrap()
        .unwrap()
        .to_record();
    assert!(
        intent["admitted_at"]
            .as_str()
            .unwrap()
            .starts_with("2026-10-22T00:00:00")
    );

    // The same formal raw identity cannot stand for incompatible canonical outcomes.
    let collision_root = Path::new(&root).with_file_name("collision-wal");
    std::fs::create_dir(&collision_root).unwrap();
    let mut collision_wal = Wal::new(&collision_root, WORK).unwrap();
    let collision_factory =
        spot_source::test_support::controlled_factory(&http.url, "ws://127.0.0.1:1", 1);
    let collision_resolver = Resolver::new(
        vec![Installed::from_executable(collision_factory, &executable).unwrap()],
        spot_source::test_support::trust(),
        Arc::new(ConstantClock),
    )
    .unwrap();
    let snapshot = Integrations::new(business.client_mut().await.unwrap())
        .read(&id, 1000, WORK)
        .await
        .unwrap()
        .unwrap();
    let collision_resolved = Arc::new(
        collision_resolver
            .resolve(&snapshot, &reference, &source_session, None)
            .unwrap(),
    );
    let mut collision = app
        .prepare_acquisition(
            collision_resolved,
            source_session.clone(),
            human.clone(),
            &mut store(business.client_mut().await.unwrap(), &ch),
            AcquisitionRequest {
                instrument_id: "LTCUSDT.BINANCE",
                semantic: &semantic(1),
                start_ns: 0,
                end_ns: 120_000_000_000,
                clock_ns: NOW,
                admitted_at: AT,
            },
        )
        .await
        .unwrap();
    let execution = lease(collision.id()).await;
    collision
        .start(
            &mut store(business.client_mut().await.unwrap(), &ch),
            &execution,
            AT,
        )
        .await
        .unwrap();
    http.repeat.store(true, Ordering::SeqCst);
    let captured = collision
        .capture(
            &app,
            &mut collision_wal,
            CaptureRequest {
                segment_id: "collision",
                capture_id: "collision",
                created_at: AT,
                deadline: deadline(),
            },
            &execution,
        )
        .await
        .unwrap();
    let raw = collision_wal.read_sealed("collision").unwrap();
    assert_eq!(
        raw[0]["evidence"]["raw_event_id"],
        raw[1]["evidence"]["raw_event_id"]
    );
    assert!(matches!(
        collision
            .publish(
                &mut store(business.client_mut().await.unwrap(), &ch),
                &collision_wal,
                &captured,
                AT
            )
            .await,
        Err(onlyalpha_product_runtime::market_product::Error::Store(
            onlyalpha_product_runtime::market_data::Error::Conflict
        ))
    ));
    assert_eq!(collision_wal.read_sealed("collision").unwrap(), raw);
    drop(captured);
    execution.close().await.unwrap();
    assert!(
        store(business.client_mut().await.unwrap(), &ch)
            .catalog()
            .latest_attempt(collision.id())
            .await
            .unwrap()
            .unwrap()
            .is_unknown()
    );
    let no_complete = app
        .window(
            &resolved,
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            &WindowRequest {
                instrument_id: "LTCUSDT.BINANCE".into(),
                semantic: semantic(1),
                before_ns: Some(180_000_000_000),
                bar_count: 2,
                clock_ns: NOW,
            },
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    assert_eq!(no_complete["coverage"]["status"], "INCOMPLETE");
    assert!(no_complete["bars"].as_array().unwrap().is_empty());
    http.repeat.store(false, Ordering::SeqCst);
    let stream_root = Path::new(&root).with_file_name("stream-wal");
    std::fs::create_dir(&stream_root).unwrap();
    let stream_wal = Wal::new(&stream_root, WORK).unwrap();
    let sealed = stream_wal.sealed_handle().unwrap();
    let instrument = app
        .reference(&resolved, &source_session, "BTCUSDT.BINANCE", deadline())
        .await
        .unwrap();
    let mut stream = app
        .open_stream(
            resolved.clone(),
            instrument,
            &mut store(business.client_mut().await.unwrap(), &ch),
            StreamRequest {
                stream_id: uid(80),
                semantic: semantic(1),
                resume_after_sequence: None,
                resume_plan_fingerprint: None,
                clock_ns: NOW,
                deadline: deadline(),
                segment_id: "live".into(),
                capture_id: "live".into(),
                created_at: AT.into(),
            },
            stream_wal,
        )
        .await
        .unwrap();
    let subscribed = stream.next().await.unwrap().unwrap();
    assert!(
        matches!(
            stream.next().await,
            Err(onlyalpha_product_runtime::market_product::Error::Busy)
        ),
        "one original delivery must be released before another can be issued"
    );
    let subscribed = stream
        .release(
            subscribed,
            &mut store(business.client_mut().await.unwrap(), &ch),
            AT,
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    emit("stream", &subscribed);
    let recovering = delivery(&mut stream, &mut business, &ch)
        .await
        .into_parts()
        .unwrap()
        .0;
    emit("stream", &recovering);
    assert_eq!(recovering["state"], "RECOVERING");
    let pending = stream.next().await.unwrap().unwrap();
    assert_eq!(
        sealed.published_sealed().unwrap().len(),
        1,
        "original baseline is sealed before any market-data release"
    );
    let original = sealed
        .read_sealed(&sealed.published_sealed().unwrap()[0])
        .unwrap();
    std::fs::write(Path::new(&root).with_file_name("rebuild-original.json"),json!({"artifact":resolved.artifact_fingerprint(),"implementation":resolved.implementation_fingerprint(),"binding":resolved.binding_fingerprint(),"fact":original[0]["canonical_facts"][0]}).to_string()).unwrap();
    let closed = stream
        .release(
            pending,
            &mut store(business.client_mut().await.unwrap(), &ch),
            AT,
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    emit("stream", &closed);
    assert_eq!(closed["event"], "BAR_CLOSED");
    ready(&mut stream, &mut business, &ch).await;
    assert_eq!(
        stream
            .drain(&mut store(business.client_mut().await.unwrap(), &ch), AT)
            .await
            .unwrap(),
        0
    );
    assert!(sealed.published_sealed().unwrap().is_empty());
    for close in ["10.1", "10.2", "10.3"] {
        let Message::Text(frame) = kline(NOW / 1_000_000, false) else {
            unreachable!()
        };
        let mut frame: Value = serde_json::from_str(&frame).unwrap();
        frame["k"]["c"] = close.into();
        ws.send
            .send(Message::Text(frame.to_string().into()))
            .unwrap();
    }
    ws.barrier().await;
    assert_eq!(
        sealed.published_sealed().unwrap().len(),
        3,
        "all observations retained while one preview is coalesced"
    );
    let preview = delivery(&mut stream, &mut business, &ch).await;
    let (preview, fence) = preview.into_parts().unwrap();
    emit("stream", &preview);
    assert_eq!(preview["event"], "BAR_PREVIEW");
    assert_eq!(preview["bar"]["close"], "10.3");
    fence.check().unwrap();
    // A delivered generation remains retained without being delivered twice.
    {
        let mut next = std::pin::pin!(stream.next());
        let mut context = std::task::Context::from_waker(std::task::Waker::noop());
        assert!(next.as_mut().poll(&mut context).is_pending());
    }
    // A new real observation gets one delivery and revokes the prior fence,
    // even when the mathematical bar value is unchanged.
    let Message::Text(frame) = kline(NOW / 1_000_000, false) else {
        unreachable!()
    };
    let mut frame: Value = serde_json::from_str(&frame).unwrap();
    frame["k"]["c"] = "10.3".into();
    ws.send
        .send(Message::Text(frame.to_string().into()))
        .unwrap();
    ws.barrier().await;
    assert!(fence.check().is_err());
    let (replacement, fence) = delivery(&mut stream, &mut business, &ch)
        .await
        .into_parts()
        .unwrap();
    assert_eq!(replacement["event"], "BAR_PREVIEW");
    assert_eq!(replacement["bar"]["close"], "10.3");
    emit("stream", &replacement);
    fence.check().unwrap();
    {
        let mut next = std::pin::pin!(stream.next());
        let mut context = std::task::Context::from_waker(std::task::Waker::noop());
        assert!(next.as_mut().poll(&mut context).is_pending());
    }
    // A different legitimate resolve/window issuance joins the original stream by
    // full Source/context/plan identity, retaining both original fences.
    let snapshot = Integrations::new(business.client_mut().await.unwrap())
        .read(&id, 1000, WORK)
        .await
        .unwrap()
        .unwrap();
    let distinct = resolver
        .resolve(&snapshot, &reference, &source_session, None)
        .unwrap();
    let history = app
        .window(
            &distinct,
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            &WindowRequest {
                instrument_id: "BTCUSDT.BINANCE".into(),
                semantic: semantic(1),
                before_ns: Some(NOW),
                bar_count: 1,
                clock_ns: NOW,
            },
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    let capability = caps["capabilities"]
        .as_array()
        .unwrap()
        .iter()
        .find(|v| v["type_id"].as_str().unwrap().ends_with(".sma"))
        .unwrap();
    let request = chart_request(&history, capability, Some(&uid(80)));
    let retained_chart = evaluate_chart(
        &query,
        &app,
        &distinct,
        &source_session,
        &mut business,
        &ch,
        &request,
        Some(&stream),
    )
    .await;
    let fresh = evaluate_chart(
        &query,
        &app,
        &distinct,
        &source_session,
        &mut business,
        &ch,
        &request,
        Some(&stream),
    )
    .await
    .into_parts()
    .unwrap()
    .0;
    emit("chart_evaluation", &fresh);
    assert!(!fresh["preview"].is_null());
    assert_eq!(fresh["preview"]["source_kind"], "PREVIEW_UNCLOSED");
    assert_eq!(
        fresh["preview"]["series"][0]["point"]["value"],
        "10.400000000000"
    );
    assert_eq!(
        fresh["preview"]["series"][0]["point"]["readiness"],
        "PARTIAL"
    );
    assert_eq!(
        fresh["preview"]["series"][0]["point"]["reason"],
        "WARMUP_INCOMPLETE"
    );
    assert_eq!(
        stream
            .drain(&mut store(business.client_mut().await.unwrap(), &ch), AT)
            .await
            .unwrap(),
        0,
        "preview original bytes are retained as raw-only"
    );
    ws.send.send(kline(NOW / 1_000_000, true)).unwrap();
    ws.barrier().await;
    let closed = delivery(&mut stream, &mut business, &ch)
        .await
        .into_parts()
        .unwrap()
        .0;
    emit("stream", &closed);
    assert_eq!(closed["event"], "BAR_CLOSED");
    let value = retained_chart.into_parts().unwrap().0;
    assert!(value["preview"].is_null());
    assert!(!value["series"].as_array().unwrap().is_empty());
    emit("chart_evaluation", &value);
    assert!(
        fence.check().is_err(),
        "closed interval invalidates queued preview"
    );
    assert_eq!(
        stream
            .drain(&mut store(business.client_mut().await.unwrap(), &ch), AT)
            .await
            .unwrap(),
        0
    );
    ws.send.send(kline(NOW / 1_000_000 + 60000, false)).unwrap();
    ws.barrier().await;
    let bad = ClickHouse::new(ClickHouseConfig {
        url: "http://127.0.0.1:1".into(),
        database: "onlyalpha_test_native_market_source".into(),
        user: "default".into(),
        password: String::new(),
        timeout: Duration::from_secs(1),
        tls_roots_pem: vec![],
        max_bytes: WORK,
        max_rows: 100_000,
    })
    .unwrap();
    assert!(
        stream
            .drain(&mut store(business.client_mut().await.unwrap(), &bad), AT)
            .await
            .is_err()
    );
    assert_eq!(
        sealed.published_sealed().unwrap().len(),
        1,
        "failed actual Store drain retains original sealed bytes"
    );
    let failed = delivery(&mut stream, &mut business, &ch)
        .await
        .into_parts()
        .unwrap()
        .0;
    emit("stream", &failed);
    assert_eq!(failed["state"], "FAILED");
    let error = delivery(&mut stream, &mut business, &ch)
        .await
        .into_parts()
        .unwrap()
        .0;
    emit("stream", &error);
    assert_eq!(error["event"], "ERROR");
    stream.close().await.unwrap();
    assert!(Wal::new(&stream_root, WORK).is_err());
    drop(stream);
    assert!(Wal::new(&stream_root, WORK).is_err());
    drop(sealed);
    drop(Wal::new(&stream_root, WORK).unwrap());
    // Every admitted session has its own actual protected WAL root and writer.
    let mut sessions = vec![];
    for n in 0..8 {
        let path = Path::new(&root).with_file_name(format!("concurrent-{n}"));
        std::fs::create_dir(&path).unwrap();
        let wal = Wal::new(&path, WORK).unwrap();
        let instrument = app
            .reference(&resolved, &source_session, "BTCUSDT.BINANCE", deadline())
            .await
            .unwrap();
        let mut stream = app
            .open_stream(
                resolved.clone(),
                instrument,
                &mut store(business.client_mut().await.unwrap(), &ch),
                StreamRequest {
                    stream_id: uid(100 + n),
                    semantic: semantic(1),
                    resume_after_sequence: None,
                    resume_plan_fingerprint: None,
                    clock_ns: NOW,
                    deadline: deadline(),
                    segment_id: format!("concurrent-{n}"),
                    capture_id: format!("concurrent-{n}"),
                    created_at: AT.into(),
                },
                wal,
            )
            .await
            .unwrap();
        ready(&mut stream, &mut business, &ch).await;
        sessions.push((path, stream));
    }
    let path = Path::new(&root).with_file_name("ninth");
    std::fs::create_dir(&path).unwrap();
    let wal = Wal::new(&path, WORK).unwrap();
    let instrument = app
        .reference(&resolved, &source_session, "BTCUSDT.BINANCE", deadline())
        .await
        .unwrap();
    let before = http.calls().len();
    assert!(matches!(
        app.open_stream(
            resolved.clone(),
            instrument,
            &mut store(business.client_mut().await.unwrap(), &ch),
            StreamRequest {
                stream_id: uid(109),
                semantic: semantic(1),
                resume_after_sequence: None,
                resume_plan_fingerprint: None,
                clock_ns: NOW,
                deadline: deadline(),
                segment_id: "ninth".into(),
                capture_id: "ninth".into(),
                created_at: AT.into()
            },
            wal
        )
        .await,
        Err(onlyalpha_product_runtime::market_product::Error::Busy)
    ));
    assert_eq!(http.calls().len(), before);
    assert!(std::fs::read_dir(path).unwrap().all(|entry| {
        !entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .ends_with(".open.wal")
    }));
    for (path, mut stream) in sessions {
        assert_eq!(
            stream
                .drain(&mut store(business.client_mut().await.unwrap(), &ch), AT)
                .await
                .unwrap(),
            0
        );
        stream.close().await.unwrap();
        assert!(Wal::new(&path, WORK).is_err());
        drop(stream);
        drop(Wal::new(&path, WORK).unwrap());
    }
    ws.wait_closed(ws.connections.load(Ordering::SeqCst), None)
        .await;
    // A staged reference proof cannot be transferred to another actual
    // Resource instance even with the same current metadata and artifact identity.
    let other = resolver
        .resolve(&snapshot, &reference, &source_session, None)
        .unwrap();
    let wrong_reference = app
        .reference(&other, &source_session, "BTCUSDT.BINANCE", deadline())
        .await
        .unwrap();
    let path = Path::new(&root).with_file_name("wrong-resource");
    std::fs::create_dir(&path).unwrap();
    let wal = Wal::new(&path, WORK).unwrap();
    let before = http.calls().len();
    assert!(matches!(
        app.open_stream(
            resolved.clone(),
            wrong_reference,
            &mut store(business.client_mut().await.unwrap(), &ch),
            StreamRequest {
                stream_id: uid(114),
                semantic: semantic(1),
                resume_after_sequence: None,
                resume_plan_fingerprint: None,
                clock_ns: NOW,
                deadline: deadline(),
                segment_id: "wrong".into(),
                capture_id: "wrong".into(),
                created_at: AT.into()
            },
            wal
        )
        .await,
        Err(onlyalpha_product_runtime::market_product::Error::Selection)
    ));
    assert_eq!(http.calls().len(), before);
    assert!(
        Wal::new(&path, WORK)
            .unwrap()
            .published_sealed()
            .unwrap()
            .is_empty()
    );
    // A multi-row native recovery observation overlaps one existing closed prefix
    // and one real gap. INCOMPLETE does not mean the prefix has no canonical facts.
    let before_gap = app
        .window(
            &resolved,
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            &WindowRequest {
                instrument_id: "BTCUSDT.BINANCE".into(),
                semantic: semantic(1),
                before_ns: Some(NOW + 120_000_000_000),
                bar_count: 2,
                clock_ns: NOW + 120_000_000_000,
            },
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    assert_eq!(before_gap["coverage"]["status"], "INCOMPLETE");
    assert_eq!(before_gap["coverage"]["gaps"].as_array().unwrap().len(), 1);
    let prefix = app
        .window(
            &resolved,
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            &WindowRequest {
                instrument_id: "BTCUSDT.BINANCE".into(),
                semantic: semantic(1),
                before_ns: Some(NOW + 60_000_000_000),
                bar_count: 1,
                clock_ns: NOW + 120_000_000_000,
            },
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    let resume = prefix["resume_after_sequence"]
        .as_str()
        .unwrap()
        .parse::<i64>()
        .unwrap();
    let plan = prefix["resume_plan_fingerprint"]
        .as_str()
        .unwrap()
        .to_owned();
    // Missing derived base history fails before recorder creation/provider opening.
    let mixed_clock = Arc::new(FixedClock(std::sync::atomic::AtomicI64::new(
        NOW + 120_000_000_000,
    )));
    let mixed_resolver = Resolver::new(
        vec![
            Installed::from_executable(
                spot_source::test_support::controlled_factory(&http.url, &ws.url, 1000),
                &executable,
            )
            .unwrap(),
        ],
        spot_source::test_support::trust(),
        mixed_clock.clone(),
    )
    .unwrap();
    let mixed = Arc::new(
        mixed_resolver
            .resolve(&snapshot, &reference, &source_session, None)
            .unwrap(),
    );
    let path = Path::new(&root).with_file_name("derived-gap");
    std::fs::create_dir(&path).unwrap();
    let wal = Wal::new(&path, WORK).unwrap();
    let instrument = app
        .reference(&mixed, &source_session, "BTCUSDT.BINANCE", deadline())
        .await
        .unwrap();
    let before = http.calls().len();
    assert!(matches!(
        app.open_stream(
            mixed.clone(),
            instrument,
            &mut store(business.client_mut().await.unwrap(), &ch),
            StreamRequest {
                stream_id: uid(115),
                semantic: semantic(7),
                resume_after_sequence: None,
                resume_plan_fingerprint: None,
                clock_ns: NOW + 120_000_000_000,
                deadline: deadline(),
                segment_id: "derived-gap".into(),
                capture_id: "derived-gap".into(),
                created_at: AT.into()
            },
            wal
        )
        .await,
        Err(onlyalpha_product_runtime::market_product::Error::Source(
            SourceError::RefreshRequired
        ))
    ));
    assert_eq!(http.calls().len(), before);
    assert!(
        Wal::new(&path, WORK)
            .unwrap()
            .recovery_pending()
            .unwrap()
            .is_empty()
    );
    for changed in [true, false] {
        let name = if changed {
            "mixed-prefix-bad"
        } else {
            "mixed-prefix-good"
        };
        let path = Path::new(&root).with_file_name(name);
        std::fs::create_dir(&path).unwrap();
        let wal = Wal::new(&path, WORK).unwrap();
        let original = wal.sealed_handle().unwrap();
        let instrument = app
            .reference(&mixed, &source_session, "BTCUSDT.BINANCE", deadline())
            .await
            .unwrap();
        http.changed.store(changed, Ordering::SeqCst);
        let mut stream = app
            .open_stream(
                mixed.clone(),
                instrument,
                &mut store(business.client_mut().await.unwrap(), &ch),
                StreamRequest {
                    stream_id: uid(if changed { 116 } else { 117 }),
                    semantic: semantic(1),
                    resume_after_sequence: Some(resume),
                    resume_plan_fingerprint: Some(plan.clone()),
                    clock_ns: NOW + 120_000_000_000,
                    deadline: deadline(),
                    segment_id: name.into(),
                    capture_id: name.into(),
                    created_at: AT.into(),
                },
                wal,
            )
            .await
            .unwrap();
        if changed {
            loop {
                let pending = stream.next().await.unwrap().unwrap();
                match stream
                    .release(
                        pending,
                        &mut store(business.client_mut().await.unwrap(), &ch),
                        AT,
                    )
                    .await
                {
                    Err(onlyalpha_product_runtime::market_product::Error::Store(
                        onlyalpha_product_runtime::market_data::Error::Conflict,
                    )) => break,
                    Ok(event) => {
                        let event = event.into_parts().unwrap().0;
                        assert!(event["event"] != "BAR_CLOSED" && event["state"] != "READY");
                    }
                    Err(error) => panic!("unexpected {error:?}"),
                }
            }
            let ids = original.published_sealed().unwrap();
            assert_eq!(ids.len(), 1);
            let raw = original.read_sealed(&ids[0]).unwrap();
            assert_eq!(raw[0]["canonical_facts"].as_array().unwrap().len(), 2);
        } else {
            ready(&mut stream, &mut business, &ch).await;
        }
        http.changed.store(false, Ordering::SeqCst);
        stream.close().await.unwrap();
        drop(stream);
        drop(original);
        if changed {
            let restarted = Wal::new(&path, WORK).unwrap();
            let mut original = restarted.sealed_handle().unwrap();
            let ids = original.published_sealed().unwrap();
            assert!(matches!(
                drain_market_capture(
                    &mut original,
                    &mut store(business.client_mut().await.unwrap(), &ch),
                    &ids,
                    AT
                )
                .await,
                Err(onlyalpha_product_runtime::market_product::Error::Store(
                    onlyalpha_product_runtime::market_data::Error::Conflict
                ))
            ));
        }
    }
    let completed = app
        .window(
            &mixed,
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            &WindowRequest {
                instrument_id: "BTCUSDT.BINANCE".into(),
                semantic: semantic(1),
                before_ns: Some(NOW + 120_000_000_000),
                bar_count: 2,
                clock_ns: NOW + 120_000_000_000,
            },
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    emit("window", &completed);
    assert_eq!(completed["bars"].as_array().unwrap().len(), 2);
    assert_eq!(completed["coverage"]["status"], "COMPLETE");
    // Actual derived stream bootstraps only proved native bars; cursor stays 1m,
    // derived closes are executor output and carry no copied provider timing.
    let path = Path::new(&root).with_file_name("derived-stream");
    std::fs::create_dir(&path).unwrap();
    let wal = Wal::new(&path, WORK).unwrap();
    let instrument = app
        .reference(&mixed, &source_session, "BTCUSDT.BINANCE", deadline())
        .await
        .unwrap();
    let mut derived = app
        .open_stream(
            mixed.clone(),
            instrument,
            &mut store(business.client_mut().await.unwrap(), &ch),
            StreamRequest {
                stream_id: uid(118),
                semantic: semantic(7),
                resume_after_sequence: None,
                resume_plan_fingerprint: None,
                clock_ns: NOW + 120_000_000_000,
                deadline: deadline(),
                segment_id: "derived".into(),
                capture_id: "derived".into(),
                created_at: AT.into(),
            },
            wal,
        )
        .await
        .unwrap();
    ready(&mut derived, &mut business, &ch).await;
    mixed_clock.0.store(NOW + 420_000_000_000, Ordering::SeqCst);
    ws.send
        .send(kline(NOW / 1_000_000 + 120000, false))
        .unwrap();
    ws.barrier().await;
    let preview = delivery(&mut derived, &mut business, &ch)
        .await
        .into_parts()
        .unwrap()
        .0;
    emit("stream", &preview);
    assert_eq!(preview["event"], "BAR_PREVIEW");
    assert!(preview["timing"].is_null());
    for n in 2..7 {
        ws.send
            .send(kline(NOW / 1_000_000 + n * 60000, true))
            .unwrap();
        ws.barrier().await;
    }
    let mut closes = 0;
    for _ in 0..6 {
        let event = delivery(&mut derived, &mut business, &ch)
            .await
            .into_parts()
            .unwrap()
            .0;
        emit("stream", &event);
        if event["event"] == "BAR_CLOSED" {
            closes += 1;
            assert!(event["timing"].is_null());
            assert_eq!(event["bar"]["bar_start_ns"], NOW.to_string());
            assert_eq!(
                event["bar"]["bar_end_ns"],
                (NOW + 420_000_000_000).to_string()
            );
        } else {
            assert_eq!(event["event"], "BASE_CURSOR");
        }
    }
    assert_eq!(closes, 1);
    derived.close().await.unwrap();
    drop(derived);
    // Bounded reliable output never drops a close silently; actual remote
    // socket close is the barrier proving the overflowing writer has stopped.
    let overflow_clock = Arc::new(FixedClock(std::sync::atomic::AtomicI64::new(NOW)));
    let overflow_resolver = Resolver::new(
        vec![
            Installed::from_executable(
                spot_source::test_support::controlled_factory(&http.url, &ws.url, 1000),
                &executable,
            )
            .unwrap(),
        ],
        spot_source::test_support::trust(),
        overflow_clock.clone(),
    )
    .unwrap();
    let overflow_resolved = Arc::new(
        overflow_resolver
            .resolve(&snapshot, &reference, &source_session, None)
            .unwrap(),
    );
    let overflow_path = Path::new(&root).with_file_name("overflow");
    std::fs::create_dir(&overflow_path).unwrap();
    let wal = Wal::new(&overflow_path, WORK).unwrap();
    let retained = wal.sealed_handle().unwrap();
    let instrument = app
        .reference(
            &overflow_resolved,
            &source_session,
            "BTCUSDT.BINANCE",
            deadline(),
        )
        .await
        .unwrap();
    let mut overflow = app
        .open_stream(
            overflow_resolved,
            instrument,
            &mut store(business.client_mut().await.unwrap(), &ch),
            StreamRequest {
                stream_id: uid(112),
                semantic: semantic(1),
                resume_after_sequence: None,
                resume_plan_fingerprint: None,
                clock_ns: NOW,
                deadline: deadline(),
                segment_id: "overflow".into(),
                capture_id: "overflow".into(),
                created_at: AT.into(),
            },
            wal,
        )
        .await
        .unwrap();
    ready(&mut overflow, &mut business, &ch).await;
    overflow_clock
        .0
        .store(NOW + 257 * 60_000_000_000, Ordering::SeqCst);
    let closed = ws.closed.load(Ordering::SeqCst) + 1;
    for n in 0..256 {
        ws.send
            .send(kline(NOW / 1_000_000 + n * 60000, true))
            .unwrap();
        ws.barrier().await;
    }
    assert_eq!(retained.published_sealed().unwrap().len(), 256);
    ws.send
        .send(kline(NOW / 1_000_000 + 256 * 60000, true))
        .unwrap();
    ws.wait_closed(closed, Some(&overflow)).await;
    let failed = delivery(&mut overflow, &mut business, &ch)
        .await
        .into_parts()
        .unwrap()
        .0;
    emit("stream", &failed);
    assert_eq!(failed["state"], "FAILED");
    let error = delivery(&mut overflow, &mut business, &ch)
        .await
        .into_parts()
        .unwrap()
        .0;
    emit("stream", &error);
    assert_eq!(error["code"], "MARKET_DATA_STREAM_BACKPRESSURE");
    assert_eq!(retained.published_sealed().unwrap().len(), 257);
    assert!(matches!(
        overflow.close().await,
        Err(onlyalpha_product_runtime::market_product::Error::Backpressure)
    ));
    drop(overflow);
    drop(retained);
    drop(Wal::new(&overflow_path, WORK).unwrap());
    // A new provider occurrence must not replace the payload of an existing
    // canonical fact merely because its WAL segment/producer occurrence is new.
    let conflict_path = Path::new(&root).with_file_name("changed-close");
    std::fs::create_dir(&conflict_path).unwrap();
    let wal = Wal::new(&conflict_path, WORK).unwrap();
    let original = wal.sealed_handle().unwrap();
    let instrument = app
        .reference(&resolved, &source_session, "BTCUSDT.BINANCE", deadline())
        .await
        .unwrap();
    http.changed.store(true, Ordering::SeqCst);
    let mut conflict = app
        .open_stream(
            resolved.clone(),
            instrument,
            &mut store(business.client_mut().await.unwrap(), &ch),
            StreamRequest {
                stream_id: uid(111),
                semantic: semantic(1),
                resume_after_sequence: None,
                resume_plan_fingerprint: None,
                clock_ns: NOW,
                deadline: deadline(),
                segment_id: "changed".into(),
                capture_id: "changed".into(),
                created_at: AT.into(),
            },
            wal,
        )
        .await
        .unwrap();
    loop {
        let pending = conflict.next().await.unwrap().unwrap();
        match conflict
            .release(
                pending,
                &mut store(business.client_mut().await.unwrap(), &ch),
                AT,
            )
            .await
        {
            Err(onlyalpha_product_runtime::market_product::Error::Store(
                onlyalpha_product_runtime::market_data::Error::Conflict,
            )) => break,
            Ok(event) => {
                let event = event.into_parts().unwrap().0;
                assert!(
                    event["event"] != "BAR_CLOSED" && event["state"] != "READY",
                    "conflicting fact must never receive display authorization"
                );
            }
            Err(error) => panic!("unexpected {error:?}"),
        }
    }
    http.changed.store(false, Ordering::SeqCst);
    assert_eq!(original.published_sealed().unwrap().len(), 1);
    conflict.close().await.unwrap();
    drop(conflict);
    drop(original);
    let restarted = Wal::new(&conflict_path, WORK).unwrap();
    let mut retained = restarted.sealed_handle().unwrap();
    let ids = retained.published_sealed().unwrap();
    assert!(
        matches!(
            drain_market_capture(
                &mut retained,
                &mut store(business.client_mut().await.unwrap(), &ch),
                &ids,
                AT
            )
            .await,
            Err(onlyalpha_product_runtime::market_product::Error::Store(
                onlyalpha_product_runtime::market_data::Error::Conflict
            ))
        ),
        "startup uses the same identity proof and cannot publish the rejected fact"
    );
    assert_eq!(retained.published_sealed().unwrap(), ids);
    drop(retained);
    drop(restarted);
    // An observation received while REST is still blocked is already sealed;
    // cancel closes the real writer and restart preserves its exact original bytes.
    let blocked_path = Path::new(&root).with_file_name("blocked-baseline");
    std::fs::create_dir(&blocked_path).unwrap();
    let wal = Wal::new(&blocked_path, WORK).unwrap();
    let sealed = wal.sealed_handle().unwrap();
    let instrument = app
        .reference(&resolved, &source_session, "BTCUSDT.BINANCE", deadline())
        .await
        .unwrap();
    *http.gate.0.lock().unwrap() = true;
    let target = ws.connections.load(Ordering::SeqCst) + 1;
    let mut blocked = app
        .open_stream(
            resolved.clone(),
            instrument,
            &mut store(business.client_mut().await.unwrap(), &ch),
            StreamRequest {
                stream_id: uid(110),
                semantic: semantic(1),
                resume_after_sequence: None,
                resume_plan_fingerprint: None,
                clock_ns: NOW,
                deadline: deadline(),
                segment_id: "blocked".into(),
                capture_id: "blocked".into(),
                created_at: AT.into(),
            },
            wal,
        )
        .await
        .unwrap();
    ws.wait_connections(target).await;
    ws.send.send(kline(NOW / 1_000_000, false)).unwrap();
    ws.barrier().await;
    let ids = sealed.published_sealed().unwrap();
    assert_eq!(
        ids.len(),
        1,
        "WS original bytes are durable before blocked REST returns"
    );
    let original = sealed.read_sealed(&ids[0]).unwrap();
    assert_eq!(original[0]["evidence"]["stream"], "websocket");
    assert!(
        original[0]["canonical_facts"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    blocked.close().await.unwrap();
    drop(blocked);
    drop(sealed);
    *http.gate.0.lock().unwrap() = false;
    http.gate.1.notify_all();
    let restarted = Wal::new(&blocked_path, WORK).unwrap();
    assert_eq!(restarted.read_sealed(&ids[0]).unwrap(), original);
    drop(restarted);
    // Real Probe uses maintained REST + depth WS, then exact append-only PG evidence.
    assert_eq!(
        latest_probe(business.client_mut().await.unwrap(), &resolved)
            .await
            .unwrap()["status"],
        "UNKNOWN"
    );
    let probe = app
        .execute_probe(resolved.clone(), human.clone(), &uid(200), deadline())
        .await
        .unwrap();
    assert_eq!(probe.document()["overall_status"], "READY");
    probe
        .persist(business.client_mut().await.unwrap())
        .await
        .unwrap();
    emit("probe_result", probe.document());
    assert_eq!(
        latest_probe(business.client_mut().await.unwrap(), &resolved)
            .await
            .unwrap()["status"],
        "READY"
    );
    let withdrawn = app
        .execute_probe(resolved.clone(), human.clone(), &uid(201), deadline())
        .await
        .unwrap();
    human.active.store(false, Ordering::SeqCst);
    assert!(matches!(
        withdrawn
            .persist(business.client_mut().await.unwrap())
            .await,
        Err(onlyalpha_product_runtime::market_product::Error::Forbidden)
    ));
    human.active.store(true, Ordering::SeqCst);
    assert_eq!(business.client_mut().await.unwrap().query_one("SELECT count(*) FROM public.integration_probe_attempt WHERE probe_attempt_id=$1::text::uuid",&[&uid(201)]).await.unwrap().get::<_,i64>(0),0);
    let mut malformed = probe.document().clone();
    malformed["probe_attempt_id"] = uid(202).into();
    malformed["checks"][0]["status"] = "FAIL".into();
    let fingerprint = sha(malformed.to_string().as_bytes());
    business.client_mut().await.unwrap().execute("INSERT INTO public.integration_probe_attempt SELECT $1::text::uuid,integration_id,revision_fingerprint,type_id,type_descriptor_fingerprint,probe_contract_fingerprint,probe_configuration_fingerprint,runtime_configuration_fingerprint,started_at,completed_at,overall_status,$2,$3::text::json FROM public.integration_probe_attempt WHERE probe_attempt_id=$4::text::uuid",&[&uid(202),&fingerprint,&malformed.to_string(),&uid(200)]).await.unwrap();
    assert!(
        matches!(
            latest_probe(business.client_mut().await.unwrap(), &resolved).await,
            Err(onlyalpha_product_runtime::market_product::Error::Corrupt)
        ),
        "even correctly hashed stored Probe must prove its check/status relation"
    );
    // A newer head and UNKNOWN Probe cannot replace or disable an explicitly
    // selected retained Revision that is still ACTIVE and actually installed.
    let retained_id = IntegrationId::new(&uid(300)).unwrap();
    Integrations::new(business.client_mut().await.unwrap())
        .create(
            &CreateIntegration::new(
                CommandId::new(&uid(301)).unwrap(),
                retained_id.clone(),
                IntegrationTypeId::new("binance.spot.market_data").unwrap(),
                "Retained source",
            )
            .unwrap(),
            &authoring,
            AT.parse().unwrap(),
            WORK,
        )
        .await
        .unwrap();
    Integrations::new(business.client_mut().await.unwrap())
        .publish_revision(
            &PublishRevision::new(CommandId::new(&uid(302)).unwrap(), retained_id.clone(), 1)
                .unwrap(),
            &authoring,
            AT.parse().unwrap(),
            1000,
            WORK,
        )
        .await
        .unwrap();
    let first = Integrations::new(business.client_mut().await.unwrap())
        .read(&retained_id, 1000, WORK)
        .await
        .unwrap()
        .unwrap();
    let old = first
        .integration()
        .record()
        .current_revision_fingerprint
        .clone()
        .unwrap();
    let old_reference =
        Reference::new(retained_id.value(), &old, Some("binance.spot.market_data")).unwrap();
    let old_selection = Selection::new(
        old_reference.clone(),
        "binance.spot.market_data.live",
        "GLOBAL",
    )
    .unwrap();
    let permitted = Authority::new(
        "retained-human",
        &sha(b"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
        vec![Grant::new(old_selection, vec![Permission::ClosedHistory]).unwrap()],
    )
    .unwrap();
    let permitted = permitted
        .authenticate("Bearer bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        .unwrap();
    let retained_path = Path::new(&root).with_file_name("retained-source");
    std::fs::create_dir(&retained_path).unwrap();
    let mut retained_wal = Wal::new(&retained_path, WORK).unwrap();
    let own = Arc::new(
        resolver
            .resolve(&first, &old_reference, &permitted, None)
            .unwrap(),
    );
    let own_human = Arc::new(Human {
        selection: own.selection().clone(),
        active: AtomicBool::new(true),
    });
    let mut own_work = app
        .prepare_acquisition(
            own,
            permitted.clone(),
            own_human,
            &mut store(business.client_mut().await.unwrap(), &ch),
            AcquisitionRequest {
                instrument_id: "BTCUSDT.BINANCE",
                semantic: &semantic(1),
                start_ns: 0,
                end_ns: 120_000_000_000,
                clock_ns: NOW,
                admitted_at: AT,
            },
        )
        .await
        .unwrap();
    let execution = lease(own_work.id()).await;
    own_work
        .start(
            &mut store(business.client_mut().await.unwrap(), &ch),
            &execution,
            AT,
        )
        .await
        .unwrap();
    let captured = own_work
        .capture(
            &app,
            &mut retained_wal,
            CaptureRequest {
                segment_id: "retained-source",
                capture_id: "retained-source",
                created_at: AT,
                deadline: deadline(),
            },
            &execution,
        )
        .await
        .unwrap();
    let complete = own_work
        .publish(
            &mut store(business.client_mut().await.unwrap(), &ch),
            &retained_wal,
            &captured,
            AT,
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    assert_eq!(complete["status"], "COMPLETE");
    drop(captured);
    execution.close().await.unwrap();
    let version = first.draft().unwrap().0.record().draft_version;
    let config = first
        .draft()
        .unwrap()
        .0
        .record()
        .public_configuration_document
        .clone();
    Integrations::new(business.client_mut().await.unwrap())
        .update_draft(
            &UpdateDraft::new(
                CommandId::new(&uid(303)).unwrap(),
                retained_id.clone(),
                version,
                config,
                Some(ObjectDocument::new("{\"instrument\":\"ETHUSDT\"}", WORK).unwrap()),
            )
            .unwrap(),
            &authoring,
            AT.parse().unwrap(),
            1000,
            WORK,
        )
        .await
        .unwrap();
    Integrations::new(business.client_mut().await.unwrap())
        .publish_revision(
            &PublishRevision::new(
                CommandId::new(&uid(304)).unwrap(),
                retained_id.clone(),
                version + 1,
            )
            .unwrap(),
            &authoring,
            AT.parse().unwrap(),
            1000,
            WORK,
        )
        .await
        .unwrap();
    let changed = Integrations::new(business.client_mut().await.unwrap())
        .read(&retained_id, 1000, WORK)
        .await
        .unwrap()
        .unwrap();
    assert_ne!(
        changed
            .integration()
            .record()
            .current_revision_fingerprint
            .as_ref()
            .unwrap(),
        &old
    );
    let old_resolved = resolver
        .resolve(&changed, &old_reference, &permitted, None)
        .unwrap();
    assert_eq!(old_resolved.selection().reference().revision(), old);
    assert_eq!(
        latest_probe(business.client_mut().await.unwrap(), &old_resolved)
            .await
            .unwrap()["status"],
        "UNKNOWN"
    );
    let old_window = app
        .window(
            &old_resolved,
            &permitted,
            &mut store(business.client_mut().await.unwrap(), &ch),
            &WindowRequest {
                instrument_id: "BTCUSDT.BINANCE".into(),
                semantic: semantic(1),
                before_ns: Some(120_000_000_000),
                bar_count: 2,
                clock_ns: NOW,
            },
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    emit("window", &old_window);
    assert_eq!(old_window["coverage"]["status"], "COMPLETE");
    assert_eq!(old_window["resolved_start_ns"], "0");
    assert_eq!(old_window["resolved_end_ns"], "120000000000");
    assert_eq!(old_window["bars"].as_array().unwrap().len(), 2);
    let missing = Resolver::new(
        vec![],
        spot_source::test_support::trust(),
        Arc::new(ConstantClock),
    )
    .unwrap();
    assert!(matches!(
        missing.resolve(&changed, &old_reference, &permitted, None),
        Err(onlyalpha_product_runtime::market_product::Error::Unavailable)
    ));
    // Original Source withdrawal fences a queued physical send while Host
    // persistence of already accepted occurrences remains available.
    let revoked_path = Path::new(&root).with_file_name("revoked");
    std::fs::create_dir(&revoked_path).unwrap();
    let wal = Wal::new(&revoked_path, WORK).unwrap();
    let instrument = app
        .reference(&resolved, &source_session, "BTCUSDT.BINANCE", deadline())
        .await
        .unwrap();
    let mut revoked = app
        .open_stream(
            resolved.clone(),
            instrument,
            &mut store(business.client_mut().await.unwrap(), &ch),
            StreamRequest {
                stream_id: uid(113),
                semantic: semantic(1),
                resume_after_sequence: None,
                resume_plan_fingerprint: None,
                clock_ns: NOW,
                deadline: deadline(),
                segment_id: "revoked".into(),
                capture_id: "revoked".into(),
                created_at: AT.into(),
            },
            wal,
        )
        .await
        .unwrap();
    ready(&mut revoked, &mut business, &ch).await;
    ws.send.send(kline(NOW / 1_000_000, false)).unwrap();
    ws.barrier().await;
    let pending = revoked.next().await.unwrap().unwrap();
    let authorized = revoked
        .release(
            pending,
            &mut store(business.client_mut().await.unwrap(), &ch),
            AT,
        )
        .await
        .unwrap();
    let (_, fence) = authorized.into_parts().unwrap();
    ws.send.send(kline(NOW / 1_000_000, false)).unwrap();
    ws.barrier().await;
    authority.withdraw();
    assert!(asset_fence.check().is_err());
    assert!(fence.check().is_err());
    assert!(matches!(
        revoked.next().await,
        Err(onlyalpha_product_runtime::market_product::Error::Forbidden)
    ));
    let _ = revoked.close().await;
    assert_eq!(
        revoked
            .drain(&mut store(business.client_mut().await.unwrap(), &ch), AT)
            .await
            .unwrap(),
        1
    );
    drop(revoked);
    drop(Wal::new(&revoked_path, WORK).unwrap());
    ws.close().await;
    business.close().await.unwrap();
}
