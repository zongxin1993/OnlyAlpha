use onlyalpha_backtest::{Inputs, MarketInput, Source};
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar};
use serde_json::Value;
const FACTS: &str = include_str!("../../../test-data/domain/fact-records-v1.jsonl");
fn bar() -> OnlyBar {
    let v: Value = FACTS
        .lines()
        .map(|s| serde_json::from_str::<Value>(s).unwrap())
        .find(|v| v["id"] == "bar")
        .unwrap();
    OnlyBar::from_record(&v["record"]).unwrap()
}
#[test]
fn simultaneous_sources_have_stable_priority_and_exact_duplicate_identity() {
    let a = Source::new(
        &"a".repeat(64),
        &"b".repeat(64),
        &"c".repeat(64),
        &"d".repeat(64),
        1,
        1,
    )
    .unwrap();
    let b = Source::new(
        &"e".repeat(64),
        &"f".repeat(64),
        &"1".repeat(64),
        &"d".repeat(64),
        0,
        1,
    )
    .unwrap();
    let x = MarketInput::new(a.id(), 1, &"d".repeat(64), bar()).unwrap();
    let y = MarketInput::new(b.id(), 1, &"d".repeat(64), bar()).unwrap();
    let inputs = Inputs::new(vec![a, b], vec![x.clone(), y.clone(), x]).unwrap();
    assert_eq!(inputs.records()[0], y);
    assert_eq!(inputs.records().len(), 2);
    let record = inputs.record();
    assert_eq!(Inputs::from_record(&record).unwrap().record(), record);
}
use onlyalpha_backtest::{Candidate, Error, Participants, RunLoop, RunSpec};
use serde_json::json;
struct Counter(u64);
impl Participants for Counter {
    fn binding(&self) -> Value {
        json!({"schema_version":1,"kind":"UNIT_COUNTER","configuration":onlyalpha_calculation_bridge::fingerprint(configuration().to_string().as_bytes()),"generation":configuration()["generation"],"initial_ns":"0","strategies":{"cluster":"revision"},"sources":["a".repeat(64)]})
    }
    fn capture(&mut self) -> Result<Value, Error> {
        Ok(json!({"count":self.0}))
    }
    fn restore(&mut self, v: &Value) -> Result<(), Error> {
        self.0 = v["count"].as_u64().ok_or_else(|| Error("counter".into()))?;
        Ok(())
    }
    fn process(&mut self, i: &MarketInput, _: &mut Candidate) -> Result<Value, Error> {
        self.0 += 1;
        Ok(json!({"input":i.identity(),"count":self.0}))
    }
    fn quiescent(&self) -> Result<bool, Error> {
        Ok(true)
    }
}
fn configuration() -> Value {
    json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"a".repeat(64),"runtime_kind":"BACKTEST","currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"initial_cash":"1000.00","capitals":{"cluster":"1000.00"},"profiles":{"cluster":{"schema_version":1,"revision":"revision","instruments":["A.X"],"rules":[]}},"instruments":[{"schema_version":1,"id":"A.X","price_precision":2,"quantity_precision":0,"multiplier":"1"}]})
}
#[test]
fn finite_loop_pause_restart_and_terminal_proof_are_source_bound() {
    let root = std::env::temp_dir().join(format!("oa-replay-loop-{}", std::process::id()));
    std::fs::create_dir(&root).unwrap();
    let source = Source::new(
        &"a".repeat(64),
        &"b".repeat(64),
        &"c".repeat(64),
        &"d".repeat(64),
        0,
        1,
    )
    .unwrap();
    let input = MarketInput::new(source.id(), 1, &"d".repeat(64), bar()).unwrap();
    let inputs = Inputs::new(vec![source], vec![input]).unwrap();
    let spec = RunSpec {
        work_id: "work".into(),
        configuration: configuration(),
        kernel_artifact: "e".repeat(64),
        driver_artifact: "f".repeat(64),
        initial_ns: 0.into(),
    };
    let mut run = RunLoop::create(&root, spec.clone(), inputs.clone(), Counter(0)).unwrap();
    run.pause().unwrap();
    assert!(run.step().is_err());
    run.recover().unwrap();
    run.resume().unwrap();
    run.run().unwrap();
    assert!(!run.step().unwrap());
    run.terminate("COMPLETED", None).unwrap();
    let result = run.result().unwrap();
    assert_eq!(result["market_exhausted"], true);
    let trace = run.trace().unwrap();
    drop(run);
    let reopened = RunLoop::open(&root, spec.clone(), inputs.clone(), Counter(0)).unwrap();
    assert_eq!(reopened.result().unwrap(), result);
    assert_eq!(reopened.trace().unwrap(), trace);
    drop(reopened);
    let mut foreign = spec;
    foreign.work_id = "other-work".into();
    assert!(RunLoop::open(&root, foreign, inputs, Counter(0)).is_err());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn foreign_participant_context_is_rejected_before_even_an_empty_run() {
    let root = std::env::temp_dir().join(format!("oa-replay-context-{}", std::process::id()));
    std::fs::create_dir(&root).unwrap();
    let source = Source::new(
        &"a".repeat(64),
        &"b".repeat(64),
        &"c".repeat(64),
        &"d".repeat(64),
        0,
        0,
    )
    .unwrap();
    let inputs = Inputs::new(vec![source], vec![]).unwrap();
    let mut cfg = configuration();
    cfg["generation"] = json!("f".repeat(64));
    let spec = RunSpec {
        work_id: "foreign".into(),
        configuration: cfg,
        kernel_artifact: "e".repeat(64),
        driver_artifact: "f".repeat(64),
        initial_ns: 0.into(),
    };
    assert!(RunLoop::create(&root, spec, inputs, Counter(0)).is_err());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn missing_tail_conflict_version_and_noncanonical_input_order_are_refused() {
    let source = Source::new(
        &"a".repeat(64),
        &"b".repeat(64),
        &"c".repeat(64),
        "opaque-version",
        0,
        1,
    )
    .unwrap();
    let input = MarketInput::new(source.id(), 1, "opaque-version", bar()).unwrap();
    let exact = Inputs::new(vec![source.clone()], vec![input.clone()]).unwrap();
    assert!(Inputs::new(vec![source.clone()], vec![]).is_err());
    assert!(Inputs::new(vec![source.clone(), source.clone()], vec![input.clone()]).is_err());
    let mut conflict = bar().to_record();
    conflict["close"]["value"] = json!("99.00");
    conflict["high"]["value"] = json!("100.00");
    let conflict = MarketInput::new(
        source.id(),
        1,
        "opaque-version",
        OnlyBar::from_record(&conflict).unwrap(),
    )
    .unwrap();
    assert!(Inputs::new(vec![source.clone()], vec![input, conflict]).is_err());
    let foreign = MarketInput::new(source.id(), 1, "different", bar()).unwrap();
    assert!(Inputs::new(vec![source], vec![foreign]).is_err());
    let mut value = exact.record();
    value["records"][0]["sequence"] = json!(2);
    assert!(Inputs::from_record(&value).is_err());
    value = exact.record();
    value["sources"][0]["rows"] = json!(2);
    assert!(Inputs::from_record(&value).is_err());
}
#[test]
fn every_explicit_noncompleted_outcome_is_durable_and_not_completion() {
    for status in ["CANCELLED", "UNKNOWN", "FAILED", "INCOMPLETE"] {
        let root =
            std::env::temp_dir().join(format!("oa-replay-outcome-{}-{status}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        let source = Source::new(
            &"a".repeat(64),
            &"b".repeat(64),
            &"c".repeat(64),
            &"d".repeat(64),
            0,
            0,
        )
        .unwrap();
        let inputs = Inputs::new(vec![source], vec![]).unwrap();
        let spec = RunSpec {
            work_id: status.into(),
            configuration: configuration(),
            kernel_artifact: "e".repeat(64),
            driver_artifact: "f".repeat(64),
            initial_ns: 0.into(),
        };
        let mut run = RunLoop::create(&root, spec.clone(), inputs.clone(), Counter(0)).unwrap();
        assert!(run.terminate(status, None).is_err());
        assert!(run.result().is_err());
        run.recover().unwrap();
        run.terminate(status, Some("EXPLICIT_REASON")).unwrap();
        let result = run.result().unwrap();
        assert_eq!(result["outcome"]["status"], status);
        assert_eq!(
            result["status"],
            if status == "UNKNOWN" {
                "INCOMPLETE"
            } else {
                status
            }
        );
        assert_eq!(result["drained"], true);
        drop(run);
        let run = RunLoop::open(&root, spec, inputs, Counter(0)).unwrap();
        assert_eq!(run.result().unwrap(), result);
        drop(run);
        std::fs::remove_dir_all(root).unwrap();
    }
}

#[test]
fn missing_work_binding_cannot_be_created_by_open() {
    let root = std::env::temp_dir().join(format!("oa-replay-unbound-{}", std::process::id()));
    std::fs::create_dir(&root).unwrap();
    let cfg = configuration();
    let runtime =
        onlyalpha_runtime_persistence::Runtime::create(&root, cfg.clone(), &"e".repeat(64))
            .unwrap();
    drop(runtime);
    let before = std::fs::read(root.join("runtime.sqlite3")).unwrap();
    let source = Source::new(
        &"a".repeat(64),
        &"b".repeat(64),
        &"c".repeat(64),
        &"d".repeat(64),
        0,
        0,
    )
    .unwrap();
    let inputs = Inputs::new(vec![source], vec![]).unwrap();
    let spec = RunSpec {
        work_id: "unbound".into(),
        configuration: cfg,
        kernel_artifact: "e".repeat(64),
        driver_artifact: "f".repeat(64),
        initial_ns: 0.into(),
    };
    assert!(RunLoop::open(&root, spec, inputs, Counter(0)).is_err());
    assert_eq!(std::fs::read(root.join("runtime.sqlite3")).unwrap(), before);
    std::fs::remove_dir_all(root).unwrap();
}

struct MissingDrain;
fn pending_configuration() -> Value {
    let mut cfg = configuration();
    cfg["currency"] = json!({"schema_version":1,"code":"CNY","precision":2,"currency_type":"FIAT"});
    cfg["instruments"][0]["id"] = json!("600000.XSHG");
    cfg["profiles"]["cluster"]["instruments"] = json!(["600000.XSHG"]);
    cfg
}
impl Participants for MissingDrain {
    fn binding(&self) -> Value {
        let mut v = Counter(0).binding();
        v["configuration"] = json!(onlyalpha_calculation_bridge::fingerprint(
            pending_configuration().to_string().as_bytes()
        ));
        v
    }
    fn capture(&mut self) -> Result<Value, Error> {
        Ok(json!({}))
    }
    fn restore(&mut self, v: &Value) -> Result<(), Error> {
        if *v != json!({}) {
            return Err(Error("CHECKPOINT".into()));
        }
        Ok(())
    }
    fn process(&mut self, _: &MarketInput, c: &mut Candidate) -> Result<Value, Error> {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../../test-data/execution/domain-inputs.json"
        ))
        .unwrap();
        let request = &fixture["request"];
        let mut v = pending_configuration();
        for field in [
            "currency",
            "initial_cash",
            "capitals",
            "profiles",
            "instruments",
        ] {
            v.as_object_mut().unwrap().remove(field);
        }
        for (key, value) in [
            ("cluster", json!("cluster")),
            ("revision", json!("revision")),
            ("input_id", json!("input-1")),
            ("source_ref", json!("source-1")),
            ("time", json!(1)),
            ("runtime_sequence", json!(1)),
            ("trading_day", json!("2026-10-19")),
            ("day_index", json!(1)),
            ("op", json!("ADMIT")),
        ] {
            v[key] = value;
        }
        v["payload"] = json!({"schema_version":1,"request":request,"fee_contract":fixture["fee_contract"],"fee_budget":"1.00","market":{"schema_version":1,"verdict":"ACCEPT","source_ref":"market-1","request_digest":onlyalpha_calculation_bridge::fingerprint(request.to_string().as_bytes()),"notional":{"schema_version":1,"amount":"40.00","currency":pending_configuration()["currency"]},"rounding":"HALF_EVEN"},"order":"runtime-ORDER-000001","collateral":{"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null}});
        c.apply(&v)?;
        Ok(json!({"step":"effect"}))
    }
    fn quiescent(&self) -> Result<bool, Error> {
        Err(Error("DRAIN_PROOF_UNAVAILABLE".into()))
    }
}
#[test]
fn pending_events_do_not_turn_missing_broker_proof_into_false() {
    let root = std::env::temp_dir().join(format!("oa-replay-proof-{}", std::process::id()));
    std::fs::create_dir(&root).unwrap();
    let source = Source::new(
        &"a".repeat(64),
        &"b".repeat(64),
        &"c".repeat(64),
        &"d".repeat(64),
        0,
        1,
    )
    .unwrap();
    let input = MarketInput::new(source.id(), 1, &"d".repeat(64), bar()).unwrap();
    let inputs = Inputs::new(vec![source], vec![input]).unwrap();
    let spec = RunSpec {
        work_id: "missing-drain".into(),
        configuration: pending_configuration(),
        kernel_artifact: "e".repeat(64),
        driver_artifact: "f".repeat(64),
        initial_ns: 0.into(),
    };
    let mut run = RunLoop::create(&root, spec, inputs, MissingDrain).unwrap();
    run.run().unwrap();
    run.terminate("UNKNOWN", Some("EXPLICIT_UNKNOWN")).unwrap();
    assert!(run.result().is_err());
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn numerically_equal_but_distinct_duplicate_records_are_conflicts_in_both_orders() {
    let source = Source::new(
        &"a".repeat(64),
        &"b".repeat(64),
        &"c".repeat(64),
        "recorded",
        0,
        1,
    )
    .unwrap();
    let first = MarketInput::new(source.id(), 1, "recorded", bar()).unwrap();
    let mut changed = bar().to_record();
    changed["open"]["value"] = json!("10");
    let second = MarketInput::new(
        source.id(),
        1,
        "recorded",
        OnlyBar::from_record(&changed).unwrap(),
    )
    .unwrap();
    assert_eq!(first, second);
    assert_ne!(first.record(), second.record());
    for records in [vec![first.clone(), second.clone()], vec![second, first]] {
        assert_eq!(
            Inputs::new(vec![source.clone()], records).unwrap_err().0,
            "BACKTEST_REPLAY_CONFLICTING_INPUT"
        );
    }
}
