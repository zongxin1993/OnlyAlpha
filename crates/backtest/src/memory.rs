//! Finite native execution over immutable in-memory inputs. No persistence or
//! official dispatch capability is created by this driver.
use crate::{
    Error, Inputs, NextOpenPolicy, boundary, err, hash,
    next_open::{NativeExecution, NativeReplay},
};
use onlyalpha_domain::{base::OnlyDomainModel, time::OnlyTimestamp};
use onlyalpha_runtime::{CompletedSession, RunBinding, RunConfiguration, Session, TradingInput};
use onlyalpha_strategy::{Executor, NodePort, SignalExecution};
use serde_json::{Value, json};

/// Exact pure driver content, not a product admission. The backend must still
/// compare these original values with its frozen owning facts.
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
        let record = json!({"schema_version":1,"kind":"FINITE_BACKTEST","configuration":configuration.record(),"policy_settings":settings,"initial_ns":initial_ns.to_string(),"cluster":cluster,"resolver":resolver,"initial_signal_state":"GENESIS"});
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
pub struct BacktestRun<C: NodePort> {
    execution_binding: ExecutionBinding,
    spec: MemoryRunSpec,
    inputs: Inputs,
    signal: SignalExecution<C>,
    runtime: Session,
    native: NativeReplay,
    driver_binding: Value,
    cursor: usize,
    raw_signals: Vec<Value>,
    events: Vec<Value>,
    closes: Vec<Value>,
    sample_start: i64,
    sample_end: i64,
    encoded_bytes: usize,
    failed: bool,
    cancelled: bool,
}
/// Actual market exhaustion, signal-owner verification, model/event drain and
/// economic completion. Backend must still verify its original frozen job,
/// permissions and actual task join before PG publication.
/// ```compile_fail
/// let forged=onlyalpha_backtest::CompletedBacktest { source_rows:1 };
/// ```
pub struct CompletedBacktest {
    execution_binding: ExecutionBinding,
    session: CompletedSession,
    program: Value,
    signal_execution: String,
    raw_signals: Vec<Value>,
    events: Vec<Value>,
    curve: Vec<Value>,
    baseline: Value,
    source_rows: usize,
}
impl CompletedBacktest {
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
    pub fn raw_signals(&self) -> &[Value] {
        &self.raw_signals
    }
    pub fn economic_result(&self) -> &Value {
        self.session.economic_result()
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
    fn configuration(&self) -> &Value {
        self.configuration().record()
    }
    fn state(&self) -> Result<Value, Error> {
        self.state()
    }
    fn position_order_view(&self) -> Result<Value, Error> {
        self.position_order_view()
    }
    fn sequence(&self) -> usize {
        self.sequence() as usize
    }
    fn order(&self, cluster: &str, order: &str) -> Result<Value, Error> {
        self.order(cluster, order)
    }
    fn fee_order_preview(&self, cluster: &str, request: &Value, at: u64) -> Result<Value, Error> {
        self.fee_order_preview(cluster, request, at)
    }
    fn apply(&mut self, input: &Value) -> Result<(), Error> {
        self.apply(&TradingInput::from_record(input.clone())?)
            .map(|_| ())
    }
}
fn bar_time(input: &crate::MarketInput, start: bool) -> Result<i64, Error> {
    OnlyTimestamp::from_datetime(if start {
        *input.bar().bar_start()
    } else {
        *input.bar().bar_end()
    })
    .unix_nanos()
    .try_into()
    .map_err(|_| err("MEMORY_INPUT_TIME"))
}
impl<C: NodePort> BacktestRun<C> {
    pub fn new(
        spec: MemoryRunSpec,
        inputs: Inputs,
        mut executor: Executor<C>,
        policy: Box<dyn NextOpenPolicy>,
    ) -> Result<Self, Error> {
        boundary(executor.require_genesis())?;
        let execution_binding = ExecutionBinding::new(
            &spec.configuration,
            &spec.policy_settings,
            spec.initial_ns,
            &spec.cluster,
            &policy.binding(),
        )?;
        if spec.binding.record()["execution"] != execution_binding.fingerprint() {
            return Err(err("MEMORY_EXECUTION_BINDING"));
        }

        let configuration = spec.configuration.record();
        let program = executor.program();
        let mut encoded_bytes = 0usize;
        for input in inputs.records() {
            encoded_bytes = encoded_bytes
                .checked_add(input.record().to_string().len())
                .filter(|n| *n <= 128 * 1024 * 1024)
                .ok_or_else(|| err("MEMORY_BUDGET"))?;
        }
        let start = spec.policy_settings["policy"]["start_ns"]
            .as_str()
            .and_then(|s| s.parse::<i64>().ok())
            .ok_or_else(|| err("MEMORY_SAMPLE_WINDOW"))?;
        let end = spec.policy_settings["policy"]["end_ns"]
            .as_str()
            .and_then(|s| s.parse::<i64>().ok())
            .ok_or_else(|| err("MEMORY_SAMPLE_WINDOW"))?;
        if inputs.records().is_empty()
            || spec.initial_ns < 0
            || start < spec.initial_ns
            || start >= end
            || spec.binding.record()["input_pin"] != inputs.fingerprint()
            || spec.binding.record()["signal_program"] != program.fingerprint()
            || spec.policy_settings["execution"] != *configuration
            || configuration["runtime_kind"] != "BACKTEST"
            || program.generation()
                != configuration["generation"]
                    .as_str()
                    .ok_or_else(|| err("MEMORY_PROGRAM_BINDING"))?
            || program.scope().engine.value() != configuration["engine"]
            || program.scope().runtime.value() != configuration["runtime"]
            || program.scope().cluster.value() != spec.cluster
            || configuration["profiles"][&spec.cluster]["revision"]
                != program.revision().fingerprint()
            || program.revision().universe().len() != 1
        {
            return Err(err("MEMORY_PROGRAM_BINDING"));
        }
        let mut sample = 0usize;
        for input in inputs.records() {
            let at = bar_time(input, true)?;
            if input.source() != program.source()
                || input.bar().instrument_id() != &program.revision().universe()[0]
                || input.bar().bar_type().semantic() != program.revision().semantic()
                || at < spec.initial_ns
                || bar_time(input, false)? > end
            {
                return Err(err("MEMORY_INPUT_BINDING"));
            }
            if at >= start && at < end {
                sample += 1;
            }
        }
        if sample == 0 {
            return Err(err("MEMORY_SAMPLE_WINDOW"));
        }
        let native = NativeReplay::new(
            &spec.policy_settings,
            policy,
            spec.initial_ns.into(),
            &spec.cluster,
        )?;
        let mut actual_resolver = native.binding();
        actual_resolver
            .as_object_mut()
            .ok_or_else(|| err("MEMORY_EXECUTION_BINDING"))?
            .remove("execution_model");
        if actual_resolver != execution_binding.record()["resolver"] {
            return Err(err("MEMORY_EXECUTION_BINDING"));
        }
        let runtime = Session::new(&spec.configuration, &spec.binding)?;
        let driver_binding = json!({"policy":spec.policy_settings,"program":{"scope":{"cluster":spec.cluster},"revision":{"strategy_fingerprint":program.revision().fingerprint()}},"opening_profile":{"schema_version":1,"kind":"OPEN_CLOSE_V1"}});
        Ok(Self {
            execution_binding,
            spec,
            inputs,
            signal: SignalExecution::new(executor),
            runtime,
            native,
            driver_binding,
            cursor: 0,
            raw_signals: Vec::new(),
            events: Vec::new(),
            closes: Vec::new(),
            sample_start: start,
            sample_end: end,
            encoded_bytes,
            failed: false,
            cancelled: false,
        })
    }
    fn charge(&mut self, value: &Value) -> Result<(), Error> {
        self.encoded_bytes = self
            .encoded_bytes
            .checked_add(value.to_string().len())
            .filter(|n| *n <= 128 * 1024 * 1024)
            .ok_or_else(|| err("MEMORY_BUDGET"))?;
        Ok(())
    }
    fn event(&mut self, family: &str, body: Value) -> Result<(), Error> {
        let value =
            json!({"schema_version":1,"sequence":self.events.len()+1,"family":family,"body":body});
        self.charge(&value)?;
        self.events
            .try_reserve(1)
            .map_err(|_| err("MEMORY_BUDGET"))?;
        self.events.push(value);
        Ok(())
    }
    fn drain(&mut self) -> Result<(), Error> {
        let pending = self.runtime.pending_events()?.to_vec();
        for event in pending {
            self.event("EXECUTION", event.record())?;
            self.runtime.acknowledge(event.sequence())?;
        }
        Ok(())
    }
    pub fn step(&mut self) -> Result<(), Error> {
        if self.failed || self.cancelled || self.cursor >= self.inputs.records().len() {
            self.failed = true;
            return Err(err("MEMORY_NOT_RUNNING"));
        }
        self.failed = true;
        let input = self.inputs.records()[self.cursor].clone();
        self.native.validate_execution(&self.runtime)?;
        let opening = self.native.opening(&input.opening(), &mut self.runtime)?;
        self.drain()?;
        self.event("OPEN", opening)?;
        let signal = boundary(self.signal.process(input.bar()))?.to_record();
        self.charge(&signal)?;
        self.raw_signals
            .try_reserve(1)
            .map_err(|_| err("MEMORY_BUDGET"))?;
        self.raw_signals.push(signal.clone());
        let context = crate::next_open::context(
            &input.identity(),
            input.event_ns(),
            &input.bar().to_record()["trading_day"],
        )?;
        let at = u64::try_from(bar_time(&input, false)?).map_err(|_| err("MEMORY_INPUT_TIME"))?;
        if let Some(mark) = crate::trading::valuation_input(
            &self.driver_binding,
            &input,
            at,
            &self.runtime,
            context["day_index"].clone(),
        )? {
            self.runtime.apply(&TradingInput::from_record(mark)?)?;
        }
        self.drain()?;
        let decision = self
            .native
            .closed(&input, &json!({"decisions":[signal]}), &self.runtime)?;
        self.event("BAR",json!({"input_identity":input.identity(),"source_sequence":input.sequence(),"raw_signal":signal,"policy":decision}))?;
        let start = bar_time(&input, true)?;
        if start >= self.sample_start && start < self.sample_end {
            let marker = json!({"bar_start_ns":start.to_string(),"bar_end_ns":bar_time(&input,false)?.to_string(),"execution_prefix":self.runtime.sequence()});
            self.charge(&marker)?;
            self.closes
                .try_reserve(1)
                .map_err(|_| err("MEMORY_BUDGET"))?;
            self.closes.push(marker);
        }
        self.cursor += 1;
        self.failed = false;
        Ok(())
    }
    /// Compact retained records and encoded payload size, excluding allocator overhead.
    /// These observations never participate in business identity or completion.
    pub fn retained_counts(&self) -> (usize, usize, usize, usize, usize) {
        (
            self.inputs.records().len(),
            self.raw_signals.len(),
            self.events.len(),
            self.closes.len(),
            self.runtime.retained_facts().len(),
        )
    }
    pub fn retained_payload_bytes(&self) -> usize {
        self.encoded_bytes
    }
    pub fn cancel(&mut self) {
        self.cancelled = true;
    }
    pub fn run(mut self) -> Result<CompletedBacktest, Error> {
        while self.cursor < self.inputs.records().len() {
            self.step()?;
        }
        self.finish()
    }
    pub fn finish(mut self) -> Result<CompletedBacktest, Error> {
        if self.failed
            || self.cancelled
            || self.cursor != self.inputs.records().len()
            || self.raw_signals.len() != self.cursor
        {
            return Err(err("MEMORY_INCOMPLETE"));
        }
        let signal_execution = hash(&boundary(self.signal.finish_barrier())?);
        self.native.validate_execution(&self.runtime)?;
        let end = self.native.end_input(&mut self.runtime)?;
        self.drain()?;
        self.event("END", end)?;
        if !self.native.quiescent()? || !self.runtime.pending_events()?.is_empty() {
            return Err(err("MEMORY_NOT_DRAINED"));
        }
        let first = self
            .inputs
            .records()
            .iter()
            .find(|i| {
                bar_time(i, true).is_ok_and(|n| n >= self.sample_start && n < self.sample_end)
            })
            .ok_or_else(|| err("MEMORY_SAMPLE_WINDOW"))?;
        let last = self
            .inputs
            .records()
            .iter()
            .rev()
            .find(|i| {
                bar_time(i, true).is_ok_and(|n| n >= self.sample_start && n < self.sample_end)
            })
            .ok_or_else(|| err("MEMORY_SAMPLE_WINDOW"))?;
        let baseline = self.native.analytical_baseline(first, last)?;
        let session = self
            .runtime
            .finish_between(self.spec.initial_ns, self.sample_end)?;
        let points = session.equity_points();
        let mut at = 0usize;
        for marker in &mut self.closes {
            let prefix = marker["execution_prefix"]
                .as_u64()
                .ok_or_else(|| err("MEMORY_CLOSE_PREFIX"))?;
            while at + 1 < points.len()
                && points[at + 1]["execution_prefix"]
                    .as_u64()
                    .is_some_and(|n| n <= prefix)
            {
                at += 1;
            }
            let point = points.get(at).ok_or_else(|| err("MEMORY_CLOSE_POINT"))?;
            if point["execution_prefix"]
                .as_u64()
                .is_none_or(|n| n > prefix)
            {
                return Err(err("MEMORY_CLOSE_PREFIX"));
            }
            for key in ["nav", "high_water_mark", "drawdown", "account_sequence"] {
                marker[key] = point[key].clone();
            }
        }
        Ok(CompletedBacktest {
            execution_binding: self.execution_binding,
            session,
            program: self.signal.program().to_record(),
            signal_execution,
            raw_signals: self.raw_signals,
            events: self.events,
            curve: self.closes,
            baseline,
            source_rows: self.cursor,
        })
    }
}
