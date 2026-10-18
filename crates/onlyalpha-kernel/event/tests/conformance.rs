mod support;
use onlyalpha_event::*;
use serde_json::{Value, json};
use std::sync::Arc;
#[test]
fn independent_current_record_vectors_preserve_every_field() {
    for line in include_str!("../../../../test-data/event/records-v2.jsonl").lines() {
        let case: Value = serde_json::from_str(line).unwrap();
        let event = OnlyEvent::from_record(&case["record"]).unwrap();
        assert_eq!(event.to_record(), case["record"], "{}", case["name"]);
    }
}
fn action_event(action: &Value) -> Arc<OnlyEvent> {
    let mut record = support::event(
        action["sequence"].as_u64().unwrap(),
        OnlyEventPriority::parse(action["priority"].as_str().unwrap()).unwrap(),
    )
    .to_record();
    record["runtime_id"] = action["runtime"].clone();
    Arc::new(OnlyEvent::from_record(&record).unwrap())
}
#[test]
fn independent_delivery_vectors_preserve_order_identities_and_outcomes() {
    for line in include_str!("../../../../test-data/event/delivery-v1.jsonl").lines() {
        let case: Value = serde_json::from_str(line).unwrap();
        let policy = match case["policy"].as_str().unwrap() {
            "REJECT" => OnlyEventQueuePolicy::Reject,
            "FAIL_RUNTIME" => OnlyEventQueuePolicy::FailRuntime,
            "DROP_LOW_PRIORITY" => OnlyEventQueuePolicy::DropLowPriority,
            _ => panic!("unknown fixture policy"),
        };
        let mut bus = OnlyEventBus::new(OnlyEventBusConfig {
            capacity: case["capacity"].as_u64().unwrap() as usize,
            scope: Some(support::scope("runtime")),
            queue_policy: policy,
            ..Default::default()
        })
        .unwrap();
        let mut errors = Vec::new();
        for (index, action) in case["actions"].as_array().unwrap().iter().enumerate() {
            let result = match action["op"].as_str().unwrap() {
                "subscribe" => {
                    let fail = action["fail"].as_bool().unwrap();
                    bus.subscribe(
                        OnlySubscriptionId::parse(action["id"].as_str().unwrap()).unwrap(),
                        OnlyEventType::new("FACT").unwrap(),
                        action["name"].as_str().unwrap(),
                        OnlyEventPriority::parse(action["priority"].as_str().unwrap()).unwrap(),
                        Box::new(move |_, _| {
                            if fail {
                                Err(OnlyEventError::Callback("controlled failure".into()))
                            } else {
                                Ok(())
                            }
                        }),
                    )
                    .map(|_| ())
                }
                "unsubscribe" => bus
                    .unsubscribe(OnlySubscriptionId::parse(action["id"].as_str().unwrap()).unwrap())
                    .map(|_| ()),
                "publish" => bus.publish(action_event(action)).map(|_| ()),
                "batch" => {
                    let events = action["events"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .map(action_event)
                        .collect::<Vec<_>>();
                    if action["atomic"].as_bool().unwrap() {
                        bus.publish_many_atomic(&events).map(|_| ())
                    } else {
                        bus.publish_many(&events)
                            .map(|_| ())
                            .map_err(|failure| failure.cause)
                    }
                }
                "drain" => bus.drain().map(|_| ()),
                "close" => bus.close().map(|_| ()),
                "port_result" => {
                    OnlyRuntimeEventPublicationResult::new(OnlyRuntimeEventPublicationInput {
                        route: OnlyRuntimeEventRoute::ExternalDirect,
                        disposition: OnlyRuntimeEventDisposition::Published,
                        attempted: action["attempted"].to_string().parse().unwrap(),
                        published: action["published"].to_string().parse().unwrap(),
                        staged: 0u32.into(),
                        suppressed: 0u32.into(),
                        rejected: 0u32.into(),
                        error: None,
                    })
                    .map(|_| ())
                }
                _ => panic!("unknown fixture action"),
            };
            if let Err(error) = result {
                let category = match error {
                    OnlyEventError::Scope => "SCOPE",
                    OnlyEventError::Capacity => "CAPACITY",
                    OnlyEventError::RuntimeFailure => "RUNTIME_FAILURE",
                    OnlyEventError::Closed => "CLOSED",
                    OnlyEventError::Validation(_) => "INVALID",
                    other => panic!("unexpected error {other}"),
                };
                errors.push(format!("{index}:{category}"));
            }
        }
        let d = bus.diagnostics().unwrap();
        let outcomes = d
            .dispatches
            .samples
            .iter()
            .flat_map(|report| {
                report.handler_results.iter().map(|result| {
                    let status = match &result.outcome {
                        OnlyEventHandlerOutcome::Succeeded => "OK",
                        OnlyEventHandlerOutcome::Error(_) => "ERR",
                        OnlyEventHandlerOutcome::Panic(_) => "PANIC",
                    };
                    format!(
                        "{}|{}|{}|{}",
                        report.event.id(),
                        result.subscription.id,
                        result.subscription.handler_name,
                        status
                    )
                })
            })
            .collect::<Vec<_>>();
        let dropped = d
            .replacements
            .samples
            .iter()
            .map(|receipt| {
                format!(
                    "{}|{}",
                    receipt.replaced.as_ref().unwrap().id(),
                    receipt.accepted.id()
                )
            })
            .collect::<Vec<_>>();
        assert_eq!(
            json!({"outcomes":outcomes,"errors":errors,"dropped":dropped,"pending":bus.pending_count().unwrap()}),
            case["expected"],
            "{}",
            case["name"]
        );
    }
}
