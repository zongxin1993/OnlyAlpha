//! Exact public SourceRevision materialization shared by Research and Backtest.
//! Installed capabilities describe mathematical state; none grants execution.
use onlyalpha_calculation::{
    Definition as ComponentDefinition,
    product::{Definition, Graph},
};
use onlyalpha_strategy::{NodeDescriptor, Program, Revision, Scope, SourceRevision};
use serde_json::{Value, json};
use std::collections::BTreeMap;
const WORK: usize = 8 * 1024 * 1024;
const INVALID: &str = "TRADING_NODE_CAPABILITIES_INVALID";
type Result<T> = std::result::Result<T, &'static str>;
fn text(v: &Value) -> Result<&str> {
    v.as_str().ok_or(INVALID)
}
pub(crate) type MaterializedTradingProgram = (
    Program,
    BTreeMap<String, Definition>,
    BTreeMap<String, String>,
);
pub(crate) fn materialize(
    source: &SourceRevision,
    scope: Scope,
    generation: &str,
    market_source: &str,
    artifact: &str,
    capabilities: &Value,
) -> Result<MaterializedTradingProgram> {
    let record = source.to_record();
    let graph = Graph::from_record(&record["decision_graph"], WORK).map_err(|_| INVALID)?;
    let bindings = record["implementation_bindings"]
        .as_array()
        .ok_or(INVALID)?
        .iter()
        .map(|row| Ok((text(&row["node_fingerprint"])?.to_owned(), row)))
        .collect::<Result<BTreeMap<_, _>>>()?;
    let mut caps = BTreeMap::new();
    for row in capabilities.as_array().ok_or(INVALID)? {
        crate::application::private_strategy::exact(
            row,
            &[
                "node_fingerprint",
                "implementation_fingerprint",
                "state_capability",
                "checkpoint_schema_version",
            ],
        )
        .map_err(|_| INVALID)?;
        if caps
            .insert(text(&row["node_fingerprint"])?.to_owned(), row)
            .is_some()
        {
            return Err(INVALID);
        }
    }
    let mut mapping = BTreeMap::new();
    let mut definitions = BTreeMap::new();
    let mut descriptors = Vec::new();
    for definition in graph.ordered_nodes() {
        let original = definition.fingerprint();
        let mut value = definition.to_record();
        let binding = bindings.get(&original).ok_or(INVALID)?;
        let (capability, schema) = if value["kind"] == "PREDICATE" {
            ("STATELESS".to_owned(), None)
        } else {
            let cap = caps.remove(&original).ok_or(INVALID)?;
            if cap["implementation_fingerprint"] != binding["trading_implementation_fingerprint"] {
                return Err(INVALID);
            }
            let capability = text(&cap["state_capability"])?;
            let schema = cap["checkpoint_schema_version"].as_u64();
            if schema.is_none() && !cap["checkpoint_schema_version"].is_null()
                || !matches!(
                    (capability, schema),
                    ("STATELESS", None) | ("CHECKPOINTABLE", Some(1..))
                )
            {
                return Err(INVALID);
            }
            (capability.to_owned(), schema)
        };
        for reference in value["input_bindings"]
            .as_object_mut()
            .ok_or(INVALID)?
            .values_mut()
        {
            if let Some(parent) = reference["node_fingerprint"].as_str() {
                reference["node_fingerprint"] = json!(mapping.get(parent).ok_or(INVALID)?);
            }
        }
        let native = Definition::from_record(&value, WORK).map_err(|_| INVALID)?;
        value["schema_version"] = json!(3);
        let component = ComponentDefinition::from_record(&value).map_err(|_| INVALID)?;
        mapping.insert(original, component.fingerprint());
        definitions.insert(component.fingerprint(), native.clone());
        descriptors.push(NodeDescriptor {
            definition: component,
            native_definition: native.fingerprint(),
            implementation: text(&binding["trading_implementation_fingerprint"])?.into(),
            state_capability: capability,
            checkpoint_schema: schema,
        });
    }
    if !caps.is_empty() {
        return Err(INVALID);
    }
    let revision = Revision::from_product(source.to_record(), descriptors, mapping.clone())
        .map_err(|_| INVALID)?;
    let program =
        Program::new(revision, scope, generation, market_source, artifact).map_err(|_| INVALID)?;
    Ok((program, definitions, mapping))
}
