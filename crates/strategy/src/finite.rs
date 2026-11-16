//! Shared signal execution and finite, unpublished mathematical completion.
use crate::{Executor, NodePort, Outcome, StrategyError, StrategyResult, model::*};
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use serde_json::{Value, json};
pub struct SignalExecution<C: NodePort> {
    executor: Executor<C>,
    calculations: Value,
}
impl<C: NodePort> SignalExecution<C> {
    pub fn new(executor: Executor<C>) -> Self {
        Self {
            executor,
            calculations: Value::Null,
        }
    }
    pub fn program(&self) -> &crate::Program {
        self.executor.program()
    }
    pub fn is_failed(&self) -> bool {
        self.executor.is_failed()
    }
    pub fn calculations(&self) -> &Value {
        &self.calculations
    }
    /// Final actual producer/cursor agreement, performed once at completion.
    pub fn finish_barrier(&mut self) -> StrategyResult<Value> {
        self.executor.capture_checkpoint()
    }
    /// Both finite Research and event-driven trading call this exact owner;
    /// account, position, risk and execution data are absent from its inputs.
    pub fn process(&mut self, bar: &OnlyBar) -> StrategyResult<Outcome> {
        let parent = record_fingerprint(
            &json!({"source":self.program().source(),"observation":observation_record(bar)}),
        );
        let time = OnlyTimestamp::from_datetime(*bar.ts_init());
        let outcome = self.executor.process(bar, &time, &parent)?;
        let record = outcome.to_record();
        let mut values = Vec::new();
        for trace in record["trace"].as_array().ok_or_else(bad)? {
            let id = text(&trace["node_fingerprint"])?;
            let key = self.program().instance_scope(bar.instrument_id(), id);
            let outputs = if matches!(trace["status"].as_str(), Some("READY" | "WARMING")) {
                self.executor
                    .states
                    .get(&key)
                    .ok_or_else(bad)?
                    .snapshot()
                    .outputs()
                    .cloned()
                    .unwrap_or(Value::Null)
            } else {
                Value::Null
            };
            values.push(json!({"node_fingerprint":id,"status":trace["status"],"outputs":outputs}));
        }
        self.calculations = json!(values);
        Ok(outcome)
    }
}
pub struct ResearchRun<C: NodePort> {
    signal: SignalExecution<C>,
    inputs: Vec<OnlyBar>,
    cursor: usize,
    signals: Vec<Value>,
    calculations: Vec<Value>,
    bytes: usize,
    failed: bool,
}
/// Actual signal/graph completion, not Target/statistics completion or permission
/// to publish a scientific result. Backend must add its remaining owned members
/// and positive child join before constructing a publication candidate.
/// ```compile_fail
/// let forged = onlyalpha_strategy::CompletedResearch { signals:vec![] };
/// ```
#[derive(Debug)]
pub struct CompletedResearch {
    program: Value,
    inputs: String,
    signals: Vec<Value>,
    calculations: Vec<Value>,
    execution_fingerprint: String,
}
impl CompletedResearch {
    pub fn program(&self) -> &Value {
        &self.program
    }
    pub fn input_fingerprint(&self) -> &str {
        &self.inputs
    }
    pub fn signals(&self) -> &[Value] {
        &self.signals
    }
    pub fn calculations(&self) -> &[Value] {
        &self.calculations
    }
    pub fn execution_fingerprint(&self) -> &str {
        &self.execution_fingerprint
    }
}
impl<C: NodePort> ResearchRun<C> {
    pub fn new(mut executor: Executor<C>, inputs: Vec<OnlyBar>) -> StrategyResult<Self> {
        executor.require_genesis()?;
        if inputs.is_empty() || inputs.len() > 1_000_000 {
            return Err(StrategyError("RESEARCH_INPUT_BUDGET"));
        }
        let bytes = inputs
            .iter()
            .try_fold(0usize, |n, b| {
                n.checked_add(b.to_record().to_string().len())
            })
            .filter(|n| *n <= 128 * 1024 * 1024)
            .ok_or(StrategyError("RESEARCH_INPUT_BUDGET"))?;
        Ok(Self {
            signal: SignalExecution::new(executor),
            inputs,
            cursor: 0,
            signals: Vec::new(),
            calculations: Vec::new(),
            bytes,
            failed: false,
        })
    }
    pub fn step(&mut self) -> StrategyResult<()> {
        if self.failed || self.cursor >= self.inputs.len() {
            return Err(StrategyError("RESEARCH_NOT_RUNNING"));
        }
        self.failed = true;
        self.signals
            .try_reserve(1)
            .map_err(|_| StrategyError("RESEARCH_INPUT_BUDGET"))?;
        self.calculations
            .try_reserve(1)
            .map_err(|_| StrategyError("RESEARCH_INPUT_BUDGET"))?;
        let outcome = self.signal.process(&self.inputs[self.cursor])?.to_record();
        let calculations = self.signal.calculations().clone();
        self.bytes = self
            .bytes
            .checked_add(outcome.to_string().len())
            .and_then(|n| n.checked_add(calculations.to_string().len()))
            .filter(|n| *n <= 128 * 1024 * 1024)
            .ok_or(StrategyError("RESEARCH_INPUT_BUDGET"))?;
        self.signals.push(outcome);
        self.calculations.push(calculations);
        self.cursor += 1;
        self.failed = false;
        Ok(())
    }
    pub fn run(mut self) -> StrategyResult<CompletedResearch> {
        while self.cursor < self.inputs.len() {
            self.step()?;
        }
        self.finish()
    }
    pub fn finish(mut self) -> StrategyResult<CompletedResearch> {
        if self.failed
            || self.signal.is_failed()
            || self.cursor != self.inputs.len()
            || self.signals.len() != self.inputs.len()
            || self.calculations.len() != self.inputs.len()
        {
            return Err(StrategyError("RESEARCH_INCOMPLETE"));
        }
        let execution_fingerprint = record_fingerprint(&self.signal.finish_barrier()?);
        Ok(CompletedResearch {
            program: self.signal.program().to_record(),
            inputs: record_fingerprint(&json!(
                self.inputs
                    .iter()
                    .map(OnlyDomainModel::to_record)
                    .collect::<Vec<_>>()
            )),
            signals: self.signals,
            calculations: self.calculations,
            execution_fingerprint,
        })
    }
}
