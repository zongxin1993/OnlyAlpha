const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
mod support;
use onlyalpha_domain::base::OnlyDomainModel;
use serde_json::{Value, json};
use support::*;

fn apply(c: &mut Harness, v: &Value) {
    let p = c.prepare(v).unwrap();
    for i in 0..p.projection_count() {
        c.install_projection(&p, i).unwrap();
    }
    c.complete(&p).unwrap();
}

fn market(n: u64, side: &str) -> Value {
    let mut v = open(n, side);
    v["payload"]["request"]["order_type"] = json!("MARKET");
    v["payload"]["request"]["price"] = Value::Null;
    let reference = if side == "BUY" {
        "11.000000"
    } else {
        "13.000000"
    };
    v["payload"]["market"]["reference_price"] =
        json!({"schema_version":1,"value":reference,"precision":6});
    v["payload"]["market"]["notional"] = settlement_money(reference, "4");
    v["payload"]["market"]["request_digest"] = json!(onlyalpha_execution::digest(
        v["payload"]["request"].to_string().as_bytes()
    ));
    if side == "BUY" {
        v["payload"]["fee_contract"]["funding"]["principal_reservation"]["amount"] = json!("44.00");
        v["payload"]["fee_contract"]["funding"]["total_reservation"]["amount"] = json!("44.00");
    }
    v
}

fn market_fill(n: u64, ordinal: u64, quantity: &str, price: &str) -> Value {
    let mut v = fill(n, ordinal, quantity, price, "1.00");
    v["payload"]["price_precision"] = json!(6);
    v
}

#[test]
fn market_reference_funds_without_becoming_a_limit() {
    let mut c = Harness::new(config()).unwrap();
    apply(&mut c, &market(1, "BUY"));
    let order = c.order_snapshot(&c.store, "cluster", &order(1)).unwrap();
    assert!(order.price().is_none());
    assert_eq!(order.to_record()["order_type"], "MARKET");
    assert_eq!(
        c.state().unwrap()["account"]["snapshot"]["reserved"],
        "45.00"
    );
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    assert!(c.prepare(&stage(3, 1, "BEGIN_SUBMIT")).is_err());
}

#[test]
fn market_fill_has_independent_precision_and_recovers_exactly() {
    let mut c = Harness::new(config()).unwrap();
    assert_eq!(config()["instruments"][0]["price_precision"], 2);
    apply(&mut c, &market(1, "BUY"));
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    let f = market_fill(3, 1, "4", "10.002000");
    let p = c.prepare(&f).unwrap();
    c.commit_only(&p).unwrap();
    let mut recovered = Harness::new(config()).unwrap();
    recovered.store = c.store.clone();
    onlyalpha_execution::recover(&mut recovered.store, &mut recovered.components).unwrap();
    let s = recovered.state().unwrap();
    assert_eq!(s["account"]["snapshot"]["cash"], "958.99");
    assert_eq!(s["account"]["snapshot"]["reserved"], "0.00");
    assert_eq!(s["position"]["accounts"][0]["snapshot"]["cost"], "40.008");
    let bought = recovered
        .order_snapshot(&recovered.store, "cluster", &order(1))
        .unwrap();
    assert!(bought.price().is_none());
    assert_eq!(bought.average_fill_price().as_ref().unwrap().precision(), 6);
    let ready = recovered.checkpoint().unwrap();
    onlyalpha_execution::recover(&mut recovered.store, &mut recovered.components).unwrap();
    assert_eq!(recovered.checkpoint().unwrap(), ready);
    assert!(recovered.prepare(&f).is_err());
    apply(&mut recovered, &market(5, "SELL"));
    apply(&mut recovered, &stage(6, 2, "UNKNOWN"));
    apply(&mut recovered, &market_fill(7, 2, "4", "11.997600"));
    let s = recovered.state().unwrap();
    assert_eq!(s["account"]["snapshot"]["cash"], "1005.98");
    assert_eq!(s["position"]["accounts"][0]["snapshot"]["quantity"], "0");
    assert_eq!(
        s["ledger"]["ledgers"]["cluster"]["snapshot"]["cash"],
        "1005.98"
    );
}

#[test]
fn market_missing_or_invalid_reference_never_mutates() {
    let c = Harness::new(config()).unwrap();
    for replacement in [
        Value::Null,
        json!({"schema_version":1,"value":"11.000000"}),
        json!({"schema_version":1,"value":"0.000000","precision":6}),
        json!({"schema_version":1,"value":"11.000001","precision":2}),
        json!({"schema_version":1,"value":"11.000000","precision":19}),
    ] {
        let mut v = market(1, "BUY");
        v["payload"]["market"]["reference_price"] = replacement;
        let before = c.checkpoint().unwrap();
        assert!(c.prepare(&v).is_err());
        assert_eq!(c.checkpoint().unwrap(), before);
    }
    let mut v = market(1, "BUY");
    v["payload"]["market"]
        .as_object_mut()
        .unwrap()
        .remove("reference_price");
    assert!(c.prepare(&v).is_err());
}

#[test]
fn market_fill_requires_explicit_exact_precision_and_funding() {
    let mut c = Harness::new(config()).unwrap();
    apply(&mut c, &market(1, "BUY"));
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    let mut f = market_fill(3, 1, "4", "10.002000");
    f["payload"]
        .as_object_mut()
        .unwrap()
        .remove("price_precision");
    assert!(c.prepare(&f).is_err());
    for precision in [json!(2), json!(19), Value::Null] {
        let mut f = market_fill(3, 1, "4", "10.002000");
        f["payload"]["price_precision"] = precision;
        let before = c.checkpoint().unwrap();
        assert!(c.prepare(&f).is_err());
        assert_eq!(c.checkpoint().unwrap(), before);
    }
    let before = c.checkpoint().unwrap();
    assert!(c.prepare(&market_fill(3, 1, "4", "12.000000")).is_err());
    assert_eq!(c.checkpoint().unwrap(), before);
    let mut cfg = config();
    cfg["initial_cash"] = json!("44.99");
    cfg["capitals"]["cluster"] = json!("44.99");
    let poor = Harness::new(cfg).unwrap();
    assert!(poor.prepare(&market(1, "BUY")).is_err());
}

#[test]
fn limit_contract_keeps_limit_and_rejects_market_precision_field() {
    let mut c = Harness::new(config()).unwrap();
    apply(&mut c, &open(1, "BUY"));
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    assert!(c.prepare(&fill(3, 1, "4", "10.01", "1.00")).is_err());
    assert!(c.prepare(&market_fill(3, 1, "4", "10.00")).is_err());
    apply(&mut c, &fill(3, 1, "4", "10.00", "1.00"));
    assert_eq!(c.state().unwrap()["account"]["snapshot"]["cash"], "959.00");
}

fn whole_fill_admission(configuration:&Value, high_precision:bool) -> Value {
    let mut admission=market(1,"BUY");
    let policy="a".repeat(64);
    admission["payload"]["request"]["metadata"]["replay_policy"]=json!(policy);
    if high_precision {
        admission["payload"]["request"]["quantity"]=json!({"schema_version":1,"value":"0.01000","precision":5});
        admission["payload"]["market"]["notional"]=settlement_money("11.000000","0.01");
        admission["payload"]["fee_contract"]["funding"]["principal_reservation"]["amount"]=json!("0.11");
        admission["payload"]["fee_contract"]["funding"]["total_reservation"]["amount"]=json!("0.11");
    }
    admission["payload"]["market"]["request_digest"]=json!(onlyalpha_execution::digest(admission["payload"]["request"].to_string().as_bytes()));
    let model=json!({"schema_version":1,"kind":"GUARANTEED_WHOLE_FILL","runtime_kind":"BACKTEST","maximum_fill_count":1,"configuration_fingerprint":onlyalpha_execution::digest(configuration.to_string().as_bytes()),"policy_fingerprint":policy});
    admission["payload"]["schema_version"]=json!(2);
    admission["payload"]["settlement_fill_contract"]=json!({"schema_version":1,"kind":"BACKTEST_WHOLE_FILL","maximum_fill_count":1,"model_fingerprint":onlyalpha_execution::digest(model.to_string().as_bytes()),"model":model,"fee_estimate_assumptions_fingerprint":admission["payload"]["fee_contract"]["estimate"]["assumptions_fingerprint"]});
    admission
}
#[test]
fn whole_fill_admit_preserves_exact_quantity_and_recovers_the_bound_contract() {
    let mut cfg=config();cfg["instruments"][0]["quantity_precision"]=json!(5);
    let mut harness=Harness::new(cfg.clone()).unwrap();let admission=whole_fill_admission(&cfg,true);
    let mut legacy=admission.clone();legacy["payload"]["schema_version"]=json!(1);legacy["payload"].as_object_mut().unwrap().remove("settlement_fill_contract");
    assert!(harness.prepare(&legacy).is_err());
    apply(&mut harness,&admission);
    let before=harness.checkpoint().unwrap();
    let mut fresh=Harness::new(cfg).unwrap();fresh.store=harness.store.clone();
    onlyalpha_execution::recover(&mut fresh.store,&mut fresh.components).unwrap();
    assert_eq!(fresh.checkpoint().unwrap(),before);
    let snapshot=fresh.order_snapshot(&fresh.store,"cluster",&order(1)).unwrap().to_record();
    assert_eq!(snapshot["quantity"]["precision"],5);assert_eq!(snapshot["quantity"]["value"],"0.01000");
    assert!(snapshot["price"].is_null());
}
#[test]
fn whole_fill_admit_rejects_detached_models_and_fee_assumptions() {
    let cfg=config();let harness=Harness::new(cfg.clone()).unwrap();let original=whole_fill_admission(&cfg,false);
    for mutation in 0..5 {
        let mut input=original.clone();let contract=&mut input["payload"]["settlement_fill_contract"];
        match mutation {
            0=>{contract.as_object_mut().unwrap().remove("model");},
            1=>contract["model_fingerprint"]=json!("b".repeat(64)),
            2=>{contract["model"]["configuration_fingerprint"]=json!("b".repeat(64));contract["model_fingerprint"]=json!(onlyalpha_execution::digest(contract["model"].to_string().as_bytes()));},
            3=>{contract["model"]["policy_fingerprint"]=json!("b".repeat(64));contract["model_fingerprint"]=json!(onlyalpha_execution::digest(contract["model"].to_string().as_bytes()));},
            _=>contract["fee_estimate_assumptions_fingerprint"]=json!("b".repeat(64)),
        }
        assert!(harness.prepare(&input).is_err());
    }
    for kind in ["LIVE","SIM"] {
        let mut cfg=config();cfg["runtime_kind"]=json!(kind);let mut input=whole_fill_admission(&cfg,false);input["runtime_kind"]=json!(kind);
        let harness=Harness::new(cfg).unwrap();assert!(harness.prepare(&input).is_err());
    }
}
#[test]
fn whole_fill_admit_cannot_install_a_partial_model_trade() {
    let cfg=config();let mut harness=Harness::new(cfg.clone()).unwrap();
    apply(&mut harness,&whole_fill_admission(&cfg,false));apply(&mut harness,&stage(2,1,"UNKNOWN"));
    let before=harness.checkpoint().unwrap();
    assert!(harness.prepare(&market_fill(3,1,"2","10.002000")).is_err());
    assert_eq!(harness.checkpoint().unwrap(),before);
    apply(&mut harness,&market_fill(3,1,"4","10.002000"));
}

#[test]
fn retained_admission_preview_uses_the_same_owner_and_cannot_commit_or_allocate() {
    use onlyalpha_execution::Components;
    for (capital,denied) in [("1000.00",false),("44.99",true)] {
        let mut cfg=config();cfg["initial_cash"]=json!(capital);cfg["capitals"]["cluster"]=json!(capital);
        let harness=Harness::new(cfg.clone()).unwrap();
        let original=harness.checkpoint().unwrap();let input=market(1,"BUY");
        let direct=harness.prepare(&input);
        if denied {assert_eq!(direct.unwrap_err().0,"EXECUTION_RISK_DENIED");}else{assert!(direct.is_ok());}
        for _ in 0..2 {
            assert_eq!(Components::admission_risk_denied(&cfg,&original,&input).unwrap(),denied);
            assert_eq!(harness.checkpoint().unwrap(),original);
            assert!(harness.store.rows.is_empty());
        }
        let preview=harness.fee_order_preview(&harness.store,"cluster",&input["payload"]["request"],1).unwrap();
        let read=Components::fee_order_preview_checkpoint(&cfg,&original["components"][0],"cluster",&input["payload"]["request"],1).unwrap();
        assert_eq!(read,preview);
        assert_eq!(read.order_id().value(),"runtime-ORDER-000001");
        assert_eq!(harness.checkpoint().unwrap(),original);
        let mut foreign=input.clone();foreign["runtime"]=json!("foreign");
        assert!(Components::admission_risk_denied(&cfg,&original,&foreign).is_err());
    }
}
