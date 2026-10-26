use crate::{Error, Inputs, MarketInput, boundary, err, hash};
use onlyalpha_clock::{BigInt, OnlyVirtualClock};
use onlyalpha_domain::{base::OnlyDomainModel, time::OnlyTimestamp};
use onlyalpha_execution::{CommitIntent, Components, Record, Store, coordinate, recover};
use onlyalpha_runtime_persistence::Runtime;
use serde_json::{Value, json};
use std::path::Path;
/// Application participant boundary: owning readers validate state; candidate effects have no external venue access.
pub trait Participants {
    fn binding(&self) -> Value;
    fn capture(&mut self) -> Result<Value, Error>;
    fn restore(&mut self, checkpoint: &Value) -> Result<(), Error>;
    fn process(&mut self, input: &MarketInput, execution: &mut Candidate) -> Result<Value, Error>;
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
            .cloned())
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
        let mut v = r.record();
        v["ready"] = json!(true);
        self.records[i] = Record::decode(&v)?;
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
        })
    }
    pub fn apply(&mut self, input: &Value) -> Result<(), Error> {
        let p = self.components.prepare(&self.store, input)?;
        coordinate(&mut self.store, &mut self.components, &p)
    }
    pub fn state(&self) -> Result<Value, Error> {
        self.components.state(&self.store)
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
    steps: Vec<Value>,
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
        Candidate::new(spec.configuration.clone(), vec![])?;
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
        let state = json!({"schema_version":1,"cursor":0,"clock_ns":spec.initial_ns.to_string(),"status":"RUNNING","participants":p.capture()?,"outcome":null});
        let binding = json!({"schema_version":1,"configuration":hash(&spec.configuration),"kernel_artifact":spec.kernel_artifact,"driver_artifact":spec.driver_artifact,"work":hash(&json!({"work_id":spec.work_id,"configuration":spec.configuration,"artifact":spec.kernel_artifact,"driver_artifact":spec.driver_artifact,"input_pin":inputs.fingerprint(),"participants":program,"initial_ns":spec.initial_ns.to_string()})),"input_pin":inputs.fingerprint(),"program":hash(&program),"initial_state":state});
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
        runtime.replay_steps()?; // Missing work is not permission to initialize another identity.
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
        if !self.healthy || self.runtime.replay_steps()? != self.steps {
            return Err(err("RECOVERY_REQUIRED"));
        }
        self.runtime.state()?;
        Ok(())
    }
    fn derive(&mut self, kind: &str, outcome: &Value, start: usize) -> Result<Value, Error> {
        let records = self.runtime.records()?;
        let prefix = records
            .get(..start)
            .ok_or_else(|| err("EXECUTION_PREFIX"))?
            .to_vec();
        let mut candidate = Candidate::new(self.spec.configuration.clone(), prefix)?;
        let mut state = self.state.clone();
        let cursor = state["cursor"].as_u64().ok_or_else(|| err("CURSOR"))?;
        let processing = match kind {
            "BAR" => {
                if state["status"] != "RUNNING" {
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
                json!({"input":input.record(),"processing":output})
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
                            || cursor != self.inputs.records().len() as u64
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
        state["clock_ns"] = json!(boundary(self.clock.timestamp_ns())?.to_string());
        state["participants"] = self.participants.capture()?;
        let inputs = candidate.records()[start..]
            .iter()
            .map(|r| r.prepared().input().clone())
            .collect::<Vec<_>>();
        let previous = self
            .steps
            .last()
            .map_or_else(|| hash(&self.binding), |s| hash(&s["step"]));
        Ok(
            json!({"schema_version":1,"index":self.steps.len()+1,"previous":previous,"execution_start":start,"cause":{"kind":kind,"outcome":outcome,"processing":processing},"inputs":inputs,"state":state}),
        )
    }
    fn install_observed(
        &mut self,
        step: &Value,
        observer: &mut impl FnMut(&str, u64, u64) -> Result<(), Error>,
    ) -> Result<(), Error> {
        let inputs = step["inputs"].as_array().ok_or_else(|| err("INPUTS"))?;
        let start = step["execution_start"]
            .as_u64()
            .ok_or_else(|| err("PREFIX"))?;
        let records = self.runtime.records()?;
        for (index, input) in inputs.iter().enumerate() {
            let n = start + index as u64;
            if let Some(old) = records.get(usize::try_from(n).map_err(|_| err("BOUND"))?) {
                if old.prepared().input() != input {
                    return Err(err("EXECUTION_RELATION"));
                }
            } else {
                self.runtime.apply(input)?;
            }
            observer(
                "EXECUTION_READY",
                step["index"].as_u64().expect("index"),
                n + 1,
            )?;
        }
        self.runtime.save_checkpoint()?;
        self.runtime
            .complete_replay(step["index"].as_u64().ok_or_else(|| err("INDEX"))?)?;
        self.state = step["state"].clone();
        self.steps = self.runtime.replay_steps()?;
        observer(
            "STEP_READY",
            step["index"].as_u64().expect("index"),
            self.runtime.records()?.len() as u64,
        )?;
        Ok(())
    }
    fn transition(&mut self, kind: &str, outcome: Value) -> Result<(), Error> {
        self.transition_observed(kind, outcome, &mut |_, _, _| Ok(()))
    }
    fn transition_observed(
        &mut self,
        kind: &str,
        outcome: Value,
        observer: &mut impl FnMut(&str, u64, u64) -> Result<(), Error>,
    ) -> Result<(), Error> {
        self.check()?;
        if kind == "TERMINATE"
            && outcome["status"] == "COMPLETED"
            && !self.runtime.pending_events()?.is_empty()
        {
            return Err(err("EVENT_DRAIN_REQUIRED"));
        }
        self.healthy = false;
        let step = self.derive(kind, &outcome, self.runtime.records()?.len())?;
        observer(
            "BEFORE_PREPARE",
            step["index"].as_u64().expect("index"),
            self.runtime.records()?.len() as u64,
        )?;
        self.runtime.prepare_replay(&step)?;
        observer(
            "PREPARED",
            step["index"].as_u64().expect("index"),
            self.runtime.records()?.len() as u64,
        )?;
        self.install_observed(&step, observer)?;
        self.healthy = true;
        Ok(())
    }
    pub fn step(&mut self) -> Result<bool, Error> {
        self.step_observed(&mut |_, _, _| Ok(()))
    }
    /// Immutable progress receipts also support deterministic crash barriers; errors require recovery.
    pub fn step_observed(
        &mut self,
        observer: &mut impl FnMut(&str, u64, u64) -> Result<(), Error>,
    ) -> Result<bool, Error> {
        self.check()?;
        if self.state["cursor"] == self.inputs.records().len() as u64 {
            return Ok(false);
        }
        self.transition_observed("BAR", Value::Null, observer)?;
        Ok(true)
    }
    pub fn run(&mut self) -> Result<(), Error> {
        while self.step()? {}
        Ok(())
    }
    /// Finalize exhausted input without inventing a Broker drain acknowledgement.
    pub fn finish_input(&mut self) -> Result<(), Error> {
        self.check()?;
        if self.state["cursor"] != self.inputs.records().len() as u64 {
            return Err(err("INPUT_NOT_EXHAUSTED"));
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
        self.check()?;
        let events = self.runtime.pending_events()?;
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
        Ok(count)
    }
    pub fn recover(&mut self) -> Result<(), Error> {
        self.healthy = false;
        self.runtime.recover()?;
        let stored = self.runtime.replay_steps()?;
        self.state = self.binding["initial_state"].clone();
        self.participants.restore(&self.state["participants"])?;
        self.clock = OnlyVirtualClock::new(self.spec.initial_ns.clone());
        self.steps.clear();
        for row in stored {
            let step = &row["step"];
            let kind = step["cause"]["kind"].as_str().ok_or_else(|| err("KIND"))?;
            let actual = self.derive(
                kind,
                &step["cause"]["outcome"],
                usize::try_from(
                    step["execution_start"]
                        .as_u64()
                        .ok_or_else(|| err("PREFIX"))?,
                )
                .map_err(|_| err("BOUND"))?,
            )?;
            if actual != *step {
                return Err(err("PARTICIPANT_SOURCE_CONFLICT"));
            }
            self.state = actual["state"].clone();
            self.steps.push(row);
        }
        if let Some(last) = self.steps.last().cloned()
            && last["ready"] == false
        {
            self.install_observed(&last["step"], &mut |_, _, _| Ok(()))?;
        }
        self.healthy = true;
        self.check()
    }
    pub fn trace(&self) -> Result<Value, Error> {
        self.check()?;
        Ok(
            json!({"schema_version":1,"binding":self.binding,"inputs":self.inputs.record(),"steps":self.steps,"state":self.state}),
        )
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
        let proof = json!({"schema_version":1,"completion_scope":"BACKTEST_REPLAY","binding":hash(&self.binding),"market_exhausted":self.state["cursor"]==self.inputs.records().len() as u64,"processed_prefix_verified":true,"drained":events_drained&&broker_drained,"status":result["run"]["status"],"source":hash(&self.trace()?),"outcome":outcome,"execution_result":result});
        Ok(proof)
    }
}
