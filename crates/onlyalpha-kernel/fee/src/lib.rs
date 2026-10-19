//! Market-neutral fee authority. Provider rules and persistence drivers remain outside.
mod manager;
mod model;
mod policy;
mod reconciliation;
pub use manager::{Application, Manager};
pub use model::{Error, digest};
pub use policy::{Assessment, Binding, Catalog};
