use crate::{ClockError, TimerId, TimerSnapshot};
use num_bigint::BigInt;
use onlyalpha_domain::time::{OnlyTimestamp, OnlyUtcDateTime};
use std::sync::Arc;

/// Read capability only.
/// ```compile_fail
/// fn forbidden(view: onlyalpha_clock::ClockView) { view.close(); }
/// ```
/// ```compile_fail
/// fn forbidden(view: onlyalpha_clock::ClockView) { view.advance_to(1.into()); }
/// ```
#[derive(Clone)]
pub struct ClockView {
    pub(crate) read: Arc<dyn Fn() -> Result<(BigInt, BigInt), ClockError> + Send + Sync>,
}
impl ClockView {
    pub fn timestamp_ns(&self) -> Result<BigInt, ClockError> {
        Ok((self.read)()?.0)
    }
    pub fn monotonic_ns(&self) -> Result<BigInt, ClockError> {
        Ok((self.read)()?.1)
    }
    pub fn now_utc(&self) -> Result<OnlyUtcDateTime, ClockError> {
        OnlyTimestamp::from_unix_nanos(self.timestamp_ns()?)
            .to_datetime()
            .map_err(|e| ClockError::Validation(e.to_string()))
    }
}
#[derive(Clone)]
pub struct TimerHandle {
    id: TimerId,
    cancel: Arc<dyn Fn() -> Result<bool, ClockError> + Send + Sync>,
    inspect: Arc<dyn Fn() -> Result<TimerSnapshot, ClockError> + Send + Sync>,
}
impl TimerHandle {
    pub(crate) fn new(
        id: TimerId,
        cancel: impl Fn() -> Result<bool, ClockError> + Send + Sync + 'static,
        inspect: impl Fn() -> Result<TimerSnapshot, ClockError> + Send + Sync + 'static,
    ) -> Self {
        Self {
            id,
            cancel: Arc::new(cancel),
            inspect: Arc::new(inspect),
        }
    }
    pub fn id(&self) -> &TimerId {
        &self.id
    }
    pub fn cancel(&self) -> Result<bool, ClockError> {
        (self.cancel)()
    }
    pub fn snapshot(&self) -> Result<TimerSnapshot, ClockError> {
        (self.inspect)()
    }
}
