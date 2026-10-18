use onlyalpha_domain::identifiers::{OnlyEngineId, OnlyRuntimeId};
use onlyalpha_event::{OnlyEventId, OnlyEventScope};
#[test]
fn explicit_identity_and_scope_are_validated() {
    let id = OnlyEventId::parse("00000000-0000-0000-0000-000000000001").unwrap();
    assert_eq!(id.to_string(), "00000000-0000-0000-0000-000000000001");
    assert!(OnlyEventId::parse("bad").is_err());
    let scope = OnlyEventScope::new(
        OnlyEngineId::new("engine").unwrap(),
        Some(OnlyRuntimeId::new("runtime").unwrap()),
        None,
    )
    .unwrap();
    assert!(scope.includes(&scope));
    let foreign = OnlyEventScope::new(OnlyEngineId::new("other").unwrap(), None, None).unwrap();
    assert!(!scope.includes(&foreign));
}

#[test]
fn scope_hierarchy_has_no_cross_cluster_or_unowned_scope() {
    use onlyalpha_domain::identifiers::OnlyClusterId;
    let engine = OnlyEngineId::new("engine").unwrap();
    let runtime = OnlyRuntimeId::new("runtime").unwrap();
    let wide = OnlyEventScope::new(engine.clone(), None, None).unwrap();
    let runtime_scope = OnlyEventScope::new(engine.clone(), Some(runtime.clone()), None).unwrap();
    let first = OnlyEventScope::new(
        engine.clone(),
        Some(runtime.clone()),
        Some(OnlyClusterId::new("first").unwrap()),
    )
    .unwrap();
    let second = OnlyEventScope::new(
        engine.clone(),
        Some(runtime),
        Some(OnlyClusterId::new("second").unwrap()),
    )
    .unwrap();
    assert!(wide.includes(&first));
    assert!(runtime_scope.includes(&first));
    assert!(runtime_scope.includes(&second));
    assert!(!first.includes(&second));
    assert!(!first.includes(&runtime_scope));
    assert!(
        OnlyEventScope::new(engine, None, Some(OnlyClusterId::new("orphan").unwrap())).is_err()
    );
}

#[test]
fn stable_fact_vocabulary_has_exact_reference_names() {
    use onlyalpha_event::{OnlyEventType, OnlyKnownEventType::*};
    for (kind, name) in [
        (BarReceived, "BAR_RECEIVED"),
        (BarValidated, "BAR_VALIDATED"),
        (DerivedBarCreated, "DERIVED_BAR_CREATED"),
        (BarCacheUpdated, "BAR_CACHE_UPDATED"),
        (IndicatorUpdated, "INDICATOR_UPDATED"),
        (MarketDataSnapshotReady, "MARKET_DATA_SNAPSHOT_READY"),
        (MarketDataPipelineFailed, "MARKET_DATA_PIPELINE_FAILED"),
        (ClusterBarHandled, "CLUSTER_BAR_HANDLED"),
        (ClusterBarHandlerFailed, "CLUSTER_BAR_HANDLER_FAILED"),
    ] {
        assert_eq!(kind.as_str(), name);
        assert_eq!(OnlyEventType::from(kind).value(), name);
    }
}
