use onlyalpha_backtest::{
    Candidate, Error, Inputs, MarketInput, OpeningInput, Participants, RunLoop, RunSpec, Source,
};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::OnlyBar,
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use serde_json::{Value, json};
use std::str::FromStr;
const FACTS: &str = include_str!("../../../test-data/domain/fact-records-v1.jsonl");
fn configuration() -> Value {
    json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"a".repeat(64),"runtime_kind":"BACKTEST","currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"initial_cash":"1000.00","capitals":{"cluster":"1000.00"},"profiles":{"cluster":{"schema_version":1,"revision":"revision","instruments":["A.X"],"rules":[]}},"instruments":[{"schema_version":1,"id":"A.X","price_precision":2,"quantity_precision":0,"multiplier":"1"}]})
}
fn inputs() -> Inputs {
    let source = Source::new(
        &"a".repeat(64),
        &"b".repeat(64),
        &"c".repeat(64),
        "recorded",
        0,
        2,
    )
    .unwrap();
    let base = FACTS
        .lines()
        .map(|s| serde_json::from_str::<Value>(s).unwrap())
        .find(|v| v["id"] == "bar")
        .unwrap()["record"]
        .clone();
    let records = (0..2)
        .map(|index| {
            let mut v = base.clone();
            for key in ["bar_start", "bar_end", "ts_event", "ts_init"] {
                let t = OnlyUtcDateTime::from_str(base[key].as_str().unwrap()).unwrap();
                let ns =
                    OnlyTimestamp::from_datetime(t).to_unix_nanos() + index * 60_000_000_000_i64;
                v[key] = json!(
                    OnlyTimestamp::from_unix_nanos(ns)
                        .to_datetime_exact()
                        .unwrap()
                        .to_string()
                );
            }
            MarketInput::new(
                source.id(),
                index as u64 + 1,
                "recorded",
                OnlyBar::from_record(&v).unwrap(),
            )
            .unwrap()
        })
        .collect();
    Inputs::new(vec![source], records).unwrap()
}
struct Phases {
    seen: Vec<Value>,
    ended: bool,
}
impl Phases {
    fn new() -> Self {
        Self {
            seen: vec![],
            ended: false,
        }
    }
}
impl Participants for Phases {
    fn binding(&self) -> Value {
        json!({"schema_version":1,"configuration":onlyalpha_calculation_bridge::fingerprint(configuration().to_string().as_bytes()),"generation":"a".repeat(64),"initial_ns":"0","strategies":{"cluster":"revision"},"sources":["a".repeat(64)],"opening_profile":{"schema_version":1,"kind":"OPEN_CLOSE_V1"}})
    }
    fn opening_phase(&self) -> bool {
        true
    }
    fn capture(&mut self) -> Result<Value, Error> {
        Ok(json!({"seen":self.seen,"ended":self.ended}))
    }
    fn restore(&mut self, v: &Value) -> Result<(), Error> {
        self.seen = v["seen"].as_array().unwrap().clone();
        self.ended = v["ended"].as_bool().unwrap();
        Ok(())
    }
    fn opening(&mut self, input: &OpeningInput, _: &mut Candidate) -> Result<Value, Error> {
        let v = json!({"phase":"OPEN","input":input.record()});
        self.seen.push(v.clone());
        Ok(v)
    }
    fn process(&mut self, input: &MarketInput, _: &mut Candidate) -> Result<Value, Error> {
        let v = json!({"phase":"CLOSE","input":input.record()});
        self.seen.push(v.clone());
        Ok(v)
    }
    fn end_input(&mut self, _: &mut Candidate) -> Result<Value, Error> {
        self.ended = true;
        Ok(json!({"status":"CANCELLED_UNSUBMITTED_SIGNALS"}))
    }
    fn cancel_input(&mut self, _: &mut Candidate) -> Result<Value, Error> {
        self.ended = true;
        Ok(json!({"status":"CANCELLED_UNSUBMITTED_SIGNALS","reason":"USER_CANCELLED"}))
    }
    fn quiescent(&self) -> Result<bool, Error> {
        Ok(self.ended)
    }
}
fn spec() -> RunSpec {
    RunSpec {
        work_id: "open-phases".into(),
        configuration: configuration(),
        kernel_artifact: "e".repeat(64),
        driver_artifact: "f".repeat(64),
        initial_ns: 0.into(),
    }
}
fn root(name: &str) -> std::path::PathBuf {
    let p = std::env::temp_dir().join(format!("oa-open-phases-{}-{name}", std::process::id()));
    std::fs::create_dir(&p).unwrap();
    p
}
#[test]
fn opening_input_does_not_expose_future_bar_values() {
    let inputs = inputs();
    let input = &inputs.records()[0];
    let opening = input.opening();
    let record = opening.record();
    for key in [
        "bar",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "trade_count",
    ] {
        assert!(record.get(key).is_none(), "{key}");
    }
    assert_eq!(record["open"], input.bar().to_record()["open"]);
    assert!(opening.event_ns() < input.event_ns());
    assert_eq!(opening.identity(), input.identity());
}
#[test]
fn opening_and_close_are_durable_ordered_steps() {
    let root = root("ordered");
    let mut run = RunLoop::create(&root, spec(), inputs(), Phases::new()).unwrap();
    assert!(run.step().unwrap());
    let first = run.trace().unwrap();
    assert_eq!(first["state"]["cursor"], 0);
    assert_eq!(first["state"]["phase"], "CLOSE");
    assert_eq!(first["steps"][0]["step"]["cause"]["kind"], "OPEN");
    assert!(run.step().unwrap());
    let second = run.trace().unwrap();
    assert_eq!(second["state"]["cursor"], 1);
    assert_eq!(second["state"]["phase"], "OPEN");
    assert_eq!(second["steps"][1]["step"]["cause"]["kind"], "BAR");
    assert!(
        second["state"]["clock_ns"].as_str().unwrap()
            > first["state"]["clock_ns"].as_str().unwrap()
    );
    run.run().unwrap();
    run.close_input().unwrap();
    run.terminate("COMPLETED", None).unwrap();
    assert_eq!(run.result().unwrap()["market_exhausted"], true);
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn restart_between_open_and_close_resumes_exact_phase() {
    let root = root("restart");
    let mut run = RunLoop::create(&root, spec(), inputs(), Phases::new()).unwrap();
    assert!(
        run.step_observed(&mut |phase, _, _| if phase == "STEP_READY" {
            Err(Error("CUT_AFTER_OPEN".into()))
        } else {
            Ok(())
        })
        .is_err()
    );
    drop(run);
    let mut run = RunLoop::open(&root, spec(), inputs(), Phases::new()).unwrap();
    assert_eq!(run.trace().unwrap()["state"]["phase"], "CLOSE");
    run.step().unwrap();
    let state = run.trace().unwrap()["state"].clone();
    assert_eq!(state["participants"]["seen"].as_array().unwrap().len(), 2);
    assert_eq!(state["participants"]["seen"][0]["phase"], "OPEN");
    assert_eq!(state["participants"]["seen"][1]["phase"], "CLOSE");
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn input_end_is_durable_and_required_before_completion() {
    let root = root("end");
    let mut run = RunLoop::create(&root, spec(), inputs(), Phases::new()).unwrap();
    run.run().unwrap();
    assert!(run.terminate("COMPLETED", None).is_err());
    run.recover().unwrap();
    run.close_input().unwrap();
    let closed = run.trace().unwrap();
    run.close_input().unwrap();
    assert_eq!(run.trace().unwrap(), closed);
    assert_eq!(
        closed["steps"].as_array().unwrap().last().unwrap()["step"]["cause"]["kind"],
        "INPUT_END"
    );
    drop(run);
    let mut run = RunLoop::open(&root, spec(), inputs(), Phases::new()).unwrap();
    run.terminate("COMPLETED", None).unwrap();
    assert_eq!(run.result().unwrap()["drained"], true);
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}

struct InitialOwnerMismatch(Phases);
impl Participants for InitialOwnerMismatch {
    fn binding(&self) -> Value {
        self.0.binding()
    }
    fn capture(&mut self) -> Result<Value, Error> {
        self.0.capture()
    }
    fn restore(&mut self, v: &Value) -> Result<(), Error> {
        self.0.restore(v)
    }
    fn opening_phase(&self) -> bool {
        true
    }
    fn opening(&mut self, i: &OpeningInput, c: &mut Candidate) -> Result<Value, Error> {
        self.0.opening(i, c)
    }
    fn process(&mut self, i: &MarketInput, c: &mut Candidate) -> Result<Value, Error> {
        self.0.process(i, c)
    }
    fn end_input(&mut self, c: &mut Candidate) -> Result<Value, Error> {
        self.0.end_input(c)
    }
    fn quiescent(&self) -> Result<bool, Error> {
        self.0.quiescent()
    }
    fn validate_execution(&self, _: &Candidate) -> Result<(), Error> {
        Err(Error("INITIAL_OWNER_MISMATCH".into()))
    }
}
#[test]
fn new_run_validates_participant_against_canonical_genesis_before_creating_store() {
    let root = root("initial-owner");
    let error = RunLoop::create(&root, spec(), inputs(), InitialOwnerMismatch(Phases::new()))
        .err()
        .expect("mismatched initial owner must be rejected");
    assert_eq!(error.0, "INITIAL_OWNER_MISMATCH");
    assert_eq!(std::fs::read_dir(&root).unwrap().count(), 0);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn user_cancel_is_a_durable_prefix_boundary_and_preserves_the_open_close_cut() {
    let root = root("user-cancel-prefix");
    let mut run = RunLoop::create(&root, spec(), inputs(), Phases::new()).unwrap();
    assert!(run.step().unwrap()); // OPEN only: this bar's closed HLCV has not been exposed.
    let before = run.trace().unwrap();
    assert!(run.close_input().is_err()); // INPUT_END still requires the whole closed input.
    run.recover().unwrap();
    run.cancel_input().unwrap();
    let stopped = run.trace().unwrap();
    assert_eq!(stopped["state"]["cursor"], before["state"]["cursor"]);
    assert_eq!(stopped["state"]["clock_ns"], before["state"]["clock_ns"]);
    assert_eq!(
        stopped["state"]["participants"]["seen"],
        before["state"]["participants"]["seen"]
    );
    let last = &stopped["steps"].as_array().unwrap().last().unwrap()["step"];
    assert_eq!(last["cause"]["kind"], "CANCEL_INPUT");
    assert_eq!(last["cause"]["processing"]["reason"], "USER_CANCELLED");
    run.cancel_input().unwrap();
    assert_eq!(run.trace().unwrap(), stopped);
    assert!(!run.step().unwrap());
    assert!(run.close_input().is_err());
    run.recover().unwrap();
    drop(run);
    let mut run = RunLoop::open(&root, spec(), inputs(), Phases::new()).unwrap();
    assert_eq!(run.trace().unwrap(), stopped);
    assert!(run.terminate("COMPLETED", None).is_err());
    run.recover().unwrap();
    run.terminate("CANCELLED", Some("USER_CANCELLED")).unwrap();
    let proof = run.result().unwrap();
    assert_eq!(proof["outcome"]["status"], "CANCELLED");
    assert_eq!(proof["market_exhausted"], false);
    assert_eq!(proof["processed_prefix_verified"], true);
    assert_eq!(proof["drained"], true);
    drop(run);
    let run = RunLoop::open(&root, spec(), inputs(), Phases::new()).unwrap();
    assert_eq!(run.result().unwrap(), proof);
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn interrupted_cancel_preparation_recovers_one_stop_and_never_consumes_the_next_close() {
    let root = root("cancel-prepared");
    let mut run = RunLoop::create(&root, spec(), inputs(), Phases::new()).unwrap();
    assert!(run.step().unwrap());
    let error = run
        .cancel_input_observed(&mut |phase, _, _| {
            if phase == "PREPARED" {
                Err(Error("CUT_DURING_CANCEL".into()))
            } else {
                Ok(())
            }
        })
        .unwrap_err();
    assert_eq!(error.0, "CUT_DURING_CANCEL");
    drop(run);
    let mut run = RunLoop::open(&root, spec(), inputs(), Phases::new()).unwrap();
    let trace = run.trace().unwrap();
    assert_eq!(trace["state"]["cursor"], 0);
    assert_eq!(
        trace["state"]["participants"]["seen"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        trace["steps"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|r| r["step"]["cause"]["kind"] == "CANCEL_INPUT")
            .count(),
        1
    );
    assert!(
        trace["steps"]
            .as_array()
            .unwrap()
            .iter()
            .all(|r| r["ready"] == true)
    );
    assert!(!run.step().unwrap());
    run.terminate("CANCELLED", Some("USER_CANCELLED")).unwrap();
    assert_eq!(run.result().unwrap()["drained"], true);
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}

struct ClosedOnly(Phases);
impl Participants for ClosedOnly {
    fn binding(&self) -> Value {
        let mut binding = self.0.binding();
        binding.as_object_mut().unwrap().remove("opening_profile");
        binding
    }
    fn capture(&mut self) -> Result<Value, Error> {
        self.0.capture()
    }
    fn restore(&mut self, value: &Value) -> Result<(), Error> {
        self.0.restore(value)
    }
    fn process(&mut self, input: &MarketInput, candidate: &mut Candidate) -> Result<Value, Error> {
        self.0.process(input, candidate)
    }
    fn quiescent(&self) -> Result<bool, Error> {
        self.0.quiescent()
    }
}
#[test]
fn user_cancel_does_not_grant_a_stop_profile_to_the_existing_closed_only_lane() {
    let root = root("cancel-unsupported-lane");
    let mut run = RunLoop::create(&root, spec(), inputs(), ClosedOnly(Phases::new())).unwrap();
    let before = run.trace().unwrap();
    assert!(run.cancel_input().is_err());
    run.recover().unwrap();
    assert_eq!(run.trace().unwrap(), before);
    assert!(run.terminate("COMPLETED", None).is_err());
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn opening_binding2_retains_original_work_and_full_participant_identity() {
    let root = root("binding2");
    let specification = spec();
    let inputs = inputs();
    let participant = Phases::new();
    let original = participant.binding();
    let captured = json!({"seen":[],"ended":false});
    let run = RunLoop::create(&root, specification.clone(), inputs.clone(), participant).unwrap();
    let actual = run.trace().unwrap()["binding"].clone();
    let work=onlyalpha_calculation_bridge::fingerprint(json!({"work_id":specification.work_id,"configuration":specification.configuration,"artifact":specification.kernel_artifact,"driver_artifact":specification.driver_artifact,"input_pin":inputs.fingerprint(),"participants":original,"initial_ns":"0"}).to_string().as_bytes());
    assert_eq!(
        actual,
        json!({"schema_version":2,"configuration":onlyalpha_calculation_bridge::fingerprint(configuration().to_string().as_bytes()),"kernel_artifact":"e".repeat(64),"driver_artifact":"f".repeat(64),"work_id":"open-phases","participants":original,"work":work,"input_pin":inputs.fingerprint(),"program":onlyalpha_calculation_bridge::fingerprint(original.to_string().as_bytes()),"initial_state":{"schema_version":1,"cursor":0,"clock_ns":"0","status":"RUNNING","participants":captured,"outcome":null,"phase":"OPEN","input_finished":false}})
    );
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}

// These are technical native-owner tests. They create canonical Execution
// facts in the existing isolated database; they are not Product/UI acceptance.
fn checkpoint_rows(root: &std::path::Path) -> Vec<(i64, String, String)> {
    let db = rusqlite::Connection::open_with_flags(
        root.join("runtime.sqlite3"),
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    )
    .unwrap();
    let mut query = db
        .prepare("SELECT sequence,payload,digest FROM checkpoints ORDER BY sequence")
        .unwrap();
    query
        .query_map([], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)))
        .unwrap()
        .collect::<rusqlite::Result<Vec<_>>>()
        .unwrap()
}
fn corrupt_original_checkpoint(root: &std::path::Path) -> Vec<(i64, String, String)> {
    let original = checkpoint_rows(root);
    assert_eq!(original.len(), 1);
    let (sequence, raw, _) = &original[0];
    let mut value: Value = serde_json::from_str(raw).unwrap();
    value["identity"] = json!("0".repeat(64));
    let encoded = value.to_string();
    let digest = onlyalpha_execution::digest(encoded.as_bytes());
    let db = rusqlite::Connection::open(root.join("runtime.sqlite3")).unwrap();
    db.execute(
        "UPDATE checkpoints SET payload=?1,digest=?2 WHERE sequence=?3",
        rusqlite::params![encoded, digest, sequence],
    )
    .unwrap();
    drop(db);
    checkpoint_rows(root)
}
struct Valuations {
    phases: Phases,
    batches: Vec<u64>,
    next: usize,
}
impl Valuations {
    fn new(batches: &[u64]) -> Self {
        Self {
            phases: Phases::new(),
            batches: batches.into(),
            next: 0,
        }
    }
}
impl Participants for Valuations {
    fn binding(&self) -> Value {
        let mut value = self.phases.binding();
        value["valuation_batches"] = json!(self.batches);
        value
    }
    fn capture(&mut self) -> Result<Value, Error> {
        Ok(json!({"phases":self.phases.capture()?,"next":self.next}))
    }
    fn restore(&mut self, value: &Value) -> Result<(), Error> {
        self.phases.restore(&value["phases"])?;
        self.next = value["next"].as_u64().unwrap().try_into().unwrap();
        Ok(())
    }
    fn opening_phase(&self) -> bool {
        true
    }
    fn opening(&mut self, input: &OpeningInput, execution: &mut Candidate) -> Result<Value, Error> {
        self.phases.opening(input, execution)
    }
    fn process(&mut self, input: &MarketInput, execution: &mut Candidate) -> Result<Value, Error> {
        let count = *self
            .batches
            .get(self.next)
            .ok_or_else(|| Error("VALUATION_BATCH_EXHAUSTED".into()))?;
        for _ in 0..count {
            let sequence = execution.records().len() as u64 + 1;
            let state = execution.state()?;
            let checkpoint = execution.checkpoint()?;
            // Flat positions legitimately have no marks. This uses the actual
            // Position evidence and Account economic version, not a fake seal.
            let payload = json!({"schema_version":1,"valuation":format!("cadence-valuation-{sequence}"),"version":sequence,
                "economic_version":state["account"]["snapshot"]["economic_version"],
                "position_evidence":onlyalpha_execution::digest(checkpoint["components"][1].to_string().as_bytes()),"marks":[]});
            let mut action = configuration();
            for key in [
                "currency",
                "initial_cash",
                "capitals",
                "profiles",
                "instruments",
            ] {
                action.as_object_mut().unwrap().remove(key);
            }
            action["cluster"] = json!("cluster");
            action["revision"] = json!("revision");
            action["input_id"] = json!(format!("cadence-input-{sequence}"));
            action["source_ref"] = json!(format!("cadence-source-{sequence}"));
            action["time"] = json!(sequence);
            action["runtime_sequence"] = json!(sequence);
            action["trading_day"] = json!("2026-10-19");
            action["day_index"] = json!(1);
            action["op"] = json!("VALUATION");
            action["payload"] = payload;
            execution.apply(&action)?;
        }
        self.next += 1;
        self.phases.process(input, execution)
    }
    fn end_input(&mut self, execution: &mut Candidate) -> Result<Value, Error> {
        self.phases.end_input(execution)
    }
    fn cancel_input(&mut self, execution: &mut Candidate) -> Result<Value, Error> {
        self.phases.cancel_input(execution)
    }
    fn quiescent(&self) -> Result<bool, Error> {
        self.phases.quiescent()
    }
}
#[test]
fn zero_effect_opening_steps_restart_without_a_checkpoint_and_terminal_forces_head() {
    let root = root("sparse-empty-restart");
    let mut run = RunLoop::create(&root, spec(), inputs(), Phases::new()).unwrap();
    run.step().unwrap();
    assert!(
        checkpoint_rows(&root).is_empty(),
        "a no-effect OPEN is already durable in the Replay journal"
    );
    let trace = run.trace().unwrap();
    drop(run);
    let bytes = std::fs::read(root.join("runtime.sqlite3")).unwrap();
    assert!(
        onlyalpha_runtime::VerifiedReplaySnapshot::read(
            &root,
            configuration(),
            &"e".repeat(64)
        )
        .is_err(),
        "source observation still requires an actual head checkpoint"
    );
    assert_eq!(std::fs::read(root.join("runtime.sqlite3")).unwrap(), bytes);
    let mut run = RunLoop::open(&root, spec(), inputs(), Phases::new()).unwrap();
    assert_eq!(run.trace().unwrap(), trace);
    run.run().unwrap();
    assert!(checkpoint_rows(&root).is_empty());
    run.close_input().unwrap();
    assert_eq!(
        checkpoint_rows(&root)
            .iter()
            .map(|row| row.0)
            .collect::<Vec<_>>(),
        [0]
    );
    run.terminate("COMPLETED", None).unwrap();
    let result = run.result().unwrap();
    drop(run);
    let source = onlyalpha_runtime::VerifiedReplaySnapshot::read(
        &root,
        configuration(),
        &"e".repeat(64),
    )
    .unwrap();
    source.verify_cut().unwrap();
    drop(source);
    let reopened = RunLoop::open(&root, spec(), inputs(), Phases::new()).unwrap();
    assert_eq!(reopened.result().unwrap(), result);
    drop(reopened);
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn checkpoint_threshold_uses_actual_execution_and_pending_cut_recovers_the_same_head() {
    let root = root("sparse-actual-threshold");
    let mut run = RunLoop::create(&root, spec(), inputs(), Valuations::new(&[63, 1])).unwrap();
    run.step().unwrap();
    run.step().unwrap();
    assert_eq!(run.state().unwrap()["execution_sequence"], 63);
    assert!(
        checkpoint_rows(&root).is_empty(),
        "63 durable facts have not crossed the fixed threshold"
    );
    run.step().unwrap();
    let error = run
        .step_observed(&mut |phase, _, sequence| {
            if phase == "EXECUTION_READY" && sequence == 64 {
                Err(Error("CUT_BEFORE_SCHEDULED_CHECKPOINT".into()))
            } else {
                Ok(())
            }
        })
        .unwrap_err();
    assert_eq!(error.0, "CUT_BEFORE_SCHEDULED_CHECKPOINT");
    assert!(checkpoint_rows(&root).is_empty());
    drop(run);
    let mut run = RunLoop::open(&root, spec(), inputs(), Valuations::new(&[63, 1])).unwrap();
    assert_eq!(run.state().unwrap()["execution_sequence"], 64);
    assert_eq!(
        checkpoint_rows(&root)
            .iter()
            .map(|row| row.0)
            .collect::<Vec<_>>(),
        [64]
    );
    assert!(!run.step().unwrap());
    assert_eq!(run.deliver(|_| Ok(())).unwrap(), 64);
    run.close_input().unwrap();
    run.terminate("COMPLETED", None).unwrap();
    let result = run.result().unwrap();
    drop(run);
    let source = onlyalpha_runtime::VerifiedReplaySnapshot::read(
        &root,
        configuration(),
        &"e".repeat(64),
    )
    .unwrap();
    assert_eq!(source.records().len(), 64);
    source.verify_cut().unwrap();
    drop(source);
    let reopened = RunLoop::open(&root, spec(), inputs(), Valuations::new(&[63, 1])).unwrap();
    assert_eq!(reopened.result().unwrap(), result);
    drop(reopened);
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn every_forced_control_rechecks_a_corrupt_retained_checkpoint() {
    for control in ["pause", "input-end", "cancel-input", "terminate"] {
        let root = root(&format!("sparse-corrupt-{control}"));
        let mut run = RunLoop::create(&root, spec(), inputs(), Phases::new()).unwrap();
        run.step().unwrap();
        if control == "input-end" {
            run.run().unwrap();
        }
        run.pause().unwrap();
        run.resume().unwrap();
        let corrupted = corrupt_original_checkpoint(&root);
        let refused = match control {
            "pause" => run.pause(),
            "input-end" => run.close_input(),
            "cancel-input" => run.cancel_input(),
            _ => run.terminate("FAILED", Some("CONTROLLED_FAILURE")),
        };
        assert!(
            refused.is_err(),
            "{control} must retain the full owning checkpoint source proof"
        );
        assert_eq!(checkpoint_rows(&root), corrupted);
        drop(run);
        assert!(RunLoop::open(&root, spec(), inputs(), Phases::new()).is_err());
        std::fs::remove_dir_all(root).unwrap();
    }
}
#[test]
fn closed_only_profile_keeps_its_original_checkpoint_frequency() {
    let root = root("sparse-legacy-unchanged");
    let mut run = RunLoop::create(&root, spec(), inputs(), ClosedOnly(Phases::new())).unwrap();
    run.step().unwrap();
    assert_eq!(
        checkpoint_rows(&root)
            .iter()
            .map(|row| row.0)
            .collect::<Vec<_>>(),
        [0]
    );
    assert_eq!(run.trace().unwrap()["binding"]["schema_version"], 1);
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn threshold_save_revalidates_a_corrupt_older_checkpoint_without_replacing_it() {
    let root = root("sparse-corrupt-threshold");
    let mut run = RunLoop::create(&root, spec(), inputs(), Valuations::new(&[63, 2])).unwrap();
    run.step().unwrap();
    run.step().unwrap();
    run.pause().unwrap();
    run.resume().unwrap();
    let corrupted = corrupt_original_checkpoint(&root);
    assert_eq!(corrupted[0].0, 63);
    run.step().unwrap();
    let error = run.step().unwrap_err();
    assert!(
        error.0.contains("CHECKPOINT_SOURCE_OR_COMPONENTS"),
        "{error}"
    );
    assert_eq!(checkpoint_rows(&root), corrupted);
    drop(run);
    assert!(RunLoop::open(&root, spec(), inputs(), Valuations::new(&[63, 2])).is_err());
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn terminal_control_forces_a_current_head_below_the_next_periodic_checkpoint() {
    let root = root("sparse-forced-terminal-head");
    let mut run = RunLoop::create(&root, spec(), inputs(), Valuations::new(&[1, 0])).unwrap();
    run.step().unwrap();
    run.step().unwrap();
    assert!(checkpoint_rows(&root).is_empty());
    assert_eq!(run.deliver(|_| Ok(())).unwrap(), 1);
    run.terminate("FAILED", Some("CONTROLLED_FAILURE")).unwrap();
    assert_eq!(
        checkpoint_rows(&root)
            .iter()
            .map(|row| row.0)
            .collect::<Vec<_>>(),
        [1]
    );
    let result = run.result().unwrap();
    drop(run);
    let source = onlyalpha_runtime::VerifiedReplaySnapshot::read(
        &root,
        configuration(),
        &"e".repeat(64),
    )
    .unwrap();
    assert_eq!(source.records().len(), 1);
    source.verify_cut().unwrap();
    drop(source);
    let reopened = RunLoop::open(&root, spec(), inputs(), Valuations::new(&[1, 0])).unwrap();
    assert_eq!(reopened.result().unwrap(), result);
    drop(reopened);
    std::fs::remove_dir_all(root).unwrap();
}

// Observer callbacks are explicit source-taint boundaries. These faults retain
// valid canonical hashes, so a cached or merely syntactic cut cannot reject them.
fn operation_cut_rows(root: &std::path::Path) -> Vec<(i64, String, String, i64)> {
    let db = rusqlite::Connection::open_with_flags(
        root.join("runtime.sqlite3"),
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    )
    .unwrap();
    let mut query = db
        .prepare("SELECT sequence,payload,digest,ready FROM replay_steps ORDER BY sequence")
        .unwrap();
    query
        .query_map([], |row| {
            Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?))
        })
        .unwrap()
        .collect::<rusqlite::Result<Vec<_>>>()
        .unwrap()
}
fn operation_cut_rehash(root: &std::path::Path, index: u64) {
    use base64::{Engine, engine::general_purpose::STANDARD};
    let db = rusqlite::Connection::open(root.join("runtime.sqlite3")).unwrap();
    assert_eq!(
        db.query_row("PRAGMA user_version", [], |row| row.get::<_, i64>(0))
            .unwrap(),
        4
    );
    let mut previous: String = db
        .query_row(
            "SELECT digest FROM replay_binding WHERE singleton=1",
            [],
            |row| row.get(0),
        )
        .unwrap();
    let mut changed = false;
    let mut old_bases = std::collections::BTreeMap::<i64, Vec<u8>>::new();
    let mut new_bases = std::collections::BTreeMap::<i64, (Vec<u8>, String, String)>::new();
    for (sequence, raw, _, _) in operation_cut_rows(root) {
        let mut frame: Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(frame["codec"], "ZSTD_CANONICAL_JSON_DICTIONARY_V1");
        let compressed = STANDARD.decode(frame["data"].as_str().unwrap()).unwrap();
        let base = (sequence - 1) / 16 * 16 + 1;
        let dictionary = if sequence == base {
            &[][..]
        } else {
            old_bases[&base].as_slice()
        };
        let decoded = zstd::bulk::Decompressor::with_dictionary(dictionary)
            .unwrap()
            .decompress(&compressed, 8 * 1024 * 1024)
            .unwrap();
        if sequence == base {
            old_bases.insert(sequence, decoded.clone());
        }
        assert_eq!(
            decoded.len() as u64,
            frame["logical_size"].as_u64().unwrap()
        );
        assert_eq!(
            onlyalpha_execution::digest(&decoded),
            frame["logical_sha256"]
        );
        let mut step: Value = serde_json::from_slice(&decoded).unwrap();
        if sequence as u64 == index {
            step["cause"]["processing"]["processing"]["phase"] = json!("FOREIGN_CAUSAL_OUTPUT");
            changed = true;
        }
        step["previous"] = json!(previous);
        let logical = step.to_string();
        previous = onlyalpha_execution::digest(logical.as_bytes());
        let dictionary = if sequence == base {
            &[][..]
        } else {
            new_bases[&base].0.as_slice()
        };
        let encoded = zstd::bulk::Compressor::with_dictionary(1, dictionary)
            .unwrap()
            .compress(logical.as_bytes())
            .unwrap();
        frame["basis"] = if sequence == base {
            Value::Null
        } else {
            json!({"sequence":base,"physical_sha256":new_bases[&base].1,"logical_sha256":new_bases[&base].2})
        };
        frame["data"] = json!(STANDARD.encode(encoded));
        frame["logical_sha256"] = json!(previous);
        frame["logical_size"] = json!(logical.len());
        frame["summary"] = json!({"kind":"REPLAY_STEP","index":step["index"],"previous":step["previous"],"execution_start":step["execution_start"],"input_fingerprints":step["inputs"].as_array().unwrap().iter().map(|input|onlyalpha_execution::digest(input.to_string().as_bytes())).collect::<Vec<_>>()});
        let encoded = frame.to_string();
        let physical = onlyalpha_execution::digest(encoded.as_bytes());
        if sequence == base {
            new_bases.insert(
                sequence,
                (logical.into_bytes(), physical.clone(), previous.clone()),
            );
        }
        db.execute(
            "UPDATE replay_steps SET payload=?1,digest=?2 WHERE sequence=?3",
            rusqlite::params![encoded, physical, sequence],
        )
        .unwrap();
    }
    assert!(changed);
    db.execute(
        "UPDATE replay_binding SET last_hash=?1 WHERE singleton=1",
        [previous],
    )
    .unwrap();
}
// A rehashed causal attack must remain valid physical codec/lineage input;
// refusal must come from the original participant derivation, not bad framing.
fn operation_cut_structurally_valid(root: &std::path::Path) {
    let runtime =
        onlyalpha_runtime::Runtime::open(root, configuration(), &"e".repeat(64))
            .unwrap();
    let refs = runtime.replay_refs().unwrap();
    for reference in refs {
        runtime
            .read_replay_step(&reference)
            .expect("a complete correctly resealed but causally foreign Step");
    }
}

#[test]
fn before_prepare_callback_cannot_replace_the_previously_checked_replay_prefix() {
    let root = root("operation-cut-before-prepare");
    let mut run = RunLoop::create(&root, spec(), inputs(), Phases::new()).unwrap();
    run.step().unwrap();
    let error = run
        .step_observed(&mut |phase, _, _| {
            if phase == "BEFORE_PREPARE" {
                operation_cut_rehash(&root, 1);
            }
            Ok(())
        })
        .unwrap_err();
    assert!(
        error.0.contains("PRECONDITION") || error.0.contains("RECOVERY"),
        "{error}"
    );
    let rows = operation_cut_rows(&root);
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].3, 1);
    assert!(run.trace().is_err());
    drop(run);
    operation_cut_structurally_valid(&root);
    assert!(RunLoop::open(&root, spec(), inputs(), Phases::new()).is_err());
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn prepared_callback_cannot_rehash_a_different_pending_proposal_into_ready() {
    let root = root("operation-cut-prepared");
    let mut run = RunLoop::create(&root, spec(), inputs(), Phases::new()).unwrap();
    run.step().unwrap();
    let result = run.step_observed(&mut |phase, index, _| {
        if phase == "PREPARED" {
            operation_cut_rehash(&root, index);
        }
        Ok(())
    });
    assert!(
        result.is_err(),
        "a fresh but different causal proposal must not be completed"
    );
    let rows = operation_cut_rows(&root);
    assert_eq!(rows.len(), 2);
    assert_eq!(
        rows[1].3, 0,
        "reject the changed proposal before Ready is written"
    );
    assert!(run.trace().is_err());
    drop(run);
    operation_cut_structurally_valid(&root);
    assert!(RunLoop::open(&root, spec(), inputs(), Phases::new()).is_err());
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn execution_ready_callback_cannot_substitute_the_original_pending_proposal() {
    let root = root("operation-cut-execution-proposal");
    let mut run = RunLoop::create(&root, spec(), inputs(), Valuations::new(&[1, 0])).unwrap();
    run.step().unwrap();
    let result = run.step_observed(&mut |phase, index, _| {
        if phase == "EXECUTION_READY" {
            operation_cut_rehash(&root, index);
        }
        Ok(())
    });
    assert!(
        result.is_err(),
        "a valid Execution prefix does not authenticate a substituted Replay cause"
    );
    let rows = operation_cut_rows(&root);
    assert_eq!(rows.len(), 2);
    assert_eq!(rows[1].3, 0);
    assert!(run.state().is_err());
    drop(run);
    operation_cut_structurally_valid(&root);
    assert!(RunLoop::open(&root, spec(), inputs(), Valuations::new(&[1, 0])).is_err());
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn execution_ready_callback_source_corruption_is_not_hidden_by_an_operation_cut() {
    let root = root("operation-cut-execution-source");
    let mut run = RunLoop::create(&root, spec(), inputs(), Valuations::new(&[1, 0])).unwrap();
    run.step().unwrap();
    let result = run.step_observed(&mut |phase, _, sequence| {
        if phase == "EXECUTION_READY" {
            let sequence = i64::try_from(sequence).unwrap();
            let db = rusqlite::Connection::open(root.join("runtime.sqlite3")).unwrap();
            // The immutable complete Prepared frame stays valid; only the
            // actual monotone owner flags are corrupted at this callback.
            assert_eq!(
                db.query_row("PRAGMA user_version", [], |row| row.get::<_, i64>(0))
                    .unwrap(),
                4
            );
            db.execute(
                "UPDATE records SET ready=0,delivered=0 WHERE sequence=?1",
                [sequence],
            )
            .unwrap();
        }
        Ok(())
    });
    assert!(result.is_err());
    assert_eq!(operation_cut_rows(&root)[1].3, 0);
    assert!(run.progress().is_err());
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn zero_plan_step_refuses_execution_history_changed_after_prepare() {
    let root = root("operation-cut-zero-plan-execution");
    let mut run = RunLoop::create(&root, spec(), inputs(), Valuations::new(&[1, 0])).unwrap();
    assert!(run.step().unwrap());
    assert!(run.step().unwrap());
    assert_eq!(run.deliver(|_| Ok(())).unwrap(), 1);
    let result = run.step_observed(&mut |phase, index, _| {
        assert_ne!(phase, "EXECUTION_READY");
        if phase == "PREPARED" {
            assert_eq!(index, 3);
            let db = rusqlite::Connection::open(root.join("runtime.sqlite3")).unwrap();
            assert_eq!(
                db.execute("UPDATE records SET ready=0,delivered=0 WHERE sequence=1", [])
                    .unwrap(),
                1
            );
        }
        Ok(())
    });
    assert!(result.is_err());
    assert_eq!(operation_cut_rows(&root)[2].3, 0);
    assert!(run.progress().is_err());
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn completed_operation_cannot_supply_a_source_proof_to_a_later_public_call() {
    let root = root("operation-cut-next-public");
    let mut run = RunLoop::create(&root, spec(), inputs(), Phases::new()).unwrap();
    run.step().unwrap();
    operation_cut_rehash(&root, 1);
    assert!(run.progress().is_err());
    assert!(run.trace().is_err());
    assert!(run.step().is_err());
    assert_eq!(operation_cut_rows(&root).len(), 1);
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn completion_requires_actual_post_update_readback_before_installing_the_rows() {
    let root = root("operation-cut-post-readback");
    let mut run = RunLoop::create(&root, spec(), inputs(), Phases::new()).unwrap();
    let result=run.step_observed(&mut |phase,_,_|{
        if phase=="PREPARED" {
            let db=rusqlite::Connection::open(root.join("runtime.sqlite3")).unwrap();
            db.execute_batch("CREATE TRIGGER operation_cut_fault AFTER UPDATE OF ready ON replay_steps WHEN NEW.ready=1 BEGIN UPDATE replay_steps SET ready=0 WHERE sequence=NEW.sequence; END").unwrap();
        }Ok(())
    });
    assert!(result.is_err());
    assert_eq!(operation_cut_rows(&root)[0].3, 0);
    assert!(run.trace().is_err());
    drop(run);
    let db = rusqlite::Connection::open(root.join("runtime.sqlite3")).unwrap();
    db.execute_batch("DROP TRIGGER operation_cut_fault")
        .unwrap();
    drop(db);
    let reopened = RunLoop::open(&root, spec(), inputs(), Phases::new()).unwrap();
    assert_eq!(reopened.trace().unwrap()["steps"][0]["ready"], true);
    drop(reopened);
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn original_operation_recovers_after_every_observer_error_without_duplicate_effects() {
    for barrier in [
        "BEFORE_PREPARE",
        "PREPARED",
        "EXECUTION_READY",
        "STEP_READY",
    ] {
        let root = root(&format!("operation-cut-unknown-{barrier}"));
        let mut run = RunLoop::create(&root, spec(), inputs(), Valuations::new(&[1, 0])).unwrap();
        run.step().unwrap();
        let result = run.step_observed(&mut |phase, _, _| {
            if phase == barrier {
                Err(Error("CONTROLLED_OBSERVER_UNKNOWN".into()))
            } else {
                Ok(())
            }
        });
        assert_eq!(result.unwrap_err().0, "CONTROLLED_OBSERVER_UNKNOWN");
        assert!(run.trace().is_err());
        drop(run);
        let mut run = RunLoop::open(&root, spec(), inputs(), Valuations::new(&[1, 0])).unwrap();
        run.run().unwrap();
        assert_eq!(run.state().unwrap()["execution_sequence"], 1);
        let trace = run.trace().unwrap();
        assert_eq!(trace["steps"].as_array().unwrap().len(), 4);
        assert!(
            trace["steps"]
                .as_array()
                .unwrap()
                .iter()
                .all(|row| row["ready"] == true)
        );
        assert_eq!(
            trace["steps"]
                .as_array()
                .unwrap()
                .iter()
                .map(|row| row["step"]["inputs"].as_array().unwrap().len())
                .sum::<usize>(),
            1
        );
        assert_eq!(run.deliver(|_| Ok(())).unwrap(), 1);
        assert_eq!(run.deliver(|_| Ok(())).unwrap(), 0);
        drop(run);
        std::fs::remove_dir_all(root).unwrap();
    }
}

// A participant method has no purity contract. This controlled fault changes
// its answer only before the actual derivation owner is entered.
struct OpeningSelectionFault {
    phases: Phases,
    before_derivation: std::rc::Rc<std::cell::Cell<bool>>,
}
impl Participants for OpeningSelectionFault {
    fn binding(&self) -> Value {
        self.phases.binding()
    }
    fn capture(&mut self) -> Result<Value, Error> {
        self.phases.capture()
    }
    fn restore(&mut self, v: &Value) -> Result<(), Error> {
        self.phases.restore(v)
    }
    fn process(&mut self, input: &MarketInput, execution: &mut Candidate) -> Result<Value, Error> {
        self.phases.process(input, execution)
    }
    fn opening_phase(&self) -> bool {
        !self.before_derivation.get()
    }
    fn opening(&mut self, input: &OpeningInput, execution: &mut Candidate) -> Result<Value, Error> {
        self.phases.opening(input, execution)
    }
    fn quiescent(&self) -> Result<bool, Error> {
        self.phases.quiescent()
    }
    fn validate_execution(&self, execution: &Candidate) -> Result<(), Error> {
        self.before_derivation.set(false);
        self.phases.validate_execution(execution)
    }
}
#[test]
fn checked_opening_binding_selects_the_next_step_without_a_dynamic_participant_decision() {
    let root = root("operation-cut-opening-selection");
    let before_derivation = std::rc::Rc::new(std::cell::Cell::new(false));
    let participants = OpeningSelectionFault {
        phases: Phases::new(),
        before_derivation: before_derivation.clone(),
    };
    let mut run = RunLoop::create(&root, spec(), inputs(), participants).unwrap();
    before_derivation.set(true);
    assert!(
        run.step()
            .expect("the immutable opening profile must determine the first step")
    );
    let trace = run.trace().unwrap();
    assert_eq!(trace["steps"][0]["step"]["cause"]["kind"], "OPEN");
    assert_eq!(trace["state"]["phase"], "CLOSE");
    assert_eq!(trace["state"]["cursor"], 0);
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn final_step_ready_callback_cannot_return_success_for_a_resealed_foreign_source() {
    let root = root("operation-cut-step-ready-source");
    let mut run = RunLoop::create(&root, spec(), inputs(), Phases::new()).unwrap();
    let result = run.step_observed(&mut |phase, index, _| {
        if phase == "STEP_READY" {
            operation_cut_rehash(&root, index);
        }
        Ok(())
    });
    assert!(
        result.is_err(),
        "the same public operation must reject a source changed by its last outward observer"
    );
    let rows = operation_cut_rows(&root);
    assert_eq!(rows.len(), 1);
    assert_eq!(
        rows[0].3, 1,
        "the original accepted effect is retained; this is not a rollback"
    );
    assert!(run.progress().is_err());
    drop(run);
    operation_cut_structurally_valid(&root);
    assert!(RunLoop::open(&root, spec(), inputs(), Phases::new()).is_err());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn accepted_event_ack_remains_durable_but_delivery_refuses_a_callback_changed_replay() {
    let root = root("operation-cut-delivery-source");
    let mut run = RunLoop::create(&root, spec(), inputs(), Valuations::new(&[1, 0])).unwrap();
    run.step().unwrap();
    run.step().unwrap();
    let original = || {
        let db = rusqlite::Connection::open_with_flags(
            root.join("runtime.sqlite3"),
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
        )
        .unwrap();
        let mut query = db
            .prepare("SELECT input_id,digest FROM records ORDER BY sequence")
            .unwrap();
        query
            .query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
            })
            .unwrap()
            .collect::<rusqlite::Result<Vec<_>>>()
            .unwrap()
    };
    let before = original();
    assert_eq!(before.len(), 1);
    let mut accepted = Vec::new();
    let result = run.deliver(|event| {
        accepted.push(event.clone());
        operation_cut_rehash(&root, 1);
        Ok(())
    });
    assert!(
        result.is_err(),
        "the delivery operation itself must refuse a callback-changed replay cut"
    );
    assert_eq!(accepted.len(), 1);
    assert_eq!(
        original(),
        before,
        "no new Execution, input identity or immutable payload is allocated"
    );
    {
        let db = rusqlite::Connection::open_with_flags(
            root.join("runtime.sqlite3"),
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
        )
        .unwrap();
        assert_eq!(
            db.query_row(
                "SELECT ready,delivered FROM records WHERE sequence=1",
                [],
                |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?))
            )
            .unwrap(),
            (1, 1),
            "the already accepted original Event stays acknowledged"
        );
    }
    assert!(run.progress().is_err());
    drop(run);
    let runtime =
        onlyalpha_runtime::Runtime::open(&root, configuration(), &"e".repeat(64))
            .unwrap();
    assert_eq!(runtime.records().unwrap().len(), 1);
    assert!(runtime.pending_events().unwrap().is_empty());
    drop(runtime);
    operation_cut_structurally_valid(&root);
    assert!(RunLoop::open(&root, spec(), inputs(), Valuations::new(&[1, 0])).is_err());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn delivery_source_failure_requires_explicit_recovery_even_after_original_bytes_return() {
    let root = root("operation-cut-delivery-sticky-recovery");
    let mut run = RunLoop::create(&root, spec(), inputs(), Valuations::new(&[1, 0])).unwrap();
    run.step().unwrap();
    run.step().unwrap();
    let rows = operation_cut_rows(&root);
    let last: String = {
        let db = rusqlite::Connection::open(root.join("runtime.sqlite3")).unwrap();
        db.query_row(
            "SELECT last_hash FROM replay_binding WHERE singleton=1",
            [],
            |row| row.get(0),
        )
        .unwrap()
    };
    let mut accepted = 0;
    assert!(
        run.deliver(|_| {
            accepted += 1;
            operation_cut_rehash(&root, 1);
            Ok(())
        })
        .is_err()
    );
    assert_eq!(accepted, 1);
    // Restore only this controlled source fault. The actual accepted Event's
    // acknowledgement is intentionally not rolled back with the Replay bytes.
    {
        let mut db = rusqlite::Connection::open(root.join("runtime.sqlite3")).unwrap();
        let tx = db.transaction().unwrap();
        for (sequence, payload, digest, ready) in rows {
            tx.execute(
                "UPDATE replay_steps SET payload=?1,digest=?2,ready=?3 WHERE sequence=?4",
                rusqlite::params![payload, digest, ready, sequence],
            )
            .unwrap();
        }
        tx.execute(
            "UPDATE replay_binding SET last_hash=?1 WHERE singleton=1",
            [last],
        )
        .unwrap();
        tx.commit().unwrap();
        assert_eq!(
            db.query_row(
                "SELECT ready,delivered FROM records WHERE sequence=1",
                [],
                |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?))
            )
            .unwrap(),
            (1, 1)
        );
    }
    assert_eq!(
        run.progress().unwrap_err().0,
        "BACKTEST_REPLAY_RECOVERY_REQUIRED",
        "restored bytes cannot silently reopen a session after an unknown source cut"
    );
    run.recover().unwrap();
    assert_eq!(run.state().unwrap()["execution_sequence"], 1);
    assert_eq!(
        run.deliver(|_| {
            accepted += 1;
            Ok(())
        })
        .unwrap(),
        0
    );
    assert_eq!(
        accepted, 1,
        "the accepted original Event is never emitted under another identity or blindly repeated"
    );
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn empty_delivery_keeps_the_actual_replay_cut_without_calling_or_acknowledging_a_consumer() {
    let root = root("empty-delivery-actual-source");
    let mut run = RunLoop::create(&root, spec(), inputs(), Phases::new()).unwrap();
    run.step().unwrap();
    let original = operation_cut_rows(&root);
    let mut calls = 0;
    assert_eq!(
        run.deliver(|_| {
            calls += 1;
            Ok(())
        })
        .unwrap(),
        0
    );
    assert_eq!(calls, 0);
    assert_eq!(operation_cut_rows(&root), original);
    operation_cut_rehash(&root, 1);
    assert!(
        run.deliver(|_| {
            calls += 1;
            Ok(())
        })
        .is_err()
    );
    assert_eq!(
        calls, 0,
        "empty delivery must not hide a later fully resealed foreign prefix"
    );
    drop(run);
    assert!(RunLoop::open(&root, spec(), inputs(), Phases::new()).is_err());
    std::fs::remove_dir_all(root).unwrap();
}


fn actual_execution_rows(root: &std::path::Path) -> Vec<(i64, String, String, i64, i64)> {
    let db = rusqlite::Connection::open_with_flags(root.join("runtime.sqlite3"),
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
    let mut query = db.prepare("SELECT sequence,payload,digest,ready,delivered FROM records ORDER BY sequence").unwrap();
    query.query_map([], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?)))
        .unwrap().collect::<rusqlite::Result<Vec<_>>>().unwrap()
}

#[test]
fn combined_step_delivery_matches_original_bytes_events_cursor_and_economics() {
    let separate_root = root("combined-separate-equivalence");
    let combined_root = root("combined-equivalence");
    let mut separate = RunLoop::create(&separate_root, spec(), inputs(), Valuations::new(&[1, 1])).unwrap();
    let mut combined = RunLoop::create(&combined_root, spec(), inputs(), Valuations::new(&[1, 1])).unwrap();
    let mut expected_events = Vec::new();
    let mut actual_events = Vec::new();
    for _ in 0..5 {
        let expected_advanced = separate.step().unwrap();
        let expected_delivered = separate.deliver(|event| {expected_events.push(event.clone()); Ok(())}).unwrap();
        let observed = combined.step_and_deliver(|event| {actual_events.push(event.clone()); Ok(())}).unwrap();
        assert_eq!(observed, (expected_advanced, expected_delivered));
        assert_eq!(actual_events, expected_events);
        assert_eq!(combined.trace().unwrap(), separate.trace().unwrap());
        assert_eq!(combined.state().unwrap(), separate.state().unwrap());
        assert_eq!(actual_execution_rows(&combined_root), actual_execution_rows(&separate_root));
        assert_eq!(operation_cut_rows(&combined_root), operation_cut_rows(&separate_root));
    }
    separate.close_input().unwrap(); combined.close_input().unwrap();
    separate.deliver(|_| Ok(())).unwrap(); combined.deliver(|_| Ok(())).unwrap();
    separate.finish_input().unwrap(); combined.finish_input().unwrap();
    assert_eq!(combined.result().unwrap(), separate.result().unwrap());
    drop(separate); drop(combined);
    std::fs::remove_dir_all(separate_root).unwrap();
    std::fs::remove_dir_all(combined_root).unwrap();
}

#[test]
fn combined_empty_step_calls_no_consumer_and_exhausted_step_still_drains_old_events() {
    let empty_root = root("combined-empty-consumer");
    let mut empty = RunLoop::create(&empty_root, spec(), inputs(), Phases::new()).unwrap();
    for _ in 0..4 {
        assert_eq!(empty.step_and_deliver(|_| panic!("empty source invoked consumer")).unwrap(), (true, 0));
    }
    assert_eq!(empty.step_and_deliver(|_| panic!("empty source invoked consumer")).unwrap(), (false, 0));
    drop(empty); std::fs::remove_dir_all(empty_root).unwrap();
    let pending_root = root("combined-exhausted-old-pending");
    let mut pending = RunLoop::create(&pending_root, spec(), inputs(), Valuations::new(&[1, 0])).unwrap();
    pending.run().unwrap();
    assert_eq!(pending.step_and_deliver(|_| Ok(())).unwrap(), (false, 1));
    assert_eq!(pending.deliver(|_| Ok(())).unwrap(), 0);
    drop(pending); std::fs::remove_dir_all(pending_root).unwrap();
}

#[test]
fn combined_final_completion_cut_refuses_actual_missing_corrupt_flags_and_replay_history() {
    for (name, fault) in [
        ("missing", "DELETE FROM records WHERE sequence=1"),
        ("corrupt", "UPDATE records SET payload='{}' WHERE sequence=1"),
        ("flags", "UPDATE records SET ready=0,delivered=0 WHERE sequence=1"),
        ("replay", "UPDATE replay_steps SET payload='{}' WHERE sequence=1"),
    ] {
        let selected = root(&format!("combined-postwrite-{name}"));
        let mut run = RunLoop::create(&selected, spec(), inputs(), Valuations::new(&[1, 0])).unwrap();
        assert!(run.step().unwrap());
        let db = rusqlite::Connection::open(selected.join("runtime.sqlite3")).unwrap();
        db.execute_batch(&format!("CREATE TRIGGER controlled_source_fault AFTER UPDATE OF ready ON replay_steps WHEN NEW.sequence=2 AND NEW.ready=1 BEGIN {fault}; END;")).unwrap();
        drop(db);
        let result = run.step_and_deliver(|_| panic!("corrupt final cut invoked consumer"));
        assert!(matches!(result, Err(onlyalpha_backtest::StepAndDeliverError::Step(_))), "{name}");
        assert!(run.progress().is_err(), "failed final cut must require original recovery: {name}");
        drop(run); std::fs::remove_dir_all(selected).unwrap();
    }
}

#[test]
fn combined_consumer_failure_keeps_pending_and_callback_source_change_keeps_original_ack() {
    for corrupt in [false, true] {
        let selected = root(&format!("combined-consumer-{corrupt}"));
        let mut run = RunLoop::create(&selected, spec(), inputs(), Valuations::new(&[1, 0])).unwrap();
        assert!(run.step().unwrap());
        let mut accepted = Vec::new();
        let result = run.step_and_deliver(|event| {
            accepted.push(event.clone());
            if corrupt { operation_cut_rehash(&selected, 1); Ok(()) }
            else { Err(Error("CONTROLLED_CONSUMER_UNKNOWN".into())) }
        });
        assert!(matches!(result, Err(onlyalpha_backtest::StepAndDeliverError::Delivery(_))));
        assert_eq!(accepted.len(), 1);
        let rows = actual_execution_rows(&selected);
        assert_eq!(rows.len(), 1);
        assert_eq!((rows[0].3, rows[0].4), (1, i64::from(corrupt)));
        if corrupt {
            assert!(run.progress().is_err());
        } else {
            assert_eq!(run.progress().unwrap()["cursor"], 1);
            let mut retried = Vec::new();
            assert_eq!(run.deliver(|event| {retried.push(event.clone()); Ok(())}).unwrap(), 1);
            assert_eq!(retried, accepted, "consumer failure must retain the same stable Event");
        }
        drop(run); std::fs::remove_dir_all(selected).unwrap();
    }
}
