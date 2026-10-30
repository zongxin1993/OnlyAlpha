//! Historical closed-Bar Dataset identity. Source/permission proof belongs to the
//! owning materializer/admission, never to these supplied values.
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::{OnlyBar, OnlyBarSemantic},
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

pub type Result<T> = std::result::Result<T, &'static str>;
pub(crate) const INVALID: &str = "DATASET_INPUT_INVALID";
pub(crate) const LIMIT: usize = 128 * 1024 * 1024;
#[derive(Clone, Debug)]
pub struct Dataset {
    definition: Value,
    rows: Vec<Value>,
    content: String,
    snapshot: String,
    construction: String,
}
impl Dataset {
    pub fn from_bars(
        definition: &Value,
        bars: &[Value],
        construction: &str,
        max_rows: usize,
    ) -> Result<Self> {
        if bars.len() > max_rows {
            return Err("DATASET_READ_BUDGET_EXCEEDED");
        }
        if !crate::is_sha256_hex(construction) {
            return Err(INVALID);
        }
        let definition = validate_definition(definition)?;
        let ids = definition["instruments"]
            .as_array()
            .ok_or(INVALID)?
            .iter()
            .map(|v| text(v).map(str::to_owned))
            .collect::<Result<BTreeSet<_>>>()?;
        let semantic =
            OnlyBarSemantic::from_record(&definition["bar_semantic"]).map_err(|_| INVALID)?;
        let start = ns(&definition["time_range"]["start"])?;
        let end = ns(&definition["time_range"]["end"])?;
        let mut rows = Vec::with_capacity(bars.len());
        let mut logical = BTreeSet::new();
        for value in bars {
            let bar = OnlyBar::from_record(value).map_err(|_| INVALID)?;
            let v = bar.to_record();
            let event = ns(&v["ts_event"])?;
            if !ids.contains(&bar.instrument_id().to_string())
                || bar.bar_type().semantic() != &semantic
                || !bar.is_closed()
                || event < start
                || event >= end
                || v["adjustment_type"] != definition["bar_semantic"]["adjustment_policy"]
            {
                return Err(INVALID);
            }
            let row = bar_row(&bar)?;
            let key = (
                text(&row["instrument_id"])?.to_string(),
                number(&row["bar_start_ns"])?,
                number(&row["bar_end_ns"])?,
            );
            if !logical.insert(key) {
                return Err("DATASET_CONTENT_CONFLICT");
            }
            rows.push(row);
        }
        rows.sort_by_key(|v| {
            (
                v["instrument_id"].as_str().unwrap_or_default().to_owned(),
                v["bar_start_ns"].as_i64(),
                v["bar_end_ns"].as_i64(),
                v["ts_event_ns"].as_i64(),
                v["revision"].as_i64(),
            )
        });
        let content = content_fingerprint(&rows)?;
        let snapshot = fp(
            &json!({"schema_version":2,"definition_fingerprint":fp(&definition)?,"dataset_schema_fingerprint":fp(&schema())?,"content_fingerprint":content,"row_count":rows.len(),"construction_fingerprint":construction}),
        )?;
        Ok(Self {
            definition,
            rows,
            content,
            snapshot,
            construction: construction.into(),
        })
    }
    pub fn rows(&self) -> &[Value] {
        &self.rows
    }
    pub fn definition(&self) -> &Value {
        &self.definition
    }
    pub fn content_fingerprint(&self) -> &str {
        &self.content
    }
    pub fn snapshot_fingerprint(&self) -> &str {
        &self.snapshot
    }
    pub fn construction_fingerprint(&self) -> &str {
        &self.construction
    }
}
fn validate_definition(definition: &Value) -> Result<Value> {
    exact(
        definition,
        &[
            "schema_version",
            "dataset_type",
            "instruments",
            "bar_semantic",
            "time_range",
            "quality_policy",
            "closed_only",
        ],
    )?;
    if definition["schema_version"] != 2
        || definition["dataset_type"] != "HISTORICAL_BAR"
        || definition["quality_policy"] != "STRICT"
        || definition["closed_only"] != true
    {
        return Err(INVALID);
    }
    let mut definition = definition.clone();
    let instruments = definition["instruments"].as_array().ok_or(INVALID)?;
    if instruments.is_empty() {
        return Err(INVALID);
    }
    let mut ids = BTreeSet::new();
    for item in instruments {
        let raw = text(item)?;
        let id = raw
            .parse::<onlyalpha_domain::identifiers::OnlyInstrumentId>()
            .map_err(|_| INVALID)?;
        if id.to_string() != raw || !ids.insert(raw.to_string()) {
            return Err(INVALID);
        }
    }
    definition["instruments"] = json!(ids);
    let semantic =
        OnlyBarSemantic::from_record(&definition["bar_semantic"]).map_err(|_| INVALID)?;
    definition["bar_semantic"] = semantic.to_record();
    exact(&definition["time_range"], &["start", "end"])?;
    let start = ns(&definition["time_range"]["start"])?;
    let end = ns(&definition["time_range"]["end"])?;
    if start >= end {
        return Err(INVALID);
    }
    for key in ["start", "end"] {
        definition["time_range"][key] = iso(text(&definition["time_range"][key])?)?.into();
    }
    Ok(definition)
}
pub(crate) fn exact(v: &Value, keys: &[&str]) -> Result<()> {
    let o = v.as_object().ok_or(INVALID)?;
    if o.len() != keys.len() || keys.iter().any(|k| !o.contains_key(*k)) {
        Err(INVALID)
    } else {
        Ok(())
    }
}
pub(crate) fn text(v: &Value) -> Result<&str> {
    v.as_str().ok_or(INVALID)
}
pub(crate) fn number(v: &Value) -> Result<i64> {
    v.as_i64().ok_or(INVALID)
}
pub(crate) fn canonical(v: &Value) -> Result<String> {
    onlyalpha_metadata_json::canonical_json(&v.to_string(), LIMIT).map_err(|_| INVALID)
}
pub(crate) fn fp(v: &Value) -> Result<String> {
    Ok(hash(canonical(v)?.as_bytes()))
}
pub(crate) fn hash(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
pub(crate) fn iso(raw: &str) -> Result<String> {
    let t: OnlyUtcDateTime = raw.parse().map_err(|_| INVALID)?;
    Ok(format!(
        "{}+00:00",
        t.to_string().strip_suffix('Z').ok_or(INVALID)?
    ))
}
fn ns(v: &Value) -> Result<i64> {
    let t: OnlyUtcDateTime = text(v)?.parse().map_err(|_| INVALID)?;
    OnlyTimestamp::from_datetime(t)
        .unix_nanos()
        .to_string()
        .parse()
        .map_err(|_| INVALID)
}
fn decimal(v: &Value) -> Result<Value> {
    if v.is_null() {
        return Ok(Value::Null);
    }
    let raw = text(v)?;
    let value: bigdecimal::BigDecimal = raw.parse().map_err(|_| INVALID)?;
    let scaled = value.with_scale(18);
    if value != scaled {
        return Err(INVALID);
    }
    let (integer, scale) = scaled.as_bigint_and_exponent();
    if scale != 18 || integer.to_string().trim_start_matches('-').len() > 38 {
        return Err(INVALID);
    }
    Ok(scaled.to_string().into())
}
fn bar_row(bar: &OnlyBar) -> Result<Value> {
    let v = bar.to_record();
    let mut r = json!({"instrument_id":bar.instrument_id().to_string(),"bar_semantic_json":canonical(&bar.bar_type().semantic().to_record())?,"trading_day":v["trading_day"],"session_type":v["session_type"],"price_precision":v["open"]["precision"],"volume_precision":v["volume"]["precision"],"is_closed":true,"revision":number(&v["revision"])? ,"adjustment_type":v["adjustment_type"],"trade_count":v["trade_count"]});
    if !v["trade_count"].is_null() {
        number(&v["trade_count"])?;
    }
    for name in ["bar_start", "bar_end", "ts_event", "ts_init"] {
        r[format!("{name}_ns")] = ns(&v[name])?.into();
    }
    for name in [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "open_interest",
    ] {
        r[name] = decimal(&v[name]["value"])?;
    }
    for name in ["quote_volume", "open_interest"] {
        r[format!("{name}_precision")] = v[name]["precision"].clone();
    }
    r["turnover_amount"] = decimal(&v["turnover"]["amount"])?;
    r["turnover_currency"] = v["turnover"]["currency"]["code"].clone();
    r["turnover_currency_precision"] = v["turnover"]["currency"]["precision"].clone();
    r["turnover_currency_type"] = v["turnover"]["currency"]["currency_type"].clone();
    Ok(r)
}
pub(crate) fn content_fingerprint(rows: &[Value]) -> Result<String> {
    let mut digest = Sha256::new();
    for row in rows {
        let raw = canonical(row)?;
        digest.update((raw.len() as u64).to_be_bytes());
        digest.update(raw.as_bytes());
    }
    Ok(digest
        .finalize()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect())
}
pub(crate) const COLUMNS: &[(&str, &str, bool, &str)] = &[
    ("instrument_id", "utf8", false, "instrument_identity"),
    ("bar_semantic_json", "utf8", false, "bar_semantic"),
    ("bar_start_ns", "int64", false, "utc_timestamp"),
    ("bar_end_ns", "int64", false, "utc_timestamp"),
    ("ts_event_ns", "int64", false, "utc_timestamp"),
    ("ts_init_ns", "int64", false, "utc_timestamp"),
    ("trading_day", "date32", false, "trading_day"),
    ("session_type", "utf8", false, "session"),
    ("open", "decimal128(38,18)", false, "price"),
    ("high", "decimal128(38,18)", false, "price"),
    ("low", "decimal128(38,18)", false, "price"),
    ("close", "decimal128(38,18)", false, "price"),
    ("price_precision", "int32", false, "precision"),
    ("volume", "decimal128(38,18)", false, "quantity"),
    ("volume_precision", "int32", false, "precision"),
    ("quote_volume", "decimal128(38,18)", true, "quantity"),
    ("quote_volume_precision", "int32", true, "precision"),
    ("turnover_amount", "decimal128(38,18)", true, "money"),
    ("turnover_currency", "utf8", true, "currency"),
    ("turnover_currency_precision", "int32", true, "precision"),
    ("turnover_currency_type", "utf8", true, "currency_type"),
    ("trade_count", "int64", true, "count"),
    ("open_interest", "decimal128(38,18)", true, "quantity"),
    ("open_interest_precision", "int32", true, "precision"),
    ("is_closed", "bool", false, "lifecycle"),
    ("revision", "int64", false, "revision"),
    ("adjustment_type", "utf8", false, "adjustment"),
];
pub fn schema() -> Value {
    json!({"schema_id":"onlyalpha.research.historical_bar","schema_version":2,"columns":COLUMNS.iter().map(|(name,kind,nullable,role)|json!({"name":name,"logical_type":kind,"nullable":nullable,"semantic_role":role})).collect::<Vec<_>>()})
}

pub(crate) fn rows_to_bars(rows: &[Value]) -> Result<Vec<Value>> {
    rows.iter().map(|r|{
        let instrument:onlyalpha_domain::identifiers::OnlyInstrumentId=text(&r["instrument_id"])?.parse().map_err(|_|INVALID)?;
        let semantic:Value=serde_json::from_str(text(&r["bar_semantic_json"])?).map_err(|_|INVALID)?;
        let mut v=json!({"schema_version":1,"bar_type":{"schema_version":2,"instrument_id":instrument.to_record(),"semantic":semantic},"trading_day":r["trading_day"],"session_type":r["session_type"],"is_closed":r["is_closed"],"revision":r["revision"],"adjustment_type":r["adjustment_type"],"trade_count":r["trade_count"]});
        for name in ["bar_start","bar_end","ts_event","ts_init"]{v[name]=OnlyTimestamp::from_unix_nanos(number(&r[format!("{name}_ns")])?.into()).to_datetime_exact().map_err(|_|INVALID)?.to_string().into();}
        for name in ["open","high","low","close","volume","quote_volume","open_interest"]{
            let key=if ["open","high","low","close"].contains(&name){"price_precision".to_string()}else{format!("{name}_precision")};
            v[name]=if r[name].is_null(){if !r[&key].is_null(){return Err(INVALID);}Value::Null}else{
                let precision=number(&r[&key])?;if !(0..=18).contains(&precision){return Err(INVALID);}
                let d:bigdecimal::BigDecimal=text(&r[name])?.parse().map_err(|_|INVALID)?;let scaled=d.with_scale(precision);if scaled!=d{return Err(INVALID);}
                json!({"schema_version":1,"value":scaled.to_string(),"precision":precision})
            };
        }
        v["turnover"]=if r["turnover_amount"].is_null(){if ["turnover_currency","turnover_currency_precision","turnover_currency_type"].iter().any(|k|!r[*k].is_null()){return Err(INVALID);}Value::Null}else{
            let p=number(&r["turnover_currency_precision"])?;if !(0..=18).contains(&p){return Err(INVALID);}
            let d:bigdecimal::BigDecimal=text(&r["turnover_amount"])?.parse().map_err(|_|INVALID)?;let scaled=d.with_scale(p);if d!=scaled{return Err(INVALID);}
            json!({"schema_version":1,"amount":scaled.to_string(),"currency":{"schema_version":1,"code":r["turnover_currency"],"precision":p,"currency_type":r["turnover_currency_type"]}})
        };
        OnlyBar::from_record(&v).map_err(|_|INVALID).map(|b|b.to_record())
    }).collect()
}
mod materialization;
pub use materialization::{MaterializedDataset, NativeMaterializationPlan};
