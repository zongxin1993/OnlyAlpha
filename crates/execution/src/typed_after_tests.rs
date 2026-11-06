//! Actual projection/restore work and immutable canonical identity. No grants.
const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[path = "../tests/support/mod.rs"]
mod support;
use crate::components::PROJECTION_RESTORES;
use crate::{Components, Prepared, Record, coordinate, recover};
use serde_json::{Value, json};
use support::{Harness, MemoryStore, config, fill, open, stage, terminal};
fn reset() {
    PROJECTION_RESTORES.with(|counts| counts.set([0; 6]));
}
fn restores() -> [u64; 6] {
    PROJECTION_RESTORES.with(std::cell::Cell::get)
}
fn apply(history: &mut Harness, input: &Value) {
    let p = history.prepare(input).unwrap();
    coordinate(&mut history.store, &mut history.components, &p).unwrap();
}
fn decoded(store: &MemoryStore) -> MemoryStore {
    let mut copy = MemoryStore::default();
    copy.rows = store
        .rows
        .iter()
        .map(|row| Record::decode(&row.record()).unwrap())
        .collect();
    copy
}
#[test]
fn original_planned_projection_uses_its_actual_typed_after_but_clone_and_wire_keep_only_canonical_data()
 {
    let mut hot = Harness::new(config()).unwrap();
    let before = hot.checkpoint().unwrap();
    let original = hot.prepare(&open(1, "BUY")).unwrap();
    let bytes = original.encode().unwrap();
    let copy = original.clone();
    let wire = Prepared::decode(&bytes).unwrap();
    assert_eq!(copy, original);
    assert_eq!(wire, original);
    assert_eq!(copy.encode().unwrap(), bytes);
    assert_eq!(wire.encode().unwrap(), bytes);
    assert_eq!(
        hot.checkpoint().unwrap(),
        before,
        "planning cannot mutate any official owner"
    );
    reset();
    coordinate(&mut hot.store, &mut hot.components, &original).unwrap();
    let counts = restores();
    assert_eq!(
        &counts[..5],
        &[0, 0, 0, 0, 0],
        "coordinate lost the original plan and replayed Manager journals from its cloned Store Record"
    );
    assert_eq!(
        counts[5], 1,
        "untyped economic metadata keeps its original validation path"
    );
    let mut cold = Harness::new(config()).unwrap();
    reset();
    coordinate(&mut cold.store, &mut cold.components, &copy).unwrap();
    assert!(
        restores()[..5].iter().sum::<u64>() > 0,
        "Clone must drop the transient typed representation"
    );
    assert_eq!(cold.state().unwrap(), hot.state().unwrap());
    assert_eq!(cold.checkpoint().unwrap(), hot.checkpoint().unwrap());
    assert_eq!(cold.store.rows, hot.store.rows);
    let mut denied = Harness::new(config()).unwrap();
    let checkpoint = denied.checkpoint().unwrap();
    assert!(
        coordinate(&mut denied.store, &mut denied.components, &wire).is_err(),
        "decoding canonical data cannot create a new commit capability"
    );
    assert!(denied.store.rows.is_empty());
    assert_eq!(denied.checkpoint().unwrap(), checkpoint);
}
#[test]
fn all_decoded_history_still_restores_owners_and_preserves_economics_and_events() {
    let mut history = Harness::new(config()).unwrap();
    for input in [
        open(1, "BUY"),
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "1", "10.00", "1.00"),
        terminal(4, 1, "CANCELLED"),
    ] {
        apply(&mut history, &input);
    }
    let checkpoint = history.checkpoint().unwrap();
    let state = history.state().unwrap();
    assert_eq!(state["account"]["snapshot"]["cash"], "989.00");
    assert_eq!(state["account"]["snapshot"]["reserved"], "0.00");
    let mut source = decoded(&history.store);
    let original = source.rows.clone();
    let mut restored = Components::new(config()).unwrap();
    reset();
    recover(&mut source, &mut restored).unwrap();
    assert!(
        restores()[..5].iter().sum::<u64>() > 0,
        "retained decoded history cannot borrow a transient planner copy"
    );
    assert_eq!(restores()[5], 4);
    assert_eq!(restored.checkpoint().unwrap(), checkpoint);
    assert_eq!(restored.state(&source).unwrap(), state);
    assert_eq!(source.rows, original);
    assert_eq!(
        crate::pending_events(&source, &restored).unwrap(),
        crate::pending_events(&history.store, &history.components).unwrap()
    );
}
#[test]
fn every_partial_projection_checks_real_committed_identity_and_recovers_without_a_typed_copy() {
    let mut expected = Harness::new(config()).unwrap();
    apply(&mut expected, &open(1, "BUY"));
    let mut foreign = Harness::new(config()).unwrap();
    let mut input = open(1, "BUY");
    input["input_id"] = json!("foreign-input");
    input["source_ref"] = json!("foreign-source");
    apply(&mut foreign, &input);
    for cut in 0..=6 {
        let mut pending = Harness::new(config()).unwrap();
        let planned = pending.prepare(&open(1, "BUY")).unwrap();
        pending.commit_only(&planned).unwrap();
        for index in 0..cut {
            pending
                .components
                .install_projection(&pending.store, &planned, index)
                .unwrap();
        }
        let checkpoint = pending.checkpoint().unwrap();
        assert!(pending.state().is_err());
        if cut < 6 {
            let original = pending.store.rows[0].clone();
            pending.store.rows[0] = foreign.store.rows[0].clone();
            reset();
            assert!(
                pending
                    .components
                    .install_projection(&pending.store, &planned, cut)
                    .is_err(),
                "typed data bypassed actual committed identity at cut {cut}"
            );
            assert_eq!(restores(), [0; 6]);
            assert_eq!(pending.checkpoint().unwrap(), checkpoint);
            pending.store.rows[0] = original;
        }
        let mut source = decoded(&pending.store);
        let mut fresh = Components::new(config()).unwrap();
        fresh
            .restore(
                &checkpoint,
                &crate::digest(checkpoint.to_string().as_bytes()),
            )
            .unwrap();
        recover(&mut source, &mut fresh).unwrap();
        assert_eq!(
            fresh.checkpoint().unwrap(),
            expected.checkpoint().unwrap(),
            "cut {cut}"
        );
        assert_eq!(
            fresh.state(&source).unwrap(),
            expected.state().unwrap(),
            "cut {cut}"
        );
        assert_eq!(source.rows, expected.store.rows, "cut {cut}");
    }
}

#[test]
fn transient_after_keeps_prepared_and_shared_records_send_and_sync() {
    fn shared<T: Send + Sync>() {}
    shared::<Prepared>();
    shared::<Record>();
}
fn swap_owner(left: &mut Components, right: &mut Components, index: usize) {
    match index {
        0 => std::mem::swap(&mut left.order, &mut right.order),
        1 => std::mem::swap(&mut left.position, &mut right.position),
        2 => std::mem::swap(&mut left.account, &mut right.account),
        3 => std::mem::swap(&mut left.ledger, &mut right.ledger),
        4 => std::mem::swap(&mut left.risk, &mut right.risk),
        5 => std::mem::swap(&mut left.meta, &mut right.meta),
        _ => unreachable!(),
    }
}
#[test]
fn mismatching_typed_owner_never_falls_back_or_hides_behind_an_idempotent_return() {
    for selected in 0..6 {
        let mut pending = Harness::new(config()).unwrap();
        let mut planned = pending.prepare(&open(1, "BUY")).unwrap();
        pending.commit_only(&planned).unwrap();
        for index in 0..selected {
            pending
                .components
                .install_projection(&pending.store, &planned, index)
                .unwrap();
        }
        let mut donor = Harness::new(config()).unwrap();
        apply(&mut donor, &open(1, "BUY"));
        apply(&mut donor, &stage(2, 1, "UNKNOWN"));
        let mut later = donor.prepare(&fill(3, 1, "1", "10.00", "1.00")).unwrap();
        let original_bytes = planned.encode().unwrap();
        swap_owner(
            planned.typed_after.as_deref_mut().unwrap(),
            later.typed_after.as_deref_mut().unwrap(),
            selected,
        );
        assert_eq!(
            planned.encode().unwrap(),
            original_bytes,
            "the transient representation never changes the original canonical transaction"
        );
        let before = pending.checkpoint().unwrap();
        reset();
        assert_eq!(
            pending
                .components
                .install_projection(&pending.store, &planned, selected)
                .unwrap_err()
                .0,
            "EXECUTION_TYPED_AFTER_CONFLICT",
            "owner {selected}"
        );
        assert_eq!(
            restores(),
            [0; 6],
            "a known inconsistent typed owner cannot fall back to canonical restore"
        );
        assert_eq!(
            pending.checkpoint().unwrap(),
            before,
            "no owner/progress changes before the inconsistent representation is refused"
        );
        swap_owner(
            planned.typed_after.as_deref_mut().unwrap(),
            later.typed_after.as_deref_mut().unwrap(),
            selected,
        );
        pending
            .components
            .install_projection(&pending.store, &planned, selected)
            .unwrap();
        let applied = pending.checkpoint().unwrap();
        swap_owner(
            planned.typed_after.as_deref_mut().unwrap(),
            later.typed_after.as_deref_mut().unwrap(),
            selected,
        );
        assert_eq!(
            pending
                .components
                .install_projection(&pending.store, &planned, selected)
                .unwrap_err()
                .0,
            "EXECUTION_TYPED_AFTER_CONFLICT",
            "applied-index early return hid owner {selected}"
        );
        assert_eq!(pending.checkpoint().unwrap(), applied);
        let mut lost_index = applied;
        lost_index["pending"][1] = json!(selected);
        pending
            .components
            .restore(
                &lost_index,
                &crate::digest(lost_index.to_string().as_bytes()),
            )
            .unwrap();
        let installed = pending.checkpoint().unwrap();
        assert_eq!(
            pending
                .components
                .install_projection(&pending.store, &planned, selected)
                .unwrap_err()
                .0,
            "EXECUTION_TYPED_AFTER_CONFLICT",
            "result-hash early return hid owner {selected}"
        );
        assert_eq!(pending.checkpoint().unwrap(), installed);
    }
}

#[test]
fn completed_coordinate_rejects_a_present_conflicting_typed_after_without_changing_ready_facts() {
    for selected in 0..6 {
        let mut ready = Harness::new(config()).unwrap();
        let mut planned = ready.prepare(&open(1, "BUY")).unwrap();
        coordinate(&mut ready.store, &mut ready.components, &planned).unwrap();
        let checkpoint = ready.checkpoint().unwrap();
        let original = ready.store.rows.clone();
        let mut donor = Harness::new(config()).unwrap();
        apply(&mut donor, &open(1, "BUY"));
        apply(&mut donor, &stage(2, 1, "UNKNOWN"));
        let mut later = donor.prepare(&fill(3, 1, "1", "10.00", "1.00")).unwrap();
        swap_owner(
            planned.typed_after.as_deref_mut().unwrap(),
            later.typed_after.as_deref_mut().unwrap(),
            selected,
        );
        assert_eq!(
            coordinate(&mut ready.store, &mut ready.components, &planned)
                .unwrap_err()
                .0,
            "EXECUTION_TYPED_AFTER_CONFLICT",
            "completed coordinate shortcut hid owner {selected}"
        );
        assert_eq!(ready.store.rows, original);
        assert_eq!(ready.checkpoint().unwrap(), checkpoint);
        let canonical = Prepared::decode(&planned.encode().unwrap()).unwrap();
        coordinate(&mut ready.store, &mut ready.components, &canonical).unwrap();
        assert_eq!(ready.store.rows, original);
        assert_eq!(
            ready.checkpoint().unwrap(),
            checkpoint,
            "the actual committed facts remain independently recoverable without a transient copy"
        );
    }
}

#[test]
fn typed_account_copy_cannot_cross_the_explicit_execution_format_binding() {
    for modern in [false, true] {
        let mut configuration = config();
        if modern {
            configuration["schema_version"] = json!(2);
            configuration["account_checkpoint_version"] = json!(5);
        }
        let mut pending = Harness::new(configuration).unwrap();
        let mut planned = pending.prepare(&open(1, "BUY")).unwrap();
        pending.commit_only(&planned).unwrap();
        for index in 0..2 {
            pending
                .components
                .install_projection(&pending.store, &planned, index)
                .unwrap();
        }
        let mut foreign = config();
        if !modern {
            foreign["schema_version"] = json!(2);
            foreign["account_checkpoint_version"] = json!(5);
        }
        let donor = Components::new(foreign).unwrap();
        planned.typed_after.as_deref_mut().unwrap().account = donor.account;
        let before = pending.checkpoint().unwrap();
        assert!(
            pending
                .components
                .install_projection(&pending.store, &planned, 2)
                .is_err()
        );
        assert_eq!(pending.checkpoint().unwrap(), before);
    }
}

fn local_construction_parts() -> (Value, Components, Vec<u8>) {
    let source = Harness::new(config()).unwrap();
    let mut planned = source.prepare(&open(1, "BUY")).unwrap();
    let original = planned.encode().unwrap();
    let mut body = planned.record();
    body.as_object_mut().unwrap().remove("payload_hash");
    let after = *planned.typed_after.take().unwrap();
    (body, after, original)
}

#[test]
fn local_typed_native_owners_avoid_repeat_hash_but_cold_and_untyped_inputs_recheck() {
    for selected in 0..5 {
        let (body, after, original) = local_construction_parts();
        let canonical = body["projections"][selected]["result"].to_string();
        crate::model::HASHED_CANONICAL_WATCH.with(|watch| {
            *watch.borrow_mut() = Some((canonical.clone(), 0));
        });
        let local = Prepared::new_with_typed_after(body.clone(), after).unwrap();
        let calls =
            crate::model::HASHED_CANONICAL_WATCH.with(|watch| watch.borrow_mut().take().unwrap().1);
        assert_eq!(
            calls, 0,
            "owner {selected} exact checkpoint was hashed again"
        );
        assert_eq!(local.encode().unwrap(), original);
        assert!(local.is_planned());
        assert!(!local.has_validated_transition_data());

        crate::model::HASHED_CANONICAL_WATCH.with(|watch| {
            *watch.borrow_mut() = Some((canonical.clone(), 0));
        });
        let untyped = Prepared::new(body).unwrap();
        let calls =
            crate::model::HASHED_CANONICAL_WATCH.with(|watch| watch.borrow_mut().take().unwrap().1);
        assert_eq!(
            calls, 1,
            "owner {selected} ordinary local body skipped its hash"
        );
        assert_eq!(untyped.encode().unwrap(), original);

        crate::model::HASHED_CANONICAL_WATCH.with(|watch| {
            *watch.borrow_mut() = Some((canonical, 0));
        });
        let cold = Prepared::decode(&original).unwrap();
        let calls =
            crate::model::HASHED_CANONICAL_WATCH.with(|watch| watch.borrow_mut().take().unwrap().1);
        assert_eq!(
            calls, 1,
            "owner {selected} external bytes skipped their hash"
        );
        assert!(!cold.is_planned());
        assert!(cold.typed_after().is_none());
        assert!(!cold.has_validated_transition_data());
        assert_eq!(cold, local);
    }
}

#[test]
fn typed_constructor_rejects_wrong_owner_hash_complete_value_config_and_account_format() {
    for selected in 0..5 {
        for fault in ["hash", "full-value", "config"] {
            let (mut body, mut after, _) = local_construction_parts();
            match fault {
                "hash" => body["projections"][selected]["result_hash"] = json!("f".repeat(64)),
                "full-value" => {
                    body["projections"][selected]["result"]["state"]["unexpected"] = json!(true);
                    body["projections"][selected]["result_hash"] =
                        json!(crate::model::hash(&body["projections"][selected]["result"],));
                }
                _ => after.config["generation"] = json!("f".repeat(64)),
            }
            assert!(
                Prepared::new_with_typed_after(body, after).is_err(),
                "owner {selected}, {fault}"
            );
        }
    }
    let (body, mut after, _) = local_construction_parts();
    let mut foreign = config();
    foreign["schema_version"] = json!(2);
    foreign["account_checkpoint_version"] = json!(5);
    after.account = Components::new(foreign).unwrap().account;
    assert_eq!(
        Prepared::new_with_typed_after(body, after).unwrap_err().0,
        "EXECUTION_ACCOUNT_CHECKPOINT_FORMAT"
    );
}

#[test]
fn typed_constructor_keeps_unchecked_number_roundtrip_and_decoder_depth_rejection() {
    for raw in ["null", "garbage", "00"] {
        let (mut body, after, _) = local_construction_parts();
        body["projections"][5]["result"]["numeric"] =
            Value::Number(serde_json::Number::from_string_unchecked(raw.into()));
        body["projections"][5]["result_hash"] =
            json!(crate::model::hash(&body["projections"][5]["result"],));
        assert!(
            Prepared::new_with_typed_after(body, after).is_err(),
            "{raw}"
        );
    }
    let (mut body, after, _) = local_construction_parts();
    let mut deep = Value::Null;
    for _ in 0..140 {
        deep = json!([deep]);
    }
    body["projections"][5]["result"]["deep"] = deep;
    body["projections"][5]["result_hash"] =
        json!(crate::model::hash(&body["projections"][5]["result"],));
    assert!(Prepared::new_with_typed_after(body, after).is_err());
}

#[test]
fn moved_projection_array_keeps_the_original_outer_json_and_canonical_prepared_bytes() {
    let mut history = Harness::new(config()).unwrap();
    for input in [
        open(1, "BUY"),
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "1", "10.00", "1.00"),
        terminal(4, 1, "CANCELLED"),
    ] {
        let planned = history.prepare(&input).unwrap();
        let projections = planned.value()["projections"].as_array().unwrap().clone();
        let sequence = history.components.sequence + 1;
        let tx = format!("ETX-{}", crate::model::hash(&input));
        // The exact original outer json! construction, including its owned
        // Vec<Value> argument, remains an independent representation oracle.
        let original = json!({
            "schema_version": 1,
            "transaction_id": tx,
            "config_hash": crate::model::hash(&history.components.config),
            "sequence": sequence,
            "predecessor": history.components.sequence,
            "input": input,
            "projections": projections,
            "events": [{
                "schema_version": 1,
                "event_id": format!("{tx}-EVENT-1"),
                "transaction_id": tx,
                "sequence": sequence,
                "input": input
            }]
        });
        let mut moved = planned.record();
        moved.as_object_mut().unwrap().remove("payload_hash");
        assert_eq!(moved, original);
        assert_eq!(
            serde_json::to_vec(&moved).unwrap(),
            serde_json::to_vec(&original).unwrap()
        );
        let original = Prepared::new(original).unwrap();
        assert_eq!(planned.encode().unwrap(), original.encode().unwrap());
        assert_eq!(
            planned.payload_fingerprint(),
            original.payload_fingerprint()
        );
        coordinate(&mut history.store, &mut history.components, &planned).unwrap();
    }
}
