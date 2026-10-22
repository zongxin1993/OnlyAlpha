use onlyalpha_calculation::product::{Definition, Error, Graph};
use serde_json::{Value, json};
const WORK: usize = 1024 * 1024;
fn rows() -> Vec<Value> {
    include_str!("../../../../test-data/calculation/product-readers-v1.jsonl")
        .lines()
        .map(|s| serde_json::from_str(s).unwrap())
        .collect()
}
fn sample() -> Value {
    rows()[0]["record"].clone()
}
#[test]
fn actual_product_serializer_vectors_preserve_original_identity_and_public_values() {
    for row in rows() {
        if row["case"].as_str().unwrap().starts_with("graph-") {
            let graph = Graph::from_record(&row["input"], WORK).unwrap();
            assert_eq!(graph.to_record(), row["record"], "{}", row["case"]);
            assert_eq!(graph.fingerprint(), row["fingerprint"]);
            assert_eq!(Graph::from_record(&graph.to_record(), WORK).unwrap(), graph);
        } else {
            let d = Definition::from_record(&row["input"], WORK).unwrap();
            assert_eq!(d.to_record(), row["record"], "{}", row["case"]);
            assert_eq!(d.semantic_payload(), row["semantic"]);
            assert_eq!(d.fingerprint(), row["fingerprint"]);
            assert_eq!(Definition::from_record(&d.to_record(), WORK).unwrap(), d);
        }
    }
    let fingerprints: Vec<_> = rows()
        .into_iter()
        .take(11)
        .map(|r| r["fingerprint"].as_str().unwrap().to_owned())
        .collect();
    assert_ne!(fingerprints[2], fingerprints[3]); // Decimal scale is identity.
    assert_ne!(fingerprints[4], fingerprints[5]); // Signed zero is identity.
    // Product2 uses the existing untagged semantic payload. Preserve it exactly;
    // retained record tags are not permission to invent a new Strategy identity.
    assert_eq!(fingerprints[2], fingerprints[8]);
}
#[test]
fn exact_public_reader_rejects_wrong_types_missing_fields_and_exclusive_binding_errors() {
    let base = sample();
    for key in base.as_object().unwrap().keys() {
        let mut d = base.clone();
        d.as_object_mut().unwrap().remove(key);
        assert_eq!(
            Definition::from_record(&d, WORK),
            Err(Error::Invalid),
            "{key}"
        );
    }
    for (pointer, value) in [
        ("/schema_version", json!(3)),
        ("/schema_version", json!(true)),
        ("/type_id", json!("No.dot")),
        ("/semantic_version", json!("has space")),
        ("/warmup/minimum_observations", json!(0)),
        ("/numeric/precision", json!(1.0)),
        ("/numeric/output_quantum", json!("NaN")),
        ("/factor_kind", json!("TIME_SERIES")),
        (
            "/parameters/parameter",
            json!({"type":"INTEGER","value":true}),
        ),
        ("/parameters/parameter", json!({"type":"DECIMAL","value":1})),
        ("/parameters/parameter", json!({"type":"NULL","value":0})),
        ("/inputs/0/nullable", json!(0)),
        ("/inputs/0/dimensions", json!([1])),
        ("/input_bindings/close/source", Value::Null),
        (
            "/input_bindings/close/node_fingerprint",
            json!("a".repeat(64)),
        ),
    ] {
        let mut d = base.clone();
        *d.pointer_mut(pointer).unwrap() = value;
        assert_eq!(
            Definition::from_record(&d, WORK),
            Err(Error::Invalid),
            "{pointer}"
        );
    }
    for pointer in [
        "",
        "/warmup",
        "/numeric",
        "/inputs/0",
        "/outputs/0",
        "/parameters/parameter",
        "/input_bindings/close",
    ] {
        let mut d = base.clone();
        d.pointer_mut(pointer)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert("extra".into(), json!(1));
        assert_eq!(
            Definition::from_record(&d, WORK),
            Err(Error::Invalid),
            "{pointer}"
        );
    }
}
#[test]
fn graph_checks_actual_edges_ports_unique_aliases_and_target_boundaries() {
    let row = rows()
        .into_iter()
        .find(|r| r["case"] == "graph-basic")
        .unwrap();
    let base = row["record"].clone();
    for (pointer, value) in [
        (
            "/nodes/1/definition/input_bindings/close/node_fingerprint",
            json!("f".repeat(64)),
        ),
        (
            "/nodes/1/definition/input_bindings/close/output_name",
            json!("missing"),
        ),
        ("/nodes/1/definition/inputs/0/data_type", json!("INTEGER")),
        ("/nodes/1/definition/inputs/0/nullable", json!(true)),
        ("/nodes/1/definition/inputs/0/dimensions", json!(["ASSET"])),
        ("/nodes/1/definition/inputs/0/semantic_type", json!("OTHER")),
        ("/nodes/1/definition/inputs/0/unit", json!("EUR")),
        ("/nodes/1/alias", json!("root")),
        ("/nodes/1/definition/kind", json!("TARGET")),
    ] {
        // nullable=true accepts a non-null producer and is deliberately not an error.
        let mut changed = base.clone();
        *changed.pointer_mut(pointer).unwrap() = value;
        if pointer.ends_with("nullable") {
            assert!(Graph::from_record(&changed, WORK).is_ok());
        } else {
            assert_eq!(
                Graph::from_record(&changed, WORK),
                Err(Error::Invalid),
                "{pointer}"
            );
        }
    }
    let mut changed = base.clone();
    changed["nodes"][0]["definition"]["outputs"][0]["nullable"] = json!(true);
    // Updating the real producer fingerprint keeps the edge linked, isolating nullability.
    let parent = Definition::from_record(&changed["nodes"][0]["definition"], WORK).unwrap();
    changed["nodes"][1]["definition"]["input_bindings"]["close"]["node_fingerprint"] =
        json!(parent.fingerprint());
    assert_eq!(Graph::from_record(&changed, WORK), Err(Error::Invalid));
    let mut wildcard = base.clone();
    wildcard["nodes"][1]["definition"]["inputs"][0]["semantic_type"] = json!("PREDICATE_OPERAND");
    wildcard["nodes"][1]["definition"]["inputs"][0]["unit"] = json!("anything");
    assert!(Graph::from_record(&wildcard, WORK).is_ok());
    let mut duplicated = base.clone();
    duplicated["nodes"][1] = duplicated["nodes"][0].clone();
    assert_eq!(Graph::from_record(&duplicated, WORK), Err(Error::Invalid));
}
#[test]
fn work_exhaustion_is_unavailable_and_never_a_partial_or_corrupt_definition() {
    let d = sample();
    for work in [0, 1, 50] {
        assert_eq!(Definition::from_record(&d, work), Err(Error::Unavailable));
        assert_eq!(
            Graph::from_record(
                &json!({"schema_version":1,"nodes":[{"definition":d,"alias":null}]}),
                work
            ),
            Err(Error::Unavailable)
        );
    }
    let mut d = sample();
    d["parameters"]["parameter"] = json!({"type":"DECIMAL","value":"1e999999999"});
    assert_eq!(Definition::from_record(&d, WORK), Err(Error::Unavailable));
}

#[test]
fn expanded_decimals_share_the_whole_input_budget_and_invalid_nested_scalars_are_rejected() {
    let mut d = sample();
    d["parameters"] = json!({});
    for i in 0..20 {
        d["parameters"][format!("p{i}")] = json!({"type":"DECIMAL","value":"1e1000"});
    }
    assert_eq!(Definition::from_record(&d, 5000), Err(Error::Unavailable));
    let mut nested = json!(true);
    for _ in 0..64 {
        nested = json!({"nested":nested});
    }
    d = sample();
    d["extensions"] = json!({"invalid":nested});
    assert_eq!(Definition::from_record(&d, WORK), Err(Error::Invalid));
    let empty = json!({"schema_version":1,"nodes":[]});
    assert_eq!(Graph::from_record(&empty, WORK).unwrap().to_record(), empty);
}

#[test]
fn wide_graph_port_index_checks_first_middle_and_last_real_names() {
    let row = rows()
        .into_iter()
        .find(|r| r["case"] == "graph-wide-ports")
        .unwrap();
    for i in [0, 75, 149] {
        let mut v = row["record"].clone();
        v["nodes"][1]["definition"]["input_bindings"][format!("input{i}")]["output_name"] =
            json!("absent");
        assert_eq!(Graph::from_record(&v, WORK), Err(Error::Invalid));
    }
    for spelling in [" 1.00 ", "1_0.00", "١.٠٠"] {
        let mut v = sample();
        v["parameters"]["parameter"] = json!({"type":"DECIMAL","value":spelling});
        assert_eq!(Definition::from_record(&v, WORK), Err(Error::Invalid));
    }
}

#[test]
fn positive_exponent_zero_keeps_original_product_fixed_decimal_identity() {
    for (input, expected) in [
        ("0E+2", "0"),
        ("-0E+2", "-0"),
        ("0E-2", "0.00"),
        ("-0E-2", "-0.00"),
    ] {
        let mut v = sample();
        v["parameters"]["parameter"] = json!({"type":"DECIMAL","value":input});
        let d = Definition::from_record(&v, WORK).unwrap();
        assert_eq!(
            d.to_record()["parameters"]["parameter"]["value"],
            json!(expected),
            "{input}"
        );
        assert_eq!(
            d.semantic_payload()["parameters"]["parameter"],
            json!(expected),
            "{input}"
        );
    }
}
