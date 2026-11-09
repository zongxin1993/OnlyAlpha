//! Observation can remove authority, never manufacture a planner origin.
use super::*;
use crate::support;
use crate::{Record, coordinate};
use support::{Harness, config, open};
// Select only the explicit authority-removing observation, never a flag copy.
fn observe(record: &Record, ready: bool, delivered: bool) -> Result<Record, Error> {
    record.observation_snapshot(ready, delivered)
}
#[test]
fn observation_reuses_immutable_body_without_another_owned_copy_or_cold_validation() {
    let mut history = Harness::new(config()).unwrap();
    let planned = history.prepare(&open(1, "BUY")).unwrap();
    history.commit_only(&planned).unwrap();
    let original = history.store.rows[0].clone();
    assert!(
        original.prepared().is_planned(),
        "fixture must prove loss of a genuine planner-origin marker"
    );
    let original_wire = original.record();
    let bytes = original.prepared().encode().unwrap();
    let fingerprint = original.prepared().input_fingerprint().to_owned();
    let decoded = Record::decode(&original_wire).unwrap();
    for source in [original.clone(), decoded] {
        for (ready, delivered) in [(false, false), (true, false), (true, true)] {
            PREPARED_OWNED_BODY_BYTES.with(|count| count.set(0));
            PREPARED_VALIDATIONS.with(|count| count.set(0));
            let observed = observe(&source, ready, delivered).unwrap();
            let copies = PREPARED_OWNED_BODY_BYTES.with(std::cell::Cell::get);
            let validations = PREPARED_VALIDATIONS.with(std::cell::Cell::get);
            assert_eq!(
                (validations, copies),
                (0, 0),
                "observing existing canonical data repeated its full body copy/validation"
            );
            let mut expected = original_wire.clone();
            expected["ready"] = json!(ready);
            expected["delivered"] = json!(delivered);
            assert_eq!(observed.record(), expected);
            assert_eq!(observed.prepared().encode().unwrap(), bytes);
            assert_eq!(observed.prepared().input_fingerprint(), fingerprint);
            assert_eq!(observed.prepared(), &planned);
            assert!(!observed.prepared().is_planned());
            assert!(observed.prepared().typed_after().is_none());
            for passive in [
                observed.clone(),
                Record::decode(&observed.record()).unwrap(),
                observed.with_observed_flags(true, false).unwrap(),
            ] {
                assert!(!passive.prepared().is_planned());
                assert!(passive.prepared().typed_after().is_none());
                let mut foreign = Harness::new(config()).unwrap();
                let before = foreign.checkpoint().unwrap();
                assert!(
                    coordinate(
                        &mut foreign.store,
                        &mut foreign.components,
                        passive.prepared()
                    )
                    .is_err(),
                    "an observation or passive copy became a fresh commit grant"
                );
                assert!(foreign.store.rows.is_empty());
                assert_eq!(foreign.checkpoint().unwrap(), before);
            }
            assert_eq!(original.record(), original_wire);
            assert!(original.prepared().is_planned());
        }
        let retained = source.record();
        assert!(observe(&source, false, true).is_err());
        assert_eq!(source.record(), retained);
    }
}
#[test]
fn original_cold_record_decoder_keeps_complete_prepared_and_flag_validation() {
    let mut history = Harness::new(config()).unwrap();
    let planned = history.prepare(&open(1, "BUY")).unwrap();
    history.commit_only(&planned).unwrap();
    let original = history.store.rows[0].record();
    for fault in ["input", "projection", "event", "delivered", "type", "extra"] {
        let mut changed = original.clone();
        match fault {
            "input" => changed["prepared"]["input"]["account"] = json!("foreign"),
            "projection" => changed["prepared"]["projections"][2]["result"]["state"] = json!({}),
            "event" => changed["prepared"]["events"] = json!([]),
            "delivered" => changed["delivered"] = json!(true),
            "type" => changed["ready"] = json!("true"),
            _ => changed["unexpected"] = json!(true),
        }
        assert!(
            Record::decode(&changed).is_err(),
            "cold decoder accepted {fault}"
        );
        assert_eq!(history.store.rows[0].record(), original);
    }
    PREPARED_VALIDATIONS.with(|count| count.set(0));
    let decoded = Record::decode(&original).unwrap();
    assert_eq!(
        PREPARED_VALIDATIONS.with(std::cell::Cell::get),
        1,
        "transport still executes the original full canonical verifier"
    );
    assert_eq!(decoded.record(), original);
    assert!(!decoded.prepared().is_planned());
}
