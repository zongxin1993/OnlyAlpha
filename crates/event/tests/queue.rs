mod support;
use onlyalpha_event::*;
use support::*;
fn config(capacity: usize, policy: OnlyEventQueuePolicy) -> OnlyEventBusConfig {
    OnlyEventBusConfig {
        capacity,
        diagnostic_capacity: 2,
        scope: Some(scope("runtime")),
        queue_policy: policy,
    }
}
#[test]
fn scoped_batches_are_atomic_while_sequential_batches_report_prefix() {
    let mut bus = OnlyEventBus::new(config(2, OnlyEventQueuePolicy::Reject)).unwrap();
    let valid = event(1, OnlyEventPriority::Normal);
    let mut input = valid.to_record();
    input["runtime_id"] = serde_json::json!("other");
    let invalid = std::sync::Arc::new(OnlyEvent::from_record(&input).unwrap());
    assert!(
        bus.publish_many_atomic(&[valid.clone(), invalid.clone()])
            .is_err()
    );
    assert_eq!(bus.pending_count().unwrap(), 0);
    let failure = bus.publish_many(&[valid, invalid]).unwrap_err();
    assert_eq!(failure.accepted.to_string(), "1");
    assert_eq!(failure.rejected_index, 1);
    assert_eq!(bus.pending_count().unwrap(), 1);
}
#[test]
fn full_queue_policies_preserve_or_report_precise_displacement() {
    for (policy, expected) in [
        (OnlyEventQueuePolicy::Reject, OnlyEventError::Capacity),
        (
            OnlyEventQueuePolicy::FailRuntime,
            OnlyEventError::RuntimeFailure,
        ),
    ] {
        let mut bus = OnlyEventBus::new(config(1, policy)).unwrap();
        bus.publish(event(1, OnlyEventPriority::Normal)).unwrap();
        assert_eq!(
            bus.publish(event(2, OnlyEventPriority::Critical))
                .unwrap_err(),
            expected
        );
        assert_eq!(bus.pending_count().unwrap(), 1);
    }
    let mut bus = OnlyEventBus::new(config(2, OnlyEventQueuePolicy::DropLowPriority)).unwrap();
    bus.publish(event(1, OnlyEventPriority::Low)).unwrap();
    bus.publish(event(2, OnlyEventPriority::Low)).unwrap();
    let receipt = bus.publish(event(3, OnlyEventPriority::High)).unwrap();
    assert_eq!(receipt.replaced.unwrap().sequence().to_string(), "1");
    assert_eq!(receipt.accepted.sequence().to_string(), "3");
    assert!(bus.publish(event(4, OnlyEventPriority::Low)).is_err());
    assert!(bus.publish_many_atomic(&[]).is_err());
    assert_eq!(bus.pending_count().unwrap(), 2);
}
