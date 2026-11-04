mod support;
use onlyalpha_event::*;
use support::*;
#[test]
fn sample_retention_is_bounded_and_loss_is_explicit() {
    let mut bus = OnlyEventBus::new(OnlyEventBusConfig {
        capacity: 4,
        diagnostic_capacity: 2,
        ..Default::default()
    })
    .unwrap();
    bus.subscribe(
        OnlySubscriptionId::parse("00000000-0000-0000-0000-000000000001").unwrap(),
        OnlyEventType::new("FACT").unwrap(),
        "failure",
        OnlyEventPriority::Normal,
        Box::new(|_, _| Err(OnlyEventError::Callback("expected".into()))),
    )
    .unwrap();
    for i in 1..=3 {
        bus.publish(event(i, OnlyEventPriority::Normal)).unwrap();
        let report = bus.dispatch_one().unwrap().unwrap();
        assert_eq!(report.event.sequence().to_string(), i.to_string());
        assert_eq!(report.handler_results.len(), 1);
    }
    let d = bus.diagnostics().unwrap();
    assert_eq!(d.dispatches.samples.len(), 2);
    assert_eq!(d.dispatches.total.to_string(), "3");
    assert_eq!(d.dispatches.evicted.to_string(), "1");
    assert_eq!(d.failures.samples.len(), 2);
    assert_eq!(d.failures.total.to_string(), "3");
    assert_eq!(d.failures.evicted.to_string(), "1");
    let mut replacement = OnlyEventBus::new(OnlyEventBusConfig {
        capacity: 1,
        diagnostic_capacity: 2,
        queue_policy: OnlyEventQueuePolicy::DropLowPriority,
        ..Default::default()
    })
    .unwrap();
    for (i, priority) in [
        OnlyEventPriority::Low,
        OnlyEventPriority::Normal,
        OnlyEventPriority::High,
        OnlyEventPriority::Critical,
    ]
    .into_iter()
    .enumerate()
    {
        replacement
            .publish(event((i + 1) as u64, priority))
            .unwrap();
    }
    let d = replacement.diagnostics().unwrap();
    assert_eq!(d.replacements.samples.len(), 2);
    assert_eq!(d.replacements.total.to_string(), "3");
    assert_eq!(d.replacements.evicted.to_string(), "1");
    assert_eq!(
        d.replacements.samples[1]
            .replaced
            .as_ref()
            .unwrap()
            .sequence()
            .to_string(),
        "3"
    );
}
