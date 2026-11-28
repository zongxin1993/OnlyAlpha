#[path = "../../tests/support/memory_run.rs"]
pub(super) mod fixture;
#[path = "../../tests/support/memory_signal.rs"]
pub(super) mod signal_support;

use super::{CompletedBacktest, FrozenReplay, OnlyAlphaRuntime, next_open};
use crate::{EventOutcome, TradingRunError};
use serde_json::{Value, json};

fn actions(run: &CompletedBacktest, kind: &str) -> Vec<Value> {
    run.venue()
        .source_trace()
        .iter()
        .map(|row| row.record())
        .filter(|row| row["action"]["kind"] == kind)
        .collect()
}

#[test]
fn signal_dispatches_at_the_following_open_and_each_original_fill_is_applied_once() {
    let run = fixture::run_prices(
        "100.00",
        false,
        &["1.00", "5.00", "8.00", "1.00", "1.00", "4.00"],
    );
    let execution = &run.economic_result()["execution"];
    assert_eq!(execution["order_count"], 2);
    assert_eq!(execution["trade_count"], 2);
    assert_eq!(run.economic_result()["final_account"]["cash"], "82.00");
    assert_eq!(run.economic_result()["final_account"]["fees"], "2.00");
    let trace: Vec<_> = run
        .venue()
        .source_trace()
        .iter()
        .map(|row| row.record())
        .collect();
    let opens = actions(&run, "OPEN");
    assert_eq!(opens.len(), 6);
    let commands: Vec<_> = trace
        .iter()
        .enumerate()
        .filter(|(_, r)| r["action"]["kind"] == "COMMAND")
        .collect();
    assert_eq!(commands.len(), 2);
    let filled: Vec<_> = run
        .execution_facts()
        .iter()
        .map(|r| &r["body"])
        .filter(|r| r["status"] == "FILLED")
        .collect();
    assert_eq!(filled.len(), 2);
    for (((i, _), row), (open_index, side, price)) in commands
        .iter()
        .zip(filled)
        .zip([(2, "BUY", "8.00"), (5, "SELL", "4.00")])
    {
        let opening = &opens[open_index]["action"];
        assert_eq!(opening["sequence"], open_index + 1);
        assert_eq!(
            trace[..*i]
                .iter()
                .rev()
                .find(|r| r["action"]["kind"] == "OPEN")
                .unwrap()["action"],
            *opening
        );
        assert_eq!(row["signal"]["source_sequence"], open_index);
        assert_eq!(row["signal"]["side"], side);
        assert_eq!(row["execution_price"]["value"], price);
        let original = row["venue_facts"].as_array().unwrap();
        assert_eq!(original.len(), 2);
        assert_eq!(original[0]["kind"], "ACCEPTED");
        assert_eq!(original[1]["kind"], "TRADE");
        for fact in original {
            assert_eq!(fact["ts_event"], opening["bar_start"]);
        }
    }
    assert_eq!(actions(&run, "PUBLISHED").len(), 4);
}

#[test]
fn a_later_close_cannot_change_the_open_order_or_analytical_quote_context() {
    use super::{MarketInput, NextOpenModel, NextOpenPolicy};
    use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar};

    let f = fixture::parts(
        "100.00",
        false,
        &["1.00", "5.00", "8.00"],
        signal_support::executor(),
    );
    let model = NextOpenModel::new(
        &f.spec.policy_settings,
        f.policy.binding(),
        f.spec.initial_ns.into(),
        &f.spec.cluster,
    )
    .unwrap();
    let prior = &f.inputs.records()[0];
    let first = &f.inputs.records()[1];
    let mut changed_bar = first.bar().to_record();
    changed_bar["high"]["value"] = json!("10.00");
    changed_bar["close"]["value"] = json!("9.00");
    let changed = MarketInput::new(
        first.source(),
        first.sequence(),
        "recorded",
        OnlyBar::from_record(&changed_bar).unwrap(),
    )
    .unwrap();
    let signal = json!({"source":prior.source(), "source_sequence":prior.sequence(), "signal_time":prior.event_ns().to_string(), "side":"BUY", "decision_identity":prior.identity()});
    let request = |input: &MarketInput| {
        let opening = input.opening();
        let (_, context) = model.opening_terms(&opening, &signal).unwrap();
        model
            .order_request(&opening, &signal, context["cause"].as_str().unwrap())
            .unwrap()
    };
    assert_ne!(first.identity(), changed.identity());
    assert_eq!(first.opening().record(), changed.opening().record());
    assert_eq!(request(first), request(&changed));
    assert_eq!(
        model.baseline_entry(first).unwrap(),
        model.baseline_entry(&changed).unwrap()
    );
}

#[test]
fn opening_gap_rechecks_available_cash_before_creating_an_order() {
    let run = fixture::run_prices("25.00", false, &["1.00", "5.00", "8.00"]);
    let rejected = run
        .execution_facts()
        .iter()
        .map(|r| &r["body"])
        .find(|r| r["status"] == "REJECTED")
        .unwrap();
    assert_eq!(rejected["reason"], "INSUFFICIENT_FUNDS");
    assert_eq!(rejected["execution_price"]["value"], "8.00");
    assert_eq!(run.economic_result()["execution"]["order_count"], 0);
    assert_eq!(run.economic_result()["execution"]["trade_count"], 0);
    assert_eq!(run.economic_result()["final_account"]["cash"], "25.00");
    assert!(actions(&run, "COMMAND").is_empty());
    assert!(actions(&run, "PUBLISHED").is_empty());
}

#[test]
fn final_close_cancels_its_signal_and_preserves_marked_holdings() {
    let run = fixture::run_prices("100.00", false, &["1.00", "5.00", "8.00", "1.00", "1.00"]);
    let end = run.execution_facts().last().unwrap();
    assert_eq!(end["family"], "END");
    assert_eq!(end["body"]["signal"]["reason"], "INPUT_EXHAUSTED");
    assert_eq!(end["body"]["signal"]["signal"]["side"], "SELL");
    assert_eq!(run.economic_result()["execution"]["trade_count"], 1);
    assert_eq!(run.close_curve().last().unwrap()["nav"], "71.00");
    assert_eq!(actions(&run, "COMMAND").len(), 1);
}

#[test]
fn cancelling_a_running_attempt_preserves_applied_position_cost() {
    let f = fixture::parts(
        "100.00",
        false,
        &["1.00", "5.00", "8.00", "1.00"],
        signal_support::executor(),
    );
    let replay = FrozenReplay::new(&f.panel, f.panel.snapshot(), f.panel.content_digest()).unwrap();
    let mut task = OnlyAlphaRuntime::new()
        .unwrap()
        .backtest(
            replay,
            f.spec,
            &f.inputs,
            f.executor,
            Box::new(f.policy),
            f.venue,
        )
        .unwrap();
    let mut markets = 0;
    let stopped = task.run(|_, outcome| {
        if matches!(outcome, EventOutcome::Market(_)) {
            markets += 1;
            if markets == 3 {
                return Err(onlyalpha_execution::Error("CANCELLED".into()));
            }
        }
        Ok(())
    });
    assert!(matches!(stopped, Err(TradingRunError::Consumption { .. })));
    let book = task.session().position_order_view().unwrap();
    let position = &book["position_accounts"][0]["snapshot"];
    assert_eq!(position["quantity"], "4");
    assert_eq!(
        position["cost"]
            .as_str()
            .unwrap()
            .parse::<onlyalpha_domain::numeric::OnlyDecimal>()
            .unwrap(),
        "32".parse().unwrap()
    );
    assert!(task.run(|_, _| Ok(())).is_err());
    assert!(task.finish().is_err());
}

#[test]
fn settlement_ordinals_follow_gregorian_leap_years() {
    let ordinal = |day| {
        next_open::context("test", 0.into(), &json!(day)).unwrap()["day_index"]
            .as_u64()
            .unwrap()
    };
    assert_eq!(ordinal("0001-01-01"), 1);
    assert_eq!(ordinal("1970-01-01"), 719163);
    assert_eq!(ordinal("1900-03-01") - ordinal("1900-02-28"), 1);
    assert_eq!(ordinal("2000-03-01") - ordinal("2000-02-28"), 2);
    assert_eq!(ordinal("2024-03-01") - ordinal("2024-02-29"), 1);
}
