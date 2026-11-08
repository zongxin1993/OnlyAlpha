//! 原命令、场所订单、已经发生的成交与待发布游标。
use crate::{
    config::Config,
    plan::{Plan, err, number, price_record, quantity_record},
    projection::Projection,
};
use bigdecimal::{BigDecimal as D, Zero};
use onlyalpha_broker::*;
use onlyalpha_domain::{
    base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp, value::OnlyMoney,
};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone)]
pub(crate) struct Order {
    pub submit: BrokerCommand,
    pub venue: String,
    pub status: &'static str,
    pub plan: Option<Plan>,
    filled: D,
    held: D,
    reference: D,
    detail: Value,
}
impl Order {
    pub fn view(&self) -> Result<Option<OrderView>, Error> {
        if self.status == "SUBMITTED" {
            return Ok(None);
        }
        let c = self.submit.record();
        Ok(Some(OrderView::decode(
            &json!({"scope":c["scope"],"order":self.submit.order(),"client":self.submit.client(),
            "venue":self.venue,"request":c["request"],"filled":self.filled.to_plain_string(),"status":self.status}),
        )?))
    }
    pub fn record(&self) -> Value {
        json!({"submit":self.submit.record(),"venue":self.venue,"status":self.status,"filled":self.filled.to_plain_string(),
            "held":self.held.to_plain_string(),"reference":self.reference.to_plain_string(),"detail":self.detail,
            "plan":self.plan.as_ref().map(|p|json!({"id":p.id,"steps":p.steps,"accepted_bar":p.accepted_bar,"cursor":p.cursor,"version":p.version}))})
    }
    pub fn open(&self) -> bool {
        matches!(self.status, "ACCEPTED" | "PARTIALLY_FILLED")
    }
}

#[derive(Clone)]
pub(crate) struct State {
    pub now: i64,
    pub bar_sequence: u64,
    last_bar: BTreeMap<String, Value>,
    pub orders: Vec<Order>,
    pub commands: BTreeMap<String, BrokerCommand>,
    pub rejected: BTreeSet<String>,
    due: BTreeMap<(i64, u64), BrokerCommand>,
    pub facts: Vec<Fact>,
    pub stream_at: Vec<i64>,
    pub outbox: BTreeSet<(i64, usize)>,
    pub projection: Projection,
    pub trade_count: u64,
}
impl State {
    pub fn new(cash: &OnlyMoney) -> Result<Self, Error> {
        Ok(Self {
            now: 0,
            bar_sequence: 0,
            last_bar: BTreeMap::new(),
            orders: Vec::new(),
            commands: BTreeMap::new(),
            rejected: BTreeSet::new(),
            due: BTreeMap::new(),
            facts: Vec::new(),
            stream_at: Vec::new(),
            outbox: BTreeSet::new(),
            projection: Projection::new(cash)?,
            trade_count: 0,
        })
    }
    pub fn order(&self, id: &str) -> Option<usize> {
        self.orders.iter().position(|o| o.submit.order() == id)
    }
    pub fn receive(
        &mut self,
        cfg: &Config,
        c: &BrokerCommand,
        ready: bool,
    ) -> Result<DispatchResult, Error> {
        let result = self.queue(cfg, c, ready)?;
        if result == DispatchResult::Rejected {
            self.commands.insert(c.id().into(), c.clone());
            self.rejected.insert(c.id().into());
        }
        Ok(result)
    }
    fn queue(
        &mut self,
        cfg: &Config,
        c: &BrokerCommand,
        ready_at_dispatch: bool,
    ) -> Result<DispatchResult, Error> {
        let raw = c.record();
        let request = &raw["request"];
        for old in self.commands.values() {
            if old.record()["request"]["request_id"] == request["request_id"] {
                return Err(err("VIRTUAL_REQUEST_CONFLICT"));
            }
            if (old.order() == c.order()
                && (c.operation() == Operation::Submit || old.client() != c.client()))
                || (old.client() == c.client() && old.order() != c.order())
            {
                return Err(err("VIRTUAL_ORDER_CONFLICT"));
            }
        }
        if !ready_at_dispatch {
            return Ok(DispatchResult::Rejected);
        }
        let delay = match c.operation() {
            Operation::Submit => {
                if !matches!(request["order_type"].as_str(), Some("MARKET" | "LIMIT"))
                    || !matches!(request["time_in_force"].as_str(), Some("DAY" | "GTC"))
                    || request["execution_intent"]["position_mode"] != "NETTING"
                    || request["execution_intent"]["close_scope"] != "ANY"
                {
                    return Ok(DispatchResult::Rejected);
                }
                self.orders.push(Order {
                    submit: c.clone(),
                    venue: format!("virtual-order-{:08}", self.orders.len() + 1),
                    status: "SUBMITTED",
                    plan: None,
                    filled: D::zero(),
                    held: D::zero(),
                    reference: D::zero(),
                    detail: Value::Null,
                });
                cfg.submit_ns
            }
            Operation::Cancel => {
                let Some(i) = self.order(c.order()) else {
                    return Ok(DispatchResult::Rejected);
                };
                if self.orders[i].submit.client() != c.client() {
                    return Err(err("VIRTUAL_CANCEL_OWNER"));
                }
                if !self.orders[i].open() && self.orders[i].status != "SUBMITTED" {
                    return Ok(DispatchResult::Rejected);
                }
                cfg.cancel_ns
            }
        };
        let at = self
            .now
            .checked_add(delay)
            .ok_or_else(|| err("VIRTUAL_TIME_OVERFLOW"))?;
        self.commands.insert(c.id().into(), c.clone());
        self.due.insert((at, self.commands.len() as u64), c.clone());
        Ok(DispatchResult::Received)
    }
    fn emit(
        &mut self,
        c: &BrokerCommand,
        kind: &str,
        payload: Value,
        delay: i64,
    ) -> Result<(), Error> {
        let seq = self.facts.len() + 1;
        let at = self
            .now
            .checked_add(delay)
            .ok_or_else(|| err("VIRTUAL_TIME_OVERFLOW"))?;
        let fact = Fact::decode(
            &json!({"scope":c.scope().record(),"session":"virtual-rust","source_sequence":seq,
            "update_id":format!("virtual-update-{seq:08}"),"correlation":c.order(),
            "causation":if kind=="TRADE"{c.order()}else{c.id()},"ts_event":self.now,"ts_init":self.now,"kind":kind,
            "payload":payload,"quality":[]}),
        )?;
        self.outbox.insert((at, self.facts.len()));
        self.facts.push(fact);
        self.stream_at.push(at);
        Ok(())
    }
    fn terminal(
        &mut self,
        i: usize,
        c: &BrokerCommand,
        status: &'static str,
        detail: Value,
    ) -> Result<(), Error> {
        let o = &mut self.orders[i];
        if o.open() {
            let req = &o.submit.record()["request"];
            self.projection.release(
                req,
                &o.held,
                &(number(&req["quantity"]["value"])? - &o.filled),
            )?;
            o.held = D::zero();
            if let Some(plan) = &mut o.plan {
                plan.version += 1;
            }
        }
        o.status = status;
        o.detail = detail.clone();
        let reason = if status == "REJECTED" {
            detail.to_string()
        } else {
            "".into()
        };
        let payload = json!({"order":c.order(),"venue":o.venue,"reason":reason});
        self.emit(c, status, payload, 0)
    }
    fn accept(&mut self, i: usize, cfg: &Config, c: &BrokerCommand) -> Result<(), Error> {
        let control = cfg
            .controls
            .get(&(i as u64 + 1))
            .cloned()
            .unwrap_or(Value::Null);
        if control["action"] == "REJECT_BEFORE_ACCEPTED" {
            return self.terminal(i, c, "REJECTED", control);
        }
        let req = &c.record()["request"];
        let reference = if req["order_type"] == "LIMIT" {
            Some(&req["price"])
        } else {
            self.projection.marks.get(&req["instrument_id"].to_string())
        };
        let Some(reference) = reference else {
            return self.terminal(i, c, "REJECTED", json!("MARKET_REFERENCE_MISSING"));
        };
        let price = number(&reference["value"])?;
        if price <= D::zero() {
            return self.terminal(i, c, "REJECTED", json!("NONPOSITIVE_REFERENCE"));
        }
        let venue = self.orders[i].venue.clone();
        let plan = match Plan::new(&cfg.fill, c, &venue, self.bar_sequence) {
            Ok(p) => p,
            Err(e) => return self.terminal(i, c, "REJECTED", json!(e.to_string())),
        };
        let qty = number(&req["quantity"]["value"])?;
        let side = &req["execution_intent"]["position_side"];
        if req["execution_intent"]["position_effect"] == "OPEN"
            && self.orders.iter().any(|o| {
                let r = &o.submit.record()["request"];
                o.open()
                    && r["instrument_id"] == req["instrument_id"]
                    && r["execution_intent"]["position_side"] != *side
            })
        {
            return self.terminal(i, c, "REJECTED", json!("NETTING_POSITION_CONFLICT"));
        }
        let Some(held) = self.projection.reserve(req, &price, &qty) else {
            return self.terminal(i, c, "REJECTED", json!("INSUFFICIENT_VENUE_CAPACITY"));
        };
        let o = &mut self.orders[i];
        o.held = held;
        o.reference = price;
        o.plan = Some(plan);
        o.status = "ACCEPTED";
        self.emit(c, "ACCEPTED", json!({"order":c.order(),"venue":venue}), 0)?;
        if control["action"] == "ACCEPT_THEN_EXPIRE" {
            self.terminal(i, c, "EXPIRED", control)?;
        }
        Ok(())
    }
    pub fn advance(&mut self, cfg: &Config, now: i64) -> Result<(), Error> {
        if now < self.now {
            return Err(err("VIRTUAL_CLOCK_REGRESSION"));
        }
        // deadline 决定出队顺序，接受/撤单观察记录显式 Clock 此次推进后的时刻。
        self.now = now;
        while let Some((&(due, _), _)) = self.due.first_key_value() {
            if due > now {
                break;
            }
            let (_, c) = self.due.pop_first().expect("pending");
            let i = self
                .order(c.order())
                .ok_or_else(|| err("VIRTUAL_ORDER_MISSING"))?;
            match c.operation() {
                Operation::Submit if self.orders[i].status == "SUBMITTED" => {
                    self.accept(i, cfg, &c)?
                }
                Operation::Cancel
                    if self.orders[i].open() || self.orders[i].status == "SUBMITTED" =>
                {
                    self.terminal(i, &c, "CANCELLED", Value::Null)?
                }
                _ => (),
            }
        }
        Ok(())
    }
    pub fn bar(&mut self, cfg: &Config, seq: u64, bar: &OnlyBar) -> Result<(), Error> {
        let record = bar.to_record();
        let instrument = bar.instrument_id().to_record();
        let key = record["bar_type"].to_string();
        if seq
            != self
                .bar_sequence
                .checked_add(1)
                .ok_or_else(|| err("VIRTUAL_BAR_SEQUENCE"))?
            || !bar.is_closed()
            || record["revision"] != 0
            || self.last_bar.get(&key).is_some_and(|prev| {
                OnlyBar::from_record(prev).is_ok_and(|p| bar.bar_end() <= p.bar_end())
            })
        {
            return Err(err("VIRTUAL_BAR_SEQUENCE"));
        }
        for k in ["open", "low", "high", "close"] {
            if number(&record[k]["value"])? <= D::zero() {
                return Err(err("VIRTUAL_BAR_PRICE"));
            }
        }
        let now = OnlyTimestamp::from_datetime(*bar.ts_event())
            .unix_nanos()
            .to_string()
            .parse()
            .map_err(|_| err("VIRTUAL_BAR_TIME"))?;
        self.advance(cfg, now)?;
        self.bar_sequence = seq;
        self.last_bar.insert(key, record.clone());
        self.projection
            .marks
            .insert(instrument.to_string(), record["close"].clone());
        for i in 0..self.orders.len() {
            if !self.orders[i].open() {
                continue;
            }
            let req = &self.orders[i].submit.record()["request"];
            if req["instrument_id"] != instrument {
                continue;
            }
            let reference = if req["order_type"] == "MARKET" {
                &record["open"]
            } else {
                let limit = number(&req["price"]["value"])?;
                if (req["side"] == "BUY" && number(&record["low"]["value"])? > limit)
                    || (req["side"] == "SELL" && number(&record["high"]["value"])? < limit)
                {
                    continue;
                }
                &req["price"]
            };
            loop {
                let p = self.orders[i].plan.as_ref().expect("open order has plan");
                let Some((offset, q)) = p.steps.get(p.cursor) else {
                    break;
                };
                if *offset > seq - p.accepted_bar {
                    break;
                }
                let quantity = number(&json!(q))?;
                self.fill(i, cfg, &quantity, reference)?;
                if cfg.fill["dispatch_mode"] == "ONE_PER_BAR" {
                    break;
                }
            }
        }
        Ok(())
    }
    fn fill(&mut self, i: usize, cfg: &Config, q: &D, reference: &Value) -> Result<(), Error> {
        let o = &mut self.orders[i];
        let c = o.submit.clone();
        let req = &c.record()["request"];
        let base = number(&reference["value"])?;
        let mut price = base.clone();
        let mut p = reference["precision"].as_i64().expect("validated");
        if let Some(offset) = &cfg.offset {
            price = if req["side"] == "BUY" {
                &base + offset
            } else {
                &base - offset
            };
            if price <= D::zero() {
                return Err(err("VIRTUAL_SLIPPAGE_NONPOSITIVE"));
            }
            p = p.max(8);
            if req["order_type"] == "LIMIT" {
                price = if req["side"] == "BUY" {
                    price.min(base)
                } else {
                    price.max(base)
                };
            }
        }
        let price = price_record(&price, p)?;
        let quantity =
            quantity_record(q, req["quantity"]["precision"].as_i64().expect("validated"))?;
        let left = number(&req["quantity"]["value"])? - &o.filled - q;
        let remaining_hold = self.projection.remaining_hold(req, &o.reference, &left);
        self.projection
            .fill(req, q, &price, &(&o.held - &remaining_hold))?;
        o.filled += q;
        o.held = remaining_hold;
        o.status = if left.is_zero() {
            "FILLED"
        } else {
            "PARTIALLY_FILLED"
        };
        let plan = o.plan.as_mut().expect("open order");
        plan.cursor += 1;
        plan.version += 1;
        self.trade_count += 1;
        let id = |value: String| json!({"schema_version":1,"value":value});
        let time = json!({"schema_version":1,"unix_nanos":self.now});
        let n = self.trade_count;
        let fill = json!({"schema_version":1,"order_id":id(c.order().into()),"venue_order_id":id(o.venue.clone()),
            "trade_id":id(format!("virtual-trade-{n:08}")),"venue_trade_id":id(format!("virtual-venue-trade-{n:08}")),
            "quantity":quantity,"price":price,"reference_price":reference,"ts_event":time,"ts_init":time,"liquidity_side":"TAKER",
            "external_event_id":format!("virtual-fill-{n:08}"),"external_sequence":self.facts.len()+1,"metadata":{}});
        self.emit(
            &c,
            "TRADE",
            json!({"order":c.order(),"fill":fill}),
            cfg.fill_ns,
        )
    }
    pub fn pending_actions(&self) -> Vec<Value> {
        self.due
            .iter()
            .map(|((at, serial), c)| json!({"due":at,"serial":serial,"command":c.id()}))
            .collect()
    }
}
