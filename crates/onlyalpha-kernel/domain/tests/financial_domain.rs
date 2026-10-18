use onlyalpha_domain::{
    base::OnlyDomainModel,
    enums::OnlyCurrencyType,
    identifiers::{OnlyInstrumentId, OnlySymbol, OnlyVenueId},
    numeric::{
        OnlyDecimal, only_add, only_divide, only_multiply, only_quantize, only_remainder,
        only_subtract,
    },
    value::{OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity},
};
use std::str::FromStr;

#[test]
fn independent_numeric_policy_vectors_preserve_exact_results() {
    for line in include_str!("../../../../test-data/domain/numeric-v1.tsv")
        .lines()
        .filter(|s| !s.starts_with('#'))
    {
        let row: Vec<_> = line.split('\t').collect();
        assert_eq!(row.len(), 4);
        let left = OnlyDecimal::from_str(row[1]).unwrap();
        let right = OnlyDecimal::from_str(row[2]).unwrap();
        let result = match row[0] {
            "add" => only_add(&left, &right),
            "subtract" => only_subtract(&left, &right),
            "multiply" => only_multiply(&left, &right),
            "divide" => only_divide(&left, &right),
            "quantize" => only_quantize(&left, &right),
            "remainder" => only_remainder(&left, &right),
            other => panic!("unknown independent vector {other}"),
        }
        .unwrap();
        assert_eq!(result.to_string(), row[3], "{line}");
    }
}

#[test]
fn values_are_validated_and_do_not_narrow_integral_magnitude() {
    let currency = OnlyCurrency::new("usd", 2, OnlyCurrencyType::Fiat).unwrap();
    let a = OnlyMoney::new("999".parse().unwrap(), currency.clone()).unwrap();
    let b = OnlyMoney::new("2".parse().unwrap(), currency.clone()).unwrap();
    assert_eq!(a.checked_add(&b).unwrap().amount().to_string(), "1001");
    let other = OnlyMoney::new(
        "2".parse().unwrap(),
        OnlyCurrency::new("EUR", 2, OnlyCurrencyType::Fiat).unwrap(),
    )
    .unwrap();
    assert!(a.checked_add(&other).unwrap_err().is_validation());
    let digits = "9".repeat(100);
    let big = OnlyQuantity::new(digits.parse().unwrap(), 0).unwrap();
    let two = OnlyQuantity::new("2".parse().unwrap(), 0).unwrap();
    assert_eq!(
        big.checked_add(&two).unwrap().value().to_string(),
        format!("1{}1", "0".repeat(99))
    );
    assert!(OnlyQuantity::new("-1".parse().unwrap(), 0).is_err());
    assert!(OnlyPrice::new("1.001".parse().unwrap(), 2).is_err());
    assert!(OnlyPrice::from_json(r#"{"schema_version":1,"value":1.25,"precision":2}"#).is_err());
    let price =
        OnlyPrice::from_json(r#"{"schema_version":1,"value":"1.25","precision":2}"#).unwrap();
    assert_eq!(
        price.to_json().unwrap(),
        r#"{"precision":2,"schema_version":1,"value":"1.25"}"#
    );
}

#[test]
fn decimal_wire_spelling_and_invalid_inputs_are_explicit() {
    for (input, output) in [
        ("١٢٣.٤٥", "123.45"),
        ("1__2", "12"),
        ("-0.00", "-0.00"),
        ("1E-7", "1E-7"),
        ("1e20", "1E+20"),
        ("1.2300", "1.2300"),
    ] {
        assert_eq!(OnlyDecimal::from_str(input).unwrap().to_string(), output);
    }
    for invalid in ["NaN", "Infinity", "-Infinity", "", "1e", "--1"] {
        assert!(OnlyDecimal::from_str(invalid).is_err(), "{invalid}");
    }
    assert!(only_divide(&"1".parse().unwrap(), &"0".parse().unwrap()).is_err());
}

#[test]
fn identifiers_preserve_symbol_dots_and_unicode_length() {
    let id = OnlyInstrumentId::new(
        OnlySymbol::new(" BRK.B ").unwrap(),
        OnlyVenueId::new("XNAS").unwrap(),
    );
    assert_eq!(id.to_string(), "BRK.B.XNAS");
    assert_eq!(OnlyInstrumentId::from_str(&id.to_string()).unwrap(), id);
    assert_eq!(
        OnlyInstrumentId::from_json(&id.to_json().unwrap()).unwrap(),
        id
    );
    assert!(OnlyVenueId::new("B.C").is_err());
    assert!(OnlySymbol::new("A\u{001c}B").is_err());
    assert!(OnlySymbol::new(&"中".repeat(128)).is_ok());
    assert!(OnlySymbol::new(&"中".repeat(129)).is_err());
}

#[test]
fn independent_record_vectors_have_exact_bytes_and_errors() {
    use onlyalpha_domain::value::{OnlyMultiplier, OnlyPercentage, OnlyRate};
    use serde_json::Value;
    let mut count = 0;
    for line in include_str!("../../../../test-data/domain/value-records-v1.jsonl").lines() {
        let row: Value = serde_json::from_str(line).unwrap();
        let payload = &row["input"];
        let result = match row["type"].as_str().unwrap() {
            "OnlyCurrency" => OnlyCurrency::from_record(payload).and_then(|v| v.to_json()),
            "OnlyPrice" => OnlyPrice::from_record(payload).and_then(|v| v.to_json()),
            "OnlyQuantity" => OnlyQuantity::from_record(payload).and_then(|v| v.to_json()),
            "OnlyMoney" => OnlyMoney::from_record(payload).and_then(|v| v.to_json()),
            "OnlyRate" => OnlyRate::from_record(payload).and_then(|v| v.to_json()),
            "OnlyPercentage" => OnlyPercentage::from_record(payload).and_then(|v| v.to_json()),
            "OnlyMultiplier" => OnlyMultiplier::from_record(payload).and_then(|v| v.to_json()),
            "OnlySymbol" => OnlySymbol::from_record(payload).and_then(|v| v.to_json()),
            "OnlyVenueId" => OnlyVenueId::from_record(payload).and_then(|v| v.to_json()),
            "OnlyInstrumentId" => OnlyInstrumentId::from_record(payload).and_then(|v| v.to_json()),
            _ => panic!("unknown independent record"),
        };
        if row.get("error").is_some() {
            assert!(
                matches!(
                    result,
                    Err(onlyalpha_domain::errors::OnlyDomainError::Serialization(_))
                ),
                "{line}: {result:?}"
            );
        } else {
            assert_eq!(result.unwrap(), row["expected"].as_str().unwrap(), "{line}");
        }
        count += 1;
    }
    assert!(count >= 19);
}

#[test]
fn arithmetic_results_must_remain_in_the_readable_canonical_range() {
    assert!(
        only_multiply(
            &"1E+999999999999999999".parse().unwrap(),
            &"1E+1".parse().unwrap()
        )
        .is_err()
    );
    assert_eq!(
        "1E-1999999999999999997"
            .parse::<OnlyDecimal>()
            .unwrap()
            .to_string(),
        "1E-1999999999999999997"
    );
}

#[test]
fn hashing_compact_exponents_must_not_expand_decimal_zeroes() {
    use std::hash::{Hash, Hasher};
    struct BoundedHasher;
    impl Hasher for BoundedHasher {
        fn finish(&self) -> u64 {
            0
        }
        fn write(&mut self, bytes: &[u8]) {
            assert!(bytes.len() <= 64, "hash expanded compact decimal exponent");
        }
    }
    "1E+10000"
        .parse::<OnlyDecimal>()
        .unwrap()
        .hash(&mut BoundedHasher);
}

#[test]
fn division_keeps_compact_exponents_symbolic() {
    assert_eq!(
        only_divide(
            &"1E+999999999999999999".parse().unwrap(),
            &"1".parse().unwrap()
        )
        .unwrap()
        .to_string(),
        "1E+999999999999999999"
    );
}
