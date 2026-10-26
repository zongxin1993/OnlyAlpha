//! Technical MarketData→Strategy composition; never an official Runtime admission.
use onlyalpha_calculation::CalculationSnapshot;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBarType};
use onlyalpha_market_data_pipeline::{
    ConsumerOutcome, MarketDataPipeline, NoCalculations, PipelineInput, PipelineProgram,
    PreparationConsumer, delivery::OnlyBarDeliveryPlan,
};
use onlyalpha_strategy::{Executor, NodePort, StrategyError, StrategyResult, record_fingerprint};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    panic::{AssertUnwindSafe, catch_unwind},
};
struct PreparedOnly {
    artifact: String,
}
impl PreparationConsumer for PreparedOnly {
    fn artifact(&self) -> &str {
        &self.artifact
    }
    fn consume(
        &mut self,
        _: &str,
        _: &OnlyBarDeliveryPlan,
        _: &BTreeMap<String, CalculationSnapshot>,
    ) -> ConsumerOutcome {
        ConsumerOutcome::Accepted
    }
}
pub struct StrategyPreparation<C: NodePort> {
    pipeline: MarketDataPipeline<NoCalculations, PreparedOnly>,
    strategy: Executor<C>,
    artifact: String,
    failed: bool,
}
fn bad() -> StrategyError {
    StrategyError("STRATEGY_PREPARATION_INVALID")
}
impl<C: NodePort> StrategyPreparation<C> {
    pub fn new(program: PipelineProgram, strategy: Executor<C>) -> StrategyResult<Self> {
        // A single Strategy component owns one exact Cluster and no duplicate calculation slots.
        let p = program.to_record();
        let artifact = p["consumer"].as_str().ok_or_else(bad)?;
        let s = strategy.program();
        let clusters = p["clusters"].as_array().ok_or_else(bad)?;
        if !program.slots().is_empty()
            || clusters.len() != 1
            || program.scope().engine_id() != &s.scope().engine
            || program.scope().runtime_id() != &s.scope().runtime
            || p["generation"] != s.generation()
        {
            return Err(bad());
        }
        let pipeline = MarketDataPipeline::new(
            program,
            NoCalculations,
            PreparedOnly {
                artifact: artifact.into(),
            },
        )
        .map_err(|_| bad())?;
        let owner = Self {
            pipeline,
            strategy,
            artifact: artifact.into(),
            failed: false,
        };
        owner.validate_cut()?;
        Ok(owner)
    }
    pub fn strategy(&self) -> &Executor<C> {
        &self.strategy
    }
    pub fn is_failed(&self) -> bool {
        self.failed
    }
    pub fn process(&mut self, input: &PipelineInput) -> StrategyResult<Value> {
        if self.failed {
            return Err(StrategyError("STRATEGY_PREPARATION_RECOVERY_REQUIRED"));
        }
        self.failed = true;
        let result = catch_unwind(AssertUnwindSafe(|| {
            let prepared = self.pipeline.process(input).map_err(|_| bad())?;
            let mut outcomes = vec![];
            for plan in &prepared.plans {
                if plan.cluster_id() != &self.strategy.program().scope().cluster {
                    return Err(bad());
                }
                let receipt = prepared
                    .receipts
                    .iter()
                    .find(|r| {
                        r["cluster"] == plan.cluster_id().value()
                            && r["event_ns"] == plan.snapshot().ts_event().unix_nanos().to_string()
                    })
                    .ok_or_else(bad)?;
                if receipt["outcome"] != "ACCEPTED" {
                    return Err(bad());
                }
                let bar = plan.snapshot().primary_bar();
                outcomes.push(
                    self.strategy
                        .process(bar, &input.logical_init, &prepared.input_identity)?
                        .to_record(),
                );
            }
            self.validate_cut()?;
            Ok(json!({"schema_version":1,"preparation":prepared.to_record(),"decisions":outcomes}))
        }))
        .unwrap_or(Err(bad()));
        if result.is_ok() {
            self.failed = false;
        }
        result
    }
    fn validate_cut(&self) -> StrategyResult<()> {
        let p = self.pipeline.program().to_record();
        let s = self.strategy.program();
        let clusters = p["clusters"].as_array().ok_or_else(bad)?;
        let cluster = clusters.first().ok_or_else(bad)?;
        if cluster["cluster"] != s.scope().cluster.value() {
            return Err(bad());
        }
        // Restrict this first composition to an exact single primary subscription.
        if s.revision().universe().len() != 1 {
            return Err(bad());
        }
        let kind=OnlyBarType::from_record(&json!({"schema_version":2,"instrument_id":s.revision().universe()[0].to_record(),"semantic":s.revision().semantic().to_record()})).map_err(|_|bad())?;
        if cluster["subscription"]["primary_bar_type"] != kind.to_record() {
            return Err(bad());
        }
        let sources = p["sources"]
            .as_array()
            .filter(|v| v.len() == 1)
            .ok_or_else(bad)?;
        let source = &sources[0];
        if source["source"] != s.source()
            || source["graph"] != cluster["subscription"]["dependency_graph"]
        {
            return Err(bad());
        }
        let graph =
            onlyalpha_market_data_pipeline::construction::OnlyConstructionGraph::from_record(
                &source["graph"],
            )
            .map_err(|_| bad())?;
        let recipe = if graph.providers().contains(
            &onlyalpha_market_data_pipeline::construction::OnlyConstructionInput::Bar(kind.clone()),
        ) {
            onlyalpha_market_data_pipeline::construction::OnlyConstructionRecipe::native(
                kind.semantic().clone(),
            )
        } else {
            graph
                .edges()
                .iter()
                .find(|e| e.target() == &kind)
                .ok_or_else(bad)?
                .recipe()
                .clone()
        };
        if &recipe != s.revision().recipe() {
            return Err(bad());
        }
        match (
            self.strategy.last_outcome(kind.instrument_id()),
            self.pipeline.last_delivery(&s.scope().cluster),
        ) {
            (None, None) => (),
            (Some(o), Some(receipt))
                if receipt["outcome"] == "ACCEPTED"
                    && o.to_record()["parent_identity"] == receipt["input_identity"]
                    && o.to_record()["event_ns"] == receipt["event_ns"] => {}
            _ => return Err(bad()),
        }
        match (
            self.pipeline.latest(&kind),
            self.strategy.last_bar(kind.instrument_id()),
        ) {
            (None, None) => Ok(()),
            (Some(p), Some(s)) if p.to_record() == s.to_record() => Ok(()),
            _ => Err(bad()),
        }
    }
    pub fn capture_checkpoint(&mut self) -> StrategyResult<Value> {
        if self.failed {
            return Err(bad());
        }
        self.failed = true;
        let result=catch_unwind(AssertUnwindSafe(||{self.validate_cut()?;let pipeline=self.pipeline.capture_checkpoint().map_err(|_|bad())?;let strategy=self.strategy.capture_checkpoint()?;Ok(json!({"schema_version":1,"pipeline":pipeline,"strategy":strategy,"binding":{"pipeline":record_fingerprint(&pipeline),"strategy":record_fingerprint(&strategy)}}))})).unwrap_or(Err(bad()));
        if result.is_ok() {
            self.failed = false;
        }
        result
    }
    pub fn restore_checkpoint(&mut self, bytes: &[u8], expected: &str) -> StrategyResult<()> {
        if bytes.len() > 128 * 1024 * 1024 {
            return Err(bad());
        }
        let v: Value = serde_json::from_slice(bytes).map_err(|_| bad())?;
        if v.to_string().as_bytes() != bytes
            || record_fingerprint(&v) != expected
            || v.as_object().is_none_or(|m| m.len() != 4)
            || v["schema_version"] != 1
            || v["binding"]
                != json!({"pipeline":record_fingerprint(&v["pipeline"]),"strategy":record_fingerprint(&v["strategy"])})
        {
            return Err(bad());
        }
        let strategy = self.strategy.restored_candidate(
            v["strategy"].to_string().as_bytes(),
            &record_fingerprint(&v["strategy"]),
        )?;
        let mut pipeline = MarketDataPipeline::new(
            self.pipeline.program().clone(),
            NoCalculations,
            PreparedOnly {
                artifact: self.artifact.clone(),
            },
        )
        .map_err(|_| bad())?;
        pipeline
            .restore_checkpoint(
                v["pipeline"].to_string().as_bytes(),
                &record_fingerprint(&v["pipeline"]),
            )
            .map_err(|_| bad())?;
        let candidate = Self {
            pipeline,
            strategy,
            artifact: self.artifact.clone(),
            failed: false,
        };
        candidate.validate_cut()?;
        *self = candidate;
        Ok(())
    }
}
