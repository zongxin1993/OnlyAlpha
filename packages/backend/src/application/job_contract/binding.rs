use super::*;
use crate::application::command::uuid4;
use crate::bootstrap::deployment::SemanticStoreId;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct FactorRecord {
    revision: String,
    program: String,
    parameters: String,
    numeric_policy: NumericPolicy,
    certificate: String,
}
/// Claimed immutable references. This value does not prove that a certificate
/// exists or was issued by the build owner; the repository must prove that.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FactorExecutionBinding(FactorRecord);
impl FactorExecutionBinding {
    pub fn from_record(value: &Value) -> Result<Self> {
        let record: FactorRecord = decode(value)?;
        record.validate()?;
        Ok(Self(record))
    }
    /// Compare a request with an owning reader's observation. Unit success is
    /// value agreement only: it is deliberately not an admission capability.
    pub fn check_certificate(&self, status: BuildStatus, observed: &Self) -> Result<()> {
        if status != BuildStatus::Ready {
            return Err(ContractError::NotReady);
        }
        if self != observed {
            return Err(ContractError::Mismatch);
        }
        Ok(())
    }
    pub fn record(&self) -> Value {
        serde_json::to_value(&self.0).expect("serializable binding")
    }
}
impl FactorRecord {
    fn validate(&self) -> Result<()> {
        for value in [
            &self.revision,
            &self.program,
            &self.parameters,
            &self.certificate,
        ] {
            pin(value)?;
        }
        Ok(())
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Scope {
    namespace: String,
    owner: String,
    run_id: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct MarketSliceBinding {
    dataset_snapshot: String,
    source_revision: String,
    bar_semantic: String,
    instruments: Vec<String>,
    start_ns: i64,
    end_ns: i64,
    versions: Vec<String>,
    seals: Vec<String>,
    segments: Vec<String>,
    rows: u64,
    warmup_rows: u64,
    sample_rows: u64,
    axis: String,
    content: String,
}
impl MarketSliceBinding {
    fn validate(&mut self) -> Result<()> {
        for value in [
            &self.dataset_snapshot,
            &self.source_revision,
            &self.bar_semantic,
            &self.axis,
            &self.content,
        ] {
            pin(value)?;
        }
        unique_sorted(&mut self.instruments, false)?;
        for values in [&mut self.versions, &mut self.seals, &mut self.segments] {
            unique_sorted(values, true)?;
        }
        if self.start_ns >= self.end_ns
            || self.sample_rows == 0
            || self.warmup_rows.checked_add(self.sample_rows) != Some(self.rows)
        {
            return Err(ContractError::Invalid);
        }
        Ok(())
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct BindingRecord {
    schema_version: u32,
    kind: JobKind,
    scope: Scope,
    strategy_revision: String,
    signal_graph: String,
    factor_bindings: Vec<FactorRecord>,
    kernel_artifact: String,
    runtime_generation: String,
    initial_state: String,
    execution_configuration: String,
    calendar: String,
    fees: String,
    market_rules: String,
    market: MarketSliceBinding,
    result_plan: super::result::PlanRecord,
}
/// Canonical replay inputs; includes original Run scope, excludes Attempt,
/// host/PID/timing. No deserialize implementation can bypass validation.
#[derive(Clone, Debug)]
pub struct FrozenJobBinding {
    record: BindingRecord,
    fingerprint: String,
}
impl FrozenJobBinding {
    pub fn from_record(value: &Value) -> Result<Self> {
        let mut record: BindingRecord = decode(value)?;
        if record.schema_version != 1 || !uuid4(&record.scope.run_id) {
            return Err(ContractError::Invalid);
        }
        SemanticStoreId::new(&record.scope.namespace).map_err(|_| ContractError::Invalid)?;
        text(&record.scope.owner)?;
        for value in [
            &record.strategy_revision,
            &record.signal_graph,
            &record.kernel_artifact,
            &record.runtime_generation,
            &record.initial_state,
            &record.execution_configuration,
            &record.calendar,
            &record.fees,
            &record.market_rules,
        ] {
            pin(value)?;
        }
        if record.factor_bindings.len() > MAX_MEMBERS {
            return Err(ContractError::BudgetExceeded);
        }
        for binding in &record.factor_bindings {
            binding.validate()?;
        }
        record.factor_bindings.sort_by(|a, b| {
            (&a.revision, &a.program, &a.parameters).cmp(&(&b.revision, &b.program, &b.parameters))
        });
        if record.factor_bindings.windows(2).any(|v| {
            (&v[0].revision, &v[0].program, &v[0].parameters)
                == (&v[1].revision, &v[1].program, &v[1].parameters)
        }) {
            return Err(ContractError::Invalid);
        }
        record.market.validate()?;
        record.result_plan.validate()?;
        if record.kind != record.result_plan.kind {
            return Err(ContractError::Mismatch);
        }
        let fingerprint = fingerprint(&record)?;
        Ok(Self {
            record,
            fingerprint,
        })
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn record(&self) -> Value {
        serde_json::to_value(&self.record).expect("serializable binding")
    }
    pub fn kind(&self) -> JobKind {
        self.record.kind
    }
    pub fn run_id(&self) -> &str {
        &self.record.scope.run_id
    }
    pub fn result_plan(&self) -> ResultPlan {
        ResultPlan(self.record.result_plan.clone())
    }
}
