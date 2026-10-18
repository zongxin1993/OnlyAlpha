mod support;
use onlyalpha_market_data_state::*;
use support::*;
#[test]
fn query_scope_is_distinct_from_local_miss() {
    let mut s = state(4);
    let a = kind(A, 1);
    let a3 = kind(A, 3);
    let b = kind(B, 1);
    let root = apply(&mut s, &[bar(A, 1, 3)], &a, 3);
    let view = root
        .restrict("c".parse().unwrap(), &[a.clone(), a3.clone()], &a)
        .unwrap();
    assert_eq!(view.scope(), s.scope());
    assert_eq!(view.cluster_id().unwrap().value(), "c");
    assert_eq!(view.ts_event(), &stamp(3));
    assert_eq!(view.ts_init(), &stamp(3));
    assert_eq!(view.primary_bar_type(), &a);
    assert!(view.quality_flags().is_empty());
    assert!(view.latest_closed(&a3).unwrap().is_none());
    assert!(view.history(&a3, 10).unwrap().is_empty());
    assert_eq!(view.version(&a3).unwrap(), 0u32.into());
    assert!(!view.was_updated(&a3).unwrap());
    assert!(view.current_partial(&a3).unwrap().is_none());
    assert!(matches!(
        view.require_latest_closed(&a3),
        Err(OnlyMarketDataStateError::MissingData)
    ));
    for outside in [b, kind(A, 2)] {
        assert!(matches!(
            view.latest_closed(&outside),
            Err(OnlyMarketDataStateError::Scope)
        ));
        assert!(matches!(
            view.history(&outside, 1),
            Err(OnlyMarketDataStateError::Scope)
        ));
        assert!(matches!(
            view.version(&outside),
            Err(OnlyMarketDataStateError::Scope)
        ));
        assert!(matches!(
            view.was_updated(&outside),
            Err(OnlyMarketDataStateError::Scope)
        ));
        assert!(matches!(
            view.current_partial(&outside),
            Err(OnlyMarketDataStateError::Scope)
        ));
    }
    assert!(matches!(
        view.history(&a, 0),
        Err(OnlyMarketDataStateError::Configuration)
    ));
    apply(&mut s, &[bar(A, 3, 3)], &a3, 3);
    let newer = apply(&mut s, &[bar(A, 1, 4)], &a, 4);
    assert!(matches!(
        newer.require_same_event_time(&a3),
        Err(OnlyMarketDataStateError::Time)
    ));
    assert_eq!(
        newer.require_same_event_time(&a).unwrap(),
        bar(A, 1, 4).as_ref()
    );
}
#[test]
fn restrict_never_widens_or_changes_owner() {
    let mut s = state(4);
    let a = kind(A, 1);
    let a3 = kind(A, 3);
    let b = kind(B, 1);
    let root = apply(&mut s, &[bar(A, 1, 3), bar(A, 3, 3), bar(B, 1, 3)], &a, 3);
    for (allowed, primary) in [
        (vec![], a.clone()),
        (vec![a.clone(), a.clone()], a.clone()),
        (vec![a.clone(), b.clone()], a.clone()),
        (vec![a.clone()], a3.clone()),
        (vec![kind(A, 2)], kind(A, 2)),
    ] {
        assert!(
            root.restrict("c".parse().unwrap(), &allowed, &primary)
                .is_err()
        );
    }
    let view = root
        .restrict("c".parse().unwrap(), &[a.clone(), a3.clone()], &a)
        .unwrap();
    let narrow = view
        .restrict("c".parse().unwrap(), std::slice::from_ref(&a), &a)
        .unwrap();
    assert_eq!(narrow.visible_bar_types(), vec![a.clone()]);
    assert_eq!(narrow.series().len(), 1);
    assert_eq!(narrow.updated_bar_types(), vec![a.clone()]);
    assert!(
        narrow
            .restrict("c".parse().unwrap(), &[a.clone(), a3.clone()], &a)
            .is_err()
    );
    assert!(
        view.restrict("sibling".parse().unwrap(), std::slice::from_ref(&a), &a)
            .is_err()
    );
    let sibling = root
        .restrict("sibling".parse().unwrap(), std::slice::from_ref(&b), &b)
        .unwrap();
    assert_eq!(sibling.series().len(), 1);
    assert_eq!(sibling.scope(), root.scope());
    let older = apply(&mut s, &[bar(A, 1, 4)], &a, 4);
    assert!(
        older
            .restrict("c".parse().unwrap(), std::slice::from_ref(&a3), &a3)
            .is_err()
    );
}
#[test]
fn snapshot_survives_updates_without_alias() {
    let mut s = state(2);
    let a = kind(A, 1);
    let old = apply(&mut s, &[bar(A, 1, 1)], &a, 1);
    let view = old
        .restrict("c".parse().unwrap(), std::slice::from_ref(&a), &a)
        .unwrap();
    let mut detached = view.history(&a, 2).unwrap();
    detached.clear();
    apply(&mut s, &[bar(A, 1, 2)], &a, 2);
    assert_eq!(view.history(&a, 99).unwrap(), vec![bar(A, 1, 1)]);
    assert_eq!(old.version(&a).unwrap(), 1u32.into());
    assert!(std::sync::Arc::ptr_eq(&old.series()[0], &view.series()[0]));
}
