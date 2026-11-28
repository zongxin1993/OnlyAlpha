use super::*;
use crate::trading::backtest::{
    CompletedBacktest,
    finite_playback::{fixture, signal_support},
};

struct Run {
    inputs: Inputs,
    policy: fixture::Policy,
    completed: CompletedBacktest,
}

impl Run {
    fn new(cash: &str, denied: bool) -> Self {
        let fixture = fixture::parts(
            cash,
            denied,
            &["1.00", "5.00", "8.00"],
            signal_support::executor(),
        );
        let inputs = fixture.inputs.clone();
        let policy = fixture::Policy {
            cfg: fixture.policy.cfg.clone(),
            denied,
        };
        let completed = fixture.run().unwrap();
        assert_eq!(
            completed.economic_result()["execution"]["trade_count"],
            if denied { 0 } else { 1 }
        );
        Self {
            inputs,
            policy,
            completed,
        }
    }

    fn verify(
        &self,
        facts: &[Value],
        economic: &Value,
        curve: &[Value],
        points: &[Value],
        venue: &CompletedMemoryVenue,
    ) -> Result<(), Error> {
        verify_finite_backtest(
            &self.inputs,
            self.completed.execution_binding(),
            &self.policy,
            self.completed.program(),
            self.completed.raw_signals(),
            self.completed.signal_receipts(),
            self.completed.signal_checkpoint(),
            &facts.iter().collect::<Vec<_>>(),
            &curve.iter().collect::<Vec<_>>(),
            economic,
            points,
            self.completed.baseline(),
            venue,
            self.completed.binding(),
        )
    }
}

#[test]
fn warmup_signals_require_the_frozen_program_receipts_and_checkpoint() {
    let sample = Run::new("100.00", false);
    let run = &sample.completed;
    let verify = |program: &Value,
                  signals: &[Value],
                  receipts: &[Value],
                  checkpoint: &Value,
                  facts: &[Value]| {
        verify_finite_backtest(
            &sample.inputs,
            run.execution_binding(),
            &sample.policy,
            program,
            signals,
            receipts,
            checkpoint,
            &facts.iter().collect::<Vec<_>>(),
            &run.close_curve().iter().collect::<Vec<_>>(),
            run.economic_result(),
            run.equity_points(),
            run.baseline(),
            run.venue(),
            run.binding(),
        )
    };
    let program = run.program();
    let receipts = run.signal_receipts();
    let signals = run.raw_signals();
    let checkpoint = run.signal_checkpoint();
    let facts = run.execution_facts();
    verify(program, signals, receipts, checkpoint, facts).unwrap();

    let mut changed_signals = signals.to_vec();
    let mut changed_facts = facts.to_vec();
    let warmup = &mut changed_facts
        .iter_mut()
        .find(|row| row["family"] == "BAR")
        .unwrap()["body"];
    assert_eq!(warmup["policy"]["status"], "WARMUP");
    assert_eq!(warmup["raw_signal"], signals[0]);
    warmup["raw_signal"] = Value::Null;
    changed_signals[0] = Value::Null;
    assert_eq!(
        verify(
            program,
            &changed_signals,
            receipts,
            checkpoint,
            &changed_facts
        )
        .unwrap_err()
        .0,
        "BACKTEST_REPLAY_STRATEGY_CONTRACT_INVALID"
    );

    let mut changed_receipts = receipts.to_vec();
    changed_receipts[0] = Value::Null;
    assert_eq!(
        verify(program, signals, &changed_receipts, checkpoint, facts)
            .unwrap_err()
            .0,
        "BACKTEST_REPLAY_STRATEGY_CONTRACT_INVALID"
    );
    let mut changed_checkpoint = checkpoint.clone();
    changed_checkpoint["chain"] = json!("0".repeat(64));
    assert_eq!(
        verify(program, signals, receipts, &changed_checkpoint, facts)
            .unwrap_err()
            .0,
        "BACKTEST_REPLAY_STRATEGY_CONTRACT_INVALID"
    );

    let original = onlyalpha_strategy::Program::from_record(program).unwrap();
    let other = onlyalpha_strategy::Program::new(
        original.revision().clone(),
        original.scope().clone(),
        original.generation(),
        original.source(),
        &"d".repeat(64),
    )
    .unwrap();
    assert_eq!(
        verify(&other.to_record(), signals, receipts, checkpoint, facts)
            .unwrap_err()
            .0,
        "BACKTEST_REPLAY_FINITE_PROGRAM_BINDING"
    );
}

#[test]
fn opening_requires_the_first_observed_acceptance_and_trade_verbatim() {
    let sample = Run::new("100.00", false);
    let run = &sample.completed;
    for index in [0, 1] {
        let mut facts = run.execution_facts().to_vec();
        let opening = facts
            .iter_mut()
            .find(|row| row["family"] == "OPEN" && row["body"]["status"] == "FILLED")
            .unwrap();
        let retained = &mut opening["body"]["venue_facts"][index];
        let original = Fact::decode(retained).unwrap();
        retained["update_id"] = json!("OTHER-OBSERVATION");
        let changed = Fact::decode(retained).unwrap();
        assert_eq!(original.identity(), changed.identity());
        assert_eq!(original.fingerprint(), changed.fingerprint());
        assert_ne!(original.record(), changed.record());
        assert_eq!(
            sample
                .verify(
                    &facts,
                    run.economic_result(),
                    run.close_curve(),
                    run.equity_points(),
                    run.venue()
                )
                .unwrap_err()
                .0,
            "BACKTEST_REPLAY_FINITE_OPEN"
        );
    }
}

#[test]
fn economic_fill_requires_its_own_original_even_when_both_transcripts_agree() {
    let sample = Run::new("100.00", false);
    let run = &sample.completed;
    let mut facts = run.execution_facts().to_vec();
    let mut economic = run.economic_result().clone();
    let accepted = facts
        .iter()
        .find(|row| row["body"]["input"]["op"] == "ACCEPT")
        .unwrap()["body"]["input"]["broker_record"]
        .clone();
    let body = &mut facts
        .iter_mut()
        .find(|row| row["body"]["input"]["op"] == "FILL")
        .unwrap()["body"];
    assert_eq!(
        body["input"]["broker_record"]["payload"]["order"],
        accepted["payload"]["order"]
    );
    body["input"]["broker_record"] = accepted;
    body["transaction"] = json!(format!("ETX-{}", hash(&body["input"])));
    let index = body["sequence"].as_u64().unwrap() as usize - 1;
    economic["facts"][index]["input"] = body["input"].clone();
    economic["facts"][index]["transaction"] = body["transaction"].clone();
    assert_eq!(
        sample
            .verify(
                &facts,
                &economic,
                run.close_curve(),
                run.equity_points(),
                run.venue()
            )
            .unwrap_err()
            .0,
        "BACKTEST_REPLAY_FINITE_EXECUTION_RELATION"
    );
}

#[test]
fn close_curve_and_equity_points_must_match_the_replayed_account() {
    let sample = Run::new("100.00", false);
    let run = &sample.completed;
    let mut curve = run.close_curve().to_vec();
    let mut points = run.equity_points().to_vec();
    for row in curve.iter_mut().chain(&mut points) {
        row["nav"] = json!("12345.00");
    }
    assert_eq!(
        sample
            .verify(
                run.execution_facts(),
                run.economic_result(),
                &curve,
                &points,
                run.venue()
            )
            .unwrap_err()
            .0,
        "BACKTEST_REPLAY_FINITE_ECONOMIC_REPLAY"
    );
}

#[test]
fn empty_broker_protocol_still_requires_the_frozen_venue() {
    let sample = Run::new("100.00", true);
    let run = &sample.completed;
    let other = Run::new("200.00", true);
    assert!(run.venue().protocol_records().is_empty());
    assert!(other.completed.venue().protocol_records().is_empty());
    assert_ne!(
        run.execution_binding().record()["venue"]["source"],
        other.completed.execution_binding().record()["venue"]["source"]
    );
    assert_eq!(
        sample
            .verify(
                run.execution_facts(),
                run.economic_result(),
                run.close_curve(),
                run.equity_points(),
                other.completed.venue()
            )
            .unwrap_err()
            .0,
        "BACKTEST_REPLAY_FINITE_VENUE_BINDING"
    );
}
