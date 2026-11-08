//! Executable provider boundary. Host supplies immutable trust, clock and the
//! installed executable artifact; Product owns grants, durability and publication.
use crate::{Descriptor, Error};
use onlyalpha_domain::{
    calendar::OnlyTradingCalendar,
    identifiers::OnlyInstrumentId,
    instrument::OnlyInstrument,
    market::{OnlyBar, OnlyBarSemantic},
    time::{OnlyTradingDay, OnlyUtcDateTime},
};
pub use onlyalpha_market_data_construction::OnlyConstructionCapability;
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

/// 日线按已封存 Session 日历定位区间；其价格量值不自动授予交易规格或实时权限。
pub struct HistoricalDayRequest {
    pub instrument: OnlyInstrumentId,
    pub semantic: OnlyBarSemantic,
    pub start: OnlyUtcDateTime,
    pub end: OnlyUtcDateTime,
    pub anchor: Option<OnlyTradingDay>,
}
/// 原查询只含 Provider 公共参数。Host 逐项封存响应，精确比较请求与响应后交回重放。
pub struct HistoricalObservation {
    /// 原采集 attempt 在首次源端 I/O 前落库的时间下界。缓存命中保留原 producer 时间。
    pub producer_started_at: OnlyUtcDateTime,
    /// 原始响应在 Host 接收时的时间，来自已核验的物理证据。
    pub received_at: OnlyUtcDateTime,
    pub query: Value,
    pub bytes: Vec<u8>,
}
pub struct HistoricalDayResult {
    pub bars: Vec<OnlyBar>,
    pub calendar: OnlyTradingCalendar,
    pub security: Value,
    pub factor_basis: Option<Value>,
    pub normalized_daily_fingerprint: String,
    pub bar_query: Value,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HistoryInputPolicy {
    PreferCache,
    ForceRefresh,
    CacheOnly,
}
pub trait HistoricalDays: Send + Sync {
    fn semantic(&self) -> &OnlyBarSemantic;
    fn input_policy(&self) -> HistoryInputPolicy;
    fn inputs(&self, request: &HistoricalDayRequest) -> Result<Vec<Value>, SourceError>;
    fn fetch<'a>(&'a self, query: &'a Value, budget: Budget) -> FutureResult<'a, Vec<u8>>;
    fn replay<'a>(
        &'a self,
        request: &'a HistoricalDayRequest,
        observations: Vec<HistoricalObservation>,
        budget: Budget,
    ) -> FutureResult<'a, HistoricalDayResult>;
    /// 供发现界面展示的只读证券元数据。缺少证券交易状态时，显式返回 UNKNOWN。
    fn instruments<'a>(&'a self, budget: Budget) -> FutureResult<'a, Vec<Value>>;
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
    fn normalizer_id(&self) -> &str;
    fn calendar(&self) -> Option<&OnlyTradingCalendar>;
    fn historical_days(&self) -> Option<&dyn HistoricalDays> {
        None
    }
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
    /// 仅在 Host 已验证全部原始 Slot 和 generation 后借用秘密；禁止记录或序列化。
    fn create_with_credentials(
        &self,
        configuration: &RawValue,
        trust: &Trust,
        clock: Arc<dyn Clock>,
        credentials: &[(&str, &str)],
    ) -> Result<Arc<dyn Resource>, SourceError> {
        if !credentials.is_empty() {
            return Err(SourceError::Unsupported);
        }
        self.create(configuration, trust, clock)
    }
}
pub fn source_contract_error(_: Error) -> SourceError {
    SourceError::Invalid
}
