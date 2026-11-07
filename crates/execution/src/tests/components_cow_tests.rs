//! Immutable owner sharing is representation reuse, never Store or Ready proof.
use super::*;
use crate::{Prepared, coordinate, recover};

const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
#[path = "../../tests/support/mod.rs"]
mod support;
use support::{Harness, config, fill, open, stage};

fn shared_owners(left: &Components, right: &Components) -> [bool; 6] {
    [
        Arc::ptr_eq(&left.order, &right.order),
        Arc::ptr_eq(&left.position, &right.position),
        Arc::ptr_eq(&left.account, &right.account),
        Arc::ptr_eq(&left.ledger, &right.ledger),
        Arc::ptr_eq(&left.risk, &right.risk),
        Arc::ptr_eq(&left.meta, &right.meta),
    ]
}

fn original_images(owner: &Components) -> Vec<Value> {
    let mut images = Vec::new();
    for bytes in [
        owner.order.checkpoint().unwrap().0,
        owner.position.checkpoint().unwrap().0,
        owner.account.checkpoint().unwrap().0,
        owner.ledger.checkpoint().unwrap().0,
        owner.risk.checkpoint().unwrap().0,
    ] {
        images.push(serde_json::from_slice(&bytes).unwrap());
    }
    images.push(owner.meta.as_ref().clone());
    images
}

#[test]
fn forks_share_immutable_owners_and_each_install_mutates_only_its_branch() {
    let source = Components::new(config()).unwrap();
    let original = source.checkpoint().unwrap();
    let mut donor = Harness::new(config()).unwrap();
    let prepared = donor.prepare(&open(1, "BUY")).unwrap();
    coordinate(&mut donor.store, &mut donor.components, &prepared).unwrap();
    let donor_images = original_images(&donor.components);

    for selected in 0..6 {
        let mut fork = source.clone_data();
        assert_eq!(shared_owners(&source, &fork), [true; 6]);
        fork.install_payload(selected, &donor_images[selected])
            .unwrap();
        for (index, shared) in shared_owners(&source, &fork).into_iter().enumerate() {
            assert_eq!(
                shared,
                index != selected,
                "installed owner {selected}, checked {index}"
            );
        }
        fork.sequence = 77;
        fork.pending = Some(("local-only".into(), selected));
        assert_eq!(source.sequence, 0);
        assert!(source.pending.is_none());
        assert_eq!(source.checkpoint().unwrap(), original);
        assert_eq!(fork.payloads().unwrap().as_ref(), &original_images(&fork));
        let mut detached = Arc::clone(&fork.meta);
        Arc::make_mut(&mut detached)["foreign"] = json!(true);
        assert!(fork.meta.get("foreign").is_none());
    }
}

#[test]
fn rejected_planning_and_restore_cannot_modify_shared_source_or_its_codec() {
    let mut history = Harness::new(config()).unwrap();
    for input in [open(1, "BUY"), stage(2, 1, "UNKNOWN")] {
        let prepared = history.prepare(&input).unwrap();
        coordinate(&mut history.store, &mut history.components, &prepared).unwrap();
    }
    let original = history.components.clone_data();
    let checkpoint = history.components.checkpoint().unwrap();
    let image = history.components.payloads().unwrap();
    assert!(history.prepare(&fill(3, 1, "11", "10.00", "1.00")).is_err());
    assert_eq!(shared_owners(&original, &history.components), [true; 6]);
    assert!(Arc::ptr_eq(&image, &history.components.payloads().unwrap()));
    assert_eq!(history.components.checkpoint().unwrap(), checkpoint);

    let mut fork = history.components.clone_data();
    let mut corrupt = checkpoint.clone();
    corrupt["components"][4]["state"]["sequence"] = json!(999);
    assert!(fork.restore(&corrupt, &hash(&corrupt)).is_err());
    assert_eq!(shared_owners(&original, &fork), [true; 6]);
    assert_eq!(fork.checkpoint().unwrap(), checkpoint);
    assert_eq!(history.components.checkpoint().unwrap(), checkpoint);
}

#[test]
fn typed_completion_reuses_exact_codec_and_cold_partial_recovery_keeps_original_bytes() {
    let mut hot = Harness::new(config()).unwrap();
    let prepared = hot.prepare(&open(1, "BUY")).unwrap();
    let encoded = prepared.encode().unwrap();
    let after = prepared.typed_after().unwrap();
    let candidate_image = after.payloads().unwrap();
    coordinate(&mut hot.store, &mut hot.components, &prepared).unwrap();
    assert_eq!(shared_owners(&hot.components, after), [true; 6]);
    assert!(Arc::ptr_eq(
        &candidate_image,
        &hot.components.payloads().unwrap()
    ));
    assert_eq!(
        hot.components.payloads().unwrap().as_ref(),
        &original_images(&hot.components)
    );
    assert_eq!(prepared.encode().unwrap(), encoded);
    let expected = hot.components.checkpoint().unwrap();

    for installed in 0..=6 {
        let mut pending = Harness::new(config()).unwrap();
        let cold = Prepared::decode(&encoded).unwrap();
        // Only the original planner may create the durable fact. The decoded
        // copy exercises cold installation/recovery after that commit exists.
        pending.commit_only(&prepared).unwrap();
        assert_eq!(pending.store.rows.len(), 1);
        assert_eq!(pending.store.rows[0].prepared(), &cold);
        // Cold reconstruction must discard the hot planner's shared validation
        // slot as well as its typed representation, while preserving the row.
        let stored_row = pending.store.rows[0].record();
        let stored_bytes = pending.store.rows[0].prepared().encode().unwrap();
        let cold_record = crate::Record::decode(&stored_row).unwrap();
        assert_eq!(cold_record.record(), stored_row);
        assert_eq!(cold_record.prepared().encode().unwrap(), stored_bytes);
        assert_eq!(cold_record.ready(), pending.store.rows[0].ready());
        assert_eq!(cold_record.delivered(), pending.store.rows[0].delivered());
        assert!(!cold_record.prepared().is_planned());
        assert!(!cold_record.prepared().has_validated_transition_data());
        assert!(cold_record.prepared().typed_after().is_none());
        assert!(!cold.is_planned());
        assert!(!cold.has_validated_transition_data());
        pending.store.rows[0] = cold_record;
        for index in 0..installed {
            pending
                .components
                .install_projection(&pending.store, &cold, index)
                .unwrap();
        }
        let checkpoint = pending.components.checkpoint().unwrap();
        let mut recovered = Components::new(config()).unwrap();
        recovered.restore(&checkpoint, &hash(&checkpoint)).unwrap();
        assert_eq!(recovered.checkpoint().unwrap(), checkpoint);
        recover(&mut pending.store, &mut recovered).unwrap();
        assert_eq!(
            recovered.checkpoint().unwrap(),
            expected,
            "partial prefix {installed}"
        );
        assert_eq!(
            recovered.payloads().unwrap().as_ref(),
            &original_images(&recovered)
        );
    }
    let removed = hot.store.rows.pop().unwrap();
    assert!(hot.components.state(&hot.store).is_err());
    assert!(hot.components.reconcile(&hot.store).is_err());
    hot.store.rows.push(removed);
    hot.components.reconcile(&hot.store).unwrap();
}

#[test]
fn codec_adoption_requires_all_owner_pointers_and_complete_matching_values_and_hashes() {
    let history = Harness::new(config()).unwrap();
    let prepared = history.prepare(&open(1, "BUY")).unwrap();
    let after = prepared.typed_after().unwrap();
    for fault in [
        "value",
        "hash",
        "length",
        "owner-pointer",
        "metadata-pointer",
        "missing",
    ] {
        let mut donor = after.clone_data();
        let mut receiver = after.clone_data();
        receiver.invalidate_payloads();
        match fault {
            "owner-pointer" => receiver.order = Arc::new(receiver.order.as_ref().clone()),
            "metadata-pointer" => receiver.meta = Arc::new(receiver.meta.as_ref().clone()),
            "missing" => donor.invalidate_payloads(),
            _ => {
                let (values, hashes) = donor.payload_cache.take().unwrap();
                let mut values = values.as_ref().clone();
                let mut hashes = hashes;
                match fault {
                    "value" => values[0]["state"]["foreign"] = json!(true),
                    "hash" => hashes[0] = "f".repeat(64),
                    _ => {
                        values.pop();
                    }
                }
                donor.payload_cache.set((Arc::new(values), hashes)).unwrap();
            }
        }
        assert!(!receiver.reuse_typed_payloads(&prepared, &donor), "{fault}");
        assert!(receiver.payload_cache.get().is_none(), "{fault}");
        assert_eq!(
            receiver.payloads().unwrap().as_ref(),
            &original_images(&receiver)
        );
    }
    let mut receiver = after.clone_data();
    receiver.invalidate_payloads();
    assert!(receiver.reuse_typed_payloads(&prepared, after));
    assert!(Arc::ptr_eq(
        &receiver.payloads().unwrap(),
        &after.payloads().unwrap()
    ));
}
