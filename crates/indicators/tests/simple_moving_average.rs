use onlyalpha_indicators::{SMA, SimpleMovingAverage};
use std::num::NonZeroUsize;

#[test]
fn rust_sma_emits_the_former_worker_reference_sequence() {
    let mut average = SMA::new(NonZeroUsize::new(3).unwrap());
    for (input, expected, ready) in [
        ("1", "1.000000000000", false),
        ("2", "1.500000000000", false),
        ("3", "2.000000000000", true),
        ("4", "3.000000000000", true),
        ("5", "4.000000000000", true),
    ] {
        let point = average.push(input).unwrap();
        assert_eq!((point.value.as_str(), point.ready), (expected, ready));
    }
}

#[test]
fn partial_values_become_ready_and_only_the_latest_window_counts() {
    let mut average = SimpleMovingAverage::new(NonZeroUsize::new(3).unwrap());

    assert_eq!(average.push(12).value, 12);
    let partial = average.push(18);
    assert_eq!(partial.value, 15);
    assert!(!partial.ready);

    let ready = average.push(30);
    assert_eq!(ready.value, 20);
    assert!(ready.ready);
    assert_eq!(average.push(42).value, 30);
}

#[test]
fn averages_round_to_nearest_even_in_both_directions() {
    let period = NonZeroUsize::new(2).unwrap();
    for (left, right, expected) in [(2, 3, 2), (3, 4, 4), (-2, -3, -2), (-3, -4, -4)] {
        let mut average = SimpleMovingAverage::new(period);
        average.push(left);
        assert_eq!(average.push(right).value, expected);
    }
}

#[test]
fn accumulator_can_hold_multiple_extreme_coefficients() {
    let mut average = SimpleMovingAverage::new(NonZeroUsize::new(2).unwrap());

    average.push(i128::MAX);
    assert_eq!(average.push(i128::MAX).value, i128::MAX);
    assert_eq!(average.push(i128::MIN).value, 0);
    assert_eq!(average.push(i128::MIN).value, i128::MIN);
}

#[test]
fn fixed_scale_preserves_the_exact_mean_at_the_decimal_context_boundary() {
    let mut average = SMA::new(NonZeroUsize::new(2).unwrap());
    let input = "9999999999999999.999999999999";

    let first = average.push(input).unwrap();
    assert_eq!(first.value, input);
    assert!(!first.ready);

    let second = average.push(input).unwrap();
    assert_eq!(second.value, input);
    assert!(second.ready);
}

#[test]
fn fixed_scale_emits_fixed_scale_and_rejects_inexact_input_before_updating() {
    let mut average = SMA::new(NonZeroUsize::new(2).unwrap());
    assert_eq!(average.push("-1").unwrap().value, "-1.000000000000");
    for invalid in [
        "1e2",
        "0.0000000000001",
        "100000000000000000000000000",
        "NaN",
    ] {
        assert!(average.push(invalid).is_err(), "{invalid}");
    }
    let ready = average.push("0.000000000001").unwrap();
    assert_eq!(ready.value, "-0.500000000000");
    assert!(ready.ready);
}

#[test]
fn fixed_scale_accepts_the_full_carrier_range_and_normalizes_signed_zero() {
    let mut average = SMA::new(NonZeroUsize::MIN);
    for price in [
        "99999999999999999999999999.999999999999",
        "-99999999999999999999999999.999999999999",
    ] {
        assert_eq!(average.push(price).unwrap().value, price);
    }
    assert_eq!(average.push("-0.0").unwrap().value, "0.000000000000");
}
