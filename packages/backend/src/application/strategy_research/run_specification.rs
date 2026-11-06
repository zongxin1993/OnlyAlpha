//! Native execution envelope over the existing public scientific Specification2.
//! Parsing proves value closure only; actual Dataset/Runtime/producer admission
//! remains with the owning PreparedInputs and immutable Evidence readers.
use super::{Specification, WORK};
use crate::application::{factor_content::hash, private_strategy, research_novelty::Subject};
use onlyalpha_calculation::product::Graph;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "PRIVATE_STRATEGY_RUN_SPECIFICATION_INVALID";
const UNAVAILABLE: &str = "PRIVATE_STRATEGY_RUN_SPECIFICATION_UNAVAILABLE";
fn fields(v: &Value, keys: &[&str]) -> Result<()> {
    private_strategy::exact(v, keys).map_err(|_| INVALID)
}
fn text(v: &Value) -> Result<&str> {
    private_strategy::name(v).map_err(|_| INVALID)
}
fn rows(v: &Value) -> Result<&Vec<Value>> {
    private_strategy::rows(v).map_err(|_| INVALID)
}
fn pin(v: &Value) -> Result<&str> {
    v.as_str()
        .filter(|s| crate::is_sha256_hex(s))
        .ok_or(INVALID)
}
#[derive(Clone)]
struct Calculation {
    graph: Graph,
    nodes: BTreeMap<String, String>,
}
/// No authoring identity or scientific identity is minted by this envelope.
#[derive(Clone)]
pub struct RunSpecification {
    record: Value,
    scientific: Specification,
    calculations: BTreeMap<String, Calculation>,
    targets: Graph,
}
impl RunSpecification {
    pub fn from_record(value: &Value) -> Result<Self> {
        if value.to_string().len() > WORK {
            return Err(UNAVAILABLE);
        }
        fields(
            value,
            &[
                "schema_version",
                "kind",
                "scientific_specification",
                "decision",
                "target_graph",
                "input_window",
                "runtime_generation_fingerprint",
                "catalog_generation_fingerprint",
                "algorithm_artifact_fingerprint",
                "execution_binding",
                "implementation_bindings",
            ],
        )?;
        if value["schema_version"].as_u64() != Some(5)
            || value["kind"] != "PRIVATE_STRATEGY_RESEARCH"
        {
            return Err(INVALID);
        }
        let scientific = Specification::from_record(&value["scientific_specification"])?;
        if scientific.record() != &value["scientific_specification"] {
            return Err(INVALID);
        }
        for key in [
            "runtime_generation_fingerprint",
            "catalog_generation_fingerprint",
            "algorithm_artifact_fingerprint",
        ] {
            pin(&value[key])?;
        }
        let binding = &value["execution_binding"];
        fields(
            binding,
            &[
                "protocol",
                "executor_version",
                "executor_manifest_fingerprint",
                "executor_artifact_sha256",
                "core_execution_fingerprint",
            ],
        )?;
        let version = text(&binding["executor_version"])?;
        if binding["protocol"] != "onlyalpha.research.executor/1"
            || version.len() > 255
            || !version
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"._+-".contains(&c))
        {
            return Err(INVALID);
        }
        for key in [
            "executor_manifest_fingerprint",
            "executor_artifact_sha256",
            "core_execution_fingerprint",
        ] {
            pin(&binding[key])?;
        }
        let decision = &value["decision"];
        fields(
            decision,
            &[
                "schema_version",
                "decision_graph_fingerprint",
                "decision_graph",
                "signal_semantics",
            ],
        )?;
        if decision["schema_version"].as_u64() != Some(1) {
            return Err(INVALID);
        }
        let graph = Graph::from_record(&decision["decision_graph"], WORK).map_err(|_| INVALID)?;
        let targets = Graph::from_record(&value["target_graph"], WORK).map_err(|_| INVALID)?;
        if graph.to_record() != decision["decision_graph"]
            || targets.to_record() != value["target_graph"]
            || decision["decision_graph_fingerprint"] != graph.fingerprint()
        {
            return Err(INVALID);
        }
        let signals = &decision["signal_semantics"];
        fields(
            signals,
            &[
                "schema_version",
                "eligibility",
                "entry",
                "exit",
                "missing_decision",
            ],
        )?;
        if signals["schema_version"].as_u64() != Some(1) || signals["missing_decision"] != "FALSE" {
            return Err(INVALID);
        }
        let mut calculations = BTreeMap::new();
        let mut used_targets = BTreeSet::new();
        for calculation in rows(&scientific.record()["calculations"])? {
            let id = text(&calculation["calculation_id"])?;
            let source = if id == "decision" { &graph } else { &targets };
            let (bound, nodes) = bind_template(&calculation["graph_template"], source)?;
            if id == "decision" {
                if bound.fingerprint() != graph.fingerprint()
                    || nodes.len() != graph.ordered_nodes().count()
                {
                    return Err(INVALID);
                }
            } else {
                for node in nodes.values() {
                    if !used_targets.insert(node.clone()) {
                        return Err(INVALID);
                    }
                }
            }
            calculations.insert(
                id.to_owned(),
                Calculation {
                    graph: bound,
                    nodes,
                },
            );
        }
        if used_targets != targets.ordered_nodes().map(|n| n.fingerprint()).collect() {
            return Err(INVALID);
        }
        let spec = Self {
            record: value.clone(),
            scientific,
            calculations,
            targets,
        };
        for selector in rows(&spec.scientific.record()["evidence"]["published_series"])? {
            spec.series(selector)?;
        }
        for (role, semantic) in [
            ("eligibility", "ELIGIBILITY"),
            ("entry", "ENTRY_SIGNAL"),
            ("exit", "EXIT_SIGNAL"),
        ] {
            let selector = &spec.scientific.record()["evidence"]["signals"][role];
            let resolved = spec.series(selector)?;
            fields(&signals[role], &["node_fingerprint", "output_name"])?;
            if signals[role]["node_fingerprint"] != resolved["node_fingerprint"]
                || signals[role]["output_name"] != resolved["output_name"]
                || selector["calculation_id"] != "decision"
            {
                return Err(INVALID);
            }
            let node = spec.calculations["decision"]
                .graph
                .ordered_nodes()
                .find(|n| resolved["node_fingerprint"] == n.fingerprint())
                .ok_or(INVALID)?
                .to_record();
            let port = port(&node, text(&resolved["output_name"])?)?;
            if node["kind"] != "PREDICATE"
                || port["data_type"] != "BOOLEAN"
                || port["semantic_type"] != semantic
            {
                return Err(INVALID);
            }
        }
        let mut implementations = BTreeSet::new();
        let mut previous = None;
        for binding in rows(&value["implementation_bindings"])? {
            fields(
                binding,
                &[
                    "node_fingerprint",
                    "research_implementation_fingerprint",
                    "trading_implementation_fingerprint",
                ],
            )?;
            let node = pin(&binding["node_fingerprint"])?;
            pin(&binding["research_implementation_fingerprint"])?;
            pin(&binding["trading_implementation_fingerprint"])?;
            if previous.is_some_and(|p| p >= node) || !implementations.insert(node.to_owned()) {
                return Err(INVALID);
            }
            previous = Some(node);
        }
        if implementations
            != spec.calculations["decision"]
                .graph
                .ordered_nodes()
                .map(|n| n.fingerprint())
                .collect()
        {
            return Err(INVALID);
        }
        let window = &value["input_window"];
        let ns = |key: &str| -> Result<u64> {
            let s = text(&window[key])?;
            let n = s.parse::<u64>().map_err(|_| INVALID)?;
            if n.to_string() != s {
                return Err(INVALID);
            }
            Ok(n)
        };
        let target_sources = spec
            .targets
            .ordered_nodes()
            .flat_map(|n| {
                let r = n.to_record();
                r["input_bindings"]
                    .as_object()
                    .into_iter()
                    .flat_map(|m| m.values())
                    .filter_map(|b| b["source"].as_str().map(str::to_owned))
                    .collect::<Vec<_>>()
            })
            .collect::<Vec<_>>();
        let expected = super::decision::canonical_input_window(
            &spec.calculations["decision"].graph,
            ns("observation_start_ns")?,
            ns("observation_end_ns")?,
            ns("bar_ns")?,
            target_sources.iter().map(String::as_str),
        )?;
        if *window != expected {
            return Err(INVALID);
        }
        // A strict value still cannot anchor the period to an actual Dataset or
        // authoring Context; the actual owning admission must verify both.
        let statistics = spec.statistics_intents()?;
        let ids = statistics
            .iter()
            .map(hash)
            .collect::<Result<BTreeSet<_>>>()?;
        if ids.len() != statistics.len() || ids.len() > 32 {
            return Err(INVALID);
        }
        Ok(spec)
    }
    pub(crate) fn calculation_graph(&self, id: &str) -> Result<&Graph> {
        self.calculations.get(id).map(|c| &c.graph).ok_or(INVALID)
    }
    pub(crate) fn target_graph(&self) -> &Graph {
        &self.targets
    }
    pub(crate) fn calculation_graphs(&self) -> impl Iterator<Item = (&str, &Graph)> {
        self.calculations
            .iter()
            .map(|(id, c)| (id.as_str(), &c.graph))
    }
    pub fn record(&self) -> &Value {
        &self.record
    }
    pub fn fingerprint(&self) -> Result<String> {
        hash(&self.record)
    }
    pub fn scientific_specification_fingerprint(&self) -> Result<String> {
        self.scientific.fingerprint()
    }
    /// Existing Calculation1 semantic identity; Runtime/code evidence is excluded.
    pub fn calculation_fingerprint(&self) -> Result<String> {
        self.calculation_identity("decision")
    }
    /// Work identity only, never a public Calculation1 or Candidate locator.
    pub fn calculation_execution_fingerprint(&self) -> Result<String> {
        hash(
            &json!({"schema_version":1,"contract":"ONLYALPHA_STRATEGY_RESEARCH_CALCULATION_EXECUTION_V1",
            "calculation_fingerprint":self.calculation_fingerprint()?,"run_specification_fingerprint":self.fingerprint()?}),
        )
    }
    pub(crate) fn calculation_identity(&self, id: &str) -> Result<String> {
        let graph = &self.calculations.get(id).ok_or(INVALID)?.graph;
        hash(
            &json!({"schema_version":1,"dataset_snapshot_fingerprint":self.scientific.record()["dataset_snapshot_fingerprint"],
            "calculation_graph_fingerprint":graph.fingerprint(),"backend":"RESEARCH"}),
        )
    }
    pub fn candidate_fingerprint(&self) -> Result<String> {
        hash(
            &json!({"schema_version":1,"specification_fingerprint":self.scientific_specification_fingerprint()?,
            "candidate_calculation_id":"decision","assignment":{},"calculation_fingerprint":self.calculation_fingerprint()?}),
        )
    }
    fn series(&self, selector: &Value) -> Result<Value> {
        fields(
            selector,
            &["calculation_id", "template_node_id", "output_name"],
        )?;
        let calculation = text(&selector["calculation_id"])?;
        let resolved = self.calculations.get(calculation).ok_or(INVALID)?;
        let node = resolved
            .nodes
            .get(text(&selector["template_node_id"])?)
            .ok_or(INVALID)?;
        let record = resolved
            .graph
            .ordered_nodes()
            .find(|n| n.fingerprint() == *node)
            .ok_or(INVALID)?
            .to_record();
        port(&record, text(&selector["output_name"])?)?;
        Ok(
            json!({"calculation_fingerprint":self.calculation_identity(calculation)?,"node_fingerprint":node,"output_name":selector["output_name"]}),
        )
    }
    pub fn statistics_intents(&self) -> Result<Vec<Value>> {
        rows(&self.scientific.record()["statistics"])?.iter().map(|request| {
            let feature=self.series(&request["feature"])?;
            let target=self.series(&request["target"])?;
            for (selector,series,kind,semantics) in [(&request["feature"],&feature,"FACTOR",&["FACTOR_VALUE","FACTOR_SCORE"][..]),
                (&request["target"],&target,"TARGET",&["TARGET_VALUE"][..])] {
                let calc=self.calculations.get(text(&selector["calculation_id"]) ?).ok_or(INVALID)?;
                let node=calc.graph.ordered_nodes().find(|n|series["node_fingerprint"]==n.fingerprint()).ok_or(INVALID)?.to_record();
                let output=port(&node,text(&series["output_name"])?)?;
                if node["kind"]!=kind || output["data_type"]!="DECIMAL" || !semantics.contains(&text(&output["semantic_type"])?) { return Err(INVALID); }
            }
            Ok(json!({"schema_version":1,"feature":feature,"target":target,"definition":request["definition"]}))
        }).collect()
    }
    /// Existing public ResultPlan2, built from semantic Calculation/Statistics refs.
    pub fn result_plan(&self) -> Result<Value> {
        let candidate = self.candidate_fingerprint()?;
        let mut statistics = self
            .statistics_intents()?
            .iter()
            .map(hash)
            .collect::<Result<Vec<_>>>()?;
        statistics.sort();
        let mut calculations=self.calculations.iter().map(|(id,c)|Ok(json!({"calculation_fingerprint":self.calculation_identity(id)?,"graph_fingerprint":c.graph.fingerprint()}))).collect::<Result<Vec<_>>>()?;
        calculations.sort_by_cached_key(|v| {
            (
                v["calculation_fingerprint"]
                    .as_str()
                    .unwrap_or_default()
                    .to_owned(),
                v["graph_fingerprint"]
                    .as_str()
                    .unwrap_or_default()
                    .to_owned(),
            )
        });
        let mut published = Vec::new();
        for selector in rows(&self.scientific.record()["evidence"]["published_series"])? {
            let mut series = self.series(selector)?;
            series["candidate_fingerprint"] = if selector["calculation_id"] == "decision" {
                json!(candidate)
            } else {
                Value::Null
            };
            published.push(series);
        }
        published.sort_by_cached_key(|v| {
            (
                v["candidate_fingerprint"]
                    .as_str()
                    .unwrap_or_default()
                    .to_owned(),
                v["calculation_fingerprint"]
                    .as_str()
                    .unwrap_or_default()
                    .to_owned(),
                v["node_fingerprint"]
                    .as_str()
                    .unwrap_or_default()
                    .to_owned(),
                v["output_name"].as_str().unwrap_or_default().to_owned(),
            )
        });
        let mut signals = Vec::new();
        for (role, selector) in [
            ("ELIGIBILITY", "eligibility"),
            ("ENTRY_SIGNAL", "entry"),
            ("EXIT_SIGNAL", "exit"),
        ] {
            let mut series =
                self.series(&self.scientific.record()["evidence"]["signals"][selector])?;
            series["candidate_fingerprint"] = json!(candidate);
            series["role"] = json!(role);
            signals.push(series);
        }
        Ok(
            json!({"schema_version":2,"dataset_snapshot_fingerprint":self.scientific.record()["dataset_snapshot_fingerprint"],
            "statistics_fingerprints":statistics,"calculations":calculations,
            "candidates":[{"candidate_fingerprint":candidate,"candidate_calculation_id":"decision","assignment":{},
                "calculation_fingerprint":self.calculation_fingerprint()?,"graph_fingerprint":self.calculations["decision"].graph.fingerprint(),"statistics_fingerprints":statistics}],
            "published_series":published,"signals":signals}),
        )
    }
    pub fn subject(&self) -> Result<Subject> {
        let statistics = self.statistics_intents()?;
        let focal = statistics
            .iter()
            .map(|s| {
                Ok((
                    text(&s["feature"]["node_fingerprint"])?.to_owned(),
                    text(&s["feature"]["output_name"])?.to_owned(),
                ))
            })
            .collect::<Result<BTreeSet<_>>>()?;
        if focal.len() != 1 {
            return Err("STRATEGY_RESEARCH_SUBJECT_AMBIGUOUS");
        }
        let (node, output) = focal.into_iter().next().ok_or(INVALID)?;
        let plan = self.result_plan()?;
        Subject::new(
            json!({"schema_version":1,"graph_fingerprint":self.calculations["decision"].graph.fingerprint(),
            "candidate_node_fingerprint":node,"output_name":output,"candidate_fingerprint":self.candidate_fingerprint()?,
            "dataset_snapshot_fingerprint":self.scientific.record()["dataset_snapshot_fingerprint"],
            "specification_fingerprint":self.scientific_specification_fingerprint()?,"result_plan_fingerprint":hash(&plan)?,
            "statistics_fingerprints":plan["statistics_fingerprints"],"catalog_generation_fingerprint":self.record["catalog_generation_fingerprint"],
            "runtime_generation_fingerprint":self.record["runtime_generation_fingerprint"],"authoring_generation_fingerprint":null}),
        )
    }
}
fn port<'a>(definition: &'a Value, name: &str) -> Result<&'a Value> {
    rows(&definition["outputs"])?
        .iter()
        .find(|p| p["name"] == name)
        .ok_or(INVALID)
}
/// Match each fixed template node to exactly one actual canonical Definition,
/// recursively substituting template references with the proven parent identity.
fn bind_template(template: &Value, graph: &Graph) -> Result<(Graph, BTreeMap<String, String>)> {
    let nodes = rows(&template["nodes"])?;
    let actual = graph.to_record();
    let actual = rows(&actual["nodes"])?;
    let mut mapped = BTreeMap::<String, String>::new();
    let mut selected = BTreeMap::<String, Value>::new();
    while mapped.len() < nodes.len() {
        let mut progress = false;
        for node in nodes {
            let id = text(&node["template_node_id"])?;
            if mapped.contains_key(id) {
                continue;
            }
            let mut inputs = serde_json::Map::new();
            let mut ready = true;
            for binding in rows(&node["input_bindings"])? {
                let reference = &binding["reference"];
                let parent = if reference["template_node_id"].is_null() {
                    Value::Null
                } else if let Some(parent) = mapped.get(text(&reference["template_node_id"])?) {
                    json!(parent)
                } else {
                    ready = false;
                    break;
                };
                inputs.insert(text(&binding["input_name"])?.into(),json!({"node_fingerprint":parent,"output_name":reference["output_name"],"source":reference["source"]}));
            }
            if !ready {
                continue;
            }
            let expected_inputs = Value::Object(inputs);
            let matches = actual
                .iter()
                .filter(|row| {
                    let d = &row["definition"];
                    let t = &node["type_reference"];
                    ["kind", "type_id", "semantic_version"]
                        .into_iter()
                        .all(|k| d[k] == t[k])
                        && d["parameters"] == node["parameters"]
                        && d["input_bindings"] == expected_inputs
                })
                .collect::<Vec<_>>();
            if matches.len() != 1 {
                return Err(INVALID);
            }
            let row = matches[0];
            let definition =
                onlyalpha_calculation::product::Definition::from_record(&row["definition"], WORK)
                    .map_err(|_| INVALID)?;
            let fp = definition.fingerprint();
            if selected.insert(fp.clone(), row.clone()).is_some() {
                return Err(INVALID);
            }
            mapped.insert(id.into(), fp);
            progress = true;
        }
        if !progress {
            return Err(INVALID);
        }
    }
    let bound = Graph::from_record(
        &json!({"schema_version":1,"nodes":selected.into_values().collect::<Vec<_>>()}),
        WORK,
    )
    .map_err(|_| INVALID)?;
    Ok((bound, mapped))
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use crate::application::{
        private_strategy::Definition,
        strategy_research::{Context, DecisionGraph, Specification},
    };
    use onlyalpha_calculation::product::Graph;
    use serde_json::{Value, json};

    pub(crate) fn record() -> Value {
        let vector: Value = serde_json::from_str(include_str!(
            "../../../tests/application/fixtures/strategy_specification.json"
        ))
        .unwrap();
        let calculations: Value = serde_json::from_str(include_str!(
            "../../../tests/application/fixtures/strategy_calculations.json"
        ))
        .unwrap();
        let seed: Value = serde_json::from_str(include_str!(
            "../../../../../examples/private-assets/strategy/simple_momentum/strategy.json"
        ))
        .unwrap();
        let mut strategy = seed["strategy"]["definition"].clone();
        strategy["calculations"] = calculations["instances"].clone();
        strategy["factor_revision_dependencies"] =
            calculations["factor_revision_dependencies"].clone();
        let strategy = Definition::from_record(&strategy).unwrap();
        let context=Context::new(json!({"schema_version":1,"start":"2025-01-02T12:00:00Z","end":"2025-01-03T00:00:00Z","targets":[{"instance_key":"forward_return","type_reference":{"kind":"TARGET","type_id":"onlyalpha.target.forward_return","semantic_version":"1"},"parameters":{"exit_offset":{"kind":"FIXED","value":{"type":"INTEGER","value":5}}},"published_outputs":["target_value"],"primary_output":null,"input_bindings":[{"input_name":"entry_price","source":"bar.close"},{"input_name":"exit_price","source":"bar.close"}]}],"statistics":[{"variable":{"kind":"VARIABLE","instance_key":"momentum","output_name":"value"},"target_instance_key":"forward_return","definition":vector["specification"]["statistics"][0]["definition"]}],"display_metadata":{}})).unwrap();
        let graph = DecisionGraph::derive(&strategy, &calculations["nodes"]).unwrap();
        let target=Graph::from_record(&json!({"schema_version":1,"nodes":[{"alias":"forward_return","definition":vector["target_definition"]}]}),8*1024*1024).unwrap();
        let scientific = Specification::derive(
            &context.definition(&strategy).unwrap(),
            &graph,
            &target,
            &"d".repeat(64),
        )
        .unwrap();
        let mut window = graph.input_window(&context, 60_000_000_000).unwrap();
        window
            .as_object_mut()
            .unwrap()
            .remove("research_context_fingerprint");
        // Value-only inputs. An owning PreparedInputs/Run admission still has to
        // prove actual implementations, files, authoring composition and consent.
        let mut bindings=graph.graph().ordered_nodes().map(|n|json!({"node_fingerprint":n.fingerprint(),"research_implementation_fingerprint":"a".repeat(64),"trading_implementation_fingerprint":"b".repeat(64)})).collect::<Vec<_>>();
        bindings.sort_by_key(|b| b["node_fingerprint"].as_str().unwrap().to_owned());
        json!({"schema_version":5,"kind":"PRIVATE_STRATEGY_RESEARCH","scientific_specification":scientific.record(),
            "decision":graph.record(),"target_graph":target.to_record(),"input_window":window,
            "runtime_generation_fingerprint":"a".repeat(64),"catalog_generation_fingerprint":"b".repeat(64),
            "algorithm_artifact_fingerprint":"c".repeat(64),
            "execution_binding":{"protocol":"onlyalpha.research.executor/1","executor_version":"0.11.1","executor_manifest_fingerprint":"e".repeat(64),"executor_artifact_sha256":"f".repeat(64),"core_execution_fingerprint":"a".repeat(64)},
            "implementation_bindings":bindings})
    }
    #[test]
    fn executable_binding_is_separate_from_public_science_and_strategy_identity() {
        let value = record();
        let spec = RunSpecification::from_record(&value).unwrap();
        assert_eq!(spec.record(), &value);
        let science = spec.scientific_specification_fingerprint().unwrap();
        let candidate = spec.candidate_fingerprint().unwrap();
        let mut changed = value.clone();
        changed["runtime_generation_fingerprint"] = json!("e".repeat(64));
        let changed = RunSpecification::from_record(&changed).unwrap();
        assert_ne!(spec.fingerprint().unwrap(), changed.fingerprint().unwrap());
        assert_eq!(
            science,
            changed.scientific_specification_fingerprint().unwrap()
        );
        assert_eq!(candidate, changed.candidate_fingerprint().unwrap());
        assert_eq!(
            spec.calculation_fingerprint().unwrap(),
            changed.calculation_fingerprint().unwrap()
        );
        assert_ne!(
            spec.calculation_execution_fingerprint().unwrap(),
            changed.calculation_execution_fingerprint().unwrap()
        );
        assert!(spec.record().get("strategy_fingerprint").is_none());
        assert!(spec.record().get("factor").is_none());
        assert_eq!(spec.statistics_intents().unwrap().len(), 1);
        assert_eq!(
            spec.subject().unwrap().record()["candidate_fingerprint"],
            candidate
        );
    }
    #[test]
    fn executable_spec_rejects_detached_graph_window_and_implementation_claims() {
        let base = record();
        for change in [
            "origin",
            "context",
            "window",
            "missing-implementation",
            "duplicate-implementation",
            "signal",
            "target",
            "template",
        ] {
            let mut value = base.clone();
            match change {
                "origin" => value["kind"] = json!("TIME_SERIES_FACTOR_RESEARCH"),
                "context" => value["display_metadata"] = json!({"title":"hidden semantic input"}),
                "window" => value["input_window"]["warmup_bars"] = json!(19),
                "missing-implementation" => {
                    value["implementation_bindings"]
                        .as_array_mut()
                        .unwrap()
                        .pop();
                }
                "duplicate-implementation" => {
                    let b = value["implementation_bindings"][0].clone();
                    value["implementation_bindings"]
                        .as_array_mut()
                        .unwrap()
                        .push(b);
                }
                "signal" => {
                    value["decision"]["signal_semantics"]["entry"] =
                        value["decision"]["signal_semantics"]["exit"].clone()
                }
                "target" => {
                    value["target_graph"]["nodes"][0]["definition"]["parameters"]["exit_offset"]["value"] =
                        json!(6)
                }
                "template" => {
                    value["scientific_specification"]["calculations"][0]["graph_template"]["nodes"]
                        [0]["parameters"]["period"] = json!({"type":"INTEGER","value":19})
                }
                _ => unreachable!(),
            }
            assert!(RunSpecification::from_record(&value).is_err(), "{change}");
        }
    }
}
