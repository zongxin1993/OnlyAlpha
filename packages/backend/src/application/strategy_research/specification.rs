//! Fixed public Research Specification2 values; no capability or Run permission.
use super::{DecisionGraph, ResearchDefinition, WORK};
use crate::application::{factor_content::hash, private_strategy};
use onlyalpha_calculation::{TypeReference, product::Graph};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "PRIVATE_STRATEGY_RESEARCH_SPECIFICATION_INVALID";
const UNAVAILABLE: &str = "PRIVATE_STRATEGY_RESEARCH_SPECIFICATION_UNAVAILABLE";
fn mapped(error: &'static str) -> &'static str {
    if error.ends_with("UNAVAILABLE") {
        UNAVAILABLE
    } else {
        INVALID
    }
}
fn fields(value: &Value, expected: &[&str]) -> Result<()> {
    private_strategy::exact(value, expected).map_err(mapped)
}
fn name(value: &Value) -> Result<&str> {
    private_strategy::name(value).map_err(mapped)
}
fn rows(value: &Value) -> Result<&Vec<Value>> {
    private_strategy::rows(value).map_err(mapped)
}

/// This is the existing author-neutral scientific request, not an admission fact.
#[derive(Clone, Debug)]
pub struct Specification(Value);
impl Specification {
    pub fn from_record(value: &Value) -> Result<Self> {
        if value.to_string().len() > WORK {
            return Err(UNAVAILABLE);
        }
        fields(
            value,
            &[
                "schema_version",
                "dataset_snapshot_fingerprint",
                "calculations",
                "statistics",
                "evidence",
            ],
        )?;
        if value["schema_version"].as_u64() != Some(2)
            || !value["dataset_snapshot_fingerprint"]
                .as_str()
                .is_some_and(crate::is_sha256_hex)
        {
            return Err(INVALID);
        }
        let mut value = value.clone();
        let mut calculations = rows(&value["calculations"])?.clone();
        if calculations.is_empty() || calculations.len() > 128 {
            return Err(UNAVAILABLE);
        }
        let mut known = BTreeMap::new();
        let mut work = WORK;
        let mut node_count = 0usize;
        for calculation in &mut calculations {
            fields(
                calculation,
                &["calculation_id", "graph_template", "sweep_dimensions"],
            )?;
            let id = name(&calculation["calculation_id"])?.to_owned();
            if calculation["sweep_dimensions"] != json!([])
                || (id != "decision" && !id.strip_prefix("target.").is_some_and(|s| !s.is_empty()))
            {
                return Err(INVALID);
            }
            let template = template(&calculation["graph_template"], &mut work, &mut node_count)?;
            let nodes = rows(&template["nodes"])?;
            let mut kinds = BTreeMap::new();
            for node in nodes {
                let kind = name(&node["type_reference"]["kind"])?;
                if (id == "decision" && kind == "TARGET") || (id != "decision" && kind != "TARGET")
                {
                    return Err(INVALID);
                }
                kinds.insert(name(&node["template_node_id"])?.to_owned(), kind.to_owned());
            }
            if known.insert(id, kinds).is_some() {
                return Err(INVALID);
            }
            calculation["graph_template"] = template;
        }
        if !known.contains_key("decision") {
            return Err(INVALID);
        }
        calculations
            .sort_by_cached_key(|v| v["calculation_id"].as_str().unwrap_or_default().to_owned());
        value["calculations"] = json!(calculations);
        let evidence = &value["evidence"];
        fields(
            evidence,
            &["candidate_calculation_id", "published_series", "signals"],
        )?;
        if evidence["candidate_calculation_id"] != "decision" {
            return Err(INVALID);
        }
        let mut published = rows(&evidence["published_series"])?.clone();
        if published.is_empty() {
            return Err(INVALID);
        }
        let mut selectors = BTreeSet::new();
        for row in &published {
            selector(row, &known)?;
            if !selectors.insert(selector_key(row)) {
                return Err(INVALID);
            }
        }
        published.sort_by_cached_key(selector_key);
        let signals = &evidence["signals"];
        fields(signals, &["eligibility", "entry", "exit"])?;
        for role in ["eligibility", "entry", "exit"] {
            if !signals[role].is_null()
                && (selector(&signals[role], &known)? != "PREDICATE"
                    || signals[role]["calculation_id"] != "decision")
            {
                return Err(INVALID);
            }
        }
        value["evidence"]["published_series"] = json!(published);
        let mut statistics = rows(&value["statistics"])?.clone();
        if statistics.is_empty() {
            return Err(INVALID);
        }
        let mut unique = BTreeSet::new();
        for item in &mut statistics {
            fields(item, &["feature", "target", "definition", "expansion"])?;
            if selector(&item["feature"], &known)? != "FACTOR"
                || item["feature"]["calculation_id"] != "decision"
                || selector(&item["target"], &known)? != "TARGET"
                || item["expansion"] != "BROADCAST_SINGLETON"
            {
                return Err(INVALID);
            }
            statistics_definition(&mut item["definition"], &mut work)?;
            if !unique.insert(item.to_string()) {
                return Err(INVALID);
            }
        }
        // Public Specification2 uses Python's stable literal ordering here.
        statistics.sort_by_cached_key(python_literal);
        value["statistics"] = json!(statistics);
        if value.to_string().len() > WORK {
            return Err(UNAVAILABLE);
        }
        Ok(Self(value))
    }
    pub fn record(&self) -> &Value {
        &self.0
    }
    pub fn fingerprint(&self) -> Result<String> {
        hash(&self.0).map_err(mapped)
    }

    /// Inputs must separately be re-anchored to their Catalog/Dataset/Runtime
    /// owners. This only compiles the already materialized numerical definitions.
    pub fn derive(
        definition: &ResearchDefinition,
        decision: &DecisionGraph,
        targets: &Graph,
        dataset: &str,
    ) -> Result<Self> {
        if !crate::is_sha256_hex(dataset) {
            return Err(INVALID);
        }
        decision.require_source(definition).map_err(mapped)?;
        let source = definition.record();
        let graph = decision.graph().to_record();
        let target_graph = targets.to_record();
        let candidate_rows = rows(&graph["nodes"])?;
        let target_rows = rows(&target_graph["nodes"])?;
        let features = instances(&source["calculations"], candidate_rows)?;
        let target_instances = instances(&source["targets"], target_rows)?;
        if target_instances.len() != target_rows.len() {
            return Err(INVALID);
        }
        let mut ids = BTreeMap::new();
        for (id, row) in &features {
            ids.insert(node_fingerprint(row)?, id.clone());
        }
        let signals = decision.record()["signal_semantics"].clone();
        for (role, id) in [
            ("eligibility", "eligibility_terminal"),
            ("entry", "entry_signal_terminal"),
            ("exit", "exit_signal_terminal"),
        ] {
            let fingerprint = name(&signals[role]["node_fingerprint"])?;
            let row = candidate_rows
                .iter()
                .find(|row| node_fingerprint(row).is_ok_and(|fp| fp == fingerprint))
                .ok_or(INVALID)?;
            let port = output(row, name(&signals[role]["output_name"])?)?;
            if port["data_type"] != "BOOLEAN" {
                return Err(INVALID);
            }
            if ids.insert(fingerprint.to_owned(), id.to_owned()).is_some() {
                return Err(INVALID);
            }
        }
        for row in candidate_rows {
            let fp = node_fingerprint(row)?;
            if !ids.contains_key(&fp) {
                if row["definition"]["kind"] != "PREDICATE" {
                    return Err(INVALID);
                }
                ids.insert(fp.clone(), format!("predicate_{fp}"));
            }
        }
        let mut calculations = vec![
            json!({"calculation_id":"decision","graph_template":compile_template(candidate_rows,&ids)?,"sweep_dimensions":[]}),
        ];
        let mut published = vec![];
        for instance in rows(&source["calculations"])? {
            let key = name(&instance["instance_key"])?;
            for port in rows(&instance["published_outputs"])? {
                published.push(series("decision", key, name(port)?));
            }
        }
        for instance in rows(&source["targets"])? {
            let key = name(&instance["instance_key"])?;
            let row = target_instances.get(key).ok_or(INVALID)?;
            let node_ids = BTreeMap::from([(node_fingerprint(row)?, key.to_owned())]);
            let id = format!("target.{key}");
            calculations.push(json!({"calculation_id":id,"graph_template":compile_template(&[(**row).clone()],&node_ids)?,"sweep_dimensions":[]}));
            for port in rows(&instance["published_outputs"])? {
                published.push(series(&id, key, name(port)?));
            }
        }
        let mut statistics = vec![];
        for request in rows(&source["statistics"])? {
            let feature_key = name(&request["variable"]["instance_key"])?;
            let feature_name = name(&request["variable"]["output_name"])?;
            let row = features.get(feature_key).ok_or(INVALID)?;
            let port = output(row, feature_name)?;
            if row["definition"]["kind"] != "FACTOR"
                || !matches!(
                    port["semantic_type"].as_str(),
                    Some("FACTOR_VALUE" | "FACTOR_SCORE")
                )
            {
                return Err(INVALID);
            }
            let target_key = name(&request["target_instance_key"])?;
            let declaration = rows(&source["targets"])?
                .iter()
                .find(|d| d["instance_key"] == target_key)
                .ok_or(INVALID)?;
            let target_name = name(
                rows(&declaration["published_outputs"])?
                    .first()
                    .ok_or(INVALID)?,
            )?;
            let target = target_instances.get(target_key).ok_or(INVALID)?;
            if target["definition"]["kind"] != "TARGET"
                || output(target, target_name)?["semantic_type"] != "TARGET_VALUE"
            {
                return Err(INVALID);
            }
            statistics.push(json!({"feature":series("decision",feature_key,feature_name),"target":series(&format!("target.{target_key}"),target_key,target_name),"definition":request["definition"],"expansion":"BROADCAST_SINGLETON"}));
        }
        let mut signal_selectors = json!({});
        for role in ["eligibility", "entry", "exit"] {
            let fp = name(&signals[role]["node_fingerprint"])?;
            signal_selectors[role] = series(
                "decision",
                ids.get(fp).ok_or(INVALID)?,
                name(&signals[role]["output_name"])?,
            );
        }
        Self::from_record(
            &json!({"schema_version":2,"dataset_snapshot_fingerprint":dataset,"calculations":calculations,"statistics":statistics,"evidence":{"candidate_calculation_id":"decision","published_series":published,"signals":signal_selectors}}),
        )
    }
}
fn template(value: &Value, work: &mut usize, count: &mut usize) -> Result<Value> {
    fields(value, &["schema_version", "nodes"])?;
    if value["schema_version"].as_u64() != Some(1) {
        return Err(INVALID);
    }
    let mut nodes = rows(&value["nodes"])?.clone();
    *count = count.checked_add(nodes.len()).ok_or(UNAVAILABLE)?;
    if nodes.is_empty() || *count > 512 {
        return Err(UNAVAILABLE);
    }
    let mut dependencies = BTreeMap::new();
    for node in &mut nodes {
        fields(
            node,
            &[
                "template_node_id",
                "type_reference",
                "parameters",
                "input_bindings",
                "alias",
            ],
        )?;
        let id = name(&node["template_node_id"])?.to_owned();
        fields(
            &node["type_reference"],
            &["kind", "type_id", "semantic_version"],
        )?;
        let t = &node["type_reference"];
        TypeReference::new(
            name(&t["kind"])?,
            name(&t["type_id"])?,
            name(&t["semantic_version"])?,
        )
        .map_err(|_| INVALID)?;
        if !node["alias"].is_null() {
            name(&node["alias"])?;
        }
        for (key, value) in node["parameters"].as_object_mut().ok_or(INVALID)? {
            name(&json!(key))?;
            *value = private_strategy::scalar(value, work).map_err(mapped)?;
        }
        let mut bindings = rows(&node["input_bindings"])?.clone();
        let mut input_names = BTreeSet::new();
        let mut parents = BTreeSet::new();
        for binding in &bindings {
            fields(binding, &["input_name", "reference"])?;
            if !input_names.insert(name(&binding["input_name"])?) {
                return Err(INVALID);
            }
            let reference = &binding["reference"];
            fields(reference, &["template_node_id", "output_name", "source"])?;
            name(&reference["output_name"])?;
            match (
                reference["template_node_id"].is_null(),
                reference["source"].is_null(),
            ) {
                (false, true) => {
                    parents.insert(name(&reference["template_node_id"])?.to_owned());
                }
                (true, false) => {
                    name(&reference["source"])?;
                }
                _ => return Err(INVALID),
            }
        }
        bindings.sort_by_cached_key(|b| b["input_name"].as_str().unwrap_or_default().to_owned());
        node["input_bindings"] = json!(bindings);
        if dependencies.insert(id, parents).is_some() {
            return Err(INVALID);
        }
    }
    if dependencies
        .values()
        .flatten()
        .any(|p| !dependencies.contains_key(p))
    {
        return Err(INVALID);
    }
    let mut visited = BTreeSet::new();
    while visited.len() < dependencies.len() {
        let ready = dependencies
            .iter()
            .filter(|(id, parents)| !visited.contains(*id) && parents.is_subset(&visited))
            .map(|(id, _)| id.clone())
            .collect::<Vec<_>>();
        if ready.is_empty() {
            return Err(INVALID);
        }
        visited.extend(ready);
    }
    nodes.sort_by_cached_key(|n| {
        n["template_node_id"]
            .as_str()
            .unwrap_or_default()
            .to_owned()
    });
    Ok(json!({"schema_version":1,"nodes":nodes}))
}
fn selector<'a>(
    value: &Value,
    known: &'a BTreeMap<String, BTreeMap<String, String>>,
) -> Result<&'a str> {
    fields(
        value,
        &["calculation_id", "template_node_id", "output_name"],
    )?;
    name(&value["output_name"])?;
    let calculation = name(&value["calculation_id"])?;
    let node = name(&value["template_node_id"])?;
    known
        .get(calculation)
        .and_then(|nodes| nodes.get(node))
        .map(String::as_str)
        .ok_or(INVALID)
}
fn selector_key(value: &Value) -> (String, String, String) {
    (
        value["calculation_id"]
            .as_str()
            .unwrap_or_default()
            .to_owned(),
        value["template_node_id"]
            .as_str()
            .unwrap_or_default()
            .to_owned(),
        value["output_name"].as_str().unwrap_or_default().to_owned(),
    )
}
fn statistics_definition(value: &mut Value, work: &mut usize) -> Result<()> {
    fields(
        value,
        &[
            "schema_version",
            "method",
            "minimum_observations",
            "pairing_policy",
            "universe_policy",
            "rank_tie_method",
            "weighting",
            "numeric",
        ],
    )?;
    if value["schema_version"].as_u64() != Some(1)
        || !matches!(value["method"].as_str(), Some("IC" | "RANK_IC"))
        || value["minimum_observations"].as_u64().is_none_or(|n| n < 2)
        || value["pairing_policy"] != "PAIRWISE_COMPLETE"
        || value["universe_policy"] != "OBSERVED_PAIRWISE"
        || value["rank_tie_method"] != "AVERAGE"
        || value["weighting"] != "EQUAL"
    {
        return Err(INVALID);
    }
    let numeric = &mut value["numeric"];
    fields(
        numeric,
        &["representation", "precision", "output_quantum", "rounding"],
    )?;
    let quantum = private_strategy::scalar(
        &json!({"type":"DECIMAL","value":numeric["output_quantum"]}),
        work,
    )
    .map_err(mapped)?;
    if numeric["representation"] != "DECIMAL"
        || numeric["precision"].as_u64() != Some(38)
        || numeric["rounding"] != "ROUND_HALF_EVEN"
        || quantum["value"] != "0.000000000001"
    {
        return Err(INVALID);
    }
    numeric["output_quantum"] = quantum["value"].clone();
    Ok(())
}
fn series(calculation: &str, node: &str, output: &str) -> Value {
    json!({"calculation_id":calculation,"template_node_id":node,"output_name":output})
}
fn node_fingerprint(row: &Value) -> Result<String> {
    onlyalpha_calculation::product::Definition::from_record(&row["definition"], WORK)
        .map(|d| d.fingerprint())
        .map_err(|_| INVALID)
}
fn output<'a>(row: &'a Value, name: &str) -> Result<&'a Value> {
    rows(&row["definition"]["outputs"])?
        .iter()
        .find(|p| p["name"] == name)
        .ok_or(INVALID)
}
fn instances<'a>(declarations: &Value, nodes: &'a [Value]) -> Result<BTreeMap<String, &'a Value>> {
    let declarations = rows(declarations)?;
    let mut found = BTreeMap::new();
    for declaration in declarations {
        let key = name(&declaration["instance_key"])?;
        let row = nodes.iter().find(|n| n["alias"] == key).ok_or(INVALID)?;
        let definition = &row["definition"];
        for field in ["kind", "type_id", "semantic_version"] {
            if definition[field] != declaration["type_reference"][field] {
                return Err(INVALID);
            }
        }
        for (parameter, value) in declaration["parameters"].as_object().ok_or(INVALID)? {
            if value["kind"] != "FIXED" || value["value"] != definition["parameters"][parameter] {
                return Err(INVALID);
            }
        }
        let bindings = rows(&declaration["input_bindings"])?;
        if bindings.len()
            != definition["input_bindings"]
                .as_object()
                .ok_or(INVALID)?
                .len()
        {
            return Err(INVALID);
        }
        for binding in bindings {
            let reference = &definition["input_bindings"][name(&binding["input_name"])?];
            if let Some(source) = binding["source"].as_str() {
                if reference["source"] != source || !reference["node_fingerprint"].is_null() {
                    return Err(INVALID);
                }
            } else {
                let source = &binding["source"];
                let parent = nodes
                    .iter()
                    .find(|n| n["alias"] == source["instance_key"])
                    .ok_or(INVALID)?;
                if reference["node_fingerprint"] != node_fingerprint(parent)?
                    || reference["output_name"] != source["output_name"]
                    || !reference["source"].is_null()
                {
                    return Err(INVALID);
                }
            }
        }
        for port in rows(&declaration["published_outputs"])? {
            output(row, name(port)?)?;
        }
        if found.insert(key.to_owned(), row).is_some() {
            return Err(INVALID);
        }
    }
    Ok(found)
}
fn compile_template(nodes: &[Value], ids: &BTreeMap<String, String>) -> Result<Value> {
    if ids.values().collect::<BTreeSet<_>>().len() != ids.len() {
        return Err(INVALID);
    }
    let mut template_nodes = vec![];
    for row in nodes {
        let definition = &row["definition"];
        let mut bindings = vec![];
        for (input, reference) in definition["input_bindings"].as_object().ok_or(INVALID)? {
            let parent = if let Some(fp) = reference["node_fingerprint"].as_str() {
                json!(ids.get(fp).ok_or(INVALID)?)
            } else {
                Value::Null
            };
            bindings.push(json!({"input_name":input,"reference":{"template_node_id":parent,"output_name":reference["output_name"],"source":reference["source"]}}));
        }
        template_nodes.push(json!({"template_node_id":ids.get(&node_fingerprint(row)?).ok_or(INVALID)?,"type_reference":{"kind":definition["kind"],"type_id":definition["type_id"],"semantic_version":definition["semantic_version"]},"parameters":definition["parameters"],"input_bindings":bindings,"alias":null}));
    }
    Ok(json!({"schema_version":1,"nodes":template_nodes}))
}
// Public ordering is a literal key only; serialization/fingerprinting continues
// through the existing canonical JSON owner. Values here have fixed shallow shape.
fn python_literal(value: &Value) -> String {
    match value {
        Value::Null => "None".into(),
        Value::Bool(v) => {
            if *v {
                "True".into()
            } else {
                "False".into()
            }
        }
        Value::Number(v) => v.to_string(),
        Value::String(v) => {
            let quote = if v.contains('\'') && !v.contains('"') {
                '"'
            } else {
                '\''
            };
            let mut out = String::from(quote);
            for c in v.chars() {
                if c == quote || c == '\\' {
                    out.push('\\');
                    out.push(c);
                } else {
                    let debug = c.escape_debug().to_string();
                    if debug.starts_with("\\u{") {
                        let n = u32::from(c);
                        out.push_str(&if n < 256 {
                            format!("\\x{n:02x}")
                        } else if n <= 65535 {
                            format!("\\u{n:04x}")
                        } else {
                            format!("\\U{n:08x}")
                        });
                    } else if c == '\'' || c == '"' {
                        out.push(c);
                    } else {
                        out.push_str(&debug);
                    }
                }
            }
            out.push(quote);
            out
        }
        Value::Array(v) => format!(
            "[{}]",
            v.iter().map(python_literal).collect::<Vec<_>>().join(", ")
        ),
        Value::Object(v) => format!(
            "{{{}}}",
            v.iter()
                .map(|(k, v)| format!("{}: {}", python_literal(&json!(k)), python_literal(v)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::{
        private_strategy::Definition,
        strategy_research::{Context, DecisionGraph},
    };
    use onlyalpha_calculation::product::Graph;
    use serde_json::{Value, json};

    fn fixture() -> Value {
        serde_json::from_str(include_str!(
            "../../../tests/application/fixtures/strategy_specification.json"
        ))
        .unwrap()
    }
    fn input() -> (Definition, Context, Graph, Value) {
        let case: Value = serde_json::from_str(include_str!(
            "../../../tests/application/fixtures/strategy_calculations.json"
        ))
        .unwrap();
        let seed: Value = serde_json::from_str(include_str!(
            "../../../../../examples/private-assets/strategy/simple_momentum/strategy.json"
        ))
        .unwrap();
        let mut strategy = seed["strategy"]["definition"].clone();
        strategy["calculations"] = case["instances"].clone();
        strategy["factor_revision_dependencies"] = case["factor_revision_dependencies"].clone();
        let f = fixture();
        let context = Context::new(json!({"schema_version":1,"start":"2025-01-02T12:00:00Z","end":"2025-01-03T00:00:00Z","targets":[{"instance_key":"forward_return","type_reference":{"kind":"TARGET","type_id":"onlyalpha.target.forward_return","semantic_version":"1"},"parameters":{"exit_offset":{"kind":"FIXED","value":{"type":"INTEGER","value":5}}},"published_outputs":["target_value"],"primary_output":null,"input_bindings":[{"input_name":"entry_price","source":"bar.close"},{"input_name":"exit_price","source":"bar.close"}]}],"statistics":[{"variable":{"kind":"VARIABLE","instance_key":"momentum","output_name":"value"},"target_instance_key":"forward_return","definition":f["specification"]["statistics"][0]["definition"]}],"display_metadata":{"title":"Research title"}})).unwrap();
        let target = Graph::from_record(&json!({"schema_version":1,"nodes":[{"alias":"forward_return","definition":f["target_definition"]}]}),8*1024*1024).unwrap();
        (
            Definition::from_record(&strategy).unwrap(),
            context,
            target,
            case["nodes"].clone(),
        )
    }
    #[test]
    fn public2_roundtrip_matches_independent_public_value_vector() {
        let vector = fixture();
        let spec = Specification::from_record(&vector["specification"]).unwrap();
        assert_eq!(spec.record(), &vector["specification"]);
        assert_eq!(
            spec.fingerprint().unwrap(),
            vector["specification_fingerprint"].as_str().unwrap()
        );
        let mut reordered = spec.record().clone();
        reordered["calculations"].as_array_mut().unwrap().reverse();
        reordered["evidence"]["published_series"]
            .as_array_mut()
            .unwrap()
            .reverse();
        assert_eq!(
            Specification::from_record(&reordered)
                .unwrap()
                .fingerprint()
                .unwrap(),
            spec.fingerprint().unwrap()
        );
        let mut changed = spec.record().clone();
        changed["dataset_snapshot_fingerprint"] = json!("e".repeat(64));
        assert_ne!(
            Specification::from_record(&changed)
                .unwrap()
                .fingerprint()
                .unwrap(),
            spec.fingerprint().unwrap()
        );
        let mut typed = spec.record().clone();
        typed["calculations"][0]["graph_template"]["nodes"][0]["parameters"] = json!({"null":{"type":"NULL","value":null},"bool":{"type":"BOOLEAN","value":true},"integer":{"type":"INTEGER","value":1},"decimal":{"type":"DECIMAL","value":"1.0"},"string":{"type":"STRING","value":"1"}});
        assert_eq!(Specification::from_record(&typed).unwrap().record(), &typed);
    }
    #[test]
    fn derives_existing_public2_without_display_or_execution_identity() {
        let (strategy, context, target, observed) = input();
        let decision = DecisionGraph::derive(&strategy, &observed).unwrap();
        let definition = context.definition(&strategy).unwrap();
        let spec = Specification::derive(&definition, &decision, &target, &"d".repeat(64)).unwrap();
        let record = spec.record();
        assert_eq!(record.as_object().unwrap().len(), 5);
        assert_eq!(record["schema_version"], 2);
        assert_eq!(record["evidence"]["candidate_calculation_id"], "decision");
        assert_eq!(record["calculations"].as_array().unwrap().len(), 2);
        assert!(
            record["calculations"]
                .as_array()
                .unwrap()
                .iter()
                .all(|c| c["sweep_dimensions"] == json!([]))
        );
        assert_eq!(record["statistics"][0]["expansion"], "BROADCAST_SINGLETON");
        assert_eq!(
            record["statistics"][0]["definition"]["universe_policy"],
            "OBSERVED_PAIRWISE"
        );
        assert_eq!(
            record["statistics"][0]["feature"]["calculation_id"],
            "decision"
        );
        assert_eq!(
            record["statistics"][0]["target"]["calculation_id"],
            "target.forward_return"
        );
        for role in ["eligibility", "entry", "exit"] {
            assert!(!record["evidence"]["signals"][role].is_null());
        }
        for forbidden in [
            "display_metadata",
            "authoring",
            "composition",
            "execution_binding",
            "runtime_generation_fingerprint",
            "research_context_fingerprint",
        ] {
            assert!(record.get(forbidden).is_none());
        }
        let mut renamed = context.record().clone();
        renamed["display_metadata"] = json!({"title":"Different label"});
        let other = Context::new(renamed)
            .unwrap()
            .definition(&strategy)
            .unwrap();
        assert_eq!(
            Specification::derive(&other, &decision, &target, &"d".repeat(64))
                .unwrap()
                .fingerprint()
                .unwrap(),
            spec.fingerprint().unwrap()
        );
        assert_eq!(Specification::from_record(record).unwrap().record(), record);
        // A value-level source relation is required even when all calculation
        // nodes match; threshold/universe changes must not borrow another graph.
        let mut other_strategy = strategy.to_record();
        other_strategy["signals"]["entry"]["right"]["value"]["value"] = json!("0.5");
        let other_definition = context
            .definition(&Definition::from_record(&other_strategy).unwrap())
            .unwrap();
        assert!(
            Specification::derive(&other_definition, &decision, &target, &"d".repeat(64)).is_err()
        );
        other_strategy = strategy.to_record();
        other_strategy["universe"]["instruments"] = json!(["OTHER.XSHG"]);
        let other_definition = context
            .definition(&Definition::from_record(&other_strategy).unwrap())
            .unwrap();
        assert!(
            Specification::derive(&other_definition, &decision, &target, &"d".repeat(64)).is_err()
        );
    }
    #[test]
    fn rejects_nonfixed_unclosed_cyclic_and_foreign_records() {
        let base = fixture()["specification"].clone();
        for change in [
            "unknown",
            "schema",
            "dataset",
            "sweep",
            "selector",
            "duplicate",
            "cycle",
            "scalar",
            "statistics",
        ] {
            let mut bad = base.clone();
            match change {
                "unknown" => bad["execution_binding"] = json!({}),
                "schema" => bad["schema_version"] = json!(5),
                "dataset" => bad["dataset_snapshot_fingerprint"] = json!("latest"),
                "sweep" => bad["calculations"][0]["sweep_dimensions"] = json!([{}]),
                "selector" => {
                    bad["evidence"]["published_series"][0]["template_node_id"] = json!("missing")
                }
                "duplicate" => {
                    let node = bad["calculations"][0]["graph_template"]["nodes"][0].clone();
                    bad["calculations"][0]["graph_template"]["nodes"]
                        .as_array_mut()
                        .unwrap()
                        .push(node);
                }
                "cycle" => {
                    let id =
                        bad["calculations"][0]["graph_template"]["nodes"][0]["template_node_id"]
                            .clone();
                    bad["calculations"][0]["graph_template"]["nodes"][0]["input_bindings"][0]["reference"] =
                        json!({"template_node_id":id,"output_name":"value","source":null});
                }
                "scalar" => {
                    bad["calculations"][0]["graph_template"]["nodes"][0]["parameters"]["period"] =
                        json!({"type":"INTEGER","value":true})
                }
                "statistics" => {
                    bad["statistics"][0]["definition"]["universe_policy"] = json!("TIME_SERIES")
                }
                _ => unreachable!(),
            }
            assert!(Specification::from_record(&bad).is_err(), "{change}");
        }
        let mut oversized = base.clone();
        oversized["calculations"][0]["graph_template"]["nodes"][0]["parameters"]["resource_bound"] =
            json!({"type":"STRING","value":"x".repeat(8*1024*1024)});
        assert!(Specification::from_record(&oversized).is_err());
        let (strategy, context, target, observed) = input();
        let decision = DecisionGraph::derive(&strategy, &observed).unwrap();
        assert!(
            Specification::derive(
                &context.definition(&strategy).unwrap(),
                &decision,
                &target,
                "latest"
            )
            .is_err()
        );
    }
}
