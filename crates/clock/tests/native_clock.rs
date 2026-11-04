use onlyalpha_clock::{ClockState, OnlyLiveClock};
use std::{sync::mpsc, thread, time::Duration};
const WATCHDOG: Duration = Duration::from_secs(5);
#[test]
fn native_callbacks_reenter_cancel_fail_and_request_close_without_self_join() {
    let mut clock = OnlyLiveClock::new().unwrap();
    let (tx, rx) = mpsc::channel();
    clock
        .schedule_after("bad", 0.into(), Box::new(|_, _| panic!("controlled panic")))
        .unwrap();
    clock
        .schedule_after(
            "good",
            0.into(),
            Box::new(move |event, control| {
                let id = event.id.to_string();
                let tx = tx.clone();
                control.schedule_after(
                    "nested",
                    0.into(),
                    Box::new(move |_, control| {
                        tx.send((id.clone(), thread::current().id())).unwrap();
                        control.request_close()?;
                        Ok(())
                    }),
                )?;
                Ok(())
            }),
        )
        .unwrap();
    assert_eq!(rx.recv_timeout(WATCHDOG).unwrap().0, "good");
    clock.close().unwrap();
    assert_eq!(clock.state().unwrap(), ClockState::Closed);
    assert_eq!(clock.failures().unwrap().len(), 1);
    assert!(
        clock
            .schedule_after("late", 0.into(), Box::new(|_, _| Ok(())))
            .is_err()
    );
    clock.close().unwrap();
    assert!(clock.view().timestamp_ns().is_ok());
}
#[test]
fn external_close_is_quiescent_and_keeps_closing_visible_until_callback_returns() {
    let mut clock = OnlyLiveClock::new().unwrap();
    let control = clock.control();
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    clock
        .schedule_after(
            "blocked",
            0.into(),
            Box::new(move |_, _| {
                entered_tx.send(()).unwrap();
                release_rx.recv().unwrap();
                Ok(())
            }),
        )
        .unwrap();
    entered_rx.recv_timeout(WATCHDOG).unwrap();
    control.request_close().unwrap();
    assert_eq!(control.state().unwrap(), ClockState::Closing);
    let join = thread::spawn(move || {
        clock.close().unwrap();
        clock.state().unwrap()
    });
    release_tx.send(()).unwrap();
    assert_eq!(join.join().unwrap(), ClockState::Closed);
}
#[test]
fn native_registration_and_cancellation_use_one_worker() {
    let mut clock = OnlyLiveClock::new().unwrap();
    let (tx, rx) = mpsc::channel();
    let mut workers = Vec::new();
    for index in 0..4 {
        let control = clock.control();
        let tx = tx.clone();
        workers.push(thread::spawn(move || {
            control
                .schedule_after(
                    &format!("timer-{index}"),
                    0.into(),
                    Box::new(move |_, _| {
                        tx.send(thread::current().id()).unwrap();
                        Ok(())
                    }),
                )
                .unwrap();
        }));
    }
    for worker in workers {
        worker.join().unwrap();
    }
    let first = rx.recv_timeout(WATCHDOG).unwrap();
    for _ in 0..3 {
        assert_eq!(rx.recv_timeout(WATCHDOG).unwrap(), first);
    }
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    clock
        .schedule_after(
            "barrier",
            0.into(),
            Box::new(move |_, _| {
                entered_tx.send(()).unwrap();
                release_rx.recv().unwrap();
                Ok(())
            }),
        )
        .unwrap();
    entered_rx.recv_timeout(WATCHDOG).unwrap();
    let handle = clock
        .schedule_after("cancel", 0.into(), Box::new(|_, _| panic!("cancelled")))
        .unwrap();
    let cancelled = handle.cancel().unwrap();
    release_tx.send(()).unwrap();
    clock.close().unwrap();
    assert!(cancelled);
}

#[test]
fn native_cancel_releases_captures_before_clock_shutdown() {
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
    let count = Arc::new(AtomicUsize::new(0));
    let mut clock = OnlyLiveClock::new().unwrap();
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    clock
        .schedule_after(
            "barrier",
            0.into(),
            Box::new(move |_, _| {
                entered_tx.send(()).unwrap();
                release_rx.recv().unwrap();
                Ok(())
            }),
        )
        .unwrap();
    entered_rx.recv_timeout(WATCHDOG).unwrap();
    let probe = Probe(count.clone());
    let handle = clock
        .schedule_after(
            "cancel",
            0.into(),
            Box::new(move |_, _| {
                let _ = &probe;
                Ok(())
            }),
        )
        .unwrap();
    handle.cancel().unwrap();
    let released = count.load(Ordering::SeqCst);
    release_tx.send(()).unwrap();
    clock.close().unwrap();
    assert_eq!(released, 1);
}
