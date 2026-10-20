//! Isolated execution planning and exact committed projection recovery.
//! Storage drivers, provider rules and official Runtime activation remain outside this library.
mod components;
mod model;
mod planning;
pub use components::Components;
pub use model::{Error, Prepared, digest};
mod coordinator;
pub use coordinator::{CommitIntent, Record, Store, coordinate, pending_events, recover};

mod margin;
mod valuation;
