use onlyalpha_calculation::{
    CalculationSnapshot, ExecutionBinding, ReadinessPlan, ReadinessRequirement,
};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::OnlyTradingCalendar,
    identifiers::{OnlyClusterId, OnlyIdentifier},
    market::{OnlyBar, OnlyBarType},
    time::OnlyTimestamp,
};
use onlyalpha_market_data_construction::*;
use onlyalpha_market_data_delivery::*;
use onlyalpha_market_data_state::*;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PipelineError {
    Configuration,
    Input,
    RecoveryRequired,
    Shared(&'static str),
    Record(&'static str),
}
impl std::fmt::Display for PipelineError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for PipelineError {}
pub type PipelineResult<T> = Result<T, PipelineError>;
pub fn digest(value: &Value) -> String {
    Sha256::digest(value.to_string().as_bytes())
        .iter()
        .map(|v| format!("{v:02x}"))
        .collect()
}
pub fn validate_digest(value: &str) -> PipelineResult<()> {
    if value.len() == 64
        && value
            .bytes()
            .all(|v| v.is_ascii_digit() || (b'a'..=b'f').contains(&v))
    {
        Ok(())
    } else {
        Err(PipelineError::Configuration)
    }
}
pub fn bar_key(kind: &OnlyBarType) -> String {
    kind.to_record().to_string()
}
pub fn calculation_scope(
    owner: &OnlyMarketDataStateScope,
    cluster: &OnlyClusterId,
    local: &str,
) -> PipelineResult<String> {
    let id: OnlyIdentifier = local.parse().map_err(|_| PipelineError::Configuration)?;
    if id.value() != local {
        return Err(PipelineError::Configuration);
    }
    Ok(json!([
        owner.engine_id().value(),
        owner.runtime_id().value(),
        cluster.value(),
        local
    ])
    .to_string())
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CalculationSlot {
    pub local: String,
    pub cluster: OnlyClusterId,
    pub binding: ExecutionBinding,
    pub source: String,
    pub bar_type: OnlyBarType,
    pub required: bool,
    pub dependencies: Vec<String>,
}
impl CalculationSlot {
    pub fn to_record(&self) -> Value {
        json!({"local":self.local,"cluster":self.cluster.value(),"binding":self.binding.to_record(),"source":self.source,"bar_type":self.bar_type.to_record(),"required":self.required,"dependencies":self.dependencies})
    }
}
#[derive(Clone)]
pub struct SourceProgram {
    pub(crate) source: String,
    pub(crate) calendar: Arc<OnlyTradingCalendar>,
    pub(crate) registry: Arc<OnlyConstructionRegistry>,
    pub(crate) artifact: String,
    pub(crate) graph: OnlyConstructionGraph,
}
impl SourceProgram {
    pub fn new(
        source: &str,
        calendar: Arc<OnlyTradingCalendar>,
        registry: Arc<OnlyConstructionRegistry>,
        artifact: &str,
        graph: OnlyConstructionGraph,
    ) -> PipelineResult<Self> {
        validate_digest(source)?;
        validate_digest(artifact)?;
        if graph.providers().is_empty() {
            return Err(PipelineError::Configuration);
        }
        Ok(Self {
            source: source.into(),
            calendar,
            registry,
            artifact: artifact.into(),
            graph,
        })
    }
    pub(crate) fn record(&self) -> Value {
        json!({"source":self.source,"calendar":self.calendar.to_record(),"executor_artifact":self.artifact,"graph":self.graph.to_record()})
    }
}
#[derive(Clone)]
pub struct ClusterProgram {
    pub cluster: OnlyClusterId,
    pub subscription: OnlyBarSubscription,
}
#[derive(Clone)]
pub struct PipelineProgram {
    pub(crate) scope: OnlyMarketDataStateScope,
    pub(crate) generation: String,
    pub(crate) history_limit: usize,
    pub(crate) sources: BTreeMap<String, SourceProgram>,
    pub(crate) clusters: BTreeMap<OnlyClusterId, OnlyBarSubscription>,
    pub(crate) slots: BTreeMap<String, CalculationSlot>,
    pub(crate) owners: BTreeMap<String, String>,
    pub(crate) consumer: String,
    fingerprint: String,
}
impl PipelineProgram {
    pub fn new(
        scope: OnlyMarketDataStateScope,
        generation: &str,
        history_limit: usize,
        sources: Vec<SourceProgram>,
        clusters: Vec<ClusterProgram>,
        slots: Vec<CalculationSlot>,
        consumer: &str,
    ) -> PipelineResult<Self> {
        validate_digest(generation)?;
        validate_digest(consumer)?;
        if history_limit == 0
            || history_limit > 20000
            || sources.is_empty()
            || sources.len() > 16
            || clusters.is_empty()
            || clusters.len() > 256
            || slots.len() > 256
        {
            return Err(PipelineError::Configuration);
        }
        let mut source_map = BTreeMap::new();
        let mut owners = BTreeMap::new();
        for source in sources {
            OnlyConstructionPlan::compile(&source.graph, &source.source)
                .map_err(|_| PipelineError::Configuration)?;
            for kind in source
                .graph
                .providers()
                .iter()
                .filter_map(|p| {
                    if let OnlyConstructionInput::Bar(k) = p {
                        Some(k)
                    } else {
                        None
                    }
                })
                .chain(source.graph.edges().iter().map(|e| e.target()))
            {
                if owners
                    .insert(bar_key(kind), source.source.clone())
                    .is_some()
                {
                    return Err(PipelineError::Configuration);
                }
            }
            if source_map.insert(source.source.clone(), source).is_some() {
                return Err(PipelineError::Configuration);
            }
        }
        let mut cluster_map = BTreeMap::new();
        let mut subscription_ids = BTreeSet::new();
        for cluster in clusters {
            if !subscription_ids.insert(cluster.subscription.id().value().to_owned())
                || cluster_map.contains_key(&cluster.cluster)
            {
                return Err(PipelineError::Configuration);
            }
            for kind in cluster.subscription.bar_types() {
                if !owners.contains_key(&bar_key(kind)) {
                    return Err(PipelineError::Configuration);
                }
            }
            for provider in cluster.subscription.graph().providers() {
                if !source_map
                    .values()
                    .any(|s| s.graph.providers().contains(provider))
                {
                    return Err(PipelineError::Configuration);
                }
            }
            for edge in cluster.subscription.graph().edges() {
                if !source_map.values().any(|s| s.graph.edges().contains(edge)) {
                    return Err(PipelineError::Configuration);
                }
            }
            cluster_map.insert(cluster.cluster, cluster.subscription);
        }
        let mut slot_map = BTreeMap::new();
        for mut slot in slots {
            slot.dependencies.sort();
            if slot.binding.scope() != calculation_scope(&scope, &slot.cluster, &slot.local)?
                || slot.binding.digests()[0] != generation
                || !cluster_map
                    .get(&slot.cluster)
                    .is_some_and(|sub| sub.bar_types().contains(&slot.bar_type))
                || owners.get(&bar_key(&slot.bar_type)) != Some(&slot.source)
                || slot.binding.digests()[5]
                    != digest(
                        &json!({"schema_version":1,"bar_type":slot.bar_type.to_record(),"source_fingerprint":slot.source}),
                    )
                || slot_map
                    .insert(slot.binding.scope().to_owned(), slot)
                    .is_some()
            {
                return Err(PipelineError::Configuration);
            }
        }
        let mut program = Self {
            scope,
            generation: generation.into(),
            history_limit,
            sources: source_map,
            clusters: cluster_map,
            slots: slot_map,
            owners,
            consumer: consumer.into(),
            fingerprint: String::new(),
        };
        for cluster in program.clusters.keys() {
            let _ = program.readiness(cluster)?;
        }
        program.fingerprint = digest(&program.to_record());
        Ok(program)
    }
    pub(crate) fn validate_registrations<C: CalculationPort>(
        &self,
        port: &C,
    ) -> PipelineResult<()> {
        let declared = port.registrations();
        if declared.len() != self.slots.len() {
            return Err(PipelineError::Configuration);
        }
        let actual: BTreeMap<_, _> = declared
            .into_iter()
            .map(|r| (r.binding.scope().to_owned(), r))
            .collect();
        if actual != self.slots {
            return Err(PipelineError::Configuration);
        }
        Ok(())
    }
    pub fn scope(&self) -> &OnlyMarketDataStateScope {
        &self.scope
    }
    pub fn slots(&self) -> &BTreeMap<String, CalculationSlot> {
        &self.slots
    }
    pub fn to_record(&self) -> Value {
        json!({"schema_version":1,"engine":self.scope.engine_id().value(),"runtime":self.scope.runtime_id().value(),"generation":self.generation,"history_limit":self.history_limit,"sources":self.sources.values().map(SourceProgram::record).collect::<Vec<_>>(),"clusters":self.clusters.iter().map(|(id,sub)|json!({"cluster":id.value(),"subscription":sub.to_record()})).collect::<Vec<_>>(),"slots":self.slots.values().map(CalculationSlot::to_record).collect::<Vec<_>>(),"consumer":self.consumer})
    }
    pub fn fingerprint(&self) -> String {
        self.fingerprint.clone()
    }
    pub(crate) fn readiness(
        &self,
        cluster: &OnlyClusterId,
    ) -> PipelineResult<Option<ReadinessPlan>> {
        let slots: Vec<_> = self
            .slots
            .values()
            .filter(|s| &s.cluster == cluster)
            .collect();
        if slots.is_empty() {
            return Ok(None);
        }
        if slots.iter().any(|s| {
            s.dependencies
                .iter()
                .any(|d| !self.slots.get(d).is_some_and(|r| &r.cluster == cluster))
        }) {
            return Err(PipelineError::Configuration);
        }
        let nodes = slots
            .iter()
            .map(|s| {
                ReadinessRequirement::new(s.binding.clone(), s.required, s.dependencies.clone())
            })
            .collect::<Result<Vec<_>, _>>()
            .map_err(|_| PipelineError::Configuration)?;
        Ok(Some(
            ReadinessPlan::new(nodes).map_err(|_| PipelineError::Configuration)?,
        ))
    }
    pub(crate) fn managers(&self) -> PipelineResult<BTreeMap<String, OnlyConstructionManager>> {
        self.sources
            .iter()
            .map(|(id, s)| {
                let scope = OnlyConstructionScope::new(
                    self.scope.engine_id().clone(),
                    self.scope.runtime_id().clone(),
                    id,
                )
                .map_err(|_| PipelineError::Configuration)?;
                let mut manager =
                    OnlyConstructionManager::new(scope, s.calendar.clone(), s.registry.clone())
                        .map_err(|_| PipelineError::Configuration)?;
                manager
                    .register("program", s.graph.clone())
                    .map_err(|_| PipelineError::Configuration)?;
                Ok((id.clone(), manager))
            })
            .collect()
    }
    pub(crate) fn delivery(&self) -> PipelineResult<OnlyMarketDataDelivery> {
        let mut d = OnlyMarketDataDelivery::new(self.scope.clone());
        for (id, sub) in &self.clusters {
            d.register(id.clone(), sub.clone())
                .map_err(|_| PipelineError::Configuration)?;
        }
        Ok(d)
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CalculationFailure {
    Known,
    Unknown,
}
/// Exact scoped calculation owner. No implicit retry; restore builds an isolated fresh candidate.
pub trait CalculationPort: Sized {
    fn registrations(&self) -> Vec<CalculationSlot>;
    fn snapshot(&mut self, scope: &str) -> Result<CalculationSnapshot, CalculationFailure>;
    fn update(&mut self, scope: &str, bars: &[Arc<OnlyBar>]) -> Result<(), CalculationFailure>;
    fn capture(&mut self) -> Result<Value, CalculationFailure>;
    fn restore_candidate(&self, value: &Value) -> Result<Self, CalculationFailure>;
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ConsumerOutcome {
    Accepted,
    Failed,
    Unknown,
}
/// Deterministic non-effectful preparation consumer, NOT a trading command/effect authority.
pub trait PreparationConsumer {
    fn artifact(&self) -> &str;
    fn consume(
        &mut self,
        identity: &str,
        plan: &OnlyBarDeliveryPlan,
        calculations: &BTreeMap<String, CalculationSnapshot>,
    ) -> ConsumerOutcome;
}
#[derive(Clone)]
pub struct PipelineInput {
    pub source: String,
    pub sequence: u64,
    pub fact: OnlyConstructionFact,
    pub logical_init: OnlyTimestamp,
    pub quality: Vec<String>,
}
impl PipelineInput {
    pub(crate) fn stream_key(&self) -> String {
        json!([self.source, self.fact.input().to_record()]).to_string()
    }
    pub fn to_record(&self) -> Value {
        let (kind, fact) = match &self.fact {
            OnlyConstructionFact::Bar(b) => ("BAR", b.to_record()),
            OnlyConstructionFact::Trade(t) => ("TRADE", t.to_record()),
        };
        json!({"source":self.source,"sequence":self.sequence,"kind":kind,"fact":fact,"logical_init_ns":self.logical_init.unix_nanos().to_string(),"quality":self.quality})
    }
}
pub struct PreparedMarketData {
    pub input_identity: String,
    pub snapshot: Option<OnlyMarketDataSnapshot>,
    pub receipts: Vec<Value>,
    pub plans: Vec<OnlyBarDeliveryPlan>,
}
impl PreparedMarketData {
    pub fn to_record(&self) -> Value {
        json!({"schema_version":2,"input_identity":self.input_identity,"snapshot":self.snapshot.as_ref().map(OnlyMarketDataSnapshot::to_record),"receipts":self.receipts,"plans":self.plans.iter().map(|p|json!({"cluster":p.cluster_id().value(),"subscription":p.subscription_id().value(),"snapshot":p.snapshot().to_record()})).collect::<Vec<_>>()})
    }
}

impl std::fmt::Display for CalculationFailure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for CalculationFailure {}
/// Explicit no-calculation declaration; no implicit worker or synthesized readiness.
pub struct NoCalculations;
impl CalculationPort for NoCalculations {
    fn registrations(&self) -> Vec<CalculationSlot> {
        vec![]
    }
    fn snapshot(&mut self, _: &str) -> Result<CalculationSnapshot, CalculationFailure> {
        Err(CalculationFailure::Known)
    }
    fn update(&mut self, _: &str, _: &[Arc<OnlyBar>]) -> Result<(), CalculationFailure> {
        Err(CalculationFailure::Known)
    }
    fn capture(&mut self) -> Result<Value, CalculationFailure> {
        Ok(json!({"schema_version":1,"instances":[]}))
    }
    fn restore_candidate(&self, value: &Value) -> Result<Self, CalculationFailure> {
        if *value == json!({"schema_version":1,"instances":[]}) {
            Ok(Self)
        } else {
            Err(CalculationFailure::Known)
        }
    }
}
