use crate::model::*;
use onlyalpha_calculation::{CalculationSnapshot, InputPosition, StateOutcome};
use onlyalpha_domain::{
    base::OnlyDomainModel, identifiers::OnlyClusterId, market::OnlyBar, time::OnlyTimestamp,
};
use onlyalpha_market_data_construction::*;
use onlyalpha_market_data_delivery::*;
use onlyalpha_market_data_state::*;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    panic::{AssertUnwindSafe, catch_unwind},
    sync::Arc,
};
#[derive(Clone)]
pub(crate) struct Frontier {
    pub source: String,
    pub input: OnlyConstructionInput,
    pub sequence: u64,
    pub count: u64,
    pub event: OnlyTimestamp,
}
pub struct MarketDataPipeline<C: CalculationPort, D: PreparationConsumer> {
    pub(crate) program: PipelineProgram,
    pub(crate) managers: BTreeMap<String, OnlyConstructionManager>,
    pub(crate) state: OnlyMarketDataState,
    pub(crate) delivery: OnlyMarketDataDelivery,
    pub(crate) calculations: C,
    pub(crate) consumer: D,
    pub(crate) failed: bool,
    pub(crate) chain: String,
    pub(crate) processed: u64,
    pub(crate) frontiers: BTreeMap<String, Frontier>,
    pub(crate) last_init: Option<OnlyTimestamp>,
    pub(crate) expected: BTreeMap<String, InputPosition>,
    pub(crate) last_inputs: BTreeMap<String, Arc<OnlyBar>>,
    pub(crate) quarantined: BTreeMap<OnlyClusterId, Value>,
}
impl<C: CalculationPort, D: PreparationConsumer> MarketDataPipeline<C, D> {
    pub fn new(program: PipelineProgram, mut calculations: C, consumer: D) -> PipelineResult<Self> {
        program.validate_registrations(&calculations)?;
        if consumer.artifact() != program.consumer {
            return Err(PipelineError::Configuration);
        }
        for (id, s) in &program.slots {
            let snap = calculations
                .snapshot(id)
                .map_err(|_| PipelineError::Configuration)?;
            if snap.binding() != &s.binding
                || snap.to_record()["cursor"]["revision"] != 0
                || snap.outcome() != StateOutcome::Uninitialized
            {
                return Err(PipelineError::Configuration);
            }
        }
        let managers = program.managers()?;
        let delivery = program.delivery()?;
        let state = OnlyMarketDataState::new(
            program.scope.clone(),
            OnlyMarketDataStateConfig {
                history_limit: program.history_limit,
            },
        )
        .map_err(|_| PipelineError::Configuration)?;
        let expected = program
            .slots
            .keys()
            .map(|k| (k.clone(), InputPosition::unobserved()))
            .collect();
        let chain = digest(
            &json!({"schema_version":1,"program":program.fingerprint(),"initial_state":state.capture_checkpoint()}),
        );
        Ok(Self {
            program,
            managers,
            state,
            delivery,
            calculations,
            consumer,
            failed: false,
            chain,
            processed: 0,
            frontiers: BTreeMap::new(),
            last_init: None,
            expected,
            last_inputs: BTreeMap::new(),
            quarantined: BTreeMap::new(),
        })
    }
    pub fn calculations(&self) -> &C {
        &self.calculations
    }
    pub fn is_failed(&self) -> bool {
        self.failed
    }
    pub fn program(&self) -> &PipelineProgram {
        &self.program
    }
    pub fn latest(&self, kind: &onlyalpha_domain::market::OnlyBarType) -> Option<&OnlyBar> {
        self.state.latest_closed(kind)
    }
    fn preflight(&self, input: &PipelineInput) -> PipelineResult<()> {
        if self.failed {
            return Err(PipelineError::RecoveryRequired);
        }
        if self.processed == u64::MAX
            || input.sequence == 0
            || input.quality.len() > 64
            || input
                .quality
                .iter()
                .any(|q| q.is_empty() || q.len() > 256 || q.chars().any(char::is_control))
            || input.quality.windows(2).any(|v| v[0] >= v[1])
        {
            return Err(PipelineError::Input);
        }
        let manager = self
            .managers
            .get(&input.source)
            .ok_or(PipelineError::Input)?;
        if !manager.graph().providers().contains(&input.fact.input())
            || input.logical_init < input.fact.event()
            || self
                .last_init
                .as_ref()
                .is_some_and(|t| t > &input.logical_init)
        {
            return Err(PipelineError::Input);
        }
        if let Some(previous) = self.frontiers.get(&input.stream_key())
            && (input.sequence <= previous.sequence
                || input.fact.event() < previous.event
                || (matches!(input.fact, OnlyConstructionFact::Bar(_))
                    && input.fact.event() == previous.event))
        {
            return Err(PipelineError::Input);
        }
        if self
            .frontiers
            .values()
            .any(|f| f.event > input.fact.event())
        {
            return Err(PipelineError::Input);
        }
        if let OnlyConstructionFact::Bar(bar) = &input.fact
            && (!bar.is_closed() || bar.ts_event() != bar.bar_end() || *bar.revision() != 0.into())
        {
            return Err(PipelineError::Input);
        }
        Ok(())
    }
    pub fn process(&mut self, input: &PipelineInput) -> PipelineResult<PreparedMarketData> {
        self.preflight(input)?;
        self.failed = true;
        let result = catch_unwind(AssertUnwindSafe(|| self.process_inner(input)))
            .unwrap_or(Err(PipelineError::Shared("PANIC")));
        if result.is_ok() {
            self.failed = false;
        }
        result
    }
    fn process_inner(&mut self, input: &PipelineInput) -> PipelineResult<PreparedMarketData> {
        let identity = digest(
            &json!({"program":self.program.fingerprint(),"previous":self.chain,"input":input.to_record()}),
        );
        let mut bars = self
            .managers
            .get_mut(&input.source)
            .ok_or(PipelineError::Input)?
            .process(&input.source, &input.fact, &input.logical_init)
            .map_err(|_| PipelineError::Shared("CONSTRUCTION"))?;
        if let OnlyConstructionFact::Bar(b) = &input.fact {
            bars.push(b.clone());
        }
        bars.sort_by_key(|b| bar_key(b.bar_type()));
        let mut seen = BTreeSet::new();
        if bars.iter().any(|b| {
            !seen.insert(bar_key(b.bar_type()))
                || self.program.owners.get(&bar_key(b.bar_type())) != Some(&input.source)
        }) {
            return Err(PipelineError::Shared("BAR_OWNER"));
        }
        let mut snapshot = None;
        let mut receipts = vec![];
        if !bars.is_empty() {
            let primary = bars
                .iter()
                .max_by_key(|b| (b.bar_end(), bar_key(b.bar_type())))
                .expect("nonempty")
                .bar_type()
                .clone();
            let current = self
                .state
                .apply_closed(
                    &bars,
                    &primary,
                    input.logical_init.clone(),
                    input.quality.clone(),
                )
                .map_err(|_| PipelineError::Shared("STATE"))?;
            let mut snapshots = BTreeMap::new();
            for (id, slot) in &self.program.slots {
                let mut value = self
                    .calculations
                    .snapshot(id)
                    .map_err(|_| PipelineError::Shared("CALCULATION_SNAPSHOT"))?;
                if value.binding() != &slot.binding || value.outcome() == StateOutcome::Unknown {
                    return Err(PipelineError::Shared("CALCULATION_UNKNOWN"));
                }
                if !self.quarantined.contains_key(&slot.cluster)
                    && !matches!(
                        value.outcome(),
                        StateOutcome::Failed | StateOutcome::Unavailable
                    )
                    && let Some(bar) = bars.iter().find(|b| b.bar_type() == &slot.bar_type)
                {
                    let cursor = &value.to_record()["cursor"];
                    let revision = cursor["revision"]
                        .as_u64()
                        .and_then(|v| v.checked_add(1))
                        .ok_or(PipelineError::Shared("CURSOR"))?;
                    let samples = cursor["samples"]
                        .as_u64()
                        .and_then(|v| v.checked_add(1))
                        .ok_or(PipelineError::Shared("CURSOR"))?;
                    let expected = InputPosition::new(
                        revision,
                        samples,
                        &OnlyTimestamp::from_datetime(*bar.bar_end())
                            .unix_nanos()
                            .to_string(),
                        &digest(&bar.to_record()),
                    )
                    .map_err(|_| PipelineError::Shared("POSITION"))?;
                    self.expected.insert(id.clone(), expected.clone());
                    self.last_inputs.insert(id.clone(), bar.clone());
                    let result = self.calculations.update(id, std::slice::from_ref(bar));
                    if result == Err(CalculationFailure::Unknown) {
                        return Err(PipelineError::Shared("CALCULATION_UNKNOWN"));
                    }
                    value = self
                        .calculations
                        .snapshot(id)
                        .map_err(|_| PipelineError::Shared("CALCULATION_SNAPSHOT"))?;
                    if value.binding() != &slot.binding
                        || match result {
                            Ok(()) => {
                                !matches!(
                                    value.outcome(),
                                    StateOutcome::Ready | StateOutcome::Warming
                                ) || value.position().as_ref() != Some(&expected)
                            }
                            Err(CalculationFailure::Known) => !matches!(
                                value.outcome(),
                                StateOutcome::Failed | StateOutcome::Unavailable
                            ),
                            Err(CalculationFailure::Unknown) => true,
                        }
                    {
                        return Err(PipelineError::Shared("CALCULATION_RECEIPT"));
                    }
                }
                snapshots.insert(id.clone(), value);
            }
            let plans = self
                .delivery
                .route(&current)
                .map_err(|_| PipelineError::Shared("DELIVERY_PLAN"))?;
            for plan in plans {
                let cluster = plan.cluster_id();
                let values: BTreeMap<String, CalculationSnapshot> = snapshots
                    .iter()
                    .filter(|(id, _)| &self.program.slots[*id].cluster == cluster)
                    .map(|(id, v)| (id.clone(), v.clone()))
                    .collect();
                let expected = self
                    .expected
                    .iter()
                    .filter(|(id, _)| &self.program.slots[*id].cluster == cluster)
                    .map(|(id, v)| (id.clone(), v.clone()))
                    .collect();
                let barrier = self
                    .program
                    .readiness(cluster)?
                    .map(|p| p.evaluate(&values, &expected))
                    .transpose()
                    .map_err(|_| PipelineError::Shared("READINESS"))?;
                let ready = barrier.as_ref().is_none_or(|b| b.ready());
                let degraded = barrier.as_ref().is_some_and(|b| b.degraded());
                let delivery_id = digest(
                    &json!({"input_identity":identity,"cluster":cluster.value(),"event_ns":plan.snapshot().ts_event().unix_nanos().to_string(),"primary":plan.snapshot().primary_bar_type().to_record(),"calculations":values.iter().map(|(k,v)|json!([k,v.to_record()])).collect::<Vec<_>>()}),
                );
                let (mut called, mut outcome) = (false, "BLOCKED");
                if self.quarantined.contains_key(cluster) {
                    outcome = "QUARANTINED";
                } else if ready {
                    called = true;
                    let observed = catch_unwind(AssertUnwindSafe(|| {
                        self.consumer.consume(&delivery_id, &plan, &values)
                    }))
                    .unwrap_or(ConsumerOutcome::Unknown);
                    outcome = match observed {
                        ConsumerOutcome::Accepted => "ACCEPTED",
                        ConsumerOutcome::Failed => "FAILED",
                        ConsumerOutcome::Unknown => "UNKNOWN",
                    };
                }
                let receipt = json!({"cluster":cluster.value(),"event_ns":plan.snapshot().ts_event().unix_nanos().to_string(),"delivery_id":delivery_id,"input_identity":identity,"called":called,"outcome":outcome,"degraded":degraded});
                if matches!(outcome, "FAILED" | "UNKNOWN") {
                    self.quarantined.insert(cluster.clone(), receipt.clone());
                }
                receipts.push(receipt);
            }
            snapshot = Some(current);
        }
        let key = input.stream_key();
        let count = self.frontiers.get(&key).map_or(1, |f| f.count + 1);
        self.frontiers.insert(
            key,
            Frontier {
                source: input.source.clone(),
                input: input.fact.input(),
                sequence: input.sequence,
                count,
                event: input.fact.event(),
            },
        );
        self.chain = identity.clone();
        self.processed += 1;
        self.last_init = Some(input.logical_init.clone());
        Ok(PreparedMarketData {
            input_identity: identity,
            snapshot,
            receipts,
        })
    }
}
