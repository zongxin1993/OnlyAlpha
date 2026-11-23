//! Shared signal execution and finite, unpublished mathematical completion.
use crate::{
    Executor, NodePort, Outcome, StrategyError, StrategyResult,
    execution::{
        Accepted, check_external_inputs, check_observation, dependencies_blocked, identity,
        initial_chain, node_request, outcome_record, trace_record,
    },
    model::*,
    recovery::{MAX_CHECKPOINT, check_native_node, checkpoint_header, native_nodes},
};
use onlyalpha_calculation::CalculationState;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use serde_json::{Value, json};
use std::collections::BTreeMap;

fn signal_parent(program: &Program, bar: &OnlyBar) -> String {
    record_fingerprint(&json!({"source":program.source(),"observation":observation_record(bar)}))
}

pub struct SignalExecution<C: NodePort> {
    executor: Executor<C>,
    calculations: Value,
    receipts: Value,
}
impl<C: NodePort> SignalExecution<C> {
    pub fn new(executor: Executor<C>) -> Self {
        Self {
            executor,
            calculations: Value::Null,
            receipts: Value::Null,
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
    /// 原始 Calculation 回执按最近一次成功输入的 trace 排列，BLOCKED 位置为 null。
    pub fn receipts(&self) -> &Value {
        &self.receipts
    }
    /// Final actual producer/cursor agreement, performed once at completion.
    pub fn finish_barrier(&mut self) -> StrategyResult<Value> {
        self.executor.capture_checkpoint()
    }
    /// Both finite Research and event-driven trading call this exact owner;
    /// account, position, risk and execution data are absent from its inputs.
    pub fn process(&mut self, bar: &OnlyBar) -> StrategyResult<Outcome> {
        let parent = signal_parent(self.program(), bar);
        let time = OnlyTimestamp::from_datetime(*bar.ts_init());
        let outcome = self.executor.process(bar, &time, &parent)?;
        let mut values = Vec::new();
        let mut receipts = Vec::new();
        for trace in array(&outcome.record["trace"])? {
            let id = text(&trace["node_fingerprint"])?;
            let key = self.program().instance_scope(bar.instrument_id(), id);
            let receipt = if matches!(trace["status"].as_str(), Some("READY" | "WARMING")) {
                self.executor.states.get(&key).ok_or_else(bad)?.capture()["receipt"].take()
            } else {
                Value::Null
            };
            values.push(json!({"node_fingerprint":id,"status":trace["status"],"outputs":receipt["outputs"]}));
            receipts.push(receipt);
        }
        self.calculations = Value::Array(values);
        self.receipts = Value::Array(receipts);
        Ok(outcome)
    }
}
impl Program {
    /// 核对调用方已绑定的冻结行情、逐行决策、Calculation 回执和末尾检查点。
    pub fn verify_finite_completion<'a>(
        &self,
        bars: impl IntoIterator<Item = &'a OnlyBar>,
        outcomes: &[Value],
        receipts: &[Value],
        checkpoint: &Value,
    ) -> StrategyResult<()> {
        if outcomes.is_empty()
            || outcomes.len() > 1_000_000
            || outcomes.len() != receipts.len()
            || checkpoint["schema_version"] != 2
            || checkpoint.to_string().len() > MAX_CHECKPOINT
        {
            return Err(bad());
        }
        checkpoint_header(self, checkpoint)?;
        let nodes: Vec<_> = self
            .revision
            .graph
            .ordered_nodes()
            .into_iter()
            .map(|definition| (definition.fingerprint(), definition.to_record()))
            .collect();
        let mut states: BTreeMap<_, _> = self
            .bindings
            .iter()
            .map(|(scope, binding)| (scope, CalculationState::new(binding.clone())))
            .collect();
        let mut requests = BTreeMap::new();
        let mut commitments = BTreeMap::new();
        let mut accepted = BTreeMap::<String, Accepted>::new();
        let mut chain = initial_chain(self);
        let mut last: Option<&OnlyBar> = None;
        let mut bars = bars.into_iter();
        for (outcome, receipts) in outcomes.iter().zip(receipts) {
            let bar = bars.next().ok_or_else(bad)?;
            let init = OnlyTimestamp::from_datetime(*bar.ts_init());
            check_observation(self, bar, &init)?;
            check_external_inputs(self, bar)?;
            let instrument = bar.instrument_id().to_string();
            let previous = accepted.get(&instrument);
            if last.is_some_and(|last| {
                last.bar_end() > bar.bar_end() || last.ts_init() > bar.ts_init()
            }) || previous.is_some_and(|previous| previous.bar.bar_end() >= bar.bar_end())
            {
                return Err(bad());
            }
            let receipts = array(receipts)?;
            let trace = array(&outcome["trace"])?;
            if receipts.len() != nodes.len() || trace.len() != nodes.len() {
                return Err(bad());
            }
            let time = OnlyTimestamp::from_datetime(*bar.bar_end())
                .unix_nanos()
                .to_string();
            let mut calls = Vec::new();
            let mut ready = BTreeMap::new();
            let mut outputs = BTreeMap::new();
            let mut checked_trace = Vec::with_capacity(nodes.len());
            for ((node, definition), (receipt, entry)) in
                nodes.iter().zip(receipts.iter().zip(trace))
            {
                if dependencies_blocked(definition, &ready)? {
                    if !receipt.is_null() {
                        return Err(bad());
                    }
                    ready.insert(node.clone(), false);
                    checked_trace.push(trace_record(node, None));
                    continue;
                }
                let scope = self.instance_scope(bar.instrument_id(), node);
                let state = states.get_mut(&scope).ok_or_else(bad)?;
                let request = node_request(state, bar, definition, &outputs)?;
                let prepared = state
                    .prepare(&[&time], &request.input_digest)
                    .map_err(|_| bad())?;
                let values = typed_values(&receipt["outputs"], &definition["outputs"])?;
                if values != receipt["outputs"] {
                    return Err(bad());
                }
                state.commit(&prepared, receipt).map_err(|_| bad())?;
                let commitment = sha(&entry["state_fingerprint"])?;
                let is_ready = receipt["ready"].as_bool().ok_or_else(bad)?;
                checked_trace.push(trace_record(node, Some((receipt, commitment, is_ready))));
                ready.insert(node.clone(), is_ready);
                outputs.insert(node.clone(), values);
                requests.insert(scope.clone(), request.input_record());
                commitments.insert(scope.clone(), commitment);
                calls.push(scope);
            }
            let parent = signal_parent(self, bar);
            let next = identity(self, &chain, bar, &init, &parent);
            let verified = outcome_record(self, bar, &next, &parent, checked_trace, &outputs)?;
            if verified.record != *outcome {
                return Err(bad());
            }
            let count = previous.map_or(1, |previous| previous.count + 1);
            accepted.insert(
                instrument,
                Accepted {
                    bar: bar.clone(),
                    init,
                    parent,
                    previous: chain,
                    count,
                    outcome: verified,
                    calls,
                },
            );
            chain = next;
            last = Some(bar);
        }
        if bars.next().is_some()
            || checkpoint["processed"] != json!(outcomes.len())
            || checkpoint["chain"] != chain
            || checkpoint["last_init_ns"]
                != json!(last.map(|bar| {
                    OnlyTimestamp::from_datetime(*bar.ts_init())
                        .unix_nanos()
                        .to_string()
                }))
            || checkpoint["accepted"]
                != json!(
                    accepted
                        .iter()
                        .map(|(instrument, row)| row.to_record(instrument))
                        .collect::<Vec<_>>()
                )
            || checkpoint["requests"]
                != json!(
                    requests
                        .iter()
                        .map(|(scope, row)| json!([scope, row]))
                        .collect::<Vec<_>>()
                )
            || checkpoint["commitments"]
                != json!(
                    commitments
                        .iter()
                        .map(|(scope, digest)| json!([scope, digest]))
                        .collect::<Vec<_>>()
                )
        {
            return Err(bad());
        }
        let native = native_nodes(&checkpoint["port"])?;
        let captures = array(&checkpoint["states"])?;
        if native.len() != states.len() || captures.len() != states.len() {
            return Err(bad());
        }
        for ((scope, state), row) in states.into_iter().zip(captures) {
            let captured = state.capture();
            if *row != json!([scope, captured]) {
                return Err(bad());
            }
            let node = native.get(scope).ok_or_else(bad)?;
            let descriptor = &self.revision.descriptors[&state.cursor().binding().digests()[2]];
            check_native_node(descriptor, &state, &captured, node)?;
            if let Some(commitment) = commitments.get(scope)
                && node["state_fingerprint"] != *commitment
            {
                return Err(bad());
            }
        }
        Ok(())
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
