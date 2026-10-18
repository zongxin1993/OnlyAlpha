//! Per-instance committed state. No clock, transport or algorithm readiness inference.
use crate::{ExecutionBinding, ExecutionCursor, PreparedBatch, Result, record::*};
use serde_json::{Value, json};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StateOutcome {
    Uninitialized,
    Warming,
    Ready,
    Failed,
    Unavailable,
    Unknown,
}
impl StateOutcome {
    fn text(self) -> &'static str {
        match self {
            Self::Uninitialized => "UNINITIALIZED",
            Self::Warming => "WARMING",
            Self::Ready => "READY",
            Self::Failed => "FAILED",
            Self::Unavailable => "UNAVAILABLE",
            Self::Unknown => "UNKNOWN",
        }
    }
    fn parse(v: &Value) -> Result<Self> {
        match text(v)? {
            "UNINITIALIZED" => Ok(Self::Uninitialized),
            "WARMING" => Ok(Self::Warming),
            "READY" => Ok(Self::Ready),
            "FAILED" => Ok(Self::Failed),
            "UNAVAILABLE" => Ok(Self::Unavailable),
            "UNKNOWN" => Ok(Self::Unknown),
            _ => Err(err("STATE_OUTCOME_INVALID")),
        }
    }
    fn failed(self) -> bool {
        matches!(self, Self::Failed | Self::Unavailable | Self::Unknown)
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InputPosition {
    record: Value,
}
impl InputPosition {
    pub fn new(revision: u64, samples: u64, event_ns: &str, input_digest: &str) -> Result<Self> {
        if revision == 0 || samples == 0 {
            return Err(err("POSITION_EMPTY"));
        }
        crate::execution::timestamp(event_ns)?;
        digest(&json!(input_digest))?;
        Ok(Self {
            record: json!({"revision":revision,"samples":samples,"event_ns":event_ns,"input_digest":input_digest}),
        })
    }
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CalculationSnapshot {
    binding: ExecutionBinding,
    cursor: Value,
    outcome: StateOutcome,
    receipt: Option<Value>,
    reason: Option<String>,
}
impl CalculationSnapshot {
    pub fn binding(&self) -> &ExecutionBinding {
        &self.binding
    }
    pub fn outcome(&self) -> StateOutcome {
        self.outcome
    }
    pub fn reason(&self) -> Option<&str> {
        self.reason.as_deref()
    }
    pub fn position(&self) -> Option<InputPosition> {
        self.receipt.as_ref().map(|r| InputPosition { record: json!({"revision":self.cursor["revision"],"samples":self.cursor["samples"],"event_ns":self.cursor["last_event_ns"],"input_digest":r["input_digest"]}) })
    }
    pub fn outputs(&self) -> Option<&Value> {
        self.receipt.as_ref().map(|r| &r["outputs"])
    }
    pub fn quality_flags(&self) -> Vec<&str> {
        self.receipt
            .as_ref()
            .map(|r| {
                r["quality_flags"]
                    .as_array()
                    .expect("validated")
                    .iter()
                    .map(|v| v.as_str().expect("validated"))
                    .collect()
            })
            .unwrap_or_default()
    }
    pub fn to_record(&self) -> Value {
        json!({"schema_version":1,"cursor":self.cursor,"outcome":self.outcome.text(),"receipt":self.receipt,"reason":self.reason})
    }
}
pub fn normalize_result_outputs(value: &Value) -> Result<Value> {
    let outputs = map(value)?;
    if outputs.is_empty() || outputs.len() > 64 {
        return Err(err("OUTPUTS_BUDGET"));
    }
    scalars(value)
}
fn receipt(v: &Value, cursor: &Value) -> Result<()> {
    object(
        v,
        &[
            "cursor",
            "input_digest",
            "outputs",
            "ready",
            "quality_flags",
        ],
    )?;
    if &v["cursor"] != cursor || cursor["samples"].as_u64().unwrap_or(0) == 0 {
        return Err(err("RECEIPT_CURSOR_MISMATCH"));
    }
    digest(&v["input_digest"])?;
    boolean(&v["ready"])?;
    let outputs = map(&v["outputs"])?;
    if outputs.is_empty()
        || outputs.len() > 64
        || normalize_result_outputs(&v["outputs"])? != v["outputs"]
    {
        return Err(err("OUTPUTS_INVALID"));
    }
    let flags = array(&v["quality_flags"])?;
    if flags.len() > 64 {
        return Err(err("QUALITY_BUDGET"));
    }
    let mut previous: Option<&str> = None;
    for flag in flags {
        let flag = name(flag)?;
        if previous.is_some_and(|p| p >= flag) {
            return Err(err("QUALITY_ORDER"));
        }
        previous = Some(flag);
    }
    Ok(())
}
#[derive(Debug)]
pub struct CalculationState {
    cursor: ExecutionCursor,
    snapshot: CalculationSnapshot,
    fresh: bool,
}
impl CalculationState {
    pub fn new(binding: ExecutionBinding) -> Self {
        let cursor = ExecutionCursor::new(binding.clone());
        let snapshot = CalculationSnapshot {
            binding,
            cursor: cursor.capture(),
            outcome: StateOutcome::Uninitialized,
            receipt: None,
            reason: None,
        };
        Self {
            cursor,
            snapshot,
            fresh: true,
        }
    }
    pub fn is_fresh(&self) -> bool {
        self.fresh
    }
    pub fn cursor(&self) -> &ExecutionCursor {
        &self.cursor
    }
    pub fn snapshot(&self) -> CalculationSnapshot {
        self.snapshot.clone()
    }
    pub fn prepare(&self, times: &[&str], input_digest: &str) -> Result<PreparedBatch> {
        if self.snapshot.outcome.failed() {
            return Err(err("EXPLICIT_RECOVERY_REQUIRED"));
        }
        self.cursor.prepare(times, input_digest)
    }
    pub fn commit(&mut self, batch: &PreparedBatch, value: &Value) -> Result<()> {
        if self.snapshot.outcome.failed() {
            return Err(err("EXPLICIT_RECOVERY_REQUIRED"));
        }
        // Validate a candidate completely before replacing either cursor or output projection.
        let mut candidate = ExecutionCursor::new(self.cursor.binding().clone());
        candidate.restore(&self.cursor.capture())?;
        let result = &value["cursor"];
        let binding = ExecutionBinding::from_record(&result["binding"])?;
        let times: Vec<_> = batch.times().iter().map(String::as_str).collect();
        candidate.commit(
            batch,
            &binding,
            result["revision"]
                .as_u64()
                .ok_or_else(|| err("REVISION_REQUIRED"))?,
            &times,
            result["samples"]
                .as_u64()
                .ok_or_else(|| err("SAMPLES_REQUIRED"))?,
            text(&value["input_digest"])?,
        )?;
        if candidate.capture() != *result {
            return Err(err("CURSOR_EXACT_REQUIRED"));
        }
        receipt(value, result)?;
        self.snapshot = CalculationSnapshot {
            binding,
            cursor: candidate.capture(),
            outcome: if boolean(&value["ready"])? {
                StateOutcome::Ready
            } else {
                StateOutcome::Warming
            },
            receipt: Some(value.clone()),
            reason: None,
        };
        self.cursor = candidate;
        self.fresh = false;
        Ok(())
    }
    pub fn fail(&mut self, outcome: StateOutcome, reason: &str) -> Result<()> {
        if !outcome.failed()
            || (self.snapshot.outcome == StateOutcome::Unknown && outcome != StateOutcome::Unknown)
        {
            return Err(err("FAILURE_OUTCOME_INVALID"));
        }
        name(&json!(reason))?;
        self.snapshot.outcome = outcome;
        self.snapshot.reason = Some(reason.into());
        self.fresh = false;
        Ok(())
    }
    pub fn reset(&mut self, revision: u64) -> Result<()> {
        self.cursor.reset(revision)?;
        self.snapshot = CalculationSnapshot {
            binding: self.cursor.binding().clone(),
            cursor: self.cursor.capture(),
            outcome: StateOutcome::Uninitialized,
            receipt: None,
            reason: None,
        };
        self.fresh = false;
        Ok(())
    }
    pub fn capture(&self) -> Value {
        self.snapshot.to_record()
    }
    pub fn restore(&mut self, record: &Value) -> Result<()> {
        if !self.fresh {
            return Err(err("FRESH_STATE_REQUIRED"));
        }
        object(
            record,
            &["schema_version", "cursor", "outcome", "receipt", "reason"],
        )?;
        if record["schema_version"].as_u64() != Some(1) {
            return Err(err("STATE_SCHEMA_REQUIRED"));
        }
        let mut candidate = ExecutionCursor::new(self.cursor.binding().clone());
        candidate.restore(&record["cursor"])?;
        let outcome = StateOutcome::parse(&record["outcome"])?;
        let output = if record["receipt"].is_null() {
            None
        } else {
            receipt(&record["receipt"], &candidate.capture())?;
            Some(record["receipt"].clone())
        };
        if (candidate.samples() > 0) != output.is_some() {
            return Err(err("STATE_RESULT_REQUIRED"));
        }
        if outcome == StateOutcome::Uninitialized && output.is_some()
            || matches!(outcome, StateOutcome::Ready | StateOutcome::Warming) && output.is_none()
            || outcome == StateOutcome::Ready && output.as_ref().is_some_and(|r| r["ready"] != true)
            || outcome == StateOutcome::Warming
                && output.as_ref().is_some_and(|r| r["ready"] != false)
            || outcome.failed() == record["reason"].is_null()
        {
            return Err(err("STATE_RELATION_INVALID"));
        }
        let reason = if record["reason"].is_null() {
            None
        } else {
            Some(name(&record["reason"])?.into())
        };
        let snapshot = CalculationSnapshot {
            binding: candidate.binding().clone(),
            cursor: candidate.capture(),
            outcome,
            receipt: output,
            reason,
        };
        self.cursor = candidate;
        self.snapshot = snapshot;
        self.fresh = false;
        Ok(())
    }
}
