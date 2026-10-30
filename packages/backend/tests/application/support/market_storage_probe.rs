//! Guarded technical DB probe. It is never a business API or a Shipping UI.
#[path = "research_execution_probe.rs"]
mod research_execution_probe;
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
    if op == "retained-source-prerequisite" {
        return retained_source_prerequisite(client, driver, v).await;
    }
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
        "dataset-materialize" | "dataset-admit" | "dataset-research" => {
            if op == "dataset-research"
                && v["phase"] == "execute"
                && v["mode"] == "node-authority-loss"
            {
                return research_execution_probe::execute_node_fence(session, v).await;
            }
            if op == "dataset-research" && v["phase"] != "submit" {
                let datasets = onlyalpha_backend::persistence::research_dataset::Store::open(
                    Path::new(text(v, "dataset_root")?),
                    512,
                    8 * 1024 * 1024,
                )?;
                let retained =
                    onlyalpha_backend::application::research_dataset::MaterializedDataset::load(
                        &datasets,
                        text(v, "materialization_id")?,
                    )?;
                return research_execution_probe::run(session.client_mut().await?, v, &retained)
                    .await;
            }
            let plan =
                onlyalpha_backend::application::research_dataset::NativeMaterializationPlan::new(
                    &v["definition"],
                    text(v, "id")?,
                    Scope::from_record(&v["scope"])?,
                    if op == "dataset-research" { 512 } else { 100 },
                )?;
            let datasets = onlyalpha_backend::persistence::research_dataset::Store::open(
                Path::new(text(v, "dataset_root")?),
                if op == "dataset-research" { 512 } else { 100 },
                8 * 1024 * 1024,
            )?;
            let result = plan
                .materialize(&mut store, &datasets, text(v, "at")?)
                .await?;
            if v["fault_after_dataset"] == true {
                std::process::exit(73);
            }
            if op == "dataset-research" {
                return research_execution_probe::run(session.client_mut().await?, v, &result)
                    .await;
            }
            if op == "dataset-admit" {
                let f = &v["factor"];
                let compiled = onlyalpha_backend::application::research_factor::compile(
                    &f["candidate"],
                    &f["draft"],
                    &f["revision"],
                )?;
                let window =
                    compiled.window(onlyalpha_backend::application::research_factor::Window {
                        start_ns: text(v, "observation_start_ns")?.parse()?,
                        end_ns: text(v, "observation_end_ns")?.parse()?,
                        bar_ns: 60_000_000_000,
                        horizon_bars: 1,
                    })?;
                let hold =
                    onlyalpha_backend::persistence::research_runtime::RuntimeInputHold::open(
                        Path::new(text(f, "runtime_root")?),
                        "research-input-fixture",
                        "research",
                        text(f, "generation")?,
                    )?;
                let installation = onlyalpha_calculation_bridge::ChartInstallation::open(
                    Path::new(text(f, "installation")?),
                    text(f, "algorithm_artifact")?,
                )?;
                let inputs = onlyalpha_backend::application::research_admission::prepare(
                    hold,
                    &installation,
                    &compiled,
                    &f["revision"],
                    &window,
                    &datasets,
                    &result,
                )?;
                inputs.verify_runtime()?;
                inputs.record().clone()
            } else {
                json!({"snapshot":result.verified().manifest(),"lineage":result.lineage()})
            }
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

// Insert only in the existing technical market_storage_probe consumer.
// Controlled prior market input: this never creates any target research business fact.
async fn retained_source_prerequisite(
    client: tokio_postgres::Client,
    driver: tokio::task::JoinHandle<Result<(), tokio_postgres::Error>>,
    v: &Value,
) -> Result<Value, Box<dyn std::error::Error>> {
    use base64::{Engine, engine::general_purpose::STANDARD};
    use onlyalpha_backend::application::{
        command::CommandId,
        integration_catalog::AuthoringCatalog,
        integration_commands::{CreateIntegration, PublishRevision},
        integration_configuration::IntegrationId,
        market_product::{Installed, Resolver},
        source_access::{Authority, Grant, Permission, Reference, Selection},
    };
    use onlyalpha_backend::persistence::{
        authority_session::AuthoritySession, integration_postgres::Integrations,
    };
    use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBarSemantic, time::OnlyTimestamp};
    use onlyalpha_integration_contract::{
        IntegrationTypeId,
        source::{Clock, Factory, SourceError, Trust},
    };
    use onlyalpha_market_data_construction::{
        OnlyConstructionIdentity, OnlyConstructionRequirement, OnlyConstructionResolutionContext,
        OnlyConstructionResolutionPlan,
    };
    use onlyalpha_plugin_binance::{spot_authoring, spot_normalize, spot_source::SpotFactory};
    use sha2::{Digest, Sha256};
    use std::{os::unix::fs::DirBuilderExt, sync::Arc};
    const WORK: usize = 64 * 1024 * 1024;
    const TYPE: &str = "binance.spot.market_data";
    const AT: &str = "2026-10-22T00:00:00Z";
    const RECEIVE: i64 = 1_792_627_200_000_000_000;
    const START_MS: i64 = 1_767_225_600_000;
    const STRIDE_MS: i64 = 900_000;
    fn sha(bytes: &[u8]) -> String {
        Sha256::digest(bytes)
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect()
    }
    fn fp(value: &Value) -> Result<String, Box<dyn std::error::Error>> {
        onlyalpha_metadata_json::fingerprint(&value.to_string(), WORK)
            .map_err(|_| "fixture identity invalid".into())
    }
    struct PriorClock;
    impl Clock for PriorClock {
        fn now_ns(&self) -> Result<i64, SourceError> {
            Ok(RECEIVE)
        }
    }
    let executable = Path::new(text(v, "selected_backend")?);
    let metadata = std::fs::symlink_metadata(executable)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err("selected native executable required".into());
    }
    let native = std::fs::read(executable)?;
    let native_sha = sha(&native);
    if native_sha != text(v, "selected_backend_sha256")? || !native.starts_with(b"\x7fELF") {
        return Err("selected native executable identity mismatch".into());
    }
    let trust = Trust::explicit_roots(vec![std::fs::read(text(v, "source_trust")?)?])?;
    let clock: Arc<dyn Clock> = Arc::new(PriorClock);
    let factory: Arc<dyn Factory> = Arc::new(SpotFactory::installed()?);
    let installed = Installed::from_executable(factory.clone(), &native)?;
    let mut session = AuthoritySession::acquire(client, driver).await?;
    let authoring = AuthoringCatalog::new(vec![
        spot_authoring(WORK).map_err(|_| "source descriptor unavailable")?,
    ])
    .map_err(|_| "source authoring unavailable")?;
    let id = IntegrationId::new(text(v, "integration_id")?)
        .map_err(|_| "invalid fixture integration")?;
    Integrations::new(session.client_mut().await?)
        .create(
            &CreateIntegration::new(
                CommandId::new(text(v, "create_command")?).map_err(|_| "invalid command")?,
                id.clone(),
                IntegrationTypeId::new(TYPE).map_err(|_| "invalid type")?,
                "受控预采集行情（离线验收前置）",
            )
            .map_err(|_| "invalid source creation")?,
            &authoring,
            AT.parse()?,
            WORK,
        )
        .await
        .map_err(|_| "source creation failed")?;
    Integrations::new(session.client_mut().await?)
        .publish_revision(
            &PublishRevision::new(
                CommandId::new(text(v, "publish_command")?).map_err(|_| "invalid command")?,
                id.clone(),
                1,
            )
            .map_err(|_| "invalid source publish")?,
            &authoring,
            AT.parse()?,
            1000,
            WORK,
        )
        .await
        .map_err(|_| "source publish failed")?;
    let snapshot = Integrations::new(session.client_mut().await?)
        .read(&id, 1000, WORK)
        .await
        .map_err(|_| "source snapshot unavailable")?
        .ok_or("missing source snapshot")?;
    let revision = snapshot
        .integration()
        .record()
        .current_revision_fingerprint
        .as_ref()
        .ok_or("missing source revision")?;
    let record = snapshot
        .history()
        .iter()
        .find(|(r, _)| r.record().revision_fingerprint == *revision)
        .ok_or("missing retained source revision")?
        .0
        .record();
    let resource = factory.create(record.configuration_document.raw(), &trust, clock.clone())?;
    let reference =
        Reference::new(id.value(), revision, Some(TYPE)).map_err(|_| "invalid source reference")?;
    let selection = Selection::new(
        reference.clone(),
        &resource.identity().source_id,
        &resource.identity().environment,
    )
    .map_err(|_| "invalid source selection")?;
    let token = "e".repeat(64);
    let authority = Authority::new(
        "local-developer",
        &sha(token.as_bytes()),
        vec![
            Grant::new(selection, vec![Permission::ClosedHistory])
                .map_err(|_| "invalid source grant")?,
        ],
    )
    .map_err(|_| "invalid source authority")?;
    let access = authority
        .authenticate(&format!("Bearer {token}"))
        .map_err(|_| "source authentication failed")?;
    let resolver = Resolver::new(vec![installed], trust, clock)?;
    let resolved = resolver.resolve(&snapshot, &reference, &access, None)?;
    let descriptor: Value = serde_json::from_str(factory.descriptor().document().get())?;
    let version = format!(
        "{TYPE}@{}",
        descriptor["public_api_version"]
            .as_str()
            .ok_or("missing source API version")?
    );
    let semantic =
        OnlyBarSemantic::fixed_duration(15u32.into(), None).map_err(|_| "invalid bar semantic")?;
    let plan = OnlyConstructionResolutionPlan::resolve(
        semantic.clone(),
        resource.capabilities(),
        OnlyConstructionResolutionContext::new(
            &resolved.identity().source_id,
            "BTCUSDT.BINANCE".parse()?,
            revision,
            &fp(&resource.calendar().to_record())?,
        )?,
        OnlyConstructionRequirement::PreferExactNative,
    )?;
    let construction = OnlyConstructionIdentity::new(plan, &version, None, None, None)?;
    let provider_instrument = json!({"symbol":"BTCUSDT","baseAsset":"BTC","quoteAsset":"USDT","status":"TRADING",
        "filters":[{"filterType":"PRICE_FILTER","tickSize":"0.01"},{"filterType":"LOT_SIZE","stepSize":"0.000001","minQty":"0.000001"}]});
    let instrument = spot_normalize::instrument(&provider_instrument)?;
    let rows = (0..575i64)
        .map(|i| {
            let start = START_MS + i * STRIDE_MS;
            let price = 10000 + (i / 13) * 3 + (i * 7) % 11;
            let close = price + i % 5 - 2;
            let volume = 10 + i % 9;
            json!([
                start,
                price.to_string(),
                (price + 4).to_string(),
                (price - 4).to_string(),
                close.to_string(),
                volume.to_string(),
                start + STRIDE_MS - 1,
                (price * volume).to_string(),
                100 + i % 17,
                "0",
                "0",
                "0"
            ])
        })
        .collect::<Vec<_>>();
    let raw = serde_json::to_vec(&rows)?;
    let raw_sha = sha(&raw);
    let capture = format!(
        "native:{}:controlled-retained",
        resolved.implementation_fingerprint()
    );
    let segment_id = "controlled-retained-source";
    let raw_id = format!(
        "raw-event:{}",
        fp(
            &json!({"source_id":resolved.identity().source_id,"capture_session_id":capture,"stream":"rest","provider_event_type":"/api/v3/klines","provider_event_id":null,"provider_sequence":null,"ts_event_ns":null,"ts_receive_ns":RECEIVE,"raw_sha256":raw_sha})
        )?
    );
    let mut facts = vec![];
    for row in &rows {
        let bar = spot_normalize::rest_bar_interval(row, &instrument, 15)?;
        let event = OnlyTimestamp::from_datetime(*bar.ts_event())
            .unix_nanos()
            .to_string()
            .parse::<i64>()?;
        let start = OnlyTimestamp::from_datetime(*bar.bar_start())
            .unix_nanos()
            .to_string()
            .parse::<i64>()?;
        // Public OAMD fixture input. Wal::append revalidates the complete identity/record contract.
        let update_id = format!(
            "market-fact:bar:{}",
            fp(
                &json!({"kind":"BAR","source":resolved.identity().source_id,"instrument":bar.instrument_id().to_json()?,"bar_type":bar.bar_type().to_json()?,"bar_start":bar.bar_start().to_string(),"data_version":version})
            )?
        );
        let update = json!({"schema_version":3,"update_id":update_id,"runtime_id":"market-data-product","source_id":resolved.identity().source_id,"source_sequence":start/(STRIDE_MS*1_000_000),"data_version":version,"instrument_id":bar.instrument_id().to_string(),"data_type":"BAR","payload":{"kind":"BAR","value":bar.to_record()},"ts_event":event,"ts_init":event,"quality_flags":["VALID"],"metadata":[],"correlation_id":null,"sequence_semantics":"CONTIGUOUS","sequence_scope":{"source_id":resolved.identity().source_id,"instrument_id":bar.instrument_id().to_json()?,"data_type":"BAR","bar_type":bar.bar_type().to_record()}});
        facts.push(json!({"canonical_fact_id":update_id,"raw_event_id":raw_id,"source_id":resolved.identity().source_id,"segment_id":segment_id,"capture_session_id":capture,"data_kind":"BAR","instrument_id":bar.instrument_id().to_string(),"ts_event_ns":event,"ts_receive_ns":RECEIVE,"ts_ingest_ns":RECEIVE,"canonical_payload_hash":fp(&update)?,"canonical_payload":update,"normalizer_id":"binance.spot.native","normalizer_version":resolved.implementation_fingerprint(),"quality_state":"VALID","provenance":"REST_BACKFILL"}));
    }
    let bundle = json!({"schema_version":1,"evidence":{"raw_event_id":raw_id,"source_id":resolved.identity().source_id,"capture_session_id":capture,"provider":resolved.identity().provider,"venue":resolved.identity().venue,"market":resolved.identity().market,"stream":"rest","provider_event_type":"/api/v3/klines","provider_event_id":null,"provider_sequence":null,"ts_event_ns":null,"ts_receive_ns":RECEIVE,"payload_codec":"application/json","provider_schema":"v1","payload_base64":STANDARD.encode(&raw),"raw_sha256":raw_sha,"provenance":"REST_BACKFILL","integration_binding_fingerprint":resolved.binding_fingerprint(),"bar_construction":construction.to_record()},"canonical_facts":facts});
    let wal_root = Path::new(text(v, "user_data")?)
        .join("market-data")
        .join(&resolved.identity().source_id)
        .join("wal");
    std::fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&wal_root)?;
    let mut wal = Wal::new(&wal_root, 128 * 1024 * 1024)?;
    wal.create_segment(segment_id, AT)?;
    wal.append(&bundle.to_string())?;
    let segment = wal.seal(AT)?;
    let retained = wal.read_sealed(segment_id)?;
    if retained != vec![bundle] {
        return Err("retained fixture did not round trip".into());
    }
    drop(wal);
    session.close().await?;
    Ok(
        json!({"schema_version":1,"controlled_external_input":true,"source":{"integration_id":id.value(),"integration_revision_fingerprint":revision,"expected_type_id":TYPE,"source_id":resolved.identity().source_id,"environment":resolved.identity().environment},
        "provider_http_fixture":{"exchange_info":{"timezone":"UTC","symbols":[provider_instrument]},"klines":rows},
        "selected_backend_sha256":native_sha,"binding_fingerprint":resolved.binding_fingerprint(),"segment":segment,"wal_root":wal_root,
        "first_event_ns":((START_MS+STRIDE_MS)*1_000_000).to_string(),"last_event_ns":((START_MS+575*STRIDE_MS)*1_000_000).to_string(),"protected_start_ns":((START_MS+576*STRIDE_MS)*1_000_000).to_string(),
        "suggested_advice":{"timeframe_minutes":15,"instrument_id":"BTCUSDT.BINANCE","start_at":"2026-01-01T06:00:00Z","development_end_at":"2026-01-03T22:00:00Z","end_at":"2026-01-06T14:00:00Z","protected_start_at":"2026-01-07T00:00:00Z","protected_end_at":"2026-01-09T16:00:00Z","horizon_bars":1,"expected_block_length":12,"replicates":4096,"confidence_bps":9500,"seed":"b".repeat(64)}}),
    )
}
