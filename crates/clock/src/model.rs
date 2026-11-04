use num_bigint::{BigInt, BigUint};
use std::{collections::BTreeMap, fmt, str::FromStr};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ClockError {
    Validation(String),
    Closed,
    Busy,
    DuplicateId(String),
    UnknownId(String),
    InvalidSnapshot(String),
    StaleDispatch,
    Native(String),
    Callback(String),
}
impl fmt::Display for ClockError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for ClockError {}
impl From<&str> for ClockError {
    fn from(value: &str) -> Self {
        Self::Callback(value.into())
    }
}
impl From<String> for ClockError {
    fn from(value: String) -> Self {
        Self::Callback(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct TimerId(String);
impl TimerId {
    pub fn new(value: &str) -> Result<Self, ClockError> {
        // Match the canonical reference's Unicode whitespace, including C0 separators.
        let value = value
            .trim_matches(|c: char| c.is_whitespace() || ('\u{001c}'..='\u{001f}').contains(&c));
        if value.is_empty() {
            return Err(ClockError::Validation("empty Timer ID".into()));
        }
        Ok(Self(value.into()))
    }
    pub fn as_str(&self) -> &str {
        &self.0
    }
}
impl FromStr for TimerId {
    type Err = ClockError;
    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}
impl fmt::Display for TimerId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ClockState {
    Running,
    Closing,
    Closed,
    Failed,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TimerMode {
    OneShot,
    FixedRate,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TimerState {
    Scheduled,
    Firing,
    Cancelled,
    Completed,
    Failed,
}
impl TimerState {
    pub fn is_active(self) -> bool {
        matches!(self, Self::Scheduled | Self::Firing)
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TimerSnapshot {
    pub id: TimerId,
    pub mode: TimerMode,
    pub state: TimerState,
    pub created_ns: BigInt,
    pub first_deadline_ns: BigInt,
    pub deadline_ns: BigInt,
    pub interval_ns: Option<BigInt>,
    pub sequence: BigUint,
    pub fire_count: BigUint,
    pub metadata: BTreeMap<String, String>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TimerEvent {
    pub id: TimerId,
    pub deadline_ns: BigInt,
    pub fired_at_ns: BigInt,
    pub sequence: BigUint,
    pub fire_count: BigUint,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CallbackFailure {
    Error(String),
    Panic(String),
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TimerFailure {
    pub event: TimerEvent,
    pub failure: CallbackFailure,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ClockSnapshot {
    pub current_ns: BigInt,
    pub sequence: BigUint,
    /// Includes terminal records: these are the sole lifetime-ID reservation authority.
    pub timers: Vec<TimerSnapshot>,
    pub failures: Vec<TimerFailure>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TimeAdvanceResult {
    pub previous_ns: BigInt,
    pub current_ns: BigInt,
    pub reached_target: bool,
    pub events: Vec<TimerEvent>,
    pub failures: Vec<TimerFailure>,
}
