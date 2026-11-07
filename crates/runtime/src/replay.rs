//! Serialized Application replay journal, sharing the exact Execution database and lease.
use crate::SqliteStore;
use onlyalpha_execution::{Error, Store, digest};
use rusqlite::{OptionalExtension, TransactionBehavior, params};
use serde_json::{Value, json};
fn err(s: &str) -> Error {
    Error(format!("RUNTIME_REPLAY_{s}"))
}
fn sql<T>(r: rusqlite::Result<T>) -> Result<T, Error> {
    r.map_err(|e| err(&format!("SQL: {e}")))
}
fn hash(v: &Value) -> String {
    digest(v.to_string().as_bytes())
}
fn fields(v: &Value, keys: &[&str]) -> Result<(), Error> {
    if v.as_object()
        .is_none_or(|m| m.len() != keys.len() || keys.iter().any(|k| !m.contains_key(*k)))
        || v["schema_version"] != 1
    {
        return Err(err("FIELDS"));
    }
    Ok(())
}
#[cfg(test)]
std::thread_local! {
    static REPLAY_STEP_SOURCE_DECODES: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}
fn decoded(raw: &str, h: &str) -> Result<Value, Error> {
    let v: Value = serde_json::from_str(raw)?;
    #[cfg(test)]
    if v.get("index").is_some() {
        REPLAY_STEP_SOURCE_DECODES.with(|count| count.set(count.get() + 1));
    }
    let canonical = serde_json::to_string(&v)?;
    if canonical != raw || digest(canonical.as_bytes()) != h {
        return Err(err("DIGEST"));
    }
    Ok(v)
}
// The original canonical binding and SHA under one exact immutable decoder
// context. No head, last hash, source rows, flags, Ready or successful source
// cut is retained. Every use still observes the complete actual SQL row.
pub(crate) struct ReplayBindingData {
    raw: String,
    fingerprint: String,
    identity: Value,
    storage_version: u32,
    value: Value,
}
impl ReplayBindingData {
    pub(crate) fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
}
#[cfg(test)]
std::thread_local! {
    static BINDING_ACTUAL_ROWS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    static BINDING_CODEC_DECODES: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    static BINDING_CODEC_HITS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}
pub(crate) struct DecodedReplayRow {
    payload: String,
    digest: String,
    value: Value,
}
impl SqliteStore {
    fn decode_replay_step(
        &self,
        sequence: i64,
        raw: String,
        expected: &str,
    ) -> Result<Value, Error> {
        // The actual complete SQL bytes are hashed on every read, including hits.
        // This memo reuses only canonical JSON decoding, never source/Ready proof.
        if digest(raw.as_bytes()) != expected {
            return Err(err("DIGEST"));
        }
        if let Some(cached) = self.decoded_replay_rows.borrow().get(&sequence)
            && cached.payload == raw
            && cached.digest == expected
        {
            return Ok(cached.value.clone());
        }
        let value = decoded(&raw, expected)?;
        self.decoded_replay_rows.borrow_mut().insert(
            sequence,
            DecodedReplayRow {
                payload: raw,
                digest: expected.into(),
                value: value.clone(),
            },
        );
        Ok(value)
    }
    pub(crate) fn replay_binding(&self) -> Result<Option<Value>, Error> {
        self.replay_binding_data()
            .map(|binding| binding.map(|binding| binding.value.clone()))
    }
    pub(crate) fn replay_binding_data(
        &self,
    ) -> Result<Option<std::sync::Arc<ReplayBindingData>>, Error> {
        let row: Option<(String, String)> = sql(self
            .connection
            .query_row(
                "SELECT payload,digest FROM replay_binding WHERE singleton=1",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional())?;
        #[cfg(test)]
        BINDING_ACTUAL_ROWS.with(|count| count.set(count.get() + 1));
        let Some((raw, fingerprint)) = row else {
            return Ok(None);
        };
        if let Some(cached) = self.replay_binding_codec.borrow().as_ref()
            && cached.storage_version == self.storage_version
            && cached.identity == self.identity
            && cached.raw.as_bytes() == raw.as_bytes()
            && cached.fingerprint == fingerprint
        {
            #[cfg(test)]
            BINDING_CODEC_HITS.with(|count| count.set(count.get() + 1));
            return Ok(Some(std::sync::Arc::clone(cached)));
        }
        #[cfg(test)]
        BINDING_CODEC_DECODES.with(|count| count.set(count.get() + 1));
        // Keep the cold/changed row's original parse, canonical-byte/SHA and
        // context validator in the same order. Retain data only after success.
        let value = decoded(&raw, &fingerprint)?;
        self.validate_replay_binding(&value)?;
        let binding = std::sync::Arc::new(ReplayBindingData {
            raw,
            fingerprint,
            identity: self.identity.clone(),
            storage_version: self.storage_version,
            value,
        });
        *self.replay_binding_codec.borrow_mut() = Some(std::sync::Arc::clone(&binding));
        Ok(Some(binding))
    }
    fn validate_replay_binding(&self, b: &Value) -> Result<(), Error> {
        let mut shape = b.clone();
        let version = b["schema_version"]
            .as_u64()
            .ok_or_else(|| err("BINDING_VERSION"))?;
        if version == 2 {
            if !b["participants"].is_object()
                || b["work_id"]
                    .as_str()
                    .is_none_or(|id| id.is_empty() || id.len() > 256)
            {
                return Err(err("BINDING_WORK"));
            }
            shape
                .as_object_mut()
                .ok_or_else(|| err("BINDING"))?
                .remove("work_id");
            shape
                .as_object_mut()
                .expect("object")
                .remove("participants");
            shape["schema_version"] = json!(1);
        } else if version != 1 {
            return Err(err("BINDING_VERSION"));
        }
        fields(
            &shape,
            &[
                "schema_version",
                "configuration",
                "kernel_artifact",
                "driver_artifact",
                "work",
                "input_pin",
                "program",
                "initial_state",
            ],
        )?;
        if b.to_string().len() > 128 * 1024 * 1024
            || b["configuration"] != hash(&self.identity["configuration"])
            || b["kernel_artifact"] != self.identity["kernel_artifact"]
        {
            return Err(err("BINDING"));
        }
        for key in ["work", "input_pin", "program", "driver_artifact"] {
            if b[key].as_str().is_none_or(|s| {
                s.len() != 64
                    || !s
                        .bytes()
                        .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
            }) {
                return Err(err("IDENTITY"));
            }
        }
        if version == 2 {
            let program = &b["participants"];
            let strategies = self.identity["configuration"]["profiles"]
                .as_object()
                .ok_or_else(|| err("BINDING"))?
                .iter()
                .map(|(cluster, profile)| (cluster.clone(), profile["revision"].clone()))
                .collect::<serde_json::Map<String, Value>>();
            let expected = hash(
                &json!({"work_id":b["work_id"],"configuration":self.identity["configuration"],"artifact":b["kernel_artifact"],"driver_artifact":b["driver_artifact"],"input_pin":b["input_pin"],"participants":program,"initial_ns":b["initial_state"]["clock_ns"]}),
            );
            if program["schema_version"] != 1
                || program["configuration"] != b["configuration"]
                || program["generation"] != self.identity["configuration"]["generation"]
                || program["initial_ns"] != b["initial_state"]["clock_ns"]
                || program["strategies"] != Value::Object(strategies)
                || program["opening_profile"] != json!({"schema_version":1,"kind":"OPEN_CLOSE_V1"})
                || b["program"] != hash(program)
                || b["work"] != expected
            {
                return Err(err("BINDING_WORK"));
            }
        }
        Ok(())
    }
    pub(crate) fn bind_replay(&mut self, b: &Value) -> Result<(), Error> {
        self.validate_replay_binding(b)?;
        if let Some(old) = self.replay_binding()? {
            if old != *b {
                return Err(err("WORK_CONFLICT"));
            }
            self.replay_steps()?;
            return Ok(());
        }
        if self.head()? != 0 {
            return Err(err("UNBOUND_HISTORY"));
        }
        sql(self.connection.execute(
            "INSERT INTO replay_binding VALUES(1,?1,?2,0,NULL)",
            params![b.to_string(), hash(b)],
        ))?;
        if self.replay_binding()?.as_ref() != Some(b) {
            return Err(err("BINDING_READBACK"));
        }
        Ok(())
    }
    pub(crate) fn replay_steps(&self) -> Result<Vec<Value>, Error> {
        let records = self.read_records()?;
        self.replay_steps_from_source(&records)
    }
    // Source rows come only from this operation's complete owning SQL read.
    pub(crate) fn replay_steps_from_source(
        &self,
        records: &[onlyalpha_execution::Record],
    ) -> Result<Vec<Value>, Error> {
        if matches!(self.storage_version, 3 | 4) {
            let refs = self.replay_refs_from_source(records)?;
            let mut total = 0_u64;
            let mut result = Vec::with_capacity(refs.len());
            for reference in refs {
                total = total
                    .checked_add(reference.decoded_size())
                    .filter(|n| *n <= 128 * 1024 * 1024)
                    .ok_or_else(|| err("EXPANSION_BOUND"))?;
                result
                    .push(json!({"step":self.logical_step(&reference)?,"ready":reference.ready()}));
            }
            return Ok(result);
        }
        let b = self.replay_binding()?.ok_or_else(|| err("UNBOUND"))?;
        let mut query = sql(self
            .connection
            .prepare("SELECT sequence,payload,digest,ready FROM replay_steps ORDER BY sequence"))?;
        let rows = sql(sql(query.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, i64>(3)?,
            ))
        }))?
        .collect::<rusqlite::Result<Vec<_>>>())?;
        let (journal_head, last_hash): (i64, Option<String>) = sql(self.connection.query_row(
            "SELECT head,last_hash FROM replay_binding WHERE singleton=1",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        ))?;
        let mut result = Vec::new();
        let mut previous = hash(&b);
        let mut execution = 0u64;
        let head = u64::try_from(records.len()).map_err(|_| err("BOUND"))?;
        for (index, raw, h, ready) in rows {
            let v = self.decode_replay_step(index, raw, &h)?;
            fields(
                &v,
                &[
                    "schema_version",
                    "index",
                    "previous",
                    "execution_start",
                    "cause",
                    "inputs",
                    "state",
                ],
            )?;
            if index != i64::try_from(result.len() + 1).map_err(|_| err("BOUND"))?
                || v["index"] != index
                || v["previous"] != previous
                || v["execution_start"] != execution
                || result.last().is_some_and(|x: &Value| x["ready"] != true)
                || !matches!(ready, 0 | 1)
            {
                return Err(err("LINEAGE"));
            }
            let inputs = v["inputs"]
                .as_array()
                .filter(|v| v.len() <= 512)
                .ok_or_else(|| err("INPUTS"))?;
            for input in inputs {
                execution = execution.checked_add(1).ok_or_else(|| err("BOUND"))?;
                if execution <= head
                    && records
                        .get(usize::try_from(execution - 1).map_err(|_| err("BOUND"))?)
                        .ok_or_else(|| err("MISSING_EXECUTION"))?
                        .prepared()
                        .input()
                        != input
                {
                    return Err(err("EXECUTION_RELATION"));
                }
            }
            if ready == 1 && execution > head {
                return Err(err("READY_AHEAD"));
            }
            previous = h;
            // Value is already fully decoded/canonical/hash checked above. Move
            // the entire state into the public projection instead of serializing
            // it again through json!'s borrowed Serialize interpolation.
            result.push(Value::Object(serde_json::Map::from_iter([
                ("step".into(), v),
                ("ready".into(), Value::Bool(ready == 1)),
            ])));
        }
        if journal_head != i64::try_from(result.len()).map_err(|_| err("BOUND"))?
            || last_hash
                != if result.is_empty() {
                    None
                } else {
                    Some(previous)
                }
        {
            return Err(err("JOURNAL_HEAD"));
        }
        if head > execution {
            return Err(err("UNMAPPED_EXECUTION"));
        }
        Ok(result)
    }
    pub(crate) fn prepare_replay(&mut self, v: &Value) -> Result<(), Error> {
        if matches!(self.storage_version, 3 | 4) {
            let refs = self.fresh_refs()?;
            let index = v["index"]
                .as_u64()
                .and_then(|n| n.checked_sub(1))
                .and_then(|n| usize::try_from(n).ok())
                .ok_or_else(|| err("INDEX"))?;
            let prefix = refs.get(..index).ok_or_else(|| err("INDEX"))?.to_vec();
            return self.prepare_ref(&prefix, v, None).map(drop);
        }
        let steps = self.replay_steps()?;
        fields(
            v,
            &[
                "schema_version",
                "index",
                "previous",
                "execution_start",
                "cause",
                "inputs",
                "state",
            ],
        )?;
        let index = v["index"]
            .as_u64()
            .filter(|n| *n > 0 && *n <= 65536)
            .ok_or_else(|| err("INDEX"))?;
        if let Some(old) = steps.get(usize::try_from(index - 1).map_err(|_| err("BOUND"))?) {
            if old["step"] != *v {
                return Err(err("STEP_CONFLICT"));
            }
            return Ok(());
        }
        let previous = steps.last().map_or_else(
            || self.replay_binding().map(|b| hash(&b.expect("bound"))),
            |s| Ok(hash(&s["step"])),
        )?;
        if index != steps.len() as u64 + 1
            || steps.last().is_some_and(|s| s["ready"] != true)
            || v["previous"] != previous
            || v["execution_start"] != self.head()?
            || v.to_string().len() > 128 * 1024 * 1024
            || v["inputs"].as_array().is_none_or(|v| v.len() > 512)
        {
            return Err(err("STEP_PRECONDITION"));
        }
        let tx = sql(self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate))?;
        sql(tx.execute(
            "INSERT INTO replay_steps VALUES(?1,?2,?3,0)",
            params![
                i64::try_from(index).map_err(|_| err("BOUND"))?,
                v.to_string(),
                hash(v)
            ],
        ))?;
        sql(tx.execute(
            "UPDATE replay_binding SET head=?1,last_hash=?2 WHERE singleton=1",
            params![i64::try_from(index).map_err(|_| err("BOUND"))?, hash(v)],
        ))?;
        sql(tx.commit())?;
        let exact = self.replay_steps()?;
        if exact
            .last()
            .is_none_or(|s| s["step"] != *v || s["ready"] != false)
        {
            return Err(err("STEP_READBACK"));
        }
        Ok(())
    }
    pub(crate) fn complete_replay(
        &mut self,
        index: u64,
        expected_step: &Value,
    ) -> Result<Vec<Value>, Error> {
        if matches!(self.storage_version, 3 | 4) {
            let refs = self.fresh_refs()?;
            let original = refs.last().ok_or_else(|| err("MISSING_STEP"))?.clone();
            if original.index() != index || self.logical_step(&original)? != *expected_step {
                return Err(err("INCOMPLETE"));
            }
            self.complete_ref(&refs[..refs.len() - 1], &original, None)?;
            return self.replay_steps();
        }
        let steps = self.replay_steps()?;
        let last = steps.last().ok_or_else(|| err("MISSING_STEP"))?;
        let v = &last["step"];
        if v != expected_step
            || v["index"] != index
            || v["execution_start"]
                .as_u64()
                .and_then(|s| s.checked_add(v["inputs"].as_array()?.len() as u64))
                != Some(self.head()?)
        {
            return Err(err("INCOMPLETE"));
        }
        sql(self.connection.execute(
            "UPDATE replay_steps SET ready=1 WHERE sequence=?1",
            [i64::try_from(index).map_err(|_| err("BOUND"))?],
        ))?;
        // Return this actual full post-write SQL cut rather than making the
        // caller refresh it again. A hash-valid different proposal is refused.
        let completed = self.replay_steps()?;
        if completed
            .last()
            .is_none_or(|row| row["ready"] != true || row["step"] != *expected_step)
        {
            return Err(err("READY_READBACK"));
        }
        Ok(completed)
    }
}

#[cfg(test)]
#[path = "tests/replay_codec_work.rs"]
mod replay_codec_work_tests;

#[cfg(test)]
#[path = "tests/binding_codec.rs"]
mod binding_codec_tests;
