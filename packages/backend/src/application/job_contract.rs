//! Frozen finite-job value contracts. Parsing checks values, never authenticates
//! a certificate, source, publication, execution owner or LIVE permission.
//! This module is not wired to job admission or persistence in phase one.
mod binding;
mod result;
pub use binding::{FactorExecutionBinding, FrozenJobBinding};
pub use result::{
    MemberKind, ResultMember, ResultPlan, result_publication_required, validate_terminal_result,
};
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use serde_json::Value;

/// Technical failure classes remain distinct from domain terminal states.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ContractError {
    Invalid,
    MissingEvidence,
    Unavailable,
    Mismatch,
    NotReady,
    OutcomeUnknown,
    BudgetExceeded,
    UnexpectedResult,
}
impl std::fmt::Display for ContractError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "JOB_CONTRACT_{self:?}")
    }
}
impl std::error::Error for ContractError {}
type Result<T> = std::result::Result<T, ContractError>;
const MAX_BYTES: usize = 256 * 1024;
const MAX_MEMBERS: usize = 1024;
fn decode<T: DeserializeOwned>(value: &Value) -> Result<T> {
    if value.to_string().len() > MAX_BYTES {
        return Err(ContractError::BudgetExceeded);
    }
    serde_json::from_value(value.clone()).map_err(|_| ContractError::Invalid)
}
fn fingerprint(value: &impl Serialize) -> Result<String> {
    let record = serde_json::to_value(value).map_err(|_| ContractError::Invalid)?;
    crate::application::factor_content::hash(&record).map_err(|_| ContractError::Invalid)
}
fn pin(value: &str) -> Result<()> {
    if crate::is_sha256_hex(value) {
        Ok(())
    } else {
        Err(ContractError::Invalid)
    }
}
fn text(value: &str) -> Result<()> {
    if value.trim().is_empty() || value.len() > 512 || value.chars().any(char::is_control) {
        Err(ContractError::Invalid)
    } else {
        Ok(())
    }
}
fn unique_sorted(values: &mut [String], pins: bool) -> Result<()> {
    if values.is_empty() || values.len() > MAX_MEMBERS {
        return Err(ContractError::Invalid);
    }
    for value in values.iter() {
        if pins {
            pin(value)?;
        } else {
            text(value)?;
        }
    }
    values.sort();
    if values.windows(2).any(|v| v[0] == v[1]) {
        return Err(ContractError::Invalid);
    }
    Ok(())
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum JobKind {
    Research,
    Backtest,
}
/// The state of an exact build/certification binding, not the Run lifecycle.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BuildStatus {
    Building,
    Ready,
    Failed,
}
/// Applies only to factor numerical execution; money/quantity retain their own contracts.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum NumericPolicy {
    #[serde(rename = "DECIMAL28_HALF_EVEN_Q12_V1")]
    Decimal28HalfEvenQ12,
}
