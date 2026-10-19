use crate::model::*;
use bigdecimal::Zero;
use serde_json::{Value, json};
pub struct Manager {
    pub(crate) config: Value,
    pub(crate) precision: u8,
    pub(crate) state: State,
}
impl Manager {
    pub fn new(mut config: Value) -> Result<Self, Error> {
        let p = validate_config(&config)?;
        let cash = nonnegative(&config["initial_cash"], p)?;
        config["initial_cash"] = json!(formatted(&cash, p));
        Ok(Self {
            config,
            precision: p,
            state: State::new(cash),
        })
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
        snapshot
    }
    pub fn reservation(&self, id: &str) -> Option<Value> {
        self.state
            .reservations
            .get(id)
            .map(|r| r.record(self.precision))
    }
    pub fn state(&self) -> Value {
        json!({"schema_version":1,"snapshot":self.snapshot(),"reservations":self.state.reservations.iter().map(|(k,r)|(k.clone(),r.record(self.precision))).collect::<std::collections::BTreeMap<_,_>>(),"receivables":self.state.receivables.iter().map(|(k,v)|(k.clone(),formatted(v,self.precision))).collect::<std::collections::BTreeMap<_,_>>(),"receipts":self.state.receipts,"semantic":self.state.semantic,"broker":self.state.broker,"broker_sequence":self.state.broker_sequence,"differences":self.state.differences})
    }
    pub fn apply(&mut self, input: &Value) -> Result<Outcome, Error> {
        if input.to_string().len() > 16384 {
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
        let mut command = input.clone();
        command["payload"] = normalize_payload(op, &r["payload"], self.precision)?;
        let h = hash(&command);
        if let Some(old) = self.state.receipts.get(&cid) {
            return Ok(outcome(if old == &h {
                Status::Duplicate
            } else {
                Status::Conflict
            }));
        }
        if self.state.journal.len() >= MAX_COMMANDS
            || self
                .state
                .journal
                .iter()
                .map(|v| v.to_string().len())
                .sum::<usize>()
                + command.to_string().len()
                > 4 * 1024 * 1024
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
            "SETTLE" => vec![key("settlement", text(&p["instruction"])?)],
            "VALUATION" => vec![key("valuation", text(&p["valuation"])?)],
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
        };
        let status = if duplicate {
            Status::Duplicate
        } else {
            candidate.transition(op, p, &t)?
        };
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
        candidate.state.journal.push(command);
        candidate.state.validate()?;
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
                let v = uint(&p["version"])?;
                if v <= self.state.valuation_version
                    || uint(&p["economic_version"])? != self.state.economic_version
                {
                    return Err(err("ACCOUNT_VALUATION_BASIS"));
                }
                self.state.market_value = nonnegative(&p["market_value"], self.precision)?;
                self.state.unrealized = money(&p["unrealized_pnl"], self.precision)?;
                self.state.valuation_version = v;
                self.state.position_evidence = Some(text(&p["position_evidence"])?.into());
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
        let realized = money(&p["realized_pnl_delta"], self.precision)?;
        match text(&p["side"])? {
            "BUY" => {
                if realized != Decimal::zero() {
                    return Err(err("ACCOUNT_BUY_REALIZED_PNL"));
                }
                let debit = &notional + &fee;
                self.consume(p, &(&notional + &charges))?;
                self.state.cash -= debit;
            }
            "SELL" => {
                if !p["reservation"].is_null() {
                    return Err(err("ACCOUNT_SELL_CASH_RESERVATION"));
                }
                let credit = &notional - &fee;
                self.state.cash += &credit;
                if !boolean(&p["cash_withdrawable"])? && credit > Decimal::zero() {
                    self.state.receivables.insert(id(&p["trade"])?, credit);
                }
            }
            _ => return Err(err("ACCOUNT_TRADE_SIDE")),
        }
        self.state.realized += realized;
        self.state.fees += fee;
        self.state.market_value += money(&p["market_value_delta"], self.precision)?;
        self.state.unrealized = money(&p["unrealized_pnl"], self.precision)?;
        self.state.position_evidence = Some(text(&p["position_evidence"])?.into());
        self.state.trade_sequence = Some(seq);
        self.state.economic_version += 1;
        Ok(Status::Applied)
    }
}
