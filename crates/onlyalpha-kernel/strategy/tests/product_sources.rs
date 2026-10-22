use onlyalpha_calculation::{Definition, product::Definition as ProductDefinition};
use onlyalpha_strategy::{
    NodeDescriptor, Revision, SourceError, SourceRevision, record_fingerprint,
};
use serde_json::{Value, json};
use std::collections::BTreeMap;
const WORK: usize = 8 * 1024 * 1024;
fn rows() -> Vec<Value> {
    include_str!("../../../../test-data/strategy/product-sources-v1.jsonl")
        .lines()
        .map(|s| serde_json::from_str(s).unwrap())
        .collect()
}
fn rehash(v: &mut Value) {
    let mut identity = v.clone();
    identity.as_object_mut().unwrap().remove("decision_graph");
    identity
        .as_object_mut()
        .unwrap()
        .remove("strategy_fingerprint");
    identity["domain"] = json!("onlyalpha.strategy.revision");
    v["strategy_fingerprint"] = json!(record_fingerprint(&identity));
}
#[test]
fn real_product_sources_keep_original_identity_without_any_execution_descriptors() {
    for row in rows() {
        let raw = row["record"].to_string();
        let parsed = SourceRevision::from_json(&raw, WORK).unwrap();
        assert_eq!(parsed.to_record(), row["record"], "{}", row["case"]);
        assert_eq!(parsed.fingerprint(), row["fingerprint"].as_str().unwrap());
        assert_eq!(
            SourceRevision::from_json(&parsed.to_record().to_string(), WORK).unwrap(),
            parsed
        );
        let mut unordered = row["record"].clone();
        unordered["decision_graph"]["nodes"]
            .as_array_mut()
            .unwrap()
            .reverse();
        assert_eq!(
            SourceRevision::from_json(&unordered.to_string(), WORK).unwrap(),
            parsed
        );
    }
}
#[test]
fn recomputed_outer_hash_cannot_replace_source_structure_or_relationships() {
    let original = rows()[0]["record"].clone();
    for mode in [
        "role",
        "missing-output",
        "binding-omitted",
        "binding-duplicate",
        "graph-hash",
        "recipe-target",
        "extra",
        "version",
    ] {
        let mut v = original.clone();
        match mode {
            "role" => v["signal_semantics"]["eligibility"] = v["signal_semantics"]["entry"].clone(),
            "missing-output" => {
                v["signal_semantics"]["eligibility"]["output_name"] = json!("absent")
            }
            "binding-omitted" => {
                v["implementation_bindings"].as_array_mut().unwrap().pop();
            }
            "binding-duplicate" => {
                let b = v["implementation_bindings"][0].clone();
                v["implementation_bindings"].as_array_mut().unwrap().push(b);
            }
            "graph-hash" => v["decision_graph_fingerprint"] = json!("a".repeat(64)),
            "recipe-target" => {
                v["market_input_contract"]["bar_semantic"]["formation"]["window_minutes"] = json!(2)
            }
            "extra" => v["unknown"] = json!(true),
            _ => v["schema_version"] = json!(2),
        }
        rehash(&mut v);
        assert_eq!(
            SourceRevision::from_json(&v.to_string(), WORK),
            Err(SourceError::Invalid),
            "{mode}"
        );
    }
}
#[test]
fn bounded_input_and_parser_failure_never_return_a_source_proof() {
    let raw = rows()[0]["record"].to_string();
    for work in [0, 1, 100] {
        assert_eq!(
            SourceRevision::from_json(&raw, work),
            Err(SourceError::Unavailable)
        );
    }
    assert_eq!(
        SourceRevision::from_json("{", WORK),
        Err(SourceError::Invalid)
    );
    let deeply_nested = format!("{}null{}", "[".repeat(200), "]".repeat(200));
    assert_eq!(
        SourceRevision::from_json(&deeply_nested, WORK),
        Err(SourceError::Invalid)
    );
}
fn materialize(source: &Value) -> (Vec<NodeDescriptor>, BTreeMap<String, String>) {
    let mut mapping = BTreeMap::new();
    let mut descriptors = vec![];
    for row in source["decision_graph"]["nodes"].as_array().unwrap() {
        let original = ProductDefinition::from_record(&row["definition"], WORK)
            .unwrap()
            .fingerprint();
        let mut d = row["definition"].clone();
        for r in d["input_bindings"].as_object_mut().unwrap().values_mut() {
            if let Some(parent) = r["node_fingerprint"].as_str() {
                r["node_fingerprint"] = json!(mapping.get(parent).unwrap());
            }
        }
        let native = ProductDefinition::from_record(&d, WORK)
            .unwrap()
            .fingerprint();
        d["schema_version"] = json!(3);
        let definition = Definition::from_record(&d).unwrap();
        mapping.insert(original, definition.fingerprint());
        descriptors.push(NodeDescriptor {
            definition,
            native_definition: native,
            implementation: "b".repeat(64),
            state_capability: "STATELESS".into(),
            checkpoint_schema: None,
        });
    }
    (descriptors, mapping)
}
#[test]
fn materialization_still_proves_real_descriptors_mapping_and_original_source_pins() {
    for row in rows().into_iter().take(3) {
        let source = &row["record"];
        let (descriptors, mapping) = materialize(source);
        let admitted =
            Revision::from_product(source.clone(), descriptors.clone(), mapping.clone()).unwrap();
        assert_eq!(admitted.fingerprint(), row["fingerprint"].as_str().unwrap());
        assert_eq!(
            Revision::from_record(&admitted.to_record()).unwrap(),
            admitted
        );
        let mut bad = descriptors.clone();
        bad[0].native_definition = "c".repeat(64);
        assert!(Revision::from_product(source.clone(), bad, mapping.clone()).is_err());
        let mut bad = descriptors;
        bad[0].implementation = "c".repeat(64);
        assert!(Revision::from_product(source.clone(), bad, mapping.clone()).is_err());
        let mut bad = mapping;
        bad.pop_first();
        assert!(
            Revision::from_product(
                source.clone(),
                admitted.descriptors().values().cloned().collect(),
                bad
            )
            .is_err()
        );
    }
}

#[test]
fn source_history_is_not_restricted_by_current_executable_component_limits() {
    for row in rows().into_iter().filter(|r| {
        matches!(
            r["case"].as_str().unwrap(),
            "seventeen-instruments" | "sixty-five-nodes" | "adjusted-source"
        )
    }) {
        let source = &row["record"];
        assert!(SourceRevision::from_json(&source.to_string(), WORK).is_ok());
        let (descriptors, mapping) = materialize(source);
        assert!(
            Revision::from_product(source.clone(), descriptors, mapping).is_err(),
            "{}",
            row["case"]
        );
    }
}
#[test]
fn existing_source_wrapper_order_is_preserved_through_materialization_and_restore() {
    let source = rows()[0]["record"].clone();
    let (descriptors, mapping) = materialize(&source);
    let mut unordered = source.clone();
    unordered["decision_graph"]["nodes"]
        .as_array_mut()
        .unwrap()
        .reverse();
    let admitted = Revision::from_product(unordered.clone(), descriptors, mapping).unwrap();
    assert_eq!(admitted.to_record()["product"]["source"], unordered);
    assert_eq!(
        Revision::from_record(&admitted.to_record()).unwrap(),
        admitted
    );
    assert_eq!(
        admitted.fingerprint(),
        source["strategy_fingerprint"].as_str().unwrap()
    );
}
