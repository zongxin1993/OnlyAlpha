//! Exact bounded conversational Factor -> existing Product Calculation Graph.
//! Pure compilation, not Human acceptance, executable admission or a Dataset proof.
use crate::application::{
    factor_content,
    private_assets::authoring::{Draft, validate_revision},
};
use onlyalpha_calculation::product::{Definition, Graph};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
type Result<T> = std::result::Result<T, &'static str>;
const WORK: usize = 1024 * 1024;
const INVALID: &str = "RESEARCH_FACTOR_CONTENT_MISMATCH";
fn hash(v: &Value) -> Result<String> {
    factor_content::hash(v).map_err(|_| INVALID)
}
fn port(name: &str) -> Value {
    json!({"name":name,"data_type":"DECIMAL","nullable":true,"dimensions":["TIME"],"semantic_type":"NUMERIC_SERIES","unit":null})
}
fn external(source: &str) -> Value {
    json!({"node_fingerprint":null,"output_name":"value","source":source})
}
fn definition(kind: &str, id: &str, inputs: Vec<Value>, bindings: Value) -> Value {
    json!({"schema_version":2,"kind":kind,"type_id":id,"semantic_version":"1","parameters":{},
        "inputs":inputs,"input_bindings":bindings,"outputs":[port("value")],
        "warmup":{"minimum_observations":1,"ready_condition":"declared inputs are available","pre_ready_output":"NULL","initialization":"UPSTREAM"},
        "missing_values":"PROPAGATE","timestamp":"EVENT_TIME",
        "numeric":{"representation":"DECIMAL","precision":28,"output_quantum":"0.000000000001","rounding":"ROUND_HALF_EVEN"},
        "factor_kind":null,"extensions":{}})
}
pub struct CompiledFactor {
    graph: Graph,
    root: String,
    columns: Vec<String>,
    history: u64,
    fingerprint: String,
    revision: String,
}
impl CompiledFactor {
    pub fn graph(&self) -> &Graph {
        &self.graph
    }
    pub fn root_fingerprint(&self) -> &str {
        &self.root
    }
    pub fn columns(&self) -> &[String] {
        &self.columns
    }
    pub fn required_history_bars(&self) -> u64 {
        self.history
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn revision_fingerprint(&self) -> &str {
        &self.revision
    }
    pub fn window(&self, window: Window) -> Result<InputWindow> {
        let invalid = "RESEARCH_FACTOR_WINDOW_INVALID";
        let width = window
            .end_ns
            .checked_sub(window.start_ns)
            .filter(|v| *v > 0)
            .ok_or(invalid)?;
        if window.bar_ns == 0 || width % window.bar_ns != 0 || window.horizon_bars == 0 {
            return Err(invalid);
        }
        let observations = width / window.bar_ns;
        if observations <= u64::from(window.horizon_bars) {
            return Err(invalid);
        }
        let history = self.history.checked_mul(window.bar_ns).ok_or(invalid)?;
        let start = window.start_ns.checked_sub(history).ok_or(invalid)?;
        let forecast = u64::from(window.horizon_bars)
            .checked_mul(window.bar_ns)
            .ok_or(invalid)?;
        let eligible_end = window.end_ns.checked_sub(forecast).ok_or(invalid)?;
        let mut columns: BTreeSet<_> = self.columns.iter().cloned().collect();
        columns.insert("close".into()); // Declared first Target is close -> future close return.
        let record = json!({"contract":"ONLYALPHA_RESEARCH_FACTOR_INPUT_WINDOW_V1",
            "factor_preparation_fingerprint":self.fingerprint,"factor_revision_fingerprint":self.revision,
            "observation_start_ns":window.start_ns.to_string(),"observation_end_ns":window.end_ns.to_string(),
            "bar_ns":window.bar_ns.to_string(),"horizon_bars":window.horizon_bars,
            "dataset_event_start_ns":start.to_string(),"dataset_event_end_ns":window.end_ns.to_string(),
            "eligible_observation_end_ns":eligible_end.to_string(),"dataset_columns":columns,
            "observation_capacity":observations,"pair_capacity":observations-u64::from(window.horizon_bars)});
        Ok(InputWindow {
            fingerprint: hash(&record)?,
            record,
            window,
            start,
            eligible_end,
            observations,
        })
    }
}
#[derive(Clone, Copy, Debug)]
pub struct Window {
    pub start_ns: u64,
    pub end_ns: u64,
    pub bar_ns: u64,
    pub horizon_bars: u32,
}
pub struct InputWindow {
    record: Value,
    fingerprint: String,
    window: Window,
    start: u64,
    eligible_end: u64,
    observations: u64,
}
impl InputWindow {
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn dataset_start_ns(&self) -> u64 {
        self.start
    }
    pub fn dataset_end_ns(&self) -> u64 {
        self.window.end_ns
    }
    pub fn eligible_end_ns(&self) -> u64 {
        self.eligible_end
    }
    pub fn observation_count(&self) -> u64 {
        self.observations
    }
    pub fn pair_capacity(&self) -> u64 {
        self.observations - u64::from(self.window.horizon_bars)
    }
}
/// Source/content consistency only. The caller must load Human acceptance, exact Revision,
/// authoritative Dataset/source proofs and selected executable Generation at their owners.
pub fn compile(
    candidate: &Value,
    confirmed_draft: &Value,
    published_revision: &Value,
) -> Result<CompiledFactor> {
    if confirmed_draft.to_string().len() > 262144 || published_revision.to_string().len() > 262144 {
        return Err(INVALID);
    }
    let draft = Draft::new(confirmed_draft.clone()).map_err(|_| INVALID)?;
    let preview = factor_content::preview(candidate, draft.factor_id()).map_err(|_| INVALID)?;
    let mut expected = preview["draft"].clone();
    expected["base_revision_fingerprint"] = confirmed_draft["base_revision_fingerprint"].clone();
    if draft.record() != &expected {
        return Err(INVALID);
    }
    validate_revision(published_revision).map_err(|_| "RESEARCH_FACTOR_REVISION_MISMATCH")?;
    if draft.revision().map_err(|_| INVALID)? != *published_revision {
        return Err("RESEARCH_FACTOR_REVISION_MISMATCH");
    }
    let deps = preview["dependencies"].as_object().ok_or(INVALID)?;
    let mut nodes = Vec::new();
    let mut bindings = BTreeMap::new();
    let mut columns = BTreeSet::new();
    let mut history = 0;
    for (name, dependency) in deps {
        let input = dependency["input"].as_str().ok_or(INVALID)?;
        columns.insert(input.to_owned());
        if let Some(operator) = dependency["operator"].as_str() {
            let period = dependency["period"].as_u64().ok_or(INVALID)?;
            let delayed = operator == "onlyalpha.operator.delay";
            if !delayed && operator != "onlyalpha.operator.rolling_mean" {
                return Err(INVALID);
            }
            let observations = if delayed { period + 1 } else { period };
            history = history.max(observations - 1);
            let mut d = definition(
                "INDICATOR",
                operator,
                vec![port("value")],
                json!({"value":external(input)}),
            );
            d["parameters"] = json!({"period":{"type":"INTEGER","value":period}});
            d["warmup"]["minimum_observations"] = json!(observations);
            d["warmup"]["ready_condition"] = json!(if delayed {
                "complete inclusive declared window is available"
            } else if period > 1 {
                "complete declared input window is available"
            } else {
                "declared input is available"
            });
            let d =
                Definition::from_record(&d, WORK).map_err(|_| "RESEARCH_FACTOR_GRAPH_INVALID")?;
            bindings.insert(
                name.clone(),
                json!({"node_fingerprint":d.fingerprint(),"output_name":"value","source":null}),
            );
            nodes.push(json!({"definition":d.to_record(),"alias":null}));
        } else {
            bindings.insert(name.clone(), external(input));
        }
    }
    let inputs = bindings.keys().map(|name| port(name)).collect();
    let mut root = definition("FACTOR", draft.factor_id(), inputs, json!(bindings));
    root["outputs"][0]["semantic_type"] = json!("FACTOR_VALUE");
    root["numeric"]["precision"] = json!(38);
    root["parameters"] = json!(
        draft.record()["parameter_contract"]
            .as_object()
            .ok_or(INVALID)?
            .iter()
            .map(|(k, v)| (k.clone(), json!({"type":"DECIMAL","value":v["default"]})))
            .collect::<BTreeMap<_, _>>()
    );
    root["factor_kind"] = json!("TIME_SERIES");
    root["warmup"] = json!({"minimum_observations":1,"ready_condition":"point inputs are available","pre_ready_output":"NULL","initialization":"STATELESS"});
    let root = Definition::from_record(&root, WORK).map_err(|_| "RESEARCH_FACTOR_GRAPH_INVALID")?;
    nodes.push(json!({"definition":root.to_record(),"alias":null}));
    let graph = Graph::from_record(&json!({"schema_version":1,"nodes":nodes}), WORK)
        .map_err(|_| "RESEARCH_FACTOR_GRAPH_INVALID")?;
    let revision = published_revision["revision_fingerprint"]
        .as_str()
        .ok_or(INVALID)?
        .to_owned();
    let fingerprint = hash(
        &json!({"contract":"ONLYALPHA_RESEARCH_FACTOR_PREPARATION_V1",
        "draft_fingerprint":draft.fingerprint().map_err(|_|INVALID)?,"factor_revision_fingerprint":revision,
        "source_sha256":published_revision["source_sha256"],"factor_api_contract_fingerprint":published_revision["factor_api_contract_fingerprint"],
        "graph_fingerprint":graph.fingerprint(),"root_fingerprint":root.fingerprint(),"columns":columns,"required_history_bars":history}),
    )?;
    Ok(CompiledFactor {
        graph,
        root: root.fingerprint(),
        columns: columns.into_iter().collect(),
        history,
        fingerprint,
        revision,
    })
}
