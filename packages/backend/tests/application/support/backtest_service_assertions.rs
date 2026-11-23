#[path = "job_fact_connection.rs"]
mod fact_connection;
use crate::{
    application::backtest_run::VerifiedRun, persistence::research_preparation::Operation,
    workers::backtest_service::Configuration,
};
use serde_json::Value;
use tokio_postgres::Client;

/// The admitted Run supplies the inputs for the in-memory completion candidate.
pub(crate) async fn memory_completion(
    client: &mut Client,
    run: &VerifiedRun,
    original: &Operation,
    configuration: &Configuration,
    source_session: &crate::application::source_access::Session,
    selection: &crate::application::source_access::Selection,
    clickhouse: &crate::persistence::market_data::ClickHouse,
) {
    use crate::application::{
        factor_build::FactorBuildService,
        factor_content::hash,
        finite_job,
        job_contract::{FrozenJobBinding, JobKind, MemberKind},
        job_input::{JobInputLoader, MemoryBudget},
        research_dataset::MaterializedDataset,
    };
    use crate::persistence::{
        market_data::{Catalog, Storage},
        research_dataset::Store,
    };
    use onlyalpha_calculation_bridge::ChartInstallation;
    use onlyalpha_domain::time::{OnlyTimestamp, OnlyUtcDateTime};
    use serde_json::json;
    use std::{sync::Arc, time::Instant};
    let started = Instant::now();
    let retired_store = configuration.runtime_root.with_file_name("backtest");
    assert!(!retired_store.exists());
    let mut facts = fact_connection::Connection::reader().await.unwrap();
    let prepared = finite_job::prepare_backtest(
        client,
        &mut facts.client,
        run,
        &configuration.research_root,
        &configuration.runtime_root,
        &configuration.algorithms_root,
    )
    .await
    .unwrap();
    let values = prepared.execution_values().unwrap();
    let factor_bindings = prepared.factor_bindings().unwrap();
    let datasets = Store::open(
        &configuration.research_root.join("datasets"),
        8192,
        8 * 1024 * 1024,
    )
    .unwrap();
    let materialized = MaterializedDataset::load(
        &datasets,
        original.outputs["ready"]["dataset_materialization_id"]
            .as_str()
            .unwrap(),
    )
    .unwrap();
    let dataset = materialized.verified().dataset();
    let mut storage = Storage::new(
        Catalog::new(client, 10000, 32 * 1024 * 1024).unwrap(),
        clickhouse,
        10000,
    )
    .unwrap();
    let original_market = &materialized.lineage()["market_data_revision_bindings"][0];
    let revision = storage
        .revision_bounded(
            original_market["revision_id"].as_str().unwrap(),
            8192,
            32 * 1024 * 1024,
        )
        .await
        .unwrap();
    let scope = &revision.revision()["scope"];
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
    let window = prepared.preparation().record()["window"].clone();
    let warmup = window["warmup_bars"].as_u64().unwrap();
    let plan = finite_job::plan_members(
        JobKind::Backtest,
        &json!(axis),
        &json!(
            axis.iter()
                .skip(warmup as usize)
                .cloned()
                .collect::<Vec<_>>()
        ),
        0,
    )
    .unwrap();
    let ns = |v: &Value| {
        let t: OnlyUtcDateTime = v.as_str().unwrap().parse().unwrap();
        let n: i64 = OnlyTimestamp::from_datetime(t)
            .unix_nanos()
            .try_into()
            .unwrap();
        n
    };
    let seal = revision.seal();
    let raw = json!({"schema_version":1,"kind":"BACKTEST","scope":{"namespace":run.namespace().value(),"owner":run.owner(),"run_id":run.run_id()},"factor_bindings":factor_bindings,
        "market":{"dataset_snapshot":dataset.snapshot_fingerprint(),"source_revision":revision.revision()["fingerprint"],"bar_semantic":hash(&dataset.definition()["bar_semantic"]).unwrap(),"instruments":dataset.definition()["instruments"],"start_ns":ns(&dataset.definition()["time_range"]["start"]),"end_ns":ns(&dataset.definition()["time_range"]["end"]),"versions":[hash(&scope["data_version"]).unwrap()],"seals":[seal["seal_id"].as_str().unwrap().strip_prefix("seal:").unwrap()],"segments":revision.revision()["segment_refs"].as_array().unwrap().iter().map(|r|hash(r).unwrap()).collect::<Vec<_>>(),"rows":axis.len(),"warmup_rows":warmup,"sample_rows":axis.len() as u64-warmup,"axis":hash(&json!(axis)).unwrap(),"content":dataset.content_fingerprint()},"result_plan":plan.record()});
    let mut raw = raw;
    for (k, v) in values.as_object().unwrap() {
        raw[k] = v.clone();
    }
    let binding = FrozenJobBinding::from_record(&raw).unwrap();
    let mut cfg: tokio_postgres::Config = std::env::var("ONLYALPHA_POSTGRES_DSN")
        .unwrap()
        .parse()
        .unwrap();
    assert!(cfg.get_dbname().unwrap().ends_with("_test"));
    cfg.user("onlyalpha_job_storage_test_login");
    let (mut factor_client, connection) = cfg.connect(tokio_postgres::NoTls).await.unwrap();
    let driver = tokio::spawn(connection);
    factor_client
        .batch_execute("SET ROLE onlyalpha_job_reader")
        .await
        .unwrap();
    let installation = Arc::new(
        ChartInstallation::open(
            &configuration.algorithms_root,
            original.outputs["ready"]["algorithm_resolution"]["algorithm_artifact"]
                .as_str()
                .unwrap(),
        )
        .unwrap(),
    );
    let mut factors = FactorBuildService::new(&mut factor_client, run.namespace(), installation)
        .await
        .unwrap();
    let input = JobInputLoader::new(&mut storage, &mut factors, source_session, selection)
        .load(
            &binding,
            &MemoryBudget::new(8192, 128 * 1024 * 1024).unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(input.bars().len(), 740);
    drop(factors);
    let frozen = crate::persistence::job_publication::PublicationRepository::new(&mut factor_client,run.namespace(),run.owner()).await.unwrap()
        .frozen_binding(&crate::persistence::job_publication::RunLocator::new(JobKind::Backtest,run.run_id()).unwrap()).await.unwrap();
    assert_eq!(frozen.record(),binding.record(),"the admitted Run must already own the exact frozen input plan before memory execution");
    let prepared_us = started.elapsed().as_micros();
    let execute = Instant::now();
    let candidate = prepared
        .start(input, binding.clone())
        .unwrap()
        .join()
        .await
        .unwrap();
    let execute_us = execute.elapsed().as_micros();
    let mut kinds = std::collections::BTreeSet::new();
    for member in binding.result_plan().members() {
        let raw = candidate
            .content(member.key())
            .expect("every planned result member must exist");
        let content: Value = serde_json::from_str(raw).unwrap();
        kinds.insert(member.kind());
        if member.kind() == MemberKind::CloseCurve {
            assert_eq!(content["rows"].as_array().unwrap().len(), 720);
        }
        if member.kind() == MemberKind::ExecutionFacts {
            assert!(content["rows"].as_array().unwrap().len() >= 1480);
        }
        if member.kind() == MemberKind::EconomicResult {
            assert_eq!(
                content["body"]["analytical_baseline"]["kind"],
                "ANALYTICAL_ESTIMATE"
            );
        }
        assert_eq!(
            candidate.content(member.key()),
            Some(raw),
            "repeated observation retains identical complete bytes"
        );
    }
    assert_eq!(
        kinds,
        std::collections::BTreeSet::from([
            MemberKind::ExecutionFacts,
            MemberKind::CloseCurve,
            MemberKind::EconomicResult,
            MemberKind::CausalEvidence
        ])
    );
    drop(factor_client);
    driver.await.unwrap().unwrap();
    let row=client.query_one("SELECT state,(SELECT count(*) FROM public.job_publication WHERE run_id=$1::text::uuid) FROM backtest_run WHERE run_id=$1::text::uuid",&[&run.run_id()]).await.unwrap();
    assert_eq!(row.get::<_, String>(0), "QUEUED");
    assert_eq!(row.get::<_, i64>(1), 0);
    assert!(
        !retired_store.exists(),
        "finite execution cannot create the old durable Runtime journal"
    );
    println!(
        "FINITE_BACKTEST_CANDIDATE {{\"prepared_us\":{prepared_us},\"execute_join_us\":{execute_us}}}"
    );
}
