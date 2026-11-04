use crate::{Manager, model::*};
use serde_json::{Value, json};
impl Manager {
    pub fn checkpoint(&self) -> Result<(Vec<u8>, String), Error> {
        if let Some(bytes)=self.checkpoint_cache.get(){return Ok(bytes.as_ref().clone());}
        #[cfg(test)] CHECKPOINT_ENCODINGS.with(|n|n.set(n.get()+1));
        let bytes = serde_json::to_vec(
            &json!({"schema_version":2,"config":self.config,"journal":self.journal.iter().map(std::sync::Arc::as_ref).collect::<Vec<_>>(),"state":self.state()}),
        )?;
        let hash = digest(&bytes);
        let result=(bytes,hash);
        let _=self.checkpoint_cache.set(std::sync::Arc::new(result.clone()));
        Ok(result)
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
        let journal = record["journal"].as_array().ok_or_else(|| err("LEDGER_CHECKPOINT_JOURNAL"))?;
        if journal.len() <= self.journal.len() || journal[..self.journal.len()].iter().zip(&self.journal).any(|(a,b)|a!=b.as_ref()) {
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
        if serde_json::to_value(candidate.journal.iter().map(std::sync::Arc::as_ref).collect::<Vec<_>>())? != r["journal"]
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

#[cfg(test)] std::thread_local! {static CHECKPOINT_ENCODINGS:std::cell::Cell<u64>=const{std::cell::Cell::new(0)};}
