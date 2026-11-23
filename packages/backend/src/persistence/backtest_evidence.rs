mod context;
mod physical;

pub(crate) use context::admitted_implementations as verify_implementation_bindings;
pub(crate) use context::{BacktestReadContext, read_context};
