use crate::{model::*, record::*};
use serde_json::json;
use std::collections::BTreeMap;
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyConstructionProviderLane {
    input: OnlyConstructionInput,
    lane_id: String,
}
impl OnlyConstructionProviderLane {
    pub fn input(&self) -> &OnlyConstructionInput {
        &self.input
    }
    pub fn lane_id(&self) -> &str {
        &self.lane_id
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyCompiledConstructionLane {
    edge: OnlyConstructionEdge,
    lane_id: String,
    source_lane_id: String,
    level: usize,
}
impl OnlyCompiledConstructionLane {
    pub fn edge(&self) -> &OnlyConstructionEdge {
        &self.edge
    }
    pub fn lane_id(&self) -> &str {
        &self.lane_id
    }
    pub fn source_lane_id(&self) -> &str {
        &self.source_lane_id
    }
    pub fn level(&self) -> usize {
        self.level
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyConstructionPlan {
    graph_fingerprint: String,
    providers: Vec<OnlyConstructionProviderLane>,
    lanes: Vec<OnlyCompiledConstructionLane>,
}
impl OnlyConstructionPlan {
    pub fn compile(graph: &OnlyConstructionGraph, source: &str) -> OnlyConstructionResult<Self> {
        nonempty(source)?;
        let providers:Vec<_>=graph.providers().iter().map(|input|OnlyConstructionProviderLane{input:input.clone(),lane_id:hash(&json!({"schema_version":1,"kind":"PROVIDER_INPUT","input_type":input.to_record(),"source_binding_identity":source}))}).collect();
        let mut by_input: BTreeMap<_, _> = providers
            .iter()
            .map(|p| (p.input.key(), p.lane_id.clone()))
            .collect();
        let mut ordered = graph.ordered_edges()?;
        ordered.sort_by_key(|(edge, level)| {
            (*level, edge.lane_id(source).expect("validated binding"))
        });
        let mut lanes = vec![];
        for (edge, level) in ordered {
            let lane_id = edge.lane_id(source)?;
            let source_lane_id = by_input
                .get(&edge.source().key())
                .ok_or_else(|| err("COMPILE_SOURCE"))?
                .clone();
            by_input.insert(
                OnlyConstructionInput::Bar(edge.target().clone()).key(),
                lane_id.clone(),
            );
            lanes.push(OnlyCompiledConstructionLane {
                edge,
                lane_id,
                source_lane_id,
                level,
            });
        }
        Ok(Self {
            graph_fingerprint: graph.fingerprint(),
            providers,
            lanes,
        })
    }
    pub fn graph_fingerprint(&self) -> &str {
        &self.graph_fingerprint
    }
    pub fn providers(&self) -> &[OnlyConstructionProviderLane] {
        &self.providers
    }
    pub fn lanes(&self) -> &[OnlyCompiledConstructionLane] {
        &self.lanes
    }
}
