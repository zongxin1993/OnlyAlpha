//! Actual READY/Run3 fixture supplies every owning input. No Work/Joined factory.
//! These assertions are called by the existing PostgreSQL FullEvidence harness;
//! a signature check alone does not claim that its runtime fixture has executed.
use crate::{
    application::backtest_run::VerifiedRun,
    persistence::{backtest_evidence::BacktestReadContext, research_preparation::Operation},
    workers::{
        backtest_result::ObservedBacktest,
        backtest_service::{
            self, Configuration, Control, Error, JoinedBacktest, PausedBacktest, Produced,
            StartMode, Work,
        },
    },
};
use onlyalpha_calculation_bridge::ProcessState;
use serde_json::Value;
use tokio_postgres::Client;
type Result<T> = std::result::Result<T, &'static str>;
#[test]
fn backtest_producer_api_requires_actual_owned_work_and_distinct_start_mode() {
    let _: fn(Work, StartMode, &Control) -> std::result::Result<Produced, Error> =
        backtest_service::produce;
    let _: fn(&Control) = Control::request_cancel;
    let _: fn(&Control) = Control::request_pause;
    let _: fn(&JoinedBacktest) -> &VerifiedRun = JoinedBacktest::run;
    let _: fn(&JoinedBacktest) -> &ObservedBacktest = JoinedBacktest::observation;
    let _: fn(&JoinedBacktest) -> &BacktestReadContext = JoinedBacktest::read_context;
    let _: fn(&JoinedBacktest) -> Result<()> = JoinedBacktest::verify_cut;
    let _: fn(&PausedBacktest) -> &VerifiedRun = PausedBacktest::run;
    let _: fn(&PausedBacktest) -> Result<()> = PausedBacktest::verify_cut;
    let _: fn(&Error) -> &'static str = Error::code;
    let _: fn(&mut Error) -> Result<()> = Error::drain;
    let _ = Work::restore;
    let _: fn(&Value) -> Result<Value> = crate::workers::backtest_terminal::read_request;
    assert_ne!(StartMode::Create, StartMode::Resume);
}
fn numeric(v: &Value) -> onlyalpha_domain::numeric::OnlyDecimal {
    v.as_str().unwrap().parse().unwrap()
}
fn terminal(
    joined: &JoinedBacktest,
    expected: &str,
    configuration: &Configuration,
) -> onlyalpha_backtest::TerminalSnapshot {
    joined.verify_cut().unwrap();
    joined.read_context().verify_cut().unwrap();
    assert_eq!(joined.run().run_id(), joined.read_context().run().run_id());
    let observed = joined.observation();
    let proof = observed.proof();
    assert_eq!(proof["status"], expected);
    assert_eq!(proof["outcome"]["status"], expected);
    assert_eq!(proof["processed_prefix_verified"], true);
    assert_eq!(proof["drained"], true);
    assert_eq!(observed.record()["status"], expected);
    assert_eq!(
        observed.preparation(),
        &joined.read_context().prepared().record()
    );
    assert_eq!(
        observed.result()["scope"],
        observed.preparation()["settings"]["execution"]
    );
    // Reuse the same existing read-only owner and original inputs as the
    // private terminal wire. An observation archive is not a replay decoder.
    let prepared = joined.read_context().prepared();
    let artifact = joined.run().resolution()["backtest_binding"]["executor_artifact_sha256"]
        .as_str()
        .unwrap();
    let specification = onlyalpha_backtest::RunSpec {
        work_id: joined.run().run_id().into(),
        configuration: prepared.configuration().clone(),
        kernel_artifact: artifact.into(),
        driver_artifact: artifact.into(),
        initial_ns: prepared.initial_ns().clone(),
    };
    let snapshot = onlyalpha_backtest::TerminalSnapshot::read(
        &configuration
            .backtest_root
            .join("runtime")
            .join(joined.run().run_id()),
        specification,
        prepared.inputs(),
        crate::workers::backtest::terminal_policy,
    )
    .unwrap();
    snapshot.verify_cut().unwrap();
    snapshot.verify_encoded_trace(observed.trace()).unwrap();
    assert_eq!(snapshot.trace(), observed.trace());
    assert_eq!(snapshot.proof(), observed.proof());
    assert_eq!(snapshot.result(), observed.result());
    snapshot
        .for_each_step(&mut |step, ready| {
            assert!(ready);
            for input in step["inputs"].as_array().unwrap() {
                if input["op"] == "FILL" {
                    assert_eq!(
                        numeric(&input["payload"]["quantity"]),
                        "0.01".parse().unwrap()
                    );
                }
            }
            Ok(())
        })
        .unwrap();
    assert!(
        backtest_service::test_child_states(joined)
            .iter()
            .all(|state| *state == ProcessState::Joined),
        "the entire original and restored child group must positively join"
    );
    joined.verify_cut().unwrap();
    snapshot.verify_cut().unwrap();
    snapshot
}
/// The caller must already own actual accepted READY and its exact Run3. This
/// helper never prepares, promotes, creates a Run, changes its Claim or releases
/// Runtime work; those remain the existing owning Product test's real steps.
pub(crate) async fn whole_interval(
    client: &mut Client,
    run: &VerifiedRun,
    original: &Operation,
    configuration: &Configuration,
) -> JoinedBacktest {
    let context = crate::persistence::backtest_evidence::read_context(
        client,
        run.namespace(),
        &configuration.research_root,
        &configuration.runtime_root,
        run.run_id(),
        Some(run.owner()),
    )
    .await
    .unwrap();
    let work = Work::restore(context, run, original, configuration)
        .unwrap_or_else(|e| panic!("actual work restore: {}", e.code()));
    let result = backtest_service::produce(work, StartMode::Create, &Control::default())
        .unwrap_or_else(|mut e| {
            let code = e.code();
            e.drain().unwrap();
            panic!("actual producer: {code}")
        });
    let Produced::Terminal(joined) = result else {
        panic!("unrequested pause")
    };
    let snapshot = terminal(&joined, "COMPLETED", configuration);
    let proof = joined.observation().proof();
    assert_eq!(proof["market_exhausted"], true);
    assert_eq!(joined.observation().record()["sample_bar_count"], 720);
    assert_eq!(joined.observation().trace()["state"]["cursor"], 740);
    let metadata = snapshot.trace_metadata().unwrap();
    assert_eq!(metadata["state"]["cursor"], 740);
    let mut consumed = 0;
    let mut last_close = Value::Null;
    snapshot
        .for_each_step(&mut |step, ready| {
            assert!(ready);
            if step["cause"]["kind"] == "BAR" {
                let input = &step["cause"]["processing"]["input"];
                assert_eq!(input, &metadata["inputs"]["records"][consumed]);
                consumed += 1;
                assert_eq!(step["state"]["cursor"], consumed);
                last_close = input["bar"].clone();
            }
            Ok(())
        })
        .unwrap();
    assert_eq!(
        consumed, 740,
        "every original closed event must be consumed exactly once"
    );
    let instant = |field: &str| {
        last_close[field]
            .as_str()
            .unwrap()
            .parse::<onlyalpha_domain::time::OnlyUtcDateTime>()
            .unwrap()
    };
    assert_eq!(
        instant("bar_start"),
        "2025-01-03T11:59:00Z".parse().unwrap()
    );
    assert_eq!(instant("ts_event"), "2025-01-03T12:00:00Z".parse().unwrap());
    assert_eq!(
        joined.observation().record()["baseline"]["kind"],
        "ANALYTICAL_ESTIMATE"
    );
    private_terminal_wire(&joined, configuration);
    snapshot.verify_cut().unwrap();
    drop(snapshot);
    joined
}
/// Deterministic STEP_READY fault injection stops directly after first BUY at
/// its OPEN. No next CLOSE is exposed, and a fresh concrete restore must retain
/// the canonical Order/Fill identity rather than re-execute that opening.
pub(crate) async fn pause_after_open_then_cancel(
    client: &mut Client,
    run: &VerifiedRun,
    original: &Operation,
    configuration: &Configuration,
) -> JoinedBacktest {
    let context = crate::persistence::backtest_evidence::read_context(
        client,
        run.namespace(),
        &configuration.research_root,
        &configuration.runtime_root,
        run.run_id(),
        Some(run.owner()),
    )
    .await
    .unwrap();
    let work = Work::restore(context, run, original, configuration)
        .unwrap_or_else(|e| panic!("{}", e.code()));
    backtest_service::test_pause_after_step(43);
    let Produced::Paused(paused) =
        backtest_service::produce(work, StartMode::Create, &Control::default())
            .unwrap_or_else(|e| panic!("{}", e.code()))
    else {
        panic!("shutdown pause must not create a terminal result")
    };
    paused.verify_cut().unwrap();
    assert_eq!(paused.run().run_id(), run.run_id());
    let before = backtest_service::test_paused_trace(&paused);
    assert_eq!(before["state"]["status"], "PAUSED");
    assert_eq!(before["state"]["cursor"], 21);
    assert_eq!(before["state"]["phase"], "CLOSE");
    let fills = |trace: &Value| {
        trace["steps"]
            .as_array()
            .unwrap()
            .iter()
            .flat_map(|s| s["step"]["inputs"].as_array().unwrap())
            .filter(|i| i["op"] == "FILL")
            .cloned()
            .collect::<Vec<_>>()
    };
    assert_eq!(fills(&before).len(), 1);
    drop(paused);
    // A later Claim uses Resume; the original Run identity and journal are exact.
    let context = crate::persistence::backtest_evidence::read_context(
        client,
        run.namespace(),
        &configuration.research_root,
        &configuration.runtime_root,
        run.run_id(),
        Some(run.owner()),
    )
    .await
    .unwrap();
    let work = Work::restore(context, run, original, configuration)
        .unwrap_or_else(|e| panic!("{}", e.code()));
    backtest_service::test_cancel_after_step(46); // PAUSE44, RESUME45, then the original pending BAR46.
    let Produced::Terminal(joined) =
        backtest_service::produce(work, StartMode::Resume, &Control::default())
            .unwrap_or_else(|e| panic!("{}", e.code()))
    else {
        panic!("user cancellation is terminal")
    };
    let snapshot = terminal(&joined, "CANCELLED", configuration);
    let proof = joined.observation().proof();
    assert_eq!(proof["market_exhausted"], false);
    assert!(joined.observation().record()["baseline"].is_null());
    let after = joined.observation().trace();
    let mut after_fills = Vec::new();
    let mut cancelled = false;
    let mut exhausted = false;
    snapshot
        .for_each_step(&mut |step, ready| {
            assert!(ready);
            for input in step["inputs"].as_array().unwrap() {
                if input["op"] == "FILL" {
                    after_fills.push(input.clone());
                }
            }
            cancelled |= step["cause"]["kind"] == "CANCEL_INPUT";
            exhausted |= step["cause"]["kind"] == "INPUT_END";
            Ok(())
        })
        .unwrap();
    assert_eq!(after_fills, fills(&before));
    assert_eq!(after["state"]["cursor"], 22);
    assert_eq!(joined.observation().record()["fill_count"], 1);
    assert_eq!(joined.observation().record()["roundtrip_count"], 0);
    assert_eq!(joined.observation().record()["sample_bar_count"], 2);
    assert!(cancelled);
    assert!(!exhausted);
    private_terminal_wire(&joined, configuration);
    snapshot.verify_cut().unwrap();
    drop(snapshot);
    joined
}
/// Create never opens an existing work, and Resume never initializes a new one.
/// The caller also snapshots the original journal around this refusal.
pub(crate) async fn refuse_mode(
    client: &mut Client,
    run: &VerifiedRun,
    original: &Operation,
    configuration: &Configuration,
    mode: StartMode,
) -> &'static str {
    let context = crate::persistence::backtest_evidence::read_context(
        client,
        run.namespace(),
        &configuration.research_root,
        &configuration.runtime_root,
        run.run_id(),
        Some(run.owner()),
    )
    .await
    .unwrap();
    let work = Work::restore(context, run, original, configuration)
        .unwrap_or_else(|e| panic!("{}", e.code()));
    let mut error = match backtest_service::produce(work, mode, &Control::default()) {
        Err(error) => error,
        Ok(_) => panic!("incompatible original Claim mode was accepted"),
    };
    let code = error.code();
    error.drain().unwrap();
    assert_eq!(
        error.code(),
        code,
        "positive child join cannot rewrite an unknown operational outcome as success"
    );
    code
}

fn private_terminal_wire(joined: &JoinedBacktest, configuration: &Configuration) {
    use serde_json::json;
    let artifact = &joined.run().resolution()["backtest_binding"]["executor_artifact_sha256"];
    let request = json!({"schema_version":1,"contract":"ONLYALPHA_BACKTEST_TERMINAL_READ_V1",
        "journal_root":configuration.backtest_root.join("runtime").join(joined.run().run_id()),
        "specification":{"work_id":joined.run().run_id(),"configuration":joined.read_context().prepared().configuration(),"kernel_artifact":artifact,"driver_artifact":artifact,"initial_ns":joined.read_context().prepared().initial_ns().to_string()},
        "inputs":joined.read_context().prepared().inputs().record()});
    let actual = crate::workers::backtest_terminal::read_request(&request).unwrap();
    let fields = actual
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(
        fields,
        std::collections::BTreeSet::from([
            "schema_version",
            "contract",
            "reader_artifact",
            "trace",
            "proof",
            "result",
            "state"
        ])
    );
    assert_eq!(actual["schema_version"], 1);
    assert_eq!(actual["contract"], request["contract"]);
    assert_eq!(&actual["reader_artifact"], artifact);
    assert_eq!(&actual["trace"], joined.observation().trace());
    assert_eq!(&actual["proof"], joined.observation().proof());
    assert_eq!(&actual["result"], joined.observation().result());
    assert_eq!(
        actual["state"]["execution_sequence"],
        joined.observation().result()["facts"]
            .as_array()
            .unwrap()
            .len()
    );
    for field in [
        "joined",
        "authority",
        "admission",
        "completion_proof",
        "evidence_fingerprint",
    ] {
        assert!(actual.get(field).is_none());
    }
    let mut foreign = request.clone();
    foreign["specification"]["kernel_artifact"] = json!("f".repeat(64));
    foreign["specification"]["driver_artifact"] = json!("f".repeat(64));
    assert_eq!(
        crate::workers::backtest_terminal::read_request(&foreign),
        Err("BACKTEST_HISTORICAL_READER_UNAVAILABLE")
    );
}
#[test]
fn terminal_reader_private_wire_rejects_foreign_authority_and_paths_without_startup() {
    use serde_json::json;
    let root = std::env::temp_dir().join(format!(
        "oa-terminal-private-invalid-{}",
        std::process::id()
    ));
    std::fs::create_dir(&root).unwrap();
    for request in [
        json!({"schema_version":1,"contract":"ONLYALPHA_BACKTEST_TERMINAL_READ_V1","journal_root":root,"specification":{},"inputs":{},"grant":true}),
        json!({"schema_version":true,"contract":"ONLYALPHA_BACKTEST_TERMINAL_READ_V1","journal_root":root,"specification":{},"inputs":{}}),
        json!({"schema_version":1,"contract":"ONLYALPHA_BACKTEST_TERMINAL_READ_V1","journal_root":"file:/tmp/native?immutable=1","specification":{},"inputs":{}}),
        json!({"schema_version":1,"contract":"ONLYALPHA_BACKTEST_TERMINAL_READ_V1","journal_root":"../foreign-runtime","specification":{},"inputs":{}}),
    ] {
        assert!(crate::workers::backtest_terminal::read_request(&request).is_err());
        assert_eq!(std::fs::read_dir(&root).unwrap().count(), 0);
    }
    std::fs::remove_dir(root).unwrap();
}

/// Actual original READY + Run supplies admission; this exercises only the new
/// in-memory completion owner, never the formal worker or PG publication.
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
    let native_runtime = configuration
        .backtest_root
        .join("runtime")
        .join(run.run_id());
    assert!(!native_runtime.exists());
    let prepared = finite_job::prepare_backtest(
        client,
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
    drop(factors);
    drop(factor_client);
    driver.await.unwrap().unwrap();
    let row=client.query_one("SELECT state,(SELECT count(*) FROM public.job_publication WHERE run_id=$1::text::uuid) FROM backtest_run WHERE run_id=$1::text::uuid",&[&run.run_id()]).await.unwrap();
    assert_eq!(row.get::<_, String>(0), "QUEUED");
    assert_eq!(row.get::<_, i64>(1), 0);
    assert!(
        !native_runtime.exists(),
        "finite execution cannot create the old durable Runtime journal"
    );
    println!(
        "FINITE_BACKTEST_CANDIDATE {{\"prepared_us\":{prepared_us},\"execute_join_us\":{execute_us}}}"
    );
}
