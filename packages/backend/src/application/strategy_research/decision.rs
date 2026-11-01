//! Authoring-to-Calculation lowering only; no Run, Freeze or Strategy identity.
use super::{WORK, canonical_expression};
use crate::application::private_strategy::Definition as Strategy;
use onlyalpha_calculation::product::{Definition, Graph, TypeDeclaration};
use onlyalpha_calculation_bridge::native_predicates::PredicateCalculation;
use serde_json::{Value, json};
use std::collections::BTreeMap;
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "PRIVATE_STRATEGY_DECISION_GRAPH_INVALID";
const UNAVAILABLE: &str = "PRIVATE_STRATEGY_DECISION_GRAPH_UNAVAILABLE";

pub struct DecisionGraph {
    graph: Graph,
    signals: Value,
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
        Ok(Self { graph, signals })
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
