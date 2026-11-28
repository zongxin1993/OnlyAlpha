//! 交易任务的经济状态与场所接线。账户、准入及成交应用均由同一个经济 owner 承担。
use super::{ExecutionPort, MarketBar, Result, boundary, error};
use crate::durability::TradingBinding;
use onlyalpha_broker::{
    Broker, BrokerCommand, CommandState, Fact, Journal, Operation, RuntimeReader, Scope,
    TradingPort,
};
use onlyalpha_domain::{
    strategy::{OrderIntent, ReadonlyAccountState},
    time::OnlyTimestamp,
};
use serde_json::Value;

pub struct Admission {
    pub facts: Vec<Value>,
    pub command: Option<BrokerCommand>,
}

pub trait EconomicOwner {
    fn scope(&self) -> &Scope;
    fn account(&self, at: &OnlyTimestamp) -> Result<ReadonlyAccountState>;
    /// 先完成风控与准入，普通拒绝返回原事实和空命令；持续交易须在持久提交后返回命令。
    fn admit(&mut self, intent: &OrderIntent, at: &OnlyTimestamp) -> Result<Admission>;
    /// 按原回报身份和正文核对重复、应用并保存经济事实；结果未知时返回错误供对账。
    fn apply_venue(&mut self, fact: &Fact) -> Result<()>;
}

pub trait FiniteEconomicOwner: EconomicOwner + onlyalpha_broker::FiniteRuntimeReader {
    fn configuration(&self) -> &crate::RunConfiguration;
}

pub trait DurableEconomicOwner: EconomicOwner + RuntimeReader {
    fn binding(&self) -> &TradingBinding;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ObservationState {
    Pending,
    Acknowledged,
}

impl ObservationState {
    pub fn from_broker(broker: &Broker, fact: &Fact) -> Result<Option<Self>> {
        if !broker.has_observed(fact).map_err(boundary)? {
            return Ok(None);
        }
        match broker
            .pending()
            .iter()
            .position(|pending| pending.identity() == fact.identity())
        {
            Some(0) => Ok(Some(Self::Pending)),
            Some(_) => Err(error("TRADING_VENUE_OUT_OF_ORDER")),
            None => Ok(Some(Self::Acknowledged)),
        }
    }
}

pub trait VenueFacts<O> {
    fn scope(&self) -> &Scope;
    /// 核对场所观察及完整正文；只有原应用回执已经过协议确认才返回 Acknowledged。
    fn stage(&mut self, fact: &Fact) -> Result<ObservationState>;
    fn acknowledge(&mut self, owner: &O, fact: &Fact) -> Result<()>;
}

pub trait VirtualVenue<O>: VenueFacts<O> {
    /// 以截面定位原闭合行情并推进模拟时钟和场所，保留该输入产生的有序回报。
    fn prepare_market(&mut self, market: &MarketBar) -> Result<()>;
    fn pending_venue(&mut self) -> Result<Option<Fact>>;
    /// 有限场所按冻结的结束时点释放延迟回报；实时场所维持最后记录的时钟。
    fn finish_market_input(&mut self) -> Result<()> {
        Ok(())
    }
    fn dispatch_simulated(&mut self, owner: &O, command: &BrokerCommand) -> Result<CommandState>;
}

pub trait BacktestVenue<O>: VirtualVenue<O> {
    fn verify_inputs(
        &self,
        configuration: &crate::RunConfiguration,
        panel: &crate::ResearchPanel,
    ) -> Result<()>;
}

pub trait AuthorizedLiveGateway<O>: VenueFacts<O> {
    /// 宿主在派发边界核验此原命令的正式人工授权、当前准入和持久化证明，未知结果按原命令对账。
    fn dispatch_authorized(&mut self, owner: &O, command: &BrokerCommand) -> Result<CommandState>;
}

fn submit<O: EconomicOwner, V>(
    owner: &mut O,
    venue: &mut V,
    intent: &OrderIntent,
    at: &OnlyTimestamp,
    dispatch: impl FnOnce(&mut V, &O, &BrokerCommand) -> Result<CommandState>,
) -> Result<Vec<Value>> {
    let admission = owner.admit(intent, at)?;
    if let Some(command) = admission.command {
        if command.scope() != owner.scope() || command.operation() != Operation::Submit {
            return Err(error("TRADING_ADMISSION_COMMAND"));
        }
        match dispatch(venue, owner, &command)? {
            CommandState::Known | CommandState::Resolved => (),
            CommandState::Unknown | CommandState::Reconciling => {
                return Err(error(&format!(
                    "TRADING_DISPATCH_RECONCILE:{}",
                    command.id()
                )));
            }
            CommandState::Durable => return Err(error("TRADING_DISPATCH_INCOMPLETE")),
        }
    }
    Ok(admission.facts)
}

fn observe<O: EconomicOwner>(
    owner: &mut O,
    venue: &mut impl VenueFacts<O>,
    fact: &Fact,
) -> Result<()> {
    if &fact.scope() != owner.scope() {
        return Err(error("TRADING_VENUE_SCOPE"));
    }
    if venue.stage(fact)? == ObservationState::Acknowledged {
        return Ok(());
    }
    owner.apply_venue(fact)?;
    venue.acknowledge(owner, fact)
}

pub struct VirtualExecution<O, V> {
    owner: O,
    venue: V,
}

impl<O: EconomicOwner, V: VirtualVenue<O>> VirtualExecution<O, V> {
    pub fn new(owner: O, venue: V) -> Result<Self> {
        if owner.scope() != venue.scope()
            || !matches!(
                owner.scope().record()["runtime_kind"].as_str(),
                Some("BACKTEST" | "SIM")
            )
        {
            return Err(error("TRADING_VENUE_SCOPE"));
        }
        Ok(Self { owner, venue })
    }

    pub fn owner(&self) -> &O {
        &self.owner
    }
    pub fn scope(&self) -> &Scope {
        self.owner.scope()
    }
    pub(super) fn venue_mut(&mut self) -> &mut V {
        &mut self.venue
    }
    pub(super) fn venue(&self) -> &V {
        &self.venue
    }
    pub fn prepare_market(&mut self, market: &MarketBar) -> Result<()> {
        self.venue.prepare_market(market)
    }
    pub fn pending_venue(&mut self) -> Result<Option<Fact>> {
        self.venue.pending_venue()
    }
    pub fn into_parts(self) -> (O, V) {
        (self.owner, self.venue)
    }
}

impl<O: DurableEconomicOwner, V> VirtualExecution<O, V> {
    pub fn binding(&self) -> &TradingBinding {
        self.owner.binding()
    }
}

impl<O: EconomicOwner, V: VirtualVenue<O>> ExecutionPort for VirtualExecution<O, V> {
    fn account(&self, at: &OnlyTimestamp) -> Result<ReadonlyAccountState> {
        self.owner.account(at)
    }
    fn submit(&mut self, intent: &OrderIntent, at: &OnlyTimestamp) -> Result<Vec<Value>> {
        submit(
            &mut self.owner,
            &mut self.venue,
            intent,
            at,
            V::dispatch_simulated,
        )
    }
    fn observe_venue(&mut self, fact: &Fact) -> Result<()> {
        observe(&mut self.owner, &mut self.venue, fact)
    }
}

pub struct LiveExecution<O, G> {
    owner: O,
    gateway: G,
}

impl<O: DurableEconomicOwner, G: AuthorizedLiveGateway<O>> LiveExecution<O, G> {
    pub fn new(owner: O, gateway: G) -> Result<Self> {
        if owner.scope() != gateway.scope() || owner.scope().record()["runtime_kind"] != "LIVE" {
            return Err(error("TRADING_VENUE_SCOPE"));
        }
        Ok(Self { owner, gateway })
    }

    pub fn owner(&self) -> &O {
        &self.owner
    }
    pub fn scope(&self) -> &Scope {
        self.owner.scope()
    }
    pub fn binding(&self) -> &TradingBinding {
        self.owner.binding()
    }
    pub fn into_parts(self) -> (O, G) {
        (self.owner, self.gateway)
    }
}

impl<O: DurableEconomicOwner, G: AuthorizedLiveGateway<O>> ExecutionPort for LiveExecution<O, G> {
    fn account(&self, at: &OnlyTimestamp) -> Result<ReadonlyAccountState> {
        self.owner.account(at)
    }
    fn submit(&mut self, intent: &OrderIntent, at: &OnlyTimestamp) -> Result<Vec<Value>> {
        submit(
            &mut self.owner,
            &mut self.gateway,
            intent,
            at,
            |gateway, owner, command| {
                let ready = owner.ready_intent(command).map_err(boundary)?;
                if ready.record()["command"] != command.record() {
                    return Err(error("TRADING_READY_COMMAND_MISMATCH"));
                }
                gateway.dispatch_authorized(owner, command)
            },
        )
    }
    fn observe_venue(&mut self, fact: &Fact) -> Result<()> {
        observe(&mut self.owner, &mut self.gateway, fact)
    }
}

/// 持续模拟场所的显式行情输入和发布游标，由持有原始行情与虚拟券商实例的适配器实现。
pub trait SimulatedTradingPort<J>: TradingPort {
    fn scope(&self) -> &Scope;
    fn prepare_market(&mut self, market: &MarketBar) -> Result<()>;
    fn publish(&mut self, broker: &mut Broker, journal: &mut J) -> Result<()>;
}

pub struct JournaledVirtualVenue<J, V> {
    journal: J,
    broker: Broker,
    venue: V,
}

impl<J: Journal, V: SimulatedTradingPort<J>> JournaledVirtualVenue<J, V> {
    pub fn new(journal: J, venue: V, capacity: usize) -> Result<Self> {
        if venue.scope().record()["runtime_kind"] != "SIM" {
            return Err(error("TRADING_VENUE_SCOPE"));
        }
        let broker =
            Broker::recover(venue.scope().clone(), &journal, capacity).map_err(boundary)?;
        Ok(Self {
            journal,
            broker,
            venue,
        })
    }

    /// 宿主用原协议与同一 Journal 记录连接健康、核对未知命令并恢复场所状态。
    pub fn parts_mut(&mut self) -> (&mut Broker, &mut J, &mut V) {
        (&mut self.broker, &mut self.journal, &mut self.venue)
    }
}

impl<O: DurableEconomicOwner, J: Journal, V: SimulatedTradingPort<J>> VenueFacts<O>
    for JournaledVirtualVenue<J, V>
{
    fn scope(&self) -> &Scope {
        self.venue.scope()
    }
    fn stage(&mut self, fact: &Fact) -> Result<ObservationState> {
        self.broker.refresh(&self.journal).map_err(boundary)?;
        if let Some(state) = ObservationState::from_broker(&self.broker, fact)? {
            return Ok(state);
        }
        if self.broker.pending().is_empty() {
            self.venue.publish(&mut self.broker, &mut self.journal)?;
            if let Some(state) = ObservationState::from_broker(&self.broker, fact)? {
                return Ok(state);
            }
        }
        Err(error("TRADING_VENUE_UNOBSERVED"))
    }
    fn acknowledge(&mut self, owner: &O, fact: &Fact) -> Result<()> {
        self.broker
            .acknowledge(&mut self.journal, owner, fact.identity())
            .map_err(boundary)
    }
}

impl<O: DurableEconomicOwner, J: Journal, V: SimulatedTradingPort<J>> VirtualVenue<O>
    for JournaledVirtualVenue<J, V>
{
    fn prepare_market(&mut self, market: &MarketBar) -> Result<()> {
        self.venue.prepare_market(market)
    }
    fn pending_venue(&mut self) -> Result<Option<Fact>> {
        self.broker.refresh(&self.journal).map_err(boundary)?;
        if self.broker.pending().is_empty() {
            self.venue.publish(&mut self.broker, &mut self.journal)?;
        }
        Ok(self.broker.pending().first().cloned())
    }
    fn dispatch_simulated(&mut self, owner: &O, command: &BrokerCommand) -> Result<CommandState> {
        self.broker
            .dispatch(&mut self.journal, owner, &mut self.venue, command)
            .map_err(boundary)
    }
}

#[cfg(test)]
#[path = "../tests/journaled_virtual_venue.rs"]
mod tests;
