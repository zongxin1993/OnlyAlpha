use onlyalpha_indicators::{
    Bollinger, BollingerPoint, EMA, FixedScaleAveragePoint, MACD, MACDCross, MACDPoint,
    RollingVolatility, StatisticalError, ZScore,
};
use std::num::NonZeroUsize;

fn period(value: usize) -> NonZeroUsize {
    NonZeroUsize::new(value).unwrap()
}

#[test]
fn ema_carries_guard_digits_between_updates_and_preserves_state_on_invalid_input() {
    let mut ema = EMA::new(period(3));
    assert_eq!(
        ema.push("0").unwrap(),
        FixedScaleAveragePoint {
            value: "0.000000000000".into(),
            ready: false,
        }
    );
    assert_eq!(ema.push("0.000000000001").unwrap().value, "0.000000000000");
    assert!(ema.push("0.0000000000001").is_err());
    assert_eq!(
        ema.push("0.000000000001").unwrap(),
        FixedScaleAveragePoint {
            value: "0.000000000001".into(),
            ready: true,
        }
    );
}

#[test]
fn macd_seeds_each_ema_and_detects_histogram_crossings() {
    assert!(MACD::new(period(3), period(3), period(2)).is_none());
    let mut macd = MACD::new(period(1), period(3), period(3)).unwrap();
    for (price, dif, dea, histogram, cross, ready) in [
        ("10", "0", "0", "0", MACDCross::None, false),
        ("14", "2", "1", "1", MACDCross::Golden, false),
        ("10", "-1", "0", "-1", MACDCross::Death, true),
    ] {
        assert_eq!(
            macd.push(price).unwrap(),
            MACDPoint {
                dif: format!("{dif}.000000000000"),
                dea: format!("{dea}.000000000000"),
                histogram: format!("{histogram}.000000000000"),
                cross,
                ready,
            }
        );
    }
}

#[test]
fn bollinger_updates_both_bands_and_rejects_overflow_without_advancing() {
    let mut bands = Bollinger::new(period(2), "2").unwrap();
    assert!(!bands.push("10").unwrap().ready);
    assert_eq!(
        bands.push("12").unwrap(),
        BollingerPoint {
            middle: "11.000000000000".into(),
            upper: "13.000000000000".into(),
            lower: "9.000000000000".into(),
            ready: true,
        }
    );
    assert_eq!(bands.push("14").unwrap().lower, "11.000000000000");

    assert!(Bollinger::new(period(2), "-1").is_err());
    let mut wide = Bollinger::new(period(2), "10000000000000000000000000").unwrap();
    wide.push("0").unwrap();
    assert_eq!(wide.push("1000"), Err(StatisticalError::OutOfRange));
    assert_eq!(wide.push("0").unwrap().upper, "0.000000000000");
}

#[test]
fn rolling_volatility_uses_population_variance_and_exact_nearest_even() {
    let mut volatility = RollingVolatility::new(period(2));
    volatility.push("90000000000000000000000000").unwrap();
    assert_eq!(
        volatility
            .push("90000000000000000000000000.000000000001")
            .unwrap()
            .value,
        "0.000000000000",
    );
    assert_eq!(
        volatility
            .push("90000000000000000000000000.000000000004")
            .unwrap()
            .value,
        "0.000000000002",
    );
}

#[test]
fn zscore_is_zero_for_a_flat_prefix_and_signed_for_a_varying_window() {
    let mut scores = ZScore::new(period(3));
    assert_eq!(scores.push("3").unwrap().value, "0.000000000000");
    assert_eq!(scores.push("2").unwrap().value, "-1.000000000000");
    assert_eq!(scores.push("1").unwrap().value, "-1.224744871392");
    assert_eq!(scores.push("3").unwrap().value, "1.224744871392");
}
