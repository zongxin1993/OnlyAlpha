use crate::plan::{err, fields, keyword, policy, setting_number};
use bigdecimal::BigDecimal;
use onlyalpha_broker::Error;
use serde_json::{Value, json};
use std::collections::BTreeMap;

#[derive(Clone)]
pub(crate) struct Config {
    pub fill: Value,
    pub offset: Option<BigDecimal>,
    pub submit_ns: i64,
    pub fill_ns: i64,
    pub cancel_ns: i64,
    pub controls: BTreeMap<u64, Value>,
    pub record: Value,
}

impl Config {
    pub fn parse(v: &Value) -> Result<Self, Error> {
        fields(
            v,
            &[
                "matching",
                "maximum_fill_quantity",
                "latency",
                "slippage",
                "simulation",
            ],
        )?;
        let empty = json!({});
        let matching = v.get("matching").unwrap_or(&empty);
        let latency = v.get("latency").unwrap_or(&empty);
        let slip = v.get("slippage").unwrap_or(&empty);
        let simulation = v.get("simulation").unwrap_or(&empty);
        fields(matching, &["type", "maximum_fill_quantity", "partial_fill"])?;
        fields(
            latency,
            &[
                "submit_ns",
                "acceptance_ns",
                "fill_ns",
                "cancel_ns",
                "query_ns",
            ],
        )?;
        fields(slip, &["type", "price_offset"])?;
        fields(simulation, &["submissions"])?;
        if keyword(matching, "type", "NEXT_BAR")? != "NEXT_BAR" {
            return Err(err("VIRTUAL_MATCHING"));
        }
        let partial = matching
            .get("partial_fill")
            .filter(|v| !v.is_null())
            .unwrap_or(&empty);
        let fill = policy(
            partial,
            &[
                &v["maximum_fill_quantity"],
                &matching["maximum_fill_quantity"],
                &partial["maximum_fill_quantity"],
            ],
        )?;
        let supplied = slip
            .get("price_offset")
            .filter(|v| !v.is_null())
            .map(setting_number)
            .transpose()?;
        let offset = match keyword(slip, "type", "NONE")?.as_str() {
            "NONE" => None,
            "FIXED" => {
                let n = supplied.unwrap_or_default();
                if n.with_scale(8) != n {
                    return Err(err("VIRTUAL_SLIPPAGE"));
                }
                Some(n)
            }
            _ => return Err(err("VIRTUAL_SLIPPAGE")),
        };
        let delay = |k: &str| match latency.get(k) {
            None => Ok(0),
            Some(v) => v
                .as_i64()
                .filter(|d| *d >= 0)
                .ok_or_else(|| err("VIRTUAL_LATENCY")),
        };
        let submit = delay("submit_ns")?;
        let acceptance = delay("acceptance_ns")?;
        let submit_ns = submit
            .checked_add(acceptance)
            .ok_or_else(|| err("VIRTUAL_LATENCY"))?;
        let fill_ns = delay("fill_ns")?;
        let cancel_ns = delay("cancel_ns")?;
        let query_ns = delay("query_ns")?;
        let mut controls = BTreeMap::new();
        let list = json!([]);
        for c in simulation
            .get("submissions")
            .unwrap_or(&list)
            .as_array()
            .ok_or_else(|| err("VIRTUAL_SUBMISSIONS"))?
        {
            fields(
                c,
                &["submission_index", "action", "reason", "rejection_code"],
            )?;
            let index = c["submission_index"]
                .as_u64()
                .filter(|i| *i > 0)
                .ok_or_else(|| err("VIRTUAL_SUBMISSION_INDEX"))?;
            let action = keyword(c, "action", "")?;
            let default_reason = match action.as_str() {
                "REJECT_BEFORE_ACCEPTED" => {
                    "deterministic Virtual Broker rejection before acceptance"
                }
                "ACCEPT_THEN_EXPIRE" if c["rejection_code"].is_null() => {
                    "deterministic Virtual Broker expiry after acceptance"
                }
                _ => return Err(err("VIRTUAL_SUBMISSION_ACTION")),
            };
            let detail = |key: &str, default: &str| -> Result<String, Error> {
                if c[key].is_null() {
                    Ok(default.into())
                } else {
                    c[key]
                        .as_str()
                        .filter(|s| !s.trim().is_empty() && s.len() <= 1024)
                        .map(str::to_owned)
                        .ok_or_else(|| err("VIRTUAL_SUBMISSION_DETAIL"))
                }
            };
            let reason = detail("reason", default_reason)?;
            let code = if action == "REJECT_BEFORE_ACCEPTED" {
                Some(detail("rejection_code", "VIRTUAL_SIMULATION_REJECTED")?)
            } else {
                None
            };
            if controls.insert(index,json!({"submission_index":index,"action":action,"reason":reason,"rejection_code":code})).is_some() {
                return Err(err("VIRTUAL_SUBMISSION_INDEX_DUPLICATE"));
            }
        }
        let record = json!({"fill":fill,"price_offset":offset.as_ref().map(|n| n.normalized().to_plain_string()),
            "latency":{"submit_ns":submit,"acceptance_ns":acceptance,"fill_ns":fill_ns,"cancel_ns":cancel_ns,"query_ns":query_ns},
            "controls":controls.values().collect::<Vec<_>>()});
        Ok(Self {
            fill,
            offset,
            submit_ns,
            fill_ns,
            cancel_ns,
            controls,
            record,
        })
    }
}
