mod support;
use onlyalpha_market_data_state::*;
use support::*;
#[test]
fn state_defaults_and_local_misses() {
    assert!(matches!(
        OnlyMarketDataState::new(
            scope("e", "r"),
            OnlyMarketDataStateConfig { history_limit: 0 }
        ),
        Err(OnlyMarketDataStateError::Configuration)
    ));
    let s = OnlyMarketDataState::new(scope("e", "r"), Default::default()).unwrap();
    let k = kind(A, 1);
    assert_eq!(s.history_limit(), 1024);
    assert!(s.latest_closed(&k).is_none());
    assert!(s.history(&k, 1).unwrap().is_empty());
    assert_eq!(s.version(&k), 0u32.into());
    assert!(s.current_partial(&k).is_none());
    assert!(matches!(
        s.history(&k, 0),
        Err(OnlyMarketDataStateError::Configuration)
    ));
}
#[test]
fn bounded_history_keeps_exact_lifetime_version() {
    let mut s = state(2);
    let k = kind(A, 1);
    let first = bar(A, 1, 1);
    let saved = apply(&mut s, &[first.clone()], &k, 1);
    for end in [2, 3] {
        apply(&mut s, &[bar(A, 1, end)], &k, end);
    }
    assert_eq!(s.history(&k, 99).unwrap(), vec![bar(A, 1, 2), bar(A, 1, 3)]);
    assert_eq!(s.version(&k), 3u32.into());
    assert_eq!(s.latest_closed(&k), Some(bar(A, 1, 3).as_ref()));
    assert_eq!(saved.primary_bar(), first.as_ref());
    assert_eq!(saved.series()[0].version(), &1u32.into());
}
