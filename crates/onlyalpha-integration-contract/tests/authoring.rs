//! A compiled authoring registration is not Source/runtime readiness.
use onlyalpha_integration_contract::authoring::{PluginProjection, Registration};
use onlyalpha_integration_contract::{Category, Descriptor, Error};
use serde_json::{Value, value::RawValue};
const WORK: usize = 8 * 1024 * 1024;
fn descriptor() -> Descriptor {
    let vectors: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/integration_types.json")).unwrap();
    Descriptor::from_json(&vectors[0]["document"].to_string(), WORK).unwrap()
}
fn projection(
    category: Category,
    id: &str,
    version: &str,
    api: &str,
    capabilities: &[&str],
) -> PluginProjection {
    PluginProjection::new(
        category,
        id,
        version,
        api,
        capabilities
            .iter()
            .map(|value| String::from(*value))
            .collect(),
    )
    .unwrap()
}
fn declared() -> PluginProjection {
    projection(
        Category::DataSource,
        "controlled.component",
        "1.0.0",
        "1.0",
        &["HISTORICAL_BARS", "PAGINATION:CURSOR"],
    )
}
fn allow(_: &RawValue, _: usize) -> Result<(), Error> {
    Ok(())
}
fn reject(_: &RawValue, _: usize) -> Result<(), Error> {
    Err(Error::Configuration)
}
fn unavailable(_: &RawValue, _: usize) -> Result<(), Error> {
    Err(Error::Unavailable)
}
fn unreachable_validator(_: &RawValue, _: usize) -> Result<(), Error> {
    panic!("invalid input reached provider code")
}
fn raw(value: &str) -> Box<RawValue> {
    RawValue::from_string(value.into()).unwrap()
}
#[test]
fn every_plugin_projection_dimension_must_match_the_actual_descriptor() {
    for value in [
        projection(
            Category::Broker,
            "controlled.component",
            "1.0.0",
            "1.0",
            &["HISTORICAL_BARS", "PAGINATION:CURSOR"],
        ),
        projection(
            Category::DataSource,
            "other.component",
            "1.0.0",
            "1.0",
            &["HISTORICAL_BARS", "PAGINATION:CURSOR"],
        ),
        projection(
            Category::DataSource,
            "controlled.component",
            "2.0.0",
            "1.0",
            &["HISTORICAL_BARS", "PAGINATION:CURSOR"],
        ),
        projection(
            Category::DataSource,
            "controlled.component",
            "1.0.0",
            "1.1",
            &["HISTORICAL_BARS", "PAGINATION:CURSOR"],
        ),
        projection(
            Category::DataSource,
            "controlled.component",
            "1.0.0",
            "1.0",
            &["HISTORICAL_BARS"],
        ),
    ] {
        assert!(matches!(
            Registration::new(value, descriptor(), allow),
            Err(Error::Type)
        ));
    }
    let original = descriptor();
    let fingerprint = original.fingerprint().to_owned();
    let registered = Registration::new(declared(), original, allow).unwrap();
    assert_eq!(registered.descriptor().fingerprint(), fingerprint);
    assert_eq!(
        registered.descriptor().id().value(),
        "controlled.data_source"
    );
}
#[test]
fn malformed_projection_and_unsupported_plugin_api_cannot_be_registered() {
    for (category, id, version, api, capabilities) in [
        (Category::AgentProvider, "invalid id", "1", "1.1", vec![]),
        (Category::DataSource, "bad..id", "1", "1.1", vec![]),
        (Category::DataSource, "controlled", "\u{1c}", "1.1", vec![]),
        (Category::DataSource, "controlled", "1", "1.2", vec![]),
        (Category::DataSource, "controlled", "1", "2.0", vec![]),
        (
            Category::DataSource,
            "controlled",
            "1",
            "1.1",
            vec!["lowercase".to_owned()],
        ),
        (
            Category::DataSource,
            "controlled",
            "1",
            "1.1",
            vec!["A".to_owned(), "A".to_owned()],
        ),
        (
            Category::DataSource,
            "controlled",
            "1",
            "1.1",
            vec!["Z".to_owned(), "A".to_owned()],
        ),
    ] {
        assert!(matches!(
            PluginProjection::new(category, id, version, api, capabilities),
            Err(Error::Type)
        ));
    }
}
#[test]
fn malformed_public_fields_never_reach_an_executable_provider_validator() {
    let registered = Registration::new(declared(), descriptor(), unreachable_validator).unwrap();
    for text in [
        "null",
        "[]",
        r#"{"unknown":1}"#,
        r#"{"api_key":"secret"}"#,
        r#"{"count":"5"}"#,
        r#"{"count":true}"#,
        r#"{"count":0}"#,
        r#"{"ratio":"1.5"}"#,
        r#"{"count":1,"count":2}"#,
        r#"{"weights":{"a":1,"a":2}}"#,
        r#"{"count":{"$serde_json::private::RawValue":"5"}}"#,
        r#"{"weights":{"$serde_json::private::RawValue":"5"}}"#,
    ] {
        assert_eq!(
            registered.validate_public_configuration(&raw(text), WORK),
            Err(Error::Configuration),
            "{text}"
        );
    }
    assert_eq!(
        registered.validate_public_configuration(&raw("{}"), 0),
        Err(Error::Unavailable)
    );
}
#[test]
fn partial_authoring_dispatches_real_validation_and_preserves_original_bytes() {
    fn original(raw: &RawValue, _: usize) -> Result<(), Error> {
        assert_eq!(
            raw.get(),
            r#"{"count":7,"ratio":1.50,"weights":{"$serde_json::private::RawValue":2}}"#
        );
        Ok(())
    }
    let registered = Registration::new(declared(), descriptor(), original).unwrap();
    let input = raw(r#"{"count":7,"ratio":1.50,"weights":{"$serde_json::private::RawValue":2}}"#);
    assert_eq!(
        registered.validate_public_configuration(&input, WORK),
        Ok(())
    );
    // Required fields/secret completeness belong to publication, not partial editing.
    let registered = Registration::new(declared(), descriptor(), allow).unwrap();
    assert_eq!(
        registered.validate_public_configuration(&raw("{}"), WORK),
        Ok(())
    );
    let registered = Registration::new(declared(), descriptor(), reject).unwrap();
    assert_eq!(
        registered.validate_public_configuration(&raw("{}"), WORK),
        Err(Error::Configuration)
    );
    let registered = Registration::new(declared(), descriptor(), unavailable).unwrap();
    assert_eq!(
        registered.validate_public_configuration(&raw("{}"), WORK),
        Err(Error::Unavailable)
    );
}
