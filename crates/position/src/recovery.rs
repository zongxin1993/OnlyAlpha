use crate::{Manager, Status, manager::CachedCheckpoint, model::*};
use serde_json::{Value, json};
use std::sync::Arc;

#[cfg(test)]
std::thread_local! {
    static CHECKPOINT_ENCODINGS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}
impl Manager {
    fn cached_checkpoint(&self) -> Result<&CachedCheckpoint, Error> {
        if let Some(checkpoint) = self.checkpoint_cache.get() {
            return Ok(checkpoint.as_ref());
        }
        #[cfg(test)]
        CHECKPOINT_ENCODINGS.with(|count| count.set(count.get() + 1));
        let record = Arc::new(json!({
            "schema_version":2,"config":self.config,
            "journal":self.state.journal,"state":self.state()
        }));
        let bytes = serde_json::to_vec(record.as_ref())?;
        let fingerprint = digest(&bytes);
        let checkpoint = CachedCheckpoint {
            bytes,
            fingerprint,
            record,
        };
        let _ = self.checkpoint_cache.set(Arc::new(checkpoint));
        // Shared readers observe the same immutable accepted owner state.
        Ok(self
            .checkpoint_cache
            .get()
            .expect("checkpoint initialized")
            .as_ref())
    }
    pub fn checkpoint(&self) -> Result<(Vec<u8>, String), Error> {
        let checkpoint = self.cached_checkpoint()?;
        Ok((checkpoint.bytes.clone(), checkpoint.fingerprint.clone()))
    }
    /// Borrow the original complete canonical checkpoint as immutable data.
    /// This representation grants no execution, source, Ready or restore proof.
    pub fn checkpoint_record(&self) -> Result<(Arc<Value>, String), Error> {
        let checkpoint = self.cached_checkpoint()?;
        Ok((
            Arc::clone(&checkpoint.record),
            checkpoint.fingerprint.clone(),
        ))
    }
    pub fn restore(&mut self, bytes: &[u8], expected: &str) -> Result<(), Error> {
        fingerprint(&json!(expected))?;
        if digest(bytes) != expected {
            return Err(err("POSITION_CHECKPOINT_DIGEST"));
        }
        let value: Value = serde_json::from_slice(bytes)?;
        let r = checkpoint_row(&value, &["config", "journal", "state"])?;
        if serde_json::to_vec(&value)? != bytes || r["config"] != self.config {
            return Err(err("POSITION_CHECKPOINT_CANONICAL_OR_CONTEXT"));
        }
        let journal = r["journal"]
            .as_array()
            .ok_or_else(|| err("POSITION_CHECKPOINT_JOURNAL"))?;
        let mut candidate = Self::new(self.config.clone())?;
        for item in journal {
            let before = candidate.state.journal.len();
            if !matches!(
                candidate.apply(item)?.status,
                Status::Applied | Status::Stale | Status::Duplicate
            ) || candidate.state.journal.len() != before + 1
            {
                return Err(err("POSITION_CHECKPOINT_REPLAY"));
            }
        }
        if candidate.state() != r["state"] {
            return Err(err("POSITION_CHECKPOINT_STATE"));
        }
        *self = candidate;
        Ok(())
    }
}

#[cfg(test)]
#[path = "checkpoint_cache_tests.rs"]
mod checkpoint_cache_tests;
