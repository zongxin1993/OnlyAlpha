//! Frozen backtest input priority, duplicate conflict, and opening-bar isolation tests.
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar};
use onlyalpha_runtime::trading::backtest::{Inputs, MarketInput, Source};
use serde_json::{Value, json};

const FACTS: &str = include_str!("../../../test-data/domain/fact-records-v1.jsonl");

fn bar() -> OnlyBar {
    let v: Value = FACTS
        .lines()
        .map(|s| serde_json::from_str::<Value>(s).unwrap())
        .find(|v| v["id"] == "bar")
        .unwrap();
    OnlyBar::from_record(&v["record"]).unwrap()
}

#[test]
fn simultaneous_sources_have_stable_priority_and_exact_duplicate_identity() {
    let a = Source::new(
        &"a".repeat(64),
        &"b".repeat(64),
        &"c".repeat(64),
        &"d".repeat(64),
        1,
        1,
    )
    .unwrap();
    let b = Source::new(
        &"e".repeat(64),
        &"f".repeat(64),
        &"1".repeat(64),
        &"d".repeat(64),
        0,
        1,
    )
    .unwrap();
    let x = MarketInput::new(a.id(), 1, &"d".repeat(64), bar()).unwrap();
    let y = MarketInput::new(b.id(), 1, &"d".repeat(64), bar()).unwrap();
    let inputs = Inputs::new(vec![a, b], vec![x.clone(), y.clone(), x]).unwrap();
    assert_eq!(inputs.records()[0], y);
    assert_eq!(inputs.records().len(), 2);
    let record = inputs.record();
    assert_eq!(Inputs::from_record(&record).unwrap().record(), record);
}

#[test]
fn missing_tail_conflict_version_and_noncanonical_input_order_are_refused() {
    let source = Source::new(
        &"a".repeat(64),
        &"b".repeat(64),
        &"c".repeat(64),
        "opaque-version",
        0,
        1,
    )
    .unwrap();
    let input = MarketInput::new(source.id(), 1, "opaque-version", bar()).unwrap();
    let exact = Inputs::new(vec![source.clone()], vec![input.clone()]).unwrap();
    assert!(Inputs::new(vec![source.clone()], vec![]).is_err());
    assert!(Inputs::new(vec![source.clone(), source.clone()], vec![input.clone()]).is_err());
    let mut conflict = bar().to_record();
    conflict["close"]["value"] = json!("99.00");
    conflict["high"]["value"] = json!("100.00");
    let conflict = MarketInput::new(
        source.id(),
        1,
        "opaque-version",
        OnlyBar::from_record(&conflict).unwrap(),
    )
    .unwrap();
    assert!(Inputs::new(vec![source.clone()], vec![input, conflict]).is_err());
    let foreign = MarketInput::new(source.id(), 1, "different", bar()).unwrap();
    assert!(Inputs::new(vec![source], vec![foreign]).is_err());
    let mut value = exact.record();
    value["records"][0]["sequence"] = json!(2);
    assert!(Inputs::from_record(&value).is_err());
    value = exact.record();
    value["sources"][0]["rows"] = json!(2);
    assert!(Inputs::from_record(&value).is_err());
}

#[test]
fn numerically_equal_but_distinct_duplicate_records_are_conflicts_in_both_orders() {
    let source = Source::new(
        &"a".repeat(64),
        &"b".repeat(64),
        &"c".repeat(64),
        "recorded",
        0,
        1,
    )
    .unwrap();
    let first = MarketInput::new(source.id(), 1, "recorded", bar()).unwrap();
    let mut changed = bar().to_record();
    changed["open"]["value"] = json!("10");
    let second = MarketInput::new(
        source.id(),
        1,
        "recorded",
        OnlyBar::from_record(&changed).unwrap(),
    )
    .unwrap();
    assert_eq!(first, second);
    assert_ne!(first.record(), second.record());
    for records in [vec![first.clone(), second.clone()], vec![second, first]] {
        assert_eq!(
            Inputs::new(vec![source.clone()], records).unwrap_err().0,
            "BACKTEST_REPLAY_CONFLICTING_INPUT"
        );
    }
}

#[test]
fn opening_input_does_not_expose_future_bar_values() {
    let source = Source::new(
        &"a".repeat(64),
        &"b".repeat(64),
        &"c".repeat(64),
        "recorded",
        0,
        1,
    )
    .unwrap();
    let input = MarketInput::new(source.id(), 1, "recorded", bar()).unwrap();
    let inputs = Inputs::new(vec![source], vec![input]).unwrap();
    let input = &inputs.records()[0];
    let opening = input.opening();
    let record = opening.record();
    for key in [
        "bar",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "trade_count",
    ] {
        assert!(record.get(key).is_none(), "{key}");
    }
    assert_eq!(record["open"], input.bar().to_record()["open"]);
    assert!(opening.event_ns() < input.event_ns());
    let mut revised_close = input.bar().to_record();
    revised_close["high"]["value"] = json!("100.00");
    revised_close["close"]["value"] = json!("99.00");
    let revised = MarketInput::new(
        input.source(),
        input.sequence(),
        "recorded",
        OnlyBar::from_record(&revised_close).unwrap(),
    )
    .unwrap();
    assert_ne!(revised.identity(), input.identity());
    assert_eq!(opening.record(), revised.opening().record());
}
