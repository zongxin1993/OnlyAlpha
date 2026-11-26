const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[path = "../../execution/tests/support/mod.rs"]
mod support;
use onlyalpha_runtime::{RunBinding, RunConfiguration, Session, TradingInput};
#[allow(dead_code)]
#[path = "support/perpetual_run.rs"]
mod perpetual;
use serde_json::json;

fn session() -> Session {
    let config = RunConfiguration::from_record(support::config()).unwrap();
    let binding =
        RunBinding::new(&config, &"b".repeat(64), &"c".repeat(64), &"d".repeat(64)).unwrap();
    Session::new(&config, &binding).unwrap()
}
#[test]
fn memory_session_executes_the_complete_buy_sell_fee_chain_without_projection_history() {
    let mut s = session();
    let inputs = [
        support::open(1, "BUY"),
        support::stage(2, 1, "UNKNOWN"),
        support::fill(3, 1, "1", "10.00", "1.00"),
        support::fill(4, 1, "3", "10.00", "1.00"),
        support::open(5, "SELL"),
        support::stage(6, 2, "UNKNOWN"),
        support::fill(7, 2, "1", "12.00", "1.00"),
        support::fill(8, 2, "3", "12.00", "1.00"),
    ];
    for (i, input) in inputs.into_iter().enumerate() {
        let event = s.apply(&TradingInput::from_record(input).unwrap()).unwrap();
        assert_eq!(event.sequence(), i as u64 + 1);
        assert_eq!(event.record().get("projections"), None);
        s.acknowledge(event.sequence()).unwrap();
    }
    let state = s.state().unwrap();
    assert_eq!(state["account"]["snapshot"]["cash"], "1006.00");
    assert_eq!(state["account"]["snapshot"]["realized_pnl"], "8.00");
    assert_eq!(
        state["ledger"]["ledgers"]["cluster"]["snapshot"]["cash"],
        "1006.00"
    );
    assert_eq!(s.sequence(), 8);
    assert!(s.pending_events().unwrap().is_empty());
    assert_eq!(s.retained_facts().len(), 8);
    assert!(
        s.retained_facts()
            .iter()
            .all(|e| !e.record().to_string().contains("checkpoint"))
    );
    let completed = s.finish().unwrap();
    assert_eq!(completed.state()["account"]["snapshot"]["cash"], "1006.00");
    assert_eq!(completed.facts().len(), 8);
}
#[test]
fn identical_input_is_idempotent_but_a_conflict_poisoned_session_cannot_finish() {
    let mut s = session();
    let input = TradingInput::from_record(support::open(1, "BUY")).unwrap();
    let first = s.apply(&input).unwrap();
    let before = s.state().unwrap();
    assert_eq!(s.apply(&input).unwrap().record(), first.record());
    assert_eq!(s.sequence(), 1);
    assert_eq!(s.state().unwrap(), before);
    let mut changed = support::open(1, "BUY");
    changed["time"] = json!(99);
    assert_eq!(
        s.apply(&TradingInput::from_record(changed).unwrap())
            .unwrap_err()
            .0,
        "MEMORY_INPUT_CONFLICT"
    );
    assert!(s.state().is_err());
    assert!(
        s.apply(&TradingInput::from_record(support::stage(2, 1, "UNKNOWN")).unwrap())
            .is_err()
    );
    assert!(s.finish().is_err());
}
#[test]
fn incomplete_event_delivery_and_open_risk_cannot_be_completed() {
    let mut s = session();
    s.apply(&TradingInput::from_record(support::open(1, "BUY")).unwrap())
        .unwrap();
    assert!(s.finish().is_err());
    let mut s = session();
    let event = s
        .apply(&TradingInput::from_record(support::open(1, "BUY")).unwrap())
        .unwrap();
    s.acknowledge(event.sequence()).unwrap();
    assert!(s.finish().is_err());
}
#[test]
fn same_run_pins_recompute_exactly_and_configuration_cannot_borrow_another_binding() {
    let mut a = session();
    let mut b = session();
    for input in [
        support::open(1, "BUY"),
        support::stage(2, 1, "UNKNOWN"),
        support::fill(3, 1, "1", "10.00", "1.00"),
        support::terminal(4, 1, "CANCELLED"),
    ] {
        let input = TradingInput::from_record(input).unwrap();
        assert_eq!(
            a.apply(&input).unwrap().record(),
            b.apply(&input).unwrap().record()
        );
    }
    assert_eq!(a.state().unwrap(), b.state().unwrap());
    let config = RunConfiguration::from_record(support::config()).unwrap();
    let binding =
        RunBinding::new(&config, &"b".repeat(64), &"c".repeat(64), &"d".repeat(64)).unwrap();
    let mut changed = support::config();
    changed["initial_cash"] = json!("999.00");
    changed["capitals"]["cluster"] = json!("999.00");
    assert!(Session::new(&RunConfiguration::from_record(changed).unwrap(), &binding).is_err());
}
#[test]
fn passive_perpetual_facts_cannot_skip_the_original_source_owner() {
    let (config, inputs) = perpetual::scenario();
    let config = RunConfiguration::from_record(config).unwrap();
    let binding =
        RunBinding::new(&config, &"b".repeat(64), &"c".repeat(64), &"d".repeat(64)).unwrap();
    let mut s = Session::new(&config, &binding).unwrap();
    let mark = inputs.into_iter().find(|i| i["op"] == "MARK").unwrap();
    assert_eq!(
        s.apply(&TradingInput::from_record(mark).unwrap())
            .unwrap_err()
            .0,
        "EXECUTION_ORIGINAL_EVIDENCE_REQUIRED"
    );
    assert!(s.finish().is_err());
}
