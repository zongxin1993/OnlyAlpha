//! 确定性的模拟场所。Broker 接收观察，Runtime 独立验证、应用交易事实。
mod config;
mod discovery;
mod plan;
mod projection;
mod source_host;
mod venue;
pub use source_host::BoundVirtualActor;

use config::Config;
use onlyalpha_broker::*;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, value::OnlyMoney};
use plan::err;
use serde_json::{Value, json};
use venue::State;

/// 原始有序输入与导出检查点由调用方持久化。实例只处理一个 BACKTEST/SIM Scope。
pub struct VirtualBroker {
    scope: Scope,
    binding: Value,
    config: Config,
    state: State,
    inputs: Vec<Value>,
    connection: Connection,
}
impl VirtualBroker {
    /// artifact_sha256 由拥有本次运行工件的装配方验证并传入。
    pub fn new(
        scope: Scope,
        artifact_sha256: &str,
        initial_cash: OnlyMoney,
        extensions: &Value,
    ) -> Result<Self, Error> {
        if scope.record()["runtime_kind"] == "LIVE" {
            return Err(err("VIRTUAL_LIVE_FORBIDDEN"));
        }
        if artifact_sha256.len() != 64
            || !artifact_sha256
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(err("VIRTUAL_ARTIFACT_DIGEST"));
        }
        let config = Config::parse(extensions)?;
        let binding = json!({"implementation":"rust","plugin_id":"virtual","release_id":"plugin-onlyalpha-broker-virtual",
            "version":env!("CARGO_PKG_VERSION"),"artifact_sha256":artifact_sha256,"scope":scope.record(),
            "initial_cash":initial_cash.to_record(),"configuration":config.record});
        Ok(Self {
            scope,
            binding,
            config,
            state: State::new(&initial_cash)?,
            inputs: Vec::new(),
            connection: Connection::Disconnected,
        })
    }
    pub fn source_binding(&self) -> &Value {
        &self.binding
    }
    pub fn now(&self) -> i64 {
        self.state.now
    }
    fn owner(&self, scope: &Scope) -> Result<(), Error> {
        if scope != &self.scope {
            return Err(err("VIRTUAL_SCOPE"));
        }
        Ok(())
    }
    fn update<T>(
        &mut self,
        input: Value,
        apply: impl FnOnce(&mut State, &Config) -> Result<T, Error>,
    ) -> Result<T, Error> {
        let mut candidate = self.state.clone();
        let result = apply(&mut candidate, &self.config)?;
        self.state = candidate;
        self.inputs.push(input);
        Ok(result)
    }
    /// 用显式纳秒时钟运行所有到期的接收、撤单及场所动作。
    pub fn advance(&mut self, now: i64) -> Result<(), Error> {
        self.update(json!(["CLOCK", now]), |s, cfg| s.advance(cfg, now))
    }
    /// sequence 从 1 连续增加；同一已闭合 Bar 重放只有原序号和内容均相同才幂等。
    pub fn on_bar(&mut self, sequence: u64, bar: &OnlyBar) -> Result<(), Error> {
        let input = json!(["BAR", sequence, bar.to_record()]);
        if sequence <= self.state.bar_sequence {
            if self.inputs.iter().any(|i| i == &input) {
                return Ok(());
            }
            return Err(err("VIRTUAL_BAR_CONFLICT"));
        }
        self.update(input, |s, cfg| s.bar(cfg, sequence, bar))
    }
    fn receive(
        &mut self,
        c: &BrokerCommand,
        ready_at_dispatch: bool,
    ) -> Result<DispatchResult, Error> {
        self.owner(c.scope())?;
        if let Some(old) = self.state.commands.get(c.id()) {
            if old != c {
                return Err(err("VIRTUAL_COMMAND_CONFLICT"));
            }
            return Ok(if self.state.rejected.contains(c.id()) {
                DispatchResult::Rejected
            } else {
                DispatchResult::Received
            });
        }
        let cause = if ready_at_dispatch {
            "COMMAND"
        } else {
            "NOT_READY"
        };
        self.update(json!([cause, c.record()]), |s, cfg| {
            s.receive(cfg, c, ready_at_dispatch)
        })
    }
    // 绑定宿主独占候选，失败后只能从原介质重开；无需复制历史输入和事实来回滚候选。
    fn apply_bound_input(&mut self, input: &Value) -> Result<(), Error> {
        match input[0].as_str() {
            Some("CLOCK") => self.state.advance(
                &self.config,
                input[1].as_i64().ok_or_else(|| err("VIRTUAL_CLOCK"))?,
            ),
            Some("BAR") => {
                let bar = OnlyBar::from_record(&input[2]).map_err(|_| err("VIRTUAL_BAR"))?;
                self.state.bar(
                    &self.config,
                    input[1]
                        .as_u64()
                        .ok_or_else(|| err("VIRTUAL_BAR_SEQUENCE"))?,
                    &bar,
                )
            }
            Some(kind @ ("COMMAND" | "NOT_READY")) => {
                let command = BrokerCommand::decode(&input[1])?;
                self.owner(command.scope())?;
                if self.state.commands.contains_key(command.id()) {
                    return Err(err("VIRTUAL_SOURCE_DUPLICATE_INPUT"));
                }
                self.state
                    .receive(&self.config, &command, kind == "COMMAND")
                    .map(|_| ())
            }
            Some("PUBLISHED") => self.consume_publication(input),
            _ => Err(err("VIRTUAL_CHECKPOINT_INPUT")),
        }
    }
    fn next_publication(&self) -> Option<(i64, usize)> {
        self.state
            .outbox
            .first()
            .copied()
            .filter(|(at, _)| *at <= self.now())
    }
    fn consume_publication(&mut self, input: &Value) -> Result<(), Error> {
        let key = self
            .next_publication()
            .ok_or_else(|| err("VIRTUAL_PUBLICATION_NOT_DUE"))?;
        let fact = &self.state.facts[key.1];
        if input != &json!(["PUBLISHED", fact.identity(), fact.fingerprint()]) {
            return Err(err("VIRTUAL_PUBLICATION_CONFLICT"));
        }
        self.state.outbox.remove(&key);
        Ok(())
    }
    fn published(&mut self, input: &Value) -> Result<(), Error> {
        self.consume_publication(input)?;
        self.inputs.push(input.clone());
        Ok(())
    }
    /// 每条观察经原 Broker Journal 成功持久化后才移动场所发布游标。
    pub fn publish(
        &mut self,
        broker: &mut Broker,
        journal: &mut impl Journal,
    ) -> Result<usize, Error> {
        let mut count = 0;
        while let Some((_, index)) = self.next_publication() {
            let fact = &self.state.facts[index];
            broker.ingest(journal, std::slice::from_ref(fact))?;
            self.published(&json!(["PUBLISHED", fact.identity(), fact.fingerprint()]))?;
            count += 1;
        }
        Ok(count)
    }
    pub fn checkpoint(&self) -> Value {
        json!({"schema_version":4,"binding":self.binding,"inputs":self.inputs,"orders":self.state.orders.iter().map(|o|o.record()).collect::<Vec<_>>(),
            "pending_actions":self.state.pending_actions(),"facts":self.state.facts.iter().map(Fact::record).collect::<Vec<_>>(),
            "outbox":self.state.outbox.iter().map(|(at,i)|json!([at,self.state.facts[*i].identity()])).collect::<Vec<_>>()})
    }
    /// expected_sha256 来自原运行的独立持久化引用。重放宿主输入时只重建本地场所投影。
    pub fn restore(
        scope: Scope,
        artifact_sha256: &str,
        initial_cash: OnlyMoney,
        extensions: &Value,
        cut: &Value,
        expected_sha256: &str,
    ) -> Result<Self, Error> {
        if cut["schema_version"] != 4 || digest(cut) != expected_sha256 {
            return Err(err("VIRTUAL_CHECKPOINT_IDENTITY"));
        }
        let mut v = Self::new(scope, artifact_sha256, initial_cash, extensions)?;
        if cut["binding"] != v.binding {
            return Err(err("VIRTUAL_CHECKPOINT_BINDING"));
        }
        for input in cut["inputs"]
            .as_array()
            .ok_or_else(|| err("VIRTUAL_CHECKPOINT_INPUTS"))?
        {
            v.replay_input(input)?;
        }
        if v.checkpoint() != *cut {
            return Err(err("VIRTUAL_CHECKPOINT_STATE_CONFLICT"));
        }
        Ok(v)
    }
    fn replay_input(&mut self, input: &Value) -> Result<(), Error> {
        match input[0].as_str() {
            Some("CLOCK") => {
                self.advance(input[1].as_i64().ok_or_else(|| err("VIRTUAL_CLOCK"))?)?
            }
            Some("BAR") => {
                let bar = OnlyBar::from_record(&input[2]).map_err(|_| err("VIRTUAL_BAR"))?;
                self.on_bar(
                    input[1]
                        .as_u64()
                        .ok_or_else(|| err("VIRTUAL_BAR_SEQUENCE"))?,
                    &bar,
                )?;
            }
            Some(cause @ ("COMMAND" | "NOT_READY")) => {
                self.receive(&BrokerCommand::decode(&input[1])?, cause == "COMMAND")?;
            }
            Some("PUBLISHED") => self.published(input)?,
            _ => return Err(err("VIRTUAL_CHECKPOINT_INPUT")),
        }
        Ok(())
    }
}
impl ConnectionPort for VirtualBroker {
    fn connect(&mut self) -> Result<Connection, Error> {
        if self.connection == Connection::Disconnected {
            self.connection = Connection::Connected;
        }
        Ok(self.connection)
    }
    fn authenticate(&mut self) -> Result<Connection, Error> {
        if !matches!(self.connection, Connection::Connected | Connection::Ready) {
            return Err(err("VIRTUAL_DISCONNECTED"));
        }
        self.connection = Connection::Ready;
        Ok(self.connection)
    }
    fn disconnect(&mut self) -> Result<(), Error> {
        self.connection = Connection::Disconnected;
        Ok(())
    }
}
impl TradingPort for VirtualBroker {
    fn capabilities(&self) -> Capabilities {
        Capabilities::new(&[
            "CONNECT",
            "AUTHENTICATE",
            "SUBMIT_ORDER",
            "CANCEL_ORDER",
            "QUERY_ACCOUNT",
            "QUERY_BALANCES",
            "QUERY_POSITIONS",
            "QUERY_OPEN_ORDERS",
            "QUERY_ORDERS",
            "QUERY_TRADES",
            "QUERY_FEE_EVIDENCE",
            "MARKET_ORDER",
            "LIMIT_ORDER",
            "PARTIAL_FILL",
            "PUSH_ORDER_UPDATES",
            "PUSH_TRADE_UPDATES",
        ])
        .expect("static Broker capabilities")
    }
    fn dispatch(&mut self, c: &BrokerCommand) -> Result<DispatchResult, Error> {
        self.receive(c, self.connection == Connection::Ready)
    }
}
impl AccountPort for VirtualBroker {
    fn account(&self, scope: &Scope) -> Result<Snapshot, Error> {
        self.owner(scope)?;
        self.state
            .projection
            .account(scope, self.inputs.len() as u64, self.now(), false)
    }
    fn balances(&self, scope: &Scope) -> Result<Vec<Snapshot>, Error> {
        self.owner(scope)?;
        Ok(vec![self.state.projection.account(
            scope,
            self.inputs.len() as u64,
            self.now(),
            true,
        )?])
    }
}
impl PositionPort for VirtualBroker {
    fn positions(&self, scope: &Scope) -> Result<Vec<Snapshot>, Error> {
        self.owner(scope)?;
        self.state
            .projection
            .positions(scope, self.inputs.len() as u64, self.now())
    }
}
impl OrderQueryPort for VirtualBroker {
    fn orders(&self, scope: &Scope, open_only: bool) -> Result<Vec<OrderView>, Error> {
        self.owner(scope)?;
        if self.state.orders.iter().any(|o| o.status == "SUBMITTED") {
            return Err(err("VIRTUAL_ORDER_VIEW_PENDING"));
        }
        let mut orders = self
            .state
            .orders
            .iter()
            .filter(|o| !open_only || o.open())
            .collect::<Vec<_>>();
        orders.sort_by(|a, b| (&a.venue, a.submit.order()).cmp(&(&b.venue, b.submit.order())));
        orders
            .into_iter()
            .filter_map(|o| o.view().transpose())
            .collect()
    }
}
impl TradeQueryPort for VirtualBroker {
    fn trades(&self, scope: &Scope, since: Option<u64>) -> Result<Vec<Fact>, Error> {
        self.owner(scope)?;
        Ok(self
            .state
            .facts
            .iter()
            .enumerate()
            .filter(|(index, f)| {
                (*index as u64 + 1) >= since.unwrap_or(0) && f.record()["kind"] == "TRADE"
            })
            .map(|(_, f)| f.clone())
            .collect())
    }
}
impl FeeEvidencePort for VirtualBroker {
    fn fee_evidence(&self, scope: &Scope, order: &str) -> Result<Vec<Value>, Error> {
        self.owner(scope)?;
        if self.state.order(order).is_none() {
            return Err(err("VIRTUAL_ORDER_MISSING"));
        }
        Ok(Vec::new())
    }
}
