//! Deterministic Strategy component and current public source values.
//! Source consistency proves no frozen publication or official Runtime admission.
mod admission;
mod execution;
mod finite;
mod model;
mod recovery;
pub use execution::Executor;
pub use finite::{CompletedResearch, ResearchRun, SignalExecution};
pub use model::*;

mod source;
pub use source::{SourceError, SourceRevision};
