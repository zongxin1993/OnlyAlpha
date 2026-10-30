//! Native owning durable market-data catalog, exact physical store and recovery.
//! Host supplies actual PG sessions and bounded explicit CH connection settings.
mod catalog;
mod coverage;
mod model;
mod physical;
mod recovery;
pub use catalog::{AcquisitionAttempt, AcquisitionIntent, Catalog, ExecutionLease};
pub use coverage::{WindowPlan, coverage, deduplicate_facts, plan_bar_window};
pub(crate) use model::validate_retained_input;
use model::*;
pub use model::{
    CoverageStatus, Manifest, PhysicalProof, Scope, SealedInput, SealedRevision, Segment,
};
pub use physical::{ClickHouse, ClickHouseConfig, PhysicalState};
pub use recovery::{DrainBoundary, DrainOutcome, RevisionPublication, Storage, VerifiedRange};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
const TABLES: [&str; 4] = [
    "market_raw_event",
    "market_trade",
    "market_bar",
    "market_reference_price",
];
const MAX_BYTES: usize = 128 * 1024 * 1024;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Invalid,
    Unprovable,
    Unavailable,
    Conflict,
    Unknown,
    Busy,
    Stopped,
    NotFound,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "MARKET_DATA_INPUT_INVALID",
            Self::Unprovable => "MARKET_DATA_EVIDENCE_UNPROVABLE",
            Self::Unavailable => "MARKET_DATA_STORE_UNAVAILABLE",
            Self::Conflict => "MARKET_DATA_IDENTITY_CONFLICT",
            Self::Unknown => "MARKET_DATA_SUBMISSION_UNKNOWN",
            Self::Busy => "MARKET_DATA_EXECUTION_ACTIVE",
            Self::Stopped => "MARKET_DATA_RECOVERY_STOPPED",
            Self::NotFound => "SEALED_REVISION_NOT_FOUND",
        }
    }
}
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}
type Result<T> = std::result::Result<T, Error>;
impl From<tokio_postgres::Error> for Error {
    fn from(_: tokio_postgres::Error) -> Self {
        Self::Unavailable
    }
}
impl From<crate::persistence::market_data_wal::Error> for Error {
    fn from(e: crate::persistence::market_data_wal::Error) -> Self {
        match e {
            crate::persistence::market_data_wal::Error::Unavailable
            | crate::persistence::market_data_wal::Error::Capacity => Self::Unavailable,
            _ => Self::Unprovable,
        }
    }
}
fn hash(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
fn canonical(v: &Value) -> Result<String> {
    onlyalpha_metadata_json::canonical_json(&v.to_string(), MAX_BYTES * 4).map_err(|e| {
        if e == onlyalpha_metadata_json::Error::Unavailable {
            Error::Unavailable
        } else {
            Error::Invalid
        }
    })
}
fn fingerprint(v: &Value) -> Result<String> {
    Ok(hash(canonical(v)?.as_bytes()))
}
fn decode(raw: &str) -> Result<Value> {
    if raw.len() > MAX_BYTES {
        return Err(Error::Unavailable);
    }
    let before = onlyalpha_metadata_json::canonical_json(raw, MAX_BYTES * 4).map_err(|e| {
        if e == onlyalpha_metadata_json::Error::Unavailable {
            Error::Unavailable
        } else {
            Error::Unprovable
        }
    })?;
    let v: Value = serde_json::from_str(raw).map_err(|_| Error::Unprovable)?;
    if before != canonical(&v)? {
        return Err(Error::Unprovable);
    }
    Ok(v)
}
fn text(v: &Value) -> Result<&str> {
    v.as_str()
        .filter(|s| !s.trim().is_empty())
        .ok_or(Error::Unprovable)
}
fn optional_text(v: &Value) -> Result<Option<&str>> {
    if v.is_null() {
        Ok(None)
    } else {
        Ok(Some(text(v)?))
    }
}
fn integer(v: &Value) -> Result<i64> {
    v.as_i64().ok_or(Error::Unprovable)
}
fn array(v: &Value) -> Result<&Vec<Value>> {
    v.as_array().ok_or(Error::Unprovable)
}
fn exact_keys(v: &Value, keys: &[&str]) -> Result<()> {
    let o = v.as_object().ok_or(Error::Unprovable)?;
    if o.len() != keys.len() || keys.iter().any(|k| !o.contains_key(*k)) {
        Err(Error::Unprovable)
    } else {
        Ok(())
    }
}

// Bound the combined retained metadata/payload of one operation, not only each
// individually bounded database response. Exhaustion is never certified absence.
fn charge(used: &mut usize, value: &Value, limit: usize) -> Result<()> {
    *used = used
        .checked_add(value.to_string().len())
        .ok_or(Error::Unavailable)?;
    if *used > limit {
        return Err(Error::Unavailable);
    }
    Ok(())
}
fn charge_revision(used: &mut usize, revision: &SealedRevision, limit: usize) -> Result<()> {
    for value in [
        &revision.revision,
        &revision.seal,
        &revision.manifest.record,
    ] {
        charge(used, value, limit)?;
    }
    Ok(())
}
