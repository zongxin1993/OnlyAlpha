use super::*;
use crate::application::backtest_preparation::BacktestOrigin;
use crate::persistence::research_preparation::{PreparationRequest, State};
fn operation() -> Operation {
    let command = CommandId::new("00000000-0000-4000-8000-000000000001").unwrap();
    let input=serde_json::from_value(json!({"schema_version":2,"profile":"BTC_SPOT_NEXT_OPEN_BACKTEST_V1",
        "origin":{"kind":"MANUAL_STRATEGY","strategy_id":"private.strategy.btc_momentum","strategy_revision_fingerprint":"a".repeat(64)},
        "source":{"integration_id":"00000000-0000-4000-8000-000000000003","integration_revision_fingerprint":"b".repeat(64),"expected_type_id":"binance.spot.market_data","source_id":"binance.spot","environment":"LIVE","instrument_id":"BTCUSDT.BINANCE"},
        "release_manifest_fingerprint":"c".repeat(64),"expected_active_generation":"d".repeat(64),"initialize_fresh_runtime":false,
        "backtest_command_id":"00000000-0000-4000-8000-000000000002"})).unwrap();
    let accepted = json!({"schema_version":2,"contract":"ONLYALPHA_ACCEPTED_BACKTEST_PREPARATION_V2","command_id":command.value(),"owner":"human","input":serde_json::to_value(&input).unwrap(),"semantic_store_id":"00000000-0000-4000-8000-000000000004","runtime_work_id":crate::application::backtest_preparation::run_id(&CommandId::new("00000000-0000-4000-8000-000000000002").unwrap()),"accepted_at":"2025-01-03T00:00:00Z"});
    Operation {
        command,
        owner: "human".into(),
        request: PreparationRequest::Backtest(input),
        accepted,
        revision: 1,
        state: State::Running,
        phase: "INPUTS".into(),
        outputs: json!({"environment":{"runtime_generation_fingerprint":"e".repeat(64),"binding":{"kind":"RuntimeWorkBound","work_id":crate::application::backtest_preparation::run_id(&CommandId::new("00000000-0000-4000-8000-000000000002").unwrap()),"generation_fingerprint":"e".repeat(64),"reason":"00000000-0000-4000-8000-000000000002"}}}),
        detail: Value::Null,
    }
}
#[test]
fn manual_origin_is_the_exact_accepted_typed_strategy_and_not_a_research_run() {
    let op = operation();
    let origin = Origin::from_operation(&op).unwrap();
    assert_eq!(origin.strategy_id, "private.strategy.btc_momentum");
    assert_eq!(origin.strategy_revision_fingerprint, "a".repeat(64));
    assert_ne!(origin.work, origin.command.value());
    assert_eq!(origin.work, op.request.reserved_run_id());
    assert_eq!(origin.generation, "e".repeat(64));
    assert_ne!(
        Some(origin.generation.as_str()),
        op.request.expected_active(),
        "expected active is the old CAS guard, not actual Generation"
    );
    assert_eq!(origin.runtime_owner, op.request.future_command());
    assert_eq!(
        origin.accepted_fingerprint,
        crate::application::factor_content::hash(&op.accepted).unwrap()
    );
    assert!(!origin.record().to_string().contains("research_run_id"));
    for field in [
        "command_id",
        "owner",
        "input",
        "runtime_work_id",
        "semantic_store_id",
        "contract",
        "schema_version",
    ] {
        let mut changed = op.clone();
        changed.accepted[field] = Value::Null;
        assert!(Origin::from_operation(&changed).is_err(), "{field}");
    }
}
#[test]
fn frozen_or_mismatched_generation_cannot_enter_manual_validation() {
    let mut op = operation();
    if let PreparationRequest::Backtest(input) = &mut op.request {
        input.origin = BacktestOrigin::FrozenStrategy {
            strategy_fingerprint: "a".repeat(64),
            freeze_relation_fingerprint: "b".repeat(64),
            qualification_decision_fingerprint: "c".repeat(64),
            promotion_fingerprint: "d".repeat(64),
        };
        op.accepted["input"] = serde_json::to_value(input).unwrap();
    }
    assert!(Origin::from_operation(&op).is_err());
    let mut op = operation();
    op.outputs["environment"]["runtime_generation_fingerprint"] = Value::Null;
    assert!(Origin::from_operation(&op).is_err());
}
#[test]
fn targetless_validation_window_includes_actual_graph_warmup_only() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../tests/application/fixtures/strategy_calculations.json"
    ))
    .unwrap();
    let graph=Graph::from_record(&json!({"schema_version":1,"nodes":fixture["nodes"].as_array().unwrap().iter().map(|node|json!({"alias":null,"definition":node["definition"]})).collect::<Vec<_>>()}),WORK).unwrap();
    let window = validation_window(&graph).unwrap();
    assert_eq!(window["observation_capacity"], 720);
    assert_eq!(window["dataset_observation_capacity"], 740);
    assert_eq!(window["warmup_bars"], 20);
    assert_eq!(
        window["dataset_event_end_ns"],
        ns("2025-01-03T12:01:00Z").unwrap().to_string()
    );
    assert!(window.get("target_future_policy").is_none());
    assert!(window.get("research_context_fingerprint").is_none());
}
#[test]
fn a_control_without_an_original_joined_child_cannot_seal_validation() {
    assert!(Control::default().verify_joined().is_err());
}
#[test]
fn missing_validation_owner_is_not_initialized_by_open() {
    let root = std::env::temp_dir().join(format!(
        "onlyalpha-manual-validation-missing-{}",
        std::process::id()
    ));
    assert!(!root.exists());
    assert!(crate::persistence::strategy_validation::Store::open(&root).is_err());
    assert!(!root.exists());
}

#[test]
fn a_validation_origin_requires_the_actual_bound_environment_not_a_cas_value() {
    let op = operation();
    for (path, bad) in [
        ("runtime_generation_fingerprint", json!("latest")),
        ("runtime_generation_fingerprint", Value::Null),
    ] {
        let mut changed = op.clone();
        changed.outputs["environment"][path] = bad;
        assert!(Origin::from_operation(&changed).is_err());
    }
    let mut absent = op.clone();
    absent.outputs = json!({});
    assert!(Origin::from_operation(&absent).is_err());
    let mut wrong = op;
    wrong.outputs["environment"]["binding"]["generation_fingerprint"] = json!("d".repeat(64));
    assert!(Origin::from_operation(&wrong).is_err());
}
