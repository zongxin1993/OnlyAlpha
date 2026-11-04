use crate::{ClockError, ClockSnapshot, TimerMode, TimerSnapshot, TimerState};
use num_bigint::{BigInt, BigUint};
use std::collections::{BTreeMap, BTreeSet};
impl ClockSnapshot {
    pub(crate) fn validate(&self) -> Result<BTreeMap<crate::TimerId, TimerSnapshot>, ClockError> {
        let bad = || ClockError::InvalidSnapshot("invalid Timer state or reservation".into());
        let mut timers = BTreeMap::new();
        let mut sequences = BTreeSet::new();
        let mut count = BigUint::ZERO;
        for timer in &self.timers {
            count += 1u32;
            if timer.sequence == BigUint::ZERO
                || timer.sequence > self.sequence
                || !sequences.insert(timer.sequence.clone())
                || timer.created_ns > self.current_ns
                || timer.first_deadline_ns < timer.created_ns
                || timer.deadline_ns < timer.first_deadline_ns
                || timer.state == TimerState::Firing
                || (timer.state == TimerState::Scheduled && timer.deadline_ns < self.current_ns)
            {
                return Err(bad());
            }
            match timer.mode {
                TimerMode::OneShot => {
                    if timer.interval_ns.is_some()
                        || timer.fire_count > BigUint::from(1u32)
                        || timer.deadline_ns != timer.first_deadline_ns
                        || (timer.state == TimerState::Completed
                            && timer.fire_count != BigUint::from(1u32))
                        || (timer.state == TimerState::Scheduled
                            && timer.fire_count != BigUint::ZERO)
                        || (timer.fire_count != BigUint::ZERO
                            && timer.deadline_ns > self.current_ns)
                    {
                        return Err(bad());
                    }
                }
                TimerMode::FixedRate => {
                    let interval = timer
                        .interval_ns
                        .as_ref()
                        .filter(|v| *v > &BigInt::ZERO)
                        .ok_or_else(bad)?;
                    if timer.state == TimerState::Completed {
                        return Err(bad());
                    }
                    let next = &timer.first_deadline_ns
                        + interval * BigInt::from(timer.fire_count.clone());
                    let last = if timer.fire_count == BigUint::ZERO {
                        None
                    } else {
                        Some(&next - interval)
                    };
                    if last.as_ref().is_some_and(|last| last > &self.current_ns) {
                        return Err(bad());
                    }
                    let valid = match timer.state {
                        TimerState::Scheduled => timer.deadline_ns == next,
                        TimerState::Failed => last.as_ref() == Some(&timer.deadline_ns),
                        TimerState::Cancelled => {
                            timer.deadline_ns == next || last.as_ref() == Some(&timer.deadline_ns)
                        }
                        _ => false,
                    };
                    if !valid {
                        return Err(bad());
                    }
                }
            }
            if timer.state == TimerState::Failed && timer.fire_count == BigUint::ZERO {
                return Err(bad());
            }
            if timers.insert(timer.id.clone(), timer.clone()).is_some() {
                return Err(bad());
            }
        }
        // All registrations remain represented, including terminal IDs. No gaps may hide forgotten identities.
        if count != self.sequence {
            return Err(bad());
        }
        let mut failed = BTreeSet::new();
        for failure in &self.failures {
            let timer = timers.get(&failure.event.id).ok_or_else(bad)?;
            let failure_deadline = match timer.mode {
                TimerMode::OneShot => timer.first_deadline_ns.clone(),
                TimerMode::FixedRate => {
                    &timer.first_deadline_ns
                        + timer.interval_ns.as_ref().ok_or_else(bad)?
                            * (BigInt::from(timer.fire_count.clone()) - 1u32)
                }
            };
            if failure.event.deadline_ns != failure_deadline
                || failure.event.sequence != timer.sequence
                || failure.event.fire_count == BigUint::ZERO
                || failure.event.fire_count != timer.fire_count
                || failure.event.deadline_ns != timer.deadline_ns
                || !failed.insert(failure.event.id.clone())
                || !matches!(timer.state, TimerState::Failed | TimerState::Cancelled)
            {
                return Err(bad());
            }
        }
        if timers
            .values()
            .any(|timer| timer.state == TimerState::Failed && !failed.contains(&timer.id))
        {
            return Err(bad());
        }
        Ok(timers)
    }
}
