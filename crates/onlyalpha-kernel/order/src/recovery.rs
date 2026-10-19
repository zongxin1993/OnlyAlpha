use crate::{ApplyResult, Manager, model::*};
use serde_json::{Value, json};
impl Manager {
    pub fn checkpoint(&self) -> Result<(Vec<u8>, String), Error> {
        let record = json!({"schema_version":1,"config":self.config,"journal":self.journal,"state":self.state_record()});
        let bytes = serde_json::to_vec(&record)?;
        let hash = digest(&bytes);
        Ok((bytes, hash))
    }
    pub fn restore(&mut self, bytes: &[u8], expected_digest: &str) -> Result<(), Error> {
        fingerprint(expected_digest)?;
        if digest(bytes) != expected_digest {
            return Err(err("ORDER_CHECKPOINT_DIGEST_OR_BOUND"));
        }
        let value: Value = serde_json::from_slice(bytes)?;
        let r = row(&value, &["config", "journal", "state"])?;
        if serde_json::to_vec(&value)? != bytes || r["config"] != self.config {
            return Err(err("ORDER_CHECKPOINT_NONCANONICAL_OR_CONTEXT"));
        }
        let journal = r["journal"]
            .as_array()
            .ok_or_else(|| err("ORDER_CHECKPOINT_JOURNAL_INVALID"))?;
        let mut candidate = Self::new(self.config.clone())?;
        for item in journal {
            if candidate.apply(item)?.result != ApplyResult::Applied {
                return Err(err("ORDER_CHECKPOINT_REPLAY_NOT_APPLIED"));
            }
        }
        if candidate.state_record() != r["state"] {
            return Err(err("ORDER_CHECKPOINT_STATE_MISMATCH"));
        }
        *self = candidate;
        Ok(())
    }
}
