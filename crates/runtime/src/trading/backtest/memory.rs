use super::{
    Inputs, NextOpenPolicy, err, hash, next_open::NativeExecution, verify_finite_backtest,
};
use crate::{CompletedSession, ResearchPanel, RunBinding, RunConfiguration, Session};
use onlyalpha_broker_virtual::CompletedMemoryVenue;
use onlyalpha_execution::Error;
use serde_json::{Value, json};

pub struct FrozenVenue {
    pub artifact: String,
    pub settings: Value,
    pub source: String,
}
#[derive(Clone, Debug)]
pub struct ExecutionBinding {
    record: Value,
    fingerprint: String,
}
impl ExecutionBinding {
    pub fn new(
        configuration: &RunConfiguration,
        settings: &Value,
        initial_ns: i64,
        cluster: &str,
        resolver: &Value,
        venue: &FrozenVenue,
        panel: &ResearchPanel,
    ) -> Result<Self, Error> {
        if initial_ns < 0
            || cluster.is_empty()
            || configuration.record()["runtime_kind"] != "BACKTEST"
            || configuration.record()["profiles"].get(cluster).is_none()
            || settings["execution"] != *configuration.record()
            || resolver["schema_version"] != 1
            || resolver["configuration"] != configuration.fingerprint()
            || resolver["reference_policy"] != "MODEL_NEXT_OPEN"
        {
            return Err(err("MEMORY_EXECUTION_BINDING"));
        }
        super::sha(&venue.artifact)?;
        super::sha(&venue.source)?;
        let matching = &venue.settings["matching"];
        if matching["type"] != "NEXT_OPEN_LONG_ONLY_V1"
            || matching["buy_multiplier"] != settings["policy"]["buy_multiplier"]
            || matching["sell_multiplier"] != settings["policy"]["sell_multiplier"]
        {
            return Err(err("MEMORY_VENUE_MODEL"));
        }
        let record = json!({"schema_version":1,"kind":"FINITE_BACKTEST","configuration":configuration.record(),"policy_settings":settings,"initial_ns":initial_ns.to_string(),"cluster":cluster,"resolver":resolver,"initial_signal_state":"GENESIS","venue":{"artifact":venue.artifact,"settings":venue.settings,"source":venue.source},"panel":{"snapshot":panel.snapshot(),"content":panel.content_digest(),"warmup":panel.warmup()}});
        if record.to_string().len() > 128 * 1024 * 1024 {
            return Err(err("MEMORY_BUDGET"));
        }
        Ok(Self {
            fingerprint: hash(&record),
            record,
        })
    }
    pub fn record(&self) -> &Value {
        &self.record
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
}
pub struct MemoryRunSpec {
    pub configuration: RunConfiguration,
    pub binding: RunBinding,
    pub policy_settings: Value,
    pub initial_ns: i64,
    pub cluster: String,
}
pub struct CompletedBacktest {
    execution_binding: ExecutionBinding,
    session: CompletedSession,
    venue: CompletedMemoryVenue,
    program: Value,
    signal_execution: String,
    signal_checkpoint: Value,
    raw_signals: Vec<Value>,
    signal_receipts: Vec<Value>,
    events: Vec<Value>,
    curve: Vec<Value>,
    baseline: Value,
    source_rows: usize,
}
impl CompletedBacktest {
    #[allow(clippy::too_many_arguments)]
    pub(super) fn verified(
        execution_binding: ExecutionBinding,
        session: CompletedSession,
        venue: CompletedMemoryVenue,
        program: Value,
        signal_checkpoint: Value,
        raw_signals: Vec<Value>,
        signal_receipts: Vec<Value>,
        events: Vec<Value>,
        mut curve: Vec<Value>,
        baseline: Value,
        inputs: &Inputs,
        policy: &dyn NextOpenPolicy,
    ) -> Result<Self, Error> {
        let mut points = session.equity_points().iter().peekable();
        let mut last = None;
        for marker in &mut curve {
            let prefix = marker["execution_prefix"]
                .as_u64()
                .ok_or_else(|| err("MEMORY_CLOSE_PREFIX"))?;
            while let Some(point) = points.peek() {
                if point["execution_prefix"]
                    .as_u64()
                    .ok_or_else(|| err("MEMORY_CLOSE_PREFIX"))?
                    > prefix
                {
                    break;
                }
                last = points.next();
            }
            let point = last.ok_or_else(|| err("MEMORY_CLOSE_POINT"))?;
            for key in ["nav", "high_water_mark", "drawdown", "account_sequence"] {
                marker[key] = point[key].clone();
            }
        }
        verify_finite_backtest(
            inputs,
            &execution_binding,
            policy,
            &program,
            &raw_signals,
            &signal_receipts,
            &signal_checkpoint,
            &events.iter().collect::<Vec<_>>(),
            &curve.iter().collect::<Vec<_>>(),
            session.economic_result(),
            session.equity_points(),
            &baseline,
            &venue,
            session.binding(),
        )?;
        Ok(Self {
            execution_binding,
            session,
            venue,
            program,
            signal_execution: hash(&signal_checkpoint),
            signal_checkpoint,
            raw_signals,
            signal_receipts,
            events,
            curve,
            baseline,
            source_rows: inputs.records().len(),
        })
    }
    pub fn venue(&self) -> &CompletedMemoryVenue {
        &self.venue
    }
    pub fn equity_points(&self) -> &[Value] {
        self.session.equity_points()
    }
    pub fn execution_binding(&self) -> &ExecutionBinding {
        &self.execution_binding
    }
    pub fn binding(&self) -> &RunBinding {
        self.session.binding()
    }
    pub fn program(&self) -> &Value {
        &self.program
    }
    pub fn signal_execution_fingerprint(&self) -> &str {
        &self.signal_execution
    }
    pub fn signal_checkpoint(&self) -> &Value {
        &self.signal_checkpoint
    }
    pub fn signal_receipts(&self) -> &[Value] {
        &self.signal_receipts
    }
    pub fn raw_signals(&self) -> &[Value] {
        &self.raw_signals
    }
    pub fn economic_result(&self) -> &Value {
        self.session.economic_result()
    }
    pub fn account_checkpoint(&self) -> &Value {
        self.session.account_checkpoint()
    }
    pub fn closed_cycle_count(&self) -> Result<usize, Error> {
        let state = self.session.state();
        let cluster = &self.execution_binding.record()["cluster"];
        let history = state["position"]["history"]
            .as_array()
            .ok_or_else(|| err("MEMORY_POSITION_HISTORY"))?;
        let allocations = self.economic_result()["final_allocations"]
            .as_array()
            .ok_or_else(|| err("MEMORY_POSITION_ALLOCATIONS"))?;
        let snapshots = history
            .iter()
            .filter(|entry| entry["owner"][0] == "CLUSTER" && entry["owner"][4] == *cluster)
            .chain(
                allocations
                    .iter()
                    .filter(|entry| entry["cluster"] == *cluster),
            );
        let mut cycles = std::collections::BTreeSet::new();
        for entry in snapshots {
            let snapshot = &entry["snapshot"];
            if snapshot["status"] == "CLOSED" {
                let id = snapshot["id"]
                    .as_str()
                    .ok_or_else(|| err("MEMORY_POSITION_ID"))?;
                let cycle = snapshot["cycle"]
                    .as_u64()
                    .ok_or_else(|| err("MEMORY_POSITION_CYCLE"))?;
                cycles.insert((id, cycle));
            }
        }
        Ok(cycles.len())
    }
    pub fn execution_facts(&self) -> &[Value] {
        &self.events
    }
    pub fn close_curve(&self) -> &[Value] {
        &self.curve
    }
    pub fn baseline(&self) -> &Value {
        &self.baseline
    }
    pub fn source_rows(&self) -> usize {
        self.source_rows
    }
}
impl NativeExecution for Session {
    fn position_order_view(&self) -> Result<Value, Error> {
        self.position_order_view()
    }
    fn sequence(&self) -> usize {
        self.sequence() as usize
    }
}
