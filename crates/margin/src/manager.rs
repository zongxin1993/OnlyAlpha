use crate::model::*;
use bigdecimal::{BigDecimal, Zero};
use num_bigint::BigInt;
use onlyalpha_domain::base::OnlyDomainModel;
use serde_json::{Value, json};
use std::collections::BTreeMap;

#[derive(Clone, Debug)]
pub struct Effect {
    value: Value,
    replay: Value,
}
impl Effect {
    /// Replayable producer input, bound to the entire before/after history.
    pub fn replay_input(&self) -> Value {
        self.replay.clone()
    }
    pub fn record(&self) -> Value {
        self.value.clone()
    }
}
#[derive(Clone)]
pub struct Manager {
    config: Value,
    capacity: usize,
    states: BTreeMap<String, Value>,
    records: Vec<Value>,
}
impl Manager {
    pub fn new(config: Value, capacity: usize) -> Result<Self, Error> {
        bounded(&config, 2048)?;
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
            || currency(&config["currency"])? > 18
        {
            return Err(err("MARGIN_CONFIG"));
        }
        Ok(Self {
            config,
            capacity,
            states: BTreeMap::new(),
            records: vec![],
        })
    }
    pub fn snapshot(&self, id: &str) -> Result<Value, Error> {
        self.states
            .get(id)
            .cloned()
            .ok_or_else(|| err("MARGIN_RESERVATION_UNKNOWN"))
    }
    pub fn snapshots(&self) -> Vec<Value> {
        self.states.values().cloned().collect()
    }
    pub fn release_quote(&self, id: &str, quantity: &str) -> Result<Value, Error> {
        let state = self.snapshot(id)?;
        let p = currency(&self.config["currency"])?;
        let precision = u8::try_from(uint(&state["quantity_precision"])?)
            .map_err(|_| err("MARGIN_QUANTITY_PRECISION"))?;
        let part = units(&json!(quantity), precision)?;
        let whole = units(&state["open"], precision)?;
        if part == 0 || part > whole {
            return Err(err("MARGIN_RELEASE_QUANTITY"));
        }
        Ok(
            json!({"amount":proportional(&number(&state["occupied"])?,part,whole,p)?.to_plain_string(),"maintenance":proportional(&number(&state["maintenance"])?,part,whole,p)?.to_plain_string(),"version":state["version"],"before_hash":digest(&state)}),
        )
    }
    pub fn checkpoint(&self) -> Value {
        json!({"schema_version":1,"config":self.config,"capacity":self.capacity,"states":self.states,"records":self.records})
    }
    pub fn apply(&mut self, input: &Value) -> Result<Effect, Error> {
        bounded(input, 8192)?;
        fields(
            input,
            &[
                "schema_version",
                "id",
                "scope",
                "reservation",
                "source_order",
                "source_trade",
                "source_ref",
                "source_fingerprint",
                "mode",
                "isolation",
                "position_side",
                "action",
                "quantity",
                "quantity_precision",
                "amount",
                "maintenance",
                "time",
                "expected_version",
                "before_hash",
            ],
        )?;
        if input["schema_version"] != 1 {
            return Err(err("MARGIN_SCHEMA"));
        }
        scope(&input["scope"])?;
        bounded(&input["scope"], 2048)?;
        for k in OWNER {
            if self.config[k] != input["scope"][k] {
                return Err(err("MARGIN_OWNER"));
            }
        }
        let _: onlyalpha_domain::identifiers::OnlyInstrumentId =
            external(text(&input["scope"]["instrument"])?.parse())?;
        for k in ["id", "source_order", "source_ref"] {
            id(&input[k])?;
        }
        fingerprint(&input["source_fingerprint"])?;
        let action = text(&input["action"])?;
        if !matches!(
            action,
            "RESERVE" | "OCCUPY" | "RELEASE_RESERVED" | "RELEASE_OCCUPIED"
        ) {
            return Err(err("MARGIN_ACTION"));
        }
        if !matches!(text(&input["mode"])?, "CROSS" | "ISOLATED")
            || !matches!(text(&input["position_side"])?, "LONG" | "SHORT")
        {
            return Err(err("MARGIN_MODE_OR_SIDE"));
        }
        if input["mode"] == "CROSS" {
            if !input["isolation"].is_null() {
                return Err(err("MARGIN_ISOLATION"));
            }
        } else {
            id(&input["isolation"])?;
        }
        if matches!(action, "OCCUPY" | "RELEASE_OCCUPIED") {
            id(&input["source_trade"])?;
        } else if !input["source_trade"].is_null() {
            return Err(err("MARGIN_TRADE_FAMILY"));
        }
        let p = currency(&self.config["currency"])?;
        let precision = u8::try_from(uint(&input["quantity_precision"])?)
            .map_err(|_| err("MARGIN_QUANTITY_PRECISION"))?;
        let mut command = input.clone();
        for k in ["amount", "maintenance"] {
            command[k] = money(&input[k], p)?;
        }
        command["quantity"] = json!(number(&input["quantity"])?.normalized().to_plain_string());
        let quanta = units(&command["quantity"], precision)?;
        let at = time(&input["time"])?;
        command["time"] = at.to_record()["unix_nanos"].clone();
        if action == "RESERVE" {
            if !input["reservation"].is_null() {
                return Err(err("MARGIN_RESERVE_ID"));
            }
            command["reservation"] = json!(format!(
                "MRES-{}",
                digest(
                    &json!({"scope":input["scope"],"order":input["source_order"],"currency":self.config["currency"],"mode":input["mode"],"isolation":input["isolation"],"position_side":input["position_side"]})
                )
            ));
        } else {
            id(&input["reservation"])?;
        }
        let mut replay_command = command.clone();
        if action == "RESERVE" {
            replay_command["reservation"] = Value::Null;
        }
        if let Some(row) = self
            .records
            .iter()
            .find(|r| r["command"]["id"] == command["id"])
        {
            return if row["command"] == command {
                Ok(Effect {
                    value: row["result"].clone(),
                    replay: {
                        let index = self
                            .records
                            .iter()
                            .position(|r| r["command"]["id"] == command["id"])
                            .expect("found record");
                        let mut prior = Self::new(self.config.clone(), self.capacity)?;
                        for entry in &self.records[..index] {
                            let mut c = entry["command"].clone();
                            if c["action"] == "RESERVE" {
                                c["reservation"] = Value::Null;
                            }
                            prior.apply(&c)?;
                        }
                        let mut c = command.clone();
                        if c["action"] == "RESERVE" {
                            c["reservation"] = Value::Null;
                        }
                        prior.apply(&c)?.replay_input()
                    },
                })
            } else {
                Err(err("MARGIN_INSTRUCTION_CONFLICT"))
            };
        }
        let key = text(&command["reservation"])?;
        let old = self.states.get(key).cloned().unwrap_or(Value::Null);
        let expected = uint(&input["expected_version"])?;
        if expected != old["version"].as_u64().unwrap_or(0)
            || command["before_hash"]
                != if old.is_null() {
                    Value::Null
                } else {
                    json!(digest(&old))
                }
        {
            return Err(err("MARGIN_BEFORE_PROOF"));
        }
        if !old.is_null() && at < time(&old["time"])? {
            return Err(err("MARGIN_TIME_REGRESSION"));
        }
        for row in &self.records {
            let c = &row["command"];
            if c["source_ref"] == command["source_ref"] {
                return Err(err("MARGIN_SOURCE_ALIAS"));
            }
            if !command["source_trade"].is_null()
                && c["source_trade"] == command["source_trade"]
                && (c["action"] != command["action"]
                    || c["source_order"] != command["source_order"]
                    || c["scope"]["cluster"] != command["scope"]["cluster"]
                    || c["scope"]["revision"] != command["scope"]["revision"]
                    || c["scope"]["instrument"] != command["scope"]["instrument"]
                    || c["mode"] != command["mode"]
                    || c["isolation"] != command["isolation"]
                    || c["position_side"] != command["position_side"]
                    || c["reservation"] == command["reservation"]
                    || action != "RELEASE_OCCUPIED")
            {
                return Err(err("MARGIN_TRADE_ALIAS"));
            }
        }
        let amount = number(&command["amount"])?;
        let maintenance = number(&command["maintenance"])?;
        let mut state = old.clone();
        if action == "RESERVE" {
            if !old.is_null()
                || quanta == 0
                || amount == BigDecimal::zero()
                || maintenance != BigDecimal::zero()
                || self
                    .states
                    .values()
                    .any(|s| s["order"] == command["source_order"])
            {
                return Err(err("MARGIN_RESERVE"));
            }
            state = json!({"schema_version":1,"id":key,"scope":command["scope"],"order":command["source_order"],"currency":self.config["currency"],"mode":command["mode"],"isolation":command["isolation"],"position_side":command["position_side"],"quantity_precision":precision,"quantity":command["quantity"],"unfilled":command["quantity"],"open":"0","closed":"0","cancelled":"0","original":command["amount"],"reserved":command["amount"],"occupied":money(&json!("0"),p)?,"released":money(&json!("0"),p)?,"maintenance":money(&json!("0"),p)?,"reserved_released":false,"version":1,"created_at":command["time"],"time":command["time"]});
        } else {
            if old.is_null() {
                return Err(err("MARGIN_RESERVATION_UNKNOWN"));
            }
            for k in [
                "scope",
                "mode",
                "isolation",
                "position_side",
                "quantity_precision",
            ] {
                if old[k] != command[k] {
                    return Err(err("MARGIN_RESERVATION_CONTEXT"));
                }
            }
            let quantity = number(&command["quantity"])?;
            if action != "RELEASE_OCCUPIED" && old["order"] != command["source_order"] {
                return Err(err("MARGIN_ORDER_OWNER"));
            }
            match action {
                "OCCUPY" => {
                    if old["reserved_released"] == true
                        || quanta == 0
                        || quantity > number(&old["unfilled"])?
                        || amount > number(&old["reserved"])?
                        || maintenance > amount
                    {
                        return Err(err("MARGIN_OCCUPY"));
                    }
                    set_number(
                        &mut state,
                        "unfilled",
                        number(&old["unfilled"])? - &quantity,
                    );
                    set_number(&mut state, "open", number(&old["open"])? + quantity);
                    set_money(
                        &mut state,
                        "reserved",
                        number(&old["reserved"])? - &amount,
                        p,
                    );
                    set_money(
                        &mut state,
                        "occupied",
                        number(&old["occupied"])? + amount,
                        p,
                    );
                    set_money(
                        &mut state,
                        "maintenance",
                        number(&old["maintenance"])? + maintenance,
                        p,
                    );
                }
                "RELEASE_RESERVED" => {
                    if old["reserved_released"] == true
                        || quantity != number(&old["unfilled"])?
                        || amount != number(&old["reserved"])?
                        || maintenance != BigDecimal::zero()
                    {
                        return Err(err("MARGIN_RESERVED_RELEASE"));
                    }
                    set_number(
                        &mut state,
                        "cancelled",
                        number(&old["cancelled"])? + quantity,
                    );
                    state["unfilled"] = json!("0");
                    set_money(&mut state, "reserved", BigDecimal::zero(), p);
                    set_money(
                        &mut state,
                        "released",
                        number(&old["released"])? + amount,
                        p,
                    );
                    state["reserved_released"] = json!(true);
                }
                "RELEASE_OCCUPIED" => {
                    let whole = units(&old["open"], precision)?;
                    if quanta == 0
                        || quanta > whole
                        || command["source_order"] == old["order"]
                        || amount != proportional(&number(&old["occupied"])?, quanta, whole, p)?
                        || maintenance
                            != proportional(&number(&old["maintenance"])?, quanta, whole, p)?
                    {
                        return Err(err("MARGIN_OCCUPIED_RELEASE"));
                    }
                    set_number(&mut state, "open", number(&old["open"])? - &quantity);
                    set_number(&mut state, "closed", number(&old["closed"])? + quantity);
                    set_money(
                        &mut state,
                        "occupied",
                        number(&old["occupied"])? - &amount,
                        p,
                    );
                    set_money(
                        &mut state,
                        "released",
                        number(&old["released"])? + amount,
                        p,
                    );
                    set_money(
                        &mut state,
                        "maintenance",
                        number(&old["maintenance"])? - maintenance,
                        p,
                    );
                }
                _ => return Err(err("MARGIN_ACTION")),
            }
            state["version"] = json!(
                expected
                    .checked_add(1)
                    .ok_or_else(|| err("MARGIN_VERSION"))?
            );
            state["time"] = command["time"].clone();
        }
        if number(&state["original"])?
            != number(&state["reserved"])?
                + number(&state["occupied"])?
                + number(&state["released"])?
            || number(&state["quantity"])?
                != number(&state["unfilled"])?
                    + number(&state["open"])?
                    + number(&state["closed"])?
                    + number(&state["cancelled"])?
        {
            return Err(err("MARGIN_CONSERVATION"));
        }
        state["status"] = json!(if number(&state["unfilled"])? == BigDecimal::zero()
            && number(&state["open"])? == BigDecimal::zero()
            && number(&state["reserved"])? == BigDecimal::zero()
            && number(&state["occupied"])? == BigDecimal::zero()
        {
            "CLOSED"
        } else if number(&state["released"])? > BigDecimal::zero() {
            "PARTIALLY_RELEASED"
        } else if number(&state["occupied"])? > BigDecimal::zero() {
            "OCCUPIED"
        } else {
            "RESERVED"
        });
        bounded(&state, 8192)?;
        let before_projection = projection(&old);
        let after_projection = projection(&state);
        let mut result = json!({"schema_version":1,"instruction":command["id"],"before_hash":command["before_hash"],"after":state,"projection_before":before_projection,"projection_after":after_projection,"source_ref":command["source_ref"],"source_fingerprint":command["source_fingerprint"]});
        result["id"] = json!(format!("MAPL-{}", digest(&result)));
        let record = json!({"command":command,"result":result});
        bounded(&record, 32768)?;
        let mut candidate = self.clone();
        candidate.states.insert(key.into(), state);
        candidate.records.push(record);
        candidate.check_budget()?;
        bounded(&candidate.checkpoint(), 33554432)?;
        let replay = json!({"schema_version":1,"config":self.config,"capacity":self.capacity,"before_hash":digest(&self.checkpoint()),"command":replay_command,"after_hash":digest(&candidate.checkpoint())});
        *self = candidate;
        Ok(Effect {
            value: result,
            replay,
        })
    }
    fn check_budget(&self) -> Result<(), Error> {
        let mut budget = self.records.len() as u64;
        for state in self.states.values() {
            let p = u8::try_from(uint(&state["quantity_precision"])?)
                .map_err(|_| err("MARGIN_QUANTITY_PRECISION"))?;
            let remaining = units(&state["unfilled"], p)?
                .checked_mul(2)
                .and_then(|v| v.checked_add(units(&state["open"], p).ok()?))
                .and_then(|v| v.checked_add(u64::from(state["reserved_released"] == false)))
                .ok_or_else(|| err("MARGIN_ADMISSION_CAPACITY"))?;
            budget = budget
                .checked_add(remaining)
                .ok_or_else(|| err("MARGIN_ADMISSION_CAPACITY"))?;
            if budget > self.capacity as u64 {
                return Err(err("MARGIN_ADMISSION_CAPACITY"));
            }
        }
        Ok(())
    }
    pub fn restore(&mut self, v: &Value, expected: &str) -> Result<(), Error> {
        bounded(v, 33554432)?;
        fields(
            v,
            &["schema_version", "config", "capacity", "states", "records"],
        )?;
        if v["schema_version"] != 1
            || v["config"] != self.config
            || v["capacity"] != self.capacity
            || digest(v) != expected
        {
            return Err(err("MARGIN_CHECKPOINT_CONTEXT"));
        }
        if !self.records.is_empty() || !self.states.is_empty() {
            return if self.checkpoint() == *v {
                Ok(())
            } else {
                Err(err("MARGIN_RESTORE_FRESH_ONLY"))
            };
        }
        let rows = v["records"]
            .as_array()
            .filter(|a| a.len() <= self.capacity)
            .ok_or_else(|| err("MARGIN_CHECKPOINT_RECORDS"))?;
        let mut fresh = Self::new(self.config.clone(), self.capacity)?;
        for row in rows {
            fields(row, &["command", "result"])?;
            let mut input = row["command"].clone();
            if input["action"] == "RESERVE" {
                input["reservation"] = Value::Null;
            }
            let effect = fresh.apply(&input)?;
            if effect.record() != row["result"] {
                return Err(err("MARGIN_CHECKPOINT_RESULT"));
            }
        }
        if fresh.checkpoint() != *v {
            return Err(err("MARGIN_CHECKPOINT_NONCANONICAL"));
        }
        *self = fresh;
        Ok(())
    }
}
fn set_number(v: &mut Value, k: &str, n: BigDecimal) {
    v[k] = json!(n.normalized().to_plain_string());
}
fn set_money(v: &mut Value, k: &str, n: BigDecimal, p: u8) {
    v[k] = json!(n.with_scale(i64::from(p)).to_plain_string());
}
fn projection(state: &Value) -> Value {
    if state.is_null() {
        return Value::Null;
    }
    let mut result = json!({});
    for k in [
        "schema_version",
        "id",
        "scope",
        "order",
        "currency",
        "mode",
        "isolation",
        "position_side",
        "original",
        "reserved",
        "occupied",
        "released",
        "maintenance",
        "version",
    ] {
        result[k] = state[k].clone();
    }
    result
}
fn proportional(total: &BigDecimal, part: u64, whole: u64, p: u8) -> Result<BigDecimal, Error> {
    if whole == 0 {
        return Err(err("MARGIN_RELEASE_QUANTITY"));
    }
    let minor = external(
        total
            .with_scale(i64::from(p))
            .as_bigint_and_exponent()
            .0
            .to_string()
            .parse::<BigInt>(),
    )?;
    let numerator = minor * BigInt::from(part);
    let denominator = BigInt::from(whole);
    let mut q = &numerator / &denominator;
    let twice = (&numerator % &denominator) * 2;
    if twice > denominator || (twice == denominator && &q % 2 != BigInt::zero()) {
        q += 1;
    }
    Ok(BigDecimal::new(q, i64::from(p)))
}
