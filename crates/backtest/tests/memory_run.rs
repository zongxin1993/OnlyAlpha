#[path = "../../calculation-bridge/tests/support/memory_signal.rs"]
mod signal_support;
#[path = "support/memory_run.rs"]
mod support;
fn run(
    cash: &str,
    denied: bool,
) -> onlyalpha_backtest::BacktestRun<onlyalpha_calculation_bridge::ProgramNodes> {
    support::run_prices(
        cash,
        denied,
        &["1.00", "3.00", "5.00", "1.00", "0.50", "2.00", "1.00"],
    )
}
#[test]
fn complete_memory_trade_path_shares_uncensored_signals_and_preserves_hand_calculated_economics() {
    let completed = run("100.00", false).run().unwrap();
    let bars = ["1.00", "3.00", "5.00", "1.00", "0.50", "2.00", "1.00"]
        .iter()
        .enumerate()
        .map(|(i, p)| signal_support::bar(i as u64 + 1, p))
        .collect();
    let research = onlyalpha_strategy::ResearchRun::new(signal_support::executor(), bars)
        .unwrap()
        .run()
        .unwrap();
    assert_eq!(completed.raw_signals(), research.signals());
    assert_eq!(
        completed.economic_result()["final_account"]["cash"],
        "102.00"
    );
    assert_eq!(completed.economic_result()["final_account"]["fees"], "2.00");
    assert_eq!(completed.economic_result()["execution"]["trade_count"], 2);
    assert_eq!(completed.close_curve().len(), 6);
    assert_eq!(completed.source_rows(), 7);
    assert_eq!(completed.baseline()["final_equity"], "91.00");
    assert!(
        completed
            .execution_facts()
            .iter()
            .all(|e| !e.to_string().contains("projections"))
    );
}
#[test]
fn real_model_rejection_and_account_risk_rejection_preserve_raw_signals_without_fake_trades() {
    for (cash, model_denied) in [("100.00", true), ("1.00", false)] {
        let result = run(cash, model_denied).run().unwrap();
        assert_eq!(result.economic_result()["execution"]["trade_count"], 0);
        assert_eq!(result.economic_result()["final_account"]["cash"], cash);
        assert!(
            result
                .raw_signals()
                .iter()
                .any(|s| s["decision"]["entry"] == true)
        );
        assert!(
            result
                .execution_facts()
                .iter()
                .any(|e| e["body"]["status"] == "REJECTED")
        );
    }
}
#[test]
fn missing_input_consumption_or_cancelled_work_cannot_produce_a_completed_backtest() {
    assert!(run("100.00", false).finish().is_err());
    let mut run = run("100.00", false);
    run.step().unwrap();
    run.cancel();
    assert!(run.finish().is_err());
}

#[test]
fn finite_backtest_refuses_an_executor_with_hidden_prior_market_history() {
    use onlyalpha_domain::{base::OnlyDomainModel, time::OnlyTimestamp};
    let prices = ["1.00", "3.00", "5.00", "1.00", "0.50", "2.00", "1.00"];
    let mut earlier = signal_support::bar(1, "99.00").to_record();
    for f in ["bar_start", "bar_end", "ts_event", "ts_init"] {
        let at = OnlyTimestamp::from_datetime(earlier[f].as_str().unwrap().parse().unwrap());
        earlier[f] = serde_json::json!(
            OnlyTimestamp::from_unix_nanos(at.unix_nanos() - 60_000_000_000i64)
                .to_datetime_exact()
                .unwrap()
                .to_string()
        );
    }
    let earlier = onlyalpha_domain::market::OnlyBar::from_record(&earlier).unwrap();
    let mut warmed = signal_support::executor();
    warmed
        .process(
            &earlier,
            &OnlyTimestamp::from_datetime(*earlier.ts_init()),
            &"a".repeat(64),
        )
        .unwrap();
    let checkpoint = warmed.capture_checkpoint().unwrap();
    let restored = signal_support::executor()
        .restored_candidate(
            checkpoint.to_string().as_bytes(),
            &onlyalpha_strategy::record_fingerprint(&checkpoint),
        )
        .unwrap();
    assert!(support::build_prices("100.00", false, &prices, signal_support::executor()).is_ok());
    assert!(support::build_prices("100.00", false, &prices, warmed).is_err());
    assert!(support::build_prices("100.00", false, &prices, restored).is_err());
}

#[test]
fn full_actual_driver_binding_rejects_changed_execution_conditions() {
    let prices = ["1.00", "3.00", "5.00", "1.00", "0.50", "2.00", "1.00"];
    for case in [
        "quantity",
        "buy_multiplier",
        "sell_multiplier",
        "calendar",
        "start",
        "initial",
        "resolver",
    ] {
        let (mut spec, inputs, executor, mut policy) =
            support::parts("100.00", false, &prices, signal_support::executor());
        match case {
            "quantity" => {
                spec.policy_settings["policy"]["quantity"]["value"] = serde_json::json!("5")
            }
            "buy_multiplier" => {
                spec.policy_settings["policy"]["buy_multiplier"] = serde_json::json!("1.01")
            }
            "sell_multiplier" => {
                spec.policy_settings["policy"]["sell_multiplier"] = serde_json::json!("0.99")
            }
            "calendar" => {
                spec.policy_settings["calendar"]["calendar_version"] = serde_json::json!(2)
            }
            "start" => {
                let old = spec.policy_settings["policy"]["start_ns"]
                    .as_str()
                    .unwrap()
                    .parse::<i64>()
                    .unwrap();
                spec.policy_settings["policy"]["start_ns"] =
                    serde_json::json!((old + 60_000_000_000).to_string());
            }
            "initial" => spec.initial_ns -= 60_000_000_000,
            "resolver" => policy.denied = true,
            _ => unreachable!(),
        }
        assert!(
            onlyalpha_backtest::BacktestRun::new(spec, inputs, executor, Box::new(policy)).is_err(),
            "{case}"
        );
    }
}
