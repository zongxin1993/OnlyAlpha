//! Product node infrastructure primitives, separate from Trading Kernel semantics.
//! The pure lifecycle models legal states; it grants no production startup or
//! mutation capability. Actual Node composition must prove its required checks,
//! recovery, retained-work draining and physical mutation authority separately.
use std::fmt;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum State {
    #[default]
    Created,
    Booting,
    Verifying,
    Recovering,
    Ready,
    Draining,
    Stopped,
    Failed,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Phase {
    Booting,
    Verifying,
    Recovering,
    Ready,
    Draining,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    IllegalTransition,
    InvalidFailure,
    NotReady,
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::IllegalTransition => "PRODUCT_NODE_LIFECYCLE_TRANSITION_INVALID",
            Self::InvalidFailure => "PRODUCT_NODE_FAILURE_INVALID",
            Self::NotReady => "PRODUCT_NODE_NOT_READY",
        })
    }
}
impl std::error::Error for Error {}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Failure {
    phase: Phase,
    step: String,
    reason: String,
}
impl Failure {
    /// Compiled composition supplies nonsecret step/reason codes, never source
    /// text, SQL/driver errors, credentials or exception formatting.
    pub fn new(phase: Phase, step: &str, reason: &str) -> Result<Self, Error> {
        if step.is_empty() || reason.is_empty() {
            return Err(Error::InvalidFailure);
        }
        Ok(Self {
            phase,
            step: step.into(),
            reason: reason.into(),
        })
    }
    pub fn phase(&self) -> Phase {
        self.phase
    }
    pub fn step(&self) -> &str {
        &self.step
    }
    pub fn reason(&self) -> &str {
        &self.reason
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Status {
    state: State,
    failure: Option<Failure>,
}
impl Status {
    pub fn state(&self) -> State {
        self.state
    }
    pub fn failure(&self) -> Option<&Failure> {
        self.failure.as_ref()
    }
    pub fn live(&self) -> bool {
        self.state != State::Stopped
    }
    pub fn ready(&self) -> bool {
        self.state == State::Ready
    }
}
#[derive(Default)]
pub struct Lifecycle {
    state: State,
    failure: Option<Failure>,
}
impl Lifecycle {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn state(&self) -> State {
        self.state
    }
    pub fn status(&self) -> Status {
        Status {
            state: self.state,
            failure: self.failure.clone(),
        }
    }
    pub fn transition(&mut self, target: State) -> Result<(), Error> {
        if !matches!(
            (self.state, target),
            (State::Created, State::Booting)
                | (State::Booting, State::Verifying)
                | (State::Verifying, State::Recovering)
                | (State::Recovering, State::Ready)
                | (State::Ready, State::Draining)
                | (State::Draining, State::Stopped)
        ) {
            return Err(Error::IllegalTransition);
        }
        self.state = target;
        Ok(())
    }
    pub fn fail(&mut self, failure: Failure) -> Result<(), Error> {
        if !matches!(
            (self.state, failure.phase),
            (State::Booting, Phase::Booting)
                | (State::Verifying, Phase::Verifying | Phase::Recovering)
                | (State::Recovering, Phase::Recovering)
                | (State::Ready, Phase::Ready)
                | (State::Draining, Phase::Draining)
        ) {
            return Err(Error::IllegalTransition);
        }
        self.failure = Some(failure);
        self.state = State::Failed;
        Ok(())
    }
    /// Model check only. A real mutation also needs the owning Host's complete
    /// startup/recovery proof and its actual, retained PostgreSQL guard/session.
    pub fn assert_ready(&self) -> Result<(), Error> {
        if self.state == State::Ready {
            Ok(())
        } else {
            Err(Error::NotReady)
        }
    }
}
