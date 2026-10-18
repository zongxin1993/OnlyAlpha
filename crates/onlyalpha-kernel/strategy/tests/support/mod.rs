#![allow(dead_code)]
use onlyalpha_calculation::{CalculationState, Definition, ExecutionBinding, Graph};
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use onlyalpha_market_data_construction::OnlyConstructionRecipe;
use onlyalpha_strategy::*;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex},
};
pub fn base() -> Value {
    serde_json::from_str::<Value>(super::CORPUS.lines().next().unwrap()).unwrap()["record"].clone()
}
pub fn bar(i: u32) -> OnlyBar {
    let mut r = base();
    for f in ["open", "high", "low", "close"] {
        r[f]["value"] = json!(format!("{i}.00"));
    }
    for f in ["bar_start", "bar_end", "ts_event", "ts_init"] {
        let t = OnlyTimestamp::from_datetime(r[f].as_str().unwrap().parse().unwrap());
        r[f] = json!(
            OnlyTimestamp::from_unix_nanos(t.unix_nanos() + i64::from(i - 1) * 60_000_000_000i64)
                .to_datetime_exact()
                .unwrap()
                .to_string()
        );
    }
    OnlyBar::from_record(&r).unwrap()
}
pub fn time(b: &OnlyBar) -> OnlyTimestamp {
    OnlyTimestamp::from_datetime(*b.ts_init())
}
fn definition(id: &str, role: &str, upstream: Option<&str>) -> Definition {
    let input = json!({"name":"value","data_type":"DECIMAL","nullable":true,"dimensions":["TIME"],"semantic_type":"PREDICATE_OPERAND","unit":null});
    let r = json!({"schema_version":3,"kind":if upstream.is_some(){"PREDICATE"}else{"INDICATOR"},"type_id":id,"semantic_version":"1","parameters":{},"inputs":[input],"input_bindings":{"value":{"node_fingerprint":upstream,"output_name":"value","source":if upstream.is_some(){Value::Null}else{json!("bar.close")}}},"outputs":[{"name":"value","data_type":if upstream.is_some(){"BOOLEAN"}else{"DECIMAL"},"nullable":true,"dimensions":["TIME"],"semantic_type":role,"unit":null}],"warmup":{"minimum_observations":1,"ready_condition":"controlled input available","pre_ready_output":"NULL","initialization":"UPSTREAM"},"missing_values":"PROPAGATE","timestamp":"BAR_CLOSE","numeric":{"representation":"DECIMAL","precision":28,"output_quantum":"0.000000000001","rounding":"ROUND_HALF_EVEN"},"factor_kind":null,"extensions":{}});
    Definition::from_record(&r).unwrap()
}
pub fn revision() -> Revision {
    let root = definition("test.scalar", "VALUE", None);
    let node = root.fingerprint();
    let terminal: Vec<_> = [
        ("test.eligibility", "ELIGIBILITY"),
        ("test.entry", "ENTRY_SIGNAL"),
        ("test.exit", "EXIT_SIGNAL"),
    ]
    .iter()
    .map(|(t, r)| definition(t, r, Some(&node)))
    .collect();
    let signals =
        std::array::from_fn(|i| SignalBinding::new(&terminal[i].fingerprint(), "value").unwrap());
    let definitions: Vec<_> = std::iter::once(root).chain(terminal).collect();
    let graph = Graph::new(definitions.iter().map(|d| (d.clone(), None)).collect()).unwrap();
    let descriptors = definitions
        .into_iter()
        .map(|definition| NodeDescriptor {
            definition,
            native_definition: "d".repeat(64),
            implementation: "e".repeat(64),
            state_capability: "CHECKPOINTABLE".into(),
            checkpoint_schema: Some(1),
        })
        .collect();
    let b = bar(1);
    Revision::new(
        vec![b.instrument_id().clone()],
        b.bar_type().semantic().clone(),
        OnlyConstructionRecipe::native(b.bar_type().semantic().clone()),
        graph,
        descriptors,
        signals,
    )
    .unwrap()
}
pub fn program() -> Program {
    Program::new(
        revision(),
        Scope {
            engine: "engine".parse().unwrap(),
            runtime: "runtime".parse().unwrap(),
            cluster: "cluster".parse().unwrap(),
        },
        &"a".repeat(64),
        &"c".repeat(64),
        &"b".repeat(64),
    )
    .unwrap()
}
#[derive(Clone, Default)]
pub struct Fault {
    pub scope: String,
    pub mode: String,
}
pub struct Port {
    pub program: Program,
    pub states: BTreeMap<String, CalculationState>,
    pub fault: Arc<Mutex<Fault>>,
    pub calls: Arc<Mutex<Vec<String>>>,
}
impl Port {
    pub fn new(program: Program) -> Self {
        let states = program
            .bindings()
            .iter()
            .map(|(s, b)| (s.clone(), CalculationState::new(b.clone())))
            .collect();
        Self {
            program,
            states,
            fault: Arc::new(Mutex::new(Fault::default())),
            calls: Arc::new(Mutex::new(vec![])),
        }
    }
}
impl NodePort for Port {
    fn bindings(&self) -> Vec<ExecutionBinding> {
        self.program.bindings().values().cloned().collect()
    }
    fn update(&mut self, r: &NodeRequest) -> Result<Value, NodeFailure> {
        self.calls.lock().unwrap().push(r.scope.clone());
        let f = self.fault.lock().unwrap();
        if f.scope == r.scope {
            match f.mode.as_str() {
                "known" => return Err(NodeFailure::Known),
                "unknown" => return Err(NodeFailure::Unknown),
                "panic" => panic!("controlled producer panic"),
                "malformed" => return Ok(json!({})),
                _ => (),
            }
        }
        let state = self.states.get_mut(&r.scope).unwrap();
        let t = OnlyTimestamp::from_datetime(*r.bar.bar_end())
            .unix_nanos()
            .to_string();
        let prepared = state.prepare(&[&t], &r.input_digest).unwrap();
        let mut cursor = state.cursor().capture();
        let n = cursor["samples"].as_u64().unwrap() + 1;
        cursor["samples"] = json!(n);
        cursor["revision"] = json!(n);
        cursor["last_event_ns"] = json!(t);
        let d = &self.program.revision().descriptors()[&r.binding.digests()[2]].definition;
        let kind = d.reference().type_id();
        let input = &r.inputs["value"];
        let value = if kind == "test.scalar" {
            input.clone()
        } else if f.mode == "null-terminal" {
            json!({"type":"NULL","value":null})
        } else {
            let v = input["value"].as_str().unwrap().parse::<i64>().unwrap();
            json!({"type":"BOOLEAN","value":match kind{"test.eligibility"=>true,"test.entry"=>v>2,_=>v<2}})
        };
        let ready = kind != "test.scalar" || n >= 3;
        let receipt = json!({"cursor":cursor,"input_digest":r.input_digest,"outputs":{"value":value},"ready":ready,"quality_flags":[]});
        state.commit(&prepared, &receipt).unwrap();
        Ok(
            json!({"receipt":receipt,"state_fingerprint":record_fingerprint(&json!({"state":state.capture()}))}),
        )
    }
    fn capture(&mut self) -> Result<Value, NodeFailure> {
        Ok(
            json!({"schema_version":1,"nodes":self.states.iter().map(|(s,state)|json!([s,{"schema_version":1,"binding":state.cursor().binding().to_record(),"cursor":state.cursor().capture(),"receipt":state.capture()["receipt"],"plugin_state":{"state":state.capture()},"state_fingerprint":record_fingerprint(&json!({"state":state.capture()})),"state_capability":"CHECKPOINTABLE","checkpoint_schema_version":1,"definition_fingerprint":state.cursor().binding().digests()[2]}])).collect::<Vec<_>>()}),
        )
    }
    fn restore_candidate(&self, v: &Value) -> Result<Self, NodeFailure> {
        let mut p = Self::new(self.program.clone());
        for row in v["nodes"].as_array().ok_or(NodeFailure::Known)? {
            let s = row[0].as_str().ok_or(NodeFailure::Known)?;
            p.states
                .get_mut(s)
                .ok_or(NodeFailure::Known)?
                .restore(&row[1]["plugin_state"]["state"])
                .map_err(|_| NodeFailure::Known)?;
        }
        Ok(p)
    }
}
pub fn executor() -> Executor<Port> {
    let p = program();
    Executor::new(p.clone(), Port::new(p)).unwrap()
}
pub fn restore<C: NodePort>(e: &mut Executor<C>, v: &Value) -> StrategyResult<()> {
    e.restore_checkpoint(v.to_string().as_bytes(), &record_fingerprint(v))
}
pub fn process<C: NodePort>(e: &mut Executor<C>, i: u32) -> StrategyResult<Outcome> {
    let b = bar(i);
    e.process(&b, &time(&b), &format!("{i:064x}"))
}
