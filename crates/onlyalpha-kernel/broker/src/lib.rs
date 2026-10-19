//! Isolated, deterministic Broker protocol. Runtime owns application of all trading facts.
//! Owning journal/read ports are trusted boundaries; hashes provide integrity, not authorization.
mod model;
mod ports;
mod protocol;
pub use model::*;
pub use ports::*;
pub use protocol::*;
