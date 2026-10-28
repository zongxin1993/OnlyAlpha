//! Concrete native startup: no implicit migration, initialization or reconnection.
use crate::application::frozen_strategy::FrozenStore;
use crate::application::integration_catalog::AuthoringCatalog;
use crate::application::market_product::{Application, Installed, Resolver};
use crate::application::qualification_policy;
use crate::bootstrap::startup::{Directory, StorageInputs, StorageRoots};
use crate::persistence::authority_session::AuthoritySession;
use crate::persistence::integration_postgres::Integrations;
use crate::persistence::market_data::{ClickHouse, ClickHouseConfig};
use crate::security::protected_files::{self, FilePolicy};
use crate::transport::endpoint::Transport;
use crate::transport::host::{self, Failure, Host, ROWS, WORK};
use onlyalpha_calculation_bridge::ChartInstallation;
use onlyalpha_integration_contract::source::{Clock, SourceError, Trust};
use std::{
    net::{IpAddr, SocketAddr},
    path::PathBuf,
    sync::{
        Arc, OnceLock,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
use tokio::{
    net::{TcpListener, TcpStream},
    sync::Mutex,
    task::{JoinHandle, JoinSet},
};
use tokio_postgres::{
    Client, Config, NoTls,
    config::{Host as PgHost, SslMode},
};
/// Operational configuration is explicit and separate from canonical identities.
/// Plaintext is admitted only by the verified sole-dev launcher.
pub struct Configuration {
    pub user_data: PathBuf,
    pub schema: PathBuf,
    pub assets: PathBuf,
    pub algorithms: PathBuf,
    pub algorithm_artifact: String,
    pub trust: PathBuf,
    pub postgres_dsn: String,
    pub postgres_peer: SocketAddr,
    pub postgres_user: String,
    pub postgres_database: String,
    pub clickhouse: ClickHouseConfig,
    pub transport: Transport,
    pub listen: SocketAddr,
}
struct WallClock;
impl Clock for WallClock {
    fn now_ns(&self) -> Result<i64, SourceError> {
        wall_clock_ns(std::time::SystemTime::now())
    }
}
// Source receive/seal observations use the Domain's microsecond wall-clock
// precision. Provider event timestamps and canonical market facts are untouched.
fn wall_clock_ns(at: std::time::SystemTime) -> Result<i64, SourceError> {
    let observed = host::observation_time(at).map_err(|_| SourceError::Unavailable)?;
    onlyalpha_domain::time::OnlyTimestamp::from_datetime(observed)
        .unix_nanos()
        .to_string()
        .parse()
        .map_err(|_| SourceError::Unavailable)
}
struct PendingRead {
    client: Option<Client>,
    driver: Option<JoinHandle<Result<(), tokio_postgres::Error>>>,
    alive: tokio::sync::watch::Receiver<bool>,
}
impl PendingRead {
    async fn close(&mut self) -> Result<(), Failure> {
        self.client.take();
        drain_driver(&mut self.driver).await
    }
}
async fn drain_driver(
    owned: &mut Option<JoinHandle<Result<(), tokio_postgres::Error>>>,
) -> Result<(), Failure> {
    if let Some(driver) = owned.as_mut() {
        let failed = match tokio::time::timeout(Duration::from_secs(5), &mut *driver).await {
            Ok(Ok(Ok(()))) => false,
            Ok(_) => true,
            Err(_) => {
                driver.abort();
                let _ = driver.await;
                true
            }
        };
        // Cancellation before this point retains the original handle in its owner.
        owned.take();
        if failed {
            return Err(Failure::unavailable("POSTGRES_DRIVER_DRAIN_FAILED"));
        }
    }
    Ok(())
}
// A finished or panicked actual driver withdraws admission even while the
// retained mutation mutex is occupied. This observer owns no second connection.
pub(crate) fn driver_active(alive: &tokio::sync::watch::Receiver<bool>) -> bool {
    alive.has_changed().is_ok() && *alive.borrow()
}
impl Drop for PendingRead {
    fn drop(&mut self) {
        self.client.take();
        if let Some(driver) = self.driver.take() {
            driver.abort();
        }
    }
}
pub(crate) struct Database {
    postgres_dsn: zeroize::Zeroizing<String>,
    postgres_peer: SocketAddr,
    postgres_user: String,
    postgres_database: String,
    transport: Transport,
}
impl Database {
    fn from(config: &Configuration) -> Self {
        Self {
            postgres_dsn: zeroize::Zeroizing::new(config.postgres_dsn.clone()),
            postgres_peer: config.postgres_peer,
            postgres_user: config.postgres_user.clone(),
            postgres_database: config.postgres_database.clone(),
            transport: config.transport.clone(),
        }
    }
    pub(crate) async fn lease(
        &self,
        id: &str,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
    ) -> Result<crate::persistence::market_data::ExecutionLease, Failure> {
        // The execution lease registers its exact acquisition lock key before
        // taking the advisory lock. It owns that catalog write, unlike the
        // separately retained read-only Product query connection.
        let mut connection = connect(self, false).await?;
        if crate::bootstrap::deployment::verify_binding(
            connection
                .client
                .as_mut()
                .ok_or(Failure::unavailable("POSTGRES_UNAVAILABLE"))?,
            namespace,
        )
        .await
        .is_err()
        {
            let closed = connection.close().await;
            closed?;
            return Err(Failure::unavailable("SEMANTIC_STORE_BINDING_MISMATCH"));
        }
        crate::persistence::market_data::ExecutionLease::acquire(
            connection
                .client
                .take()
                .ok_or(Failure::unavailable("POSTGRES_UNAVAILABLE"))?,
            connection
                .driver
                .take()
                .ok_or(Failure::unavailable("POSTGRES_UNAVAILABLE"))?,
            id,
        )
        .await
        .map_err(Failure::from)
    }
}
async fn connect(config: &Database, readonly: bool) -> Result<PendingRead, Failure> {
    // NoTls never silently falls back from SSLPrefer/Require. Independent exact
    // TCP peer + explicit endpoint/user/database + later semantic namespace proof.
    let mut pg: Config = config
        .postgres_dsn
        .as_str()
        .parse()
        .map_err(|_| Failure::unavailable("POSTGRES_CONFIGURATION_INVALID"))?;
    if pg.get_ssl_mode() != SslMode::Disable
        || pg.get_hosts().len() != 1
        || pg.get_ports() != [config.postgres_peer.port()]
        || pg.get_user() != Some(config.postgres_user.as_str())
        || pg.get_dbname() != Some(config.postgres_database.as_str())
        || !matches!(pg.get_hosts().first(),Some(PgHost::Tcp(name)) if name=="postgres")
    {
        return Err(Failure::unavailable("DEV_POSTGRES_TRANSPORT_DENIED"));
    }
    if !matches!(
        config.transport,
        Transport::ContainedDevelopment { .. } | Transport::Loopback { .. }
    ) || !matches!(config.postgres_peer.ip(),IpAddr::V4(a) if a.is_private())
    {
        return Err(Failure::unavailable("DEV_POSTGRES_TRANSPORT_DENIED"));
    }
    pg.options(if readonly {
        "-c default_transaction_read_only=on -c search_path=pg_catalog,public,pg_temp"
    } else {
        "-c search_path=pg_catalog,public,pg_temp"
    });
    let stream = tokio::time::timeout(
        Duration::from_secs(5),
        TcpStream::connect(config.postgres_peer),
    )
    .await
    .map_err(|_| Failure::unavailable("POSTGRES_UNAVAILABLE"))?
    .map_err(|_| Failure::unavailable("POSTGRES_UNAVAILABLE"))?;
    if stream.peer_addr().ok() != Some(config.postgres_peer) {
        return Err(Failure::unavailable("POSTGRES_PEER_MISMATCH"));
    }
    let (client, connection) =
        tokio::time::timeout(Duration::from_secs(5), pg.connect_raw(stream, NoTls))
            .await
            .map_err(|_| Failure::unavailable("POSTGRES_UNAVAILABLE"))?
            .map_err(|_| Failure::unavailable("POSTGRES_UNAVAILABLE"))?;
    let (observed, alive) = tokio::sync::watch::channel(true);
    let driver = tokio::spawn(async move {
        let result = connection.await;
        observed.send_replace(false);
        result
    });
    let mut owned = PendingRead {
        client: Some(client),
        driver: Some(driver),
        alive,
    };
    let verified = async {
        let mode: bool = owned
            .client
            .as_ref()
            .ok_or(Failure::unavailable("POSTGRES_UNAVAILABLE"))?
            .query_one(
                "SELECT current_setting('default_transaction_read_only')='on'",
                &[],
            )
            .await
            .map_err(|_| Failure::unavailable("POSTGRES_UNAVAILABLE"))?
            .get(0);
        if mode != readonly {
            return Err(Failure::unavailable("POSTGRES_READ_POLICY_MISMATCH"));
        }
        Ok(())
    }
    .await;
    if let Err(error) = verified {
        let closed = owned.close().await;
        closed?;
        return Err(error);
    }
    Ok(owned)
}
pub struct Running {
    pub host: Arc<Host>,
    pub ingress: crate::security::ingress::LocalIngress,
    reader_driver: Option<JoinHandle<Result<(), tokio_postgres::Error>>>,
    connections: JoinSet<Result<(), crate::security::ingress::Error>>,
}
impl Drop for Running {
    fn drop(&mut self) {
        self.host
            .ready
            .store(false, std::sync::atomic::Ordering::Release);
        self.host.chart_gate.close();
        if let Some(driver) = self.reader_driver.take() {
            driver.abort();
        }
    }
}
impl Running {
    pub async fn open(
        config: Configuration,
        shutdown: &tokio::sync::watch::Receiver<bool>,
    ) -> Result<Self, Failure> {
        if *shutdown.borrow() {
            return Err(Failure::unavailable("NATIVE_STARTUP_INTERRUPTED"));
        }
        let database = Database::from(&config);
        let inputs = StorageInputs::load(
            StorageRoots::open(&config.user_data).map_err(|e| Failure::unavailable(e.code()))?,
            &config.schema,
            WORK,
        )
        .map_err(|e| Failure::unavailable(e.code()))?;
        let chart_installation =
            ChartInstallation::open(&config.algorithms, &config.algorithm_artifact)
                .map_err(|_| Failure::unavailable("ALGORITHM_INSTALLATION_INVALID"))?;
        if chart_installation
            .distribution_version()
            .map_err(|_| Failure::unavailable("ALGORITHM_INSTALLATION_INVALID"))?
            != env!("CARGO_PKG_VERSION")
        {
            return Err(Failure::unavailable("ALGORITHM_RELEASE_MISMATCH"));
        }
        let chart = Arc::new(
            crate::application::chart::ChartQuery::new(chart_installation)
                .map_err(|e| Failure::unavailable(e.code()))?,
        );
        let catalog = Arc::new(
            AuthoringCatalog::new(vec![
                crate::adapters::agent_model::registration(WORK)
                    .map_err(|_| Failure::unavailable("AGENT_CATALOG_INVALID"))?,
                onlyalpha_plugin_binance::spot_authoring(WORK)
                    .map_err(|_| Failure::unavailable("SOURCE_CATALOG_INVALID"))?,
                onlyalpha_plugin_binance::usdm_authoring(WORK)
                    .map_err(|_| Failure::unavailable("SOURCE_CATALOG_INVALID"))?,
                onlyalpha_plugin_tushare::daily_authoring(WORK)
                    .map_err(|_| Failure::unavailable("SOURCE_CATALOG_INVALID"))?,
            ])
            .map_err(|_| Failure::unavailable("SOURCE_CATALOG_INVALID"))?,
        );
        let trust = read_bounded(&config.trust, FilePolicy::HistoryDocument, 1024 * 1024)
            .map_err(|_| Failure::unavailable("SOURCE_TRUST_INVALID"))?;
        let executable = std::env::current_exe()
            .map_err(|_| Failure::unavailable("NATIVE_ARTIFACT_UNAVAILABLE"))?;
        let bytes = read_bounded(&executable, FilePolicy::Executable, 128 * 1024 * 1024)
            .map_err(|_| Failure::unavailable("NATIVE_ARTIFACT_UNAVAILABLE"))?;
        let factory = onlyalpha_plugin_binance::spot_source::SpotFactory::installed()
            .map_err(|_| Failure::unavailable("SOURCE_CATALOG_INVALID"))?;
        let resolver = Resolver::new(
            vec![Installed::from_executable(Arc::new(factory), &bytes)?],
            Trust::explicit_roots(vec![trust.to_vec()])
                .map_err(|_| Failure::unavailable("SOURCE_TRUST_INVALID"))?,
            Arc::new(WallClock),
        )?;
        drop(bytes);
        let assets = crate::transport::web_assets::Assets::load(&config.assets, WORK)
            .map_err(|e| Failure::unavailable(e.code()))?
            .router();
        if *shutdown.borrow() {
            return Err(Failure::unavailable("NATIVE_STARTUP_INTERRUPTED"));
        }
        let access = crate::security::human_access::Access::generate()?;
        let mut write = connect(&database, false).await?;
        let writer_live = write.alive.clone();
        let mut writer = AuthoritySession::acquire(
            write
                .client
                .take()
                .ok_or(Failure::unavailable("POSTGRES_UNAVAILABLE"))?,
            write
                .driver
                .take()
                .ok_or(Failure::unavailable("POSTGRES_UNAVAILABLE"))?,
        )
        .await
        .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
        let result = async {
            inputs
                .verify(
                    writer
                        .client_mut()
                        .await
                        .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?,
                    ROWS,
                )
                .await
                .map_err(|e| Failure::unavailable(e.code()))?;
            let frozen = FrozenStore::open(inputs.roots().directory(Directory::Research))
                .map_err(|e| Failure::unavailable(e.code()))?;
            frozen
                .inventory(&mut writer, WORK)
                .await
                .map_err(|e| Failure::unavailable(e.code()))?;
            frozen
                .reconcile(
                    &mut writer,
                    inputs.namespace(),
                    &host::now()?.to_string(),
                    ROWS,
                    WORK,
                )
                .await
                .map_err(|e| Failure::unavailable(e.code()))?;
            qualification_policy::Store::open(inputs.roots().directory(Directory::Research))
                .map_err(|e| Failure::unavailable(e.code()))?
                .admit(&mut writer, inputs.namespace(), &[], WORK)
                .await
                .map_err(|e| Failure::unavailable(e.code()))?;
            let snapshots = Integrations::new(
                writer
                    .client_mut()
                    .await
                    .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?,
            )
            .list_snapshots(None, None, ROWS, WORK)
            .await?;
            host::issue(host::grants(&snapshots)?)
        }
        .await;
        let issuer = match result {
            Ok(v) => v,
            Err(e) => {
                let _ = writer.close().await;
                return Err(e);
            }
        };
        let mut reader = match connect(&database, true).await {
            Ok(r) => r,
            Err(e) => {
                let _ = writer.close().await;
                return Err(e);
            }
        };
        if let Err(e) = inputs
            .verify(
                reader
                    .client
                    .as_mut()
                    .ok_or(Failure::unavailable("POSTGRES_UNAVAILABLE"))?,
                ROWS,
            )
            .await
        {
            let _ = reader.close().await;
            let _ = writer.close().await;
            return Err(Failure::unavailable(e.code()));
        }
        let clickhouse = match async {
            let selected = Arc::new(ClickHouse::new(config.clickhouse)?);
            selected.assert_server().await?;
            Ok::<_, Failure>(selected)
        }
        .await
        {
            Ok(v) => v,
            Err(error) => {
                let mut failed = Some(error);
                remember(&mut failed, reader.close().await);
                remember(
                    &mut failed,
                    writer
                        .close()
                        .await
                        .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_DRAIN_FAILED")),
                );
                return Err(failed.expect("recorded startup failure"));
            }
        };
        let read = Arc::new(Mutex::new(reader.client.take()));
        let metadata = match crate::transport::integrations::query_router_shared(
            Arc::clone(&read),
            ROWS,
            WORK,
        )
        .await
        {
            Ok(r) => r.merge(crate::transport::integration_types::router(Arc::clone(
                &catalog,
            ))),
            Err(e) => {
                read.lock().await.take();
                let _ = reader.close().await;
                let _ = writer.close().await;
                return Err(Failure::unavailable(e.code()));
            }
        };
        let host = Arc::new(Host {
            inputs,
            database,
            writer_live,
            writer: Mutex::new(Some(writer)),
            reader: read,
            catalog,
            resolver,
            app: Arc::new(Application::default()),
            clickhouse,
            chart,
            chart_gate: Arc::new(tokio::sync::Semaphore::new(
                crate::application::chart::ChartQuery::MAX_CONCURRENT_INVOCATIONS,
            )),
            metadata,
            assets,
            issuer: Mutex::new(issuer),
            proposal_fence: Mutex::new(crate::transport::host::issue(Vec::new())?),
            revoker: OnceLock::new(),
            ready: AtomicBool::new(false),
            socket_slots: Arc::new(tokio::sync::Semaphore::new(8)),
            stream_tasks: tokio::sync::Mutex::new(JoinSet::new()),
            stream_failure: std::sync::Mutex::new(None),
            previews: std::sync::Mutex::new(std::collections::BTreeMap::new()),
        });
        let ingress = crate::security::ingress::LocalIngress::new_workstation(
            access,
            host.router(),
            config.transport,
        );
        let mut running = Self {
            host,
            ingress,
            reader_driver: reader.driver.take(),
            connections: JoinSet::new(),
        };
        let admitted = async {
            running
                .host
                .revoker
                .set(running.ingress.source_revoker())
                .map_err(|_| Failure::unavailable("SOURCE_GATE_INVALID"))?;
            running.host.recover_market_data().await?;
            let selected = Arc::clone(&running.host.chart);
            tokio::task::spawn_blocking(move || {
                selected.registered_capabilities_before(
                    std::time::Instant::now() + Duration::from_secs(10),
                )
            })
            .await
            .map_err(|_| Failure::unavailable("ALGORITHM_QUALIFICATION_UNAVAILABLE"))?
            .map_err(|_| Failure::unavailable("ALGORITHM_QUALIFICATION_UNAVAILABLE"))?;
            if *shutdown.borrow() {
                return Err(Failure::unavailable("NATIVE_STARTUP_INTERRUPTED"));
            }
            if !running.host.writer_active() {
                return Err(Failure::unavailable("PRODUCT_AUTHORITY_DRIVER_LOST"));
            }
            Ok(())
        }
        .await;
        if let Err(error) = admitted {
            let mut failed = Some(error);
            remember(&mut failed, running.close().await);
            return Err(failed.expect("recorded startup failure"));
        }
        running.host.ready.store(true, Ordering::Release);
        Ok(running)
    }
    pub async fn serve(
        mut self,
        listener: TcpListener,
        mut shutdown: tokio::sync::watch::Receiver<bool>,
    ) -> Result<(), Failure> {
        let mut writer_live = self.host.writer_live.clone();
        let mut failure = loop {
            if *shutdown.borrow() {
                break None;
            }
            if !self.host.writer_active() {
                break Some(Failure::unavailable("PRODUCT_AUTHORITY_DRIVER_LOST"));
            }
            tokio::select! {
             _=shutdown.changed()=>break None,
             expired=self.host.app.expire_temporary()=>{if expired.is_err(){break Some(Failure::unavailable("TEMPORARY_CACHE_LIFECYCLE_FAILED"));}},
             _=writer_live.changed()=>break Some(Failure::unavailable("PRODUCT_AUTHORITY_DRIVER_LOST")),
             _=self.reader_driver.as_mut().expect("retained read driver")=>{self.reader_driver.take();break Some(Failure::unavailable("PRODUCT_READ_DRIVER_LOST"));},
             accepted=listener.accept()=>match accepted {Ok((stream,_))=>{let ingress=self.ingress.clone();self.connections.spawn(async move{ingress.serve_connection(stream).await});},Err(_)=>break Some(Failure::unavailable("LISTENER_UNAVAILABLE"))},
             result=self.connections.join_next(),if !self.connections.is_empty()=>{if matches!(result,Some(Err(_))){break Some(Failure::unavailable("CONNECTION_TASK_FAILED"));}}
            }
        };
        drop(listener);
        remember(&mut failure, self.close().await);
        if let Some(error) = failure {
            Err(error)
        } else {
            Ok(())
        }
    }
    async fn close(&mut self) -> Result<(), Failure> {
        // Each resource is attempted even after an earlier failure. Physical mutation
        // authority is released last, after sockets, streams, workers and read driver.
        self.host.ready.store(false, Ordering::Release);
        self.host.chart_gate.close();
        let mut failure = None;
        remember(
            &mut failure,
            self.ingress
                .shutdown_and_drain()
                .await
                .map_err(|_| Failure::unavailable("INGRESS_DRAIN_FAILED")),
        );
        while let Some(result) = self.connections.join_next().await {
            if result.is_err() {
                remember(
                    &mut failure,
                    Err(Failure::unavailable("CONNECTION_TASK_FAILED")),
                );
            }
        }
        while let Some(result) = self.host.stream_tasks.lock().await.join_next().await {
            if let Ok(Err(error)) = &result {
                eprintln!("NATIVE_STREAM_FAILED {error}");
            }
            if !matches!(result, Ok(Ok(()))) {
                remember(
                    &mut failure,
                    Err(Failure::unavailable("STREAM_DRAIN_FAILED")),
                );
            }
        }
        match self.host.stream_failure.lock() {
            Ok(record) => {
                if let Some(code) = *record {
                    remember(&mut failure, Err(Failure::unavailable(code)));
                }
            }
            Err(_) => remember(
                &mut failure,
                Err(Failure::unavailable("STREAM_DRAIN_FAILED")),
            ),
        }
        let chart = Arc::clone(&self.host.chart);
        let drained = tokio::task::spawn_blocking(move || {
            let closed = chart.close();
            let drained = chart.drain();
            closed.and(drained)
        })
        .await
        .map_err(|_| Failure::unavailable("CHART_DRAIN_FAILED"))
        .and_then(|r| r.map_err(|e| Failure::unavailable(e.code())));
        remember(&mut failure, drained);
        self.host.reader.lock().await.take();
        remember(&mut failure, drain_driver(&mut self.reader_driver).await);
        match self.host.writer.lock().await.take() {
            Some(writer) => remember(
                &mut failure,
                writer
                    .close()
                    .await
                    .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_DRAIN_FAILED")),
            ),
            None => remember(
                &mut failure,
                Err(Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE")),
            ),
        }
        if let Some(error) = failure {
            Err(error)
        } else {
            Ok(())
        }
    }
}

fn remember(first: &mut Option<Failure>, result: Result<(), Failure>) {
    if let Err(error) = result {
        eprintln!("NATIVE_CLEANUP_FAILED {error}");
        if first.is_none() {
            *first = Some(error);
        }
    }
}

fn read_bounded(
    path: &std::path::Path,
    policy: FilePolicy,
    limit: usize,
) -> Result<zeroize::Zeroizing<Vec<u8>>, protected_files::ReadError> {
    let parent = path.parent().ok_or(protected_files::ReadError::Invalid)?;
    let name = path
        .file_name()
        .ok_or(protected_files::ReadError::Invalid)?;
    let directory = protected_files::open_directory(parent)?;
    protected_files::read_file_at(&directory, name, policy, limit)
}

#[cfg(test)]
mod driver_tests {
    use super::*;
    #[test]
    fn source_wall_clock_is_exact_for_persisted_receive_and_seal_observations() {
        let at = std::time::UNIX_EPOCH + Duration::from_nanos(123_456_789);
        let sampled = wall_clock_ns(at).unwrap();
        assert_eq!(sampled, 123_456_000);
        assert!(
            onlyalpha_domain::time::OnlyTimestamp::from_unix_nanos(sampled.into())
                .to_datetime_exact()
                .is_ok()
        );
        assert!(wall_clock_ns(std::time::UNIX_EPOCH - Duration::from_nanos(1)).is_err());
    }
    #[tokio::test(flavor = "current_thread")]
    async fn cancelled_driver_drain_retains_the_original_join_handle() {
        use std::{future::Future, task::Poll};
        let (release, wait) = tokio::sync::oneshot::channel::<()>();
        let (finished, completion) = tokio::sync::oneshot::channel();
        let mut driver = Some(tokio::spawn(async move {
            wait.await.unwrap();
            let _ = finished.send(());
            Ok(())
        }));
        {
            let mut closing = Box::pin(drain_driver(&mut driver));
            let first = std::future::poll_fn(|cx| Poll::Ready(closing.as_mut().poll(cx))).await;
            assert!(first.is_pending());
        }
        release.send(()).unwrap();
        completion.await.unwrap();
        let retained = driver.is_some();
        if let Some(driver) = driver.take() {
            driver.await.unwrap().unwrap();
        }
        assert!(retained, "cancelled drain detached the original driver");
    }
    #[tokio::test(flavor = "current_thread")]
    async fn actual_driver_completion_and_panic_withdraw_admission() {
        let (sender, mut observer) = tokio::sync::watch::channel(true);
        assert!(driver_active(&observer));
        let driver = tokio::spawn(async move {
            sender.send_replace(false);
        });
        observer.changed().await.unwrap();
        driver.await.unwrap();
        assert!(!driver_active(&observer));
        let (sender, mut observer) = tokio::sync::watch::channel(true);
        let driver = tokio::spawn(async move {
            let _retained = sender;
            panic!("controlled driver failure")
        });
        assert!(driver.await.is_err());
        assert!(observer.changed().await.is_err());
        assert!(!driver_active(&observer));
    }
}
