use crate::{Manager, model::*};
use serde_json::{Value, json};
impl Manager {
    pub fn checkpoint(&self) -> Result<(Vec<u8>, String), Error> {
        let b = serde_json::to_vec(
            &json!({"schema_version":1,"config":self.config,"journal":self.journal,"state":self.state()}),
        )?;
        let h = digest(&b);
        Ok((b, h))
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
