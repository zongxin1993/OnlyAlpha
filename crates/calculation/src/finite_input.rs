//! Pure graph dependency preparation, independent of market axes, Source and Target policy.
use crate::product::{Error, Graph};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Requirements {
    history: u64,
    sources: BTreeSet<String>,
}
impl Requirements {
    pub fn history(&self) -> u64 {
        self.history
    }
    pub fn sources(&self) -> &BTreeSet<String> {
        &self.sources
    }
}
/// Compose each node's own warmup with its longest upstream path. The exclusive
/// limit is caller-controlled; no Source reads or synthetic execution occur.
pub fn requirements(graph: &Graph, history_limit: u64) -> Result<Requirements, Error> {
    let mut histories = BTreeMap::new();
    let mut sources = BTreeSet::new();
    for definition in graph.ordered_nodes() {
        let record = definition.to_record();
        let mut upstream = 0_u64;
        for binding in record["input_bindings"]
            .as_object()
            .ok_or(Error::Invalid)?
            .values()
        {
            if let Some(parent) = binding["node_fingerprint"].as_str() {
                upstream = upstream.max(*histories.get(parent).ok_or(Error::Invalid)?);
            } else {
                sources.insert(binding["source"].as_str().ok_or(Error::Invalid)?.to_owned());
            }
        }
        let own = record["warmup"]["minimum_observations"]
            .as_u64()
            .filter(|n| *n > 0)
            .ok_or(Error::Invalid)?
            - 1;
        let history = upstream
            .checked_add(own)
            .filter(|n| *n < history_limit)
            .ok_or(Error::Unavailable)?;
        histories.insert(definition.fingerprint(), history);
    }
    Ok(Requirements {
        history: histories.values().copied().max().ok_or(Error::Invalid)?,
        sources,
    })
}
