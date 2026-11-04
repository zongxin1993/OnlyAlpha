#![allow(dead_code)]
use serde_json::{Value, json};
pub fn config() -> Value {
    let g = "a".repeat(64);
    let currency = json!({"schema_version":1,"code":"CNY","precision":2,"currency_type":"FIAT"});
    json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":g,"runtime_kind":"BACKTEST","currency":currency,"initial_cash":"1000.00","capitals":{"cluster":"1000.00"},"profiles":{"cluster":{"schema_version":1,"revision":"revision","instruments":["600000.XSHG"],"rules":[]}},"instruments":[{"schema_version":1,"id":"600000.XSHG","price_precision":2,"quantity_precision":0,"multiplier":"1"}]})
}
pub fn fixture() -> Value {
    serde_json::from_str(super::FIXTURE).unwrap()
}
pub fn input(n: u64, op: &str, payload: Value) -> Value {
    let mut c = config();
    for f in [
        "currency",
        "initial_cash",
        "capitals",
        "profiles",
        "instruments",
    ] {
        c.as_object_mut().unwrap().remove(f);
    }
    c["cluster"] = json!("cluster");
    c["revision"] = json!("revision");
    c["input_id"] = json!(format!("input-{n}"));
    c["time"] = json!(n);
    c["runtime_sequence"] = json!(n);
    c["trading_day"] = json!("2026-10-19");
    c["day_index"] = json!(1);
    c["source_ref"] = json!(format!("source-{n}"));
    c["op"] = json!(op);
    c["payload"] = payload;
    if matches!(op, "ADMIT" | "FILL" | "TERMINAL") {
        c["payload"]["collateral"] =
            json!({"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null});
    }
    c
}
pub fn open(n: u64, side: &str) -> Value {
    let mut f = fixture();
    let ordinal = if side == "BUY" { 1 } else { 2 };
    let oid = format!("runtime-ORDER-{ordinal:06}");
    let rid = format!("request-{ordinal}");
    let r = &mut f["request"];
    r["request_id"]["value"] = json!(rid);
    r["side"] = json!(side);
    r["execution_intent"]["side"] = json!(side);
    r["execution_intent"]["position_effect"] = json!(if side == "BUY" { "OPEN" } else { "CLOSE" });
    r["price"]["value"] = json!(if side == "BUY" { "10.00" } else { "12.00" });
    let contract = if side == "BUY" {
        f["fee_contract"].clone()
    } else {
        f["second_fee_contract"].clone()
    };
    input(
        n,
        "ADMIT",
        json!({"schema_version":1,"request":f["request"],"fee_contract":contract,"fee_budget":"1.00","market":{"schema_version":1,"verdict":"ACCEPT","source_ref":format!("market-{n}"),"request_digest":onlyalpha_risk::digest(f["request"].to_string().as_bytes()),"notional":settlement_money(f["request"]["price"]["value"].as_str().unwrap(),f["request"]["quantity"]["value"].as_str().unwrap()),"rounding":"HALF_EVEN"},"order":oid}),
    )
}
pub fn order(ordinal: u64) -> String {
    format!("runtime-ORDER-{ordinal:06}")
}
pub fn stage(n: u64, ordinal: u64, stage: &str) -> Value {
    input(
        n,
        "SUBMISSION",
        json!({"schema_version":1,"order":order(ordinal),"outcome":stage}),
    )
}
pub fn fill(n: u64, ordinal: u64, quantity: &str, price: &str, charges: &str) -> Value {
    let policy = if ordinal == 1 {
        fixture()["fee_contract"]["binding"]["fingerprint"].clone()
    } else {
        fixture()["second_fee_contract"]["binding"]["fingerprint"].clone()
    };
    let mut v = input(
        n,
        "FILL",
        json!({"schema_version":1,"order":order(ordinal),"trade":format!("trade-{n}"),"venue_trade":format!("venue-trade-{n}"),"venue_order":format!("venue-{ordinal}"),"quantity":quantity,"price":price,"fees":{"schema_version":1,"instruction":format!("fee-{n}"),"source_ref":format!("fee-source-{n}"),"policy":policy,"order":order(ordinal),"trade":format!("trade-{n}"),"currency":config()["currency"],"charge_target":charges,"rebate_target":"0.00"},"settlement":{"schema_version":1,"instruction":format!("settlement-{n}"),"source_ref":format!("settlement-source-{n}"),"order":order(ordinal),"trade":format!("trade-{n}"),"currency":config()["currency"],"model":"CASH_SETTLEMENT","gross_notional":settlement_money(price,quantity),"rounding":"HALF_EVEN"},"valuation":{"schema_version":1,"source_ref":format!("valuation-source-{n}"),"currency":config()["currency"],"mark":price}}),
    );
    let template: Value = serde_json::from_str(super::SETTLEMENT_FIXTURE).unwrap();
    v["payload"]["settlement"]["calendar"] = template["calendar"].clone();
    v["payload"]["settlement"]["policy"] = template["policy"].clone();
    let scope = json!({"schema_version":1,"engine":v["engine"],"runtime":v["runtime"],"account":v["account"],"gateway":v["gateway"],"generation":v["generation"],"runtime_kind":v["runtime_kind"],"cluster":v["cluster"],"revision":v["revision"],"instrument":"600000.XSHG","request":format!("request-{ordinal}")});
    for (key, family) in [
        ("fees", "ORDER_FEE_ACCRUAL"),
        ("settlement", "SETTLEMENT"),
        ("valuation", "VALUATION"),
    ] {
        let proof = &mut v["payload"][key];
        proof["scope"] = scope.clone();
        proof["family"] = json!(family);
        proof["version"] = json!(n);
        proof["as_of_sequence"] = json!(n);
        let hash = onlyalpha_execution::digest(proof.to_string().as_bytes());
        proof["source_digest"] = json!(hash);
    }
    v
}

pub fn terminal(n: u64, ordinal: u64, outcome: &str) -> Value {
    input(
        n,
        "TERMINAL",
        json!({"schema_version":1,"order":order(ordinal),"outcome":outcome}),
    )
}

use onlyalpha_execution::{CommitIntent, Components, Error, Prepared, Record, Store};
#[derive(Default, Clone)]
pub struct MemoryStore {
    pub rows: Vec<Record>,
    unknown_commit: bool,
}
impl Store for MemoryStore {
    fn head(&self) -> Result<u64, Error> {
        Ok(self.rows.len() as u64)
    }
    fn commit(&mut self, intent: &CommitIntent) -> Result<Record, Error> {
        let p = intent.prepared();
        if let Some(r) = self.rows.get((p.sequence() - 1) as usize) {
            if r.prepared() != p {
                return Err(Error("STORE_CONFLICT".into()));
            }
            return Ok(r.clone());
        }
        if p.sequence() != self.rows.len() as u64 + 1 {
            return Err(Error("STORE_SEQUENCE".into()));
        }
        let r = Record::new(intent);
        self.rows.push(r.clone());
        if self.unknown_commit {
            return Err(Error("UNKNOWN_COMMIT".into()));
        }
        Ok(r)
    }
    fn get(&self, n: u64) -> Result<Option<Record>, Error> {
        Ok(self.rows.get((n - 1) as usize).cloned())
    }
    fn mark_ready(&mut self, n: u64) -> Result<(), Error> {
        let mut r = self.rows[(n - 1) as usize].record();
        r["ready"] = json!(true);
        self.rows[(n - 1) as usize] = Record::decode(&r)?;
        Ok(())
    }
    fn acknowledge(&mut self, n: u64) -> Result<(), Error> {
        let mut r = self.rows[(n - 1) as usize].record();
        if r["ready"] != true {
            return Err(Error("NOT_READY".into()));
        }
        r["delivered"] = json!(true);
        self.rows[(n - 1) as usize] = Record::decode(&r)?;
        Ok(())
    }
}
pub struct Harness {
    pub components: Components,
    pub store: MemoryStore,
}
impl Harness {
    pub fn new(c: Value) -> Result<Self, Error> {
        Ok(Self {
            components: Components::new(c)?,
            store: MemoryStore::default(),
        })
    }
    pub fn prepare(&self, v: &Value) -> Result<Prepared, Error> {
        self.components.prepare(&self.store, v)
    }
    pub fn state(&self) -> Result<Value, Error> {
        self.components.state(&self.store)
    }
    pub fn commit_only(&mut self, p: &Prepared) -> Result<(), Error> {
        if self.store.get(p.sequence())?.is_none() {
            self.store.unknown_commit = true;
            let result = onlyalpha_execution::coordinate(&mut self.store, &mut self.components, p);
            self.store.unknown_commit = false;
            if result.is_ok() {
                return Err(Error("TEST_COMMIT_FAULT_NOT_OBSERVED".into()));
            }
        }
        Ok(())
    }
    pub fn install_projection(&mut self, p: &Prepared, i: usize) -> Result<(), Error> {
        self.commit_only(p)?;
        self.components.install_projection(&self.store, p, i)
    }
    pub fn complete(&mut self, p: &Prepared) -> Result<(), Error> {
        self.store.mark_ready(p.sequence())?;
        self.components.complete(&self.store, p)
    }
    pub fn restore(&mut self, v: &Value) -> Result<(), Error> {
        self.components
            .restore(v, &onlyalpha_execution::digest(&serde_json::to_vec(v)?))
    }
}
impl std::ops::Deref for Harness {
    type Target = Components;
    fn deref(&self) -> &Self::Target {
        &self.components
    }
}
impl std::ops::DerefMut for Harness {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.components
    }
}

pub fn settlement_money(price: &str, quantity: &str) -> Value {
    use std::str::FromStr;
    let n = bigdecimal::BigDecimal::from_str(price).unwrap()
        * bigdecimal::BigDecimal::from_str(quantity).unwrap();
    json!({"schema_version":1,"amount":n.with_scale_round(2,bigdecimal::RoundingMode::HalfEven).to_plain_string(),"currency":config()["currency"]})
}
pub fn refresh_market(v: &mut Value) {
    v["payload"]["market"]["notional"] = settlement_money(
        v["payload"]["request"]["price"]["value"].as_str().unwrap(),
        v["payload"]["request"]["quantity"]["value"]
            .as_str()
            .unwrap(),
    );
    v["payload"]["market"]["request_digest"] = json!(onlyalpha_execution::digest(
        v["payload"]["request"].to_string().as_bytes()
    ));
}
