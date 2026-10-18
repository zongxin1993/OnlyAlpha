mod support;
use onlyalpha_domain::base::OnlyDomainModel;
use onlyalpha_market_data_state::*;
use serde_json::json;
use support::*;
#[test]
fn late_restore_failure_preserves_populated_state() {
    let mut s = state(2);
    let a = kind(A, 1);
    apply(&mut s, &[bar(A, 1, 2)], &a, 2);
    apply(&mut s, &[bar(A, 1, 3), bar(A, 3, 3)], &a, 3);
    let baseline = s.capture_checkpoint();
    let mut cases = vec![];
    for bad in [json!(true), json!("1"), json!(1.0), json!(-1), json!(0)] {
        let mut row = baseline.clone();
        row["series"][1]["version"] = bad;
        cases.push(row);
    }
    let mut row = baseline.clone();
    row["series"][0]["version"] = json!(1);
    cases.push(row);
    for (field, value) in [
        ("bar_type", kind(B, 1).to_record()),
        ("is_closed", json!(false)),
        ("revision", json!(1)),
        ("ts_event", json!("2026-01-05T01:32:00Z")),
    ] {
        let mut row = baseline.clone();
        row["series"][1]["history"][0][field] = value;
        cases.push(row);
    }
    let mut row = baseline.clone();
    row["series"][0]["history"]
        .as_array_mut()
        .unwrap()
        .reverse();
    cases.push(row);
    let mut row = baseline.clone();
    row["series"][1]["history"] = json!([
        bar(A, 3, 3).to_record(),
        bar(A, 3, 6).to_record(),
        bar(A, 3, 9).to_record()
    ]);
    row["series"][1]["version"] = json!(3);
    cases.push(row);
    let mut row = baseline.clone();
    let duplicate = row["series"][0].clone();
    row["series"].as_array_mut().unwrap().push(duplicate);
    cases.push(row);
    for row in cases {
        assert!(matches!(
            s.restore_checkpoint(&row),
            Err(OnlyMarketDataStateError::Record(_))
        ));
        assert_eq!(s.capture_checkpoint(), baseline);
    }
    let mut foreign = baseline.clone();
    foreign["engine_id"] = json!("other");
    assert!(matches!(
        s.restore_checkpoint(&foreign),
        Err(OnlyMarketDataStateError::Scope)
    ));
    assert_eq!(s.capture_checkpoint(), baseline);
    let mut foreign = baseline.clone();
    foreign["runtime_id"] = json!("other");
    assert!(matches!(
        s.restore_checkpoint(&foreign),
        Err(OnlyMarketDataStateError::Scope)
    ));
    assert_eq!(s.capture_checkpoint(), baseline);
    let mut config = baseline.clone();
    config["history_limit"] = json!(3);
    assert!(matches!(
        s.restore_checkpoint(&config),
        Err(OnlyMarketDataStateError::Configuration)
    ));
    assert_eq!(s.capture_checkpoint(), baseline);
}
#[test]
fn restore_replaces_and_replay_matches_fresh() {
    let mut reference = state(2);
    let a = kind(A, 1);
    let saved = apply(&mut reference, &[bar(A, 1, 1)], &a, 1);
    let checkpoint = reference.capture_checkpoint();
    let mut target = state(2);
    apply(&mut target, &[bar(B, 1, 1)], &kind(B, 1), 1);
    target.restore_checkpoint(&checkpoint).unwrap();
    target.restore_checkpoint(&checkpoint).unwrap();
    assert_eq!(target.capture_checkpoint(), checkpoint);
    assert_eq!(target.bar_types(), vec![a.clone()]);
    for end in [2, 3, 4] {
        let expected = apply(&mut reference, &[bar(A, 1, end)], &a, end);
        let actual = apply(&mut target, &[bar(A, 1, end)], &a, end);
        assert_eq!(actual, expected);
        assert_eq!(target.capture_checkpoint(), reference.capture_checkpoint());
    }
    assert_eq!(saved.primary_bar(), bar(A, 1, 1).as_ref());
    let empty = state(2).capture_checkpoint();
    target.restore_checkpoint(&empty).unwrap();
    assert!(target.bar_types().is_empty());
    assert_eq!(saved.version(&a).unwrap(), 1u32.into());
}
