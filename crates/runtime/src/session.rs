//! Finite in-memory work; losing it requires deterministic recomputation.
//! None of these observations is a durable receipt or external dispatch permit.
use onlyalpha_execution::{
    CompletedWorkingState, Components, Error, WorkingState, WorkingStep, digest,
};
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc};
fn error(code: &str) -> Error {
    Error(code.into())
}
pub(crate) fn fingerprint(v: &Value) -> String {
    digest(v.to_string().as_bytes())
}
pub(crate) fn sha(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}
#[derive(Clone, Debug)]
pub struct RunConfiguration {
    value: Value,
    fingerprint: String,
}
impl RunConfiguration {
    pub fn from_record(value: Value) -> Result<Self, Error> {
        Components::new(value.clone())?;
        Ok(Self {
            fingerprint: fingerprint(&value),
            value,
        })
    }
    pub fn record(&self) -> &Value {
        &self.value
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
}
/// Explicit calculation pins. Value construction authenticates no asset,
/// Source permission, product Run, or publication; the backend owns those checks.
#[derive(Clone, Debug)]
pub struct RunBinding {
    value: Value,
    fingerprint: String,
}
impl RunBinding {
    pub fn new(
        configuration: &RunConfiguration,
        kernel_artifact: &str,
        input_pin: &str,
        signal_program: &str,
    ) -> Result<Self, Error> {
        if ![kernel_artifact, input_pin, signal_program]
            .into_iter()
            .all(sha)
        {
            return Err(error("MEMORY_BINDING_INVALID"));
        }
        let value = json!({"schema_version":1,"configuration":configuration.fingerprint(),"kernel_artifact":kernel_artifact,"input_pin":input_pin,"signal_program":signal_program});
        Ok(Self {
            fingerprint: fingerprint(&value),
            value,
        })
    }
    /// A declared driver pin only. The execution owner must compare its actual
    /// complete driver content; this grants no admission or dispatch capability.
    pub fn with_execution_fingerprint(mut self, execution: &str) -> Result<Self, Error> {
        if !sha(execution) {
            return Err(error("MEMORY_BINDING_INVALID"));
        }
        self.value["execution"] = json!(execution);
        self.fingerprint = fingerprint(&self.value);
        Ok(self)
    }
    pub fn record(&self) -> &Value {
        &self.value
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
}
#[derive(Clone, Debug)]
pub struct TradingInput {
    value: Value,
}
impl TradingInput {
    pub fn from_record(value: Value) -> Result<Self, Error> {
        if value.to_string().len() > 65536
            || value["schema_version"] != 1
            || !matches!(
                value["op"].as_str(),
                Some(
                    "ADMIT"
                        | "SUBMISSION"
                        | "ACCEPT"
                        | "CANCEL"
                        | "FILL"
                        | "VALUATION"
                        | "SETTLEMENT_MATURITY"
                        | "TERMINAL"
                        | "MARK"
                        | "FUNDING"
                )
            )
        {
            return Err(error("MEMORY_INPUT_INVALID"));
        }
        Ok(Self { value })
    }
    pub fn record(&self) -> &Value {
        &self.value
    }
}
/// Actual advancement observation; no decoder or public constructor.
#[derive(Clone, Debug)]
pub struct AppliedEvent {
    step: WorkingStep,
}
impl AppliedEvent {
    pub fn sequence(&self) -> u64 {
        self.step.sequence()
    }
    pub fn input(&self) -> &Value {
        self.step.input()
    }
    pub fn record(&self) -> Value {
        json!({"schema_version":1,"sequence":self.sequence(),"transaction":format!("ETX-{}",fingerprint(self.input())),"input":self.input()})
    }
}
pub struct Session {
    configuration: RunConfiguration,
    binding: RunBinding,
    state: WorkingState,
    facts: Vec<Arc<AppliedEvent>>,
    identities: BTreeMap<String, usize>,
    broker_facts: BTreeMap<String, usize>,
    acknowledged: usize,
    encoded_bytes: usize,
    healthy: bool,
}
/// Complete unpublished economic work. It does not establish market exhaustion
/// or child join; the Backtest and backend execution owners add those barriers.
/// ```compile_fail
/// let forged = onlyalpha_runtime::CompletedSession { facts: vec![] };
/// ```
pub struct CompletedSession {
    binding: RunBinding,
    state: CompletedWorkingState,
    facts: Vec<Arc<AppliedEvent>>,
}
impl CompletedSession {
    pub fn binding(&self) -> &RunBinding {
        &self.binding
    }
    pub fn state(&self) -> &Value {
        self.state.state()
    }
    pub fn economic_result(&self) -> &Value {
        self.state.result()
    }
    pub fn account_checkpoint(&self) -> &Value {
        self.state.account_checkpoint()
    }
    pub fn equity_points(&self) -> &[Value] {
        self.state.equity_points()
    }
    pub fn facts(&self) -> &[Arc<AppliedEvent>] {
        &self.facts
    }
}
impl Session {
    pub fn new(configuration: &RunConfiguration, binding: &RunBinding) -> Result<Self, Error> {
        if binding.record()["configuration"] != configuration.fingerprint() {
            return Err(error("MEMORY_BINDING_MISMATCH"));
        }
        Ok(Self {
            configuration: configuration.clone(),
            binding: binding.clone(),
            state: WorkingState::for_run(configuration.record().clone(), binding.fingerprint())?,
            facts: Vec::new(),
            identities: BTreeMap::new(),
            broker_facts: BTreeMap::new(),
            acknowledged: 0,
            encoded_bytes: 0,
            healthy: true,
        })
    }
    fn ready(&self) -> Result<(), Error> {
        if self.healthy {
            Ok(())
        } else {
            Err(error("MEMORY_SESSION_FAILED"))
        }
    }
    pub fn configuration(&self) -> &RunConfiguration {
        &self.configuration
    }
    pub fn binding(&self) -> &RunBinding {
        &self.binding
    }
    pub fn sequence(&self) -> u64 {
        self.state.sequence()
    }
    pub fn apply(&mut self, input: &TradingInput) -> Result<Arc<AppliedEvent>, Error> {
        if input.record().get("broker_record").is_some() {
            return Err(error("MEMORY_ORIGINAL_VENUE_REQUIRED"));
        }
        let operation = if input.record()["op"] == "ADMIT" {
            "memory.admission"
        } else {
            "memory.apply"
        };
        onlyalpha_observability::measure_counted(
            "runtime",
            operation,
            onlyalpha_observability::Correlation::default(),
            1,
            0,
            || self.apply_inner(input, None),
        )
    }
    pub(crate) fn apply_cash_venue(
        &mut self,
        input: &TradingInput,
        observed: &onlyalpha_broker::ObservedFact,
    ) -> Result<Arc<AppliedEvent>, Error> {
        let fact = observed.fact();
        self.finite_scope(&fact.scope())
            .map_err(|e| Error(e.to_string()))?;
        let original = fact.record();
        let value = input.record();
        if self.configuration.record()["schema_version"] == 3
            || value.get("broker_record") != Some(&original)
            || value["payload"]["order"] != original["payload"]["order"]
            || value["time"] != original["ts_event"]
            || !matches!(
                (value["op"].as_str(), original["kind"].as_str()),
                (Some("ACCEPT"), Some("ACCEPTED")) | (Some("FILL"), Some("TRADE"))
            )
        {
            return Err(error("MEMORY_ORIGINAL_VENUE_MISMATCH"));
        }
        if let Some(&index) = self.broker_facts.get(fact.identity()) {
            let prior = &self.facts[index];
            if prior.input() != value {
                return Err(error("MEMORY_INPUT_CONFLICT"));
            }
            return Ok(Arc::clone(prior));
        }
        let evidence = self.state.check_cash_observation(value, observed)?;
        let applied = self.apply_inner(input, Some(evidence))?;
        self.broker_facts
            .insert(fact.identity().into(), applied.sequence() as usize - 1);
        Ok(applied)
    }
    pub fn apply_original(
        &mut self,
        input: &TradingInput,
        cut: &onlyalpha_execution::MarketSourceCut,
        broker: &onlyalpha_broker::MemoryBroker,
        source: Option<&onlyalpha_broker::source::SourceHistory>,
    ) -> Result<Arc<AppliedEvent>, Error> {
        self.ready()?;
        self.healthy = false;
        let evidence = self
            .state
            .check_original_input(input.record(), cut, broker, source)?;
        self.healthy = true;
        self.apply_inner(input, Some(evidence))
    }
    fn apply_inner(
        &mut self,
        input: &TradingInput,
        evidence: Option<onlyalpha_execution::OriginalEvidence>,
    ) -> Result<Arc<AppliedEvent>, Error> {
        self.ready()?;
        self.healthy = false;
        if evidence.is_none() {
            self.state.check_plain_input(input.record())?;
        }
        let id = input.record()["input_id"]
            .as_str()
            .filter(|s| !s.is_empty())
            .ok_or_else(|| error("MEMORY_INPUT_INVALID"))?;
        if let Some(&index) = self.identities.get(id) {
            let original = &self.facts[index];
            if original.input() != input.record() {
                return Err(error("MEMORY_INPUT_CONFLICT"));
            }
            self.healthy = true;
            return Ok(Arc::clone(original));
        }
        let size = input.record().to_string().len();
        let next = self
            .encoded_bytes
            .checked_add(size)
            .filter(|n| *n <= 128 * 1024 * 1024)
            .ok_or_else(|| error("MEMORY_BUDGET_EXCEEDED"))?;
        if self.facts.len() >= 1_000_000 {
            return Err(error("MEMORY_BUDGET_EXCEEDED"));
        }
        self.facts
            .try_reserve(1)
            .map_err(|_| error("MEMORY_BUDGET_EXCEEDED"))?;
        let applied = if let Some(evidence) = evidence {
            self.state.apply_verified(input.record(), evidence)
        } else {
            self.state.apply(input.record())
        };
        let step = match applied {
            Ok(step) => step,
            Err(e)
                if matches!(
                    e.0.as_str(),
                    "EXECUTION_RISK_DENIED" | "EXECUTION_ACCOUNT_CAPACITY_DENIED"
                ) =>
            {
                self.healthy = true;
                return Err(e);
            }
            Err(e) => return Err(e),
        };
        let event = Arc::new(AppliedEvent { step });
        self.identities.insert(id.into(), self.facts.len());
        if let Some(fact) = input.record()["payload"]["broker"]["id"].as_str() {
            self.broker_facts
                .entry(fact.into())
                .or_insert(self.facts.len());
        }
        self.facts.push(Arc::clone(&event));
        self.encoded_bytes = next;
        self.healthy = true;
        Ok(event)
    }
    pub fn state(&self) -> Result<Value, Error> {
        self.ready()?;
        self.state.state()
    }
    pub fn account_snapshot(&self) -> Result<Value, Error> {
        self.ready()?;
        self.state.account_snapshot()
    }
    pub fn position_order_view(&self) -> Result<Value, Error> {
        self.ready()?;
        self.state.position_order_view()
    }
    pub fn order(&self, cluster: &str, order: &str) -> Result<Value, Error> {
        self.ready()?;
        self.state.order(cluster, order)
    }
    pub fn fee_order_preview(
        &self,
        cluster: &str,
        request: &Value,
        at: u64,
    ) -> Result<Value, Error> {
        self.ready()?;
        self.state.fee_order_preview(cluster, request, at)
    }
    pub fn retained_facts(&self) -> &[Arc<AppliedEvent>] {
        &self.facts
    }
    pub fn pending_events(&self) -> Result<&[Arc<AppliedEvent>], Error> {
        self.ready()?;
        Ok(&self.facts[self.acknowledged..])
    }
    pub fn acknowledge(&mut self, sequence: u64) -> Result<(), Error> {
        self.ready()?;
        let sequence = usize::try_from(sequence).map_err(|_| error("MEMORY_EVENT_SEQUENCE"))?;
        if sequence == 0 || sequence > self.facts.len() || sequence > self.acknowledged + 1 {
            return Err(error("MEMORY_EVENT_SEQUENCE"));
        }
        self.acknowledged = self.acknowledged.max(sequence);
        Ok(())
    }
    pub fn finish(self) -> Result<CompletedSession, Error> {
        let final_ns = self
            .facts
            .last()
            .map_or(Some(0), |f| f.input()["time"].as_i64())
            .ok_or_else(|| error("RESULT_INPUT_TIME"))?;
        self.finish_between(0, final_ns)
    }
    pub fn finish_between(self, initial_ns: i64, final_ns: i64) -> Result<CompletedSession, Error> {
        self.ready()?;
        if self.acknowledged != self.facts.len() {
            return Err(error("MEMORY_EVENTS_NOT_DRAINED"));
        }
        let inputs = self
            .facts
            .iter()
            .map(|f| f.input().clone())
            .collect::<Vec<_>>();
        let state = self
            .state
            .finish(&inputs, self.binding.record(), initial_ns, final_ns)?;
        Ok(CompletedSession {
            binding: self.binding,
            state,
            facts: self.facts,
        })
    }
}

fn broker_error(_: impl std::fmt::Display) -> onlyalpha_broker::Error {
    onlyalpha_broker::Error::new("FINITE_ORIGINAL_EVIDENCE_UNAVAILABLE")
}
impl Session {
    fn finite_scope(&self, scope: &onlyalpha_broker::Scope) -> Result<(), onlyalpha_broker::Error> {
        self.ready().map_err(broker_error)?;
        let cfg = self.configuration.record();
        let raw = scope.record();
        if cfg["runtime_kind"] != "BACKTEST"
            || [
                "engine",
                "runtime",
                "account",
                "gateway",
                "generation",
                "runtime_kind",
            ]
            .iter()
            .any(|k| raw[*k] != cfg[*k])
        {
            return Err(broker_error("scope"));
        }
        Ok(())
    }
    fn finite_order(
        &self,
        command: &onlyalpha_broker::BrokerCommand,
    ) -> Result<(Arc<onlyalpha_execution::MemoryAdmission>, Value), onlyalpha_broker::Error> {
        self.finite_scope(command.scope())?;
        let admission = self
            .state
            .admission(command.order())
            .map_err(broker_error)?;
        let input = admission.input();
        let cluster = input["cluster"]
            .as_str()
            .ok_or_else(|| broker_error("cluster"))?;
        let order = self
            .state
            .order(cluster, command.order())
            .map_err(broker_error)?;
        if input["payload"]["request"] != command.record()["request"]
            || order["client_order_id"]["value"] != command.client()
        {
            return Err(broker_error("order"));
        }
        Ok((admission, order))
    }
}
impl onlyalpha_broker::FiniteRuntimeReader for Session {
    fn simulation_intent(
        &self,
        command: &onlyalpha_broker::BrokerCommand,
    ) -> Result<onlyalpha_broker::SimulationIntent, onlyalpha_broker::Error> {
        let (admission, order) = self.finite_order(command)?;
        let cluster = admission.input()["cluster"]
            .as_str()
            .ok_or_else(|| broker_error("cluster"))?;
        if command.operation() != onlyalpha_broker::Operation::Submit
            || order["status"] != "SUBMITTED"
            || self
                .state
                .order_submission(cluster, command.order())
                .map_err(broker_error)?
                != "DISPATCHING"
        {
            return Err(broker_error("submission"));
        }
        onlyalpha_broker::SimulationIntent::new(
            command.clone(),
            admission.transaction().into(),
            admission.payload_fingerprint().into(),
            &admission.input()["time"],
        )
    }
    fn simulation_receipt(
        &self,
        fact: &onlyalpha_broker::Fact,
    ) -> Result<Option<onlyalpha_broker::ApplicationReceipt>, onlyalpha_broker::Error> {
        self.finite_scope(&fact.scope())?;
        let Some(index) = self.broker_facts.get(fact.identity()) else {
            return Ok(None);
        };
        let event = &self.facts[*index];
        let input = event.input();
        let matches = if let Some(record) = input.get("broker_record") {
            record == &fact.record()
        } else {
            let original = &input["payload"]["broker"];
            original["record"] == fact.record() && original["fingerprint"] == fact.fingerprint()
        };
        if !matches {
            return Err(broker_error("original"));
        }
        onlyalpha_broker::ApplicationReceipt::new(
            fact,
            format!("ETX-{}", fingerprint(event.input())),
            event.step.payload_fingerprint().into(),
            onlyalpha_broker::ApplicationStatus::Applied,
        )
        .map(Some)
    }
    fn simulation_order(
        &self,
        command: &onlyalpha_broker::BrokerCommand,
    ) -> Result<Option<onlyalpha_broker::OrderView>, onlyalpha_broker::Error> {
        let (admission, order) = self.finite_order(command)?;
        if order["venue_order_id"].is_null() {
            return Ok(None);
        }
        onlyalpha_broker::OrderView::decode(&json!({"scope":command.scope().record(),"order":order["order_id"]["value"],"client":order["client_order_id"]["value"],"venue":order["venue_order_id"]["value"],"request":admission.input()["payload"]["request"],"filled":order["filled_quantity"]["value"],"status":order["status"]})).map(Some)
    }
}
