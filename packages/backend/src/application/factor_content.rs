//! Human-led Factor authoring. No Research or execution admission.
use crate::application::private_assets::authoring::{API_FINGERPRINT, Draft};
use serde_json::{Value, json};
use std::collections::BTreeMap;
pub type Result<T> = std::result::Result<T, &'static str>;
pub const INVALID: &str = "FACTOR_CHAT_INVALID";
pub fn hash(value: &Value) -> Result<String> {
    onlyalpha_metadata_json::fingerprint(&value.to_string(), 8 * 1024 * 1024).map_err(|_| INVALID)
}
fn fields(value: &Value, keys: &[&str]) -> Result<()> {
    let o = value.as_object().ok_or(INVALID)?;
    if o.len() != keys.len() || keys.iter().any(|k| !o.contains_key(*k)) {
        return Err(INVALID);
    }
    Ok(())
}
fn text<'a>(value: &'a Value, key: &str, limit: usize) -> Result<&'a str> {
    let v = value[key].as_str().ok_or(INVALID)?;
    if v.trim().is_empty() || v.len() > limit || v.chars().any(char::is_control) {
        return Err(INVALID);
    }
    Ok(v)
}
/// Formula and restricted V1 source are generated together; returned model code is never accepted.
pub fn preview(candidate: &Value, factor_id: &str) -> Result<Value> {
    fields(candidate, &["name", "purpose", "hypothesis", "expression"])?;
    text(candidate, "name", 400)?;
    text(candidate, "purpose", 4000)?;
    crate::application::private_assets::display::Display::create(
        factor_id,
        &json!({"display_name":candidate["name"],"usage_summary":candidate["purpose"]}),
    )
    .map_err(|_| INVALID)?;
    let hypothesis = text(candidate, "hypothesis", 4000)?;
    let mut dependencies = BTreeMap::new();
    let (formula, source) = expression(&candidate["expression"], 0, &mut dependencies)?;
    let inputs: BTreeMap<_, _> = dependencies
        .keys()
        .map(|k| (k.clone(), json!({"type":"DECIMAL","missing":true})))
        .collect();
    let draft=Draft::new(json!({"schema_version":1,"factor_id":factor_id,"base_revision_fingerprint":null,"semantic_version":"1","source_text":format!("def calculate(api, inputs, parameters):\n    return {{'value': {source}}}\n"),"factor_api_version":1,"factor_api_contract_fingerprint":API_FINGERPRINT,"input_contract":inputs,"parameter_contract":{},"output_contract":{"value":{"type":"DECIMAL","missing":true}},"description":hypothesis,"economic_rationale":hypothesis,"category":"chat","tags":[]})).map_err(|_|INVALID)?;
    Ok(
        json!({"name":candidate["name"],"purpose":candidate["purpose"],"hypothesis":hypothesis,"formula":formula,"expression":candidate["expression"],"dependencies":dependencies,"draft":draft.record(),"draft_fingerprint":draft.fingerprint().map_err(|_|INVALID)?,"execution_admitted":false}),
    )
}
fn expression(
    v: &Value,
    depth: usize,
    deps: &mut BTreeMap<String, Value>,
) -> Result<(String, String)> {
    if depth > 8 || v.to_string().len() > 8192 {
        return Err(INVALID);
    }
    if let Some(input) = v["input"].as_str() {
        if !["open", "high", "low", "close", "volume"].contains(&input) {
            return Err(INVALID);
        }
        let (name, label, binding) = if v.get("lag").is_some() || v.get("mean").is_some() {
            let key = if v.get("lag").is_some() {
                "lag"
            } else {
                "mean"
            };
            fields(v, &["input", key])?;
            let period = v[key]
                .as_u64()
                .filter(|p| *p >= 1 && *p <= 10000)
                .ok_or(INVALID)?;
            (
                format!("{input}_{key}_{period}"),
                format!("{key}({input}, {period})"),
                json!({"input":input,"operator":if key=="lag"{"onlyalpha.operator.delay"}else{"onlyalpha.operator.rolling_mean"},"semantic_version":"1","period":period,"closed_only":true}),
            )
        } else {
            fields(v, &["input"])?;
            (
                input.into(),
                input.into(),
                json!({"input":input,"closed_only":true}),
            )
        };
        deps.insert(name.clone(), binding);
        return Ok((label, format!("inputs['{name}']")));
    }
    if let Some(n) = v["integer"].as_i64() {
        fields(v, &["integer"])?;
        if n.unsigned_abs() > 1000000 {
            return Err(INVALID);
        }
        return Ok((n.to_string(), n.to_string()));
    }
    fields(v, &["op", "left", "right"])?;
    let op = v["op"].as_str().ok_or(INVALID)?;
    let symbol = match op {
        "add" => "+",
        "sub" => "−",
        "mul" => "×",
        "div" => "÷",
        _ => return Err(INVALID),
    };
    let (lf, ls) = expression(&v["left"], depth + 1, deps)?;
    let (rf, rs) = expression(&v["right"], depth + 1, deps)?;
    Ok((
        format!("({lf} {symbol} {rf})"),
        format!("api.{op}({ls}, {rs})"),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn preview_source_and_formula_are_derived_from_one_expression() {
        let candidate = json!({"name":"价量关系","purpose":"观察收盘价与成交量的关系","hypothesis":"价格与成交量同时上升","expression":{"op":"mul","left":{"input":"close"},"right":{"input":"volume"}}});
        let value = preview(&candidate, "private.factor.chat_test").unwrap();
        assert_eq!(value["formula"], "(close × volume)");
        assert_eq!(
            value["draft"]["source_text"],
            "def calculate(api, inputs, parameters):\n    return {'value': api.mul(inputs['close'], inputs['volume'])}\n"
        );
        assert!(value["draft"]["input_contract"]["close"].is_object());
    }
    #[test]
    fn unapproved_code_unknown_inputs_and_unbounded_expressions_are_rejected() {
        let mut c = json!({"name":"test","purpose":"test","hypothesis":"test","expression":{"input":"secret"}});
        assert!(preview(&c, "private.factor.chat_test").is_err());
        c["expression"] = json!({"input":"close"});
        c["source_text"] = json!("import os");
        assert!(preview(&c, "private.factor.chat_test").is_err());
    }
}
