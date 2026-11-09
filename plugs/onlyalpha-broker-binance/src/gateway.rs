use super::*;
use crate::evidence::{Evidence, Orders, journal_head};
use onlyalpha_broker::*;
use onlyalpha_integration_contract::source::{Clock, Trust};
use std::{
    cell::{Cell, RefCell},
    sync::Arc,
};

pub(crate) struct Venue {
    pub(crate) config: Config,
    pub(crate) io: Box<dyn Exchange>,
    pub(crate) evidence: Evidence,
    pub(crate) clock: Arc<dyn Clock>,
    pub(crate) orders: RefCell<Orders>,
    authed: Cell<bool>,
    trade: Cell<bool>,
    pub(crate) trusted: Cell<bool>,
    pub(crate) subscription: Cell<Option<(u64, u64)>>,
}
impl Venue {
    pub(crate) fn now(&self) -> Result<i64> {
        self.clock
            .now_ns()
            .map_err(|_| err("BINANCE_CLOCK"))
            .and_then(|t| {
                if t >= 0 {
                    Ok(t)
                } else {
                    Err(err("BINANCE_CLOCK"))
                }
            })
    }
    pub(crate) fn read(
        &self,
        method: &str,
        path: &str,
        p: BTreeMap<String, String>,
        command: Option<&BrokerCommand>,
        budget: &Budget,
    ) -> Result<(Observation, Value)> {
        let result = self.io.request(method, path, &p, budget)?;
        let action = json!({"kind":"REST","method":method,"path":path,"params":p,"command":command.map(BrokerCommand::record),"retry_after_ms":result.retry_after_ms});
        let raw = self.evidence.append(
            action,
            result.status,
            self.now()?,
            result.bytes,
            self.config.max_bytes,
        )?;
        let value = wire_json(&raw.bytes)?;
        if matches!(raw.status, 401 | 403) || matches!(value["code"].as_i64(), Some(-2014 | -2015))
        {
            self.authed.set(false);
            self.trade.set(false);
            self.trusted.set(false);
        }
        Ok((raw, value))
    }
    pub(crate) fn get(
        &self,
        path: &str,
        p: BTreeMap<String, String>,
        c: Option<&BrokerCommand>,
        b: &Budget,
    ) -> Result<(Observation, Value)> {
        let (raw, v) = self.read("GET", path, p, c, b)?;
        if raw.status != 200 || v.get("code").is_some() {
            return Err(err(match (raw.status, v["code"].as_i64()) {
                (418 | 429, _) => "BINANCE_RATE_LIMIT",
                (_, Some(-2013)) => "BINANCE_ORDER_NOT_VISIBLE",
                (401 | 403, _) | (_, Some(-2014 | -2015)) => "BINANCE_PERMISSION",
                _ => "BINANCE_QUERY_INCONCLUSIVE",
            }));
        }
        Ok((raw, v))
    }
    fn owner(&self, s: &Scope) -> Result<()> {
        if s != &self.config.scope || !self.authed.get() {
            return Err(err("BINANCE_ACCOUNT_SCOPE"));
        }
        Ok(())
    }
    pub(crate) fn account_info(&self, b: &Budget) -> Result<(Observation, Value)> {
        let (raw, v) = self.get(
            "/api/v3/account",
            BTreeMap::from([("omitZeroBalances".into(), "false".into())]),
            None,
            b,
        )?;
        if v["uid"].as_u64() != Some(self.config.uid)
            || v["accountType"] != "SPOT"
            || !v["balances"].is_array()
            || !v["canTrade"].is_boolean()
        {
            self.authed.set(false);
            self.trade.set(false);
            self.trusted.set(false);
            return Err(err("BINANCE_AUTHENTICATED_ACCOUNT_CONFLICT"));
        }
        self.authed.set(true);
        self.trade.set(
            self.config.access == Access::Trading
                && v["canTrade"] == true
                && v["permissions"]
                    .as_array()
                    .is_some_and(|p| p.iter().any(|v| v == "SPOT")),
        );
        Ok((raw, v))
    }
    // 已认证 REST 返回的订单或成交关系若无法核实，后续有效查询不单独恢复交易信任。
    fn verify_rest_relation<T>(&self, observation: Result<T>) -> Result<T> {
        observation.inspect_err(|_| self.trusted.set(false))
    }
    pub(crate) fn current_order(
        &self,
        c: &BrokerCommand,
        b: &Budget,
    ) -> Result<(Observation, Value, OrderView)> {
        self.owner(c.scope())?;
        let (num, clients) = {
            let orders = self.orders.borrow();
            if !orders.dispatched_at(c.id(), u64::MAX) {
                return Err(err("BINANCE_UNDISPATCHED_ORDER"));
            }
            (orders.venues.get(c.order()).copied(), orders.clients(c))
        };
        let mut p = BTreeMap::from([("symbol".into(), symbol(c)?)]);
        if let Some(n) = num {
            p.insert("orderId".into(), n.to_string());
        } else {
            p.insert("origClientOrderId".into(), wire_client(c.client()));
        }
        let (raw, v) = self.get("/api/v3/order", p, Some(c), b)?;
        let view = self.verify_rest_relation(order_view(c, num, &clients, &v))?;
        self.verify_rest_relation(
            self.orders.borrow_mut().bind(
                c,
                v["orderId"]
                    .as_u64()
                    .ok_or_else(|| err("BINANCE_ORDER_ID"))?,
            ),
        )?;
        Ok((raw, v, view))
    }
    pub(crate) fn trades_for(
        &self,
        c: &BrokerCommand,
        raw: &Value,
        b: &Budget,
    ) -> Result<Vec<Value>> {
        let venue = raw["orderId"]
            .as_u64()
            .ok_or_else(|| err("BINANCE_ORDER_ID"))?;
        let mut pages = TradePages::new(
            c,
            venue,
            raw["executedQty"]
                .as_str()
                .ok_or_else(|| err("BINANCE_FILLED"))?,
            1000,
        )?;
        let symbol = symbol(c)?;
        loop {
            let p = BTreeMap::from([
                ("symbol".into(), symbol.clone()),
                ("orderId".into(), venue.to_string()),
                ("fromId".into(), pages.cursor().to_string()),
                ("limit".into(), "1000".into()),
            ]);
            let (_, rows) = self.get("/api/v3/myTrades", p, Some(c), b)?;
            if self.verify_rest_relation(pages.push(&rows))? {
                return Ok(pages.rows);
            }
        }
    }
    pub(crate) fn open_orders(&self, b: &Budget) -> Result<Vec<OrderView>> {
        let (_, v) = self.get("/api/v3/openOrders", BTreeMap::new(), None, b)?;
        self.verify_rest_relation(self.decode_open_orders(&v))
    }
    fn decode_open_orders(&self, v: &Value) -> Result<Vec<OrderView>> {
        let mut seen = BTreeMap::new();
        for row in v.as_array().ok_or_else(|| err("BINANCE_OPEN_ORDERS"))? {
            let mut registry = self.orders.borrow_mut();
            let original = registry
                .by_wire(
                    row["clientOrderId"]
                        .as_str()
                        .ok_or_else(|| err("BINANCE_CLIENT_ID"))?,
                    u64::MAX,
                )?
                .clone();
            let view = order_view(
                &original,
                registry.venues.get(original.order()).copied(),
                &registry.clients(&original),
                row,
            )?;
            if !matches!(
                view.record()["status"].as_str(),
                Some("ACCEPTED" | "PARTIALLY_FILLED")
            ) || seen.insert(original.order().to_string(), view).is_some()
            {
                return Err(err("BINANCE_OPEN_ORDERS_IDENTITY"));
            }
            registry.bind(
                &original,
                row["orderId"]
                    .as_u64()
                    .ok_or_else(|| err("BINANCE_ORDER_ID"))?,
            )?;
        }
        Ok(seen.into_values().collect())
    }
    fn stream_fact(&self, active: u64, session: u64, raw: &Observation, cut: u64) -> Result<Fact> {
        let doc = wire_json(&raw.bytes)?;
        let event = subscription_event(active, &doc)?;
        let event_time = ns(&event["E"])?;
        let session = format!("ws-{session}");
        let prov = Provenance {
            session: &session,
            received: raw.at_ns,
            source: "binance-stream",
        };
        if event["e"] == "outboundAccountPosition" {
            let items = balances(&self.config, &event["B"], event_time, true)?;
            return prov.fact(
                &self.config.scope,
                "balances",
                "BALANCES",
                event_time,
                json!(items.iter().map(Snapshot::record).collect::<Vec<_>>()),
            );
        }
        let client = if event["x"] == "CANCELED" {
            event["C"]
                .as_str()
                .filter(|s| !s.is_empty())
                .or_else(|| event["c"].as_str())
        } else {
            event["c"].as_str()
        }
        .ok_or_else(|| err("BINANCE_STREAM_CLIENT"))?;
        let c = self.orders.borrow().by_wire(client, cut)?.clone();
        let num = event["i"].as_u64().ok_or_else(|| err("BINANCE_ORDER_ID"))?;
        let wire = submit_params(&c)?;
        let s = &wire["symbol"];
        if event["s"] != *s || event["S"] != wire["side"] || event["o"] != wire["type"] {
            return Err(err("BINANCE_STREAM_ORDER_CONFLICT"));
        }
        check_order_terms(&wire, &event["q"], &event["p"], &event["f"])?;
        let fact = match (event["x"].as_str(), event["X"].as_str()) {
            (Some("NEW"), Some("NEW")) => order_fact(&c, num, "ACCEPTED", event_time, &prov, ""),
            (Some("CANCELED"), Some("CANCELED")) => {
                order_fact(&c, num, "CANCELLED", event_time, &prov, "")
            }
            (Some("REJECTED"), Some("REJECTED")) => {
                order_fact(&c, num, "REJECTED", event_time, &prov, "VENUE_REJECTED")
            }
            (Some("EXPIRED" | "TRADE_PREVENTION"), Some("EXPIRED" | "EXPIRED_IN_MATCH")) => {
                order_fact(&c, num, "EXPIRED", event_time, &prov, "")
            }
            (Some("TRADE"), Some("PARTIALLY_FILLED" | "FILLED")) => trade_fact(
                &c,
                &json!({"symbol":s,"orderId":num,"id":event["t"],"time":event["T"],"qty":event["l"],"price":event["L"],"isMaker":event["m"],"isBuyer":event["S"]=="BUY"}),
                &prov,
            ),
            _ => Err(err("BINANCE_STREAM_ORDER_STATE")),
        }?;
        self.orders.borrow_mut().bind(&c, num)?;
        Ok(fact)
    }
}
#[derive(Clone)]
struct DeferredRaw {
    sequence: u64,
    hash: String,
    session: (u64, u64),
}
impl Venue {
    fn stream_observation(
        &self,
        raw: &Observation,
        session: &mut Option<(u64, u64)>,
        history: &[Record],
    ) -> Result<Option<Fact>> {
        match raw.action["kind"].as_str() {
            Some("SUBSCRIPTION") => {
                let request = raw.action["request"]
                    .as_str()
                    .ok_or_else(|| err("BINANCE_SUBSCRIPTION_ACK"))?;
                *session = subscription_id(request, &wire_json(&raw.bytes)?)
                    .ok()
                    .map(|id| (id, raw.sequence));
                Ok(None)
            }
            Some("WS") => {
                let (id, epoch) = session.ok_or_else(|| err("BINANCE_STREAM_SESSION"))?;
                if raw.action["epoch"] != epoch || raw.action["subscription"] != id {
                    return Err(err("BINANCE_STREAM_SESSION"));
                }
                let cut = raw.action["journal_length"]
                    .as_u64()
                    .ok_or_else(|| err("BINANCE_OBSERVATION_JOURNAL"))?;
                if raw.action["journal_hash"] != journal_head(history, cut)? {
                    return Err(err("BINANCE_OBSERVATION_JOURNAL"));
                }
                if terminated_subscription(id, &wire_json(&raw.bytes)?)? {
                    *session = None;
                    return Ok(None);
                }
                self.stream_fact(id, epoch, raw, cut).map(Some)
            }
            Some("REST") => Ok(None),
            _ => Err(err("BINANCE_EVIDENCE_KIND")),
        }
    }
}
struct Prepared<'a> {
    venue: &'a Venue,
    original: BrokerCommand,
    params: BTreeMap<String, String>,
    budget: Budget,
}
impl TradingPort for Prepared<'_> {
    fn capabilities(&self) -> Capabilities {
        capabilities(self.venue.config.access)
    }
    fn dispatch(&mut self, c: &BrokerCommand) -> Result<DispatchResult> {
        let method = if c.operation() == Operation::Submit {
            "POST"
        } else {
            "DELETE"
        };
        let (raw, v) = self.venue.read(
            method,
            "/api/v3/order",
            self.params.clone(),
            Some(c),
            &self.budget,
        )?;
        if !(200..300).contains(&raw.status) {
            return Ok(error_outcome(raw.status, v["code"].as_i64()));
        }
        let known = self.venue.orders.borrow().venues.get(c.order()).copied();
        let num = ack_venue(c, &self.original, known, &v)?;
        self.venue.orders.borrow_mut().bind(&self.original, num)?;
        Ok(DispatchResult::Received)
    }
}
fn capabilities(access: Access) -> Capabilities {
    let mut names = vec![
        "CONNECT",
        "AUTHENTICATE",
        "QUERY_BALANCES",
        "QUERY_POSITIONS",
        "QUERY_OPEN_ORDERS",
        "QUERY_ORDERS",
        "QUERY_TRADES",
        "QUERY_FEE_EVIDENCE",
        "PUSH_ORDER_UPDATES",
        "PUSH_TRADE_UPDATES",
    ];
    if access == Access::Trading {
        names.extend([
            "SUBMIT_ORDER",
            "CANCEL_ORDER",
            "MARKET_ORDER",
            "LIMIT_ORDER",
            "PARTIAL_FILL",
        ]);
    }
    Capabilities::new(&names).expect("static capabilities")
}
pub struct SpotBroker<J: Journal> {
    pub(crate) venue: Venue,
    pub(crate) broker: Broker,
    pub(crate) journal: J,
    deferred: Option<DeferredRaw>,
}
impl<J: Journal> SpotBroker<J> {
    #[expect(
        clippy::too_many_arguments,
        reason = "宿主显式注入两个持久化端口、工件与凭据绑定、信任根和时钟"
    )]
    pub fn open(
        config: Config,
        secrets: BoundCredentials,
        trust: &Trust,
        clock: Arc<dyn Clock>,
        journal: J,
        store: Box<dyn ObservationStore>,
        checkpoint: Option<&Checkpoint>,
        capacity: usize,
    ) -> Result<Self> {
        config.validate()?;
        if secrets.binding != config.binding {
            return Err(err("BINANCE_SECRET_BINDING"));
        }
        let io = Native::new(&config, secrets.keys, trust, clock.clone())?;
        Self::restore(
            config,
            clock,
            journal,
            store,
            checkpoint,
            capacity,
            Box::new(io),
        )
    }
    pub(crate) fn restore(
        config: Config,
        clock: Arc<dyn Clock>,
        journal: J,
        store: Box<dyn ObservationStore>,
        checkpoint: Option<&Checkpoint>,
        capacity: usize,
        io: Box<dyn Exchange>,
    ) -> Result<Self> {
        config.validate()?;
        let broker = Broker::recover(config.scope.clone(), &journal, capacity)?;
        let evidence = Evidence::open(&config, store);
        let rows = journal.records()?;
        let length = evidence.store.len(&evidence.binding)?;
        if let Some(cp) = checkpoint {
            if cp.binding != evidence.binding
                || cp.observation_length > length
                || cp.journal_hash != journal_head(&rows, cp.journal_length)?
                || cp.observation_length == 0 && cp.observation_hash != "0".repeat(64)
            {
                return Err(err("BINANCE_CHECKPOINT"));
            }
        } else if !rows.is_empty() || length != 0 {
            return Err(err("BINANCE_CHECKPOINT_REQUIRED"));
        }
        // 先核对完整原文链和 checkpoint，再允许向 Broker Journal 投递任何恢复事实。
        for n in 1..=length {
            let raw = evidence.store.read(&evidence.binding, n)?;
            evidence.replay(&raw, config.max_bytes)?;
            if checkpoint
                .is_some_and(|cp| cp.observation_length == n && cp.observation_hash != raw.hash)
            {
                return Err(err("BINANCE_CHECKPOINT"));
            }
        }
        let mut orders = Orders::default();
        orders.load(&journal, &config.scope)?;
        let mut s = Self {
            broker,
            journal,
            deferred: None,
            venue: Venue {
                config,
                clock,
                io,
                evidence,
                orders: RefCell::new(orders),
                authed: Cell::new(false),
                trade: Cell::new(false),
                trusted: Cell::new(false),
                subscription: Cell::new(None),
            },
        };
        let mut session = None;
        let mut previous = "0".repeat(64);
        for n in 1..=length {
            let v = &s.venue;
            let raw = v.evidence.store.read(&v.evidence.binding, n)?;
            v.evidence
                .verify(&raw, n - 1, &previous, v.config.max_bytes)?;
            if n == length && v.evidence.head().1 != raw.hash {
                return Err(err("BINANCE_EVIDENCE_PREFIX"));
            }
            previous = raw.hash.clone();
            match raw.action["kind"].as_str() {
                Some("SUBSCRIPTION" | "WS") => {
                    if let Some(f) = v.stream_observation(&raw, &mut session, &rows)?
                        && let Err(error) = s.broker.ingest(&mut s.journal, &[f])
                    {
                        if error.to_string() != "BROKER_INBOUND_OVERFLOW" {
                            return Err(error);
                        }
                        // 原文已经通过会话、Journal 前缀和订单检查。只记第一条未投递的原文位置。
                        s.deferred.get_or_insert(DeferredRaw {
                            sequence: n,
                            hash: raw.hash.clone(),
                            session: session.ok_or_else(|| err("BINANCE_STREAM_SESSION"))?,
                        });
                    }
                }
                Some("REST")
                    if raw.status >= 200
                        && raw.status < 300
                        && !raw.action["command"].is_null()
                        && raw.action["path"] == "/api/v3/order" =>
                {
                    let c = BrokerCommand::decode(&raw.action["command"])?;
                    let original = v.orders.borrow().original(&c)?.clone();
                    if c.operation() == Operation::Submit && c != original
                        || c.operation() == Operation::Cancel
                            && v.orders.borrow().cancels.get(c.id()) != Some(&c)
                    {
                        return Err(err("BINANCE_OBSERVATION_COMMAND"));
                    }
                    if let Ok(payload) = wire_json(&raw.bytes) {
                        let known = v.orders.borrow().venues.get(c.order()).copied();
                        if raw.action["method"] == "GET" {
                            if order_view(
                                &original,
                                known,
                                &v.orders.borrow().clients(&original),
                                &payload,
                            )
                            .is_ok()
                            {
                                v.orders.borrow_mut().bind(
                                    &original,
                                    payload["orderId"]
                                        .as_u64()
                                        .ok_or_else(|| err("BINANCE_ORDER_ID"))?,
                                )?;
                            }
                        } else if let Ok(num) = ack_venue(&c, &original, known, &payload) {
                            v.orders.borrow_mut().bind(&original, num)?;
                        }
                    }
                }
                Some("REST") => (),
                _ => return Err(err("BINANCE_EVIDENCE_KIND")),
            }
        }
        Ok(s)
    }
    pub fn checkpoint(&self) -> Result<Checkpoint> {
        let history = self.journal.records()?;
        let n = history.len() as u64;
        let (length, hash) = self.venue.evidence.head();
        if self
            .venue
            .evidence
            .store
            .len(&self.venue.evidence.binding)?
            != length
        {
            return Err(err("BINANCE_EVIDENCE_PREFIX"));
        }
        Ok(Checkpoint {
            binding: self.venue.evidence.binding.clone(),
            journal_length: n,
            journal_hash: journal_head(&history, n)?,
            observation_length: length,
            observation_hash: hash,
        })
    }
    pub fn capabilities(&self) -> Capabilities {
        capabilities(self.venue.config.access)
    }
    pub fn pending(&self) -> &[Fact] {
        self.broker.pending()
    }
    pub fn command_state(&self, id: &str) -> Option<CommandState> {
        self.broker.command_state(id)
    }
    pub fn acknowledge(&mut self, r: &impl RuntimeReader, id: &str) -> Result<()> {
        self.broker.acknowledge(&mut self.journal, r, id)?;
        self.deliver_deferred()
    }
    pub(crate) fn deliver_deferred(&mut self) -> Result<()> {
        let Some(cursor) = self.deferred.clone() else {
            return Ok(());
        };
        let (end, head) = self.venue.evidence.head();
        let rows = self.journal.records()?;
        let mut previous = None;
        let mut session = Some(cursor.session);
        for n in cursor.sequence..=end {
            let evidence = &self.venue.evidence;
            let raw = evidence.store.read(&evidence.binding, n)?;
            if n == cursor.sequence && raw.hash != cursor.hash || n == end && raw.hash != head {
                return Err(err("BINANCE_EVIDENCE_PREFIX"));
            }
            evidence.verify(
                &raw,
                n - 1,
                previous.as_deref().unwrap_or(&raw.previous),
                self.venue.config.max_bytes,
            )?;
            previous = Some(raw.hash.clone());
            if let Some(f) = self.venue.stream_observation(&raw, &mut session, &rows)? {
                match self.broker.ingest(&mut self.journal, &[f]) {
                    Ok(()) => (),
                    Err(error) if error.to_string() == "BROKER_INBOUND_OVERFLOW" => {
                        self.deferred = Some(DeferredRaw {
                            sequence: n,
                            hash: raw.hash,
                            session: session.ok_or_else(|| err("BINANCE_STREAM_SESSION"))?,
                        });
                        return Ok(());
                    }
                    Err(error) => return Err(error),
                }
            }
        }
        self.deferred = None;
        Ok(())
    }
    pub fn ready(&self) -> bool {
        self.deferred.is_none()
            && self.broker.pending().is_empty()
            && self.broker.ready()
            && self.venue.trusted.get()
            && self.venue.authed.get()
            && self.venue.trade.get()
    }
    pub fn subscribe(&mut self) -> Result<()> {
        self.venue.owner(&self.venue.config.scope)?;
        self.venue.trusted.set(false);
        self.venue.subscription.set(None);
        self.broker.set_health(true, false, false);
        let request = format!(
            "subscribe-{}",
            self.venue
                .evidence
                .head()
                .0
                .checked_add(1)
                .ok_or_else(|| err("BINANCE_SEQUENCE"))?
        );
        let bytes = self
            .venue
            .io
            .subscribe(&request, &self.venue.config.budget())?;
        let raw = self.venue.evidence.append(
            json!({"kind":"SUBSCRIPTION","request":request}),
            200,
            self.venue.now()?,
            bytes,
            self.venue.config.max_bytes,
        )?;
        let id = subscription_id(&request, &wire_json(&raw.bytes)?)?;
        self.venue.subscription.set(Some((id, raw.sequence)));
        Ok(())
    }
    pub fn poll(&mut self) -> Result<()> {
        let result = (|| {
            if self.deferred.is_some() {
                return Err(err("BROKER_INBOUND_OVERFLOW"));
            }
            let active = self
                .venue
                .subscription
                .get()
                .ok_or_else(|| err("BINANCE_STREAM_SESSION"))?;
            let bytes = self.venue.io.next(&self.venue.config.budget())?;
            let rows = self.journal.records()?;
            let cut = rows.len() as u64;
            let action = json!({"kind":"WS","subscription":active.0,"epoch":active.1,"journal_length":cut,"journal_hash":journal_head(&rows,cut)?});
            let raw = self.venue.evidence.append(
                action,
                200,
                self.venue.now()?,
                bytes,
                self.venue.config.max_bytes,
            )?;
            let fact = self
                .venue
                .stream_observation(&raw, &mut Some(active), &rows)?
                .ok_or_else(|| err("BINANCE_SUBSCRIPTION_TERMINATED"))?;
            let admitted = self.broker.ingest(&mut self.journal, &[fact]);
            if admitted
                .as_ref()
                .is_err_and(|error| error.to_string() == "BROKER_INBOUND_OVERFLOW")
            {
                self.deferred = Some(DeferredRaw {
                    sequence: raw.sequence,
                    hash: raw.hash,
                    session: active,
                });
            }
            admitted
        })();
        if result.is_err() {
            self.venue.io.close();
            self.venue.trusted.set(false);
            self.venue.subscription.set(None);
            self.broker
                .set_health(self.venue.authed.get(), false, false);
        }
        result
    }
    pub fn dispatch(&mut self, r: &impl RuntimeReader, c: &BrokerCommand) -> Result<CommandState> {
        if self.venue.config.access != Access::Trading {
            return Err(err("BINANCE_READ_ONLY"));
        }
        if c.scope() != &self.venue.config.scope {
            return Err(err("BINANCE_COMMAND_SCOPE"));
        }
        let b = self.venue.config.budget();
        let state = self.broker.command_state(c.id());
        let retry = state.is_some_and(|s| s != CommandState::Durable);
        let mut original = c.clone();
        let mut params = BTreeMap::new();
        if !retry {
            self.venue.owner(c.scope())?;
            self.venue.orders.borrow().check(c)?;
            if c.operation() == Operation::Submit {
                if !self.ready() {
                    return Err(err("BINANCE_NOT_READY"));
                }
                params = submit_params(c)?;
            } else {
                original = self.venue.orders.borrow().original(c)?.clone();
                let (_, venue, _) = self.venue.current_order(&original, &b)?;
                let num = venue["orderId"]
                    .as_u64()
                    .ok_or_else(|| err("BINANCE_CANCEL_ORDER_ID"))?;
                params = BTreeMap::from([
                    ("symbol".into(), symbol(&original)?),
                    ("orderId".into(), num.to_string()),
                    ("origClientOrderId".into(), wire_client(c.client())),
                    ("newClientOrderId".into(), cancel_client(c)),
                ]);
            }
            self.venue.io.preflight(&b)?;
        }
        let mut prepared = Prepared {
            venue: &self.venue,
            original,
            params,
            budget: b,
        };
        let result = self.broker.dispatch(&mut self.journal, r, &mut prepared, c);
        self.venue
            .orders
            .borrow_mut()
            .load(&self.journal, &self.venue.config.scope)?;
        // Runtime 可以在写意图前拒绝单个请求；连接信任由真实的持久化和发送结果决定。
        if !self.broker.ready() || matches!(result, Ok(CommandState::Unknown)) {
            self.venue.trusted.set(false);
        }
        result
    }
}
impl<J: Journal> ConnectionPort for SpotBroker<J> {
    fn connect(&mut self) -> Result<Connection> {
        self.disconnect()?;
        self.broker.set_connection(Connection::Connected);
        Ok(Connection::Connected)
    }
    fn authenticate(&mut self) -> Result<Connection> {
        self.venue.authed.set(false);
        self.venue.trusted.set(false);
        self.broker.set_health(false, false, false);
        self.venue.account_info(&self.venue.config.budget())?;
        self.broker.set_connection(Connection::Connected);
        Ok(Connection::Connected)
    }
    fn disconnect(&mut self) -> Result<()> {
        self.venue.io.close();
        self.venue.authed.set(false);
        self.venue.trade.set(false);
        self.venue.trusted.set(false);
        self.venue.subscription.set(None);
        self.broker.set_connection(Connection::Disconnected);
        Ok(())
    }
}
impl<J: Journal> AccountPort for SpotBroker<J> {
    fn account(&self, s: &Scope) -> Result<Snapshot> {
        self.venue.owner(s)?;
        Err(err("BINANCE_MULTI_ASSET_ACCOUNT_USE_BALANCES"))
    }
    fn balances(&self, s: &Scope) -> Result<Vec<Snapshot>> {
        self.venue.owner(s)?;
        let (raw, v) = self.venue.account_info(&self.venue.config.budget())?;
        balances(&self.venue.config, &v["balances"], raw.at_ns, false)
    }
}
impl<J: Journal> PositionPort for SpotBroker<J> {
    fn positions(&self, s: &Scope) -> Result<Vec<Snapshot>> {
        self.venue.owner(s)?;
        Ok(Vec::new())
    }
}
impl<J: Journal> OrderQueryPort for SpotBroker<J> {
    fn orders(&self, s: &Scope, open_only: bool) -> Result<Vec<OrderView>> {
        self.venue.owner(s)?;
        let b = self.venue.config.budget();
        if open_only {
            return self.venue.open_orders(&b);
        }
        let cs = self.venue.orders.borrow().submits.clone();
        cs.values()
            .map(|c| self.venue.current_order(c, &b).map(|(_, _, v)| v))
            .collect()
    }
}
impl<J: Journal> TradeQueryPort for SpotBroker<J> {
    fn trades(&self, s: &Scope, since: Option<u64>) -> Result<Vec<Fact>> {
        self.venue.owner(s)?;
        if since.is_some() {
            return Err(err("BINANCE_NO_GLOBAL_TRADE_SEQUENCE"));
        }
        let b = self.venue.config.budget();
        let mut output = Vec::new();
        let commands = self.venue.orders.borrow().submits.clone();
        for c in commands.values() {
            let (raw, order, _) = self.venue.current_order(c, &b)?;
            let prov = Provenance {
                session: "rest",
                received: raw.at_ns,
                source: "binance-query",
            };
            for trade in self.venue.trades_for(c, &order, &b)? {
                output.push(trade_fact(c, &trade, &prov)?);
            }
        }
        Ok(output)
    }
}
impl<J: Journal> FeeEvidencePort for SpotBroker<J> {
    fn fee_evidence(&self, s: &Scope, order: &str) -> Result<Vec<Value>> {
        self.venue.owner(s)?;
        let c = self
            .venue
            .orders
            .borrow()
            .submits
            .get(order)
            .cloned()
            .ok_or_else(|| err("BINANCE_ORDER_MISSING"))?;
        let b = self.venue.config.budget();
        let (_, view, _) = self.venue.current_order(&c, &b)?;
        self.venue
            .trades_for(&c, &view, &b)?
            .iter()
            .map(|row| fee_evidence(&c, row, &self.venue.config.currencies))
            .collect()
    }
}
