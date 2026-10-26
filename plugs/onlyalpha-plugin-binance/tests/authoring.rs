use onlyalpha_integration_contract::{Error, authoring::Registration};
use serde_json::value::RawValue;
const WORK: usize = 8 * 1024 * 1024;
fn check(registration: &Registration, input: &str) -> Result<(), Error> {
    registration.validate_public_configuration(&RawValue::from_string(input.into()).unwrap(), WORK)
}
use onlyalpha_plugin_binance::{spot_authoring, usdm_authoring};
#[test]
fn compiled_declarations_bind_current_native_chart_contract() {
    assert_eq!(
        spot_authoring(WORK).unwrap().descriptor().fingerprint(),
        "203dd5f3add8460b57c6c8411b12e98c0c134b0ebb8f4a66d11e6bb48765f83f"
    );
    assert_eq!(
        usdm_authoring(WORK).unwrap().descriptor().fingerprint(),
        "c6d0f750e146d921a04b5bb4a7573652e1c7498b5495b3e0adae52f1aa78fc7b"
    );
    assert!(matches!(spot_authoring(0), Err(Error::Unavailable)));
    assert!(matches!(usdm_authoring(0), Err(Error::Unavailable)));
}
#[test]
fn spot_validates_endpoint_pairs_and_reconnect_relationships() {
    let source = spot_authoring(WORK).unwrap();
    for input in [
        "{}",
        r#"{"environment":"US"}"#,
        r#"{"environment":"US","endpoint_profile":"DEFAULT"}"#,
        r#"{"environment":"SPOT_TESTNET","endpoint_profile":"GCP"}"#,
        r#"{"environment":"GLOBAL","endpoint_profile":"API4"}"#,
        r#"{"reconnect_initial_seconds":30,"reconnect_max_seconds":30.0}"#,
        r#"{"max_response_bytes":999999999999999999999999999999999999999999999999}"#,
    ] {
        assert_eq!(check(&source, input), Ok(()), "{input}");
    }
    for input in [
        r#"{"environment":"GLOBAL","endpoint_profile":"DEFAULT"}"#,
        r#"{"environment":"US","endpoint_profile":"PUBLIC_MARKET_DATA"}"#,
        r#"{"environment":"SPOT_TESTNET","endpoint_profile":"STANDARD"}"#,
        r#"{"environment":"LIVE"}"#,
        r#"{"cache_policy":"cache_only"}"#,
        r#"{"reconnect_initial_seconds":31,"reconnect_max_seconds":30}"#,
        r#"{"reconnect_initial_seconds":301}"#,
        r#"{"timeout_seconds":0}"#,
        r#"{"rest_page_size":1001}"#,
        r#"{"max_response_bytes":true}"#,
        r#"{"timeout_seconds":"1.5"}"#,
        r#"{"environment":{"$serde_json::private::RawValue":"GLOBAL"}}"#,
    ] {
        assert_eq!(check(&source, input), Err(Error::Configuration), "{input}");
    }
}
#[test]
fn usdm_requires_a_complete_https_base_and_preserves_prefix_paths() {
    let source = usdm_authoring(WORK).unwrap();
    for url in [
        "https://fapi.binance.com",
        "https://example.com:443/prefix/",
        "https://[::1]:443/a%20b",
        "https://example.com/",
    ] {
        let input = serde_json::json!({"rest_base_url":url}).to_string();
        assert_eq!(check(&source, &input), Ok(()), "{url}");
    }
    for url in [
        "https://",
        "http://example.com",
        "https:///abc",
        "https://user:password@example.com",
        "https://example.com?q=a",
        "https://example.com#fragment",
        "https://example.com:bad",
        "https://example.com:65536",
        "https://example.com:0",
        "https://ex%61mple.com",
        "https://example.com:",
        "https://example.com/ space",
    ] {
        let input = serde_json::json!({"rest_base_url":url}).to_string();
        assert_eq!(check(&source, &input), Err(Error::Configuration), "{url}");
    }
    let input =
        serde_json::json!({"rest_base_url":format!("https://example.com/{}","a".repeat(65535))})
            .to_string();
    assert_eq!(check(&source, &input), Err(Error::Unavailable));
    for input in [
        r#"{"rest_page_size":1501}"#,
        r#"{"timeout_seconds":31}"#,
        r#"{"token":"secret"}"#,
    ] {
        assert_eq!(check(&source, input), Err(Error::Configuration));
    }
    assert_eq!(check(&source, "{}"), Ok(()));
}

#[test]
fn public_authoring_rejects_nonobjects_unknown_secrets_duplicates_and_exhaustion() {
    for source in [spot_authoring(WORK).unwrap(), usdm_authoring(WORK).unwrap()] {
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
fn spot_partial_and_default_filled_publication_are_distinct_candidates() {
    let source = spot_authoring(WORK).unwrap();
    for environment in ["US", "SPOT_TESTNET"] {
        assert_eq!(
            check(
                &source,
                &serde_json::json!({"environment":environment}).to_string()
            ),
            Ok(())
        );
        assert_eq!(check(&source,&serde_json::json!({"environment":environment,"endpoint_profile":"PUBLIC_MARKET_DATA"}).to_string()),Err(Error::Configuration));
    }
    assert_eq!(
        check(&source, r#"{"reconnect_max_seconds":0.1}"#),
        Err(Error::Configuration)
    );
}
#[test]
fn usdm_ipv6_and_empty_delimiters_keep_the_same_validation_boundary() {
    let source = usdm_authoring(WORK).unwrap();
    assert_eq!(
        check(&source, r#"{"rest_base_url":"https://[::1]/prefix"}"#),
        Ok(())
    );
    for url in [
        "https://[::1]:/",
        "https://[::1]:bad/",
        "https://[::1]:65536/",
        "https://[::1]:0/",
        "https://example.com?",
        "https://example.com#",
        "https://[::1]?",
        "https://[::1]#",
    ] {
        assert_eq!(
            check(
                &source,
                &serde_json::json!({"rest_base_url":url}).to_string()
            ),
            Err(Error::Configuration),
            "{url}"
        );
    }
}
