//! Controlled actual PG/CH + admitted finite execution; no fixture completion grant.
use onlyalpha_backend::{
    application::{
        factor_build::FactorBuildService,
        factor_content::hash,
        finite_job::{self, plan_members},
        job_contract::{FrozenJobBinding, JobKind, MemberKind},
        job_input::{JobInputLoader, MemoryBudget},
        research_admission::{self},
        research_run::VerifiedRun,
        source_access::{Authority, Grant, Permission, Reference, Selection},
    },
    bootstrap::deployment::SemanticStoreId,
    persistence::{
        authority_session::AuthoritySession,
        market_data::{Catalog, ClickHouse, ClickHouseConfig, Scope, Storage},
        research_dataset::Store,
        research_runtime::RuntimeInputHold,
        strategy_research::Composer,
    },
};
use onlyalpha_calculation::product::Graph;
use onlyalpha_calculation_bridge::ChartInstallation;
use onlyalpha_domain::time::{OnlyTimestamp, OnlyUtcDateTime};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    path::Path,
    sync::Arc,
    time::{Duration, Instant},
};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn text<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str().ok_or_else(|| format!("missing {k}").into())
}
fn rows(v: &Value) -> Result<&Vec<Value>> {
    v.as_array().ok_or_else(|| "missing array".into())
}
fn ns(v: &Value) -> Result<i64> {
    let time: OnlyUtcDateTime = v.as_str().ok_or("time")?.parse()?;
    Ok(OnlyTimestamp::from_datetime(time).unix_nanos().try_into()?)
}
async fn connection(
    runtime: bool,
) -> Result<(
    tokio_postgres::Client,
    tokio::task::JoinHandle<std::result::Result<(), tokio_postgres::Error>>,
)> {
    let mut cfg: tokio_postgres::Config = std::env::var("ONLYALPHA_POSTGRES_DSN")?.parse()?;
    if cfg.get_dbname().is_none_or(|d| !d.ends_with("_test")) {
        return Err("test DSN required".into());
    }
    if runtime {
        cfg.user("onlyalpha_job_storage_test_login");
    }
    let (client, driver) = cfg.connect(tokio_postgres::NoTls).await?;
    Ok((client, tokio::spawn(driver)))
}
pub async fn build(session: &mut AuthoritySession, v: &Value) -> Result<Value> {
    let installation = Arc::new(ChartInstallation::open(
        Path::new(text(v, "algorithm_root")?),
        text(v, "algorithm_artifact")?,
    )?);
    let (mut client, driver) = connection(true).await?;
    client
        .batch_execute("SET ROLE onlyalpha_factor_builder")
        .await?;
    let namespace:String=session.client_mut().await?.query_one("SELECT semantic_store_id::text FROM research_deployment_semantic_store_binding WHERE singleton",&[]).await?.get(0);
    let namespace = SemanticStoreId::new(&namespace)?;
    let mut service = FactorBuildService::new(&mut client, &namespace, installation).await?;
    let mut parses = Vec::new();
    let mut bindings = Vec::new();
    for instance in rows(&v["build_instances"])? {
        let factor = text(instance, "factor_id")?;
        let revision = text(instance, "revision")?;
        service
            .request(factor, revision, &instance["parameters"])
            .await?;
        // Drain actual queued build work until the owner positively reports empty.
        let mut drained = false;
        for _ in 0..128 {
            match service.run_pending().await? {
                Some(report) => parses.push(report.source_parse_count),
                None => {
                    drained = true;
                    break;
                }
            }
        }
        if !drained {
            return Err("controlled factor build queue not drained".into());
        }
        let ready = service
            .resolve_ready_binding(factor, revision, &instance["parameters"])
            .await?;
        bindings.push(json!({"revision":ready.revision_fingerprint(),"program":ready.program_fingerprint(),"certificate":ready.certificate_fingerprint(),"parameters":ready.program().parameters().fingerprint()}));
    }
    drop(service);
    drop(client);
    driver.await??;
    Ok(json!({"source_parse_counts":parses,"bindings":bindings}))
}
pub async fn research(
    session: &mut AuthoritySession,
    v: &Value,
    run: VerifiedRun,
) -> Result<Value> {
    let start = Instant::now();
    let spec = run.strategy_specification()?.clone();
    let datasets = Store::open(Path::new(text(v, "dataset_root")?), 8192, 8 * 1024 * 1024)?;
    let saved = datasets.load(text(
        &spec.record()["scientific_specification"],
        "dataset_snapshot_fingerprint",
    )?)?;
    let dataset = saved.dataset();
    let runtime = RuntimeInputHold::open(
        Path::new(text(v, "runtime_root")?),
        run.run_id(),
        "research",
        run.runtime_generation_fingerprint()?,
    )?;
    let installation = Arc::new(ChartInstallation::open(
        Path::new(text(v, "algorithm_root")?),
        text(v, "algorithm_artifact")?,
    )?);
    let mut facts = crate::job_fact_connection::Connection::reader().await?;
    let prepared = research_admission::restore_strategy(
        &mut Composer::new(session.client_mut().await?).with_fact_reader(&mut facts.client),
        &run,
        runtime,
        &installation,
        &datasets,
    )
    .await?;
    let (mut factor_client, factor_driver) = connection(true).await?;
    factor_client
        .batch_execute("SET ROLE onlyalpha_factor_builder")
        .await?;
    let namespace:String=session.client_mut().await?.query_one("SELECT semantic_store_id::text FROM research_deployment_semantic_store_binding WHERE singleton",&[]).await?.get(0);
    let namespace = SemanticStoreId::new(&namespace)?;
    let mut factors =
        FactorBuildService::new(&mut factor_client, &namespace, installation.clone()).await?;
    let graph = Graph::from_record(
        &spec.record()["decision"]["decision_graph"],
        8 * 1024 * 1024,
    )?;
    let mut bindings = Vec::new();
    let parses: Vec<Option<u64>> = Vec::new();
    for node in graph
        .ordered_nodes()
        .filter(|n| n.to_record()["kind"] == "FACTOR")
    {
        let value = node.to_record();
        let factor = text(&value, "type_id")?;
        let dependency = rows(&prepared.record()["composition"]["factor_revision_bindings"])?
            .iter()
            .find(|d| d["factor_id"] == factor)
            .ok_or("factor dependency")?;
        let revision = text(dependency, "revision_fingerprint")?;
        let params = Value::Object(
            value["parameters"]
                .as_object()
                .ok_or("parameters")?
                .iter()
                .map(|(key, v)| (key.clone(), v["value"].clone()))
                .collect(),
        );
        let ready = factors
            .resolve_ready_binding(factor, revision, &params)
            .await?;
        bindings.push(json!({"revision":ready.revision_fingerprint(),"program":ready.program_fingerprint(),"certificate":ready.certificate_fingerprint(),"parameters":ready.program().parameters().fingerprint(),"numeric_policy":"DECIMAL28_HALF_EVEN_Q12_V1"}));
    }
    let db = text(v, "database")?;
    if !db.starts_with("onlyalpha_test_") {
        return Err("test CH namespace required".into());
    }
    let ch = ClickHouse::new(ClickHouseConfig {
        url: text(v, "url")?.into(),
        database: db.into(),
        user: std::env::var("ONLYALPHA_CLICKHOUSE_USER").unwrap_or("default".into()),
        password: std::env::var("ONLYALPHA_CLICKHOUSE_PASSWORD").unwrap_or_default(),
        timeout: Duration::from_secs(5),
        tls_roots_pem: vec![],
        max_bytes: 32 * 1024 * 1024,
        max_rows: 10_000,
    })?;
    let (mut source_client, source_driver) = connection(false).await?;
    let mut storage = Storage::new(
        Catalog::new(&mut source_client, 10_000, 32 * 1024 * 1024)?,
        &ch,
        10_000,
    )?;
    let revision = storage
        .revision_bounded(text(v, "id")?, 8192, 32 * 1024 * 1024)
        .await?;
    let scope = Scope::from_record(&v["scope"])?;
    let scope = scope.to_record();
    let recipe = &scope["bar_construction"]["plan"]["resolved_recipe"];
    let identity = finite_job::research_execution_values(&spec, dataset.definition(), recipe)?;
    let axis = dataset
        .rows()
        .iter()
        .map(|r| {
            json!([
                r["instrument_id"],
                r["bar_start_ns"],
                r["bar_end_ns"],
                r["ts_event_ns"],
                r["revision"]
            ])
        })
        .collect::<Vec<_>>();
    let warmup = spec.record()["input_window"]["warmup_bars"]
        .as_u64()
        .ok_or("warmup")?;
    let plan = plan_members(
        JobKind::Research,
        &json!(axis),
        &json!(
            axis.iter()
                .skip(warmup as usize)
                .cloned()
                .collect::<Vec<_>>()
        ),
        spec.statistics_intents()?.len(),
    )?;
    let mut raw = json!({"schema_version":1,"kind":"RESEARCH","scope":{"namespace":namespace.value(),"owner":"local-developer","run_id":run.run_id()},"factor_bindings":bindings,"market":{"dataset_snapshot":dataset.snapshot_fingerprint(),"source_revision":revision.revision()["fingerprint"],"bar_semantic":hash(&dataset.definition()["bar_semantic"])?,"instruments":dataset.definition()["instruments"],"start_ns":ns(&dataset.definition()["time_range"]["start"])?,"end_ns":ns(&dataset.definition()["time_range"]["end"])?,"versions":[hash(&scope["data_version"])?],"seals":[text(&revision.seal(),"seal_id")?.strip_prefix("seal:").ok_or("seal")?],"segments":rows(&revision.revision()["segment_refs"])?.iter().map(hash).collect::<std::result::Result<Vec<_>,_>>()?,"rows":axis.len(),"warmup_rows":warmup,"sample_rows":axis.len() as u64-warmup,"axis":hash(&json!(axis))?,"content":dataset.content_fingerprint()},"result_plan":plan.record()});
    for (key, value) in identity.as_object().ok_or("identity")? {
        if key != "source" {
            raw[key] = value.clone();
        }
    }
    let fault = v["finite_fault"].as_str().unwrap_or("normal");
    if fault == "run" {
        raw["scope"]["run_id"] = json!("11111111-1111-4111-8111-111111111111");
    }
    if fault == "plan-axis" {
        for m in raw["result_plan"]["members"].as_array_mut().ok_or("plan")? {
            if m["kind"] == "SIGNAL_VALUES" {
                m["axis"] = json!("0".repeat(64));
            }
        }
    }
    if fault == "execution" {
        raw["execution_configuration"] = json!("0".repeat(64));
    }
    let binding = FrozenJobBinding::from_record(&raw)?;
    let reference = Reference::new(
        "finite-job-test",
        text(
            &scope["bar_construction"]["plan"],
            "integration_revision_fingerprint",
        )?,
        Some("test.market.source"),
    )?;
    let selection = Selection::new(reference, text(&scope, "source_id")?, "LIVE")?;
    let authority = Authority::new(
        "local-developer",
        "add5b41fc5a881fc87ef4640581ed5ff7fe5eab39640b3a3e6e8b90f0aa71730",
        vec![Grant::new(
            selection.clone(),
            vec![Permission::ClosedHistory],
        )?],
    )?;
    let access = authority.authenticate(&format!("Bearer {}", "e".repeat(64)))?;
    let input = JobInputLoader::new(&mut storage, &mut factors, &access, &selection)
        .load(&binding, &MemoryBudget::new(8192, 128 * 1024 * 1024)?)
        .await?;
    let prepared_us = start.elapsed().as_micros();
    let executed = Instant::now();
    let task = finite_job::start_research(
        run.clone(),
        prepared,
        input,
        binding.clone(),
        &mut Composer::new(session.client_mut().await?).with_fact_reader(&mut facts.client),
        installation,
    )
    .await?;
    let stopped = if fault == "cancel" {
        Some(task.cancellation().stop())
    } else {
        None
    };
    let joined = task.join().await;
    if let Some(stopped) = stopped {
        stopped?;
    }
    let candidate = joined?;
    let execute_join_us = executed.elapsed().as_micros();
    let observed = Instant::now();
    let mut members = Vec::new();
    let mut lineage = Value::Null;
    for m in binding.result_plan().members() {
        let canonical = candidate.content(m.key()).ok_or("missing actual member")?;
        let content: Value = serde_json::from_str(canonical)?;
        if m.kind() == MemberKind::CausalEvidence {
            let execution = &content["body"]["execution"];
            lineage = json!({"calculation_batch":execution["calculation_batch"],"signal_plane":execution["signal_plane"]});
        }
        let content_digest: String = Sha256::digest(canonical.as_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        members.push(json!({"key":m.key(),"kind":m.kind(),"rows":content["rows"].as_array().map(Vec::len),"content":content_digest}));
    }
    let state: String = session
        .client_mut()
        .await?
        .query_one(
            "SELECT state FROM research_run WHERE run_id=$1::text::uuid",
            &[&run.run_id()],
        )
        .await?
        .get(0);
    let published: i64 = session
        .client_mut()
        .await?
        .query_one(
            "SELECT count(*) FROM job_publication WHERE run_id=$1::text::uuid",
            &[&run.run_id()],
        )
        .await?
        .get(0);
    let result = json!({"candidate":candidate.fingerprint(),"members":members,"lineage":lineage,"prepared_us":prepared_us,"execute_join_us":execute_join_us,"probe_observation_us":observed.elapsed().as_micros(),"source_parses_in_preparation":parses,"state":state,"publications":published});
    drop(candidate);
    drop(source_client);
    source_driver.await??;
    drop(factors);
    drop(factor_client);
    factor_driver.await??;
    Ok(result)
}
