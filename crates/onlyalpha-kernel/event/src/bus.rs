use crate::*;
use num_bigint::BigUint;
use std::{
    cell::{RefCell, RefMut},
    collections::{BTreeMap, BTreeSet, VecDeque},
    rc::Rc,
    sync::Arc,
};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OnlyEventQueuePolicy {
    Reject,
    FailRuntime,
    DropLowPriority,
}
#[derive(Clone, Debug)]
pub struct OnlyEventBusConfig {
    pub capacity: usize,
    pub diagnostic_capacity: usize,
    pub scope: Option<OnlyEventScope>,
    pub queue_policy: OnlyEventQueuePolicy,
}
impl Default for OnlyEventBusConfig {
    fn default() -> Self {
        Self {
            capacity: 1024,
            diagnostic_capacity: 1024,
            scope: None,
            queue_policy: OnlyEventQueuePolicy::Reject,
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyEventEnqueueReceipt {
    pub accepted: Arc<OnlyEvent>,
    pub replaced: Option<Arc<OnlyEvent>>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyEventBatchFailure {
    pub accepted: BigUint,
    pub rejected_index: usize,
    pub cause: OnlyEventError,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OnlyEventBusState {
    Running,
    Closing,
    Closed,
    Failed,
}
#[derive(Clone)]
pub(crate) struct RegisteredHandler {
    pub(crate) subscription: OnlySubscription,
    pub(crate) handler: Rc<RefCell<OnlyEventHandler>>,
}
pub(crate) struct State {
    pub(crate) diagnostics: crate::diagnostics::Diagnostics,
    pub(crate) handlers: BTreeMap<OnlySubscriptionId, RegisteredHandler>,
    pub(crate) used_ids: BTreeSet<OnlySubscriptionId>,
    pub(crate) sequence: BigUint,
    pub(crate) dispatching: bool,
    pub(crate) phase: OnlyEventBusState,
    pub(crate) config: OnlyEventBusConfig,
    pub(crate) queue: VecDeque<Arc<OnlyEvent>>,
}
pub struct OnlyEventBus {
    pub(crate) shared: Rc<RefCell<State>>,
}
pub(crate) fn borrow(shared: &Rc<RefCell<State>>) -> Result<RefMut<'_, State>, OnlyEventError> {
    shared.try_borrow_mut().map_err(|_| OnlyEventError::Busy)
}
impl OnlyEventBus {
    pub fn new(config: OnlyEventBusConfig) -> Result<Self, OnlyEventError> {
        if config.capacity == 0 || config.diagnostic_capacity == 0 {
            return Err(crate::model::invalid("capacities must be positive"));
        }
        Ok(Self {
            shared: Rc::new(RefCell::new(State {
                diagnostics: crate::diagnostics::Diagnostics::new(config.diagnostic_capacity),
                handlers: BTreeMap::new(),
                used_ids: BTreeSet::new(),
                sequence: BigUint::ZERO,
                dispatching: false,
                phase: OnlyEventBusState::Running,
                config,
                queue: VecDeque::new(),
            })),
        })
    }
    pub fn publish(
        &mut self,
        event: Arc<OnlyEvent>,
    ) -> Result<OnlyEventEnqueueReceipt, OnlyEventError> {
        enqueue(&self.shared, event)
    }
    pub fn publish_many(
        &mut self,
        events: &[Arc<OnlyEvent>],
    ) -> Result<BigUint, OnlyEventBatchFailure> {
        for (index, event) in events.iter().enumerate() {
            self.publish(event.clone())
                .map_err(|cause| OnlyEventBatchFailure {
                    accepted: index.into(),
                    rejected_index: index,
                    cause,
                })?;
        }
        Ok(events.len().into())
    }
    pub fn publish_many_atomic(
        &mut self,
        events: &[Arc<OnlyEvent>],
    ) -> Result<BigUint, OnlyEventError> {
        let mut state = borrow(&self.shared)?;
        require_running(&state)?;
        if state.config.queue_policy == OnlyEventQueuePolicy::DropLowPriority {
            return Err(crate::model::invalid("atomic replacement unsupported"));
        }
        for event in events {
            require_scope(&state, event)?;
        }
        if events.len() > state.config.capacity - state.queue.len() {
            return Err(capacity_error(&state));
        }
        state.queue.extend(events.iter().cloned());
        Ok(events.len().into())
    }
    pub fn pending_count(&self) -> Result<usize, OnlyEventError> {
        Ok(borrow(&self.shared)?.queue.len())
    }
}
fn require_scope(state: &State, event: &OnlyEvent) -> Result<(), OnlyEventError> {
    if state
        .config
        .scope
        .as_ref()
        .is_some_and(|scope| !scope.includes(event.scope()))
    {
        return Err(OnlyEventError::Scope);
    }
    Ok(())
}
fn capacity_error(state: &State) -> OnlyEventError {
    if state.config.queue_policy == OnlyEventQueuePolicy::FailRuntime {
        OnlyEventError::RuntimeFailure
    } else {
        OnlyEventError::Capacity
    }
}
pub(crate) fn enqueue(
    shared: &Rc<RefCell<State>>,
    event: Arc<OnlyEvent>,
) -> Result<OnlyEventEnqueueReceipt, OnlyEventError> {
    let mut state = borrow(shared)?;
    require_running(&state)?;
    require_scope(&state, &event)?;
    let mut replaced = None;
    if state.queue.len() == state.config.capacity {
        if state.config.queue_policy != OnlyEventQueuePolicy::DropLowPriority {
            return Err(capacity_error(&state));
        }
        let index = state
            .queue
            .iter()
            .enumerate()
            .filter(|(_, old)| old.priority() < event.priority())
            .min_by_key(|(i, old)| (old.priority(), *i))
            .map(|(i, _)| i)
            .ok_or_else(|| capacity_error(&state))?;
        replaced = state.queue.remove(index);
    }
    state.queue.push_back(event.clone());
    let receipt = OnlyEventEnqueueReceipt {
        accepted: event,
        replaced,
    };
    if receipt.replaced.is_some() {
        state.diagnostics.replacement(receipt.clone());
    }
    Ok(receipt)
}

pub(crate) fn require_running(state: &State) -> Result<(), OnlyEventError> {
    if state.phase != OnlyEventBusState::Running {
        Err(OnlyEventError::Closed)
    } else {
        Ok(())
    }
}
struct DispatchGuard {
    shared: Rc<RefCell<State>>,
    completed: bool,
}
impl Drop for DispatchGuard {
    fn drop(&mut self) {
        if !self.completed
            && let Ok(mut state) = self.shared.try_borrow_mut()
        {
            state.dispatching = false;
            state.phase = OnlyEventBusState::Failed;
        }
    }
}
impl OnlyEventBus {
    pub fn view(&self) -> OnlyEventBusSubscriptionView {
        OnlyEventBusSubscriptionView {
            shared: self.shared.clone(),
        }
    }
    pub fn state(&self) -> Result<OnlyEventBusState, OnlyEventError> {
        Ok(borrow(&self.shared)?.phase)
    }
    pub fn subscribe(
        &mut self,
        id: OnlySubscriptionId,
        event_type: OnlyEventType,
        handler_name: &str,
        priority: OnlyEventPriority,
        handler: OnlyEventHandler,
    ) -> Result<OnlySubscriptionHandle, OnlyEventError> {
        register(
            &self.shared,
            id,
            event_type,
            handler_name,
            priority,
            handler,
        )
    }
    pub fn unsubscribe(&mut self, id: OnlySubscriptionId) -> Result<bool, OnlyEventError> {
        unsubscribe(&self.shared, id)
    }
    pub fn dispatch_one(&mut self) -> Result<Option<OnlyEventDispatchReport>, OnlyEventError> {
        let (event, mut handlers) = {
            let mut state = borrow(&self.shared)?;
            if state.dispatching {
                return Err(OnlyEventError::Busy);
            }
            if state.phase == OnlyEventBusState::Failed {
                return Err(OnlyEventError::Closed);
            }
            let Some(event) = state.queue.pop_front() else {
                return Ok(None);
            };
            let handlers = state
                .handlers
                .values()
                .filter(|h| h.subscription.event_type == *event.event_type())
                .cloned()
                .collect::<Vec<_>>();
            state.dispatching = true;
            (event, handlers)
        };
        let mut guard = DispatchGuard {
            shared: self.shared.clone(),
            completed: false,
        };
        handlers.sort_by(|a, b| {
            b.subscription.priority.cmp(&a.subscription.priority).then(
                a.subscription
                    .registration_sequence
                    .cmp(&b.subscription.registration_sequence),
            )
        });
        let mut handler_results = Vec::new();
        for registered in handlers {
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                let mut handler = registered
                    .handler
                    .try_borrow_mut()
                    .map_err(|_| OnlyEventError::Busy)?;
                handler(
                    &event,
                    &mut OnlyEventCallbackContext {
                        shared: &self.shared,
                    },
                )
            }));
            let outcome = match result {
                Ok(Ok(())) => OnlyEventHandlerOutcome::Succeeded,
                Ok(Err(e)) => OnlyEventHandlerOutcome::Error(e.to_string()),
                Err(payload) => OnlyEventHandlerOutcome::Panic(consume_panic(payload)),
            };
            // A cancelled observer may own the final callback reference. Release it
            // separately, after the callback has stopped unwinding and outside State.
            let outcome = match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                drop(registered.handler);
            })) {
                Ok(()) => outcome,
                Err(payload) => OnlyEventHandlerOutcome::Panic(format!(
                    "{outcome:?}; callback capture destructor: {}",
                    consume_panic(payload)
                )),
            };
            handler_results.push(OnlyEventHandlerResult {
                subscription: registered.subscription,
                outcome,
            });
        }
        let report = OnlyEventDispatchReport {
            event,
            handler_results,
        };
        {
            let mut state = borrow(&self.shared)?;
            state.dispatching = false;
            state.diagnostics.dispatch(report.clone());
        }
        finish_closing(&self.shared)?;
        guard.completed = true;
        Ok(Some(report))
    }
    pub fn drain(&mut self) -> Result<BigUint, OnlyEventError> {
        let mut count = BigUint::ZERO;
        while self.dispatch_one()?.is_some() {
            count += 1u32;
        }
        Ok(count)
    }
}

// Panic payloads are user-owned values too: their destructors may panic.
// Dispose each payload under its own unwind boundary without leaking it or
// unwinding through the remaining observer snapshot. No callback is retried.
fn consume_panic(mut payload: Box<dyn std::any::Any + Send>) -> String {
    let mut message = payload
        .downcast_ref::<String>()
        .cloned()
        .or_else(|| payload.downcast_ref::<&str>().map(|s| (*s).to_owned()))
        .unwrap_or_else(|| "non-string callback panic".into());
    let mut cleanup_panicked = false;
    loop {
        match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(payload))) {
            Ok(()) => break,
            Err(next) => {
                cleanup_panicked = true;
                payload = next;
            }
        }
    }
    if cleanup_panicked {
        message.push_str(" (panic payload destructor also panicked)");
    }
    message
}

pub(crate) fn finish_closing(shared: &Rc<RefCell<State>>) -> Result<(), OnlyEventError> {
    let retired = {
        let mut state = borrow(shared)?;
        if state.phase == OnlyEventBusState::Closing && !state.dispatching && state.queue.is_empty()
        {
            state.phase = OnlyEventBusState::Closed;
            std::mem::take(&mut state.handlers)
        } else {
            BTreeMap::new()
        }
    };
    drop(retired);
    Ok(())
}
impl OnlyEventBus {
    pub fn close(&mut self) -> Result<OnlyEventBusState, OnlyEventError> {
        {
            let mut state = borrow(&self.shared)?;
            if state.dispatching {
                return Err(OnlyEventError::Busy);
            }
            if state.phase == OnlyEventBusState::Failed {
                return Err(OnlyEventError::Closed);
            }
            if state.phase == OnlyEventBusState::Running {
                state.phase = OnlyEventBusState::Closing;
            }
        }
        self.drain()?;
        finish_closing(&self.shared)?;
        self.state()
    }
    pub fn diagnostics(&self) -> Result<OnlyEventDiagnostics, OnlyEventError> {
        Ok(borrow(&self.shared)?.diagnostics.snapshot())
    }
}
impl Drop for OnlyEventBus {
    fn drop(&mut self) {
        let retired = {
            let Ok(mut state) = self.shared.try_borrow_mut() else {
                return;
            };
            let unfinished = state.dispatching
                || !state.queue.is_empty()
                || state.phase == OnlyEventBusState::Failed;
            state.phase = if unfinished {
                OnlyEventBusState::Failed
            } else {
                OnlyEventBusState::Closed
            };
            let abandoned = BigUint::from(state.queue.len());
            state.diagnostics.abandoned_pending += abandoned;
            let handlers = std::mem::take(&mut state.handlers);
            let queue = std::mem::take(&mut state.queue);
            (handlers, queue)
        };
        drop(retired);
    }
}

#[cfg(test)]
mod control_tests {
    use super::*;
    #[test]
    fn rejected_recursive_dispatch_keeps_state_unchanged() {
        let mut bus = OnlyEventBus::new(Default::default()).unwrap();
        let event = OnlyEvent::new(OnlyEventInput {
            event_id: OnlyEventId::parse("00000000-0000-0000-0000-000000000001").unwrap(),
            event_type: OnlyEventType::new("FACT").unwrap(),
            source: OnlyEventSource::new("test").unwrap(),
            scope: OnlyEventScope::new(
                onlyalpha_domain::identifiers::OnlyEngineId::new("engine").unwrap(),
                Some(onlyalpha_domain::identifiers::OnlyRuntimeId::new("runtime").unwrap()),
                None,
            )
            .unwrap(),
            timestamp: onlyalpha_domain::time::OnlyTimestamp::from_unix_nanos(0.into()),
            init_timestamp: onlyalpha_domain::time::OnlyTimestamp::from_unix_nanos(0.into()),
            sequence: 1u32.into(),
            correlation_id: None,
            causation_id: None,
            priority: OnlyEventPriority::Normal,
            payload: OnlyEventPayload::Scalar(serde_json::Value::Null),
            metadata: Default::default(),
        })
        .unwrap();
        bus.publish(Arc::new(event)).unwrap();
        borrow(&bus.shared).unwrap().dispatching = true;
        assert_eq!(bus.dispatch_one().unwrap_err(), OnlyEventError::Busy);
        assert_eq!(bus.pending_count().unwrap(), 1);
        assert_eq!(bus.diagnostics().unwrap().dispatches.total, BigUint::ZERO);
        borrow(&bus.shared).unwrap().dispatching = false;
        assert_eq!(bus.drain().unwrap(), BigUint::from(1u32));
    }
}
