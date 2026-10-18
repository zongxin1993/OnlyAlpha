mod support;
use onlyalpha_event::*;
use std::{cell::RefCell, rc::Rc};
use support::*;
fn id(n: u64) -> OnlySubscriptionId {
    OnlySubscriptionId::parse(&format!("00000000-0000-0000-0000-{n:012x}")).unwrap()
}
#[test]
fn serial_snapshot_membership_and_new_publications_have_fixed_order() {
    let mut bus = OnlyEventBus::new(Default::default()).unwrap();
    let output = Rc::new(RefCell::new(Vec::new()));
    let a = output.clone();
    let once = Rc::new(RefCell::new(false));
    let registered = once.clone();
    bus.subscribe(
        id(1),
        OnlyEventType::new("FACT").unwrap(),
        "first",
        OnlyEventPriority::High,
        Box::new(move |event, context| {
            a.borrow_mut().push(format!("a{}", event.sequence()));
            if !*registered.borrow() {
                *registered.borrow_mut() = true;
                context.unsubscribe(id(2))?;
                let later = a.clone();
                context.subscribe(
                    id(3),
                    OnlyEventType::new("FACT").unwrap(),
                    "new",
                    OnlyEventPriority::Normal,
                    Box::new(move |e, _| {
                        later.borrow_mut().push(format!("c{}", e.sequence()));
                        Ok(())
                    }),
                )?;
                context.publish(support::event(3, OnlyEventPriority::Critical))?;
            }
            Ok(())
        }),
    )
    .unwrap();
    let b = output.clone();
    bus.subscribe(
        id(2),
        OnlyEventType::new("FACT").unwrap(),
        "second",
        OnlyEventPriority::Normal,
        Box::new(move |e, _| {
            b.borrow_mut().push(format!("b{}", e.sequence()));
            Ok(())
        }),
    )
    .unwrap();
    bus.publish_many(&[
        event(1, OnlyEventPriority::Low),
        event(2, OnlyEventPriority::High),
    ])
    .unwrap();
    bus.drain().unwrap();
    assert_eq!(*output.borrow(), ["a1", "b1", "a2", "c2", "a3", "c3"]);
}
#[test]
fn panic_and_error_are_distinct_and_do_not_stop_later_observers() {
    let mut bus = OnlyEventBus::new(Default::default()).unwrap();
    bus.subscribe(
        id(1),
        OnlyEventType::new("FACT").unwrap(),
        "error",
        OnlyEventPriority::Normal,
        Box::new(|_, _| Err(OnlyEventError::Callback("failure".into()))),
    )
    .unwrap();
    bus.subscribe(
        id(2),
        OnlyEventType::new("FACT").unwrap(),
        "panic",
        OnlyEventPriority::Normal,
        Box::new(|_, _| panic!("controlled panic")),
    )
    .unwrap();
    bus.subscribe(
        id(3),
        OnlyEventType::new("FACT").unwrap(),
        "ok",
        OnlyEventPriority::Normal,
        Box::new(|_, _| Ok(())),
    )
    .unwrap();
    bus.publish(event(1, OnlyEventPriority::Normal)).unwrap();
    let report = bus.dispatch_one().unwrap().unwrap();
    assert!(matches!(
        report.handler_results[0].outcome,
        OnlyEventHandlerOutcome::Error(_)
    ));
    assert!(matches!(
        report.handler_results[1].outcome,
        OnlyEventHandlerOutcome::Panic(_)
    ));
    assert_eq!(
        report.handler_results[2].outcome,
        OnlyEventHandlerOutcome::Succeeded
    );
}

struct PanickingDrop;
impl Drop for PanickingDrop {
    fn drop(&mut self) {
        panic!("capture destructor panic");
    }
}
#[test]
fn panic_payload_and_self_cancelled_capture_destructors_do_not_stop_observers() {
    let mut bus = OnlyEventBus::new(Default::default()).unwrap();
    bus.subscribe(
        id(1),
        OnlyEventType::new("FACT").unwrap(),
        "payload",
        OnlyEventPriority::Normal,
        Box::new(|_, _| std::panic::panic_any(PanickingDrop)),
    )
    .unwrap();
    let capture = PanickingDrop;
    bus.subscribe(
        id(2),
        OnlyEventType::new("FACT").unwrap(),
        "capture",
        OnlyEventPriority::Normal,
        Box::new(move |_, context| {
            let _ = &capture;
            context.unsubscribe(id(2))?;
            Ok(())
        }),
    )
    .unwrap();
    bus.subscribe(
        id(3),
        OnlyEventType::new("FACT").unwrap(),
        "later",
        OnlyEventPriority::Normal,
        Box::new(|_, _| Ok(())),
    )
    .unwrap();
    bus.publish(event(1, OnlyEventPriority::Normal)).unwrap();
    let report = bus.dispatch_one().unwrap().unwrap();
    assert_eq!(report.handler_results.len(), 3);
    assert!(matches!(
        report.handler_results[0].outcome,
        OnlyEventHandlerOutcome::Panic(_)
    ));
    assert!(matches!(
        report.handler_results[1].outcome,
        OnlyEventHandlerOutcome::Panic(_)
    ));
    assert_eq!(
        report.handler_results[2].outcome,
        OnlyEventHandlerOutcome::Succeeded
    );
    assert_eq!(bus.state().unwrap(), OnlyEventBusState::Running);
    assert_eq!(
        bus.diagnostics().unwrap().failures.total,
        num_bigint::BigUint::from(2u32)
    );
    bus.close().unwrap();
}
