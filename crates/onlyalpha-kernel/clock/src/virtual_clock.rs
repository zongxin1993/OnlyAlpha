use crate::{
    CallbackFailure, ClockError, ClockSnapshot, ClockState, ClockView, OnlyTimerScheduler,
    TimeAdvanceResult, TimerEvent, TimerFailure, TimerHandle, TimerId, TimerSnapshot,
};
use num_bigint::BigInt;
use std::{
    collections::BTreeMap,
    panic::{AssertUnwindSafe, catch_unwind},
    sync::{Arc, Mutex, MutexGuard},
};

/// Callback access must not permit replacing the owning Clock.
/// ```compile_fail
/// use onlyalpha_clock::{OnlyVirtualClock,VirtualCallback,ClockError,TimerEvent};
/// fn replace(clock:&mut OnlyVirtualClock,_:&TimerEvent)->Result<(),ClockError> {
///     *clock=OnlyVirtualClock::new(100.into());Ok(())
/// }
/// let _:VirtualCallback=Box::new(replace);
/// ```
/// ```compile_fail
/// let _:onlyalpha_clock::VirtualCallback=Box::new(|clock,_| {clock.advance_to(1.into())?;Ok(())});
/// ```
pub type VirtualCallback = Box<
    dyn for<'a> FnMut(&mut VirtualClockContext<'a>, &TimerEvent) -> Result<(), ClockError> + Send,
>;
/// Scoped callback capabilities; the owning Clock is deliberately inaccessible.
/// ```compile_fail
/// use onlyalpha_clock::{OnlyVirtualClock,VirtualCallback};
/// let snapshot=OnlyVirtualClock::new(0.into()).snapshot().unwrap();
/// let _:VirtualCallback=Box::new(move |clock,_| {clock.restore(snapshot.clone(),Default::default())?;Ok(())});
/// ```
pub struct VirtualClockContext<'a> {
    clock: &'a mut OnlyVirtualClock,
}
impl VirtualClockContext<'_> {
    pub fn timestamp_ns(&self) -> Result<BigInt, ClockError> {
        self.clock.timestamp_ns()
    }
    pub fn now_utc(&self) -> Result<onlyalpha_domain::time::OnlyUtcDateTime, ClockError> {
        self.clock.now_utc()
    }
    pub fn view(&self) -> ClockView {
        self.clock.view()
    }
    pub fn timer(&self, id: &str) -> Result<TimerSnapshot, ClockError> {
        self.clock.timer(id)
    }
    pub fn has_timer(&self, id: &str) -> Result<bool, ClockError> {
        self.clock.has_timer(id)
    }
    pub fn schedule_at(
        &mut self,
        id: &str,
        deadline: BigInt,
        callback: VirtualCallback,
    ) -> Result<TimerHandle, ClockError> {
        self.clock.schedule_at(id, deadline, callback)
    }
    pub fn schedule_after(
        &mut self,
        id: &str,
        delay: BigInt,
        callback: VirtualCallback,
    ) -> Result<TimerHandle, ClockError> {
        self.clock.schedule_after(id, delay, callback)
    }
    pub fn schedule_every(
        &mut self,
        id: &str,
        interval: BigInt,
        start: Option<BigInt>,
        callback: VirtualCallback,
    ) -> Result<TimerHandle, ClockError> {
        self.clock.schedule_every(id, interval, start, callback)
    }
    pub fn cancel(&mut self, id: &str) -> Result<bool, ClockError> {
        self.clock.cancel(id)
    }
    pub fn request_close(&mut self) -> Result<(), ClockError> {
        self.clock.close()
    }
}
type Callbacks = BTreeMap<TimerId, VirtualCallback>;
struct VirtualState {
    scheduler: OnlyTimerScheduler,
    callbacks: Callbacks,
}
pub struct OnlyVirtualClock {
    shared: Arc<Mutex<VirtualState>>,
    advancing: bool,
}
impl OnlyVirtualClock {
    pub fn new(initial_ns: BigInt) -> Self {
        Self {
            shared: Arc::new(Mutex::new(VirtualState {
                scheduler: OnlyTimerScheduler::new(initial_ns),
                callbacks: BTreeMap::new(),
            })),
            advancing: false,
        }
    }
    fn lock(&self) -> Result<MutexGuard<'_, VirtualState>, ClockError> {
        self.shared
            .lock()
            .map_err(|_| ClockError::Native("poisoned virtual Clock state".into()))
    }
    pub fn timestamp_ns(&self) -> Result<BigInt, ClockError> {
        Ok(self.lock()?.scheduler.timestamp_ns())
    }
    pub fn state(&self) -> Result<ClockState, ClockError> {
        Ok(self.lock()?.scheduler.state())
    }
    pub fn now_utc(&self) -> Result<onlyalpha_domain::time::OnlyUtcDateTime, ClockError> {
        self.view().now_utc()
    }
    pub fn view(&self) -> ClockView {
        let scheduler = self.shared.clone();
        ClockView {
            read: Arc::new(move || {
                let scheduler = scheduler
                    .lock()
                    .map_err(|_| ClockError::Native("poisoned Clock view".into()))?;
                let value = scheduler.scheduler.timestamp_ns();
                Ok((value.clone(), value))
            }),
        }
    }
    fn handle(&self, id: TimerId) -> TimerHandle {
        let cancel = self.shared.clone();
        let inspect = self.shared.clone();
        let cancel_id = id.clone();
        let inspect_id = id.clone();
        TimerHandle::new(
            id,
            move || {
                let (changed, callback) = {
                    let mut state = cancel
                        .lock()
                        .map_err(|_| ClockError::Native("poisoned Clock".into()))?;
                    let changed = state.scheduler.cancel(cancel_id.as_str())?;
                    let callback = if changed {
                        state.callbacks.remove(&cancel_id)
                    } else {
                        None
                    };
                    (changed, callback)
                };
                drop(callback);
                Ok(changed)
            },
            move || {
                inspect
                    .lock()
                    .map_err(|_| ClockError::Native("poisoned Clock".into()))?
                    .scheduler
                    .timer(inspect_id.as_str())
            },
        )
    }
    pub fn schedule_at(
        &mut self,
        id: &str,
        deadline: BigInt,
        callback: VirtualCallback,
    ) -> Result<TimerHandle, ClockError> {
        let mut state = self.lock()?;
        let id = state.scheduler.schedule_at(id, deadline)?;
        state.callbacks.insert(id.clone(), callback);
        drop(state);
        Ok(self.handle(id))
    }
    pub fn schedule_after(
        &mut self,
        id: &str,
        delay: BigInt,
        callback: VirtualCallback,
    ) -> Result<TimerHandle, ClockError> {
        let mut state = self.lock()?;
        let id = state.scheduler.schedule_after(id, delay)?;
        state.callbacks.insert(id.clone(), callback);
        drop(state);
        Ok(self.handle(id))
    }
    pub fn schedule_every(
        &mut self,
        id: &str,
        interval: BigInt,
        start: Option<BigInt>,
        callback: VirtualCallback,
    ) -> Result<TimerHandle, ClockError> {
        let mut state = self.lock()?;
        let id = state.scheduler.schedule_every(id, interval, start)?;
        state.callbacks.insert(id.clone(), callback);
        drop(state);
        Ok(self.handle(id))
    }
    pub fn cancel(&mut self, id: &str) -> Result<bool, ClockError> {
        self.handle(TimerId::new(id)?).cancel()
    }
    pub fn has_timer(&self, id: &str) -> Result<bool, ClockError> {
        Ok(self.lock()?.scheduler.has_timer(id))
    }
    pub fn timer(&self, id: &str) -> Result<TimerSnapshot, ClockError> {
        self.lock()?.scheduler.timer(id)
    }
    pub fn failures(&self) -> Result<Vec<TimerFailure>, ClockError> {
        Ok(self.lock()?.scheduler.failures().to_vec())
    }
    pub fn snapshot(&self) -> Result<ClockSnapshot, ClockError> {
        if self.advancing {
            return Err(ClockError::Busy);
        }
        self.lock()?.scheduler.snapshot()
    }
    pub fn restore(
        &mut self,
        snapshot: ClockSnapshot,
        callbacks: BTreeMap<TimerId, VirtualCallback>,
    ) -> Result<(), ClockError> {
        if self.advancing {
            return Err(ClockError::Busy);
        }
        let bindings = callbacks.keys().cloned().collect();
        if OnlyTimerScheduler::active_ids(&snapshot) != bindings {
            return Err(ClockError::InvalidSnapshot(
                "callback bindings differ".into(),
            ));
        }
        let old = {
            let mut current = self.lock()?;
            current.scheduler.restore(snapshot)?;
            std::mem::replace(&mut current.callbacks, callbacks)
        };
        drop(old);
        Ok(())
    }
    pub fn restore_fresh(
        &mut self,
        snapshot: ClockSnapshot,
        callbacks: BTreeMap<TimerId, VirtualCallback>,
    ) -> Result<(), ClockError> {
        if !self.lock()?.scheduler.is_fresh() {
            return Err(ClockError::InvalidSnapshot(
                "fresh restore requires unused Clock".into(),
            ));
        }
        self.restore(snapshot, callbacks)
    }
    pub fn close(&mut self) -> Result<(), ClockError> {
        let callbacks = {
            let mut state = self.lock()?;
            state.scheduler.close();
            std::mem::take(&mut state.callbacks)
        };
        drop(callbacks);
        Ok(())
    }
    pub fn advance_by(&mut self, delta: BigInt) -> Result<TimeAdvanceResult, ClockError> {
        if delta < BigInt::ZERO {
            return Err(ClockError::Validation("negative advancement".into()));
        }
        self.advance_to(self.timestamp_ns()? + delta)
    }
    pub fn advance_to(&mut self, target: BigInt) -> Result<TimeAdvanceResult, ClockError> {
        if self.advancing {
            return Err(ClockError::Busy);
        }
        if self.state()? != ClockState::Running {
            return Err(ClockError::Closed);
        }
        if target < self.timestamp_ns()? {
            return Err(ClockError::Validation("backward advancement".into()));
        }
        self.advancing = true;
        let result = self.advance_inner(target);
        self.advancing = false;
        result
    }
    fn advance_inner(&mut self, target: BigInt) -> Result<TimeAdvanceResult, ClockError> {
        let previous_ns = self.timestamp_ns()?;
        let start = self.lock()?.scheduler.failures().len();
        let mut events = Vec::new();
        while self.state()? == ClockState::Running {
            let claimed = {
                let mut state = self.lock()?;
                match state.scheduler.dispatch_next(&target)? {
                    Some(token) => {
                        let callback = state
                            .callbacks
                            .remove(&token.event.id)
                            .expect("registered Timer has a callback");
                        Some((token, callback))
                    }
                    None => {
                        state.scheduler.current_ns = target.clone();
                        None
                    }
                }
            };
            let Some((token, mut callback)) = claimed else {
                break;
            };
            let event = token.event.clone();
            let result = callback_result(catch_unwind(AssertUnwindSafe(|| {
                callback(&mut VirtualClockContext { clock: self }, &event)
            })));
            let mut retained = Some(callback);
            {
                let mut state = self.lock()?;
                state.scheduler.complete_dispatch(token, result)?;
                if state.scheduler.timer(event.id.as_str())?.state.is_active() {
                    state.callbacks.insert(
                        event.id.clone(),
                        retained.take().expect("callback owned by dispatch"),
                    );
                }
            }
            drop(retained);
            events.push(event);
        }
        let current_ns = self.timestamp_ns()?;
        let failures = self.lock()?.scheduler.failures()[start..].to_vec();
        Ok(TimeAdvanceResult {
            previous_ns,
            reached_target: current_ns == target,
            current_ns,
            events,
            failures,
        })
    }
}
type CallbackOutcome = Result<Result<(), ClockError>, Box<dyn std::any::Any + Send>>;
pub(crate) fn callback_result(result: CallbackOutcome) -> Result<(), CallbackFailure> {
    match result {
        Ok(Ok(())) => Ok(()),
        Ok(Err(error)) => Err(CallbackFailure::Error(error.to_string())),
        Err(_) => Err(CallbackFailure::Panic("callback panicked".into())),
    }
}

impl Drop for OnlyVirtualClock {
    fn drop(&mut self) {
        let _ = self.close();
    }
}
