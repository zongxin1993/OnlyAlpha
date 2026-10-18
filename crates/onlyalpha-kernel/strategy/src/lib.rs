//! Deterministic Strategy component. No official Revision1 reader or Runtime admission.
mod execution;
mod model;
mod recovery;
pub use execution::Executor;
pub use model::*;
