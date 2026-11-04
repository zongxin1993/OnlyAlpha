use onlyalpha_clock::{OnlyVirtualClock, TimerEvent, TimerState, VirtualCallback};
use std::collections::BTreeMap;
fn handlers() -> BTreeMap<onlyalpha_clock::TimerId, VirtualCallback> {
    [(
        "periodic".parse().unwrap(),
        Box::new(|_: &mut onlyalpha_clock::VirtualClockContext<'_>, _: &TimerEvent| Ok(()))
            as VirtualCallback,
    )]
    .into()
}
#[test]
fn valid_restore_continues_exact_deadline_sequence_and_fire_count() {
    let mut original = OnlyVirtualClock::new(0.into());
    original
        .schedule_every("periodic", 10.into(), None, Box::new(|_, _| Ok(())))
        .unwrap();
    original.advance_to(10.into()).unwrap();
    let snapshot = original.snapshot().unwrap();
    let mut restored = OnlyVirtualClock::new(0.into());
    restored.restore_fresh(snapshot, handlers()).unwrap();
    assert_eq!(
        original.advance_to(30.into()).unwrap(),
        restored.advance_to(30.into()).unwrap()
    );
    assert_eq!(original.snapshot().unwrap(), restored.snapshot().unwrap());
}
#[test]
fn all_malformed_candidates_are_rejected_without_mutation() {
    let mut clock = OnlyVirtualClock::new(0.into());
    clock
        .schedule_every("periodic", 10.into(), None, Box::new(|_, _| Ok(())))
        .unwrap();
    let before = clock.snapshot().unwrap();
    let mut cases = Vec::new();
    let mut bad = before.clone();
    bad.timers.push(bad.timers[0].clone());
    cases.push(bad);
    let mut bad = before.clone();
    bad.timers[0].interval_ns = Some(0.into());
    cases.push(bad);
    let mut bad = before.clone();
    bad.timers[0].state = TimerState::Firing;
    cases.push(bad);
    let mut bad = before.clone();
    bad.current_ns = 11.into();
    cases.push(bad);
    let mut bad = before.clone();
    bad.sequence = 0u32.into();
    cases.push(bad);
    let mut bad = before.clone();
    bad.timers[0].state = TimerState::Completed;
    cases.push(bad);
    for candidate in cases {
        assert!(clock.restore(candidate, handlers()).is_err());
        assert_eq!(clock.snapshot().unwrap(), before);
    }
    assert!(clock.restore(before.clone(), Default::default()).is_err());
    assert_eq!(clock.snapshot().unwrap(), before);
}
#[test]
fn old_snapshot_cannot_release_lifetime_reservations() {
    let mut clock = OnlyVirtualClock::new(0.into());
    let old = clock.snapshot().unwrap();
    clock
        .schedule_at("later", 1.into(), Box::new(|_, _| Ok(())))
        .unwrap();
    clock.advance_to(1.into()).unwrap();
    let before = clock.snapshot().unwrap();
    assert!(clock.restore(old, Default::default()).is_err());
    assert_eq!(clock.snapshot().unwrap(), before);
}

#[test]
fn fresh_restore_rejects_missing_reservation_history() {
    let mut original = OnlyVirtualClock::new(0.into());
    original
        .schedule_at("used", 1.into(), Box::new(|_, _| Ok(())))
        .unwrap();
    original.advance_to(1.into()).unwrap();
    let mut snapshot = original.snapshot().unwrap();
    snapshot.timers.clear();
    let mut fresh = OnlyVirtualClock::new(0.into());
    let before = fresh.snapshot().unwrap();
    assert!(fresh.restore_fresh(snapshot, Default::default()).is_err());
    assert_eq!(fresh.snapshot().unwrap(), before);
}
#[test]
fn restore_rejects_impossible_fixed_rate_fire_count() {
    let mut original = OnlyVirtualClock::new(0.into());
    original
        .schedule_every("periodic", 10.into(), None, Box::new(|_, _| Ok(())))
        .unwrap();
    let before = original.snapshot().unwrap();
    let mut snapshot = before.clone();
    snapshot.timers[0].fire_count = 100u32.into();
    assert!(original.restore(snapshot, handlers()).is_err());
    assert_eq!(original.snapshot().unwrap(), before);
}

#[test]
fn restore_cannot_redefine_first_deadline_or_forge_earlier_failure() {
    let mut one = OnlyVirtualClock::new(0.into());
    one.schedule_at("one", 10.into(), Box::new(|_, _| Ok(())))
        .unwrap();
    let before = one.snapshot().unwrap();
    let mut bad = before.clone();
    bad.timers[0].first_deadline_ns = 100.into();
    bad.timers[0].deadline_ns = 100.into();
    let binding = [(
        "one".parse().unwrap(),
        Box::new(|_: &mut onlyalpha_clock::VirtualClockContext<'_>, _: &TimerEvent| Ok(()))
            as VirtualCallback,
    )]
    .into();
    assert!(one.restore(bad, binding).is_err());
    assert_eq!(one.snapshot().unwrap(), before);
    let mut periodic = OnlyVirtualClock::new(0.into());
    periodic
        .schedule_every(
            "periodic",
            10.into(),
            None,
            Box::new(|_, event| {
                if event.fire_count == 2u32.into() {
                    Err("controlled failure".into())
                } else {
                    Ok(())
                }
            }),
        )
        .unwrap();
    periodic.advance_to(20.into()).unwrap();
    let before = periodic.snapshot().unwrap();
    let mut bad = before.clone();
    bad.failures[0].event.fire_count = 1u32.into();
    bad.failures[0].event.deadline_ns = 10.into();
    assert!(periodic.restore(bad, Default::default()).is_err());
    assert_eq!(periodic.snapshot().unwrap(), before);
}

#[test]
fn cancelled_periodic_cannot_forge_failure_at_next_deadline() {
    let mut clock = OnlyVirtualClock::new(0.into());
    clock
        .schedule_every("periodic", 10.into(), None, Box::new(|_, _| Ok(())))
        .unwrap();
    clock.advance_to(10.into()).unwrap();
    clock.cancel("periodic").unwrap();
    clock.advance_to(20.into()).unwrap();
    let before = clock.snapshot().unwrap();
    let mut bad = before.clone();
    bad.failures.push(onlyalpha_clock::TimerFailure {
        event: onlyalpha_clock::TimerEvent {
            id: "periodic".parse().unwrap(),
            deadline_ns: 20.into(),
            fired_at_ns: 20.into(),
            sequence: 1u32.into(),
            fire_count: 1u32.into(),
        },
        failure: onlyalpha_clock::CallbackFailure::Error("forged".into()),
    });
    assert!(clock.restore(bad, Default::default()).is_err());
    assert_eq!(clock.snapshot().unwrap(), before);
}
