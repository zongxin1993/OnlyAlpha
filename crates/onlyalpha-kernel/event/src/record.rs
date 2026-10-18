use crate::*;
use num_bigint::{BigInt, BigUint};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    identifiers::{OnlyClusterId, OnlyEngineId, OnlyRuntimeId},
    market::OnlyBar,
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use serde_json::{Value, json};
use std::{collections::BTreeMap, str::FromStr};
fn text(v: &Value) -> Result<&str, OnlyEventError> {
    v.as_str()
        .ok_or_else(|| OnlyEventError::Record("expected string".into()))
}
fn integer(v: &Value) -> Result<BigInt, OnlyEventError> {
    v.as_number()
        .ok_or_else(|| OnlyEventError::Record("expected integer".into()))?
        .to_string()
        .parse()
        .map_err(|_| OnlyEventError::Record("expected integer".into()))
}
fn number(v: impl ToString) -> Value {
    Value::Number(v.to_string().parse().expect("canonical exact integer"))
}
impl OnlyEvent {
    pub fn to_record(&self) -> Value {
        let i = &self.input;
        let payload = match &i.payload {
            OnlyEventPayload::Bar(v) => json!({"kind":"OnlyBar","value":v.to_record()}),
            OnlyEventPayload::Mapping(v) => json!({"kind":"mapping","value":v}),
            OnlyEventPayload::Scalar(v) => json!({"kind":"scalar","value":v}),
        };
        json!({
            "schema_version": 2,
            "event_id": i.event_id.to_string(),
            "event_type": i.event_type.value(),
            "ts_event_ns": number(i.timestamp.unix_nanos()),
            "ts_init_ns": number(i.init_timestamp.unix_nanos()),
            "ts_event": i.timestamp.to_datetime().expect("validated Event time").to_string(),
            "ts_init": i.init_timestamp.to_datetime().expect("validated Event time").to_string(),
            "engine_id": i.scope.engine.to_string(),
            "runtime_id": i.scope.runtime.as_ref().expect("Event Runtime").to_string(),
            "cluster_id": i.scope.cluster.as_ref().map(ToString::to_string),
            "source": i.source.value(),
            "sequence": number(&i.sequence),
            "correlation_id": i.correlation_id.map(|v| v.to_string()),
            "causation_id": i.causation_id.map(|v| v.to_string()),
            "priority": i.priority.name(),
            "payload": payload,
            "metadata": i.metadata,
        })
    }
    pub fn from_record(v: &Value) -> Result<Self, OnlyEventError> {
        (|| {
            let keys = [
                "schema_version",
                "event_id",
                "event_type",
                "ts_event_ns",
                "ts_init_ns",
                "ts_event",
                "ts_init",
                "engine_id",
                "runtime_id",
                "cluster_id",
                "source",
                "sequence",
                "correlation_id",
                "causation_id",
                "priority",
                "payload",
                "metadata",
            ];
            let row = v
                .as_object()
                .ok_or_else(|| crate::model::invalid("Event record must be object"))?;
            if row.len() != keys.len()
                || keys.iter().any(|k| !row.contains_key(*k))
                || row["schema_version"] != json!(2)
            {
                return Err(crate::model::invalid("unknown schema or fields"));
            }
            let timestamp = OnlyTimestamp::from_unix_nanos(integer(&row["ts_event_ns"])?);
            let init_timestamp = OnlyTimestamp::from_unix_nanos(integer(&row["ts_init_ns"])?);
            for (key, stamp) in [("ts_event", &timestamp), ("ts_init", &init_timestamp)] {
                let parsed = OnlyUtcDateTime::from_str(text(&row[key])?)?;
                if parsed != stamp.to_datetime()? {
                    return Err(crate::model::invalid("conflicting Event timestamp"));
                }
            }
            let p = row["payload"]
                .as_object()
                .ok_or_else(|| crate::model::invalid("payload envelope"))?;
            if p.len() != 2 || !p.contains_key("kind") || !p.contains_key("value") {
                return Err(crate::model::invalid("payload fields"));
            }
            let payload = match text(&p["kind"])? {
                "OnlyBar" => OnlyEventPayload::Bar(Box::new(OnlyBar::from_record(&p["value"])?)),
                "mapping" => OnlyEventPayload::Mapping(p["value"].clone()),
                "scalar" => OnlyEventPayload::Scalar(p["value"].clone()),
                _ => return Err(crate::model::invalid("unknown payload kind")),
            };
            let metadata = row["metadata"]
                .as_object()
                .ok_or_else(|| crate::model::invalid("metadata object"))?
                .iter()
                .map(|(k, v)| Ok((k.clone(), text(v)?.to_owned())))
                .collect::<Result<BTreeMap<_, _>, OnlyEventError>>()?;
            Self::new(OnlyEventInput {
                event_id: OnlyEventId::parse(text(&row["event_id"])?)?,
                event_type: OnlyEventType::new(text(&row["event_type"])?)?,
                source: OnlyEventSource::new(text(&row["source"])?)?,
                scope: OnlyEventScope::new(
                    OnlyEngineId::new(text(&row["engine_id"])?)?,
                    Some(OnlyRuntimeId::new(text(&row["runtime_id"])?)?),
                    if row["cluster_id"].is_null() {
                        None
                    } else {
                        Some(OnlyClusterId::new(text(&row["cluster_id"])?)?)
                    },
                )?,
                timestamp,
                init_timestamp,
                sequence: BigUint::try_from(integer(&row["sequence"])?)
                    .map_err(|_| crate::model::invalid("negative sequence"))?,
                correlation_id: if row["correlation_id"].is_null() {
                    None
                } else {
                    Some(OnlyCorrelationId::parse(text(&row["correlation_id"])?)?)
                },
                causation_id: if row["causation_id"].is_null() {
                    None
                } else {
                    Some(OnlyCausationId::parse(text(&row["causation_id"])?)?)
                },
                priority: OnlyEventPriority::parse(text(&row["priority"])?)?,
                payload,
                metadata,
            })
        })()
        .map_err(|e: OnlyEventError| OnlyEventError::Record(e.to_string()))
    }
    pub fn to_json(&self) -> Result<String, OnlyEventError> {
        serde_json::to_string(&self.to_record()).map_err(|e| OnlyEventError::Record(e.to_string()))
    }
    pub fn from_json(s: &str) -> Result<Self, OnlyEventError> {
        let v = serde_json::from_str(s).map_err(|e| OnlyEventError::Record(e.to_string()))?;
        Self::from_record(&v)
    }
}
