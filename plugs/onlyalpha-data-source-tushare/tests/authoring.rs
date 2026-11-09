use onlyalpha_integration_contract::{Error, authoring::Registration};
use serde_json::value::RawValue;
const WORK: usize = 8 * 1024 * 1024;
fn check(registration: &Registration, input: &str) -> Result<(), Error> {
    registration.validate_public_configuration(&RawValue::from_string(input.into()).unwrap(), WORK)
}
use onlyalpha_data_source_tushare::daily_authoring;
#[test]
fn compiled_declaration_preserves_independent_python_identity_without_credentials() {
    let source = daily_authoring(WORK).unwrap();
    assert_eq!(
        source.descriptor().fingerprint(),
        "f04dba8e6cf4b50a58258ffedba9b61ab26d69c8ff8668ca7ab00ba0425ce782"
    );
    assert!(matches!(daily_authoring(0), Err(Error::Unavailable)));
    for input in [
        "{}",
        r#"{"frequency":"1d","adjustment":"qfq","cache_policy":"cache_only","strict_validation":false}"#,
        r#"{"adjustment":"hfq","strict_validation":true}"#,
    ] {
        assert_eq!(check(&source, input), Ok(()), "{input}");
    }
    for input in [
        r#"{"frequency":"1m"}"#,
        r#"{"frequency":"1D"}"#,
        r#"{"adjustment":"raw"}"#,
        r#"{"cache_policy":"unknown"}"#,
        r#"{"strict_validation":"false"}"#,
        r#"{"token":"secret"}"#,
        r#"{"token_env":"ANY"}"#,
        r#"{"mode":"historical"}"#,
        r#"{"strict_validation":true,"strict_validation":false}"#,
    ] {
        assert_eq!(check(&source, input), Err(Error::Configuration), "{input}");
    }
}

#[test]
fn public_authoring_rejects_nonobjects_unknown_secrets_duplicates_and_exhaustion() {
    for source in [daily_authoring(WORK).unwrap()] {
        for input in [
            "[]",
            "null",
            r#"{"unknown":1}"#,
            r#"{"timeout_seconds":null}"#,
            r#"{"strict_validation":null}"#,
            r#"{"timeout_seconds":1,"timeout_seconds":2}"#,
            r#"{"token":"private"}"#,
            r#"{"unknown":1,"unknown":2}"#,
        ] {
            assert_eq!(check(&source, input), Err(Error::Configuration), "{input}");
        }
        assert_eq!(
            source.validate_public_configuration(&RawValue::from_string("{}".into()).unwrap(), 0),
            Err(Error::Unavailable)
        );
    }
}

#[test]
fn native_single_venue_identity_is_distinct_from_original_authoring() {
    use onlyalpha_data_source_tushare::source::{history_identity, native_authoring};
    let source = native_authoring(WORK).unwrap();
    let original = daily_authoring(WORK).unwrap();
    assert_ne!(
        source.descriptor().fingerprint(),
        original.descriptor().fingerprint()
    );
    for venue in ["XSHG", "XSHE"] {
        let config = RawValue::from_string(serde_json::json!({"venue":venue}).to_string()).unwrap();
        assert_eq!(source.validate_public_configuration(&config, WORK), Ok(()));
        let identity = history_identity(source.descriptor(), &config).unwrap();
        assert_eq!(identity.venue, venue);
        assert_eq!(
            identity.source_id,
            format!("tushare.daily.{}", venue.to_ascii_lowercase())
        );
        assert!(history_identity(original.descriptor(), &config).is_err());
    }
    for config in [
        r#"{"venue":"XBSE"}"#,
        r#"{"venue":null}"#,
        r#"{"token":"secret"}"#,
        r#"{"venue":"XSHE","venue":"XSHG"}"#,
    ] {
        assert_eq!(check(&source, config), Err(Error::Configuration));
    }
}

#[test]
fn native_probe_defaults_are_frozen_per_venue_and_explicit_mismatches_fail() {
    use onlyalpha_data_source_tushare::source::native_authoring;
    use onlyalpha_integration_contract::Descriptor;
    use serde_json::{Value, json};
    let native = native_authoring(WORK).unwrap();
    let probe = native.descriptor().probe().unwrap();
    for (venue, expected, explicit) in [
        ("XSHG", "600000.XSHG", "600001.XSHG"),
        ("XSHE", "000001.XSHE", "000002.XSHE"),
    ] {
        assert_eq!(probe.instrument_for(Some(venue), None).unwrap(), expected);
        assert_eq!(
            probe.instrument_for(Some(venue), Some(explicit)).unwrap(),
            explicit
        );
    }
    assert!(
        probe
            .instrument_for(Some("XSHE"), Some("600000.XSHG"))
            .is_err()
    );
    assert_eq!(
        check(&native, r#"{"strict_validation":false}"#),
        Err(Error::Configuration)
    );
    let doc: Value = serde_json::from_str(native.descriptor().document().get()).unwrap();
    for (field, vals, default, version) in [
        (
            "token",
            json!({"XSHE":"000001.XSHE","XSHG":"600000.XSHG"}),
            "600000.XSHG",
            2,
        ),
        ("missing", json!({}), "600000.XSHG", 2),
        ("venue", json!({"XSHE":"000001.XSHE"}), "600000.XSHG", 2),
        (
            "venue",
            json!({"XSHE":"bad","XSHG":"600000.XSHG"}),
            "600000.XSHG",
            2,
        ),
        (
            "venue",
            json!({"XSHE":"000001.XSHE","XSHG":"600000.XSHG","XBSE":"870001.XBSE"}),
            "600000.XSHG",
            2,
        ),
        (
            "venue",
            json!({"XSHE":"000001.XSHE","XSHG":"600000.XSHG"}),
            "600001.XSHG",
            2,
        ),
        (
            "venue",
            json!({"XSHE":"000001.XSHE","XSHG":"600000.XSHG"}),
            "600000.XSHG",
            1,
        ),
    ] {
        let mut invalid = doc.clone();
        let p = &mut invalid["probe_contract"];
        p["configured_instruments"] = json!({"field_id":field,"instruments":vals});
        p["default_probe_instrument"] = default.into();
        p["probe_version"] = version.into();
        p.as_object_mut().unwrap().remove("fingerprint");
        p["fingerprint"] = onlyalpha_metadata_json::fingerprint(&p.to_string(), WORK)
            .unwrap()
            .into();
        assert!(Descriptor::from_json(&invalid.to_string(), WORK).is_err());
    }
    let mut old = doc;
    old["public_api_version"] = "1.1".into();
    assert!(Descriptor::from_json(&old.to_string(), WORK).is_err());
}
