use num_bigint::BigUint;
use onlyalpha_domain::{
    identifiers::{OnlyClusterId, OnlyEngineId, OnlyRuntimeId},
    market::OnlyBar,
    time::OnlyTimestamp,
};
use serde_json::Value;
use std::{collections::BTreeMap, fmt};
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OnlyEventError {
    Validation(String),
    Record(String),
    Scope,
    Capacity,
    RuntimeFailure,
    Closed,
    Busy,
    DuplicateSubscription,
    Callback(String),
}
impl fmt::Display for OnlyEventError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for OnlyEventError {}
impl From<onlyalpha_domain::errors::OnlyDomainError> for OnlyEventError {
    fn from(e: onlyalpha_domain::errors::OnlyDomainError) -> Self {
        Self::Validation(e.to_string())
    }
}
pub(crate) fn invalid(s: &str) -> OnlyEventError {
    OnlyEventError::Validation(s.into())
}
macro_rules! uuid_id {
    ($($name:ident),+) => {$(
        #[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub struct $name([u8; 16]);
        impl $name {
            pub fn parse(s: &str) -> Result<Self, OnlyEventError> {
                const HYPHENS: [usize; 4] = [8, 13, 18, 23];
                if s.len() != 36 || !HYPHENS.into_iter().all(|i| s.as_bytes()[i] == b'-') {
                    return Err(invalid("invalid UUID"));
                }
                let bytes: Vec<_> = s.bytes().enumerate()
                    .filter(|(i, _)| !HYPHENS.contains(i)).map(|(_, b)| b).collect();
                let hex = |b: u8| match b {
                    b'0'..=b'9' => Some(b - b'0'),
                    b'a'..=b'f' => Some(b - b'a' + 10),
                    b'A'..=b'F' => Some(b - b'A' + 10),
                    _ => None,
                };
                let mut out = [0; 16];
                for (i, pair) in bytes.chunks_exact(2).enumerate() {
                    out[i] = hex(pair[0]).ok_or_else(|| invalid("invalid UUID"))? * 16
                        + hex(pair[1]).ok_or_else(|| invalid("invalid UUID"))?;
                }
                Ok(Self(out))
            }
        }
        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                for (i, b) in self.0.iter().enumerate() {
                    if [4, 6, 8, 10].contains(&i) { f.write_str("-")?; }
                    write!(f, "{b:02x}")?;
                }
                Ok(())
            }
        }
    )+};
}
uuid_id!(
    OnlyEventId,
    OnlyCorrelationId,
    OnlyCausationId,
    OnlySubscriptionId
);
macro_rules! text_id {
    ($($name:ident),+) => {$(
        #[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
        pub struct $name(String);
        impl $name {
            pub fn new(s: &str) -> Result<Self, OnlyEventError> {
                let s = s.trim_matches(|c: char| c.is_whitespace()
                    || ('\u{001c}'..='\u{001f}').contains(&c));
                if s.is_empty() { return Err(invalid("empty Event name")); }
                Ok(Self(s.into()))
            }
            pub fn value(&self) -> &str { &self.0 }
        }
        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { f.write_str(&self.0) }
        }
    )+};
}
text_id!(OnlyEventType, OnlyEventSource);
/// Stable fact names; this vocabulary is not a handler or pipeline registry.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OnlyKnownEventType {
    BarReceived,
    BarValidated,
    DerivedBarCreated,
    BarCacheUpdated,
    IndicatorUpdated,
    MarketDataSnapshotReady,
    MarketDataPipelineFailed,
    ClusterBarHandled,
    ClusterBarHandlerFailed,
}
impl OnlyKnownEventType {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::BarReceived => "BAR_RECEIVED",
            Self::BarValidated => "BAR_VALIDATED",
            Self::DerivedBarCreated => "DERIVED_BAR_CREATED",
            Self::BarCacheUpdated => "BAR_CACHE_UPDATED",
            Self::IndicatorUpdated => "INDICATOR_UPDATED",
            Self::MarketDataSnapshotReady => "MARKET_DATA_SNAPSHOT_READY",
            Self::MarketDataPipelineFailed => "MARKET_DATA_PIPELINE_FAILED",
            Self::ClusterBarHandled => "CLUSTER_BAR_HANDLED",
            Self::ClusterBarHandlerFailed => "CLUSTER_BAR_HANDLER_FAILED",
        }
    }
}
impl From<OnlyKnownEventType> for OnlyEventType {
    fn from(value: OnlyKnownEventType) -> Self {
        Self(value.as_str().into())
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum OnlyEventPriority {
    Low,
    Normal,
    High,
    Critical,
}
impl OnlyEventPriority {
    pub fn name(self) -> &'static str {
        match self {
            Self::Low => "LOW",
            Self::Normal => "NORMAL",
            Self::High => "HIGH",
            Self::Critical => "CRITICAL",
        }
    }
    pub fn parse(s: &str) -> Result<Self, OnlyEventError> {
        match s {
            "LOW" => Ok(Self::Low),
            "NORMAL" => Ok(Self::Normal),
            "HIGH" => Ok(Self::High),
            "CRITICAL" => Ok(Self::Critical),
            _ => Err(invalid("unknown Event priority")),
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyEventScope {
    pub(crate) engine: OnlyEngineId,
    pub(crate) runtime: Option<OnlyRuntimeId>,
    pub(crate) cluster: Option<OnlyClusterId>,
}
impl OnlyEventScope {
    pub fn new(
        engine: OnlyEngineId,
        runtime: Option<OnlyRuntimeId>,
        cluster: Option<OnlyClusterId>,
    ) -> Result<Self, OnlyEventError> {
        if cluster.is_some() && runtime.is_none() {
            return Err(invalid("Cluster requires Runtime"));
        }
        Ok(Self {
            engine,
            runtime,
            cluster,
        })
    }
    pub fn engine_id(&self) -> &OnlyEngineId {
        &self.engine
    }
    pub fn runtime_id(&self) -> Option<&OnlyRuntimeId> {
        self.runtime.as_ref()
    }
    pub fn cluster_id(&self) -> Option<&OnlyClusterId> {
        self.cluster.as_ref()
    }
    pub fn includes(&self, other: &Self) -> bool {
        self.engine == other.engine
            && self
                .runtime
                .as_ref()
                .is_none_or(|v| Some(v) == other.runtime.as_ref())
            && self
                .cluster
                .as_ref()
                .is_none_or(|v| Some(v) == other.cluster.as_ref())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OnlyEventPayload {
    Bar(Box<OnlyBar>),
    Mapping(Value),
    Scalar(Value),
}
impl OnlyEventPayload {
    fn validate(&self) -> Result<(), OnlyEventError> {
        match self {
            Self::Bar(_) => Ok(()),
            Self::Mapping(v) if v.is_object() => validate_json(v),
            Self::Scalar(v)
                if v.is_null()
                    || v.is_string()
                    || v.is_boolean()
                    || v.as_number()
                        .is_some_and(|n| n.to_string().parse::<num_bigint::BigInt>().is_ok()) =>
            {
                Ok(())
            }
            _ => Err(invalid("unsupported Event payload")),
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyEventInput {
    pub event_id: OnlyEventId,
    pub event_type: OnlyEventType,
    pub source: OnlyEventSource,
    pub scope: OnlyEventScope,
    pub timestamp: OnlyTimestamp,
    pub init_timestamp: OnlyTimestamp,
    pub sequence: BigUint,
    pub correlation_id: Option<OnlyCorrelationId>,
    pub causation_id: Option<OnlyCausationId>,
    pub priority: OnlyEventPriority,
    pub payload: OnlyEventPayload,
    pub metadata: BTreeMap<String, String>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyEvent {
    pub(crate) input: OnlyEventInput,
}
impl OnlyEvent {
    pub fn new(input: OnlyEventInput) -> Result<Self, OnlyEventError> {
        if input.scope.runtime.is_none()
            || input.init_timestamp.unix_nanos() < input.timestamp.unix_nanos()
        {
            return Err(invalid("invalid Event scope or timestamps"));
        }
        input.timestamp.to_datetime()?;
        input.init_timestamp.to_datetime()?;
        input.payload.validate()?;
        Ok(Self { input })
    }
    pub fn id(&self) -> OnlyEventId {
        self.input.event_id
    }
    pub fn source(&self) -> &OnlyEventSource {
        &self.input.source
    }
    pub fn correlation_id(&self) -> Option<OnlyCorrelationId> {
        self.input.correlation_id
    }
    pub fn causation_id(&self) -> Option<OnlyCausationId> {
        self.input.causation_id
    }
    pub fn event_type(&self) -> &OnlyEventType {
        &self.input.event_type
    }
    pub fn scope(&self) -> &OnlyEventScope {
        &self.input.scope
    }
    pub fn priority(&self) -> OnlyEventPriority {
        self.input.priority
    }
    pub fn sequence(&self) -> &BigUint {
        &self.input.sequence
    }
    pub fn payload(&self) -> &OnlyEventPayload {
        &self.input.payload
    }
    pub fn metadata(&self) -> &BTreeMap<String, String> {
        &self.input.metadata
    }
    pub fn timestamp(&self) -> &OnlyTimestamp {
        &self.input.timestamp
    }
    pub fn init_timestamp(&self) -> &OnlyTimestamp {
        &self.input.init_timestamp
    }
}

fn validate_json(value: &Value) -> Result<(), OnlyEventError> {
    let mut pending = vec![value];
    while let Some(value) = pending.pop() {
        match value {
            Value::Object(mapping) => pending.extend(mapping.values()),
            Value::Array(array) => pending.extend(array),
            Value::Number(number) => {
                number
                    .to_string()
                    .parse::<serde_json::Number>()
                    .map_err(|_| invalid("invalid JSON numeric token"))?;
            }
            _ => {}
        }
    }
    Ok(())
}
