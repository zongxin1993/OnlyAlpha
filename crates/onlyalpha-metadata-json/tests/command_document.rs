//! Existing Python command-document number normalization, independent of metadata identity.
use onlyalpha_metadata_json::{Error, canonical_json, integral_float_json};
use serde_json::Value;
use sha2::{Digest, Sha256};
const WORK: usize = 8 * 1024 * 1024;
#[test]
fn command_json_preserves_ordinary_numeric_types_and_matches_existing_python() {
    let fixture: Value =
        serde_json::from_str(include_str!("fixtures/command_document.json")).unwrap();
    for vector in fixture["vectors"].as_array().unwrap() {
        assert_eq!(
            integral_float_json(vector["raw"].as_str().unwrap(), WORK).unwrap(),
            vector["normalized"].as_str().unwrap()
        );
    }
}
#[test]
fn new_output_budget_cannot_change_existing_metadata_scan_budget_or_return_partial_json() {
    assert_eq!(canonical_json("1e9", 6).unwrap(), "\"1000000000.0\"");
    assert_eq!(integral_float_json("1e9", 9), Err(Error::Unavailable));
    assert_eq!(integral_float_json("1e9", 10).unwrap(), "1000000000");
    assert_eq!(integral_float_json("1e308", 308), Err(Error::Unavailable));
    assert_eq!(integral_float_json("1e308", 309).unwrap().len(), 309);
    assert_eq!(integral_float_json("{}", 3), Err(Error::Unavailable));
    assert_eq!(integral_float_json("{}", 4).unwrap(), "{}");
    for input in [
        "1e9999",
        "NaN",
        r#"{"a":1,"\u0061":2}"#,
        r#"{"$serde_json::private::Number":1,"$serde_json::private::Number":2}"#,
    ] {
        assert_eq!(integral_float_json(input, WORK), Err(Error::Invalid));
    }
    let nested = format!("{}0{}", "[".repeat(1000), "]".repeat(1000));
    assert_eq!(integral_float_json(&nested, WORK).unwrap(), nested);
    assert_eq!(integral_float_json(&nested, 4096), Err(Error::Unavailable));
}
#[test]
fn finite_binary64_command_documents_match_the_independent_python_aggregate() {
    let mut bits = vec![
        0,
        1,
        2,
        0x8000000000000000,
        0x0010000000000000,
        0x7fefffffffffffff,
    ];
    for value in [
        1e-6_f64,
        1e-5,
        1e-4,
        1e-3,
        1e15,
        1e16,
        1e20,
        1e21,
        1.2345678901234567,
        1e23,
    ] {
        bits.extend([value.to_bits() - 1, value.to_bits(), value.to_bits() + 1]);
    }
    let mut state = 0x91E10DA5C79E7B1D_u64;
    for _ in 0..20000 {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        bits.push(state);
    }
    let mut hash = Sha256::new();
    let mut count = 0;
    for bit in bits {
        let value = f64::from_bits(bit);
        if value.is_finite() {
            let raw = serde_json::to_string(&value).unwrap();
            hash.update(integral_float_json(&raw, WORK).unwrap().as_bytes());
            hash.update(b"\n");
            count += 1;
        }
    }
    let fixture: Value =
        serde_json::from_str(include_str!("fixtures/command_document.json")).unwrap();
    assert_eq!(count, fixture["aggregate"]["count"].as_u64().unwrap());
    assert_eq!(
        hash.finalize()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>(),
        fixture["aggregate"]["sha256"].as_str().unwrap()
    );
}
