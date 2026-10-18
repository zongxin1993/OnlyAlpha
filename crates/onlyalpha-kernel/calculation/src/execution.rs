//! Pure ordered execution ownership. Algorithm values/readiness remain plugin facts.
use crate::{CalculationError, Result};
use bigdecimal::num_bigint::BigInt;
use serde_json::{Value, json};
use std::str::FromStr;

pub const MAX_BATCH: usize = 256;
fn invalid() -> CalculationError {
    CalculationError("EXECUTION_CONTRACT_INVALID".into())
}
fn sha(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|v| v.is_ascii_digit() || (b'a'..=b'f').contains(&v))
}
fn timestamp(value: &str) -> Result<BigInt> {
    if value.len() > 128 {
        return Err(invalid());
    }
    let parsed = BigInt::from_str(value).map_err(|_| invalid())?;
    if parsed.to_string() != value {
        return Err(invalid());
    }
    Ok(parsed)
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionBinding {
    digests: [String; 6],
    scope: String,
}
impl ExecutionBinding {
    /// generation, worker artifact, component definition, native definition,
    /// native implementation, exact input context, followed by explicit instance scope.
    pub fn new(digests: [String; 6], scope: &str) -> Result<Self> {
        if digests.iter().any(|v| !sha(v))
            || scope.is_empty()
            || scope.trim() != scope
            || scope.len() > 1024
            || scope.chars().any(char::is_control)
        {
            return Err(invalid());
        }
        Ok(Self {
            digests,
            scope: scope.into(),
        })
    }
    pub fn to_record(&self) -> Value {
        json!({"schema_version":1,"digests":self.digests,"scope":self.scope})
    }
    pub fn from_record(v: &Value) -> Result<Self> {
        if v.as_object().map(|m| m.len()) != Some(3) || v["schema_version"].as_u64() != Some(1) {
            return Err(invalid());
        }
        let values = v["digests"].as_array().ok_or_else(invalid)?;
        if values.len() != 6 {
            return Err(invalid());
        }
        let values: Vec<String> = values
            .iter()
            .map(|s| s.as_str().map(str::to_owned).ok_or_else(invalid))
            .collect::<Result<_>>()?;
        Self::new(
            values.try_into().map_err(|_| invalid())?,
            v["scope"].as_str().ok_or_else(invalid)?,
        )
    }
    pub fn digests(&self) -> &[String; 6] {
        &self.digests
    }
    pub fn scope(&self) -> &str {
        &self.scope
    }
}
#[derive(Debug)]
pub struct PreparedBatch {
    binding: ExecutionBinding,
    revision: u64,
    samples: u64,
    times: Vec<String>,
    input_digest: String,
}
impl PreparedBatch {
    pub fn revision(&self) -> u64 {
        self.revision
    }
    pub fn input_digest(&self) -> &str {
        &self.input_digest
    }
    pub fn times(&self) -> &[String] {
        &self.times
    }
}
#[derive(Debug)]
pub struct ExecutionCursor {
    binding: ExecutionBinding,
    revision: u64,
    samples: u64,
    last: Option<BigInt>,
    fresh: bool,
}
impl ExecutionCursor {
    pub fn new(binding: ExecutionBinding) -> Self {
        Self {
            binding,
            revision: 0,
            samples: 0,
            last: None,
            fresh: true,
        }
    }
    pub fn binding(&self) -> &ExecutionBinding {
        &self.binding
    }
    pub fn revision(&self) -> u64 {
        self.revision
    }
    pub fn samples(&self) -> u64 {
        self.samples
    }
    pub fn prepare(&self, times: &[&str], input_digest: &str) -> Result<PreparedBatch> {
        if times.is_empty()
            || times.len() > MAX_BATCH
            || !sha(input_digest)
            || self.revision == u64::MAX
            || self.samples.checked_add(times.len() as u64).is_none()
        {
            return Err(invalid());
        }
        let mut previous = self.last.clone();
        for raw in times {
            let next = timestamp(raw)?;
            if previous.as_ref().is_some_and(|v| v >= &next) {
                return Err(invalid());
            }
            previous = Some(next);
        }
        Ok(PreparedBatch {
            binding: self.binding.clone(),
            revision: self.revision,
            samples: self.samples,
            times: times.iter().map(|v| v.to_string()).collect(),
            input_digest: input_digest.into(),
        })
    }
    pub fn commit(
        &mut self,
        batch: &PreparedBatch,
        binding: &ExecutionBinding,
        revision: u64,
        times: &[&str],
        samples: u64,
        input_digest: &str,
    ) -> Result<()> {
        if self.binding != *binding
            || batch.input_digest != input_digest
            || batch.binding != self.binding
            || batch.revision != self.revision
            || batch.samples != self.samples
            || revision != self.revision.checked_add(1).ok_or_else(invalid)?
            || batch
                .times
                .iter()
                .map(String::as_str)
                .ne(times.iter().copied())
            || samples
                != self
                    .samples
                    .checked_add(times.len() as u64)
                    .ok_or_else(invalid)?
        {
            return Err(invalid());
        }
        let last = timestamp(times.last().ok_or_else(invalid)?)?;
        self.last = Some(last);
        self.samples = samples;
        self.revision = revision;
        self.fresh = false;
        Ok(())
    }
    pub fn reset(&mut self, revision: u64) -> Result<()> {
        if self.revision.checked_add(1) != Some(revision) {
            return Err(invalid());
        }
        self.revision = revision;
        self.samples = 0;
        self.last = None;
        self.fresh = false;
        Ok(())
    }
    pub fn capture(&self) -> Value {
        json!({"schema_version":1,"binding":self.binding.to_record(),"revision":self.revision,"samples":self.samples,"last_event_ns":self.last.as_ref().map(ToString::to_string)})
    }
    pub fn restore(&mut self, v: &Value) -> Result<()> {
        if !self.fresh
            || v.as_object().map(|v| v.len()) != Some(5)
            || v["schema_version"].as_u64() != Some(1)
            || ExecutionBinding::from_record(&v["binding"])? != self.binding
        {
            return Err(invalid());
        }
        let revision = v["revision"].as_u64().ok_or_else(invalid)?;
        let samples = v["samples"].as_u64().ok_or_else(invalid)?;
        let last = if v["last_event_ns"].is_null() {
            None
        } else {
            Some(timestamp(v["last_event_ns"].as_str().ok_or_else(invalid)?)?)
        };
        if (samples == 0) != last.is_none() || (revision == 0 && samples != 0) {
            return Err(invalid());
        }
        self.revision = revision;
        self.samples = samples;
        self.last = last;
        self.fresh = false;
        Ok(())
    }
}
