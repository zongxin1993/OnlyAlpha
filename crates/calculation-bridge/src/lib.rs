//! Supplied algorithm transport and reusable calculation adapters. No official Runtime admission.
mod process;
pub use process::{
    Cancellation, ProcessControl, ProcessState, Result, Worker, WorkerConnector, WorkerError,
    serve_chart,
};

mod strategy_adapter;
pub use strategy_adapter::StrategyNodes;

mod strategy_preparation;
pub use strategy_preparation::StrategyPreparation;

mod chart_installation;
pub use chart_installation::ChartInstallation;

pub mod native_predicates;

pub mod protocol;

/// Fingerprint the exact bytes of a private calculation artifact or record.
pub fn fingerprint(raw: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    Sha256::digest(raw)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
