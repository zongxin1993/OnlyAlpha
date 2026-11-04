//! Publication interfaces only. The owning Runtime decides routing and durability.
use crate::*;
use num_bigint::BigUint;
use std::sync::Arc;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OnlyRuntimeEventRoute {
    ExternalDirect,
    DurableOutbox,
    Lifecycle,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OnlyRuntimeEventDisposition {
    Published,
    Staged,
    Suppressed,
    Rejected,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyRuntimeEventPublicationInput {
    pub route: OnlyRuntimeEventRoute,
    pub disposition: OnlyRuntimeEventDisposition,
    pub attempted: BigUint,
    pub published: BigUint,
    pub staged: BigUint,
    pub suppressed: BigUint,
    pub rejected: BigUint,
    pub error: Option<String>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyRuntimeEventPublicationResult {
    input: OnlyRuntimeEventPublicationInput,
}
impl OnlyRuntimeEventPublicationResult {
    pub fn new(input: OnlyRuntimeEventPublicationInput) -> Result<Self, OnlyEventError> {
        if input.attempted != &input.published + &input.staged + &input.suppressed + &input.rejected
        {
            return Err(crate::model::invalid(
                "publication counts must conserve attempts",
            ));
        }
        Ok(Self { input })
    }
    pub fn counts(&self) -> &OnlyRuntimeEventPublicationInput {
        &self.input
    }
}
pub trait OnlyDirectEventPublicationPort {
    fn publish_direct(
        &mut self,
        event: Arc<OnlyEvent>,
    ) -> Result<OnlyRuntimeEventPublicationResult, OnlyEventError>;
    fn publish_direct_many(
        &mut self,
        events: &[Arc<OnlyEvent>],
    ) -> Result<OnlyRuntimeEventPublicationResult, OnlyEventError>;
}
pub trait OnlyDurableEventPublicationPort {
    fn publish_durable(
        &mut self,
        event: Arc<OnlyEvent>,
    ) -> Result<OnlyRuntimeEventPublicationResult, OnlyEventError>;
}
pub trait OnlyLifecycleEventPublicationPort {
    fn publish_lifecycle(
        &mut self,
        event: Arc<OnlyEvent>,
    ) -> Result<OnlyRuntimeEventPublicationResult, OnlyEventError>;
}
