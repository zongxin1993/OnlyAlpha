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
async fn run() -> Result<(), String> {
    let args: Vec<_> = std::env::args().skip(1).collect();
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
