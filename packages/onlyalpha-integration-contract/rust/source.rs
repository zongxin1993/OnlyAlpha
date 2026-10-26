//! Executable provider boundary. Host supplies immutable trust, clock and the
//! installed executable artifact; Product owns grants, durability and publication.
use crate::{Descriptor, Error};
use onlyalpha_domain::{
    calendar::OnlyTradingCalendar, instrument::OnlyInstrument, market::OnlyBar,
};
use onlyalpha_market_data_construction::OnlyConstructionCapability;
use serde_json::{Value, value::RawValue};
use std::{future::Future, pin::Pin, sync::Arc};
/// Finite remaining operation budget. Product computes it after queue waits and
/// retains its original absolute deadline; Source pins one local monotonic end.
#[derive(Clone, Copy)]
pub struct Budget(u64);
impl Budget {
    pub fn from_millis(ms: u64) -> Result<Self, SourceError> {
        if ms == 0 || ms > 60000 {
            return Err(SourceError::Invalid);
        }
        Ok(Self(ms))
    }
    pub fn millis(self) -> u64 {
        self.0
    }
}
pub type FutureResult<'a, T> = Pin<Box<dyn Future<Output = Result<T, SourceError>> + Send + 'a>>;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SourceError {
    Invalid,
    Unsupported,
    Unavailable,
    Timeout,
    Evidence,
    Gap,
    Conflict,
    RefreshRequired,
    Stopped,
}
impl SourceError {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "MARKET_DATA_REQUEST_INVALID",
            Self::Unsupported => "MARKET_DATA_CAPABILITY_UNSUPPORTED",
            Self::Unavailable => "MARKET_DATA_SOURCE_UNAVAILABLE",
            Self::Timeout => "MARKET_DATA_SOURCE_TIMEOUT",
            Self::Evidence => "MARKET_DATA_DURABILITY_UNAVAILABLE",
            Self::Gap => "MARKET_DATA_CONTINUITY_UNPROVEN",
            Self::Conflict => "MARKET_DATA_IDENTITY_CONFLICT",
            Self::RefreshRequired => "HISTORY_REFRESH_REQUIRED",
            Self::Stopped => "MARKET_DATA_STOPPED",
        }
    }
}
impl std::fmt::Display for SourceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for SourceError {}
/// No ambient roots, proxy discovery or sensitive Debug/serialization. Empty or
/// invalid roots fail construction; the Host owns loading and qualifying roots.
#[derive(Clone)]
pub struct Trust {
    roots_pem: Arc<[Vec<u8>]>,
}
impl Trust {
    pub fn explicit_roots(roots: Vec<Vec<u8>>) -> Result<Self, SourceError> {
        if roots.is_empty()
            || roots.len() > 64
            || roots.iter().any(|r| r.is_empty() || r.len() > 1024 * 1024)
        {
            return Err(SourceError::Invalid);
        }
        Ok(Self {
            roots_pem: roots.into(),
        })
    }
    pub fn roots_pem(&self) -> &[Vec<u8>] {
        &self.roots_pem
    }
}
pub trait Clock: Send + Sync {
    fn now_ns(&self) -> Result<i64, SourceError>;
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MarketIdentity {
    pub provider: String,
    pub venue: String,
    pub market: String,
    pub environment: String,
    pub source_id: String,
}
#[derive(Clone)]
pub struct Observation {
    pub identity: MarketIdentity,
    pub stream: String,
    pub event_type: String,
    pub provider_event_id: Option<String>,
    pub provider_sequence: Option<i64>,
    pub event_ns: Option<i64>,
    pub receive_ns: i64,
    pub bytes: Vec<u8>,
    pub bars: Vec<OnlyBar>,
}
/// One call means one original Raw plus 0..N facts. A successful return requires
/// the actual OAMD append+fsync, before any row/preview/readiness may escape.
pub trait Recorder: Send {
    fn record(&mut self, observation: Observation) -> Result<(), SourceError>;
    fn finish(&mut self) -> Result<(), SourceError>;
}
#[derive(Clone)]
pub struct HistoryRequest {
    pub instrument: OnlyInstrument,
    pub minutes: u16,
    pub start_ms: i64,
    pub end_ms: i64,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Quote {
    pub instrument_id: String,
    pub last_price: String,
    pub change_pct: String,
    pub event_ns: i64,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct IngressTiming {
    pub provider_event_ns: i64,
    pub ingress_received_ns: i64,
}
pub enum StreamEvent {
    Recovering,
    Ready,
    Closed(OnlyBar, i64, Option<IngressTiming>),
    Preview(OnlyBar, i64, Option<IngressTiming>),
    Lost(SourceError),
}
pub trait Stream: Send {
    fn next<'a>(&'a mut self, recorder: &'a mut dyn Recorder) -> FutureResult<'a, StreamEvent>;
    fn close<'a>(&'a mut self) -> FutureResult<'a, ()>;
}
/// Volatile display stream; cannot issue a durable Recorder receipt.
pub trait TemporaryStream: Send {
    fn next<'a>(&'a mut self) -> FutureResult<'a, StreamEvent>;
    fn close<'a>(&'a mut self) -> FutureResult<'a, ()>;
}
pub trait Resource: Send + Sync {
    fn identity(&self) -> &MarketIdentity;
    fn calendar(&self) -> &OnlyTradingCalendar;
    fn capabilities(&self) -> &[OnlyConstructionCapability];
    fn resume_max_bars(&self) -> u16;
    fn instruments<'a>(
        &'a self,
        symbols: &'a [String],
        deadline: Budget,
    ) -> FutureResult<'a, Vec<OnlyInstrument>>;
    fn quotes<'a>(
        &'a self,
        symbols: &'a [String],
        deadline: Budget,
    ) -> FutureResult<'a, Vec<Quote>>;
    fn history<'a>(
        &'a self,
        request: &'a HistoryRequest,
        deadline: Budget,
        recorder: &'a mut dyn Recorder,
    ) -> FutureResult<'a, Vec<OnlyBar>>;
    /// Volatile display only. No Recorder, durable receipt or publication.
    /// Formal collection MUST continue to use `history` with its real WAL owner.
    fn temporary_history<'a>(
        &'a self,
        _request: &'a HistoryRequest,
        _deadline: Budget,
    ) -> FutureResult<'a, Vec<OnlyBar>> {
        Box::pin(async { Err(SourceError::Unsupported) })
    }
    /// The checkpoint is an owning, closed native input from the temporary read,
    /// never caller prices or a sealed-history witness. Provider owns its cursor.
    fn temporary_stream<'a>(
        &'a self,
        _request: HistoryRequest,
        _checkpoint: OnlyBar,
        _deadline: Budget,
    ) -> FutureResult<'a, Box<dyn TemporaryStream>> {
        Box::pin(async { Err(SourceError::Unsupported) })
    }
    fn stream<'a>(
        &'a self,
        request: HistoryRequest,
        resume: Option<i64>,
        deadline: Budget,
    ) -> FutureResult<'a, Box<dyn Stream>>;
    fn probe<'a>(&'a self, symbol: &'a str, deadline: Budget) -> FutureResult<'a, Value>;
}
/// Real installed implementation, not authoring metadata. Only the compiled
/// composition supplies this trait object. No runtime loader or compatibility.
pub trait Factory: Send + Sync {
    fn descriptor(&self) -> &Descriptor;
    fn implementation_fingerprint(&self) -> &str;
    fn validate_configuration(&self, configuration: &RawValue) -> Result<(), SourceError>;
    fn create(
        &self,
        configuration: &RawValue,
        trust: &Trust,
        clock: Arc<dyn Clock>,
    ) -> Result<Arc<dyn Resource>, SourceError>;
}
pub fn source_contract_error(_: Error) -> SourceError {
    SourceError::Invalid
}
