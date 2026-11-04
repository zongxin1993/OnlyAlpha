use onlyalpha_domain::{
    identifiers::{OnlyEngineId, OnlyRuntimeId},
    time::OnlyTimestamp,
};
use onlyalpha_event::*;
use serde_json::json;
use std::sync::Arc;
pub fn event(sequence: u64, priority: OnlyEventPriority) -> Arc<OnlyEvent> {
    Arc::new(
        OnlyEvent::new(OnlyEventInput {
            event_id: OnlyEventId::parse(&format!("00000000-0000-0000-0000-{sequence:012x}"))
                .unwrap(),
            event_type: OnlyEventType::new("FACT").unwrap(),
            source: OnlyEventSource::new("feed").unwrap(),
            scope: scope("runtime"),
            timestamp: OnlyTimestamp::from_unix_nanos(0.into()),
            init_timestamp: OnlyTimestamp::from_unix_nanos(0.into()),
            sequence: sequence.into(),
            correlation_id: None,
            causation_id: None,
            priority,
            payload: OnlyEventPayload::Scalar(json!(null)),
            metadata: Default::default(),
        })
        .unwrap(),
    )
}
pub fn scope(runtime: &str) -> OnlyEventScope {
    OnlyEventScope::new(
        OnlyEngineId::new("engine").unwrap(),
        Some(OnlyRuntimeId::new(runtime).unwrap()),
        None,
    )
    .unwrap()
}
