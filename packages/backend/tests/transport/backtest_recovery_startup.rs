//! Technical cold worker fixture: actual startup Infrastructure, no background scan.
use super::*;
use std::path::Path;

#[path = "../../src/tests/support/job_publication_proxy.rs"]
pub(crate) mod publication_fault;

pub(crate) struct FaultedBacktestOwner<'a> {
    pub(crate) database: &'a Database,
    pub(crate) user_data: &'a Path,
    pub(crate) schema: &'a Path,
}

impl FaultedBacktestOwner<'_> {
    pub(crate) async fn open(
        &self,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
        mode: publication_fault::Mode,
    ) -> Result<
        (
            ResearchConnection,
            crate::workers::research::SharedAuthority,
            publication_fault::Proxy,
        ),
        Failure,
    > {
        if self.database.postgres_database != "onlyalpha_dev_validation_test" {
            return Err(Failure::unavailable("TEST_DATABASE_REQUIRED"));
        }
        let (pg, upstream) = postgres_socket(self.database, false).await?;
        let upstream = upstream
            .into_std()
            .map_err(|_| Failure::unavailable("POSTGRES_UNAVAILABLE"))?;
        upstream
            .set_nonblocking(false)
            .map_err(|_| Failure::unavailable("POSTGRES_UNAVAILABLE"))?;
        let fault = publication_fault::Proxy::forward(mode, upstream);
        let stream = TcpStream::connect((std::net::Ipv4Addr::LOCALHOST, fault.port()))
            .await
            .map_err(|_| Failure::unavailable("POSTGRES_UNAVAILABLE"))?;
        let socket = postgres_session(pg, stream, false).await?;
        let (connection, writer) = open_owner(
            self.user_data,
            self.schema,
            self.database,
            namespace,
            socket,
            "BACKTEST_FAULT_OWNER_PID",
        )
        .await?;
        Ok((connection, writer, fault))
    }
}

pub(crate) async fn open(
    config: &Configuration,
    namespace: &crate::bootstrap::deployment::SemanticStoreId,
) -> Result<
    (
        ResearchConnection,
        crate::workers::research::SharedAuthority,
    ),
    Failure,
> {
    let database = Database::from(config);
    let socket = connect(&database, false).await?;
    open_owner(
        &config.user_data,
        &config.schema,
        &database,
        namespace,
        socket,
        "BACKTEST_OWNER_PID",
    )
    .await
}

async fn open_owner(
    user_data: &Path,
    schema: &Path,
    database: &Database,
    namespace: &crate::bootstrap::deployment::SemanticStoreId,
    mut socket: PendingRead,
    pid_label: &str,
) -> Result<(ResearchConnection, crate::workers::research::SharedAuthority), Failure> {
    let inputs = StorageInputs::load(
        StorageRoots::open(user_data).map_err(|e| Failure::unavailable(e.code()))?,
        schema,
        WORK,
    )
    .map_err(|e| Failure::unavailable(e.code()))?;
    if inputs.namespace() != namespace {
        return Err(Failure::unavailable("RESEARCH_SEMANTIC_STORE_MISMATCH"));
    }
    let live = socket.alive.clone();
    let mut writer =
        AuthoritySession::acquire(socket.client.take().unwrap(), socket.driver.take().unwrap())
            .await
            .map_err(|e| Failure::unavailable(e.code()))?;
    inputs
        .verify(
            writer
                .client_mut()
                .await
                .map_err(|e| Failure::unavailable(e.code()))?,
            ROWS,
        )
        .await
        .map_err(|e| Failure::unavailable(e.code()))?;
    writer
        .verify()
        .await
        .map_err(|e| Failure::unavailable(e.code()))?;
    if crate::bootstrap::research_namespace::open_manual_backtest_existing(user_data)
        .map_err(Failure::unavailable)?
        != *namespace
    {
        return Err(Failure::unavailable("RESEARCH_SEMANTIC_STORE_MISMATCH"));
    }
    crate::persistence::research_runtime::Registry::open_existing(&user_data.join("runtime"))
        .map_err(Failure::unavailable)?;
    let pid = writer
        .client_mut()
        .await
        .map_err(|e| Failure::unavailable(e.code()))?
        .query_one("SELECT pg_catalog.pg_backend_pid()", &[])
        .await
        .map_err(|_| Failure::unavailable("POSTGRES_UNAVAILABLE"))?
        .get(0);
    println!("{pid_label} {pid}");
    let connection = database.research_connection(namespace, pid, live).await?;
    Ok((connection, Arc::new(Mutex::new(Some(writer)))))
}

/// An independently owned reader, preserving the original writer lifecycle.
pub(crate) async fn facts(reference:&ResearchConnection) -> Result<ResearchConnection,Failure> {
    let mut config:tokio_postgres::Config=std::env::var("ONLYALPHA_POSTGRES_DSN").map_err(|_|Failure::unavailable("TEST_DATABASE_REQUIRED"))?.parse().map_err(|_|Failure::unavailable("TEST_DATABASE_REQUIRED"))?;
    if config.get_dbname()!=Some("onlyalpha_dev_validation_test") {return Err(Failure::unavailable("TEST_DATABASE_REQUIRED"));}
    config.user("onlyalpha_node_test");
    config.options("-c default_transaction_read_only=on -c search_path=pg_catalog,public,pg_temp");
    let (client,driver)=config.connect(NoTls).await.map_err(|_|Failure::unavailable("TEST_READER_UNAVAILABLE"))?;
    let (alive,observed)=tokio::sync::watch::channel(true);
    let driver=tokio::spawn(async move {let result=driver.await;alive.send_replace(false);result});
    let mut connection=ResearchConnection {owned:PendingRead {client:Some(client),driver:Some(driver),alive:observed},namespace:reference.namespace.clone(),writer_pid:reference.writer_pid,writer_live:reference.writer_live.clone()};
    let client=connection.client_mut().await?;
    client.batch_execute("SET ROLE onlyalpha_job_reader").await.map_err(|_|Failure::unavailable("TEST_READER_UNAVAILABLE"))?;
    crate::persistence::job_publication::role(client,&["onlyalpha_job_reader"]).await.map_err(|_|Failure::unavailable("TEST_READER_UNAVAILABLE"))?;
    Ok(connection)
}

/// Technical Research scheduler fixture: actual ordinary Node sockets and
/// drivers, without asserting that a complete Shipping Host is READY.
pub(crate) async fn research(
    namespace:&crate::bootstrap::deployment::SemanticStoreId,
) -> Result<(ResearchConnection,crate::workers::research::SharedAuthority),Failure> {
    let mut config:tokio_postgres::Config=std::env::var("ONLYALPHA_POSTGRES_DSN").map_err(|_|Failure::unavailable("TEST_DATABASE_REQUIRED"))?.parse().map_err(|_|Failure::unavailable("TEST_DATABASE_REQUIRED"))?;
    if config.get_dbname()!=Some("onlyalpha_dev_validation_test") {return Err(Failure::unavailable("TEST_DATABASE_REQUIRED"));}
    config.user("onlyalpha_node_test");
    config.options("-c search_path=pg_catalog,public,pg_temp");
    let (client,driver)=config.connect(NoTls).await.map_err(|_|Failure::unavailable("TEST_WRITER_UNAVAILABLE"))?;
    let (alive,writer_live)=tokio::sync::watch::channel(true);
    let driver=tokio::spawn(async move {let result=driver.await;alive.send_replace(false);result});
    let mut writer=AuthoritySession::acquire(client,driver).await.map_err(|e|Failure::unavailable(e.code()))?;
    let client=writer.client_mut().await.map_err(|e|Failure::unavailable(e.code()))?;
    crate::persistence::node_access::verify(client,"onlyalpha_node_test").await.map_err(Failure::unavailable)?;
    crate::bootstrap::deployment::verify_binding(client,namespace).await.map_err(|_|Failure::unavailable("SEMANTIC_STORE_BINDING_MISMATCH"))?;
    let pid=client.query_one("SELECT pg_backend_pid()",&[]).await.map_err(|_|Failure::unavailable("TEST_WRITER_UNAVAILABLE"))?.get(0);
    config.options("-c default_transaction_read_only=on -c search_path=pg_catalog,public,pg_temp");
    let (client,driver)=config.connect(NoTls).await.map_err(|_|Failure::unavailable("TEST_READER_UNAVAILABLE"))?;
    let (alive,observed)=tokio::sync::watch::channel(true);
    let driver=tokio::spawn(async move {let result=driver.await;alive.send_replace(false);result});
    let mut metadata=ResearchConnection {owned:PendingRead {client:Some(client),driver:Some(driver),alive:observed},namespace:namespace.clone(),writer_pid:pid,writer_live};
    metadata.client_mut().await?;
    Ok((metadata,Arc::new(Mutex::new(Some(writer)))))
}
