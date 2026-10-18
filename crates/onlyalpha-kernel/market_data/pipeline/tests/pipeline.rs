mod support;
use onlyalpha_domain::base::OnlyDomainModel;
use onlyalpha_market_data_pipeline::*;
use serde_json::{Value, json};
use support::*;
#[test]
fn multiple_cycles_gate_actual_consumer_and_resume_exactly() {
    let mut p = pipeline();
    let mut restored = pipeline();
    for i in 1..=2 {
        let o = p.process(&input(i)).unwrap();
        assert_eq!(o.receipts[0]["outcome"], "BLOCKED");
    }
    let cp = p.capture_checkpoint().unwrap();
    restore(&mut restored, &cp).unwrap();
    for i in 3..=6 {
        assert_eq!(
            p.process(&input(i)).unwrap().to_record(),
            restored.process(&input(i)).unwrap().to_record()
        );
    }
    assert_eq!(
        p.capture_checkpoint().unwrap(),
        restored.capture_checkpoint().unwrap()
    );
}
#[test]
fn exact_actual_delivery_corpus() {
    let slots = vec![slot("a", 1, true), slot("b", 3, true)];
    let consumer = Recorder::default();
    let calls = consumer.calls.clone();
    let mut p =
        MarketDataPipeline::new(program(slots.clone()), Port::new(slots), consumer).unwrap();
    for line in
        include_str!("../../../../../test-data/market-data-pipeline/operations-v1.jsonl").lines()
    {
        let row: Value = serde_json::from_str(line).unwrap();
        let out = p
            .process(&input(row["minute"].as_u64().unwrap() as u32))
            .unwrap();
        assert_eq!(
            out.receipts
                .iter()
                .map(|r| json!([r["cluster"], r["outcome"]]))
                .collect::<Vec<_>>(),
            row["receipts"].as_array().unwrap().clone()
        );
    }
    assert_eq!(
        calls
            .lock()
            .unwrap()
            .iter()
            .map(|c| c["cluster"].clone())
            .collect::<Vec<_>>(),
        vec![json!("a"), json!("a"), json!("a"), json!("a"), json!("b")]
    );
}
#[test]
fn preflight_refusal_is_atomic_and_does_not_poison() {
    let mut p = pipeline();
    p.process(&input(1)).unwrap();
    let saved = p.capture_checkpoint().unwrap();
    for mode in 0..6 {
        let mut bad = input(2);
        match mode {
            0 => bad.sequence = 1,
            1 => bad.source = "b".repeat(64),
            2 => bad.logical_init = stamp(0),
            3 => bad.quality = vec!["z".into(), "a".into()],
            4 => bad.quality = vec!["a".into(), "a".into()],
            _ => bad = input(1),
        };
        assert!(p.process(&bad).is_err());
        assert!(!p.is_failed());
        assert_eq!(p.capture_checkpoint().unwrap(), saved);
    }
    p.process(&input(2)).unwrap();
}
#[test]
fn unknown_or_malformed_calculation_poison_shared_owner_until_restore() {
    for mode in ["unknown", "malformed"] {
        let mut p = pipeline();
        let saved = p.capture_checkpoint().unwrap();
        *p.calculations().fault.lock().unwrap() = Fault {
            scope: slot("a", 1, true).binding.scope().into(),
            mode: mode.into(),
        };
        assert!(p.process(&input(1)).is_err());
        assert!(p.is_failed());
        assert!(p.process(&input(2)).is_err());
        assert!(p.capture_checkpoint().is_err());
        restore(&mut p, &saved).unwrap();
        p.process(&input(1)).unwrap();
    }
}
#[test]
fn known_failure_blocks_only_required_cluster_and_is_not_retried() {
    let mut p = pipeline();
    *p.calculations().fault.lock().unwrap() = Fault {
        scope: slot("a", 1, true).binding.scope().into(),
        mode: "known".into(),
    };
    for i in 1..=6 {
        let o = p.process(&input(i)).unwrap();
        assert_eq!(o.receipts[0]["outcome"], "BLOCKED");
        if i == 6 {
            assert_eq!(o.receipts[1]["outcome"], "ACCEPTED");
        }
    }
    let cp = p.capture_checkpoint().unwrap();
    let mut fresh = pipeline();
    restore(&mut fresh, &cp).unwrap();
    assert_eq!(cp, fresh.capture_checkpoint().unwrap());
}
#[test]
fn consumer_failure_or_panic_quarantines_only_its_cluster() {
    for mode in ["a", "panic:a"] {
        let slots = vec![slot("a", 1, true), slot("b", 3, true)];
        let consumer = Recorder::default();
        *consumer.fail.lock().unwrap() = mode.into();
        let calls = consumer.calls.clone();
        let mut p =
            MarketDataPipeline::new(program(slots.clone()), Port::new(slots), consumer).unwrap();
        for i in 1..=6 {
            let o = p.process(&input(i)).unwrap();
            if i > 3 {
                assert_eq!(o.receipts[0]["outcome"], "QUARANTINED");
            }
            if i == 6 {
                assert_eq!(o.receipts[1]["outcome"], "ACCEPTED");
            }
        }
        assert_eq!(calls.lock().unwrap().len(), 2);
        let cp = p.capture_checkpoint().unwrap();
        let mut fresh = pipeline();
        restore(&mut fresh, &cp).unwrap();
        assert_eq!(cp, fresh.capture_checkpoint().unwrap());
    }
}
#[test]
fn restoring_initial_checkpoint_to_used_owner_is_valid() {
    let mut p = pipeline();
    let initial = p.capture_checkpoint().unwrap();
    p.process(&input(1)).unwrap();
    restore(&mut p, &initial).unwrap();
    assert_eq!(initial, p.capture_checkpoint().unwrap());
}
#[test]
fn delivery_watermark_cannot_disappear_behind_materialized_primary() {
    let mut p = pipeline();
    p.process(&input(1)).unwrap();
    let before = p.capture_checkpoint().unwrap();
    let mut corrupt = before.clone();
    corrupt["delivery"]["registrations"][0]["last_planned_event_ns"] = Value::Null;
    assert!(restore(&mut p, &corrupt).is_err());
    assert_eq!(before, p.capture_checkpoint().unwrap());
}
#[test]
fn duplicate_calculation_registration_is_refused() {
    let slots = vec![slot("a", 1, true)];
    let mut port = Port::new(slots.clone());
    port.slots.push(slots[0].clone());
    assert!(MarketDataPipeline::new(program(slots), port, Recorder::default()).is_err());
}
#[test]
fn input_identity_commits_the_ordered_prefix() {
    let mut first = pipeline();
    let mut second = pipeline();
    let mut changed = input(1);
    changed.quality = vec!["CONTROLLED".into()];
    first.process(&input(1)).unwrap();
    second.process(&changed).unwrap();
    assert_ne!(
        first.process(&input(2)).unwrap().input_identity,
        second.process(&input(2)).unwrap().input_identity
    );
}
#[test]
fn quarantined_unobserved_optional_slot_can_remain_unobserved() {
    let slots = vec![slot("a", 3, false)];
    let consumer = Recorder::default();
    *consumer.fail.lock().unwrap() = "a".into();
    let mut p = MarketDataPipeline::new(program(slots.clone()), Port::new(slots.clone()), consumer)
        .unwrap();
    for i in 1..=3 {
        p.process(&input(i)).unwrap();
    }
    let cp = p.capture_checkpoint().unwrap();
    let mut fresh = MarketDataPipeline::new(
        program(slots.clone()),
        Port::new(slots),
        Recorder::default(),
    )
    .unwrap();
    restore(&mut fresh, &cp).unwrap();
    assert_eq!(cp, fresh.capture_checkpoint().unwrap());
}
#[test]
fn composite_corruption_rejected_without_replacing_current_owner() {
    let mut p = pipeline();
    for i in 1..=4 {
        p.process(&input(i)).unwrap();
    }
    let cp = p.capture_checkpoint().unwrap();
    for mode in 0..10 {
        let mut v = cp.clone();
        match mode {
            0 => v["processed"] = json!(5),
            1 => v["frontiers"][0]["sequence"] = json!(0),
            2 => v["program"]["consumer"] = json!("a".repeat(64)),
            3 => v["expected"][0][1]["samples"] = json!(99),
            4 => v["last_inputs"][0][1]["close"]["value"] = json!("10.06"),
            5 => v["state"]["unknown"] = Value::Null,
            6 => v["calculations"][0][1]["cursor"]["binding"]["scope"] = json!("alien"),
            7 => v["managers"] = json!([]),
            8 => v["quarantined"] = json!([{}]),
            _ => v["extra"] = Value::Null,
        };
        assert!(restore(&mut p, &v).is_err(), "mutation {mode}");
        assert_eq!(cp, p.capture_checkpoint().unwrap(), "mutation {mode}");
    }
    assert!(
        p.restore_checkpoint(cp.to_string().as_bytes(), &"a".repeat(64))
            .is_err()
    );
}

#[test]
fn healthy_calculations_cannot_restore_an_older_input_prefix_than_market_state() {
    let mut p = pipeline();
    for i in 1..=3 {
        p.process(&input(i)).unwrap();
    }
    let old = p.capture_checkpoint().unwrap();
    for i in 4..=6 {
        p.process(&input(i)).unwrap();
    }
    let current = p.capture_checkpoint().unwrap();
    let mut spliced = current.clone();
    for key in ["calculations", "expected", "last_inputs"] {
        spliced[key] = old[key].clone();
        // Rebind the structural manifest to exercise semantic cursor-vs-State checks too.
        spliced["component_bindings"]["components"][key] = json!(digest(&spliced[key]));
    }
    assert!(restore(&mut p, &spliced).is_err());
    assert_eq!(p.capture_checkpoint().unwrap(), current);
}

#[test]
fn construction_checkpoint_cannot_be_spliced_from_an_older_source_prefix() {
    let mut p = pipeline();
    for i in 1..=3 {
        p.process(&input(i)).unwrap();
    }
    let old = p.capture_checkpoint().unwrap();
    p.process(&input(4)).unwrap();
    let current = p.capture_checkpoint().unwrap();
    for include_binding in [false, true] {
        let mut spliced = current.clone();
        spliced["managers"] = old["managers"].clone();
        if include_binding {
            spliced["component_bindings"] = old["component_bindings"].clone();
        }
        assert!(restore(&mut p, &spliced).is_err());
        assert_eq!(p.capture_checkpoint().unwrap(), current);
    }
}

#[test]
fn a_later_scope_unknown_cannot_hide_an_earlier_committed_update() {
    let mut p = pipeline();
    p.process(&input(1)).unwrap();
    p.process(&input(2)).unwrap();
    let cp = p.capture_checkpoint().unwrap();
    let a = slot("a", 1, true).binding.scope().to_owned();
    let b = slot("b", 3, true).binding.scope().to_owned();
    *p.calculations().fault.lock().unwrap() = Fault {
        scope: b.clone(),
        mode: "unknown".into(),
    };
    assert!(p.process(&input(3)).is_err());
    assert_eq!(
        p.calculations().states[&a].snapshot().to_record()["cursor"]["samples"],
        3
    );
    assert_eq!(
        p.calculations().states[&b].snapshot().to_record()["cursor"]["samples"],
        0
    );
    assert!(p.is_failed());
    assert!(p.capture_checkpoint().is_err());
    restore(&mut p, &cp).unwrap();
    assert_eq!(
        p.calculations().states[&a].snapshot().to_record()["cursor"]["samples"],
        2
    );
    p.process(&input(3)).unwrap();
}

#[test]
fn construction_gap_requires_explicit_complete_restore_before_continuation() {
    let mut p = pipeline();
    p.process(&input(1)).unwrap();
    let cp = p.capture_checkpoint().unwrap();
    assert!(p.process(&input(3)).is_err());
    assert!(p.is_failed());
    restore(&mut p, &cp).unwrap();
    p.process(&input(2)).unwrap();
    p.process(&input(3)).unwrap();
}

#[test]
fn derived_state_delivery_and_calculation_cannot_form_a_separate_older_cut() {
    let mut p = pipeline();
    for i in 1..=3 {
        p.process(&input(i)).unwrap();
    }
    let old = p.capture_checkpoint().unwrap();
    for i in 4..=6 {
        p.process(&input(i)).unwrap();
    }
    let current = p.capture_checkpoint().unwrap();
    let mut spliced = current.clone();
    let kind = slot("b", 3, true).bar_type.to_record();
    let old_series = old["state"]["series"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["bar_type"] == kind)
        .unwrap()
        .clone();
    for row in spliced["state"]["series"].as_array_mut().unwrap() {
        if row["bar_type"] == kind {
            *row = old_series.clone();
        }
    }
    let old_delivery = old["delivery"]["registrations"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["cluster_id"] == "b")
        .unwrap()
        .clone();
    for row in spliced["delivery"]["registrations"].as_array_mut().unwrap() {
        if row["cluster_id"] == "b" {
            *row = old_delivery.clone();
        }
    }
    let scope = slot("b", 3, true).binding.scope().to_owned();
    for key in ["calculations", "expected", "last_inputs"] {
        let prior = old[key]
            .as_array()
            .unwrap()
            .iter()
            .find(|r| r[0] == scope)
            .unwrap()
            .clone();
        for row in spliced[key].as_array_mut().unwrap() {
            if row[0] == scope {
                *row = prior.clone();
            }
        }
    }
    assert!(restore(&mut p, &spliced).is_err());
    assert_eq!(p.capture_checkpoint().unwrap(), current);
}
