//! Authoring-to-Calculation lowering only; no Run, Freeze or Strategy identity.
use super::{WORK, canonical_expression};
use crate::application::private_strategy::Definition as Strategy;
use onlyalpha_calculation::product::{Definition, Graph, TypeDeclaration};
use onlyalpha_calculation_bridge::native_predicates::PredicateCalculation;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "PRIVATE_STRATEGY_DECISION_GRAPH_INVALID";
const UNAVAILABLE: &str = "PRIVATE_STRATEGY_DECISION_GRAPH_UNAVAILABLE";

pub struct DecisionGraph {
    graph: Graph,
    signals: Value,
    source: Value,
}
struct Builder {
    variables: BTreeMap<String, Definition>,
    nodes: BTreeMap<String, Value>,
}
impl DecisionGraph {
    /// The caller separately proves these exact installed observations against
    /// the held Runtime and immutable authoring composition. Values grant no authority.
    pub fn derive(strategy: &Strategy, observations: &Value) -> Result<Self> {
        let strategy = strategy.to_record();
        let mut builder = Builder::resolved(&strategy["calculations"], observations)?;
        let mut signals = json!({"schema_version":1,"missing_decision":"FALSE"});
        for (role, name, expression) in [
            ("eligibility", "eligibility", &strategy["eligibility"]),
            ("entry", "entry_signal", &strategy["signals"]["entry"]),
            ("exit", "exit_signal", &strategy["signals"]["exit"]),
        ] {
            let root =
                builder.expression(&canonical_expression(expression).map_err(|_| INVALID)?, 0)?;
            let id = builder.predicate(
                &format!("terminal.{name}"),
                json!({}),
                json!({"value":reference(&root)}),
            )?;
            signals[role] = json!({"node_fingerprint":id,"output_name":"value"});
        }
        let graph = Graph::from_record(
            &json!({"schema_version":1,"nodes":builder.nodes.into_values().collect::<Vec<_>>()}),
            WORK,
        )
        .map_err(|_| INVALID)?;
        let source = source_semantics(
            &strategy,
            json!({"kind":strategy["universe"]["kind"],"instrument_ids":strategy["universe"]["instruments"],"registered_id":null}),
            &strategy["market_input"]["bar_semantic"],
        )?;
        Ok(Self {
            graph,
            signals,
            source,
        })
    }
    /// Pure source relation; this grants no authoring, dataset or Run authority.
    pub(super) fn require_source(&self, definition: &super::ResearchDefinition) -> Result<()> {
        let record = definition.record();
        let source = source_semantics(
            record,
            record["dataset"]["universe"].clone(),
            &record["dataset"]["bar_semantic"],
        )?;
        if source != self.source {
            return Err(INVALID);
        }
        Ok(())
    }
    /// Finite Research value propagation over the complete graph. Numerical
    /// columns come from one actual backend execution; they are not permits.
    pub fn evaluate_columns(&self, rows: &Value, numerical: &Value) -> Result<Value> {
        evaluate_graph_columns(&self.graph, rows, numerical)
    }

    /// Exact finite input axis. Warmup precedes the observation interval; future
    /// Target rows stop at its end and can never authorize an expanded read.
    pub fn input_window(&self, context: &super::Context, bar_ns: u64) -> Result<Value> {
        use onlyalpha_domain::time::{OnlyTimestamp, OnlyUtcDateTime};
        let ns = |key: &str| -> Result<u64> {
            let time = context.record()[key]
                .as_str()
                .ok_or(INVALID)?
                .parse::<OnlyUtcDateTime>()
                .map_err(|_| INVALID)?;
            OnlyTimestamp::from_datetime(time)
                .unix_nanos()
                .to_string()
                .parse()
                .map_err(|_| INVALID)
        };
        let start = ns("start")?;
        let end = ns("end")?;
        let mut target_sources = Vec::new();
        for target in context.record()["targets"].as_array().ok_or(INVALID)? {
            for binding in target["input_bindings"].as_array().ok_or(INVALID)? {
                if let Some(value) = binding["source"].as_str() {
                    target_sources.push(value);
                }
            }
        }
        let mut window = canonical_input_window(&self.graph, start, end, bar_ns, target_sources)?;
        window["research_context_fingerprint"] = json!(context.fingerprint()?);
        Ok(window)
    }
    pub(crate) fn target_graph(context: &super::Context, observations: &Value) -> Result<Graph> {
        let builder = Builder::resolved(&context.record()["targets"], observations)?;
        Graph::from_record(
            &json!({"schema_version":1,"nodes":builder.nodes.into_values().collect::<Vec<_>>()}),
            WORK,
        )
        .map_err(|_| INVALID)
    }
    pub fn graph(&self) -> &Graph {
        &self.graph
    }
    pub fn record(&self) -> Value {
        json!({"schema_version":1,"decision_graph_fingerprint":self.graph.fingerprint(),"decision_graph":self.graph.to_record(),"signal_semantics":self.signals})
    }
}
pub(super) fn evaluate_graph_columns(
    graph: &Graph,
    rows: &Value,
    numerical: &Value,
) -> Result<Value> {
    if rows
        .to_string()
        .len()
        .saturating_add(numerical.to_string().len())
        > WORK
    {
        return Err(UNAVAILABLE);
    }
    let rows = rows
        .as_array()
        .filter(|r| !r.is_empty() && r.len() <= 8192)
        .ok_or(INVALID)?;
    let mut axis = Vec::with_capacity(rows.len());
    for row in rows {
        crate::application::private_strategy::exact(row, &["at_ns", "values"])
            .map_err(|_| INVALID)?;
        let at = row["at_ns"].as_u64().ok_or(INVALID)?;
        if axis.last().is_some_and(|previous| *previous >= at) || !row["values"].is_object() {
            return Err(INVALID);
        }
        axis.push(at);
    }
    let mut provided = BTreeMap::new();
    for column in numerical.as_array().ok_or(INVALID)? {
        crate::application::private_strategy::exact(column, &["node_fingerprint", "values"])
            .map_err(|_| INVALID)?;
        let id = column["node_fingerprint"].as_str().ok_or(INVALID)?;
        if provided.insert(id, column["values"].clone()).is_some() {
            return Err(INVALID);
        }
    }
    let mut workspace: BTreeMap<String, Value> = BTreeMap::new();
    for definition in graph.ordered_nodes() {
        let id = definition.fingerprint();
        let d = definition.to_record();
        let values = if d["kind"] == "PREDICATE" {
            let calculation = PredicateCalculation::from_record(&d).map_err(|_| INVALID)?;
            let mut output = Vec::with_capacity(rows.len());
            for (index, row) in rows.iter().enumerate() {
                let mut inputs = serde_json::Map::new();
                for (name, binding) in d["input_bindings"].as_object().ok_or(INVALID)? {
                    let value = if let Some(parent) = binding["node_fingerprint"].as_str() {
                        workspace
                            .get(parent)
                            .and_then(|p| p.get(binding["output_name"].as_str()?))
                            .and_then(|c| c.as_array())
                            .and_then(|c| c.get(index))
                            .ok_or(INVALID)?
                            .clone()
                    } else {
                        let source = binding["source"]
                            .as_str()
                            .ok_or(INVALID)?
                            .strip_prefix("bar.")
                            .ok_or(INVALID)?;
                        row["values"].get(source).ok_or(INVALID)?.clone()
                    };
                    inputs.insert(name.clone(), value);
                }
                output.push(
                    calculation
                        .evaluate(&Value::Object(inputs))
                        .map_err(|_| INVALID)?["value"]
                        .clone(),
                );
            }
            json!({"value":output})
        } else {
            provided.remove(id.as_str()).ok_or(INVALID)?
        };
        check_columns(&values, &d["outputs"], rows.len())?;
        workspace.insert(id, values);
    }
    if !provided.is_empty() {
        return Err(INVALID);
    }
    let outputs=workspace.into_iter().map(|(node_fingerprint,values)|json!({"node_fingerprint":node_fingerprint,"values":values})).collect::<Vec<_>>();
    Ok(
        json!({"schema_version":1,"graph_fingerprint":graph.fingerprint(),"input_fingerprint":crate::application::factor_content::hash(&json!(rows))?,"axis":axis,"outputs":outputs}),
    )
}

fn source_semantics(record: &Value, universe: Value, bar_semantic: &Value) -> Result<Value> {
    let mut calculations = record["calculations"].as_array().ok_or(INVALID)?.clone();
    for calculation in &mut calculations {
        calculation
            .as_object_mut()
            .ok_or(INVALID)?
            .remove("primary_output");
    }
    calculations.sort_by_cached_key(|c| c["instance_key"].as_str().unwrap_or_default().to_owned());
    Ok(
        json!({"calculations":calculations,"eligibility":canonical_expression(&record["eligibility"]).map_err(|_|INVALID)?,"signals":{"entry":canonical_expression(&record["signals"]["entry"]).map_err(|_|INVALID)?,"exit":canonical_expression(&record["signals"]["exit"]).map_err(|_|INVALID)?},"universe":universe,"bar_semantic":bar_semantic}),
    )
}
fn check_columns(values: &Value, ports: &Value, count: usize) -> Result<()> {
    let values = values.as_object().ok_or(INVALID)?;
    let ports = ports.as_array().ok_or(INVALID)?;
    if values.len() != ports.len() {
        return Err(INVALID);
    }
    for port in ports {
        let name = port["name"].as_str().ok_or(INVALID)?;
        let data = port["data_type"].as_str().ok_or(INVALID)?;
        let column = values
            .get(name)
            .and_then(Value::as_array)
            .filter(|c| c.len() == count)
            .ok_or(INVALID)?;
        for value in column {
            if value.is_null() {
                if port["nullable"] != true {
                    return Err(INVALID);
                }
                continue;
            }
            if (data == "DECIMAL" && !value.is_string())
                || (data == "BOOLEAN" && !value.is_boolean())
            {
                return Err(INVALID);
            }
            onlyalpha_calculation::product::normalize_scalar(
                &json!({"type":data,"value":value}),
                WORK,
            )
            .map_err(|_| INVALID)?;
        }
    }
    Ok(())
}

fn reference(id: &str) -> Value {
    json!({"node_fingerprint":id,"output_name":"value","source":null})
}
impl Builder {
    fn resolved(instances: &Value, observations: &Value) -> Result<Self> {
        if observations.to_string().len() > WORK {
            return Err(UNAVAILABLE);
        }
        let instances = instances.as_array().ok_or(INVALID)?;
        let observed = observations.as_array().ok_or(INVALID)?;
        if instances.len() != observed.len() {
            return Err(INVALID);
        }
        let mut builder = Builder {
            variables: BTreeMap::new(),
            nodes: BTreeMap::new(),
        };
        let mut declarations = BTreeMap::new();
        for row in observed {
            crate::application::private_strategy::exact(
                row,
                &[
                    "instance_key",
                    "definition",
                    "definition_fingerprint",
                    "type_declaration",
                ],
            )
            .map_err(|_| INVALID)?;
            let key = row["instance_key"].as_str().ok_or(INVALID)?;
            let declaration = TypeDeclaration::from_record(&row["type_declaration"], WORK)
                .map_err(|_| INVALID)?;
            let definition = declaration
                .validate_candidate(&row["definition"], WORK)
                .map_err(|_| INVALID)?;
            let record = definition.to_record();
            let descriptor = declaration.descriptor();
            for field in [
                "inputs",
                "outputs",
                "missing_values",
                "timestamp",
                "numeric",
                "factor_kind",
            ] {
                if record[field] != descriptor[field] {
                    return Err(INVALID);
                }
            }
            if record["kind"] == "PREDICATE"
                || row["definition_fingerprint"] != definition.fingerprint()
                || declarations.insert(key.to_owned(), declaration).is_some()
                || builder
                    .variables
                    .insert(key.to_owned(), definition)
                    .is_some()
            {
                return Err(INVALID);
            }
        }
        for instance in instances {
            let key = instance["instance_key"].as_str().ok_or(INVALID)?;
            let definition = builder.variables.get(key).ok_or(INVALID)?;
            let record = definition.to_record();
            for field in ["kind", "type_id", "semantic_version"] {
                if record[field] != instance["type_reference"][field] {
                    return Err(INVALID);
                }
            }
            let declaration = declarations.get(key).ok_or(INVALID)?.to_record();
            let specs = declaration["descriptor"]["parameters"]
                .as_array()
                .ok_or(INVALID)?;
            let defaults = declaration["parameter_values"].as_array().ok_or(INVALID)?;
            let fixed = instance["parameters"].as_object().ok_or(INVALID)?;
            let mut expected = serde_json::Map::new();
            for (spec, default) in specs.iter().zip(defaults) {
                let name = spec["name"].as_str().ok_or(INVALID)?;
                let value = match fixed.get(name) {
                    Some(p) => p["value"].clone(),
                    None if spec["required"] == false => default["default"].clone(),
                    _ => return Err(INVALID),
                };
                expected.insert(name.to_owned(), value);
            }
            if fixed.keys().any(|k| !expected.contains_key(k))
                || record["parameters"] != Value::Object(expected)
            {
                return Err(INVALID);
            }
            let mut bindings = serde_json::Map::new();
            for binding in instance["input_bindings"].as_array().ok_or(INVALID)? {
                let name = binding["input_name"].as_str().ok_or(INVALID)?;
                let source = &binding["source"];
                let reference = if source.is_string() {
                    json!({"node_fingerprint":null,"output_name":"value","source":source})
                } else {
                    let parent = builder
                        .variables
                        .get(source["instance_key"].as_str().ok_or(INVALID)?)
                        .ok_or(INVALID)?;
                    json!({"node_fingerprint":parent.fingerprint(),"output_name":source["output_name"],"source":null})
                };
                if bindings.insert(name.to_owned(), reference).is_some() {
                    return Err(INVALID);
                }
            }
            if record["input_bindings"] != Value::Object(bindings) {
                return Err(INVALID);
            }
            for output in instance["published_outputs"].as_array().ok_or(INVALID)? {
                if !record["outputs"]
                    .as_array()
                    .ok_or(INVALID)?
                    .iter()
                    .any(|p| p["name"] == *output)
                {
                    return Err(INVALID);
                }
            }
            builder.nodes.insert(
                definition.fingerprint(),
                json!({"alias":key,"definition":record}),
            );
        }
        Ok(builder)
    }
    fn predicate(&mut self, name: &str, parameters: Value, bindings: Value) -> Result<String> {
        if self.nodes.len() >= 512 {
            return Err(UNAVAILABLE);
        }
        let calculation = PredicateCalculation::resolve(
            &format!("onlyalpha.predicate.internal.{name}"),
            "1",
            &parameters,
            &bindings,
        )
        .map_err(|_| UNAVAILABLE)?;
        let definition = calculation.definition();
        let id = definition.fingerprint();
        self.nodes.insert(
            id.clone(),
            json!({"alias":format!("predicate_{id}"),"definition":definition.to_record()}),
        );
        Ok(id)
    }
    fn expression(&mut self, expression: &Value, depth: usize) -> Result<String> {
        if depth > 32 {
            return Err(UNAVAILABLE);
        }
        match expression["kind"].as_str() {
            Some("NOT") => {
                let child = self.expression(&expression["operand"], depth + 1)?;
                self.predicate("boolean.not", json!({}), json!({"value":reference(&child)}))
            }
            Some(kind @ ("AND" | "OR")) => {
                let operands = expression["operands"]
                    .as_array()
                    .filter(|v| v.len() >= 2)
                    .ok_or(INVALID)?;
                let mut current = self.expression(&operands[0], depth + 1)?;
                for operand in &operands[1..] {
                    let child = self.expression(operand, depth + 1)?;
                    current = self.predicate(
                        if kind == "AND" {
                            "boolean.and"
                        } else {
                            "boolean.or"
                        },
                        json!({}),
                        json!({"left":reference(&current),"right":reference(&child)}),
                    )?;
                }
                Ok(current)
            }
            Some("COMPARISON") => self.comparison(expression),
            _ => Err(INVALID),
        }
    }
    fn operand(&self, value: &Value, name: &str) -> Result<(Value, Value)> {
        match value["kind"].as_str() {
            Some("DATASET_FIELD") => {
                let field = value["field_name"].as_str().ok_or(INVALID)?;
                if !["open", "high", "low", "close", "volume"].contains(&field) {
                    return Err(UNAVAILABLE);
                }
                Ok((
                    json!({"node_fingerprint":null,"output_name":name,"source":format!("bar.{field}")}),
                    json!({"data_type":"DECIMAL","dimensions":["TIME"],"unit":null}),
                ))
            }
            Some("VARIABLE") => {
                let definition = self
                    .variables
                    .get(value["instance_key"].as_str().ok_or(INVALID)?)
                    .ok_or(INVALID)?;
                let record = definition.to_record();
                let output = record["outputs"]
                    .as_array()
                    .ok_or(INVALID)?
                    .iter()
                    .find(|p| p["name"] == value["output_name"])
                    .ok_or(INVALID)?;
                Ok((
                    json!({"node_fingerprint":definition.fingerprint(),"output_name":value["output_name"],"source":null}),
                    output.clone(),
                ))
            }
            _ => Err(INVALID),
        }
    }
    fn comparison(&mut self, expression: &Value) -> Result<String> {
        let op = match expression["operator"].as_str() {
            Some("==") => "eq",
            Some("!=") => "ne",
            Some("<") => "lt",
            Some("<=") => "le",
            Some(">") => "gt",
            Some(">=") => "ge",
            _ => return Err(INVALID),
        };
        let left = &expression["left"];
        let right = &expression["right"];
        let ll = left["kind"] == "LITERAL";
        let rl = right["kind"] == "LITERAL";
        if ll && rl {
            return Err(INVALID);
        }
        if ll || rl {
            let (literal, variable) = if ll { (left, right) } else { (right, left) };
            let (binding, contract) = self.operand(variable, "left")?;
            if contract["data_type"] != literal["data_type"] {
                return Err(INVALID);
            }
            if contract["data_type"] != "DECIMAL" {
                return Err(UNAVAILABLE);
            }
            self.predicate(
                &format!("compare.{op}.decimal.literal"),
                json!({"literal":literal["value"],"literal_left":{"type":"BOOLEAN","value":ll}}),
                json!({"left":binding}),
            )
        } else {
            let (left, lc) = self.operand(left, "left")?;
            let (right, rc) = self.operand(right, "right")?;
            if lc["data_type"] != rc["data_type"]
                || lc["dimensions"] != rc["dimensions"]
                || (!lc["unit"].is_null() && !rc["unit"].is_null() && lc["unit"] != rc["unit"])
            {
                return Err(INVALID);
            }
            if lc["data_type"] != "DECIMAL" {
                return Err(UNAVAILABLE);
            }
            self.predicate(
                &format!("compare.{op}.decimal.refs"),
                json!({}),
                json!({"left":left,"right":right}),
            )
        }
    }
}

/// One arithmetic/column contract shared by authoring preparation and the strict
/// native Run envelope. It proves value closure, not Dataset or Runtime authority.
pub(crate) fn canonical_input_window<'a>(
    graph: &Graph,
    start: u64,
    end: u64,
    bar_ns: u64,
    target_sources: impl IntoIterator<Item = &'a str>,
) -> Result<Value> {
    if bar_ns == 0 || !start.is_multiple_of(bar_ns) || !end.is_multiple_of(bar_ns) || start >= end {
        return Err(INVALID);
    }
    let mut histories: BTreeMap<String, u64> = BTreeMap::new();
    let mut columns = BTreeSet::new();
    let mut source = |value: &str| -> Result<()> {
        let key = value.strip_prefix("bar.").ok_or(INVALID)?;
        if !["open", "high", "low", "close", "volume"].contains(&key) {
            return Err(INVALID);
        }
        columns.insert(key.to_owned());
        Ok(())
    };
    for definition in graph.ordered_nodes() {
        let d = definition.to_record();
        let mut upstream = 0;
        for binding in d["input_bindings"].as_object().ok_or(INVALID)?.values() {
            if let Some(parent) = binding["node_fingerprint"].as_str() {
                upstream = upstream.max(*histories.get(parent).ok_or(INVALID)?);
            } else {
                source(binding["source"].as_str().ok_or(INVALID)?)?;
            }
        }
        let own = d["warmup"]["minimum_observations"]
            .as_u64()
            .filter(|n| *n > 0)
            .ok_or(INVALID)?
            - 1;
        let history = upstream
            .checked_add(own)
            .filter(|n| *n < 8192)
            .ok_or(UNAVAILABLE)?;
        histories.insert(definition.fingerprint(), history);
    }
    for value in target_sources {
        source(value)?;
    }
    let history = histories.values().copied().max().ok_or(INVALID)?;
    let count = (end - start) / bar_ns;
    let total = count
        .checked_add(history)
        .filter(|n| *n <= 8192)
        .ok_or(UNAVAILABLE)?;
    let dataset_start = start
        .checked_sub(history.checked_mul(bar_ns).ok_or(INVALID)?)
        .ok_or(INVALID)?;
    Ok(
        json!({"schema_version":1,"contract":"ONLYALPHA_STRATEGY_RESEARCH_INPUT_WINDOW_V1",
            "decision_graph_fingerprint":graph.fingerprint(),
            "observation_start_ns":start.to_string(),"observation_end_ns":end.to_string(),
            "bar_ns":bar_ns.to_string(),"dataset_event_start_ns":dataset_start.to_string(),
            "dataset_event_end_ns":end.to_string(),"dataset_columns":columns,"warmup_bars":history,
            "observation_capacity":count,"dataset_observation_capacity":total,
            "target_future_policy":"WITHIN_OBSERVATION_INTERVAL"}),
    )
}
