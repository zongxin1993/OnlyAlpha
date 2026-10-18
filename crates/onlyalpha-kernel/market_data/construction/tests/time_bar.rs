mod support;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use onlyalpha_market_data_construction::*;
use serde_json::json;
use support::*;
#[test]
fn exact_aggregation_and_duplicate_after_reset() {
    let mut e = time_executor(OnlyMissingPolicy::Reject, OnlyIncompletePolicy::Drop);
    for end in [1, 2] {
        assert!(e.process(&fact(end), &stamp(end)).unwrap().is_empty());
    }
    let out = e.process(&fact(3), &stamp(3)).unwrap();
    assert_eq!(out.len(), 1);
    let b = &out[0];
    assert_eq!(b.bar_type(), &kind(A, 3));
    assert_eq!(b.open().value().to_string(), "10.00");
    assert_eq!(b.high().value().to_string(), "10.10");
    assert_eq!(b.low().value().to_string(), "9.90");
    assert_eq!(b.close().value().to_string(), "10.05");
    assert_eq!(b.volume().value().to_string(), "300");
    assert_eq!(b.trade_count().as_ref().unwrap(), &3.into());
    assert_eq!(
        *b.bar_start(),
        "2026-01-05T01:30:00Z".parse::<OnlyUtcDateTime>().unwrap()
    );
    assert_eq!(OnlyTimestamp::from_datetime(*b.ts_init()), stamp(3));
    let before = e.capture_checkpoint().unwrap();
    assert!(e.process(&fact(3), &stamp(3)).is_err());
    assert_eq!(e.capture_checkpoint().unwrap(), before);
}
#[test]
fn missing_policies_and_bad_init_are_atomic() {
    let mut strict = time_executor(OnlyMissingPolicy::Reject, OnlyIncompletePolicy::Drop);
    strict.process(&fact(1), &stamp(1)).unwrap();
    let before = strict.capture_checkpoint().unwrap();
    assert!(strict.process(&fact(3), &stamp(3)).is_err());
    assert_eq!(strict.capture_checkpoint().unwrap(), before);
    strict.process(&fact(2), &stamp(2)).unwrap();
    let before = strict.capture_checkpoint().unwrap();
    assert!(strict.process(&fact(3), &stamp(2)).is_err());
    assert_eq!(strict.capture_checkpoint().unwrap(), before);
    let mut skip = time_executor(OnlyMissingPolicy::SkipWindow, OnlyIncompletePolicy::Drop);
    skip.process(&fact(1), &stamp(1)).unwrap();
    assert!(skip.process(&fact(3), &stamp(3)).unwrap().is_empty());
    for end in [4, 5] {
        assert!(skip.process(&fact(end), &stamp(end)).unwrap().is_empty());
    }
    assert_eq!(skip.process(&fact(6), &stamp(6)).unwrap().len(), 1);
}
#[test]
fn historical_acquisition_is_not_logical_init() {
    let mut e = time_executor(OnlyMissingPolicy::Reject, OnlyIncompletePolicy::Drop);
    for end in [1, 2, 3] {
        let b = altered(&bar(A, 1, end), "ts_init", json!("2026-10-01T00:00:00Z"));
        let out = e
            .process(&OnlyConstructionFact::Bar(b), &stamp(end))
            .unwrap();
        if end == 3 {
            assert_eq!(OnlyTimestamp::from_datetime(*out[0].ts_init()), stamp(3));
        }
    }
}
#[test]
fn executor_restore_rejects_foreign_or_inconsistent_state_atomically() {
    let mut e = time_executor(OnlyMissingPolicy::Reject, OnlyIncompletePolicy::Drop);
    e.process(&fact(1), &stamp(1)).unwrap();
    let before = e.capture_checkpoint().unwrap();
    let mut bad = before.clone();
    bad["calendar_fingerprint"] = json!("a".repeat(64));
    assert!(e.restore_checkpoint(&bad).is_err());
    assert_eq!(e.capture_checkpoint().unwrap(), before);
    let mut bad = before.clone();
    bad["state"]["bars"] = json!([bar(A, 1, 2).to_record(), bar(A, 1, 1).to_record()]);
    assert!(e.restore_checkpoint(&bad).is_err());
    assert_eq!(e.capture_checkpoint().unwrap(), before);
    let mut fresh = time_executor(OnlyMissingPolicy::Reject, OnlyIncompletePolicy::Drop);
    fresh.restore_checkpoint(&before).unwrap();
    for end in [2, 3] {
        assert_eq!(
            fresh.process(&fact(end), &stamp(end)).unwrap(),
            e.process(&fact(end), &stamp(end)).unwrap()
        );
    }
}
