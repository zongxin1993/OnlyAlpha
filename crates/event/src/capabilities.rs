use crate::bus::{RegisteredHandler, State, borrow, enqueue, require_running};
use crate::*;
use num_bigint::BigUint;
use std::{cell::RefCell, rc::Rc, sync::Arc};
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlySubscription {
    pub id: OnlySubscriptionId,
    pub event_type: OnlyEventType,
    pub handler_name: String,
    pub priority: OnlyEventPriority,
    pub registration_sequence: BigUint,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OnlyEventHandlerOutcome {
    Succeeded,
    Error(String),
    Panic(String),
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyEventHandlerResult {
    pub subscription: OnlySubscription,
    pub outcome: OnlyEventHandlerOutcome,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyEventDispatchReport {
    pub event: Arc<OnlyEvent>,
    pub handler_results: Vec<OnlyEventHandlerResult>,
}
/// Callback control cannot drive the owning dispatcher.
/// ```compile_fail
/// let _:onlyalpha_event::OnlyEventHandler=Box::new(|_,context|{context.dispatch_one()?;Ok(())});
/// ```
/// ```compile_fail
/// use onlyalpha_event::{OnlyEvent,OnlyEventBus,OnlyEventError,OnlyEventHandler};
/// fn owner(_: &OnlyEvent, bus:&mut OnlyEventBus)->Result<(),OnlyEventError>{*bus=OnlyEventBus::new(Default::default())?;Ok(())}
/// let _:OnlyEventHandler=Box::new(owner);
/// ```
pub type OnlyEventHandler = Box<
    dyn for<'a> FnMut(&OnlyEvent, &mut OnlyEventCallbackContext<'a>) -> Result<(), OnlyEventError>,
>;
pub struct OnlySubscriptionHandle {
    subscription: OnlySubscription,
    shared: Rc<RefCell<State>>,
}
impl OnlySubscriptionHandle {
    pub fn subscription(&self) -> &OnlySubscription {
        &self.subscription
    }
    pub fn cancel(&self) -> Result<bool, OnlyEventError> {
        unsubscribe(&self.shared, self.subscription.id)
    }
}
/// Subscription access never grants publication or dispatcher ownership.
/// ```compile_fail
/// let bus=onlyalpha_event::OnlyEventBus::new(Default::default()).unwrap();
/// bus.view().close().unwrap();
/// ```
/// ```compile_fail
/// let bus=onlyalpha_event::OnlyEventBus::new(Default::default()).unwrap();
/// let view=bus.view();view.publish_many_atomic(&[]).unwrap();
/// ```
/// ```compile_fail
/// let mut bus=onlyalpha_event::OnlyEventBus::new(Default::default()).unwrap();
/// std::thread::spawn(move||bus.drain());
/// ```
/// ```compile_fail
/// let bus=onlyalpha_event::OnlyEventBus::new(Default::default()).unwrap();
/// let view=bus.view();std::thread::spawn(move||view.pending_count());
/// ```
#[derive(Clone)]
pub struct OnlyEventBusSubscriptionView {
    pub(crate) shared: Rc<RefCell<State>>,
}
impl OnlyEventBusSubscriptionView {
    pub fn subscribe(
        &self,
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
    pub fn unsubscribe(&self, id: OnlySubscriptionId) -> Result<bool, OnlyEventError> {
        unsubscribe(&self.shared, id)
    }
    pub fn diagnostics(&self) -> Result<OnlyEventDiagnostics, OnlyEventError> {
        Ok(borrow(&self.shared)?.diagnostics.snapshot())
    }
    pub fn pending_count(&self) -> Result<usize, OnlyEventError> {
        Ok(borrow(&self.shared)?.queue.len())
    }
    pub fn state(&self) -> Result<OnlyEventBusState, OnlyEventError> {
        Ok(borrow(&self.shared)?.phase)
    }
}
pub struct OnlyEventCallbackContext<'a> {
    pub(crate) shared: &'a Rc<RefCell<State>>,
}
impl OnlyEventCallbackContext<'_> {
    pub fn publish(
        &mut self,
        event: Arc<OnlyEvent>,
    ) -> Result<OnlyEventEnqueueReceipt, OnlyEventError> {
        enqueue(self.shared, event)
    }
    pub fn subscribe(
        &mut self,
        id: OnlySubscriptionId,
        event_type: OnlyEventType,
        handler_name: &str,
        priority: OnlyEventPriority,
        handler: OnlyEventHandler,
    ) -> Result<OnlySubscriptionHandle, OnlyEventError> {
        register(self.shared, id, event_type, handler_name, priority, handler)
    }
    pub fn unsubscribe(&mut self, id: OnlySubscriptionId) -> Result<bool, OnlyEventError> {
        unsubscribe(self.shared, id)
    }
    pub fn request_close(&mut self) -> Result<(), OnlyEventError> {
        let mut state = borrow(self.shared)?;
        if state.phase == OnlyEventBusState::Failed {
            return Err(OnlyEventError::Closed);
        }
        if state.phase == OnlyEventBusState::Running {
            state.phase = OnlyEventBusState::Closing;
        }
        Ok(())
    }
    pub fn view(&self) -> OnlyEventBusSubscriptionView {
        OnlyEventBusSubscriptionView {
            shared: self.shared.clone(),
        }
    }
}
pub(crate) fn register(
    shared: &Rc<RefCell<State>>,
    id: OnlySubscriptionId,
    event_type: OnlyEventType,
    handler_name: &str,
    priority: OnlyEventPriority,
    handler: OnlyEventHandler,
) -> Result<OnlySubscriptionHandle, OnlyEventError> {
    let handler_name = handler_name.trim();
    if handler_name.is_empty() {
        return Err(crate::model::invalid("empty handler name"));
    }
    let mut state = borrow(shared)?;
    require_running(&state)?;
    if state.used_ids.contains(&id) {
        return Err(OnlyEventError::DuplicateSubscription);
    }
    state.sequence += 1u32;
    let subscription = OnlySubscription {
        id,
        event_type,
        handler_name: handler_name.into(),
        priority,
        registration_sequence: state.sequence.clone(),
    };
    state.used_ids.insert(id);
    state.handlers.insert(
        id,
        RegisteredHandler {
            subscription: subscription.clone(),
            handler: Rc::new(RefCell::new(handler)),
        },
    );
    Ok(OnlySubscriptionHandle {
        subscription,
        shared: shared.clone(),
    })
}
pub(crate) fn unsubscribe(
    shared: &Rc<RefCell<State>>,
    id: OnlySubscriptionId,
) -> Result<bool, OnlyEventError> {
    let removed = { borrow(shared)?.handlers.remove(&id) };
    let changed = removed.is_some();
    drop(removed);
    Ok(changed)
}
