use crate::application::private_assets::authoring::{API_FINGERPRINT, Draft};
use serde_json::{Value, json};
fn draft() -> Value {
    json!({"schema_version":1,"factor_id":"private.factor.momentum","base_revision_fingerprint":null,"semantic_version":"1","source_text":"def calculate(api, inputs, parameters):\n    return {'value': inputs['close']}\n","factor_api_version":1,"factor_api_contract_fingerprint":"3265e2397f581705b67c1372483b6629671b68af71f69575c7bd602816d63be9","input_contract":{"close":{"type":"DECIMAL"}},"parameter_contract":{},"output_contract":{"value":{"type":"DECIMAL"}},"description":"Momentum","economic_rationale":"Trend","category":"price","tags":["price","trend"]})
}
#[test]
fn authoring_preserves_canonical_revision_and_source_identity() {
    let original = draft();
    let parsed = Draft::new(original.clone()).unwrap();
    let revision = parsed.revision().unwrap();
    assert_eq!(parsed.record(), &original);
    assert_eq!(revision["factor_api_contract_fingerprint"], API_FINGERPRINT);
    assert_eq!(
        revision["revision_fingerprint"],
        "0e9cbd14005ce4f295480363a2305e55d28e9582d8428cc26c486b5d2d128b2b"
    );
    assert_eq!(
        revision["source_sha256"],
        "e07fa56f3c846738816c4d67e0b6430286b36c14bb6f006fb3311ed318488b71"
    );
    assert_ne!(
        parsed.fingerprint().unwrap(),
        revision["revision_fingerprint"]
    );
}
#[test]
fn invalid_identity_and_nested_values_never_become_an_authoring_draft() {
    for (field, value) in [
        ("factor_id", json!("private.strategy.momentum")),
        ("semantic_version", json!("01")),
        ("factor_api_version", json!(true)),
        ("factor_api_contract_fingerprint", json!("f".repeat(64))),
        (
            "input_contract",
            json!({"x":{"type":"DECIMAL","default":1.5}}),
        ),
        ("tags", json!(["a", "a"])),
        ("base_revision_fingerprint", json!("absent")),
    ] {
        let mut mutated = draft();
        mutated[field] = value;
        assert!(Draft::new(mutated).is_err(), "{field}");
    }
}
#[test]
fn formal_authoring_routes_are_available_without_enabling_research_execution() {
    use crate::transport::routes::{Operation, operation};
    for (method, path) in [
        (http::Method::GET, "/api/v2/private-assets/factors"),
        (
            http::Method::PUT,
            "/api/v2/private-assets/factors/private.factor.momentum/display",
        ),
        (
            http::Method::GET,
            "/api/v2/private-assets/factors/private.factor.momentum",
        ),
        (
            http::Method::PUT,
            "/api/v2/private-assets/factors/private.factor.momentum/draft",
        ),
        (
            http::Method::POST,
            "/api/v2/private-assets/factors/private.factor.momentum/revisions",
        ),
        (
            http::Method::GET,
            "/api/v2/private-assets/factors/private.factor.momentum/commands/cmd",
        ),
    ] {
        assert_eq!(
            operation(&method, path),
            Some(Operation::Implemented),
            "{path}"
        );
    }
    assert_eq!(
        operation(&http::Method::POST, "/api/v2/research/runs"),
        Some(Operation::Deferred)
    );
}

#[test]
fn nul_content_and_keys_are_rejected_before_storage() {
    for (field, value) in [
        ("source_text", json!("code\u{0000}")),
        ("description", json!("name\u{0000}")),
        ("input_contract", json!({"x": "bad\u{0000}"})),
        ("parameter_contract", json!({"bad\u{0000}": 1})),
    ] {
        let mut value_under_test = draft();
        value_under_test[field] = value;
        assert!(Draft::new(value_under_test).is_err());
    }
}
