use serde_json::{Value, json};
fn setup() -> (
    onlyalpha_account::Manager,
    onlyalpha_position::Manager,
    Value,
) {
    let mut config = json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","gateway":"g","generation":"a".repeat(64),"currency":{"schema_version":1,"code":"CNY","precision":2,"currency_type":"FIAT"},"account_type":"CASH","initial_cash":"100.00"});
    let mut pc = config.clone();
    pc.as_object_mut().unwrap().remove("account_type");
    pc.as_object_mut().unwrap().remove("initial_cash");
    pc["clusters"] = json!(["c"]);
    pc["instruments"] = json!([{"schema_version":1,"id":"600000.XSHG","price_precision":2,"quantity_precision":0,"multiplier":"1"}]);
    config["schema_version"] = json!(2);
    config["position_configuration"] = json!(onlyalpha_position::digest(pc.to_string().as_bytes()));
    let account = onlyalpha_account::Manager::new(config.clone()).unwrap();
    let position = onlyalpha_position::Manager::new(pc).unwrap();
    let mut cmd = config;
    cmd.as_object_mut().unwrap().retain(|k, _| {
        [
            "schema_version",
            "engine",
            "runtime",
            "account",
            "gateway",
            "generation",
        ]
        .contains(&k.as_str())
    });
    cmd["schema_version"] = json!(1);
    cmd["command_id"] = json!("v1");
    cmd["cause"] = json!("b".repeat(64));
    cmd["time"] = json!(1);
    cmd["op"] = json!("VALUATION");
    cmd["payload"] = Value::Null;
    (account, position, cmd)
}
fn intent(p: &onlyalpha_position::Manager) -> Value {
    json!({"schema_version":1,"valuation":"v1","version":1,"economic_version":0,"position_evidence":p.checkpoint().unwrap().1,"time":1,"marks":[]})
}
#[test]
fn typed_valuation_requires_basis_owner_and_version_and_rederives_on_restore() {
    let (mut a, p, mut cmd) = setup();
    let effect = p.value(&intent(&p)).unwrap();
    a.apply_valuation(&cmd, &effect).unwrap();
    let cp = a.checkpoint().unwrap();
    let (mut fresh, _, _) = setup();
    fresh.restore(&cp.0, &cp.1).unwrap();
    assert_eq!(fresh.state(), a.state());
    cmd["command_id"] = json!("v2");
    let mut i = intent(&p);
    i["valuation"] = json!("v2");
    let effect = p.value(&i).unwrap();
    assert!(a.apply_valuation(&cmd, &effect).is_err());
    i["version"] = json!(2);
    i["economic_version"] = json!(1);
    let effect = p.value(&i).unwrap();
    assert!(a.apply_valuation(&cmd, &effect).is_err());
    let before = fresh.state();
    let mut corrupt: Value = serde_json::from_slice(&cp.0).unwrap();
    corrupt["journal"][0]["payload"]["position"]["state"]["sequence"] = json!(999);
    let bytes = serde_json::to_vec(&corrupt).unwrap();
    assert!(
        fresh
            .restore(&bytes, &onlyalpha_account::digest(&bytes))
            .is_err()
    );
    assert_eq!(fresh.state(), before);
}

#[test]
fn rehashed_derived_equity_and_complete_foreign_owner_cannot_author_account_truth() {
    let (mut account, source, command) = setup();
    let effect = source.value(&intent(&source)).unwrap();
    account.apply_valuation(&command, &effect).unwrap();
    let (bytes, _) = account.checkpoint().unwrap();
    let mut forged: Value = serde_json::from_slice(&bytes).unwrap();
    forged["state"]["snapshot"]["market_value"] = json!("999.00");
    forged["state"]["snapshot"]["equity"] = json!("1099.00");
    let data = serde_json::to_vec(&forged).unwrap();
    let before = account.state();
    assert!(
        account
            .restore(&data, &onlyalpha_account::digest(&data))
            .is_err()
    );
    assert_eq!(account.state(), before);
    let cp: Value = serde_json::from_slice(&source.checkpoint().unwrap().0).unwrap();
    let mut config = cp["config"].clone();
    config["account"] = json!("foreign");
    let foreign = onlyalpha_position::Manager::new(config).unwrap();
    let effect = foreign.value(&intent(&foreign)).unwrap();
    let (mut empty, _, command) = setup();
    assert_eq!(
        empty.apply_valuation(&command, &effect).unwrap_err().0,
        "ACCOUNT_VALUATION_OWNER"
    );
}

#[test]
fn same_scope_unfunded_position_history_cannot_create_account_equity() {
    let (mut account, mut position, command) = setup();
    let trade = json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","gateway":"g","generation":"a".repeat(64),"command_id":"unfunded","cause":"b".repeat(64),"time":1,"op":"TRADE","payload":{"schema_version":1,"instrument":"600000.XSHG","cluster":"c","order":"o","trade":"t","venue_trade":"v","execution":"x","sequence":1,"side":"BUY","position_side":"LONG","position_mode":"NETTING","price":"1.00","quantity":"1","fee":"0.00","bucket":"SETTLED","terminal_fill":false}});
    position.apply(&trade).unwrap();
    let mut source = intent(&position);
    source["marks"] = json!([{"schema_version":1,"instrument":"600000.XSHG","mark":"12.00","family":"CLOSED_BAR","source_ref":"bar","version":1,"time":1,"as_of_sequence":1}]);
    let effect = position.value(&source).unwrap();
    let before = account.state();
    assert!(account.apply_valuation(&command, &effect).is_err());
    assert_eq!(account.state(), before);
}
