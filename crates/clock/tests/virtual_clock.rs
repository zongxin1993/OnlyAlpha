use onlyalpha_clock::{OnlyVirtualClock, TimerState};

#[test]
fn callback_scoped_queries_observe_deadline_without_owner_control() {
    let mut clock = OnlyVirtualClock::new(0.into());
    clock
        .schedule_at(
            "nested",
            1.into(),
            Box::new(|clock, _| {
                assert_eq!(clock.timestamp_ns()?, 1.into());
                Ok(())
            }),
        )
        .unwrap();
    let result = clock.advance_to(10.into()).unwrap();
    assert_eq!(result.current_ns, 10.into());
}

#[test]
fn restoring_malformed_state_is_atomic_and_retains_used_ids() {
    let mut clock = OnlyVirtualClock::new(0.into());
    clock
        .schedule_at("used", 1.into(), Box::new(|_, _| Ok(())))
        .unwrap();
    clock.advance_to(1.into()).unwrap();
    clock
        .schedule_at("active", 5.into(), Box::new(|_, _| Ok(())))
        .unwrap();
    let before = clock.snapshot().unwrap();
    let mut invalid = before.clone();
    invalid.current_ns = 500.into();
    assert!(clock.restore(invalid, Default::default()).is_err());
    assert_eq!(clock.snapshot().unwrap(), before);
    let handlers = [(
        "active".parse().unwrap(),
        Box::new(
            |_: &mut onlyalpha_clock::VirtualClockContext<'_>, _: &onlyalpha_clock::TimerEvent| {
                Ok(())
            },
        ) as onlyalpha_clock::VirtualCallback,
    )]
    .into();
    clock.restore(before, handlers).unwrap();
    assert_eq!(clock.timer("used").unwrap().state, TimerState::Completed);
    assert!(
        clock
            .schedule_at("used", 3.into(), Box::new(|_, _| Ok(())))
            .is_err()
    );
}

#[test]
fn callback_reentrancy_failure_and_close_have_explicit_results() {
    let mut clock = OnlyVirtualClock::new(0.into());
    clock
        .schedule_at(
            "first",
            1.into(),
            Box::new(|clock, _| {
                assert_eq!(clock.timer("first")?.state, TimerState::Firing);
                assert!(clock.cancel("cancel-me")?);
                clock.schedule_at("created", 1.into(), Box::new(|_, _| Ok(())))?;
                Ok(())
            }),
        )
        .unwrap();
    clock
        .schedule_at(
            "cancel-me",
            1.into(),
            Box::new(|_, _| panic!("must be cancelled")),
        )
        .unwrap();
    clock
        .schedule_every(
            "bad-periodic",
            1.into(),
            None,
            Box::new(|_, _| Err("boom".into())),
        )
        .unwrap();
    let result = clock.advance_to(2.into()).unwrap();
    assert_eq!(
        result
            .events
            .iter()
            .map(|e| e.id.as_str())
            .collect::<Vec<_>>(),
        vec!["first", "bad-periodic", "created"]
    );
    assert_eq!(result.failures.len(), 1);
    assert_eq!(
        clock.timer("bad-periodic").unwrap().state,
        TimerState::Failed
    );
    clock
        .schedule_at(
            "close",
            3.into(),
            Box::new(|clock, _| {
                clock.request_close()?;
                Ok(())
            }),
        )
        .unwrap();
    clock
        .schedule_at(
            "later",
            4.into(),
            Box::new(|_, _| panic!("must not dispatch after close")),
        )
        .unwrap();
    let result = clock.advance_to(10.into()).unwrap();
    assert_eq!(result.current_ns, 3.into());
    assert!(!result.reached_target);
    assert_eq!(clock.timer("later").unwrap().state, TimerState::Cancelled);
    clock.close().unwrap();
    assert!(
        clock
            .schedule_at("late", 11.into(), Box::new(|_, _| Ok(())))
            .is_err()
    );
}
#[test]
fn restricted_handles_and_views_observe_the_actual_clock() {
    let mut clock = OnlyVirtualClock::new(1.into());
    let view = clock.view();
    let handle = clock
        .schedule_after("timer", 2.into(), Box::new(|_, _| Ok(())))
        .unwrap();
    assert_eq!(view.timestamp_ns().unwrap(), 1.into());
    clock.advance_to(2.into()).unwrap();
    assert_eq!(view.timestamp_ns().unwrap(), 2.into());
    assert!(handle.cancel().unwrap());
    assert!(!handle.cancel().unwrap());
    assert_eq!(handle.snapshot().unwrap().state, TimerState::Cancelled);
}

#[test]
fn cancelling_handles_and_closing_release_callback_captures() {
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    struct Probe(Arc<AtomicUsize>);
    impl Drop for Probe {
        fn drop(&mut self) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }
    let dropped = Arc::new(AtomicUsize::new(0));
    let mut clock = OnlyVirtualClock::new(0.into());
    let probe = Probe(dropped.clone());
    let handle = clock
        .schedule_at(
            "cancel",
            10.into(),
            Box::new(move |_, _| {
                let _ = &probe;
                Ok(())
            }),
        )
        .unwrap();
    handle.cancel().unwrap();
    assert_eq!(dropped.load(Ordering::SeqCst), 1);
    let probe = Probe(dropped.clone());
    clock
        .schedule_at(
            "close",
            10.into(),
            Box::new(move |_, _| {
                let _ = &probe;
                Ok(())
            }),
        )
        .unwrap();
    clock.close().unwrap();
    assert_eq!(dropped.load(Ordering::SeqCst), 2);
}

#[test]
fn cross_thread_cancellation_during_callback_does_not_rearm_or_retain_capture() {
    use std::sync::{Arc, mpsc};
    use std::time::Duration;
    let (entered_tx, entered_rx) = mpsc::channel();
    let (cancelled_tx, cancelled_rx) = mpsc::channel();
    let capture = Arc::new(());
    let weak = Arc::downgrade(&capture);
    let mut clock = OnlyVirtualClock::new(0.into());
    let handle = clock
        .schedule_every(
            "periodic",
            10.into(),
            None,
            Box::new(move |_, _| {
                let _ = &capture;
                entered_tx.send(()).unwrap();
                cancelled_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                Ok(())
            }),
        )
        .unwrap();
    let cancel = std::thread::spawn(move || {
        entered_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        assert!(handle.cancel().unwrap());
        cancelled_tx.send(()).unwrap();
    });
    let result = clock.advance_to(100.into()).unwrap();
    cancel.join().unwrap();
    assert_eq!(result.events.len(), 1);
    assert_eq!(
        clock.timer("periodic").unwrap().state,
        TimerState::Cancelled
    );
    assert!(weak.upgrade().is_none());
}
