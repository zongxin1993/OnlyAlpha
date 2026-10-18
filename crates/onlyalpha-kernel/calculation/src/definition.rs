use crate::{Result, parameters, record::*};
use serde_json::{Value, json};
use std::collections::BTreeSet;
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct TypeReference {
    kind: String,
    type_id: String,
    semantic_version: String,
}
impl TypeReference {
    pub fn new(kind: &str, type_id: &str, semantic_version: &str) -> Result<Self> {
        member(
            &json!(kind),
            &["INDICATOR", "FACTOR", "TARGET", "PREDICATE"],
        )?;
        name(&json!(semantic_version))?;
        if type_id.len() > LIMIT
            || !type_id.contains('.')
            || type_id.split('.').any(|part| {
                part.is_empty()
                    || !part
                        .bytes()
                        .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
            })
        {
            return Err(err("TYPE_ID_INVALID"));
        }
        Ok(Self {
            kind: kind.into(),
            type_id: type_id.into(),
            semantic_version: semantic_version.into(),
        })
    }
    pub fn kind(&self) -> &str {
        &self.kind
    }
    pub fn type_id(&self) -> &str {
        &self.type_id
    }
    pub fn semantic_version(&self) -> &str {
        &self.semantic_version
    }
}
fn reference(v: &Value) -> Result<TypeReference> {
    TypeReference::new(
        text(&v["kind"])?,
        text(&v["type_id"])?,
        text(&v["semantic_version"])?,
    )
}
pub(crate) fn port(v: &Value) -> Result<()> {
    object(
        v,
        &[
            "name",
            "data_type",
            "nullable",
            "dimensions",
            "semantic_type",
            "unit",
        ],
    )?;
    name(&v["name"])?;
    member(
        &v["data_type"],
        &["DECIMAL", "INTEGER", "BOOLEAN", "STRING"],
    )?;
    boolean(&v["nullable"])?;
    name(&v["semantic_type"])?;
    if !v["unit"].is_null() {
        name(&v["unit"])?;
    }
    let dimensions = array(&v["dimensions"])?;
    let mut names = BTreeSet::new();
    if dimensions.is_empty() {
        return Err(err("DIMENSIONS_REQUIRED"));
    }
    for d in dimensions {
        if !names.insert(name(d)?) {
            return Err(err("DUPLICATE_DIMENSION"));
        }
    }
    Ok(())
}
fn ports(v: &Value, required: bool) -> Result<()> {
    let list = array(v)?;
    if required && list.is_empty() {
        return Err(err("OUTPUT_REQUIRED"));
    }
    let mut names = BTreeSet::new();
    for p in list {
        port(p)?;
        if !names.insert(name(&p["name"])?) {
            return Err(err("DUPLICATE_PORT"));
        }
    }
    Ok(())
}
fn numeric(v: &Value) -> Result<Value> {
    object(
        v,
        &["representation", "precision", "output_quantum", "rounding"],
    )?;
    name(&v["representation"])?;
    name(&v["rounding"])?;
    positive(&v["precision"])?;
    let quantum = if v["output_quantum"].is_null() {
        Value::Null
    } else {
        json!(quantum(text(&v["output_quantum"])?)?)
    };
    Ok(
        json!({"representation":v["representation"], "precision":v["precision"], "rounding":v["rounding"], "output_quantum":quantum}),
    )
}
fn validate_warmup(v: &Value) -> Result<()> {
    let warmup = object(
        v,
        &[
            "minimum_observations",
            "ready_condition",
            "pre_ready_output",
            "initialization",
        ],
    )?;
    positive(&warmup["minimum_observations"])?;
    for field in ["ready_condition", "initialization"] {
        let description = text(&warmup[field])?;
        if description.trim().is_empty() || description.chars().any(char::is_control) {
            return Err(err("EXPLICIT_WARMUP_REQUIRED"));
        }
    }
    member(&warmup["pre_ready_output"], &["NULL", "PARTIAL"])?;
    Ok(())
}
fn validate_bindings(v: &Value, inputs: &Value) -> Result<()> {
    let bindings = map(v)?;
    let inputs = array(inputs)?;
    if bindings.len() != inputs.len()
        || inputs
            .iter()
            .any(|p| !bindings.contains_key(p["name"].as_str().expect("validated port")))
    {
        return Err(err("EXACT_INPUT_BINDINGS_REQUIRED"));
    }
    for binding in bindings.values() {
        object(binding, &["node_fingerprint", "output_name", "source"])?;
        name(&binding["output_name"])?;
        match (
            binding["node_fingerprint"].is_null(),
            binding["source"].is_null(),
        ) {
            (false, true) => {
                digest(&binding["node_fingerprint"])?;
            }
            (true, false) => {
                name(&binding["source"])?;
            }
            _ => return Err(err("EXACT_SOURCE_REQUIRED")),
        }
    }
    Ok(())
}

fn common(v: &Value) -> Result<TypeReference> {
    let r = reference(v)?;
    ports(&v["inputs"], false)?;
    ports(&v["outputs"], true)?;
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
    if r.kind() == "FACTOR" {
        member(&v["factor_kind"], &["TIME_SERIES", "CROSS_SECTION"])?;
    } else if !v["factor_kind"].is_null() {
        return Err(err("FACTOR_KIND_FORBIDDEN"));
    }
    Ok(r)
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Definition {
    record: Value,
    reference: TypeReference,
}
impl Definition {
    pub fn from_record(v: &Value) -> Result<Self> {
        object(
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
        if v["schema_version"].as_u64() != Some(3) {
            return Err(err("DEFINITION_SCHEMA_REQUIRED"));
        }
        let reference = common(v)?;
        let parameters = scalars(&v["parameters"])?;
        let extensions = scalars(&v["extensions"])?;
        let numeric = numeric(&v["numeric"])?;
        validate_warmup(&v["warmup"])?;
        validate_bindings(&v["input_bindings"], &v["inputs"])?;
        // Every nested leaf is validated before copying the caller-owned record.
        let mut normalized = v.clone();
        normalized["parameters"] = parameters;
        normalized["extensions"] = extensions;
        normalized["numeric"] = numeric;
        let result = Self {
            record: normalized,
            reference,
        };
        result.execution_shape()?;
        Ok(result)
    }
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub fn reference(&self) -> &TypeReference {
        &self.reference
    }
    pub fn fingerprint(&self) -> String {
        hash(&self.record)
    }
    pub fn execution_shape(&self) -> Result<&str> {
        let extension = self.record["extensions"].get("calculation_execution_shape");
        let explicit = if let Some(s) = extension {
            if s["type"] != "STRING" {
                return Err(err("EXECUTION_SHAPE_TYPE"));
            }
            Some(member(&s["value"], &["TIME_SERIES", "CROSS_SECTION"])?)
        } else {
            None
        };
        if self.reference.kind() == "FACTOR" {
            let shape = text(&self.record["factor_kind"])?;
            if explicit.is_some_and(|s| s != shape) {
                return Err(err("EXECUTION_SHAPE_CONFLICT"));
            }
            Ok(shape)
        } else {
            Ok(explicit.unwrap_or("TIME_SERIES"))
        }
    }
    pub(crate) fn record(&self) -> &Value {
        &self.record
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TypeDefinition {
    record: Value,
    reference: TypeReference,
}
impl TypeDefinition {
    pub fn from_record(v: &Value) -> Result<Self> {
        object(
            v,
            &[
                "schema_version",
                "kind",
                "type_id",
                "semantic_version",
                "parameters",
                "inputs",
                "outputs",
                "missing_values",
                "timestamp",
                "numeric",
                "factor_kind",
                "execution_shape",
            ],
        )?;
        if v["schema_version"].as_u64() != Some(1) {
            return Err(err("TYPE_SCHEMA_REQUIRED"));
        }
        let reference = common(v)?;
        member(&v["execution_shape"], &["TIME_SERIES", "CROSS_SECTION"])?;
        if reference.kind() == "FACTOR" && v["execution_shape"] != v["factor_kind"] {
            return Err(err("EXECUTION_SHAPE_CONFLICT"));
        }
        let parameters = parameters::schema(&v["parameters"])?;
        let numeric = numeric(&v["numeric"])?;
        let mut record = v.clone();
        record["parameters"] = parameters;
        record["numeric"] = numeric;
        Ok(Self { record, reference })
    }
    pub fn reference(&self) -> &TypeReference {
        &self.reference
    }
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub fn resolve(
        &self,
        parameters: &Value,
        input_bindings: &Value,
        warmup: &Value,
    ) -> Result<Definition> {
        validate_bindings(input_bindings, &self.record["inputs"])?;
        validate_warmup(warmup)?;
        let mut d = self.record.clone();
        let m = d.as_object_mut().expect("validated type");
        m.remove("execution_shape");
        m.insert("schema_version".into(), json!(3));
        m.insert(
            "parameters".into(),
            parameters::parameters(&self.record["parameters"], parameters)?,
        );
        m.insert("input_bindings".into(), input_bindings.clone());
        m.insert("warmup".into(), warmup.clone());
        m.insert(
            "extensions".into(),
            if self.reference.kind() != "FACTOR"
                && self.record["execution_shape"] == "CROSS_SECTION"
            {
                json!({"calculation_execution_shape":{"type":"STRING","value":"CROSS_SECTION"}})
            } else {
                json!({})
            },
        );
        Definition::from_record(&d)
    }
}
