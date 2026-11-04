use onlyalpha_clock::{CallbackFailure, ClockError, OnlyTimerScheduler, TimerState};

#[test]
fn dispatch_completion_is_owner_bound_and_cannot_be_replayed() {
    let mut first = OnlyTimerScheduler::new(0.into());
    let mut second = OnlyTimerScheduler::new(0.into());
    first.schedule_at("same", 1.into()).unwrap();
    second.schedule_at("same", 1.into()).unwrap();
    let a = first.dispatch_next(&1.into()).unwrap().unwrap();
    let b = second.dispatch_next(&1.into()).unwrap().unwrap();
    let before = second.timer("same").unwrap();
    assert_eq!(
        second.complete_dispatch(a.clone(), Ok(())).unwrap_err(),
        ClockError::StaleDispatch
    );
    assert_eq!(second.timer("same").unwrap(), before);
    first.complete_dispatch(a.clone(), Ok(())).unwrap();
    assert_eq!(
        first.complete_dispatch(a, Ok(())).unwrap_err(),
        ClockError::StaleDispatch
    );
    second
        .complete_dispatch(b, Err(CallbackFailure::Error("boom".into())))
        .unwrap();
    assert_eq!(second.timer("same").unwrap().state, TimerState::Failed);
    assert_eq!(second.failures().len(), 1);
}
#[test]
fn invalid_registration_and_duplicate_ids_do_not_consume_sequence() {
    let mut scheduler = OnlyTimerScheduler::new(0.into());
    let before = scheduler.snapshot().unwrap();
    assert!(scheduler.schedule_every("bad", 0.into(), None).is_err());
    assert!(scheduler.schedule_at("past", (-1).into()).is_err());
    assert_eq!(scheduler.snapshot().unwrap(), before);
    scheduler.schedule_at("id", 1.into()).unwrap();
    let before = scheduler.snapshot().unwrap();
    assert!(scheduler.schedule_at("id", 2.into()).is_err());
    assert_eq!(scheduler.snapshot().unwrap(), before);
}
