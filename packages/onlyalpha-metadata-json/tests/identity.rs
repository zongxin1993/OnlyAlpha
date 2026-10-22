//! Independent Python canonical preimages, not a Shipping endpoint.
use onlyalpha_metadata_json::{Error, canonical_json, fingerprint};
use sha2::{Digest, Sha256};
const WORK: usize = 8 * 1024 * 1024;

#[test]
fn exact_python_preimages_include_unicode_large_integers_and_reserved_object_keys() {
    let vectors: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/integration_document.json")).unwrap();
    for vector in vectors.as_array().unwrap() {
        let raw = vector["raw"].as_str().unwrap();
        assert_eq!(
            canonical_json(raw, WORK).unwrap(),
            vector["canonical"].as_str().unwrap()
        );
        assert_eq!(
            fingerprint(raw, WORK).unwrap(),
            vector["fingerprint"].as_str().unwrap()
        );
    }
    assert_eq!(canonical_json("-0", WORK).unwrap(), "0");
    assert_eq!(canonical_json("1e0", WORK).unwrap(), "\"1.0\"");
    assert_eq!(canonical_json("1.00", WORK).unwrap(), "\"1.0\"");
    assert_eq!(canonical_json("1e-9999", WORK).unwrap(), "\"0.0\"");
    assert_eq!(canonical_json("-1e-9999", WORK).unwrap(), "\"-0.0\"");
}

#[test]
fn duplicate_decoded_keys_and_malformed_or_nonfinite_numbers_fail_closed() {
    for raw in [
        r#"{"a":1,"\u0061":2}"#,
        r#"[{"a":1,"a":2}]"#,
        r#"{"$serde_json::private::Number":"1","$serde_json::private::Number":"2"}"#,
        "01",
        "1e9999",
        "-1e9999",
        "NaN",
        "null true",
        "[1,]",
        "{",
        r#""\ud800""#,
    ] {
        assert_eq!(canonical_json(raw, WORK), Err(Error::Invalid));
    }
}

#[test]
fn deep_valid_documents_use_no_application_recursion_and_limits_are_unavailable() {
    let raw = format!("{}0{}", "[".repeat(1000), "]".repeat(1000));
    assert_eq!(canonical_json(&raw, WORK).unwrap(), raw);
    assert_eq!(canonical_json(&raw, 4096), Err(Error::Unavailable));
    assert_eq!(canonical_json("true", 3), Err(Error::Unavailable));
    assert_eq!(canonical_json("{}", 0), Err(Error::Unavailable));
    assert_eq!(canonical_json("{}", 3), Err(Error::Unavailable));
    assert_eq!(canonical_json("{}", 4).unwrap(), "{}");
    assert_eq!(canonical_json(" {} ", 5), Err(Error::Unavailable));
    assert_eq!(canonical_json(" {} ", 6).unwrap(), "{}");
    assert_eq!(canonical_json("\"é\"", 7), Err(Error::Unavailable));
    assert_eq!(canonical_json("\"é\"", 8).unwrap(), "\"é\"");
    let mixed = format!("{}0{}", "{\"x\":[".repeat(500), "]}".repeat(500));
    assert_eq!(canonical_json(&mixed, WORK).unwrap(), mixed);
    let invalid = "[1e9999]";
    assert_eq!(
        canonical_json(invalid, invalid.len()),
        Err(Error::Unavailable)
    );
    assert_eq!(canonical_json(invalid, WORK), Err(Error::Invalid));
}

#[test]
fn finite_binary64_preimages_match_the_independent_python_aggregate() {
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
            hash.update(canonical_json(&raw, WORK).unwrap().as_bytes());
            hash.update(b"\n");
            count += 1;
        }
    }
    assert_eq!(count, 20026);
    assert_eq!(
        hash.finalize()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>(),
        "bd289e2d55629fe871497689f0b302cf9799ac891379a561def0169ce29aa481"
    );
}
