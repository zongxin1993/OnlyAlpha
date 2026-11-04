//! Exact materialization of verified current public source, retaining its identity.
use crate::{
    model::*,
    source::{SOURCE_WORK, SourceError, SourceRevision},
};
use onlyalpha_calculation::{Definition, Graph, product::Definition as ProductDefinition};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
impl Revision {
    /// Actual descriptors are resolved by the admitted owner, not fabricated by a
    /// source reader. Every original source edge and implementation remains proved.
    pub fn from_product(
        source: Value,
        descriptors: Vec<NodeDescriptor>,
        mapping: BTreeMap<String, String>,
    ) -> StrategyResult<Self> {
        // These remain executable component bounds, never source-history validity.
        if source["decision_graph"]["nodes"]
            .as_array()
            .is_none_or(|a| a.len() > 64)
            || source["universe"]["instruments"]
                .as_array()
                .is_none_or(|a| {
                    a.len() > 16 || a.iter().any(|s| s.as_str().is_none_or(|s| s.len() > 4096))
                })
        {
            return Err(bad());
        }
        let parsed = SourceRevision::parse_value(&source, SOURCE_WORK).map_err(|e| match e {
            SourceError::Invalid => bad(),
            SourceError::Unavailable => StrategyError(e.code()),
        })?;
        let nodes: BTreeMap<_, _> = parsed
            .graph
            .ordered_nodes()
            .map(|d| (d.fingerprint(), d.to_record()))
            .collect();
        if nodes.is_empty() || nodes.keys().ne(mapping.keys()) || mapping.len() != descriptors.len()
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
            for r in expected["input_bindings"]
                .as_object_mut()
                .expect("validated bindings")
                .values_mut()
            {
                if let Some(parent) = r["node_fingerprint"].as_str() {
                    r["node_fingerprint"] = json!(mapping.get(parent).ok_or_else(bad)?);
                }
            }
            let native =
                ProductDefinition::from_record(&expected, SOURCE_WORK).map_err(|_| bad())?;
            if d.native_definition != native.fingerprint()
                || d.implementation != parsed.bindings[original].1
            {
                return Err(bad());
            }
            // Compare the actual typed component projection, retaining the independent
            // original Product identity above, including Decimal scale and signed zero.
            expected["schema_version"] = json!(3);
            if d.definition != Definition::from_record(&expected).map_err(|_| bad())? {
                return Err(bad());
            }
        }
        let signals = parsed
            .signals
            .iter()
            .map(|(id, output)| SignalBinding::new(mapping.get(id).ok_or_else(bad)?, output))
            .collect::<StrategyResult<Vec<_>>>()?;
        if source["universe"]["instruments"]
            != json!(
                parsed
                    .universe
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()
            )
        {
            return Err(bad());
        }
        let fingerprint = parsed.fingerprint().to_owned();
        let mut result = Self::new(
            parsed.universe,
            parsed.semantic,
            parsed.recipe,
            Graph::new(
                descriptors
                    .iter()
                    .map(|d| (d.definition.clone(), None))
                    .collect(),
            )
            .map_err(|_| bad())?,
            descriptors,
            signals.try_into().map_err(|_| bad())?,
        )?;
        result.product = Some(json!({"source":source,"mapping":mapping}));
        result.fingerprint = fingerprint;
        Ok(result)
    }
}
