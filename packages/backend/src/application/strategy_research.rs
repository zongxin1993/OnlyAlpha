//! Strategy-owned semantics and research-only context remain separate values.
//! These values do not grant execution, Freeze or promotion.
use crate::application::{
    factor_content::hash,
    private_strategy::{self as strategy, Definition, Variables},
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use serde_json::{Value, json};
use std::collections::BTreeSet;
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "PRIVATE_STRATEGY_RESEARCH_CONTEXT_INVALID";
const UNAVAILABLE: &str = "PRIVATE_STRATEGY_RESEARCH_CONTEXT_UNAVAILABLE";
const WORK: usize = 8 * 1024 * 1024;
mod decision;
pub use decision::DecisionGraph;
mod resolution;
pub use resolution::ResolvedCalculations;
fn mapped(e: &'static str) -> &'static str {
    if e.ends_with("UNAVAILABLE") {
        UNAVAILABLE
    } else {
        INVALID
    }
}
fn exact(v: &Value, keys: &[&str]) -> Result<()> {
    strategy::exact(v, keys).map_err(mapped)
}
fn name(v: &Value) -> Result<&str> {
    strategy::name(v).map_err(mapped)
}
fn rows(v: &Value) -> Result<&Vec<Value>> {
    strategy::rows(v).map_err(mapped)
}
/// The existing public Research Context1, not an execution configuration.
#[derive(Clone, Debug)]
pub struct Context(Value);
impl Context {
    pub fn new(mut value: Value) -> Result<Self> {
        if value.to_string().len() > WORK {
            return Err(UNAVAILABLE);
        }
        exact(
            &value,
            &[
                "schema_version",
                "start",
                "end",
                "targets",
                "statistics",
                "display_metadata",
            ],
        )?;
        if value["schema_version"] != 1 || !value["display_metadata"].is_object() {
            return Err(INVALID);
        }
        let start = name(&value["start"])?
            .parse::<OnlyUtcDateTime>()
            .map_err(|_| INVALID)?;
        let end = name(&value["end"])?
            .parse::<OnlyUtcDateTime>()
            .map_err(|_| INVALID)?;
        if start >= end
            || rows(&value["targets"])?.is_empty()
            || rows(&value["statistics"])?.is_empty()
        {
            return Err(INVALID);
        }
        let mut work = WORK;
        let (targets, _) =
            strategy::normalize_instances(&mut value["targets"], &["TARGET"], &mut work)
                .map_err(mapped)?;
        for request in value["statistics"].as_array_mut().ok_or(INVALID)? {
            exact(request, &["variable", "target_instance_key", "definition"])?;
            exact(
                &request["variable"],
                &["kind", "instance_key", "output_name"],
            )?;
            if request["variable"]["kind"] != "VARIABLE"
                || !targets.contains_key(name(&request["target_instance_key"])?)
            {
                return Err(INVALID);
            }
            name(&request["variable"]["instance_key"])?;
            name(&request["variable"]["output_name"])?;
            let d = &mut request["definition"];
            exact(
                d,
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
            if d["schema_version"] != 1
                || !matches!(d["method"].as_str(), Some("IC" | "RANK_IC"))
                || d["minimum_observations"].as_u64().is_none_or(|v| v < 2)
                || d["pairing_policy"] != "PAIRWISE_COMPLETE"
                || d["universe_policy"] != "OBSERVED_PAIRWISE"
                || d["rank_tie_method"] != "AVERAGE"
                || d["weighting"] != "EQUAL"
            {
                return Err(INVALID);
            }
            let n = &mut d["numeric"];
            exact(
                n,
                &["representation", "precision", "output_quantum", "rounding"],
            )?;
            let quantum = strategy::scalar(
                &json!({"type":"DECIMAL","value":n["output_quantum"]}),
                &mut work,
            )
            .map_err(mapped)?;
            if n["representation"] != "DECIMAL"
                || n["precision"] != 38
                || quantum["value"] != "0.000000000001"
                || n["rounding"] != "ROUND_HALF_EVEN"
            {
                return Err(INVALID);
            }
            n["output_quantum"] = quantum["value"].clone();
        }
        value["statistics"]
            .as_array_mut()
            .ok_or(INVALID)?
            .sort_by_cached_key(|s| {
                (
                    s["variable"]["instance_key"].to_string(),
                    s["variable"]["output_name"].to_string(),
                    s["target_instance_key"].to_string(),
                    s["definition"].to_string(),
                )
            });
        let context = Self(value);
        context.fingerprint()?;
        Ok(context)
    }
    pub fn record(&self) -> &Value {
        &self.0
    }
    pub fn fingerprint(&self) -> Result<String> {
        let mut value = self.0.clone();
        value["contract"] = json!("ONLYALPHA_PRIVATE_STRATEGY_RESEARCH_CONTEXT_V1");
        hash(&value).map_err(mapped)
    }

    /// Pure authoring derivation. The owning composer must still re-anchor exact
    /// Strategy/Factor revisions, Catalog and selected Runtime capabilities.
    pub fn definition(&self, strategy: &Definition) -> Result<ResearchDefinition> {
        let d = strategy.to_record();
        let calculations = rows(&d["calculations"])?;
        let mut all = calculations.clone();
        all.extend(rows(&self.0["targets"])?.iter().cloned());
        let mut variables = Variables::new();
        let mut feature_variables = Variables::new();
        for c in &all {
            let outputs = rows(&c["published_outputs"])?
                .iter()
                .map(|v| name(v).map(str::to_owned))
                .collect::<Result<BTreeSet<_>>>()?;
            let key = name(&c["instance_key"])?.to_owned();
            if variables.insert(key.clone(), outputs.clone()).is_some() {
                return Err(INVALID);
            }
            if c["type_reference"]["kind"] != "TARGET" {
                feature_variables.insert(key, outputs);
            }
        }
        strategy::validate_instances(&all, &variables).map_err(mapped)?;
        for request in rows(&self.0["statistics"])? {
            strategy::variable(&request["variable"], &feature_variables).map_err(mapped)?;
        }
        let value = json!({"schema_version":1,"dataset":{"universe":{"kind":d["universe"]["kind"],"instrument_ids":d["universe"]["instruments"],"registered_id":null},"bar_semantic":d["market_input"]["bar_semantic"],"start":self.0["start"],"end":self.0["end"]},"calculations":d["calculations"],"eligibility":d["eligibility"],"signals":d["signals"],"targets":self.0["targets"],"statistics":self.0["statistics"],"display_metadata":self.0["display_metadata"]});
        if value.to_string().len() > WORK {
            return Err(UNAVAILABLE);
        }
        let definition = ResearchDefinition(value);
        definition.fingerprint()?;
        Ok(definition)
    }
}
/// Public Research Definition1 identity. No executable or evidence authority.
#[derive(Clone, Debug)]
pub struct ResearchDefinition(Value);
impl ResearchDefinition {
    pub fn record(&self) -> &Value {
        &self.0
    }
    pub fn fingerprint(&self) -> Result<String> {
        let mut value = self.0.clone();
        value
            .as_object_mut()
            .ok_or(INVALID)?
            .remove("display_metadata");
        for key in ["calculations", "targets"] {
            for c in value[key].as_array_mut().ok_or(INVALID)? {
                c.as_object_mut().ok_or(INVALID)?.remove("primary_output");
            }
        }
        value["eligibility"] = canonical_expression(&value["eligibility"])?;
        for role in ["entry", "exit"] {
            value["signals"][role] = canonical_expression(&value["signals"][role])?;
        }
        hash(&value).map_err(mapped)
    }
}
fn canonical_expression(value: &Value) -> Result<Value> {
    match value["kind"].as_str() {
        Some("COMPARISON") => Ok(value.clone()),
        Some("NOT") => Ok(json!({"kind":"NOT","operand":canonical_expression(&value["operand"])?})),
        Some("AND" | "OR") => {
            let kind = &value["kind"];
            let mut children = vec![];
            for child in rows(&value["operands"])? {
                let child = canonical_expression(child)?;
                if &child["kind"] == kind {
                    children.extend(rows(&child["operands"])?.iter().cloned());
                } else {
                    children.push(child);
                }
            }
            let mut keyed = children
                .into_iter()
                .map(|c| Ok((hash(&c).map_err(mapped)?, c)))
                .collect::<Result<Vec<_>>>()?;
            keyed.sort_by(|a, b| a.0.cmp(&b.0));
            Ok(json!({"kind":kind,"operands":keyed.into_iter().map(|(_,c)|c).collect::<Vec<_>>()}))
        }
        _ => Err(INVALID),
    }
}
/// Composition1 lineage value. This constructor validates values only; the
/// production composer must re-anchor revisions through PostgreSQL and retain
/// the exact RuntimeInputHold. It grants no Run, admission or Freeze authority.
#[derive(Clone, Debug)]
pub struct Composition(Value);
impl Composition {
    pub fn derive(
        revision: &Value,
        context: &Context,
        manifest: &Value,
        factors: &std::collections::BTreeMap<String, Value>,
    ) -> Result<Self> {
        const INVALID: &str = "PRIVATE_STRATEGY_COMPOSITION_INVALID";
        const MISMATCH: &str = "PRIVATE_STRATEGY_COMPOSITION_FACTOR_BINDING_MISMATCH";
        let mut size = revision
            .to_string()
            .len()
            .checked_add(context.record().to_string().len())
            .and_then(|n| n.checked_add(manifest.to_string().len()))
            .ok_or(UNAVAILABLE)?;
        for factor in factors.values() {
            size = size
                .checked_add(factor.to_string().len())
                .ok_or(UNAVAILABLE)?;
        }
        if size > WORK {
            return Err(UNAVAILABLE);
        }
        crate::application::private_assets::revision("STRATEGY", revision).map_err(|_| INVALID)?;
        let definition = Definition::from_record(&revision["definition"]).map_err(|_| INVALID)?;
        let d = definition.to_record();
        let research = context.definition(&definition)?;
        let dependencies = rows(&d["factor_revision_dependencies"])?;
        if dependencies.len() != factors.len()
            || !manifest["catalog_generation_fingerprint"]
                .as_str()
                .is_some_and(crate::is_sha256_hex)
        {
            return Err(INVALID);
        }
        let bindings = manifest["private_factor_bindings"]
            .as_array()
            .ok_or(INVALID)?;
        let implementations = manifest["implementations"].as_array().ok_or(INVALID)?;
        for dependency in dependencies {
            let id = dependency["factor_id"].as_str().ok_or(INVALID)?;
            let factor = factors.get(id).ok_or(MISMATCH)?;
            crate::application::private_assets::revision("FACTOR", factor).map_err(|_| INVALID)?;
            if factor["factor_id"] != id
                || factor["revision_fingerprint"] != dependency["revision_fingerprint"]
            {
                return Err(MISMATCH);
            }
            let mut matched = bindings.iter().filter(|b| b["entry"]["factor_id"] == id);
            let binding = matched.next().ok_or(MISMATCH)?;
            if matched.next().is_some() {
                return Err(MISMATCH);
            }
            for key in [
                "provider_snapshot_fingerprint",
                "runtime_artifact_fingerprint",
            ] {
                if !binding[key].as_str().is_some_and(crate::is_sha256_hex) {
                    return Err(MISMATCH);
                }
            }
            let entry = &binding["entry"];
            for key in [
                "factor_id",
                "revision_fingerprint",
                "semantic_version",
                "source_sha256",
                "factor_api_version",
                "factor_api_contract_fingerprint",
            ] {
                if entry[key] != factor[key] {
                    return Err(MISMATCH);
                }
            }
            if !entry["research_implementation_fingerprint"]
                .as_str()
                .is_some_and(crate::is_sha256_hex)
                || implementations
                    .iter()
                    .filter(|i| {
                        i["kind"] == "FACTOR"
                            && i["type_id"] == id
                            && i["semantic_version"] == factor["semantic_version"]
                            && i["backend"] == "RESEARCH"
                            && i["implementation_fingerprint"]
                                == entry["research_implementation_fingerprint"]
                    })
                    .count()
                    != 1
            {
                return Err(MISMATCH);
            }
        }
        for calculation in rows(&d["calculations"])?
            .iter()
            .chain(rows(&context.record()["targets"])?)
        {
            let reference = &calculation["type_reference"];
            let mut matched = implementations.iter().filter(|i| {
                i["kind"] == reference["kind"]
                    && i["type_id"] == reference["type_id"]
                    && i["semantic_version"] == reference["semantic_version"]
                    && i["backend"] == "RESEARCH"
            });
            let implementation = matched
                .next()
                .ok_or("PRIVATE_STRATEGY_CALCULATION_UNAVAILABLE")?;
            if matched.next().is_some()
                || !implementation["implementation_fingerprint"]
                    .as_str()
                    .is_some_and(crate::is_sha256_hex)
            {
                return Err(INVALID);
            }
            if reference["kind"] == "FACTOR"
                && reference["type_id"]
                    .as_str()
                    .is_some_and(|id| id.starts_with("private.factor."))
            {
                let factor = factors
                    .get(reference["type_id"].as_str().ok_or(INVALID)?)
                    .ok_or(MISMATCH)?;
                if reference["semantic_version"] != factor["semantic_version"] {
                    return Err(MISMATCH);
                }
            }
        }
        let mut record = json!({"schema_version":1,"private_strategy_id":revision["strategy_id"],"private_strategy_revision_fingerprint":revision["revision_fingerprint"],"private_strategy_definition_fingerprint":revision["definition_fingerprint"],"research_context_fingerprint":context.fingerprint()?,"factor_revision_bindings":dependencies,"catalog_generation_fingerprint":manifest["catalog_generation_fingerprint"],"research_definition_fingerprint":research.fingerprint()?});
        record["contract"] = json!("ONLYALPHA_PRIVATE_STRATEGY_RESEARCH_COMPOSITION_V1");
        let fingerprint = hash(&record).map_err(|_| INVALID)?;
        record.as_object_mut().ok_or(INVALID)?.remove("contract");
        record["composition_fingerprint"] = json!(fingerprint);
        Ok(Self(record))
    }
    pub fn record(&self) -> &Value {
        &self.0
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::{factor_content::hash, private_strategy::Definition};
    use serde_json::{Value, json};
    fn strategy() -> Value {
        let seed: Value = serde_json::from_str(include_str!(
            "../../../../examples/private-assets/strategy/simple_momentum/strategy.json"
        ))
        .unwrap();
        let mut definition = seed["strategy"]["definition"].clone();
        definition["factor_revision_dependencies"] = json!([{"factor_id":"private.factor.simple_momentum","revision_fingerprint":"a".repeat(64)}]);
        definition
    }
    fn context() -> Value {
        json!({"schema_version":1,"start":"2025-01-02T12:00:00Z","end":"2025-01-03T00:00:00Z",
         "targets":[{"instance_key":"forward_return","type_reference":{"kind":"TARGET","type_id":"onlyalpha.target.forward_return","semantic_version":"1"},"parameters":{"exit_offset":{"kind":"FIXED","value":{"type":"INTEGER","value":5}}},"published_outputs":["target_value"],"primary_output":null,"input_bindings":[{"input_name":"entry_price","source":"bar.close"},{"input_name":"exit_price","source":"bar.close"}]}],
         "statistics":[{"variable":{"kind":"VARIABLE","instance_key":"momentum","output_name":"value"},"target_instance_key":"forward_return","definition":{"schema_version":1,"method":"IC","minimum_observations":2,"pairing_policy":"PAIRWISE_COMPLETE","universe_policy":"OBSERVED_PAIRWISE","rank_tie_method":"AVERAGE","weighting":"EQUAL","numeric":{"representation":"DECIMAL","precision":38,"output_quantum":"0.000000000001","rounding":"ROUND_HALF_EVEN"}}}],"display_metadata":{}})
    }
    fn calculation_fixture() -> Value {
        serde_json::from_str(include_str!(
            "../../tests/application/fixtures/strategy_calculations.json"
        ))
        .unwrap()
    }
    #[test]
    fn decision_graph_lowers_the_exact_calculations_and_three_native_terminals() {
        let fixture = calculation_fixture();
        let mut value = strategy();
        value["calculations"] = fixture["instances"].clone();
        value["factor_revision_dependencies"] = fixture["factor_revision_dependencies"].clone();
        let definition = Definition::from_record(&value).unwrap();
        let graph = DecisionGraph::derive(&definition, &fixture["nodes"]).unwrap();
        assert_eq!(graph.graph().ordered_nodes().count(), 9);
        let record = graph.record();
        assert_eq!(
            record["decision_graph_fingerprint"],
            fixture["reference_decision_graph_fingerprint"]
        );
        assert_eq!(
            record["signal_semantics"],
            fixture["reference_signal_semantics"]
        );
        for (role, semantic) in [
            ("eligibility", "ELIGIBILITY"),
            ("entry", "ENTRY_SIGNAL"),
            ("exit", "EXIT_SIGNAL"),
        ] {
            let id = record["signal_semantics"][role]["node_fingerprint"]
                .as_str()
                .unwrap();
            let node = graph
                .graph()
                .ordered_nodes()
                .find(|d| d.fingerprint() == id)
                .unwrap()
                .to_record();
            assert_eq!(node["outputs"][0]["semantic_type"], semantic);
            onlyalpha_calculation_bridge::native_predicates::PredicateCalculation::from_record(
                &node,
            )
            .unwrap();
        }
        assert_eq!(record["signal_semantics"]["missing_decision"], "FALSE");
        assert!(record.get("strategy_fingerprint").is_none());
        let mut changed = fixture["nodes"].clone();
        let row = changed
            .as_array_mut()
            .unwrap()
            .iter_mut()
            .find(|r| r["definition"]["type_id"] == "onlyalpha.operator.delay")
            .unwrap();
        row["definition"]["parameters"]["period"]["value"] = json!(19);
        row["definition_fingerprint"] = json!(
            onlyalpha_calculation::product::Definition::from_record(&row["definition"], WORK)
                .unwrap()
                .fingerprint()
        );
        assert!(DecisionGraph::derive(&definition, &changed).is_err());
        assert!(DecisionGraph::derive(&definition, &json!([])).is_err());
    }
    #[test]
    fn decision_graph_boolean_order_is_canonical_and_never_changes_strategy_semantics() {
        let fixture = calculation_fixture();
        let mut value = strategy();
        value["calculations"] = fixture["instances"].clone();
        value["factor_revision_dependencies"] = fixture["factor_revision_dependencies"].clone();
        let a = value["eligibility"].clone();
        let b = value["signals"]["entry"].clone();
        value["signals"]["entry"] = json!({"kind":"AND","operands":[a,b]});
        let first =
            DecisionGraph::derive(&Definition::from_record(&value).unwrap(), &fixture["nodes"])
                .unwrap();
        value["signals"]["entry"]["operands"]
            .as_array_mut()
            .unwrap()
            .reverse();
        let second =
            DecisionGraph::derive(&Definition::from_record(&value).unwrap(), &fixture["nodes"])
                .unwrap();
        assert_eq!(first.graph().fingerprint(), second.graph().fingerprint());
        value["signals"]["entry"] = json!({"kind":"COMPARISON","operator":">","left":{"kind":"LITERAL","data_type":"DECIMAL","value":{"type":"DECIMAL","value":"2"}},"right":{"kind":"LITERAL","data_type":"DECIMAL","value":{"type":"DECIMAL","value":"1"}}});
        assert!(
            DecisionGraph::derive(&Definition::from_record(&value).unwrap(), &fixture["nodes"])
                .is_err()
        );
    }
    fn composition_inputs() -> (
        Value,
        Context,
        Value,
        std::collections::BTreeMap<String, Value>,
    ) {
        use crate::application::private_assets::authoring::{
            API_FINGERPRINT, Draft as FactorDraft,
        };
        let factor=FactorDraft::new(json!({"schema_version":1,"factor_id":"private.factor.simple_momentum","semantic_version":"1","base_revision_fingerprint":null,"source_text":"def calculate(api, inputs, parameters):\n    return {'value': inputs['close']}\n","factor_api_version":1,"factor_api_contract_fingerprint":API_FINGERPRINT,"input_contract":{"close":{"type":"DECIMAL"},"previous_close":{"type":"DECIMAL"}},"parameter_contract":{},"output_contract":{"value":{"type":"DECIMAL"}},"description":"Technical metadata fixture","economic_rationale":"Contract only","category":"price","tags":[]})).unwrap().revision().unwrap();
        let mut d = strategy();
        d["factor_revision_dependencies"][0]["revision_fingerprint"] =
            factor["revision_fingerprint"].clone();
        let revision=crate::application::private_strategy::Draft::new(json!({"schema_version":1,"strategy_id":"private.strategy.composition","semantic_version":"1","base_revision_fingerprint":null,"definition":d,"description":"Contract fixture","tags":[]})).unwrap().revision().unwrap();
        let context = Context::new(context()).unwrap();
        // Only value-level metadata. No READY/executable/equivalence claim is made.
        let manifest = json!({"catalog_generation_fingerprint":"a".repeat(64),"private_factor_bindings":[{"provider_snapshot_fingerprint":"b".repeat(64),"runtime_artifact_fingerprint":"c".repeat(64),"entry":{"factor_id":factor["factor_id"],"revision_fingerprint":factor["revision_fingerprint"],"semantic_version":factor["semantic_version"],"source_sha256":factor["source_sha256"],"factor_api_version":factor["factor_api_version"],"factor_api_contract_fingerprint":factor["factor_api_contract_fingerprint"],"research_implementation_fingerprint":"d".repeat(64)}}],"implementations":[{"kind":"FACTOR","type_id":factor["factor_id"],"semantic_version":"1","backend":"RESEARCH","implementation_fingerprint":"d".repeat(64)},{"kind":"TARGET","type_id":"onlyalpha.target.forward_return","semantic_version":"1","backend":"RESEARCH","implementation_fingerprint":"e".repeat(64)}]});
        let factors =
            std::collections::BTreeMap::from([("private.factor.simple_momentum".into(), factor)]);
        (revision, context, manifest, factors)
    }
    #[test]
    fn composition_is_exact_lineage_and_not_a_second_strategy_or_runtime_identity() {
        let (revision, context, manifest, factors) = composition_inputs();
        let composition = Composition::derive(&revision, &context, &manifest, &factors).unwrap();
        let record = composition.record();
        assert_eq!(
            record["private_strategy_revision_fingerprint"],
            revision["revision_fingerprint"]
        );
        assert_eq!(
            record["research_definition_fingerprint"],
            context
                .definition(&Definition::from_record(&revision["definition"]).unwrap())
                .unwrap()
                .fingerprint()
                .unwrap()
        );
        assert!(record.get("strategy_fingerprint").is_none());
        assert!(record.get("runtime_generation_fingerprint").is_none());
        let mut descriptor = record.clone();
        descriptor
            .as_object_mut()
            .unwrap()
            .remove("composition_fingerprint");
        descriptor["contract"] = json!("ONLYALPHA_PRIVATE_STRATEGY_RESEARCH_COMPOSITION_V1");
        assert_eq!(
            record["composition_fingerprint"],
            hash(&descriptor).unwrap()
        );
        assert_eq!(
            Composition::derive(&revision, &context, &manifest, &factors)
                .unwrap()
                .record(),
            record
        );
    }
    #[test]
    fn composition_rejects_missing_or_changed_exact_factor_and_runtime_capabilities() {
        let (revision, context, manifest, factors) = composition_inputs();
        assert!(
            Composition::derive(
                &revision,
                &context,
                &manifest,
                &std::collections::BTreeMap::new()
            )
            .is_err()
        );
        for key in [
            "revision_fingerprint",
            "source_sha256",
            "semantic_version",
            "factor_api_contract_fingerprint",
        ] {
            let mut changed = manifest.clone();
            changed["private_factor_bindings"][0]["entry"][key] = json!("f".repeat(64));
            assert!(
                Composition::derive(&revision, &context, &changed, &factors).is_err(),
                "{key}"
            );
        }
        let mut changed = manifest.clone();
        changed["private_factor_bindings"] = json!([]);
        assert!(Composition::derive(&revision, &context, &changed, &factors).is_err());
        let mut changed = manifest.clone();
        changed["implementations"][1]["backend"] = json!("TRADING");
        assert!(Composition::derive(&revision, &context, &changed, &factors).is_err());
        let mut changed = manifest;
        changed["implementations"][0]["semantic_version"] = json!("2");
        assert!(Composition::derive(&revision, &context, &changed, &factors).is_err());
    }
    #[test]
    fn context_derives_the_public_research_definition_without_overriding_strategy() {
        let strategy = Definition::from_record(&strategy()).unwrap();
        let before = strategy.fingerprint().unwrap();
        let context = Context::new(context()).unwrap();
        let definition = context.definition(&strategy).unwrap();
        let value = definition.record();
        assert_eq!(value["schema_version"], 1);
        assert_eq!(value["dataset"]["start"], "2025-01-02T12:00:00Z");
        assert_eq!(
            value["dataset"]["universe"],
            json!({"kind":"SINGLE_INSTRUMENT","instrument_ids":["TEST.XSHG"],"registered_id":null})
        );
        assert_eq!(value["signals"], strategy.to_record()["signals"]);
        assert_eq!(value["calculations"], strategy.to_record()["calculations"]);
        assert!(value.get("factor_revision_dependencies").is_none());
        assert_eq!(strategy.fingerprint().unwrap(), before);
        let mut semantic = value.clone();
        semantic.as_object_mut().unwrap().remove("display_metadata");
        for key in ["calculations", "targets"] {
            for calculation in semantic[key].as_array_mut().unwrap() {
                calculation
                    .as_object_mut()
                    .unwrap()
                    .remove("primary_output");
            }
        }
        assert_eq!(definition.fingerprint().unwrap(), hash(&semantic).unwrap());
    }
    #[test]
    fn target_instance_names_follow_the_same_public_authoring_contract() {
        for bad in ["ForwardReturn", "1return", "with.dot", "收益"] {
            let mut value = context();
            value["targets"][0]["instance_key"] = json!(bad);
            value["statistics"][0]["target_instance_key"] = json!(bad);
            assert!(Context::new(value).is_err(), "accepted {bad}");
        }
    }
    #[test]
    fn context_cannot_override_strategy_or_accept_unclosed_or_future_inputs() {
        let strategy = Definition::from_record(&strategy()).unwrap();
        for key in [
            "signals",
            "market_input",
            "universe",
            "account",
            "execution",
        ] {
            let mut value = context();
            value[key] = json!({});
            assert!(Context::new(value).is_err(), "{key}");
        }
        for key in ["targets", "statistics"] {
            let mut value = context();
            value[key] = json!([]);
            assert!(Context::new(value).is_err());
        }
        for start in [
            "2025-01-02T12:00:00",
            "2025-01-02T12:00:00+08:00",
            "2025-01-04T00:00:00Z",
        ] {
            let mut value = context();
            value["start"] = json!(start);
            assert!(Context::new(value).is_err());
        }
        let mut value = context();
        value["targets"][0]["parameters"]["exit_offset"]["kind"] = json!("SWEEP");
        assert!(Context::new(value).is_err());
        let mut value = context();
        value["targets"][0]["instance_key"] = json!("momentum");
        assert!(
            Context::new(value)
                .and_then(|c| c.definition(&strategy))
                .is_err()
        );
        let mut value = context();
        value["statistics"][0]["variable"]["instance_key"] = json!("missing");
        assert!(
            Context::new(value)
                .and_then(|c| c.definition(&strategy))
                .is_err()
        );
        let mut value = context();
        value["statistics"][0]["target_instance_key"] = json!("missing");
        assert!(Context::new(value).is_err());
        let mut value = context();
        value["targets"][0]["input_bindings"][0]["source"] =
            json!({"kind":"VARIABLE","instance_key":"missing","output_name":"value"});
        assert!(
            Context::new(value)
                .and_then(|c| c.definition(&strategy))
                .is_err()
        );
    }
    #[test]
    fn research_identity_canonicalizes_boolean_structure_and_excludes_presentation() {
        let mut a = strategy();
        let comparison = a["signals"]["entry"].clone();
        let other = a["signals"]["exit"].clone();
        a["eligibility"] =
            json!({"kind":"AND","operands":[comparison.clone(),other.clone(),comparison.clone()]});
        let mut b = a.clone();
        b["eligibility"] = json!({"kind":"AND","operands":[other,{"kind":"AND","operands":[comparison.clone(),comparison]}]});
        let c = Context::new(context()).unwrap();
        let first = c.definition(&Definition::from_record(&a).unwrap()).unwrap();
        let second = c.definition(&Definition::from_record(&b).unwrap()).unwrap();
        assert_eq!(first.fingerprint().unwrap(), second.fingerprint().unwrap());
        let mut changed = context();
        changed["display_metadata"] = json!({"title":"different title"});
        let changed = Context::new(changed).unwrap();
        assert_ne!(changed.fingerprint().unwrap(), c.fingerprint().unwrap());
        assert_eq!(
            changed
                .definition(&Definition::from_record(&a).unwrap())
                .unwrap()
                .fingerprint()
                .unwrap(),
            first.fingerprint().unwrap()
        );
        let mut changed = context();
        changed["start"] = json!("2025-01-02T13:00:00Z");
        let changed = Context::new(changed).unwrap();
        assert_ne!(
            changed
                .definition(&Definition::from_record(&a).unwrap())
                .unwrap()
                .fingerprint()
                .unwrap(),
            first.fingerprint().unwrap()
        );
    }
}
