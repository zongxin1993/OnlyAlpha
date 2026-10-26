//! A volatile input epoch, never a durable identity or Source grant.
use super::*;
use std::sync::Arc;
pub(super) struct TemporaryState {
    current: tokio::sync::watch::Sender<(u64, bool)>,
}
impl Default for TemporaryState {
    fn default() -> Self {
        Self {
            current: tokio::sync::watch::channel((0, true)).0,
        }
    }
}
#[derive(Clone)]
pub(super) struct TemporaryFence {
    state: Arc<TemporaryState>,
    generation: u64,
    lifetime: Option<Arc<TemporarySubscription>>,
}
impl TemporaryState {
    pub(super) fn fence(self: &Arc<Self>) -> TemporaryFence {
        TemporaryFence {
            state: Arc::clone(self),
            generation: self.current.borrow().0,
            lifetime: None,
        }
    }
    pub(super) fn invalidate(&self) -> Result<()> {
        let generation = self.current.borrow().0;
        let next = generation.checked_add(1);
        self.current
            .send_replace((next.unwrap_or(generation), false));
        next.map(|_| ()).ok_or(Error::Unavailable)
    }
    pub(super) fn reset(&self) -> Result<()> {
        let generation = self.current.borrow().0;
        if generation == u64::MAX {
            return Err(Error::Unavailable);
        }
        self.current.send_replace((generation, true));
        Ok(())
    }
}
impl TemporaryFence {
    /// A late failure can withdraw its original occurrence, never a replacement
    /// that has already been explicitly re-fetched at a newer epoch.
    pub(super) fn invalidate_context(&self) -> Result<()> {
        let mut exhausted = false;
        self.state.current.send_if_modified(|current| {
            if *current != (self.generation, true) {
                return false;
            }
            let next = current.0.checked_add(1);
            exhausted = next.is_none();
            *current = (next.unwrap_or(current.0), false);
            true
        });
        if exhausted {
            Err(Error::Unavailable)
        } else {
            Ok(())
        }
    }

    pub(super) fn for_subscription(mut self, lifetime: Arc<TemporarySubscription>) -> Self {
        self.lifetime = Some(lifetime);
        self
    }
    pub(super) fn check(&self) -> Result<()> {
        if self
            .lifetime
            .as_ref()
            .is_some_and(|active| !active.is_active())
        {
            return Err(Error::Source(SourceError::Stopped));
        }
        let current = *self.state.current.borrow();
        if current == (self.generation, true) {
            Ok(())
        } else {
            Err(Error::Conflict)
        }
    }
    pub(super) async fn invalidated(&self) {
        let mut receiver = self.state.current.subscribe();
        while self.check().is_ok() {
            tokio::select! {
                changed=receiver.changed()=>{if changed.is_err(){return;}},
                _=async{match &self.lifetime{Some(lifetime)=>lifetime.closed().await,None=>std::future::pending().await}}=>return,
            }
        }
    }
}
/// A single page subscription's lifetime, independent of its shared closed cache.
pub(super) struct TemporarySubscription {
    active: std::sync::atomic::AtomicBool,
    wake: tokio::sync::Notify,
}
impl Default for TemporarySubscription {
    fn default() -> Self {
        Self {
            active: std::sync::atomic::AtomicBool::new(true),
            wake: tokio::sync::Notify::new(),
        }
    }
}
impl TemporarySubscription {
    pub(super) fn is_active(&self) -> bool {
        self.active.load(std::sync::atomic::Ordering::Acquire)
    }
    pub(super) fn cancel(&self) {
        self.active
            .store(false, std::sync::atomic::Ordering::Release);
        self.wake.notify_waiters();
    }
    pub(super) async fn closed(&self) {
        let wake = self.wake.notified();
        if self.is_active() {
            wake.await;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        future::Future,
        task::{Context, Waker},
    };
    #[tokio::test(flavor = "current_thread")]
    async fn temporary_conflict_wakes_original_inputs_and_reset_cannot_reauthorize_them() {
        let state = Arc::new(TemporaryState::default());
        let original = state.fence();
        original.check().unwrap();
        let mut pending = Box::pin(original.invalidated());
        assert!(
            pending
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop()))
                .is_pending()
        );
        state.invalidate().unwrap();
        pending.await;
        assert!(original.check().is_err());
        state.reset().unwrap();
        assert!(original.check().is_err());
        let replacement = state.fence();
        original.invalidate_context().unwrap();
        replacement.check().unwrap();
    }
    #[test]
    fn temporary_epoch_exhaustion_withdraws_inputs_without_wrapping_or_reset() {
        let state = Arc::new(TemporaryState::default());
        state.current.send_replace((u64::MAX, true));
        let last = state.fence();
        assert!(state.invalidate().is_err());
        assert!(last.check().is_err());
        assert!(state.reset().is_err());
    }
}
