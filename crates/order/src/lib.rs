//! Isolated deterministic Order component. No transport, execution permission or economic projections.
mod manager;
mod model;
mod recovery;
pub use manager::Manager;
pub use model::{ApplyResult, Error, Outcome, digest};
