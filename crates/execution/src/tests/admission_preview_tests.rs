use super::*;
use crate::{
    coordinate,
    support::{Harness, config, open},
};

fn cold(c: &Value, checkpoint: &Value, input: &Value) -> Result<Option<Error>, Error> {
    Components::admission_rejection(c, checkpoint, input)
}

#[test]
fn same_complete_checkpoint_is_restored_once_and_each_input_is_checked() {
    let configuration = config();
    let checkpoint = Components::new(configuration.clone())
        .unwrap()
        .checkpoint()
        .unwrap();
    let mut preview = AdmissionPreview::default();
    for n in 1..=4 {
        let mut input = open(n, "BUY");
        input["input_id"] = json!(format!("preview-{n}"));
        input["source_ref"] = json!(format!("preview-source-{n}"));
        assert_eq!(
            preview.check(&configuration, &checkpoint, &input),
            cold(&configuration, &checkpoint, &input)
        );
        assert_eq!(
            preview.baseline.as_ref().unwrap().1.checkpoint().unwrap(),
            checkpoint
        );
    }
    assert_eq!(preview.restores, 1);
    for field in [
        "engine",
        "runtime",
        "account",
        "gateway",
        "generation",
        "runtime_kind",
        "revision",
    ] {
        let mut input = open(1, "BUY");
        input[field] = json!("foreign");
        assert_eq!(
            preview.check(&configuration, &checkpoint, &input),
            cold(&configuration, &checkpoint, &input)
        );
        assert!(preview.check(&configuration, &checkpoint, &input).is_err());
    }
    let mut malformed = open(1, "BUY");
    malformed["payload"]["request"]["quantity"]["value"] = json!({"invalid":true});
    assert_eq!(
        preview.check(&configuration, &checkpoint, &malformed),
        cold(&configuration, &checkpoint, &malformed)
    );
    assert!(
        preview
            .check(&configuration, &checkpoint, &malformed)
            .is_err()
    );
    assert_eq!(preview.restores, 1);
}

fn head(input_id: &str) -> (Value, Value) {
    let configuration = config();
    let mut h = Harness::new(configuration.clone()).unwrap();
    let mut input = open(1, "BUY");
    input["input_id"] = json!(input_id);
    input["source_ref"] = json!(format!("source-{input_id}"));
    let p = h.prepare(&input).unwrap();
    coordinate(&mut h.store, &mut h.components, &p).unwrap();
    (configuration, h.components.checkpoint().unwrap())
}

#[test]
fn same_sequence_different_history_and_failed_restore_cannot_reuse_old_baseline() {
    let (configuration, first) = head("first");
    let (_, second) = head("second");
    assert_eq!(first["sequence"], second["sequence"]);
    assert_ne!(first, second);
    let input = open(2, "BUY");
    let mut preview = AdmissionPreview::default();
    assert_eq!(
        preview.check(&configuration, &first, &input),
        cold(&configuration, &first, &input)
    );
    assert_eq!(
        preview.check(&configuration, &second, &input),
        cold(&configuration, &second, &input)
    );
    assert_eq!(preview.restores, 2);
    let mut corrupt = second.clone();
    corrupt["components"][2]["state"]["snapshot"]["cash"] = json!("999999.00");
    assert!(preview.check(&configuration, &corrupt, &input).is_err());
    assert!(
        preview.baseline.is_none(),
        "failed changed history must not retain the old source"
    );
    assert_eq!(
        preview.check(&configuration, &second, &input),
        cold(&configuration, &second, &input)
    );
    assert_eq!(preview.restores, 3);
}

#[test]
fn warm_preview_keeps_stale_alias_pending_and_non_admit_failures() {
    let (configuration, checkpoint) = head("original");
    let mut preview = AdmissionPreview::default();
    let valid = open(2, "BUY");
    assert_eq!(
        preview.check(&configuration, &checkpoint, &valid),
        cold(&configuration, &checkpoint, &valid)
    );
    for kind in [
        "stale",
        "input-alias",
        "source-alias",
        "not-admit",
        "pending",
        "missing-owner",
    ] {
        let mut input = valid.clone();
        let mut cp = checkpoint.clone();
        match kind {
            "stale" => input["runtime_sequence"] = json!(1),
            "input-alias" => input["input_id"] = json!("original"),
            "source-alias" => input["source_ref"] = json!("source-original"),
            "not-admit" => input["op"] = json!("FILL"),
            "pending" => cp["pending"] = json!(["unready", 0]),
            _ => {
                cp["components"].as_array_mut().unwrap().pop();
            }
        }
        let expected = cold(&configuration, &cp, &input);
        assert!(expected.is_err(), "{kind} must fail closed");
        assert_eq!(
            preview.check(&configuration, &cp, &input),
            expected,
            "{kind}"
        );
    }
}

#[test]
fn changed_checkpoint_drops_baseline_even_when_new_input_scope_is_invalid() {
    let configuration = config();
    let checkpoint = Components::new(configuration.clone())
        .unwrap()
        .checkpoint()
        .unwrap();
    let input = open(1, "BUY");
    let mut preview = AdmissionPreview::default();
    preview.check(&configuration, &checkpoint, &input).unwrap();
    assert!(preview.baseline.is_some());
    let mut changed = checkpoint.clone();
    changed["sequence"] = json!(1);
    let mut foreign = input;
    foreign["generation"] = json!("foreign");
    assert!(preview.check(&configuration, &changed, &foreign).is_err());
    assert!(preview.baseline.is_none());
}

#[test]
fn checkpoint5_and_independent_contexts_keep_their_own_cold_restore() {
    let mut configuration = config();
    configuration["schema_version"] = json!(2);
    configuration["account_checkpoint_version"] = json!(5);
    let checkpoint = Components::new(configuration.clone())
        .unwrap()
        .checkpoint()
        .unwrap();
    assert_eq!(checkpoint["components"][2]["schema_version"], 5);
    let input = open(1, "BUY");
    let mut first = AdmissionPreview::default();
    let mut second = AdmissionPreview::default();
    for _ in 0..2 {
        assert_eq!(
            first.check(&configuration, &checkpoint, &input),
            cold(&configuration, &checkpoint, &input)
        );
        assert_eq!(
            second.check(&configuration, &checkpoint, &input),
            cold(&configuration, &checkpoint, &input)
        );
    }
    assert_eq!(first.restores, 1);
    assert_eq!(second.restores, 1);
    let mut foreign_config = configuration.clone();
    foreign_config["generation"] = json!("foreign");
    assert!(first.check(&foreign_config, &checkpoint, &input).is_err());
    assert!(first.baseline.is_none());
    assert!(second.baseline.is_some());
}
