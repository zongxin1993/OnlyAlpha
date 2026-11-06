//! Strict V2 values; authoring metadata never claims an existing Trading grant.
use crate::application::{
    backtest_preparation::{BacktestOrigin, BacktestPrepareInput, run_id},
    command::CommandId,
};
use serde_json::{Value, json};
fn input() -> Value {
    json!({"schema_version":2,"profile":"BTC_SPOT_NEXT_OPEN_BACKTEST_V1",
        "origin":{"kind":"MANUAL_STRATEGY","strategy_id":"private.strategy.btc_momentum","strategy_revision_fingerprint":"a".repeat(64)},
        "source":{"integration_id":"00000000-0000-4000-8000-000000008101","integration_revision_fingerprint":"e".repeat(64),
            "expected_type_id":"binance.spot.market_data","source_id":"binance.spot","environment":"LIVE","instrument_id":"BTCUSDT.BINANCE"},
        "release_manifest_fingerprint":"f".repeat(64),"expected_active_generation":"1".repeat(64),
        "initialize_fresh_runtime":false,"backtest_command_id":"00000000-0000-4000-8000-000000008102"})
}
fn preparation() -> CommandId {
    CommandId::new("00000000-0000-4000-8000-000000008103").unwrap()
}
#[test]
fn manual_preparation_pins_the_exact_published_strategy_without_research_or_trading_refs() {
    let value = input();
    let parsed: BacktestPrepareInput = serde_json::from_value(value.clone()).unwrap();
    parsed.validate(&preparation()).unwrap();
    assert_eq!(serde_json::to_value(&parsed).unwrap(), value);
    assert!(
        matches!(&parsed.origin,BacktestOrigin::ManualStrategy{strategy_id,..} if strategy_id=="private.strategy.btc_momentum")
    );
    for key in [
        "schema_version",
        "profile",
        "release_manifest_fingerprint",
        "initialize_fresh_runtime",
        "backtest_command_id",
    ] {
        let mut changed = value.clone();
        changed[key] = Value::Null;
        assert!(
            serde_json::from_value::<BacktestPrepareInput>(changed)
                .map(|i| i.validate(&preparation()).is_err())
                .unwrap_or(true),
            "{key}"
        );
    }
    for bad in [
        json!("private.strategy.bad__name"),
        json!("00000000-0000-4000-8000-000000008100"),
        json!("private.factor.volume_momentum"),
        json!(""),
    ] {
        let mut changed = value.clone();
        changed["origin"]["strategy_id"] = bad;
        assert!(
            serde_json::from_value::<BacktestPrepareInput>(changed)
                .unwrap()
                .validate(&preparation())
                .is_err()
        );
    }
    for bad in [json!("latest"), json!("A".repeat(64)), json!(null)] {
        let mut changed = value.clone();
        changed["origin"]["strategy_revision_fingerprint"] = bad;
        assert!(
            serde_json::from_value::<BacktestPrepareInput>(changed)
                .map(|i| i.validate(&preparation()).is_err())
                .unwrap_or(true)
        );
    }
    let mut same = value;
    same["backtest_command_id"] = json!(preparation().value());
    assert!(
        serde_json::from_value::<BacktestPrepareInput>(same)
            .unwrap()
            .validate(&preparation())
            .is_err()
    );
}
#[test]
fn frozen_preparation_requires_exact_all_four_qualified_refs_and_no_research_locator() {
    let mut value = input();
    value["origin"] = json!({"kind":"FROZEN_STRATEGY","strategy_fingerprint":"a".repeat(64),"freeze_relation_fingerprint":"b".repeat(64),"qualification_decision_fingerprint":"c".repeat(64),"promotion_fingerprint":"d".repeat(64)});
    let parsed: BacktestPrepareInput = serde_json::from_value(value.clone()).unwrap();
    parsed.validate(&preparation()).unwrap();
    for key in [
        "strategy_fingerprint",
        "freeze_relation_fingerprint",
        "qualification_decision_fingerprint",
        "promotion_fingerprint",
    ] {
        let mut bad = value.clone();
        bad["origin"][key] = json!("latest");
        assert!(
            serde_json::from_value::<BacktestPrepareInput>(bad)
                .unwrap()
                .validate(&preparation())
                .is_err(),
            "{key}"
        );
    }
    value["origin"]["research_run_id"] = json!("00000000-0000-4000-8000-000000008100");
    assert!(serde_json::from_value::<BacktestPrepareInput>(value).is_err());
}
#[test]
fn preparation_rejects_legacy_shape_hidden_grants_windows_and_foreign_sources() {
    for key in [
        "research_run_id",
        "strategy_fingerprint",
        "freeze_relation_fingerprint",
        "qualification_decision_fingerprint",
        "promotion_fingerprint",
        "research_command_id",
        "study_proposal_fingerprint",
        "prepared_inputs",
        "runtime_hold",
        "backtest_capability",
        "run_permit",
        "start",
        "end",
        "quantity",
        "rules_snapshot",
    ] {
        let mut changed = input();
        changed[key] = json!("not an authority");
        assert!(
            serde_json::from_value::<BacktestPrepareInput>(changed).is_err(),
            "{key}"
        );
    }
    let mut old = input();
    old["schema_version"] = json!(1);
    assert!(
        serde_json::from_value::<BacktestPrepareInput>(old)
            .unwrap()
            .validate(&preparation())
            .is_err()
    );
    for (key, bad) in [
        ("instrument_id", json!("ETHUSDT.BINANCE")),
        ("expected_type_id", json!("binance.futures.market_data")),
        ("integration_revision_fingerprint", json!("latest")),
        ("source_id", json!("")),
    ] {
        let mut changed = input();
        changed["source"][key] = bad;
        assert!(
            serde_json::from_value::<BacktestPrepareInput>(changed)
                .unwrap()
                .validate(&preparation())
                .is_err(),
            "{key}"
        );
    }
    let mut changed = input();
    changed["source"]["grant"] = json!("hidden");
    assert!(serde_json::from_value::<BacktestPrepareInput>(changed).is_err());
    assert!(
        serde_json::from_value::<crate::application::factor_studies::PrepareInput>(input())
            .is_err()
    );
    assert!(
        serde_json::from_value::<crate::application::strategy_research::StrategyPrepareInput>(
            input()
        )
        .is_err()
    );
}
#[test]
fn preparation_reserves_the_same_original_backtest_domain_run_identity() {
    let command = CommandId::new(input()["backtest_command_id"].as_str().unwrap()).unwrap();
    let run = run_id(&command);
    assert_eq!(run, "c0132b77-35a1-48b8-aad7-0b2f0655916c");
    assert!(crate::application::command::uuid4(&run));
    assert_eq!(run, run_id(&command));
    assert_ne!(
        run,
        crate::persistence::research_submission::run_id(&command)
    );
    assert_ne!(run, command.value());
    assert_ne!(run, run_id(&preparation()));
}

#[test]
fn first_manual_preparation_accepts_only_an_explicit_empty_cas_without_initializing_a_registry() {
    let mut value = input();
    value["expected_active_generation"] = Value::Null;
    serde_json::from_value::<BacktestPrepareInput>(value.clone())
        .unwrap()
        .validate(&preparation())
        .unwrap();
    value["initialize_fresh_runtime"] = json!(true);
    assert!(
        serde_json::from_value::<BacktestPrepareInput>(value.clone())
            .unwrap()
            .validate(&preparation())
            .is_err()
    );
    value["initialize_fresh_runtime"] = json!(false);
    value["origin"] = json!({"kind":"FROZEN_STRATEGY","strategy_fingerprint":"a".repeat(64),"freeze_relation_fingerprint":"b".repeat(64),"qualification_decision_fingerprint":"c".repeat(64),"promotion_fingerprint":"d".repeat(64)});
    assert!(
        serde_json::from_value::<BacktestPrepareInput>(value)
            .unwrap()
            .validate(&preparation())
            .is_err()
    );
    let mut malformed = input();
    malformed["expected_active_generation"] = json!("current");
    assert!(
        serde_json::from_value::<BacktestPrepareInput>(malformed)
            .unwrap()
            .validate(&preparation())
            .is_err()
    );
}
