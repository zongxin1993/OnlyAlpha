use crate::{OnlyDeliveryError, OnlyDeliveryResult, record::*};
use onlyalpha_domain::{base::OnlyDomainModel, identifiers::OnlyIdentifier, market::OnlyBarType};
use onlyalpha_market_data_construction::{OnlyConstructionGraph, OnlyConstructionInput};
use serde_json::{Value, json};
use std::collections::BTreeSet;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OnlyBarFreshness {
    LatestClosed,
    SameEventTime,
}
impl OnlyBarFreshness {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::LatestClosed => "LATEST_CLOSED",
            Self::SameEventTime => "SAME_EVENT_TIME",
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyBarSubscription {
    id: OnlyIdentifier,
    types: Vec<OnlyBarType>,
    graph: OnlyConstructionGraph,
    primary: OnlyBarType,
    freshness: OnlyBarFreshness,
}
fn key(kind: &OnlyBarType) -> String {
    kind.to_record().to_string()
}
impl OnlyBarSubscription {
    pub fn new(
        id: &str,
        mut types: Vec<OnlyBarType>,
        graph: OnlyConstructionGraph,
        primary: Option<OnlyBarType>,
        freshness: OnlyBarFreshness,
    ) -> OnlyDeliveryResult<Self> {
        let id = identifier(id)?;
        types.sort_by_key(key);
        let Some(first) = types.first() else {
            return Err(OnlyDeliveryError::Configuration);
        };
        let instrument = first.instrument_id();
        let keys: BTreeSet<_> = types.iter().map(key).collect();
        if keys.len() != types.len() || types.iter().any(|kind| kind.instrument_id() != instrument)
        {
            return Err(OnlyDeliveryError::Configuration);
        }
        let graph_keys: BTreeSet<_> = graph
            .providers()
            .iter()
            .filter_map(|input| match input {
                OnlyConstructionInput::Bar(kind) => Some(key(kind)),
                _ => None,
            })
            .chain(graph.edges().iter().map(|edge| key(edge.target())))
            .collect();
        if graph_keys != keys
            || graph
                .providers()
                .iter()
                .any(|input| input.instrument() != instrument)
            || graph
                .edges()
                .iter()
                .any(|edge| edge.target().instrument_id() != instrument)
        {
            return Err(OnlyDeliveryError::Configuration);
        }
        let primary = match primary {
            Some(kind) => kind,
            None => {
                if types
                    .iter()
                    .any(|kind| !kind.semantic().is_fixed_duration())
                {
                    return Err(OnlyDeliveryError::Configuration);
                }
                types
                    .iter()
                    .min_by(|a, b| {
                        a.semantic()
                            .stride_minutes()
                            .expect("fixed duration")
                            .cmp(b.semantic().stride_minutes().expect("fixed duration"))
                            .then_with(|| key(a).cmp(&key(b)))
                    })
                    .expect("nonempty types")
                    .clone()
            }
        };
        if !keys.contains(&key(&primary)) {
            return Err(OnlyDeliveryError::Configuration);
        }
        Ok(Self {
            id,
            types,
            graph,
            primary,
            freshness,
        })
    }
    pub fn id(&self) -> &OnlyIdentifier {
        &self.id
    }
    pub fn bar_types(&self) -> &[OnlyBarType] {
        &self.types
    }
    pub fn graph(&self) -> &OnlyConstructionGraph {
        &self.graph
    }
    pub fn primary(&self) -> &OnlyBarType {
        &self.primary
    }
    pub fn freshness(&self) -> OnlyBarFreshness {
        self.freshness
    }
    pub fn to_record(&self) -> Value {
        json!({"schema_version":1,"subscription_id":self.id.value(),"bar_types":self.types.iter().map(OnlyDomainModel::to_record).collect::<Vec<_>>(),"dependency_graph":self.graph.to_record(),"primary_bar_type":self.primary.to_record(),"delivery_mode":"PRIMARY_ONLY","freshness_policy":self.freshness.as_str()})
    }
    pub fn from_record(value: &Value) -> OnlyDeliveryResult<Self> {
        let row = object(
            value,
            &[
                "schema_version",
                "subscription_id",
                "bar_types",
                "dependency_graph",
                "primary_bar_type",
                "delivery_mode",
                "freshness_policy",
            ],
        )?;
        if text(&row["delivery_mode"])? != "PRIMARY_ONLY" {
            return Err(OnlyDeliveryError::Configuration);
        }
        let freshness = match text(&row["freshness_policy"])? {
            "LATEST_CLOSED" => OnlyBarFreshness::LatestClosed,
            "SAME_EVENT_TIME" => OnlyBarFreshness::SameEventTime,
            _ => return Err(OnlyDeliveryError::Configuration),
        };
        let types = array(&row["bar_types"])?
            .iter()
            .map(|raw| OnlyBarType::from_record(raw).map_err(invalid))
            .collect::<OnlyDeliveryResult<_>>()?;
        Self::new(
            text(&row["subscription_id"])?,
            types,
            OnlyConstructionGraph::from_record(&row["dependency_graph"]).map_err(invalid)?,
            Some(OnlyBarType::from_record(&row["primary_bar_type"]).map_err(invalid)?),
            freshness,
        )
    }
}
