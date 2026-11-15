//! Research 与回测共用的有限输入准备。此模块不创建 Run，不授予交易权限。
use super::research_dataset::Dataset;
use super::{
    factor_build::{BuildError, FactorBuildService, ReadyFactorBinding},
    job_contract::FrozenJobBinding,
    research_dataset::NativeMaterializationPlan,
    source_access::{Permission, Selection, Session},
};
use crate::{
    bootstrap::deployment::SemanticStoreId,
    persistence::market_data::{self, Scope, Storage},
};
use onlyalpha_domain::{
    market::OnlyBar,
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use onlyalpha_market_data::finite_input::Axis;
use serde_json::{Value, json};
use std::time::{Duration, Instant};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InputError {
    Invalid,
    BudgetExceeded,
    MissingEvidence,
    Unavailable,
    Mismatch,
    Forbidden,
    NotReady,
    Unknown,
}
impl std::fmt::Display for InputError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "JOB_INPUT_{self:?}")
    }
}
impl std::error::Error for InputError {}

/// 上限来自已有受控配置；调用方不能借此扩大物理存储的原有上限。
#[derive(Clone, Copy, Debug)]
pub struct MemoryBudget {
    rows: usize,
    bytes: usize,
}
impl MemoryBudget {
    pub fn new(rows: usize, bytes: usize) -> Result<Self, InputError> {
        if rows == 0 || rows > 1_000_000 || bytes == 0 || bytes > 128 * 1024 * 1024 {
            return Err(InputError::Invalid);
        }
        Ok(Self { rows, bytes })
    }
    pub fn check(&self, rows: u64, bytes: usize) -> Result<(), InputError> {
        if usize::try_from(rows).ok().is_none_or(|n| n > self.rows) || bytes > self.bytes {
            return Err(InputError::BudgetExceeded);
        }
        Ok(())
    }
    pub fn rows(&self) -> usize {
        self.rows
    }
    pub fn bytes(&self) -> usize {
        self.bytes
    }
}

/// 兼容迁移中的已保留 Dataset 身份；只校验值，来源和权限由 owning loader 验证。
pub(crate) fn ordered_bars(dataset: &Dataset) -> Result<Vec<OnlyBar>, &'static str> {
    const INVALID: &str = "JOB_INPUT_MARKET_AXIS_MISMATCH";
    let definition = dataset.definition();
    let ns = |key: &str| -> Result<i64, &'static str> {
        let time: OnlyUtcDateTime = definition["time_range"][key]
            .as_str()
            .ok_or(INVALID)?
            .parse()
            .map_err(|_| INVALID)?;
        OnlyTimestamp::from_datetime(time)
            .unix_nanos()
            .try_into()
            .map_err(|_| INVALID)
    };
    if definition["instruments"].as_array().map(Vec::len) != Some(1)
        || definition["bar_semantic"]["formation"]["kind"] != "FIXED_DURATION"
        || definition["bar_semantic"]["formation"]["window_minutes"]
            != definition["bar_semantic"]["formation"]["stride_minutes"]
    {
        return Err(INVALID);
    }
    let stride = definition["bar_semantic"]["formation"]["stride_minutes"]
        .as_i64()
        .and_then(|n| n.checked_mul(60_000_000_000))
        .ok_or(INVALID)?;
    let axis =
        Axis::new(ns("start")?, ns("end")?, stride, dataset.rows().len()).map_err(|_| INVALID)?;
    let bars = dataset.bars()?;
    for (index, bar) in bars.iter().enumerate() {
        axis.check(index, bar).map_err(|_| INVALID)?;
    }
    Ok(bars)
}

/// Timings are observations only; never part of frozen business identity.
#[derive(Debug, Default)]
pub struct InputTimings {
    pub total: Duration,
    pub budget_meter: Duration,
    pub final_guard: Duration,
    pub program_preflight: Duration,
    pub physical: market_data::ReadTimings,
    pub source_read: Duration,
    pub dataset_prepare: Duration,
    pub allocation: Duration,
    pub normalize: Duration,
    pub sort: Duration,
    pub digest: Duration,
    pub axis: Duration,
    pub identity: Duration,
    pub programs: Duration,
}
/// Only an owning loader can construct this complete input. Dropped on any failure.
/// Proves market/program inputs only; execution/Runtime/rules remain the corresponding owners' responsibility.
pub struct PreparedJobInput {
    binding: String,
    source_evidence: Value,
    dataset: Dataset,
    bars: Vec<OnlyBar>,
    factors: Vec<ReadyFactorBinding>,
    timings: InputTimings,
}
impl PreparedJobInput {
    pub fn binding_fingerprint(&self) -> &str {
        &self.binding
    }
    pub fn source_evidence(&self) -> &Value {
        &self.source_evidence
    }
    pub fn dataset(&self) -> &Dataset {
        &self.dataset
    }
    pub fn bars(&self) -> &[OnlyBar] {
        &self.bars
    }
    pub fn factors(&self) -> &[ReadyFactorBinding] {
        &self.factors
    }
    pub fn timings(&self) -> &InputTimings {
        &self.timings
    }
}
pub struct JobInputLoader<'a, 's, 'f> {
    source: &'a mut Storage<'s>,
    factors: &'a mut FactorBuildService<'f>,
    session: &'a Session,
    selection: &'a Selection,
}
fn market_error(error: market_data::Error) -> InputError {
    match error {
        market_data::Error::NotFound | market_data::Error::MissingEvidence => {
            InputError::MissingEvidence
        }
        market_data::Error::Unavailable
        | market_data::Error::Busy
        | market_data::Error::Stopped => InputError::Unavailable,
        market_data::Error::Unknown => InputError::Unknown,
        market_data::Error::BudgetExceeded => InputError::BudgetExceeded,
        _ => InputError::Mismatch,
    }
}
fn factor_error(error: BuildError) -> InputError {
    use crate::persistence::job_publication::PublicationError;
    match error {
        BuildError::NotReady => InputError::NotReady,
        BuildError::Unknown | BuildError::Storage(PublicationError::OutcomeUnknown) => {
            InputError::Unknown
        }
        BuildError::Storage(PublicationError::Unavailable) => InputError::Unavailable,
        BuildError::Storage(PublicationError::MissingEvidence) => InputError::MissingEvidence,
        BuildError::Storage(PublicationError::Denied) => InputError::Forbidden,
        BuildError::Storage(PublicationError::BudgetExceeded) => InputError::BudgetExceeded,
        _ => InputError::Mismatch,
    }
}
fn dataset_error(error: &'static str) -> InputError {
    if error == "DATASET_READ_BUDGET_EXCEEDED" {
        InputError::BudgetExceeded
    } else {
        InputError::Mismatch
    }
}
#[cfg(test)]
mod dataset_error_tests {
    #[test]
    fn dataset_budget_is_not_a_content_mismatch() {
        assert_eq!(
            super::dataset_error("DATASET_READ_BUDGET_EXCEEDED"),
            super::InputError::BudgetExceeded
        );
        assert_eq!(
            super::dataset_error("DATASET_MARKET_DATA_SCOPE_MISMATCH"),
            super::InputError::Mismatch
        );
    }
}
fn pin(value: &Value) -> Result<&str, InputError> {
    value.as_str().ok_or(InputError::Mismatch)
}
fn digest(value: &Value) -> Result<String, InputError> {
    super::factor_content::hash(value).map_err(|_| InputError::Mismatch)
}
fn utc(ns: i64) -> Result<String, InputError> {
    OnlyTimestamp::from_unix_nanos(ns.into())
        .to_datetime_exact()
        .map(|t| t.to_string())
        .map_err(|_| InputError::Mismatch)
}
impl<'a, 's, 'f> JobInputLoader<'a, 's, 'f> {
    pub fn new(
        source: &'a mut Storage<'s>,
        factors: &'a mut FactorBuildService<'f>,
        session: &'a Session,
        selection: &'a Selection,
    ) -> Self {
        Self {
            source,
            factors,
            session,
            selection,
        }
    }
    fn access(&self, binding: &FrozenJobBinding) -> Result<(), InputError> {
        if self
            .session
            .subject_id()
            .map_err(|_| InputError::Forbidden)?
            != binding.owner()
            || self.factors.namespace().value() != binding.namespace()
        {
            return Err(InputError::Forbidden);
        }
        self.session
            .require_selection(self.selection, Permission::ClosedHistory)
            .map_err(|_| InputError::Forbidden)
    }
    pub async fn load(
        &mut self,
        binding: &FrozenJobBinding,
        budget: &MemoryBudget,
    ) -> Result<PreparedJobInput, InputError> {
        let loading = Instant::now();
        self.access(binding)?;
        let market = binding.market().record();
        let rows = market["rows"].as_u64().ok_or(InputError::Invalid)?;
        // Reserve the row vector and a bounded working slice before source I/O.
        let mut allocation = usize::try_from(rows)
            .ok()
            .and_then(|n| {
                n.checked_mul(std::mem::size_of::<OnlyBar>() + std::mem::size_of::<Value>())
            })
            .ok_or(InputError::BudgetExceeded)?;
        budget.check(rows, allocation)?;
        let preflight = Instant::now();
        for factor in binding.factor_bindings() {
            self.access(binding)?;
            let bytes = self
                .factors
                .read_memory_requirement(&factor)
                .await
                .map_err(factor_error)?;
            allocation = allocation
                .checked_add(bytes)
                .ok_or(InputError::BudgetExceeded)?;
            budget.check(rows, allocation)?;
        }
        let program_preflight = preflight.elapsed();
        let source_bytes = budget
            .bytes()
            .checked_sub(allocation)
            .map(|n| n / 4)
            .filter(|n| *n > 0)
            .ok_or(InputError::BudgetExceeded)?;
        let namespace =
            SemanticStoreId::new(binding.namespace()).map_err(|_| InputError::Invalid)?;
        let source_started = Instant::now();
        self.source
            .verify_namespace(&namespace)
            .await
            .map_err(|e| match e {
                crate::bootstrap::deployment::Error::Unavailable => InputError::Unavailable,
                crate::bootstrap::deployment::Error::Missing
                | crate::bootstrap::deployment::Error::BindingMissing => {
                    InputError::MissingEvidence
                }
                _ => InputError::Mismatch,
            })?;
        let id = format!("market-data-revision:{}", pin(&market["source_revision"])?);
        let revision = self
            .source
            .revision_bounded(&id, budget.rows(), source_bytes)
            .await
            .map_err(market_error)?;
        let raw = revision.revision();
        let scope = Scope::from_record(&raw["scope"]).map_err(market_error)?;
        let scope_record = scope.to_record();
        let plan = &scope_record["bar_construction"]["plan"];
        if scope_record["source_id"] != self.selection.source_id()
            || plan["integration_revision_fingerprint"] != self.selection.reference().revision()
            || market["instruments"] != json!([scope_record["instrument_id"]])
            || market["versions"] != json!([digest(&scope_record["data_version"])?])
            || market["bar_semantic"] != digest(&plan["target_semantic"])?
        {
            return Err(InputError::Mismatch);
        }
        let start = market["start_ns"].as_i64().ok_or(InputError::Invalid)?;
        let end = market["end_ns"].as_i64().ok_or(InputError::Invalid)?;
        let definition = json!({"schema_version":2,"dataset_type":"HISTORICAL_BAR","instruments":market["instruments"],"bar_semantic":plan["target_semantic"],"time_range":{"start":utc(start)?,"end":utc(end)?},"quality_policy":"STRICT","closed_only":true});
        let materializer =
            NativeMaterializationPlan::new(&definition, &id, scope.clone(), budget.rows())
                .map_err(|_| InputError::Mismatch)?;
        let mut timings = InputTimings {
            program_preflight,
            ..Default::default()
        };
        let (input, physical) = self
            .source
            .read_dataset_input_profiled(&id, &scope, budget.rows(), source_bytes)
            .await
            .map_err(market_error)?;
        timings.source_read = source_started.elapsed();
        timings.physical = physical;
        let metering = Instant::now();
        // Charge retained input and output vectors before normalization clones them.
        let bytes = input.facts().iter().try_fold(allocation, |used, row| {
            used.checked_add(
                row.to_string()
                    .len()
                    .checked_mul(4)
                    .ok_or(InputError::BudgetExceeded)?,
            )
            .ok_or(InputError::BudgetExceeded)
        })?;
        let proof_bytes = input
            .evidence()
            .to_string()
            .len()
            .checked_add(input.segments().to_string().len())
            .and_then(|n| n.checked_mul(4))
            .and_then(|n| n.checked_add(bytes))
            .ok_or(InputError::BudgetExceeded)?;
        budget.check(rows, proof_bytes)?;
        timings.budget_meter = metering.elapsed();
        let started = Instant::now();
        let (dataset, dataset_timings) = materializer
            .dataset_profiled(&input)
            .map_err(dataset_error)?;
        timings.dataset_prepare = started.elapsed();
        timings.normalize = dataset_timings.normalize;
        timings.allocation = dataset_timings.allocation;
        timings.sort = dataset_timings.sort;
        timings.digest = dataset_timings.digest;
        let started = Instant::now();
        let bars = ordered_bars(&dataset).map_err(|_| InputError::Mismatch)?;
        timings.axis = started.elapsed();
        let started = Instant::now();
        let axis = Value::Array(
            dataset
                .rows()
                .iter()
                .map(|row| {
                    json!([
                        row["instrument_id"],
                        row["bar_start_ns"],
                        row["bar_end_ns"],
                        row["ts_event_ns"],
                        row["revision"]
                    ])
                })
                .collect(),
        );
        let segments = raw["segment_refs"]
            .as_array()
            .ok_or(InputError::Mismatch)?
            .iter()
            .map(digest)
            .collect::<Result<std::collections::BTreeSet<_>, _>>()?;
        let seal = input.revision().seal();
        let seal = pin(&seal["seal_id"])?
            .strip_prefix("seal:")
            .ok_or(InputError::Mismatch)?;
        if dataset.snapshot_fingerprint() != pin(&market["dataset_snapshot"])?
            || dataset.content_fingerprint() != pin(&market["content"])?
            || market["rows"] != bars.len() as u64
            || market["axis"] != digest(&axis)?
            || market["segments"] != json!(segments)
            || market["seals"] != json!([seal])
        {
            return Err(InputError::Mismatch);
        }
        timings.identity = started.elapsed();
        let started = Instant::now();
        let mut factors = Vec::new();
        for factor in binding.factor_bindings() {
            self.access(binding)?;
            factors.push(
                self.factors
                    .resolve_frozen_binding(&factor)
                    .await
                    .map_err(factor_error)?,
            );
        }
        timings.programs = started.elapsed();
        let final_guard = Instant::now();
        self.access(binding)?;
        self.source
            .verify_namespace(&namespace)
            .await
            .map_err(|error| match error {
                crate::bootstrap::deployment::Error::Unavailable => InputError::Unavailable,
                crate::bootstrap::deployment::Error::Missing
                | crate::bootstrap::deployment::Error::BindingMissing => {
                    InputError::MissingEvidence
                }
                _ => InputError::Mismatch,
            })?;
        let source_evidence = json!({"evidence":input.evidence(),"segments":input.segments()});
        timings.final_guard = final_guard.elapsed();
        timings.total = loading.elapsed();
        Ok(PreparedJobInput {
            binding: binding.fingerprint().to_owned(),
            source_evidence,
            dataset,
            bars,
            factors,
            timings,
        })
    }
}
