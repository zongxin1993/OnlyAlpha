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
        let mut lookup = BTreeMap::new();
        for (i, (d, alias)) in nodes.iter().enumerate() {
            if lookup.insert(d.fingerprint(), i).is_some() {
                return Err(err("DUPLICATE_NODE"));
            }
            if let Some(alias) = alias {
                name(&json!(alias))?;
                if !aliases.insert(alias) {
                    return Err(err("DUPLICATE_ALIAS"));
                }
            }
        }
        let targets = nodes
            .iter()
            .filter(|(d, _)| d.reference().kind() == "TARGET")
            .count();
        if targets > 0 && targets != nodes.len() {
            return Err(err("TARGET_FEATURE_GRAPH_MIX"));
        }
        let mut edges: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for (id, index) in &lookup {
            let d = nodes[*index].0.record();
            let mut references: Vec<_> = map(&d["input_bindings"])?.iter().collect();
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
                    let producer = &nodes[*lookup
                        .get(dependency)
                        .ok_or_else(|| err("MISSING_DEPENDENCY"))?]
                    .0;
                    let output = array(&producer.record()["outputs"])?
                        .iter()
                        .find(|p| p["name"] == r["output_name"])
                        .ok_or_else(|| err("MISSING_OUTPUT"))?;
                    let input = array(&d["inputs"])?
                        .iter()
                        .find(|p| p["name"].as_str() == Some(input_name))
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
