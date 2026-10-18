use crate::{execution::*, model::*};
use onlyalpha_calculation::{CalculationState, StateOutcome};
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    panic::{AssertUnwindSafe, catch_unwind},
};
const MAX_CHECKPOINT: usize = 64 * 1024 * 1024;
fn integer(v: &Value) -> StrategyResult<u64> {
    v.as_u64().ok_or_else(bad)
}
fn manifest(v: &Value) -> StrategyResult<Value> {
    Ok(Value::Object(
        v.as_object()
            .ok_or_else(bad)?
            .iter()
            .filter(|(k, _)| k.as_str() != "component_bindings")
            .map(|(k, v)| (k.clone(), json!(record_fingerprint(v))))
            .collect(),
    ))
}
fn pairs(v: &Value) -> StrategyResult<BTreeMap<String, Value>> {
    let mut m = BTreeMap::new();
    for row in array(v)? {
        let a = array(row)?;
        if a.len() != 2 || m.insert(text(&a[0])?.to_owned(), a[1].clone()).is_some() {
            return Err(bad());
        }
    }
    Ok(m)
}
impl<C: NodePort> Executor<C> {
    fn validate_components(&self, port: &Value) -> StrategyResult<()> {
        same_bindings(&self.program, &self.port)?;
        object(port, &["schema_version", "nodes"])?;
        if port["schema_version"] != 1 {
            return Err(bad());
        }
        let native = pairs(&port["nodes"])?;
        if native.keys().ne(self.states.keys())
            || self.states.keys().ne(self.program.bindings.keys())
        {
            return Err(bad());
        }
        for (scope, state) in &self.states {
            let binding = &self.program.bindings[scope];
            let n = &native[scope];
            let captured = state.capture();
            object(
                n,
                &[
                    "schema_version",
                    "binding",
                    "cursor",
                    "receipt",
                    "plugin_state",
                    "state_fingerprint",
                    "state_capability",
                    "checkpoint_schema_version",
                    "definition_fingerprint",
                ],
            )?;
            let d = &self.program.revision.descriptors[&binding.digests()[2]];
            if n["schema_version"] != 1
                || n["binding"] != binding.to_record()
                || n["cursor"] != captured["cursor"]
                || n["receipt"] != captured["receipt"]
                || n["state_capability"] != d.state_capability
                || n["checkpoint_schema_version"] != json!(d.checkpoint_schema)
                || n["definition_fingerprint"] != d.definition.fingerprint()
                || !matches!(
                    state.snapshot().outcome(),
                    StateOutcome::Uninitialized | StateOutcome::Warming | StateOutcome::Ready
                )
            {
                return Err(bad());
            }
            if state.cursor().revision() != state.cursor().samples() {
                return Err(bad());
            }
            if n["state_fingerprint"] != record_fingerprint(&n["plugin_state"]) {
                return Err(bad());
            }
            if state.cursor().samples() == 0 {
                if self.requests.contains_key(scope) || self.commitments.contains_key(scope) {
                    return Err(bad());
                }
                continue;
            }
            if self
                .commitments
                .get(scope)
                .is_none_or(|h| n["state_fingerprint"] != *h)
            {
                return Err(bad());
            }
            let request = self.requests.get(scope).ok_or_else(bad)?;
            object(request, &["schema_version", "binding", "bar", "inputs"])?;
            let bar = OnlyBar::from_record(&request["bar"]).map_err(|_| bad())?;
            let accepted = self
                .accepted
                .get(&bar.instrument_id().to_string())
                .ok_or_else(bad)?;
            if request["schema_version"] != 1
                || request["binding"] != binding.to_record()
                || scope
                    != &self
                        .program
                        .instance_scope(bar.instrument_id(), &d.definition.fingerprint())
                || bar.bar_type().semantic() != self.program.revision.semantic()
                || !bar.is_closed()
                || bar.ts_event() != bar.bar_end()
                || bar.bar_end() > accepted.bar.bar_end()
                || state.cursor().samples() > accepted.count
                || captured["cursor"]["last_event_ns"]
                    != OnlyTimestamp::from_datetime(*bar.bar_end())
                        .unix_nanos()
                        .to_string()
                || captured["receipt"]["input_digest"] != record_fingerprint(request)
                || typed_values(&request["inputs"], &d.definition.to_record()["inputs"])?
                    != request["inputs"]
                || typed_values(
                    &captured["receipt"]["outputs"],
                    &d.definition.to_record()["outputs"],
                )? != captured["receipt"]["outputs"]
            {
                return Err(bad());
            }
            if accepted.calls.contains(scope) && bar.to_record() != accepted.bar.to_record() {
                return Err(bad());
            }
        }
        if self.commitments.keys().ne(self.requests.keys())
            || self.requests.keys().any(|k| !self.states.contains_key(k))
        {
            return Err(bad());
        }
        self.validate_frontier()
    }
    fn validate_frontier(&self) -> StrategyResult<()> {
        let mut total = 0u64;
        let mut latest = None;
        let mut has_chain = false;
        for (instrument, a) in &self.accepted {
            let bar = &a.bar;
            let event = OnlyTimestamp::from_datetime(*bar.bar_end());
            let time = event.unix_nanos().to_string();
            let revision = &self.program.revision;
            if instrument != &bar.instrument_id().to_string()
                || !revision.universe.contains(bar.instrument_id())
                || bar.bar_type().semantic() != revision.semantic()
                || !bar.is_closed()
                || bar.ts_event() != bar.bar_end()
                || bar.to_record()["revision"] != 0
                || a.init < event
                || a.count == 0
            {
                return Err(bad());
            }
            sha(&json!(a.parent))?;
            sha(&json!(a.previous))?;
            total = total.checked_add(a.count).ok_or_else(bad)?;
            if latest.as_ref().is_none_or(|t| t < &a.init) {
                latest = Some(a.init.clone());
            }
            let input = identity(&self.program, &a.previous, bar, &a.init, &a.parent);
            has_chain |= self.chain == input;
            let r = &a.outcome.record;
            object(
                r,
                &[
                    "schema_version",
                    "strategy_fingerprint",
                    "instrument_id",
                    "event_ns",
                    "observation_fingerprint",
                    "input_identity",
                    "parent_identity",
                    "status",
                    "decision",
                    "trace",
                ],
            )?;
            if r["schema_version"] != 2
                || r["strategy_fingerprint"] != revision.fingerprint()
                || r["instrument_id"] != *instrument
                || r["event_ns"] != time
                || r["observation_fingerprint"] != observation_fingerprint(bar)
                || r["input_identity"] != input
                || r["parent_identity"] != a.parent
            {
                return Err(bad());
            }
            let trace = array(&r["trace"])?;
            let nodes = revision.graph.ordered_nodes();
            if trace.len() != nodes.len() {
                return Err(bad());
            }
            let mut current = BTreeMap::new();
            let mut calls = Vec::new();
            let mut outputs = BTreeMap::new();
            for (t, d) in trace.iter().zip(nodes) {
                object(
                    t,
                    &[
                        "node_fingerprint",
                        "status",
                        "receipt_fingerprint",
                        "state_fingerprint",
                    ],
                )?;
                let node = d.fingerprint();
                if t["node_fingerprint"] != node {
                    return Err(bad());
                }
                let row = d.to_record();
                let blocked = row["input_bindings"]
                    .as_object()
                    .ok_or_else(bad)?
                    .values()
                    .any(|b| {
                        b["node_fingerprint"]
                            .as_str()
                            .is_some_and(|s| current.get(s) != Some(&true))
                    });
                if blocked {
                    if t["status"] != "BLOCKED"
                        || (!t["receipt_fingerprint"].is_null()
                            || !t["state_fingerprint"].is_null())
                    {
                        return Err(bad());
                    }
                    current.insert(node, false);
                    continue;
                }
                let scope = self.program.instance_scope(bar.instrument_id(), &node);
                calls.push(scope.clone());
                let state = self.states.get(&scope).ok_or_else(bad)?.capture();
                let request = self.requests.get(&scope).ok_or_else(bad)?;
                if request["bar"] != bar.to_record()
                    || (t["receipt_fingerprint"] != record_fingerprint(&state["receipt"])
                        || t["state_fingerprint"] != self.commitments[&scope])
                {
                    return Err(bad());
                }
                let ready = state["receipt"]["ready"].as_bool().ok_or_else(bad)?;
                if t["status"] != if ready { "READY" } else { "WARMING" } {
                    return Err(bad());
                }
                // Bind each input to this exact observation and the current upstream output.
                for (name, b) in row["input_bindings"].as_object().ok_or_else(bad)? {
                    let value = if let Some(source) = b["source"].as_str() {
                        project(bar, source)?
                    } else {
                        outputs
                            .get(text(&b["node_fingerprint"])?)
                            .and_then(|v: &Value| v.get(text(&b["output_name"]).ok()?))
                            .cloned()
                            .ok_or_else(bad)?
                    };
                    if request["inputs"][name] != value {
                        return Err(bad());
                    }
                }
                current.insert(node.clone(), ready);
                outputs.insert(node, state["receipt"]["outputs"].clone());
            }
            if calls != a.calls {
                return Err(bad());
            }
            let ready = current.values().all(|r| *r);
            if r["status"] != if ready { "READY" } else { "BLOCKED" } {
                return Err(bad());
            }
            if ready {
                let signals = revision
                    .signals
                    .iter()
                    .map(|s| {
                        let v = &outputs[&s.node][&s.output];
                        if v["type"] == "NULL" {
                            Ok(false)
                        } else {
                            v["value"].as_bool().ok_or_else(bad)
                        }
                    })
                    .collect::<StrategyResult<Vec<_>>>()?;
                let decision = json!({"schema_version":2,"strategy_fingerprint":revision.fingerprint(),"instrument_id":instrument,"observation_key":{"instrument_id":instrument,"bar_semantic_fingerprint":bar.bar_type().semantic().fingerprint().map_err(|_|bad())?,"bar_end_ns":time},"observation_fingerprint":observation_fingerprint(bar),"decision_time_ns":time,"input_identity":input,"trace_fingerprint":record_fingerprint(&r["trace"]),"eligibility":signals[0],"entry":signals[1],"exit":signals[2]});
                if r["decision"] != decision {
                    return Err(bad());
                }
            } else if !r["decision"].is_null() {
                return Err(bad());
            }
        }
        if total != self.processed
            || latest != self.last_init
            || if self.processed == 0 {
                self.chain != initial_chain(&self.program)
            } else {
                !has_chain
            }
        {
            return Err(bad());
        }
        Ok(())
    }
    pub fn capture_checkpoint(&mut self) -> StrategyResult<Value> {
        if self.failed {
            return Err(StrategyError("STRATEGY_RECOVERY_REQUIRED"));
        }
        self.failed = true;
        let result=catch_unwind(AssertUnwindSafe(||{let port=self.port.capture().map_err(|_|bad())?;self.validate_components(&port)?;
   let mut v=json!({"schema_version":1,"program":self.program.to_record(),"processed":self.processed,"chain":self.chain,"last_init_ns":self.last_init.as_ref().map(|t|t.unix_nanos().to_string()),"states":self.states.iter().map(|(k,s)|json!([k,s.capture()])).collect::<Vec<_>>(),"commitments":self.commitments.iter().map(|(k,v)|json!([k,v])).collect::<Vec<_>>(),"requests":self.requests.iter().map(|(k,v)|json!([k,v])).collect::<Vec<_>>(),"accepted":self.accepted.iter().map(|(k,a)|json!({"instrument":k,"bar":a.bar.to_record(),"init_ns":a.init.unix_nanos().to_string(),"parent":a.parent,"previous":a.previous,"count":a.count,"outcome":a.outcome.to_record(),"calls":a.calls})).collect::<Vec<_>>(),"port":port});
   v["component_bindings"]=manifest(&v)?;if v.to_string().len()>MAX_CHECKPOINT{return Err(bad());}Ok(v)
  })).unwrap_or(Err(StrategyError("STRATEGY_PRODUCER_PANIC")));
        if result.is_ok() {
            self.failed = false;
        }
        result
    }
    pub fn restored_candidate(&self, bytes: &[u8], expected: &str) -> StrategyResult<Self> {
        if bytes.len() > MAX_CHECKPOINT {
            return Err(bad());
        }
        let v: Value = serde_json::from_slice(bytes).map_err(|_| bad())?;
        if v.to_string().as_bytes() != bytes || record_fingerprint(&v) != expected {
            return Err(bad());
        }
        object(
            &v,
            &[
                "schema_version",
                "program",
                "processed",
                "chain",
                "last_init_ns",
                "states",
                "requests",
                "commitments",
                "accepted",
                "port",
                "component_bindings",
            ],
        )?;
        if v["schema_version"] != 1
            || v["program"] != self.program.to_record()
            || v["component_bindings"] != manifest(&v)?
        {
            return Err(bad());
        }
        // Decode all semantic state before invoking the producer's fresh restore boundary.
        let mut states = BTreeMap::new();
        for (scope, row) in pairs(&v["states"])? {
            let binding = self.program.bindings.get(&scope).ok_or_else(bad)?;
            let mut state = CalculationState::new(binding.clone());
            state.restore(&row).map_err(|_| bad())?;
            states.insert(scope, state);
        }
        let requests = pairs(&v["requests"])?;
        let commitments = pairs(&v["commitments"])?
            .into_iter()
            .map(|(k, v)| Ok((k, sha(&v)?.to_owned())))
            .collect::<StrategyResult<BTreeMap<_, _>>>()?;
        let mut accepted = BTreeMap::new();
        let mut keys = BTreeSet::new();
        for row in array(&v["accepted"])? {
            object(
                row,
                &[
                    "instrument",
                    "bar",
                    "init_ns",
                    "parent",
                    "previous",
                    "count",
                    "outcome",
                    "calls",
                ],
            )?;
            let key = text(&row["instrument"])?.to_owned();
            if !keys.insert(key.clone()) {
                return Err(bad());
            }
            let calls = array(&row["calls"])?
                .iter()
                .map(|v| Ok(text(v)?.to_owned()))
                .collect::<StrategyResult<Vec<_>>>()?;
            accepted.insert(
                key,
                Accepted {
                    bar: OnlyBar::from_record(&row["bar"]).map_err(|_| bad())?,
                    init: stamp(&row["init_ns"])?,
                    parent: sha(&row["parent"])?.into(),
                    previous: sha(&row["previous"])?.into(),
                    count: integer(&row["count"])?,
                    outcome: Outcome {
                        record: row["outcome"].clone(),
                    },
                    calls,
                },
            );
        }
        let port = catch_unwind(AssertUnwindSafe(|| self.port.restore_candidate(&v["port"])))
            .map_err(|_| bad())?
            .map_err(|_| bad())?;
        let mut candidate = Self {
            program: self.program.clone(),
            port,
            states,
            requests,
            commitments,
            accepted,
            failed: false,
            processed: integer(&v["processed"])?,
            chain: sha(&v["chain"])?.into(),
            last_init: if v["last_init_ns"].is_null() {
                None
            } else {
                Some(stamp(&v["last_init_ns"])?)
            },
        };
        candidate.validate_components(&v["port"])?;
        let fresh = catch_unwind(AssertUnwindSafe(|| candidate.port.capture()))
            .map_err(|_| bad())?
            .map_err(|_| bad())?;
        if fresh != v["port"] {
            return Err(bad());
        }
        candidate.validate_components(&fresh)?;
        Ok(candidate)
    }
    pub fn restore_checkpoint(&mut self, bytes: &[u8], expected: &str) -> StrategyResult<()> {
        let candidate = self.restored_candidate(bytes, expected)?;
        *self = candidate;
        Ok(())
    }
}
