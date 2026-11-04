//! One Runtime-local construction owner. Checkpoints never configure a different program.
use crate::{compiler::*, executor::*, model::*, record::*};
use num_bigint::BigUint;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::OnlyTradingCalendar,
    identifiers::{OnlyEngineId, OnlyIdentifier, OnlyRuntimeId},
    market::OnlyBar,
    time::OnlyTimestamp,
};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyConstructionScope {
    engine: OnlyEngineId,
    runtime: OnlyRuntimeId,
    source: String,
}
impl OnlyConstructionScope {
    pub fn new(
        engine: OnlyEngineId,
        runtime: OnlyRuntimeId,
        source: &str,
    ) -> OnlyConstructionResult<Self> {
        nonempty(source)?;
        Ok(Self {
            engine,
            runtime,
            source: source.into(),
        })
    }
    pub fn engine_id(&self) -> &OnlyEngineId {
        &self.engine
    }
    pub fn runtime_id(&self) -> &OnlyRuntimeId {
        &self.runtime
    }
    pub fn source_binding(&self) -> &str {
        &self.source
    }
}
struct Committed {
    registrations: BTreeMap<String, OnlyConstructionGraph>,
    graph: OnlyConstructionGraph,
    plan: OnlyConstructionPlan,
    executors: BTreeMap<String, Box<dyn OnlyConstructionExecutor>>,
    creation_count: BigUint,
}
pub struct OnlyConstructionManager {
    scope: OnlyConstructionScope,
    calendar: Arc<OnlyTradingCalendar>,
    calendar_fingerprint: String,
    registry: Arc<OnlyConstructionRegistry>,
    committed: Committed,
    failed: bool,
}
fn registration_id(id: &str) -> OnlyConstructionResult<String> {
    let parsed = OnlyIdentifier::new(id).map_err(err)?;
    if parsed.value() != id {
        return Err(err("REGISTRATION_ID_NOT_CANONICAL"));
    }
    Ok(id.into())
}
fn merged_graph(
    registrations: &BTreeMap<String, OnlyConstructionGraph>,
) -> OnlyConstructionResult<OnlyConstructionGraph> {
    let mut providers = BTreeMap::new();
    let mut edges = BTreeMap::new();
    for graph in registrations.values() {
        for provider in graph.providers() {
            providers.insert(provider.key(), provider.clone());
        }
        for edge in graph.edges() {
            let key = OnlyConstructionInput::Bar(edge.target().clone()).key();
            if edges.get(&key).is_some_and(|prior| prior != edge) {
                return Err(err("CONSTRUCTION_LANE_CONFLICT"));
            }
            edges.insert(key, edge.clone());
        }
    }
    OnlyConstructionGraph::new(
        providers.into_values().collect(),
        edges.into_values().collect(),
    )
}
fn provider_counts(
    registrations: &BTreeMap<String, OnlyConstructionGraph>,
) -> BTreeMap<String, (OnlyConstructionInput, usize)> {
    let mut counts = BTreeMap::new();
    for graph in registrations.values() {
        for provider in graph.providers() {
            let entry = counts
                .entry(provider.key())
                .or_insert((provider.clone(), 0));
            entry.1 += 1;
        }
    }
    counts
}
fn lane_count(
    registrations: &BTreeMap<String, OnlyConstructionGraph>,
    id: &str,
    source: &str,
) -> usize {
    registrations
        .values()
        .filter(|g| {
            g.edges()
                .iter()
                .any(|e| e.lane_id(source).expect("validated binding") == id)
        })
        .count()
}
impl OnlyConstructionManager {
    pub fn new(
        scope: OnlyConstructionScope,
        calendar: Arc<OnlyTradingCalendar>,
        registry: Arc<OnlyConstructionRegistry>,
    ) -> OnlyConstructionResult<Self> {
        let graph = OnlyConstructionGraph::new(vec![], vec![])?;
        let plan = OnlyConstructionPlan::compile(&graph, &scope.source)?;
        let calendar_fingerprint = hash(&calendar.to_record());
        Ok(Self {
            scope,
            calendar,
            calendar_fingerprint,
            registry,
            committed: Committed {
                registrations: BTreeMap::new(),
                graph,
                plan,
                executors: BTreeMap::new(),
                creation_count: BigUint::default(),
            },
            failed: false,
        })
    }
    pub fn scope(&self) -> &OnlyConstructionScope {
        &self.scope
    }
    pub fn graph(&self) -> &OnlyConstructionGraph {
        &self.committed.graph
    }
    pub fn plan(&self) -> &OnlyConstructionPlan {
        &self.committed.plan
    }
    pub fn creation_count(&self) -> &BigUint {
        &self.committed.creation_count
    }
    pub fn registration_count(&self) -> usize {
        self.committed.registrations.len()
    }
    pub fn lane_reference_count(&self, id: &str) -> usize {
        lane_count(&self.committed.registrations, id, &self.scope.source)
    }
    pub fn is_failed(&self) -> bool {
        self.failed
    }
    fn require_available(&self) -> OnlyConstructionResult<()> {
        if self.failed {
            return Err(OnlyConstructionError::RecoveryRequired);
        }
        Ok(())
    }
    fn prepare_configuration(
        &self,
        registrations: BTreeMap<String, OnlyConstructionGraph>,
    ) -> OnlyConstructionResult<Committed> {
        let graph = merged_graph(&registrations)?;
        let plan = OnlyConstructionPlan::compile(&graph, &self.scope.source)?;
        let mut executors = BTreeMap::new();
        let mut created = 0usize;
        for lane in plan.lanes() {
            let mut executor = self.registry.create(lane.edge(), self.calendar.clone())?;
            if let Some(previous) = self.committed.executors.get(lane.lane_id()) {
                executor.restore_checkpoint(&previous.capture_checkpoint()?)?;
            } else {
                created += 1;
            }
            executors.insert(lane.lane_id().to_string(), executor);
        }
        Ok(Committed {
            registrations,
            graph,
            plan,
            executors,
            creation_count: &self.committed.creation_count + BigUint::from(created),
        })
    }
    pub fn register(
        &mut self,
        id: &str,
        graph: OnlyConstructionGraph,
    ) -> OnlyConstructionResult<()> {
        self.require_available()?;
        let id = registration_id(id)?;
        if self.committed.registrations.contains_key(&id) {
            return Err(err("REGISTRATION_ALREADY_EXISTS"));
        }
        let mut registrations = self.committed.registrations.clone();
        registrations.insert(id, graph);
        let next = self.prepare_configuration(registrations)?;
        self.committed = next;
        Ok(())
    }
    pub fn unregister(&mut self, id: &str) -> OnlyConstructionResult<()> {
        self.require_available()?;
        let id = registration_id(id)?;
        if !self.committed.registrations.contains_key(&id) {
            return Err(err("REGISTRATION_NOT_FOUND"));
        }
        let mut registrations = self.committed.registrations.clone();
        registrations.remove(&id);
        let next = self.prepare_configuration(registrations)?;
        self.committed = next;
        Ok(())
    }
    fn stage_executors(
        &self,
    ) -> OnlyConstructionResult<BTreeMap<String, Box<dyn OnlyConstructionExecutor>>> {
        let mut result = BTreeMap::new();
        for lane in self.committed.plan.lanes() {
            let mut executor = self.registry.create(lane.edge(), self.calendar.clone())?;
            executor.restore_checkpoint(
                &self.committed.executors[lane.lane_id()].capture_checkpoint()?,
            )?;
            result.insert(lane.lane_id().to_string(), executor);
        }
        Ok(result)
    }
    pub fn process(
        &mut self,
        source: &str,
        fact: &OnlyConstructionFact,
        init: &OnlyTimestamp,
    ) -> OnlyConstructionResult<Vec<Arc<OnlyBar>>> {
        self.require_available()?;
        if source != self.scope.source {
            return Err(OnlyConstructionError::Scope);
        }
        let input = fact.input();
        let Some(provider) = self
            .committed
            .plan
            .providers()
            .iter()
            .find(|p| p.input() == &input)
        else {
            return Ok(vec![]);
        };
        let provider_id = provider.lane_id().to_string();
        // Set before extension calls: an unwind cannot leave the owner apparently healthy.
        self.failed = true;
        if let OnlyConstructionFact::Bar(bar) = fact
            && (!bar.is_closed() || *bar.revision() != 0.into() || bar.ts_event() != bar.bar_end())
        {
            return Err(err("PROVIDER_BAR_CONTRACT"));
        }
        if init < &fact.event() {
            return Err(OnlyConstructionError::Time);
        }
        let mut staged = self.stage_executors()?;
        let mut facts = BTreeMap::from([(provider_id, fact.clone())]);
        let mut outputs = vec![];
        let mut output_types = BTreeSet::new();
        // An acyclic single-source-per-target graph reaches fixpoint in one topological pass.
        // Global (level,lane_id) order is independent of the order in which parents emit.
        for lane in self.committed.plan.lanes() {
            let Some(input) = facts.get(lane.source_lane_id()).cloned() else {
                continue;
            };
            let produced = staged
                .get_mut(lane.lane_id())
                .expect("complete staged plan")
                .process(&input, init)?;
            for bar in produced {
                if bar.bar_type() != lane.edge().target()
                    || !bar.is_closed()
                    || *bar.revision() != 0.into()
                    || bar.ts_event() != bar.bar_end()
                    || OnlyTimestamp::from_datetime(*bar.bar_end()) > fact.event()
                    || OnlyTimestamp::from_datetime(*bar.ts_init()) != *init
                {
                    return Err(err("EXECUTOR_OUTPUT_CONTRACT"));
                }
                if !output_types.insert(OnlyConstructionInput::Bar(bar.bar_type().clone()).key()) {
                    return Err(err("DUPLICATE_CONSTRUCTION_OUTPUT"));
                }
                facts.insert(
                    lane.lane_id().to_string(),
                    OnlyConstructionFact::Bar(bar.clone()),
                );
                outputs.push(bar);
            }
        }
        self.committed.executors = staged;
        self.failed = false;
        Ok(outputs)
    }
    pub fn capture_checkpoint(&self) -> OnlyConstructionResult<Value> {
        self.require_available()?;
        let lanes=self.committed.executors.iter().map(|(id,executor)|{let lane=self.committed.plan.lanes().iter().find(|l|l.lane_id()==id).expect("compiled owner");Ok(json!({"lane_id":id,"source_lane_id":lane.source_lane_id(),"topological_level":lane.level(),"recipe_fingerprint":lane.edge().recipe().fingerprint(),"reference_count":self.lane_reference_count(id),"executor_state":executor.capture_checkpoint()?}))}).collect::<OnlyConstructionResult<Vec<_>>>()?;
        Ok(
            json!({"schema_version":4,"engine_id":self.scope.engine.value(),"runtime_id":self.scope.runtime.value(),"source_binding_identity":self.scope.source,"calendar_fingerprint":self.calendar_fingerprint,"registrations":self.committed.registrations.iter().map(|(id,graph)|json!({"registration_id":id,"graph":graph.to_record()})).collect::<Vec<_>>(),"construction_graph_fingerprint":self.committed.graph.fingerprint(),"lanes":lanes,"provider_reference_counts":provider_counts(&self.committed.registrations).into_values().map(|(provider,count)|json!([provider.to_record(),count])).collect::<Vec<_>>(),"creation_count":number(&self.committed.creation_count)}),
        )
    }
    pub fn restore_checkpoint(&mut self, value: &Value) -> OnlyConstructionResult<()> {
        let row = object(
            value,
            4,
            &[
                "engine_id",
                "runtime_id",
                "source_binding_identity",
                "calendar_fingerprint",
                "registrations",
                "construction_graph_fingerprint",
                "lanes",
                "provider_reference_counts",
                "creation_count",
            ],
        )?;
        let scope = OnlyConstructionScope::new(
            text(&row["engine_id"])?.parse().map_err(err)?,
            text(&row["runtime_id"])?.parse().map_err(err)?,
            text(&row["source_binding_identity"])?,
        )?;
        if scope.engine.value() != text(&row["engine_id"])?
            || scope.runtime.value() != text(&row["runtime_id"])?
        {
            return Err(err("OWNER_ID_NOT_CANONICAL"));
        }
        digest(text(&row["calendar_fingerprint"])?)?;
        digest(text(&row["construction_graph_fingerprint"])?)?;
        if scope != self.scope
            || text(&row["calendar_fingerprint"])? != self.calendar_fingerprint
            || text(&row["construction_graph_fingerprint"])? != self.committed.graph.fingerprint()
        {
            return Err(OnlyConstructionError::Scope);
        }
        let mut registrations = BTreeMap::new();
        for raw in array(&row["registrations"])? {
            let r = raw
                .as_object()
                .filter(|r| {
                    r.len() == 2 && r.contains_key("registration_id") && r.contains_key("graph")
                })
                .ok_or_else(|| err("REGISTRATION_FIELDS"))?;
            let id = registration_id(text(&r["registration_id"])?)?;
            let graph = OnlyConstructionGraph::from_record(&r["graph"])?;
            if registrations.insert(id, graph).is_some() {
                return Err(err("DUPLICATE_REGISTRATION"));
            }
        }
        if registrations != self.committed.registrations {
            return Err(OnlyConstructionError::Scope);
        }
        let mut counts = BTreeMap::new();
        for raw in array(&row["provider_reference_counts"])? {
            let pair = array(raw)?;
            if pair.len() != 2 {
                return Err(err("PROVIDER_COUNT_FIELDS"));
            }
            let provider = OnlyConstructionInput::from_record(&pair[0])?;
            let count: usize = integer(&pair[1])?;
            if count == 0 || counts.insert(provider.key(), (provider, count)).is_some() {
                return Err(err("PROVIDER_COUNTS"));
            }
        }
        if counts != provider_counts(&self.committed.registrations) {
            return Err(err("PROVIDER_COUNT_RELATIONS"));
        }
        let creation_count: BigUint = integer(&row["creation_count"])?;
        if creation_count < BigUint::from(self.committed.executors.len()) {
            return Err(err("CREATION_COUNT"));
        }
        let mut states = BTreeMap::new();
        for raw in array(&row["lanes"])? {
            let r = raw
                .as_object()
                .filter(|r| {
                    r.len() == 6
                        && [
                            "lane_id",
                            "source_lane_id",
                            "topological_level",
                            "recipe_fingerprint",
                            "reference_count",
                            "executor_state",
                        ]
                        .iter()
                        .all(|k| r.contains_key(*k))
                })
                .ok_or_else(|| err("LANE_FIELDS"))?;
            let id = text(&r["lane_id"])?;
            let lane = self
                .committed
                .plan
                .lanes()
                .iter()
                .find(|l| l.lane_id() == id)
                .ok_or_else(|| err("UNKNOWN_LANE"))?;
            if text(&r["source_lane_id"])? != lane.source_lane_id()
                || integer::<usize>(&r["topological_level"])? != lane.level()
                || text(&r["recipe_fingerprint"])? != lane.edge().recipe().fingerprint()
                || integer::<usize>(&r["reference_count"])? != self.lane_reference_count(id)
            {
                return Err(err("LANE_RELATIONS"));
            }
            if states
                .insert(id.to_string(), &r["executor_state"])
                .is_some()
            {
                return Err(err("DUPLICATE_LANE"));
            }
        }
        if states.len() != self.committed.executors.len() {
            return Err(err("INCOMPLETE_LANE_SET"));
        }
        let mut executors = BTreeMap::new();
        for lane in self.committed.plan.lanes() {
            let mut executor = self.registry.create(lane.edge(), self.calendar.clone())?;
            executor.restore_checkpoint(states[lane.lane_id()])?;
            executors.insert(lane.lane_id().to_string(), executor);
        }
        self.committed.executors = executors;
        self.committed.creation_count = creation_count;
        self.failed = false;
        Ok(())
    }
}
#[cfg(test)]
mod atomic_tests {
    use super::*;
    use onlyalpha_domain::market::OnlyBarType;
    use onlyalpha_domain::{
        calendar::{OnlyTradingCalendarInput, OnlyTradingSession, OnlyTradingSessionInput},
        enums::{OnlyAdjustmentType, OnlySessionType},
        market::{OnlyBar, OnlyBarInput, OnlyBarSemantic, OnlyBarTypeInput},
        time::OnlyTimeZone,
        value::{OnlyPrice, OnlyQuantity},
    };
    use std::sync::atomic::{AtomicUsize, Ordering};
    struct Factory {
        calls: Arc<AtomicUsize>,
        panic: bool,
    }
    struct Executor {
        target: OnlyBarType,
        calls: Arc<AtomicUsize>,
        steps: u64,
        panic: bool,
    }
    impl OnlyConstructionFactory for Factory {
        fn create(
            &self,
            edge: &OnlyConstructionEdge,
            _calendar: Arc<OnlyTradingCalendar>,
        ) -> OnlyConstructionResult<Box<dyn OnlyConstructionExecutor>> {
            Ok(Box::new(Executor {
                target: edge.target().clone(),
                calls: self.calls.clone(),
                steps: 0,
                panic: self.panic,
            }))
        }
    }
    impl OnlyConstructionExecutor for Executor {
        fn target(&self) -> &OnlyBarType {
            &self.target
        }
        fn process(
            &mut self,
            _fact: &OnlyConstructionFact,
            _init: &OnlyTimestamp,
        ) -> OnlyConstructionResult<Vec<Arc<OnlyBar>>> {
            self.steps += 1;
            if self.calls.fetch_add(1, Ordering::SeqCst) + 1 == 2 {
                if self.panic {
                    panic!("controlled executor unwind");
                }
                return Err(err("CONTROLLED_LATE_FAILURE"));
            }
            Ok(vec![])
        }
        fn capture_checkpoint(&self) -> OnlyConstructionResult<Value> {
            Ok(json!({"steps":self.steps}))
        }
        fn restore_checkpoint(&mut self, value: &Value) -> OnlyConstructionResult<()> {
            self.steps = value["steps"].as_u64().ok_or_else(|| err("STEPS"))?;
            Ok(())
        }
    }
    pub(super) fn fixture(
        panic: bool,
    ) -> (
        OnlyConstructionManager,
        OnlyConstructionFact,
        Arc<AtomicUsize>,
    ) {
        let semantic = OnlyBarSemantic::fixed_duration(1.into(), None).unwrap();
        let source = OnlyBarType::new(OnlyBarTypeInput {
            instrument_id: "A.X".parse().unwrap(),
            semantic,
        })
        .unwrap();
        let edges = [3, 5]
            .into_iter()
            .map(|minutes| {
                let target = OnlyBarType::new(OnlyBarTypeInput {
                    instrument_id: source.instrument_id().clone(),
                    semantic: OnlyBarSemantic::fixed_duration(minutes.into(), None).unwrap(),
                })
                .unwrap();
                let recipe = OnlyConstructionRecipe::derived(
                    target.semantic().clone(),
                    OnlyConstructionSemantic::Bar(source.semantic().clone()),
                    "FAULT_TEST",
                    1u32.into(),
                    OnlyMissingPolicy::Reject,
                    OnlyIncompletePolicy::Drop,
                )
                .unwrap();
                OnlyConstructionEdge::new(
                    OnlyConstructionInput::Bar(source.clone()),
                    target,
                    recipe,
                )
                .unwrap()
            })
            .collect();
        let graph =
            OnlyConstructionGraph::new(vec![OnlyConstructionInput::Bar(source.clone())], edges)
                .unwrap();
        let session = OnlyTradingSession::new(OnlyTradingSessionInput {
            name: "all".into(),
            opens_at: "00:00:00".parse().unwrap(),
            closes_at: "00:00:00".parse().unwrap(),
            session_type: OnlySessionType::Continuous,
            belongs_to_trading_day_offset: 0,
            allows_orders: false,
            allows_market_data: true,
        })
        .unwrap();
        let calendar = Arc::new(
            OnlyTradingCalendar::new(OnlyTradingCalendarInput {
                calendar_id: "calendar".parse().unwrap(),
                venue_id: "X".parse().unwrap(),
                timezone: OnlyTimeZone::new("UTC").unwrap(),
                sessions: vec![session],
                holidays: vec![],
                weekend_days: vec![5, 6],
                session_profile_id: None,
                special_schedules: vec![],
                calendar_version: 1.into(),
                effective_from: None,
                effective_to: None,
            })
            .unwrap(),
        );
        let calls = Arc::new(AtomicUsize::new(0));
        let mut registry = OnlyConstructionRegistry::default();
        registry
            .register(
                "FAULT_TEST",
                1u32.into(),
                Arc::new(Factory {
                    calls: calls.clone(),
                    panic,
                }),
            )
            .unwrap();
        let mut manager = OnlyConstructionManager::new(
            OnlyConstructionScope::new("e".parse().unwrap(), "r".parse().unwrap(), "source")
                .unwrap(),
            calendar,
            Arc::new(registry),
        )
        .unwrap();
        manager.register("program", graph).unwrap();
        let price = OnlyPrice::new("1".parse().unwrap(), 0).unwrap();
        let end = "2026-01-05T00:01:00Z".parse().unwrap();
        let bar = OnlyBar::new(OnlyBarInput {
            bar_type: source,
            open: price.clone(),
            high: price.clone(),
            low: price.clone(),
            close: price,
            volume: OnlyQuantity::new("1".parse().unwrap(), 0).unwrap(),
            quote_volume: None,
            turnover: None,
            trade_count: Some(1.into()),
            open_interest: None,
            bar_start: "2026-01-05T00:00:00Z".parse().unwrap(),
            bar_end: end,
            ts_event: end,
            ts_init: end,
            is_closed: true,
            revision: 0.into(),
            adjustment_type: OnlyAdjustmentType::Raw,
            trading_day: "2026-01-05".parse().unwrap(),
            session_type: OnlySessionType::Continuous,
        })
        .unwrap();
        (manager, OnlyConstructionFact::Bar(Arc::new(bar)), calls)
    }
    #[test]
    fn failed_or_unwinding_late_executor_never_changes_committed_prefix() {
        for panic in [false, true] {
            let (mut manager, fact, calls) = fixture(panic);
            let before: Vec<_> = manager
                .committed
                .executors
                .iter()
                .map(|(id, executor)| (id.clone(), executor.capture_checkpoint().unwrap()))
                .collect();
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                manager.process("source", &fact, &fact.event())
            }));
            if panic {
                assert!(result.is_err());
            } else {
                assert!(result.unwrap().is_err());
            }
            assert!(manager.is_failed());
            assert_eq!(calls.load(Ordering::SeqCst), 2);
            let after: Vec<_> = manager
                .committed
                .executors
                .iter()
                .map(|(id, executor)| (id.clone(), executor.capture_checkpoint().unwrap()))
                .collect();
            assert_eq!(after, before);
        }
    }
}
#[cfg(test)]
mod root_input_tests {
    use super::*;
    use onlyalpha_domain::market::OnlyBarType;
    // An extension that deliberately emits nothing must not bypass universal root validation.
    struct Factory;
    struct Executor {
        target: OnlyBarType,
    }
    impl OnlyConstructionFactory for Factory {
        fn create(
            &self,
            e: &OnlyConstructionEdge,
            _: Arc<OnlyTradingCalendar>,
        ) -> OnlyConstructionResult<Box<dyn OnlyConstructionExecutor>> {
            Ok(Box::new(Executor {
                target: e.target().clone(),
            }))
        }
    }
    impl OnlyConstructionExecutor for Executor {
        fn target(&self) -> &OnlyBarType {
            &self.target
        }
        fn process(
            &mut self,
            _: &OnlyConstructionFact,
            _: &OnlyTimestamp,
        ) -> OnlyConstructionResult<Vec<Arc<OnlyBar>>> {
            Ok(vec![])
        }
        fn capture_checkpoint(&self) -> OnlyConstructionResult<Value> {
            Ok(json!({}))
        }
        fn restore_checkpoint(&mut self, _: &Value) -> OnlyConstructionResult<()> {
            Ok(())
        }
    }
    #[test]
    fn extension_cannot_admit_forming_or_revised_root() {
        let (mut m, fact, _) = super::atomic_tests::fixture(false);
        let OnlyConstructionFact::Bar(base) = fact else {
            unreachable!()
        };
        let mut registry = OnlyConstructionRegistry::default();
        registry
            .register("FAULT_TEST", 1u32.into(), Arc::new(Factory))
            .unwrap();
        m.registry = Arc::new(registry);
        for (field, value) in [
            ("is_closed", json!(false)),
            ("revision", json!(1)),
            ("ts_event", json!("2026-01-05T00:00:30+00:00")),
        ] {
            let before = m.capture_checkpoint().unwrap();
            let mut row = base.to_record();
            row[field] = value;
            let input = OnlyConstructionFact::Bar(Arc::new(OnlyBar::from_record(&row).unwrap()));
            assert!(
                m.process(
                    "source",
                    &input,
                    &OnlyTimestamp::from_datetime(*base.bar_end())
                )
                .is_err(),
                "{field}"
            );
            assert!(m.is_failed());
            m.restore_checkpoint(&before).unwrap();
        }
    }
}
