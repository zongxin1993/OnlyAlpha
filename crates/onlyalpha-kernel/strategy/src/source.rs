//! Current public Strategy source value; no Freeze, publication or execution grant.
use crate::model::{object, record_fingerprint};
use onlyalpha_calculation::product::{Error as CalculationError, Graph};
use onlyalpha_domain::{
    base::OnlyDomainModel, identifiers::OnlyInstrumentId, market::OnlyBarSemantic,
};
use onlyalpha_market_data_construction::OnlyConstructionRecipe;
use serde_json::{Value, json};
use std::{collections::BTreeMap, fmt};
pub(crate) const SOURCE_WORK: usize = 8 * 1024 * 1024;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SourceError {
    Invalid,
    Unavailable,
}
impl SourceError {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "STRATEGY_SOURCE_CONTRACT_INVALID",
            Self::Unavailable => "STRATEGY_SOURCE_READ_UNAVAILABLE",
        }
    }
}
impl fmt::Display for SourceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for SourceError {}
impl From<CalculationError> for SourceError {
    fn from(e: CalculationError) -> Self {
        match e {
            CalculationError::Invalid => Self::Invalid,
            CalculationError::Unavailable => Self::Unavailable,
        }
    }
}
type Result<T> = std::result::Result<T, SourceError>;
fn exact(v: &Value, keys: &[&str]) -> Result<()> {
    object(v, keys)
        .map(|_| ())
        .map_err(|_| SourceError::Invalid)
}
fn text(v: &Value) -> Result<&str> {
    v.as_str().ok_or(SourceError::Invalid)
}
fn sha(v: &Value) -> Result<&str> {
    crate::model::sha(v).map_err(|_| SourceError::Invalid)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceRevision {
    pub(crate) graph: Graph,
    pub(crate) universe: Vec<OnlyInstrumentId>,
    pub(crate) semantic: OnlyBarSemantic,
    pub(crate) recipe: OnlyConstructionRecipe,
    pub(crate) bindings: BTreeMap<String, (String, String)>,
    pub(crate) signals: [(String, String); 3],
    fingerprint: String,
}
impl SourceRevision {
    /// Bounded parsing to a self-consistent value only. Frozen readers must still
    /// prove original canonical bytes, manifest/path and immutable Freeze relations.
    pub fn from_json(raw: &str, max_work: usize) -> Result<Self> {
        if raw.len() > max_work {
            return Err(SourceError::Unavailable);
        }
        let value = serde_json::from_str(raw).map_err(|_| SourceError::Invalid)?;
        Self::parse_value(&value, max_work)
    }
    pub(crate) fn parse_value(v: &Value, max_work: usize) -> Result<Self> {
        exact(
            v,
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
        if v["schema_version"].as_u64() != Some(1) {
            return Err(SourceError::Invalid);
        }
        let graph = Graph::from_record(&v["decision_graph"], max_work)?;
        if v["decision_graph_fingerprint"] != graph.fingerprint() {
            return Err(SourceError::Invalid);
        }
        let nodes: BTreeMap<_, _> = graph
            .ordered_nodes()
            .map(|d| (d.fingerprint(), d.to_record()))
            .collect();
        let rows = v["implementation_bindings"]
            .as_array()
            .ok_or(SourceError::Invalid)?;
        if rows.len() != nodes.len() {
            return Err(SourceError::Invalid);
        }
        let mut bindings = BTreeMap::new();
        for b in rows {
            exact(
                b,
                &[
                    "node_fingerprint",
                    "research_implementation_fingerprint",
                    "trading_implementation_fingerprint",
                ],
            )?;
            let id = sha(&b["node_fingerprint"])?;
            if bindings
                .insert(
                    id.to_owned(),
                    (
                        sha(&b["research_implementation_fingerprint"])?.to_owned(),
                        sha(&b["trading_implementation_fingerprint"])?.to_owned(),
                    ),
                )
                .is_some()
            {
                return Err(SourceError::Invalid);
            }
        }
        if !bindings.keys().eq(nodes.keys())
            || v["implementation_bindings"] != binding_record(&bindings)
        {
            return Err(SourceError::Invalid);
        }
        let u = &v["universe"];
        exact(u, &["kind", "instruments"])?;
        let instruments = u["instruments"].as_array().ok_or(SourceError::Invalid)?;
        if instruments.is_empty() {
            return Err(SourceError::Invalid);
        }
        if instruments.len() > max_work {
            return Err(SourceError::Unavailable);
        }
        let mut universe = instruments
            .iter()
            .map(|id| {
                text(id)?
                    .parse::<OnlyInstrumentId>()
                    .map_err(|_| SourceError::Invalid)
            })
            .collect::<Result<Vec<_>>>()?;
        universe.sort_by_key(ToString::to_string);
        if universe.windows(2).any(|pair| pair[0] == pair[1])
            || u["kind"]
                != if universe.len() == 1 {
                    "SINGLE_INSTRUMENT"
                } else {
                    "EXPLICIT_INSTRUMENT_SET"
                }
        {
            return Err(SourceError::Invalid);
        }
        let contract = &v["market_input_contract"];
        exact(
            contract,
            &[
                "schema_version",
                "data_kind",
                "bar_semantic",
                "construction_requirement",
                "observation_admission",
            ],
        )?;
        if contract["schema_version"].as_u64() != Some(2)
            || contract["data_kind"] != "BAR"
            || contract["observation_admission"] != "FINAL_ONLY"
        {
            return Err(SourceError::Invalid);
        }
        let requirement = &contract["construction_requirement"];
        exact(requirement, &["schema_version", "kind", "policy", "recipe"])?;
        if requirement["schema_version"].as_u64() != Some(1)
            || requirement["kind"] != "EXACT_RECIPE"
            || !requirement["policy"].is_null()
        {
            return Err(SourceError::Invalid);
        }
        let semantic = OnlyBarSemantic::from_record(&contract["bar_semantic"])
            .map_err(|_| SourceError::Invalid)?;
        let recipe = OnlyConstructionRecipe::from_record(&requirement["recipe"])
            .map_err(|_| SourceError::Invalid)?;
        if recipe.target() != &semantic {
            return Err(SourceError::Invalid);
        }
        let s = &v["signal_semantics"];
        exact(
            s,
            &[
                "schema_version",
                "eligibility",
                "entry",
                "exit",
                "missing_decision",
            ],
        )?;
        if s["schema_version"].as_u64() != Some(1) || s["missing_decision"] != "FALSE" {
            return Err(SourceError::Invalid);
        }
        let mut signals = vec![];
        for (name, role) in [
            ("eligibility", "ELIGIBILITY"),
            ("entry", "ENTRY_SIGNAL"),
            ("exit", "EXIT_SIGNAL"),
        ] {
            let b = &s[name];
            exact(b, &["node_fingerprint", "output_name"])?;
            let id = sha(&b["node_fingerprint"])?;
            let output = text(&b["output_name"])?;
            if !output
                .chars()
                .any(|c| !c.is_whitespace() && !('\u{1c}'..='\u{1f}').contains(&c))
            {
                return Err(SourceError::Invalid);
            }
            let node = nodes.get(id).ok_or(SourceError::Invalid)?;
            let port = node["outputs"]
                .as_array()
                .expect("validated ports")
                .iter()
                .find(|p| p["name"] == output)
                .ok_or(SourceError::Invalid)?;
            if port["data_type"] != "BOOLEAN" || port["semantic_type"] != role {
                return Err(SourceError::Invalid);
            }
            signals.push((id.to_owned(), output.to_owned()));
        }
        let result = Self {
            graph,
            universe,
            semantic,
            recipe,
            bindings,
            signals: signals.try_into().map_err(|_| SourceError::Invalid)?,
            fingerprint: sha(&v["strategy_fingerprint"])?.to_owned(),
        };
        if result.fingerprint != record_fingerprint(&result.identity()) {
            return Err(SourceError::Invalid);
        }
        Ok(result)
    }
    fn identity(&self) -> Value {
        let signals: Vec<_> = self
            .signals
            .iter()
            .map(|(node, output)| json!({"node_fingerprint":node,"output_name":output}))
            .collect();
        json!({"domain":"onlyalpha.strategy.revision","schema_version":1,"universe":{"kind":if self.universe.len()==1{"SINGLE_INSTRUMENT"}else{"EXPLICIT_INSTRUMENT_SET"},"instruments":self.universe.iter().map(ToString::to_string).collect::<Vec<_>>()},"market_input_contract":{"schema_version":2,"data_kind":"BAR","bar_semantic":self.semantic.to_record(),"construction_requirement":{"schema_version":1,"kind":"EXACT_RECIPE","policy":null,"recipe":self.recipe.to_record()},"observation_admission":"FINAL_ONLY"},"decision_graph_fingerprint":self.graph.fingerprint(),"implementation_bindings":binding_record(&self.bindings),"signal_semantics":{"schema_version":1,"eligibility":signals[0],"entry":signals[1],"exit":signals[2],"missing_decision":"FALSE"}})
    }
    pub fn to_record(&self) -> Value {
        let mut v = self.identity();
        v.as_object_mut()
            .expect("constructed object")
            .remove("domain");
        v["strategy_fingerprint"] = json!(self.fingerprint);
        v["decision_graph"] = self.graph.to_record();
        v
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
}
fn binding_record(bindings: &BTreeMap<String, (String, String)>) -> Value {
    json!(bindings.iter().map(|(id,(research,trading))|json!({"node_fingerprint":id,"research_implementation_fingerprint":research,"trading_implementation_fingerprint":trading})).collect::<Vec<_>>())
}
