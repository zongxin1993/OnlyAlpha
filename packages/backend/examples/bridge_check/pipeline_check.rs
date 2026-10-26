//! Real worker composition proof; no formal Runtime/economic effects.
use onlyalpha_backend::workers::algorithm::AlgorithmProcess;
use onlyalpha_calculation::{CalculationSnapshot, StateOutcome};
use onlyalpha_calculation_bridge::{PipelineCalculations, SmaRequest, fingerprint};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::*,
    enums::OnlySessionType,
    market::{OnlyBar, OnlyBarType},
    time::{OnlyTimeZone, OnlyTimestamp},
};
use onlyalpha_market_data_pipeline::{construction::*, delivery::*, state::*, *};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    error::Error,
    path::Path,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
type Calls = Arc<Mutex<Vec<Value>>>;
type ProbePipeline = MarketDataPipeline<PipelineCalculations, Consumer>;
const DEADLINE: Duration = Duration::from_secs(10);
#[derive(Clone)]
struct Consumer {
    artifact: String,
    calls: Arc<Mutex<Vec<Value>>>,
}
impl PreparationConsumer for Consumer {
    fn artifact(&self) -> &str {
        &self.artifact
    }
    fn consume(
        &mut self,
        id: &str,
        plan: &OnlyBarDeliveryPlan,
        values: &BTreeMap<String, CalculationSnapshot>,
    ) -> ConsumerOutcome {
        assert!(values.values().all(|v| v.outcome() == StateOutcome::Ready));
        for v in values.values() {
            assert_eq!(v.outputs().unwrap()["value"]["value"], "10.5");
        }
        self.calls
            .lock()
            .unwrap()
            .push(json!([plan.cluster_id().value(), id]));
        ConsumerOutcome::Accepted
    }
}
fn kind(base: &Value, n: u32) -> OnlyBarType {
    let mut r = base["bar_type"].clone();
    r["semantic"]["formation"]["window_minutes"] = json!(n);
    r["semantic"]["formation"]["stride_minutes"] = json!(n);
    OnlyBarType::from_record(&r).unwrap()
}
fn input(base: &Value, i: u32) -> PipelineInput {
    let mut r = base.clone();
    for key in ["bar_start", "bar_end", "ts_event", "ts_init"] {
        let t = OnlyTimestamp::from_datetime(base[key].as_str().unwrap().parse().unwrap());
        r[key] = json!(
            OnlyTimestamp::from_unix_nanos(t.unix_nanos() + i64::from(i - 1) * 60_000_000_000i64)
                .to_datetime_exact()
                .unwrap()
                .to_string()
        );
    }
    let b = Arc::new(OnlyBar::from_record(&r).unwrap());
    PipelineInput {
        source: "c".repeat(64),
        sequence: u64::from(i),
        logical_init: OnlyTimestamp::from_datetime(*b.ts_init()),
        fact: OnlyConstructionFact::Bar(b),
        quality: vec![],
    }
}
fn setup(
    python: &Path,
    worker_artifact: &str,
    artifact: &str,
    base: &Value,
    derived: bool,
) -> Result<(ProbePipeline, Calls), Box<dyn Error>> {
    let owner = OnlyMarketDataStateScope::new("probe-engine".parse()?, "probe-runtime".parse()?);
    let calendar = Arc::new(OnlyTradingCalendar::new(OnlyTradingCalendarInput {
        calendar_id: "probe-calendar".parse()?,
        venue_id: "X".parse()?,
        timezone: OnlyTimeZone::new("UTC")?,
        sessions: vec![OnlyTradingSession::new(OnlyTradingSessionInput {
            name: "session".into(),
            opens_at: "01:30:00".parse()?,
            closes_at: "23:59:00".parse()?,
            session_type: OnlySessionType::Regular,
            belongs_to_trading_day_offset: 0,
            allows_orders: true,
            allows_market_data: true,
        })?],
        holidays: vec![],
        weekend_days: vec![5, 6],
        session_profile_id: None,
        special_schedules: vec![],
        calendar_version: 1.into(),
        effective_from: None,
        effective_to: None,
    })?);
    let one = kind(base, 1);
    let three = kind(base, 3);
    let edges = if derived {
        vec![OnlyConstructionEdge::new(
            OnlyConstructionInput::Bar(one.clone()),
            three.clone(),
            OnlyConstructionRecipe::derived(
                three.semantic().clone(),
                OnlyConstructionSemantic::Bar(one.semantic().clone()),
                "TIME_BAR",
                1u32.into(),
                OnlyMissingPolicy::Reject,
                OnlyIncompletePolicy::Drop,
            )?,
        )?]
    } else {
        vec![]
    };
    let graph = OnlyConstructionGraph::new(vec![OnlyConstructionInput::Bar(one.clone())], edges)?;
    let mut requests = vec![];
    let mut clusters = vec![];
    for (id, bar, period) in [("a", one.clone(), 3), ("b", three.clone(), 2)]
        .into_iter()
        .take(if derived { 2 } else { 1 })
    {
        requests.push(SmaRequest {
            local: "sma".into(),
            cluster: id.parse()?,
            source: "c".repeat(64),
            bar_type: bar.clone(),
            parameters: json!({"period":period}),
            required: true,
            dependencies: vec![],
        });
        clusters.push(ClusterProgram {
            cluster: id.parse()?,
            subscription: OnlyBarSubscription::new(
                &format!("sub-{id}"),
                if derived {
                    vec![one.clone(), three.clone()]
                } else {
                    vec![one.clone()]
                },
                graph.clone(),
                Some(bar),
                OnlyBarFreshness::LatestClosed,
            )?,
        });
    }
    let port = PipelineCalculations::new(
        Arc::new(AlgorithmProcess::new(python.to_owned())),
        "a".repeat(64),
        worker_artifact.to_owned(),
        owner.clone(),
        requests,
        DEADLINE,
    )?;
    let source = SourceProgram::new(
        &"c".repeat(64),
        calendar,
        Arc::new(OnlyConstructionRegistry::default()),
        artifact,
        graph,
    )?;
    let program = PipelineProgram::new(
        owner,
        &"a".repeat(64),
        128,
        vec![source],
        clusters,
        port.registrations(),
        artifact,
    )?;
    let calls = Arc::new(Mutex::new(vec![]));
    let consumer = Consumer {
        artifact: artifact.to_owned(),
        calls: calls.clone(),
    };
    Ok((MarketDataPipeline::new(program, port, consumer)?, calls))
}
pub fn run(python: &Path, worker_artifact: &str, base: &Value) -> Result<(), Box<dyn Error>> {
    let artifact = fingerprint(&std::fs::read(std::env::current_exe()?)?);
    let (mut original, calls) = setup(python, worker_artifact, &artifact, base, true)?;
    for i in 1..=2 {
        original.process(&input(base, i))?;
    }
    let checkpoint = original.capture_checkpoint()?;
    let bytes = checkpoint.to_string();
    let sha = digest(&checkpoint);
    let (mut restored, restored_calls) = setup(python, worker_artifact, &artifact, base, true)?;
    restored.restore_checkpoint(bytes.as_bytes(), &sha)?;
    for i in 3..=6 {
        assert_eq!(
            original.process(&input(base, i))?.to_record(),
            restored.process(&input(base, i))?.to_record()
        );
    }
    assert_eq!(
        original.capture_checkpoint()?,
        restored.capture_checkpoint()?
    );
    assert_eq!(*calls.lock().unwrap(), *restored_calls.lock().unwrap());
    assert_eq!(calls.lock().unwrap().len(), 5);
    // Cancellation cannot preserve a stale READY projection or invoke any consumer.
    let n = calls.lock().unwrap().len();
    let cancellation = original.calculations().cancellation()?;
    cancellation.cancel()?;
    assert!(original.process(&input(base, 7)).is_err());
    assert!(original.is_failed());
    assert_eq!(calls.lock().unwrap().len(), n);
    original.restore_checkpoint(bytes.as_bytes(), &sha)?;
    original.process(&input(base, 3))?;
    // A known Python arithmetic rejection blocks readiness without poisoning shared state.
    let (mut rejected, rejected_calls) = setup(python, worker_artifact, &artifact, base, false)?;
    let mut huge = base.clone();
    for key in ["open", "high", "low", "close"] {
        huge[key]["value"] = json!("1000000000000000000000000000000000000.00");
    }
    let out = rejected.process(&input(&huge, 1))?;
    assert_eq!(out.receipts[0]["outcome"], "BLOCKED");
    assert!(!rejected.is_failed());
    assert!(rejected_calls.lock().unwrap().is_empty());
    let cp = rejected.capture_checkpoint()?;
    let (mut candidate, _) = setup(python, worker_artifact, &artifact, base, false)?;
    candidate.restore_checkpoint(cp.to_string().as_bytes(), &digest(&cp))?;
    // Diagnostic wall time lives in Infrastructure, never Kernel state/identity.
    let startup = Instant::now();
    let (mut measured, _) = setup(python, worker_artifact, &artifact, base, false)?;
    let startup_ms = startup.elapsed().as_secs_f64() * 1000.;
    let start = Instant::now();
    let mut times = vec![];
    for i in 1..=512 {
        let now = Instant::now();
        measured.process(&input(base, i))?;
        times.push(now.elapsed().as_secs_f64() * 1000.);
    }
    let total_ms = start.elapsed().as_secs_f64() * 1000.;
    times.sort_by(f64::total_cmp);
    let (exchange, backend) = measured.calculations().timing();
    println!(
        "{}",
        json!({"probe":"market-data-pipeline","bars":512,"startup_ms":startup_ms,"whole_chain_ms":total_ms,"worker_exchange_ms":exchange.as_secs_f64()*1000.,"worker_backend_ms":backend.as_secs_f64()*1000.,"input_p50_ms":times[256],"input_p95_ms":times[486]})
    );
    println!("REAL_MARKET_DATA_PIPELINE_PASS");
    Ok(())
}
