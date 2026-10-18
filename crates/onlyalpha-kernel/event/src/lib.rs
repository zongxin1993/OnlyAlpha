//! Immutable facts and single-thread observation; never trading or durable publication authority.
mod model;
mod record;
pub use model::*;
mod bus;
pub use bus::*;

mod capabilities;
pub use capabilities::*;

mod diagnostics;
mod ports;
pub use diagnostics::*;
pub use ports::*;
