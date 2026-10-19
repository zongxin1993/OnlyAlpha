use crate::model::*;
use bigdecimal::{BigDecimal, Zero};
use onlyalpha_domain::base::OnlyDomainModel;
use serde_json::{Value, json};
use std::collections::BTreeMap;
#[derive(Clone)]
pub struct Authority {
    config: Value,
    capacity: usize,
    instructions: BTreeMap<String, Value>,
    orders: BTreeMap<String, Value>,
}
impl Authority {
    pub fn new(config: Value, capacity: usize) -> Result<Self, Error> {
        fields(
            &config,
            &[
                "engine",
                "runtime",
                "account",
                "gateway",
                "generation",
                "runtime_kind",
                "currency",
            ],
        )?;
        for k in OWNER {
            id(&config[k])?;
        }
        fingerprint(&config["generation"])?;
        if !matches!(text(&config["runtime_kind"])?, "BACKTEST" | "SIM" | "LIVE")
            || capacity == 0
            || capacity > 512
        {
            return Err(err("SETTLEMENT_CONFIG"));
        }
        currency(&config["currency"])?;
        Ok(Self {
            config,
            capacity,
            instructions: BTreeMap::new(),
            orders: BTreeMap::new(),
        })
    }

    /// Resource admission before external submission. Quantity precision is the owning Instrument's.
    /// A positive canonical Fill consumes at least one quantum; total remaining quanta bound future slots.
    pub fn admit_order(
        &mut self,
        scope_value: Value,
        order: &str,
        side: &str,
        quantity: &str,
        precision: u8,
    ) -> Result<(), Error> {
        scope(&scope_value)?;
        id(&json!(order))?;
        if OWNER.iter().any(|k| self.config[k] != scope_value[k]) || !matches!(side, "BUY" | "SELL")
        {
            return Err(err("SETTLEMENT_ORDER_OWNER"));
        }
        let q = number(&json!(quantity))?;
        let amount = json!(q.normalized().to_plain_string());
        if units(&amount, precision)? == 0 {
            return Err(err("SETTLEMENT_ORDER_QUANTITY"));
        }
        let ordinal = self
            .orders
            .get(order)
            .map(|v| v["ordinal"].clone())
            .unwrap_or_else(|| json!(self.orders.len() + 1));
        let value = json!({"ordinal":ordinal,"order":order,"scope":scope_value,"side":side,"quantity":amount,"precision":precision});
        bounded(&value, 2048)?;
        if let Some(old) = self.orders.get(order) {
            return if *old == value {
                Ok(())
            } else {
                Err(err("SETTLEMENT_ORDER_BINDING_CONFLICT"))
            };
        }
        if self.orders.len() >= self.capacity {
            return Err(err("SETTLEMENT_ADMISSION_CAPACITY"));
        }
        let mut candidate = self.clone();
        candidate.orders.insert(order.into(), value);
        candidate.check_budget()?;
        candidate.check_size()?;
        *self = candidate;
        Ok(())
    }
    fn check_budget(&self) -> Result<(), Error> {
        let mut slots = self.instructions.len() as u64;
        for (id, order) in &self.orders {
            let precision = u8::try_from(uint(&order["precision"])?)
                .map_err(|_| err("SETTLEMENT_QUANTITY_PRECISION"))?;
            let mut remaining = units(&order["quantity"], precision)?;
            for item in self
                .instructions
                .values()
                .filter(|v| v["instruction"]["input"]["order"] == *id)
            {
                remaining = remaining
                    .checked_sub(units(&item["instruction"]["input"]["quantity"], precision)?)
                    .ok_or_else(|| err("SETTLEMENT_ORDER_OVERFILL"))?;
            }
            slots = slots
                .checked_add(remaining)
                .ok_or_else(|| err("SETTLEMENT_ADMISSION_CAPACITY"))?;
            if slots > self.capacity as u64 {
                return Err(err("SETTLEMENT_ADMISSION_CAPACITY"));
            }
        }
        Ok(())
    }
    pub fn register(&mut self, instruction: &Instruction) -> Result<(), Error> {
        let input = &instruction.value["input"];
        if OWNER.iter().any(|k| self.config[k] != input["scope"][k])
            || self.config["currency"] != input["currency"]
        {
            return Err(err("SETTLEMENT_OWNER_CONTEXT"));
        }
        if let Some(old) = self.instructions.get(instruction.id()) {
            if old["instruction"] != instruction.value {
                return Err(err("SETTLEMENT_INSTRUCTION_CONFLICT"));
            }
            return Ok(());
        }
        for old in self.instructions.values() {
            let prior = &old["instruction"]["input"];
            if prior["trade"] == input["trade"]
                || prior["provenance"]["reference"] == input["provenance"]["reference"]
                || prior["provenance"]["instruction"] == input["provenance"]["instruction"]
            {
                return Err(err("SETTLEMENT_TRADE_OR_SOURCE_CONFLICT"));
            }
            if prior["policy"]["id"] == input["policy"]["id"]
                && prior["policy"]["version"] == input["policy"]["version"]
                && prior["policy"] != input["policy"]
            {
                return Err(err("SETTLEMENT_POLICY_VERSION_CONFLICT"));
            }
            if prior["calendar"]["calendar_id"] == input["calendar"]["calendar_id"]
                && prior["calendar"]["calendar_version"] == input["calendar"]["calendar_version"]
                && prior["calendar"] != input["calendar"]
            {
                return Err(err("SETTLEMENT_CALENDAR_VERSION_CONFLICT"));
            }
        }

        let order = self
            .orders
            .get(text(&input["order"])?)
            .ok_or_else(|| err("SETTLEMENT_ORDER_NOT_ADMITTED"))?;
        if order["scope"] != input["scope"] || order["side"] != input["side"] {
            return Err(err("SETTLEMENT_ORDER_BINDING_CONFLICT"));
        }
        if units(
            &input["quantity"],
            u8::try_from(uint(&order["precision"])?)
                .map_err(|_| err("SETTLEMENT_QUANTITY_PRECISION"))?,
        )? == 0
        {
            return Err(err("SETTLEMENT_QUANTITY"));
        }
        if self.instructions.len() >= self.capacity {
            return Err(err("SETTLEMENT_ADMISSION_CAPACITY"));
        }
        let mut flags = json!({});
        for k in AXES {
            flags[k] =
                json!(day(&instruction.value["schedule"][k])? <= day(&input["trading_day"])?);
        }
        let status = status(&flags);
        let state = json!({"instruction":instruction.value,"flags":flags,"status":status,"version":1,"through":input["trading_day"],"time":input["time"],"maturities":[]});
        // Reserve the largest possible receipt before installing this fact. Dates and
        // timestamps each have a 256-byte input bound; versions cannot exceed seven.
        // Every subset of these six immutable transitions is smaller than this shape.
        let max_time: Value = serde_json::from_str(&"9".repeat(256)).expect("integer");
        let request = json!({"instruction":instruction.id(),"through":"9".repeat(256),"time":max_time,"expected_version":6});
        let transitions = AXES
            .iter()
            .map(|k| json!({"kind":k,"effective_on":instruction.value["schedule"][k]}))
            .collect::<Vec<_>>();
        bounded(&request, 1024)?;
        bounded(
            &maturity_body(&state, &request, json!(transitions), true, true)?,
            4096 - 80,
        )?;
        let mut candidate = self.clone();
        candidate
            .instructions
            .insert(instruction.id().into(), state);
        candidate.check_budget()?;
        candidate.check_size()?;
        *self = candidate;
        Ok(())
    }
    pub fn snapshot(&self, instruction: &str) -> Result<Value, Error> {
        self.instructions
            .get(instruction)
            .cloned()
            .ok_or_else(|| err("SETTLEMENT_INSTRUCTION_UNKNOWN"))
    }
    pub fn snapshots(&self) -> Vec<Value> {
        self.instructions.values().cloned().collect()
    }
    pub fn sequence_head(&self) -> u64 {
        self.instructions
            .values()
            .map(|s| s["version"].as_u64().expect("version") - 1)
            .sum()
    }
    pub fn due(&self, through: &str) -> Result<Vec<Value>, Error> {
        let end = day(&json!(through))?;
        let mut rows = vec![];
        for (id, s) in &self.instructions {
            for k in AXES {
                let effective = &s["instruction"]["schedule"][k];
                if s["flags"][k] == false && day(effective)? <= end {
                    rows.push(json!({"instruction":id,"transition":k,"effective_on":effective,"version":s["version"],"before_hash":digest(s),"scope":s["instruction"]["input"]["scope"]}));
                }
            }
        }
        rows.sort_by_key(|r| {
            (
                r["effective_on"].as_str().unwrap().to_owned(),
                r["instruction"].as_str().unwrap().to_owned(),
                r["transition"].as_str().unwrap().to_owned(),
            )
        });
        Ok(rows)
    }
    pub fn mature(
        &mut self,
        id: &str,
        through: &str,
        at: Value,
        expected_version: u64,
    ) -> Result<Maturity, Error> {
        let end = day(&json!(through))?;
        let t = time(&at)?;
        let at = t.to_record()["unix_nanos"].clone();
        let request = json!({"instruction":id,"through":through,"time":at,"expected_version":expected_version});
        let old = self
            .instructions
            .get(id)
            .ok_or_else(|| err("SETTLEMENT_INSTRUCTION_UNKNOWN"))?;
        for item in old["maturities"].as_array().expect("maturities") {
            if item["request"] == request {
                return Ok(Maturity {
                    value: item["result"].clone(),
                });
            }
        }
        if old["version"] != expected_version
            || end < day(&old["through"])?
            || t < time(&old["time"])?
        {
            return Err(err("SETTLEMENT_MATURITY_PRECONDITION"));
        }
        let mut state = old.clone();
        let mut transitions = vec![];
        for k in AXES {
            let effective = &old["instruction"]["schedule"][k];
            if old["flags"][k] == false && day(effective)? <= end {
                state["flags"][k] = json!(true);
                transitions.push(json!({"kind":k,"effective_on":effective}));
            }
        }
        if transitions.is_empty() {
            return Err(err("SETTLEMENT_NO_DUE_TRANSITION"));
        }
        let asset = old["flags"]["asset_trade_available"] == false
            && state["flags"]["asset_trade_available"] == true
            && old["instruction"]["input"]["side"] == "BUY";
        let cash = old["flags"]["cash_withdrawable"] == false
            && state["flags"]["cash_withdrawable"] == true;
        let body = maturity_body(old, &request, json!(transitions), asset, cash)?;
        bounded(&request, 1024)?;
        bounded(&body, 4096 - 80)?;
        let mut result = body.clone();
        result["id"] = json!(format!("SMAT-{}", digest(&body)));
        state["status"] = json!(status(&state["flags"]));
        state["version"] = json!(expected_version + 1);
        state["through"] = json!(through);
        state["time"] = at;
        state["maturities"]
            .as_array_mut()
            .expect("array")
            .push(json!({"request":request,"result":result}));
        bounded(&state, 49152)?;
        let mut candidate = self.clone();
        candidate.instructions.insert(id.into(), state);
        candidate.check_budget()?;
        candidate.check_size()?;
        *self = candidate;
        Ok(Maturity { value: result })
    }
    fn check_size(&self) -> Result<(), Error> {
        if self.checkpoint().to_string().len() > 33554432 {
            return Err(err("SETTLEMENT_CHECKPOINT_BOUND"));
        }
        Ok(())
    }
    pub fn checkpoint(&self) -> Value {
        json!({"schema_version":1,"config":self.config,"capacity":self.capacity,"orders":self.orders,"instructions":self.instructions})
    }

    pub fn restore(&mut self, v: &Value, expected: &str) -> Result<(), Error> {
        bounded(v, 33554432)?;
        fields(
            v,
            &[
                "schema_version",
                "config",
                "capacity",
                "orders",
                "instructions",
            ],
        )?;
        if v["schema_version"] != 1
            || digest(v) != expected
            || v["config"] != self.config
            || v["capacity"] != self.capacity
        {
            return Err(err("SETTLEMENT_CHECKPOINT_CONTEXT"));
        }
        if !self.instructions.is_empty() || !self.orders.is_empty() {
            return if self.checkpoint() == *v {
                Ok(())
            } else {
                Err(err("SETTLEMENT_RESTORE_FRESH_ONLY"))
            };
        }
        let rows = v["instructions"]
            .as_object()
            .filter(|r| r.len() <= self.capacity)
            .ok_or_else(|| err("SETTLEMENT_CHECKPOINT_INSTRUCTIONS"))?;
        let orders = v["orders"]
            .as_object()
            .filter(|r| r.len() <= self.capacity)
            .ok_or_else(|| err("SETTLEMENT_CHECKPOINT_ORDERS"))?;
        let mut ordered = Vec::new();
        for (key, value) in orders {
            fields(
                value,
                &["ordinal", "order", "scope", "side", "quantity", "precision"],
            )?;
            if value["order"] != *key {
                return Err(err("SETTLEMENT_CHECKPOINT_ORDER_ID"));
            }
            ordered.push((uint(&value["ordinal"])?, key, value));
        }
        ordered.sort_by_key(|row| row.0);
        let mut fresh = Self::new(self.config.clone(), self.capacity)?;
        // Replay complete preceding orders before later admissions. Remaining-quantity slots only decrease.
        for (ordinal, key, value) in ordered {
            if ordinal != fresh.orders.len() as u64 + 1 {
                return Err(err("SETTLEMENT_CHECKPOINT_ORDER_SEQUENCE"));
            }
            fresh.admit_order(
                value["scope"].clone(),
                key,
                text(&value["side"])?,
                text(&value["quantity"])?,
                u8::try_from(uint(&value["precision"])?)
                    .map_err(|_| err("SETTLEMENT_QUANTITY_PRECISION"))?,
            )?;
            if fresh.orders[key] != *value {
                return Err(err("SETTLEMENT_CHECKPOINT_ORDER_CANONICAL"));
            }
            for (id, state) in rows
                .iter()
                .filter(|(_, s)| s["instruction"]["input"]["order"] == *key)
            {
                let instruction = compile(state["instruction"]["input"].clone())?;
                if instruction.id() != id || instruction.value != state["instruction"] {
                    return Err(err("SETTLEMENT_CHECKPOINT_INSTRUCTION"));
                }
                fresh.register(&instruction)?;
                let events = state["maturities"]
                    .as_array()
                    .filter(|a| a.len() <= 6)
                    .ok_or_else(|| err("SETTLEMENT_CHECKPOINT_MATURITIES"))?;
                for e in events {
                    let q = &e["request"];
                    let effect = fresh.mature(
                        id,
                        text(&q["through"])?,
                        q["time"].clone(),
                        uint(&q["expected_version"])?,
                    )?;
                    if effect.value != e["result"] {
                        return Err(err("SETTLEMENT_CHECKPOINT_MATURITY"));
                    }
                }
            }
        }
        if fresh.checkpoint() != *v {
            return Err(err("SETTLEMENT_CHECKPOINT_NONCANONICAL"));
        }
        *self = fresh;
        Ok(())
    }
}
fn status(flags: &Value) -> &'static str {
    if AXES.iter().all(|k| flags[k] == true) {
        "COMPLETED"
    } else if AXES.iter().any(|k| flags[k] == true) {
        "PARTIALLY_EFFECTIVE"
    } else {
        "PENDING"
    }
}

fn maturity_body(
    old: &Value,
    request: &Value,
    transitions: Value,
    asset: bool,
    cash: bool,
) -> Result<Value, Error> {
    let input = &old["instruction"]["input"];
    let p = currency(&input["currency"])?;
    let credit = external(
        old["instruction"]["cash_flow"]
            .as_str()
            .expect("cash")
            .parse::<BigDecimal>(),
    )?
    .max(BigDecimal::zero());
    let id = &request["instruction"];
    let through = &request["through"];
    let at = &request["time"];
    let expected_version = uint(&request["expected_version"])?;
    let body = json!({"schema_version":1,"instruction":id,"scope":input["scope"],"order":input["order"],"trade":input["trade"],"position":input["position"],"position_cycle":input["position_cycle"],"allocation":input["allocation"],"allocation_cycle":input["allocation_cycle"],"currency":input["currency"],"before_version":expected_version,"after_version":expected_version+1,"before_hash":digest(old),"through":through,"time":at,"transitions":transitions,"asset_quantity":if asset{input["quantity"].clone()}else{json!("0")},"cash_amount":if cash{json!(credit.with_scale(i64::from(p)).to_plain_string())}else{money(&json!("0"),p)?}});
    Ok(body)
}
