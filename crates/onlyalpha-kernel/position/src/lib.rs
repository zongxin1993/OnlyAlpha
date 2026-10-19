//! Isolated Position semantics. No Runtime activation or external effects.
mod manager;
mod model;
mod reconciliation;
mod recovery;
mod reservation;
pub use manager::Manager;
pub use model::{Error, Outcome, Status, digest};
