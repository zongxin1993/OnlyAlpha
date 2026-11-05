use onlyalpha_indicators::{ROC, RateOfChangeError};
use std::num::NonZeroUsize;

#[test]
fn measures_fractional_return_at_the_exact_lag() {
    let mut roc = ROC::new(NonZeroUsize::new(2).unwrap());
    assert_eq!(roc.push(Some("4")).unwrap(), None);
    assert_eq!(roc.push(Some("0")).unwrap(), None);
    assert_eq!(
        roc.push(Some("5")).unwrap().as_deref(),
        Some("0.250000000000")
    );
    assert_eq!(roc.push(None).unwrap(), None);
    assert_eq!(
        roc.push(Some("4")).unwrap().as_deref(),
        Some("-0.200000000000")
    );
    assert_eq!(roc.push(Some("7")).unwrap(), None);
}

#[test]
fn rounds_signed_half_ties_and_rejects_invalid_input_before_advancing() {
    let mut roc = ROC::new(NonZeroUsize::MIN);
    assert_eq!(roc.push(Some("-2")).unwrap(), None);
    assert!(roc.push(Some("2e0")).is_err());
    assert_eq!(
        roc.push(Some("-2.000000000003")).unwrap().as_deref(),
        Some("0.000000000002")
    );
    assert_eq!(
        roc.push(Some("0")).unwrap().as_deref(),
        Some("-1.000000000000")
    );
    assert_eq!(roc.push(Some("7")).unwrap(), None);
}

#[test]
fn rejects_both_signs_outside_the_decimal_carrier_without_advancing() {
    let mut roc = ROC::new(NonZeroUsize::MIN);
    assert_eq!(roc.push(Some("0.000000000001")).unwrap(), None);
    for price in [
        "100000000000000.000000000001",
        "-99999999999999.999999999999",
    ] {
        assert_eq!(roc.push(Some(price)), Err(RateOfChangeError::OutOfRange));
    }
    assert_eq!(
        roc.push(Some("100000000000000")).unwrap().as_deref(),
        Some("99999999999999999999999999.000000000000")
    );
}
