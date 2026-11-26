//! 持续交易的内核计划、已提交事实的投影恢复，以及异步持久化端口。
use crate::{RunConfiguration, session::{fingerprint, sha}};
use onlyalpha_execution::{Components, CommitIntent, Error, Prepared, Record, Store, coordinate};
use serde_json::{Value, json};
use std::{fmt, future::Future};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DurabilityError {
    Rejected(String),
    Unavailable,
    UnknownCommit,
}

impl fmt::Display for DurabilityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Rejected(code) => f.write_str(code),
            Self::Unavailable => f.write_str("TRADING_FACTS_UNAVAILABLE"),
            Self::UnknownCommit => f.write_str("TRADING_COMMIT_UNKNOWN"),
        }
    }
}

impl std::error::Error for DurabilityError {}

impl From<Error> for DurabilityError {
    fn from(error: Error) -> Self {
        Self::Rejected(error.0)
    }
}

type Result<T> = std::result::Result<T, DurabilityError>;

#[derive(Debug, Clone)]
pub struct TradingBinding {
    key: String,
    fingerprint: String,
    configuration: RunConfiguration,
    kernel_artifact: String,
}

impl TradingBinding {
    pub fn new(configuration: RunConfiguration, kernel_artifact: &str) -> Result<Self> {
        let config = configuration.record();
        if !matches!(config["runtime_kind"].as_str(), Some("SIM" | "LIVE")) || !sha(kernel_artifact) {
            return Err(DurabilityError::Rejected("TRADING_BINDING_INVALID".into()));
        }
        let key = fingerprint(&json!({"schema_version":1,"engine":config["engine"],"runtime":config["runtime"],"generation":config["generation"]}));
        let fingerprint = fingerprint(&json!({"schema_version":1,"stream":key,"configuration":configuration.fingerprint(),"kernel_artifact":kernel_artifact}));
        Ok(Self { key, fingerprint, configuration, kernel_artifact: kernel_artifact.into() })
    }

    pub fn key(&self) -> &str { &self.key }
    pub fn fingerprint(&self) -> &str { &self.fingerprint }
    pub fn configuration(&self) -> &RunConfiguration { &self.configuration }
    pub fn kernel_artifact(&self) -> &str { &self.kernel_artifact }
}

#[derive(Debug)]
pub struct PreparedTradingFacts {
    binding: TradingBinding,
    prepared: Prepared,
    predecessor: Option<(String, String)>,
}

impl PreparedTradingFacts {
    pub fn binding(&self) -> &TradingBinding { &self.binding }
    pub fn prepared(&self) -> &Prepared { &self.prepared }
    pub fn predecessor(&self) -> Option<(&str, &str)> {
        self.predecessor.as_ref().map(|(id, digest)| (id.as_str(), digest.as_str()))
    }
}

/// 回执记录精确提交的读回结果，派单权限由后端单独验证。
#[derive(Debug, PartialEq, Eq)]
pub struct DurableCommitReceipt {
    binding: String,
    transaction_id: String,
    sequence: u64,
    payload_fingerprint: String,
    ready: bool,
}

impl DurableCommitReceipt {
    pub fn from_record(facts: &PreparedTradingFacts, stored_binding: &str, record: &Record) -> Result<Self> {
        let plan = facts.prepared();
        if stored_binding != facts.binding().fingerprint() || record.prepared() != plan {
            return Err(DurabilityError::Rejected("TRADING_COMMIT_CONFLICT".into()));
        }
        Ok(Self {
            binding: stored_binding.into(), transaction_id: plan.id().into(),
            sequence: plan.sequence(), payload_fingerprint: plan.payload_fingerprint().into(),
            ready: record.ready(),
        })
    }

    pub fn binding_fingerprint(&self) -> &str { &self.binding }
    pub fn transaction_id(&self) -> &str { &self.transaction_id }
    pub fn sequence(&self) -> u64 { self.sequence }
    pub fn payload_fingerprint(&self) -> &str { &self.payload_fingerprint }
    pub fn ready(&self) -> bool { self.ready }
}

pub trait DurableFactPort {
    fn commit(&mut self, prepared: &PreparedTradingFacts) -> impl Future<Output = Result<DurableCommitReceipt>> + Send;
    fn load_recovery(&mut self, binding: &TradingBinding) -> impl Future<Output = Result<RecoveryFacts>> + Send;
}

pub struct RecoveryFacts {
    binding: TradingBinding,
    records: Vec<Record>,
    projected: Replay,
    owners: Components,
}

impl RecoveryFacts {
    /// 水位、绑定和原记录必须由仓储在同一快照内读出。
    pub fn from_records(binding: &TradingBinding, stored_binding: &str, expected_head: u64, records: Vec<Record>) -> Result<Self> {
        if stored_binding != binding.fingerprint() || u64::try_from(records.len()) != Ok(expected_head) {
            return Err(DurabilityError::Rejected("TRADING_HISTORY_INCOMPLETE".into()));
        }
        let mut owners = Components::new(binding.configuration().record().clone())?;
        let mut projected = Replay::default();
        for row in &records {
            let stored = row.prepared();
            let original = owners.prepare(&projected, stored.input())?;
            if original != *stored || (!row.ready() && stored.sequence() != expected_head) {
                return Err(DurabilityError::Rejected("TRADING_HISTORY_CONFLICT".into()));
            }
            projected.push_observed(row.clone());
            coordinate(&mut projected, &mut owners, stored)?;
        }
        if owners.reconcile(&projected)?.record()["status"] != "MATCHED" {
            return Err(DurabilityError::Rejected("TRADING_RECONCILIATION_MISMATCH".into()));
        }
        Ok(Self { binding: binding.clone(), records, projected, owners })
    }

    pub fn binding(&self) -> &TradingBinding { &self.binding }
    pub fn records(&self) -> &[Record] { &self.records }
    pub fn unprojected(&self) -> Option<&Record> { self.records.last().filter(|row| !row.ready()) }
    pub fn state(&self) -> Result<Value> { Ok(self.owners.state(&self.projected)?) }

    pub fn observe_input(&self, input: &Value) -> Result<Option<&Record>> {
        let id = onlyalpha_execution::input_id(input)?;
        let found = self
            .records
            .iter()
            .find(|row| row.prepared().input()["input_id"] == id);
        match found {
            Some(row) if row.prepared().input() != input => {
                Err(DurabilityError::Rejected("TRADING_INPUT_CONFLICT".into()))
            }
            _ => Ok(found),
        }
    }

    pub fn prepare(&self, input: &Value) -> Result<PreparedTradingFacts> {
        if self.unprojected().is_some() {
            return Err(DurabilityError::Rejected("TRADING_PROJECTION_PENDING".into()));
        }
        let prepared = self.owners.prepare(&self.projected, input)?;
        let predecessor = self.records.last().map(|row| {
            let plan = row.prepared();
            (plan.id().into(), plan.payload_fingerprint().into())
        });
        Ok(PreparedTradingFacts { binding: self.binding.clone(), prepared, predecessor })
    }
}

// Isolated proof replay only. It cannot commit new authority or publish external Events.
#[derive(Default)]
pub(crate) struct Replay {
    rows: Vec<Record>,
}
impl Replay {
    pub(crate) fn push_observed(&mut self, row: Record) {
        self.rows.push(row);
    }
}
#[cfg(test)]
std::thread_local! {
    static CHECKPOINT_PROOF_GETS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}
impl Store for Replay {
    fn head(&self) -> std::result::Result<u64, Error> {
        Ok(self.rows.len() as u64)
    }
    fn get(&self, n: u64) -> std::result::Result<Option<Record>, Error> {
        #[cfg(test)]
        CHECKPOINT_PROOF_GETS.with(|reads| reads.set(reads.get() + 1));
        Ok(self
            .rows
            .get(n.checked_sub(1).ok_or_else(|| Error("RUNTIME_STORE_SEQUENCE".to_string()))? as usize)
            .map(Record::compact_snapshot))
    }
    fn commit(&mut self, _: &CommitIntent) -> std::result::Result<Record, Error> {
        Err(Error("RUNTIME_STORE_READ_ONLY_REPLAY".to_string()))
    }
    fn mark_ready(&mut self, n: u64) -> std::result::Result<(), Error> {
        let mut v = self.rows[n as usize - 1].record();
        v["ready"] = json!(true);
        self.rows[n as usize - 1] = Record::decode(&v)?;
        Ok(())
    }
    fn acknowledge(&mut self, _: u64) -> std::result::Result<(), Error> {
        Err(Error("RUNTIME_STORE_READ_ONLY_REPLAY".to_string()))
    }
}

#[cfg(test)]
#[path = "tests/durability_tests.rs"]
mod tests;
