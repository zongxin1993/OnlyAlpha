use crate::{Definition, Result, record::*};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Graph {
    nodes: Vec<(Definition, Option<String>)>,
}
fn compatible(output: &Value, input: &Value) -> bool {
    output["data_type"] == input["data_type"]
        && (!output["nullable"].as_bool().expect("validated")
            || input["nullable"].as_bool().expect("validated"))
        && output["dimensions"] == input["dimensions"]
        && (input["semantic_type"] == "PREDICATE_OPERAND"
            || (output["semantic_type"] == input["semantic_type"]
                && output["unit"] == input["unit"]))
}
impl Graph {
    pub fn new(nodes: Vec<(Definition, Option<String>)>) -> Result<Self> {
        if nodes.len() > LIMIT {
            return Err(err("GRAPH_BUDGET"));
        }
        let mut aliases = BTreeSet::new();
        for (_, alias) in &nodes {
            if let Some(alias) = alias {
                name(&json!(alias))?;
                if !aliases.insert(alias) {
                    return Err(err("DUPLICATE_ALIAS"));
                }
            }
        }
        let ids: Vec<_> = nodes.iter().map(|(d, _)| d.fingerprint()).collect();
        let records: Vec<_> = nodes
            .iter()
            .zip(&ids)
            .map(|((d, _), id)| (id.as_str(), d.record()))
            .collect();
        let ordered = order(&records)?;
        Ok(Self {
            nodes: ordered.into_iter().map(|i| nodes[i].clone()).collect(),
        })
    }

    pub fn ordered_nodes(&self) -> Vec<&Definition> {
        self.nodes.iter().map(|(d, _)| d).collect()
    }
    pub fn fingerprint(&self) -> String {
        hash(
            &json!({"schema_version":1,"nodes":self.nodes.iter().map(|(d,_)|d.to_record()).collect::<Vec<_>>()}),
        )
    }
    pub fn to_record(&self) -> Value {
        json!({"schema_version":1,"nodes":self.nodes.iter().map(|(d,a)|json!({"definition":d.to_record(),"alias":a})).collect::<Vec<_>>()})
    }
    pub fn from_record(v: &Value) -> Result<Self> {
        object(v, &["schema_version", "nodes"])?;
        if v["schema_version"].as_u64() != Some(1) {
            return Err(err("GRAPH_SCHEMA_REQUIRED"));
        }
        let mut nodes = vec![];
        for n in array(&v["nodes"])? {
            object(n, &["definition", "alias"])?;
            let alias = if n["alias"].is_null() {
                None
            } else {
                Some(name(&n["alias"])?.into())
            };
            nodes.push((Definition::from_record(&n["definition"])?, alias));
        }
        Self::new(nodes)
    }
}

// Both wire readers validate every record before this shared structural pass.
// Original semantic IDs are supplied by their owning Definition, never remapped.
pub(crate) fn order(nodes: &[(&str, &Value)]) -> Result<Vec<usize>> {
    let mut lookup = BTreeMap::new();
    for (i, (id, _)) in nodes.iter().enumerate() {
        if lookup.insert((*id).to_owned(), i).is_some() {
            return Err(err("DUPLICATE_NODE"));
        }
    }
    let targets = nodes.iter().filter(|(_, d)| d["kind"] == "TARGET").count();
    if targets > 0 && targets != nodes.len() {
        return Err(err("TARGET_FEATURE_GRAPH_MIX"));
    }
    // Index each validated port once; wide public graphs must not make every
    // edge rescan all producer outputs and consumer inputs.
    let ports = |field: &str| {
        nodes
            .iter()
            .map(|(_, d)| {
                d[field]
                    .as_array()
                    .expect("validated ports")
                    .iter()
                    .map(|p| (p["name"].as_str().expect("validated port name"), p))
                    .collect::<BTreeMap<_, _>>()
            })
            .collect::<Vec<_>>()
    };
    let outputs = ports("outputs");
    let inputs = ports("inputs");
    let mut edges: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for (id, index) in &lookup {
        let d = nodes[*index].1;
        let mut references: Vec<_> = d["input_bindings"]
            .as_object()
            .expect("validated bindings")
            .iter()
            .collect();
        references.sort_by_key(|(_, r)| {
            (
                r["node_fingerprint"].as_str().unwrap_or(""),
                r["output_name"].as_str().unwrap_or(""),
                r["source"].as_str().unwrap_or(""),
            )
        });
        let mut dependencies = vec![];
        for (input_name, r) in references {
            if let Some(dependency) = r["node_fingerprint"].as_str() {
                if targets > 0 {
                    return Err(err("TARGET_NODE_DEPENDENCY_FORBIDDEN"));
                }
                let producer = *lookup
                    .get(dependency)
                    .ok_or_else(|| err("MISSING_DEPENDENCY"))?;
                let output = outputs[producer]
                    .get(r["output_name"].as_str().expect("validated output name"))
                    .ok_or_else(|| err("MISSING_OUTPUT"))?;
                let input = inputs[*index]
                    .get(input_name.as_str())
                    .expect("validated binding");
                if !compatible(output, input) {
                    return Err(err("INCOMPATIBLE_PORT"));
                }
                dependencies.push(dependency.to_owned());
            }
        }
        edges.insert(id.clone(), dependencies);
    }
    let mut markers = BTreeMap::new();
    let mut ordered = vec![];
    for root in lookup.keys() {
        let mut stack = vec![(root.clone(), false)];
        while let Some((id, expanded)) = stack.pop() {
            if expanded {
                markers.insert(id.clone(), 2);
                ordered.push(*lookup.get(&id).expect("validated dependency"));
                continue;
            }
            match markers.get(&id) {
                Some(1) => return Err(err("GRAPH_CYCLE")),
                Some(2) => continue,
                _ => {}
            }
            markers.insert(id.clone(), 1);
            stack.push((id.clone(), true));
            for dependency in edges[&id].iter().rev() {
                stack.push((dependency.clone(), false));
            }
        }
    }
    Ok(ordered)
}
