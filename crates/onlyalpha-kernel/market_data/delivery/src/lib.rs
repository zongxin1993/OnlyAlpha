//! Delivery plans carry scoped data, never calculation readiness or execution authority.
//! ```compile_fail
//! use onlyalpha_market_data_delivery::OnlyMarketDataDelivery;
//! fn duplicate(owner: OnlyMarketDataDelivery) { owner.clone(); }
//! ```
//! ```compile_fail
//! use onlyalpha_market_data_delivery::OnlyBarDeliveryPlan;
//! fn ready(plan: &OnlyBarDeliveryPlan) { plan.is_ready(); }
//! ```
//! ```compile_fail
//! use onlyalpha_market_data_delivery::OnlyMarketDataDelivery;
//! fn mutate(owner: &mut OnlyMarketDataDelivery) { owner.entries.clear(); }
//! ```
mod owner;
mod record;
mod subscription;
pub use owner::*;
pub use subscription::*;
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OnlyDeliveryError {
    Configuration,
    Scope,
    Sequence,
    Freshness,
    Record(String),
}
impl std::fmt::Display for OnlyDeliveryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for OnlyDeliveryError {}
pub type OnlyDeliveryResult<T> = Result<T, OnlyDeliveryError>;
