//! Calculation definitions and pure scoped execution ownership.
//! No algorithm, transport, readiness inference or official Runtime admission.
//! Internal Definition3 is separate from the current Product2 wire reader.
//! Neither a source read nor the component registry grants official Runtime admission.
mod definition;
mod execution;
mod graph;
mod parameters;
mod readiness;
mod record;
mod registry;
mod state;
pub use definition::{Definition, TypeDefinition, TypeReference};
pub use execution::{ExecutionBinding, ExecutionCursor, MAX_BATCH, PreparedBatch};
pub use graph::Graph;
pub use registry::{Backend, Registration, Registry};
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CalculationError(String);
impl std::fmt::Display for CalculationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for CalculationError {}
pub type Result<T> = std::result::Result<T, CalculationError>;

pub use readiness::{ReadinessBarrier, ReadinessPlan, ReadinessRequirement, ReadinessStatus};
pub use state::{
    CalculationSnapshot, CalculationState, InputPosition, StateOutcome, normalize_result_outputs,
};

pub mod product;
