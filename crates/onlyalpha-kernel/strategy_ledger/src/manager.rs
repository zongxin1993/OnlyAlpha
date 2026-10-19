use crate::model::*;
use bigdecimal::Zero;
use serde_json::{Value, json};
use std::collections::BTreeMap;
#[derive(Clone)]
pub struct Manager {
    pub(crate) config: Value,
    pub(crate) precision: u8,
    pub(crate) ledgers: BTreeMap<String, Ledger>,
    pub(crate) receipts: BTreeMap<String, String>,
    pub(crate) aliases: BTreeMap<String, String>,
    // Observed attribution includes reservations and non-booked stale Fill observations.
    pub(crate) orders: BTreeMap<String, String>,
    // Only booked Trades establish the relation used by fee adjustments.
    pub(crate) trades: BTreeMap<String, (String, String)>,
    pub(crate) allocation_owners: BTreeMap<String, Value>,
    pub(crate) journal: Vec<Value>,
    pub(crate) timeline: Vec<Value>,
    pub(crate) sequence: u64,
    pub(crate) now: Option<num_bigint::BigInt>,
    pub(crate) trading_day: Option<String>,
    pub(crate) day_index: Option<u64>,
}
impl Manager {
    pub fn new(mut config: Value) -> Result<Self, Error> {
        let c = row(
            &config,
            &[
                "engine",
                "runtime",
                "account",
                "generation",
                "runtime_kind",
                "currency",
                "account_initial_cash",
                "capitals",
            ],
        )?;
        for f in ["engine", "runtime", "account", "generation"] {
            id(&c[f])?;
        }
        if !matches!(text(&c["runtime_kind"])?, "BACKTEST" | "SIM" | "LIVE") {
            return Err(err("LEDGER_RUNTIME_KIND"));
        }
        let currency = onlyalpha_domain::value::OnlyCurrency::from_record(&c["currency"])?;
        use onlyalpha_domain::base::OnlyDomainModel;
        if currency.to_record() != c["currency"] {
            return Err(err("LEDGER_CURRENCY_NONCANONICAL"));
        }
        let p = currency.precision();
        let initial = nonnegative(&c["account_initial_cash"], p)?;
        let capitals = c["capitals"]
            .as_object()
            .filter(|a| !a.is_empty() && a.len() <= 64)
            .ok_or_else(|| err("LEDGER_CAPITALS"))?;
        let mut ledgers = BTreeMap::new();
        let mut normalized = serde_json::Map::new();
        let mut sum = Decimal::zero();
        for (cluster, amount) in capitals {
            id(&json!(cluster))?;
            let amount = nonnegative(amount, p)?;
            sum += &amount;
            normalized.insert(cluster.clone(), json!(formatted(&amount, p)));
            ledgers.insert(cluster.clone(), Ledger::new(amount, p));
        }
        if sum != initial {
            return Err(err("LEDGER_CAPITAL_SUM"));
        }
        config["account_initial_cash"] = json!(formatted(&initial, p));
        config["capitals"] = Value::Object(normalized);
        Ok(Self {
            config,
            precision: p,
            ledgers,
            receipts: BTreeMap::new(),
            aliases: BTreeMap::new(),
            orders: BTreeMap::new(),
            trades: BTreeMap::new(),
            allocation_owners: BTreeMap::new(),
            journal: vec![],
            timeline: vec![],
            sequence: 0,
            now: None,
            trading_day: None,
            day_index: None,
        })
    }
    pub fn snapshot(&self, cluster: &str) -> Result<Value, Error> {
        let mut v = self
            .ledgers
            .get(cluster)
            .ok_or_else(|| err("LEDGER_SCOPE"))?
            .snapshot(self.precision);
        for f in ["engine", "runtime", "account", "generation", "currency"] {
            v[f] = self.config[f].clone();
        }
        v["cluster"] = json!(cluster);
        v["runtime_sequence"] = json!(self.sequence);
        v["trading_day"] = json!(self.trading_day);
        v["day_index"] = json!(self.day_index);
        Ok(v)
    }
    pub fn state(&self) -> Value {
        json!({"schema_version":1,"config":self.config,"ledgers":self.ledgers.iter().map(|(k,v)|(k.clone(),v.record(self.precision))).collect::<BTreeMap<_,_>>(),"receipts":self.receipts,"aliases":self.aliases,"orders":self.orders,"trades":self.trades,"timeline":self.timeline,"allocation_owners":self.allocation_owners,"sequence":self.sequence,"time":self.now.as_ref().map(|n|serde_json::from_str::<Value>(&n.to_string()).expect("integer")),"trading_day":self.trading_day,"day_index":self.day_index})
    }
    pub fn apply(&mut self, input: &Value) -> Result<Outcome, Error> {
        if input.to_string().len() > 65536 {
            return Err(err("LEDGER_COMMAND_BOUND"));
        }
        let r = row(
            input,
            &[
                "engine",
                "runtime",
                "account",
                "generation",
                "cluster",
                "command_id",
                "cause",
                "time",
                "runtime_sequence",
                "trading_day",
                "day_index",
                "op",
                "payload",
            ],
        )?;
        for f in ["engine", "runtime", "account", "generation"] {
            if r[f] != self.config[f] {
                return Err(err("LEDGER_CONTEXT_CONFLICT"));
            }
        }
        let cluster = id(&r["cluster"])?;
        if !self.ledgers.contains_key(&cluster) {
            return Err(err("LEDGER_SCOPE"));
        }
        let cid = id(&r["command_id"])?;
        fingerprint(&r["cause"])?;
        let t = time(&r["time"])?;
        let seq = uint(&r["runtime_sequence"])?;
        day(&r["trading_day"])?;
        let di = uint(&r["day_index"])?;
        let op = text(&r["op"])?;
        let mut cmd = input.clone();
        cmd["payload"] = normalize(op, &r["payload"], self.precision)?;
        let h = hash(&cmd);
        if let Some(old) = self.receipts.get(&cid) {
            return Ok(outcome(if old == &h {
                Status::Duplicate
            } else {
                Status::Conflict
            }));
        }
        let admission = matches!(op, "RESERVE" | "ACTIVATE");
        if admission
            && (self.journal.len() >= MAX_COMMANDS
                || self
                    .journal
                    .iter()
                    .map(|v| v.to_string().len())
                    .sum::<usize>()
                    + cmd.to_string().len()
                    > 8 * 1024 * 1024)
        {
            return Err(err("LEDGER_JOURNAL_BOUND"));
        }
        let p = &cmd["payload"];
        let fields: &[(&str, &str)] = match op {
            "RESERVE" => &[("reservation", "reservation"), ("reserved_order", "order")],
            "TRADE" => &[
                ("trade", "trade"),
                ("execution", "execution"),
                ("venue_trade", "venue_trade"),
                ("fee_instruction", "fee_instruction"),
            ],
            "FEE" => &[
                ("fee_instruction", "fee_instruction"),
                ("source_fact", "source_fact"),
            ],
            "CASH_FLOW" => &[("cashflow", "cashflow"), ("source_fact", "source_fact")],
            "VALUATION" => &[("valuation", "valuation")],
            _ => &[],
        };
        let aliases = fields
            .iter()
            .map(|(family, f)| Ok(key(family, text(&p[*f])?)))
            .collect::<Result<Vec<_>, Error>>()?;
        let mut semantic = cmd.clone();
        semantic
            .as_object_mut()
            .expect("record")
            .remove("command_id");
        let sh = hash(&semantic);
        let known = aliases
            .iter()
            .filter_map(|k| self.aliases.get(k))
            .collect::<Vec<_>>();
        if known.iter().any(|old| *old != &sh)
            || (!known.is_empty() && known.len() != aliases.len())
        {
            return Ok(outcome(Status::Conflict));
        }
        if matches!(op, "TRADE" | "RESERVE" | "FEE")
            && self
                .orders
                .get(text(&p["order"])?)
                .is_some_and(|c| c != &cluster)
        {
            return Ok(outcome(Status::Conflict));
        }
        if op == "FEE" {
            let relation = self.trades.get(text(&p["trade"])?);
            if !relation.is_some_and(|(owner, order)| owner == &cluster && p["order"] == *order) {
                return Err(err("LEDGER_FEE_SOURCE_RELATION"));
            }
        }
        let duplicate = !known.is_empty();
        let mut candidate = self.clone();
        let status = if duplicate {
            Status::Duplicate
        } else {
            if seq <= self.sequence {
                return Err(err("LEDGER_RUNTIME_SEQUENCE"));
            }
            if self.day_index.is_some_and(|old| di < old)
                || (self.day_index == Some(di)
                    && self.trading_day.as_ref() != Some(&text(&r["trading_day"])?.to_owned()))
            {
                return Err(err("LEDGER_CALENDAR_REGRESSION_OR_CONFLICT"));
            }
            if self.day_index.is_some_and(|old| di > old)
                && self
                    .trading_day
                    .as_deref()
                    .is_some_and(|old| text(&r["trading_day"]).is_ok_and(|new| new <= old))
            {
                return Err(err("LEDGER_CALENDAR_REGRESSION_OR_CONFLICT"));
            }
            if self.day_index != Some(di) {
                for l in candidate.ledgers.values_mut() {
                    l.day_start = l.equity();
                    l.day_external = l.external.clone();
                    l.day_flow_occurred = false;
                }
                candidate.day_index = Some(di);
                candidate.trading_day = Some(text(&r["trading_day"])?.into());
            }
            if op != "TRADE" && self.now.as_ref().is_some_and(|old| t < *old) {
                return Err(err("LEDGER_TIME_REGRESSION"));
            }
            let status = candidate.transition(&cluster, op, p, &t, seq)?;
            if status == Status::Duplicate {
                candidate = self.clone();
            } else {
                candidate.sequence = seq;
                candidate.now = Some(
                    candidate
                        .now
                        .as_ref()
                        .map_or(t.clone(), |old| old.max(&t).clone()),
                );
                let l = candidate.ledgers.get_mut(&cluster).expect("scope");
                l.refresh();
                l.validate()?;
                let snap = candidate.snapshot(&cluster)?;
                candidate.timeline.push(json!({"sequence":seq,"cluster":cluster,"time":input["time"],"cause":input["cause"],"snapshot":snap,"status":format!("{status:?}")}));
            }
            status
        };
        candidate.receipts.insert(cid, h);
        for a in aliases {
            candidate.aliases.insert(a, sh.clone());
        }
        candidate.journal.push(cmd);
        if admission && candidate.aliases.len() > 16384 {
            return Err(err("LEDGER_ALIAS_BOUND"));
        }
        // Reuse the owning checkpoint encoder/bound, so every accepted state is recoverable.
        if admission {
            for l in candidate.ledgers.values() {
                l.validate_admission()?;
            }
            if candidate.checkpoint()?.0.len() > MAX_CHECKPOINT {
                return Err(err("LEDGER_CHECKPOINT_BOUND"));
            }
        }
        let fact = if status == Status::Duplicate {
            None
        } else {
            Some(
                json!({"schema_version":1,"runtime_sequence":seq,"cause":input["cause"],"op":op,"snapshot":candidate.snapshot(&cluster)?}),
            )
        };
        *self = candidate;
        Ok(Outcome { status, fact })
    }
    fn transition(
        &mut self,
        c: &str,
        op: &str,
        p: &Value,
        t: &num_bigint::BigInt,
        sequence: u64,
    ) -> Result<Status, Error> {
        let precision = self.precision;
        if op == "TRADE" {
            let identity = id(&p["after"]["identity"])?;
            let owner = json!([c, p["instrument"], p["after"]["cycle"]]);
            if self
                .allocation_owners
                .get(&identity)
                .is_some_and(|old| old != &owner)
            {
                return Err(err("LEDGER_ALLOCATION_OWNER_CONFLICT"));
            }
            self.allocation_owners.insert(identity, owner);
        }
        let l = self.ledgers.get_mut(c).expect("scope");
        if l.lifecycle == "CLOSED" {
            return Err(err("LEDGER_CLOSED"));
        }
        match op {
            "ACTIVATE" => {
                if l.lifecycle != "CREATED" {
                    return Err(err("LEDGER_ACTIVATION_STATE"));
                }
                l.lifecycle = "ACTIVE".into();
            }
            "CLOSE" => {
                if l.reserved() != Decimal::zero()
                    || l.lines
                        .values()
                        .any(|v| v.allocation.quantity != Decimal::zero())
                {
                    return Err(err("LEDGER_CLOSE_NOT_FLAT"));
                }
                l.lifecycle = "CLOSED".into();
            }
            "RESERVE" => {
                if !l.ready() {
                    return Err(err("LEDGER_RESERVE_BLOCKED"));
                }
                let amount = nonnegative(&p["amount"], precision)?;
                if amount <= Decimal::zero() || amount > l.available() {
                    return Err(err("LEDGER_INSUFFICIENT_CASH"));
                }
                let rid = id(&p["reservation"])?;
                let order = id(&p["order"])?;
                if l.reservations.contains_key(&rid) || self.orders.contains_key(&order) {
                    return Err(err("LEDGER_RESERVATION_CONFLICT"));
                }
                l.reservations.insert(
                    rid,
                    Reservation {
                        order: order.clone(),
                        original: amount.clone(),
                        consumed: Decimal::zero(),
                        remaining: amount.clone(),
                        released: Decimal::zero(),
                        sent: false,
                        acknowledged: false,
                        unknown: false,
                        cancel_pending: false,
                        terminal_outcome: None,
                    },
                );
                self.orders.insert(order, c.into());
                l.entry(op, -amount, false, p, sequence, precision);
            }
            "STAGE" | "RELEASE" => {
                let r = l
                    .reservations
                    .get_mut(text(&p["reservation"])?)
                    .ok_or_else(|| err("LEDGER_RESERVATION_UNKNOWN"))?;
                if op == "STAGE" {
                    if r.remaining == Decimal::zero() {
                        return Err(err("LEDGER_RESERVATION_TERMINAL"));
                    }
                    match text(&p["stage"])? {
                        "SENT_TO_BROKER" => {
                            if r.sent {
                                return Err(err("LEDGER_STAGE_REGRESSION"));
                            }
                            r.sent = true;
                        }
                        "SUBMIT_UNKNOWN" => {
                            r.sent = true;
                            r.unknown = true;
                        }
                        "BROKER_ACKNOWLEDGED" => {
                            r.sent = true;
                            r.acknowledged = true;
                            r.unknown = false;
                        }
                        "CANCEL_REQUESTED" => {
                            if !r.sent {
                                return Err(err("LEDGER_CANCEL_BEFORE_SEND"));
                            }
                            r.cancel_pending = true;
                        }
                        _ => return Err(err("LEDGER_STAGE")),
                    }
                } else {
                    let observed = text(&p["outcome"])?;
                    if let Some(old) = &r.terminal_outcome {
                        return if old == observed {
                            Ok(Status::Duplicate)
                        } else {
                            Err(err("LEDGER_TERMINAL_CONFLICT"))
                        };
                    }
                    if observed == "UNKNOWN" {
                        r.sent = true;
                        r.unknown = true;
                        r.cancel_pending = true;
                    } else {
                        if !matches!(
                            observed,
                            "NOT_SENT" | "CANCELLED" | "REJECTED" | "EXPIRED" | "FAILED"
                        ) || (observed == "NOT_SENT" && r.sent)
                        {
                            return Err(err("LEDGER_RELEASE_UNPROVEN"));
                        }
                        let released = r.remaining.clone();
                        r.released += &released;
                        r.remaining = Decimal::zero();
                        r.unknown = false;
                        r.cancel_pending = false;
                        r.terminal_outcome = Some(observed.into());
                        l.entry("RELEASE", released, false, p, sequence, precision);
                    }
                }
            }
            "CASH_FLOW" => {
                let amount = money(&p["amount"], precision)?;
                if amount < Decimal::zero() && (!l.ready() || -amount.clone() > l.available()) {
                    return Err(err("LEDGER_WITHDRAWAL_BLOCKED"));
                }
                l.cash += &amount;
                l.external += &amount;
                l.external_occurred = true;
                l.day_flow_occurred = true;
                l.economic_version += 1;
                l.entry(op, amount, true, p, sequence, precision);
            }
            "FEE" => {
                let fee =
                    nonnegative(&p["charges"], precision)? - nonnegative(&p["rebates"], precision)?;
                l.cash -= &fee;
                l.fees += &fee;
                l.economic_version += 1;
                l.fee_entries.push(p.clone());
                l.entry(op, -fee, true, p, sequence, precision);
            }
            "TRADE" => {
                if l.lifecycle != "ACTIVE" {
                    return Err(err("LEDGER_TRADE_LIFECYCLE"));
                }
                let source = uint(&p["source_sequence"])?;
                if l.trade_sequence.is_some_and(|s| source <= s)
                    || self.now.as_ref().is_some_and(|old| t < old)
                {
                    l.flags.insert("STALE_TRADE".into());
                    // Observation proves ownership even when economics require reconciliation.
                    self.orders.insert(id(&p["order"])?, c.into());
                    return Ok(Status::Stale);
                }
                l.trade(p, precision, sequence)?;
                self.orders.insert(id(&p["order"])?, c.into());
                self.trades
                    .insert(id(&p["trade"])?, (c.into(), id(&p["order"])?));
            }
            "VALUATION" => l.valuation(p, precision)?,
            _ => return Err(err("LEDGER_OP_UNSUPPORTED")),
        }
        Ok(Status::Applied)
    }
}
