//! Linux native-time/lifecycle boundary; pure scheduling only receives explicit samples.
use crate::{
    ClockError, ClockState, ClockView, OnlyTimerScheduler, TimerEvent, TimerFailure, TimerHandle,
    TimerId, TimerSnapshot, native_state::NativeSchedule, virtual_clock::callback_result,
};
use num_bigint::BigInt;
use std::{
    collections::BTreeMap,
    panic::{AssertUnwindSafe, catch_unwind},
    sync::{Arc, Condvar, Mutex, MutexGuard},
    thread::{self, JoinHandle},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

pub type NativeCallback =
    Box<dyn FnMut(&TimerEvent, &LiveClockControl) -> Result<(), ClockError> + Send>;
struct NativeTime {
    origin: Instant,
}
impl NativeTime {
    fn sample(&self) -> (BigInt, BigInt) {
        let wall = match SystemTime::now().duration_since(UNIX_EPOCH) {
            Ok(value) => BigInt::from(value.as_nanos()),
            Err(error) => -BigInt::from(error.duration().as_nanos()),
        };
        (wall, BigInt::from(self.origin.elapsed().as_nanos()))
    }
}
struct NativeState {
    engine: NativeSchedule,
    callbacks: BTreeMap<TimerId, NativeCallback>,
    phase: ClockState,
    error: Option<String>,
}
struct Shared {
    state: Mutex<NativeState>,
    changed: Condvar,
    time: Arc<NativeTime>,
}
impl Shared {
    fn lock(&self) -> Result<MutexGuard<'_, NativeState>, ClockError> {
        self.state
            .lock()
            .map_err(|_| ClockError::Native("poisoned native Clock state".into()))
    }
}
#[derive(Clone)]
pub struct LiveClockControl {
    shared: Arc<Shared>,
}
impl LiveClockControl {
    pub fn view(&self) -> ClockView {
        let time = self.shared.time.clone();
        ClockView {
            read: Arc::new(move || Ok(time.sample())),
        }
    }
    pub fn state(&self) -> Result<ClockState, ClockError> {
        Ok(self.shared.lock()?.phase)
    }
    pub fn failures(&self) -> Result<Vec<TimerFailure>, ClockError> {
        Ok(self.shared.lock()?.engine.scheduler.failures().to_vec())
    }
    pub fn timer(&self, id: &str) -> Result<TimerSnapshot, ClockError> {
        self.shared.lock()?.engine.scheduler.timer(id)
    }
    pub fn cancel(&self, id: &str) -> Result<bool, ClockError> {
        let (changed, callback) = {
            let mut state = self.shared.lock()?;
            let changed = state.engine.cancel(id)?;
            let callback = if changed {
                state.callbacks.remove(&id.parse()?)
            } else {
                None
            };
            (changed, callback)
        };
        self.shared.changed.notify_all();
        drop(callback);
        Ok(changed)
    }
    pub fn request_close(&self) -> Result<(), ClockError> {
        let mut state = self.shared.lock()?;
        if state.phase == ClockState::Failed {
            return Err(ClockError::Native(state.error.clone().unwrap_or_default()));
        }
        if state.phase == ClockState::Running {
            state.phase = ClockState::Closing;
            state.engine.scheduler.close();
        }
        self.shared.changed.notify_all();
        Ok(())
    }
    pub fn schedule_at(
        &self,
        id: &str,
        deadline: BigInt,
        callback: NativeCallback,
    ) -> Result<TimerHandle, ClockError> {
        self.register(callback, |s| s.schedule_at(id, deadline))
    }
    pub fn schedule_after(
        &self,
        id: &str,
        delay: BigInt,
        callback: NativeCallback,
    ) -> Result<TimerHandle, ClockError> {
        self.register(callback, |s| s.schedule_after(id, delay))
    }
    pub fn schedule_every(
        &self,
        id: &str,
        interval: BigInt,
        start: Option<BigInt>,
        callback: NativeCallback,
    ) -> Result<TimerHandle, ClockError> {
        self.register(callback, |s| s.schedule_every(id, interval, start))
    }
    fn register(
        &self,
        callback: NativeCallback,
        register: impl FnOnce(&mut OnlyTimerScheduler) -> Result<TimerId, ClockError>,
    ) -> Result<TimerHandle, ClockError> {
        let mut state = self.shared.lock()?;
        if state.phase != ClockState::Running {
            return Err(ClockError::Closed);
        }
        let (wall, mono) = self.shared.time.sample();
        state.engine.observe(wall.clone(), &mono)?;
        let id = register(&mut state.engine.scheduler)?;
        state.engine.arm(id.clone(), &wall, &mono)?;
        state.callbacks.insert(id.clone(), callback);
        self.shared.changed.notify_all();
        drop(state);
        let cancel = self.clone();
        let inspect = self.clone();
        let cancel_id = id.clone();
        let inspect_id = id.clone();
        Ok(TimerHandle::new(
            id,
            move || cancel.cancel(cancel_id.as_str()),
            move || inspect.timer(inspect_id.as_str()),
        ))
    }
}
pub struct OnlyLiveClock {
    control: LiveClockControl,
    worker: Option<JoinHandle<()>>,
}
impl OnlyLiveClock {
    pub fn new() -> Result<Self, ClockError> {
        let time = Arc::new(NativeTime {
            origin: Instant::now(),
        });
        let (wall, _) = time.sample();
        let shared = Arc::new(Shared {
            state: Mutex::new(NativeState {
                engine: NativeSchedule::new(wall),
                callbacks: BTreeMap::new(),
                phase: ClockState::Running,
                error: None,
            }),
            changed: Condvar::new(),
            time,
        });
        let control = LiveClockControl { shared };
        let worker_control = control.clone();
        let worker = thread::Builder::new()
            .name("onlyalpha-clock".into())
            .spawn(move || {
                if let Err(error) = run(&worker_control) {
                    let callbacks = if let Ok(mut state) = worker_control.shared.lock() {
                        state.phase = ClockState::Failed;
                        state.error = Some(error.to_string());
                        state.engine.scheduler.close();
                        worker_control.shared.changed.notify_all();
                        std::mem::take(&mut state.callbacks)
                    } else {
                        BTreeMap::new()
                    };
                    drop(callbacks);
                }
            })
            .map_err(|e| ClockError::Native(e.to_string()))?;
        Ok(Self {
            control,
            worker: Some(worker),
        })
    }
    pub fn control(&self) -> LiveClockControl {
        self.control.clone()
    }
    pub fn view(&self) -> ClockView {
        self.control.view()
    }
    pub fn state(&self) -> Result<ClockState, ClockError> {
        self.control.state()
    }
    pub fn failures(&self) -> Result<Vec<TimerFailure>, ClockError> {
        self.control.failures()
    }
    pub fn schedule_at(
        &self,
        id: &str,
        deadline: BigInt,
        callback: NativeCallback,
    ) -> Result<TimerHandle, ClockError> {
        self.control.schedule_at(id, deadline, callback)
    }
    pub fn schedule_after(
        &self,
        id: &str,
        delay: BigInt,
        callback: NativeCallback,
    ) -> Result<TimerHandle, ClockError> {
        self.control.schedule_after(id, delay, callback)
    }
    pub fn schedule_every(
        &self,
        id: &str,
        interval: BigInt,
        start: Option<BigInt>,
        callback: NativeCallback,
    ) -> Result<TimerHandle, ClockError> {
        self.control.schedule_every(id, interval, start, callback)
    }
    pub fn close(&mut self) -> Result<ClockState, ClockError> {
        let requested = self.control.request_close();
        if self
            .worker
            .as_ref()
            .is_some_and(|worker| worker.thread().id() == thread::current().id())
        {
            requested?;
            return Ok(ClockState::Closing);
        }
        if let Some(worker) = self.worker.take()
            && worker.join().is_err()
        {
            let mut state = self.control.shared.lock()?;
            state.phase = ClockState::Failed;
            state.error = Some("native worker panicked".into());
            return Err(ClockError::Native("native worker panicked".into()));
        }
        requested?;
        let mut state = self.control.shared.lock()?;
        if state.phase == ClockState::Failed {
            return Err(ClockError::Native(state.error.clone().unwrap_or_default()));
        }
        state.phase = ClockState::Closed;
        Ok(state.phase)
    }
}
impl Drop for OnlyLiveClock {
    fn drop(&mut self) {
        let _ = self.close();
    }
}
fn run(control: &LiveClockControl) -> Result<(), ClockError> {
    let mut state = control.shared.lock()?;
    loop {
        if state.phase != ClockState::Running {
            let callbacks = std::mem::take(&mut state.callbacks);
            control.shared.changed.notify_all();
            drop(state);
            drop(callbacks);
            return Ok(());
        }
        let (wall, mono) = control.shared.time.sample();
        if let Some(token) = state.engine.take_due(wall, &mono)? {
            let event = token.event.clone();
            let mut callback = state
                .callbacks
                .remove(&event.id)
                .ok_or_else(|| ClockError::Native("missing native callback".into()))?;
            drop(state);
            let result =
                callback_result(catch_unwind(AssertUnwindSafe(|| callback(&event, control))));
            state = control.shared.lock()?;
            state.engine.complete(token, result)?;
            if state.phase == ClockState::Running
                && state.engine.scheduler.has_timer(event.id.as_str())
            {
                state.callbacks.insert(event.id, callback);
            } else {
                drop(state);
                drop(callback);
                state = control.shared.lock()?;
            }
            continue;
        }
        if let Some(remaining) = state.engine.remaining(&mono) {
            // Exact remaining-duration strategy: re-sample at most once per day for very distant anchors.
            // This caps only the OS wait chunk, never the business deadline or recurring interval.
            const MAX_WAIT_NS: u64 = 86_400_000_000_000;
            let nanos = u64::try_from(&remaining)
                .unwrap_or(MAX_WAIT_NS)
                .min(MAX_WAIT_NS);
            state = control
                .shared
                .changed
                .wait_timeout(state, Duration::from_nanos(nanos))
                .map_err(|_| ClockError::Native("poisoned native wait".into()))?
                .0;
        } else {
            state = control
                .shared
                .changed
                .wait(state)
                .map_err(|_| ClockError::Native("poisoned native wait".into()))?;
        }
    }
}
