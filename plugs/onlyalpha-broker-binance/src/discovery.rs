use super::*;
use crate::evidence::journal_head;
use crate::gateway::{SpotBroker, Venue};
use onlyalpha_broker::*;

struct DiscoveryQuery<'a> {
    venue: &'a Venue,
    history: Vec<Record>,
    budget: Budget,
    observed: Option<&'a mut Vec<Fact>>,
}
impl DiscoveryPort for DiscoveryQuery<'_> {
    fn discover(&mut self, command: &BrokerCommand) -> Result<Discovery> {
        let c = self.venue.orders.borrow().original(command)?.clone();
        let head = journal_head(&self.history, self.history.len() as u64)?;
        let read = self.venue.current_order(&c, &self.budget);
        // 单独的 -2013/404、空/截断分页、重置或缺证始终不会出具负证明。
        let (raw, order, view) = match read {
            Ok(data) => data,
            Err(error) if error.to_string() == "BINANCE_ORDER_NOT_VISIBLE" => {
                let (seq, hash) = self.venue.evidence.head();
                let proof = digest(&json!([command.record(), head, hash]));
                return Discovery::new(
                    command.clone(),
                    proof,
                    seq,
                    Presence::Inconclusive,
                    None,
                    Vec::new(),
                );
            }
            Err(error) => return Err(error),
        };
        if command.operation() == Operation::Cancel
            && !(order["status"] == "CANCELED" && order["clientOrderId"] == cancel_client(command))
        {
            return Discovery::new(
                command.clone(),
                digest(&json!([command.record(), head, raw.hash])),
                raw.sequence,
                Presence::Inconclusive,
                None,
                Vec::new(),
            );
        }
        let trades = self.venue.trades_for(&c, &order, &self.budget)?;
        let (last, check, view2) = self.venue.current_order(&c, &self.budget)?;
        if view != view2
            || check["updateTime"] != order["updateTime"]
            || check["clientOrderId"] != order["clientOrderId"]
        {
            return Err(err("BINANCE_DISCOVERY_ORDER_CHANGED"));
        }
        let facts = observed_facts(&c, &order, &view, &trades, last.at_ns)?;
        let mut previous = BTreeMap::new();
        for row in &self.history {
            let e = row.record()["event"].clone();
            if e["kind"] == "DISCOVERY" && e["command_id"] == command.id() {
                if e["discovery"]["command"] != command.record() {
                    return Err(err("BINANCE_DISCOVERY_COMMAND"));
                }
                for f in e["discovery"]["facts"]
                    .as_array()
                    .ok_or_else(|| err("BINANCE_DISCOVERY_FACT"))?
                {
                    let f = Fact::decode(f)?;
                    previous.insert(f.identity().to_string(), f);
                }
            }
        }
        let mut missing = Vec::new();
        for f in facts {
            match previous.remove(f.identity()) {
                Some(prev) if prev.fingerprint() != f.fingerprint() => {
                    return Err(err("BINANCE_DISCOVERY_FACT_CONFLICT"));
                }
                Some(_) => (),
                None => missing.push(f),
            }
        }
        // 已投递的 Accepted 在转为终态后不会出现在新的 terminal-only 快照。
        if previous.values().any(|f| f.record()["kind"] != "ACCEPTED") {
            return Err(err("BINANCE_DISCOVERY_HISTORY_AHEAD"));
        }
        let proof = digest(&json!([command.record(), head, raw.hash, last.hash]));
        if let Some(observed) = self.observed.as_deref_mut() {
            observed.clone_from(&missing);
        }
        Discovery::new(
            command.clone(),
            proof,
            last.sequence,
            Presence::Present,
            Some(view),
            missing,
        )
    }
}
// 同一份场所快照通过主动对账和重连调查产生相同的规范事实。
fn observed_facts(
    c: &BrokerCommand,
    order: &Value,
    view: &OrderView,
    trades: &[Value],
    received: i64,
) -> Result<Vec<Fact>> {
    let prov = Provenance {
        session: "rest",
        received,
        source: "binance-discovery",
    };
    let event = ns(&order["updateTime"])?;
    let num = order["orderId"]
        .as_u64()
        .ok_or_else(|| err("BINANCE_ORDER_ID"))?;
    let snapshot = view.record();
    let status = snapshot["status"]
        .as_str()
        .ok_or_else(|| err("BINANCE_ORDER_STATE"))?;
    let mut facts = Vec::new();
    if matches!(status, "ACCEPTED" | "PARTIALLY_FILLED") {
        facts.push(order_fact(c, num, "ACCEPTED", event, &prov, "")?);
    }
    for row in trades {
        facts.push(trade_fact(c, row, &prov)?);
    }
    if matches!(status, "CANCELLED" | "EXPIRED" | "REJECTED") {
        facts.push(order_fact(
            c,
            num,
            status,
            event,
            &prov,
            if status == "REJECTED" {
                "VENUE_REJECTED"
            } else {
                ""
            },
        )?);
    }
    Ok(facts)
}
impl<J: Journal> SpotBroker<J> {
    pub fn reconcile(&mut self, id: &str) -> Result<()> {
        self.venue.trusted.set(false);
        let mut observed = Vec::new();
        let mut d = DiscoveryQuery {
            venue: &self.venue,
            history: self.journal.records()?,
            budget: self.venue.config.budget(),
            observed: Some(&mut observed),
        };
        let result = self.broker.reconcile(&mut self.journal, &mut d, id);
        if result
            .as_ref()
            .is_err_and(|e| e.to_string() == "BROKER_INBOUND_OVERFLOW")
        {
            // 完整 Discovery 尚未提交。让 Runtime 先消费能装下的规范事实，下次仍对原单做完整调查。
            self.ingest_in_order(&observed)?;
        }
        result
    }
    pub fn resolve(&mut self, r: &impl RuntimeReader, id: &str) -> Result<()> {
        let mut d = DiscoveryQuery {
            venue: &self.venue,
            history: self.journal.records()?,
            budget: self.venue.config.budget(),
            observed: None,
        };
        self.broker.resolve(&mut self.journal, r, &mut d, id)
    }
    fn ingest_in_order(&mut self, facts: &[Fact]) -> Result<()> {
        for fact in facts {
            self.broker
                .ingest(&mut self.journal, std::slice::from_ref(fact))?;
        }
        Ok(())
    }
    /// 签名账户和开放订单，加上每张已发订单的完整成交、Runtime 同值订单和原事实回执。
    pub fn synchronize(&mut self, r: &impl RuntimeReader) -> Result<()> {
        self.venue.trusted.set(false);
        self.broker.set_health(false, false, false);
        self.deliver_deferred()?;
        if self.venue.subscription.get().is_none() || !self.broker.pending().is_empty() {
            return Err(err("BINANCE_STREAM_NOT_READY"));
        }
        let b = self.venue.config.budget();
        self.venue.account_info(&b)?;
        let open = self
            .venue
            .open_orders(&b)?
            .into_iter()
            .map(|v| (v.record()["order"].as_str().unwrap_or("").to_owned(), v))
            .collect::<BTreeMap<_, _>>();
        let submits = self.venue.orders.borrow().submits.clone();
        for c in submits.values() {
            if !self.venue.orders.borrow().dispatched_at(c.id(), u64::MAX) {
                if open.contains_key(c.order()) {
                    return Err(err("BINANCE_UNSENT_ORDER_VISIBLE"));
                }
                continue;
            }
            let (_, raw, view) = self.venue.current_order(c, &b)?;
            let active = matches!(
                view.record()["status"].as_str(),
                Some("ACCEPTED" | "PARTIALLY_FILLED")
            );
            if open.get(c.order()) != active.then_some(&view) {
                return Err(err("BINANCE_OPEN_ORDER_MISMATCH"));
            }
            let trades = self.venue.trades_for(c, &raw, &b)?;
            let (last, confirm, fresh) = self.venue.current_order(c, &b)?;
            if view != fresh
                || raw["updateTime"] != confirm["updateTime"]
                || raw["clientOrderId"] != confirm["clientOrderId"]
            {
                return Err(err("BINANCE_DISCOVERY_ORDER_CHANGED"));
            }
            let facts = observed_facts(c, &raw, &view, &trades, last.at_ns)?;
            if !facts.is_empty() {
                self.ingest_in_order(&facts)?;
                if !self.broker.pending().is_empty() {
                    return Err(err("BINANCE_APPLICATION_RECEIPT_REQUIRED"));
                }
            }
            if r.order_view(c)?.as_ref() != Some(&view) {
                return Err(err("BINANCE_RUNTIME_ORDER_MISMATCH"));
            }
            if self.broker.command_state(c.id()) != Some(CommandState::Resolved) {
                return Err(err("BINANCE_ORDER_RECONCILIATION_REQUIRED"));
            }
        }
        self.broker.set_connection(Connection::Ready);
        self.broker.set_health(true, true, true);
        if !self.broker.ready() {
            self.broker.set_health(true, false, false);
            return Err(err("BINANCE_BROKER_UNRESOLVED"));
        }
        self.venue.trusted.set(true);
        Ok(())
    }
}
