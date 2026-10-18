//! Canonical mutable owners cannot be duplicated or used as trading-readiness proof.
//! ```compile_fail
//! use onlyalpha_market_data_construction::OnlyConstructionManager;
//! fn duplicate(owner: &OnlyConstructionManager) -> OnlyConstructionManager { owner.clone() }
//! ```
//! ```compile_fail
//! use onlyalpha_market_data_construction::OnlyConstructionManager;
//! fn ready(owner: &OnlyConstructionManager) -> bool { owner.is_ready() }
//! ```
//! ```compile_fail
//! use onlyalpha_market_data_construction::OnlyConstructionManager;
//! fn alter(owner: &mut OnlyConstructionManager) { owner.failed = false; }
//! ```
//! Pure market-data construction. No Source, Runtime or historical-store authority.
mod compiler;
mod model;
mod record;
pub use compiler::*;
pub use model::*;
mod resolution;
pub use resolution::*;
mod executor;
mod time_bar;
pub use executor::*;
pub use time_bar::{OnlyConstructionWindow, OnlyTimeBarExecutor};

mod manager;
pub use manager::*;
