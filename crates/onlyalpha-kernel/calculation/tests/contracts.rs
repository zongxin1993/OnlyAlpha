use onlyalpha_calculation::{Definition, TypeDefinition};
use serde_json::{Value, json};
fn sample() -> Value {
    serde_json::from_str::<Value>(
        include_str!("../../../../test-data/calculation/definitions-v1.jsonl")
            .lines()
            .next()
            .unwrap(),
    )
    .unwrap()["record"]
        .clone()
}
fn type_record() -> Value {
    let d = sample();
    json!({"schema_version":1,"kind":d["kind"],"type_id":d["type_id"],"semantic_version":"1","parameters":[{"name":"period","parameter_type":"INTEGER","required":false,"default":{"type":"INTEGER","value":2},"minimum":{"type":"INTEGER","value":1},"maximum":{"type":"INTEGER","value":100},"enum_values":[],"uppercase":false}],"inputs":d["inputs"],"outputs":d["outputs"],"missing_values":d["missing_values"],"timestamp":d["timestamp"],"numeric":d["numeric"],"factor_kind":null,"execution_shape":"TIME_SERIES"})
}
#[test]
fn independent_tagged_vectors_and_roundtrip() {
    for line in include_str!("../../../../test-data/calculation/definitions-v1.jsonl").lines() {
        let row: Value = serde_json::from_str(line).unwrap();
        let d = Definition::from_record(&row["record"]).unwrap();
        assert_eq!(d.fingerprint(), row["fingerprint"]);
        assert_eq!(d.to_record(), row["record"]);
        assert_eq!(Definition::from_record(&d.to_record()).unwrap(), d);
    }
}
#[test]
fn decimal_aliases_normalize_without_erasing_types() {
    let mut d = sample();
    let mut hashes = vec![];
    for raw in ["2.00", "2E0", "0.20e1", "2"] {
        d["parameters"]["parameter"] = json!({"type":"DECIMAL","value":raw});
        let v = Definition::from_record(&d).unwrap();
        assert_eq!(v.to_record()["parameters"]["parameter"]["value"], "2");
        hashes.push(v.fingerprint());
    }
    assert!(hashes.iter().all(|h| *h == hashes[0]));
    d["parameters"]["parameter"] = json!({"type":"STRING","value":"2"});
    assert_ne!(
        Definition::from_record(&d).unwrap().fingerprint(),
        hashes[0]
    );
    for zero in ["-0.00", "0e100"] {
        d["parameters"]["parameter"] = json!({"type":"DECIMAL","value":zero});
        assert_eq!(
            Definition::from_record(&d).unwrap().to_record()["parameters"]["parameter"]["value"],
            "0"
        );
    }
}
#[test]
fn strict_nested_reader_and_names() {
    let base = sample();
    for pointer in [
        "",
        "/numeric",
        "/warmup",
        "/inputs/0",
        "/outputs/0",
        "/input_bindings/close",
        "/parameters/parameter",
    ] {
        let mut d = base.clone();
        d.pointer_mut(pointer)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert("extra".into(), json!(1));
        assert!(Definition::from_record(&d).is_err(), "{pointer}");
    }
    for (pointer, value) in [
        ("/schema_version", json!(true)),
        ("/schema_version", json!(2)),
        ("/numeric/precision", json!(1.0)),
        ("/warmup/minimum_observations", json!(0)),
        ("/inputs/0/nullable", json!(0)),
        ("/inputs/0/name", json!("")),
        ("/inputs/0/dimensions", json!(["TIME", "TIME"])),
        ("/type_id", json!("bad..id")),
        ("/input_bindings/close/source", json!("")),
        ("/input_bindings/close/output_name", json!("")),
        ("/numeric/output_quantum", json!("NaN")),
        ("/factor_kind", json!("TIME_SERIES")),
        (
            "/parameters/parameter",
            json!({"type":"INTEGER","value":true}),
        ),
    ] {
        let mut d = base.clone();
        *d.pointer_mut(pointer)
            .unwrap_or_else(|| panic!("{pointer}")) = value;
        assert!(Definition::from_record(&d).is_err(), "{pointer}");
    }
    let mut d = base.clone();
    d["extensions"] = json!({"calculation_execution_shape":{"type":"INTEGER","value":1}});
    assert!(Definition::from_record(&d).is_err());
    d = base;
    d["input_bindings"]["close"] =
        json!({"node_fingerprint":"g".repeat(64),"source":null,"output_name":"value"});
    assert!(Definition::from_record(&d).is_err());
}
#[test]
fn readers_reject_missing_fields_and_wrong_scalar_tags() {
    let base = sample();
    for key in base.as_object().unwrap().keys() {
        let mut d = base.clone();
        d.as_object_mut().unwrap().remove(key);
        assert!(Definition::from_record(&d).is_err());
    }
    for bad in [
        json!({"type":"INTEGER","value":1.5}),
        json!({"type":"INTEGER","value":"1"}),
        json!({"type":"BOOLEAN","value":"false"}),
        json!({"type":"STRING","value":1}),
        json!({"type":"DECIMAL","value":"Infinity"}),
        json!({"type":"NULL","value":0}),
        json!({"type":"DECIMAL","value":"1e999999999"}),
    ] {
        let mut d = base.clone();
        d["parameters"]["parameter"] = bad;
        assert!(Definition::from_record(&d).is_err());
    }
}
#[test]
fn type_resolves_normalized_parameters_and_is_immutable() {
    let t = TypeDefinition::from_record(&type_record()).unwrap();
    let d = sample();
    for p in [json!({}), json!({"period":"2"}), json!({"period":2})] {
        let out = t.resolve(&p, &d["input_bindings"], &d["warmup"]).unwrap();
        assert_eq!(
            out.to_record()["parameters"]["period"],
            json!({"type":"INTEGER","value":2})
        );
    }
    for p in [
        json!({"period":true}),
        json!({"period":0}),
        json!({"period":101}),
        json!({"period":2.0}),
        json!({"unknown":2}),
    ] {
        assert!(t.resolve(&p, &d["input_bindings"], &d["warmup"]).is_err());
    }
    let mut copy = t.to_record();
    copy["type_id"] = json!("changed.id");
    assert_eq!(t.to_record()["type_id"], "example.mean");
}
#[test]
fn metadata_default_bounds_enums_and_required_validation() {
    let base = type_record();
    for (key, bad) in [
        ("minimum", json!({"type":"INTEGER","value":101})),
        ("default", json!({"type":"BOOLEAN","value":true})),
        ("required", json!(true)),
        ("enum_values", json!([{"type":"INTEGER","value":3}])),
        ("uppercase", json!(true)),
    ] {
        let mut t = base.clone();
        t["parameters"][0][key] = bad;
        assert!(TypeDefinition::from_record(&t).is_err(), "{key}");
    }
    let mut t = base;
    t["parameters"][0] = json!({"name":"side","parameter_type":"STRING","required":false,"default":{"type":"STRING","value":"close"},"minimum":null,"maximum":null,"enum_values":[{"type":"STRING","value":"CLOSE"}],"uppercase":true});
    let t = TypeDefinition::from_record(&t).unwrap();
    let d = sample();
    assert_eq!(
        t.resolve(&json!({}), &d["input_bindings"], &d["warmup"])
            .unwrap()
            .to_record()["parameters"]["side"]["value"],
        "CLOSE"
    );
    assert!(
        t.resolve(&json!({"side":false}), &d["input_bindings"], &d["warmup"])
            .is_err()
    );
}

#[test]
fn resource_budgets_fail_closed_without_decimal_expansion() {
    let base = sample();
    for (pointer, bad) in [
        ("/type_id", json!("a".repeat(5000))),
        (
            "/parameters/parameter",
            json!({"type":"DECIMAL","value":"1e999999999"}),
        ),
        (
            "/parameters/parameter",
            json!({"type":"INTEGER","value":serde_json::from_str::<Value>(&"1".repeat(4097)).unwrap()}),
        ),
        (
            "/inputs/0/dimensions",
            json!((0..4097).map(|i| i.to_string()).collect::<Vec<_>>()),
        ),
        ("/numeric/precision", json!(4097)),
    ] {
        let mut v = base.clone();
        *v.pointer_mut(pointer).unwrap() = bad;
        assert!(Definition::from_record(&v).is_err());
    }
}
#[test]
fn factor_and_cross_section_shape_are_explicit() {
    let mut v = sample();
    v["kind"] = json!("FACTOR");
    assert!(Definition::from_record(&v).is_err());
    v["factor_kind"] = json!("CROSS_SECTION");
    assert_eq!(
        Definition::from_record(&v)
            .unwrap()
            .execution_shape()
            .unwrap(),
        "CROSS_SECTION"
    );
    v["extensions"] =
        json!({"calculation_execution_shape":{"type":"STRING","value":"TIME_SERIES"}});
    assert!(Definition::from_record(&v).is_err());
    v["kind"] = json!("INDICATOR");
    v["factor_kind"] = Value::Null;
    v["extensions"] =
        json!({"calculation_execution_shape":{"type":"STRING","value":"CROSS_SECTION"}});
    assert_eq!(
        Definition::from_record(&v)
            .unwrap()
            .execution_shape()
            .unwrap(),
        "CROSS_SECTION"
    );
}
#[test]
fn decimal_boolean_required_and_string_parameter_contracts() {
    let d = sample();
    let base = type_record();
    for (kind, default, input, expected) in [
        (
            "DECIMAL",
            json!({"type":"DECIMAL","value":"1.00"}),
            json!("1e0"),
            json!({"type":"DECIMAL","value":"1"}),
        ),
        (
            "BOOLEAN",
            json!({"type":"BOOLEAN","value":false}),
            json!(true),
            json!({"type":"BOOLEAN","value":true}),
        ),
        (
            "STRING",
            json!({"type":"STRING","value":"原文"}),
            json!("原文"),
            json!({"type":"STRING","value":"原文"}),
        ),
    ] {
        let mut t = base.clone();
        t["parameters"][0] = json!({"name":"parameter","parameter_type":kind,"required":false,"default":default,"minimum":null,"maximum":null,"enum_values":[],"uppercase":false});
        let t = TypeDefinition::from_record(&t).unwrap();
        assert_eq!(
            t.resolve(
                &json!({"parameter":input}),
                &d["input_bindings"],
                &d["warmup"]
            )
            .unwrap()
            .to_record()["parameters"]["parameter"],
            expected
        );
    }
    let mut t = base;
    t["parameters"][0]["required"] = json!(true);
    t["parameters"][0]["default"] = Value::Null;
    let t = TypeDefinition::from_record(&t).unwrap();
    assert!(
        t.resolve(&json!({}), &d["input_bindings"], &d["warmup"])
            .is_err()
    );
    assert!(
        t.resolve(&json!({"period":2}), &d["input_bindings"], &d["warmup"])
            .is_ok()
    );
}

#[test]
fn warmup_contract_accepts_explicit_expressions_and_initialization_text() {
    let mut value = sample();
    value["warmup"]["ready_condition"] = json!("samples >= minimum_observations");
    value["warmup"]["initialization"] = json!("first complete window seeds the mean");
    assert!(Definition::from_record(&value).is_ok());
    value["warmup"]["ready_condition"] = json!("   ");
    assert!(Definition::from_record(&value).is_err());
}

#[test]
fn independent_common_parameter_vectors() {
    let d = sample();
    for line in include_str!("../../../../test-data/calculation/parameters-v1.jsonl").lines() {
        let row: Value = serde_json::from_str(line).unwrap();
        let mut t = type_record();
        t["parameters"] = json!([row["parameter"]]);
        let t = TypeDefinition::from_record(&t).unwrap();
        let result = t.resolve(&row["provided"], &d["input_bindings"], &d["warmup"]);
        if row["expected"].is_null() {
            assert!(result.is_err(), "{}", row["case"]);
        } else {
            assert_eq!(
                result.unwrap().to_record()["parameters"]["value"],
                row["expected"],
                "{}",
                row["case"]
            );
        }
    }
}
