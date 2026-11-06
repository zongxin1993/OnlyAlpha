use crate::{Manager, manager::CachedCheckpoint, model::*};
use serde_json::{Value, json};
use std::sync::Arc;
impl Manager {
    fn cached_checkpoint(&self) -> Result<&CachedCheckpoint, Error> {
        if let Some(checkpoint) = self.checkpoint_cache.get() {
            return Ok(checkpoint.as_ref());
        }
        #[cfg(test)]
        CHECKPOINT_ENCODINGS.with(|n| n.set(n.get() + 1));
        let record = Arc::new(json!({
            "schema_version": 2,
            "config": self.config,
            "journal": self.journal.iter().map(Arc::as_ref).collect::<Vec<_>>(),
            "state": self.state()
        }));
        let bytes = serde_json::to_vec(record.as_ref())?;
        let fingerprint = digest(&bytes);
        let checkpoint = CachedCheckpoint {
            bytes,
            fingerprint,
            record,
        };
        let _ = self.checkpoint_cache.set(Arc::new(checkpoint));
        // Concurrent shared readers construct the same immutable state. A
        // successful set, or another reader winning it, always leaves a value.
        Ok(self
            .checkpoint_cache
            .get()
            .expect("checkpoint was initialized")
            .as_ref())
    }

    pub fn checkpoint(&self) -> Result<(Vec<u8>, String), Error> {
        let checkpoint = self.cached_checkpoint()?;
        Ok((checkpoint.bytes.clone(), checkpoint.fingerprint.clone()))
    }

    /// Exact JSON representation of the owning checkpoint encoder, with its
    /// original byte fingerprint. This detached immutable data grants no Store,
    /// source, Ready or execution authority.
    pub fn checkpoint_record(&self) -> Result<(Arc<Value>, String), Error> {
        let checkpoint = self.cached_checkpoint()?;
        Ok((
            Arc::clone(&checkpoint.record),
            checkpoint.fingerprint.clone(),
        ))
    }
    /// Extend this exact canonical data prefix without reapplying its commands.
    /// This validates data only; it supplies no Store, source or Ready proof.
    pub fn restore_exact_extension(&mut self, bytes: &[u8], expected: &str) -> Result<(), Error> {
        fingerprint(&json!(expected))?;
        if digest(bytes) != expected {
            return Err(err("LEDGER_CHECKPOINT_DIGEST"));
        }
        let value: Value = serde_json::from_slice(bytes)?;
        let record = checkpoint_row(&value, &["config", "journal", "state"])?;
        if serde_json::to_vec(&value)? != bytes || record["config"] != self.config {
            return Err(err("LEDGER_CHECKPOINT_CONTEXT_OR_CANONICAL"));
        }
        let journal = record["journal"]
            .as_array()
            .ok_or_else(|| err("LEDGER_CHECKPOINT_JOURNAL"))?;
        if journal.len() <= self.journal.len()
            || journal[..self.journal.len()]
                .iter()
                .zip(&self.journal)
                .any(|(a, b)| a != b.as_ref())
        {
            return Err(err("LEDGER_CHECKPOINT_EXTENSION_PREFIX"));
        }
        let mut candidate = self.clone();
        for command in &journal[self.journal.len()..] {
            let before = candidate.journal.len();
            candidate.apply(command)?;
            if candidate.journal.len() != before + 1 {
                return Err(err("LEDGER_REPLAY_RECEIPT"));
            }
        }
        let (actual, fingerprint) = candidate.checkpoint()?;
        if actual != bytes || fingerprint != expected {
            return Err(err("LEDGER_CHECKPOINT_STATE"));
        }
        *self = candidate;
        Ok(())
    }
    pub fn restore(&mut self, bytes: &[u8], expected: &str) -> Result<(), Error> {
        fingerprint(&json!(expected))?;
        if digest(bytes) != expected {
            return Err(err("LEDGER_CHECKPOINT_DIGEST"));
        }
        let v: Value = serde_json::from_slice(bytes)?;
        let r = checkpoint_row(&v, &["config", "journal", "state"])?;
        if serde_json::to_vec(&v)? != bytes || r["config"] != self.config {
            return Err(err("LEDGER_CHECKPOINT_CONTEXT_OR_CANONICAL"));
        }
        let journal = r["journal"]
            .as_array()
            .ok_or_else(|| err("LEDGER_CHECKPOINT_JOURNAL"))?;
        let mut candidate = Self::new(self.config.clone())?;
        for command in journal {
            let before = candidate.journal.len();
            candidate.apply(command)?;
            if candidate.journal.len() != before + 1 {
                return Err(err("LEDGER_REPLAY_RECEIPT"));
            }
        }
        if serde_json::to_value(
            candidate
                .journal
                .iter()
                .map(std::sync::Arc::as_ref)
                .collect::<Vec<_>>(),
        )? != r["journal"]
            || candidate.state() != r["state"]
        {
            return Err(err("LEDGER_CHECKPOINT_STATE"));
        }
        *self = candidate;
        Ok(())
    }
}

#[cfg(test)]
#[path = "recovery_extension_tests.rs"]
mod extension_tests;

#[cfg(test)]
std::thread_local! {static CHECKPOINT_ENCODINGS:std::cell::Cell<u64>=const{std::cell::Cell::new(0)};}
