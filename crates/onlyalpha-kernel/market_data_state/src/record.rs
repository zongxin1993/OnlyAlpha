//! Current component records. Decoding grants no Source or Runtime capability.
use crate::{
    OnlyMarketDataSeriesSnapshot, OnlyMarketDataSnapshot, OnlyMarketDataState,
    model::*,
    state::{SeriesMap, key},
};
use num_bigint::{BigInt, BigUint};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    identifiers::OnlyClusterId,
    market::{OnlyBar, OnlyBarType},
    time::OnlyTimestamp,
};
use serde_json::{Map, Number, Value, json};
use std::{
    collections::{BTreeMap, VecDeque},
    str::FromStr,
    sync::Arc,
};
fn invalid(message: impl ToString) -> OnlyMarketDataStateError {
    OnlyMarketDataStateError::Record(message.to_string())
}
fn object<'a>(
    value: &'a Value,
    fields: &[&str],
) -> Result<&'a Map<String, Value>, OnlyMarketDataStateError> {
    let row = value
        .as_object()
        .ok_or_else(|| invalid("object required"))?;
    if row.len() != fields.len() || fields.iter().any(|field| !row.contains_key(*field)) {
        return Err(invalid("exact fields required"));
    }
    Ok(row)
}
fn schema(row: &Map<String, Value>) -> Result<(), OnlyMarketDataStateError> {
    if row["schema_version"]
        .as_number()
        .map(ToString::to_string)
        .as_deref()
        != Some("2")
    {
        return Err(invalid("current schema 2 required"));
    }
    Ok(())
}
fn array(value: &Value) -> Result<&Vec<Value>, OnlyMarketDataStateError> {
    value.as_array().ok_or_else(|| invalid("array required"))
}
fn text(value: &Value) -> Result<&str, OnlyMarketDataStateError> {
    value.as_str().ok_or_else(|| invalid("string required"))
}
fn integer<T: FromStr>(value: &Value) -> Result<T, OnlyMarketDataStateError> {
    value
        .as_number()
        .ok_or_else(|| invalid("integer token required"))?
        .to_string()
        .parse()
        .map_err(|_| invalid("exact integer required"))
}
fn number(value: impl ToString) -> Value {
    Value::Number(Number::from_str(&value.to_string()).expect("exact integer spelling"))
}
fn scope(row: &Map<String, Value>) -> Result<OnlyMarketDataStateScope, OnlyMarketDataStateError> {
    Ok(OnlyMarketDataStateScope::new(
        text(&row["engine_id"])?.parse().map_err(invalid)?,
        text(&row["runtime_id"])?.parse().map_err(invalid)?,
    ))
}
fn bar_type(value: &Value) -> Result<OnlyBarType, OnlyMarketDataStateError> {
    OnlyBarType::from_record(value).map_err(invalid)
}
fn series_record(series: &OnlyMarketDataSeriesSnapshot) -> Value {
    json!({"bar_type":series.bar_type().to_record(),"version":number(series.version()),"history":series.history().iter().map(|b|b.to_record()).collect::<Vec<_>>()})
}
fn parse_series(
    value: &Value,
    limit: Option<usize>,
) -> Result<SeriesMap, OnlyMarketDataStateError> {
    let mut result = BTreeMap::new();
    for row in array(value)? {
        let row = object(row, &["bar_type", "version", "history"])?;
        let kind = bar_type(&row["bar_type"])?;
        let version: BigUint = integer(&row["version"])?;
        let bars = array(&row["history"])?;
        if limit.is_some_and(|limit| bars.len() > limit) {
            return Err(invalid("history exceeds configured limit"));
        }
        let history: VecDeque<_> = bars
            .iter()
            .map(|v| OnlyBar::from_record(v).map(Arc::new).map_err(invalid))
            .collect::<Result<_, _>>()?;
        let series =
            OnlyMarketDataSeriesSnapshot::new(kind.clone(), version, history).map_err(invalid)?;
        if result.insert(key(&kind), Arc::new(series)).is_some() {
            return Err(invalid("duplicate series"));
        }
    }
    Ok(result)
}
fn parse_types(value: &Value) -> Result<BTreeMap<String, OnlyBarType>, OnlyMarketDataStateError> {
    let mut result = BTreeMap::new();
    for value in array(value)? {
        let kind = bar_type(value)?;
        if result.insert(key(&kind), kind).is_some() {
            return Err(invalid("duplicate type"));
        }
    }
    Ok(result)
}
impl OnlyMarketDataState {
    pub fn capture_checkpoint(&self) -> Value {
        json!({"schema_version":2,"engine_id":self.scope.engine_id().value(),"runtime_id":self.scope.runtime_id().value(),"history_limit":self.history_limit,"series":self.series.values().map(|s|series_record(s)).collect::<Vec<_>>()})
    }
    pub fn restore_checkpoint(&mut self, value: &Value) -> Result<(), OnlyMarketDataStateError> {
        let row = object(
            value,
            &[
                "schema_version",
                "engine_id",
                "runtime_id",
                "history_limit",
                "series",
            ],
        )?;
        schema(row)?;
        let owner = scope(row)?;
        let limit: usize = integer(&row["history_limit"])?;
        if limit == 0 {
            return Err(invalid("positive history_limit required"));
        }
        let series = parse_series(&row["series"], Some(limit))?;
        if owner != self.scope {
            return Err(OnlyMarketDataStateError::Scope);
        }
        if limit != self.history_limit {
            return Err(OnlyMarketDataStateError::Configuration);
        }
        self.series = series;
        Ok(())
    }
}
impl OnlyMarketDataSnapshot {
    pub fn to_record(&self) -> Value {
        json!({"schema_version":2,"engine_id":self.scope.engine_id().value(),"runtime_id":self.scope.runtime_id().value(),"cluster_id":self.cluster_id.as_ref().map(|id|id.value()),"ts_event_ns":number(self.ts_event.unix_nanos()),"ts_init_ns":number(self.ts_init.unix_nanos()),"primary_bar_type":self.primary.to_record(),"visible_bar_types":self.visible.values().map(|t|t.to_record()).collect::<Vec<_>>(),"updated_bar_types":self.updated.iter().map(|k|self.visible[k].to_record()).collect::<Vec<_>>(),"series":self.series.values().map(|s|series_record(s)).collect::<Vec<_>>(),"quality_flags":self.quality_flags})
    }
    pub fn from_record(value: &Value) -> Result<Self, OnlyMarketDataStateError> {
        let row = object(
            value,
            &[
                "schema_version",
                "engine_id",
                "runtime_id",
                "cluster_id",
                "ts_event_ns",
                "ts_init_ns",
                "primary_bar_type",
                "visible_bar_types",
                "updated_bar_types",
                "series",
                "quality_flags",
            ],
        )?;
        schema(row)?;
        let cluster_id = if row["cluster_id"].is_null() {
            None
        } else {
            Some(
                text(&row["cluster_id"])?
                    .parse::<OnlyClusterId>()
                    .map_err(invalid)?,
            )
        };
        let updated = parse_types(&row["updated_bar_types"])?
            .into_keys()
            .collect();
        let flags = array(&row["quality_flags"])?
            .iter()
            .map(|v| text(v).map(str::to_owned))
            .collect::<Result<Vec<_>, _>>()?;
        let result = Self {
            scope: scope(row)?,
            cluster_id,
            ts_event: OnlyTimestamp::from_unix_nanos(integer::<BigInt>(&row["ts_event_ns"])?),
            ts_init: OnlyTimestamp::from_unix_nanos(integer::<BigInt>(&row["ts_init_ns"])?),
            primary: bar_type(&row["primary_bar_type"])?,
            visible: parse_types(&row["visible_bar_types"])?,
            series: parse_series(&row["series"], None)?,
            updated,
            quality_flags: flags,
        };
        result.validate().map_err(invalid)?;
        Ok(result)
    }
    pub fn to_json(&self) -> Result<String, OnlyMarketDataStateError> {
        serde_json::to_string(&self.to_record()).map_err(invalid)
    }
    pub fn from_json(input: &str) -> Result<Self, OnlyMarketDataStateError> {
        Self::from_record(&serde_json::from_str(input).map_err(invalid)?)
    }
}
