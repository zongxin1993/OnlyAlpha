//! Native storage identity and proof regression, independent of a Product Host.
use onlyalpha_backend::persistence::market_data::{CoverageStatus, Scope, coverage};
use serde_json::{Value, json};
fn scope() -> Value {
    let fixture: Value =
        serde_json::from_str(include_str!("fixtures/market_wal_history.json")).unwrap();
    let metadata: Value =
        serde_json::from_str(fixture["native_metadata_json"].as_str().unwrap()).unwrap();
    let mut result = json!({});
    for key in [
        "source_id",
        "market",
        "instrument_id",
        "data_kind",
        "start_ns",
        "end_ns",
        "data_version",
        "bar_type",
        "first_sequence",
        "last_sequence",
        "bar_construction",
    ] {
        result[key] = metadata[key].clone();
    }
    result
}
#[test]
fn missing_context_is_unprovable_and_never_empty_complete() {
    let s = Scope::from_record(&scope()).unwrap();
    assert_eq!(
        coverage(&s, &[], &[], 100).unwrap().status(),
        CoverageStatus::Incomplete
    );
    for key in [
        "source_id",
        "instrument_id",
        "bar_construction",
        "data_version",
    ] {
        let mut bad = scope();
        bad.as_object_mut().unwrap().remove(key);
        assert!(Scope::from_record(&bad).is_err(), "{key}");
    }
}
#[test]
fn strict_scope_integer_kinds_and_nested_context() {
    for value in [
        json!(true),
        json!(1.0),
        json!("1"),
        json!({"$serde_json::private::Number":"1"}),
        Value::Null,
    ] {
        let mut bad = scope();
        bad["start_ns"] = value;
        assert!(Scope::from_record(&bad).is_err());
    }
    let mut bad = scope();
    bad["bar_construction"]["plan"]["source_id"] = json!("other");
    assert!(Scope::from_record(&bad).is_err());
}

#[test]
fn exact_native_coverage_and_provenance_dedup_preserve_market_identity() {
    use onlyalpha_backend::persistence::market_data::{Segment, deduplicate_facts};
    use onlyalpha_metadata_json::fingerprint;
    let fixture: Value =
        serde_json::from_str(include_str!("fixtures/market_wal_history.json")).unwrap();
    let metadata: Value =
        serde_json::from_str(fixture["native_metadata_json"].as_str().unwrap()).unwrap();
    let bundle: Value =
        serde_json::from_str(fixture["native_bundle_json"].as_str().unwrap()).unwrap();
    let segment = Segment::from_record(&metadata).unwrap();
    let scope = Scope::from_record(&scope()).unwrap();
    let fact = bundle["canonical_facts"][0].clone();
    assert_eq!(
        coverage(&scope, &[segment], std::slice::from_ref(&fact), 100)
            .unwrap()
            .status(),
        CoverageStatus::Complete
    );
    let mut observation = fact.clone();
    observation["canonical_payload"]["runtime_id"] = json!("another-runtime");
    observation["canonical_payload"]["ts_init"] = json!(1767225660000000001i64);
    observation["canonical_payload_hash"] =
        fingerprint(&observation["canonical_payload"].to_string(), 1024 * 1024)
            .unwrap()
            .into();
    assert_eq!(
        deduplicate_facts(&[fact.clone(), observation.clone()])
            .unwrap()
            .len(),
        1
    );
    observation["canonical_payload"]["data_version"] = json!("DIFFERENT");
    observation["canonical_payload_hash"] =
        fingerprint(&observation["canonical_payload"].to_string(), 1024 * 1024)
            .unwrap()
            .into();
    assert!(deduplicate_facts(&[fact, observation]).is_err());
}
#[test]
fn aligned_native_window_keeps_real_session_remainders_and_before_boundaries() {
    use onlyalpha_backend::persistence::market_data::plan_bar_window;
    use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBarSemantic};
    let target = scope()["bar_construction"]["plan"]["target_semantic"].clone();
    const DAY: i64 = 86_400_000_000_000;
    for step in [1, 3, 5, 7, 15, 240] {
        let mut v = target.clone();
        v["formation"]["window_minutes"] = json!(step);
        v["formation"]["stride_minutes"] = json!(step);
        let semantic = OnlyBarSemantic::from_record(&v).unwrap();
        let plan = plan_bar_window(&semantic, None, 2 * DAY, 3, 100).unwrap();
        assert_eq!(plan.intervals.len(), 3);
        for &(s, e) in &plan.intervals {
            assert_eq!(e - s, step * 60_000_000_000);
            assert_eq!(s / DAY, (e - 1) / DAY);
            assert_eq!((s % DAY) % (step * 60_000_000_000), 0);
        }
        let older = plan_bar_window(&semantic, Some(plan.intervals[0].0), 2 * DAY, 3, 100).unwrap();
        assert!(older.intervals.last().unwrap().1 <= plan.intervals[0].0);
    }
}

#[test]
fn planner_extreme_timestamps_are_total_at_the_public_boundary() {
    use onlyalpha_backend::persistence::market_data::{Error, plan_bar_window};
    use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBarSemantic};
    let target = scope()["bar_construction"]["plan"]["target_semantic"].clone();
    let semantic = OnlyBarSemantic::from_record(&target).unwrap();
    for end in [i64::MIN, i64::MIN + 1, -1, 0] {
        assert_eq!(
            plan_bar_window(&semantic, None, end, 1, 100),
            Err(Error::Invalid)
        );
    }
    for end in [i64::MAX, i64::MAX - 1, i64::MAX - 86_400_000_000_000] {
        let result = plan_bar_window(&semantic, None, end, 2, 100).unwrap();
        assert_eq!(result.intervals.len(), 2);
        assert!(
            result
                .intervals
                .iter()
                .all(|(s, e)| *s >= 0 && s < e && *e <= end)
        );
    }
    assert!(plan_bar_window(&semantic, Some(i64::MIN), i64::MAX, 1, 100).is_err());
    assert!(plan_bar_window(&semantic, Some(i64::MAX - 1), i64::MAX, 1, 100).is_ok());
    for step in [1440, 1441] {
        let mut value = target.clone();
        value["formation"]["window_minutes"] = json!(step);
        value["formation"]["stride_minutes"] = json!(step);
        let semantic = OnlyBarSemantic::from_record(&value).unwrap();
        let result = plan_bar_window(&semantic, None, 172_800_000_000_000, 1, 100);
        if step == 1440 {
            assert_eq!(
                result.unwrap().intervals,
                vec![(86_400_000_000_000, 172_800_000_000_000)]
            );
        } else {
            assert_eq!(result, Err(Error::Invalid));
        }
    }
}
