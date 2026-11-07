//! Exact bytes/digests at original planner and every partial projection cut.
const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
#[path = "../../tests/support/mod.rs"]
mod support;
use crate::{Components, Prepared, digest};
use serde_json::{Value, json};
use support::{Harness, config, fill, open, stage, terminal};
fn assert_owner_digests(components: &Components) {
    let payloads = components.payloads().unwrap();
    assert_eq!(payloads.len(), 6);
    for (index, payload) in payloads.iter().enumerate() {
        assert_eq!(
            components.payload_digest(index).unwrap(),
            digest(payload.to_string().as_bytes()),
            "owner {index}"
        );
    }
    assert!(components.payload_digest(6).is_err());
}

#[test]
fn ready_memory_fork_is_an_independent_head_and_still_checks_its_actual_source() {
    let mut original = Harness::new(config()).unwrap();
    for input in [open(1, "BUY"), stage(2, 1, "UNKNOWN")] {
        let planned = original.prepare(&input).unwrap();
        crate::coordinate(&mut original.store, &mut original.components, &planned).unwrap();
    }
    let checkpoint = original.components.checkpoint().unwrap();
    let copy = original.components.fork_ready(&original.store).unwrap();
    assert_eq!(copy.checkpoint().unwrap(), checkpoint);
    let mut branch = Harness {
        components: copy,
        store: original.store.clone(),
    };
    let partial = fill(3, 1, "1", "10.00", "1.00");
    let planned = branch.prepare(&partial).unwrap();
    crate::coordinate(&mut branch.store, &mut branch.components, &planned).unwrap();
    assert_ne!(branch.components.checkpoint().unwrap(), checkpoint);
    assert_eq!(original.components.checkpoint().unwrap(), checkpoint);
    assert!(
        original.components.fork_ready(&branch.store).is_err(),
        "an independent copy does not grant a different committed head"
    );
    let planned = original.prepare(&partial).unwrap();
    original.commit_only(&planned).unwrap();
    assert!(
        original.components.fork_ready(&original.store).is_err(),
        "the actual unready tail cannot be cloned into Ready"
    );
}
#[test]
fn selected_owner_digest_equals_original_full_payload_at_every_projection_cut() {
    let mut history = Harness::new(config()).unwrap();
    assert_owner_digests(&history.components);
    for value in [
        open(1, "BUY"),
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "1", "10.00", "1.00"),
        terminal(4, 1, "CANCELLED"),
    ] {
        let prepared = history.prepare(&value).unwrap();
        for index in 0..6 {
            assert_owner_digests(&history.components);
            history.install_projection(&prepared, index).unwrap();
            assert_owner_digests(&history.components);
        }
        history.complete(&prepared).unwrap();
        assert_owner_digests(&history.components);
    }
}
#[test]
fn complete_prepared_encoding_preserves_original_source_hash_and_value_isolation() {
    let history = Harness::new(config()).unwrap();
    let prepared = history.prepare(&open(1, "BUY")).unwrap();
    let original = prepared.record();
    let encoded = prepared.encode().unwrap();
    let expected = serde_json::to_vec(&original).unwrap();
    assert_eq!(encoded, expected);
    let full = digest(&expected);
    // payload_hash intentionally omits itself; the durable Store source does not.
    assert_ne!(Value::String(full.clone()), original["payload_hash"]);
    let decoded = Prepared::decode(&encoded).unwrap();
    assert_eq!(decoded, prepared);
    assert_eq!(digest(&decoded.encode().unwrap()), full);
    let mut detached = prepared.record();
    detached["input"]["source_ref"] = json!("detached-source");
    assert_eq!(prepared.record(), original);
    assert_eq!(digest(&prepared.encode().unwrap()), full);
}

#[test]
fn immutable_prepared_validates_at_construction_and_transport_boundaries() {
    crate::model::PREPARED_VALIDATIONS.with(|count| count.set(0));
    let mut history = Harness::new(config()).unwrap();
    let prepared = history.prepare(&open(1, "BUY")).unwrap();
    crate::coordinate(&mut history.store, &mut history.components, &prepared).unwrap();
    // One planner construction and the actual Ready-row transport decode.
    // Reusing the same immutable typed value must not re-encode all projections.
    assert_eq!(
        crate::model::PREPARED_VALIDATIONS.with(std::cell::Cell::get),
        2
    );
    let decoded = Prepared::decode(&prepared.encode().unwrap()).unwrap();
    assert_eq!(decoded.record(), prepared.record());
    assert_eq!(
        crate::model::PREPARED_VALIDATIONS.with(std::cell::Cell::get),
        3
    );
    let mut destination = Harness::new(config()).unwrap();
    let before = destination.checkpoint().unwrap();
    assert!(
        crate::coordinate(
            &mut destination.store,
            &mut destination.components,
            &decoded
        )
        .is_err()
    );
    assert_eq!(destination.checkpoint().unwrap(), before);
    assert!(destination.store.rows.is_empty());
    crate::coordinate(&mut history.store, &mut history.components, &prepared).unwrap();
    crate::coordinate(&mut history.store, &mut history.components, &decoded).unwrap();
    assert_eq!(
        crate::model::PREPARED_VALIDATIONS.with(std::cell::Cell::get),
        3
    );
    let mut detached = prepared.record();
    detached["input"]["source_ref"] = json!("changed-after-construction");
    assert!(Prepared::decode(&serde_json::to_vec(&detached).unwrap()).is_err());
    assert_ne!(prepared.record(), detached);
}

#[test]
fn reconciliation_captures_only_one_complete_current_and_genesis_owner_image() {
    for count in [16_u64, 32] {
        let mut history = Harness::new(config()).unwrap();
        for n in 1..=count {
            let value = match n {
                1 => open(1, "BUY"),
                2 => stage(2, 1, "UNKNOWN"),
                3 => fill(3, 1, "1", "10.00", "1.00"),
                4 => terminal(4, 1, "CANCELLED"),
                _ => {
                    let state = history.components.state(&history.store).unwrap();
                    support::input(
                        n,
                        "VALUATION",
                        json!({"schema_version":1,"valuation":format!("owner-capture-{n}"),"version":n,
                    "position_evidence":digest(history.components.checkpoint().unwrap()["components"][1].to_string().as_bytes()),"economic_version":state["account"]["snapshot"]["economic_version"],
                    "marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":"12.00","source_ref":format!("owner-mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}]}),
                    )
                }
            };
            let prepared = history.prepare(&value).unwrap();
            crate::coordinate(&mut history.store, &mut history.components, &prepared).unwrap();
        }
        let before = history.components.checkpoint().unwrap();
        let expected = history
            .components
            .reconcile(&history.store)
            .unwrap()
            .record();
        crate::components::PAYLOAD_CAPTURE_BYTES.with(|bytes| bytes.set(0));
        history.components.payloads().unwrap();
        let current = crate::components::PAYLOAD_CAPTURE_BYTES.with(std::cell::Cell::get);
        crate::components::PAYLOAD_CAPTURE_BYTES.with(|bytes| bytes.set(0));
        Components::new(config()).unwrap().payloads().unwrap();
        let genesis = crate::components::PAYLOAD_CAPTURE_BYTES.with(std::cell::Cell::get);
        crate::components::PAYLOAD_CAPTURE_BYTES.with(|bytes| bytes.set(0));
        assert_eq!(
            history
                .components
                .reconcile(&history.store)
                .unwrap()
                .record(),
            expected
        );
        let captured = crate::components::PAYLOAD_CAPTURE_BYTES.with(std::cell::Cell::get);
        assert_eq!(
            captured, 0,
            "warm reconciliation recaptured immutable owner data"
        );
        let mut cold = Components::new(config()).unwrap();
        cold.restore(&before, &digest(before.to_string().as_bytes()))
            .unwrap();
        crate::components::PAYLOAD_CAPTURE_BYTES.with(|bytes| bytes.set(0));
        assert_eq!(cold.reconcile(&history.store).unwrap().record(), expected);
        let captured = crate::components::PAYLOAD_CAPTURE_BYTES.with(std::cell::Cell::get);
        assert!(
            captured > 0 && captured <= current + genesis,
            "reconciliation repeatedly encoded the same complete history: {captured} > {}",
            current + genesis
        );
        assert_eq!(
            history.components.checkpoint().unwrap(),
            before,
            "a source observation cannot mutate an economic owner"
        );
    }
}

fn checkpoint5_configuration() -> Value {
    let mut value = config();
    value["schema_version"] = json!(2);
    value["account_checkpoint_version"] = json!(5);
    value
}
#[test]
fn explicit_account_format_is_part_of_execution_configuration_and_keeps_legacy_genesis() {
    let old = Components::new(config()).unwrap().checkpoint().unwrap();
    assert_eq!(old["components"][2]["schema_version"], 4);
    let new = Components::new(checkpoint5_configuration())
        .unwrap()
        .checkpoint()
        .unwrap();
    assert_eq!(new["components"][2]["schema_version"], 5);
    assert_ne!(
        digest(old["config"].to_string().as_bytes()),
        digest(new["config"].to_string().as_bytes())
    );
    for index in [0, 1, 3, 4, 5] {
        assert_eq!(
            new["components"][index], old["components"][index],
            "only the explicitly selected Account codec changes genesis"
        );
    }
    for version in [json!(0), json!(3), json!(null)] {
        let mut wrong = checkpoint5_configuration();
        wrong["schema_version"] = version;
        assert!(Components::new(wrong).is_err());
    }
    for selected in [json!(4), json!(6), json!(null), json!("5")] {
        let mut wrong = checkpoint5_configuration();
        wrong["account_checkpoint_version"] = selected;
        assert!(Components::new(wrong).is_err());
    }
    let mut missing = checkpoint5_configuration();
    missing
        .as_object_mut()
        .unwrap()
        .remove("account_checkpoint_version");
    assert!(Components::new(missing).is_err());
    let mut old_with_selector = config();
    old_with_selector["account_checkpoint_version"] = json!(5);
    assert!(Components::new(old_with_selector).is_err());
    for kind in ["SIM", "LIVE"] {
        let mut wrong = checkpoint5_configuration();
        wrong["runtime_kind"] = json!(kind);
        assert!(Components::new(wrong).is_err());
    }
    let mut extra = checkpoint5_configuration();
    extra["new_authority"] = json!(true);
    assert!(Components::new(extra).is_err());
}
#[test]
fn a_configuration_cannot_restore_another_account_checkpoint_variant() {
    let old = Components::new(config()).unwrap().checkpoint().unwrap();
    let new = Components::new(checkpoint5_configuration())
        .unwrap()
        .checkpoint()
        .unwrap();
    for (configuration, original, foreign) in [
        (config(), old.clone(), new["components"][2].clone()),
        (
            checkpoint5_configuration(),
            new.clone(),
            old["components"][2].clone(),
        ),
    ] {
        let mut target = Components::new(configuration).unwrap();
        let _ = target.payloads().unwrap();
        let mut mixed = original.clone();
        mixed["components"][2] = foreign.clone();
        assert!(
            target
                .restore(&mixed, &digest(mixed.to_string().as_bytes()))
                .is_err()
        );
        assert_eq!(target.checkpoint().unwrap(), original);
    }
}

#[test]
fn a_resealed_intermediate_account_format_cannot_hide_behind_the_same_ready_head() {
    for modern in [false, true] {
        let configuration = if modern {
            checkpoint5_configuration()
        } else {
            config()
        };
        let mut history = Harness::new(configuration).unwrap();
        for input in [open(1, "BUY"), stage(2, 1, "UNKNOWN")] {
            let planned = history.prepare(&input).unwrap();
            crate::coordinate(&mut history.store, &mut history.components, &planned).unwrap();
        }
        let checkpoint = history.components.checkpoint().unwrap();
        let mut first = history.store.rows[0].record();
        let account = &mut first["prepared"]["projections"][2]["result"];
        account["schema_version"] = json!(if modern { 4 } else { 5 });
        if modern {
            account.as_object_mut().unwrap().remove("positions");
        } else {
            account["positions"] = json!({});
        }
        let middle = digest(account.to_string().as_bytes());
        first["prepared"]["projections"][2]["result_hash"] = json!(middle);
        first["prepared"]
            .as_object_mut()
            .unwrap()
            .remove("payload_hash");
        first["prepared"]["payload_hash"] = json!(digest(first["prepared"].to_string().as_bytes()));
        history.store.rows[0] = crate::Record::decode(&first).unwrap();
        let mut second = history.store.rows[1].record();
        second["prepared"]["projections"][2]["before_hash"] = json!(middle);
        second["prepared"]
            .as_object_mut()
            .unwrap()
            .remove("payload_hash");
        second["prepared"]["payload_hash"] =
            json!(digest(second["prepared"].to_string().as_bytes()));
        history.store.rows[1] = crate::Record::decode(&second).unwrap();
        assert_eq!(
            history.components.checkpoint().unwrap(),
            checkpoint,
            "the actual final owner has not changed"
        );
        assert!(history.components.state(&history.store).is_err());
        assert!(history.components.reconcile(&history.store).is_err());
        assert!(history.components.fork_ready(&history.store).is_err());
    }
}

#[test]
fn prepared_clones_share_canonical_body_without_copying_the_linear_plan() {
    let source = Harness::new(config()).unwrap();
    let prepared = source.prepare(&open(1, "BUY")).unwrap();
    assert!(prepared.is_planned());
    assert!(prepared.typed_after().is_some());
    let original = prepared.record();
    let encoded = serde_json::to_vec(&original).unwrap();
    assert_eq!(prepared.encode().unwrap(), encoded);
    let decoded = Prepared::decode(&encoded).unwrap();
    assert_eq!(decoded, prepared);
    assert_eq!(decoded.encode().unwrap(), encoded);
    assert!(!decoded.is_planned());
    assert!(decoded.typed_after().is_none());
    assert!(
        !std::ptr::eq(prepared.value(), decoded.value()),
        "a cold transport decode owns its own validated body"
    );
    let copy = prepared.clone();
    let decoded_copy = decoded.clone();
    assert!(copy.is_planned());
    assert!(!decoded_copy.is_planned());
    assert!(copy.typed_after().is_none());
    assert!(decoded_copy.typed_after().is_none());
    assert_eq!(copy, prepared);
    assert_eq!(decoded_copy, decoded);
    assert_eq!(format!("{copy:?}"), format!("{prepared:?}"));
    let mut detached = copy.record();
    detached["input"]["source_ref"] = json!("detached-copy");
    detached["projections"][5]["result"]["inputs"]["detached-input"] = json!("not-an-owning-fact");
    assert_ne!(detached, original);
    for retained in [&prepared, &copy, &decoded, &decoded_copy] {
        assert_eq!(retained.record(), original);
        assert_eq!(retained.encode().unwrap(), encoded);
    }
    let mut destination = Harness::new(config()).unwrap();
    let before = destination.checkpoint().unwrap();
    assert!(
        crate::coordinate(
            &mut destination.store,
            &mut destination.components,
            &decoded_copy
        )
        .is_err()
    );
    assert!(destination.store.rows.is_empty());
    assert_eq!(destination.checkpoint().unwrap(), before);
    assert!(
        std::ptr::eq(prepared.value(), copy.value()),
        "clone must share the entire already validated canonical body instead of duplicating all owner histories"
    );
    assert!(
        std::ptr::eq(decoded.value(), decoded_copy.value()),
        "decoded immutable bodies have the same sharing property without acquiring a planner grant"
    );
}

#[test]
fn passive_prepared_observation_retains_exact_data_without_retaining_an_expanded_history() {
    let source = Harness::new(config()).unwrap();
    let planned = source.prepare(&open(1, "BUY")).unwrap();
    let original = planned.record();
    let bytes = planned.encode().unwrap();
    let expansion = planned.retained_expansion().unwrap();
    let passive = planned.observation();
    assert!(
        passive.retained_expansion().is_none(),
        "a passive source observation must not pin the original expanded owner histories"
    );
    assert!(!passive.is_planned());
    assert!(passive.typed_after().is_none());
    assert_eq!(passive.id(), planned.id());
    assert_eq!(passive.sequence(), planned.sequence());
    assert_eq!(passive.input(), planned.input());
    assert_eq!(passive.events(), planned.events());
    assert_eq!(passive.input_fingerprint(), planned.input_fingerprint());
    assert_eq!(passive.encode().unwrap(), bytes);
    assert_eq!(passive.record(), original);
    assert!(
        passive.retained_expansion().is_none(),
        "metadata and detached exports must not populate the source's full-body memo"
    );
    drop(planned);
    assert!(
        expansion.upgrade().is_none(),
        "the exact encoded data must not retain the old expanded allocation indirectly"
    );
    assert_eq!(passive.value(), &original);
    let copy = passive.clone();
    assert!(
        std::ptr::eq(passive.value(), copy.value()),
        "explicitly expanded immutable clones retain their existing sharing semantics"
    );
    let next = passive.observation();
    assert!(next.retained_expansion().is_none());
    assert_eq!(next.record(), original);
    assert_eq!(next.encode().unwrap(), bytes);
    assert!(!next.is_planned());
    assert!(next.typed_after().is_none());
}

#[test]
fn full_ready_and_financial_source_guards_do_not_expand_retained_body_histories() {
    for modern in [false, true] {
        let mut configuration = config();
        if modern {
            configuration["schema_version"] = json!(2);
            configuration["account_checkpoint_version"] = json!(5);
        }
        let mut h = Harness::new(configuration).unwrap();
        for input in [
            open(1, "BUY"),
            stage(2, 1, "UNKNOWN"),
            fill(3, 1, "1", "10.00", "1.00"),
            terminal(4, 1, "CANCELLED"),
        ] {
            let plan = h.prepare(&input).unwrap();
            crate::coordinate(&mut h.store, &mut h.components, &plan).unwrap();
        }
        let before = h.checkpoint().unwrap();
        let original = h
            .store
            .rows
            .iter()
            .map(|record| record.prepared().encode().unwrap())
            .collect::<Vec<_>>();
        h.store.rows = h
            .store
            .rows
            .iter()
            .map(|record| {
                record
                    .observation_snapshot(record.ready(), record.delivered())
                    .unwrap()
            })
            .collect();
        for _ in 0..2 {
            h.components.state(&h.store).unwrap();
            h.components.reconcile(&h.store).unwrap();
            h.components.fork_ready(&h.store).unwrap();
            assert_eq!(h.components.ready_records(&h.store).unwrap(), h.store.rows);
            assert!(
                h.store
                    .rows
                    .iter()
                    .all(|record| record.prepared().retained_expansion().is_none()),
                "complete source guards need the exact validated headers, not expanded owner histories"
            );
        }
        assert_eq!(h.checkpoint().unwrap(), before);
        assert_eq!(
            h.store
                .rows
                .iter()
                .map(|record| record.prepared().encode().unwrap())
                .collect::<Vec<_>>(),
            original
        );
    }
}

#[test]
fn planned_body_must_have_exact_readable_canonical_json_before_becoming_compact() {
    let source = Harness::new(config()).unwrap();
    let original = source.prepare(&open(1, "BUY")).unwrap().record();
    for raw in ["null", "garbage", "00"] {
        let mut body = original.clone();
        body["projections"][0]["result"]["numeric"] =
            Value::Number(serde_json::Number::from_string_unchecked(raw.into()));
        body["projections"][0]["result_hash"] = json!(digest(
            body["projections"][0]["result"].to_string().as_bytes()
        ));
        body.as_object_mut().unwrap().remove("payload_hash");
        assert!(
            Prepared::new(body).is_err(),
            "an unchecked Number must not change the decoded meaning or make its encoded body unreadable: {raw}"
        );
    }
    let mut body = original;
    let mut deep = Value::Null;
    for _ in 0..140 {
        deep = json!([deep]);
    }
    body["projections"][0]["result"]["deep"] = deep;
    body["projections"][0]["result_hash"] = json!(digest(
        body["projections"][0]["result"].to_string().as_bytes()
    ));
    body.as_object_mut().unwrap().remove("payload_hash");
    assert!(
        Prepared::new(body).is_err(),
        "a planned body must be readable by its original bounded decoder"
    );
}

#[test]
fn compact_body_equality_preserves_full_values_for_exact_numeric_lexemes() {
    let source = Harness::new(config()).unwrap();
    let original = source.prepare(&open(1, "BUY")).unwrap().record();
    let mut cases = Vec::new();
    for raw in [
        "0",
        "-0",
        "1",
        "1.0",
        "1e0",
        "1E+0",
        "18446744073709551615",
        "18446744073709551616",
        "0.00000001",
        "1e-8",
    ] {
        let mut body = original.clone();
        body["projections"][0]["result"]["numeric"] = serde_json::from_str(raw).unwrap();
        body["projections"][0]["result_hash"] = json!(digest(
            body["projections"][0]["result"].to_string().as_bytes()
        ));
        body.as_object_mut().unwrap().remove("payload_hash");
        body["payload_hash"] = json!(digest(body.to_string().as_bytes()));
        let bytes = serde_json::to_vec(&body).unwrap();
        let compact = Prepared::decode(&bytes).unwrap().compact_clone();
        assert_eq!(compact.record(), body);
        assert_eq!(compact.encode().unwrap(), bytes);
        cases.push((body, compact));
    }
    for (left_body, left) in &cases {
        for (right_body, right) in &cases {
            assert_eq!(left == right, left_body == right_body);
        }
    }
}

#[test]
fn compact_planner_keeps_exact_commit_but_compact_decoded_data_has_no_new_origin() {
    let source = Harness::new(config()).unwrap();
    let planned = source.prepare(&open(1, "BUY")).unwrap();
    let bytes = planned.encode().unwrap();
    let compact = planned.compact_clone();
    assert!(compact.is_planned());
    assert!(compact.typed_after().is_none());
    assert!(compact.retained_expansion().is_none());
    let mut hot = Harness::new(config()).unwrap();
    crate::coordinate(&mut hot.store, &mut hot.components, &planned).unwrap();
    let mut cold = Harness::new(config()).unwrap();
    crate::coordinate(&mut cold.store, &mut cold.components, &compact).unwrap();
    assert_eq!(cold.checkpoint().unwrap(), hot.checkpoint().unwrap());
    assert_eq!(cold.store.rows, hot.store.rows);
    assert_eq!(cold.store.rows[0].prepared().encode().unwrap(), bytes);
    let decoded = Prepared::decode(&bytes).unwrap().compact_clone();
    assert!(!decoded.is_planned());
    let mut denied = Harness::new(config()).unwrap();
    let before = denied.checkpoint().unwrap();
    assert!(crate::coordinate(&mut denied.store, &mut denied.components, &decoded).is_err());
    assert!(denied.store.rows.is_empty());
    assert_eq!(denied.checkpoint().unwrap(), before);
}

#[test]
fn immutable_prepared_input_fingerprint_is_exact_and_codec_work_is_not_source_authority() {
    let history = Harness::new(config()).unwrap();
    let prepared = history.prepare(&open(1, "BUY")).unwrap();
    let bytes = prepared.encode().unwrap();
    let canonical = serde_json::to_string(prepared.input()).unwrap();
    let expected = digest(canonical.as_bytes());
    let copy = prepared.clone();
    crate::model::HASHED_CANONICAL_WATCH
        .with(|watch| *watch.borrow_mut() = Some((canonical.clone(), 0)));
    let wire = Prepared::decode(&bytes).unwrap();
    assert_eq!(
        crate::model::HASHED_CANONICAL_WATCH.with(|watch| watch.borrow().as_ref().unwrap().1),
        1,
        "a cold decoder hashes its complete actual input during original ETX validation"
    );
    crate::model::HASHED_CANONICAL_WATCH
        .with(|watch| *watch.borrow_mut() = Some((canonical.clone(), 0)));
    for _ in 0..4 {
        assert_eq!(prepared.input_fingerprint(), expected);
        assert_eq!(copy.input_fingerprint(), expected);
        assert_eq!(wire.input_fingerprint(), expected);
    }
    let calls =
        crate::model::HASHED_CANONICAL_WATCH.with(|watch| watch.borrow_mut().take().unwrap().1);
    assert_eq!(
        calls, 0,
        "new/decode already verified the same complete input for its transaction identity"
    );
    assert_eq!(prepared, copy);
    assert_eq!(prepared, wire);
    assert_eq!(prepared.encode().unwrap(), bytes);
    assert_eq!(wire.encode().unwrap(), bytes);
    assert!(
        !wire.is_planned(),
        "a cached data fingerprint must not create a planner origin"
    );
    let mut different = open(1, "BUY");
    different["source_ref"] = json!("different-original-source");
    let other = history.prepare(&different).unwrap();
    assert_ne!(other.input_fingerprint(), expected);
    assert_eq!(
        other.input_fingerprint(),
        digest(serde_json::to_string(&different).unwrap().as_bytes())
    );
    let other_wire = Prepared::decode(&other.encode().unwrap()).unwrap();
    assert_ne!(other_wire.input_fingerprint(), wire.input_fingerprint());
    assert_eq!(
        wire.input_fingerprint(),
        expected,
        "a distinct cold decoder cannot overwrite an earlier immutable fingerprint"
    );
    let mut denied = Harness::new(config()).unwrap();
    let before = denied.checkpoint().unwrap();
    assert!(crate::coordinate(&mut denied.store, &mut denied.components, &wire).is_err());
    assert!(denied.store.rows.is_empty());
    assert_eq!(denied.checkpoint().unwrap(), before);
}

#[test]
fn prepared_equality_keeps_complete_values_for_shared_and_independent_bodies() {
    let history = Harness::new(config()).unwrap();
    let planned = history.prepare(&open(1, "BUY")).unwrap();
    let cloned = planned.clone();
    let bytes = planned.encode().unwrap();
    let decoded = Prepared::decode(&bytes).unwrap();
    assert!(
        std::ptr::eq(planned.value(), cloned.value()),
        "fixture must exercise a shared immutable allocation"
    );
    assert!(
        !std::ptr::eq(planned.value(), decoded.value()),
        "cold transport owns an independent canonical allocation"
    );
    assert_eq!(planned, cloned);
    assert_eq!(planned, decoded);
    assert_eq!(decoded, cloned);
    // A freshly decoded canonical body may retain the same transaction/input
    // identity while differing in another complete projection field. It is
    // passive data, not a planner or authenticated owning Store fact.
    let mut changed = planned.record();
    changed["projections"][0]["before_hash"] = json!("f".repeat(64));
    changed.as_object_mut().unwrap().remove("payload_hash");
    changed["payload_hash"] = json!(digest(changed.to_string().as_bytes()));
    let changed = Prepared::decode(&serde_json::to_vec(&changed).unwrap()).unwrap();
    assert_eq!(changed.id(), planned.id());
    assert_eq!(changed.input_fingerprint(), planned.input_fingerprint());
    assert_ne!(changed, planned);
    assert_ne!(changed, cloned);
    assert_ne!(changed, decoded);
    for passive in [&decoded, &changed] {
        let mut foreign = Harness::new(config()).unwrap();
        let before = foreign.checkpoint().unwrap();
        assert!(crate::coordinate(&mut foreign.store, &mut foreign.components, passive).is_err());
        assert!(foreign.store.rows.is_empty());
        assert_eq!(foreign.checkpoint().unwrap(), before);
    }
}

#[test]
fn a_caller_marker_in_transport_json_never_certifies_transition_data() {
    let history = Harness::new(config()).unwrap();
    let planned = history.prepare(&open(1, "BUY")).unwrap();
    let mut body = planned.record();
    body["validated_transition_data"] = json!(true);
    body.as_object_mut().unwrap().remove("payload_hash");
    body["payload_hash"] = json!(digest(body.to_string().as_bytes()));
    assert!(
        Prepared::decode(&serde_json::to_vec(&body).unwrap()).is_err(),
        "a resealed DTO cannot issue a pure validity marker or planner origin"
    );
}

#[test]
fn local_prepared_constructor_hashes_complete_body_once_and_cold_decode_rechecks_it() {
    let history = Harness::new(config()).unwrap();
    let planned = history.prepare(&open(1, "BUY")).unwrap();
    let mut body = planned.record();
    body.as_object_mut().unwrap().remove("payload_hash");
    let canonical = body.to_string();
    crate::model::HASHED_CANONICAL_WATCH
        .with(|watch| *watch.borrow_mut() = Some((canonical.clone(), 0)));
    let local = Prepared::new(body).unwrap();
    assert_eq!(
        crate::model::HASHED_CANONICAL_WATCH.with(|watch| watch.borrow_mut().take().unwrap().1),
        1,
        "the same owned complete payload was hashed twice during local construction"
    );
    assert!(local.is_planned());
    assert_eq!(local.encode().unwrap(), planned.encode().unwrap());
    crate::model::HASHED_CANONICAL_WATCH.with(|watch| *watch.borrow_mut() = Some((canonical, 0)));
    let cold = Prepared::decode(&local.encode().unwrap()).unwrap();
    assert_eq!(
        crate::model::HASHED_CANONICAL_WATCH.with(|watch| watch.borrow_mut().take().unwrap().1),
        1,
        "cold bytes must still recompute the complete payload hash"
    );
    assert!(!cold.is_planned());
    assert_eq!(cold, local);
    assert_eq!(
        Prepared::new(local.record()).unwrap_err().0,
        "EXECUTION_PAYLOAD_HASH"
    );
    let mut corrupt = local.record();
    corrupt["payload_hash"] = json!("f".repeat(64));
    assert_eq!(
        Prepared::decode(&serde_json::to_vec(&corrupt).unwrap())
            .unwrap_err()
            .0,
        "EXECUTION_PAYLOAD_HASH"
    );
}

#[test]
fn locally_computed_payload_hash_does_not_skip_structure_projection_or_event_checks() {
    let history = Harness::new(config()).unwrap();
    let mut original = history.prepare(&open(1, "BUY")).unwrap().record();
    original.as_object_mut().unwrap().remove("payload_hash");
    for fault in 0..6 {
        let mut body = original.clone();
        match fault {
            0 => {
                body["sequence"] = json!(0);
            }
            1 => {
                body["config_hash"] = json!("bad");
            }
            2 => {
                body["projections"][0]["result_hash"] = json!("f".repeat(64));
            }
            3 => {
                body["projections"][0]["component"] = json!("UNKNOWN");
            }
            4 => {
                body["events"][0]["event_id"] = json!("foreign-event");
            }
            _ => {
                body["unexpected"] = Value::Null;
            }
        }
        assert!(
            Prepared::new(body).is_err(),
            "local payload shortcut accepted fault {fault}"
        );
    }
}
