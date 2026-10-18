//! Pure market-data construction. No Source, Runtime or historical-store authority.
mod model;
mod record;
mod compiler;
pub use model::*;
pub use compiler::*;
