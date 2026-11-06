use crate::{Manager, model::*};
use serde_json::{Map, Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};

// One immutable representation of the original canonical checkpoint.
// This memo contains no Runtime/source or Ready authority.
pub(crate) struct CachedCheckpoint {
    bytes: Vec<u8>,
    fingerprint: String,
    record: Arc<Value>,
}

pub(crate) fn check_expanded_size(
    config: &Value,
    state: &Value,
    journal_bytes: usize,
) -> Result<(), Error> {
    // The empty array already contributes both brackets. journal_bytes adds
    // exact canonical command bytes and only the intervening commas.
    let envelope = serde_json::to_vec(
        &json!({"schema_version":4,"config":config,"journal":[],"state":state}),
    )?
    .len();
    envelope
        .checked_add(journal_bytes)
        .filter(|size| *size <= MAX_CHECKPOINT)
        .ok_or_else(|| err("ACCOUNT_CHECKPOINT_BOUND"))?;
    Ok(())
}
fn with_payload(command: &Value, payload: Value) -> Result<Value, Error> {
    let mut encoded = Map::new();
    for (key, value) in command
        .as_object()
        .ok_or_else(|| err("ACCOUNT_CHECKPOINT_JOURNAL"))?
    {
        if key != "payload" {
            encoded.insert(key.clone(), value.clone());
        }
    }
    encoded.insert("payload".into(), payload);
    Ok(Value::Object(encoded))
}
fn validate_dictionary(value: &Value) -> Result<(), Error> {
    let positions = value["positions"]
        .as_object()
        .ok_or_else(|| err("ACCOUNT_CHECKPOINT_DICTIONARY"))?;
    let mut sizes = BTreeMap::new();
    for (reference, position) in positions {
        fingerprint(&json!(reference))?;
        let bytes = serde_json::to_vec(position)?;
        if digest(&bytes) != *reference {
            return Err(err("ACCOUNT_CHECKPOINT_POSITION_DIGEST"));
        }
        sizes.insert(reference.as_str(), bytes.len());
    }
    let journal = value["journal"]
        .as_array()
        .ok_or_else(|| err("ACCOUNT_CHECKPOINT_JOURNAL"))?;
    let mut used = BTreeSet::new();
    let mut expanded = 0_usize;
    for (index, command) in journal.iter().enumerate() {
        let mut size = serde_json::to_vec(command)?.len();
        if command["op"] == "VALUATION" {
            let payload = row(&command["payload"], &["intent", "position_ref"])?;
            fingerprint(&payload["position_ref"])?;
            let reference = text(&payload["position_ref"])?;
            if payload["intent"]["position_evidence"] != reference {
                return Err(err("ACCOUNT_CHECKPOINT_POSITION_REFERENCE"));
            }
            let position_size = sizes
                .get(reference)
                .ok_or_else(|| err("ACCOUNT_CHECKPOINT_POSITION_REFERENCE"))?;
            // Both payloads have the same number of fields. Canonical SHA
            // text has no escapes: replacing position_ref with position
            // removes four key bytes and the quoted reference value.
            size = size
                .checked_sub("position_ref".len() - "position".len() + reference.len() + 2)
                .and_then(|size| size.checked_add(*position_size))
                .ok_or_else(|| err("ACCOUNT_CHECKPOINT_BOUND"))?;
            used.insert(reference);
        }
        expanded = expanded
            .checked_add(size)
            .and_then(|size| size.checked_add(usize::from(index != 0)))
            .ok_or_else(|| err("ACCOUNT_CHECKPOINT_BOUND"))?;
    }
    if used.len() != positions.len() {
        return Err(err("ACCOUNT_CHECKPOINT_UNUSED_POSITION"));
    }
    check_expanded_size(&value["config"], &value["state"], expanded)
}
// Compare the full original command without hydrating another copy of its
// repeated Position source. The entire incoming dictionary was checked first.
fn original_command_matches(
    version: u8,
    checkpoint: &Value,
    encoded: &Value,
    original: &Value,
) -> Result<bool, Error> {
    if version != 5 || encoded["op"] != "VALUATION" {
        return Ok(encoded == original);
    }
    if original["op"] != "VALUATION" {
        return Ok(false);
    }
    let current = row(&original["payload"], &["position", "intent"])?;
    let payload = &encoded["payload"];
    let reference = text(&payload["position_ref"])?;
    let fields = encoded
        .as_object()
        .ok_or_else(|| err("ACCOUNT_CHECKPOINT_JOURNAL"))?;
    let previous = original
        .as_object()
        .ok_or_else(|| err("ACCOUNT_CHECKPOINT_JOURNAL"))?;
    Ok(fields.len() == previous.len()
        && fields.iter().all(|(key, value)| {
            if key == "payload" {
                payload["intent"] == current["intent"]
                    && checkpoint["positions"][reference] == current["position"]
            } else {
                previous.get(key) == Some(value)
            }
        }))
}
impl Manager {
    fn checkpoint5(&self) -> Result<Value, Error> {
        let mut positions = Map::new();
        let mut journal = Vec::with_capacity(self.state.journal.len());
        for command in &self.state.journal {
            if command["op"] != "VALUATION" {
                journal.push(command.as_ref().clone());
                continue;
            }
            let payload = row(&command["payload"], &["position", "intent"])?;
            fingerprint(&payload["intent"]["position_evidence"])?;
            let reference = text(&payload["intent"]["position_evidence"])?;
            if let Some(original) = positions.get(reference) {
                if original != &payload["position"] {
                    return Err(err("ACCOUNT_CHECKPOINT_POSITION_CONFLICT"));
                }
            } else {
                // One full source clone per unique body, never a large
                // Command clone followed by removal of that same body.
                positions.insert(reference.into(), payload["position"].clone());
            }
            journal.push(with_payload(
                command,
                json!({"schema_version":1,"intent":payload["intent"],"position_ref":reference}),
            )?);
        }
        let value = json!({"schema_version":5,"config":self.config,"journal":journal,"positions":positions,"state":self.state()});
        // Independently derive the weighted size and every dictionary digest;
        // the incremental counter never authenticates a serialized checkpoint.
        validate_dictionary(&value)?;
        Ok(value)
    }
    fn cached_checkpoint(&self) -> Result<Arc<CachedCheckpoint>, Error> {
        if let Some(checkpoint) = self.checkpoint_cache.get() {
            return Ok(Arc::clone(checkpoint));
        }
        #[cfg(test)]
        CHECKPOINT_ENCODINGS.with(|n| n.set(n.get() + 1));
        let value = match self.checkpoint_version {
            4 => {
                json!({"schema_version":4,"config":self.config,"journal":self.state.journal.iter().map(std::sync::Arc::as_ref).collect::<Vec<_>>(),"state":self.state()})
            }
            5 => self.checkpoint5()?,
            _ => return Err(err("COMPONENT_CHECKPOINT_SCHEMA")),
        };
        let bytes = serde_json::to_vec(&value)?;
        let fingerprint = digest(&bytes);
        let checkpoint = Arc::new(CachedCheckpoint {
            bytes,
            fingerprint,
            record: Arc::new(value),
        });
        let _ = self.checkpoint_cache.set(Arc::clone(&checkpoint));
        Ok(checkpoint)
    }
    pub fn checkpoint(&self) -> Result<(Vec<u8>, String), Error> {
        let checkpoint = self.cached_checkpoint()?;
        Ok((checkpoint.bytes.clone(), checkpoint.fingerprint.clone()))
    }
    /// The exact canonical JSON used by `checkpoint`, shared as immutable data.
    /// This representation supplies no Runtime/source or Ready proof.
    pub fn checkpoint_record(&self) -> Result<(Arc<Value>, String), Error> {
        let checkpoint = self.cached_checkpoint()?;
        Ok((
            Arc::clone(&checkpoint.record),
            checkpoint.fingerprint.clone(),
        ))
    }
    fn checked_checkpoint(&self, bytes: &[u8], expected: &str) -> Result<Value, Error> {
        fingerprint(&json!(expected))?;
        if digest(bytes) != expected {
            return Err(err("ACCOUNT_CHECKPOINT_DIGEST"));
        }
        let value: Value = serde_json::from_slice(bytes)?;
        let fields: &[&str] = if self.checkpoint_version == 4 {
            &["config", "journal", "state"]
        } else {
            &["config", "journal", "positions", "state"]
        };
        let record = checkpoint_row(&value, self.checkpoint_version, fields)?;
        if serde_json::to_vec(&value)? != bytes || record["config"] != self.config {
            return Err(err("ACCOUNT_CHECKPOINT_CONTEXT_OR_CANONICAL"));
        }
        if self.checkpoint_version == 5 {
            validate_dictionary(&value)?;
        }
        Ok(value)
    }
    pub fn restore(&mut self, bytes: &[u8], expected: &str) -> Result<(), Error> {
        let value = self.checked_checkpoint(bytes, expected)?;
        let record = &value;
        let journal = record["journal"]
            .as_array()
            .ok_or_else(|| err("ACCOUNT_CHECKPOINT_JOURNAL"))?;
        let mut candidate = self.fresh()?;
        for encoded in journal {
            let command = if self.checkpoint_version == 5 && encoded["op"] == "VALUATION" {
                let payload = &encoded["payload"];
                let reference = text(&payload["position_ref"])?;
                Some(with_payload(
                    encoded,
                    json!({"schema_version":1,"intent":payload["intent"],"position":value["positions"][reference]}),
                )?)
            } else {
                None
            };
            let before = candidate.state.journal.len();
            candidate.apply_inner(command.as_ref().unwrap_or(encoded))?;
            if candidate.state.journal.len() != before + 1 {
                return Err(err("ACCOUNT_REPLAY_RECEIPT"));
            }
        }
        if candidate.state() != record["state"]
            || (self.checkpoint_version == 4
                && serde_json::to_value(
                    candidate
                        .state
                        .journal
                        .iter()
                        .map(std::sync::Arc::as_ref)
                        .collect::<Vec<_>>(),
                )? != record["journal"])
            || (self.checkpoint_version == 5 && candidate.checkpoint()?.0 != bytes)
        {
            return Err(err("ACCOUNT_CHECKPOINT_STATE"));
        }
        *self = candidate;
        Ok(())
    }
    /// Extend only this exact canonical journal. This is not arbitrary cold
    /// recovery or a Runtime/source grant; a changed prefix never falls back.
    pub fn restore_exact_extension(&mut self, bytes: &[u8], expected: &str) -> Result<(), Error> {
        let value = self.checked_checkpoint(bytes, expected)?;
        let journal = value["journal"]
            .as_array()
            .ok_or_else(|| err("ACCOUNT_CHECKPOINT_JOURNAL"))?;
        let prefix = self.state.journal.len();
        if journal.len() <= prefix {
            return Err(err("ACCOUNT_CHECKPOINT_PREFIX"));
        }
        for (encoded, original) in journal.iter().zip(&self.state.journal) {
            if !original_command_matches(self.checkpoint_version, &value, encoded, original)? {
                return Err(err("ACCOUNT_CHECKPOINT_PREFIX"));
            }
        }
        let mut candidate = self.clone();
        for encoded in &journal[prefix..] {
            let command = if self.checkpoint_version == 5 && encoded["op"] == "VALUATION" {
                let payload = &encoded["payload"];
                let reference = text(&payload["position_ref"])?;
                Some(with_payload(
                    encoded,
                    json!({"schema_version":1,"intent":payload["intent"],"position":value["positions"][reference]}),
                )?)
            } else {
                None
            };
            let before = candidate.state.journal.len();
            candidate.apply_inner(command.as_ref().unwrap_or(encoded))?;
            if candidate.state.journal.len() != before + 1 {
                return Err(err("ACCOUNT_REPLAY_RECEIPT"));
            }
        }
        let actual = candidate.checkpoint()?;
        if actual.0 != bytes || actual.1 != expected {
            return Err(err("ACCOUNT_CHECKPOINT_STATE"));
        }
        *self = candidate;
        Ok(())
    }
}

#[cfg(test)]
mod dictionary_size_tests {
    use super::*;
    fn config() -> Value {
        json!({"schema_version":2,"engine":"e","runtime":"r","account":"a","gateway":"g","generation":"a".repeat(64),"account_type":"CASH","currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"initial_cash":"100.00","position_configuration":"b".repeat(64)})
    }
    fn command(n: u64) -> Value {
        json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","gateway":"g","generation":"a".repeat(64),"command_id":format!("现金-\\\"-{n}"),"cause":"b".repeat(64),"time":n,"op":"CASH_CHANGE","payload":{"schema_version":1,"change":format!("change-{n}"),"source_fact":format!("来源-\\\"-{n}"),"kind":"DEPOSIT","amount":"0.00"}})
    }
    #[test]
    fn immutable_checkpoint_encoding_is_shared_until_a_successful_state_change() {
        for version in [4, 5] {
            let fresh = || {
                if version == 4 {
                    Manager::new(config()).unwrap()
                } else {
                    Manager::new_checkpoint5(config()).unwrap()
                }
            };
            let mut owner = fresh();
            owner.apply(&command(1)).unwrap();
            let original = owner.checkpoint().unwrap();
            let mut fork = owner.clone();
            CHECKPOINT_ENCODINGS.with(|n| n.set(0));
            for _ in 0..4 {
                assert_eq!(owner.checkpoint().unwrap(), original);
                assert_eq!(fork.checkpoint().unwrap(), original);
            }
            assert_eq!(
                CHECKPOINT_ENCODINGS.with(std::cell::Cell::get),
                0,
                "unchanged actual owner was re-encoded"
            );
            fork.apply(&command(2)).unwrap();
            let changed = fork.checkpoint().unwrap();
            assert_ne!(changed, original);
            assert_eq!(owner.checkpoint().unwrap(), original);
            let mut restored = fresh();
            restored.restore(&changed.0, &changed.1).unwrap();
            assert_eq!(restored.checkpoint().unwrap(), changed);
            let mut invalid = command(3);
            invalid["payload"]["amount"] = json!("-1.00");
            assert!(fork.apply(&invalid).is_err());
            assert_eq!(fork.checkpoint().unwrap(), changed);
            let mut corrupt = changed.0.clone();
            corrupt.push(b' ');
            assert!(fork.restore(&corrupt, &changed.1).is_err());
            assert_eq!(fork.checkpoint().unwrap(), changed);
            let mut detached = owner.checkpoint().unwrap();
            detached.0.clear();
            assert_eq!(owner.checkpoint().unwrap(), original);
        }
    }
    fn exact_record(owner: &Manager) -> Arc<Value> {
        let (record, fingerprint) = owner.checkpoint_record().unwrap();
        let (bytes, original_fingerprint) = owner.checkpoint().unwrap();
        assert_eq!(serde_json::to_vec(record.as_ref()).unwrap(), bytes);
        assert_eq!(fingerprint, original_fingerprint);
        assert_eq!(digest(&bytes), fingerprint);
        record
    }
    #[test]
    fn cached_checkpoint_record_is_the_original_canonical_bytes_and_hash() {
        for version in [4, 5] {
            let owner = if version == 4 {
                Manager::new(config()).unwrap()
            } else {
                Manager::new_checkpoint5(config()).unwrap()
            };
            CHECKPOINT_ENCODINGS.with(|n| n.set(0));
            let record = exact_record(&owner);
            assert!(Arc::ptr_eq(&record, &exact_record(&owner)));
            assert_eq!(CHECKPOINT_ENCODINGS.with(std::cell::Cell::get), 1);
            let mut detached = Arc::clone(&record);
            Arc::make_mut(&mut detached)["state"] = Value::Null;
            assert_ne!(*detached, *record);
            assert!(Arc::ptr_eq(&record, &exact_record(&owner)));
            assert_eq!(CHECKPOINT_ENCODINGS.with(std::cell::Cell::get), 1);
        }
    }
    #[test]
    fn checkpoint_record_follows_owner_mutation_clone_restore_and_refusal() {
        for version in [4, 5] {
            let fresh = || {
                if version == 4 {
                    Manager::new(config()).unwrap()
                } else {
                    Manager::new_checkpoint5(config()).unwrap()
                }
            };
            let mut owner = fresh();
            let original = exact_record(&owner);
            let mut fork = owner.clone();
            assert!(Arc::ptr_eq(&original, &exact_record(&fork)));
            fork.apply(&command(1)).unwrap();
            let changed = exact_record(&fork);
            assert!(!Arc::ptr_eq(&original, &changed));
            assert!(Arc::ptr_eq(&original, &exact_record(&owner)));
            owner.apply(&command(2)).unwrap();
            assert!(!Arc::ptr_eq(&original, &exact_record(&owner)));
            assert!(Arc::ptr_eq(&changed, &exact_record(&fork)));
            let mut invalid = command(3);
            invalid["payload"]["amount"] = json!("-1.00");
            assert!(fork.apply(&invalid).is_err());
            assert!(Arc::ptr_eq(&changed, &exact_record(&fork)));
            assert_eq!(
                fork.apply(&command(1)).unwrap().status,
                crate::Status::Duplicate
            );
            assert!(Arc::ptr_eq(&changed, &exact_record(&fork)));
            let wire = fork.checkpoint().unwrap();
            let mut restored = fresh();
            restored.restore(&wire.0, &wire.1).unwrap();
            assert_eq!(*exact_record(&restored), *changed);
            let before_refusal = exact_record(&restored);
            let mut corrupt = wire.0.clone();
            corrupt.push(b' ');
            assert!(restored.restore(&corrupt, &wire.1).is_err());
            assert!(Arc::ptr_eq(&before_refusal, &exact_record(&restored)));
            fork.apply(&command(3)).unwrap();
            let extension = fork.checkpoint().unwrap();
            restored
                .restore_exact_extension(&extension.0, &extension.1)
                .unwrap();
            assert_eq!(*exact_record(&restored), *exact_record(&fork));
            assert!(!Arc::ptr_eq(&before_refusal, &exact_record(&restored)));
        }
    }
    #[test]
    fn cloned_owner_shares_immutable_journal_commands_without_changing_history() {
        for version in [4, 5] {
            let mut owner = if version == 4 {
                Manager::new(config()).unwrap()
            } else {
                Manager::new_checkpoint5(config()).unwrap()
            };
            owner.apply(&command(1)).unwrap();
            let original = owner.checkpoint().unwrap();
            let mut fork = owner.clone();
            let a: &Value = &owner.state.journal[0];
            let b: &Value = &fork.state.journal[0];
            assert!(
                std::ptr::eq(a, b),
                "a clone deep-copied an immutable accepted journal command"
            );
            fork.apply(&command(2)).unwrap();
            assert_eq!(owner.state.journal.len(), 1);
            assert_eq!(fork.state.journal.len(), 2);
            assert_eq!(owner.checkpoint().unwrap(), original);
            let changed = fork.checkpoint().unwrap();
            let mut cold = owner.fresh().unwrap();
            cold.restore(&changed.0, &changed.1).unwrap();
            assert_eq!(cold.checkpoint().unwrap(), changed);
        }
    }
    fn exact_original_size(owner: &Manager) {
        // Independent literal schema4 serialization, not the codec's budget helper.
        let full=serde_json::to_vec(&json!({"schema_version":4,"config":owner.config,"journal":owner.state.journal.iter().map(std::sync::Arc::as_ref).collect::<Vec<_>>(),"state":owner.state()})).unwrap();
        let empty = serde_json::to_vec(
            &json!({"schema_version":4,"config":owner.config,"journal":[],"state":owner.state()}),
        )
        .unwrap();
        assert_eq!(empty.len() + owner.journal_bytes, full.len());
    }
    #[test]
    fn original_utf8_journal_size_tracks_only_successful_appends_clone_and_restore() {
        for version in [4, 5] {
            let fresh = || {
                if version == 4 {
                    Manager::new(config()).unwrap()
                } else {
                    Manager::new_checkpoint5(config()).unwrap()
                }
            };
            let mut owner = fresh();
            exact_original_size(&owner);
            for n in 1..=3 {
                owner.apply(&command(n)).unwrap();
                exact_original_size(&owner);
            }
            let before = owner.checkpoint().unwrap();
            let count = owner.journal_bytes;
            assert_eq!(
                owner.apply(&command(3)).unwrap().status,
                crate::Status::Duplicate
            );
            assert_eq!(owner.journal_bytes, count);
            assert_eq!(owner.checkpoint().unwrap(), before);
            let mut redelivery = command(3);
            redelivery["command_id"] = json!("另一投递-\\\"");
            assert_eq!(
                owner.apply(&redelivery).unwrap().status,
                crate::Status::Duplicate
            );
            assert!(
                owner.journal_bytes > count,
                "a distinct retained receipt really appends its original command"
            );
            exact_original_size(&owner);
            let before = owner.checkpoint().unwrap();
            let count = owner.journal_bytes;
            let mut invalid = command(4);
            invalid["payload"]["amount"] = json!("-1.00");
            assert!(owner.apply(&invalid).is_err());
            assert_eq!(owner.journal_bytes, count);
            exact_original_size(&owner);
            let mut fork = owner.clone();
            fork.apply(&command(4)).unwrap();
            exact_original_size(&fork);
            assert_eq!(owner.checkpoint().unwrap(), before);
            assert_eq!(owner.journal_bytes, count);
            let fork_bytes = fork.checkpoint().unwrap();
            owner.apply(&command(5)).unwrap();
            exact_original_size(&owner);
            assert_eq!(fork.checkpoint().unwrap(), fork_bytes);
            let checkpoint = owner.checkpoint().unwrap();
            let mut restored = fresh();
            restored.restore(&checkpoint.0, &checkpoint.1).unwrap();
            exact_original_size(&restored);
            assert_eq!(restored.journal_bytes, owner.journal_bytes);
            assert_eq!(restored.checkpoint_version, version);
            assert_eq!(restored.checkpoint().unwrap(), checkpoint);
        }
    }
}

#[cfg(test)]
std::thread_local! {
    pub(crate) static ACCOUNT_COMMAND_REPLAYS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}

#[cfg(test)]
std::thread_local! {static CHECKPOINT_ENCODINGS:std::cell::Cell<u64>=const{std::cell::Cell::new(0)};}
