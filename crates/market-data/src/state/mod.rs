//! Snapshots expose immutable data and no trading-readiness or owner capability.
//!
//! ```compile_fail
//! use onlyalpha_market_data::state::OnlyMarketDataSnapshot;
//! fn mutate(mut snapshot: OnlyMarketDataSnapshot) { snapshot.series.clear(); }
//! ```
//! ```compile_fail
//! use onlyalpha_market_data::state::OnlyMarketDataSeriesSnapshot;
//! fn mutate(mut series: OnlyMarketDataSeriesSnapshot) { series.history.clear(); }
//! ```
//! ```compile_fail
//! use onlyalpha_market_data::state::OnlyMarketDataState;
//! fn clone_owner(owner: OnlyMarketDataState) { owner.clone(); }
//! ```
//! ```compile_fail
//! use onlyalpha_market_data::state::{OnlyMarketDataSnapshot,OnlyMarketDataState};
//! fn extract(snapshot: &OnlyMarketDataSnapshot) -> &mut OnlyMarketDataState { snapshot.owner() }
//! ```
//! ```compile_fail
//! use onlyalpha_market_data::state::OnlyMarketDataSnapshot;
//! fn ready(snapshot: &OnlyMarketDataSnapshot) { snapshot.is_ready(); }
//! ```
//! Bounded Runtime-owned closed-Bar state, not durable market-history authority.
mod model;
mod owner;
mod snapshot;
pub use model::*;
pub use owner::{OnlyMarketDataSeriesSnapshot, OnlyMarketDataState};
pub use snapshot::OnlyMarketDataSnapshot;

mod record;
