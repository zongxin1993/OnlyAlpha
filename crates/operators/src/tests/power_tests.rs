use super::*;
use std::str::FromStr;

fn d(text: &str) -> Decimal {
    Decimal::from_str(text).unwrap()
}

#[test]
fn exact_roots_integral_powers_and_half_even_ties() {
    for (base, exponent, expected) in [
        ("-2", "3.00", "-8"),
        ("-2", "-4", "0.0625"),
        ("-2", "-3", "-0.125"),
        ("81", "0.25", "3"),
        ("32", "-0.2", "0.5"),
        ("2", "0.5", "1.414213562373"),
        ("1.00000000000100000000000025", "0.5", "1"),
        ("1.00000000000300000000000225", "0.5", "1.000000000002"),
        ("-1", "1e1024", "1"),
        ("3", "0", "1"),
        ("0", "1e-1024", "0"),
    ] {
        assert_eq!(
            power(&d(base), &d(exponent)),
            Ok(Some(d(expected))),
            "{base}^{exponent}"
        );
    }
}

#[test]
fn nonintegral_exponents_and_range_bounds() {
    for (base, exponent, expected) in [
        ("2", "0.333333333333", "1.259921049895"),
        ("0.37", "-1.234567890123", "3.412591356718"),
        ("3.141592653589", "2.718281828459", "22.459157718344"),
        ("1e1000", "0.001", "10"),
        ("1e-1000", "0.001", "0.1"),
        ("2", "-1e1024", "0"),
        ("0.001", "1e1024", "0"),
    ] {
        assert_eq!(
            power(&d(base), &d(exponent)),
            Ok(Some(d(expected))),
            "{base}^{exponent}"
        );
    }
    let almost_one = d(&format!("1.{}1", "0".repeat(70)));
    assert_eq!(
        power(&almost_one, &d("1e71")),
        Ok(Some(d("2.718281828459")))
    );
    assert_eq!(power(&d("2"), &d("1e1024")), Err(Error::NumericFailure));
    assert_eq!(power(&d("1e16"), &d("1")), Err(Error::NumericFailure));
}

#[test]
fn undefined_powers_and_rounded_zero() {
    for (base, exponent) in [("-4", "0.5"), ("-32", "0.2"), ("0", "0"), ("0", "-2")] {
        assert_eq!(power(&d(base), &d(exponent)), Ok(None));
    }
    let zero = power(&d("-0.001"), &d("5")).unwrap().unwrap();
    assert_eq!(zero.sign(), Sign::NoSign);
    assert_eq!(zero.to_plain_string(), "0.000000000000");
}
