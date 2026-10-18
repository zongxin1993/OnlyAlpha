use onlyalpha_calculation::{
    CalculationState, ExecutionBinding, InputPosition, ReadinessPlan, ReadinessRequirement,
    StateOutcome,
};
use serde_json::{Value, json};
use std::collections::BTreeMap;
fn binding(scope: &str) -> ExecutionBinding {
    ExecutionBinding::new(std::array::from_fn(|_| "a".repeat(64)), scope).unwrap()
}
fn committed(scope: &str, ready: bool) -> CalculationState {
    let mut state = CalculationState::new(binding(scope));
    let batch = state.prepare(&["1"], &"b".repeat(64)).unwrap();
    let mut cursor = state.cursor().capture();
    cursor["revision"] = json!(1);
    cursor["samples"] = json!(1);
    cursor["last_event_ns"] = json!("1");
    state.commit(&batch, &json!({"cursor":cursor,"input_digest":"b".repeat(64),"outputs":{"value":{"type":"DECIMAL","value":"1"}},"ready":ready,"quality_flags":[]})).unwrap();
    state
}
#[test]
fn exact_receipts_snapshot_and_failure_are_not_stale_readiness() {
    let mut state = committed("first", true);
    let snapshot = state.snapshot();
    assert_eq!(snapshot.outcome(), StateOutcome::Ready);
    assert_eq!(
        snapshot.position().unwrap(),
        InputPosition::new(1, 1, "1", &"b".repeat(64)).unwrap()
    );
    state.fail(StateOutcome::Unknown, "WORKER_LOST").unwrap();
    assert_eq!(snapshot.outcome(), StateOutcome::Ready);
    assert_eq!(state.snapshot().outcome(), StateOutcome::Unknown);
    assert_eq!(state.snapshot().outputs(), snapshot.outputs());
    assert!(state.prepare(&["2"], &"c".repeat(64)).is_err());
    state.reset(2).unwrap();
    assert_eq!(state.snapshot().outcome(), StateOutcome::Uninitialized);
    assert!(state.snapshot().outputs().is_none());
}
#[test]
fn required_dependency_is_current_even_if_declared_optional() {
    let first = committed("first", true).snapshot();
    let second = committed("second", true).snapshot();
    let plan = ReadinessPlan::new(vec![
        ReadinessRequirement::new(binding("second"), true, vec!["first".into()]).unwrap(),
        ReadinessRequirement::new(binding("first"), false, vec![]).unwrap(),
    ])
    .unwrap();
    let mut positions = BTreeMap::from([
        ("first".into(), first.position().unwrap()),
        ("second".into(), second.position().unwrap()),
    ]);
    let snapshots: BTreeMap<String, _> =
        BTreeMap::from([("first".into(), first), ("second".into(), second)]);
    assert!(plan.evaluate(&snapshots, &positions).unwrap().ready());
    positions.insert(
        "first".into(),
        InputPosition::new(2, 2, "2", &"c".repeat(64)).unwrap(),
    );
    let barrier = plan.evaluate(&snapshots, &positions).unwrap();
    assert!(!barrier.ready());
    assert!(barrier.degraded());
}
#[test]
fn state_restore_is_fresh_exact_and_atomic() {
    let state = committed("first", false);
    let record = state.capture();
    let mut fresh = CalculationState::new(binding("first"));
    assert!(fresh.is_fresh());
    let before = fresh.capture();
    for mutate in ["binding", "samples", "ready", "extra"] {
        let mut bad = record.clone();
        match mutate {
            "binding" => bad["cursor"]["binding"]["scope"] = json!("other"),
            "samples" => bad["cursor"]["samples"] = json!(2),
            "ready" => bad["outcome"] = json!("READY"),
            _ => bad["extra"] = Value::Null,
        }
        assert!(fresh.restore(&bad).is_err(), "{mutate}");
        assert_eq!(fresh.capture(), before);
    }
    fresh.restore(&record).unwrap();
    assert!(!fresh.is_fresh());
    assert_eq!(fresh.capture(), record);
    assert!(fresh.restore(&record).is_err());
}
#[test]
fn receipt_rejection_never_commits_cursor_or_output() {
    let good = committed("first", true).capture()["receipt"].clone();
    let mut state = CalculationState::new(binding("first"));
    let batch = state.prepare(&["1"], &"b".repeat(64)).unwrap();
    let before = state.capture();
    for path in [
        "digest", "revision", "samples", "event", "binding", "type", "infinite", "ready", "extra",
        "flags", "outputs",
    ] {
        let mut bad = good.clone();
        match path {
            "digest" => bad["input_digest"] = json!("c".repeat(64)),
            "revision" => bad["cursor"]["revision"] = json!(2),
            "samples" => bad["cursor"]["samples"] = json!(2),
            "event" => bad["cursor"]["last_event_ns"] = json!("01"),
            "binding" => bad["cursor"]["binding"]["scope"] = json!("other"),
            "type" => bad["outputs"]["value"]["type"] = json!("BOOLEAN"),
            "infinite" => bad["outputs"]["value"]["value"] = json!("NaN"),
            "ready" => bad["ready"] = json!(1),
            "extra" => bad["extra"] = json!(null),
            "flags" => bad["quality_flags"] = json!(["DUP", "DUP"]),
            _ => bad["outputs"] = json!({}),
        }
        assert!(state.commit(&batch, &bad).is_err(), "{path}");
        assert_eq!(state.capture(), before);
    }
    state.commit(&batch, &good).unwrap();
    assert!(state.commit(&batch, &good).is_err());
}
#[test]
fn all_outcomes_restore_without_implicitly_becoming_ready() {
    for outcome in [
        StateOutcome::Failed,
        StateOutcome::Unavailable,
        StateOutcome::Unknown,
    ] {
        for has_result in [false, true] {
            let mut state = if has_result {
                committed("first", true)
            } else {
                CalculationState::new(binding("first"))
            };
            state.fail(outcome, "UNAVAILABLE").unwrap();
            let saved = state.capture();
            let mut fresh = CalculationState::new(binding("first"));
            fresh.restore(&saved).unwrap();
            assert_eq!(fresh.snapshot().outcome(), outcome);
            assert_eq!(fresh.capture(), saved);
            assert!(fresh.prepare(&["2"], &"b".repeat(64)).is_err());
            let mut missing_reason = saved;
            missing_reason["reason"] = Value::Null;
            assert!(
                CalculationState::new(binding("first"))
                    .restore(&missing_reason)
                    .is_err()
            );
        }
    }
    let mut unknown = committed("first", true);
    unknown.fail(StateOutcome::Unknown, "UNKNOWN").unwrap();
    assert!(unknown.fail(StateOutcome::Failed, "KNOWN").is_err());
}
fn req(scope: &str, required: bool, dependencies: &[&str]) -> ReadinessRequirement {
    ReadinessRequirement::new(
        binding(scope),
        required,
        dependencies.iter().map(|s| (*s).into()).collect(),
    )
    .unwrap()
}
#[test]
fn plans_reject_cycles_missing_dependencies_scope_and_generation_mixing() {
    for nodes in [
        vec![],
        vec![req("a", false, &[])],
        vec![req("a", true, &["b"])],
        vec![req("a", true, &["b"]), req("b", false, &["a"])],
        vec![req("a", true, &[]), req("a", true, &[])],
    ] {
        assert!(ReadinessPlan::new(nodes).is_err());
    }
    assert!(ReadinessRequirement::new(binding("a"), true, vec!["a".into()]).is_err());
    assert!(ReadinessRequirement::new(binding("a"), true, vec!["b".into(), "b".into()]).is_err());
    let mut digests = binding("b").digests().clone();
    digests[0] = "b".repeat(64);
    let foreign = ExecutionBinding::new(digests, "b").unwrap();
    assert!(
        ReadinessPlan::new(vec![
            req("a", true, &[]),
            ReadinessRequirement::new(foreign, false, vec![]).unwrap()
        ])
        .is_err()
    );
    assert!(
        ReadinessPlan::new((0..257).map(|i| req(&format!("n{i}"), true, &[])).collect()).is_err()
    );
}
#[test]
fn missing_unknown_and_warming_required_nodes_block_optional_nodes_degrade() {
    let plan =
        ReadinessPlan::new(vec![req("first", true, &[]), req("second", false, &[])]).unwrap();
    let ready = committed("first", true).snapshot();
    let positions = BTreeMap::from([
        ("first".into(), ready.position().unwrap()),
        ("second".into(), ready.position().unwrap()),
    ]);
    let mut snapshots = BTreeMap::from([("first".into(), ready.clone())]);
    let barrier = plan.evaluate(&snapshots, &positions).unwrap();
    assert!(barrier.ready() && barrier.degraded());
    snapshots.insert("first".into(), committed("first", false).snapshot());
    assert!(!plan.evaluate(&snapshots, &positions).unwrap().ready());
    snapshots.clear();
    assert!(!plan.evaluate(&snapshots, &positions).unwrap().ready());
    snapshots.insert("first".into(), committed("other", true).snapshot());
    assert!(plan.evaluate(&snapshots, &positions).is_err());
    snapshots.clear();
    let mut incomplete = positions.clone();
    incomplete.remove("second");
    assert!(plan.evaluate(&snapshots, &incomplete).is_err());
    snapshots.insert("foreign".into(), ready);
    assert!(plan.evaluate(&snapshots, &positions).is_err());
}
#[test]
fn distinct_timeframes_and_transitive_dependencies_have_explicit_positions() {
    let first = committed("first", true);
    let mut second = committed("second", true);
    let batch = second.prepare(&["900000000000"], &"c".repeat(64)).unwrap();
    let mut receipt = first.capture()["receipt"].clone();
    receipt["cursor"] = second.cursor().capture();
    receipt["cursor"]["last_event_ns"] = json!("900000000000");
    receipt["cursor"]["revision"] = json!(2);
    receipt["cursor"]["samples"] = json!(2);
    receipt["input_digest"] = json!("c".repeat(64));
    second.commit(&batch, &receipt).unwrap();
    let plan = ReadinessPlan::new(vec![
        req("first", false, &[]),
        req("second", true, &["first"]),
    ])
    .unwrap();
    let snapshots: BTreeMap<String, _> = BTreeMap::from([
        ("first".into(), first.snapshot()),
        ("second".into(), second.snapshot()),
    ]);
    let mut positions = snapshots
        .iter()
        .map(|(s, v)| (s.clone(), v.position().unwrap()))
        .collect::<BTreeMap<_, _>>();
    assert!(plan.evaluate(&snapshots, &positions).unwrap().ready());
    for changed in [
        InputPosition::new(2, 1, "1", &"b".repeat(64)).unwrap(),
        InputPosition::new(1, 2, "1", &"b".repeat(64)).unwrap(),
        InputPosition::new(1, 1, "1", &"c".repeat(64)).unwrap(),
    ] {
        positions.insert("first".into(), changed);
        assert!(!plan.evaluate(&snapshots, &positions).unwrap().ready());
    }
}
#[test]
fn independent_sma_state_corpus_preserves_producer_warmup_and_exact_outputs() {
    let mut state = CalculationState::new(binding("sma"));
    for line in include_str!("../../../../test-data/calculation/state-v1.jsonl").lines() {
        let row: Value = serde_json::from_str(line).unwrap();
        let index = row["samples"].as_u64().unwrap();
        let time = index.to_string();
        let batch = state.prepare(&[&time], &"b".repeat(64)).unwrap();
        let mut cursor = state.cursor().capture();
        cursor["revision"] = json!(index);
        cursor["samples"] = json!(index);
        cursor["last_event_ns"] = json!(time);
        state.commit(&batch, &json!({"cursor":cursor,"input_digest":"b".repeat(64),"outputs":{"value":{"type":"DECIMAL","value":row["value"]}},"ready":row["ready"],"quality_flags":[]})).unwrap();
        assert_eq!(
            state.snapshot().outcome(),
            if row["ready"] == true {
                StateOutcome::Ready
            } else {
                StateOutcome::Warming
            }
        );
        assert_eq!(
            state.snapshot().outputs().unwrap()["value"]["value"],
            row["value"]
        );
    }
}
