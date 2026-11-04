mod support;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::*,
    enums::OnlySessionType,
    market::OnlyBar,
    time::{OnlyTimeZone, OnlyTimestamp},
};
use onlyalpha_market_data_construction::*;
use serde_json::json;
use std::sync::Arc;
use support::*;
fn at(window: u32, start: &str, end: &str, day: &str) -> Arc<OnlyBar> {
    let mut row = bar(A, 1, 1).to_record();
    row["bar_type"] = kind(A, window).to_record();
    row["bar_start"] = json!(start);
    for name in ["bar_end", "ts_event", "ts_init"] {
        row[name] = json!(end);
    }
    row["trading_day"] = json!(day);
    Arc::new(OnlyBar::from_record(&row).unwrap())
}
fn executor(
    source: u32,
    target: u32,
    cal: Arc<OnlyTradingCalendar>,
    tail: OnlyIncompletePolicy,
) -> OnlyTimeBarExecutor {
    let e = edge(source, target);
    let r = OnlyConstructionRecipe::derived(
        e.target().semantic().clone(),
        OnlyConstructionSemantic::Bar(kind(A, source).semantic().clone()),
        "TIME_BAR",
        1u32.into(),
        OnlyMissingPolicy::Reject,
        tail,
    )
    .unwrap();
    OnlyTimeBarExecutor::new(
        OnlyConstructionEdge::new(e.source().clone(), e.target().clone(), r).unwrap(),
        cal,
    )
    .unwrap()
}
#[test]
fn lunch_anchor_and_cross_day_use_calendar_intervals() {
    let mut e = executor(1, 3, calendar(), OnlyIncompletePolicy::Drop);
    let mut output = vec![];
    for (start, end) in [
        ("2026-01-05T03:27:00Z", "2026-01-05T03:28:00Z"),
        ("2026-01-05T03:28:00Z", "2026-01-05T03:29:00Z"),
        ("2026-01-05T03:29:00Z", "2026-01-05T03:30:00Z"),
    ] {
        let b = at(1, start, end, "2026-01-05");
        output = e
            .process(
                &OnlyConstructionFact::Bar(b.clone()),
                &OnlyTimestamp::from_datetime(*b.bar_end()),
            )
            .unwrap();
    }
    assert_eq!(output.len(), 1);
    assert_eq!(output[0].bar_end().to_string(), "2026-01-05T03:30:00Z");
    let b = at(
        1,
        "2026-01-06T01:30:00Z",
        "2026-01-06T01:31:00Z",
        "2026-01-06",
    );
    assert!(
        e.process(
            &OnlyConstructionFact::Bar(b.clone()),
            &OnlyTimestamp::from_datetime(*b.bar_end())
        )
        .unwrap()
        .is_empty()
    );
    let mut seven = executor(1, 7, calendar(), OnlyIncompletePolicy::Drop);
    let b = at(
        1,
        "2026-01-05T05:00:00Z",
        "2026-01-05T05:01:00Z",
        "2026-01-05",
    );
    let window = seven.window_for(&b).unwrap();
    assert_eq!(window.start().to_string(), "2026-01-05T05:00:00Z");
    assert_eq!(window.end().to_string(), "2026-01-05T05:07:00Z");
    assert!(
        seven
            .process(
                &OnlyConstructionFact::Bar(b.clone()),
                &OnlyTimestamp::from_datetime(*b.bar_end())
            )
            .unwrap()
            .is_empty()
    );
    let lunch = at(
        1,
        "2026-01-05T04:00:00Z",
        "2026-01-05T04:01:00Z",
        "2026-01-05",
    );
    assert!(seven.window_for(&lunch).is_err());
}
#[test]
fn truncated_tail_drop_and_reject_are_explicit() {
    let tail = at(
        1,
        "2026-01-05T03:29:00Z",
        "2026-01-05T03:30:00Z",
        "2026-01-05",
    );
    let init = OnlyTimestamp::from_datetime(*tail.bar_end());
    let mut drop = executor(1, 7, calendar(), OnlyIncompletePolicy::Drop);
    assert!(
        drop.process(&OnlyConstructionFact::Bar(tail.clone()), &init)
            .unwrap()
            .is_empty()
    );
    let mut reject = executor(1, 7, calendar(), OnlyIncompletePolicy::Reject);
    let before = reject.capture_checkpoint().unwrap();
    assert!(
        reject
            .process(&OnlyConstructionFact::Bar(tail), &init)
            .is_err()
    );
    assert_eq!(reject.capture_checkpoint().unwrap(), before);
}
#[test]
fn dst_uses_actual_utc_duration_and_no_synthetic_hour() {
    let mut fields = calendar().input();
    fields.timezone = OnlyTimeZone::new("America/New_York").unwrap();
    fields.weekend_days.clear();
    fields.sessions = vec![
        OnlyTradingSession::new(OnlyTradingSessionInput {
            name: "dst".into(),
            opens_at: "00:00:00".parse().unwrap(),
            closes_at: "04:00:00".parse().unwrap(),
            session_type: OnlySessionType::Continuous,
            belongs_to_trading_day_offset: 0,
            allows_orders: true,
            allows_market_data: true,
        })
        .unwrap(),
    ];
    let mut e = executor(
        60,
        120,
        Arc::new(OnlyTradingCalendar::new(fields).unwrap()),
        OnlyIncompletePolicy::Drop,
    );
    let mut output = vec![];
    for (start, end) in [
        ("2026-03-08T05:00:00Z", "2026-03-08T06:00:00Z"),
        ("2026-03-08T06:00:00Z", "2026-03-08T07:00:00Z"),
    ] {
        let b = at(60, start, end, "2026-03-08");
        output = e
            .process(
                &OnlyConstructionFact::Bar(b.clone()),
                &OnlyTimestamp::from_datetime(*b.bar_end()),
            )
            .unwrap();
    }
    assert_eq!(output.len(), 1);
    assert_eq!(output[0].bar_start().to_string(), "2026-03-08T05:00:00Z");
    assert_eq!(output[0].bar_end().to_string(), "2026-03-08T07:00:00Z");
    assert_eq!(output[0].volume().value().to_string(), "200");
}
#[test]
fn precision_mismatch_is_rejected_before_committing_pending_fact() {
    let mut e = time_executor(OnlyMissingPolicy::Reject, OnlyIncompletePolicy::Drop);
    e.process(&fact(1), &stamp(1)).unwrap();
    let before = e.capture_checkpoint().unwrap();
    let b = altered(
        &bar(A, 1, 2),
        "volume",
        json!({"schema_version":1,"value":"100.0","precision":1}),
    );
    assert!(e.process(&OnlyConstructionFact::Bar(b), &stamp(2)).is_err());
    assert_eq!(e.capture_checkpoint().unwrap(), before);
}
#[test]
fn signed_zero_sums_start_at_positive_zero_and_price_ties_keep_first() {
    let mut e = time_executor(OnlyMissingPolicy::Reject, OnlyIncompletePolicy::Drop);
    let mut out = vec![];
    for end in [1, 2, 3] {
        let mut row = bar(A, 1, end).to_record();
        for field in ["open", "high", "low", "close"] {
            row[field]["value"] = json!(if end == 1 { "-0.00" } else { "0.00" });
        }
        row["volume"]["value"] = json!("-0");
        row["turnover"] = json!({"schema_version":1,"amount":"-0.00","currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"}});
        let b = Arc::new(OnlyBar::from_record(&row).unwrap());
        out = e
            .process(&OnlyConstructionFact::Bar(b), &stamp(end))
            .unwrap();
    }
    let row = out[0].to_record();
    assert_eq!(row["volume"]["value"], "0");
    assert_eq!(row["turnover"]["amount"], "0.00");
    assert_eq!(row["high"]["value"], "-0.00");
    assert_eq!(row["low"]["value"], "-0.00");
}
#[test]
fn unsupported_time_shapes_and_unknown_algorithms_do_not_fallback() {
    assert!(OnlyTimeBarExecutor::new(edge(3, 5), calendar()).is_err());
    let source = kind(A, 1);
    let target = kind(A, 3);
    let recipe = OnlyConstructionRecipe::derived(
        target.semantic().clone(),
        OnlyConstructionSemantic::Bar(source.semantic().clone()),
        "ROLLING_TIME_BAR",
        1u32.into(),
        OnlyMissingPolicy::Reject,
        OnlyIncompletePolicy::Drop,
    )
    .unwrap();
    let e = OnlyConstructionEdge::new(OnlyConstructionInput::Bar(source), target, recipe).unwrap();
    assert!(matches!(
        OnlyConstructionRegistry::default().create(&e, calendar()),
        Err(OnlyConstructionError::Unavailable)
    ));
    let mut fields = calendar().input();
    let mut session = fields.sessions[0].input();
    session.allows_market_data = false;
    fields.sessions[0] = OnlyTradingSession::new(session).unwrap();
    let mut blocked = executor(
        1,
        3,
        Arc::new(OnlyTradingCalendar::new(fields).unwrap()),
        OnlyIncompletePolicy::Drop,
    );
    assert!(blocked.process(&fact(1), &stamp(1)).is_err());
}
#[test]
fn optional_amounts_are_complete_and_currency_scoped() {
    let money = |code: &str| json!({"schema_version":1,"amount":"10.00","currency":{"schema_version":1,"code":code,"precision":2,"currency_type":"FIAT"}});
    for missing in [false, true] {
        let mut e = time_executor(OnlyMissingPolicy::Reject, OnlyIncompletePolicy::Drop);
        let mut out = vec![];
        for end in [1, 2, 3] {
            let mut row = bar(A, 1, end).to_record();
            row["quote_volume"] = json!({"schema_version":1,"value":"200.00","precision":2});
            row["turnover"] = money("USD");
            if missing && end == 2 {
                row["quote_volume"] = json!(null);
                row["turnover"] = json!(null);
            }
            out = e
                .process(
                    &OnlyConstructionFact::Bar(Arc::new(OnlyBar::from_record(&row).unwrap())),
                    &stamp(end),
                )
                .unwrap();
        }
        if missing {
            assert!(out[0].quote_volume().is_none());
            assert!(out[0].turnover().is_none());
        } else {
            assert_eq!(
                out[0].quote_volume().as_ref().unwrap().value().to_string(),
                "600.00"
            );
            assert_eq!(
                out[0].turnover().as_ref().unwrap().amount().to_string(),
                "30.00"
            );
        }
    }
    let mut e = time_executor(OnlyMissingPolicy::Reject, OnlyIncompletePolicy::Drop);
    let first = altered(&bar(A, 1, 1), "turnover", money("USD"));
    e.process(&OnlyConstructionFact::Bar(first), &stamp(1))
        .unwrap();
    let before = e.capture_checkpoint().unwrap();
    let second = altered(&bar(A, 1, 2), "turnover", money("EUR"));
    assert!(
        e.process(&OnlyConstructionFact::Bar(second), &stamp(2))
            .is_err()
    );
    assert_eq!(e.capture_checkpoint().unwrap(), before);
}
#[test]
fn submicrosecond_output_init_fails_without_flooring_or_partial_commit() {
    let mut e = time_executor(OnlyMissingPolicy::Reject, OnlyIncompletePolicy::Drop);
    for end in [1, 2] {
        e.process(&fact(end), &stamp(end)).unwrap();
    }
    let before = e.capture_checkpoint().unwrap();
    let init = OnlyTimestamp::from_unix_nanos(stamp(3).unix_nanos() + 17);
    assert!(e.process(&fact(3), &init).is_err());
    assert_eq!(e.capture_checkpoint().unwrap(), before);
    assert_eq!(e.process(&fact(3), &stamp(3)).unwrap().len(), 1);
}
