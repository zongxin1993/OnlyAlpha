use crate::{Manager, Status, model::*};
use serde_json::{Value, json};
impl Manager {
    pub fn checkpoint(&self) -> Result<(Vec<u8>, String), Error> {
        let bytes = serde_json::to_vec(
            &json!({"schema_version":1,"config":self.config,"journal":self.state.journal,"state":self.state()}),
        )?;
        if bytes.len() > MAX_CHECKPOINT {
            return Err(err("POSITION_CHECKPOINT_BOUND"));
        }
        let hash = digest(&bytes);
        Ok((bytes, hash))
    }
    pub fn restore(&mut self, bytes: &[u8], expected: &str) -> Result<(), Error> {
        fingerprint(&json!(expected))?;
        if bytes.len() > MAX_CHECKPOINT || digest(bytes) != expected {
            return Err(err("POSITION_CHECKPOINT_DIGEST"));
        }
        let value: Value = serde_json::from_slice(bytes)?;
        let r = row(&value, &["config", "journal", "state"])?;
        if serde_json::to_vec(&value)? != bytes || r["config"] != self.config {
            return Err(err("POSITION_CHECKPOINT_CANONICAL_OR_CONTEXT"));
        }
        let journal = r["journal"]
            .as_array()
            .filter(|j| j.len() <= MAX_JOURNAL)
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
