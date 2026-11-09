use crate::model::*;
use bigdecimal::Zero;
use serde_json::{Value, json};
#[derive(Clone)]
pub struct Manager {
    pub(crate) config: Value,
    pub(crate) precision: u8,
    pub(crate) state: State,
    pub(crate) checkpoint_version: u8,
    // Rebuildable canonical byte count; neither state nor source authority.
    pub(crate) journal_bytes: usize,
    // Pure canonical encoding of this immutable state, never a source proof.
    pub(crate) checkpoint_cache:
        std::sync::OnceLock<std::sync::Arc<crate::recovery::CachedCheckpoint>>,
}
impl Manager {
    pub fn new(config: Value) -> Result<Self, Error> {
        Self::configured(config, 4)
    }
    fn configured(mut config: Value, checkpoint_version: u8) -> Result<Self, Error> {
        if config["schema_version"] == 3 && checkpoint_version != 5 {
            return Err(err("ACCOUNT_PERPETUAL_CHECKPOINT_FORMAT"));
        }

        let p = validate_config(&config)?;
        let cash = nonnegative(&config["initial_cash"], p)?;
        config["initial_cash"] = json!(formatted(&cash, p));
        let mut state = State::new(cash);
        state.perpetual = config["account_type"] == "LINEAR_PERPETUAL";
        Ok(Self {
            config,
            precision: p,
            state,
            checkpoint_version,
            journal_bytes: 0,
            checkpoint_cache: std::sync::OnceLock::new(),
        })
    }
    /// Explicit bounded self-contained dictionary format. Existing `new` stays schema4.
    pub fn new_checkpoint5(config: Value) -> Result<Self, Error> {
        Self::configured(config, 5)
    }
    pub(crate) fn fresh(&self) -> Result<Self, Error> {
        Self::configured(self.config.clone(), self.checkpoint_version)
    }
    pub fn snapshot(&self) -> Value {
        let mut snapshot = self.state.snapshot(self.precision);
        for field in [
            "engine",
            "runtime",
            "account",
            "gateway",
            "generation",
            "currency",
            "account_type",
        ] {
            snapshot[field] = self.config[field].clone();
        }
        if self.state.perpetual {
            let collateral = &self.state.cash + &self.state.market_value;
            let maintenance = self.state.margin_total("maintenance");
            snapshot["collateral"] = json!(formatted(&collateral, self.precision));
            let current = !self.state.flags.contains("MAINTENANCE_UNAVAILABLE");
            snapshot["maintenance_status"] = json!(if current { "CURRENT" } else { "UNAVAILABLE" });
            snapshot["last_confirmed_maintenance"] = self.state.last_confirmed_maintenance.clone();
            if !current {
                snapshot["maintenance_required"] = Value::Null;
            }
            snapshot["maintenance_to_equity"] = if current && collateral > Decimal::zero() {
                json!(
                    (maintenance / collateral)
                        .with_scale_round(8, bigdecimal::RoundingMode::HalfEven)
                        .to_plain_string()
                )
            } else {
                Value::Null
            };
        }
        snapshot
    }
    pub fn reservation(&self, id: &str) -> Option<Value> {
        self.state
            .reservations
            .get(id)
            .map(|r| r.record(self.precision))
    }
    /// Original accepted valuation intents in journal order. This borrowed data
    /// query neither encodes a checkpoint nor supplies a source or Ready proof.
    pub fn valuation_intents(&self) -> impl Iterator<Item = &Value> {
        self.state
            .journal
            .iter()
            .filter(|command| command["op"] == "VALUATION")
            .map(|command| &command["payload"]["intent"])
    }
    pub fn state(&self) -> Value {
        json!({"schema_version":1,"snapshot":self.snapshot(),"reservations":self.state.reservations.iter().map(|(k,r)|(k.clone(),r.record(self.precision))).collect::<std::collections::BTreeMap<_,_>>(),"receivables":self.state.receivables.iter().map(|(k,v)|(k.clone(),formatted(v,self.precision))).collect::<std::collections::BTreeMap<_,_>>(),"margin":self.state.margin,"margin_owner":self.state.margin_owner,"position_trades":self.state.position_trades,"receipts":self.state.receipts,"semantic":self.state.semantic,"broker":self.state.broker,"broker_sequence":self.state.broker_sequence,"differences":self.state.differences})
    }
    /// 仅由绑定的 Position 和冻结的来源原件推导资金费流水。
    pub fn apply_funding(
        &mut self,
        input: &Value,
        effect: &onlyalpha_position::FundingEffect,
    ) -> Result<Outcome, Error> {
        let flow = effect.record();
        if input["op"] != "ECONOMIC"
            || self.config["position_configuration"] != effect.position_configuration()
            || self.config["account"] != flow["account"]
            || !self.state.perpetual
        {
            return Err(err("ACCOUNT_FUNDING_PRODUCER_SCOPE"));
        }
        let mut command = input.clone();
        command["payload"] = json!({"schema_version":1,"cashflow":flow["cashflow"],"source_fact":flow["source_fact"],"amount":flow["amount"],"funding_source":effect.reference(),"trade_lineage":effect.account_lineage()});
        command["payload"]["kind"] = json!("FUNDING");
        command["payload"]["instrument"] = flow["instrument"].clone();
        // 已保留的同一原命令先走原幂等路径，不以未来成交改写旧 Funding。
        if let Some(original) = self.state.journal.iter().find(|c| {
            c["op"] == "ECONOMIC"
                && c["payload"]["kind"] == "FUNDING"
                && c["payload"]["cashflow"] == flow["cashflow"]
        }) {
            let mut retained = original.as_ref().clone();
            retained["command_id"] = command["command_id"].clone();
            if retained != command {
                return Err(err("ACCOUNT_FUNDING_IDENTITY_CONFLICT"));
            }
            return self.apply_inner(&command);
        }
        if self.state.journal.iter().any(|c| {
            c["op"] == "TRADE"
                && c["payload"]["instrument"] == flow["instrument"]
                && c["payload"]["trade"]
                    .as_str()
                    .is_none_or(|id| !self.state.position_trades.contains_key(id))
        }) || effect.account_lineage()
            != hash(&serde_json::to_value(&self.state.position_trades)?)
        {
            return Err(err("ACCOUNT_FUNDING_SOURCE_RELATION"));
        }
        self.apply_inner(&command)
    }
    /// 显式永续 TRADE 的原输入身份只由实际已应用的 Position 成交签发。
    pub fn apply_position_trade(
        &mut self,
        input: &Value,
        original: &onlyalpha_position::TradeEvidence,
    ) -> Result<Outcome, Error> {
        let evidence = original
            .verify_projection(&self.config, input, false)
            .map_err(|e| Error(e.0))?;
        let mut command = input.clone();
        if command["payload"]
            .get("trade_evidence")
            .is_some_and(|old| old != evidence)
        {
            return Err(err("ACCOUNT_TRADE_EVIDENCE_CONFLICT"));
        }
        command["payload"]["trade_evidence"] = json!(evidence);
        self.apply_inner(&command)
    }
    pub fn apply(&mut self, input: &Value) -> Result<Outcome, Error> {
        if self.state.perpetual && input["op"] == "TRADE" {
            return Err(err("ACCOUNT_TRADE_PRODUCER_REQUIRED"));
        }
        if self.state.perpetual
            && input["op"] == "ECONOMIC"
            && input["payload"]["kind"] == "FUNDING"
        {
            return Err(err("ACCOUNT_FUNDING_PRODUCER_REQUIRED"));
        }

        if input["op"] == "VALUATION" {
            return Err(err("ACCOUNT_VALUATION_PRODUCER_REQUIRED"));
        }
        if input["op"] == "MARGIN" {
            return Err(err("ACCOUNT_MARGIN_PRODUCER_REQUIRED"));
        }
        self.apply_inner(input)
    }
    pub fn apply_valuation(
        &mut self,
        input: &Value,
        effect: &onlyalpha_position::ValuationEffect,
    ) -> Result<Outcome, Error> {
        if input["op"] != "VALUATION" {
            return Err(err("ACCOUNT_VALUATION_OP"));
        }
        let mut command = input.clone();
        command["payload"] = effect.replay_input();
        self.apply_inner(&command)
    }
    pub fn apply_margin(
        &mut self,
        input: &Value,
        effect: &onlyalpha_margin::Effect,
    ) -> Result<Outcome, Error> {
        if input["op"] != "MARGIN" {
            return Err(err("ACCOUNT_MARGIN_OP"));
        }
        let mut command = input.clone();
        command["payload"] = effect.replay_input();
        self.apply_inner(&command)
    }
    pub(crate) fn apply_inner(&mut self, input: &Value) -> Result<Outcome, Error> {
        #[cfg(test)]
        crate::recovery::ACCOUNT_COMMAND_REPLAYS.with(|count| count.set(count.get() + 1));
        if input.to_string().len()
            > if input["op"] == "VALUATION" {
                32 * 1024 * 1024
            } else {
                16384
            }
        {
            return Err(err("ACCOUNT_COMMAND_BOUND"));
        }
        let r = row(
            input,
            &[
                "engine",
                "runtime",
                "account",
                "gateway",
                "generation",
                "command_id",
                "cause",
                "time",
                "op",
                "payload",
            ],
        )?;
        for f in ["engine", "runtime", "account", "gateway", "generation"] {
            if r[f] != self.config[f] {
                return Err(err("ACCOUNT_CONTEXT_CONFLICT"));
            }
        }
        let cid = id(&r["command_id"])?;
        fingerprint(&r["cause"])?;
        let t = time(&r["time"])?;
        let op = text(&r["op"])?;
        if op == "TRADE" && self.state.perpetual != r["payload"].get("trade_evidence").is_some() {
            return Err(err("ACCOUNT_TRADE_EVIDENCE_PROFILE"));
        }
        let mut command = input.clone();
        command["payload"] = normalize_payload(op, &r["payload"], self.precision)?;
        let encoded = serde_json::to_vec(&command)?;
        let h = digest(&encoded);
        if let Some(old) = self.state.receipts.get(&cid) {
            return Ok(outcome(if old == &h {
                Status::Duplicate
            } else {
                Status::Conflict
            }));
        }
        let admission = matches!(op, "RESERVE" | "CASH_CHANGE")
            || (op == "MARGIN" && command["payload"]["command"]["action"] == "RESERVE");
        if admission
            && (self.state.journal.len() >= MAX_COMMANDS
                || self
                    .state
                    .journal
                    .iter()
                    .map(|v| v.to_string().len())
                    .sum::<usize>()
                    + command.to_string().len()
                    > 4 * 1024 * 1024)
        {
            return Err(err("ACCOUNT_JOURNAL_BOUND"));
        }
        let p = &command["payload"];
        let aliases: Vec<String> = match op {
            "TRADE" => ["trade", "execution", "venue_trade", "fee_instruction"]
                .iter()
                .map(|f| key(f, p[f].as_str().expect("validated ID")))
                .collect(),
            "RESERVE" => vec![key("reservation", text(&p["reservation"])?)],
            "CASH_CHANGE" => vec![
                key("change", text(&p["change"])?),
                key("source_fact", text(&p["source_fact"])?),
            ],
            "ECONOMIC" => vec![
                key("cashflow", text(&p["cashflow"])?),
                key("source_fact", text(&p["source_fact"])?),
            ],
            "MARGIN" => vec![key("margin", text(&p["command"]["id"])?)],
            "SETTLE" => vec![key("settlement", text(&p["instruction"])?)],
            "VALUATION" => vec![key("valuation", text(&p["intent"]["valuation"])?)],
            "BROKER" => vec![key("broker", text(&p["snapshot"])?)],
            _ => vec![],
        };
        let mut semantic = command.clone();
        semantic
            .as_object_mut()
            .expect("validated record")
            .remove("command_id");
        let sh = hash(&semantic);
        let known: Vec<_> = aliases
            .iter()
            .filter_map(|a| self.state.semantic.get(a))
            .collect();
        if known.iter().any(|old| *old != &sh) {
            return Ok(outcome(Status::Conflict));
        }
        let duplicate = !known.is_empty();
        let mut candidate = Self {
            config: self.config.clone(),
            precision: self.precision,
            state: self.state.clone(),
            checkpoint_version: self.checkpoint_version,
            journal_bytes: self.journal_bytes,
            checkpoint_cache: std::sync::OnceLock::new(),
        };
        let status = if duplicate {
            Status::Duplicate
        } else {
            if op == "MARGIN" && candidate.state.perpetual {
                let cause = text(&command["cause"])?;
                if candidate
                    .state
                    .maintenance_origin
                    .as_ref()
                    .is_none_or(|(old, _)| old != cause)
                {
                    candidate.state.maintenance_origin = Some((
                        cause.into(),
                        candidate.state.last_confirmed_maintenance.clone(),
                    ));
                }
            }
            candidate.transition(op, p, &t)?
        };
        if op == "TRADE" && status == Status::Applied {
            candidate.state.position_trades.insert(id(&p["trade"])?,json!({"position_evidence":p["position_evidence"],"cause":command["cause"],"time":command["time"],"order":p["order"],"execution":p["execution"],"venue_trade":p["venue_trade"],"sequence":p["sequence"]}));
            if let Some(original) = p.get("trade_evidence") {
                candidate
                    .state
                    .position_trades
                    .get_mut(text(&p["trade"])?)
                    .expect("inserted trade")["trade_evidence"] = original.clone();
            }
        }
        if status != Status::Duplicate {
            candidate.state.sequence += 1;
            candidate.state.now = Some(
                candidate
                    .state
                    .now
                    .as_ref()
                    .map_or(t.clone(), |old| old.max(&t).clone()),
            );
        }
        candidate.state.receipts.insert(cid, h);
        for a in aliases {
            candidate.state.semantic.insert(a, sh.clone());
        }
        candidate.journal_bytes = candidate
            .journal_bytes
            .checked_add(encoded.len())
            .and_then(|size| size.checked_add(usize::from(!candidate.state.journal.is_empty())))
            .ok_or_else(|| err("ACCOUNT_CHECKPOINT_BOUND"))?;
        candidate.state.journal.push(std::sync::Arc::new(command));
        let perpetual = candidate.config["account_type"] == "LINEAR_PERPETUAL";
        if perpetual {
            if candidate.state.available() < Decimal::zero()
                || &candidate.state.cash + &candidate.state.market_value
                    < candidate.state.margin_total("maintenance")
            {
                candidate.state.flags.insert("INSUFFICIENT_MARGIN".into());
            } else {
                candidate.state.flags.remove("INSUFFICIENT_MARGIN");
            }
        }
        candidate.state.validate(perpetual)?;
        if candidate.checkpoint_version == 5 {
            crate::recovery::check_expanded_size(
                &candidate.config,
                &candidate.state(),
                candidate.journal_bytes,
            )?;
        }
        if admission {
            candidate.state.validate_admission()?;
            if candidate.checkpoint()?.0.len() > MAX_CHECKPOINT {
                return Err(err("ACCOUNT_CHECKPOINT_BOUND"));
            }
        }

        let fact = if status == Status::Applied {
            Some(
                json!({"schema_version":1,"sequence":candidate.state.sequence,"cause":input["cause"],"op":op,"snapshot":candidate.snapshot()}),
            )
        } else {
            None
        };
        *self = candidate;
        Ok(Outcome { status, fact })
    }
    fn transition(&mut self, op: &str, p: &Value, t: &num_bigint::BigInt) -> Result<Status, Error> {
        if op != "TRADE" && op != "BROKER" && self.state.now.as_ref().is_some_and(|old| t < old) {
            return Err(err("ACCOUNT_TIME_REGRESSION"));
        }
        match op {
            "MARGIN" => self.margin_effect(p)?,
            "RESERVE" => self.reserve(p)?,
            "STAGE" => self.stage(p)?,
            "RELEASE" => return self.release(p),
            "TRADE" => return self.trade(p, t),
            "BROKER" => return self.observe_broker(p, t),
            "CASH_CHANGE" => {
                let amount = nonnegative(&p["amount"], self.precision)?;
                match text(&p["kind"])? {
                    "DEPOSIT" => self.state.cash += amount,
                    "WITHDRAWAL" => {
                        if !self.state.flags.is_empty() || amount > self.state.withdrawable() {
                            return Err(err("ACCOUNT_WITHDRAWAL_BLOCKED"));
                        }
                        self.state.cash -= amount;
                    }
                    _ => return Err(err("ACCOUNT_CASH_CHANGE_KIND")),
                }
                self.state.economic_version += 1;
            }
            "ECONOMIC" => {
                let amount = money(&p["amount"], self.precision)?;
                match text(&p["kind"])? {
                    "REALIZED_PNL" | "VARIATION_MARGIN" => self.state.realized += &amount,
                    "FUNDING" => {}
                    _ => return Err(err("ACCOUNT_ECONOMIC_KIND")),
                }
                self.state.cash += amount;
                self.state.economic_version += 1;
            }
            "SETTLE" => {
                let source = text(&p["source_trade"])?;
                let amount = nonnegative(&p["amount"], self.precision)?;
                let left = self
                    .state
                    .receivables
                    .get_mut(source)
                    .ok_or_else(|| err("ACCOUNT_SETTLEMENT_SOURCE_UNKNOWN"))?;
                if amount <= Decimal::zero() || amount > *left {
                    return Err(err("ACCOUNT_SETTLEMENT_AMOUNT"));
                }
                *left -= amount;
                self.state.economic_version += 1;
            }
            "VALUATION" => {
                let effect = onlyalpha_position::ValuationEffect::rederive(p)
                    .map_err(|e| err(&e.to_string()))?;
                let result = effect.record();
                let intent = &result["intent"];
                for f in [
                    "engine",
                    "runtime",
                    "account",
                    "gateway",
                    "generation",
                    "currency",
                ] {
                    if result["scope"][f] != self.config[f] {
                        return Err(err("ACCOUNT_VALUATION_OWNER"));
                    }
                }
                if result["configuration"] != self.config["position_configuration"]
                    || result["trades"] != serde_json::to_value(&self.state.position_trades)?
                {
                    return Err(err("ACCOUNT_VALUATION_SOURCE_RELATION"));
                }
                let v = uint(&intent["version"])?;
                if v <= self.state.valuation_version
                    || uint(&intent["economic_version"])? != self.state.economic_version
                    || time(&intent["time"])? != *t
                {
                    return Err(err("ACCOUNT_VALUATION_BASIS"));
                }
                self.state.market_value = if self.config["account_type"] == "LINEAR_PERPETUAL" {
                    money(&result["market_value"], self.precision)?
                } else {
                    nonnegative(&result["market_value"], self.precision)?
                };
                self.state.unrealized = analytical(&result["unrealized_pnl"])?;
                self.state.valuation_version = v;
                self.state.position_evidence = Some(text(&intent["position_evidence"])?.into());
            }
            _ => return Err(err("ACCOUNT_OP_UNSUPPORTED")),
        }
        Ok(Status::Applied)
    }
    fn trade(&mut self, p: &Value, t: &num_bigint::BigInt) -> Result<Status, Error> {
        let seq = uint(&p["sequence"])?;
        if self.state.trade_sequence.is_some_and(|old| seq <= old)
            || self.state.now.as_ref().is_some_and(|old| t < old)
        {
            self.state.flags.insert("STALE_TRADE".into());
            return Ok(Status::Stale);
        }
        let notional = nonnegative(&p["notional"], self.precision)?;
        let charges = nonnegative(&p["charges"], self.precision)?;
        let rebates = nonnegative(&p["rebates"], self.precision)?;
        let fee = &charges - &rebates;
        let realized = analytical(&p["realized_pnl_delta"])?;
        let credit = match text(&p["side"])? {
            "BUY" => {
                if realized != Decimal::zero() {
                    return Err(err("ACCOUNT_BUY_REALIZED_PNL"));
                }
                let principal = if self.config["account_type"] == "LINEAR_PERPETUAL" {
                    Decimal::zero()
                } else {
                    notional.clone()
                };
                let debit = &principal + &fee;
                self.consume(p, &(&principal + &charges))?;
                self.state.cash -= &debit;
                -debit
            }
            "SELL" => {
                if self.state.perpetual {
                    return Err(err("ACCOUNT_PERPETUAL_OPEN_ONLY"));
                }
                if !p["reservation"].is_null() {
                    return Err(err("ACCOUNT_SELL_CASH_RESERVATION"));
                }
                let credit = &notional - &fee;
                self.state.cash += &credit;
                credit
            }
            _ => return Err(err("ACCOUNT_TRADE_SIDE")),
        };
        if !boolean(&p["cash_withdrawable"])? && credit > Decimal::zero() {
            self.state.receivables.insert(id(&p["trade"])?, credit);
        }
        self.state.realized += realized;
        self.state.fees += fee;
        self.state.market_value += money(&p["market_value_delta"], self.precision)?;
        self.state.unrealized = analytical(&p["unrealized_pnl"])?;
        self.state.realized_rounding_adjustment = analytical(&p["realized_rounding_adjustment"])?;
        self.state.position_evidence = Some(text(&p["position_evidence"])?.into());
        self.state.trade_sequence = Some(seq);
        self.state.economic_version += 1;
        Ok(Status::Applied)
    }
}

impl Manager {
    fn margin_effect(&mut self, proof: &Value) -> Result<(), Error> {
        if proof["config"].get("observation_capacity").is_some() != self.state.perpetual {
            return Err(err("ACCOUNT_MARGIN_CONFIGURATION"));
        }
        let mut owner = onlyalpha_margin::Manager::new(
            proof["config"].clone(),
            usize::try_from(uint(&proof["capacity"])?)
                .map_err(|_| err("ACCOUNT_MARGIN_CAPACITY"))?,
        )
        .map_err(|e| err(&e.to_string()))?;
        if !self.state.margin_owner.is_null() {
            let cp = &self.state.margin_owner;
            owner
                .restore(cp, &onlyalpha_margin::digest(cp))
                .map_err(|e| err(&e.to_string()))?;
        }
        if proof["before_hash"] != onlyalpha_margin::digest(&owner.checkpoint()) {
            return Err(err("ACCOUNT_MARGIN_PRODUCER_BEFORE"));
        }
        let effect = owner
            .apply(&proof["command"])
            .map_err(|e| err(&e.to_string()))?;
        if proof["after_hash"] != onlyalpha_margin::digest(&owner.checkpoint()) {
            return Err(err("ACCOUNT_MARGIN_PRODUCER_AFTER"));
        }
        let result = effect.record();
        self.margin_projection(
            &json!({"before":result["projection_before"],"after":result["projection_after"]}),
        )?;
        if self.state.perpetual {
            if proof["command"]["action"] == "MARK_MAINTENANCE"
                && self
                    .state
                    .margin
                    .values()
                    .all(|r| r.get("observation_gap").is_none())
            {
                self.state.flags.remove("MAINTENANCE_UNAVAILABLE");
            }
            if result["after"]["observation_gap"].is_object()
                && self.state.flags.insert("MAINTENANCE_UNAVAILABLE".into())
            {
                // Earlier reservations in this same input may already have been repriced.
                self.state.last_confirmed_maintenance = self
                    .state
                    .maintenance_origin
                    .as_ref()
                    .expect("validated Margin cause")
                    .1
                    .clone();
            }
            if !self.state.flags.contains("MAINTENANCE_UNAVAILABLE")
                && matches!(
                    proof["command"]["action"].as_str(),
                    Some("OCCUPY" | "RELEASE_OCCUPIED" | "MARK_MAINTENANCE")
                )
            {
                self.state.last_confirmed_maintenance = json!({"amount":formatted(&self.state.margin_total("maintenance"),self.precision),"time":proof["command"]["time"],"source_ref":proof["command"]["source_ref"]});
            }
        }
        self.state.margin_owner = owner.checkpoint();
        Ok(())
    }
    // Only called with a projection re-derived by the canonical Margin producer.
    // Margin owns decimal/conservation/version/quantity checks; Account owns
    // owner/currency binding and account-wide funding admission.
    fn margin_projection(&mut self, p: &Value) -> Result<(), Error> {
        let after = &p["after"];
        for field in ["engine", "runtime", "account", "gateway", "generation"] {
            if after["scope"][field] != self.config[field] {
                return Err(err("ACCOUNT_MARGIN_OWNER"));
            }
        }
        if after["currency"] != self.config["currency"] {
            return Err(err("ACCOUNT_MARGIN_CONTEXT"));
        }
        let key = text(&after["id"])?;
        let before = self.state.margin.get(key).cloned().unwrap_or(Value::Null);
        if p["before"] != before {
            return Err(err("ACCOUNT_MARGIN_BEFORE"));
        }
        if before.is_null()
            && (!self.state.flags.is_empty()
                || nonnegative(&after["reserved"], self.precision)? > self.state.withdrawable())
        {
            return Err(err("ACCOUNT_MARGIN_ADMISSION"));
        }
        self.state.margin.insert(key.into(), after.clone());
        self.state.economic_version += 1;
        Ok(())
    }
}
