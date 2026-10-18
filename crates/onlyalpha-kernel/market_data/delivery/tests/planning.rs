mod support;
use onlyalpha_market_data_delivery::*;
use onlyalpha_market_data_state::{OnlyMarketDataState, OnlyMarketDataStateConfig};
use serde_json::json;
use support::*;
#[test]
fn subscription_validates_explicit_identity_graph_primary_and_records() {
    let kinds = vec![kind(A, 3), kind(A, 1)];
    let s = OnlyBarSubscription::new(
        "explicit",
        kinds.clone(),
        graph(&kinds),
        None,
        OnlyBarFreshness::LatestClosed,
    )
    .unwrap();
    assert_eq!(s.primary(), &kind(A, 1));
    assert_eq!(s.bar_types(), &[kind(A, 1), kind(A, 3)]);
    assert_eq!(OnlyBarSubscription::from_record(&s.to_record()).unwrap(), s);
    assert!(
        OnlyBarSubscription::new(
            " spaced ",
            kinds.clone(),
            graph(&kinds),
            None,
            OnlyBarFreshness::LatestClosed
        )
        .is_err()
    );
    assert!(
        OnlyBarSubscription::new(
            "id",
            vec![kind(A, 1), kind(A, 1)],
            graph(&[kind(A, 1)]),
            None,
            OnlyBarFreshness::LatestClosed
        )
        .is_err()
    );
    assert!(
        OnlyBarSubscription::new(
            "id",
            vec![kind(A, 1)],
            graph(&kinds),
            None,
            OnlyBarFreshness::LatestClosed
        )
        .is_err()
    );
    assert!(
        OnlyBarSubscription::new(
            "id",
            kinds.clone(),
            graph(&kinds),
            Some(kind(A, 5)),
            OnlyBarFreshness::LatestClosed
        )
        .is_err()
    );
    let foreign = vec![kind(A, 1), kind(B, 3)];
    assert!(
        OnlyBarSubscription::new(
            "id",
            foreign.clone(),
            graph(&foreign),
            None,
            OnlyBarFreshness::LatestClosed
        )
        .is_err()
    );
    for field in [
        "subscription_id",
        "delivery_mode",
        "freshness_policy",
        "schema_version",
    ] {
        let mut row = s.to_record();
        row[field] = json!(false);
        assert!(OnlyBarSubscription::from_record(&row).is_err(), "{field}");
    }
    let mut row = s.to_record();
    row["extra"] = json!(0);
    assert!(OnlyBarSubscription::from_record(&row).is_err());
}
#[test]
fn primary_routing_is_stable_scoped_and_not_registration_order() {
    let mut d = delivery();
    d.register(
        "z".parse().unwrap(),
        subscription("one", 1, OnlyBarFreshness::LatestClosed),
    )
    .unwrap();
    d.register(
        "a".parse().unwrap(),
        subscription("three", 3, OnlyBarFreshness::LatestClosed),
    )
    .unwrap();
    let mut other = delivery();
    other
        .register(
            "a".parse().unwrap(),
            subscription("three", 3, OnlyBarFreshness::LatestClosed),
        )
        .unwrap();
    other
        .register(
            "z".parse().unwrap(),
            subscription("one", 1, OnlyBarFreshness::LatestClosed),
        )
        .unwrap();
    let mut state = state(3);
    let first = apply(&mut state, &[bar(A, 1, 1)], &kind(A, 1), 1);
    let plans = d.route(&first).unwrap();
    assert_eq!(plans.len(), 1);
    assert_eq!(plans[0].cluster_id().value(), "z");
    assert_eq!(plans[0].subscription_id().value(), "one");
    assert_eq!(
        plans[0].snapshot().visible_bar_types(),
        vec![kind(A, 1), kind(A, 3)]
    );
    assert!(plans[0].snapshot().latest_closed(&kind(B, 1)).is_err());
    assert_eq!(other.route(&first).unwrap(), plans);
    let third = apply(&mut state, &[bar(A, 1, 3), bar(A, 3, 3)], &kind(A, 1), 3);
    let plans = d.route(&third).unwrap();
    assert_eq!(
        plans
            .iter()
            .map(|p| p.cluster_id().value())
            .collect::<Vec<_>>(),
        vec!["a", "z"]
    );
    assert_eq!(other.route(&third).unwrap(), plans);
    assert_eq!(other.capture_checkpoint(), d.capture_checkpoint());
    let before = d.capture_checkpoint();
    assert!(d.route(&third).is_err());
    assert!(d.route(&first).is_err());
    assert_eq!(d.capture_checkpoint(), before);
}
#[test]
fn freshness_and_foreign_context_fail_before_any_watermark_commit() {
    let mut d = delivery();
    d.register(
        "a".parse().unwrap(),
        subscription("latest", 1, OnlyBarFreshness::LatestClosed),
    )
    .unwrap();
    d.register(
        "z".parse().unwrap(),
        subscription("same", 1, OnlyBarFreshness::SameEventTime),
    )
    .unwrap();
    let mut state = state(2);
    let incomplete = apply(&mut state, &[bar(A, 1, 1)], &kind(A, 1), 1);
    let before = d.capture_checkpoint();
    assert!(d.route(&incomplete).is_err());
    assert_eq!(d.capture_checkpoint(), before);
    let complete = apply(&mut state, &[bar(A, 1, 3), bar(A, 3, 3)], &kind(A, 1), 3);
    assert_eq!(d.route(&complete).unwrap().len(), 2);
    let view = complete
        .restrict("a".parse().unwrap(), &[kind(A, 1)], &kind(A, 1))
        .unwrap();
    let before = d.capture_checkpoint();
    assert!(d.route(&view).is_err());
    assert_eq!(d.capture_checkpoint(), before);
    let mut foreign = OnlyMarketDataState::new(
        scope("other", "runtime"),
        OnlyMarketDataStateConfig::default(),
    )
    .unwrap();
    let foreign = apply(&mut foreign, &[bar(A, 1, 4)], &kind(A, 1), 4);
    assert!(d.route(&foreign).is_err());
    assert_eq!(d.capture_checkpoint(), before);
}
#[test]
fn same_timestamp_can_plan_different_clusters_in_separate_input_batches() {
    let mut d = delivery();
    d.register(
        "one".parse().unwrap(),
        subscription("one", 1, OnlyBarFreshness::LatestClosed),
    )
    .unwrap();
    d.register(
        "three".parse().unwrap(),
        subscription("three", 3, OnlyBarFreshness::LatestClosed),
    )
    .unwrap();
    let mut s = state(2);
    let one = apply(&mut s, &[bar(A, 1, 3)], &kind(A, 1), 3);
    assert_eq!(d.route(&one).unwrap().len(), 1);
    let three = apply(&mut s, &[bar(A, 3, 3)], &kind(A, 3), 3);
    let plans = d.route(&three).unwrap();
    assert_eq!(plans.len(), 1);
    assert_eq!(plans[0].cluster_id().value(), "three");
}
#[test]
fn late_duplicate_does_not_consume_earlier_fresh_registration() {
    let mut d = delivery();
    for (cluster, id) in [("a", "a"), ("z", "z")] {
        d.register(
            cluster.parse().unwrap(),
            subscription(id, 1, OnlyBarFreshness::LatestClosed),
        )
        .unwrap();
    }
    let mut s = state(2);
    let input = apply(&mut s, &[bar(A, 1, 1)], &kind(A, 1), 1);
    d.route(&input).unwrap();
    d.unregister(&"a".parse().unwrap()).unwrap();
    d.register(
        "a".parse().unwrap(),
        subscription("new", 1, OnlyBarFreshness::LatestClosed),
    )
    .unwrap();
    let before = d.capture_checkpoint();
    assert!(d.route(&input).is_err());
    assert_eq!(d.capture_checkpoint(), before);
    assert!(d.unregister(&"absent".parse().unwrap()).is_err());
    assert_eq!(d.capture_checkpoint(), before);
    assert!(
        d.register(
            "a".parse().unwrap(),
            subscription("x", 1, OnlyBarFreshness::LatestClosed)
        )
        .is_err()
    );
    assert!(
        d.register(
            "new".parse().unwrap(),
            subscription("z", 1, OnlyBarFreshness::LatestClosed)
        )
        .is_err()
    );
    assert_eq!(d.capture_checkpoint(), before);
}
#[test]
fn non_time_requires_explicit_primary_and_equal_strides_use_canonical_tie_break() {
    use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBarType};
    let mut tick = kind(A, 1).to_record();
    tick["semantic"]["formation"] = json!({"schema_version":1,"kind":"TICK_COUNT","count":2});
    let tick = OnlyBarType::from_record(&tick).unwrap();
    let kinds = vec![kind(A, 1), tick.clone()];
    assert!(
        OnlyBarSubscription::new(
            "tick",
            kinds.clone(),
            graph(&kinds),
            None,
            OnlyBarFreshness::LatestClosed
        )
        .is_err()
    );
    assert!(
        OnlyBarSubscription::new(
            "tick",
            kinds.clone(),
            graph(&kinds),
            Some(tick),
            OnlyBarFreshness::LatestClosed
        )
        .is_ok()
    );
    let mut rolling = kind(A, 3).to_record();
    rolling["semantic"]["formation"]["stride_minutes"] = json!(1);
    let rolling = OnlyBarType::from_record(&rolling).unwrap();
    let kinds = vec![rolling, kind(A, 1)];
    let sub = OnlyBarSubscription::new(
        "tie",
        kinds.clone(),
        graph(&kinds),
        None,
        OnlyBarFreshness::LatestClosed,
    )
    .unwrap();
    assert_eq!(sub.primary(), &kind(A, 1));
    let mut row = sub.to_record();
    row["delivery_mode"] = json!("EACH_BAR");
    assert!(OnlyBarSubscription::from_record(&row).is_err());
}
#[test]
fn stale_secondary_rejects_without_consuming_latest_closed_plan() {
    let mut d = delivery();
    d.register(
        "a".parse().unwrap(),
        subscription("latest", 1, OnlyBarFreshness::LatestClosed),
    )
    .unwrap();
    d.register(
        "z".parse().unwrap(),
        subscription("same", 1, OnlyBarFreshness::SameEventTime),
    )
    .unwrap();
    let mut s = state(2);
    let first = apply(&mut s, &[bar(A, 1, 3), bar(A, 3, 3)], &kind(A, 1), 3);
    let plans = d.route(&first).unwrap();
    let before = d.capture_checkpoint();
    let newer = apply(&mut s, &[bar(A, 1, 4)], &kind(A, 1), 4);
    assert!(d.route(&newer).is_err());
    assert_eq!(d.capture_checkpoint(), before);
    assert_eq!(plans[0].snapshot().ts_event(), &stamp(3));
}
#[test]
fn one_runtime_can_deliver_isolated_views_for_multiple_instruments() {
    let mut d = delivery();
    d.register(
        "a".parse().unwrap(),
        subscription("a", 1, OnlyBarFreshness::LatestClosed),
    )
    .unwrap();
    let kinds = vec![kind(B, 1)];
    d.register(
        "b".parse().unwrap(),
        OnlyBarSubscription::new(
            "b",
            kinds.clone(),
            graph(&kinds),
            None,
            OnlyBarFreshness::LatestClosed,
        )
        .unwrap(),
    )
    .unwrap();
    let mut s = state(2);
    let snapshot = apply(&mut s, &[bar(A, 1, 1), bar(B, 1, 1)], &kind(A, 1), 1);
    let plans = d.route(&snapshot).unwrap();
    assert_eq!(plans.len(), 2);
    assert!(plans[0].snapshot().latest_closed(&kind(B, 1)).is_err());
    assert!(plans[1].snapshot().latest_closed(&kind(A, 1)).is_err());
}
