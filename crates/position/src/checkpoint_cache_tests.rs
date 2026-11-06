//! Exact owner data reuse; no Runtime/source or admission assertions.
use super::*;

fn config() -> Value {
    json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account",
        "gateway":"gateway","generation":"generation",
        "currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},
        "clusters":["a","b"],"instruments":[{"schema_version":1,"id":"BTCUSDT.BINANCE",
            "price_precision":2,"quantity_precision":0,"multiplier":"1"}]})
}
fn command(id: &str, op: &str, at: u64, payload: Value) -> Value {
    json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account",
        "gateway":"gateway","generation":"generation","command_id":id,"cause":"a".repeat(64),
        "time":at,"op":op,"payload":payload})
}
fn trade(id: &str, at: u64) -> Value {
    command(
        id,
        "TRADE",
        at,
        json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE",
        "cluster":"a","order":"order-a","trade":id,"venue_trade":format!("venue-{id}"),
        "execution":format!("execution-{id}"),"sequence":at,"side":"BUY","position_side":"LONG",
        "position_mode":"NETTING","price":"10.00","quantity":"2","fee":"0.00",
        "bucket":"SETTLED","terminal_fill":false}),
    )
}
fn reserve(id: &str, quantity: &str, at: u64) -> Value {
    command(
        id,
        "RESERVE",
        at,
        json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE",
        "cluster":"a","order":"order-a","quantity":quantity}),
    )
}
fn original_checkpoint(owner: &Manager) -> (Vec<u8>, String) {
    // Independent literal original encoder, not checkpoint_record's projection.
    let bytes = serde_json::to_vec(&json!({"schema_version":2,"config":owner.config,
        "journal":owner.state.journal,"state":owner.state()}))
    .unwrap();
    let fingerprint = digest(&bytes);
    (bytes, fingerprint)
}
fn assert_exact(owner: &Manager) -> Arc<Value> {
    let original = original_checkpoint(owner);
    let (record, fingerprint) = owner.checkpoint_record().unwrap();
    assert_eq!(serde_json::to_vec(record.as_ref()).unwrap(), original.0);
    assert_eq!(fingerprint, original.1);
    assert_eq!(owner.checkpoint().unwrap(), original);
    record
}

#[test]
fn checkpoint_record_keeps_original_bytes_and_warm_reads_do_not_reencode() {
    let mut owner = Manager::new(config()).unwrap();
    assert_exact(&owner);
    owner.apply(&trade("open", 1)).unwrap();
    owner.apply(&reserve("reserve", "1", 2)).unwrap();
    CHECKPOINT_ENCODINGS.with(|count| count.set(0));
    let original = assert_exact(&owner);
    assert_eq!(CHECKPOINT_ENCODINGS.with(std::cell::Cell::get), 1);
    for _ in 0..4 {
        assert!(Arc::ptr_eq(&original, &assert_exact(&owner)));
    }
    assert_eq!(CHECKPOINT_ENCODINGS.with(std::cell::Cell::get), 1);
    let mut detached = Arc::clone(&original);
    Arc::make_mut(&mut detached)["state"] = Value::Null;
    assert!(!original["state"].is_null());
    assert!(Arc::ptr_eq(&original, &assert_exact(&owner)));
    let mut bytes = owner.checkpoint().unwrap().0;
    bytes.clear();
    assert!(!owner.checkpoint().unwrap().0.is_empty());
}

#[test]
fn clone_shares_only_immutable_representation_and_mutation_invalidates_its_own_cache() {
    let mut owner = Manager::new(config()).unwrap();
    owner.apply(&trade("open", 1)).unwrap();
    let original = assert_exact(&owner);
    let mut fork = owner.clone();
    assert!(Arc::ptr_eq(&original, &assert_exact(&fork)));
    fork.apply(&reserve("reserve", "1", 2)).unwrap();
    let changed = assert_exact(&fork);
    assert!(!Arc::ptr_eq(&original, &changed));
    assert_ne!(original, changed);
    assert!(Arc::ptr_eq(&original, &assert_exact(&owner)));
    let mut cold_clone = Manager::new(config()).unwrap();
    cold_clone.apply(&trade("cold", 3)).unwrap();
    assert!(cold_clone.checkpoint_cache.get().is_none());
    let copy = cold_clone.clone();
    assert_exact(&cold_clone);
    assert!(copy.checkpoint_cache.get().is_none());
    assert_eq!(copy.checkpoint().unwrap(), cold_clone.checkpoint().unwrap());
}

#[test]
fn refusal_and_exact_duplicate_preserve_cache_but_new_duplicate_occurrence_changes_journal() {
    let mut owner = Manager::new(config()).unwrap();
    let opening = trade("open", 1);
    owner.apply(&opening).unwrap();
    let original = assert_exact(&owner);
    assert!(owner.apply(&reserve("retry", "3", 2)).is_err());
    assert!(Arc::ptr_eq(&original, &assert_exact(&owner)));
    assert_eq!(owner.apply(&opening).unwrap().status, Status::Duplicate);
    assert!(Arc::ptr_eq(&original, &assert_exact(&owner)));
    let mut conflicting = opening.clone();
    conflicting["payload"]["price"] = json!("11.00");
    assert_eq!(owner.apply(&conflicting).unwrap().status, Status::Conflict);
    assert!(Arc::ptr_eq(&original, &assert_exact(&owner)));
    // The failed attempt did not consume this identity; the valid retry commits.
    assert_eq!(
        owner.apply(&reserve("retry", "1", 2)).unwrap().status,
        Status::Applied
    );
    let reserved = assert_exact(&owner);
    assert!(!Arc::ptr_eq(&original, &reserved));
    assert_eq!(
        owner
            .apply(&reserve("second-occurrence", "1", 3))
            .unwrap()
            .status,
        Status::Duplicate
    );
    let repeated = assert_exact(&owner);
    assert!(!Arc::ptr_eq(&reserved, &repeated));
    assert_eq!(
        repeated["journal"].as_array().unwrap().len(),
        reserved["journal"].as_array().unwrap().len() + 1
    );
    assert_eq!(repeated["state"]["now"], reserved["state"]["now"]);
}

#[test]
fn successful_stale_observation_invalidates_the_retained_representation() {
    let mut owner = Manager::new(config()).unwrap();
    owner.apply(&trade("current", 10)).unwrap();
    let original = assert_exact(&owner);
    assert_eq!(
        owner.apply(&trade("stale", 1)).unwrap().status,
        Status::Stale
    );
    let changed = assert_exact(&owner);
    assert!(!Arc::ptr_eq(&original, &changed));
    assert_ne!(original, changed);
}

#[test]
fn restore_replays_exact_history_and_failed_candidates_cannot_replace_warm_receiver() {
    let mut source = Manager::new(config()).unwrap();
    source.apply(&trade("open", 1)).unwrap();
    source.apply(&reserve("reserve", "1", 2)).unwrap();
    let expected = assert_exact(&source);
    let (bytes, fingerprint) = source.checkpoint().unwrap();
    let mut receiver = Manager::new(config()).unwrap();
    let empty = assert_exact(&receiver);
    assert!(receiver.restore(&bytes, &"0".repeat(64)).is_err());
    assert!(Arc::ptr_eq(&empty, &assert_exact(&receiver)));
    receiver.restore(&bytes, &fingerprint).unwrap();
    let restored = assert_exact(&receiver);
    assert_eq!(restored, expected);
    assert!(!Arc::ptr_eq(&restored, &expected));
    for fault in ["state", "context", "journal", "canonical"] {
        let mut corrupt = expected.as_ref().clone();
        match fault {
            "state" => corrupt["state"]["sequence"] = json!(999),
            "context" => corrupt["config"]["runtime"] = json!("foreign"),
            "journal" => corrupt["journal"][0]["payload"]["quantity"] = json!("999"),
            _ => (),
        }
        let mut encoded = serde_json::to_vec(&corrupt).unwrap();
        if fault == "canonical" {
            encoded.push(b' ');
        }
        assert!(
            receiver.restore(&encoded, &digest(&encoded)).is_err(),
            "{fault}"
        );
        assert!(Arc::ptr_eq(&restored, &assert_exact(&receiver)), "{fault}");
    }
    // Preserve the existing API's ability to replace an owner via full replay.
    let fresh = Manager::new(config()).unwrap();
    let genesis = fresh.checkpoint().unwrap();
    receiver.restore(&genesis.0, &genesis.1).unwrap();
    assert_eq!(receiver.checkpoint().unwrap(), genesis);
    assert_eq!(assert_exact(&source), expected);
}

#[test]
fn checkpoint_memo_keeps_owner_send_and_sync() {
    fn shared<T: Send + Sync>() {}
    shared::<Manager>();
}
