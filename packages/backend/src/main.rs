//! Actual native Shipping executable. Contract export is pure and starts no owner.
use onlyalpha_backend::bootstrap::workstation_startup::{Configuration, Running};
use onlyalpha_backend::persistence::market_data::ClickHouseConfig;
use onlyalpha_backend::transport::endpoint::Transport;
use onlyalpha_backend::transport::routes;
use std::{
    net::{IpAddr, SocketAddr},
    path::PathBuf,
    time::Duration,
};
fn required(name: &str) -> Result<String, &'static str> {
    std::env::var(name)
        .ok()
        .filter(|s| !s.is_empty())
        .ok_or("NATIVE_CONFIGURATION_REQUIRED")
}
fn algorithm_artifact() -> Result<String, &'static str> {
    match (
        std::env::var_os("ONLYALPHA_NATIVE_ALGORITHM_ARTIFACT"),
        std::env::var_os("ONLYALPHA_NATIVE_ALGORITHM_ARTIFACT_FILE"),
    ) {
        (Some(value), None) => {
            onlyalpha_backend::bootstrap::configuration::parse_algorithm_artifact(
                value
                    .to_str()
                    .ok_or("ALGORITHM_ARTIFACT_INVALID")?
                    .as_bytes(),
            )
            .map_err(|_| "ALGORITHM_ARTIFACT_INVALID")
        }
        (None, Some(path)) => onlyalpha_backend::bootstrap::configuration::load_algorithm_artifact(
            std::path::Path::new(&path),
        )
        .map_err(|_| "ALGORITHM_ARTIFACT_INVALID"),
        _ => Err("ALGORITHM_ARTIFACT_CONFIGURATION_INVALID"),
    }
}
fn configuration(user_data: PathBuf) -> Result<Configuration, &'static str> {
    if required("ONLYALPHA_NATIVE_DEPLOYMENT")? != "CONTAINED_DEVELOPMENT" {
        return Err("NATIVE_DEPLOYMENT_DENIED");
    }
    let local: IpAddr = required("ONLYALPHA_NATIVE_LOCAL_ADDRESS")?
        .parse()
        .map_err(|_| "DEV_TRANSPORT_ATTESTATION_INVALID")?;
    let gateway = required("ONLYALPHA_NATIVE_GATEWAY")?
        .parse()
        .map_err(|_| "DEV_TRANSPORT_ATTESTATION_INVALID")?;
    let publication = required("ONLYALPHA_NATIVE_PUBLICATION")?
        .parse()
        .map_err(|_| "DEV_TRANSPORT_ATTESTATION_INVALID")?;
    let transport = if local == IpAddr::from([127, 0, 0, 1])
        && gateway == local
        && publication == SocketAddr::from(([127, 0, 0, 1], 5173))
    {
        Transport::Loopback { port: 5173 }
    } else {
        Transport::contained(local, gateway, publication)?
    };
    // Only the explicitly admitted loopback and exact gateway-facing interface
    // pass the physical accept gate, including the in-container health client.
    let listen = SocketAddr::new(
        if local.is_loopback() {
            local
        } else {
            IpAddr::from([0, 0, 0, 0])
        },
        5173,
    );
    Ok(Configuration {
        user_data,
        schema: PathBuf::from(required("ONLYALPHA_NATIVE_SCHEMA")?),
        assets: PathBuf::from(required("ONLYALPHA_NATIVE_WEB_ASSETS")?),
        algorithms: PathBuf::from(required("ONLYALPHA_NATIVE_ALGORITHMS")?),
        algorithm_artifact: algorithm_artifact()?,
        trust: PathBuf::from(required("ONLYALPHA_NATIVE_SOURCE_TRUST")?),
        postgres_dsn: required("ONLYALPHA_POSTGRES_DSN")?,
        postgres_peer: required("ONLYALPHA_NATIVE_POSTGRES_PEER")?
            .parse()
            .map_err(|_| "DEV_POSTGRES_TRANSPORT_DENIED")?,
        postgres_user: required("ONLYALPHA_NATIVE_POSTGRES_USER")?,
        postgres_database: required("ONLYALPHA_NATIVE_POSTGRES_DATABASE")?,
        clickhouse: ClickHouseConfig {
            url: required("ONLYALPHA_CLICKHOUSE_URL")?,
            database: required("ONLYALPHA_CLICKHOUSE_DATABASE")?,
            user: required("ONLYALPHA_CLICKHOUSE_USER")?,
            password: required("ONLYALPHA_CLICKHOUSE_PASSWORD")?,
            timeout: Duration::from_secs(5),
            tls_roots_pem: vec![],
            max_bytes: 64 * 1024 * 1024,
            max_rows: 100000,
        },
        transport,
        listen,
    })
}
#[tokio::main(flavor = "current_thread")]
async fn main() {
    if let Err(code) = run().await {
        eprintln!("{code}");
        std::process::exit(1);
    }
}
/// Explicit contained operator connection. Unlike normal Shipping startup,
/// this command needs no Web, algorithms or market-data services. NoTls is used
/// only when the operator's DSN explicitly selects Disable; Prefer/Require are
/// rejected rather than downgraded. All errors are credential-safe codes.
async fn operator_postgres() -> Result<
    (
        tokio_postgres::Client,
        tokio::task::JoinHandle<Result<(), tokio_postgres::Error>>,
    ),
    String,
> {
    let dsn = zeroize::Zeroizing::new(required("ONLYALPHA_POSTGRES_DSN").map_err(str::to_owned)?);
    let mut pg: tokio_postgres::Config = dsn
        .as_str()
        .parse()
        .map_err(|_| "POSTGRES_CONFIGURATION_INVALID".to_owned())?;
    if pg.get_ssl_mode() != tokio_postgres::config::SslMode::Disable {
        return Err("OPERATOR_POSTGRES_TRANSPORT_DENIED".into());
    }
    pg.connect_timeout(Duration::from_secs(5))
        .options("-c search_path=pg_catalog,public,pg_temp");
    let (client, connection) =
        tokio::time::timeout(Duration::from_secs(5), pg.connect(tokio_postgres::NoTls))
            .await
            .map_err(|_| "POSTGRES_UNAVAILABLE".to_owned())?
            .map_err(|_| "POSTGRES_UNAVAILABLE".to_owned())?;
    Ok((client, tokio::spawn(connection)))
}

async fn namespace_operator_session()
-> Result<onlyalpha_backend::persistence::authority_session::AuthoritySession, String> {
    use onlyalpha_backend::persistence::authority_session::AuthoritySession;
    let (client, connection) = operator_postgres().await?;
    AuthoritySession::acquire(client, connection)
        .await
        .map_err(|e| e.code().to_owned())
}
async fn extend_research_namespace(
    root: &std::path::Path,
    manual_backtest: bool,
) -> Result<onlyalpha_backend::bootstrap::deployment::SemanticStoreId, String> {
    let mut session = namespace_operator_session().await?;
    let result = if manual_backtest {
        onlyalpha_backend::bootstrap::research_namespace::extend_manual_backtest(root, &mut session)
            .await
    } else {
        onlyalpha_backend::bootstrap::research_namespace::extend_strategy(root, &mut session).await
    }
    .map_err(str::to_owned);
    let closed = session.close().await.map_err(|e| e.code().to_owned());
    match (result, closed) {
        (Err(code), _) => Err(code),
        (Ok(identity), Ok(())) => Ok(identity),
        (_, Err(code)) => Err(code),
    }
}

async fn initialize_runtime_registry(
    root: &std::path::Path,
    schema: &std::path::Path,
) -> Result<serde_json::Value, String> {
    let schema =
        onlyalpha_backend::bootstrap::configuration::load_schema_history(schema, 8 * 1024 * 1024)
            .map_err(|error| error.code().to_owned())?;
    let mut session = namespace_operator_session().await?;
    let result = onlyalpha_backend::bootstrap::research_namespace::initialize_runtime_registry(
        root,
        &schema,
        &mut session,
    )
    .await
    .map_err(str::to_owned);
    let closed = session
        .close()
        .await
        .map_err(|error| error.code().to_owned());
    runtime_initialization_reply(result, closed)
}
fn runtime_initialization_reply(
    result: Result<serde_json::Value, String>,
    closed: Result<(), String>,
) -> Result<serde_json::Value, String> {
    match (result, closed) {
        (Err(code), _) => Err(code),
        (Ok(mut value), Ok(())) => {
            value["schema_version"] = serde_json::json!(1);
            Ok(value)
        }
        (_, Err(_)) => Err("RESEARCH_RUNTIME_INITIALIZATION_OUTCOME_UNKNOWN".into()),
    }
}

async fn initialize_backtest_evidence(
    root: &std::path::Path,
    schema: &std::path::Path,
) -> Result<serde_json::Value, String> {
    let schema =
        onlyalpha_backend::bootstrap::configuration::load_schema_history(schema, 8 * 1024 * 1024)
            .map_err(|error| error.code().to_owned())?;
    let mut session = namespace_operator_session().await?;
    let result = onlyalpha_backend::bootstrap::research_namespace::initialize_backtest_evidence(
        root,
        &schema,
        &mut session,
    )
    .await
    .map_err(str::to_owned);
    let closed = session
        .close()
        .await
        .map_err(|error| error.code().to_owned());
    backtest_evidence_initialization_reply(result, closed)
}
fn backtest_evidence_initialization_reply(
    result: Result<serde_json::Value, String>,
    closed: Result<(), String>,
) -> Result<serde_json::Value, String> {
    match (result, closed) {
        (Err(code), _) => Err(code),
        (Ok(mut value), Ok(())) => {
            value["schema_version"] = serde_json::json!(1);
            Ok(value)
        }
        (_, Err(_)) => Err("BACKTEST_EVIDENCE_INITIALIZATION_OUTCOME_UNKNOWN".into()),
    }
}

async fn run() -> Result<(), String> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if let [command, schema] = args.as_slice()
        && command == "--migrate-postgres-schema"
    {
        let schema = onlyalpha_backend::bootstrap::configuration::load_schema_history(
            std::path::Path::new(schema),
            8 * 1024 * 1024,
        )
        .map_err(|error| error.code().to_owned())?;
        let (mut client, connection) = operator_postgres().await?;
        let result = schema.migrate(&mut client).await;
        drop(client);
        let closed = connection.await;
        let applied = result.map_err(|error| error.code().to_owned())?;
        if !matches!(closed, Ok(Ok(()))) {
            return Err("POSTGRES_MIGRATION_OUTCOME_UNKNOWN".into());
        }
        println!("{}", serde_json::json!({"applied": applied}));
        return Ok(());
    }
    if let [command, root, schema] = args.as_slice()
        && command == "--initialize-research-deployment"
    {
        let schema = onlyalpha_backend::bootstrap::configuration::load_schema_history(
            std::path::Path::new(schema),
            8 * 1024 * 1024,
        )
        .map_err(|error| error.code().to_owned())?;
        let mut session = namespace_operator_session().await?;
        let result = onlyalpha_backend::bootstrap::research_namespace::initialize_deployment(
            std::path::Path::new(root),
            &schema,
            &mut session,
        )
        .await;
        let closed = session.close().await;
        let id = result.map_err(str::to_owned)?;
        closed.map_err(|_| "RESEARCH_DEPLOYMENT_BINDING_OUTCOME_UNKNOWN".to_owned())?;
        println!(
            "{}",
            serde_json::json!({"schema_version": 1, "semantic_store_id": id.value()})
        );
        return Ok(());
    }
    if let [command, root, schema] = args.as_slice()
        && command == "--initialize-fresh-backtest-evidence"
    {
        let value =
            initialize_backtest_evidence(std::path::Path::new(root), std::path::Path::new(schema))
                .await?;
        println!("{value}");
        return Ok(());
    }
    if let [command, root, schema] = args.as_slice()
        && command == "--initialize-fresh-runtime-registry"
    {
        let value =
            initialize_runtime_registry(std::path::Path::new(root), std::path::Path::new(schema))
                .await?;
        println!("{value}");
        return Ok(());
    }

    if let [command, database] = args.as_slice()
        && matches!(
            command.as_str(),
            "--initialize-test-clickhouse" | "--drop-test-clickhouse"
        )
    {
        let client =
            onlyalpha_backend::persistence::market_data::ClickHouse::new(ClickHouseConfig {
                url: required("ONLYALPHA_TEST_CLICKHOUSE_URL")?,
                database: database.clone(),
                user: required("ONLYALPHA_TEST_CLICKHOUSE_USER")?,
                password: required("ONLYALPHA_TEST_CLICKHOUSE_PASSWORD")?,
                timeout: Duration::from_secs(5),
                tls_roots_pem: vec![],
                max_bytes: 1024 * 1024,
                max_rows: 100,
            })
            .map_err(|e| e.code().to_owned())?;
        if command == "--initialize-test-clickhouse" {
            let applied = client
                .initialize_test_schema(&required("ONLYALPHA_TEST_CLICKHOUSE_STORAGE_POLICY")?)
                .await
                .map_err(|e| e.code().to_owned())?;
            println!(
                "{}",
                serde_json::json!({"schema_version":1,"database":database,"applied":applied})
            );
        } else {
            client
                .drop_test_database()
                .await
                .map_err(|e| e.code().to_owned())?;
            println!(
                "{}",
                serde_json::json!({"schema_version":1,"database":database,"dropped":true})
            );
        }
        return Ok(());
    }
    if let [command, root] = args.as_slice() {
        if matches!(
            command.as_str(),
            "--extend-strategy-research-namespace" | "--extend-manual-backtest-namespace"
        ) {
            let identity = extend_research_namespace(
                std::path::Path::new(root),
                command == "--extend-manual-backtest-namespace",
            )
            .await?;
            println!(
                "{}",
                serde_json::json!({"schema_version":1,"semantic_store_id":identity.value()})
            );
            return Ok(());
        }
    }
    if args.len() == 2
        && matches!(
            args[0].as_str(),
            "--initialize-fresh-research-namespace" | "--verify-research-namespace"
        )
    {
        let root = std::path::Path::new(&args[1]);
        let identity = if args[0] == "--initialize-fresh-research-namespace" {
            onlyalpha_backend::bootstrap::research_namespace::initialize_fresh(root)
        } else {
            onlyalpha_backend::bootstrap::research_namespace::open_existing(root)
        }
        .map_err(str::to_owned)?;
        println!(
            "{}",
            serde_json::json!({"schema_version":1,"semantic_store_id":identity.value(),
            "profile":onlyalpha_backend::bootstrap::research_namespace::profile(),
            "policy":onlyalpha_backend::bootstrap::research_namespace::policy()})
        );
        return Ok(());
    }
    if args == ["--read-native-backtest-terminal"] {
        return onlyalpha_backend::workers::backtest_terminal::run_stdio().map_err(str::to_owned);
    }
    if args == ["--describe-research-runtime"] {
        println!(
            "{}",
            onlyalpha_backend::workers::algorithm::describe_research_runtime(env!(
                "CARGO_PKG_VERSION"
            ))
            .map_err(|e| e.to_string())?
        );
        return Ok(());
    }
    if args == ["--describe-native-runtime"] {
        println!(
            "{}",
            onlyalpha_backend::workers::algorithm::describe_native_runtime(env!(
                "CARGO_PKG_VERSION"
            ))
            .map_err(|e| e.to_string())?
        );
        return Ok(());
    }
    if args == ["--export-websocket"] {
        println!(
            "{}",
            serde_json::to_string(&onlyalpha_backend::transport::stream_wire::document())
                .map_err(|_| "NATIVE_CONTRACT_EXPORT_FAILED")?
        );
        return Ok(());
    }
    if args == ["--export-openapi"] {
        let (_, doc) = routes::declaration();
        println!(
            "{}",
            serde_json::to_string(&doc).map_err(|_| "NATIVE_CONTRACT_EXPORT_FAILED")?
        );
        return Ok(());
    }
    let user_data = match args.as_slice() {
        [flag, root] if flag == "--user-data-root" => PathBuf::from(root),
        _ => return Err("NATIVE_ARGUMENT_INVALID".into()),
    };
    let config = configuration(user_data).map_err(String::from)?;
    let address = config.listen;
    // Register both maintained OS signal streams before any protected startup work.
    let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        .map_err(|_| "SIGNAL_UNAVAILABLE")?;
    let mut interrupt = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::interrupt())
        .map_err(|_| "SIGNAL_UNAVAILABLE")?;
    let (stop, shutdown) = tokio::sync::watch::channel(false);
    let signal = tokio::spawn(async move {
        tokio::select! {_=term.recv()=>{},_=interrupt.recv()=>{}}
        stop.send_replace(true);
    });
    let result = async {
        let listener = tokio::net::TcpListener::bind(address)
            .await
            .map_err(|_| "NATIVE_LISTENER_UNAVAILABLE".to_owned())?;
        // Never cancel/drop a cleanup-bearing startup future on signal receipt.
        let running = Running::open(config, &shutdown)
            .await
            .map_err(|e| e.to_string())?;
        eprintln!(
            "NATIVE_WORKSTATION_READY version={}",
            env!("CARGO_PKG_VERSION")
        );
        running
            .serve(listener, shutdown)
            .await
            .map_err(|e| e.to_string())
    }
    .await;
    signal.abort();
    let _ = signal.await;
    result
}

#[cfg(test)]
mod initialization_tests {
    use super::*;
    #[test]
    fn evidence_initialization_reply_never_reports_success_after_uncertain_close() {
        let value = serde_json::json!({"semantic_store_id":"22222222-2222-4222-8222-222222222222","initialized":true});
        assert_eq!(
            backtest_evidence_initialization_reply(
                Ok(value.clone()),
                Err("POSTGRES_UNAVAILABLE".into())
            )
            .unwrap_err(),
            "BACKTEST_EVIDENCE_INITIALIZATION_OUTCOME_UNKNOWN"
        );
        let success = backtest_evidence_initialization_reply(Ok(value), Ok(())).unwrap();
        assert_eq!(success["schema_version"], 1);
        assert_eq!(success["initialized"], true);
        assert_eq!(
            backtest_evidence_initialization_reply(
                Err("original failure".into()),
                Err("POSTGRES_UNAVAILABLE".into())
            )
            .unwrap_err(),
            "original failure"
        );
    }
    #[test]
    fn runtime_initialization_reply_never_reports_success_after_uncertain_close() {
        let value = serde_json::json!({"active_for_new_work":null,"states":{}});
        assert_eq!(
            runtime_initialization_reply(
                Ok(value.clone()),
                Err("PRODUCT_KERNEL_AUTHORITY_RELEASE_FAILED".into())
            ),
            Err("RESEARCH_RUNTIME_INITIALIZATION_OUTCOME_UNKNOWN".into())
        );
        assert_eq!(
            runtime_initialization_reply(Ok(value), Ok(())).unwrap(),
            serde_json::json!({"schema_version":1,"active_for_new_work":null,"states":{}})
        );
        assert_eq!(
            runtime_initialization_reply(
                Err("POSTGRES_SCHEMA_INCOMPATIBLE".into()),
                Err("PRODUCT_KERNEL_AUTHORITY_LOST".into())
            ),
            Err("POSTGRES_SCHEMA_INCOMPATIBLE".into())
        );
    }
}
