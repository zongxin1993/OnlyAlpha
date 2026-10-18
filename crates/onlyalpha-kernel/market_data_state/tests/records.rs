mod support;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use onlyalpha_market_data_state::*;
use serde_json::{Value, json};
use std::sync::Arc;
use support::*;
fn fields(row: &Value) -> Vec<&str> {
    row.as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect()
}
#[test]
fn current_records_preserve_exact_fields() {
    let mut s = state(2);
    let a = kind(A, 1);
    let root = s
        .apply_closed(
            &[bar(A, 1, 3)],
            &a,
            stamp(3),
            vec!["second".into(), "first".into()],
        )
        .unwrap();
    let view = root
        .restrict("c".parse().unwrap(), &[a.clone(), kind(A, 3)], &a)
        .unwrap();
    let checkpoint = s.capture_checkpoint();
    assert_eq!(
        fields(&checkpoint),
        vec![
            "engine_id",
            "history_limit",
            "runtime_id",
            "schema_version",
            "series"
        ]
    );
    assert_eq!(
        fields(&checkpoint["series"][0]),
        vec!["bar_type", "history", "version"]
    );
    let record = view.to_record();
    assert_eq!(
        fields(&record),
        vec![
            "cluster_id",
            "engine_id",
            "primary_bar_type",
            "quality_flags",
            "runtime_id",
            "schema_version",
            "series",
            "ts_event_ns",
            "ts_init_ns",
            "updated_bar_types",
            "visible_bar_types"
        ]
    );
    assert_eq!(record["engine_id"], "engine");
    assert_eq!(record["runtime_id"], "runtime");
    assert_eq!(record["schema_version"], 2);
    assert_eq!(OnlyMarketDataSnapshot::from_record(&record).unwrap(), view);
    assert_eq!(
        OnlyMarketDataSnapshot::from_json(&view.to_json().unwrap()).unwrap(),
        view
    );
    assert_eq!(view.quality_flags(), &["second", "first"]);
    assert_eq!(view.version(&kind(A, 3)).unwrap(), 0u32.into());
    let mut fresh = state(2);
    fresh.restore_checkpoint(&checkpoint).unwrap();
    assert_eq!(fresh.capture_checkpoint(), checkpoint);
}
#[test]
fn large_versions_restore_and_increment_without_loss() {
    let mut s = state(2);
    let a = kind(A, 1);
    apply(&mut s, &[bar(A, 1, 1)], &a, 1);
    let mut row = s.capture_checkpoint();
    row["series"][0]["version"] = serde_json::from_str("18446744073709551616").unwrap();
    s.restore_checkpoint(&row).unwrap();
    let snap = apply(&mut s, &[bar(A, 1, 2)], &a, 2);
    assert_eq!(s.version(&a).to_string(), "18446744073709551617");
    assert!(
        snap.to_json()
            .unwrap()
            .contains("\"version\":18446744073709551617")
    );
    let mut negative = bar(A, 1, 1).to_record();
    for (field, time) in [
        ("bar_start", "1969-12-31T23:58:59.999999Z"),
        ("bar_end", "1969-12-31T23:59:59.999999Z"),
        ("ts_event", "1969-12-31T23:59:59.999999Z"),
        ("ts_init", "1969-12-31T23:59:59.999999Z"),
    ] {
        negative[field] = json!(time);
    }
    negative["trading_day"] = json!("1969-12-31");
    let mut s = state(2);
    let snap = s
        .apply_closed(
            &[Arc::new(OnlyBar::from_record(&negative).unwrap())],
            &a,
            OnlyTimestamp::from_unix_nanos((-999).into()),
            vec![],
        )
        .unwrap();
    assert_eq!(snap.to_record()["ts_event_ns"], json!(-1000));
    assert_eq!(snap.to_record()["ts_init_ns"], json!(-999));
    assert_eq!(
        OnlyMarketDataSnapshot::from_json(&snap.to_json().unwrap()).unwrap(),
        snap
    );
}
#[test]
fn snapshot_reader_revalidates_relations() {
    let mut s = state(3);
    let a = kind(A, 1);
    apply(&mut s, &[bar(A, 1, 2)], &a, 2);
    let root = apply(&mut s, &[bar(A, 1, 3), bar(A, 3, 3), bar(B, 1, 3)], &a, 3);
    let good = root.to_record();
    let mut cases = vec![];
    for version in [json!(1), json!(3), json!(true), json!(2.0)] {
        let mut row = good.clone();
        row["schema_version"] = version;
        cases.push(row);
    }
    let mut row = good.clone();
    row["extra"] = json!(0);
    cases.push(row);
    let mut row = good.clone();
    row.as_object_mut().unwrap().remove("quality_flags");
    cases.push(row);
    for name in ["series", "visible_bar_types", "updated_bar_types"] {
        let mut row = good.clone();
        let first = row[name][0].clone();
        row[name].as_array_mut().unwrap().push(first);
        cases.push(row);
    }
    let mut row = good.clone();
    row["primary_bar_type"] = kind(A, 2).to_record();
    cases.push(row);
    let mut row = good.clone();
    row["ts_event_ns"] = json!(0);
    cases.push(row);
    let mut row = good.clone();
    row["ts_init_ns"] = json!(0);
    cases.push(row);
    let mut row = good.clone();
    row["series"][0]["history"][0]["bar_type"] = kind(A, 2).to_record();
    cases.push(row);
    let mut row = good.clone();
    row["series"][0]["history"]
        .as_array_mut()
        .unwrap()
        .reverse();
    cases.push(row);
    let mut row = good.clone();
    row["series"][0]["version"] = json!(0);
    cases.push(row);
    for row in cases {
        assert!(
            matches!(
                OnlyMarketDataSnapshot::from_record(&row),
                Err(OnlyMarketDataStateError::Record(_))
            ),
            "accepted {row}"
        );
    }
    assert!(OnlyMarketDataSnapshot::from_record(&s.capture_checkpoint()).is_err());
    let mut reordered = good.clone();
    for name in ["series", "visible_bar_types", "updated_bar_types"] {
        reordered[name].as_array_mut().unwrap().reverse();
    }
    assert_eq!(
        OnlyMarketDataSnapshot::from_record(&reordered)
            .unwrap()
            .to_record(),
        good
    );
    let view = root
        .restrict("c".parse().unwrap(), std::slice::from_ref(&a), &a)
        .unwrap();
    let row = view.to_record();
    assert_eq!(row["series"].as_array().unwrap().len(), 1);
    assert!(!view.to_json().unwrap().contains(B));
    assert!(!view.to_json().unwrap().contains("indicator"));
    assert!(!view.to_json().unwrap().contains("partial"));
}
