//! Actual native mathematical owners shared by preparation certification and
//! finite execution. READY comes only from the PostgreSQL reader.
use crate::application::factor_build::ReadyFactorBinding;
use onlyalpha_calculation::{
    product::{Definition, Graph},
    program::{ProgramInput, ProgramInstance, ProgramValue, evaluate_batch},
};
use onlyalpha_calculation_bridge::{
    ProgramFactor, ProgramNodes,
    native_operators::{OperatorCalculation, OperatorStream},
    native_predicates::PredicateCalculation,
};
use serde_json::{Value, json};
use std::{collections::BTreeMap, str::FromStr, sync::Arc};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "NATIVE_SIGNAL_PROGRAM_MISMATCH";
fn batch_content_fingerprint(value: &Value) -> Result<String> {
    use crate::persistence::job_publication::{PublicationError, content_fingerprint};
    content_fingerprint(value).map_err(|error| match error {
        PublicationError::BudgetExceeded => "FINITE_CANDIDATE_BUDGET_EXCEEDED",
        _ => INVALID,
    })
}
enum Owner {
    Factor(Box<ReadyFactorBinding>),
    Operator(OperatorCalculation),
    Predicate(PredicateCalculation),
}
pub(crate) struct SignalPrograms {
    owners: BTreeMap<String, Owner>,
    image: String,
    graph: String,
    research: BTreeMap<String, Value>,
}
/// Actual native batch invocation, with no constructor from caller columns.
/// It is mathematical completion only, not READY or a publication capability.
pub(crate) struct CompletedNativeBatch {
    values: Value,
    evidence: Value,
}
impl CompletedNativeBatch {
    pub(crate) fn values(&self) -> &Value {
        &self.values
    }
    pub(crate) fn evidence(&self) -> &Value {
        &self.evidence
    }
}
impl SignalPrograms {
    pub(crate) fn new(
        graph: &Graph,
        ready: &[ReadyFactorBinding],
        bindings: &Value,
        image: &str,
    ) -> Result<Self> {
        let mut owners = BTreeMap::new();
        let mut research_manifests = BTreeMap::new();
        for d in graph.ordered_nodes() {
            let r = d.to_record();
            let id = d.fingerprint();
            let (owner, research, trading) = match r["kind"].as_str() {
                Some("FACTOR") => {
                    let mut found = ready.iter().filter(|p| {
                        p.metadata()["factor_id"] == r["type_id"]
                            && p.program().parameters().record() == &r["parameters"]
                    });
                    let p = found.next().ok_or(INVALID)?;
                    if found
                        .any(|other| other.certificate_fingerprint() != p.certificate_fingerprint())
                    {
                        return Err(INVALID);
                    }
                    let c = p
                        .calculation(image, &r["input_bindings"])
                        .map_err(|_| INVALID)?;
                    if c.definition() != d {
                        return Err(INVALID);
                    }
                    (
                        Owner::Factor(Box::new(p.clone())),
                        c.implementation_manifest("RESEARCH").map_err(|_| INVALID)?,
                        c.implementation_manifest("TRADING").map_err(|_| INVALID)?,
                    )
                }
                Some("INDICATOR") => {
                    let c = OperatorCalculation::from_record(&r)?;
                    let research = c.implementation_manifest("RESEARCH", image)?;
                    let trading = c.implementation_manifest("TRADING", image)?;
                    (Owner::Operator(c), research, trading)
                }
                Some("PREDICATE") => {
                    let c = PredicateCalculation::from_record(&r)?;
                    let research = c.implementation_manifest("RESEARCH", image)?;
                    let trading = c.implementation_manifest("TRADING", image)?;
                    (Owner::Predicate(c), research, trading)
                }
                _ => return Err(INVALID),
            };
            let actual = bindings
                .as_array()
                .ok_or(INVALID)?
                .iter()
                .filter(|b| b["node_fingerprint"] == id)
                .collect::<Vec<_>>();
            if actual.len() != 1
                || actual[0]["research_implementation_fingerprint"]
                    != research["implementation_fingerprint"]
                || actual[0]["trading_implementation_fingerprint"]
                    != trading["implementation_fingerprint"]
            {
                return Err(INVALID);
            }
            research_manifests.insert(id.clone(), research);
            owners.insert(id, owner);
        }
        if owners.len() != bindings.as_array().ok_or(INVALID)?.len() {
            return Err(INVALID);
        }
        Ok(Self {
            owners,
            image: image.into(),
            graph: graph.fingerprint(),
            research: research_manifests,
        })
    }
    pub(crate) fn capabilities(&self, bindings: &Value) -> Result<Value> {
        Ok(json!(self.owners.iter().filter_map(|(id,owner)|match owner{
            Owner::Predicate(_)=>None,
            Owner::Factor(_)=>Some((id,"CHECKPOINTABLE",Some(1))),
            Owner::Operator(c)=>Some((id,c.state_capability(),c.checkpoint_schema_version()))
        }).map(|(id,cap,schema)|{
            let b=bindings.as_array().ok_or(INVALID)?.iter().find(|b|b["node_fingerprint"]==*id).ok_or(INVALID)?;
            Ok(json!({"node_fingerprint":id,"implementation_fingerprint":b["trading_implementation_fingerprint"],"state_capability":cap,"checkpoint_schema_version":schema}))
        }).collect::<Result<Vec<_>>>()?))
    }
    pub(crate) fn port(
        &self,
        program: onlyalpha_strategy::Program,
        definitions: BTreeMap<String, Definition>,
        mapping: &BTreeMap<String, String>,
        bindings: &Value,
    ) -> Result<ProgramNodes> {
        let mut factors = BTreeMap::new();
        for (id, owner) in &self.owners {
            if let Owner::Factor(p) = owner {
                let b = bindings
                    .as_array()
                    .ok_or(INVALID)?
                    .iter()
                    .find(|b| b["node_fingerprint"] == *id)
                    .ok_or(INVALID)?;
                factors.insert(
                    mapping.get(id).ok_or(INVALID)?.clone(),
                    ProgramFactor::new(
                        Arc::new(p.program().clone()),
                        b["trading_implementation_fingerprint"]
                            .as_str()
                            .ok_or(INVALID)?,
                    )
                    .map_err(|_| INVALID)?,
                );
            }
        }
        ProgramNodes::new(program, definitions, factors, &self.image).map_err(|_| INVALID)
    }
    pub(crate) fn complete_batch(
        &self,
        graph: &Graph,
        rows: &Value,
        mut check: impl FnMut() -> Result<()>,
    ) -> Result<CompletedNativeBatch> {
        if graph.fingerprint() != self.graph {
            return Err(INVALID);
        }
        let values = self.batch(graph, rows, &mut check)?;
        check()?;
        let evidence = json!({"contract":"NATIVE_GRAPH_BATCH_COMPLETED_V1","graph":self.graph,
            "input_fingerprint":batch_content_fingerprint(rows)?,
            "output_fingerprint":batch_content_fingerprint(&values)?,
            "implementations":self.research.values().collect::<Vec<_>>()});
        Ok(CompletedNativeBatch { values, evidence })
    }
    /// Independent finite batch invocation for each graph node; outputs are not
    /// copied from the event executor being checked.
    pub(crate) fn batch(
        &self,
        graph: &Graph,
        rows: &Value,
        mut check: impl FnMut() -> Result<()>,
    ) -> Result<Value> {
        let rows = rows.as_array().ok_or(INVALID)?;
        let mut columns = BTreeMap::<String, Value>::new();
        let starts = onlyalpha_calculation::finite_input::node_execution_starts(graph, 8192)
            .map_err(|_| INVALID)?;
        for definition in graph.ordered_nodes() {
            check()?;
            let r = definition.to_record();
            let id = definition.fingerprint();
            // A blocked upstream does not advance the downstream instance.
            let upstream =
                usize::try_from(*starts.get(&id).ok_or(INVALID)?).map_err(|_| INVALID)?;
            let mut inputs = Vec::new();
            for (index, row) in rows.iter().enumerate() {
                let mut values = serde_json::Map::new();
                for (name, b) in r["input_bindings"].as_object().ok_or(INVALID)? {
                    let value = if let Some(parent) = b["node_fingerprint"].as_str() {
                        columns
                            .get(parent)
                            .and_then(|v| v.get(b["output_name"].as_str()?))
                            .and_then(|v| v.get(index))
                            .ok_or(INVALID)?
                            .clone()
                    } else {
                        row["values"]
                            .get(
                                b["source"]
                                    .as_str()
                                    .and_then(|s| s.strip_prefix("bar."))
                                    .ok_or(INVALID)?,
                            )
                            .ok_or(INVALID)?
                            .clone()
                    };
                    values.insert(name.clone(), value);
                }
                inputs.push(Value::Object(values));
            }
            let prefix = upstream.min(inputs.len());
            let output = self.node_rows(&id, &inputs[prefix..], false, &mut check)?;
            let mut transposed = serde_json::Map::new();
            for p in r["outputs"].as_array().ok_or(INVALID)? {
                let name = p["name"].as_str().ok_or(INVALID)?;
                transposed.insert(
                    name.into(),
                    json!(
                        std::iter::repeat_n(Value::Null, prefix)
                            .chain(output.iter().map(|r| r[name].clone()))
                            .collect::<Vec<_>>()
                    ),
                );
            }
            columns.insert(id, Value::Object(transposed));
        }
        Ok(json!(columns.into_iter().map(|(node_fingerprint,values)|json!({"node_fingerprint":node_fingerprint,"values":values})).collect::<Vec<_>>()))
    }
    pub(crate) fn node_rows(
        &self,
        id: &str,
        inputs: &[Value],
        event: bool,
        mut check: impl FnMut() -> Result<()>,
    ) -> Result<Vec<Value>> {
        let output = match self.owners.get(id).ok_or(INVALID)? {
            Owner::Factor(p) => {
                let ir = p.program().program().record();
                let rows = inputs
                    .iter()
                    .enumerate()
                    .map(|(i, r)| {
                        check()?;
                        let v = r
                            .as_object()
                            .ok_or(INVALID)?
                            .iter()
                            .map(|(k, v)| {
                                let value = if v.is_null() {
                                    ProgramValue::Missing
                                } else {
                                    match ir["inputs"][k]["type"].as_str() {
                                        Some("DECIMAL") => ProgramValue::Decimal(
                                            bigdecimal::BigDecimal::from_str(
                                                v.as_str().ok_or(INVALID)?,
                                            )
                                            .map_err(|_| INVALID)?,
                                        ),
                                        Some("INTEGER") => ProgramValue::Integer(
                                            bigdecimal::num_bigint::BigInt::from_str(
                                                &v.to_string(),
                                            )
                                            .map_err(|_| INVALID)?,
                                        ),
                                        Some("BOOLEAN") => {
                                            ProgramValue::Boolean(v.as_bool().ok_or(INVALID)?)
                                        }
                                        _ => return Err(INVALID),
                                    }
                                };
                                Ok((k.clone(), value))
                            })
                            .collect::<Result<BTreeMap<_, _>>>()?;
                        ProgramInput::new(
                            "controlled-single-instrument",
                            i.try_into().map_err(|_| INVALID)?,
                            v,
                        )
                        .map_err(|_| INVALID)
                    })
                    .collect::<Result<Vec<_>>>()?;
                let out = if event {
                    let mut stream = ProgramInstance::new(Arc::new(p.program().clone()));
                    rows.iter()
                        .map(|r| {
                            check()?;
                            stream.step(r).map_err(|_| INVALID)
                        })
                        .collect::<Result<Vec<_>>>()?
                } else {
                    evaluate_batch(p.program(), &rows).map_err(|_| INVALID)?
                };
                out.iter()
                    .map(|r| {
                        json!(
                            r.iter()
                                .map(|(k, v)| (k.clone(), v.record()))
                                .collect::<BTreeMap<_, _>>()
                        )
                    })
                    .collect()
            }
            Owner::Operator(c) => {
                if event {
                    let mut stream: OperatorStream = c.stream()?;
                    inputs
                        .iter()
                        .map(|r| {
                            check()?;
                            stream.push(r)
                        })
                        .collect::<Result<Vec<_>>>()?
                } else {
                    let mut columns = serde_json::Map::new();
                    for p in c.definition().to_record()["inputs"]
                        .as_array()
                        .ok_or(INVALID)?
                    {
                        let k = p["name"].as_str().ok_or(INVALID)?;
                        columns.insert(
                            k.into(),
                            json!(inputs.iter().map(|r| r[k].clone()).collect::<Vec<_>>()),
                        );
                    }
                    let out = c.evaluate_batch_controlled(&Value::Object(columns), &mut check)?;
                    (0..inputs.len())
                        .map(|i| {
                            Ok(Value::Object(
                                out.as_object()
                                    .ok_or(INVALID)?
                                    .iter()
                                    .map(|(k, v)| Ok((k.clone(), v.get(i).ok_or(INVALID)?.clone())))
                                    .collect::<Result<serde_json::Map<_, _>>>()?,
                            ))
                        })
                        .collect::<Result<Vec<_>>>()?
                }
            }
            Owner::Predicate(c) => inputs
                .iter()
                .map(|r| {
                    check()?;
                    c.evaluate(r)
                })
                .collect::<Result<Vec<_>>>()?,
        };
        Ok(output)
    }
}

#[cfg(test)]
#[path = "../../tests/native_signal_tests.rs"]
mod tests;
