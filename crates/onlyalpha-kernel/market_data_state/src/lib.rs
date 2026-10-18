//! Snapshots expose immutable data and no trading-readiness or owner capability.
//!
//! ```compile_fail
//! use onlyalpha_market_data_state::OnlyMarketDataSnapshot;
//! fn mutate(mut snapshot: OnlyMarketDataSnapshot) { snapshot.series.clear(); }
//! ```
//! ```compile_fail
//! use onlyalpha_market_data_state::OnlyMarketDataSeriesSnapshot;
//! fn mutate(mut series: OnlyMarketDataSeriesSnapshot) { series.history.clear(); }
//! ```
//! ```compile_fail
//! use onlyalpha_market_data_state::OnlyMarketDataState;
//! fn clone_owner(owner: OnlyMarketDataState) { owner.clone(); }
//! ```
//! ```compile_fail
//! use onlyalpha_market_data_state::{OnlyMarketDataSnapshot,OnlyMarketDataState};
//! fn extract(snapshot: &OnlyMarketDataSnapshot) -> &mut OnlyMarketDataState { snapshot.owner() }
//! ```
//! ```compile_fail
//! use onlyalpha_market_data_state::OnlyMarketDataSnapshot;
//! fn ready(snapshot: &OnlyMarketDataSnapshot) { snapshot.is_ready(); }
//! ```
//! Bounded Runtime-owned closed-Bar state, not durable market-history authority.
mod model;
mod state;
mod snapshot;
pub use model::*;
pub use state::{OnlyMarketDataState,OnlyMarketDataSeriesSnapshot};
pub use snapshot::OnlyMarketDataSnapshot;
