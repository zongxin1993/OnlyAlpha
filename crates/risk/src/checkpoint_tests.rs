use super::{CHECKPOINT_ENCODINGS, Manager};
use crate::{Status, digest};
use serde_json::{Value, json};
use std::sync::Arc;

fn config() -> Value {
    json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","generation":"g","runtime_kind":"BACKTEST","admission_limits":{"schema_version":1,"commands":4096,"journal_bytes":8388608,"checkpoint_bytes":33554432,"reservations":1024},"currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"clusters":{"c":{"schema_version":1,"revision":"revision","instruments":["BTCUSDT.BINANCE"],"rules":[]}}})
}

fn kill(n: u64, active: bool) -> Value {
    json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","generation":"g","cluster":"c","command_id":format!("kill-{n}"),"causal":"a".repeat(64),"time":n,"runtime_sequence":n,"op":"KILL","payload":{"schema_version":1,"scope":"RUNTIME","active":active}})
}

fn assert_original_encoding(manager: &Manager) {
    // This is the unchanged encoder expression from before representation reuse.
    let expected = serde_json::to_vec(&json!({
        "schema_version": 1,
        "config": manager.config,
        "journal": manager.journal,
        "state": manager.state()
    }))
    .unwrap();
    let (record, fingerprint) = manager.checkpoint_record().unwrap();
    assert_eq!(serde_json::to_vec(record.as_ref()).unwrap(), expected);
    assert_eq!(fingerprint, digest(&expected));
    assert_eq!(manager.checkpoint().unwrap(), (expected, fingerprint));
}

#[test]
fn cold_and_warm_records_reuse_one_exact_encoding() {
    CHECKPOINT_ENCODINGS.with(|n| n.set(0));
    let mut manager = Manager::new(config()).unwrap();
    assert!(manager.checkpoint_cache.get().is_none());
    assert_original_encoding(&manager);
    let (first, _) = manager.checkpoint_record().unwrap();
    for _ in 0..3 {
        assert_original_encoding(&manager);
        assert!(Arc::ptr_eq(&first, &manager.checkpoint_record().unwrap().0));
    }
    CHECKPOINT_ENCODINGS.with(|n| assert_eq!(n.get(), 1));

    manager.apply(&kill(1, true)).unwrap();
    assert!(manager.checkpoint_cache.get().is_none());
    assert_original_encoding(&manager);
    assert!(!Arc::ptr_eq(&first, &manager.checkpoint_record().unwrap().0));
    CHECKPOINT_ENCODINGS.with(|n| assert_eq!(n.get(), 2));
}

#[test]
fn cloned_owners_and_detached_records_do_not_share_mutations() {
    let mut manager = Manager::new(config()).unwrap();
    manager.apply(&kill(1, true)).unwrap();
    let (original, fingerprint) = manager.checkpoint_record().unwrap();
    let mut other = manager.clone();
    assert!(Arc::ptr_eq(&original, &other.checkpoint_record().unwrap().0));

    let mut detached = Arc::clone(&original);
    Arc::make_mut(&mut detached)["state"]["sequence"] = json!(999);
    assert_eq!(manager.checkpoint_record().unwrap().1, fingerprint);
    assert_eq!(original["state"]["sequence"], 1);

    other.apply(&kill(2, false)).unwrap();
    assert_eq!(manager.checkpoint_record().unwrap().0, original);
    assert_eq!(manager.state()["sequence"], 1);
    assert_eq!(other.state()["sequence"], 2);
    assert_original_encoding(&other);
    manager.apply(&kill(3, false)).unwrap();
    assert_eq!(other.state()["sequence"], 2);
    assert_original_encoding(&manager);
}

#[test]
fn rejected_duplicate_and_restore_paths_preserve_exact_owner_state() {
    let mut manager = Manager::new(config()).unwrap();
    let command = kill(1, true);
    manager.apply(&command).unwrap();
    let (original, _) = manager.checkpoint_record().unwrap();
    let checkpoint = manager.checkpoint().unwrap();
    assert_eq!(manager.apply(&command).unwrap().status, Status::Duplicate);
    assert!(Arc::ptr_eq(&original, &manager.checkpoint_record().unwrap().0));

    let mut conflicting = command;
    conflicting["payload"]["active"] = json!(false);
    assert!(manager.apply(&conflicting).is_err());
    let mut invalid_candidate = kill(2, false);
    invalid_candidate["payload"]["scope"] = json!("FOREIGN");
    assert!(manager.apply(&invalid_candidate).is_err());
    assert!(Arc::ptr_eq(&original, &manager.checkpoint_record().unwrap().0));

    let mut corrupt = original.as_ref().clone();
    corrupt["state"]["sequence"] = json!(999);
    let bytes = serde_json::to_vec(&corrupt).unwrap();
    assert!(manager.restore(&bytes, &digest(&bytes)).is_err());
    assert!(manager.restore(&checkpoint.0, &"f".repeat(64)).is_err());
    assert!(Arc::ptr_eq(&original, &manager.checkpoint_record().unwrap().0));

    let mut restored = Manager::new(config()).unwrap();
    restored.restore(&checkpoint.0, &checkpoint.1).unwrap();
    assert_eq!(restored.checkpoint().unwrap(), checkpoint);
    assert_original_encoding(&restored);
    restored.apply(&kill(2, false)).unwrap();
    let updated = restored.checkpoint().unwrap();
    manager.restore(&updated.0, &updated.1).unwrap();
    assert_eq!(manager.checkpoint().unwrap(), updated);
    assert_original_encoding(&manager);
}
