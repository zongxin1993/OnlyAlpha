//! Immutable Calculation contracts. No algorithm, execution or readiness authority.
//! Definition component schema3 is not admitted to Python Definition2 or official Runtime.
mod definition;
mod graph;
mod parameters;
mod record;
mod registry;
pub use definition::{Definition, TypeDefinition, TypeReference};
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
