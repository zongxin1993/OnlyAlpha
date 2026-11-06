//! Existing public EquivalenceV2 identities over actual typed node observations.
use super::super::{INVALID, Result, hash};
use onlyalpha_calculation::product::{Graph, normalize_scalar};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
const PROFILE: &str = "ONLYALPHA_P9_CALCULATION_EQUIVALENCE_V2";
const CONTRACT: &str = "P9_CALCULATION_EQUIVALENCE_V2";
const BASE: [&str; 6] = [
    "FLAT_SEQUENCE",
    "NEGATIVE_SLOPE_SEQUENCE",
    "POSITIVE_SLOPE_SEQUENCE",
    "QUANTIZATION_BOUNDARY",
    "WARMUP_AND_STEADY_STATE",
    "ZERO_BOUNDARY",
];
fn array(value: &Value) -> Result<&Vec<Value>> {
    value.as_array().ok_or(INVALID)
}
fn text(value: &Value) -> Result<&str> {
    value.as_str().ok_or(INVALID)
}
fn typed(row: &Value, ports: &Value) -> Result<()> {
    let fields = row.as_object().ok_or(INVALID)?;
    let ports = array(ports)?;
    if fields.len() != ports.len() {
        return Err(INVALID);
    }
    for port in ports {
        let v = fields.get(text(&port["name"])?).ok_or(INVALID)?;
        if normalize_scalar(v, 8 * 1024 * 1024).map_err(|_| INVALID)? != *v {
            return Err(INVALID);
        }
        if v["type"] == "NULL" {
            if port["nullable"] != true {
                return Err(INVALID);
            }
        } else if v["type"] != port["data_type"] {
            return Err(INVALID);
        }
    }
    Ok(())
}
pub(crate) fn required(definition: &Value) -> Result<(Vec<String>, String)> {
    if definition["kind"] == "TARGET" || definition["factor_kind"] == "CROSS_SECTION" {
        return Err(INVALID);
    }
    let inputs = array(&definition["inputs"])?;
    let mut names = BASE
        .iter()
        .map(|s| (*s).to_owned())
        .collect::<BTreeSet<_>>();
    if inputs.iter().any(|p| p["nullable"] == true) {
        names.insert("NULLABLE_INPUT_SEMANTICS".into());
    }
    if inputs.iter().any(|p| p["data_type"] == "BOOLEAN") {
        names.insert("BOOLEAN_TRUTH_NULL_SEMANTICS".into());
    }
    if array(&definition["outputs"])?.len() > 1 {
        names.insert("MULTI_OUTPUT_ALIGNMENT".into());
    }
    let names = names.into_iter().collect::<Vec<_>>();
    let fingerprint = hash(
        &json!({"domain":"onlyalpha.calculation.equivalence-certification-profile","schema_version":1,
        "profile_id":PROFILE,"cases":names,"comparison_contract":"EXACT_TYPED_ORDERED_ROWS_V1"}),
    )?;
    Ok((names, fingerprint))
}
pub(crate) fn derive(graph: &Graph, bindings: &Value, observation: &Value) -> Result<Vec<Value>> {
    let profiles = array(&observation["node_profiles"])?;
    let mut index = BTreeMap::new();
    for value in profiles {
        let id = text(&value["node_fingerprint"])?;
        if index.insert(id, value).is_some() {
            return Err(INVALID);
        }
    }
    let bindings = array(bindings)?;
    let mut result = BTreeMap::new();
    for node in graph.ordered_nodes() {
        let id = node.fingerprint();
        let definition = node.to_record();
        let actual = index.remove(id.as_str()).ok_or(INVALID)?;
        super::super::exact(
            actual,
            &[
                "node_fingerprint",
                "research_implementation_fingerprint",
                "trading_implementation_fingerprint",
                "cases",
                "profile_covered_cases",
            ],
        )?;
        let binding = bindings
            .iter()
            .find(|b| b["node_fingerprint"] == id)
            .ok_or(INVALID)?;
        for role in [
            "research_implementation_fingerprint",
            "trading_implementation_fingerprint",
        ] {
            if actual[role] != binding[role] {
                return Err(INVALID);
            }
        }
        let (names, profile) = required(&definition)?;
        if actual["profile_covered_cases"] != json!(names) {
            return Err(INVALID);
        }
        let cases = array(&actual["cases"])?;
        if cases.len() != names.len() {
            return Err(INVALID);
        }
        let mut corpus = Vec::new();
        let mut research = Vec::new();
        let mut trading = Vec::new();
        for (case, name) in cases.iter().zip(&names) {
            super::super::exact(
                case,
                &["case_id", "inputs", "research_outputs", "trading_outputs"],
            )?;
            if case["case_id"] != *name {
                return Err(INVALID);
            }
            let inputs = array(&case["inputs"])?;
            let r = array(&case["research_outputs"])?;
            let t = array(&case["trading_outputs"])?;
            if inputs.is_empty()
                || inputs.len() > 8192
                || r.len() != inputs.len()
                || t.len() != inputs.len()
                || r != t
            {
                return Err(INVALID);
            }
            let minimum = definition["warmup"]["minimum_observations"]
                .as_u64()
                .and_then(|n| n.checked_add(2))
                .ok_or(INVALID)?;
            if (inputs.len() as u64) < minimum {
                return Err(INVALID);
            }
            let mut columns: serde_json::Map<String, Value> = serde_json::Map::new();
            for port in array(&definition["inputs"])? {
                columns.insert(text(&port["name"])?.into(), json!([]));
            }
            for (ordinal, ((input, r), t)) in inputs.iter().zip(r).zip(t).enumerate() {
                typed(input, &definition["inputs"])?;
                typed(r, &definition["outputs"])?;
                typed(t, &definition["outputs"])?;
                for (name, value) in input.as_object().ok_or(INVALID)? {
                    columns
                        .get_mut(name)
                        .ok_or(INVALID)?
                        .as_array_mut()
                        .ok_or(INVALID)?
                        .push(value.clone());
                }
                research.push(json!({"case_id":name,"ordinal":ordinal,"outputs":r}));
                trading.push(json!({"case_id":name,"ordinal":ordinal,"outputs":t}));
            }
            // The selected SDK profile factory consumes typed input vectors;
            // no Bar is supplied to that per-node method. Full graph Bar cases
            // remain a distinct actual observation in the original Run report.
            corpus.push(json!({"case_id":name,"inputs":columns,"bars":[]}));
        }
        let corpus = hash(
            &json!({"domain":"onlyalpha.calculation.equivalence-corpus","schema_version":2,
            "calculation_node_fingerprint":id,"certification_profile_fingerprint":profile,"cases":corpus}),
        )?;
        let output = |rows: &[Value]| {
            hash(
                &json!({"domain":"onlyalpha.calculation.equivalence-output","schema_version":2,
            "calculation_node_fingerprint":id,"rows":rows}),
            )
        };
        let r = output(&research)?;
        let t = output(&trading)?;
        if r != t {
            return Err(INVALID);
        }
        let comparison = hash(
            &json!({"domain":"onlyalpha.calculation.equivalence-comparison","schema_version":2,
            "calculation_node_fingerprint":id,"research_implementation_fingerprint":actual["research_implementation_fingerprint"],
            "trading_implementation_fingerprint":actual["trading_implementation_fingerprint"],"equivalence_contract_version":CONTRACT,
            "certification_profile_fingerprint":profile,"corpus_fingerprint":corpus,"research_output_fingerprint":r,
            "trading_output_fingerprint":t,"comparison":"EXACT_TYPED_ORDERED_ROWS"}),
        )?;
        let mut value = json!({"schema_version":2,"calculation_node_fingerprint":id,
            "calculation_type_reference":{"kind":definition["kind"],"type_id":definition["type_id"],"semantic_version":definition["semantic_version"]},
            "research_implementation_fingerprint":actual["research_implementation_fingerprint"],"trading_implementation_fingerprint":actual["trading_implementation_fingerprint"],
            "equivalence_contract_version":CONTRACT,"certification_profile_id":PROFILE,"certification_profile_fingerprint":profile,
            "corpus_fingerprint":corpus,"research_output_fingerprint":r,"trading_output_fingerprint":t,"comparison_fingerprint":comparison,"verdict":"EQUIVALENT"});
        let mut identity = value.clone();
        identity["domain"] = json!("onlyalpha.calculation.equivalence-evidence");
        let fingerprint = hash(&identity)?;
        value["evidence_fingerprint"] = json!(fingerprint);
        if result.insert(fingerprint, value).is_some() {
            return Err(INVALID);
        }
    }
    if !index.is_empty() || result.len() != bindings.len() {
        return Err(INVALID);
    }
    Ok(result.into_values().collect())
}
