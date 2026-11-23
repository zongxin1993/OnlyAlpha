//! Isolated, deterministic Broker protocol. Runtime owns application of all trading facts.
//! Owning journal/read ports are trusted boundaries; hashes provide integrity, not authorization.
mod finite;
mod model;
mod ports;
mod protocol;
pub use finite::{CompletedMemoryBroker, MemoryBroker};
pub use model::*;
pub use ports::*;
pub use protocol::*;

pub mod source;
