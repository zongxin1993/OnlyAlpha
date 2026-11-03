use crate::{Error, Inputs, MarketInput, OpeningInput, boundary, err, hash};
use onlyalpha_clock::{BigInt, OnlyVirtualClock};
use onlyalpha_domain::{base::OnlyDomainModel, time::OnlyTimestamp};
use onlyalpha_execution::{CommitIntent, Components, Prepared, Record, Store, coordinate, recover};
use onlyalpha_runtime_persistence::{ReplayEntryRef, Runtime};
use serde_json::{Value, json};
use std::path::Path;
/// Application participant boundary: owning readers validate state; candidate effects have no external venue access.
pub trait Participants {
    fn binding(&self) -> Value;
    fn capture(&mut self) -> Result<Value, Error>;
    fn restore(&mut self, checkpoint: &Value) -> Result<(), Error>;
    fn process(&mut self, input: &MarketInput, execution: &mut Candidate) -> Result<Value, Error>;
    /// Two active driver profiles exist. The default preserves the closed-bar LIMIT profile.
    fn opening_phase(&self) -> bool {
        false
    }
    fn opening(&mut self, _: &OpeningInput, _: &mut Candidate) -> Result<Value, Error> {
        Err(err("OPENING_PROFILE_REQUIRED"))
    }
    fn end_input(&mut self, _: &mut Candidate) -> Result<Value, Error> {
        Err(err("OPENING_PROFILE_REQUIRED"))
    }
    /// Explicit prefix cancellation is available only to a participant that can drain it.
    fn cancel_input(&mut self, _: &mut Candidate) -> Result<Value, Error> {
        Err(err("OPENING_PROFILE_REQUIRED"))
    }
    /// Verify one fresh work binding before any durable Store is created or opened.
    fn validate_initial(&self, execution: &Candidate) -> Result<(), Error> {
        self.validate_execution(execution)
    }
    /// Read-only agreement between participant state and the exact canonical execution prefix.
    fn validate_execution(&self, _: &Candidate) -> Result<(), Error> {
        Ok(())
    }
    fn quiescent(&self) -> Result<bool, Error>;
}
#[derive(Clone)]
struct Memory {
    records: Vec<Record>,
}
impl Store for Memory {
    fn head(&self) -> Result<u64, Error> {
        Ok(self.records.len() as u64)
    }
    fn get(&self, n: u64) -> Result<Option<Record>, Error> {
        if n == 0 {
            return Err(err("SEQUENCE"));
        }
        Ok(self
            .records
            .get(usize::try_from(n - 1).map_err(|_| err("BOUND"))?)
            .map(Record::compact_snapshot))
    }
    fn commit(&mut self, i: &CommitIntent) -> Result<Record, Error> {
        let n = i.prepared().sequence();
        if let Some(r) = self.get(n)? {
            if r.prepared() != i.prepared() {
                return Err(err("CANDIDATE_CONFLICT"));
            }
            return Ok(r);
        }
        if n != self.head()? + 1 || self.records.last().is_some_and(|r| !r.ready()) {
            return Err(err("CANDIDATE_PREDECESSOR"));
        }
        let r = Record::new(i);
        self.records.push(r.clone());
        Ok(r)
    }
    fn mark_ready(&mut self, n: u64) -> Result<(), Error> {
        let i = usize::try_from(n.checked_sub(1).ok_or_else(|| err("SEQUENCE"))?)
            .map_err(|_| err("BOUND"))?;
        let r = self.records.get(i).ok_or_else(|| err("MISSING"))?;
        self.records[i] = r.observation_snapshot(true, r.delivered())?;
        Ok(())
    }
    fn acknowledge(&mut self, _: u64) -> Result<(), Error> {
        Err(err("CANDIDATE_CANNOT_DELIVER"))
    }
}
/// Rebuildable isolated Kernel preflight, never a durable writer or dispatch permission.
pub struct Candidate {
    components: Components,
    store: Memory,
    configuration: Value,
    plans: Vec<Prepared>,
}
impl Candidate {
    pub(crate) fn new(configuration: Value, records: Vec<Record>) -> Result<Self, Error> {
        let mut store = Memory { records };
        let mut components = Components::new(configuration.clone())?;
        recover(&mut store, &mut components)?;
        Ok(Self {
            components,
            store,
            configuration,
            plans: Vec::new(),
        })
    }
    fn from_runtime_head(runtime: &Runtime, configuration: Value) -> Result<Self, Error> {
        let (components, records) = runtime.fork_ready()?;
        if components.configuration() != &configuration {
            return Err(err("EXECUTION_CONTEXT"));
        }
        Ok(Self {
            components,
            store: Memory { records },
            configuration,
            plans: Vec::new(),
        })
    }
    pub fn apply(&mut self, input: &Value) -> Result<(), Error> {
        if self.plans.len() >= 512 {
            return Err(err("INPUTS"));
        }
        // Earlier plans keep their original canonical body and planner origin.
        // Only the last plan needs its optional typed acceleration state; drop
        // the previous copy before constructing another full candidate head.
        if let Some(previous) = self.plans.last_mut() {
            *previous = previous.compact_clone();
        }
        let p = self.components.prepare(&self.store, input)?;
        coordinate(&mut self.store, &mut self.components, &p)?;
        self.plans.push(p);
        Ok(())
    }
    pub fn state(&self) -> Result<Value, Error> {
        self.components.state(&self.store)
    }
    pub(crate) fn position_order_view(&self) -> Result<Value, Error> {
        self.components.position_order_view(&self.store)
    }
    pub fn checkpoint(&self) -> Result<Value, Error> {
        self.components.checkpoint()
    }
    pub fn fee_order_preview(
        &self,
        cluster: &str,
        request: &Value,
        at: u64,
    ) -> Result<Value, Error> {
        Ok(self
            .components
            .fee_order_preview(&self.store, cluster, request, at)?
            .to_record())
    }
    pub fn configuration(&self) -> &Value {
        &self.configuration
    }
    pub fn records(&self) -> &[Record] {
        &self.store.records
    }
    pub fn order(&self, cluster: &str, order: &str) -> Result<Value, Error> {
        Ok(self
            .components
            .order_snapshot(&self.store, cluster, order)?
            .to_record())
    }
}
// Original planner objects are local to one derive/install. Passive Records,
// serialized inputs and retained source expectations cannot construct them.
struct DerivedStep {
    record: Value,
    plans: Vec<Prepared>,
}
impl DerivedStep {
    fn verify_plans(&self) -> Result<(), Error> {
        let inputs = self.record["inputs"]
            .as_array()
            .ok_or_else(|| err("INPUTS"))?;
        let start = self.record["execution_start"]
            .as_u64()
            .ok_or_else(|| err("PREFIX"))?;
        if inputs.len() != self.plans.len() || inputs.len() > 512 {
            return Err(err("EXECUTION_PLAN_RELATION"));
        }
        for (index, (input, plan)) in inputs.iter().zip(&self.plans).enumerate() {
            let sequence = start
                .checked_add(index as u64)
                .and_then(|n| n.checked_add(1))
                .ok_or_else(|| err("BOUND"))?;
            if plan.sequence() != sequence || plan.input() != input {
                return Err(err("EXECUTION_PLAN_RELATION"));
            }
        }
        Ok(())
    }
}

// Historical rederivation never substitutes the current official head, even for an empty suffix.
enum DeriveSource {
    RuntimeHead,
    HistoricalPrefix(usize),
}

#[derive(Clone)]
pub struct RunSpec {
    pub work_id: String,
    pub configuration: Value,
    pub kernel_artifact: String,
    pub driver_artifact: String,
    pub initial_ns: BigInt,
}
pub struct RunLoop<P: Participants> {
    runtime: Runtime,
    spec: RunSpec,
    inputs: Inputs,
    participants: P,
    clock: OnlyVirtualClock,
    binding: Value,
    state: Value,
    // Expectations privately sealed by original derivation; never source proof.
    steps: Vec<ReplayEntryRef>,
    healthy: bool,
}
impl<P: Participants> RunLoop<P> {
    fn binding(spec: &RunSpec, inputs: &Inputs, p: &mut P) -> Result<(Value, Value), Error> {
        if spec.work_id.is_empty()
            || spec.work_id.len() > 256
            || spec.configuration["runtime_kind"] != "BACKTEST"
            || inputs
                .records()
                .first()
                .is_some_and(|i| i.event_ns() < spec.initial_ns)
        {
            return Err(err("WORK"));
        }
        let candidate = Candidate::new(spec.configuration.clone(), vec![])?;
        p.validate_initial(&candidate)?;
        crate::sha(&spec.kernel_artifact)?;
        crate::sha(&spec.driver_artifact)?;
        let program = p.binding();
        let strategies = spec.configuration["profiles"]
            .as_object()
            .ok_or_else(|| err("PROFILES"))?
            .iter()
            .map(|(k, v)| (k.clone(), v["revision"].clone()))
            .collect::<serde_json::Map<String, Value>>();
        let sources = inputs.record()["sources"]
            .as_array()
            .expect("sources")
            .iter()
            .map(|s| s["source"].clone())
            .collect::<Vec<_>>();
        if program["schema_version"] != 1
            || program["configuration"] != hash(&spec.configuration)
            || program["generation"] != spec.configuration["generation"]
            || program["initial_ns"] != spec.initial_ns.to_string()
            || program["strategies"] != Value::Object(strategies)
            || program["sources"] != json!(sources)
        {
            return Err(err("PARTICIPANT_CONTEXT"));
        }
        let mut state = json!({"schema_version":1,"cursor":0,"clock_ns":spec.initial_ns.to_string(),"status":"RUNNING","participants":p.capture()?,"outcome":null});
        if p.opening_phase() {
            if program["opening_profile"] != json!({"schema_version":1,"kind":"OPEN_CLOSE_V1"})
                || inputs
                    .records()
                    .first()
                    .is_some_and(|i| i.opening().event_ns() < spec.initial_ns)
                || inputs
                    .records()
                    .windows(2)
                    .any(|w| w[0].event_ns() > w[1].opening().event_ns())
            {
                return Err(err("OPENING_CONTEXT"));
            }
            state["phase"] = json!("OPEN");
            state["input_finished"] = json!(false);
        } else if !program["opening_profile"].is_null() {
            return Err(err("OPENING_PROFILE_CONFLICT"));
        }
        let mut binding = json!({"schema_version":1,"configuration":hash(&spec.configuration),"kernel_artifact":spec.kernel_artifact,"driver_artifact":spec.driver_artifact,"work":hash(&json!({"work_id":spec.work_id,"configuration":spec.configuration,"artifact":spec.kernel_artifact,"driver_artifact":spec.driver_artifact,"input_pin":inputs.fingerprint(),"participants":program,"initial_ns":spec.initial_ns.to_string()})),"input_pin":inputs.fingerprint(),"program":hash(&program),"initial_state":state});
        if p.opening_phase() {
            // Explicit new binding version. The original work hash is unchanged;
            // read-side owners no longer have to infer identity from a locator.
            binding["schema_version"] = json!(2);
            binding["work_id"] = json!(spec.work_id);
            binding["participants"] = program;
        }
        Ok((binding, state))
    }
    pub fn create(
        root: &Path,
        spec: RunSpec,
        inputs: Inputs,
        mut participants: P,
    ) -> Result<Self, Error> {
        let (binding, state) = Self::binding(&spec, &inputs, &mut participants)?;
        let mut runtime = Runtime::create(root, spec.configuration.clone(), &spec.kernel_artifact)?;
        runtime.bind_replay(&binding)?;
        Ok(Self {
            clock: OnlyVirtualClock::new(spec.initial_ns.clone()),
            runtime,
            spec,
            inputs,
            participants,
            binding,
            state,
            steps: vec![],
            healthy: true,
        })
    }
    pub fn open(
        root: &Path,
        spec: RunSpec,
        inputs: Inputs,
        mut participants: P,
    ) -> Result<Self, Error> {
        let (binding, state) = Self::binding(&spec, &inputs, &mut participants)?;
        let mut runtime = Runtime::open(root, spec.configuration.clone(), &spec.kernel_artifact)?;
        runtime.replay_refs()?; // Missing work is not permission to initialize another identity.
        runtime.bind_replay(&binding)?;
        let mut result = Self {
            clock: OnlyVirtualClock::new(spec.initial_ns.clone()),
            runtime,
            spec,
            inputs,
            participants,
            binding,
            state,
            steps: vec![],
            healthy: false,
        };
        result.recover()?;
        Ok(result)
    }
    fn check(&self) -> Result<(), Error> {
        if !self.healthy {
            return Err(err("RECOVERY_REQUIRED"));
        }
        // This one fresh cut includes the original full Execution/reconcile and
        // participant-state guard plus every actual encoded replay row.
        self.runtime.verify_replay_refs(&self.steps)
    }
    fn derive(
        &mut self,
        kind: &str,
        outcome: &Value,
        source: DeriveSource,
    ) -> Result<DerivedStep, Error> {
        let mut candidate = match source {
            DeriveSource::RuntimeHead => {
                Candidate::from_runtime_head(&self.runtime, self.spec.configuration.clone())?
            }
            DeriveSource::HistoricalPrefix(start) => {
                let records = self.runtime.records()?;
                let prefix = records
                    .get(..start)
                    .ok_or_else(|| err("EXECUTION_PREFIX"))?
                    .to_vec();
                Candidate::new(self.spec.configuration.clone(), prefix)?
            }
        };
        let start = candidate.records().len();
        self.participants.validate_execution(&candidate)?;
        let mut state = self.state.clone();
        let cursor = state["cursor"].as_u64().ok_or_else(|| err("CURSOR"))?;
        let processing = match kind {
            "OPEN" if self.participants.opening_phase() => {
                if state["status"] != "RUNNING"
                    || state["phase"] != "OPEN"
                    || state["input_finished"] != false
                {
                    return Err(err("OPENING_TRANSITION"));
                }
                let input = self
                    .inputs
                    .records()
                    .get(usize::try_from(cursor).map_err(|_| err("BOUND"))?)
                    .ok_or_else(|| err("INPUT_EXHAUSTED"))?
                    .opening();
                boundary(self.clock.advance_to(input.event_ns()))?;
                let output = self.participants.opening(&input, &mut candidate)?;
                state["phase"] = json!("CLOSE");
                json!({"input":input.record(),"processing":output})
            }
            "BAR" => {
                if state["status"] != "RUNNING"
                    || (self.participants.opening_phase()
                        && (state["phase"] != "CLOSE" || state["input_finished"] != false))
                {
                    return Err(err("NOT_RUNNING"));
                }
                let input = self
                    .inputs
                    .records()
                    .get(usize::try_from(cursor).map_err(|_| err("BOUND"))?)
                    .ok_or_else(|| err("INPUT_EXHAUSTED"))?;
                boundary(self.clock.advance_to(input.event_ns()))?;
                let output = self.participants.process(input, &mut candidate)?;
                state["cursor"] = json!(cursor + 1);
                if self.participants.opening_phase() {
                    state["phase"] = json!("OPEN");
                }
                json!({"input":input.record(),"processing":output})
            }
            "INPUT_END" if self.participants.opening_phase() => {
                if !matches!(state["status"].as_str(), Some("RUNNING" | "PAUSED"))
                    || cursor != self.inputs.records().len() as u64
                    || state["phase"] != "OPEN"
                    || state["input_finished"] != false
                {
                    return Err(err("INPUT_END_TRANSITION"));
                }
                let output = self.participants.end_input(&mut candidate)?;
                state["input_finished"] = json!(true);
                output
            }
            "CANCEL_INPUT" if self.participants.opening_phase() => {
                if !matches!(state["status"].as_str(), Some("RUNNING" | "PAUSED"))
                    || state["input_finished"] != false
                {
                    return Err(err("INPUT_CANCEL_TRANSITION"));
                }
                let output = self.participants.cancel_input(&mut candidate)?;
                state["input_finished"] = json!(true);
                // This field exists only on the new explicit cancellation cut;
                // retained INPUT_END states keep their exact original shape.
                state["input_cancelled"] = json!(true);
                output
            }
            "PAUSE" if state["status"] == "RUNNING" => {
                state["status"] = json!("PAUSED");
                Value::Null
            }
            "RESUME" if state["status"] == "PAUSED" => {
                state["status"] = json!("RUNNING");
                Value::Null
            }
            "TERMINATE" if state["status"] == "RUNNING" || state["status"] == "PAUSED" => {
                crate::fields(outcome, &["schema_version", "status", "reason"])?;
                if outcome["schema_version"] != 1 {
                    return Err(err("OUTCOME"));
                }
                let status = outcome["status"].as_str().ok_or_else(|| err("OUTCOME"))?;
                match status {
                    "COMPLETED" => {
                        if !outcome["reason"].is_null()
                            || state["input_cancelled"] == true
                            || cursor != self.inputs.records().len() as u64
                            || (self.participants.opening_phase()
                                && state["input_finished"] != true)
                            || !self.participants.quiescent()?
                        {
                            return Err(err("INCOMPLETE_PROOF"));
                        }
                    }
                    "FAILED" | "CANCELLED" | "INCOMPLETE" | "UNKNOWN" => {
                        if outcome["reason"]
                            .as_str()
                            .is_none_or(|r| r.is_empty() || r.len() > 256)
                        {
                            return Err(err("OUTCOME_REASON"));
                        }
                    }
                    _ => return Err(err("OUTCOME")),
                };
                state["status"] = json!("TERMINATED");
                state["outcome"] = outcome.clone();
                Value::Null
            }
            _ => return Err(err("TRANSITION")),
        };
        self.participants.validate_execution(&candidate)?;
        state["clock_ns"] = json!(boundary(self.clock.timestamp_ns())?.to_string());
        state["participants"] = self.participants.capture()?;
        let inputs = candidate.records()[start..]
            .iter()
            .map(|r| r.prepared().input().clone())
            .collect::<Vec<_>>();
        let previous = self.steps.last().map_or_else(
            || hash(&self.binding),
            |s| s.logical_fingerprint().to_owned(),
        );
        let derived = DerivedStep {
            record: json!({"schema_version":1,"index":self.steps.len()+1,"previous":previous,"execution_start":start,"cause":{"kind":kind,"outcome":outcome,"processing":processing},"inputs":inputs,"state":state}),
            plans: candidate.plans,
        };
        derived.verify_plans()?;
        Ok(derived)
    }
    fn install_observed(
        &mut self,
        mut derived: DerivedStep,
        original: &ReplayEntryRef,
        mut observer: Option<&mut dyn FnMut(&str, u64, u64) -> Result<(), Error>>,
    ) -> Result<(), Error> {
        derived.verify_plans()?;
        let step = &derived.record;
        let inputs = step["inputs"].as_array().ok_or_else(|| err("INPUTS"))?;
        let start = step["execution_start"]
            .as_u64()
            .ok_or_else(|| err("PREFIX"))?;
        let records = self.runtime.records()?;
        // Consume and release each original plan after matching or installing
        // it; no typed state is retained in the RunLoop or durable journal.
        for (index, plan) in derived.plans.drain(..).enumerate() {
            let n = start + index as u64;
            if let Some(old) = records.get(usize::try_from(n).map_err(|_| err("BOUND"))?) {
                if old.prepared() != &plan {
                    return Err(err("EXECUTION_RELATION"));
                }
            } else {
                self.runtime.apply_prepared(&plan)?;
            }
            drop(plan);
            if let Some(observer) = observer.as_mut() {
                observer(
                    "EXECUTION_READY",
                    step["index"].as_u64().expect("index"),
                    n + 1,
                )?;
            }
        }
        // Replay steps and all Execution facts/Ready flags are durable on
        // every step. Complete checkpoints are recovery optimizations; only
        // binding2 uses this fixed fact-count cadence. Controls seal the
        // actual head before their outward Ready boundary.
        let end = start
            .checked_add(u64::try_from(inputs.len()).map_err(|_| err("BOUND"))?)
            .ok_or_else(|| err("BOUND"))?;
        let force = matches!(
            step["cause"]["kind"].as_str(),
            Some("PAUSE" | "INPUT_END" | "CANCEL_INPUT" | "TERMINATE")
        );
        if self.binding["schema_version"] != 2 || force || start / 64 < end / 64 {
            self.runtime.save_checkpoint()?;
        }
        let completed = self.runtime.complete_replay_ref(&self.steps, original)?;
        if completed.last().is_none_or(|row| {
            !row.ready()
                || row.index() != original.index()
                || row.physical_fingerprint() != original.physical_fingerprint()
                || row.logical_fingerprint() != hash(step)
        }) {
            return Err(err("REPLAY_COMPLETION_SOURCE"));
        }
        self.state = step["state"].clone();
        self.steps = completed;
        if let Some(observer) = observer.as_mut() {
            observer(
                "STEP_READY",
                step["index"].as_u64().expect("index"),
                self.runtime.records()?.len() as u64,
            )?;
        }
        // The last observer is also an external source-taint boundary.
        // Keep recovery closed until its complete actual cut is rechecked.
        if observer.is_some() {
            self.runtime.verify_replay_refs(&self.steps)?;
        }
        Ok(())
    }
    fn transition(&mut self, kind: &str, outcome: Value) -> Result<(), Error> {
        self.check()?;
        self.transition_after_check(kind, outcome, None)
    }
    fn transition_observed(
        &mut self,
        kind: &str,
        outcome: Value,
        observer: &mut impl FnMut(&str, u64, u64) -> Result<(), Error>,
    ) -> Result<(), Error> {
        self.check()?;
        self.transition_after_check(kind, outcome, Some(observer))
    }
    // Only an entry point that has just called check() may enter here. There
    // is no observer or public call between that check and this continuation.
    fn transition_after_check(
        &mut self,
        kind: &str,
        outcome: Value,
        mut observer: Option<&mut dyn FnMut(&str, u64, u64) -> Result<(), Error>>,
    ) -> Result<(), Error> {
        if kind == "TERMINATE"
            && outcome["status"] == "COMPLETED"
            && !self.runtime.pending_events()?.is_empty()
        {
            return Err(err("EVENT_DRAIN_REQUIRED"));
        }
        self.healthy = false;
        let derived = self.derive(kind, &outcome, DeriveSource::RuntimeHead)?;
        let step = &derived.record;
        if let Some(observer) = observer.as_mut() {
            observer(
                "BEFORE_PREPARE",
                step["index"].as_u64().expect("index"),
                self.runtime.records()?.len() as u64,
            )?;
        }
        let original = self.runtime.prepare_replay_ref(&self.steps, step)?;
        if let Some(observer) = observer.as_mut() {
            observer(
                "PREPARED",
                step["index"].as_u64().expect("index"),
                self.runtime.records()?.len() as u64,
            )?;
        }
        self.install_observed(derived, &original, observer)?;
        self.healthy = true;
        Ok(())
    }
    pub fn step(&mut self) -> Result<bool, Error> {
        self.step_inner(None)
    }
    /// Immutable progress receipts also support deterministic crash barriers; errors require recovery.
    pub fn step_observed(
        &mut self,
        observer: &mut impl FnMut(&str, u64, u64) -> Result<(), Error>,
    ) -> Result<bool, Error> {
        self.step_inner(Some(observer))
    }
    fn step_inner(
        &mut self,
        observer: Option<&mut dyn FnMut(&str, u64, u64) -> Result<(), Error>>,
    ) -> Result<bool, Error> {
        self.check()?;
        if self.state["input_cancelled"] == true
            || self.state["cursor"] == self.inputs.records().len() as u64
        {
            return Ok(false);
        }
        let kind = if self.binding["schema_version"] == 2 && self.state["phase"] == "OPEN" {
            "OPEN"
        } else {
            "BAR"
        };
        self.transition_after_check(kind, Value::Null, observer)?;
        Ok(true)
    }
    pub fn run(&mut self) -> Result<(), Error> {
        while self.step()? {}
        Ok(())
    }
    /// Persist finite input processing separately from Event acknowledgement and completion.
    pub fn close_input(&mut self) -> Result<(), Error> {
        self.check()?;
        if !self.participants.opening_phase() {
            return Err(err("OPENING_PROFILE_REQUIRED"));
        }
        if self.state["input_cancelled"] == true {
            return Err(err("INPUT_CANCELLED"));
        }
        if self.state["input_finished"] == true {
            return Ok(());
        }
        self.transition("INPUT_END", Value::Null)
    }
    /// Durably stop the accepted prefix without consuming unobserved closed Bars.
    pub fn cancel_input(&mut self) -> Result<(), Error> {
        self.cancel_input_observed(&mut |_, _, _| Ok(()))
    }
    pub fn cancel_input_observed(
        &mut self,
        observer: &mut impl FnMut(&str, u64, u64) -> Result<(), Error>,
    ) -> Result<(), Error> {
        self.check()?;
        if !self.participants.opening_phase() {
            return Err(err("OPENING_PROFILE_REQUIRED"));
        }
        if self.state["input_cancelled"] == true {
            return Ok(());
        }
        if self.state["input_finished"] == true {
            return Err(err("INPUT_ALREADY_FINISHED"));
        }
        self.transition_observed("CANCEL_INPUT", Value::Null, observer)
    }
    /// Finalize exhausted input without inventing a Broker drain acknowledgement.
    pub fn finish_input(&mut self) -> Result<(), Error> {
        self.check()?;
        if self.state["cursor"] != self.inputs.records().len() as u64 {
            return Err(err("INPUT_NOT_EXHAUSTED"));
        }
        if self.participants.opening_phase() {
            self.close_input()?;
            if !self.runtime.pending_events()?.is_empty() {
                return Err(err("EVENT_DRAIN_REQUIRED"));
            }
        }
        if self.participants.quiescent()? && self.runtime.pending_events()?.is_empty() {
            self.terminate("COMPLETED", None)
        } else {
            self.terminate("INCOMPLETE", Some("INPUT_EXHAUSTED_BEFORE_DRAIN"))
        }
    }
    pub fn pause(&mut self) -> Result<(), Error> {
        self.transition("PAUSE", Value::Null)
    }
    pub fn resume(&mut self) -> Result<(), Error> {
        self.transition("RESUME", Value::Null)
    }
    pub fn terminate(&mut self, status: &str, reason: Option<&str>) -> Result<(), Error> {
        self.transition(
            "TERMINATE",
            json!({"schema_version":1,"status":status,"reason":reason}),
        )
    }
    /// Consumer acceptance must be real; uncertain/rejected delivery leaves the stable Event pending.
    pub fn deliver(
        &mut self,
        mut consumer: impl FnMut(&Value) -> Result<(), Error>,
    ) -> Result<usize, Error> {
        if !self.healthy {
            return Err(err("RECOVERY_REQUIRED"));
        }
        let events = self.runtime.pending_events_at_replay_refs(&self.steps)?;
        // No callback or write runs for an empty observation. Its one complete
        // current cut is sufficient; the next public call reads its own source.
        if events.is_empty() {
            return Ok(0);
        }
        let mut count = 0;
        for event in events {
            consumer(&event)?;
            self.runtime.acknowledge(
                event["sequence"]
                    .as_u64()
                    .ok_or_else(|| err("EVENT_SEQUENCE"))?,
            )?;
            count += 1;
        }
        // Preserve actual consumer acceptance and its original acknowledgement;
        // a failed final cut requires explicit recovery of this same session.
        if let Err(error) = self.check() {
            self.healthy = false;
            return Err(error);
        }
        Ok(count)
    }
    pub fn recover(&mut self) -> Result<(), Error> {
        self.healthy = false;
        self.runtime.recover()?;
        let stored = self.runtime.replay_refs()?;
        self.state = self.binding["initial_state"].clone();
        self.participants.restore(&self.state["participants"])?;
        self.clock = OnlyVirtualClock::new(self.spec.initial_ns.clone());
        self.steps.clear();
        for original in stored {
            // A ref names source data. Only the complete original derivation
            // below can install that expectation in this private history.
            let step = self.runtime.read_replay_step(&original)?;
            let kind = step["cause"]["kind"].as_str().ok_or_else(|| err("KIND"))?;
            let actual = self.derive(
                kind,
                &step["cause"]["outcome"],
                DeriveSource::HistoricalPrefix(
                    usize::try_from(original.execution_start()).map_err(|_| err("BOUND"))?,
                ),
            )?;
            if actual.record != step || hash(&actual.record) != original.logical_fingerprint() {
                return Err(err("PARTICIPANT_SOURCE_CONFLICT"));
            }
            if original.ready() {
                self.state = actual.record["state"].clone();
                self.steps.push(original);
            } else {
                // Only the original final pending proposal can be completed;
                // the full ready prefix and its original body are re-read by
                // the owner before and after Ready is changed.
                self.install_observed(actual, &original, None)?;
            }
        }
        self.healthy = true;
        self.check()
    }
    /// Complete logical Trace1, streamed in its original canonical key order.
    /// Output is not publishable until the final fresh cut succeeds.
    pub fn write_trace(&self, writer: &mut dyn std::io::Write) -> Result<(), Error> {
        self.check()?;
        crate::trace::logical(
            writer,
            &self.binding,
            &self.inputs.record(),
            &self.state,
            &self.steps,
            |reference| self.runtime.read_replay_step(reference),
        )?;
        self.check()
    }
    /// Visit complete original Steps without expanding the entire history.
    /// A callback observes data only; success requires the final fresh cut.
    pub fn for_each_step(
        &self,
        visit: &mut dyn FnMut(&Value, bool) -> Result<(), Error>,
    ) -> Result<(), Error> {
        self.check()?;
        for reference in &self.steps {
            let step = self.runtime.read_replay_step(reference)?;
            visit(&step, reference.ready())?;
        }
        self.check()
    }
    pub fn trace_fingerprint(&self) -> Result<String, Error> {
        crate::trace::fingerprint(|writer| self.write_trace(writer))
    }
    /// Full actual storage representation. No mutable path descriptor is emitted.
    pub fn write_encoded_trace(&self, writer: &mut dyn std::io::Write) -> Result<(), Error> {
        self.check()?;
        match self.runtime.storage_version() {
            2 => crate::trace::bounded(writer, |writer| self.write_trace(writer))?,
            3 | 4 => crate::trace::encoded(
                writer,
                &self.binding,
                &self.inputs.record(),
                &self.state,
                &self.steps,
                |reference, writer| self.runtime.write_encoded_step(reference, writer),
            )?,
            _ => return Err(err("TRACE_STORAGE_VERSION")),
        }
        self.check()
    }
    pub fn encoded_trace(&self) -> Result<Value, Error> {
        crate::trace::value(|writer| self.write_encoded_trace(writer))
    }
    /// Read-only display fields; this is not the complete Trace or a proof.
    pub fn trace_metadata(&self) -> Result<Value, Error> {
        self.check()?;
        Ok(json!({"binding":self.binding,"inputs":self.inputs.record(),"state":self.state}))
    }
    /// Explicit bounded diagnostic expansion. Production Result/Evidence never
    /// calls this whole-history Value API.
    pub fn trace(&self) -> Result<Value, Error> {
        crate::trace::value(|writer| self.write_trace(writer))
    }
    pub fn progress(&self) -> Result<Value, Error> {
        self.check()?;
        Ok(
            json!({"schema_version":1,"work_id":self.spec.work_id,"binding":hash(&self.binding),"cursor":self.state["cursor"],"total":self.inputs.records().len(),"status":self.state["status"],"outcome":self.state["outcome"]}),
        )
    }
    pub fn state(&self) -> Result<Value, Error> {
        self.check()?;
        self.runtime.state()
    }
    pub fn result(&self) -> Result<Value, Error> {
        self.check()?;
        if self.state["status"] != "TERMINATED" {
            return Err(err("NOT_TERMINATED"));
        }
        let outcome = &self.state["outcome"];
        let completed = outcome["status"] == "COMPLETED";
        let broker_drained = self.participants.quiescent()?;
        let events_drained = self.runtime.pending_events()?.is_empty();
        if completed && !(broker_drained && events_drained) {
            return Err(err("DRAIN_REQUIRED"));
        }
        let final_ns: BigInt = boundary(
            self.state["clock_ns"]
                .as_str()
                .ok_or_else(|| err("CLOCK"))?
                .parse(),
        )?;
        let manifest = json!({"schema_version":1,"configuration":hash(&self.spec.configuration),"kernel_artifact":self.spec.kernel_artifact,"input_pin":self.inputs.fingerprint(),"initial_time":OnlyTimestamp::from_unix_nanos(self.spec.initial_ns.clone()).to_record(),"final_time":OnlyTimestamp::from_unix_nanos(final_ns).to_record(),"inputs":self.runtime.records()?.iter().map(|r|hash(r.prepared().input())).collect::<Vec<_>>()});
        let result = self.runtime.backtest_result(&manifest, outcome)?.record();
        let proof = json!({"schema_version":1,"completion_scope":"BACKTEST_REPLAY","binding":hash(&self.binding),"market_exhausted":self.state["cursor"]==self.inputs.records().len() as u64,"processed_prefix_verified":true,"drained":events_drained&&broker_drained,"status":result["run"]["status"],"source":self.trace_fingerprint()?,"outcome":outcome,"execution_result":result});
        Ok(proof)
    }
}

#[cfg(all(test, target_os = "linux"))]
#[path = "candidate_configuration_tests.rs"]
mod configuration_tests;
