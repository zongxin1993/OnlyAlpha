//! Same actual configuration as the Shipping Host; locators never grant Work.
use crate::{
    application::command::CommandId, bootstrap::workstation_startup::Configuration,
    persistence::market_data::ClickHouseConfig, transport::endpoint::Transport,
};
use serde_json::Value;
use std::{error::Error, path::PathBuf, time::Duration};
fn field<'a>(v: &'a Value, key: &str) -> Result<&'a str, Box<dyn Error>> {
    v[key]
        .as_str()
        .ok_or_else(|| format!("missing {key}").into())
}
fn path(v: &Value, key: &str) -> Result<PathBuf, Box<dyn Error>> {
    let path = PathBuf::from(field(v, key)?);
    if !path.is_absolute() {
        return Err("absolute fixture path required".into());
    }
    Ok(path)
}
pub async fn run(scenario: &str) -> Result<(), Box<dyn Error>> {
    let frame: Value = serde_json::from_slice(&std::fs::read(std::env::var(
        "ONLYALPHA_BACKTEST_OWNER_REQUEST",
    )?)?)?;
    if frame.as_object().is_none_or(|m| m.len() != 4) {
        return Err("explicit scenario locators required".into());
    }
    let v = &frame["configuration"];
    if v.as_object().is_none_or(|m| m.len() != 9) || v["schema_version"] != 1 {
        return Err("explicit Host configuration required".into());
    }
    let dsn = std::env::var("ONLYALPHA_POSTGRES_DSN")?;
    let pg: tokio_postgres::Config = dsn.parse()?;
    if !pg.get_dbname().is_some_and(|n| n.ends_with("_test")) {
        return Err("canonical test database required".into());
    }
    let database = field(v, "clickhouse_database")?;
    if !database.starts_with("onlyalpha_test_") {
        return Err("canonical ClickHouse namespace required".into());
    }
    let config = Configuration {
        user_data: path(v, "user_data")?,
        schema: path(v, "schema")?,
        assets: path(v, "assets")?,
        algorithms: path(v, "algorithms")?,
        algorithm_artifact: field(v, "algorithm_artifact")?.into(),
        trust: path(v, "source_trust")?,
        postgres_peer: field(v, "postgres_peer")?.parse()?,
        postgres_user: pg.get_user().ok_or("postgres user")?.into(),
        postgres_database: pg.get_dbname().ok_or("postgres database")?.into(),
        postgres_dsn: dsn,
        clickhouse: ClickHouseConfig {
            url: std::env::var("ONLYALPHA_TEST_CLICKHOUSE_URL")?,
            database: database.into(),
            user: std::env::var("ONLYALPHA_TEST_CLICKHOUSE_USER")?,
            password: std::env::var("ONLYALPHA_TEST_CLICKHOUSE_PASSWORD")?,
            timeout: Duration::from_secs(5),
            tls_roots_pem: vec![],
            max_bytes: 64 * 1024 * 1024,
            max_rows: 100000,
        },
        transport: Transport::Loopback { port: 5173 },
        listen: "127.0.0.1:5173".parse()?,
    };

    let preparation = CommandId::new(field(&frame, "preparation")?)?;
    let fresh = frame["fresh"].as_str().map(CommandId::new).transpose()?;
    let external = frame["external_files"]
        .as_array()
        .ok_or("external owner paths required")?
        .iter()
        .map(|v| {
            v.as_str()
                .map(PathBuf::from)
                .ok_or("external owner path required")
        })
        .collect::<Result<Vec<_>, _>>()?;
    crate::transport::run_backtest_owner_scenario(
        config,
        &preparation,
        fresh.as_ref(),
        scenario,
        &external,
    )
    .await;
    println!("BACKTEST_OWNER_SCENARIO_CONFIRMED {scenario}");
    Ok(())
}
