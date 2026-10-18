use crate::{
    CallbackFailure, ClockError, ClockSnapshot, ClockState, TimerEvent, TimerFailure, TimerId,
    TimerMode, TimerSnapshot, TimerState,
};
use num_bigint::{BigInt, BigUint};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};

#[derive(Clone, Debug)]
pub struct DispatchToken {
    pub event: TimerEvent,
    owner: Arc<()>,
    nonce: BigUint,
}
pub struct OnlyTimerScheduler {
    pub(crate) current_ns: BigInt,
    sequence: BigUint,
    timers: BTreeMap<TimerId, TimerSnapshot>,
    pending: BTreeSet<(BigInt, BigUint, TimerId)>,
    failures: Vec<TimerFailure>,
    closed: bool,
    owner: Arc<()>,
    nonce: BigUint,
    outstanding: Option<DispatchToken>,
}
impl OnlyTimerScheduler {
    pub fn new(initial_ns: BigInt) -> Self {
        Self {
            current_ns: initial_ns,
            sequence: BigUint::ZERO,
            timers: BTreeMap::new(),
            pending: BTreeSet::new(),
            failures: Vec::new(),
            closed: false,
            owner: Arc::new(()),
            nonce: BigUint::ZERO,
            outstanding: None,
        }
    }
    pub fn state(&self) -> ClockState {
        if self.closed {
            ClockState::Closed
        } else {
            ClockState::Running
        }
    }
    pub fn timestamp_ns(&self) -> BigInt {
        self.current_ns.clone()
    }
    pub fn failures(&self) -> &[TimerFailure] {
        &self.failures
    }
    pub fn timer(&self, id: &str) -> Result<TimerSnapshot, ClockError> {
        self.timers
            .get(&TimerId::new(id)?)
            .cloned()
            .ok_or_else(|| ClockError::UnknownId(id.into()))
    }
    pub fn has_timer(&self, id: &str) -> bool {
        self.timer(id).is_ok_and(|timer| timer.state.is_active())
    }
    pub fn schedule_at(&mut self, id: &str, deadline: BigInt) -> Result<TimerId, ClockError> {
        self.register(id, deadline, TimerMode::OneShot, None)
    }
    pub fn schedule_after(&mut self, id: &str, delay: BigInt) -> Result<TimerId, ClockError> {
        if delay < BigInt::ZERO {
            return Err(ClockError::Validation("negative delay".into()));
        }
        self.schedule_at(id, &self.current_ns + delay)
    }
    pub fn schedule_every(
        &mut self,
        id: &str,
        interval: BigInt,
        start: Option<BigInt>,
    ) -> Result<TimerId, ClockError> {
        if interval <= BigInt::ZERO {
            return Err(ClockError::Validation("nonpositive interval".into()));
        }
        let deadline = start.unwrap_or_else(|| &self.current_ns + &interval);
        self.register(id, deadline, TimerMode::FixedRate, Some(interval))
    }
    fn register(
        &mut self,
        id: &str,
        deadline: BigInt,
        mode: TimerMode,
        interval: Option<BigInt>,
    ) -> Result<TimerId, ClockError> {
        if self.closed {
            return Err(ClockError::Closed);
        }
        let id = TimerId::new(id)?;
        if self.timers.contains_key(&id) {
            return Err(ClockError::DuplicateId(id.to_string()));
        }
        if deadline < self.current_ns {
            return Err(ClockError::Validation("past deadline".into()));
        }
        self.sequence += 1u32;
        self.pending
            .insert((deadline.clone(), self.sequence.clone(), id.clone()));
        self.timers.insert(
            id.clone(),
            TimerSnapshot {
                id: id.clone(),
                mode,
                state: TimerState::Scheduled,
                created_ns: self.current_ns.clone(),
                first_deadline_ns: deadline.clone(),
                deadline_ns: deadline,
                interval_ns: interval,
                sequence: self.sequence.clone(),
                fire_count: BigUint::ZERO,
                metadata: BTreeMap::new(),
            },
        );
        Ok(id)
    }
    pub fn cancel(&mut self, id: &str) -> Result<bool, ClockError> {
        let id = TimerId::new(id)?;
        if let Some(timer) = self.timers.get_mut(&id)
            && timer.state.is_active()
        {
            self.pending.remove(&(
                timer.deadline_ns.clone(),
                timer.sequence.clone(),
                timer.id.clone(),
            ));
            timer.state = TimerState::Cancelled;
            return Ok(true);
        }
        Ok(false)
    }
    pub fn dispatch_next(&mut self, target: &BigInt) -> Result<Option<DispatchToken>, ClockError> {
        self.require_dispatchable()?;
        let next = self
            .pending
            .first()
            .filter(|(deadline, _, _)| deadline <= target)
            .cloned();
        next.map(|(deadline, _, id)| self.dispatch_id(&id, deadline))
            .transpose()
    }
    pub(crate) fn dispatch_id(
        &mut self,
        id: &TimerId,
        fired_at: BigInt,
    ) -> Result<DispatchToken, ClockError> {
        self.require_dispatchable()?;
        let timer = self
            .timers
            .get_mut(id)
            .ok_or_else(|| ClockError::UnknownId(id.to_string()))?;
        if timer.state != TimerState::Scheduled {
            return Err(ClockError::StaleDispatch);
        }
        self.pending.remove(&(
            timer.deadline_ns.clone(),
            timer.sequence.clone(),
            id.clone(),
        ));
        timer.state = TimerState::Firing;
        timer.fire_count += 1u32;
        self.nonce += 1u32;
        self.current_ns = fired_at.clone();
        let token = DispatchToken {
            event: TimerEvent {
                id: id.clone(),
                deadline_ns: timer.deadline_ns.clone(),
                fired_at_ns: fired_at,
                sequence: timer.sequence.clone(),
                fire_count: timer.fire_count.clone(),
            },
            owner: self.owner.clone(),
            nonce: self.nonce.clone(),
        };
        self.outstanding = Some(token.clone());
        Ok(token)
    }
    pub fn complete_dispatch(
        &mut self,
        token: DispatchToken,
        result: Result<(), CallbackFailure>,
    ) -> Result<(), ClockError> {
        let valid = self.outstanding.as_ref().is_some_and(|actual| {
            Arc::ptr_eq(&token.owner, &self.owner)
                && token.nonce == actual.nonce
                && token.event == actual.event
        });
        if !valid {
            return Err(ClockError::StaleDispatch);
        }
        let timer = self
            .timers
            .get_mut(&token.event.id)
            .expect("outstanding Timer remains reserved");
        if let Err(failure) = result {
            self.failures.push(TimerFailure {
                event: token.event,
                failure,
            });
            if timer.state != TimerState::Cancelled {
                timer.state = TimerState::Failed;
            }
        } else if timer.state != TimerState::Cancelled {
            match timer.mode {
                TimerMode::OneShot => timer.state = TimerState::Completed,
                TimerMode::FixedRate => {
                    timer.deadline_ns += timer
                        .interval_ns
                        .as_ref()
                        .expect("validated fixed-rate interval");
                    timer.state = TimerState::Scheduled;
                    self.pending.insert((
                        timer.deadline_ns.clone(),
                        timer.sequence.clone(),
                        timer.id.clone(),
                    ));
                }
            }
        }
        self.outstanding = None;
        Ok(())
    }
    fn require_dispatchable(&self) -> Result<(), ClockError> {
        if self.closed {
            return Err(ClockError::Closed);
        }
        if self.outstanding.is_some() {
            return Err(ClockError::Busy);
        }
        Ok(())
    }
    pub fn close(&mut self) {
        self.closed = true;
        self.pending.clear();
        for timer in self.timers.values_mut() {
            if timer.state.is_active() {
                timer.state = TimerState::Cancelled;
            }
        }
    }
    pub fn snapshot(&self) -> Result<ClockSnapshot, ClockError> {
        if self.outstanding.is_some() {
            return Err(ClockError::Busy);
        }
        let mut timers: Vec<_> = self.timers.values().cloned().collect();
        timers.sort_by(|a, b| a.sequence.cmp(&b.sequence));
        Ok(ClockSnapshot {
            current_ns: self.current_ns.clone(),
            sequence: self.sequence.clone(),
            timers,
            failures: self.failures.clone(),
        })
    }
    pub(crate) fn active_ids(snapshot: &ClockSnapshot) -> std::collections::BTreeSet<TimerId> {
        snapshot
            .timers
            .iter()
            .filter(|t| t.state == TimerState::Scheduled)
            .map(|t| t.id.clone())
            .collect()
    }
    pub fn restore(&mut self, snapshot: ClockSnapshot) -> Result<(), ClockError> {
        self.require_dispatchable()?;
        let candidate = snapshot.validate()?;
        for (id, old) in &self.timers {
            let Some(new) = candidate.get(id) else {
                return Err(ClockError::InvalidSnapshot(
                    "restore releases reserved ID".into(),
                ));
            };
            if old.created_ns != new.created_ns
                || old.sequence != new.sequence
                || old.mode != new.mode
                || old.interval_ns != new.interval_ns
                || old.first_deadline_ns != new.first_deadline_ns
                || old.metadata != new.metadata
            {
                return Err(ClockError::InvalidSnapshot(
                    "restore redefines reserved Timer".into(),
                ));
            }
        }
        self.pending = candidate
            .values()
            .filter(|t| t.state == TimerState::Scheduled)
            .map(|t| (t.deadline_ns.clone(), t.sequence.clone(), t.id.clone()))
            .collect();
        self.current_ns = snapshot.current_ns;
        self.sequence = snapshot.sequence;
        self.timers = candidate;
        self.failures = snapshot.failures;
        self.owner = Arc::new(());
        Ok(())
    }
    pub(crate) fn is_fresh(&self) -> bool {
        self.timers.is_empty() && self.sequence == BigUint::ZERO
    }
}
