//! Runtime-scoped virtual strategy accounts, without IO or Runtime admission.
mod accounting;
mod manager;
mod model;
mod recovery;
mod valuation;
pub use manager::Manager;
pub use model::{Error, Outcome, Status, digest};
