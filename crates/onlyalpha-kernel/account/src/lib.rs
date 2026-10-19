//! Market-independent scoped cash state. No official Runtime admission or effects.
mod manager;
mod model;
mod reconciliation;
mod recovery;
mod reservation;
pub use manager::Manager;
pub use model::{Error, Outcome, Status, digest};
