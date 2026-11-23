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
fn retained_memory_result_checks_complete_events_curve_and_baseline() {
    use onlyalpha_backtest::{BacktestRun, verify_finite_backtest};
    use onlyalpha_execution::verify_finite_backtest_result;
    use serde_json::{Value, json};

    let prices = ["1.00", "3.00", "5.00", "1.00", "0.50", "2.00", "1.00"];
    for (cash, model_denied) in [("100.00", false), ("100.00", true), ("1.00", false)] {
        let (spec, inputs, executor, policy) =
            support::parts(cash, model_denied, &prices, signal_support::executor());
        let (settings, initial_ns) = (spec.policy_settings.clone(), spec.initial_ns);
        let result = BacktestRun::new(
            spec,
            inputs.clone(),
            executor,
            Box::new(support::Policy {
                cfg: policy.cfg.clone(),
                denied: model_denied,
            }),
        )
        .unwrap()
        .run()
        .unwrap();
        let economic = result.economic_result();
        let verified = verify_finite_backtest_result(
            economic,
            result.account_checkpoint(),
            &settings["execution"],
            &"b".repeat(64),
            &inputs.fingerprint(),
            initial_ns,
            settings["policy"]["end_ns"]
                .as_str()
                .unwrap()
                .parse()
                .unwrap(),
        )
        .unwrap();
        let check_economic =
            |facts: &[Value], curve: &[Value], baseline: &Value, economic: &Value| {
                verify_finite_backtest(
                    &inputs,
                    &settings,
                    &policy,
                    result.raw_signals(),
                    &facts.iter().collect::<Vec<_>>(),
                    &curve.iter().collect::<Vec<_>>(),
                    economic,
                    verified.equity_points(),
                    baseline,
                )
            };
        let facts = result.execution_facts();
        let curve = result.close_curve();
        let baseline = result.baseline();
        let check = |facts: &[Value], curve: &[Value], baseline: &Value| {
            check_economic(facts, curve, baseline, economic)
        };
        check(facts, curve, baseline).unwrap();

        if let Some(index) = facts.iter().position(|fact| {
            fact["family"] == "OPEN" && fact["body"]["status"] == "REJECTED"
        }) {
            let mut changed = facts.to_vec();
            let opening = &mut changed[index]["body"];
            if model_denied {
                opening["admission"]["reason"] = json!("FALSE_MARKET_REJECTION");
                opening["reason"] = opening["admission"]["reason"].clone();
                assert_eq!(
                    check(&changed, curve, baseline).unwrap_err().0,
                    "BACKTEST_REPLAY_FINITE_OPEN_REJECTION"
                );

                let completed = run(cash, false).run().unwrap();
                let filled = completed
                    .execution_facts()
                    .iter()
                    .map(|fact| &fact["body"])
                    .find(|body| body["status"] == "FILLED" && body["opening"] == facts[index]["body"]["opening"])
                    .unwrap();
                assert_eq!(filled["signal"], facts[index]["body"]["signal"]);
                let accepting = support::Policy { cfg: policy.cfg.clone(), denied: false };
                changed[index]["body"]["admission"] = filled["admission"].clone();
                changed[index]["body"]["reason"] = json!("INSUFFICIENT_FUNDS");
                assert_eq!(
                    verify_finite_backtest(
                        &inputs,
                        &settings,
                        &accepting,
                        result.raw_signals(),
                        &changed.iter().collect::<Vec<_>>(),
                        &curve.iter().collect::<Vec<_>>(),
                        economic,
                        verified.equity_points(),
                        baseline,
                    )
                    .unwrap_err()
                    .0,
                    "BACKTEST_REPLAY_FINITE_OPEN_REJECTION"
                );
            } else {
                assert_eq!(opening["reason"], "INSUFFICIENT_FUNDS");
                opening["reason"] = json!("ACCOUNT_JOURNAL_BOUND");
                assert_eq!(
                    check(&changed, curve, baseline).unwrap_err().0,
                    "BACKTEST_REPLAY_FINITE_OPEN_REJECTION"
                );
            }
        }

        if let Some(index) = facts.iter().position(|fact| {
            fact["family"] == "OPEN" && fact["body"]["status"] == "FILLED"
        }) {
            let mut changed = facts.to_vec();
            let opening = &mut changed[index]["body"];
            opening["admission"]["settlement_policy"]["asset_trade_available"] = json!(1);
            opening["economic_evidence"]["settlement_policy"] =
                opening["admission"]["settlement_policy"].clone();
            assert_eq!(
                check(&changed, curve, baseline).unwrap_err().0,
                "BACKTEST_REPLAY_MODEL_SETTLEMENT_POLICY"
            );

            let mut changed = facts.to_vec();
            changed[index]["body"]["economic_evidence"]["settlement_policy"]["cash_withdrawable"] =
                json!(1);
            assert_eq!(
                check(&changed, curve, baseline).unwrap_err().0,
                "BACKTEST_REPLAY_MODEL_SETTLEMENT_POLICY"
            );
        }

        let mut invalid_initial = economic.clone();
        invalid_initial["run"]["initial_time"]["unix_nanos"] = json!(initial_ns + 1);
        assert!(check_economic(facts, curve, baseline, &invalid_initial).is_err());

        if let Some(index) = economic["account_equity_timeline"]
            .as_array()
            .unwrap()
            .iter()
            .position(|point| point["source"] == "VALUATION")
        {
            let mut invalid = economic.clone();
            invalid["account_equity_timeline"][index]["snapshot"]["position_evidence"] =
                json!("e".repeat(64));
            assert!(check_economic(facts, curve, baseline, &invalid).is_err());
        }

        let mut duplicate_end = facts.to_vec();
        duplicate_end.push(facts.last().unwrap().clone());
        duplicate_end.last_mut().unwrap()["sequence"] = json!(facts.len() + 1);
        assert!(check(&duplicate_end, curve, baseline).is_err());
        assert!(check(&facts[..facts.len() - 1], curve, baseline).is_err());

        let mut truncated = facts.to_vec();
        truncated.drain(0..2);
        for (index, event) in truncated.iter_mut().enumerate() {
            event["sequence"] = json!(index + 1);
        }
        assert!(check(&truncated, curve, baseline).is_err());

        for key in ["high_water_mark", "account_sequence", "drawdown"] {
            let mut invalid = curve.to_vec();
            invalid[0].as_object_mut().unwrap().remove(key);
            assert!(check(facts, &invalid, baseline).is_err(), "{key}");
        }
        let mut invalid = curve.to_vec();
        invalid[0]["drawdown"] = json!(0);
        assert!(check(facts, &invalid, baseline).is_err());
        let mut invalid = baseline.clone();
        invalid["entry_fee_quote"]["gross_notional"]["amount"] = json!("1.00");
        assert!(check(facts, curve, &invalid).is_err());

        if let Some(index) = facts
            .iter()
            .position(|fact| fact["body"]["input"]["op"] == "FILL")
        {
            let mut invalid = facts.to_vec();
            invalid[index]["body"]["input"]["payload"]["order"] = json!("other-order");
            let input_digest =
                onlyalpha_execution::digest(invalid[index]["body"]["input"].to_string().as_bytes());
            invalid[index]["body"]["transaction"] = json!(format!("ETX-{input_digest}"));
            assert!(check(&invalid, curve, baseline).is_err());
        }
    }
}

#[test]
fn retained_closed_cycle_count_excludes_reopened_position_until_it_closes() {
    use onlyalpha_backtest::BacktestRun;
    use onlyalpha_execution::verify_finite_backtest_result;

    let prices = [
        "1.00", "3.00", "5.00", "1.00", "0.50", "2.00", "1.00", "5.00", "5.00", "1.00", "1.00",
        "1.00",
    ];
    for (bar_count, trades, cycles) in [(9, 3, 1), (12, 4, 2)] {
        let (spec, inputs, executor, policy) = support::parts(
            "100.00",
            false,
            &prices[..bar_count],
            signal_support::executor(),
        );
        let initial_ns = spec.initial_ns;
        let final_ns = spec.policy_settings["policy"]["end_ns"]
            .as_str()
            .unwrap()
            .parse()
            .unwrap();
        let configuration = spec.policy_settings["execution"].clone();
        let input_pin = inputs.fingerprint();
        let completed = BacktestRun::new(spec, inputs, executor, Box::new(policy))
            .unwrap()
            .run()
            .unwrap();
        assert_eq!(
            completed
                .execution_facts()
                .iter()
                .filter(|fact| fact["body"]["input"]["op"] == "FILL")
                .count(),
            trades
        );
        let verified = verify_finite_backtest_result(
            completed.economic_result(),
            completed.account_checkpoint(),
            &configuration,
            &"b".repeat(64),
            &input_pin,
            initial_ns,
            final_ns,
        )
        .unwrap();
        assert_eq!(completed.closed_cycle_count().unwrap(), cycles);
        assert_eq!(verified.closed_cycles()["cluster"], cycles);
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
