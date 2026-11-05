use onlyalpha_indicators::{
    ATR, FinancialInputError, FinancialValue, OBV, RSI, RSIZone, Stochastic, UtcSessionVWAP, VWAP,
};
use std::num::NonZeroUsize;

fn period(value: usize) -> NonZeroUsize {
    NonZeroUsize::new(value).unwrap()
}

fn ready(value: &str) -> FinancialValue {
    FinancialValue::Ready(value.into())
}

#[test]
fn obv_compares_closes_and_retains_exact_state_after_overflow() {
    let mut obv = OBV::new();
    let max = "99999999999999999999999999.999999999999";
    assert_eq!(
        obv.push(Some("10"), Some(max)).unwrap(),
        ready("0.000000000000")
    );
    assert_eq!(obv.push(Some("11"), Some(max)).unwrap(), ready(max));
    assert_eq!(
        obv.push(Some("12"), Some("0.000000000001")).unwrap(),
        FinancialValue::OutOfRange
    );
    assert_eq!(
        obv.push(Some("13"), Some("-1")),
        Err(FinancialInputError::NegativeVolume)
    );
    assert_eq!(
        obv.push(Some("11"), Some("0.000000000001")).unwrap(),
        ready(max)
    );
    assert_eq!(obv.push(Some("11"), Some(max)).unwrap(), ready(max));
    assert_eq!(obv.push(None, Some("1")).unwrap(), FinancialValue::Missing);
    assert_eq!(
        obv.push(Some("14"), Some("1")).unwrap(),
        FinancialValue::Missing
    );
}

#[test]
fn vwap_tracks_missing_and_zero_volume_without_poisoning_later_windows() {
    let mut vwap = VWAP::new(period(2));
    assert_eq!(
        vwap.push(Some("10"), Some("0")).unwrap(),
        FinancialValue::Warmup
    );
    assert_eq!(
        vwap.push(Some("20"), Some("0")).unwrap(),
        FinancialValue::Undefined
    );
    assert_eq!(
        vwap.push(Some("20"), Some("-1")),
        Err(FinancialInputError::NegativeVolume)
    );
    assert_eq!(
        vwap.push(Some("30"), Some("1")).unwrap(),
        ready("30.000000000000")
    );
    assert_eq!(
        vwap.push(Some("40"), Some("3")).unwrap(),
        ready("37.500000000000")
    );
    assert_eq!(
        vwap.push(Some("50"), None).unwrap(),
        FinancialValue::Missing
    );
    assert_eq!(
        vwap.push(Some("60"), Some("1")).unwrap(),
        FinancialValue::Missing
    );
    assert_eq!(
        vwap.push(Some("70"), Some("1")).unwrap(),
        ready("65.000000000000")
    );
}

#[test]
fn utc_session_vwap_uses_typical_prices_and_resets_at_the_utc_boundary() {
    let mut vwap = UtcSessionVWAP::new();
    let midnight = 86_400_000_000_000;
    assert_eq!(
        vwap.push(midnight - 2, "12", "9", "10", "2").unwrap(),
        ready("10.333333333333")
    );
    assert_eq!(
        vwap.push(midnight - 2, "99", "99", "99", "2"),
        Err(FinancialInputError::InvalidTimestampOrder)
    );
    assert_eq!(
        vwap.push(midnight - 1, "15", "12", "15", "1").unwrap(),
        ready("11.555555555556")
    );
    assert_eq!(
        vwap.push(midnight, "20", "20", "20", "0").unwrap(),
        FinancialValue::Undefined
    );
    assert_eq!(
        vwap.push(midnight + 1, "24", "21", "21", "1").unwrap(),
        ready("22.000000000000")
    );
}

#[test]
fn stochastic_uses_the_window_extrema_and_a_complete_window_of_k_values() {
    let mut oscillator = Stochastic::new(period(2), period(2));
    let first = oscillator.push(Some("10"), Some("0"), Some("2")).unwrap();
    assert_eq!(first.k, FinancialValue::Warmup);
    let second = oscillator.push(Some("12"), Some("2"), Some("6")).unwrap();
    assert_eq!(second.k, ready("50.000000000000"));
    assert_eq!(second.d, FinancialValue::Warmup);
    let third = oscillator.push(Some("14"), Some("4"), Some("8")).unwrap();
    assert_eq!(third.k, ready("50.000000000000"));
    assert_eq!(third.d, ready("50.000000000000"));
    assert_eq!(
        oscillator.push(Some("3"), Some("4"), Some("4")),
        Err(FinancialInputError::InvalidPriceRange)
    );
    let missing = oscillator.push(Some("14"), Some("4"), None).unwrap();
    assert_eq!(missing.k, FinancialValue::Missing);
    assert_eq!(missing.d, FinancialValue::Missing);

    let flat = Stochastic::new(period(1), period(1))
        .push(Some("7"), Some("7"), Some("7"))
        .unwrap();
    assert_eq!(flat.k, FinancialValue::Undefined);
    assert_eq!(flat.d, FinancialValue::Undefined);
}

#[test]
fn slow_stochastic_smooths_raw_k_before_computing_d() {
    let mut oscillator = Stochastic::slow(period(2), period(2), period(2));
    oscillator.push(Some("10"), Some("0"), Some("2")).unwrap();
    let second = oscillator.push(Some("12"), Some("2"), Some("6")).unwrap();
    assert_eq!(second.k, FinancialValue::Warmup);
    let third = oscillator.push(Some("14"), Some("4"), Some("14")).unwrap();
    assert_eq!(third.k, ready("75.000000000000"));
    assert_eq!(third.d, FinancialValue::Warmup);
    let fourth = oscillator.push(Some("16"), Some("6"), Some("13")).unwrap();
    assert_eq!(fourth.k, ready("87.500000000000"));
    assert_eq!(fourth.d, ready("81.250000000000"));
}

#[test]
fn atr_seeds_with_true_ranges_then_uses_wilder_smoothing() {
    let mut atr = ATR::new(period(2));
    assert_eq!(
        atr.push("10", "8", "9").unwrap().atr,
        FinancialValue::Warmup
    );
    assert_eq!(
        atr.push("7", "8", "8"),
        Err(FinancialInputError::InvalidPriceRange)
    );
    let seeded = atr.push("16", "14", "15").unwrap();
    assert_eq!(seeded.atr, ready("4.500000000000"));
    assert_eq!(seeded.normalized_atr, ready("0.300000000000"));
    let smoothed = atr.push("16", "14", "15").unwrap();
    assert_eq!(smoothed.atr, ready("3.250000000000"));
    assert_eq!(smoothed.normalized_atr, ready("0.216666666667"));
    let zero = atr.push("1", "0", "0").unwrap();
    assert_eq!(zero.normalized_atr, FinancialValue::Undefined);
}

#[test]
fn rsi_needs_a_baseline_and_period_changes_before_wilder_smoothing() {
    let mut rsi = RSI::new(period(2));
    assert_eq!(rsi.push("10").unwrap().value, FinancialValue::Warmup);
    assert_eq!(rsi.push("12").unwrap().value, FinancialValue::Warmup);
    assert_eq!(
        rsi.push("invalid"),
        Err(FinancialInputError::InvalidDecimal)
    );
    let seeded = rsi.push("11").unwrap();
    assert_eq!(seeded.value, ready("66.666666666667"));
    assert_eq!(seeded.zone, RSIZone::Neutral);
    assert_eq!(rsi.push("10").unwrap().value, ready("40.000000000000"));

    let mut edge = RSI::new(period(1));
    edge.push("5").unwrap();
    let flat = edge.push("5").unwrap();
    assert_eq!(flat.value, ready("50.000000000000"));
    assert_eq!(flat.zone, RSIZone::Neutral);
    assert_eq!(edge.push("6").unwrap().zone, RSIZone::Overbought);
    assert_eq!(edge.push("5").unwrap().zone, RSIZone::Oversold);
}
