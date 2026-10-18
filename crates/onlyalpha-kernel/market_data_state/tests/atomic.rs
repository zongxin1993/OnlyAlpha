mod support;
use onlyalpha_domain::time::OnlyTimestamp;
use onlyalpha_market_data_state::*;
use serde_json::json;
use support::*;
#[test]
fn failed_batch_or_snapshot_is_not_a_prefix_commit() {
    let mut s = state(2);
    let k = kind(A, 1);
    let slow = kind(A, 3);
    apply(&mut s, &[bar(A, 1, 3), bar(A, 3, 3)], &k, 3);
    let bad = vec![
        vec![bar(A, 1, 4), bar(A, 3, 3)],
        vec![],
        vec![bar(A, 1, 4), bar(A, 1, 4)],
        vec![altered(&bar(A, 1, 4), "is_closed", json!(false))],
        vec![altered(&bar(A, 1, 4), "revision", json!(1))],
        vec![bar(A, 3, 6)],
    ];
    for batch in bad {
        assert!(s.apply_closed(&batch, &k, stamp(6), vec![]).is_err());
        assert_eq!(s.version(&k), 1u32.into());
        assert_eq!(s.version(&slow), 1u32.into());
        assert_eq!(s.latest_closed(&k), Some(bar(A, 1, 3).as_ref()));
    }
    let init = OnlyTimestamp::from_unix_nanos(stamp(4).unix_nanos() - 1);
    assert!(matches!(
        s.apply_closed(&[bar(A, 1, 4)], &k, init, vec![]),
        Err(OnlyMarketDataStateError::Time)
    ));
    assert_eq!(s.version(&k), 1u32.into());
}
#[test]
fn logical_init_and_multinstrument_anchor() {
    let mut s = state(4);
    let k = kind(A, 1);
    let acquired = altered(&bar(A, 1, 3), "ts_init", json!("2026-10-01T00:00:00Z"));
    let init = OnlyTimestamp::from_unix_nanos(stamp(3).unix_nanos() + 17);
    s.apply_closed(&[acquired], &k, init, vec![]).unwrap();
    apply(&mut s, &[bar(B, 1, 5)], &kind(B, 1), 5);
    assert!(
        s.apply_closed(&[bar(A, 1, 4)], &k, stamp(4), vec![])
            .is_err()
    );
    assert_eq!(s.version(&k), 1u32.into());
    let snap = apply(&mut s, &[bar(A, 1, 6)], &k, 6);
    assert_eq!(snap.series().len(), 2);
}
