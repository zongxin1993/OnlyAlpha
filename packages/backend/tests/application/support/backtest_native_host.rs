//! Technical entry into the unchanged Shipping startup and HTTP owners.
//! This starts no alternate Backtest authority and never accepts a Work/grant DTO.
use onlyalpha_backend::{bootstrap::workstation_startup::{Configuration,Running},
    persistence::market_data::ClickHouseConfig,transport::endpoint::Transport};
use serde_json::Value;
use std::{error::Error,io::{self,Read,Write},path::PathBuf,time::Duration};
fn field<'a>(v:&'a Value,name:&str)->Result<&'a str,Box<dyn Error>> {v[name].as_str().ok_or_else(||format!("missing {name}").into())}
fn path(v:&Value,name:&str)->Result<PathBuf,Box<dyn Error>> {
    let p=PathBuf::from(field(v,name)?);if !p.is_absolute(){return Err("absolute selected path required".into());}Ok(p)
}
pub(super) async fn serve()->Result<(),Box<dyn Error>> {
    let mut raw=String::new();io::stdin().take(131073).read_to_string(&mut raw)?;
    if raw.len()>131072{return Err("probe frame bound".into());}
    let v:Value=serde_json::from_str(&raw)?;
    if v.as_object().is_none_or(|m|m.len()!=9)||v["schema_version"]!=1{return Err("explicit Host configuration required".into());}
    let dsn=std::env::var("ONLYALPHA_POSTGRES_DSN")?;
    let pg:tokio_postgres::Config=dsn.parse()?;
    if !pg.get_dbname().is_some_and(|n|n.ends_with("_test")){return Err("canonical test database required".into());}
    let database=field(&v,"clickhouse_database")?;
    if !database.starts_with("onlyalpha_test_"){return Err("canonical ClickHouse namespace required".into());}
    let config=Configuration{user_data:path(&v,"user_data")?,schema:path(&v,"schema")?,assets:path(&v,"assets")?,
        algorithms:path(&v,"algorithms")?,algorithm_artifact:field(&v,"algorithm_artifact")?.into(),trust:path(&v,"source_trust")?,
        postgres_peer:field(&v,"postgres_peer")?.parse()?,postgres_user:pg.get_user().ok_or("postgres user")?.into(),
        postgres_database:pg.get_dbname().ok_or("postgres database")?.into(),postgres_dsn:dsn,
        clickhouse:ClickHouseConfig{url:std::env::var("ONLYALPHA_TEST_CLICKHOUSE_URL")?,database:database.into(),
            user:std::env::var("ONLYALPHA_TEST_CLICKHOUSE_USER")?,password:std::env::var("ONLYALPHA_TEST_CLICKHOUSE_PASSWORD")?,
            timeout:Duration::from_secs(5),tls_roots_pem:vec![],max_bytes:64*1024*1024,max_rows:100000},
        transport:Transport::Loopback{port:5173},listen:"127.0.0.1:5173".parse()?};
    // Register the real shutdown stream before startup, as the Shipping main does.
    let mut term=tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    let mut interrupt=tokio::signal::unix::signal(tokio::signal::unix::SignalKind::interrupt())?;
    let (stop,shutdown)=tokio::sync::watch::channel(false);
    let signal=tokio::spawn(async move {tokio::select!{_=term.recv()=>{},_=interrupt.recv()=>{}}stop.send_replace(true);});
    let result=async {
        let listener=tokio::net::TcpListener::bind(config.listen).await?;
        let running=Running::open(config,&shutdown).await?;
        println!("BACKTEST_NATIVE_HOST_READY");io::stdout().flush()?;
        running.serve(listener,shutdown).await?;Ok::<_,Box<dyn Error>>(())
    }.await;
    signal.abort();let _=signal.await;result
}
