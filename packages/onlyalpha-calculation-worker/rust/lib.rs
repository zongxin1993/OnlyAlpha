//! Managed Python calculation process Infrastructure. No official Runtime admission.
mod client;
mod process;
pub use client::{Checkpoint, Client, Resolution, fingerprint};
pub use process::{Cancellation, Result, Worker, WorkerError};

mod pipeline_adapter;
pub use pipeline_adapter::{PipelineCalculations, SmaRequest};
