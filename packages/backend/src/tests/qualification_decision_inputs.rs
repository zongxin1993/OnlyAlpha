//! Extraction alone never verifies a PG proof or creates an owning capability.
use super::*;
use serde_json::json;

fn decision() -> Value {
    json!({"schema_version":1,"decision_graph_fingerprint":"a".repeat(64),
        "decision_graph":{"nodes":["retained-original"]},
        "signal_semantics":{"entry":"retained-original"}})
}
fn proof(decision: &Value) -> Value {
    json!({"contract":"ONLYALPHA_CALCULATION_BUILD_PROOF_V1","context":{"decision":decision}})
}

#[test]
fn research_uses_original_certified_decision_without_changing_evidence() {
    let original = decision();
    let prepared = json!({"build_certification":proof(&original)});
    let before = prepared.clone();
    let selected = research_decision(&prepared).unwrap();
    assert!(std::ptr::eq(
        selected,
        &prepared["build_certification"]["context"]["decision"]
    ));
    assert_eq!(selected, &original);
    assert_eq!(prepared, before);
}

#[test]
fn research_never_uses_a_top_level_decision_as_missing_proof_fallback() {
    for prepared in [
        json!({}),
        json!({"decision":decision()}),
        json!({"build_certification":null}),
    ] {
        assert!(research_decision(&prepared).is_err());
    }
}

#[test]
fn research_rejects_missing_null_or_malformed_proof_decision() {
    for value in [
        Value::Null,
        json!([]),
        json!({}),
        json!({"decision_graph":null,"signal_semantics":{}}),
    ] {
        assert!(research_decision(&json!({"build_certification":proof(&value)})).is_err());
    }
}

#[test]
fn manual_uses_current_original_top_level_decision() {
    let original = decision();
    let prepared = json!({"decision":original,"build_certification":proof(&original)});
    let before = prepared.clone();
    let selected = manual_decision(&prepared).unwrap();
    assert!(std::ptr::eq(selected, &prepared["decision"]));
    assert_eq!(prepared, before);
    // An original legacy manual record has no new build certification.
    assert_eq!(
        manual_decision(&json!({"decision":original})).unwrap(),
        &original
    );
}

#[test]
fn manual_never_falls_back_to_nested_or_historical_decision() {
    let original = decision();
    for prepared in [
        json!({"build_certification":proof(&original)}),
        json!({"decision":null,"build_certification":proof(&original)}),
    ] {
        assert!(manual_decision(&prepared).is_err());
    }
}

#[test]
fn manual_rejects_conflicting_graph_signal_or_missing_existing_proof_decision() {
    let original = decision();
    for member in ["decision_graph", "signal_semantics"] {
        let mut changed = original.clone();
        changed[member] = json!({"wrong":"occurrence"});
        assert!(
            manual_decision(&json!({"decision":original,"build_certification":proof(&changed)}))
                .is_err()
        );
    }
    assert!(manual_decision(&json!({"decision":original,"build_certification":null})).is_err());
}
