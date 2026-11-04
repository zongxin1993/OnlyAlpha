use super::*;

/// One algorithm's lossless declaration, not an installed factory or admission.
/// The public descriptor remains its original fixed-decimal projection. Retained
/// SDK values have no separate Product fingerprint and never select a backend.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TypeDeclaration {
    record: Value,
}
impl TypeDeclaration {
    pub fn from_record(v: &Value, max_work: usize) -> Result<Self> {
        let mut work = Work(max_work);
        work.scan(v)?;
        exact(v, &["schema_version", "descriptor", "parameter_values"])?;
        if v["schema_version"].as_u64() != Some(1) {
            return Err(Error::Invalid);
        }
        let d = &v["descriptor"];
        exact(
            d,
            &[
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
                "semantic_bounds",
            ],
        )?;
        let (_, numeric) = semantics(d, &mut work)?;
        if numeric != d["numeric"] {
            return Err(Error::Invalid);
        }
        member(&d["execution_shape"], &["TIME_SERIES", "CROSS_SECTION"])?;
        if d["kind"] == "FACTOR" && d["execution_shape"] != d["factor_kind"] {
            return Err(Error::Invalid);
        }
        let outputs = d["outputs"].as_array().ok_or(Error::Invalid)?;
        let mut expected_bounds = serde_json::Map::new();
        for output in outputs {
            expected_bounds.insert(
                text(&output["name"])?.to_owned(),
                if output["semantic_type"] == "FACTOR_SCORE" {
                    json!(["0", "1"])
                } else {
                    Value::Null
                },
            );
        }
        if d["semantic_bounds"] != Value::Object(expected_bounds) {
            return Err(Error::Invalid);
        }
        let parameters = d["parameters"].as_array().ok_or(Error::Invalid)?;
        let values = v["parameter_values"].as_array().ok_or(Error::Invalid)?;
        if parameters.len() != values.len() {
            return Err(Error::Invalid);
        }
        let mut names = BTreeSet::new();
        for (spec, values) in parameters.iter().zip(values) {
            exact(
                spec,
                &[
                    "name",
                    "parameter_type",
                    "required",
                    "default",
                    "minimum",
                    "maximum",
                    "enum_values",
                    "uppercase",
                ],
            )?;
            let name = text(&spec["name"])?;
            if name.is_empty() || name.chars().any(space) || !names.insert(name) {
                return Err(Error::Invalid);
            }
            member(
                &spec["parameter_type"],
                &["INTEGER", "DECIMAL", "STRING", "BOOLEAN"],
            )?;
            let required = spec["required"].as_bool().ok_or(Error::Invalid)?;
            spec["uppercase"].as_bool().ok_or(Error::Invalid)?;
            exact(values, &["default", "minimum", "maximum", "enum_values"])?;
            for field in ["default", "minimum", "maximum"] {
                let projected = scalar(&values[field], &mut work)?;
                if projected["value"] != spec[field] {
                    return Err(Error::Invalid);
                }
            }
            if !required && values["default"]["type"] == "NULL" {
                return Err(Error::Invalid);
            }
            let min = bound(&values["minimum"])?;
            let max = bound(&values["maximum"])?;
            if min.zip(max).is_some_and(|(min, max)| min > max) {
                return Err(Error::Invalid);
            }
            let choices = values["enum_values"].as_array().ok_or(Error::Invalid)?;
            let public_choices = spec["enum_values"].as_array().ok_or(Error::Invalid)?;
            if choices.len() != public_choices.len() {
                return Err(Error::Invalid);
            }
            for (choice, public) in choices.iter().zip(public_choices) {
                if scalar(choice, &mut work)?["value"] != *public {
                    return Err(Error::Invalid);
                }
            }
        }
        Ok(Self { record: v.clone() })
    }
    /// Validate pure resolver output. This does not normalize the original user
    /// input (including uppercase/default/coercion rules), prove algorithm-specific
    /// derivations or grant a caller's admission.
    pub fn validate_candidate(&self, candidate: &Value, max_work: usize) -> Result<Definition> {
        let mut work = Work(max_work);
        work.scan(&self.record)?;
        work.scan(candidate)?;
        let definition = Definition::decode(candidate, &mut work)?;
        let d = &self.record["descriptor"];
        for key in ["kind", "type_id", "semantic_version"] {
            if definition.record[key] != d[key] {
                return Err(Error::Invalid);
            }
        }
        let specs = d["parameters"].as_array().ok_or(Error::Invalid)?;
        let values = self.record["parameter_values"]
            .as_array()
            .ok_or(Error::Invalid)?;
        let parameters = definition.record["parameters"]
            .as_object()
            .ok_or(Error::Invalid)?;
        if specs.len() != parameters.len() {
            return Err(Error::Invalid);
        }
        for (spec, declared) in specs.iter().zip(values) {
            let value = parameters.get(text(&spec["name"])?).ok_or(Error::Invalid)?;
            if value["type"] != spec["parameter_type"] {
                return Err(Error::Invalid);
            }
            for (field, minimum) in [("minimum", true), ("maximum", false)] {
                if declared[field]["type"] != "NULL" {
                    work.take(value_size(&value["value"]))?;
                    work.take(value_size(&spec[field]))?;
                    let n = bound(value)?.ok_or(Error::Invalid)?;
                    let limit = bound(&declared[field])?.ok_or(Error::Invalid)?;
                    if (minimum && n < limit) || (!minimum && n > limit) {
                        return Err(Error::Invalid);
                    }
                }
            }
            let choices = declared["enum_values"].as_array().ok_or(Error::Invalid)?;
            let public = spec["enum_values"].as_array().ok_or(Error::Invalid)?;
            if !choices.is_empty() {
                let mut allowed = false;
                for (choice, projection) in choices.iter().zip(public) {
                    // Decimal exponents can be short on the private wire but
                    // expensive in comparison; charge the verified public size.
                    work.take(value_size(&value["value"]))?;
                    work.take(value_size(projection))?;
                    if equivalent(value, choice)? {
                        allowed = true;
                        break;
                    }
                }
                if !allowed {
                    return Err(Error::Invalid);
                }
            }
        }
        Ok(definition)
    }
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub fn descriptor(&self) -> Value {
        self.record["descriptor"].clone()
    }
}

fn bound(v: &Value) -> Result<Option<BigDecimal>> {
    let n = match text(&v["type"])? {
        "NULL" => return Ok(None),
        "INTEGER" => integer(&v["value"])?.to_string(),
        "DECIMAL" => text(&v["value"])?.to_owned(),
        // bool is an int in the original SDK's inclusive numeric comparisons.
        "BOOLEAN" => if v["value"].as_bool().ok_or(Error::Invalid)? {
            "1"
        } else {
            "0"
        }
        .to_owned(),
        _ => return Err(Error::Invalid),
    };
    Ok(Some(BigDecimal::from_str(&n).map_err(|_| Error::Invalid)?))
}

fn value_size(v: &Value) -> usize {
    match v {
        Value::String(s) => s.len(),
        Value::Number(n) => n.as_str().len(),
        _ => 1,
    }
}
fn equivalent(a: &Value, b: &Value) -> Result<bool> {
    let numeric = |v: &Value| matches!(v["type"].as_str(), Some("INTEGER" | "DECIMAL" | "BOOLEAN"));
    if numeric(a) && numeric(b) {
        Ok(bound(a)? == bound(b)?)
    } else {
        Ok(a["type"] == b["type"] && a["value"] == b["value"])
    }
}
