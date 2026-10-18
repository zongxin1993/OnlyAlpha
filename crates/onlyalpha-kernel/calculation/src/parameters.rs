use crate::{Result, record::*};
use bigdecimal::BigDecimal;
use serde_json::{Map, Value, json};
use std::{collections::BTreeSet, str::FromStr};
fn normalize(spec: &Value, input: &Value) -> Result<Value> {
    let t = text(&spec["parameter_type"])?;
    let value = match t {
        "INTEGER" => {
            let raw = if let Some(n) = input.as_number() {
                n.to_string()
            } else {
                text(input)?.to_owned()
            };
            if raw.len() > LIMIT {
                return Err(err("INTEGER_BUDGET"));
            }
            let n = bigdecimal::num_bigint::BigInt::from_str(&raw)
                .map_err(|_| err("INTEGER_REQUIRED"))?;
            serde_json::from_str(&n.to_string()).map_err(|_| err("INTEGER_REQUIRED"))?
        }
        "DECIMAL" => {
            let raw = if let Some(n) = input.as_number() {
                let s = n.to_string();
                if s.contains(['.', 'e', 'E']) {
                    return Err(err("BINARY_FLOAT_FORBIDDEN"));
                }
                s
            } else {
                text(input)?.to_owned()
            };
            json!(decimal(&raw)?)
        }
        "STRING" => {
            let raw = text(input)?;
            if boolean(&spec["uppercase"])? {
                if !raw.is_ascii() {
                    return Err(err("ASCII_UPPERCASE_REQUIRED"));
                }
                json!(raw.to_ascii_uppercase())
            } else {
                json!(raw)
            }
        }
        "BOOLEAN" => json!(boolean(input)?),
        _ => return Err(err("PARAMETER_TYPE_INVALID")),
    };
    let result = scalar(&json!({"type":t,"value":value}))?;
    for (key, minimum) in [("minimum", true), ("maximum", false)] {
        if !spec[key].is_null() {
            let limit = scalar(&spec[key])?;
            if limit["type"] != t || !matches!(t, "INTEGER" | "DECIMAL") {
                return Err(err("BOUND_TYPE_INVALID"));
            }
            let n = number(&result)?;
            let bound = number(&limit)?;
            if (minimum && n < bound) || (!minimum && n > bound) {
                return Err(err("PARAMETER_RANGE"));
            }
        }
    }
    let allowed = array(&spec["enum_values"])?;
    if !allowed.is_empty() && !allowed.contains(&result) {
        return Err(err("PARAMETER_ENUM"));
    }
    Ok(result)
}
fn number(v: &Value) -> Result<BigDecimal> {
    let s = if let Some(s) = v["value"].as_str() {
        s.to_owned()
    } else {
        v["value"].to_string()
    };
    BigDecimal::from_str(&s).map_err(|_| err("NUMERIC_BOUND_REQUIRED"))
}
pub(crate) fn schema(v: &Value) -> Result<Value> {
    let mut out = vec![];
    let mut names = BTreeSet::new();
    for spec in array(v)? {
        object(
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
        if !names.insert(name(&spec["name"])?) {
            return Err(err("DUPLICATE_PARAMETER"));
        }
        let t = member(
            &spec["parameter_type"],
            &["INTEGER", "DECIMAL", "STRING", "BOOLEAN"],
        )?;
        let required = boolean(&spec["required"])?;
        let upper = boolean(&spec["uppercase"])?;
        if upper && t != "STRING" {
            return Err(err("UPPERCASE_TYPE"));
        }
        let mut bounds = vec![];
        for key in ["minimum", "maximum"] {
            let bound = if spec[key].is_null() {
                Value::Null
            } else {
                let bound = scalar(&spec[key])?;
                if bound["type"] != t || !matches!(t, "INTEGER" | "DECIMAL") {
                    return Err(err("BOUND_TYPE_INVALID"));
                }
                bound
            };
            bounds.push(bound);
        }
        if !bounds[0].is_null() && !bounds[1].is_null() && number(&bounds[0])? > number(&bounds[1])?
        {
            return Err(err("INVALID_RANGE"));
        }
        let default = if required {
            if !spec["default"].is_null() {
                return Err(err("REQUIRED_HAS_DEFAULT"));
            }
            Value::Null
        } else {
            let d = scalar(&spec["default"])?;
            if d["type"] != t {
                return Err(err("DEFAULT_TYPE"));
            }
            d
        };
        let mut allowed = vec![];
        for value in array(&spec["enum_values"])? {
            let value = scalar(value)?;
            if value["type"] != t || allowed.contains(&value) {
                return Err(err("ENUM_TYPE_OR_DUPLICATE"));
            }
            allowed.push(value);
        }
        // Construct from validated leaves instead of recursively cloning untrusted metadata.
        let mut s = json!({"name":spec["name"],"parameter_type":t,"required":required,"default":default,"minimum":bounds[0],"maximum":bounds[1],"enum_values":[],"uppercase":upper});
        s["enum_values"] = json!(allowed);
        // Enum entries themselves must satisfy normalization and bounds; a temporary empty enum avoids circular membership checking.
        let mut unrestricted = s.clone();
        unrestricted["enum_values"] = json!([]);
        for value in &allowed {
            if normalize(&unrestricted, &value["value"])? != *value {
                return Err(err("ENUM_NOT_CANONICAL"));
            }
        }
        if !required {
            s["default"] = normalize(&s, &s["default"]["value"])?;
        }
        out.push(s);
    }
    Ok(json!(out))
}
pub(crate) fn parameters(schema: &Value, input: &Value) -> Result<Value> {
    let supplied = map(input)?;
    let specs = array(schema)?;
    if supplied
        .keys()
        .any(|k| !specs.iter().any(|s| s["name"].as_str() == Some(k)))
    {
        return Err(err("UNKNOWN_PARAMETER"));
    }
    let mut out = Map::new();
    for spec in specs {
        let key = text(&spec["name"])?;
        let value = if let Some(v) = supplied.get(key) {
            normalize(spec, v)?
        } else if boolean(&spec["required"])? {
            return Err(err("MISSING_PARAMETER"));
        } else {
            spec["default"].clone()
        };
        out.insert(key.into(), value);
    }
    Ok(Value::Object(out))
}
