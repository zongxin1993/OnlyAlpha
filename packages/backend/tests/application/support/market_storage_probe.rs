//! Guarded technical DB probe. It is never a business API or a Shipping UI.
use onlyalpha_backend::persistence::market_data::*;
use onlyalpha_backend::persistence::market_data_wal::Wal;
use serde_json::{Value, json};
use std::{path::Path, time::Duration};
fn text<'a>(v: &'a Value, k: &str) -> Result<&'a str, Box<dyn std::error::Error>> {
    v[k].as_str().ok_or_else(|| format!("missing {k}").into())
}
pub async fn run(v: &Value) -> Result<Value, Box<dyn std::error::Error>> {
    let dsn = std::env::var("ONLYALPHA_POSTGRES_DSN")?;
    let config: tokio_postgres::Config = dsn.parse()?;
    if !config.get_dbname().is_some_and(|n| n.ends_with("_test")) {
        return Err("test DSN required".into());
    }
    let (client, connection) = tokio_postgres::connect(&dsn, tokio_postgres::NoTls).await?;
    let driver = tokio::spawn(connection);
    let op = text(v, "op")?;
    if op == "lease-start" || op == "lease-busy" {
        let lease = ExecutionLease::acquire(client, driver, text(v, "id")?).await?;
        if op == "lease-busy" {
            let (c, conn) = tokio_postgres::connect(&dsn, tokio_postgres::NoTls).await?;
            let second = ExecutionLease::acquire(c, tokio::spawn(conn), text(v, "id")?).await;
            if !matches!(second, Err(Error::Busy)) {
                return Err("second lease accepted".into());
            }
        }
        let (c, conn) = tokio_postgres::connect(&dsn, tokio_postgres::NoTls).await?;
        let business_driver = tokio::spawn(conn);
        let mut session =
            onlyalpha_backend::persistence::authority_session::AuthoritySession::acquire(
                c,
                business_driver,
            )
            .await?;
        let result = Catalog::new(session.client_mut().await?, 10_000, 32 * 1024 * 1024)?
            .start_attempt(&lease, text(v, "at")?)
            .await?;
        lease.close().await?;
        session.close().await?;
        return Ok(result.to_record());
    }
    let mut session = onlyalpha_backend::persistence::authority_session::AuthoritySession::acquire(
        client, driver,
    )
    .await?;
    let bytes = v["max_bytes"].as_u64().unwrap_or(32 * 1024 * 1024) as usize;
    let catalog = Catalog::new(session.client_mut().await?, 10_000, bytes)?;
    let db = text(v, "database")?;
    if !db.starts_with("onlyalpha_test_") {
        return Err("test CH namespace required".into());
    }
    let url = text(v, "url")?.to_owned();
    let ch = ClickHouse::new(ClickHouseConfig {
        url,
        database: db.into(),
        user: std::env::var("ONLYALPHA_CLICKHOUSE_USER").unwrap_or("default".into()),
        password: std::env::var("ONLYALPHA_CLICKHOUSE_PASSWORD").unwrap_or_default(),
        timeout: Duration::from_secs(5),
        tls_roots_pem: vec![],
        max_bytes: 32 * 1024 * 1024,
        max_rows: 10_000,
    })?;
    ch.assert_server().await?;
    let mut store = Storage::new(catalog, &ch, 10_000)?;
    let result = match op {
        "intent" => {
            let scope = Scope::from_record(&v["scope"])?;
            store
                .catalog()
                .admit_intent(&AcquisitionIntent::build(
                    scope,
                    text(v, "provenance")?,
                    text(v, "binding")?,
                    text(v, "at")?,
                )?)
                .await?
                .to_record()
        }
        "intent-load" => store
            .catalog()
            .intent(text(v, "id")?)
            .await?
            .map(|i| i.to_record())
            .unwrap_or(Value::Null),
        "attempt" => store
            .catalog()
            .latest_attempt(text(v, "id")?)
            .await?
            .map(|i| i.to_record())
            .unwrap_or(Value::Null),
        "failure" => {
            let a = store
                .catalog()
                .latest_attempt(text(v, "id")?)
                .await?
                .ok_or("attempt missing")?;
            store
                .catalog()
                .record_failure(&a, text(v, "detail")?, text(v, "at")?)
                .await?
                .to_record()
        }
        "complete" => {
            let a = store
                .catalog()
                .latest_attempt(text(v, "id")?)
                .await?
                .ok_or("attempt missing")?;
            store
                .complete_acquisition(
                    &a,
                    text(v, "revision_id")?,
                    text(v, "detail")?,
                    text(v, "at")?,
                )
                .await?
                .to_record()
        }
        "segment" => {
            let (s, p) = store.catalog().segment(text(v, "id")?).await?;
            json!({"segment":s.to_record(),"proof":p.to_record()})
        }
        "compose" => {
            let scope = Scope::from_record(&v["scope"])?;
            let selected: Vec<(String, String)> = serde_json::from_value(v["refs"].clone())?;
            let (manifest, revision) = store
                .commit_scope(
                    &scope,
                    &selected,
                    RevisionPublication {
                        parent: None,
                        reason: "BACKFILL",
                        at: text(v, "at")?,
                    },
                )
                .await?;
            json!({"manifest":manifest.to_record(),"revision":revision.map(|r|r.revision())})
        }
        "latest" => {
            let (revision, facts) = store.read_latest(&Scope::from_record(&v["scope"])?).await?;
            json!({"revision":revision.revision(),"facts":facts})
        }
        "read" => {
            let (r, facts) = store.read_exact(text(v, "id")?).await?;
            json!({"revision":r.revision(),"manifest":r.manifest().to_record(),"seal":r.seal(),"facts":facts})
        }
        "range" => {
            let scope = Scope::from_record(&v["scope"])?;
            let intervals = v["intervals"]
                .as_array()
                .ok_or("intervals")?
                .iter()
                .map(|v| Ok((v[0].as_i64().ok_or("start")?, v[1].as_i64().ok_or("end")?)))
                .collect::<Result<Vec<_>, Box<dyn std::error::Error>>>()?;
            let r = store.read_range(&scope, &intervals).await?;
            json!({"status":r.coverage_status.as_str(),"facts":r.facts,"evidence":r.evidence,"gaps":r.gaps,"issues":r.issues,"expected":r.expected_base_fact_count,"complete_intervals":r.complete_interval_count})
        }
        "drain-record" => drain_with_active_recorder(&mut store, v).await?,
        "drain" => {
            let wal = Wal::new(Path::new(text(v, "root")?), 32 * 1024 * 1024)?;
            let scope = v
                .get("scope")
                .filter(|v| !v.is_null())
                .map(Scope::from_record)
                .transpose()?;
            let ids = v["ids"]
                .as_array()
                .ok_or("ids")?
                .iter()
                .map(|v| v.as_str().map(str::to_owned).ok_or("id"))
                .collect::<Result<Vec<_>, _>>()?;
            let stop = v["stop"].as_str().unwrap_or("");
            let r = store
                .drain(
                    &mut wal.sealed_handle()?,
                    &ids,
                    scope.as_ref(),
                    RevisionPublication {
                        parent: None,
                        reason: v["reason"].as_str().unwrap_or("BACKFILL"),
                        at: text(v, "at")?,
                    },
                    |b| format!("{b:?}") != stop,
                )
                .await?;
            json!({"manifest":r.coverage.map(|m|m.to_record()),"revision":r.revision.as_ref().map(SealedRevision::revision),"seal":r.revision.map(|r|r.seal())})
        }
        "recover" => {
            let mut wal = Wal::new(Path::new(text(v, "root")?), 32 * 1024 * 1024)?;
            let r = store
                .recover(&mut wal, v["startup"] == true, text(v, "at")?, |_| true)
                .await?;
            json!({"count":r.len()})
        }
        _ => return Err("unknown op".into()),
    };
    session.close().await?;
    Ok(result)
}

async fn drain_with_active_recorder(
    store: &mut Storage<'_>,
    v: &Value,
) -> Result<Value, Box<dyn std::error::Error>> {
    use std::{
        future::Future,
        io::{Read, Write},
        os::unix::net::UnixListener,
        pin::Pin,
        task::Poll,
    };
    let root = Path::new(text(v, "root")?);
    let mut wal = Wal::new(root, 32 * 1024 * 1024)?;
    let mut sealed = wal.sealed_handle()?;
    wal.create_segment("live", text(v, "at")?)?;
    let live = v["live_bundle"].to_string();
    wal.append(&live)?;
    let listener = UnixListener::bind(root.join("recorder-control.sock"))?;
    let (signal, mut receive) = tokio::sync::oneshot::channel::<()>();
    let (acknowledge, ack) = std::sync::mpsc::sync_channel::<()>(1);
    let control = std::thread::spawn(move || -> Result<(), String> {
        let (mut socket, _) = listener.accept().map_err(|e| e.to_string())?;
        socket
            .set_read_timeout(Some(Duration::from_secs(10)))
            .map_err(|e| e.to_string())?;
        let mut byte = [0];
        socket.read_exact(&mut byte).map_err(|e| e.to_string())?;
        if byte != *b"G" {
            return Err("control token".into());
        }
        signal.send(()).map_err(|_| "recorder gone")?;
        ack.recv_timeout(Duration::from_secs(10))
            .map_err(|e| e.to_string())?;
        socket.write_all(b"A").map_err(|e| e.to_string())?;
        Ok(())
    });
    let scope = Scope::from_record(&v["scope"])?;
    let ids = v["ids"]
        .as_array()
        .ok_or("ids")?
        .iter()
        .map(|v| v.as_str().map(str::to_owned).ok_or("id"))
        .collect::<Result<Vec<_>, _>>()?;
    let mut draining = Box::pin(store.drain(
        &mut sealed,
        &ids,
        Some(&scope),
        RevisionPublication {
            parent: None,
            reason: "BACKFILL",
            at: text(v, "at")?,
        },
        |_| true,
    ));
    let mut appended = false;
    let result = std::future::poll_fn(|cx| {
        if !appended {
            match Pin::new(&mut receive).poll(cx) {
                Poll::Ready(Ok(())) => {
                    if wal.append(&live).is_err() {
                        return Poll::Ready(Err(Error::Unprovable));
                    }
                    appended = true;
                    if acknowledge.send(()).is_err() {
                        return Poll::Ready(Err(Error::Unavailable));
                    }
                }
                Poll::Ready(Err(_)) => return Poll::Ready(Err(Error::Unavailable)),
                Poll::Pending => {}
            }
        }
        draining.as_mut().poll(cx)
    })
    .await?;
    drop(draining);
    control
        .join()
        .map_err(|_| "recorder thread")?
        .map_err(|e| format!("recorder control: {e}"))?;
    if !appended {
        return Err("recorder never ran".into());
    }
    Ok(
        json!({"appended":appended,"live_open":root.join("live.open.wal").exists(),"revision":result.revision.map(|r|r.revision())}),
    )
}
