use super::*;
use crate::support;

fn binding() -> TradingBinding {
    let mut configuration = support::config();
    configuration["runtime_kind"] = json!("SIM");
    TradingBinding::new(
        RunConfiguration::from_record(configuration).unwrap(),
        &"b".repeat(64),
    )
    .unwrap()
}

fn sim(mut input: Value) -> Value {
    input["runtime_kind"] = json!("SIM");
    input
}

fn genesis(binding: &TradingBinding) -> RecoveryFacts {
    RecoveryFacts::from_records(binding, binding.fingerprint(), 0, Vec::new()).unwrap()
}

fn row(facts: &PreparedTradingFacts, ready: bool) -> Record {
    Record::decode(&json!({"schema_version": 1, "prepared": facts.prepared().record(), "ready": ready, "delivered": false})).unwrap()
}

#[test]
fn bindings_reject_finite_work_and_distinguish_changed_pins_from_new_streams() {
    let base = binding();
    assert!(
        TradingBinding::new(
            RunConfiguration::from_record(support::config()).unwrap(),
            base.kernel_artifact()
        )
        .is_err()
    );
    let repinned = TradingBinding::new(base.configuration().clone(), &"c".repeat(64)).unwrap();
    assert_eq!(base.key(), repinned.key());
    assert_ne!(base.fingerprint(), repinned.fingerprint());
    assert!(RecoveryFacts::from_records(&base, repinned.fingerprint(), 0, vec![]).is_err());
    let mut next = base.configuration().record().clone();
    next["generation"] = json!("d".repeat(64));
    let advanced = TradingBinding::new(
        RunConfiguration::from_record(next).unwrap(),
        base.kernel_artifact(),
    )
    .unwrap();
    assert_ne!(base.key(), advanced.key());
}

#[test]
fn committed_unready_recovers_original_projection_without_granting_another_write() {
    let binding = binding();
    let empty = genesis(&binding);
    let facts = empty.prepare(&sim(support::open(1, "BUY"))).unwrap();
    let stored = row(&facts, false);
    let receipt =
        DurableCommitReceipt::from_record(&facts, binding.fingerprint(), &stored).unwrap();
    assert_eq!(receipt.transaction_id(), facts.prepared().id());
    assert_eq!(receipt.sequence(), 1);
    assert!(!receipt.ready());
    let pending =
        RecoveryFacts::from_records(&binding, binding.fingerprint(), 1, vec![stored]).unwrap();
    assert_eq!(pending.unprojected().unwrap().prepared(), facts.prepared());
    let next = sim(support::stage(2, 1, "UNKNOWN"));
    assert!(pending.prepare(&next).is_err());
    let ready =
        RecoveryFacts::from_records(&binding, binding.fingerprint(), 1, vec![row(&facts, true)])
            .unwrap();
    assert_eq!(pending.state().unwrap(), ready.state().unwrap());
    assert_eq!(
        ready.prepare(&next).unwrap().predecessor(),
        Some((
            facts.prepared().id(),
            facts.prepared().payload_fingerprint()
        ))
    );
    assert!(ready.prepare(facts.prepared().input()).is_err());
}

#[test]
fn observation_returns_the_original_ready_or_pending_row_and_detects_conflict() {
    let binding = binding();
    let first_input = sim(support::open(1, "BUY"));
    let second_input = sim(support::stage(2, 1, "UNKNOWN"));
    let first = genesis(&binding).prepare(&first_input).unwrap();
    let one =
        RecoveryFacts::from_records(&binding, binding.fingerprint(), 1, vec![row(&first, true)])
            .unwrap();
    assert!(one.observe_input(&second_input).unwrap().is_none());
    let second = one.prepare(&second_input).unwrap();
    let history = RecoveryFacts::from_records(
        &binding,
        binding.fingerprint(),
        2,
        vec![row(&first, true), row(&second, false)],
    )
    .unwrap();
    let original = history.observe_input(&first_input).unwrap().unwrap();
    assert!(std::ptr::eq(original, &history.records()[0]));
    let pending = history.observe_input(&second_input).unwrap().unwrap();
    assert!(std::ptr::eq(pending, history.unprojected().unwrap()));
    let mut changed = second_input;
    changed["payload"] = Value::Null;
    assert!(matches!(
        history.observe_input(&changed),
        Err(DurabilityError::Rejected(code)) if code == "TRADING_INPUT_CONFLICT"
    ));
}

#[test]
fn observation_rejects_invalid_identity_even_in_an_empty_history() {
    let history = genesis(&binding());
    for input in [
        json!({}),
        json!({"input_id":null}),
        json!({"input_id":7}),
        json!({"input_id":""}),
        json!({"input_id":" a "}),
        json!({"input_id":"a".repeat(257)}),
    ] {
        assert!(matches!(
            history.observe_input(&input),
            Err(DurabilityError::Rejected(_))
        ));
    }
}

#[test]
fn recovery_rejects_a_rehashed_account_projection_unrelated_to_the_original_plan() {
    let binding = binding();
    let facts = genesis(&binding)
        .prepare(&sim(support::open(1, "BUY")))
        .unwrap();
    let mut stored = row(&facts, true).record();
    let body = &mut stored["prepared"];
    let account = &mut body["projections"][2];
    account["result"]["state"]["snapshot"]["cash"] = json!("99999.00");
    account["result_hash"] = json!(fingerprint(&account["result"]));
    body.as_object_mut().unwrap().remove("payload_hash");
    body["payload_hash"] = json!(fingerprint(body));
    let forged = Record::decode(&stored).unwrap();
    assert!(RecoveryFacts::from_records(&binding, binding.fingerprint(), 1, vec![forged]).is_err());
}

#[test]
fn recovery_rejects_missing_or_reordered_rows_and_an_unready_predecessor() {
    let binding = binding();
    let first = genesis(&binding)
        .prepare(&sim(support::open(1, "BUY")))
        .unwrap();
    let one =
        RecoveryFacts::from_records(&binding, binding.fingerprint(), 1, vec![row(&first, true)])
            .unwrap();
    let second = one.prepare(&sim(support::stage(2, 1, "UNKNOWN"))).unwrap();
    let check = |rows| RecoveryFacts::from_records(&binding, binding.fingerprint(), 2, rows);
    assert!(check(vec![row(&first, true)]).is_err());
    assert!(check(vec![row(&second, true), row(&first, true)]).is_err());
    assert!(check(vec![row(&first, false), row(&second, true)]).is_err());
    assert!(check(vec![row(&first, true), row(&second, true)]).is_ok());
    assert!(
        DurableCommitReceipt::from_record(&second, binding.fingerprint(), &row(&first, true))
            .is_err()
    );
    assert!(
        DurableCommitReceipt::from_record(&first, &"c".repeat(64), &row(&first, true)).is_err()
    );
}
