//! Native graph adapter over already selected programs and implementations.
//! These values prove mathematics/binding only, never PG certification or admission.
use crate::{
    ImplementationArtifact,
    native_operators::{OperatorCalculation, OperatorStream},
    native_predicates::PredicateCalculation,
};
use onlyalpha_calculation::{
    CalculationState, Definition, ExecutionBinding,
    product::Definition as ProductDefinition,
    program::{BoundProgram, ProgramInput, ProgramInstance, ProgramValue},
};
use onlyalpha_domain::time::OnlyTimestamp;
use onlyalpha_strategy::{NodeFailure, NodePort, NodeRequest, Program, record_fingerprint};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};
type Result<T> = std::result::Result<T, NodeFailure>;
fn known<T>(_: T) -> NodeFailure {
    NodeFailure::Known
}
fn sha(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
#[derive(Clone)]
pub struct ProgramFactor {
    program: Arc<BoundProgram>,
    implementation: String,
}
impl ProgramFactor {
    /// The caller must obtain this exact implementation/program pair from its
    /// owning certificate reader. Construction is not a READY certificate.
    pub fn new(program: Arc<BoundProgram>, implementation: &str) -> Result<Self> {
        if !sha(implementation) {
            return Err(NodeFailure::Known);
        }
        Ok(Self {
            program,
            implementation: implementation.into(),
        })
    }
}
enum Kernel {
    Factor(ProgramInstance),
    Operator(OperatorStream),
    Predicate(PredicateCalculation),
}
struct Node {
    state: CalculationState,
    definition: ProductDefinition,
    kernel: Kernel,
    plugin: Value,
}
pub struct ProgramNodes {
    program: Program,
    definitions: BTreeMap<String, ProductDefinition>,
    factors: BTreeMap<String, ProgramFactor>,
    artifact: ImplementationArtifact,
    nodes: BTreeMap<String, Node>,
    failed: bool,
}
fn typed(raw: &Value, ports: &Value) -> Result<Value> {
    let raw = raw.as_object().ok_or(NodeFailure::Known)?;
    let ports = ports.as_array().ok_or(NodeFailure::Known)?;
    if ports.len() != raw.len() {
        return Err(NodeFailure::Known);
    }
    let mut values = serde_json::Map::new();
    for p in ports {
        let name = p["name"].as_str().ok_or(NodeFailure::Known)?;
        let value = raw.get(name).ok_or(NodeFailure::Known)?;
        if value.is_null() && p["nullable"] != true {
            return Err(NodeFailure::Known);
        }
        let tagged = if value.is_null() {
            json!({"type":"NULL","value":null})
        } else {
            json!({"type":p["data_type"],"value":value})
        };
        values.insert(name.into(), tagged);
    }
    let value = Value::Object(values);
    // Program values preserve q12 scale; Calculation tagged scalars have their
    // own canonical representation. Convert through that existing owner rather
    // than rejecting equal numeric values because their decimal text differs.
    onlyalpha_calculation::normalize_result_outputs(&value).map_err(known)
}
impl ProgramNodes {
    pub fn new(
        program: Program,
        definitions: BTreeMap<String, ProductDefinition>,
        factors: BTreeMap<String, ProgramFactor>,
        artifact: &ImplementationArtifact,
    ) -> Result<Self> {
        if definitions.len() > 128
            || definitions
                .keys()
                .ne(program.revision().descriptors().keys())
        {
            return Err(NodeFailure::Known);
        }
        let expected = definitions
            .iter()
            .filter(|(_, d)| d.to_record()["kind"] == "FACTOR")
            .map(|(k, _)| k.clone())
            .collect::<BTreeSet<_>>();
        if factors.keys().cloned().collect::<BTreeSet<_>>() != expected {
            return Err(NodeFailure::Known);
        }
        let mut nodes = BTreeMap::new();
        for (scope, binding) in program.bindings() {
            let id = &binding.digests()[2];
            let definition = definitions.get(id).ok_or(NodeFailure::Known)?;
            let descriptor = &program.revision().descriptors()[id];
            let r = definition.to_record();
            let mut projected = r.clone();
            projected["schema_version"] = json!(3);
            if Definition::from_record(&projected).map_err(known)? != descriptor.definition
                || definition.fingerprint() != descriptor.native_definition
            {
                return Err(NodeFailure::Known);
            }
            let (kernel, implementation, capability, schema) = match r["kind"].as_str() {
                Some("FACTOR") => {
                    let factor = &factors[id];
                    let actual = factor.program.program().record();
                    if factor.program.parameters().record() != &r["parameters"]
                        || actual["numeric_policy"] != "DECIMAL28_HALF_EVEN_Q12_V1"
                        || r["warmup"]["minimum_observations"]
                            .as_u64()
                            .is_none_or(|n| n < factor.program.max_history() as u64)
                    {
                        return Err(NodeFailure::Known);
                    }
                    let ports = r["inputs"].as_array().ok_or(NodeFailure::Known)?;
                    if ports.len()
                        != actual["inputs"]
                            .as_object()
                            .ok_or(NodeFailure::Known)?
                            .len()
                    {
                        return Err(NodeFailure::Known);
                    }
                    for p in ports {
                        if actual["inputs"][p["name"].as_str().ok_or(NodeFailure::Known)?]["type"]
                            != p["data_type"]
                        {
                            return Err(NodeFailure::Known);
                        }
                    }
                    let outputs = r["outputs"]
                        .as_array()
                        .ok_or(NodeFailure::Known)?
                        .iter()
                        .map(|p| {
                            Ok((
                                p["name"].as_str().ok_or(NodeFailure::Known)?.to_owned(),
                                p["data_type"]
                                    .as_str()
                                    .ok_or(NodeFailure::Known)?
                                    .to_owned(),
                            ))
                        })
                        .collect::<Result<BTreeMap<_, _>>>()?;
                    if factor
                        .program
                        .program()
                        .output_types()
                        .into_iter()
                        .map(|(k, v)| (k.to_owned(), v.to_owned()))
                        .collect::<BTreeMap<_, _>>()
                        != outputs
                    {
                        return Err(NodeFailure::Known);
                    }
                    (
                        Kernel::Factor(ProgramInstance::new(Arc::clone(&factor.program))),
                        factor.implementation.clone(),
                        "CHECKPOINTABLE".to_owned(),
                        Some(1),
                    )
                }
                Some("INDICATOR") => {
                    let op = OperatorCalculation::from_record(&r).map_err(known)?;
                    let implementation = op
                        .implementation_manifest("TRADING", artifact)
                        .map_err(known)?["implementation_fingerprint"]
                        .as_str()
                        .ok_or(NodeFailure::Known)?
                        .to_owned();
                    (
                        Kernel::Operator(op.stream().map_err(known)?),
                        implementation,
                        op.state_capability().into(),
                        op.checkpoint_schema_version(),
                    )
                }
                Some("PREDICATE") => {
                    let predicate = PredicateCalculation::from_record(&r).map_err(known)?;
                    let implementation = predicate
                        .implementation_manifest("TRADING", artifact)
                        .map_err(known)?["implementation_fingerprint"]
                        .as_str()
                        .ok_or(NodeFailure::Known)?
                        .to_owned();
                    (
                        Kernel::Predicate(predicate),
                        implementation,
                        "STATELESS".into(),
                        None,
                    )
                }
                _ => return Err(NodeFailure::Known),
            };
            if descriptor.implementation != implementation
                || descriptor.state_capability != capability
                || descriptor.checkpoint_schema != schema
            {
                return Err(NodeFailure::Known);
            }
            let plugin = json!({"definition":r,"implementation_fingerprint":implementation,"state_capability":capability,"checkpoint_schema_version":schema,"state":null});
            nodes.insert(
                scope.clone(),
                Node {
                    state: CalculationState::new(binding.clone()),
                    definition: definition.clone(),
                    kernel,
                    plugin,
                },
            );
        }
        Ok(Self {
            program,
            definitions,
            factors,
            artifact: artifact.clone(),
            nodes,
            failed: false,
        })
    }
    fn update_inner(&mut self, r: &NodeRequest) -> Result<Value> {
        let node = self.nodes.get_mut(&r.scope).ok_or(NodeFailure::Known)?;
        if r.binding != *node.state.cursor().binding()
            || r.revision != node.state.cursor().revision()
            || r.input_digest != record_fingerprint(&r.input_record())
            || self
                .program
                .instance_scope(r.bar.instrument_id(), &r.binding.digests()[2])
                != r.scope
        {
            return Err(NodeFailure::Known);
        }
        let definition = node.definition.to_record();
        let tagged = r.inputs.as_object().ok_or(NodeFailure::Known)?;
        let mut raw = serde_json::Map::new();
        for (name, value) in tagged {
            raw.insert(
                name.clone(),
                if value["type"] == "NULL" {
                    Value::Null
                } else {
                    value["value"].clone()
                },
            );
        }
        let raw = Value::Object(raw);
        if typed(&raw, &definition["inputs"])? != r.inputs {
            return Err(NodeFailure::Known);
        }
        let time = OnlyTimestamp::from_datetime(*r.bar.bar_end())
            .unix_nanos()
            .to_string();
        let prepared = node
            .state
            .prepare(&[&time], &r.input_digest)
            .map_err(known)?;
        let samples = node
            .state
            .cursor()
            .samples()
            .checked_add(1)
            .ok_or(NodeFailure::Known)?;
        let (outputs, state) = match &mut node.kernel {
            Kernel::Factor(factor) => {
                let values = tagged
                    .iter()
                    .map(|(k, v)| {
                        let v = match v["type"].as_str() {
                            Some("NULL") => ProgramValue::Missing,
                            Some("BOOLEAN") => ProgramValue::Boolean(
                                v["value"].as_bool().ok_or(NodeFailure::Known)?,
                            ),
                            Some("INTEGER") => ProgramValue::Integer(
                                v["value"].to_string().parse().map_err(known)?,
                            ),
                            Some("DECIMAL") => ProgramValue::Decimal(
                                v["value"]
                                    .as_str()
                                    .ok_or(NodeFailure::Known)?
                                    .parse()
                                    .map_err(known)?,
                            ),
                            _ => return Err(NodeFailure::Known),
                        };
                        Ok((k.clone(), v))
                    })
                    .collect::<Result<BTreeMap<_, _>>>()?;
                // Program positions start at zero; Calculation receipt samples
                // count the observation being committed and start at one.
                let input = ProgramInput::new(
                    &r.bar.instrument_id().to_string(),
                    node.state.cursor().samples(),
                    values,
                )
                .map_err(known)?;
                let values = factor
                    .step(&input)
                    .map_err(known)?
                    .into_iter()
                    .map(|(k, v)| (k, v.record()))
                    .collect::<serde_json::Map<_, _>>();
                (
                    typed(&Value::Object(values), &definition["outputs"])?,
                    factor.capture(),
                )
            }
            Kernel::Operator(stream) => {
                let outputs = typed(&stream.push(&raw).map_err(known)?, &definition["outputs"])?;
                let state = if node.plugin["state_capability"] == "STATELESS" {
                    Value::Null
                } else {
                    stream.checkpoint().map_err(known)?
                };
                (outputs, state)
            }
            Kernel::Predicate(predicate) => (
                typed(
                    &predicate.evaluate(&raw).map_err(known)?,
                    &definition["outputs"],
                )?,
                Value::Null,
            ),
        };
        let mut cursor = node.state.cursor().capture();
        cursor["revision"] = json!(r.revision.checked_add(1).ok_or(NodeFailure::Known)?);
        cursor["samples"] = json!(samples);
        cursor["last_event_ns"] = json!(time);
        let ready = samples
            >= definition["warmup"]["minimum_observations"]
                .as_u64()
                .ok_or(NodeFailure::Known)?;
        let receipt = json!({"cursor":cursor,"input_digest":r.input_digest,"outputs":outputs,"ready":ready,"quality_flags":[]});
        node.state.commit(&prepared, &receipt).map_err(known)?;
        node.plugin["state"] = state;
        Ok(json!({"receipt":receipt,"state_fingerprint":record_fingerprint(&node.plugin)}))
    }
}
impl NodePort for ProgramNodes {
    fn bindings(&self) -> Vec<ExecutionBinding> {
        self.program.bindings().values().cloned().collect()
    }
    fn update(&mut self, request: &NodeRequest) -> Result<Value> {
        if self.failed {
            return Err(NodeFailure::Unknown);
        }
        self.failed = true;
        let value = self.update_inner(request)?;
        self.failed = false;
        Ok(value)
    }
    fn capture(&mut self) -> Result<Value> {
        if self.failed {
            return Err(NodeFailure::Unknown);
        }
        let value = json!({"schema_version":1,"nodes":self.nodes.iter().map(|(scope,n)|{
            let state=n.state.capture();let d=&self.program.revision().descriptors()[&n.state.cursor().binding().digests()[2]];
            json!([scope,{"schema_version":1,"binding":n.state.cursor().binding().to_record(),"cursor":state["cursor"],"receipt":state["receipt"],"plugin_state":n.plugin,"state_fingerprint":record_fingerprint(&n.plugin),"state_capability":d.state_capability,"checkpoint_schema_version":d.checkpoint_schema,"definition_fingerprint":d.definition.fingerprint()}])
        }).collect::<Vec<_>>()});
        if value.to_string().len() > 8 * 1024 * 1024 {
            return Err(NodeFailure::Known);
        }
        Ok(value)
    }
    fn restore_candidate(&self, checkpoint: &Value) -> Result<Self> {
        if checkpoint.to_string().len() > 8 * 1024 * 1024 || checkpoint["schema_version"] != 1 {
            return Err(NodeFailure::Known);
        }
        let mut restored = Self::new(
            self.program.clone(),
            self.definitions.clone(),
            self.factors.clone(),
            &self.artifact,
        )?;
        let rows = checkpoint["nodes"]
            .as_array()
            .filter(|v| v.len() == restored.nodes.len())
            .ok_or(NodeFailure::Known)?;
        let mut seen = BTreeSet::new();
        for row in rows {
            let scope = row[0]
                .as_str()
                .filter(|_| row.as_array().map(Vec::len) == Some(2))
                .ok_or(NodeFailure::Known)?;
            if !seen.insert(scope) {
                return Err(NodeFailure::Known);
            }
            let node = restored.nodes.get_mut(scope).ok_or(NodeFailure::Known)?;
            let data = &row[1];
            if data["binding"] != node.state.cursor().binding().to_record()
                || data["state_fingerprint"] != record_fingerprint(&data["plugin_state"])
            {
                return Err(NodeFailure::Known);
            }
            for key in [
                "definition",
                "implementation_fingerprint",
                "state_capability",
                "checkpoint_schema_version",
            ] {
                if data["plugin_state"][key] != node.plugin[key] {
                    return Err(NodeFailure::Known);
                }
            }
            node.state.restore(&json!({"schema_version":1,"cursor":data["cursor"],"receipt":data["receipt"],"outcome":if data["receipt"].is_null(){"UNINITIALIZED"}else if data["receipt"]["ready"]==true{"READY"}else{"WARMING"},"reason":null})).map_err(known)?;
            if data["plugin_state"]["state_capability"] == "CHECKPOINTABLE"
                && node.state.cursor().samples() > 0
                && data["plugin_state"]["state"].is_null()
            {
                return Err(NodeFailure::Known);
            }
            if !data["plugin_state"]["state"].is_null() {
                match &mut node.kernel {
                    Kernel::Factor(p) => {
                        p.restore(&data["plugin_state"]["state"]).map_err(known)?
                    }
                    Kernel::Operator(s) => {
                        *s = s
                            .restored_candidate(&data["plugin_state"]["state"])
                            .map_err(known)?
                    }
                    Kernel::Predicate(_) => return Err(NodeFailure::Known),
                }
            }
            node.plugin = data["plugin_state"].clone();
        }
        // A full round-trip rejects ignored fields, inconsistent metadata and
        // state representations, including uninitialized extra producer state.
        if restored.capture()? != *checkpoint {
            return Err(NodeFailure::Known);
        }
        Ok(restored)
    }
}
