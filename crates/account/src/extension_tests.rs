use crate::{Manager, Status, digest};
use serde_json::{Value, json};

fn setup(version: u8) -> (Manager, onlyalpha_position::Manager) {
    let position = json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","gateway":"g","generation":"a".repeat(64),"currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"clusters":["c"],"instruments":[{"schema_version":1,"id":"BTCUSDT.BINANCE","price_precision":2,"quantity_precision":0,"multiplier":"1"}]});
    let config = json!({"schema_version":2,"engine":"e","runtime":"r","account":"a","gateway":"g","generation":"a".repeat(64),"currency":position["currency"],"account_type":"CASH","initial_cash":"100.00","position_configuration":onlyalpha_position::digest(position.to_string().as_bytes())});
    let account = if version == 4 { Manager::new(config) } else { Manager::new_checkpoint5(config) }.unwrap();
    (account, onlyalpha_position::Manager::new(position).unwrap())
}
fn command(n: u64, op: &str, payload: Value) -> Value {
    json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","gateway":"g","generation":"a".repeat(64),"command_id":format!("command-{n}"),"cause":"b".repeat(64),"time":n,"op":op,"payload":payload})
}
fn append_valuation(account: &mut Manager, position: &mut onlyalpha_position::Manager, n: u64, cause: &str) {
    if n == 2 {
        position.apply(&command(n,"BROKER",json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE","snapshot_id":format!("broker-{n}"),"sequence":n,"position_side":"FLAT","total":"0","settled":"0","unsettled":"0","available":"0","frozen":"0","average":null,"quality":"VERIFIED"}))).unwrap();
    }
    let intent=json!({"schema_version":1,"valuation":format!("估值-\\\"-{n}"),"version":n,"economic_version":0,"position_evidence":position.checkpoint().unwrap().1,"time":10+n,"marks":[]});
    let effect=position.value(&intent).unwrap();
    let mut input=command(10+n,"VALUATION",Value::Null);
    input["cause"]=json!(cause);
    assert_eq!(account.apply_valuation(&input,&effect).unwrap().status,Status::Applied);
}
fn capture(owner: &Manager) -> Value { serde_json::from_slice(&owner.checkpoint().unwrap().0).unwrap() }
fn replay_count() -> usize { crate::recovery::ACCOUNT_COMMAND_REPLAYS.with(|count| count.replace(0)) }
// Extension is explicitly selected; ordinary arbitrary cold restore stays tested.
fn extend(owner: &mut Manager, bytes: &[u8], expected: &str) -> Result<(), crate::Error> {
    owner.restore_exact_extension(bytes, expected)
}
fn encode(value: &Value) -> (Vec<u8>,String) { let bytes=serde_json::to_vec(value).unwrap();let hash=digest(&bytes);(bytes,hash) }

#[test]
fn exact_extension_replays_each_actual_command_only_once() {
    for version in [4,5] {
        let (mut actual, mut position)=setup(version);
        let (mut restored,_)=setup(version);
        for n in 1..=3 {
            append_valuation(&mut actual,&mut position,n,&"b".repeat(64));
            let expected=actual.checkpoint().unwrap();
            replay_count();
            extend(&mut restored,&expected.0,&expected.1).unwrap();
            assert_eq!(replay_count(),1,"checkpoint{version} snapshot{n} must replay only its new command");
            assert_eq!(restored.checkpoint().unwrap(),expected);
            assert_eq!(restored.state(),actual.state());
        }
        let expected=actual.checkpoint().unwrap();
        let (mut cold,_)=setup(version);
        replay_count();cold.restore(&expected.0,&expected.1).unwrap();
        assert_eq!(replay_count(),3,"ordinary arbitrary cold restore keeps complete replay");
        assert_eq!(cold.checkpoint().unwrap(),expected);
        append_valuation(&mut actual,&mut position,4,&"b".repeat(64));
        append_valuation(&mut restored,&mut position,4,&"b".repeat(64));
        assert_eq!(restored.checkpoint().unwrap(),actual.checkpoint().unwrap());
    }
}

#[test]
fn exact_extension_retains_semantic_redelivery_receipts_and_refuses_no_extension() {
    for version in [4,5] {
        let (mut current,_)=setup(version);
        let first=command(1,"CASH_CHANGE",json!({"schema_version":1,"change":"deposit","source_fact":"source","kind":"DEPOSIT","amount":"0.00"}));
        current.apply(&first).unwrap();
        let saved=current.checkpoint().unwrap();
        let mut target=current.clone();
        let mut redelivery=first.clone();redelivery["command_id"]=json!("redelivery");
        assert_eq!(target.apply(&redelivery).unwrap().status,Status::Duplicate);
        let expected=target.checkpoint().unwrap();
        replay_count();extend(&mut current,&expected.0,&expected.1).unwrap();
        assert_eq!(replay_count(),1);
        assert_eq!(current.checkpoint().unwrap(),expected);
        assert_eq!(current.state()["receipts"].as_object().unwrap().len(),2);
        assert!(extend(&mut current,&expected.0,&expected.1).is_err(),"proper extension requires a newly retained command");
        assert_eq!(current.checkpoint().unwrap(),expected);
        assert!(extend(&mut current,&saved.0,&saved.1).is_err(),"cannot truncate a retained prefix");
        assert_eq!(current.checkpoint().unwrap(),expected);
        let mut invalid=command(2,"CASH_CHANGE",json!({"schema_version":1,"change":"bad","source_fact":"bad-source","kind":"DEPOSIT","amount":"-1.00"}));
        assert!(target.apply(&invalid).is_err());
        invalid=first.clone();invalid["payload"]["amount"]=json!("1.00");
        assert_eq!(target.apply(&invalid).unwrap().status,Status::Conflict);
        assert_eq!(target.checkpoint().unwrap(),expected,"failed/conflicting commands never manufacture an extension");
    }
}

#[test]
fn exact_extension_checks_full_target_and_errors_leave_original_owner_unchanged() {
    for version in [4,5] {
        let (mut original,mut position)=setup(version);
        append_valuation(&mut original,&mut position,1,&"b".repeat(64));
        let saved=original.checkpoint().unwrap();
        let mut target=original.clone();append_valuation(&mut target,&mut position,2,&"b".repeat(64));
        let target=capture(&target);
        for fault in ["digest","noncanonical","context","version","prefix","state","receipt","suffix-id","extra"] {
            let mut bad=target.clone();
            match fault {
                "context"=>bad["config"]["initial_cash"]=json!("200.00"),
                "version"=>bad["schema_version"]=json!(if version==4{5}else{4}),
                "prefix"=>bad["journal"][0]["cause"]=json!("c".repeat(64)),
                "state"=>bad["state"]["snapshot"]["cash"]=json!("101.00"),
                "receipt"=>{bad["state"]["receipts"].as_object_mut().unwrap().remove("command-11");},
                "suffix-id"=>bad["journal"][1]["command_id"]=bad["journal"][0]["command_id"].clone(),
                "extra"=>bad["unknown"]=json!(true),
                _=>{},
            }
            let (mut bytes,mut hash)=encode(&bad);
            if fault=="digest" {hash="0".repeat(64);}
            if fault=="noncanonical" {bytes.push(b' ');hash=digest(&bytes);}
            let mut current=original.clone();
            assert!(extend(&mut current,&bytes,&hash).is_err(),"version{version} fault {fault}");
            assert_eq!(current.checkpoint().unwrap(),saved,"failure {fault} must not install even a valid suffix prefix");
        }
    }
}

#[test]
fn exact_extension_never_falls_back_to_a_valid_alternative_history() {
    for version in [4,5] {
        let (mut current,mut current_position)=setup(version);
        append_valuation(&mut current,&mut current_position,1,&"b".repeat(64));
        let before=current.checkpoint().unwrap();
        let (mut alternate,mut alternate_position)=setup(version);
        append_valuation(&mut alternate,&mut alternate_position,1,&"c".repeat(64));
        append_valuation(&mut alternate,&mut alternate_position,2,&"b".repeat(64));
        let target=alternate.checkpoint().unwrap();
        let (mut cold,_)=setup(version);cold.restore(&target.0,&target.1).unwrap();
        assert_eq!(cold.checkpoint().unwrap(),target,"the alternative history is independently valid");
        assert!(extend(&mut current,&target.0,&target.1).is_err(),"a valid foreign prefix cannot select a cold fallback");
        assert_eq!(current.checkpoint().unwrap(),before);
    }
}

#[test]
fn exact_extension_rejects_all_checkpoint5_dictionary_substitutions() {
    let (mut original,mut position)=setup(5);
    append_valuation(&mut original,&mut position,1,&"b".repeat(64));
    let saved=original.checkpoint().unwrap();
    let mut target=original.clone();append_valuation(&mut target,&mut position,2,&"b".repeat(64));
    let target=capture(&target);
    for fault in ["missing","unused","digest","mixed","intent","source-fields"] {
        let mut bad=target.clone();
        let key=bad["journal"][1]["payload"]["position_ref"].as_str().unwrap().to_owned();
        match fault {
            "missing"=>{bad["positions"].as_object_mut().unwrap().remove(&key);},
            "unused"=>{
                let mut source=bad["positions"][&key].clone();source["extra"]=json!(true);
                let (_,hash)=encode(&source);bad["positions"][&hash]=source;
            },
            "digest"=>bad["positions"][&key]["state"]=json!({}),
            "mixed"=>bad["journal"][1]["payload"]["position"]=bad["positions"][&key].clone(),
            "intent"=>bad["journal"][1]["payload"]["intent"]["position_evidence"]=json!("0".repeat(64)),
            "source-fields"=>{
                let mut source=bad["positions"].as_object_mut().unwrap().remove(&key).unwrap();source["extra"]=json!(true);
                let (_,hash)=encode(&source);bad["positions"][&hash]=source;
                bad["journal"][1]["payload"]["position_ref"]=json!(hash);
                bad["journal"][1]["payload"]["intent"]["position_evidence"]=json!(hash);
            },
            _=>unreachable!(),
        }
        let (bytes,hash)=encode(&bad);let mut current=original.clone();
        assert!(extend(&mut current,&bytes,&hash).is_err(),"dictionary {fault}");
        assert_eq!(current.checkpoint().unwrap(),saved);
    }
}

#[test]
fn exact_extension_bounds_full_checkpoint5_expansion_before_replaying_any_suffix() {
    let (mut current,mut position)=setup(5);
    append_valuation(&mut current,&mut position,1,&"b".repeat(64));
    let before=current.checkpoint().unwrap();
    let mut target=capture(&current);
    let mut source=position.checkpoint().unwrap().0;
    let mut large:Value=serde_json::from_slice(&source).unwrap();
    large["controlled-expansion"]=json!("x".repeat(1024*1024));
    source=serde_json::to_vec(&large).unwrap();let reference=digest(&source);
    target["positions"][&reference]=large;
    let template=target["journal"][0].clone();
    for n in 2..=20 {
        let mut entry=template.clone();entry["command_id"]=json!(format!("large-{n}"));
        entry["payload"]["position_ref"]=json!(reference);
        entry["payload"]["intent"]["position_evidence"]=json!(reference);
        target["journal"].as_array_mut().unwrap().push(entry);
    }
    let (bytes,hash)=encode(&target);
    assert!(bytes.len()<2*1024*1024,"controlled wire remains small");
    // Independently serialize one full original command at a time, never an
    // expanded whole-history array, to prove the weighted guard really applies.
    let mut expanded=0;
    for (index,entry) in target["journal"].as_array().unwrap().iter().enumerate() {
        let mut full=entry.clone();let r=full["payload"].as_object_mut().unwrap().remove("position_ref").unwrap();
        full["payload"]["position"]=target["positions"][r.as_str().unwrap()].clone();
        expanded+=serde_json::to_vec(&full).unwrap().len()+usize::from(index!=0);
    }
    assert!(expanded>16*1024*1024);
    replay_count();
    assert_eq!(extend(&mut current,&bytes,&hash).unwrap_err().0,"ACCOUNT_CHECKPOINT_BOUND");
    assert_eq!(replay_count(),0,"complete dictionary/expansion validation precedes every command");
    assert_eq!(current.checkpoint().unwrap(),before);
}

// The implementation patch switches this direct owning-history test to the
// explicit borrowed query; its expected values stay actual original commands.
fn borrowed_valuation_intents(owner: &Manager) -> impl Iterator<Item = &Value> {
    owner.valuation_intents()
}
#[test]
fn valuation_intents_borrow_original_commands_at_both_checkpoint_formats() {
    for version in [4, 5] {
        let (mut owner, mut position) = setup(version);
        assert_eq!(borrowed_valuation_intents(&owner).count(), 0);
        for n in 1..=2 { append_valuation(&mut owner, &mut position, n, &"b".repeat(64)); }
        let original = owner.checkpoint().unwrap();
        let copied = owner.clone();
        for actual in [&owner, &copied] {
            let expected: Vec<_> = actual.state.journal.iter().filter(|command| command["op"] == "VALUATION")
                .map(|command| &command["payload"]["intent"]).collect();
            let borrowed: Vec<_> = borrowed_valuation_intents(actual).collect();
            assert_eq!(borrowed, expected);
            assert_eq!(borrowed.len(), 2);
            for (got, original) in borrowed.into_iter().zip(expected) { assert!(std::ptr::eq(got, original)); }
        }
        assert_eq!(owner.checkpoint().unwrap(), original);
        let mut restored = setup(version).0;
        restored.restore(&original.0, &original.1).unwrap();
        assert_eq!(borrowed_valuation_intents(&restored).collect::<Vec<_>>(), borrowed_valuation_intents(&owner).collect::<Vec<_>>());
        assert_eq!(restored.checkpoint().unwrap(), original);
    }
}
