//! Current Product Definition2 and Graph1 values, with their original identities.
//! Pure historical semantics only: no provider, execution or Freeze admission.
use bigdecimal::{BigDecimal, Zero, num_bigint::BigInt};
use serde_json::{Value, json};
use std::{collections::BTreeSet, fmt, str::FromStr};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Invalid,
    Unavailable,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "CALCULATION_PRODUCT_CONTRACT_INVALID",
            Self::Unavailable => "CALCULATION_PRODUCT_READ_UNAVAILABLE",
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}
type Result<T> = std::result::Result<T, Error>;
struct Work(usize);
impl Work {
    fn take(&mut self, n: usize) -> Result<()> {
        self.0 = self.0.checked_sub(n).ok_or(Error::Unavailable)?;
        Ok(())
    }
    fn scan(&mut self, v: &Value) -> Result<()> {
        let mut pending = vec![v];
        while let Some(v) = pending.pop() {
            self.take(1)?;
            match v {
                Value::String(s) => self.take(s.len())?,
                Value::Number(n) => self.take(n.as_str().len())?,
                Value::Array(a) => {
                    if a.len() > self.0 {
                        return Err(Error::Unavailable);
                    }
                    pending.extend(a);
                }
                Value::Object(m) => {
                    for k in m.keys() {
                        self.take(k.len())?;
                    }
                    if m.len() > self.0 {
                        return Err(Error::Unavailable);
                    }
                    pending.extend(m.values());
                }
                _ => (),
            }
        }
        Ok(())
    }
}
fn exact(v: &Value, fields: &[&str]) -> Result<()> {
    crate::record::object(v, fields)
        .map(|_| ())
        .map_err(|_| Error::Invalid)
}

fn text(v: &Value) -> Result<&str> {
    v.as_str().ok_or(Error::Invalid)
}
fn member(v: &Value, choices: &[&str]) -> Result<()> {
    if choices.contains(&text(v)?) {
        Ok(())
    } else {
        Err(Error::Invalid)
    }
}
fn optional_text(v: &Value) -> Result<()> {
    if !v.is_null() {
        text(v)?;
    }
    Ok(())
}
fn integer(v: &Value) -> Result<BigInt> {
    let n = v.as_number().ok_or(Error::Invalid)?.as_str();
    if n.contains(['.', 'e', 'E']) {
        return Err(Error::Invalid);
    }
    BigInt::from_str(n).map_err(|_| Error::Invalid)
}
fn positive(v: &Value) -> Result<()> {
    if integer(v)? <= BigInt::from(0) {
        return Err(Error::Invalid);
    }
    Ok(())
}
fn decimal(v: &Value, work: &mut Work) -> Result<Value> {
    let s = text(v)?;
    if s.is_empty()
        || !s
            .bytes()
            .all(|b| b.is_ascii_digit() || b"+-.eE".contains(&b))
    {
        return Err(Error::Invalid);
    }
    let n = BigDecimal::from_str(s).map_err(|_| Error::Invalid)?;
    let (coefficient, scale) = n.as_bigint_and_exponent();
    // Positive-exponent zero needs no fixed-f padding, even for a large SDK
    // exponent. Retain the lossless spelling without charging fictional output.
    let expansion = if n.is_zero() && scale < 0 {
        0
    } else {
        scale.unsigned_abs()
    };
    let estimate = usize::try_from(expansion)
        .ok()
        .and_then(|scale| scale.checked_add(coefficient.to_string().len()))
        .and_then(|n| n.checked_add(4))
        .ok_or(Error::Unavailable)?;
    work.take(estimate)?;
    // Decimal fixed-f zero has no positive-exponent padding. BigDecimal's
    // to_plain_string emits e.g. "000" for 0E+2; that changes Product identity.
    let mut out = if n.is_zero() && scale < 0 {
        "0".to_owned()
    } else {
        n.to_plain_string()
    };
    // BigDecimal has no negative zero, while Decimal's sign is Product identity.
    if n.is_zero() && s.starts_with('-') {
        out.insert(0, '-');
    }
    Ok(json!(out))
}
fn scalar(v: &Value, work: &mut Work) -> Result<Value> {
    exact(v, &["type", "value"])?;
    let value = &v["value"];
    let normalized = match text(&v["type"])? {
        "NULL" if value.is_null() => Value::Null,
        "BOOLEAN" => json!(value.as_bool().ok_or(Error::Invalid)?),
        "STRING" => json!(text(value)?),
        "INTEGER" => {
            serde_json::from_str(&integer(value)?.to_string()).map_err(|_| Error::Invalid)?
        }
        "DECIMAL" => decimal(value, work)?,
        _ => return Err(Error::Invalid),
    };
    Ok(json!({"type":v["type"],"value":normalized}))
}
fn ports(v: &Value) -> Result<BTreeSet<&str>> {
    let a = v.as_array().ok_or(Error::Invalid)?;
    let mut names = BTreeSet::new();
    for p in a {
        exact(
            p,
            &[
                "name",
                "data_type",
                "nullable",
                "dimensions",
                "semantic_type",
                "unit",
            ],
        )?;
        if !names.insert(text(&p["name"])?) {
            return Err(Error::Invalid);
        }
        member(
            &p["data_type"],
            &["DECIMAL", "INTEGER", "BOOLEAN", "STRING"],
        )?;
        p["nullable"].as_bool().ok_or(Error::Invalid)?;
        for dimension in p["dimensions"].as_array().ok_or(Error::Invalid)? {
            text(dimension)?;
        }
        text(&p["semantic_type"])?;
        optional_text(&p["unit"])?;
    }
    Ok(names)
}
fn space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}
fn semantics<'a>(v: &'a Value, work: &mut Work) -> Result<(BTreeSet<&'a str>, Value)> {
    member(&v["kind"], &["INDICATOR", "FACTOR", "TARGET", "PREDICATE"])?;
    let id = text(&v["type_id"])?;
    let version = text(&v["semantic_version"])?;
    if !id.contains('.')
        || id.to_lowercase() != id
        || version.is_empty()
        || version.chars().any(space)
    {
        return Err(Error::Invalid);
    }
    let inputs = ports(&v["inputs"])?;
    if ports(&v["outputs"])?.is_empty() {
        return Err(Error::Invalid);
    }
    member(
        &v["missing_values"],
        &["FAIL", "SKIP", "PROPAGATE", "RESET"],
    )?;
    member(
        &v["timestamp"],
        &[
            "BAR_OPEN",
            "BAR_CLOSE",
            "EVENT_TIME",
            "OBSERVATION_TIME",
            "AVAILABILITY_TIME",
        ],
    )?;
    if v["kind"] == "FACTOR" {
        member(&v["factor_kind"], &["TIME_SERIES", "CROSS_SECTION"])?;
    } else if !v["factor_kind"].is_null() {
        return Err(Error::Invalid);
    }
    let numeric = &v["numeric"];
    exact(
        numeric,
        &["representation", "precision", "output_quantum", "rounding"],
    )?;
    text(&numeric["representation"])?;
    text(&numeric["rounding"])?;
    positive(&numeric["precision"])?;
    let quantum = if numeric["output_quantum"].is_null() {
        Value::Null
    } else {
        decimal(&numeric["output_quantum"], work)?
    };
    let mut numeric = numeric.clone();
    numeric["output_quantum"] = quantum;
    Ok((inputs, numeric))
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Definition {
    record: Value,
}
impl Definition {
    pub fn from_record(v: &Value, max_work: usize) -> Result<Self> {
        let mut work = Work(max_work);
        work.scan(v)?;
        Self::decode(v, &mut work)
    }
    fn decode(v: &Value, work: &mut Work) -> Result<Self> {
        exact(
            v,
            &[
                "schema_version",
                "kind",
                "type_id",
                "semantic_version",
                "parameters",
                "inputs",
                "input_bindings",
                "outputs",
                "warmup",
                "missing_values",
                "timestamp",
                "numeric",
                "factor_kind",
                "extensions",
            ],
        )?;
        if v["schema_version"].as_u64() != Some(2) {
            return Err(Error::Invalid);
        }
        let (inputs, numeric) = semantics(v, work)?;
        let bindings = v["input_bindings"].as_object().ok_or(Error::Invalid)?;
        if inputs.len() != bindings.len()
            || !inputs
                .iter()
                .copied()
                .eq(bindings.keys().map(String::as_str))
        {
            return Err(Error::Invalid);
        }
        for r in bindings.values() {
            exact(r, &["node_fingerprint", "output_name", "source"])?;
            optional_text(&r["node_fingerprint"])?;
            optional_text(&r["source"])?;
            text(&r["output_name"])?;
            if r["node_fingerprint"].is_null() == r["source"].is_null()
                || r["node_fingerprint"]
                    .as_str()
                    .is_some_and(|s| s.chars().count() != 64)
            {
                return Err(Error::Invalid);
            }
        }
        let warm = &v["warmup"];
        exact(
            warm,
            &[
                "minimum_observations",
                "ready_condition",
                "pre_ready_output",
                "initialization",
            ],
        )?;
        positive(&warm["minimum_observations"])?;
        if text(&warm["ready_condition"])?.is_empty() || text(&warm["initialization"])?.is_empty() {
            return Err(Error::Invalid);
        }
        member(&warm["pre_ready_output"], &["NULL", "PARTIAL"])?;
        let mut normalized = Vec::new();
        for field in ["parameters", "extensions"] {
            let mut m = serde_json::Map::new();
            for (name, value) in v[field].as_object().ok_or(Error::Invalid)? {
                m.insert(name.clone(), scalar(value, work)?);
            }
            normalized.push((field, Value::Object(m)));
        }
        // Every potentially nested caller field is validated before cloning it.
        let mut record = v.clone();
        record["numeric"] = numeric;
        for (field, values) in normalized {
            record[field] = values;
        }

        Ok(Self { record })
    }
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub fn semantic_payload(&self) -> Value {
        let mut v = self.record.clone();
        for field in ["parameters", "extensions"] {
            for value in v[field]
                .as_object_mut()
                .expect("validated map")
                .values_mut()
            {
                *value = value["value"].clone();
            }
        }
        v
    }
    pub fn fingerprint(&self) -> String {
        crate::record::hash(&self.semantic_payload())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Graph {
    nodes: Vec<(Definition, Option<String>)>,
}
impl Graph {
    pub fn from_record(v: &Value, max_work: usize) -> Result<Self> {
        let mut work = Work(max_work);
        work.scan(v)?;
        exact(v, &["schema_version", "nodes"])?;
        if v["schema_version"].as_u64() != Some(1) {
            return Err(Error::Invalid);
        }
        let mut nodes = vec![];
        let mut aliases = BTreeSet::new();
        for node in v["nodes"].as_array().ok_or(Error::Invalid)? {
            exact(node, &["definition", "alias"])?;
            let alias = if node["alias"].is_null() {
                None
            } else {
                let a = text(&node["alias"])?;
                if !aliases.insert(a) {
                    return Err(Error::Invalid);
                }
                Some(a.to_owned())
            };
            nodes.push((Definition::decode(&node["definition"], &mut work)?, alias));
        }
        let ids: Vec<_> = nodes.iter().map(|(d, _)| d.fingerprint()).collect();
        let records: Vec<_> = nodes
            .iter()
            .zip(&ids)
            .map(|((d, _), id)| (id.as_str(), &d.record))
            .collect();
        let order = crate::graph::order(&records).map_err(|_| Error::Invalid)?;
        let mut selected: Vec<_> = nodes.into_iter().map(Some).collect();
        Ok(Self {
            nodes: order
                .into_iter()
                .map(|i| selected[i].take().expect("unique ordered index"))
                .collect(),
        })
    }
    pub fn ordered_nodes(&self) -> impl Iterator<Item = &Definition> {
        self.nodes.iter().map(|(definition, _)| definition)
    }
    pub fn to_record(&self) -> Value {
        json!({"schema_version":1,"nodes":self.nodes.iter().map(|(d,a)|json!({"definition":d.to_record(),"alias":a})).collect::<Vec<_>>()})
    }
    pub fn fingerprint(&self) -> String {
        crate::record::hash(
            &json!({"schema_version":1,"nodes":self.nodes.iter().map(|(d,_)|d.semantic_payload()).collect::<Vec<_>>()}),
        )
    }
}

mod types;
pub use types::TypeDeclaration;
