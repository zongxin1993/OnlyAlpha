mod support;
use onlyalpha_market_data_construction::*;
use serde_json::json;
use support::*;
#[test]
fn checkpoint_restore_is_atomic_and_configuration_bound() {
    let mut m = manager();
    m.register("graph", graph()).unwrap();
    m.process("source", &fact(1), &stamp(1)).unwrap();
    let before = m.capture_checkpoint().unwrap();
    for kind in [
        "lane_duplicate",
        "registration_duplicate",
        "count_bool",
        "extra",
        "late_state",
    ] {
        let mut row = before.clone();
        match kind {
            "lane_duplicate" => {
                let first = row["lanes"][0].clone();
                row["lanes"].as_array_mut().unwrap().push(first);
            }
            "registration_duplicate" => {
                let first = row["registrations"][0].clone();
                row["registrations"].as_array_mut().unwrap().push(first);
            }
            "count_bool" => row["creation_count"] = json!(true),
            "extra" => row["extra"] = json!(0),
            _ => {
                let last = row["lanes"].as_array_mut().unwrap().last_mut().unwrap();
                last["executor_state"]["state"] = json!({"kind":"PENDING","bars":[]});
            }
        }
        assert!(m.restore_checkpoint(&row).is_err(), "{kind}");
        assert_eq!(m.capture_checkpoint().unwrap(), before);
    }
    for field in [
        "engine_id",
        "runtime_id",
        "source_binding_identity",
        "calendar_fingerprint",
        "construction_graph_fingerprint",
    ] {
        let mut row = before.clone();
        row[field] = json!("different");
        assert!(m.restore_checkpoint(&row).is_err());
        assert_eq!(m.capture_checkpoint().unwrap(), before);
    }
    let mut empty = manager();
    assert!(empty.restore_checkpoint(&before).is_err());
    assert_eq!(empty.registration_count(), 0);
}
#[test]
fn restored_and_uninterrupted_sequences_match_and_versions_are_exact() {
    let mut original = manager();
    original.register("graph", graph()).unwrap();
    for end in [1, 2] {
        original.process("source", &fact(end), &stamp(end)).unwrap();
    }
    let mut row = original.capture_checkpoint().unwrap();
    row["creation_count"] = serde_json::from_str("18446744073709551616").unwrap();
    original.restore_checkpoint(&row).unwrap();
    let mut fresh = manager();
    fresh.register("graph", graph()).unwrap();
    fresh.restore_checkpoint(&row).unwrap();
    fresh.restore_checkpoint(&row).unwrap();
    for end in 3..=9 {
        assert_eq!(
            fresh.process("source", &fact(end), &stamp(end)).unwrap(),
            original.process("source", &fact(end), &stamp(end)).unwrap()
        );
    }
    fresh.register("new", one_graph(5)).unwrap();
    assert_eq!(fresh.creation_count().to_string(), "18446744073709551617");
}
#[test]
fn processing_failure_requires_explicit_recovery() {
    let mut m = manager();
    m.register("graph", one_graph(3)).unwrap();
    m.process("source", &fact(1), &stamp(1)).unwrap();
    let good = m.capture_checkpoint().unwrap();
    assert!(m.process("source", &fact(3), &stamp(3)).is_err());
    assert!(m.is_failed());
    assert!(matches!(
        m.process("source", &fact(2), &stamp(2)),
        Err(OnlyConstructionError::RecoveryRequired)
    ));
    assert!(m.capture_checkpoint().is_err());
    let mut bad = good.clone();
    bad["schema_version"] = json!(3);
    assert!(m.restore_checkpoint(&bad).is_err());
    assert!(m.is_failed());
    m.restore_checkpoint(&good).unwrap();
    assert!(!m.is_failed());
    m.process("source", &fact(2), &stamp(2)).unwrap();
    assert_eq!(m.process("source", &fact(3), &stamp(3)).unwrap().len(), 1);
}
#[test]
fn noncanonical_owner_spelling_is_not_an_alias() {
    let mut m = manager();
    m.register("graph", one_graph(3)).unwrap();
    let before = m.capture_checkpoint().unwrap();
    for field in ["engine_id", "runtime_id"] {
        let mut record = before.clone();
        record[field] = json!(format!(" {} ", record[field].as_str().unwrap()));
        assert!(m.restore_checkpoint(&record).is_err(), "{field}");
        assert_eq!(m.capture_checkpoint().unwrap(), before);
    }
}

#[test]
fn late_executor_restore_rejection_preserves_an_earlier_different_candidate() {
    let mut m = manager();
    m.register("three", one_graph(3)).unwrap();
    m.register("five", one_graph(5)).unwrap();
    m.process("source", &fact(1), &stamp(1)).unwrap();
    let before = m.capture_checkpoint().unwrap();
    m.process("source", &fact(2), &stamp(2)).unwrap();
    let mut later = m.capture_checkpoint().unwrap();
    assert_ne!(
        later["lanes"][0]["executor_state"],
        before["lanes"][0]["executor_state"]
    );
    m.restore_checkpoint(&before).unwrap();
    later["lanes"].as_array_mut().unwrap().last_mut().unwrap()["executor_state"]["state"] =
        json!({"kind":"PENDING","bars":[]});
    assert!(m.restore_checkpoint(&later).is_err());
    assert_eq!(m.capture_checkpoint().unwrap(), before);
    for field in ["calendar_fingerprint", "construction_graph_fingerprint"] {
        let mut bad = before.clone();
        bad[field] = json!("d".repeat(64));
        assert!(m.restore_checkpoint(&bad).is_err());
        assert_eq!(m.capture_checkpoint().unwrap(), before);
    }
    for field in ["source_lane_id", "recipe_fingerprint", "lane_id"] {
        let mut bad = before.clone();
        bad["lanes"][0][field] = json!("d".repeat(64));
        assert!(m.restore_checkpoint(&bad).is_err());
        assert_eq!(m.capture_checkpoint().unwrap(), before);
    }
    for field in ["topological_level", "reference_count"] {
        let mut bad = before.clone();
        bad["lanes"][0][field] = json!(0);
        assert!(m.restore_checkpoint(&bad).is_err());
        assert_eq!(m.capture_checkpoint().unwrap(), before);
    }
    let mut duplicate = before.clone();
    let p = duplicate["provider_reference_counts"][0].clone();
    duplicate["provider_reference_counts"]
        .as_array_mut()
        .unwrap()
        .push(p);
    assert!(m.restore_checkpoint(&duplicate).is_err());
    assert_eq!(m.capture_checkpoint().unwrap(), before);
    let mut reordered = before.clone();
    for field in ["lanes", "registrations", "provider_reference_counts"] {
        reordered[field].as_array_mut().unwrap().reverse();
    }
    m.restore_checkpoint(&reordered).unwrap();
    assert_eq!(m.capture_checkpoint().unwrap(), before);
}
