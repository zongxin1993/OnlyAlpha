use crate::{ApplyResult, Manager, model::*};
use serde_json::{Value, json};
use std::sync::Arc;

#[derive(Debug)]
pub(crate) struct CachedCheckpoint {
    bytes: Vec<u8>,
    fingerprint: String,
    record: Arc<Value>,
}

#[cfg(test)]
std::thread_local! {
    static CHECKPOINT_ENCODINGS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}
impl Manager {
    fn cached_checkpoint(&self) -> Result<Arc<CachedCheckpoint>, Error> {
        if let Some(checkpoint) = self.checkpoint_cache.get() {
            return Ok(Arc::clone(checkpoint));
        }
        #[cfg(test)]
        CHECKPOINT_ENCODINGS.with(|count| count.set(count.get() + 1));
        let record = json!({"schema_version":1,"config":self.config,"journal":self.journal,"state":self.state_record()});
        let bytes = serde_json::to_vec(&record)?;
        let fingerprint = digest(&bytes);
        let checkpoint = Arc::new(CachedCheckpoint {
            bytes,
            fingerprint,
            record: Arc::new(record),
        });
        let _ = self.checkpoint_cache.set(Arc::clone(&checkpoint));
        Ok(checkpoint)
    }
    pub fn checkpoint(&self) -> Result<(Vec<u8>, String), Error> {
        let checkpoint = self.cached_checkpoint()?;
        Ok((checkpoint.bytes.clone(), checkpoint.fingerprint.clone()))
    }
    /// Exact immutable JSON used by the original canonical checkpoint encoder.
    /// This representation grants no Store, source, Ready or execution authority.
    pub fn checkpoint_record(&self) -> Result<(Arc<Value>, String), Error> {
        let checkpoint = self.cached_checkpoint()?;
        Ok((
            Arc::clone(&checkpoint.record),
            checkpoint.fingerprint.clone(),
        ))
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

#[cfg(test)]
mod checkpoint_cache_tests {
    use super::*;
    const FIXTURE: &str = include_str!("../../../test-data/order/domain-inputs.json");
    fn config() -> Value {
        json!({"schema_version":1,"engine_id":"engine","runtime_id":"runtime","gateway_id":"gateway","generation":"a".repeat(64)})
    }
    fn create() -> Value {
        let fixture: Value = serde_json::from_str(FIXTURE).unwrap();
        json!({"schema_version":1,"op":"CREATE","cluster_id":"cluster","account_id":"account","request":fixture["request"],"cause":"b".repeat(64),"at":1})
    }
    fn local(op: &str, at: u64) -> Value {
        json!({"schema_version":1,"op":op,"cluster_id":"cluster","order_id":"runtime-ORDER-000001","at":at})
    }
    fn fee() -> Value {
        let fixture: Value = serde_json::from_str(FIXTURE).unwrap();
        let mut command = local("FEE", 1);
        command["contract"] = fixture["fee_contract"].clone();
        command["contract"]["schema_version"] = json!(1);
        command
    }
    fn exact_original(owner: &Manager) -> Arc<Value> {
        // Independent original encoder expression: no cache value is used to
        // construct the expected canonical bytes or fingerprint.
        let original = json!({"schema_version":1,"config":owner.config,"journal":owner.journal,"state":owner.state_record()});
        let bytes = serde_json::to_vec(&original).unwrap();
        let expected = digest(&bytes);
        let (record, fingerprint) = owner.checkpoint_record().unwrap();
        assert_eq!(record.as_ref(), &original);
        assert_eq!(serde_json::to_vec(record.as_ref()).unwrap(), bytes);
        assert_eq!(fingerprint, expected);
        assert_eq!(owner.checkpoint().unwrap(), (bytes, expected));
        record
    }
    #[test]
    fn canonical_checkpoint_cache_counts_cold_warm_and_both_actual_commit_paths() {
        let mut owner = Manager::new(config()).unwrap();
        CHECKPOINT_ENCODINGS.with(|count| count.set(0));
        let empty = exact_original(&owner);
        for _ in 0..3 {
            assert!(Arc::ptr_eq(&empty, &exact_original(&owner)));
        }
        assert_eq!(CHECKPOINT_ENCODINGS.with(std::cell::Cell::get), 1);
        let mut invalid = create();
        invalid["cause"] = json!("bad");
        assert!(owner.apply(&invalid).is_err());
        assert!(Arc::ptr_eq(&empty, &exact_original(&owner)));
        assert_eq!(owner.apply(&create()).unwrap().result, ApplyResult::Applied);
        let created = exact_original(&owner);
        assert!(!Arc::ptr_eq(&empty, &created));
        assert_eq!(CHECKPOINT_ENCODINGS.with(std::cell::Cell::get), 2);
        assert_eq!(
            owner.apply(&local("BEGIN_SUBMIT", 2)).unwrap().result,
            ApplyResult::Invalid
        );
        assert_eq!(
            owner.apply(&create()).unwrap().result,
            ApplyResult::Duplicate
        );
        let mut conflict = create();
        conflict["cause"] = json!("c".repeat(64));
        assert_eq!(
            owner.apply(&conflict).unwrap().result,
            ApplyResult::Conflict
        );
        assert!(Arc::ptr_eq(&created, &exact_original(&owner)));
        assert_eq!(CHECKPOINT_ENCODINGS.with(std::cell::Cell::get), 2);
        owner.apply(&fee()).unwrap();
        let funded = exact_original(&owner);
        assert!(!Arc::ptr_eq(&created, &funded));
        assert_eq!(CHECKPOINT_ENCODINGS.with(std::cell::Cell::get), 3);
        let mut detached = Arc::clone(&funded);
        Arc::make_mut(&mut detached)["state"] = Value::Null;
        assert_ne!(detached, funded);
        assert!(Arc::ptr_eq(&funded, &exact_original(&owner)));
        let inventory = owner.snapshots().collect::<Vec<_>>();
        assert_eq!(inventory.len(), 1);
        drop(inventory);
        owner.get("cluster", "runtime-ORDER-000001").unwrap();
        owner.submission("cluster", "runtime-ORDER-000001").unwrap();
        assert!(Arc::ptr_eq(&funded, &exact_original(&owner)));
        assert_eq!(CHECKPOINT_ENCODINGS.with(std::cell::Cell::get), 3);
    }
    #[test]
    fn checkpoint_cache_clone_mutation_restore_and_refusal_are_isolated() {
        let mut owner = Manager::new(config()).unwrap();
        owner.apply(&create()).unwrap();
        let original = exact_original(&owner);
        let mut fork = owner.clone();
        assert!(Arc::ptr_eq(&original, &exact_original(&fork)));
        fork.apply(&fee()).unwrap();
        let funded = exact_original(&fork);
        assert!(Arc::ptr_eq(&original, &exact_original(&owner)));
        owner.apply(&fee()).unwrap();
        assert_eq!(exact_original(&owner), funded);
        assert!(!Arc::ptr_eq(&funded, &exact_original(&owner)));
        fork.apply(&local("BEGIN_SUBMIT", 2)).unwrap();
        let submitted = exact_original(&fork);
        assert_ne!(submitted, exact_original(&owner));
        assert_eq!(owner.apply(&fee()).unwrap().result, ApplyResult::Duplicate);
        assert_eq!(
            fork.apply(&local("BEGIN_SUBMIT", 3)).unwrap().result,
            ApplyResult::Invalid
        );
        assert!(Arc::ptr_eq(&submitted, &exact_original(&fork)));
        let wire = fork.checkpoint().unwrap();
        let mut restored = Manager::new(config()).unwrap();
        restored.restore(&wire.0, &wire.1).unwrap();
        assert_eq!(exact_original(&restored), submitted);
        let before_failure = exact_original(&restored);
        let mut corrupt = wire.0.clone();
        corrupt.push(b' ');
        assert!(restored.restore(&corrupt, &wire.1).is_err());
        let mut corrupt: Value = serde_json::from_slice(&wire.0).unwrap();
        corrupt["state"]["sequence"] = json!(999);
        let bad = serde_json::to_vec(&corrupt).unwrap();
        assert!(restored.restore(&bad, &digest(&bad)).is_err());
        assert!(Arc::ptr_eq(&before_failure, &exact_original(&restored)));
        restored.restore(&wire.0, &wire.1).unwrap();
        assert_eq!(exact_original(&restored), submitted);
        assert!(Arc::ptr_eq(&submitted, &exact_original(&fork)));
    }
}
