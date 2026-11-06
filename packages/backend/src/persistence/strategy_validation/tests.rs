//! Pure value and physical-reader regressions; no fixture mints a validation grant.
use super::*;
use std::os::unix::fs::PermissionsExt;
fn case() -> (Graph, Value, Value, Vec<Value>) {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../tests/application/fixtures/strategy_calculations.json"
    ))
    .unwrap();
    let node = fixture["nodes"]
        .as_array()
        .unwrap()
        .iter()
        .find(|n| n["definition"]["type_id"] == "onlyalpha.operator.delay")
        .unwrap();
    let graph = Graph::from_record(
        &json!({"schema_version":1,"nodes":[{"alias":null,"definition":node["definition"]}]}),
        WORK,
    )
    .unwrap();
    let id = graph.ordered_nodes().next().unwrap().fingerprint();
    let axis = vec![json!(1), json!(2)];
    let values = json!({"value":[{"type":"NULL","value":null},{"type":"NULL","value":null}]});
    let bindings = json!([{"node_fingerprint":id,"research_implementation_fingerprint":"a".repeat(64),"trading_implementation_fingerprint":"b".repeat(64)}]);
    let observed = json!({"axis":axis,"research_outputs":[{"node_fingerprint":id,"implementation_fingerprint":"a".repeat(64),"values":values}],
        "streaming_outputs":[{"node_fingerprint":id,"implementation_fingerprint":"b".repeat(64),"values":values}],"target_outputs":[],
        "decisions":[{"at_ns":1,"status":"BLOCKED","decision":null},{"at_ns":2,"status":"BLOCKED","decision":null}],"restoration":null});
    (graph, bindings, observed, axis)
}
#[test]
fn graph_comparison_rejects_missing_nodes_ports_rows_targets_and_unequal_values() {
    let (graph, bindings, value, axis) = case();
    verify_case(&graph, &bindings, &Value::Null, &value, &axis).unwrap();
    for (key, bad) in [
        ("research_outputs", json!([])),
        ("streaming_outputs", json!([])),
        ("target_outputs", json!([{}])),
        ("axis", json!([2, 1])),
        ("decisions", json!([])),
    ] {
        let mut changed = value.clone();
        changed[key] = bad;
        assert!(
            verify_case(&graph, &bindings, &Value::Null, &changed, &axis).is_err(),
            "{key}"
        );
    }
    for bad in [
        json!([]),
        json!([{"type":"NULL","value":null}]),
        json!([{"type":"BOOLEAN","value":true},{"type":"BOOLEAN","value":false}]),
    ] {
        let mut changed = value.clone();
        changed["streaming_outputs"][0]["values"]["value"] = bad;
        assert!(verify_case(&graph, &bindings, &Value::Null, &changed, &axis).is_err());
    }
    let mut changed = value.clone();
    changed["streaming_outputs"][0]["implementation_fingerprint"] = json!("a".repeat(64));
    assert!(verify_case(&graph, &bindings, &Value::Null, &changed, &axis).is_err());
}
#[test]
fn validation_manifest_codec_has_the_same_sha_identity_with_a_local_work_budget() {
    let value = json!({"schema_version":1,"decimal":"1.00","ordered":[true,null,"é"]});
    assert_eq!(
        fingerprint(&value).unwrap(),
        crate::application::factor_content::hash(&value).unwrap()
    );
    assert_eq!(
        canonical(&value).unwrap(),
        onlyalpha_metadata_json::canonical_json(&value.to_string(), WORK)
            .unwrap()
            .into_bytes()
    );
    assert!(canonical(&json!({"oversized":"x".repeat(WORK)})).is_err());
}
#[test]
fn a_retained_original_witness_rejects_identical_bytes_under_a_replacement_inode() {
    let mut entropy = [0u8; 16];
    getrandom::fill(&mut entropy).unwrap();
    let path = std::env::temp_dir().canonicalize().unwrap().join(format!(
        "onlyalpha-validation-cut-{}",
        entropy
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>()
    ));
    std::fs::create_dir(&path).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
    std::fs::write(path.join("manifest.json"), b"{}").unwrap();
    std::fs::set_permissions(
        path.join("manifest.json"),
        std::fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    let directory = Directory::open(&path).unwrap();
    let (raw, file) = physical::read_file(&directory, "manifest.json").unwrap();
    let witness = physical::witness(&directory, "manifest.json", &raw, &file).unwrap();
    witness.verify().unwrap();
    std::fs::write(path.join("replacement.json"), b"{}").unwrap();
    std::fs::set_permissions(
        path.join("replacement.json"),
        std::fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    std::fs::rename(path.join("replacement.json"), path.join("manifest.json")).unwrap();
    assert!(witness.verify().is_err());
    drop(file);
    drop(witness);
    drop(directory);
    std::fs::remove_dir_all(path).unwrap();
}
