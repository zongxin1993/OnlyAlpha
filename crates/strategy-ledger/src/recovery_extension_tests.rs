//! Exact-prefix component replay, without a retained Store/source proof.
use super::*;
use crate::manager::RECOVERY_COMMAND_APPLICATIONS;

fn configuration() -> Value {
    json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","generation":"g","runtime_kind":"BACKTEST","currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"account_initial_cash":"1000.00","capitals":{"c1":"1000.00"}})
}
fn command(sequence:u64, foreign:bool) -> Value {
    let identity=if foreign && sequence==2 {"another-flow-2".into()} else {format!("flow-{sequence}")};
    json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","generation":"g","cluster":"c1","command_id":identity,"cause":"a".repeat(64),"time":0,"runtime_sequence":sequence,"trading_day":"2026-10-19","day_index":1,"op":if sequence==1{"ACTIVATE"}else{"CASH_FLOW"},"payload":if sequence==1{json!({"schema_version":1})}else{json!({"schema_version":1,"cashflow":identity,"source_fact":format!("source-{identity}"),"amount":"0.00"})}})
}
fn prefixes(count:u64,foreign:bool)->Vec<(Vec<u8>,String)> {
    let mut manager=Manager::new(configuration()).unwrap();
    (1..=count).map(|sequence|{
        assert_eq!(manager.apply(&command(sequence,foreign)).unwrap().status,Status::Applied);
        manager.checkpoint().unwrap()
    }).collect()
}
// Select only the explicit strict-prefix reader. Ordinary cold restore remains
// independently exercised below and does not acquire extension semantics.
fn extend(manager:&mut Manager,bytes:&[u8],fingerprint:&str)->Result<(),Error> {
    manager.restore_exact_extension(bytes,fingerprint)
}
#[test]
fn exact_prefix_recovery_applies_each_original_command_once() {
    for count in [16_u64,32] {
        let expected=prefixes(count,false);let mut actual=Manager::new(configuration()).unwrap();
        RECOVERY_COMMAND_APPLICATIONS.with(|calls|calls.set(0));
        for checkpoint in &expected {
            extend(&mut actual,&checkpoint.0,&checkpoint.1).unwrap();
            assert_eq!(actual.checkpoint().unwrap(),*checkpoint,"every full retained checkpoint must be identical");
        }
        assert_eq!(RECOVERY_COMMAND_APPLICATIONS.with(std::cell::Cell::get),count,"a forward exact-prefix replay reapplied previously verified original commands");
        assert_eq!(actual.snapshot("c1").unwrap()["cash"],"1000.00");
    }
}
#[test]
fn exact_extension_rejects_divergence_and_every_invalid_suffix_atomically() {
    let history=prefixes(4,false);let foreign=prefixes(4,true);
    for fault in ["shorter","same","foreign-prefix","digest","noncanonical","schema","fields","config","state","receipt","duplicate-receipt","command-bound","sequence","time","unknown-op"] {
        let mut actual=Manager::new(configuration()).unwrap();actual.restore(&history[2].0,&history[2].1).unwrap();let before=actual.checkpoint().unwrap();
        let mut value:Value=serde_json::from_slice(&history[3].0).unwrap();
        match fault {
            "shorter"=>value=serde_json::from_slice(&history[1].0).unwrap(),
            "same"=>value=serde_json::from_slice(&history[2].0).unwrap(),
            "foreign-prefix"=>value=serde_json::from_slice(&foreign[3].0).unwrap(),
            "schema"=>value["schema_version"]=json!(1),
            "fields"=>value["unknown"]=json!(true),
            "config"=>value["config"]["generation"]=json!("foreign-generation"),
            "state"=>value["state"]["timeline"][2]["sequence"]=json!(1),
            "receipt"=>{value["state"]["receipts"].as_object_mut().unwrap().remove("flow-2");},
            "duplicate-receipt"=>{let duplicate=value["journal"][2].clone();value["journal"].as_array_mut().unwrap().push(duplicate);},
            "command-bound"=>{let mut oversized=command(5,false);oversized["command_id"]=json!("x".repeat(65536));value["journal"].as_array_mut().unwrap().push(oversized);},
            "sequence"=>value["journal"][3]["runtime_sequence"]=json!(2),
            "time"=>value["journal"][3]["time"]=json!(-1),
            "unknown-op"=>value["journal"][3]["op"]=json!("UNKNOWN"),
            _=>{},
        }
        let mut bytes=serde_json::to_vec(&value).unwrap();if fault=="noncanonical"{bytes.push(b' ');}
        let fingerprint=if fault=="digest"{"0".repeat(64)}else{digest(&bytes)};
        assert!(extend(&mut actual,&bytes,&fingerprint).is_err(),"invalid extension accepted {fault}");
        assert_eq!(actual.checkpoint().unwrap(),before,"failed suffix changed accepted owner {fault}");
    }
}
#[test]
fn semantic_redelivery_retains_its_new_receipt_without_another_equity_occurrence() {
    let history=prefixes(3,false);let mut producer=Manager::new(configuration()).unwrap();producer.restore(&history[2].0,&history[2].1).unwrap();
    let before=producer.state();let mut redelivery=command(3,false);redelivery["command_id"]=json!("second-receipt");
    assert_eq!(producer.apply(&redelivery).unwrap().status,Status::Duplicate);
    let expected=producer.checkpoint().unwrap();
    assert_eq!(producer.state()["timeline"],before["timeline"]);assert_eq!(producer.snapshot("c1").unwrap()["cash"],"1000.00");
    assert!(producer.state()["receipts"].get("second-receipt").is_some());
    let mut actual=Manager::new(configuration()).unwrap();actual.restore(&history[2].0,&history[2].1).unwrap();
    RECOVERY_COMMAND_APPLICATIONS.with(|calls|calls.set(0));extend(&mut actual,&expected.0,&expected.1).unwrap();
    assert_eq!(RECOVERY_COMMAND_APPLICATIONS.with(std::cell::Cell::get),1);
    assert_eq!(actual.checkpoint().unwrap(),expected);
}
#[test]
fn ordinary_cold_restore_still_accepts_an_arbitrary_original_checkpoint() {
    let history=prefixes(4,false);let mut actual=Manager::new(configuration()).unwrap();
    actual.restore(&history[3].0,&history[3].1).unwrap();assert_eq!(actual.checkpoint().unwrap(),history[3]);
    actual.restore(&history[1].0,&history[1].1).unwrap();assert_eq!(actual.checkpoint().unwrap(),history[1]);
}

#[test]
fn immutable_checkpoint_encoding_is_shared_until_actual_ledger_changes(){
 let mut owner=Manager::new(configuration()).unwrap();owner.apply(&command(1,false)).unwrap();
 let original=owner.checkpoint().unwrap();let mut fork=owner.clone();
 CHECKPOINT_ENCODINGS.with(|n|n.set(0));
 for _ in 0..4{assert_eq!(owner.checkpoint().unwrap(),original);assert_eq!(fork.checkpoint().unwrap(),original);}
 assert_eq!(CHECKPOINT_ENCODINGS.with(std::cell::Cell::get),0,"unchanged Ledger was re-encoded");
 fork.apply(&command(2,false)).unwrap();let changed=fork.checkpoint().unwrap();assert_ne!(changed,original);assert_eq!(owner.checkpoint().unwrap(),original);
 let mut restored=Manager::new(configuration()).unwrap();restored.restore(&changed.0,&changed.1).unwrap();assert_eq!(restored.checkpoint().unwrap(),changed);
 let mut invalid=command(3,false);invalid["op"]=json!("INVALID");assert!(fork.apply(&invalid).is_err());assert_eq!(fork.checkpoint().unwrap(),changed);
 let mut corrupt=changed.0.clone();corrupt.push(b' ');assert!(fork.restore(&corrupt,&changed.1).is_err());assert_eq!(fork.checkpoint().unwrap(),changed);
 let mut detached=owner.checkpoint().unwrap();detached.0.clear();assert_eq!(owner.checkpoint().unwrap(),original);
}

#[test]
fn terminal_redelivery_retains_new_receipt_and_replaces_warmed_encoding(){
 let mut owner=Manager::new(configuration()).unwrap();owner.apply(&command(1,false)).unwrap();
 let mut reserve=command(2,false);reserve["op"]=json!("RESERVE");reserve["payload"]=json!({"schema_version":1,"reservation":"r","order":"o","amount":"10.00"});owner.apply(&reserve).unwrap();
 let mut release=command(3,false);release["op"]=json!("RELEASE");release["payload"]=json!({"schema_version":1,"reservation":"r","outcome":"NOT_SENT"});owner.apply(&release).unwrap();
 let original=owner.checkpoint().unwrap();release["command_id"]=json!("new-receipt");release["runtime_sequence"]=json!(4);
 assert_eq!(owner.apply(&release).unwrap().status,Status::Duplicate);
 let changed=owner.checkpoint().unwrap();assert_ne!(changed,original);
 assert!(owner.receipts.contains_key("new-receipt"));assert_eq!(owner.journal.len(),4);
 let mut restored=Manager::new(configuration()).unwrap();restored.restore(&changed.0,&changed.1).unwrap();assert_eq!(restored.checkpoint().unwrap(),changed);
}

#[test]
fn cloned_owner_shares_immutable_journal_commands_without_changing_history(){
 let mut owner=Manager::new(configuration()).unwrap();owner.apply(&command(1,false)).unwrap();let original=owner.checkpoint().unwrap();let mut fork=owner.clone();
 let a:&Value=&owner.journal[0];let b:&Value=&fork.journal[0];assert!(std::ptr::eq(a,b),"a clone deep-copied an immutable accepted journal command");
 let a:&Value=&owner.timeline[0];let b:&Value=&fork.timeline[0];assert!(std::ptr::eq(a,b),"a clone deep-copied an immutable historical snapshot");
 fork.apply(&command(2,false)).unwrap();assert_eq!(owner.journal.len(),1);assert_eq!(fork.journal.len(),2);assert_eq!(owner.checkpoint().unwrap(),original);
 let changed=fork.checkpoint().unwrap();let mut cold=Manager::new(configuration()).unwrap();cold.restore(&changed.0,&changed.1).unwrap();assert_eq!(cold.checkpoint().unwrap(),changed);
}

#[test]
fn checkpoint_record_preserves_exact_bytes_fingerprint_and_detaches_caller_mutation() {
    let mut owner = Manager::new(configuration()).unwrap();
    owner.apply(&command(1, false)).unwrap();
    let (bytes, fingerprint) = owner.checkpoint().unwrap();
    let (record, observed) = owner.checkpoint_record().unwrap();
    assert_eq!(observed, fingerprint);
    assert_eq!(serde_json::to_vec(record.as_ref()).unwrap(), bytes);
    assert_eq!(digest(&bytes), observed);
    assert_eq!(*record, serde_json::from_slice::<Value>(&bytes).unwrap());

    CHECKPOINT_ENCODINGS.with(|count| count.set(0));
    for _ in 0..4 {
        let (same, hash) = owner.checkpoint_record().unwrap();
        assert!(std::sync::Arc::ptr_eq(&record, &same));
        assert_eq!(hash, fingerprint);
        assert_eq!(owner.checkpoint().unwrap(), (bytes.clone(), fingerprint.clone()));
    }
    assert_eq!(CHECKPOINT_ENCODINGS.with(std::cell::Cell::get), 0);

    let mut detached = std::sync::Arc::clone(&record);
    std::sync::Arc::make_mut(&mut detached)["state"] = Value::Null;
    assert_ne!(detached, record);
    let (retained, hash) = owner.checkpoint_record().unwrap();
    assert!(std::sync::Arc::ptr_eq(&record, &retained));
    assert_eq!(hash, fingerprint);
    assert_eq!(owner.checkpoint().unwrap(), (bytes, fingerprint));
}

#[test]
fn checkpoint_record_clone_mutation_and_failed_transitions_preserve_original_representation() {
    let mut owner = Manager::new(configuration()).unwrap();
    owner.apply(&command(1, false)).unwrap();
    let original = owner.checkpoint_record().unwrap();
    let mut fork = owner.clone();
    assert!(std::sync::Arc::ptr_eq(&original.0, &fork.checkpoint_record().unwrap().0));

    fork.apply(&command(2, false)).unwrap();
    let changed = fork.checkpoint_record().unwrap();
    assert_ne!(changed.1, original.1);
    assert!(!std::sync::Arc::ptr_eq(&original.0, &changed.0));
    let retained = owner.checkpoint_record().unwrap();
    assert!(std::sync::Arc::ptr_eq(&original.0, &retained.0));
    assert_eq!(retained.1, original.1);

    let mut invalid = command(3, false);
    invalid["op"] = json!("INVALID");
    assert!(fork.apply(&invalid).is_err());
    let mut conflict = command(2, false);
    conflict["payload"]["amount"] = json!("1.00");
    assert_eq!(fork.apply(&conflict).unwrap().status, Status::Conflict);
    let mut bytes = fork.checkpoint().unwrap().0;
    bytes.push(b' ');
    assert!(fork.restore(&bytes, &changed.1).is_err());
    assert!(fork.restore_exact_extension(&bytes, &changed.1).is_err());
    let unchanged = fork.checkpoint_record().unwrap();
    assert!(std::sync::Arc::ptr_eq(&changed.0, &unchanged.0));
    assert_eq!(unchanged.1, changed.1);

    let mut cold = Manager::new(configuration()).unwrap();
    let bytes = serde_json::to_vec(changed.0.as_ref()).unwrap();
    cold.restore(&bytes, &changed.1).unwrap();
    assert_eq!(cold.checkpoint_record().unwrap(), changed);
    owner.restore_exact_extension(&bytes, &changed.1).unwrap();
    assert_eq!(owner.checkpoint_record().unwrap(), changed);
}
