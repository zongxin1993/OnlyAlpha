use onlyalpha_indicators::WMA;
use std::num::NonZeroUsize;

#[test]
fn newest_value_receives_the_largest_weight_after_warmup_and_rollover() {
    let mut average = WMA::new(NonZeroUsize::new(3).unwrap());
    assert_eq!(average.push("1").unwrap(), None);
    assert!(average.push("0.0000000000001").is_err());
    assert_eq!(average.push("2").unwrap(), None);
    assert_eq!(average.push("3").unwrap().unwrap(), "2.333333333333");
    assert_eq!(average.push("4").unwrap().unwrap(), "3.333333333333");
}

#[test]
fn weighting_preserves_the_full_decimal_carrier() {
    let mut average = WMA::new(NonZeroUsize::new(2).unwrap());
    let price = "99999999999999999999999999.999999999999";
    assert_eq!(average.push(price).unwrap(), None);
    assert_eq!(average.push(price).unwrap().unwrap(), price);
}
