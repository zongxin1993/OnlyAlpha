//! Native Calculation graph orchestration around the bounded authored-source ABI.
//! The child owns supplied Factor arithmetic. Operators and graph order stay native.
use onlyalpha_calculation::product::{Definition, Graph, TypeDeclaration};
use onlyalpha_calculation_bridge::{
    Cancellation, Result, Worker, WorkerError, native_operators::OperatorCalculation,
};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    time::{Duration, Instant},
};
const WORK: usize = 8 * 1024 * 1024;
const INSTANCES: &str = "ONLYALPHA_CALCULATION_INSTANCES_RESOLVE_V1";
const SESSION: &str = "ONLYALPHA_AUTHORING_SESSION_V1";
const BOUND: &str = "ONLYALPHA_BOUND_CALCULATION_RESOLVE_V1";
const EVALUATE: &str = "ONLYALPHA_BOUND_CALCULATION_EVALUATE_V1";
fn invalid<T>(_: T) -> WorkerError {
    WorkerError::Invalid
}
fn text(value: &Value) -> Result<&str> {
    value.as_str().ok_or(WorkerError::Invalid)
}
fn rows(value: &Value) -> Result<&Vec<Value>> {
    value.as_array().ok_or(WorkerError::Invalid)
}
fn hash(value: &Value) -> String {
    onlyalpha_strategy::record_fingerprint(value)
}
fn exact(value: &Value, fields: &[&str]) -> Result<()> {
    if value
        .as_object()
        .is_none_or(|m| m.len() != fields.len() || fields.iter().any(|k| !m.contains_key(*k)))
    {
        return Err(WorkerError::Invalid);
    }
    Ok(())
}
pub struct ResearchProcess {
    worker: Worker,
    image: String,
    version: String,
    session: Option<(Value, Value)>,
    expires: Option<Instant>,
}
impl ResearchProcess {
    pub(super) fn new(worker: Worker, image: String, version: String) -> Self {
        Self {
            worker,
            image,
            version,
            session: None,
            expires: None,
        }
    }
    fn begin(&mut self, deadline: Duration) -> Result<()> {
        if deadline.is_zero() {
            return Err(WorkerError::Invalid);
        }
        self.expires = Some(
            Instant::now()
                .checked_add(deadline)
                .ok_or(WorkerError::Invalid)?,
        );
        Ok(())
    }
    fn remaining(&self, maximum: Duration) -> Result<Duration> {
        match self.worker.cancellation()?.state() {
            onlyalpha_calculation_bridge::ProcessState::Running => {}
            onlyalpha_calculation_bridge::ProcessState::Joined => {
                return Err(WorkerError::Rejected);
            }
            onlyalpha_calculation_bridge::ProcessState::Uncertain => {
                return Err(WorkerError::Unknown("PROCESS_OWNER_UNCERTAIN"));
            }
        }
        let remaining = self
            .expires
            .ok_or(WorkerError::Invalid)?
            .checked_duration_since(Instant::now())
            .filter(|v| !v.is_zero())
            .ok_or(WorkerError::Rejected)?;
        Ok(remaining.min(maximum))
    }
    pub fn cancellation(&self) -> Result<Cancellation> {
        self.worker.cancellation()
    }
    pub fn terminate(&self) -> Result<()> {
        self.worker.terminate()
    }
    pub fn handshake_research(&mut self, deadline: Duration) -> Result<()> {
        self.worker.handshake_research(deadline)
    }
    fn initialize(&mut self, request: &Value, deadline: Duration) -> Result<Value> {
        let sources = if request["sources"].is_array() {
            request["sources"].clone()
        } else {
            json!([request["source"]])
        };
        let input = json!({"schema_version":1,"contract":SESSION,"sources":sources,"core_artifact":request["core_artifact"],"target_artifact":request["target_artifact"]});
        if let Some((prior, result)) = &self.session {
            if *prior != input {
                return Err(WorkerError::Invalid);
            }
            return Ok(result.clone());
        }
        let result = self
            .worker
            .resolve_research(input.clone(), self.remaining(deadline)?)?;
        exact(
            &result,
            &[
                "schema_version",
                "contract",
                "algorithm_artifact",
                "core_artifact_sha256",
                "core_resources_fingerprint",
                "target_artifact_sha256",
                "target_resources_fingerprint",
                "source_artifacts",
                "isolation",
            ],
        )?;
        if result["schema_version"] != 1
            || result["contract"] != SESSION
            || result["algorithm_artifact"] != self.worker.artifact()
            || result["isolation"] != "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
        {
            return Err(WorkerError::Invalid);
        }
        self.session = Some((input, result.clone()));
        Ok(result)
    }
    fn native(&self, record: &Value) -> bool {
        record["type_id"]
            .as_str()
            .is_some_and(|id| id.starts_with("onlyalpha.operator."))
    }
    fn resolve_bound(
        &mut self,
        reference: &Value,
        parameters: &Value,
        bindings: &Value,
        deadline: Duration,
    ) -> Result<Value> {
        exact(reference, &["kind", "type_id", "semantic_version"])?;
        self.remaining(deadline)?;
        if self.native(reference) {
            if reference["kind"] != "INDICATOR" {
                return Err(WorkerError::Invalid);
            }
            let node = OperatorCalculation::resolve(
                text(&reference["type_id"])?,
                text(&reference["semantic_version"])?,
                parameters,
                bindings,
            )
            .map_err(invalid)?;
            let definition = node.definition().to_record();
            let mut implementations = vec![
                node.implementation_manifest("RESEARCH", &self.image)
                    .map_err(invalid)?,
            ];
            let trading = if node.state_capability() != "RESEARCH_ONLY" {
                let manifest = node
                    .implementation_manifest("TRADING", &self.image)
                    .map_err(invalid)?;
                let capability = json!({"implementation_fingerprint":manifest["implementation_fingerprint"],"state_capability":node.state_capability(),"checkpoint_schema_version":node.checkpoint_schema_version()});
                implementations.push(manifest);
                capability
            } else {
                Value::Null
            };
            return Ok(
                json!({"definition":definition,"definition_fingerprint":node.definition().fingerprint(),"type_declaration":node.type_declaration().map_err(invalid)?,"implementations":implementations,"trading_capability":trading}),
            );
        }
        if !matches!(reference["kind"].as_str(), Some("FACTOR" | "TARGET")) {
            return Err(WorkerError::Invalid);
        }
        let result=self.worker.resolve_research(json!({"schema_version":1,"contract":BOUND,"type_reference":reference,"parameters":parameters,"input_bindings":bindings}),self.remaining(deadline)?)?;
        exact(
            &result,
            &[
                "definition",
                "definition_fingerprint",
                "type_declaration",
                "implementations",
                "trading_capability",
            ],
        )?;
        let declaration =
            TypeDeclaration::from_record(&result["type_declaration"], WORK).map_err(invalid)?;
        let definition = declaration
            .validate_candidate(&result["definition"], WORK)
            .map_err(invalid)?;
        let record = definition.to_record();
        if result["definition_fingerprint"] != definition.fingerprint()
            || record["input_bindings"] != *bindings
            || ["kind", "type_id", "semantic_version"]
                .iter()
                .any(|key| record[*key] != reference[*key])
            || parameters
                .as_object()
                .ok_or(WorkerError::Invalid)?
                .iter()
                .any(|(key, value)| record["parameters"].get(key) != Some(value))
        {
            return Err(WorkerError::Invalid);
        }
        Ok(result)
    }
    fn base(&self, session: &Value, contract: &str) -> Value {
        json!({"schema_version":1,"contract":contract,"algorithm_artifact":session["algorithm_artifact"],"core_artifact_sha256":session["core_artifact_sha256"],"core_resources_fingerprint":session["core_resources_fingerprint"],"isolation":session["isolation"]})
    }
    fn resolve_factor(&mut self, request: &Value, deadline: Duration) -> Result<Value> {
        exact(
            request,
            &["schema_version", "source", "graph", "core_artifact"],
        )?;
        if request["schema_version"] != 1 {
            return Err(WorkerError::Invalid);
        }
        let session = self.initialize(request, deadline)?;
        let graph = Graph::from_record(&request["graph"], WORK).map_err(invalid)?;
        let mut implementations = BTreeMap::new();
        for definition in graph.ordered_nodes() {
            let d = definition.to_record();
            let reference = json!({"kind":d["kind"],"type_id":d["type_id"],"semantic_version":d["semantic_version"]});
            let actual =
                self.resolve_bound(&reference, &d["parameters"], &d["input_bindings"], deadline)?;
            if actual["definition"] != d {
                return Err(WorkerError::Invalid);
            }
            for implementation in rows(&actual["implementations"])? {
                implementations.insert(
                    text(&implementation["implementation_fingerprint"])?.to_owned(),
                    implementation.clone(),
                );
            }
        }
        let artifacts = rows(&session["source_artifacts"])?;
        if artifacts.len() != 1 {
            return Err(WorkerError::Invalid);
        }
        let artifact = &artifacts[0];
        let mut result = self.base(&session, "ONLYALPHA_PRIVATE_FACTOR_RESOLVE_V1");
        result["factor_revision_fingerprint"] = request["source"]["revision_fingerprint"].clone();
        result["source_artifact"] = artifact["source_artifact"].clone();
        result["validation_evidence"] = artifact["validation_evidence"].clone();
        result["private_calculations"] = artifact["private_calculations"].clone();
        result["source_projection_fingerprint"] = json!(hash(&request["source"]));
        result["graph"] = request["graph"].clone();
        result["implementations"] = json!(implementations.into_values().collect::<Vec<_>>());
        Ok(result)
    }
    fn resolve_instances(&mut self, request: &Value, deadline: Duration) -> Result<Value> {
        exact(
            request,
            &[
                "schema_version",
                "contract",
                "sources",
                "instances",
                "core_artifact",
                "operator_artifact",
                "target_artifact",
            ],
        )?;
        if request["schema_version"] != 1 || request["operator_artifact"]["sha256"] != self.image {
            return Err(WorkerError::Invalid);
        }
        let session = self.initialize(request, deadline)?;
        let mut pending = BTreeMap::new();
        for row in rows(&request["instances"])? {
            exact(
                row,
                &[
                    "instance_key",
                    "type_reference",
                    "parameters",
                    "published_outputs",
                    "input_bindings",
                    "primary_output",
                ],
            )?;
            let key = text(&row["instance_key"])?;
            if key.is_empty()
                || key.len() > 256
                || !key.bytes().enumerate().all(|(i, b)| {
                    b.is_ascii_lowercase() || i > 0 && (b.is_ascii_digit() || b == b'_')
                })
                || pending.insert(key.to_owned(), row.clone()).is_some()
            {
                return Err(WorkerError::Invalid);
            }
        }
        if pending.is_empty() || pending.len() > 128 {
            return Err(WorkerError::Invalid);
        }
        let mut completed: BTreeMap<String, Value> = BTreeMap::new();
        while !pending.is_empty() {
            let mut progress = Vec::new();
            for (key, row) in &pending {
                let mut parameters = serde_json::Map::new();
                for (name, parameter) in
                    row["parameters"].as_object().ok_or(WorkerError::Invalid)?
                {
                    exact(parameter, &["kind", "value"])?;
                    if parameter["kind"] != "FIXED" {
                        return Err(WorkerError::Invalid);
                    }
                    parameters.insert(name.clone(), parameter["value"].clone());
                }
                let mut bindings = serde_json::Map::new();
                let mut waiting = false;
                for binding in rows(&row["input_bindings"])? {
                    exact(binding, &["input_name", "source"])?;
                    let input = text(&binding["input_name"])?;
                    let source = &binding["source"];
                    let reference = if let Some(source) = source.as_str() {
                        json!({"node_fingerprint":null,"output_name":"value","source":source})
                    } else {
                        exact(source, &["kind", "instance_key", "output_name"])?;
                        if source["kind"] != "VARIABLE" {
                            return Err(WorkerError::Invalid);
                        }
                        let parent = text(&source["instance_key"])?;
                        let Some(parent_node) = completed.get(parent) else {
                            if !pending.contains_key(parent) {
                                return Err(WorkerError::Invalid);
                            }
                            waiting = true;
                            continue;
                        };
                        if !rows(&parent_node["published_outputs"])?
                            .contains(&source["output_name"])
                        {
                            return Err(WorkerError::Invalid);
                        }
                        json!({"node_fingerprint":parent_node["definition_fingerprint"],"output_name":source["output_name"],"source":null})
                    };
                    if bindings.insert(input.into(), reference).is_some() {
                        return Err(WorkerError::Invalid);
                    }
                }
                if waiting {
                    continue;
                }
                let mut result = self.resolve_bound(
                    &row["type_reference"],
                    &Value::Object(parameters),
                    &Value::Object(bindings),
                    deadline,
                )?;
                let published = rows(&row["published_outputs"])?;
                let available = rows(&result["definition"]["outputs"])?
                    .iter()
                    .map(|p| p["name"].clone())
                    .collect::<Vec<_>>();
                let mut unique = BTreeSet::new();
                if published.is_empty()
                    || published
                        .iter()
                        .any(|p| !available.contains(p) || !unique.insert(p.to_string()))
                    || !row["primary_output"].is_null()
                        && !published.contains(&row["primary_output"])
                {
                    return Err(WorkerError::Invalid);
                }
                result["instance_key"] = json!(key);
                result["published_outputs"] = row["published_outputs"].clone();
                completed.insert(key.clone(), result);
                progress.push(key.clone());
            }
            if progress.is_empty() {
                return Err(WorkerError::Invalid);
            }
            for key in progress {
                pending.remove(&key);
            }
        }
        let nodes = completed
            .into_values()
            .map(|mut row| {
                let m = row.as_object_mut().expect("constructed object");
                m.remove("published_outputs");
                m.remove("trading_capability");
                row
            })
            .collect::<Vec<_>>();
        let mut result = self.base(&session, INSTANCES);
        result["nodes"] = json!(nodes);
        result["source_artifacts"] = session["source_artifacts"].clone();
        result["operator_artifact_sha256"] = json!(self.image);
        result["operator_resources_fingerprint"] = json!(hash(
            &json!([{"relative_path":"bin/onlyalpha-backend","byte_sha256":self.image}])
        ));
        result["target_artifact_sha256"] = session["target_artifact_sha256"].clone();
        result["target_resources_fingerprint"] = session["target_resources_fingerprint"].clone();
        Ok(result)
    }
    pub fn resolve_research(&mut self, request: Value, deadline: Duration) -> Result<Value> {
        self.begin(deadline)?;
        let result = self.resolve_internal(request, deadline)?;
        self.remaining(deadline)?;
        if result.to_string().len() > WORK {
            return Err(WorkerError::Invalid);
        }
        Ok(result)
    }
    fn resolve_internal(&mut self, request: Value, deadline: Duration) -> Result<Value> {
        if request.to_string().len() > WORK || request["schema_version"] != 1 {
            return Err(WorkerError::Invalid);
        }
        match request["contract"].as_str() {
            Some(INSTANCES) => self.resolve_instances(&request, deadline),
            Some("ONLYALPHA_TRADING_NODE_CAPABILITIES_V1") => {
                self.trading_capabilities(&request, deadline)
            }
            None => self.resolve_factor(&request, deadline),
            _ => Err(WorkerError::Invalid),
        }
    }
}
impl ResearchProcess {
    fn trading_capabilities(&mut self, request: &Value, deadline: Duration) -> Result<Value> {
        exact(
            request,
            &["schema_version", "contract", "sources", "definitions"],
        )?;
        self.initialize(request, deadline)?;
        let mut nodes = BTreeMap::new();
        for record in rows(&request["definitions"])? {
            let definition = Definition::from_record(record, WORK).map_err(invalid)?;
            let d = definition.to_record();
            let reference = json!({"kind":d["kind"],"type_id":d["type_id"],"semantic_version":d["semantic_version"]});
            let actual =
                self.resolve_bound(&reference, &d["parameters"], &d["input_bindings"], deadline)?;
            let capability = &actual["trading_capability"];
            if actual["definition"] != d || !capability.is_object() {
                return Err(WorkerError::Invalid);
            }
            let id = definition.fingerprint();
            if nodes.insert(id.clone(),json!({"node_fingerprint":id,"implementation_fingerprint":capability["implementation_fingerprint"],"state_capability":capability["state_capability"],"checkpoint_schema_version":capability["checkpoint_schema_version"]})).is_some(){return Err(WorkerError::Invalid);}
        }
        if nodes.is_empty() || nodes.len() > 128 {
            return Err(WorkerError::Invalid);
        }
        Ok(
            json!({"schema_version":1,"contract":"ONLYALPHA_TRADING_NODE_CAPABILITIES_V1","nodes":nodes.into_values().collect::<Vec<_>>(),"isolation":"LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"}),
        )
    }
    fn evaluate_bound(
        &mut self,
        definition: &Value,
        columns: &Value,
        include_trading: bool,
        deadline: Duration,
    ) -> Result<Value> {
        if self.native(definition) {
            let node = OperatorCalculation::from_record(definition).map_err(invalid)?;
            // A TIME axis is not proof of a canonical cross-section cohort.
            if node.state_capability() == "RESEARCH_ONLY" {
                return Err(WorkerError::Invalid);
            }
            let mut interrupted = None;
            let result =
                node.evaluate_batch_controlled(columns, || match self.remaining(deadline) {
                    Ok(_) => Ok(()),
                    Err(error) => {
                        interrupted = Some(error);
                        Err("NATIVE_OPERATOR_INTERRUPTED")
                    }
                });
            if let Some(error) = interrupted {
                return Err(error);
            }
            let values = result.map_err(invalid)?;
            let mut trading = Value::Null;
            let mut trading_implementation = Value::Null;
            if include_trading {
                let mut stream = node.stream().map_err(invalid)?;
                let ports = columns.as_object().ok_or(WorkerError::Invalid)?;
                let count = ports
                    .values()
                    .next()
                    .and_then(Value::as_array)
                    .ok_or(WorkerError::Invalid)?
                    .len();
                let mut output: serde_json::Map<String, Value> = values
                    .as_object()
                    .ok_or(WorkerError::Invalid)?
                    .keys()
                    .map(|k| (k.clone(), json!([])))
                    .collect();
                for i in 0..count {
                    self.remaining(deadline)?;
                    let inputs = ports
                        .iter()
                        .map(|(name, c)| {
                            Ok((
                                name.clone(),
                                rows(c)?.get(i).ok_or(WorkerError::Invalid)?.clone(),
                            ))
                        })
                        .collect::<Result<serde_json::Map<_, _>>>()?;
                    let observed = stream.push(&Value::Object(inputs)).map_err(invalid)?;
                    for (name, values) in &mut output {
                        values
                            .as_array_mut()
                            .ok_or(WorkerError::Invalid)?
                            .push(observed[name].clone());
                    }
                }
                trading = Value::Object(output);
                trading_implementation = node
                    .implementation_manifest("TRADING", &self.image)
                    .map_err(invalid)?["implementation_fingerprint"]
                    .clone();
            }
            return Ok(
                json!({"values":values,"implementation_fingerprint":node.implementation_manifest("RESEARCH",&self.image).map_err(invalid)?["implementation_fingerprint"],"trading_values":trading,"trading_implementation_fingerprint":trading_implementation}),
            );
        }
        self.worker.evaluate_research(json!({"schema_version":1,"contract":EVALUATE,"definition":definition,"input_columns":columns,"include_trading":include_trading}),self.remaining(deadline)?)
    }
    fn evaluate_graph(
        &mut self,
        graph: &Graph,
        input: &Value,
        deadline: Duration,
    ) -> Result<Value> {
        let input_rows = rows(input)?;
        if input_rows.is_empty() || input_rows.len() > 8192 {
            return Err(WorkerError::Invalid);
        }
        let mut axis = Vec::new();
        for row in input_rows {
            exact(row, &["at_ns", "values"])?;
            let at = row["at_ns"].as_u64().ok_or(WorkerError::Invalid)?;
            if row["values"].as_object().is_none_or(|m| {
                m.keys()
                    .any(|k| !["open", "high", "low", "close", "volume"].contains(&k.as_str()))
            }) || axis.last().is_some_and(|previous| *previous >= at)
            {
                return Err(WorkerError::Invalid);
            }
            axis.push(at);
        }
        if axis.len() > 1 {
            let stride = axis[1] - axis[0];
            if axis.windows(2).any(|w| w[1] - w[0] != stride) {
                return Err(WorkerError::Invalid);
            }
        }
        let mut remaining = WORK
            .checked_sub(input.to_string().len())
            .ok_or(WorkerError::Invalid)?;
        let mut workspace: BTreeMap<String, Value> = BTreeMap::new();
        let mut outputs = BTreeMap::new();
        for definition in graph.ordered_nodes() {
            let d = definition.to_record();
            let mut inputs = serde_json::Map::new();
            for (name, binding) in d["input_bindings"]
                .as_object()
                .ok_or(WorkerError::Invalid)?
            {
                let values = if let Some(parent) = binding["node_fingerprint"].as_str() {
                    workspace
                        .get(parent)
                        .and_then(|p| p.get(text(&binding["output_name"]).ok()?))
                        .ok_or(WorkerError::Invalid)?
                        .clone()
                } else {
                    let source = text(&binding["source"])?;
                    let name = source.strip_prefix("bar.").unwrap_or(source);
                    if !["open", "high", "low", "close", "volume"].contains(&name) {
                        return Err(WorkerError::Invalid);
                    }
                    json!(
                        input_rows
                            .iter()
                            .map(|row| row["values"].get(name).cloned().ok_or(WorkerError::Invalid))
                            .collect::<Result<Vec<_>>>()?
                    )
                };
                inputs.insert(name.clone(), values);
            }
            let actual = self.evaluate_bound(&d, &Value::Object(inputs), false, deadline)?;
            exact(
                &actual,
                &[
                    "values",
                    "implementation_fingerprint",
                    "trading_values",
                    "trading_implementation_fingerprint",
                ],
            )?;
            remaining = remaining
                .checked_sub(actual.to_string().len())
                .ok_or(WorkerError::Invalid)?;
            let values = actual["values"].as_object().ok_or(WorkerError::Invalid)?;
            let ports = rows(&d["outputs"])?;
            if values.len() != ports.len()
                || ports.iter().any(|p| {
                    values
                        .get(p["name"].as_str().unwrap_or(""))
                        .and_then(Value::as_array)
                        .is_none_or(|v| v.len() != input_rows.len())
                })
            {
                return Err(WorkerError::Invalid);
            }
            let id = definition.fingerprint();
            workspace.insert(id.clone(), actual["values"].clone());
            outputs.insert(id.clone(),json!({"node_fingerprint":id,"implementation_fingerprint":actual["implementation_fingerprint"],"values":actual["values"]}));
        }
        Ok(
            json!({"schema_version":1,"graph_fingerprint":graph.fingerprint(),"input_fingerprint":hash(input),"axis":axis,"outputs":outputs.into_values().collect::<Vec<_>>()}),
        )
    }
    fn graph_from_nodes(nodes: &[Value], targets: bool) -> Result<Option<Graph>> {
        let nodes = nodes
            .iter()
            .filter(|n| (n["definition"]["kind"] == "TARGET") == targets)
            .map(|n| json!({"alias":n["instance_key"],"definition":n["definition"]}))
            .collect::<Vec<_>>();
        if nodes.is_empty() {
            return Ok(None);
        }
        Graph::from_record(&json!({"schema_version":1,"nodes":nodes}), WORK)
            .map(Some)
            .map_err(invalid)
    }
    pub fn evaluate_research(&mut self, request: Value, deadline: Duration) -> Result<Value> {
        if request.to_string().len() > WORK {
            return Err(WorkerError::Invalid);
        }
        self.begin(deadline)?;
        let mut resolved = self.resolve_internal(request["resolution"].clone(), deadline)?;
        let evaluation = match request["contract"].as_str() {
            Some("ONLYALPHA_CALCULATION_PLANES_OBSERVATION_V1") => {
                exact(&request, &["contract", "resolution", "rows"])?;
                let nodes = rows(&resolved["nodes"])?.clone();
                let feature = match Self::graph_from_nodes(&nodes, false)? {
                    Some(graph) => self.evaluate_graph(&graph, &request["rows"], deadline)?,
                    None => Value::Null,
                };
                let targets = match Self::graph_from_nodes(&nodes, true)? {
                    Some(graph) => self.evaluate_graph(&graph, &request["rows"], deadline)?,
                    None => Value::Null,
                };
                let mut capabilities = Vec::new();
                for node in nodes.iter().filter(|n| n["definition"]["kind"] != "TARGET") {
                    let d = &node["definition"];
                    let reference = json!({"kind":d["kind"],"type_id":d["type_id"],"semantic_version":d["semantic_version"]});
                    let actual = self.resolve_bound(
                        &reference,
                        &d["parameters"],
                        &d["input_bindings"],
                        deadline,
                    )?;
                    let mut capability = actual["trading_capability"].clone();
                    if !capability.is_object() {
                        return Err(WorkerError::Invalid);
                    }
                    capability["node_fingerprint"] = node["definition_fingerprint"].clone();
                    capabilities.push(capability);
                }
                capabilities
                    .sort_by_key(|c| c["node_fingerprint"].as_str().unwrap_or("").to_owned());
                json!({"schema_version":1,"contract":"ONLYALPHA_CALCULATION_PLANES_OBSERVATION_V1","input_fingerprint":hash(&request["rows"]),"axis":rows(&request["rows"] )?.iter().map(|r|r["at_ns"].clone()).collect::<Vec<_>>(),"feature":feature,"targets":targets,"trading_capabilities":capabilities})
            }
            Some("ONLYALPHA_CALCULATION_NODE_PROFILE_OBSERVATION_V1") => {
                self.node_profiles(&request, &resolved, deadline)?
            }
            None => {
                exact(&request, &["resolution", "rows", "root_fingerprint"])?;
                let graph =
                    Graph::from_record(&request["resolution"]["graph"], WORK).map_err(invalid)?;
                let root = text(&request["root_fingerprint"])?;
                let definition = graph
                    .ordered_nodes()
                    .find(|d| d.fingerprint() == root)
                    .ok_or(WorkerError::Invalid)?
                    .to_record();
                if definition["kind"] != "FACTOR"
                    || definition["type_id"] != request["resolution"]["source"]["factor_id"]
                    || rows(&definition["outputs"])?.len() != 1
                    || definition["outputs"][0]["name"] != "value"
                {
                    return Err(WorkerError::Invalid);
                }
                let mut result = self.evaluate_graph(&graph, &request["rows"], deadline)?;
                result["feature"] = rows(&result["outputs"])?
                    .iter()
                    .find(|r| r["node_fingerprint"] == root)
                    .ok_or(WorkerError::Invalid)?["values"]["value"]
                    .clone();
                result
            }
            _ => return Err(WorkerError::Invalid),
        };
        self.remaining(deadline)?;
        resolved["evaluation"] = evaluation;
        if resolved.to_string().len() > WORK {
            return Err(WorkerError::Invalid);
        }
        Ok(resolved)
    }
}
impl ResearchProcess {
    fn node_profiles(
        &mut self,
        request: &Value,
        resolved: &Value,
        deadline: Duration,
    ) -> Result<Value> {
        exact(
            request,
            &["schema_version", "contract", "resolution", "nodes"],
        )?;
        if request["schema_version"].as_u64() != Some(1) {
            return Err(WorkerError::Invalid);
        }
        let available = rows(&resolved["nodes"])?
            .iter()
            .map(|n| {
                Ok((
                    text(&n["definition_fingerprint"])?.to_owned(),
                    n["definition"].clone(),
                ))
            })
            .collect::<Result<BTreeMap<_, _>>>()?;
        let mut seen = BTreeSet::new();
        let mut result = Vec::new();
        let mut work = 0usize;
        for node in rows(&request["nodes"])? {
            exact(node, &["definition", "cases"])?;
            let definition = Definition::from_record(&node["definition"], WORK).map_err(invalid)?;
            let id = definition.fingerprint();
            if available.get(&id) != Some(&definition.to_record()) || !seen.insert(id.clone()) {
                return Err(WorkerError::Invalid);
            }
            let d = definition.to_record();
            let mut cases = Vec::new();
            let mut research_pin = Value::Null;
            let mut trading_pin = Value::Null;
            let mut names = BTreeSet::new();
            let profiles = rows(&node["cases"])?;
            if profiles.is_empty() || profiles.len() > 32 {
                return Err(WorkerError::Invalid);
            }
            for case in profiles {
                exact(case, &["case_id", "inputs"])?;
                let name = text(&case["case_id"])?;
                if name.is_empty()
                    || name.len() > 255
                    || name.chars().any(|c| c.is_whitespace() || c.is_control())
                    || !names.insert(name.to_owned())
                {
                    return Err(WorkerError::Invalid);
                }
                let inputs = rows(&case["inputs"])?;
                work = work
                    .checked_add(inputs.len())
                    .filter(|n| *n <= 8192)
                    .ok_or(WorkerError::Invalid)?;
                if inputs.is_empty() {
                    return Err(WorkerError::Invalid);
                }
                let mut columns = serde_json::Map::new();
                for port in rows(&d["inputs"])? {
                    let name = text(&port["name"])?;
                    let mut column = Vec::new();
                    for input in inputs {
                        let v = input.get(name).ok_or(WorkerError::Invalid)?;
                        if onlyalpha_calculation::product::normalize_scalar(v, WORK)
                            .map_err(invalid)?
                            != *v
                            || v["type"] != "NULL" && v["type"] != port["data_type"]
                            || v["type"] == "NULL" && port["nullable"] != true
                        {
                            return Err(WorkerError::Invalid);
                        }
                        column.push(if v["type"] == "NULL" {
                            Value::Null
                        } else {
                            v["value"].clone()
                        });
                    }
                    columns.insert(name.into(), json!(column));
                }
                if inputs
                    .iter()
                    .any(|i| i.as_object().is_none_or(|m| m.len() != columns.len()))
                {
                    return Err(WorkerError::Invalid);
                }
                let observed = self.evaluate_bound(&d, &Value::Object(columns), true, deadline)?;
                if observed["trading_values"].is_null() {
                    return Err(WorkerError::Invalid);
                }
                research_pin = observed["implementation_fingerprint"].clone();
                trading_pin = observed["trading_implementation_fingerprint"].clone();
                let encode = |columns: &Value| -> Result<Value> {
                    let mut result = Vec::new();
                    for i in 0..inputs.len() {
                        let mut output = serde_json::Map::new();
                        for port in rows(&d["outputs"])? {
                            let name = text(&port["name"])?;
                            let v = rows(&columns[name])?.get(i).ok_or(WorkerError::Invalid)?;
                            let scalar = if v.is_null() {
                                json!({"type":"NULL","value":null})
                            } else {
                                json!({"type":port["data_type"],"value":v})
                            };
                            output.insert(
                                name.into(),
                                onlyalpha_calculation::product::normalize_scalar(&scalar, WORK)
                                    .map_err(invalid)?,
                            );
                        }
                        result.push(Value::Object(output));
                    }
                    Ok(json!(result))
                };
                cases.push(json!({"case_id":case["case_id"],"inputs":inputs,"research_outputs":encode(&observed["values"] )?,"trading_outputs":encode(&observed["trading_values"] )?}));
            }
            if cases.is_empty() {
                return Err(WorkerError::Invalid);
            }
            result.push(json!({"node_fingerprint":id,"research_implementation_fingerprint":research_pin,"trading_implementation_fingerprint":trading_pin,"cases":cases}));
        }
        if result.is_empty() || result.len() > 128 {
            return Err(WorkerError::Invalid);
        }
        Ok(
            json!({"schema_version":1,"contract":"ONLYALPHA_CALCULATION_NODE_PROFILE_OBSERVATION_V1","nodes":result}),
        )
    }
    pub fn prepare_research(&mut self, mut request: Value, deadline: Duration) -> Result<Value> {
        self.begin(deadline)?;
        if self.session.is_some()
            || request.to_string().len() > WORK
            || request["schema_version"].as_u64() != Some(1)
            || request["operator_artifact"]["sha256"] != self.image
        {
            return Err(WorkerError::Invalid);
        }
        if request["contract"] == "ONLYALPHA_STRATEGY_EXECUTABLE_PREPARATION_V1" {
            exact(
                &request,
                &[
                    "schema_version",
                    "contract",
                    "source",
                    "graph",
                    "core_artifact",
                    "operator_artifact",
                    "target_artifact",
                ],
            )?;
        } else {
            exact(
                &request,
                &[
                    "schema_version",
                    "source",
                    "graph",
                    "core_artifact",
                    "operator_artifact",
                ],
            )?;
        }
        request
            .as_object_mut()
            .ok_or(WorkerError::Invalid)?
            .remove("operator_artifact");
        let graph = Graph::from_record(&request["graph"], WORK).map_err(invalid)?;
        let mut native = Vec::new();
        for definition in graph.ordered_nodes() {
            let d = definition.to_record();
            if self.native(&d) {
                let node = OperatorCalculation::from_record(&d).map_err(invalid)?;
                native.push(
                    node.implementation_manifest("RESEARCH", &self.image)
                        .map_err(invalid)?,
                );
                if node.state_capability() != "RESEARCH_ONLY" {
                    native.push(
                        node.implementation_manifest("TRADING", &self.image)
                            .map_err(invalid)?,
                    );
                }
            }
        }
        let mut result = self
            .worker
            .prepare_research(request, self.remaining(deadline)?)?;
        let mut implementations = rows(&result["implementations"])?
            .iter()
            .cloned()
            .chain(native)
            .map(|i| Ok((text(&i["implementation_fingerprint"])?.to_owned(), i)))
            .collect::<Result<BTreeMap<_, _>>>()?;
        result["implementations"] = json!(
            implementations
                .values_mut()
                .map(|i| i.clone())
                .collect::<Vec<_>>()
        );
        let provider = onlyalpha_calculation_bridge::native_operators::provider_record(
            &self.image,
            &self.version,
        )
        .map_err(invalid)?;
        result["operator_provider_manifest"] = provider["manifest"].clone();
        result["operator_calculations"] = provider["calculations"].clone();
        self.remaining(deadline)?;
        result["operator_artifact_sha256"] = json!(self.image);
        result["operator_resources_fingerprint"] = json!(hash(
            &json!([{"relative_path":"bin/onlyalpha-backend","byte_sha256":self.image}])
        ));
        Ok(result)
    }
}
