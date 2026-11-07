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
            "schema_version": 1,
            "config": self.config,
            "journal": self.journal,
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
        // Shared readers see the same immutable owner. Either this reader or
        // another successful set has now initialized the representation.
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

    /// Exact owning checkpoint JSON and its original byte fingerprint. This
    /// immutable data grants no Runtime source, Ready or execution authority.
    pub fn checkpoint_record(&self) -> Result<(Arc<Value>, String), Error> {
        let checkpoint = self.cached_checkpoint()?;
        Ok((
            Arc::clone(&checkpoint.record),
            checkpoint.fingerprint.clone(),
        ))
    }
    pub fn restore(&mut self, bytes: &[u8], expected: &str) -> Result<(), Error> {
        fp(&json!(expected))?;
        if digest(bytes) != expected {
            return Err(err("RISK_CHECKPOINT_DIGEST"));
        }
        let v: Value = serde_json::from_slice(bytes)?;
        let r = row(&v, &["config", "journal", "state"])?;
        if serde_json::to_vec(&v)? != bytes || r["config"] != self.config {
            return Err(err("RISK_CHECKPOINT_CONTEXT_OR_CANONICAL"));
        }
        let journal = r["journal"]
            .as_array()
            .ok_or_else(|| err("RISK_CHECKPOINT_JOURNAL"))?;
        let mut candidate = Self::new(self.config.clone())?;
        for c in journal {
            let before = candidate.journal.len();
            candidate.apply(c)?;
            if candidate.journal.len() != before + 1 {
                return Err(err("RISK_REPLAY_RECEIPT"));
            }
        }
        if serde_json::to_value(&candidate.journal)? != r["journal"]
            || candidate.state() != r["state"]
        {
            return Err(err("RISK_CHECKPOINT_STATE"));
        }
        *self = candidate;
        Ok(())
    }
}

#[cfg(test)]
std::thread_local! {
    static CHECKPOINT_ENCODINGS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}

#[cfg(test)]
#[path = "tests/checkpoint_tests.rs"]
mod checkpoint_tests;
