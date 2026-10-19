use crate::{Manager, model::*};
use serde_json::{Value, json};
impl Manager {
    pub fn checkpoint(&self) -> Result<(Vec<u8>, String), Error> {
        let bytes = serde_json::to_vec(
            &json!({"schema_version":2,"config":self.config,"journal":self.state.journal,"state":self.state()}),
        )?;
        let hash = digest(&bytes);
        Ok((bytes, hash))
    }
    pub fn restore(&mut self, bytes: &[u8], expected: &str) -> Result<(), Error> {
        fingerprint(&json!(expected))?;
        if digest(bytes) != expected {
            return Err(err("ACCOUNT_CHECKPOINT_DIGEST"));
        }
        let v: Value = serde_json::from_slice(bytes)?;
        let r = checkpoint_row(&v, &["config", "journal", "state"])?;
        if serde_json::to_vec(&v)? != bytes || r["config"] != self.config {
            return Err(err("ACCOUNT_CHECKPOINT_CONTEXT_OR_CANONICAL"));
        }
        let journal = r["journal"]
            .as_array()
            .ok_or_else(|| err("ACCOUNT_CHECKPOINT_JOURNAL"))?;
        let mut candidate = Self::new(self.config.clone())?;
        for command in journal {
            let before = candidate.state.journal.len();
            candidate.apply(command)?;
            if candidate.state.journal.len() != before + 1 {
                return Err(err("ACCOUNT_REPLAY_RECEIPT"));
            }
        }
        if serde_json::to_value(&candidate.state.journal)? != r["journal"]
            || candidate.state() != r["state"]
        {
            return Err(err("ACCOUNT_CHECKPOINT_STATE"));
        }
        *self = candidate;
        Ok(())
    }
}
