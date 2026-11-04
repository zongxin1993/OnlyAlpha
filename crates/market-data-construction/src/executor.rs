//! Pure in-process algorithm extension contracts, selected by exact ID/version.
use crate::{model::*, record::*, time_bar::OnlyTimeBarExecutor};
use num_bigint::BigUint;
use onlyalpha_domain::{
    calendar::OnlyTradingCalendar,
    market::{OnlyBar, OnlyBarType, OnlyTradeInputType, OnlyTradeTick},
    time::OnlyTimestamp,
};
use serde_json::Value;
use std::{collections::BTreeMap, sync::Arc};
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OnlyConstructionFact {
    Bar(Arc<OnlyBar>),
    Trade(Arc<OnlyTradeTick>),
}
impl OnlyConstructionFact {
    pub fn input(&self) -> OnlyConstructionInput {
        match self {
            Self::Bar(b) => OnlyConstructionInput::Bar(b.bar_type().clone()),
            Self::Trade(t) => {
                OnlyConstructionInput::Trade(OnlyTradeInputType::new(t.instrument_id().clone()))
            }
        }
    }
    pub fn event(&self) -> OnlyTimestamp {
        OnlyTimestamp::from_datetime(match self {
            Self::Bar(b) => *b.ts_event(),
            Self::Trade(t) => *t.ts_event(),
        })
    }
}
/// Implementations are deterministic and side-effect-free. Recovery must validate before mutation.
/// Upstream admission owns Source continuity/grants; this port grants no execution authority.
pub trait OnlyConstructionExecutor: Send {
    fn target(&self) -> &OnlyBarType;
    fn process(
        &mut self,
        fact: &OnlyConstructionFact,
        init: &OnlyTimestamp,
    ) -> OnlyConstructionResult<Vec<Arc<OnlyBar>>>;
    fn capture_checkpoint(&self) -> OnlyConstructionResult<Value>;
    fn restore_checkpoint(&mut self, record: &Value) -> OnlyConstructionResult<()>;
}
/// Factories create isolated initial state, never shared mutable state or external side effects.
pub trait OnlyConstructionFactory: Send + Sync {
    fn create(
        &self,
        edge: &OnlyConstructionEdge,
        calendar: Arc<OnlyTradingCalendar>,
    ) -> OnlyConstructionResult<Box<dyn OnlyConstructionExecutor>>;
}
struct TimeBarFactory;
impl OnlyConstructionFactory for TimeBarFactory {
    fn create(
        &self,
        edge: &OnlyConstructionEdge,
        calendar: Arc<OnlyTradingCalendar>,
    ) -> OnlyConstructionResult<Box<dyn OnlyConstructionExecutor>> {
        Ok(Box::new(OnlyTimeBarExecutor::new(edge.clone(), calendar)?))
    }
}
pub struct OnlyConstructionRegistry {
    factories: BTreeMap<(String, BigUint), Arc<dyn OnlyConstructionFactory>>,
}
impl Default for OnlyConstructionRegistry {
    fn default() -> Self {
        let mut factories: BTreeMap<_, Arc<dyn OnlyConstructionFactory>> = BTreeMap::new();
        factories.insert(("TIME_BAR".into(), 1u32.into()), Arc::new(TimeBarFactory));
        Self { factories }
    }
}
impl OnlyConstructionRegistry {
    pub fn register(
        &mut self,
        id: &str,
        version: BigUint,
        factory: Arc<dyn OnlyConstructionFactory>,
    ) -> OnlyConstructionResult<()> {
        nonempty(id)?;
        let key = (id.to_string(), version);
        if key.1 == BigUint::default() || self.factories.contains_key(&key) {
            return Err(err("ALGORITHM_REGISTRATION"));
        }
        self.factories.insert(key, factory);
        Ok(())
    }
    pub fn create(
        &self,
        edge: &OnlyConstructionEdge,
        calendar: Arc<OnlyTradingCalendar>,
    ) -> OnlyConstructionResult<Box<dyn OnlyConstructionExecutor>> {
        let (id, version) = edge
            .recipe()
            .algorithm()
            .ok_or(OnlyConstructionError::Unavailable)?;
        let factory = self
            .factories
            .get(&(id.to_string(), version.clone()))
            .ok_or(OnlyConstructionError::Unavailable)?;
        let executor = factory.create(edge, calendar)?;
        if executor.target() != edge.target() {
            return Err(err("EXECUTOR_TARGET"));
        }
        Ok(executor)
    }
}
