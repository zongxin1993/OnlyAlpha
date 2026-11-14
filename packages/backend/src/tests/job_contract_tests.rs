use crate::application::job_contract::*;
use crate::persistence::backtest_run::RunState;
use serde_json::{Value, json};

fn pin(c: char) -> String {
    c.to_string().repeat(64)
}
fn binding() -> Value {
    json!({
        "schema_version":1,"kind":"BACKTEST",
        "scope":{"namespace":"22222222-2222-4222-8222-222222222222","owner":"human:one","run_id":"11111111-1111-4111-8111-111111111111"},
        "strategy_revision":pin('b'),"signal_graph":pin('c'),
        "factor_bindings":[{"revision":pin('d'),"program":pin('e'),"parameters":pin('f'),"numeric_policy":"DECIMAL28_HALF_EVEN_Q12_V1","certificate":pin('1')}],
        "kernel_artifact":pin('2'),"runtime_generation":pin('3'),"initial_state":pin('4'),
        "execution_configuration":pin('5'),"calendar":pin('6'),"fees":pin('7'),"market_rules":pin('8'),
        "market":{"dataset_snapshot":pin('9'),"source_revision":pin('a'),"bar_semantic":pin('b'),"instruments":["BTCUSDT.BINANCE"],"start_ns":0,"end_ns":60000000000_i64,"versions":[pin('c')],"seals":[pin('d')],"segments":[pin('e')],"rows":2,"warmup_rows":1,"sample_rows":1,"axis":pin('f'),"content":pin('1')},
        "result_plan":{"kind":"BACKTEST","members":[
          {"key":"execution","kind":"EXECUTION_FACTS","schema":pin('2'),"axis":pin('3'),"rows":2},
          {"key":"result","kind":"ECONOMIC_RESULT","schema":pin('4'),"axis":null,"rows":1},
          {"key":"observation","kind":"CLOSE_CURVE","schema":pin('5'),"axis":pin('6'),"rows":1},
          {"key":"causes","kind":"CAUSAL_EVIDENCE","schema":pin('7'),"axis":null,"rows":1}
        ]}
    })
}

#[test]
fn frozen_identity_is_canonical_and_excludes_attempt_metadata() {
    let original = binding();
    let frozen = FrozenJobBinding::from_record(&original).unwrap();
    assert_eq!(
        FrozenJobBinding::from_record(&frozen.record())
            .unwrap()
            .fingerprint(),
        frozen.fingerprint()
    );
    let mut reordered = original.clone();
    reordered["result_plan"]["members"]
        .as_array_mut()
        .unwrap()
        .reverse();
    assert_eq!(
        FrozenJobBinding::from_record(&reordered)
            .unwrap()
            .fingerprint(),
        frozen.fingerprint()
    );
    for field in ["attempt_id", "pid", "host", "elapsed_ms", "created_at"] {
        let mut invalid = original.clone();
        invalid[field] = json!("operational");
        assert!(FrozenJobBinding::from_record(&invalid).is_err(), "{field}");
    }
}

#[test]
fn every_frozen_execution_identity_change_changes_binding() {
    let original = binding();
    let identity = FrozenJobBinding::from_record(&original)
        .unwrap()
        .fingerprint()
        .to_owned();
    for pointer in [
        "/strategy_revision",
        "/signal_graph",
        "/kernel_artifact",
        "/runtime_generation",
        "/initial_state",
        "/execution_configuration",
        "/calendar",
        "/fees",
        "/market_rules",
        "/factor_bindings/0/program",
        "/factor_bindings/0/parameters",
        "/factor_bindings/0/certificate",
        "/market/source_revision",
        "/market/content",
        "/market/axis",
    ] {
        let mut changed = original.clone();
        *changed.pointer_mut(pointer).unwrap() = json!(pin('0'));
        assert_ne!(
            FrozenJobBinding::from_record(&changed)
                .unwrap()
                .fingerprint(),
            identity,
            "{pointer}"
        );
    }
}

#[test]
fn exact_market_slice_rejects_missing_ambiguous_and_overflowing_axes() {
    for (pointer, value) in [
        ("/market/segments", json!([])),
        ("/market/seals", json!([])),
        ("/market/versions", json!([])),
        (
            "/market/instruments",
            json!(["BTCUSDT.BINANCE", "BTCUSDT.BINANCE"]),
        ),
        ("/market/end_ns", json!(0)),
        ("/market/sample_rows", json!(2)),
        ("/market/warmup_rows", json!(u64::MAX)),
        ("/market/content", json!("bad")),
    ] {
        let mut v = binding();
        *v.pointer_mut(pointer).unwrap() = value;
        assert!(FrozenJobBinding::from_record(&v).is_err(), "{pointer}");
    }
}

#[test]
fn result_plan_requires_typed_complete_members_and_exact_job_kind() {
    let original = binding();
    for key in ["execution", "result", "observation", "causes"] {
        let mut v = original.clone();
        v["result_plan"]["members"]
            .as_array_mut()
            .unwrap()
            .retain(|x| x["key"] != key);
        assert!(FrozenJobBinding::from_record(&v).is_err(), "missing {key}");
    }
    let mut v = original.clone();
    v["result_plan"]["members"][0]["axis"] = Value::Null;
    assert!(FrozenJobBinding::from_record(&v).is_err());
    let mut v = original.clone();
    v["result_plan"]["kind"] = json!("RESEARCH");
    assert!(FrozenJobBinding::from_record(&v).is_err());
    let mut v = original;
    let duplicate = v["result_plan"]["members"][0].clone();
    v["result_plan"]["members"]
        .as_array_mut()
        .unwrap()
        .push(duplicate);
    assert!(FrozenJobBinding::from_record(&v).is_err());
}

#[test]
fn exact_certificate_status_is_separate_from_parameter_identity() {
    let request = FactorExecutionBinding::from_record(&binding()["factor_bindings"][0]).unwrap();
    assert_eq!(
        request.check_certificate(BuildStatus::Building, &request),
        Err(ContractError::NotReady)
    );
    assert_eq!(
        request.check_certificate(BuildStatus::Failed, &request),
        Err(ContractError::NotReady)
    );
    assert_eq!(
        request.check_certificate(BuildStatus::Ready, &request),
        Ok(())
    );
    for field in ["revision", "program", "parameters", "certificate"] {
        let mut v = binding()["factor_bindings"][0].clone();
        v[field] = json!(pin('0'));
        let observed = FactorExecutionBinding::from_record(&v).unwrap();
        assert_eq!(
            request.check_certificate(BuildStatus::Ready, &observed),
            Err(ContractError::Mismatch)
        );
    }
    let mut v = binding()["factor_bindings"][0].clone();
    v["numeric_policy"] = json!("DECIMAL38");
    assert!(FactorExecutionBinding::from_record(&v).is_err());
}

#[test]
fn terminal_policy_rejects_partial_cancelled_failed_and_unknown_results() {
    for state in [
        RunState::Queued,
        RunState::Running,
        RunState::CancelRequested,
        RunState::Cancelled,
        RunState::Failed,
    ] {
        assert!(!result_publication_required(state));
        assert_eq!(
            validate_terminal_result(state, true),
            Err(ContractError::UnexpectedResult)
        );
        assert_eq!(validate_terminal_result(state, false), Ok(()));
    }
    assert!(result_publication_required(RunState::Completed));
    assert_eq!(
        validate_terminal_result(RunState::Completed, false),
        Err(ContractError::MissingEvidence)
    );
    assert_eq!(validate_terminal_result(RunState::Completed, true), Ok(()));
    assert_ne!(ContractError::MissingEvidence, ContractError::Unavailable);
    assert_ne!(ContractError::Mismatch, ContractError::OutcomeUnknown);
}

#[test]
fn publication_inventory_rejects_missing_changed_and_foreign_members() {
    let frozen = FrozenJobBinding::from_record(&binding()).unwrap();
    let plan = frozen.result_plan();
    assert_eq!(plan.check_inventory(plan.members()), Ok(()));
    assert_eq!(
        plan.check_inventory(&plan.members()[1..]),
        Err(ContractError::MissingEvidence)
    );
    for (field, value) in [
        ("schema", json!(pin('0'))),
        ("axis", json!(pin('0'))),
        ("rows", json!(99)),
        ("key", json!("foreign")),
    ] {
        let mut record = plan.record();
        record["members"][0][field] = value;
        let members: Vec<ResultMember> = serde_json::from_value(record["members"].clone()).unwrap();
        assert_eq!(plan.check_inventory(&members), Err(ContractError::Mismatch));
    }
}

#[test]
fn research_plan_preserves_science_and_signal_roles_without_inventing_returns() {
    let mut v = binding();
    v["kind"] = json!("RESEARCH");
    v["result_plan"] = json!({"kind":"RESEARCH","members":[
      {"key":"calculation","kind":"CALCULATION_VALUES","schema":pin('2'),"axis":pin('3'),"rows":2},
      {"key":"signal","kind":"SIGNAL_VALUES","schema":pin('4'),"axis":pin('3'),"rows":2},
      {"key":"statistics","kind":"STATISTICS","schema":pin('5'),"axis":null,"rows":1},
      {"key":"report","kind":"RESEARCH_REPORT","schema":pin('6'),"axis":null,"rows":1},
      {"key":"evidence","kind":"CAUSAL_EVIDENCE","schema":pin('7'),"axis":null,"rows":1}
    ]});
    let frozen = FrozenJobBinding::from_record(&v).unwrap();
    assert_eq!(frozen.kind(), JobKind::Research);
    for kind in [
        "CALCULATION_VALUES",
        "SIGNAL_VALUES",
        "STATISTICS",
        "RESEARCH_REPORT",
        "CAUSAL_EVIDENCE",
    ] {
        let mut invalid = v.clone();
        invalid["result_plan"]["members"]
            .as_array_mut()
            .unwrap()
            .retain(|x| x["kind"] != kind);
        assert!(FrozenJobBinding::from_record(&invalid).is_err(), "{kind}");
    }
}

#[test]
fn frozen_plan_allows_owner_produced_fact_count_but_final_inventory_requires_count() {
    let mut v = binding();
    v["result_plan"]["members"][0]["rows"] = Value::Null;
    let frozen =
        FrozenJobBinding::from_record(&v).expect("trade count is not knowable before execution");
    let plan = frozen.result_plan();
    assert_eq!(
        plan.check_inventory(plan.members()),
        Err(ContractError::MissingEvidence)
    );
    let mut produced = plan.record();
    for member in produced["members"].as_array_mut().unwrap() {
        if member["key"] == "execution" {
            member["rows"] = json!(17);
        }
    }
    let members: Vec<ResultMember> = serde_json::from_value(produced["members"].clone()).unwrap();
    assert_eq!(plan.check_inventory(&members), Ok(()));
    let mut v = binding();
    v["result_plan"]["members"][1]["rows"] = Value::Null;
    assert!(
        FrozenJobBinding::from_record(&v).is_err(),
        "one economic root is mandatory"
    );
}

#[test]
fn malformed_nested_values_and_wrong_scope_are_rejected() {
    for (pointer, value) in [
        ("/scope/namespace", json!(pin('a'))),
        ("/scope/run_id", json!("latest")),
        ("/scope/owner", json!("\n")),
        ("/schema_version", json!(2)),
        ("/factor_bindings/0/revision", json!("A".repeat(64))),
    ] {
        let mut v = binding();
        *v.pointer_mut(pointer).unwrap() = value;
        assert!(FrozenJobBinding::from_record(&v).is_err(), "{pointer}");
    }
    for pointer in [
        "/scope",
        "/market",
        "/factor_bindings/0",
        "/result_plan",
        "/result_plan/members/0",
    ] {
        let mut v = binding();
        v.pointer_mut(pointer).unwrap()["hidden"] = json!(true);
        assert!(FrozenJobBinding::from_record(&v).is_err(), "{pointer}");
    }
}

#[test]
fn duplicate_bindings_and_oversized_requests_do_not_create_identity() {
    let mut v = binding();
    let item = v["factor_bindings"][0].clone();
    v["factor_bindings"].as_array_mut().unwrap().push(item);
    assert!(FrozenJobBinding::from_record(&v).is_err());
    let mut v = binding();
    v["scope"]["owner"] = json!("x".repeat(256 * 1024));
    assert_eq!(
        FrozenJobBinding::from_record(&v).unwrap_err(),
        ContractError::BudgetExceeded
    );
}

#[test]
fn owner_produced_fact_axis_requires_frozen_rule_and_concrete_final_axis() {
    let mut v = binding();
    let facts = &mut v["result_plan"]["members"][0];
    facts["rows"] = Value::Null;
    facts["axis"] = Value::Null;
    facts["axis_rule"] = json!(pin('8'));
    let frozen = FrozenJobBinding::from_record(&v)
        .expect("freeze axis rule rather than unknowable actual fact axis");
    let plan = frozen.result_plan();
    let mut produced = plan.record();
    let index = produced["members"]
        .as_array()
        .unwrap()
        .iter()
        .position(|m| m["key"] == "execution")
        .unwrap();
    produced["members"][index]["rows"] = json!(17);
    let members: Vec<ResultMember> = serde_json::from_value(produced["members"].clone()).unwrap();
    assert_eq!(
        plan.check_inventory(&members),
        Err(ContractError::MissingEvidence)
    );
    produced["members"][index]["axis"] = json!(pin('9'));
    let members: Vec<ResultMember> = serde_json::from_value(produced["members"].clone()).unwrap();
    assert_eq!(plan.check_inventory(&members), Ok(()));
    produced["members"][index]["axis"] = json!(pin('a'));
    let members: Vec<ResultMember> = serde_json::from_value(produced["members"].clone()).unwrap();
    assert_eq!(
        plan.check_inventory(&members),
        Ok(()),
        "actual axes are computed from actual facts by the future owning producer"
    );
    produced["members"][index]["axis_rule"] = json!(pin('0'));
    let members: Vec<ResultMember> = serde_json::from_value(produced["members"].clone()).unwrap();
    assert_eq!(plan.check_inventory(&members), Err(ContractError::Mismatch));
    v["result_plan"]["members"][0]["axis_rule"] = Value::Null;
    assert!(FrozenJobBinding::from_record(&v).is_err());
    v = binding();
    v["result_plan"]["members"][2]["axis"] = Value::Null;
    v["result_plan"]["members"][2]["axis_rule"] = json!(pin('8'));
    assert!(
        FrozenJobBinding::from_record(&v).is_err(),
        "known sample curve axis cannot be marked dynamic"
    );
}
