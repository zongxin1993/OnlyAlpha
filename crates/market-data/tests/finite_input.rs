mod support;
use onlyalpha_market_data::finite_input::{Axis, InputError};

#[test]
fn axis_checks_every_position_and_checked_count() {
    let start: i64 = support::stamp(1).unix_nanos().try_into().unwrap();
    let a = Axis::new(start, start + 180_000_000_000, 60_000_000_000, 3).unwrap();
    assert_eq!(a.rows(), 3);
    for (index, minute) in [1, 2, 3].into_iter().enumerate() {
        a.check(index, &support::bar(support::A, 1, minute))
            .unwrap();
    }
    assert!(a.check(1, &support::bar(support::A, 1, 3)).is_err());
    assert!(a.check(3, &support::bar(support::A, 1, 3)).is_err());
    for (start, end, stride, rows) in [
        (0, 3, 2, 1),
        (0, 0, 1, 0),
        (0, 3, 0, 3),
        (0, 3, 1, 2),
        (i64::MIN, i64::MAX, 1, 1),
    ] {
        assert_eq!(
            Axis::new(start, end, stride, rows).unwrap_err(),
            InputError::InvalidAxis
        );
    }
}
