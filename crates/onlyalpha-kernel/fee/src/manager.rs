use crate::{
    model::*,
    policy::{Assessment, Catalog},
};
use bigdecimal::{BigDecimal, Zero};
use serde_json::{Value, json};
use std::collections::BTreeMap;
#[derive(Clone, Debug)]
pub struct Application {
    pub(crate) value: Value,
}
impl Application {
    pub fn record(&self) -> Value {
        self.value.clone()
    }
}
/// One scoped Fee authority. Owning Execution persists its checkpoint atomically with economics.
#[derive(Clone)]
pub struct Manager {
    pub(crate) config: Value,
    pub(crate) capacity: usize,
    pub(crate) history: Vec<Value>,
    pub(crate) applications: BTreeMap<String, Value>,
    pub(crate) orders: BTreeMap<String, Value>,
    pub(crate) heads: BTreeMap<String, Value>,
    pub(crate) evidence: BTreeMap<String, Value>,
    pub(crate) decisions: BTreeMap<String, Value>,
    pub(crate) adjustments: Vec<Value>,
    pub(crate) blockers: BTreeMap<String, Value>,
}
impl Manager {
    pub fn new(config: Value, capacity: usize) -> Result<Self, Error> {
        fields(
            &config,
            &[
                "engine",
                "runtime",
                "account",
                "gateway",
                "runtime_kind",
                "generation",
            ],
        )?;
        for v in config.as_object().expect("object").values() {
            text(v)?;
        }
        one(&config["runtime_kind"], &["BACKTEST", "SIM", "LIVE"])?;
        let g = text(&config["generation"])?;
        if g.len() != 64
            || !g
                .bytes()
                .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
            || capacity == 0
            || capacity > 4096
        {
            return Err(err("FEE_CONFIG"));
        }
        Ok(Self {
            config,
            capacity,
            history: Vec::new(),
            applications: BTreeMap::new(),
            orders: BTreeMap::new(),
            heads: BTreeMap::new(),
            evidence: BTreeMap::new(),
            decisions: BTreeMap::new(),
            adjustments: Vec::new(),
            blockers: BTreeMap::new(),
        })
    }
    pub fn config(&self) -> &Value {
        &self.config
    }
    pub(crate) fn check_subject(&self, s: &Value) -> Result<(), Error> {
        for k in [
            "engine",
            "runtime",
            "account",
            "gateway",
            "runtime_kind",
            "generation",
        ] {
            if s[k] != self.config[k] {
                return Err(err("FEE_OWNER_CONTEXT"));
            }
        }
        Ok(())
    }
    pub(crate) fn append(&mut self, command: Value) -> Result<Value, Error> {
        bound(&command, 0)?;
        let order = if command["kind"] == "ASSESS" {
            &command["input"]["binding"]["subject"]["order"]
        } else {
            &command["input"]["order"]
        };
        if !order.is_null()
            && self.orders.len() >= self.capacity
            && !self.orders.contains_key(text(order)?)
        {
            return Err(err("FEE_CAPACITY"));
        }
        let mut candidate = self.clone();
        let result = candidate.execute(&command)?;
        candidate.history.push(command);
        bound(&candidate.checkpoint(), 0)?;
        *self = candidate;
        Ok(result)
    }
    fn execute(&mut self, c: &Value) -> Result<Value, Error> {
        fields(c, &["kind", "input"])?;
        match text(&c["kind"])? {
            "ASSESS" => {
                let a = Catalog::read_assessment(&c["input"])?;
                self.accrue(&a.value)
            }
            "ADMITTED_TARGET" => self.admitted(&c["input"]),
            "RECONCILE" => self.reconcile_inner(&c["input"]),
            _ => Err(err("FEE_OPERATION")),
        }
    }
    pub fn apply(&mut self, a: &Assessment) -> Result<Application, Error> {
        let trade = text(&a.value["trade"])?;
        let key = format!("native:{trade}");
        if let Some(old) = self.applications.get(&key) {
            if old["input"] != a.value {
                return Err(err("FEE_TRADE_CONFLICT"));
            }
            return Ok(Application {
                value: old["result"].clone(),
            });
        }
        Ok(Application {
            value: self.append(json!({"kind":"ASSESS","input":a.value}))?,
        })
    }
    fn accrue(&mut self, a: &Value) -> Result<Value, Error> {
        let subject = &a["binding"]["subject"];
        self.check_subject(subject)?;
        let order = text(&subject["order"])?;
        let trade = text(&a["trade"])?;
        let key = format!("native:{trade}");
        if self
            .applications
            .values()
            .any(|a| a["result"]["trade"] == trade)
        {
            return Err(err("FEE_TRADE_CONFLICT"));
        }
        let application_id = format!("FAPP-{}", digest(a));
        if self
            .applications
            .values()
            .any(|a| a["result"]["id"] == application_id)
        {
            return Err(err("FEE_APPLICATION_ID_CONFLICT"));
        }
        let p = currency(&subject["currency"])?;
        let binding = digest(&a["binding"]);
        let old = self.orders.get(order);
        if old.is_some_and(|o| o["binding"] != binding || o["subject"] != *subject) {
            return Err(err("FEE_ORDER_BINDING_CONFLICT"));
        }
        let zero = json!({"binding":binding,"subject":subject,"components":{},"quantity":"0","notional":"0","time":0});
        let mut state = old.unwrap_or(&zero).clone();
        if old.is_some() && instant(&a["time"])? < instant(&state["time"])? {
            return Err(err("FEE_TIME_REGRESSION"));
        }
        let quantity = num(&a["fill"]["quantity"])?;
        let notional = num(&a["fill"]["notional"])?;
        if quantity.is_zero()
            || num(&state["quantity"])? + &quantity != num(&a["cumulative"]["quantity"])?
            || num(&state["notional"])? + &notional != num(&a["cumulative"]["notional"])?
        {
            return Err(err("FEE_CUMULATIVE_BASIS_RELATION"));
        }
        let contracts = &a["fill"]["contracts"];
        let cumulative_contracts = &a["cumulative"]["contracts"];
        if contracts.is_null() != cumulative_contracts.is_null()
            || (old.is_some() && state["contracts"].is_null() != contracts.is_null())
        {
            return Err(err("FEE_CONTRACT_BASIS_RELATION"));
        }
        if !contracts.is_null() {
            let before = if old.is_none() {
                BigDecimal::zero()
            } else {
                num(&state["contracts"])?
            };
            if before + num(contracts)? != num(cumulative_contracts)? {
                return Err(err("FEE_CONTRACT_BASIS_RELATION"));
            }
        }
        state["contracts"] = cumulative_contracts.clone();
        let mut components = Vec::new();
        let mut charges = BigDecimal::zero();
        let mut rebates = BigDecimal::zero();
        for c in array(&a["components"])? {
            let identity = &c["identity"];
            let ck = digest(identity);
            let prior = &state["components"][&ck];
            let before = if prior.is_null() {
                BigDecimal::zero()
            } else {
                num(&prior["applied"])?
            };
            let target = num(&c["target"])?;
            let delta = if identity["scope"] == "FILL" {
                target.clone()
            } else {
                &target - &before
            };
            if delta < BigDecimal::zero() {
                return Err(err("FEE_ACCRUAL_NEGATIVE_INCREMENT"));
            }
            let after = &before + &delta;
            state["components"][&ck] = json!({"identity":identity,"applied":amount(&after,p)?});
            if identity["direction"] == "CHARGE" {
                charges += &delta;
            } else {
                rebates += &delta;
            }
            components.push(json!({"identity":identity,"amount":amount(&delta,p)?,"before":amount(&before,p)?,"after":amount(&after,p)?}));
        }
        state["quantity"] = a["cumulative"]["quantity"].clone();
        state["notional"] = a["cumulative"]["notional"].clone();
        state["time"] = a["time"].clone();
        self.orders.insert(order.into(), state);
        let result = json!({"schema_version":1,"id":application_id,"trade":trade,"order":order,"subject":subject,"time":a["time"],"charges":amount(&charges,p)?,"rebates":amount(&rebates,p)?,"components":components,"detail_available":true,"assessment":digest(a)});
        self.applications
            .insert(key, json!({"input":a,"result":result}));
        Ok(result)
    }
    /// Trusted owning Runtime admission of the current normalized cumulative-source contract.
    /// A source hash validates integrity only. The Runtime must authenticate the source before entry.
    /// This explicit aggregate path cannot claim detailed component evidence for reconciliation.
    pub fn apply_admitted_target(&mut self, proof: &Value) -> Result<Application, Error> {
        let key = format!("admitted:{}", text(&proof["trade"])?);
        if let Some(old) = self.applications.get(&key) {
            if old["input"] != *proof {
                return Err(err("FEE_TRADE_CONFLICT"));
            }
            return Ok(Application {
                value: old["result"].clone(),
            });
        }
        Ok(Application {
            value: self.append(json!({"kind":"ADMITTED_TARGET","input":proof}))?,
        })
    }
    fn admitted(&mut self, p: &Value) -> Result<Value, Error> {
        fields(
            p,
            &[
                "schema_version",
                "instruction",
                "source_ref",
                "policy",
                "order",
                "trade",
                "currency",
                "charge_target",
                "rebate_target",
                "scope",
                "family",
                "version",
                "as_of_sequence",
                "source_digest",
            ],
        )?;
        if p["schema_version"] != 1
            || p["family"] != "ORDER_FEE_ACCRUAL"
            || unsigned(&p["version"])? == 0
            || unsigned(&p["as_of_sequence"])? == 0
        {
            return Err(err("FEE_TARGET_SOURCE"));
        }
        self.check_subject(&p["scope"])?;
        fields(
            &p["scope"],
            &[
                "schema_version",
                "engine",
                "runtime",
                "account",
                "gateway",
                "generation",
                "runtime_kind",
                "cluster",
                "revision",
                "instrument",
                "request",
            ],
        )?;
        if p["scope"]["schema_version"] != 1 {
            return Err(err("FEE_TARGET_SCOPE"));
        }
        for v in p["scope"]
            .as_object()
            .expect("scope")
            .values()
            .filter(|v| v.is_string())
        {
            text(v)?;
        }
        one(&p["scope"]["runtime_kind"], &["BACKTEST", "SIM", "LIVE"])?;
        let mut content = p.clone();
        content
            .as_object_mut()
            .expect("record")
            .remove("source_digest");
        if p["source_digest"] != digest(&content) {
            return Err(err("FEE_SOURCE_DIGEST"));
        }
        let policy = text(&p["policy"])?;
        if policy.len() != 64
            || !policy
                .bytes()
                .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        {
            return Err(err("FEE_POLICY_DIGEST"));
        }
        let order = text(&p["order"])?;
        let trade = text(&p["trade"])?;
        text(&p["instruction"])?;
        text(&p["source_ref"])?;
        let precision = currency(&p["currency"])?;
        if self
            .applications
            .values()
            .any(|a| a["result"]["trade"] == trade || a["result"]["id"] == p["instruction"])
        {
            return Err(err("FEE_TRADE_OR_APPLICATION_CONFLICT"));
        }
        exact_amount(&num(&p["charge_target"])?, precision)?;
        exact_amount(&num(&p["rebate_target"])?, precision)?;
        for a in self.applications.values() {
            let old = &a["input"];
            if old["instruction"] == p["instruction"] || old["source_ref"] == p["source_ref"] {
                return Err(err("FEE_SOURCE_ALIAS"));
            }
        }
        let zero = json!({"scope":p["scope"],"currency":p["currency"],"policy":p["policy"],"charges":"0","rebates":"0"});
        let old = self.orders.get(order).unwrap_or(&zero);
        if old["scope"] != p["scope"]
            || old["currency"] != p["currency"]
            || old["policy"] != p["policy"]
        {
            return Err(err("FEE_ORDER_BINDING_CONFLICT"));
        }
        let charge = num(&p["charge_target"])?;
        let rebate = num(&p["rebate_target"])?;
        let charges = &charge - num(&old["charges"])?;
        let rebates = &rebate - num(&old["rebates"])?;
        if charges < BigDecimal::zero() || rebates < BigDecimal::zero() {
            return Err(err("FEE_ACCRUAL_NEGATIVE_INCREMENT"));
        }
        let result = json!({"schema_version":1,"id":p["instruction"],"trade":trade,"order":order,"subject":p["scope"],"time":p["as_of_sequence"],"charges":amount(&charges,precision)?,"rebates":amount(&rebates,precision)?,"components":[],"detail_available":false,"assessment":digest(p)});
        self.orders.insert(order.into(),json!({"scope":p["scope"],"currency":p["currency"],"policy":p["policy"],"charges":amount(&charge,precision)?,"rebates":amount(&rebate,precision)?}));
        self.applications.insert(
            format!("admitted:{trade}"),
            json!({"input":p,"result":result}),
        );
        Ok(result)
    }
    pub fn checkpoint(&self) -> Value {
        json!({"schema_version":1,"config":self.config,"capacity":self.capacity,"history":self.history,"state_hash":digest(&json!([self.applications,self.orders,self.heads,self.evidence,self.decisions,self.adjustments,self.blockers]))})
    }
    pub fn restore(&mut self, v: &Value, expected: &str) -> Result<(), Error> {
        bound(v, 0)?;
        fields(
            v,
            &[
                "schema_version",
                "config",
                "capacity",
                "history",
                "state_hash",
            ],
        )?;
        if v["schema_version"] != 1
            || digest(v) != expected
            || v["config"] != self.config
            || v["capacity"] != self.capacity
        {
            return Err(err("FEE_CHECKPOINT_CONTEXT"));
        }
        if !self.history.is_empty() {
            if self.checkpoint() == *v {
                return Ok(());
            }
            return Err(err("FEE_RESTORE_FRESH_ONLY"));
        }
        let mut fresh = Self::new(self.config.clone(), self.capacity)?;
        for c in array(&v["history"])? {
            fresh.append(c.clone())?;
        }
        if fresh.checkpoint() != *v {
            return Err(err("FEE_CHECKPOINT_NONCANONICAL"));
        }
        *self = fresh;
        Ok(())
    }
    pub fn query(&self, s: &Value) -> Result<Vec<Value>, Error> {
        validate_query(s)?;
        if s["account"] != self.config["account"] {
            return Err(err("FEE_QUERY_OWNER"));
        }
        // Aggregate admission proves economics but not broker or economic time.
        // Missing proof cannot certify that a typed scope has no matching facts.
        if self
            .applications
            .values()
            .any(|a| a["result"]["detail_available"] != true)
        {
            return Err(err("FEE_QUERY_PROOF_UNAVAILABLE"));
        }
        Ok(self
            .applications
            .values()
            .map(|a| &a["result"])
            .filter(|a| matches_query(a, s))
            .cloned()
            .collect())
    }
    pub fn adjustments(&self) -> Vec<Value> {
        self.adjustments.clone()
    }
    pub fn decisions(&self) -> Vec<Value> {
        self.decisions.values().cloned().collect()
    }
    pub fn active_blockers(&self) -> Vec<Value> {
        self.blockers.values().cloned().collect()
    }
    pub fn permits(&self, risk_change: &str) -> Result<bool, Error> {
        if ![
            "RISK_REDUCING",
            "RISK_INCREASING",
            "RISK_NEUTRAL",
            "UNKNOWN",
        ]
        .contains(&risk_change)
        {
            return Err(err("FEE_RISK_CLASSIFICATION"));
        }
        Ok(self.blockers.is_empty() || risk_change == "RISK_REDUCING")
    }
}
pub(crate) fn validate_query(s: &Value) -> Result<(), Error> {
    let kind = text(&s["kind"])?;
    let common = ["kind", "id", "account", "broker", "currency"];
    if kind == "STATEMENT" {
        fields(
            s,
            &[
                "kind",
                "id",
                "account",
                "broker",
                "currency",
                "fingerprint",
                "from",
                "to",
            ],
        )?;
        if instant(&s["from"])? >= instant(&s["to"])? {
            return Err(err("FEE_STATEMENT_INTERVAL"));
        }
        let fp = text(&s["fingerprint"])?;
        let mut body = s.clone();
        body.as_object_mut().expect("scope").remove("fingerprint");
        if fp.len() != 64 || fp != digest(&body) {
            return Err(err("FEE_STATEMENT_FINGERPRINT"));
        }
    } else {
        one(&s["kind"], &["ORDER", "TRADE"])?;
        fields(s, &common)?;
    }
    for k in common {
        text(&s[k])?;
    }
    Ok(())
}
pub(crate) fn matches_query(a: &Value, s: &Value) -> bool {
    let subject = &a["subject"];
    if subject["account"] != s["account"]
        || subject["broker"] != s["broker"]
        || subject["currency"]["code"] != s["currency"]
    {
        return false;
    }
    match s["kind"].as_str() {
        Some("ORDER") => a["order"] == s["id"],
        Some("TRADE") => a["trade"] == s["id"],
        Some("STATEMENT") => instant(&a["time"]).is_ok_and(|t| {
            instant(&s["from"]).is_ok_and(|from| t >= from)
                && instant(&s["to"]).is_ok_and(|to| t < to)
        }),
        _ => false,
    }
}
