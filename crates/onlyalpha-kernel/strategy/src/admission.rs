//! Exact materialization of the existing public Strategy Revision; no new Strategy identity.
use crate::model::*;
use onlyalpha_calculation::{Definition, Graph};
use onlyalpha_domain::{
    base::OnlyDomainModel, identifiers::OnlyInstrumentId, market::OnlyBarSemantic,
};
use onlyalpha_market_data_construction::OnlyConstructionRecipe;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

fn semantic(definition: &Value) -> StrategyResult<Value> {
    let mut value = definition.clone();
    if value["schema_version"] != 2 {
        return Err(bad());
    }
    let mut checked = value.clone();
    checked["schema_version"] = json!(3);
    if Definition::from_record(&checked)
        .map_err(|_| bad())?
        .to_record()
        != checked
    {
        return Err(bad());
    }
    for field in ["parameters", "extensions"] {
        for scalar in value[field].as_object_mut().ok_or_else(bad)?.values_mut() {
            object(scalar, &["type", "value"])?;
            *scalar = scalar["value"].clone();
        }
    }
    Ok(value)
}
fn visit(
    id: &str,
    nodes: &BTreeMap<String, Value>,
    seen: &mut BTreeSet<String>,
    active: &mut BTreeSet<String>,
    ordered: &mut Vec<Value>,
) -> StrategyResult<()> {
    if seen.contains(id) {
        return Ok(());
    }
    if !active.insert(id.into()) {
        return Err(bad());
    }
    let node = nodes.get(id).ok_or_else(bad)?;
    let mut references = node["input_bindings"]
        .as_object()
        .ok_or_else(bad)?
        .values()
        .collect::<Vec<_>>();
    references.sort_by_key(|r| {
        (
            r["node_fingerprint"].as_str().unwrap_or(""),
            r["output_name"].as_str().unwrap_or(""),
            r["source"].as_str().unwrap_or(""),
        )
    });
    for reference in references {
        if let Some(parent) = reference["node_fingerprint"].as_str() {
            visit(parent, nodes, seen, active, ordered)?;
        }
    }
    active.remove(id);
    seen.insert(id.into());
    ordered.push(semantic(node)?);
    Ok(())
}
impl Revision {
    /// Descriptors must be resolved by the admitted node owner; every semantic edge is compared here.
    pub fn from_product(
        source: Value,
        descriptors: Vec<NodeDescriptor>,
        mapping: BTreeMap<String, String>,
    ) -> StrategyResult<Self> {
        object(
            &source,
            &[
                "schema_version",
                "strategy_fingerprint",
                "universe",
                "market_input_contract",
                "decision_graph_fingerprint",
                "decision_graph",
                "implementation_bindings",
                "signal_semantics",
            ],
        )?;
        if source["schema_version"] != 1 || source["decision_graph"]["schema_version"] != 1 {
            return Err(bad());
        }
        object(&source["decision_graph"], &["schema_version", "nodes"])?;
        let contract = &source["market_input_contract"];
        object(
            contract,
            &[
                "schema_version",
                "data_kind",
                "bar_semantic",
                "construction_requirement",
                "observation_admission",
            ],
        )?;
        if contract["schema_version"] != 2
            || contract["data_kind"] != "BAR"
            || contract["observation_admission"] != "FINAL_ONLY"
            || contract["construction_requirement"]["kind"] != "EXACT_RECIPE"
            || !contract["construction_requirement"]["policy"].is_null()
        {
            return Err(bad());
        }
        object(
            &contract["construction_requirement"],
            &["schema_version", "kind", "policy", "recipe"],
        )?;
        if contract["construction_requirement"]["schema_version"] != 1 {
            return Err(bad());
        }
        let mut nodes = BTreeMap::new();
        for row in array(&source["decision_graph"]["nodes"])? {
            object(row, &["definition", "alias"])?;
            let d = &row["definition"];
            let id = record_fingerprint(&semantic(d)?);
            if nodes.insert(id, d.clone()).is_some() {
                return Err(bad());
            }
        }
        if nodes.is_empty()
            || nodes.len() > 64
            || nodes.keys().ne(mapping.keys())
            || mapping.len() != descriptors.len()
        {
            return Err(bad());
        }
        let mut ordered = vec![];
        let mut seen = BTreeSet::new();
        let mut active = BTreeSet::new();
        for id in nodes.keys() {
            visit(id, &nodes, &mut seen, &mut active, &mut ordered)?;
        }
        if source["decision_graph_fingerprint"]
            != record_fingerprint(&json!({"schema_version":1,"nodes":ordered}))
        {
            return Err(bad());
        }
        let mut bindings = BTreeMap::new();
        for b in array(&source["implementation_bindings"])? {
            object(
                b,
                &[
                    "node_fingerprint",
                    "research_implementation_fingerprint",
                    "trading_implementation_fingerprint",
                ],
            )?;
            sha(&b["research_implementation_fingerprint"])?;
            sha(&b["trading_implementation_fingerprint"])?;
            if bindings
                .insert(sha(&b["node_fingerprint"])?.to_owned(), b)
                .is_some()
            {
                return Err(bad());
            }
        }
        if bindings.keys().ne(nodes.keys())
            || source["implementation_bindings"] != json!(bindings.values().collect::<Vec<_>>())
        {
            return Err(bad());
        }
        let ds: BTreeMap<_, _> = descriptors
            .iter()
            .map(|d| (d.definition.fingerprint(), d))
            .collect();
        if ds.len() != mapping.len()
            || mapping.values().collect::<BTreeSet<_>>().len() != mapping.len()
        {
            return Err(bad());
        }
        for (original, compiled) in &mapping {
            let d = ds.get(compiled).ok_or_else(bad)?;
            let mut expected = nodes[original].clone();
            for reference in expected["input_bindings"]
                .as_object_mut()
                .ok_or_else(bad)?
                .values_mut()
            {
                if let Some(parent) = reference["node_fingerprint"].as_str() {
                    reference["node_fingerprint"] = json!(mapping.get(parent).ok_or_else(bad)?);
                }
            }
            if d.native_definition != record_fingerprint(&semantic(&expected)?)
                || d.implementation != bindings[original]["trading_implementation_fingerprint"]
            {
                return Err(bad());
            }
            expected["schema_version"] = json!(3);
            if d.definition.to_record() != expected {
                return Err(bad());
            }
        }
        let signals = &source["signal_semantics"];
        object(
            signals,
            &[
                "schema_version",
                "eligibility",
                "entry",
                "exit",
                "missing_decision",
            ],
        )?;
        if signals["schema_version"] != 1 || signals["missing_decision"] != "FALSE" {
            return Err(bad());
        }
        let compiled_signals = ["eligibility", "entry", "exit"]
            .map(|name| {
                let b = SignalBinding::from_record(&signals[name])?;
                SignalBinding::new(mapping.get(&b.node).ok_or_else(bad)?, &b.output)
            })
            .into_iter()
            .collect::<StrategyResult<Vec<_>>>()?;
        let universe = &source["universe"];
        object(universe, &["kind", "instruments"])?;
        let instruments = array(&universe["instruments"])?;
        if universe["kind"]
            != if instruments.len() == 1 {
                "SINGLE_INSTRUMENT"
            } else {
                "EXPLICIT_INSTRUMENT_SET"
            }
        {
            return Err(bad());
        }
        let ids = instruments
            .iter()
            .map(|v| text(v)?.parse::<OnlyInstrumentId>().map_err(|_| bad()))
            .collect::<StrategyResult<Vec<_>>>()?;
        let mut result = Self::new(
            ids,
            OnlyBarSemantic::from_record(&contract["bar_semantic"]).map_err(|_| bad())?,
            OnlyConstructionRecipe::from_record(&contract["construction_requirement"]["recipe"])
                .map_err(|_| bad())?,
            Graph::new(
                descriptors
                    .iter()
                    .map(|d| (d.definition.clone(), None))
                    .collect(),
            )
            .map_err(|_| bad())?,
            descriptors,
            compiled_signals.try_into().map_err(|_| bad())?,
        )?;
        if source["universe"]["instruments"]
            != json!(
                result
                    .universe()
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()
            )
        {
            return Err(bad());
        }
        let mut identity = source.clone();
        identity
            .as_object_mut()
            .ok_or_else(bad)?
            .remove("decision_graph");
        identity
            .as_object_mut()
            .ok_or_else(bad)?
            .remove("strategy_fingerprint");
        identity["domain"] = json!("onlyalpha.strategy.revision");
        if source["strategy_fingerprint"] != record_fingerprint(&identity) {
            return Err(bad());
        }
        result.product = Some(json!({"source":source,"mapping":mapping}));
        result.fingerprint = sha(&source["strategy_fingerprint"])?.to_owned();
        Ok(result)
    }
}
