#[path = "support/memory_signal.rs"]
mod support;
use onlyalpha_calculation_bridge::ProgramNodes;
use onlyalpha_strategy::ResearchRun;
use onlyalpha_strategy::{NodeFailure, NodePort, NodeRequest};
use serde_json::Value;
struct UnavailableFinalState(ProgramNodes, bool);
impl NodePort for UnavailableFinalState {
    fn bindings(&self) -> Vec<onlyalpha_calculation::ExecutionBinding> {
        self.0.bindings()
    }
    fn update(&mut self, input: &NodeRequest) -> Result<Value, NodeFailure> {
        self.0.update(input)
    }
    fn capture(&mut self) -> Result<Value, NodeFailure> {
        if self.1 {
            return Err(NodeFailure::Unknown);
        }
        self.1 = true;
        self.0.capture()
    }
    fn restore_candidate(&self, value: &Value) -> Result<Self, NodeFailure> {
        self.0
            .restore_candidate(value)
            .map(|node| Self(node, false))
    }
}
#[test]
fn same_private_program_and_graph_have_exact_batch_event_raw_signals() {
    let rows = ["1.00", "3.00", "5.00", "1.00", "0.00"]
        .iter()
        .enumerate()
        .map(|(i, p)| support::bar(i as u64 + 1, p))
        .collect::<Vec<_>>();
    let completed = ResearchRun::new(support::executor(), rows.clone())
        .unwrap()
        .run()
        .unwrap();
    let mut event = onlyalpha_strategy::SignalExecution::new(support::executor());
    for (i, bar) in rows.iter().enumerate() {
        assert_eq!(
            event.process(bar).unwrap().to_record(),
            completed.signals()[i]
        );
    }
    assert_eq!(completed.signals()[0]["status"], "BLOCKED");
    assert_eq!(completed.signals()[2]["decision"]["entry"], true);
    assert_eq!(completed.signals()[4]["decision"]["exit"], true);
    assert_eq!(completed.calculations().len(), rows.len());
    let numeric = completed.calculations()[1]
        .as_array()
        .unwrap()
        .iter()
        .find(|n| n["outputs"]["value"]["type"] == "DECIMAL")
        .unwrap();
    assert_eq!(numeric["outputs"]["value"]["value"], "2");
}
#[test]
fn actual_values_cannot_complete_when_the_final_owner_state_is_unavailable() {
    let (program, nodes) = support::parts();
    let executor =
        onlyalpha_strategy::Executor::new(program, UnavailableFinalState(nodes, false)).unwrap();
    let rows = (1..=3).map(|i| support::bar(i, "3.00")).collect();
    assert!(ResearchRun::new(executor, rows).unwrap().run().is_err());
}
#[test]
fn original_native_program_checkpoint_restores_exactly_and_missing_window_is_rejected() {
    let mut executor = support::executor();
    for i in 1..=3 {
        let bar = support::bar(i, "3.00");
        executor
            .process(
                &bar,
                &onlyalpha_domain::time::OnlyTimestamp::from_datetime(*bar.ts_init()),
                &"d".repeat(64),
            )
            .unwrap();
    }
    let checkpoint = executor.capture_checkpoint().unwrap();
    let bytes = checkpoint.to_string().into_bytes();
    let mut restored = executor
        .restored_candidate(&bytes, &onlyalpha_strategy::record_fingerprint(&checkpoint))
        .unwrap();
    let bar = support::bar(4, "5.00");
    let time = onlyalpha_domain::time::OnlyTimestamp::from_datetime(*bar.ts_init());
    assert_eq!(
        executor
            .process(&bar, &time, &"d".repeat(64))
            .unwrap()
            .to_record(),
        restored
            .process(&bar, &time, &"d".repeat(64))
            .unwrap()
            .to_record()
    );
    let mut missing = checkpoint;
    let node = missing["port"]["nodes"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|r| r[1]["plugin_state"]["definition"]["kind"] == "FACTOR")
        .unwrap();
    node[1]["plugin_state"]["state"] = Value::Null;
    node[1]["state_fingerprint"] = serde_json::json!(onlyalpha_strategy::record_fingerprint(
        &node[1]["plugin_state"]
    ));
    let bytes = missing.to_string().into_bytes();
    assert!(
        executor
            .restored_candidate(&bytes, &onlyalpha_strategy::record_fingerprint(&missing))
            .is_err()
    );
}

#[test]
fn finite_research_refuses_hidden_warmup_and_restored_signal_history() {
    use onlyalpha_domain::time::OnlyTimestamp;
    let earlier = support::bar(1, "99.00");
    let inputs = (2..=5).map(|n| support::bar(n, "1.00")).collect::<Vec<_>>();
    assert!(ResearchRun::new(support::executor(), inputs.clone()).is_ok());
    let mut warmed = support::executor();
    warmed
        .process(
            &earlier,
            &OnlyTimestamp::from_datetime(*earlier.ts_init()),
            &"a".repeat(64),
        )
        .unwrap();
    let checkpoint = warmed.capture_checkpoint().unwrap();
    let restored = support::executor()
        .restored_candidate(
            checkpoint.to_string().as_bytes(),
            &onlyalpha_strategy::record_fingerprint(&checkpoint),
        )
        .unwrap();
    assert!(
        ResearchRun::new(warmed, inputs.clone()).is_err(),
        "a hidden warmup prefix is not a frozen input"
    );
    assert!(
        ResearchRun::new(restored, inputs).is_err(),
        "finite recomputation must start at genesis"
    );
}
