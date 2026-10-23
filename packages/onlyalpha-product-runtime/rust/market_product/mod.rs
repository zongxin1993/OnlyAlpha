//! Transport-neutral chart Product owners. Provider protocol remains a Source;
//! canonical history remains Storage. Host owns human mutation admission and send.
mod acquisition;
mod queries;
mod recorder;
mod runtime;
mod stream;
use crate::{market_data, source_access};
pub use acquisition::{
    AcquisitionRequest, AcquisitionWork, CaptureRequest, Captured, MutationAdmission,
};
use onlyalpha_integration_contract::source::SourceError;
pub use queries::{
    Application, Authorized, AuthorizedBatch, BatchFence, InstrumentQuery, SendFence, WindowRequest,
};
use recorder::WalRecorder;
pub use runtime::{GenerationAdmission, Installed, Resolved, Resolver};
use serde_json::Value;
use sha2::{Digest, Sha256};
pub use stream::{
    PendingStreamEvent, PreviewSource, ProductStream, StreamRequest, drain_historical_capture,
    drain_market_capture,
};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Invalid,
    Unavailable,
    Corrupt,
    Selection,
    Forbidden,
    Unknown,
    Conflict,
    Busy,
    Backpressure,
    PreviewSuperseded,
    Source(SourceError),
    Store(market_data::Error),
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "MARKET_DATA_REQUEST_INVALID",
            Self::Unavailable => "MARKET_DATA_SOURCE_CATALOG_UNAVAILABLE",
            Self::Corrupt => "MARKET_DATA_SOURCE_CATALOG_CORRUPT",
            Self::Selection => "MARKET_DATA_SOURCE_SELECTION_UNRESOLVED",
            Self::Forbidden => "MARKET_DATA_ACCESS_DENIED",
            Self::Unknown => "MARKET_DATA_ACQUISITION_PENDING",
            Self::Conflict => "MARKET_DATA_PROVENANCE_CONFLICT",
            Self::Busy => "MARKET_DATA_EXECUTION_ACTIVE",
            Self::Backpressure => "MARKET_DATA_STREAM_BACKPRESSURE",
            Self::PreviewSuperseded => "MARKET_DATA_PREVIEW_SUPERSEDED",
            Self::Source(e) => e.code(),
            Self::Store(e) => e.code(),
        }
    }
}
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}
impl From<SourceError> for Error {
    fn from(e: SourceError) -> Self {
        Self::Source(e)
    }
}
impl From<market_data::Error> for Error {
    fn from(e: market_data::Error) -> Self {
        Self::Store(e)
    }
}
impl From<source_access::Error> for Error {
    fn from(_: source_access::Error) -> Self {
        Self::Forbidden
    }
}
type Result<T> = std::result::Result<T, Error>;
fn hash(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
fn canonical(v: &Value) -> Result<String> {
    onlyalpha_metadata_json::canonical_json(&v.to_string(), 64 * 1024 * 1024)
        .map_err(|_| Error::Corrupt)
}
fn fp(v: &Value) -> Result<String> {
    Ok(hash(canonical(v)?.as_bytes()))
}
fn ns(t: onlyalpha_domain::time::OnlyUtcDateTime) -> Result<i64> {
    onlyalpha_domain::time::OnlyTimestamp::from_datetime(t)
        .unix_nanos()
        .to_string()
        .parse()
        .map_err(|_| Error::Invalid)
}
fn time(ns: i64) -> Result<onlyalpha_domain::time::OnlyUtcDateTime> {
    onlyalpha_domain::time::OnlyTimestamp::from_unix_nanos(ns.into())
        .to_datetime_exact()
        .map_err(|_| Error::Invalid)
}

fn budget(end: std::time::Instant) -> Result<onlyalpha_integration_contract::source::Budget> {
    let ms = end
        .checked_duration_since(std::time::Instant::now())
        .ok_or(Error::Source(SourceError::Timeout))?
        .as_millis();
    onlyalpha_integration_contract::source::Budget::from_millis(
        u64::try_from(ms).map_err(|_| Error::Invalid)?.min(60000),
    )
    .map_err(Into::into)
}

mod probe;
pub use probe::{CompletedProbe, ProbeAdmission, latest_probe, probe_attempts};

mod history;
pub use history::HistoryContext;
