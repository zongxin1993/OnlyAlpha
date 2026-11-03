//! Immutable source expectations, never producer authentication or permits.
use crate::{Runtime, SqliteStore, codec};
use onlyalpha_execution::{Components, Error, Record, digest};
use rusqlite::{OptionalExtension, TransactionBehavior, params};
use serde_json::{Value, json};
use std::io::Write;
fn bad(reason: &str) -> Error {
    Error(format!("RUNTIME_REPLAY_{reason}"))
}
#[cfg(test)]
std::thread_local! {
 static REFERENCE_TAG_PARSES:std::cell::Cell<u64>=const{std::cell::Cell::new(0)};
 static REFERENCE_FRAME_INSPECTIONS:std::cell::Cell<u64>=const{std::cell::Cell::new(0)};
 static REFERENCE_SOURCE_ROWS:std::cell::Cell<u64>=const{std::cell::Cell::new(0)};
 // Actual owned copies of complete encoded Replay payload bytes only.
 static REFERENCE_OWNED_RAW_BYTES:std::cell::Cell<u64>=const{std::cell::Cell::new(0)};
 static REFERENCE_INPUT_HASHES:std::cell::RefCell<Option<(Value,u64)>>=const{std::cell::RefCell::new(None)};
}
fn sql<T>(value: rusqlite::Result<T>) -> Result<T, Error> {
    value.map_err(|e| bad(&format!("SQL: {e}")))
}
fn sha(v: &Value) -> String {
    #[cfg(test)]
    REFERENCE_INPUT_HASHES.with(|watch| {
        if let Some((input, count)) = watch.borrow_mut().as_mut() {
            if input == v {
                *count += 1;
            }
        }
    });
    digest(v.to_string().as_bytes())
}
fn fingerprint(value: &Value) -> Result<String, Error> {
    value
        .as_str()
        .filter(|s| {
            s.len() == 64
                && s.bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        })
        .map(str::to_owned)
        .ok_or_else(|| bad("REFERENCE_HASH"))
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReplayEntryRef {
    index: u64,
    previous: String,
    logical: String,
    physical: String,
    start: u64,
    inputs: Vec<String>,
    ready: bool,
    version: u32,
    encoded: u64,
    decoded: u64,
    dictionary: bool,
    basis: Option<(u64, String, String)>,
}
// Pure frame/header decoding only. Ready is deliberately absent from the
// cached expectation; every actual SQL row supplies and checks it separately.
pub(crate) struct CachedReplayReference {
    raw: String,
    physical: String,
    version: u32,
    metadata: ReplayEntryRef,
}
impl ReplayEntryRef {
    pub fn index(&self) -> u64 {
        self.index
    }
    pub fn logical_fingerprint(&self) -> &str {
        &self.logical
    }
    pub fn physical_fingerprint(&self) -> &str {
        &self.physical
    }
    pub fn execution_start(&self) -> u64 {
        self.start
    }
    pub fn ready(&self) -> bool {
        self.ready
    }
    pub fn encoded_size(&self) -> u64 {
        self.encoded
    }
    pub fn decoded_size(&self) -> u64 {
        self.decoded
    }
    fn same_body(&self, other: &Self) -> bool {
        let mut a = self.clone();
        let mut b = other.clone();
        a.ready = false;
        b.ready = false;
        a == b
    }
}
fn summary(step: &Value) -> Result<Value, Error> {
    let fields = [
        "schema_version",
        "index",
        "previous",
        "execution_start",
        "cause",
        "inputs",
        "state",
    ];
    if step
        .as_object()
        .is_none_or(|m| m.len() != fields.len() || fields.iter().any(|k| !m.contains_key(*k)))
        || step["schema_version"] != 1
    {
        return Err(bad("FIELDS"));
    }
    let index = step["index"]
        .as_u64()
        .filter(|n| *n > 0 && *n <= 65536)
        .ok_or_else(|| bad("INDEX"))?;
    let previous = fingerprint(&step["previous"])?;
    let start = step["execution_start"]
        .as_u64()
        .ok_or_else(|| bad("PREFIX"))?;
    let inputs = step["inputs"]
        .as_array()
        .filter(|v| v.len() <= 512)
        .ok_or_else(|| bad("INPUTS"))?;
    Ok(
        json!({"kind":"REPLAY_STEP","index":index,"previous":previous,"execution_start":start,"input_fingerprints":inputs.iter().map(sha).collect::<Vec<_>>()}),
    )
}
fn from_frame(
    raw: &str,
    physical: &str,
    index: i64,
    ready: i64,
    version: u32,
) -> Result<ReplayEntryRef, Error> {
    if !matches!(ready, 0 | 1) {
        return Err(bad("READY"));
    }
    if version == 4 && raw.len() > codec::STORED_LIMIT {
        return Err(bad("FRAME_BOUND"));
    }
    #[cfg(test)]
    if matches!(version, 3 | 4) {
        REFERENCE_FRAME_INSPECTIONS.with(|count| count.set(count.get() + 1));
    }
    let dictionary = if version == 4 {
        #[cfg(test)]
        REFERENCE_TAG_PARSES.with(|n| n.set(n.get() + 1));
        serde_json::from_str::<Value>(raw)?["codec"] == crate::dictionary_codec::NAME
    } else {
        false
    };
    let mut basis = None;
    let (meta, logical, decoded) = if dictionary {
        let frame = crate::dictionary_codec::inspect(
            raw,
            physical,
            u64::try_from(index).map_err(|_| bad("INDEX"))?,
        )?;
        basis = frame.basis.map(|b| (b.sequence, b.physical, b.logical));
        (frame.summary, frame.logical, frame.size as u64)
    } else if matches!(version, 3 | 4) {
        let f = codec::inspect(raw, physical)?;
        (f.summary, f.logical, f.size as u64)
    } else {
        let value: Value = serde_json::from_str(raw)?;
        if value.to_string() != raw || digest(raw.as_bytes()) != physical {
            return Err(bad("DIGEST"));
        }
        (summary(&value)?, sha(&value), raw.len() as u64)
    };
    let keys = [
        "kind",
        "index",
        "previous",
        "execution_start",
        "input_fingerprints",
    ];
    if meta
        .as_object()
        .is_none_or(|m| m.len() != keys.len() || keys.iter().any(|k| !m.contains_key(*k)))
        || meta["kind"] != "REPLAY_STEP"
    {
        return Err(bad("REFERENCE"));
    }
    let n = meta["index"]
        .as_u64()
        .filter(|n| *n > 0 && *n <= 65536)
        .ok_or_else(|| bad("INDEX"))?;
    if i64::try_from(n).ok() != Some(index) {
        return Err(bad("INDEX"));
    }
    let inputs = meta["input_fingerprints"]
        .as_array()
        .filter(|v| v.len() <= 512)
        .ok_or_else(|| bad("INPUTS"))?
        .iter()
        .map(fingerprint)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(ReplayEntryRef {
        index: n,
        previous: fingerprint(&meta["previous"])?,
        logical,
        physical: physical.into(),
        start: meta["execution_start"]
            .as_u64()
            .ok_or_else(|| bad("PREFIX"))?,
        inputs,
        ready: ready == 1,
        version,
        encoded: raw.len() as u64,
        decoded,
        dictionary,
        basis,
    })
}
impl SqliteStore {
    // A matching complete actual row may reuse only its immutable codec result.
    // The caller still checks this invocation's lineage, flags, head and inputs.
    fn reference_metadata(
        &self,
        raw: &str,
        physical: &str,
        index: i64,
        ready: i64,
    ) -> Result<ReplayEntryRef, Error> {
        if !matches!(ready, 0 | 1) {
            return Err(bad("READY"));
        }
        if !matches!(self.storage_version, 3 | 4) {
            return from_frame(raw, physical, index, ready, self.storage_version);
        }
        if let Some(cached) = self.replay_reference_metadata.borrow().get(&index)
            && cached.version == self.storage_version
            && cached.raw == raw
            && cached.physical == physical
        {
            let mut entry = cached.metadata.clone();
            entry.ready = ready == 1;
            return Ok(entry);
        }
        let entry = from_frame(raw, physical, index, ready, self.storage_version)?;
        let mut metadata = entry.clone();
        metadata.ready = false;
        #[cfg(test)]
        REFERENCE_OWNED_RAW_BYTES.with(|count| count.set(count.get() + raw.len() as u64));
        self.replay_reference_metadata.borrow_mut().insert(
            index,
            CachedReplayReference {
                raw: raw.into(),
                physical: physical.into(),
                version: self.storage_version,
                metadata,
            },
        );
        Ok(entry)
    }
    pub(crate) fn replay_refs_from_source(
        &self,
        records: &[Record],
    ) -> Result<Vec<ReplayEntryRef>, Error> {
        let binding = self.replay_binding()?.ok_or_else(|| bad("UNBOUND"))?;
        let mut previous = sha(&binding);
        let mut execution = 0_u64;
        let mut result: Vec<ReplayEntryRef> = Vec::new();
        let mut statement = sql(self
            .connection
            .prepare("SELECT sequence,payload,digest,ready FROM replay_steps ORDER BY sequence"))?;
        let mut rows = sql(statement.query([]))?;
        while let Some(row) = sql(rows.next())? {
            let index: i64 = sql(row.get(0))?;
            let raw = crate::store::text_column(row, 1)?;
            let physical = crate::store::text_column(row, 2)?;
            let ready: i64 = sql(row.get(3))?;
            #[cfg(test)]
            REFERENCE_SOURCE_ROWS.with(|count| count.set(count.get() + 1));
            let entry = self.reference_metadata(raw, physical, index, ready)?;
            if let Some((base, physical, logical)) = &entry.basis {
                let anchor = result
                    .get(
                        usize::try_from(base.checked_sub(1).ok_or_else(|| bad("BASIS"))?)
                            .map_err(|_| bad("BASIS"))?,
                    )
                    .ok_or_else(|| bad("BASIS"))?;
                if !anchor.dictionary
                    || anchor.basis.is_some()
                    || !anchor.ready
                    || anchor.physical != *physical
                    || anchor.logical != *logical
                {
                    return Err(bad("BASIS"));
                }
            }
            if entry.index != result.len() as u64 + 1
                || entry.previous != previous
                || entry.start != execution
                || result.last().is_some_and(|r| !r.ready)
            {
                return Err(bad("LINEAGE"));
            }
            for expected in &entry.inputs {
                execution = execution.checked_add(1).ok_or_else(|| bad("BOUND"))?;
                if let Some(actual) =
                    records.get(usize::try_from(execution - 1).map_err(|_| bad("BOUND"))?)
                {
                    if actual.prepared().input_fingerprint() != expected {
                        return Err(bad("EXECUTION_RELATION"));
                    }
                }
            }
            if entry.ready && execution > records.len() as u64 {
                return Err(bad("READY_AHEAD"));
            }
            previous = entry.logical.clone();
            result.push(entry);
        }
        let (head, last): (i64, Option<String>) = sql(self.connection.query_row(
            "SELECT head,last_hash FROM replay_binding WHERE singleton=1",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        ))?;
        if head != result.len() as i64
            || last
                != if result.is_empty() {
                    None
                } else {
                    Some(previous)
                }
            || records.len() as u64 > execution
        {
            return Err(bad("JOURNAL_HEAD"));
        }
        Ok(result)
    }
    // One owning invocation only. Runtime reconciles its actual owners against
    // these same freshly read complete rows; the raw Store caller retains its
    // original lower-level contract. Neither branch retains a source proof.
    fn fresh_ref_source(
        &self,
        current: Option<&Components>,
    ) -> Result<(usize, Vec<ReplayEntryRef>), Error> {
        let read = |records: &[Record]| {
            self.replay_refs_from_source(records)
                .map(|refs| (records.len(), refs))
        };
        match current {
            Some(current) => self.with_ready_source(current, |source| read(source.records())),
            None => read(&self.read_records()?),
        }
    }
    pub(crate) fn fresh_refs(&self) -> Result<Vec<ReplayEntryRef>, Error> {
        self.fresh_ref_source(None).map(|(_, refs)| refs)
    }
    // A pure dictionary memo never substitutes for this call's actual base row.
    fn replay_anchor(
        &self,
        raw: &str,
        physical: &str,
        index: u64,
    ) -> Result<std::sync::Arc<crate::dictionary_codec::Anchor>, Error> {
        let frame = crate::dictionary_codec::inspect(raw, physical, index)?;
        if frame.basis.is_some() {
            return Err(bad("BASIS"));
        }
        if let Some((previous, anchor)) = self.replay_anchors.borrow().get(&index)
            && previous == raw
            && anchor.sequence() == index
            && anchor.physical() == physical
            && anchor.logical() == frame.logical
        {
            return Ok(std::sync::Arc::clone(anchor));
        }
        let (value, anchor) = crate::dictionary_codec::decode_anchor(&frame)?;
        if summary(&value)? != frame.summary {
            return Err(bad("REFERENCE_BODY"));
        }
        let anchor = std::sync::Arc::new(anchor);
        self.replay_anchors
            .borrow_mut()
            .insert(index, (raw.into(), std::sync::Arc::clone(&anchor)));
        Ok(anchor)
    }
    fn observed_encoded_step(
        &self,
        reference: &ReplayEntryRef,
    ) -> Result<
        (
            String,
            Option<std::sync::Arc<crate::dictionary_codec::Anchor>>,
        ),
        Error,
    > {
        self.validate_identity_for_reference()?;
        let base = reference.basis.as_ref().map_or(0, |b| b.0);
        // Target and fixed base are observed in one SQLite statement/snapshot.
        let row:Option<(String,String,i64,Option<String>,Option<String>,Option<i64>)>=sql(self.connection.query_row("SELECT t.payload,t.digest,t.ready,b.payload,b.digest,b.ready FROM replay_steps t LEFT JOIN replay_steps b ON b.sequence=?2 WHERE t.sequence=?1",params![i64::try_from(reference.index).map_err(|_|bad("BOUND"))?,i64::try_from(base).map_err(|_|bad("BOUND"))?],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get(4)?,row.get(5)?))).optional())?;
        let (raw, physical, ready, base_raw, base_physical, base_ready) =
            row.ok_or_else(|| bad("MISSING_STEP"))?;
        let actual = from_frame(
            &raw,
            &physical,
            reference.index as i64,
            ready,
            self.storage_version,
        )?;
        if actual != *reference {
            return Err(bad("SOURCE_CHANGED"));
        }
        let anchor = if let Some((base, expected_physical, expected_logical)) = &actual.basis {
            let base_raw = base_raw.ok_or_else(|| bad("BASIS"))?;
            let physical = base_physical.ok_or_else(|| bad("BASIS"))?;
            let observed = from_frame(
                &base_raw,
                &physical,
                *base as i64,
                base_ready.ok_or_else(|| bad("BASIS"))?,
                self.storage_version,
            )?;
            if !observed.dictionary
                || observed.basis.is_some()
                || !observed.ready
                || observed.physical != *expected_physical
                || observed.logical != *expected_logical
            {
                return Err(bad("BASIS"));
            }
            Some(self.replay_anchor(&base_raw, &physical, *base)?)
        } else {
            None
        };
        Ok((raw, anchor))
    }
    pub(crate) fn encoded_step(&self, reference: &ReplayEntryRef) -> Result<String, Error> {
        self.observed_encoded_step(reference).map(|v| v.0)
    }
    pub(crate) fn logical_step(&self, reference: &ReplayEntryRef) -> Result<Value, Error> {
        let (raw, anchor) = self.observed_encoded_step(reference)?;
        let value = if reference.dictionary {
            let f = crate::dictionary_codec::inspect(&raw, &reference.physical, reference.index)?;
            let value = if f.basis.is_none() {
                crate::dictionary_codec::decode_anchor(&f)?.0
            } else {
                crate::dictionary_codec::decode(&f, anchor.as_deref())?
            };
            if summary(&value)? != f.summary {
                return Err(bad("REFERENCE_BODY"));
            }
            value
        } else if matches!(self.storage_version, 3 | 4) {
            let f = codec::inspect(&raw, &reference.physical)?;
            let value = codec::decode(&f)?;
            if summary(&value)? != f.summary {
                return Err(bad("REFERENCE_BODY"));
            }
            value
        } else {
            serde_json::from_str(&raw)?
        };
        if sha(&value) != reference.logical {
            return Err(bad("REFERENCE_BODY"));
        }
        Ok(value)
    }
    fn encode_step(
        &self,
        step: &Value,
        meta: Value,
        prefix: &[ReplayEntryRef],
        index: u64,
    ) -> Result<String, Error> {
        if self.storage_version == 4 {
            let base = crate::dictionary_codec::anchor_sequence(index)?;
            let anchor = if base == index {
                None
            } else {
                let reference = prefix
                    .get(usize::try_from(base - 1).map_err(|_| bad("BASIS"))?)
                    .ok_or_else(|| bad("BASIS"))?;
                if !reference.dictionary || reference.basis.is_some() || !reference.ready {
                    return Err(bad("BASIS"));
                }
                let raw = self.encoded_step(reference)?;
                Some(self.replay_anchor(&raw, &reference.physical, base)?)
            };
            crate::dictionary_codec::encode_bytes(
                &serde_json::to_vec(step)?,
                meta,
                index,
                anchor.as_deref(),
            )
        } else if self.storage_version == 3 {
            codec::encode(step, meta)
        } else {
            Ok(step.to_string())
        }
    }
    pub(crate) fn prepare_ref(
        &mut self,
        prefix: &[ReplayEntryRef],
        step: &Value,
        current: Option<&Components>,
    ) -> Result<ReplayEntryRef, Error> {
        let meta = summary(step)?;
        let index = step["index"].as_u64().ok_or_else(|| bad("INDEX"))?;
        if index != prefix.len() as u64 + 1 || prefix.iter().any(|r| !r.ready) {
            return Err(bad("STEP_PRECONDITION"));
        }
        let (execution_head, actual) = self.fresh_ref_source(current)?;
        if actual.len() > prefix.len() + 1 || actual.get(..prefix.len()) != Some(prefix) {
            return Err(bad("STEP_PRECONDITION"));
        }
        let raw = self.encode_step(step, meta, prefix, index)?;
        let physical = digest(raw.as_bytes());
        let expected = from_frame(&raw, &physical, index as i64, 0, self.storage_version)?;
        if actual.len() == prefix.len() + 1
            && actual[..prefix.len()] == *prefix
            && actual.last().is_some_and(|r| r.same_body(&expected))
        {
            return Ok(actual.last().expect("last").clone());
        }
        if actual != prefix {
            return Err(bad("STEP_PRECONDITION"));
        }
        let previous = match prefix.last() {
            Some(last) => last.logical.clone(),
            None => sha(&self.replay_binding()?.ok_or_else(|| bad("UNBOUND"))?),
        };
        if expected.previous != previous || expected.start != execution_head as u64 {
            return Err(bad("STEP_PRECONDITION"));
        }
        let tx = sql(self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate))?;
        sql(tx.execute(
            "INSERT INTO replay_steps VALUES(?1,?2,?3,0)",
            params![index as i64, &raw, &physical],
        ))?;
        sql(tx.execute(
            "UPDATE replay_binding SET head=?1,last_hash=?2 WHERE singleton=1",
            params![index as i64, &expected.logical],
        ))?;
        sql(tx.commit())?;
        let (_, observed) = self.fresh_ref_source(current)?;
        let mut all = prefix.to_vec();
        all.push(expected.clone());
        if observed != all || self.logical_step(&expected)? != *step {
            return Err(bad("STEP_READBACK"));
        }
        Ok(expected)
    }
    pub(crate) fn complete_ref(
        &mut self,
        prefix: &[ReplayEntryRef],
        original: &ReplayEntryRef,
        current: Option<&Components>,
    ) -> Result<Vec<ReplayEntryRef>, Error> {
        let (execution_head, actual) = self.fresh_ref_source(current)?;
        if actual.len() != prefix.len() + 1
            || actual[..prefix.len()] != *prefix
            || actual.last().is_none_or(|r| !r.same_body(original))
            || prefix.iter().any(|r| !r.ready)
        {
            return Err(bad("INCOMPLETE"));
        }
        if original.start.checked_add(original.inputs.len() as u64) != Some(execution_head as u64) {
            return Err(bad("INCOMPLETE"));
        }
        sql(self.connection.execute(
            "UPDATE replay_steps SET ready=1 WHERE sequence=?1",
            [original.index as i64],
        ))?;
        let (_, observed) = self.fresh_ref_source(current)?;
        let mut expected = prefix.to_vec();
        let mut last = original.clone();
        last.ready = true;
        expected.push(last);
        if observed != expected {
            return Err(bad("READY_READBACK"));
        }
        Ok(observed)
    }
}
impl Runtime {
    pub fn storage_version(&self) -> u32 {
        self.store.storage_version
    }
    pub fn replay_refs(&self) -> Result<Vec<ReplayEntryRef>, Error> {
        self.require_healthy()?;
        self.store.with_ready_source(&self.components, |source| {
            self.store.replay_refs_from_source(source.records())
        })
    }
    pub fn verify_replay_refs(&self, expected: &[ReplayEntryRef]) -> Result<(), Error> {
        if self.replay_refs()? != expected {
            return Err(bad("SOURCE_CHANGED"));
        }
        Ok(())
    }
    /// One pending-event observation bound to the exact expected Replay prefix.
    /// Data only; delivery and acknowledgement retain their own actual source checks.
    pub fn pending_events_at_replay_refs(
        &self,
        expected: &[ReplayEntryRef],
    ) -> Result<Vec<Value>, Error> {
        self.require_healthy()?;
        self.store.with_ready_source(&self.components, |source| {
            if self.store.replay_refs_from_source(source.records())? != expected {
                return Err(bad("SOURCE_CHANGED"));
            }
            onlyalpha_execution::pending_events(source, &self.components)
        })
    }
    pub fn read_replay_step(&self, reference: &ReplayEntryRef) -> Result<Value, Error> {
        self.require_healthy()?;
        self.store.logical_step(reference)
    }
    pub fn write_encoded_step(
        &self,
        reference: &ReplayEntryRef,
        writer: &mut dyn Write,
    ) -> Result<u64, Error> {
        self.require_healthy()?;
        let raw = self.store.encoded_step(reference)?;
        writer
            .write_all(raw.as_bytes())
            .map_err(|e| bad(&e.to_string()))?;
        Ok(raw.len() as u64)
    }
    pub fn prepare_replay_ref(
        &mut self,
        prefix: &[ReplayEntryRef],
        step: &Value,
    ) -> Result<ReplayEntryRef, Error> {
        self.require_healthy()?;
        self.healthy = false;
        let reference = self
            .store
            .prepare_ref(prefix, step, Some(&self.components))?;
        self.healthy = true;
        Ok(reference)
    }
    pub fn complete_replay_ref(
        &mut self,
        prefix: &[ReplayEntryRef],
        original: &ReplayEntryRef,
    ) -> Result<Vec<ReplayEntryRef>, Error> {
        self.require_healthy()?;
        self.healthy = false;
        let refs = self
            .store
            .complete_ref(prefix, original, Some(&self.components))?;
        self.healthy = true;
        Ok(refs)
    }
}

#[cfg(test)]
#[path = "../tests/support/replay_references.rs"]
mod reference_tests;

#[cfg(test)]
mod frame_bound_tests {
    use super::*;
    #[test]
    fn oversized_storage4_frame_is_rejected_before_tag_json_allocation() {
        let raw =
            json!({"codec":"ZSTD_CANONICAL_JSON_DICTIONARY_V1","data":"x".repeat(16*1024*1024)})
                .to_string();
        REFERENCE_TAG_PARSES.with(|n| n.set(0));
        let result = from_frame(&raw, &digest(raw.as_bytes()), 1, 1, 4);
        assert!(result.is_err());
        assert_eq!(
            REFERENCE_TAG_PARSES.with(std::cell::Cell::get),
            0,
            "untrusted over-budget frame reached tag JSON parsing"
        );
    }
}
