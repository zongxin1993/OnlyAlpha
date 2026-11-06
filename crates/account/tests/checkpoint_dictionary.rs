use onlyalpha_account::{Manager, Status, digest};
use onlyalpha_domain::time::OnlyTimestamp;
use serde_json::{Value, json};

const BOUND: usize = 16 * 1024 * 1024;
fn setup() -> (Value, onlyalpha_position::Manager) {
    let position = json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","gateway":"g","generation":"a".repeat(64),"currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"clusters":["c"],"instruments":[{"schema_version":1,"id":"BTCUSDT.BINANCE","price_precision":2,"quantity_precision":0,"multiplier":"1"}]});
    let account = json!({"schema_version":2,"engine":"e","runtime":"r","account":"a","gateway":"g","generation":"a".repeat(64),"currency":position["currency"],"account_type":"CASH","initial_cash":"100.00","position_configuration":onlyalpha_position::digest(position.to_string().as_bytes())});
    (account, onlyalpha_position::Manager::new(position).unwrap())
}
fn command(n: u64, op: &str, payload: Value) -> Value {
    json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","gateway":"g","generation":"a".repeat(64),"command_id":format!("command-{n}"),"cause":"b".repeat(64),"time":n,"op":op,"payload":payload})
}
fn broker(position: &mut onlyalpha_position::Manager, n: u64) {
    position.apply(&command(n,"BROKER",json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE","snapshot_id":format!("broker-{n}"),"sequence":n,"position_side":"FLAT","total":"0","settled":"0","unsettled":"0","available":"0","frozen":"0","average":null,"quality":"VERIFIED"}))).unwrap();
}
fn valuation(
    position: &onlyalpha_position::Manager,
    n: u64,
) -> (Value, onlyalpha_position::ValuationEffect) {
    let identity = format!("估值-\\\"-{n}");
    let intent = json!({"schema_version":1,"valuation":identity,"version":n,"economic_version":0,"position_evidence":position.checkpoint().unwrap().1,"time":n,"marks":[]});
    let mut input = command(n, "VALUATION", Value::Null);
    input["command_id"] = json!(identity);
    (input, position.value(&intent).unwrap())
}
fn capture(account: &Manager) -> Value {
    serde_json::from_slice(&account.checkpoint().unwrap().0).unwrap()
}
// Independent test projection: compare literal full original commands with the
// unchanged schema4 owner, rather than comparing two codec-produced hashes.
fn expand(compact: &Value) -> Value {
    let mut original = compact.clone();
    original["schema_version"] = json!(4);
    let positions = original
        .as_object_mut()
        .unwrap()
        .remove("positions")
        .unwrap();
    for entry in original["journal"].as_array_mut().unwrap() {
        if entry["op"] == "VALUATION" {
            let reference = entry["payload"]
                .as_object_mut()
                .unwrap()
                .remove("position_ref")
                .unwrap();
            entry["payload"]["position"] = positions[reference.as_str().unwrap()].clone();
        }
    }
    original
}
fn histories() -> (Manager, Manager, onlyalpha_position::Manager) {
    let (config, mut position) = setup();
    let mut original = Manager::new(config.clone()).unwrap();
    let mut compact = Manager::new_checkpoint5(config).unwrap();
    for n in 1..=8 {
        if n == 5 {
            broker(&mut position, n);
        }
        let (input, effect) = valuation(&position, 10 + n);
        assert_eq!(
            original.apply_valuation(&input, &effect).unwrap().status,
            Status::Applied
        );
        assert_eq!(
            compact.apply_valuation(&input, &effect).unwrap().status,
            Status::Applied
        );
    }
    (original, compact, position)
}

#[test]
fn checkpoint5_deduplicates_only_source_bytes_and_restores_full_original_commands() {
    let (original, compact, _) = histories();
    let old = capture(&original);
    let encoded = capture(&compact);
    assert_eq!(old["schema_version"], 4);
    assert_eq!(encoded["schema_version"], 5);
    assert_eq!(encoded["positions"].as_object().unwrap().len(), 2);
    assert_eq!(encoded["journal"].as_array().unwrap().len(), 8);
    for entry in encoded["journal"].as_array().unwrap() {
        assert!(entry["payload"].get("position").is_none());
        assert_eq!(
            entry["payload"]["position_ref"],
            entry["payload"]["intent"]["position_evidence"]
        );
    }
    assert_eq!(expand(&encoded), old);
    assert_eq!(compact.state(), original.state());
    assert_eq!(compact.snapshot()["cash"], "100.00");
    assert_eq!(compact.snapshot()["equity"], "100.00");
    assert_eq!(compact.snapshot()["valuation_version"], 18);
    assert!(compact.checkpoint().unwrap().0.len() < original.checkpoint().unwrap().0.len());
    let (bytes, hash) = compact.checkpoint().unwrap();
    let (config, _) = setup();
    let mut restored = Manager::new_checkpoint5(config).unwrap();
    restored.restore(&bytes, &hash).unwrap();
    assert_eq!(restored.checkpoint().unwrap(), (bytes, hash));
    assert_eq!(restored.state(), original.state());
    let at = OnlyTimestamp::from_unix_nanos(0.into());
    let a = original.performance(&at).unwrap().record();
    let b = restored.performance(&at).unwrap().record();
    assert_eq!(a["timeline"], b["timeline"]);
    assert_eq!(a["summary"], b["summary"]);
    assert_eq!(b["account_checkpoint"], restored.checkpoint().unwrap().1);
}

#[test]
fn checkpoint4_keeps_exact_bytes_and_formats_cannot_be_silently_switched() {
    let (original, compact, _) = histories();
    let (config, _) = setup();
    let old = original.checkpoint().unwrap();
    let new = compact.checkpoint().unwrap();
    let mut legacy = Manager::new(config.clone()).unwrap();
    legacy.restore(&old.0, &old.1).unwrap();
    assert_eq!(legacy.checkpoint().unwrap(), old);
    let before = legacy.checkpoint().unwrap();
    assert!(legacy.restore(&new.0, &new.1).is_err());
    assert_eq!(legacy.checkpoint().unwrap(), before);
    let mut fresh = Manager::new_checkpoint5(config).unwrap();
    let before = fresh.checkpoint().unwrap();
    assert!(fresh.restore(&old.0, &old.1).is_err());
    assert_eq!(fresh.checkpoint().unwrap(), before);
    fresh.restore(&new.0, &new.1).unwrap();
    assert_eq!(fresh.checkpoint().unwrap(), new);
}

#[test]
fn rehashed_checkpoint5_dictionary_and_derived_state_faults_are_atomic() {
    let (_, compact, _) = histories();
    let valid = capture(&compact);
    let reference = valid["journal"][0]["payload"]["position_ref"]
        .as_str()
        .unwrap()
        .to_owned();
    for fault in 0..12 {
        let mut damaged = valid.clone();
        match fault {
            0 => {
                damaged["positions"]
                    .as_object_mut()
                    .unwrap()
                    .remove(&reference);
            }
            1 => {
                damaged["positions"]["c".repeat(64)] = damaged["positions"][&reference].clone();
            }
            2 => damaged["positions"][&reference]["state"]["sequence"] = json!(999),
            3 => damaged["journal"][0]["payload"]["position_ref"] = json!("f".repeat(64)),
            4 => {
                damaged["journal"][0]["payload"]["intent"]["position_evidence"] =
                    json!("f".repeat(64))
            }
            5 => {
                damaged["journal"][0]["payload"]["position"] =
                    damaged["positions"][&reference].clone()
            }
            6 => {
                damaged["journal"][0]["payload"]
                    .as_object_mut()
                    .unwrap()
                    .remove("position_ref");
            }
            7 => damaged["journal"][0]["payload"]["extra"] = json!(true),
            8 => damaged["schema_version"] = json!(6),
            9 => damaged["state"]["snapshot"]["equity"] = json!("999.00"),
            10 => damaged["journal"][0]["payload"]["intent"]["economic_version"] = json!(999),
            _ => {
                // Correct dictionary hash alone cannot validate a false full
                // Position source. The original owning restore must run.
                let mut source = damaged["positions"]
                    .as_object_mut()
                    .unwrap()
                    .remove(&reference)
                    .unwrap();
                source["state"]["sequence"] = json!(999);
                let changed =
                    onlyalpha_position::digest(serde_json::to_vec(&source).unwrap().as_slice());
                damaged["positions"][&changed] = source;
                for entry in damaged["journal"].as_array_mut().unwrap() {
                    if entry["payload"]["position_ref"] == reference {
                        entry["payload"]["position_ref"] = json!(changed);
                        entry["payload"]["intent"]["position_evidence"] = json!(changed);
                    }
                }
            }
        }
        let bytes = serde_json::to_vec(&damaged).unwrap();
        let mut destination = compact.clone();
        let before = destination.checkpoint().unwrap();
        assert!(
            destination.restore(&bytes, &digest(&bytes)).is_err(),
            "fault {fault}"
        );
        assert_eq!(
            destination.checkpoint().unwrap(),
            before,
            "fault {fault} cannot partially install"
        );
    }
}

#[test]
fn checkpoint5_clones_keep_format_and_both_mutation_directions_are_independent() {
    let (_, mut original, position) = histories();
    let before = original.checkpoint().unwrap();
    let mut fork = original.clone();
    let (input, effect) = valuation(&position, 19);
    fork.apply_valuation(&input, &effect).unwrap();
    assert_eq!(original.checkpoint().unwrap(), before);
    let fork_before = fork.checkpoint().unwrap();
    let (input, effect) = valuation(&position, 20);
    original.apply_valuation(&input, &effect).unwrap();
    assert_eq!(fork.checkpoint().unwrap(), fork_before);
    assert_eq!(capture(&fork)["schema_version"], 5);
    assert_eq!(capture(&original)["schema_version"], 5);
    assert_ne!(original.checkpoint().unwrap(), fork.checkpoint().unwrap());
}

#[test]
fn checkpoint5_rejects_small_wire_with_over_budget_expansion_before_replay() {
    let (config, mut position) = setup();
    for n in 1..=64 {
        broker(&mut position, n);
    }
    let mut account = Manager::new_checkpoint5(config).unwrap();
    let (input, effect) = valuation(&position, 100);
    account.apply_valuation(&input, &effect).unwrap();
    let mut encoded = capture(&account);
    let full = expand(&encoded)["journal"][0].clone();
    let compact = encoded["journal"][0].clone();
    let count = BOUND / serde_json::to_vec(&full).unwrap().len() + 2;
    encoded["journal"] = Value::Array(
        (0..count)
            .map(|i| {
                let mut entry = compact.clone();
                entry["command_id"] = json!(format!("expansion-{i}"));
                entry["payload"]["intent"]["valuation"] = json!(format!("expansion-{i}"));
                entry["payload"]["intent"]["version"] = json!(101 + i);
                entry["payload"]["intent"]["time"] = json!(101 + i);
                entry["time"] = json!(101 + i);
                entry
            })
            .collect(),
    );
    let bytes = serde_json::to_vec(&encoded).unwrap();
    assert!(bytes.len() < BOUND);
    assert!(serde_json::to_vec(&expand(&encoded)).unwrap().len() > BOUND);
    let before = account.checkpoint().unwrap();
    assert_eq!(
        account.restore(&bytes, &digest(&bytes)).unwrap_err().0,
        "ACCOUNT_CHECKPOINT_BOUND"
    );
    assert_eq!(account.checkpoint().unwrap(), before);
}

#[test]
fn checkpoint5_weighted_limit_refuses_the_actual_candidate_before_mutation() {
    let (config, mut position) = setup();
    for n in 1..=64 {
        broker(&mut position, n);
    }
    let mut account = Manager::new_checkpoint5(config).unwrap();
    for n in 100..=2000 {
        let before = account.checkpoint().unwrap();
        let (input, effect) = valuation(&position, n);
        match account.apply_valuation(&input, &effect) {
            Ok(outcome) => assert_eq!(outcome.status, Status::Applied),
            Err(error) => {
                assert_eq!(error.0, "ACCOUNT_CHECKPOINT_BOUND");
                assert_eq!(account.checkpoint().unwrap(), before);
                // The original schema4 safety path still records and reads
                // this same real history beyond its admission-only limit.
                let original = expand(&capture(&account));
                let data = serde_json::to_vec(&original).unwrap();
                let mut legacy = Manager::new(original["config"].clone()).unwrap();
                legacy.restore(&data, &digest(&data)).unwrap();
                legacy.apply_valuation(&input, &effect).unwrap();
                let oversized = legacy.checkpoint().unwrap();
                assert!(oversized.0.len() > BOUND);
                let mut historical = Manager::new(original["config"].clone()).unwrap();
                historical.restore(&oversized.0, &oversized.1).unwrap();
                assert_eq!(historical.checkpoint().unwrap(), oversized);
                return;
            }
        }
    }
    panic!("the weighted limit never rejected the full original history");
}
