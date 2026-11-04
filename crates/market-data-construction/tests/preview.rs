mod support;
use onlyalpha_market_data_construction::*;
use serde_json::json;
use support::*;
#[test]
fn preview_is_read_only_and_never_a_closed_fact() {
    let mut e = time_executor(OnlyMissingPolicy::Reject, OnlyIncompletePolicy::Drop);
    e.process(&fact(1), &stamp(1)).unwrap();
    let before = e.capture_checkpoint().unwrap();
    let forming = altered(&bar(A, 1, 2), "is_closed", json!(false));
    let preview = e.preview(&forming).unwrap().unwrap();
    assert!(!preview.is_closed());
    assert_eq!(preview.volume().value().to_string(), "200");
    assert_eq!(preview.bar_type(), &kind(A, 3));
    assert_eq!(e.capture_checkpoint().unwrap(), before);
    assert!(
        e.process(&OnlyConstructionFact::Bar(preview), &stamp(3))
            .is_err()
    );
    assert_eq!(e.capture_checkpoint().unwrap(), before);
}
