mod support;
use onlyalpha_market_data_delivery::*;
use serde_json::{Value, json};
use support::*;
fn configured() -> OnlyMarketDataDelivery {
    let mut d = delivery();
    for id in ["a", "z"] {
        d.register(
            id.parse().unwrap(),
            subscription(id, 1, OnlyBarFreshness::LatestClosed),
        )
        .unwrap();
    }
    d
}
#[test]
fn checkpoint_mutations_are_strict_complete_and_atomic() {
    let mut d = configured();
    let mut s = state(2);
    d.route(&apply(&mut s, &[bar(A, 1, 1)], &kind(A, 1), 1))
        .unwrap();
    let before = d.capture_checkpoint();
    d.route(&apply(&mut s, &[bar(A, 1, 3)], &kind(A, 1), 3))
        .unwrap();
    let later = d.capture_checkpoint();
    d.restore_checkpoint(&before).unwrap();
    let mut invalid_late = later.clone();
    invalid_late["registrations"][1]["last_planned_event_ns"] = json!(true);
    assert!(d.restore_checkpoint(&invalid_late).is_err());
    assert_eq!(d.capture_checkpoint(), before);
    for field in ["engine_id", "runtime_id"] {
        for value in [
            json!("other"),
            json!(format!(" {} ", before[field].as_str().unwrap())),
            json!(null),
        ] {
            let mut row = before.clone();
            row[field] = value;
            assert!(d.restore_checkpoint(&row).is_err());
            assert_eq!(d.capture_checkpoint(), before);
        }
    }
    for invalid in [
        json!(true),
        json!("1"),
        json!(1.0),
        json!(1),
        serde_json::from_str::<Value>("99999999999999999999999999999999999999").unwrap(),
    ] {
        let mut row = before.clone();
        row["registrations"][1]["last_planned_event_ns"] = invalid;
        assert!(d.restore_checkpoint(&row).is_err());
        assert_eq!(d.capture_checkpoint(), before);
    }
    for mutation in [
        "duplicate",
        "missing",
        "foreign",
        "sub",
        "graph",
        "extra",
        "old",
    ] {
        let mut row = before.clone();
        match mutation {
            "duplicate" => {
                let item = row["registrations"][0].clone();
                row["registrations"].as_array_mut().unwrap().push(item);
            }
            "missing" => {
                row["registrations"].as_array_mut().unwrap().pop();
            }
            "foreign" => row["registrations"][0]["cluster_id"] = json!("else"),
            "sub" => {
                row["registrations"][0]["subscription"] =
                    subscription("other", 1, OnlyBarFreshness::LatestClosed).to_record()
            }
            "graph" => {
                row["registrations"][0]["subscription"]["dependency_graph"]["provider_inputs"] =
                    json!([])
            }
            "extra" => row["extra"] = json!(false),
            _ => row["schema_version"] = json!(0),
        }
        assert!(d.restore_checkpoint(&row).is_err(), "{mutation}");
        assert_eq!(d.capture_checkpoint(), before);
    }
    let mut reordered = later.clone();
    reordered["registrations"].as_array_mut().unwrap().reverse();
    d.restore_checkpoint(&reordered).unwrap();
    assert_eq!(d.capture_checkpoint(), later);
    let mut empty = delivery();
    assert!(empty.restore_checkpoint(&later).is_err());
    assert_eq!(empty.subscription_count(), 0);
}
#[test]
fn fresh_configured_restore_replays_identically_and_retains_one_watermark() {
    let mut original = configured();
    let mut s = state(1);
    original
        .route(&apply(&mut s, &[bar(A, 1, 1)], &kind(A, 1), 1))
        .unwrap();
    let saved = original.capture_checkpoint();
    let mut fresh = configured();
    fresh.restore_checkpoint(&saved).unwrap();
    fresh.restore_checkpoint(&saved).unwrap();
    for end in 2..=1000 {
        let snapshot = apply(&mut s, &[bar(A, 1, end)], &kind(A, 1), end);
        assert_eq!(
            fresh.route(&snapshot).unwrap(),
            original.route(&snapshot).unwrap()
        );
    }
    let checkpoint = fresh.capture_checkpoint();
    assert_eq!(checkpoint["registrations"].as_array().unwrap().len(), 2);
    for row in checkpoint["registrations"].as_array().unwrap() {
        assert_eq!(row.as_object().unwrap().len(), 3);
        assert!(row["last_planned_event_ns"].is_number());
    }
    assert_eq!(checkpoint, original.capture_checkpoint());
}
