use onlyalpha_integration_contract::{Error, authoring::Registration};
use serde_json::value::RawValue;
const WORK: usize = 8 * 1024 * 1024;
fn check(registration: &Registration, input: &str) -> Result<(), Error> {
    registration.validate_public_configuration(&RawValue::from_string(input.into()).unwrap(), WORK)
}
use onlyalpha_plugin_tushare::daily_authoring;
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
