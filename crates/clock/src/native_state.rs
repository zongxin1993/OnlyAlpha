//! Explicit sampled-time mechanics; contains no OS clock or waiting operations.
use crate::{CallbackFailure, ClockError, DispatchToken, OnlyTimerScheduler, TimerId, TimerState};
use num_bigint::BigInt;
use std::collections::BTreeMap;

pub(crate) struct NativeSchedule {
    pub(crate) scheduler: OnlyTimerScheduler,
    anchors: BTreeMap<TimerId, BigInt>,
    last_mono: Option<BigInt>,
}
impl NativeSchedule {
    pub(crate) fn new(wall: BigInt) -> Self {
        Self {
            scheduler: OnlyTimerScheduler::new(wall),
            anchors: BTreeMap::new(),
            last_mono: None,
        }
    }
    pub(crate) fn observe(&mut self, wall: BigInt, mono: &BigInt) -> Result<(), ClockError> {
        if mono < &BigInt::ZERO || self.last_mono.as_ref().is_some_and(|old| mono < old) {
            return Err(ClockError::Native(
                "monotonic source moved backwards".into(),
            ));
        }
        self.last_mono = Some(mono.clone());
        self.scheduler.current_ns = wall;
        Ok(())
    }
    pub(crate) fn arm(
        &mut self,
        id: TimerId,
        wall: &BigInt,
        mono: &BigInt,
    ) -> Result<(), ClockError> {
        let timer = self.scheduler.timer(id.as_str())?;
        self.anchors
            .insert(id, mono + (&timer.deadline_ns - wall).max(BigInt::ZERO));
        Ok(())
    }
    pub(crate) fn take_due(
        &mut self,
        wall: BigInt,
        mono: &BigInt,
    ) -> Result<Option<DispatchToken>, ClockError> {
        self.observe(wall.clone(), mono)?;
        // ponytail: scan active reservations; add an ordered wait index if measured Timer populations require it.
        let candidate = self
            .anchors
            .iter()
            .filter(|(_, anchor)| *anchor <= mono)
            .filter_map(|(id, _)| self.scheduler.timer(id.as_str()).ok())
            .filter(|timer| timer.state == TimerState::Scheduled)
            .min_by(|a, b| {
                (&a.deadline_ns, &a.sequence, &a.id).cmp(&(&b.deadline_ns, &b.sequence, &b.id))
            });
        candidate
            .map(|timer| self.scheduler.dispatch_id(&timer.id, wall))
            .transpose()
    }
    pub(crate) fn cancel(&mut self, id: &str) -> Result<bool, ClockError> {
        let changed = self.scheduler.cancel(id)?;
        if changed {
            self.anchors.remove(&id.parse()?);
        }
        Ok(changed)
    }
    pub(crate) fn remaining(&self, mono: &BigInt) -> Option<BigInt> {
        self.anchors
            .iter()
            .filter(|(id, _)| {
                self.scheduler
                    .timer(id.as_str())
                    .is_ok_and(|t| t.state == TimerState::Scheduled)
            })
            .map(|(_, anchor)| (anchor - mono).max(BigInt::ZERO))
            .min()
    }
    pub(crate) fn complete(
        &mut self,
        token: DispatchToken,
        result: Result<(), CallbackFailure>,
    ) -> Result<(), ClockError> {
        let id = token.event.id.clone();
        self.scheduler.complete_dispatch(token, result)?;
        let timer = self.scheduler.timer(id.as_str())?;
        if timer.state == TimerState::Scheduled {
            *self
                .anchors
                .get_mut(&id)
                .expect("dispatched Timer retains its wait anchor") +=
                timer.interval_ns.expect("periodic rearm interval");
        } else {
            self.anchors.remove(&id);
        }
        Ok(())
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn wall_jump_cannot_block_an_independently_monotonic_due_timer() {
        let mut state = NativeSchedule::new(1000.into());
        state.observe(1000.into(), &0.into()).unwrap();
        let first = state.scheduler.schedule_at("first", 1100.into()).unwrap();
        state.arm(first, &1000.into(), &0.into()).unwrap();
        // Wall clock jumps back. Earlier business deadline now has a later wait anchor.
        state.observe(0.into(), &10.into()).unwrap();
        let later = state.scheduler.schedule_at("later", 50.into()).unwrap();
        state.arm(later, &0.into(), &10.into()).unwrap();
        let token = state.take_due(60.into(), &60.into()).unwrap().unwrap();
        assert_eq!(token.event.id.as_str(), "later");
        state.complete(token, Ok(())).unwrap();
        assert!(state.take_due(70.into(), &70.into()).unwrap().is_none());
        assert_eq!(
            state
                .take_due(100.into(), &100.into())
                .unwrap()
                .unwrap()
                .event
                .id
                .as_str(),
            "first"
        );
    }
    #[test]
    fn sample_regression_is_rejected_without_state_change() {
        let mut state = NativeSchedule::new(100.into());
        state.observe(100.into(), &20.into()).unwrap();
        assert!(state.observe(99.into(), &19.into()).is_err());
        assert_eq!(state.scheduler.timestamp_ns(), 100.into());
    }
}
