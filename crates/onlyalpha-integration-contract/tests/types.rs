//! Independent Python SPI declarations; this is not provider/runtime admission.
use onlyalpha_integration_contract::{Category, Descriptor, Error, IntegrationTypeId, ValueKind};
use onlyalpha_metadata_json::fingerprint;
use serde_json::{Value, json, value::RawValue};
const WORK: usize = 8 * 1024 * 1024;
fn vectors() -> Vec<Value> {
    serde_json::from_str(include_str!("fixtures/integration_types.json")).unwrap()
}
fn parse(value: &Value) -> Result<Descriptor, Error> {
    Descriptor::from_json(&serde_json::to_string(value).unwrap(), WORK)
}
fn refresh(value: &mut Value) {
    for key in ["configuration_contract", "probe_contract"] {
        if value[key].is_null() {
            continue;
        }
        let content = value[key].as_object_mut().unwrap();
        content.remove("fingerprint");
        let fp = fingerprint(&serde_json::to_string(content).unwrap(), WORK).unwrap();
        content.insert("fingerprint".into(), json!(fp));
    }
}
fn field<'a>(value: &'a mut Value, id: &str) -> &'a mut Value {
    value["configuration_contract"]["fields"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|field| field["field_id"] == id)
        .unwrap()
}
#[test]
fn declared_python_documents_and_component_identities_match_exactly() {
    for v in vectors() {
        let descriptor = parse(&v["document"]).unwrap();
        assert_eq!(descriptor.fingerprint(), v["fingerprint"].as_str().unwrap());
        assert_eq!(
            descriptor.configuration_fingerprint(),
            v["configuration_fingerprint"].as_str().unwrap()
        );
        assert_eq!(
            descriptor.probe().unwrap().fingerprint(),
            v["probe_fingerprint"].as_str().unwrap()
        );
        assert_eq!(
            descriptor.id().value(),
            v["document"]["type_id"].as_str().unwrap()
        );
        assert_eq!(
            descriptor.category().as_str(),
            v["document"]["category"].as_str().unwrap()
        );
        assert_eq!(
            serde_json::from_str::<Value>(descriptor.document().get()).unwrap(),
            v["document"]
        );
        assert_eq!(descriptor.fields().len(), 9);
        let key = descriptor
            .fields()
            .iter()
            .find(|field| field.id() == "api_key")
            .unwrap();
        assert!(key.required() && key.secret() && key.default().is_none());
        assert_eq!(descriptor.probe().unwrap().default_instrument(), "BTCUSDT");
        assert_eq!(
            descriptor.probe().unwrap().user_selectable(),
            descriptor.category() == Category::DataSource
        );
    }
}
#[test]
fn every_invalid_field_still_fails_when_its_component_hash_is_recomputed() {
    for case in 0..18 {
        let mut doc = vectors()[0]["document"].clone();
        match case {
            0 => field(&mut doc, "text")["value_kind"] = json!("NOPE"),
            1 => field(&mut doc, "text")["field_id"] = json!("api_key"),
            2 => {
                field(&mut doc, "text")
                    .as_object_mut()
                    .unwrap()
                    .remove("default");
            }
            3 => field(&mut doc, "api_key")["default"] = json!("forbidden-secret"),
            4 => field(&mut doc, "text")["default"] = json!(true),
            5 => field(&mut doc, "choice")["enum_values"] = json!(["a", "a"]),
            6 => field(&mut doc, "ratio")["minimum"] = json!(6),
            7 => field(&mut doc, "flag")["minimum"] = json!(0),
            8 => field(&mut doc, "delay")["minimum"] = Value::Null,
            9 => field(&mut doc, "count")["default"] = json!(0),
            10 => field(&mut doc, "ratio")["default"] = json!({"$serde_json::private::Number":"1"}),
            11 => field(&mut doc, "count")["default"] = json!(1.0),
            12 => field(&mut doc, "choice")["default"] = json!("c"),
            13 => field(&mut doc, "weights")["default"] = json!({}),
            14 => {
                field(&mut doc, "text")["required"] =
                    json!({"$serde_json::private::RawValue":"true"})
            }
            15 => field(&mut doc, "text")["unknown"] = json!(0),
            16 => {
                field(&mut doc, "api_key")["secret"] =
                    json!({"$serde_json::private::RawValue":"true"})
            }
            _ => field(&mut doc, "text")["display_name"] = json!("\u{a0}\u{1c}"),
        }
        refresh(&mut doc);
        assert!(parse(&doc).is_err(), "field case {case}");
    }
}
#[test]
fn strict_root_probe_capabilities_order_and_original_component_hashes_are_required() {
    for case in 0..16 {
        let mut doc = vectors()[0]["document"].clone();
        match case {
            0 => doc["schema_version"] = json!(1.0),
            1 => doc["type_id"] = json!("controlled.latest"),
            2 => doc["provider_id"] = json!("Provider"),
            3 => doc["implementation_id"] = json!("a..b"),
            4 => doc["category"] = json!("OTHER"),
            5 => doc["capabilities"] = json!(["HISTORICAL_BARS", "HISTORICAL_BARS"]),
            6 => doc["capabilities"] = json!(["lowercase"]),
            7 => doc["capabilities"] = json!(["A:B:C"]),
            8 => doc["configuration_contract"]["fingerprint"] = json!("a".repeat(64)),
            9 => doc["configuration_contract"]["fields"]
                .as_array_mut()
                .unwrap()
                .reverse(),
            10 => doc["probe_contract"]["default_probe_instrument"] = json!(" "),
            11 => doc["probe_contract"]["probe_mode"] = json!("OTHER"),
            12 => doc["probe_contract"]["probe_checks"] = json!([]),
            13 => doc["probe_contract"]["probe_checks"] = json!(["UNKNOWN"]),
            14 => doc["probe_contract"]["fingerprint"] = json!("b".repeat(64)),
            _ => doc["extra"] = json!(1),
        }
        if !matches!(case, 8 | 14) {
            refresh(&mut doc)
        }
        assert!(parse(&doc).is_err(), "root/probe case {case}");
    }
    for id in ["", "A", "a-b", "a.latest.x", "a..b"] {
        assert!(IntegrationTypeId::new(id).is_err())
    }
}
#[test]
fn value_checks_keep_primitive_kinds_exact_and_map_marker_keys_ordinary() {
    let doc = parse(&vectors()[0]["document"]).unwrap();
    for (id, raw, valid) in [
        ("count", "2", true),
        ("count", "2.0", false),
        ("count", "false", false),
        ("count", "0", false),
        ("count", "11", false),
        ("ratio", "1.5", true),
        ("ratio", "1", true),
        ("ratio", "5.0", true),
        ("ratio", "6", false),
        ("ratio", "\"1\"", false),
        ("ratio", "true", false),
        ("delay", "0", false),
        ("delay", "-1", false),
        ("delay", "1", true),
        (
            "weights",
            r#"{"x":1000000000000000000000000000000000000000}"#,
            true,
        ),
        ("weights", r#"{"$serde_json::private::Number":1}"#, true),
        ("weights", r#"{"x":1.0}"#, false),
        ("weights", r#"{"":1}"#, false),
        (
            "weights",
            r#"{"x":{"$serde_json::private::Number":"1"}}"#,
            false,
        ),
        ("choice", "\"a\"", true),
        ("choice", "\"c\"", false),
        ("flag", "true", true),
        ("flag", "1", false),
    ] {
        let field = doc.fields().iter().find(|field| field.id() == id).unwrap();
        let raw: Box<RawValue> = serde_json::from_str(raw).unwrap();
        assert_eq!(field.accepts(&raw), valid, "{id}: {}", raw.get());
    }
    assert_eq!(
        doc.fields()
            .iter()
            .find(|field| field.id() == "weights")
            .unwrap()
            .kind(),
        ValueKind::StringIntegerMap
    );
}
#[test]
fn empty_optional_contracts_and_binary64_default_bound_policy_match_the_existing_spi() {
    let mut doc = vectors()[0]["document"].clone();
    doc["probe_contract"] = Value::Null;
    doc["capabilities"] = json!([]);
    doc["configuration_contract"]["fields"] = json!([]);
    refresh(&mut doc);
    let parsed = parse(&doc).unwrap();
    assert!(parsed.probe().is_none() && parsed.fields().is_empty());
    let mut doc = vectors()[0]["document"].clone();
    field(&mut doc, "count")["default"] = json!(9007199254740993_u64);
    field(&mut doc, "count")["minimum"] = json!(9007199254740993_u64);
    field(&mut doc, "count")["maximum"] = Value::Null;
    refresh(&mut doc);
    assert!(parse(&doc).is_err());
}
#[test]
fn parsing_limits_and_duplicates_do_not_become_a_partial_declared_contract() {
    let raw = serde_json::to_string(&vectors()[0]["document"]).unwrap();
    assert!(matches!(
        Descriptor::from_json(&raw, 10),
        Err(Error::Unavailable)
    ));
    assert!(Descriptor::from_json(r#"{"schema_version":1,"schema_version":1}"#, WORK).is_err());
}

#[test]
fn numeric_defaults_and_runtime_bounds_match_independent_python_binary64_integer_comparisons() {
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/numeric_contract.json")).unwrap();
    for (index, case) in cases.iter().enumerate() {
        let parsed = Descriptor::from_json(case["document"].as_str().unwrap(), WORK);
        assert_eq!(
            parsed.is_ok(),
            case["accepted"].as_bool().unwrap(),
            "declaration {index}"
        );
        if let (Ok(descriptor), Some(input), Some(expected)) = (
            parsed,
            case["input"].as_str(),
            case["value_accepted"].as_bool(),
        ) {
            let value: Box<RawValue> = serde_json::from_str(input).unwrap();
            let field = descriptor
                .fields()
                .iter()
                .find(|field| field.id() == "count")
                .unwrap();
            assert_eq!(field.accepts(&value), expected, "value {index}: {input}");
        }
    }
}
