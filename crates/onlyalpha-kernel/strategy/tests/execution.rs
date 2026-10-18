const CORPUS: &str = include_str!("../../../../test-data/strategy/decisions-v2.jsonl");

mod support;
use onlyalpha_domain::base::OnlyDomainModel;
use onlyalpha_strategy::*;
use serde_json::{Value, json};
use support::*;
#[test]
fn revision_records_are_exact_and_explicitly_schema_two() {
    let r = revision();
    let record = r.to_record();
    assert_eq!(record["schema_version"], 2);
    assert_eq!(Revision::from_record(&record).unwrap(), r);
    for mode in [
        "schema",
        "hash",
        "graph",
        "extra",
        "signal",
        "implementation",
    ] {
        let mut v = record.clone();
        match mode {
            "schema" => v["schema_version"] = json!(1),
            "hash" => v["strategy_fingerprint"] = json!("a".repeat(64)),
            "graph" => v["decision_graph_fingerprint"] = json!("a".repeat(64)),
            "extra" => v["extra"] = Value::Null,
            "signal" => v["signals"][0]["node_fingerprint"] = json!("a".repeat(64)),
            _ => v["implementations"][0]["state_capability"] = json!("INFER"),
        };
        assert!(Revision::from_record(&v).is_err(), "{mode}");
    }
}
#[test]
fn independent_vector_warmup_and_ready_decisions() {
    let mut e = executor();
    for line in CORPUS.lines().skip(1) {
        let row: Value = serde_json::from_str(line).unwrap();
        let result = process(&mut e, row["minute"].as_u64().unwrap() as u32)
            .unwrap()
            .to_record();
        assert_eq!(result["status"], row["status"]);
        if row["status"] == "READY" {
            assert_eq!(result["decision"]["entry"], row["entry"]);
            assert_eq!(result["decision"]["exit"], row["exit"]);
            assert_eq!(result["decision"]["eligibility"], true);
        } else {
            assert!(result["decision"].is_null());
        }
    }
}
#[test]
fn identical_duplicate_never_updates_nodes_again() {
    let mut e = executor();
    for i in 1..=3 {
        process(&mut e, i).unwrap();
    }
    let calls = e.port().calls.lock().unwrap().len();
    let before = e.capture_checkpoint().unwrap();
    let old = process(&mut e, 3).unwrap();
    assert!(old.decision().is_some());
    assert_eq!(e.port().calls.lock().unwrap().len(), calls);
    assert_eq!(before, e.capture_checkpoint().unwrap());
}
#[test]
fn corrected_old_or_wrong_source_input_is_refused_without_mutation() {
    let mut e = executor();
    process(&mut e, 1).unwrap();
    let cp = e.capture_checkpoint().unwrap();
    let mut r = bar(1).to_record();
    r["close"]["value"] = json!("1.01");
    r["high"]["value"] = json!("1.01");
    let corrected = onlyalpha_domain::market::OnlyBar::from_record(&r).unwrap();
    assert!(
        e.process(&corrected, &time(&corrected), &"1".repeat(64))
            .is_err()
    );
    assert_eq!(cp, e.capture_checkpoint().unwrap());
    assert!(!e.is_failed());
}
#[test]
fn later_node_failure_withdraws_the_owner_without_retrying_prefix() {
    for mode in ["known", "unknown", "malformed", "panic"] {
        let mut e = executor();
        for i in 1..=2 {
            process(&mut e, i).unwrap();
        }
        let cp = e.capture_checkpoint().unwrap();
        let last = e
            .program()
            .revision()
            .graph()
            .ordered_nodes()
            .last()
            .unwrap()
            .fingerprint();
        let b = bar(1);
        let scope = e.program().instance_scope(b.instrument_id(), &last);
        *e.port().fault.lock().unwrap() = Fault {
            scope,
            mode: mode.into(),
        };
        let n = e.port().calls.lock().unwrap().len();
        assert!(process(&mut e, 3).is_err());
        assert!(e.port().calls.lock().unwrap().len() > n + 1);
        assert!(e.is_failed());
        let n = e.port().calls.lock().unwrap().len();
        assert!(process(&mut e, 3).is_err());
        assert_eq!(e.port().calls.lock().unwrap().len(), n);
        assert!(e.capture_checkpoint().is_err());
        restore(&mut e, &cp).unwrap();
        process(&mut e, 3).unwrap();
    }
}
#[test]
fn fresh_restore_continuation_matches_uninterrupted_bytes() {
    let mut a = executor();
    let mut b = executor();
    for i in 1..=3 {
        process(&mut a, i).unwrap();
    }
    let cp = a.capture_checkpoint().unwrap();
    restore(&mut b, &cp).unwrap();
    for i in 4..=6 {
        assert_eq!(
            process(&mut a, i).unwrap().to_record(),
            process(&mut b, i).unwrap().to_record()
        );
    }
    assert_eq!(
        a.capture_checkpoint().unwrap(),
        b.capture_checkpoint().unwrap()
    );
}
#[test]
fn corrupt_or_spliced_checkpoint_never_replaces_a_healthy_receiver() {
    let mut e = executor();
    for i in 1..=3 {
        process(&mut e, i).unwrap();
    }
    let old = e.capture_checkpoint().unwrap();
    for i in 4..=6 {
        process(&mut e, i).unwrap();
    }
    let cp = e.capture_checkpoint().unwrap();
    for mode in ["states", "port", "accepted", "program", "extra"] {
        let mut v = cp.clone();
        match mode {
            "states" => v["states"] = old["states"].clone(),
            "port" => v["port"] = old["port"].clone(),
            "accepted" => v["accepted"] = old["accepted"].clone(),
            "program" => v["program"]["source"] = json!("d".repeat(64)),
            _ => v["extra"] = Value::Null,
        };
        assert!(restore(&mut e, &v).is_err(), "{mode}");
        assert_eq!(e.capture_checkpoint().unwrap(), cp);
    }
    assert!(
        e.restore_checkpoint(cp.to_string().as_bytes(), &"a".repeat(64))
            .is_err()
    );
}
#[test]
fn initial_checkpoint_can_restore_a_used_or_failed_owner() {
    let mut e = executor();
    let cp = e.capture_checkpoint().unwrap();
    process(&mut e, 1).unwrap();
    restore(&mut e, &cp).unwrap();
    assert_eq!(cp, e.capture_checkpoint().unwrap());
}

#[test]
fn independent_instrument_warmup_is_not_shared_and_recovers_exactly() {
    let original = revision();
    let signals = original.to_record()["signals"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| SignalBinding::from_record(v).unwrap())
        .collect::<Vec<_>>()
        .try_into()
        .unwrap();
    let r = Revision::new(
        vec!["A.X".parse().unwrap(), "B.X".parse().unwrap()],
        original.semantic().clone(),
        original.recipe().clone(),
        original.graph().clone(),
        original.descriptors().values().cloned().collect(),
        signals,
    )
    .unwrap();
    let base = program();
    let p = Program::new(
        r,
        base.scope().clone(),
        base.generation(),
        base.source(),
        base.artifact(),
    )
    .unwrap();
    let mut e = Executor::new(p.clone(), Port::new(p.clone())).unwrap();
    for i in 1..=3 {
        let b = bar(i);
        let a = e.process(&b, &time(&b), &format!("{i:064x}")).unwrap();
        assert_eq!(a.blocked(), i < 3);
        if i < 3 {
            let mut row = b.to_record();
            row["bar_type"]["instrument_id"]["symbol"]["value"] = json!("B");
            let other = onlyalpha_domain::market::OnlyBar::from_record(&row).unwrap();
            assert!(
                e.process(&other, &time(&other), &format!("{i:064x}"))
                    .unwrap()
                    .blocked()
            );
        }
    }
    let cp = e.capture_checkpoint().unwrap();
    let mut fresh = Executor::new(p.clone(), Port::new(p)).unwrap();
    restore(&mut fresh, &cp).unwrap();
    let mut row = bar(3).to_record();
    row["bar_type"]["instrument_id"]["symbol"]["value"] = json!("B");
    let b = onlyalpha_domain::market::OnlyBar::from_record(&row).unwrap();
    assert_eq!(
        e.process(&b, &time(&b), &"c".repeat(64)).unwrap(),
        fresh.process(&b, &time(&b), &"c".repeat(64)).unwrap()
    );
    assert_eq!(
        e.capture_checkpoint().unwrap(),
        fresh.capture_checkpoint().unwrap()
    );
}

#[test]
fn inadmissible_input_and_global_time_regression_do_not_mutate_nodes() {
    let mut e = executor();
    process(&mut e, 2).unwrap();
    let cp = e.capture_checkpoint().unwrap();
    for mode in ["foreign", "semantic", "open", "revision", "old"] {
        let mut row = bar(3).to_record();
        match mode {
            "foreign" => row["bar_type"]["instrument_id"]["symbol"]["value"] = json!("B"),
            "semantic" => {
                row["bar_type"]["semantic"]["formation"]["window_minutes"] = json!(2);
                row["bar_type"]["semantic"]["formation"]["stride_minutes"] = json!(2);
            }
            "open" => row["is_closed"] = json!(false),
            "revision" => row["revision"] = json!(1),
            _ => row = bar(1).to_record(),
        }
        let b = onlyalpha_domain::market::OnlyBar::from_record(&row).unwrap();
        assert!(e.process(&b, &time(&b), &"c".repeat(64)).is_err(), "{mode}");
        assert_eq!(cp, e.capture_checkpoint().unwrap());
    }
    let b = bar(3);
    assert!(e.process(&b, &time(&bar(1)), &"c".repeat(64)).is_err());
    assert_eq!(cp, e.capture_checkpoint().unwrap());
}

#[test]
fn old_native_state_and_request_splices_fail_even_with_rederived_manifest() {
    let mut e = executor();
    for i in 1..=3 {
        process(&mut e, i).unwrap();
    }
    let old = e.capture_checkpoint().unwrap();
    process(&mut e, 4).unwrap();
    let current = e.capture_checkpoint().unwrap();
    for field in ["port", "states", "requests", "accepted"] {
        let mut v = current.clone();
        v[field] = old[field].clone();
        let hashes = v
            .as_object()
            .unwrap()
            .iter()
            .filter(|(k, _)| k.as_str() != "component_bindings")
            .map(|(k, v)| (k.clone(), json!(record_fingerprint(v))))
            .collect();
        v["component_bindings"] = Value::Object(hashes);
        assert!(restore(&mut e, &v).is_err(), "{field}");
        assert_eq!(current, e.capture_checkpoint().unwrap());
    }
}

#[test]
fn decision_itself_binds_the_input_prefix_and_actual_receipt_trace() {
    let mut e = executor();
    for i in 1..=2 {
        process(&mut e, i).unwrap();
    }
    let r = process(&mut e, 3).unwrap().to_record();
    assert_eq!(r["decision"]["input_identity"], r["input_identity"]);
    assert_eq!(
        r["decision"]["trace_fingerprint"],
        record_fingerprint(&r["trace"])
    );
}

#[test]
fn ready_nullable_terminal_values_follow_false_decision_policy() {
    let mut e = executor();
    e.port().fault.lock().unwrap().mode = "null-terminal".into();
    for i in 1..=2 {
        assert!(process(&mut e, i).unwrap().blocked());
    }
    let value = process(&mut e, 3).unwrap().to_record();
    assert_eq!(value["status"], "READY");
    for role in ["eligibility", "entry", "exit"] {
        assert_eq!(value["decision"][role], false);
    }
    e.capture_checkpoint().unwrap();
}
