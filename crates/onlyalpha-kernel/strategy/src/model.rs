use onlyalpha_calculation::{Definition, ExecutionBinding, Graph};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    identifiers::{OnlyClusterId, OnlyEngineId, OnlyInstrumentId, OnlyRuntimeId},
    market::{OnlyBar, OnlyBarSemantic, OnlyBarType},
    time::OnlyTimestamp,
};
use onlyalpha_market_data_construction::OnlyConstructionRecipe;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StrategyError(pub &'static str);
impl std::fmt::Display for StrategyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.0)
    }
}
impl std::error::Error for StrategyError {}
pub type StrategyResult<T> = Result<T, StrategyError>;
pub fn record_fingerprint(v: &Value) -> String {
    Sha256::digest(v.to_string().as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
pub(crate) fn bad() -> StrategyError {
    StrategyError("STRATEGY_CONTRACT_INVALID")
}
pub(crate) fn object<'a>(v: &'a Value, keys: &[&str]) -> StrategyResult<&'a Map<String, Value>> {
    let m = v.as_object().ok_or_else(bad)?;
    if m.len() != keys.len() || keys.iter().any(|k| !m.contains_key(*k)) {
        return Err(bad());
    }
    Ok(m)
}
pub(crate) fn text(v: &Value) -> StrategyResult<&str> {
    v.as_str().filter(|s| s.len() <= 4096).ok_or_else(bad)
}
pub(crate) fn array(v: &Value) -> StrategyResult<&Vec<Value>> {
    v.as_array().filter(|v| v.len() <= 4096).ok_or_else(bad)
}
pub(crate) fn sha(v: &Value) -> StrategyResult<&str> {
    let s = text(v)?;
    if s.len() != 64
        || !s
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(bad());
    }
    Ok(s)
}
pub(crate) fn stamp(v: &Value) -> StrategyResult<OnlyTimestamp> {
    let s = text(v)?;
    if s.len() > 128 {
        return Err(bad());
    }
    let n: num_bigint::BigInt = s.parse().map_err(|_| bad())?;
    if n.to_string() != s {
        return Err(bad());
    }
    Ok(OnlyTimestamp::from_unix_nanos(n))
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NodeDescriptor {
    pub definition: Definition,
    pub native_definition: String,
    pub implementation: String,
    pub state_capability: String,
    pub checkpoint_schema: Option<u64>,
}
impl NodeDescriptor {
    pub fn from_record(v: &Value) -> StrategyResult<Self> {
        object(
            v,
            &[
                "schema_version",
                "definition",
                "definition_fingerprint",
                "native_definition",
                "implementation",
                "state_capability",
                "checkpoint_schema_version",
            ],
        )?;
        let definition = Definition::from_record(&v["definition"]).map_err(|_| bad())?;
        let native_definition = sha(&v["native_definition"])?.to_owned();
        let implementation = sha(&v["implementation"])?.to_owned();
        let capability = text(&v["state_capability"])?;
        let checkpoint_schema = if v["checkpoint_schema_version"].is_null() {
            None
        } else {
            Some(
                v["checkpoint_schema_version"]
                    .as_u64()
                    .filter(|x| *x > 0)
                    .ok_or_else(bad)?,
            )
        };
        if v["schema_version"].as_u64() != Some(1)
            || v["definition_fingerprint"] != definition.fingerprint()
            || !matches!(
                (capability, checkpoint_schema),
                ("STATELESS", None) | ("CHECKPOINTABLE", Some(_))
            )
        {
            return Err(bad());
        }
        Ok(Self {
            definition,
            native_definition,
            implementation,
            state_capability: capability.into(),
            checkpoint_schema,
        })
    }
    pub fn to_record(&self) -> Value {
        json!({"schema_version":1,"definition":self.definition.to_record(),"definition_fingerprint":self.definition.fingerprint(),"native_definition":self.native_definition,"implementation":self.implementation,"state_capability":self.state_capability,"checkpoint_schema_version":self.checkpoint_schema})
    }
    fn binding_record(&self) -> Value {
        json!({"node_fingerprint":self.definition.fingerprint(),"native_definition":self.native_definition,"implementation":self.implementation,"state_capability":self.state_capability,"checkpoint_schema_version":self.checkpoint_schema})
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SignalBinding {
    pub node: String,
    pub output: String,
}
impl SignalBinding {
    pub fn new(node: &str, output: &str) -> StrategyResult<Self> {
        sha(&json!(node))?;
        if output.is_empty()
            || output.len() > 128
            || output.chars().any(|c| c.is_whitespace() || c.is_control())
        {
            return Err(bad());
        }
        Ok(Self {
            node: node.into(),
            output: output.into(),
        })
    }
    pub fn to_record(&self) -> Value {
        json!({"node_fingerprint":self.node,"output_name":self.output})
    }
    pub fn from_record(v: &Value) -> StrategyResult<Self> {
        object(v, &["node_fingerprint", "output_name"])?;
        Self::new(text(&v["node_fingerprint"])?, text(&v["output_name"])?)
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Revision {
    pub(crate) universe: Vec<OnlyInstrumentId>,
    pub(crate) semantic: OnlyBarSemantic,
    pub(crate) recipe: OnlyConstructionRecipe,
    pub(crate) graph: Graph,
    pub(crate) descriptors: BTreeMap<String, NodeDescriptor>,
    pub(crate) signals: [SignalBinding; 3],
    pub(crate) fingerprint: String,
    pub(crate) product: Option<Value>,
}
impl Revision {
    pub fn new(
        mut universe: Vec<OnlyInstrumentId>,
        semantic: OnlyBarSemantic,
        recipe: OnlyConstructionRecipe,
        graph: Graph,
        descriptors: Vec<NodeDescriptor>,
        signals: [SignalBinding; 3],
    ) -> StrategyResult<Self> {
        universe.sort_by_key(ToString::to_string);
        let unique: BTreeSet<_> = universe.iter().map(ToString::to_string).collect();
        let ordered = graph.ordered_nodes();
        if universe.is_empty()
            || universe.len() > 16
            || unique.len() != universe.len()
            || ordered.is_empty()
            || ordered.len() > 64
            || recipe.target() != &semantic
            || semantic.to_record()["adjustment_policy"] != "RAW"
        {
            return Err(bad());
        }
        let mut ds = BTreeMap::new();
        for d in descriptors {
            NodeDescriptor::from_record(&d.to_record())?;
            if ds.insert(d.definition.fingerprint(), d).is_some() {
                return Err(bad());
            }
        }
        if ds.len() != ordered.len() {
            return Err(bad());
        }
        for n in ordered {
            if n.reference().kind() == "TARGET"
                || n.execution_shape().map_err(|_| bad())? != "TIME_SERIES"
                || ds.get(&n.fingerprint()).is_none_or(|d| d.definition != *n)
            {
                return Err(bad());
            }
            let row = n.to_record();
            for p in row["inputs"]
                .as_array()
                .ok_or_else(bad)?
                .iter()
                .chain(row["outputs"].as_array().ok_or_else(bad)?.iter())
            {
                if p["dimensions"] != json!(["TIME"]) {
                    return Err(StrategyError("EXECUTION_SHAPE_UNAVAILABLE"));
                }
            }
            for b in row["input_bindings"].as_object().ok_or_else(bad)?.values() {
                if let Some(s) = b["source"].as_str()
                    && !BAR_SOURCES.contains(&s)
                {
                    return Err(bad());
                }
            }
        }
        for (s, role) in signals
            .iter()
            .zip(["ELIGIBILITY", "ENTRY_SIGNAL", "EXIT_SIGNAL"])
        {
            SignalBinding::new(&s.node, &s.output)?;
            let d = ds.get(&s.node).ok_or_else(bad)?.definition.to_record();
            let out = d["outputs"]
                .as_array()
                .ok_or_else(bad)?
                .iter()
                .find(|p| p["name"] == s.output)
                .ok_or_else(bad)?;
            if out["data_type"] != "BOOLEAN" || out["semantic_type"] != role {
                return Err(bad());
            }
        }
        let mut r = Self {
            universe,
            semantic,
            recipe,
            graph,
            descriptors: ds,
            signals,
            fingerprint: String::new(),
            product: None,
        };
        r.fingerprint = record_fingerprint(&r.identity());
        Ok(r)
    }
    fn identity(&self) -> Value {
        json!({"domain":"onlyalpha.strategy.revision","schema_version":2,"universe":self.universe.iter().map(OnlyDomainModel::to_record).collect::<Vec<_>>(),"bar_semantic":self.semantic.to_record(),"construction_recipe":self.recipe.to_record(),"decision_graph_fingerprint":self.graph.fingerprint(),"implementations":self.descriptors.values().map(NodeDescriptor::binding_record).collect::<Vec<_>>(),"signals":self.signals.iter().map(SignalBinding::to_record).collect::<Vec<_>>(),"missing_decision":"FALSE"})
    }
    pub fn to_record(&self) -> Value {
        let mut v = self.identity();
        v["decision_graph"] = self.graph.to_record();
        v["strategy_fingerprint"] = json!(self.fingerprint);
        if let Some(product) = &self.product {
            v["product"] = product.clone();
            v["compiled_fingerprint"] = json!(record_fingerprint(&self.identity()));
        }
        v
    }
    pub fn from_record(v: &Value) -> StrategyResult<Self> {
        if let Some(product) = v.get("product") {
            object(product, &["source", "mapping"])?;
            let mut compiled = v.clone();
            compiled.as_object_mut().ok_or_else(bad)?.remove("product");
            let fingerprint = compiled
                .as_object_mut()
                .ok_or_else(bad)?
                .remove("compiled_fingerprint")
                .ok_or_else(bad)?;
            compiled["strategy_fingerprint"] = fingerprint;
            let base = Self::from_record(&compiled)?;
            let mapping = product["mapping"]
                .as_object()
                .ok_or_else(bad)?
                .iter()
                .map(|(k, v)| Ok((k.clone(), text(v)?.to_owned())))
                .collect::<StrategyResult<BTreeMap<_, _>>>()?;
            let result = Self::from_product(
                product["source"].clone(),
                base.descriptors.into_values().collect(),
                mapping,
            )?;
            if result.to_record() != *v {
                return Err(bad());
            }
            return Ok(result);
        }
        object(
            v,
            &[
                "domain",
                "schema_version",
                "universe",
                "bar_semantic",
                "construction_recipe",
                "decision_graph_fingerprint",
                "implementations",
                "signals",
                "missing_decision",
                "decision_graph",
                "strategy_fingerprint",
            ],
        )?;
        if v["domain"] != "onlyalpha.strategy.revision"
            || v["schema_version"].as_u64() != Some(2)
            || v["missing_decision"] != "FALSE"
        {
            return Err(bad());
        }
        let graph = Graph::from_record(&v["decision_graph"]).map_err(|_| bad())?;
        let defs: BTreeMap<_, _> = graph
            .ordered_nodes()
            .into_iter()
            .map(|d| (d.fingerprint(), d.clone()))
            .collect();
        let mut descriptors = vec![];
        for d in array(&v["implementations"])? {
            object(
                d,
                &[
                    "node_fingerprint",
                    "native_definition",
                    "implementation",
                    "state_capability",
                    "checkpoint_schema_version",
                ],
            )?;
            let id = text(&d["node_fingerprint"])?;
            let definition = defs.get(id).ok_or_else(bad)?;
            let mut row = d.clone();
            let m = row.as_object_mut().ok_or_else(bad)?;
            m.remove("node_fingerprint");
            m.insert("schema_version".into(), json!(1));
            m.insert("definition".into(), definition.to_record());
            m.insert("definition_fingerprint".into(), json!(id));
            descriptors.push(NodeDescriptor::from_record(&row)?);
        }
        let universe = array(&v["universe"])?
            .iter()
            .map(|v| OnlyInstrumentId::from_record(v).map_err(|_| bad()))
            .collect::<StrategyResult<Vec<_>>>()?;
        let signals = array(&v["signals"])?
            .iter()
            .map(SignalBinding::from_record)
            .collect::<StrategyResult<Vec<_>>>()?
            .try_into()
            .map_err(|_| bad())?;
        let r = Self::new(
            universe,
            OnlyBarSemantic::from_record(&v["bar_semantic"]).map_err(|_| bad())?,
            OnlyConstructionRecipe::from_record(&v["construction_recipe"]).map_err(|_| bad())?,
            graph,
            descriptors,
            signals,
        )?;
        if r.fingerprint() != sha(&v["strategy_fingerprint"])?
            || r.graph.fingerprint() != sha(&v["decision_graph_fingerprint"])?
            || r.to_record() != *v
        {
            return Err(bad());
        }
        Ok(r)
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn is_product_materialization(&self) -> bool {
        self.product.is_some()
    }
    pub fn graph(&self) -> &Graph {
        &self.graph
    }
    pub fn descriptors(&self) -> &BTreeMap<String, NodeDescriptor> {
        &self.descriptors
    }
    pub fn universe(&self) -> &[OnlyInstrumentId] {
        &self.universe
    }
    pub fn semantic(&self) -> &OnlyBarSemantic {
        &self.semantic
    }
    pub fn recipe(&self) -> &OnlyConstructionRecipe {
        &self.recipe
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Scope {
    pub engine: OnlyEngineId,
    pub runtime: OnlyRuntimeId,
    pub cluster: OnlyClusterId,
}
impl Scope {
    pub fn to_record(&self) -> Value {
        json!({"engine":self.engine.value(),"runtime":self.runtime.value(),"cluster":self.cluster.value()})
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Program {
    pub(crate) revision: Revision,
    pub(crate) scope: Scope,
    pub(crate) generation: String,
    pub(crate) source: String,
    pub(crate) artifact: String,
    pub(crate) bindings: BTreeMap<String, ExecutionBinding>,
    fingerprint: String,
}
impl Program {
    pub fn new(
        revision: Revision,
        scope: Scope,
        generation: &str,
        source: &str,
        artifact: &str,
    ) -> StrategyResult<Self> {
        for s in [generation, source, artifact] {
            sha(&json!(s))?;
        }
        let mut p = Self {
            revision,
            scope,
            generation: generation.into(),
            source: source.into(),
            artifact: artifact.into(),
            bindings: BTreeMap::new(),
            fingerprint: String::new(),
        };
        for instrument in &p.revision.universe {
            let k=OnlyBarType::from_record(&json!({"schema_version":2,"instrument_id":instrument.to_record(),"semantic":p.revision.semantic.to_record()})).map_err(|_|bad())?;
            for (node, d) in &p.revision.descriptors {
                let key = p.instance_scope(instrument, node);
                let context = record_fingerprint(
                    &json!({"schema_version":1,"bar_type":k.to_record(),"source_fingerprint":source,"strategy_fingerprint":p.revision.fingerprint()}),
                );
                p.bindings.insert(
                    key.clone(),
                    ExecutionBinding::new(
                        [
                            generation.into(),
                            artifact.into(),
                            node.clone(),
                            d.native_definition.clone(),
                            d.implementation.clone(),
                            context,
                        ],
                        &key,
                    )
                    .map_err(|_| bad())?,
                );
            }
        }
        p.fingerprint = record_fingerprint(&p.to_record());
        Ok(p)
    }
    pub fn instance_scope(&self, instrument: &OnlyInstrumentId, node: &str) -> String {
        json!([
            self.scope.engine.value(),
            self.scope.runtime.value(),
            self.scope.cluster.value(),
            instrument.to_string(),
            node
        ])
        .to_string()
    }
    pub fn to_record(&self) -> Value {
        json!({"schema_version":1,"revision":self.revision.to_record(),"scope":self.scope.to_record(),"generation":self.generation,"source":self.source,"artifact":self.artifact,"bindings":self.bindings.values().map(ExecutionBinding::to_record).collect::<Vec<_>>()})
    }
    pub fn bindings(&self) -> &BTreeMap<String, ExecutionBinding> {
        &self.bindings
    }
    pub fn revision(&self) -> &Revision {
        &self.revision
    }
    pub fn scope(&self) -> &Scope {
        &self.scope
    }
    pub fn source(&self) -> &str {
        &self.source
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn generation(&self) -> &str {
        &self.generation
    }
    pub fn artifact(&self) -> &str {
        &self.artifact
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NodeFailure {
    Known,
    Unknown,
}
impl std::fmt::Display for NodeFailure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for NodeFailure {}
pub trait NodePort: Sized {
    fn bindings(&self) -> Vec<ExecutionBinding>;
    /// Exact acknowledgment: shared Calculation receipt plus SHA-256 of the actual
    /// committed native plugin state. Capture must reproduce this acknowledgment.
    fn update(&mut self, request: &NodeRequest) -> Result<Value, NodeFailure>;
    fn capture(&mut self) -> Result<Value, NodeFailure>;
    fn restore_candidate(&self, checkpoint: &Value) -> Result<Self, NodeFailure>;
}
pub struct NodeRequest {
    pub scope: String,
    pub binding: ExecutionBinding,
    pub revision: u64,
    pub bar: OnlyBar,
    pub inputs: Value,
    pub input_digest: String,
}
impl NodeRequest {
    pub fn input_record(&self) -> Value {
        json!({"schema_version":1,"binding":self.binding.to_record(),"bar":self.bar.to_record(),"inputs":self.inputs})
    }
}
pub(crate) const BAR_SOURCES: [&str; 9] = [
    "bar.open",
    "bar.high",
    "bar.low",
    "bar.close",
    "bar.volume",
    "bar.quote_volume",
    "bar.turnover",
    "bar.trade_count",
    "bar.open_interest",
];
pub(crate) fn normalized(v: &Value) -> StrategyResult<Value> {
    onlyalpha_calculation::normalize_result_outputs(v).map_err(|_| bad())
}
pub(crate) fn typed_values(values: &Value, ports: &Value) -> StrategyResult<Value> {
    let values = normalized(values)?;
    let map = values.as_object().ok_or_else(bad)?;
    let ports = array(ports)?;
    if map.len() != ports.len() {
        return Err(bad());
    }
    for p in ports {
        let val = map.get(text(&p["name"])?).ok_or_else(bad)?;
        let tag = text(&val["type"])?;
        if tag == "NULL" {
            if p["nullable"] != true {
                return Err(bad());
            }
        } else if val["type"] != p["data_type"] {
            return Err(bad());
        }
    }
    Ok(values)
}
pub(crate) fn project(bar: &OnlyBar, source: &str) -> StrategyResult<Value> {
    let r = bar.to_record();
    let name = source.strip_prefix("bar.").ok_or_else(bad)?;
    let value = r.get(name).ok_or_else(bad)?;
    let scalar = if value.is_null() {
        json!({"type":"NULL","value":null})
    } else if name == "trade_count" {
        json!({"type":"INTEGER","value":value})
    } else {
        let key = if name == "turnover" {
            "amount"
        } else {
            "value"
        };
        json!({"type":"DECIMAL","value":value[key]})
    };
    Ok(normalized(&json!({"value":scalar}))?["value"].clone())
}
pub fn observation_record(bar: &OnlyBar) -> Value {
    let mut row = bar.to_record();
    row.as_object_mut()
        .expect("domain record")
        .remove("ts_init");
    json!({"domain":"onlyalpha.strategy.observation.bar","schema_version":2,"bar":row})
}
pub fn observation_fingerprint(bar: &OnlyBar) -> String {
    record_fingerprint(&observation_record(bar))
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Outcome {
    pub(crate) record: Value,
}
impl Outcome {
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub fn decision(&self) -> Option<&Value> {
        self.record["decision"]
            .as_object()
            .map(|_| &self.record["decision"])
    }
    pub fn blocked(&self) -> bool {
        self.record["status"] == "BLOCKED"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exact_port_tags_and_nullable_policy_cover_all_scalar_families() {
        for (tag, value) in [
            ("DECIMAL", json!("-1.25")),
            ("INTEGER", json!(3)),
            ("BOOLEAN", json!(false)),
            ("STRING", json!("x")),
        ] {
            let ports = json!([{"name":"value","data_type":tag,"nullable":false}]);
            let values = json!({"value":{"type":tag,"value":value}});
            assert_eq!(typed_values(&values, &ports).unwrap(), values);
            assert!(typed_values(&json!({"value":{"type":"NULL","value":null}}), &ports).is_err());
            let mut nullable = ports.clone();
            nullable[0]["nullable"] = json!(true);
            assert!(
                typed_values(&json!({"value":{"type":"NULL","value":null}}), &nullable).is_ok()
            );
            assert!(
                typed_values(&json!({"value":{"type":"UNKNOWN","value":null}}), &ports).is_err()
            );
            assert!(typed_values(&json!({"other":{"type":tag,"value":value}}), &ports).is_err());
        }
    }
}
