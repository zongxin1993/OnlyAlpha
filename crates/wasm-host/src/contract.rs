//! Formal WIT contract versions, immutable artifact bindings, domain types, and Fail-Closed errors.

use onlyalpha_operators::algebra::Decimal;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fmt;

/// Formal versioned WIT contract package identifier (`contracts/wasm/v1/onlyalpha-plugin.wit`).
pub const WIT_CONTRACT_VERSION: &str = "onlyalpha:plugin@1.0.0";
/// Canonical host runtime ABI contract identifier recorded in frozen bindings.
pub const HOST_RUNTIME_VERSION: &str = "onlyalpha-wasm-host/1.0.0";
/// Canonical numeric policy required for extended operator plugins.
pub const NUMERIC_POLICY: &str = onlyalpha_operators::registry::NUMERIC_POLICY;
/// Maximum significant decimal digits allowed across the WASM ABI (`DECIMAL28_HALF_EVEN_Q12_V1`).
pub const MAX_DECIMAL_PRECISION: usize = 28;
/// Maximum fractional decimal digits allowed across the WASM ABI (`DECIMAL28_HALF_EVEN_Q12_V1`).
pub const MAX_DECIMAL_SCALE: usize = 12;
/// Maximum canonical parameter entries allowed in one plugin binding or call.
pub const MAX_CANONICAL_PARAMETERS: usize = 64;
/// Maximum parameter key length in bytes.
pub const MAX_PARAMETER_KEY_BYTES: usize = 128;
/// Maximum parameter value length in bytes.
pub const MAX_PARAMETER_VALUE_BYTES: usize = 1024;

/// Fully qualified WIT interface name for L3 extended operator plugins.
pub const EXTENDED_OPERATOR_INTERFACE: &str = "onlyalpha:plugin/extended-operator@1.0.0";
/// Fully qualified WIT interface name for L3 market rule plugins.
pub const MARKET_RULE_INTERFACE: &str = "onlyalpha:plugin/market-rule@1.0.0";
/// Fully qualified WIT interface name for L3 programmable strategy plugins.
pub const STRATEGY_INTERFACE: &str = "onlyalpha:plugin/strategy@1.0.0";

/// L3 WASM plugin category defined by ADR 0152.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PluginKind {
    ExtendedOperator,
    MarketRule,
    Strategy,
}

impl PluginKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ExtendedOperator => "EXTENDED_OPERATOR",
            Self::MarketRule => "MARKET_RULE",
            Self::Strategy => "STRATEGY",
        }
    }

    pub const fn wit_interface(self) -> &'static str {
        match self {
            Self::ExtendedOperator => EXTENDED_OPERATOR_INTERFACE,
            Self::MarketRule => MARKET_RULE_INTERFACE,
            Self::Strategy => STRATEGY_INTERFACE,
        }
    }
}

/// Computes canonical lowercase 64-hex SHA-256 over raw bytes.
pub fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

/// Validates that a string is a canonical lowercase 64-character hexadecimal SHA-256 digest.
pub fn is_valid_sha256_hex(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

/// Immutable replay and audit binding for one L3 WASM plugin artifact (ADR 0152 §2.6).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ArtifactBinding {
    pub plugin_id: String,
    pub kind: PluginKind,
    pub artifact_sha256: String,
    pub wit_contract_version: String,
    pub host_version: String,
    pub canonical_parameters: BTreeMap<String, String>,
}

impl ArtifactBinding {
    pub fn new(
        plugin_id: impl Into<String>,
        kind: PluginKind,
        artifact_sha256: impl Into<String>,
        canonical_parameters: BTreeMap<String, String>,
    ) -> Result<Self> {
        let plugin_id = plugin_id.into();
        let artifact_sha256 = artifact_sha256.into();
        validate_non_empty_id(&plugin_id, "plugin_id")?;
        if !is_valid_sha256_hex(&artifact_sha256) {
            return Err(Error::InvalidArtifact(
                "artifact_sha256 must be 64 lowercase hex characters".into(),
            ));
        }
        validate_canonical_parameters(&canonical_parameters)?;
        if kind == PluginKind::MarketRule && !canonical_parameters.is_empty() {
            return Err(Error::InvalidHostInput(
                "market-rule plugin bindings do not accept canonical_parameters".into(),
            ));
        }
        Ok(Self {
            plugin_id,
            kind,
            artifact_sha256,
            wit_contract_version: WIT_CONTRACT_VERSION.to_owned(),
            host_version: HOST_RUNTIME_VERSION.to_owned(),
            canonical_parameters,
        })
    }

    /// Verifies that raw `.wasm` bytes and contract metadata match this frozen binding exactly.
    pub fn verify_bytes(&self, wasm_bytes: &[u8]) -> Result<()> {
        if self.wit_contract_version != WIT_CONTRACT_VERSION {
            return Err(Error::UnsupportedContractVersion {
                expected: WIT_CONTRACT_VERSION.to_owned(),
                actual: self.wit_contract_version.clone(),
            });
        }
        if self.host_version != HOST_RUNTIME_VERSION {
            return Err(Error::UnsupportedContractVersion {
                expected: HOST_RUNTIME_VERSION.to_owned(),
                actual: self.host_version.clone(),
            });
        }
        let actual = sha256_hex(wasm_bytes);
        if actual != self.artifact_sha256 {
            return Err(Error::Sha256Mismatch {
                expected: self.artifact_sha256.clone(),
                actual,
            });
        }
        Ok(())
    }

    /// Canonical SHA-256 fingerprint over the entire frozen binding record.
    pub fn binding_digest(&self) -> String {
        let record = json!({
            "artifact_sha256": self.artifact_sha256,
            "canonical_parameters": self.canonical_parameters,
            "host_version": self.host_version,
            "kind": self.kind.as_str(),
            "plugin_id": self.plugin_id,
            "wit_contract_version": self.wit_contract_version,
        });
        sha256_hex(record.to_string().as_bytes())
    }
}

/// Output of one deterministic sandboxed guest call paired with exact fuel consumed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CallOutcome<T> {
    pub value: T,
    pub fuel_consumed: u64,
}

/// Static metadata declared by a WASM extended operator plugin.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OperatorMetadata {
    pub operator_id: String,
    pub version: String,
    pub input_arity: u32,
    pub warmup: u32,
    pub numeric_policy: String,
}

/// Immutable READY admission certificate issued after automatic dual-kernel certification.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReadyCertificate {
    pub plugin_id: String,
    pub operator_id: String,
    pub operator_version: String,
    pub artifact_sha256: String,
    pub wit_contract_version: String,
    pub host_version: String,
    pub numeric_policy: String,
    pub canonical_parameters: BTreeMap<String, String>,
    pub certified_cases_count: usize,
    pub golden_cases_count: usize,
    pub vector_event_equivalent: bool,
    pub causal_prefixes_verified: bool,
    pub warmup_null_verified: bool,
    pub snapshot_restore_verified: bool,
    pub deterministic_fuel_verified: bool,
    pub certificate_digest: String,
}

impl ReadyCertificate {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn issue(
        plugin_id: String,
        metadata: &OperatorMetadata,
        artifact_sha256: String,
        canonical_parameters: BTreeMap<String, String>,
        certified_cases_count: usize,
        golden_cases_count: usize,
    ) -> Self {
        let wit_contract_version = WIT_CONTRACT_VERSION.to_owned();
        let host_version = HOST_RUNTIME_VERSION.to_owned();
        let record = json!({
            "artifact_sha256": artifact_sha256,
            "canonical_parameters": canonical_parameters,
            "causal_prefixes_verified": true,
            "certified_cases_count": certified_cases_count,
            "deterministic_fuel_verified": true,
            "golden_cases_count": golden_cases_count,
            "host_version": host_version,
            "numeric_policy": metadata.numeric_policy,
            "operator_id": metadata.operator_id,
            "operator_version": metadata.version,
            "plugin_id": plugin_id,
            "snapshot_restore_verified": true,
            "vector_event_equivalent": true,
            "warmup_null_verified": true,
            "wit_contract_version": wit_contract_version,
        });
        let certificate_digest = sha256_hex(record.to_string().as_bytes());
        Self {
            plugin_id,
            operator_id: metadata.operator_id.clone(),
            operator_version: metadata.version.clone(),
            artifact_sha256,
            wit_contract_version,
            host_version,
            numeric_policy: metadata.numeric_policy.clone(),
            canonical_parameters,
            certified_cases_count,
            golden_cases_count,
            vector_event_equivalent: true,
            causal_prefixes_verified: true,
            warmup_null_verified: true,
            snapshot_restore_verified: true,
            deterministic_fuel_verified: true,
            certificate_digest,
        }
    }
}

/// Static metadata declared by a WASM market rule plugin.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MarketRuleMetadata {
    pub plugin_id: String,
    pub market_id: String,
    pub version: String,
}

/// Canonical order side matching `onlyalpha:plugin@1.0.0` (`order-side`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OrderSide {
    Buy,
    Sell,
}

impl OrderSide {
    pub const fn wit_name(self) -> &'static str {
        match self {
            Self::Buy => "buy",
            Self::Sell => "sell",
        }
    }

    pub fn from_wit_name(name: &str) -> Result<Self> {
        match name {
            "buy" => Ok(Self::Buy),
            "sell" => Ok(Self::Sell),
            other => Err(Error::InvalidGuestOutput(format!(
                "unknown order-side enum case: {other}"
            ))),
        }
    }
}

/// Canonical order type matching `onlyalpha:plugin@1.0.0` (`order-type`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OrderType {
    Market,
    Limit,
}

impl OrderType {
    pub const fn wit_name(self) -> &'static str {
        match self {
            Self::Market => "market",
            Self::Limit => "limit",
        }
    }

    pub fn from_wit_name(name: &str) -> Result<Self> {
        match name {
            "market" => Ok(Self::Market),
            "limit" => Ok(Self::Limit),
            other => Err(Error::InvalidGuestOutput(format!(
                "unknown order-type enum case: {other}"
            ))),
        }
    }
}

/// Canonical order time-in-force matching `onlyalpha:plugin@1.0.0` (`time-in-force`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TimeInForce {
    Day,
    Gtc,
    Ioc,
    Fok,
}

impl TimeInForce {
    pub const fn wit_name(self) -> &'static str {
        match self {
            Self::Day => "day",
            Self::Gtc => "gtc",
            Self::Ioc => "ioc",
            Self::Fok => "fok",
        }
    }

    pub fn from_wit_name(name: &str) -> Result<Self> {
        match name {
            "day" => Ok(Self::Day),
            "gtc" => Ok(Self::Gtc),
            "ioc" => Ok(Self::Ioc),
            "fok" => Ok(Self::Fok),
            other => Err(Error::InvalidGuestOutput(format!(
                "unknown time-in-force enum case: {other}"
            ))),
        }
    }
}

/// Explicit market-rule validation input passed into a market-rule WASM plugin.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MarketRuleInput {
    pub trading_day: String,
    pub instrument_id: String,
    pub side: OrderSide,
    pub order_type: OrderType,
    pub quantity: Decimal,
    pub price: Option<Decimal>,
    pub reference_price: Option<Decimal>,
    pub settled_quantity: Decimal,
    pub rule_version: String,
}

/// Deterministic decision returned by a market-rule WASM plugin.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MarketRuleDecision {
    pub allowed: bool,
    pub reject_code: Option<String>,
    pub normalized_quantity: Option<Decimal>,
    pub normalized_price: Option<Decimal>,
    pub fee_estimate: Option<Decimal>,
}

/// Static metadata declared by a WASM strategy plugin.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StrategyMetadata {
    pub strategy_id: String,
    pub version: String,
    pub required_factors: Vec<String>,
}

/// One bound causal factor value supplied to a strategy plugin.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NamedFactor {
    pub name: String,
    pub value: Option<Decimal>,
}

/// Read-only position view supplied to a strategy plugin.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReadonlyPosition {
    pub instrument_id: String,
    pub quantity: Decimal,
    pub average_cost: Option<Decimal>,
}

/// Read-only account/portfolio snapshot supplied to a strategy plugin.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReadonlyAccountState {
    pub timestamp_ns: i64,
    pub cash_available: Decimal,
    pub total_equity: Decimal,
    pub positions: Vec<ReadonlyPosition>,
}

/// Canonical order intent emitted by a strategy WASM plugin.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OrderIntent {
    pub instrument_id: String,
    pub side: OrderSide,
    pub order_type: OrderType,
    pub quantity: Decimal,
    pub limit_price: Option<Decimal>,
    pub time_in_force: TimeInForce,
    pub reason_code: String,
}

/// Fail-Closed error model for L3 WASM plugin loading, certification, and execution.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Error {
    HostInitialization(String),
    InvalidBudget(String),
    InvalidArtifact(String),
    Sha256Mismatch { expected: String, actual: String },
    UnsupportedContractVersion { expected: String, actual: String },
    ForbiddenImport { import_name: String },
    ContractExportMismatch { expected: String, detail: String },
    FuelExhausted { limit: u64 },
    MemoryLimitExceeded { limit_bytes: usize },
    HostLiftLimitExceeded { limit_bytes: usize },
    GuestTrap(String),
    GuestError { code: String, message: String },
    InvalidGuestOutput(String),
    InvalidHostInput(String),
    CertificationFailed { stage: &'static str, reason: String },
    PluginNotFound { plugin_id: String },
    PluginAlreadyLoaded { plugin_id: String },
    BindingMismatch { plugin_id: String, detail: String },
    LockPoisoned,
}

pub type Result<T> = std::result::Result<T, Error>;

impl Error {
    pub const fn code(&self) -> &'static str {
        match self {
            Self::HostInitialization(_) => "WASM_HOST_INIT_FAILED",
            Self::InvalidBudget(_) => "WASM_BUDGET_INVALID",
            Self::InvalidArtifact(_) => "WASM_ARTIFACT_INVALID",
            Self::Sha256Mismatch { .. } => "WASM_ARTIFACT_SHA256_MISMATCH",
            Self::UnsupportedContractVersion { .. } => "WASM_CONTRACT_VERSION_UNSUPPORTED",
            Self::ForbiddenImport { .. } => "WASM_FORBIDDEN_IMPORT",
            Self::ContractExportMismatch { .. } => "WASM_CONTRACT_EXPORT_MISMATCH",
            Self::FuelExhausted { .. } => "WASM_FUEL_EXHAUSTED",
            Self::MemoryLimitExceeded { .. } => "WASM_MEMORY_LIMIT_EXCEEDED",
            Self::HostLiftLimitExceeded { .. } => "WASM_HOST_LIFT_LIMIT_EXCEEDED",
            Self::GuestTrap(_) => "WASM_GUEST_TRAP",
            Self::GuestError { .. } => "WASM_GUEST_ERROR",
            Self::InvalidGuestOutput(_) => "WASM_GUEST_OUTPUT_INVALID",
            Self::InvalidHostInput(_) => "WASM_HOST_INPUT_INVALID",
            Self::CertificationFailed { .. } => "WASM_CERTIFICATION_FAILED",
            Self::PluginNotFound { .. } => "WASM_PLUGIN_NOT_FOUND",
            Self::PluginAlreadyLoaded { .. } => "WASM_PLUGIN_ALREADY_LOADED",
            Self::BindingMismatch { .. } => "WASM_BINDING_MISMATCH",
            Self::LockPoisoned => "WASM_HOST_LOCK_POISONED",
        }
    }

    /// All L3 WASM sandbox, contract, and certification errors fail closed and block new
    /// risk-increasing actions while keeping the host runtime alive for observation/cancel/recovery.
    pub const fn is_fail_closed(&self) -> bool {
        true
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::HostInitialization(msg) => write!(f, "{}: {msg}", self.code()),
            Self::InvalidBudget(msg) => write!(f, "{}: {msg}", self.code()),
            Self::InvalidArtifact(msg) => write!(f, "{}: {msg}", self.code()),
            Self::Sha256Mismatch { expected, actual } => {
                write!(f, "{}: expected {expected}, got {actual}", self.code())
            }
            Self::UnsupportedContractVersion { expected, actual } => {
                write!(f, "{}: expected {expected}, got {actual}", self.code())
            }
            Self::ForbiddenImport { import_name } => {
                write!(f, "{}: forbidden guest import '{import_name}'", self.code())
            }
            Self::ContractExportMismatch { expected, detail } => {
                write!(f, "{}: expected {expected} ({detail})", self.code())
            }
            Self::FuelExhausted { limit } => {
                write!(f, "{}: call exhausted fuel budget {limit}", self.code())
            }
            Self::MemoryLimitExceeded { limit_bytes } => {
                write!(
                    f,
                    "{}: guest exceeded linear memory limit {limit_bytes} bytes",
                    self.code()
                )
            }
            Self::HostLiftLimitExceeded { limit_bytes } => {
                write!(
                    f,
                    "{}: guest return payload exceeded host lift memory budget {limit_bytes} bytes",
                    self.code()
                )
            }
            Self::GuestTrap(msg) => write!(f, "{}: {msg}", self.code()),
            Self::GuestError { code, message } => {
                write!(f, "{}: guest error {code}: {message}", self.code())
            }
            Self::InvalidGuestOutput(msg) => write!(f, "{}: {msg}", self.code()),
            Self::InvalidHostInput(msg) => write!(f, "{}: {msg}", self.code()),
            Self::CertificationFailed { stage, reason } => {
                write!(f, "{}: [{stage}] {reason}", self.code())
            }
            Self::PluginNotFound { plugin_id } => {
                write!(f, "{}: plugin '{plugin_id}' not loaded", self.code())
            }
            Self::PluginAlreadyLoaded { plugin_id } => {
                write!(f, "{}: plugin '{plugin_id}' is already loaded", self.code())
            }
            Self::BindingMismatch { plugin_id, detail } => {
                write!(f, "{}: plugin '{plugin_id}' ({detail})", self.code())
            }
            Self::LockPoisoned => write!(f, "{}", self.code()),
        }
    }
}

impl std::error::Error for Error {}

pub(crate) fn validate_non_empty_id(value: &str, field: &str) -> Result<()> {
    if value.trim().is_empty() || value.len() > 256 {
        return Err(Error::InvalidHostInput(format!(
            "{field} must be non-empty and <= 256 bytes"
        )));
    }
    Ok(())
}

pub(crate) fn validate_canonical_parameters(params: &BTreeMap<String, String>) -> Result<()> {
    if params.len() > MAX_CANONICAL_PARAMETERS {
        return Err(Error::InvalidHostInput(format!(
            "canonical_parameters count {} exceeds limit {MAX_CANONICAL_PARAMETERS}",
            params.len()
        )));
    }
    for (key, value) in params {
        if key.trim().is_empty() || key.len() > MAX_PARAMETER_KEY_BYTES {
            return Err(Error::InvalidHostInput(format!(
                "canonical parameter key must be non-empty and <= {MAX_PARAMETER_KEY_BYTES} bytes"
            )));
        }
        if value.len() > MAX_PARAMETER_VALUE_BYTES {
            return Err(Error::InvalidHostInput(format!(
                "canonical parameter '{key}' value length {} exceeds {MAX_PARAMETER_VALUE_BYTES} bytes",
                value.len()
            )));
        }
    }
    Ok(())
}

fn is_valid_q12_plain_decimal_str(raw: &str, require_trimmed_fraction: bool) -> bool {
    // Max plain length: optional '-' (1) + 28 int digits + '.' (1) + 12 frac digits = 42.
    if raw.is_empty() || raw.len() > 42 || raw.trim() != raw {
        return false;
    }
    let (is_negative, body) = match raw.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, raw),
    };
    if body.is_empty() {
        return false;
    }
    let (int_part, frac_part) = match body.split_once('.') {
        Some((i, f)) => (i, Some(f)),
        None => (body, None),
    };
    // Integer part must be "0" or a non-zero-prefixed ASCII digit string of <= 28 digits.
    if int_part.is_empty()
        || int_part.len() > MAX_DECIMAL_PRECISION
        || !int_part.bytes().all(|b| b.is_ascii_digit())
    {
        return false;
    }
    if int_part.len() > 1 && int_part.starts_with('0') {
        return false;
    }
    // Fractional part (if present) must be non-empty, <= Q12 scale, and all ASCII digits.
    if let Some(frac) = frac_part {
        if frac.is_empty()
            || frac.len() > MAX_DECIMAL_SCALE
            || !frac.bytes().all(|b| b.is_ascii_digit())
        {
            return false;
        }
        if require_trimmed_fraction && frac.ends_with('0') {
            return false;
        }
    }
    // Trim trailing fractional zeros when computing significant digits and checking signed zero.
    let trimmed_frac = frac_part.map(|f| f.trim_end_matches('0')).unwrap_or("");
    let int_is_zero = int_part == "0";
    let frac_is_zero = trimmed_frac.is_empty();
    if int_is_zero && frac_is_zero {
        // Reject negative zero ("-0", "-0.00", etc.); allow "0" (and "0.00" when not trimmed).
        return !is_negative;
    }

    let sig_digits = if int_is_zero {
        trimmed_frac.trim_start_matches('0').len()
    } else {
        int_part.len() + trimmed_frac.len()
    };
    sig_digits > 0 && sig_digits <= MAX_DECIMAL_PRECISION
}

/// Formats a host `Decimal` into a canonical normalized plain base-10 string under
/// `DECIMAL28_HALF_EVEN_Q12_V1` (never scientific notation, never `-0`, never trailing fractional zeros).
pub(crate) fn format_host_decimal(value: &Decimal, field: &str) -> Result<String> {
    let zero = Decimal::from(0);
    if *value == zero {
        return Ok("0".to_owned());
    }
    let normalized = value.normalized();
    let (_, scale) = normalized.as_bigint_and_exponent();
    if scale > MAX_DECIMAL_SCALE as i64 || scale < -(MAX_DECIMAL_PRECISION as i64) {
        return Err(Error::InvalidHostInput(format!(
            "{field} exceeds DECIMAL28_HALF_EVEN_Q12_V1 scale bounds"
        )));
    }
    if normalized.digits() > MAX_DECIMAL_PRECISION as u64 {
        return Err(Error::InvalidHostInput(format!(
            "{field} exceeds DECIMAL28_HALF_EVEN_Q12_V1 precision ({MAX_DECIMAL_PRECISION})"
        )));
    }
    let plain = normalized.to_plain_string();
    if !is_valid_q12_plain_decimal_str(&plain, true) {
        return Err(Error::InvalidHostInput(format!(
            "{field} cannot be encoded as canonical DECIMAL28_HALF_EVEN_Q12_V1 plain decimal: {plain:?}"
        )));
    }
    Ok(plain)
}

/// Parses and validates a guest decimal string under strict `DECIMAL28_HALF_EVEN_Q12_V1`
/// plain base-10 encoding (rejects scientific notation, `-0`, whitespace, out-of-range precision/scale).
pub(crate) fn parse_guest_decimal(raw: &str, field: &str) -> Result<Decimal> {
    if !is_valid_q12_plain_decimal_str(raw, false) {
        return Err(Error::InvalidGuestOutput(format!(
            "{field} is not a canonical DECIMAL28_HALF_EVEN_Q12_V1 plain decimal: {raw:?}"
        )));
    }
    let parsed: Decimal = raw.parse().map_err(|_| {
        Error::InvalidGuestOutput(format!(
            "{field} is not a canonical DECIMAL28_HALF_EVEN_Q12_V1 plain decimal: {raw:?}"
        ))
    })?;
    let zero = Decimal::from(0);
    if parsed == zero {
        Ok(zero)
    } else {
        Ok(parsed.normalized())
    }
}
