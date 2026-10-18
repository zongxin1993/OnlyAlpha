use crate::model::*;
use onlyalpha_calculation::{CalculationState, StateOutcome};
use onlyalpha_domain::{
    base::OnlyDomainModel, identifiers::OnlyInstrumentId, market::OnlyBar, time::OnlyTimestamp,
};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    panic::{AssertUnwindSafe, catch_unwind},
};
#[derive(Clone)]
pub(crate) struct Accepted {
    pub bar: OnlyBar,
    pub init: OnlyTimestamp,
    pub parent: String,
    pub previous: String,
    pub count: u64,
    pub outcome: Outcome,
    pub calls: Vec<String>,
}
pub struct Executor<C: NodePort> {
    pub(crate) program: Program,
    pub(crate) port: C,
    pub(crate) states: BTreeMap<String, CalculationState>,
    pub(crate) requests: BTreeMap<String, Value>,
    pub(crate) commitments: BTreeMap<String, String>,
    pub(crate) accepted: BTreeMap<String, Accepted>,
    pub(crate) failed: bool,
    pub(crate) processed: u64,
    pub(crate) chain: String,
    pub(crate) last_init: Option<OnlyTimestamp>,
}
pub(crate) fn initial_chain(p: &Program) -> String {
    record_fingerprint(
        &json!({"schema_version":1,"program":p.fingerprint(),"initial_state":"EMPTY"}),
    )
}
pub(crate) fn same_bindings<C: NodePort>(p: &Program, c: &C) -> StrategyResult<()> {
    let bs = c.bindings();
    if bs.len() != p.bindings.len()
        || bs
            .into_iter()
            .map(|b| (b.scope().to_owned(), b))
            .collect::<BTreeMap<_, _>>()
            != p.bindings
    {
        return Err(bad());
    }
    Ok(())
}
pub(crate) fn identity(
    p: &Program,
    previous: &str,
    bar: &OnlyBar,
    init: &OnlyTimestamp,
    parent: &str,
) -> String {
    record_fingerprint(
        &json!({"schema_version":1,"program":p.fingerprint(),"previous":previous,"observation":observation_record(bar),"logical_init_ns":init.unix_nanos().to_string(),"parent_identity":parent}),
    )
}
impl<C: NodePort> Executor<C> {
    pub fn new(program: Program, port: C) -> StrategyResult<Self> {
        same_bindings(&program, &port)?;
        let states = program
            .bindings
            .iter()
            .map(|(s, b)| (s.clone(), CalculationState::new(b.clone())))
            .collect();
        let chain = initial_chain(&program);
        Ok(Self {
            program,
            port,
            states,
            requests: BTreeMap::new(),
            commitments: BTreeMap::new(),
            accepted: BTreeMap::new(),
            failed: false,
            processed: 0,
            chain,
            last_init: None,
        })
    }
    pub fn program(&self) -> &Program {
        &self.program
    }
    pub fn port(&self) -> &C {
        &self.port
    }
    pub fn is_failed(&self) -> bool {
        self.failed
    }
    pub fn prefix(&self) -> &str {
        &self.chain
    }
    pub fn last_outcome(&self, instrument: &OnlyInstrumentId) -> Option<&Outcome> {
        self.accepted
            .get(&instrument.to_string())
            .map(|v| &v.outcome)
    }
    pub fn last_bar(&self, instrument: &OnlyInstrumentId) -> Option<&OnlyBar> {
        self.accepted.get(&instrument.to_string()).map(|v| &v.bar)
    }
    fn preflight(
        &self,
        bar: &OnlyBar,
        init: &OnlyTimestamp,
        parent: &str,
    ) -> StrategyResult<Option<Outcome>> {
        if self.failed {
            return Err(StrategyError("STRATEGY_RECOVERY_REQUIRED"));
        }
        sha(&json!(parent))?;
        let row = bar.to_record();
        if !self.program.revision.universe.contains(bar.instrument_id())
            || bar.bar_type().semantic() != &self.program.revision.semantic
            || !bar.is_closed()
            || bar.ts_event() != bar.bar_end()
            || row["revision"].as_u64() != Some(0)
            || row["adjustment_type"] != "RAW"
        {
            return Err(StrategyError("STRATEGY_OBSERVATION_NOT_ADMITTED"));
        }
        let event = OnlyTimestamp::from_datetime(*bar.bar_end());
        if init < &event {
            return Err(bad());
        }
        if let Some(old) = self.accepted.get(&bar.instrument_id().to_string()) {
            if bar.bar_end() == old.bar.bar_end() {
                if observation_fingerprint(bar) != observation_fingerprint(&old.bar) {
                    return Err(StrategyError("CORRECTED_FINAL_BAR_UNSUPPORTED"));
                }
                return Ok(Some(old.outcome.clone()));
            }
            if bar.bar_end() < old.bar.bar_end() {
                return Err(StrategyError("STRATEGY_OBSERVATION_OUT_OF_ORDER"));
            }
        }
        if self.processed == u64::MAX
            || self.last_init.as_ref().is_some_and(|t| t > init)
            || self
                .accepted
                .values()
                .any(|v| v.bar.bar_end() > bar.bar_end())
        {
            return Err(bad());
        }
        // Validate all external inputs before any producer can mutate.
        for d in self.program.revision.graph.ordered_nodes() {
            let r = d.to_record();
            let ports = array(&r["inputs"])?;
            for (name, b) in r["input_bindings"].as_object().ok_or_else(bad)? {
                if let Some(source) = b["source"].as_str() {
                    let value = project(bar, source)?;
                    let p = ports.iter().find(|p| p["name"] == *name).ok_or_else(bad)?;
                    typed_values(&json!({name:value}), &json!([p]))?;
                }
            }
        }
        Ok(None)
    }
    pub fn process(
        &mut self,
        bar: &OnlyBar,
        logical_init: &OnlyTimestamp,
        parent: &str,
    ) -> StrategyResult<Outcome> {
        if let Some(old) = self.preflight(bar, logical_init, parent)? {
            return Ok(old);
        }
        self.failed = true;
        let result = catch_unwind(AssertUnwindSafe(|| {
            self.process_inner(bar, logical_init, parent)
        }))
        .unwrap_or(Err(StrategyError("STRATEGY_PRODUCER_PANIC")));
        if result.is_ok() {
            self.failed = false;
        }
        result
    }
    fn process_inner(
        &mut self,
        bar: &OnlyBar,
        init: &OnlyTimestamp,
        parent: &str,
    ) -> StrategyResult<Outcome> {
        let previous = self.chain.clone();
        let input_id = identity(&self.program, &previous, bar, init, parent);
        let time = OnlyTimestamp::from_datetime(*bar.bar_end())
            .unix_nanos()
            .to_string();
        let mut outputs: BTreeMap<String, Value> = BTreeMap::new();
        let mut ready: BTreeMap<String, bool> = BTreeMap::new();
        let mut trace = Vec::new();
        let mut calls = Vec::new();
        for definition in self.program.revision.graph.ordered_nodes() {
            let node = definition.fingerprint();
            let row = definition.to_record();
            let key = self.program.instance_scope(bar.instrument_id(), &node);
            let references = row["input_bindings"].as_object().ok_or_else(bad)?;
            if references.values().any(|r| {
                r["node_fingerprint"]
                    .as_str()
                    .is_some_and(|d| ready.get(d) != Some(&true))
            }) {
                ready.insert(node.clone(), false);
                trace.push(
                    json!({"node_fingerprint":node,"status":"BLOCKED","receipt_fingerprint":null,"state_fingerprint":null}),
                );
                continue;
            }
            let mut inputs = serde_json::Map::new();
            for (name, r) in references {
                let value = if let Some(source) = r["source"].as_str() {
                    project(bar, source)?
                } else {
                    outputs
                        .get(text(&r["node_fingerprint"])?)
                        .and_then(|v| v.get(text(&r["output_name"]).ok()?))
                        .cloned()
                        .ok_or_else(bad)?
                };
                inputs.insert(name.clone(), value);
            }
            let inputs = typed_values(&Value::Object(inputs), &row["inputs"])?;
            let state = self.states.get(&key).ok_or_else(bad)?;
            let mut request = NodeRequest {
                scope: key.clone(),
                binding: state.cursor().binding().clone(),
                revision: state.cursor().revision(),
                bar: bar.clone(),
                inputs,
                input_digest: String::new(),
            };
            request.input_digest = record_fingerprint(&request.input_record());
            let prepared = state
                .prepare(&[&time], &request.input_digest)
                .map_err(|_| bad())?;
            let acknowledgment = match self.port.update(&request) {
                Ok(v) => v,
                Err(f) => {
                    self.states
                        .get_mut(&key)
                        .ok_or_else(bad)?
                        .fail(
                            if f == NodeFailure::Unknown {
                                StateOutcome::Unknown
                            } else {
                                StateOutcome::Failed
                            },
                            "PRODUCER_FAILED",
                        )
                        .map_err(|_| bad())?;
                    return Err(StrategyError(if f == NodeFailure::Unknown {
                        "STRATEGY_CALCULATION_UNKNOWN"
                    } else {
                        "STRATEGY_CALCULATION_FAILED"
                    }));
                }
            };
            object(&acknowledgment, &["receipt", "state_fingerprint"])?;
            let commitment = sha(&acknowledgment["state_fingerprint"])?.to_owned();
            let receipt = acknowledgment["receipt"].clone();
            let typed = typed_values(&receipt["outputs"], &row["outputs"])?;
            if typed != receipt["outputs"] {
                return Err(StrategyError("NONCANONICAL_PRODUCER_OUTPUT"));
            }
            self.states
                .get_mut(&key)
                .ok_or_else(bad)?
                .commit(&prepared, &receipt)
                .map_err(|_| StrategyError("STRATEGY_RECEIPT_INVALID"))?;
            self.requests.insert(key.clone(), request.input_record());
            self.commitments.insert(key.clone(), commitment.clone());
            calls.push(key);
            let is_ready = receipt["ready"].as_bool().ok_or_else(bad)?;
            ready.insert(node.clone(), is_ready);
            outputs.insert(node.clone(), typed);
            trace.push(json!({"node_fingerprint":node,"status":if is_ready{"READY"}else{"WARMING"},"receipt_fingerprint":record_fingerprint(&receipt),"state_fingerprint":commitment}));
        }
        let all_ready = ready.values().all(|r| *r);
        let observation = observation_fingerprint(bar);
        let instrument = bar.instrument_id().to_string();
        let decision = if all_ready {
            let mut booleans = Vec::new();
            for s in &self.program.revision.signals {
                let v = &outputs.get(&s.node).ok_or_else(bad)?[&s.output];
                booleans.push(if v["type"] == "NULL" {
                    false
                } else if v["type"] == "BOOLEAN" {
                    v["value"].as_bool().ok_or_else(bad)?
                } else {
                    return Err(bad());
                });
            }
            json!({"schema_version":2,"strategy_fingerprint":self.program.revision.fingerprint(),"instrument_id":instrument,"observation_key":{"instrument_id":instrument,"bar_semantic_fingerprint":bar.bar_type().semantic().fingerprint().map_err(|_|bad())?,"bar_end_ns":time},"observation_fingerprint":observation,"decision_time_ns":time,"input_identity":input_id,"trace_fingerprint":record_fingerprint(&json!(trace)),"eligibility":booleans[0],"entry":booleans[1],"exit":booleans[2]})
        } else {
            Value::Null
        };
        let outcome = Outcome {
            record: json!({"schema_version":2,"strategy_fingerprint":self.program.revision.fingerprint(),"instrument_id":instrument,"event_ns":time,"observation_fingerprint":observation,"input_identity":input_id,"parent_identity":parent,"status":if all_ready{"READY"}else{"BLOCKED"},"decision":decision,"trace":trace}),
        };
        let count = self.accepted.get(&instrument).map_or(1, |v| v.count + 1);
        self.accepted.insert(
            instrument,
            Accepted {
                bar: bar.clone(),
                init: init.clone(),
                parent: parent.into(),
                previous,
                count,
                outcome: outcome.clone(),
                calls,
            },
        );
        self.chain = input_id;
        self.processed += 1;
        self.last_init = Some(init.clone());
        Ok(outcome)
    }
}
