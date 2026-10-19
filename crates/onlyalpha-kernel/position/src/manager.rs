use crate::model::*;
use bigdecimal::Zero;
use onlyalpha_domain::{base::OnlyDomainModel, value::OnlyMoney};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Debug)]
pub struct Manager {
    pub(crate) config: Value,
    pub(crate) instruments: BTreeMap<String, Instrument>,
    pub(crate) currency: onlyalpha_domain::value::OnlyCurrency,
    pub(crate) clusters: BTreeSet<String>,
    pub(crate) state: State,
}
impl Manager {
    pub fn new(config: Value) -> Result<Self, Error> {
        if config.to_string().len() > 16384 {
            return Err(err("POSITION_CONFIG_BOUND"));
        }
        let r = row(
            &config,
            &[
                "engine",
                "runtime",
                "account",
                "gateway",
                "generation",
                "currency",
                "clusters",
                "instruments",
            ],
        )?;
        for k in ["engine", "runtime", "account", "gateway", "generation"] {
            id(&r[k])?;
        }
        let currency = currency(&r["currency"])?;
        let mut clusters = BTreeSet::new();
        let list = r["clusters"]
            .as_array()
            .filter(|a| !a.is_empty() && a.len() <= 32)
            .ok_or_else(|| err("POSITION_CLUSTERS_BOUND"))?;
        for c in list {
            if !clusters.insert(id(c)?) {
                return Err(err("POSITION_DUPLICATE_CLUSTER"));
            }
        }
        let list = r["instruments"]
            .as_array()
            .filter(|a| !a.is_empty() && a.len() <= 32)
            .ok_or_else(|| err("POSITION_INSTRUMENTS_BOUND"))?;
        let mut instruments = BTreeMap::new();
        for v in list {
            let (key, spec) = instrument(v)?;
            if instruments.insert(key, spec).is_some() {
                return Err(err("POSITION_DUPLICATE_INSTRUMENT"));
            }
        }
        Ok(Self {
            config,
            instruments,
            currency,
            clusters,
            state: State::default(),
        })
    }
    pub(crate) fn spec(&self, i: &str) -> Result<&Instrument, Error> {
        self.instruments
            .get(i)
            .ok_or_else(|| err("POSITION_UNKNOWN_INSTRUMENT"))
    }
    pub(crate) fn cluster_id(&self, v: &Value) -> Result<String, Error> {
        let c = id(v)?;
        if !self.clusters.contains(&c) {
            return Err(err("POSITION_CLUSTER_SCOPE"));
        }
        Ok(c)
    }
    pub(crate) fn blocked(&self, i: &str) -> bool {
        self.state.stale.contains_key(i)
            || self
                .state
                .brokers
                .get(i)
                .is_some_and(|v| v["blocking"] == true)
    }
    pub(crate) fn holds(&self, i: &str, c: Option<&str>, local: bool) -> Decimal {
        self.state
            .reservations
            .values()
            .filter(|r| {
                r.instrument == i && c.is_none_or(|c| r.cluster == c) && (!local || r.local())
            })
            .fold(Decimal::zero(), |n, r| n + &r.remaining)
    }
    pub(crate) fn restrictions(&self, i: &str) -> Result<Decimal, Error> {
        let mut q = Decimal::zero();
        for r in self
            .state
            .restrictions
            .values()
            .filter(|r| r["instrument"] == i)
        {
            let from = time(&r["from"])?;
            let until = if r["until"].is_null() {
                None
            } else {
                Some(time(&r["until"])?)
            };
            if from <= self.state.now && until.is_none_or(|t| self.state.now < t) {
                q += nonnegative(&r["quantity"])?;
            }
        }
        Ok(q)
    }
    pub(crate) fn account_available(&self, i: &str) -> Result<Decimal, Error> {
        if self.blocked(i) {
            return Ok(Decimal::zero());
        }
        let Some(b) = self.state.accounts.get(i) else {
            return Ok(Decimal::zero());
        };
        // Satisfy both independent constraints. Known ACK holds constrain local
        // tradable inventory but are already reflected in the Broker cap.
        let mut value =
            (&b.settled - self.restrictions(i)? - self.holds(i, None, false)).max(Decimal::zero());
        if let Some(broker) = self.state.brokers.get(i) {
            let cap = (nonnegative(&broker["snapshot"]["available"])? - self.holds(i, None, true))
                .max(Decimal::zero());
            value = value.min(cap);
        }
        Ok(value)
    }
    pub(crate) fn cluster_available(&self, c: &str, i: &str) -> Result<Decimal, Error> {
        let Some(b) = self.state.allocations.get(&(c.into(), i.into())) else {
            return Ok(Decimal::zero());
        };
        Ok((&b.settled - self.holds(i, Some(c), false))
            .max(Decimal::zero())
            .min(self.account_available(i)?))
    }
    pub fn account(&self, i: &str) -> Result<Value, Error> {
        let s = self.spec(i)?;
        self.state
            .accounts
            .get(i)
            .ok_or_else(|| err("POSITION_NOT_FOUND"))?
            .record(s, self.account_available(i)?, self.blocked(i))
    }
    pub fn cluster(&self, c: &str, i: &str) -> Result<Value, Error> {
        if !self.clusters.contains(c) {
            return Err(err("POSITION_CLUSTER_SCOPE"));
        }
        let s = self.spec(i)?;
        self.state
            .allocations
            .get(&(c.into(), i.into()))
            .ok_or_else(|| err("POSITION_ALLOCATION_NOT_FOUND"))?
            .record(s, self.cluster_available(c, i)?, self.blocked(i))
    }
    pub fn unallocated(&self, i: &str) -> Result<Option<Value>, Error> {
        let s = self.spec(i)?;
        self.state
            .allocations
            .get(&(String::new(), i.into()))
            .map(|b| b.record(s, Decimal::zero(), self.blocked(i)))
            .transpose()
    }
    pub fn reservation(&self, o: &str) -> Result<Value, Error> {
        self.state
            .reservations
            .get(o)
            .map(Reservation::record)
            .ok_or_else(|| err("POSITION_RESERVATION_NOT_FOUND"))
    }
    pub fn state(&self) -> Value {
        let accounts: Vec<_> = self
            .state
            .accounts
            .keys()
            .map(|i| json!({"instrument":i,"snapshot":self.account(i).expect("validated state")}))
            .collect();
        let allocations:Vec<_>=self.state.allocations.iter().map(|((c,i),b)|json!({"cluster":if c.is_empty(){Value::Null}else{json!(c)},"instrument":i,"snapshot":b.record(&self.instruments[i],if c.is_empty(){Decimal::zero()}else{self.cluster_available(c,i).expect("validated state")},self.blocked(i)).expect("validated state")})).collect();
        json!({"sequence":self.state.sequence,"now":if self.state.journal.is_empty() {Value::Null} else {json!(self.state.now.to_string())},"accounts":accounts,"allocations":allocations,"history":self.state.history,"reservations":self.state.reservations.values().map(Reservation::record).collect::<Vec<_>>(),"restrictions":self.state.restrictions,"brokers":self.state.brokers,"stale":self.state.stale,"watermarks":self.state.watermarks.iter().map(|(i,(s,t,id))|json!([i,s,t.to_string(),id])).collect::<Vec<_>>(),"receipts":self.state.receipts,"commands":self.state.commands})
    }
    /// New-risk admission only. Existing accepted observations and close processing must continue.
    pub fn admit_new_risk(&self) -> Result<(), Error> {
        if self.state.journal.len() >= MAX_JOURNAL
            || serde_json::to_vec(&self.state.journal)?.len() > MAX_JOURNAL_BYTES
            || self.state.allocations.len() + self.state.history.len() > 256
            || self.state.reservations.len() > 512
            || serde_json::to_vec(&self.state())?.len() > 8 * 1024 * 1024
        {
            return Err(err("POSITION_CAPACITY"));
        }
        if self.checkpoint()?.0.len() > MAX_CHECKPOINT {
            return Err(err("POSITION_CAPACITY"));
        }
        Ok(())
    }
    pub fn apply(&mut self, command: &Value) -> Result<Outcome, Error> {
        if command.to_string().len() > 16384 {
            return Err(err("POSITION_COMMAND_BOUND"));
        }
        let r = row(
            command,
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
        for k in ["engine", "runtime", "account", "gateway", "generation"] {
            if r[k] != self.config[k] {
                return Err(err("POSITION_CONTEXT_MISMATCH"));
            }
        }
        let command_id = id(&r["command_id"])?;
        fingerprint(&r["cause"])?;
        let at = time(&r["time"])?;
        let op = text(&r["op"])?;
        let signature = hash(command);
        if let Some(previous) = self.state.commands.get(&command_id) {
            return Ok(Outcome {
                status: if previous == &signature {
                    Status::Duplicate
                } else {
                    Status::Conflict
                },
                fact: None,
            });
        }
        if !self.state.journal.is_empty()
            && !matches!(op, "TRADE" | "BROKER")
            && at < self.state.now
        {
            return Err(err("POSITION_LOCAL_TIME_REGRESSION"));
        }
        let mut candidate = Self {
            config: self.config.clone(),
            instruments: self.instruments.clone(),
            currency: self.currency.clone(),
            clusters: self.clusters.clone(),
            state: self.state.clone(),
        };
        candidate.state.now = if self.state.journal.is_empty() {
            at.clone()
        } else {
            candidate.state.now.max(at.clone())
        };
        let (status, details) = match op {
            "TRADE" => candidate.trade(&r["payload"], &at)?,
            "RESERVE" | "STAGE" | "RELEASE" => candidate.reserve_command(op, &r["payload"], &at)?,
            "BROKER" => candidate.reconcile(&r["payload"], &at)?,
            "RESTRICTION" | "REMOVE_RESTRICTION" | "SETTLE" | "TICK" => {
                candidate.administration(op, &r["payload"], &at)?
            }
            _ => return Err(err("POSITION_OPERATION_INVALID")),
        };
        if status == Status::Conflict {
            return Ok(Outcome { status, fact: None });
        }
        if status == Status::Duplicate {
            // A successful duplicate response binds this new command forever,
            // but changes no economics, business time or source fact occurrence.
            candidate.state = self.state.clone();
        }
        candidate.state.sequence += 1;
        candidate
            .state
            .commands
            .insert(command_id.clone(), signature.clone());
        candidate.state.journal.push(command.clone());
        candidate.validate()?;
        let fact = json!({"schema_version":1,"config":self.config,"sequence":candidate.state.sequence,"command_id":command_id,"cause":r["cause"],"input_fingerprint":signature,"outcome":if status==Status::Stale{"STALE_OBSERVED"}else{"APPLIED"},"details":details,"realized_pnl":details.get("realized_pnl").cloned().unwrap_or(Value::Null)});
        *self = candidate;
        Ok(Outcome {
            status,
            fact: if status == Status::Duplicate {
                None
            } else {
                Some(fact)
            },
        })
    }
    fn trade(&mut self, v: &Value, at: &num_bigint::BigInt) -> Result<(Status, Value), Error> {
        let r = row(
            v,
            &[
                "instrument",
                "cluster",
                "order",
                "trade",
                "venue_trade",
                "execution",
                "sequence",
                "side",
                "position_side",
                "position_mode",
                "price",
                "quantity",
                "fee",
                "bucket",
                "terminal_fill",
            ],
        )?;
        let i = id(&r["instrument"])?;
        let spec = self.spec(&i)?.clone();
        let c = if r["cluster"].is_null() {
            String::new()
        } else {
            self.cluster_id(&r["cluster"])?
        };
        let order = id(&r["order"])?;
        let trade = id(&r["trade"])?;
        if r["position_side"] != "LONG" || r["position_mode"] != "NETTING" {
            return Err(err("POSITION_UNSUPPORTED_MODE"));
        }
        let side = text(&r["side"])?;
        if !matches!(side, "BUY" | "SELL") {
            return Err(err("POSITION_SIDE"));
        }
        let price = spec.price(&r["price"])?;
        let quantity = spec.quantity(&r["quantity"])?;
        let fee = nonnegative(&r["fee"])?;
        OnlyMoney::new(fee.to_string().parse()?, self.currency.clone())?;
        let terminal = boolean(&r["terminal_fill"])?;
        let settled = match text(&r["bucket"])? {
            "SETTLED" => true,
            "UNSETTLED" => false,
            _ => return Err(err("POSITION_BUCKET")),
        };
        let seq = uint(&r["sequence"])?;
        let signature = hash(&json!([v, at.to_string()]));
        let mut aliases = vec![format!("trade:{trade}")];
        for field in ["venue_trade", "execution"] {
            if !r[field].is_null() {
                aliases.push(format!("{field}:{}", id(&r[field])?));
            }
        }
        for alias in &aliases {
            if let Some(old) = self.state.receipts.get(alias) {
                return Ok((
                    if old == &signature {
                        Status::Duplicate
                    } else {
                        Status::Conflict
                    },
                    Value::Null,
                ));
            }
        }
        let position = (seq, at.clone(), trade);
        if self
            .state
            .watermarks
            .get(&i)
            .is_some_and(|head| &position <= head)
        {
            self.state.stale.insert(
                i.clone(),
                json!({"input":v,"at":at.to_string(),"reason":"UNAPPLIED_STALE_TRADE"}),
            );
            for alias in aliases {
                self.state.receipts.insert(alias, signature.clone());
            }
            return Ok((
                Status::Stale,
                json!({"instrument":i,"reason":"UNAPPLIED_STALE_TRADE"}),
            ));
        }
        let key = (c.clone(), i.clone());
        let mut allocation = self.state.allocations.get(&key).cloned();
        let mut account = self.state.accounts.get(&i).cloned();
        let mut realized = Decimal::zero();
        let mut released = Decimal::zero();
        if side == "BUY" {
            for (b, owner) in [
                (
                    &mut account,
                    json!(["ACCOUNT", self.config["runtime"], self.config["account"], i]),
                ),
                (
                    &mut allocation,
                    if c.is_empty() {
                        json!([
                            "UNALLOCATED",
                            self.config["runtime"],
                            self.config["account"],
                            i
                        ])
                    } else {
                        json!([
                            "CLUSTER",
                            self.config["runtime"],
                            self.config["account"],
                            i,
                            c
                        ])
                    },
                ),
            ] {
                if b.as_ref().is_none_or(|b| b.qty.is_zero()) {
                    let cycle = b.as_ref().map_or(1, |b| b.cycle + 1);
                    if let Some(previous) = b.as_ref() {
                        self.state.history.push(json!({"owner":owner,"snapshot":previous.record(&spec,Decimal::zero(),false)?}));
                    }
                    *b = Some(Book::new(&owner, cycle, at));
                }
                let b = b.as_mut().ok_or_else(|| err("POSITION_STATE"))?;
                b.qty += &quantity;
                b.cost += &price * &quantity;
                if settled {
                    b.settled += &quantity;
                }
            }
        } else {
            if c.is_empty()
                || self
                    .state
                    .allocations
                    .get(&(String::new(), i.clone()))
                    .is_some_and(|u| !u.qty.is_zero())
            {
                return Err(err("POSITION_UNALLOCATED_CLOSE_UNSUPPORTED"));
            }
            let a = allocation
                .as_mut()
                .ok_or_else(|| err("POSITION_ALLOCATION_REQUIRED"))?;
            let b = account.as_mut().ok_or_else(|| err("POSITION_REQUIRED"))?;
            let reservation = self
                .state
                .reservations
                .get_mut(&order)
                .ok_or_else(|| err("POSITION_CLOSE_RESERVATION_REQUIRED"))?;
            if reservation.cluster != c
                || reservation.instrument != i
                || quantity > reservation.remaining
                || quantity > a.settled
                || quantity > b.settled
            {
                return Err(err("POSITION_CLOSE_SCOPE_OR_QUANTITY"));
            }
            released = release_cost(&a.cost, &a.qty, &quantity, spec.qp)?;
            let exact_delta = (&price * &quantity - &released) * &spec.multiplier;
            let target = (&a.realized_exact + &exact_delta).with_scale_round(
                i64::from(self.currency.precision()),
                bigdecimal::RoundingMode::HalfEven,
            );
            realized = target - &a.realized;
            for b in [a, b] {
                b.realized_exact += &exact_delta;
                b.qty -= &quantity;
                b.settled -= &quantity;
                b.cost -= &released;
                b.realized += &realized;
                if b.qty.is_zero() {
                    if !b.cost.is_zero() {
                        return Err(err("POSITION_FINAL_COST_NONZERO"));
                    }
                    b.closed = Some(at.clone());
                }
            }
            reservation.remaining -= &quantity;
            reservation.consumed += &quantity;
            reservation.version += 1;
            if terminal {
                reservation.released += &reservation.remaining;
                reservation.remaining = Decimal::zero();
                reservation.state = if reservation.released.is_zero() {
                    "CONSUMED"
                } else {
                    "RELEASED"
                }
                .into();
                if reservation.state == "RELEASED" {
                    reservation.stage = "RELEASED".into();
                }
            } else if reservation.remaining.is_zero() {
                return Err(err("POSITION_NONTERMINAL_FILL_EXHAUSTS_RESERVATION"));
            } else {
                reservation.state = "PARTIALLY_CONSUMED".into();
            }
        }
        let mut account = account.ok_or_else(|| err("POSITION_REQUIRED"))?;
        let mut allocation = allocation.ok_or_else(|| err("POSITION_ALLOCATION_REQUIRED"))?;
        for b in [&mut account, &mut allocation] {
            b.fees += &fee;
            b.updated = at.clone();
            b.version += 1;
        }
        self.state.accounts.insert(i.clone(), account);
        self.state.allocations.insert(key, allocation);
        self.state.watermarks.insert(i.clone(), position);
        for alias in aliases {
            self.state.receipts.insert(alias, signature.clone());
        }
        Ok((
            Status::Applied,
            json!({"instrument":i,"cluster":if c.is_empty(){Value::Null}else{json!(c)},"order":order,"released_cost":number(&released),"realized_pnl":rounded(&realized,self.currency.precision()),"account":self.account(&i)?}),
        ))
    }
    fn administration(
        &mut self,
        op: &str,
        v: &Value,
        at: &num_bigint::BigInt,
    ) -> Result<(Status, Value), Error> {
        match op {
            "TICK" => {
                row(v, &[])?;
            }
            "RESTRICTION" => {
                let r = row(
                    v,
                    &[
                        "instrument",
                        "id",
                        "quantity",
                        "kind",
                        "source",
                        "from",
                        "until",
                        "reason",
                    ],
                )?;
                let i = id(&r["instrument"])?;
                let spec = self.spec(&i)?;
                spec.quantity(&r["quantity"])?;
                let rid = id(&r["id"])?;
                id(&r["kind"])?;
                id(&r["source"])?;
                text(&r["reason"])?;
                let from = time(&r["from"])?;
                if !r["until"].is_null() && time(&r["until"])? <= from {
                    return Err(err("POSITION_RESTRICTION_INTERVAL"));
                }
                if let Some(old) = self.state.restrictions.get(&rid) {
                    return Ok((
                        if old == v {
                            Status::Duplicate
                        } else {
                            Status::Conflict
                        },
                        Value::Null,
                    ));
                }
                self.state.restrictions.insert(rid, v.clone());
            }
            "REMOVE_RESTRICTION" => {
                let r = row(v, &["instrument", "id"])?;
                let i = id(&r["instrument"])?;
                self.spec(&i)?;
                let rid = id(&r["id"])?;
                let old = self
                    .state
                    .restrictions
                    .get(&rid)
                    .ok_or_else(|| err("POSITION_RESTRICTION_MISSING"))?;
                if old["instrument"] != i {
                    return Err(err("POSITION_RESTRICTION_SCOPE"));
                }
                self.state.restrictions.remove(&rid);
            }
            "SETTLE" => {
                let r = row(v, &["instrument", "trading_day", "source", "buckets"])?;
                let i = id(&r["instrument"])?;
                self.spec(&i)?;
                id(&r["source"])?;
                let day = text(&r["trading_day"])?;
                onlyalpha_domain::time::OnlyTradingDay::from_record(
                    &json!({"schema_version":1,"value":day}),
                )?;
                let source_key = format!("settlement:{}", hash(&json!([i, r["source"], day])));
                let source_signature = hash(v);
                if let Some(previous) = self.state.receipts.get(&source_key) {
                    return Ok((
                        if previous == &source_signature {
                            Status::Duplicate
                        } else {
                            Status::Conflict
                        },
                        Value::Null,
                    ));
                }
                let buckets = r["buckets"]
                    .as_array()
                    .filter(|b| !b.is_empty())
                    .ok_or_else(|| err("POSITION_SETTLEMENT_BUCKETS"))?;
                let mut seen = BTreeSet::new();
                let mut total = Decimal::zero();
                for value in buckets {
                    let b = row(value, &["cluster", "quantity"])?;
                    let c = if b["cluster"].is_null() {
                        String::new()
                    } else {
                        self.cluster_id(&b["cluster"])?
                    };
                    if !seen.insert(c.clone()) {
                        return Err(err("POSITION_SETTLEMENT_DUPLICATE_OWNER"));
                    }
                    let q = self.spec(&i)?.quantity(&b["quantity"])?;
                    let allocation = self
                        .state
                        .allocations
                        .get_mut(&(c, i.clone()))
                        .ok_or_else(|| err("POSITION_SETTLEMENT_ALLOCATION"))?;
                    if q > &allocation.qty - &allocation.settled {
                        return Err(err("POSITION_SETTLEMENT_EXCESS"));
                    }
                    allocation.settled += &q;
                    allocation.version += 1;
                    allocation.updated = at.clone();
                    total += q;
                }
                let account = self
                    .state
                    .accounts
                    .get_mut(&i)
                    .ok_or_else(|| err("POSITION_REQUIRED"))?;
                account.settled += total;
                account.updated = at.clone();
                account.version += 1;
                self.state.receipts.insert(source_key, source_signature);
            }
            _ => return Err(err("POSITION_OPERATION")),
        }
        Ok((Status::Applied, json!({"operation":op})))
    }
    pub(crate) fn validate(&self) -> Result<(), Error> {
        for (i, a) in &self.state.accounts {
            let mut quantity = Decimal::zero();
            let mut settled = Decimal::zero();
            let mut cost = Decimal::zero();
            for ((_, instrument), b) in &self.state.allocations {
                if instrument != i {
                    continue;
                }
                for d in [
                    &b.qty,
                    &b.settled,
                    &b.cost,
                    &b.realized,
                    &b.realized_exact,
                    &b.fees,
                ] {
                    bounded(d, false)?;
                }
                if b.qty < Decimal::zero()
                    || b.settled < Decimal::zero()
                    || b.settled > b.qty
                    || b.cost < Decimal::zero()
                    || (b.qty.is_zero() && !b.cost.is_zero())
                {
                    return Err(err("POSITION_ALLOCATION_INVARIANT"));
                }
                quantity += &b.qty;
                settled += &b.settled;
                cost += &b.cost;
            }
            if quantity != a.qty || settled != a.settled || cost != a.cost {
                return Err(err("POSITION_CONSERVATION"));
            }
            for d in [
                &a.qty,
                &a.settled,
                &a.cost,
                &a.realized,
                &a.realized_exact,
                &a.fees,
            ] {
                bounded(d, false)?;
            }
            self.account(i)?;
        }
        for r in self.state.reservations.values() {
            if &r.remaining + &r.consumed + &r.released != r.quantity
                || r.remaining < Decimal::zero()
            {
                return Err(err("POSITION_RESERVATION_CONSERVATION"));
            }
        }
        for ((c, i), b) in &self.state.allocations {
            if self.holds(i, Some(c), false) > b.settled {
                return Err(err("POSITION_HOLD_EXCEEDS_SETTLED"));
            }
        }
        Ok(())
    }
}
