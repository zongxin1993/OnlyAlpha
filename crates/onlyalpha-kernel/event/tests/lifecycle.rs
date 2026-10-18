mod support;
use onlyalpha_event::*;
use std::{cell::RefCell, rc::Rc};
use support::*;
fn id(n: u64) -> OnlySubscriptionId {
    OnlySubscriptionId::parse(&format!("00000000-0000-0000-0000-{n:012x}")).unwrap()
}
#[test]
fn callback_close_drains_accepted_facts_before_closed() {
    let mut bus = OnlyEventBus::new(Default::default()).unwrap();
    let output = Rc::new(RefCell::new(Vec::new()));
    let log = output.clone();
    bus.subscribe(
        id(1),
        OnlyEventType::new("FACT").unwrap(),
        "close",
        OnlyEventPriority::Normal,
        Box::new(move |e, c| {
            log.borrow_mut().push(e.sequence().to_string());
            c.request_close()?;
            assert!(c.publish(event(3, OnlyEventPriority::Normal)).is_err());
            Ok(())
        }),
    )
    .unwrap();
    bus.publish_many(&[
        event(1, OnlyEventPriority::Normal),
        event(2, OnlyEventPriority::Normal),
    ])
    .unwrap();
    bus.dispatch_one().unwrap();
    assert_eq!(bus.state().unwrap(), OnlyEventBusState::Closing);
    assert_eq!(bus.pending_count().unwrap(), 1);
    assert_eq!(*output.borrow(), ["1"]);
    assert_eq!(bus.close().unwrap(), OnlyEventBusState::Closed);
    assert_eq!(*output.borrow(), ["1", "2"]);
    assert_eq!(bus.close().unwrap(), OnlyEventBusState::Closed);
    assert!(bus.publish(event(3, OnlyEventPriority::Normal)).is_err());
}
#[test]
fn dropping_owner_releases_cyclic_callback_and_exposes_unfinished_state() {
    let mut bus = OnlyEventBus::new(Default::default()).unwrap();
    let view = bus.view();
    let captured = view.clone();
    let token = Rc::new(());
    let weak = Rc::downgrade(&token);
    bus.subscribe(
        id(1),
        OnlyEventType::new("FACT").unwrap(),
        "cycle",
        OnlyEventPriority::Normal,
        Box::new(move |_, _| {
            let _ = (&captured, &token);
            Ok(())
        }),
    )
    .unwrap();
    bus.publish(event(1, OnlyEventPriority::Normal)).unwrap();
    drop(bus);
    assert_eq!(view.state().unwrap(), OnlyEventBusState::Failed);
    assert!(weak.upgrade().is_none());
    assert_eq!(
        view.diagnostics().unwrap().abandoned_pending.to_string(),
        "1"
    );
}
#[test]
fn duplicate_and_invalid_subscriptions_do_not_consume_sequence() {
    let mut bus = OnlyEventBus::new(Default::default()).unwrap();
    let ty = OnlyEventType::new("FACT").unwrap();
    assert!(
        bus.subscribe(
            id(1),
            ty.clone(),
            "",
            OnlyEventPriority::Normal,
            Box::new(|_, _| Ok(()))
        )
        .is_err()
    );
    let first = bus
        .subscribe(
            id(1),
            ty.clone(),
            "first",
            OnlyEventPriority::Normal,
            Box::new(|_, _| Ok(())),
        )
        .unwrap();
    assert_eq!(first.subscription().registration_sequence.to_string(), "1");
    first.cancel().unwrap();
    assert!(
        bus.subscribe(
            id(1),
            ty.clone(),
            "again",
            OnlyEventPriority::Normal,
            Box::new(|_, _| Ok(()))
        )
        .is_err()
    );
    let second = bus
        .subscribe(
            id(2),
            ty,
            "second",
            OnlyEventPriority::Normal,
            Box::new(|_, _| Ok(())),
        )
        .unwrap();
    assert_eq!(second.subscription().registration_sequence.to_string(), "2");
}
