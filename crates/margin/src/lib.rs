//! Instruction-driven canonical collateral state. Rates and external effects stay outside this library.
mod manager;
mod model;
pub use manager::{Effect, Manager};
pub use model::{Error, digest};
