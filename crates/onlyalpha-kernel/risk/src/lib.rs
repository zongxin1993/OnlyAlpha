//! Market-independent Risk decision and reservation owner. No official Runtime activation.
mod manager;
mod model;
mod pipeline;
mod recovery;
mod reservation;
pub use manager::Manager;
pub use model::{Error, Outcome, Status, digest};
