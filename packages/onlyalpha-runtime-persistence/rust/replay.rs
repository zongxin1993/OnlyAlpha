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
fn decoded(raw: &str, h: &str) -> Result<Value, Error> {
    let v: Value = serde_json::from_str(raw)?;
    let canonical = serde_json::to_string(&v)?;
    if canonical != raw || digest(canonical.as_bytes()) != h {
        return Err(err("DIGEST"));
    }
    Ok(v)
}
impl SqliteStore {
    fn replay_binding(&self) -> Result<Option<Value>, Error> {
        let row: Option<(String, String)> = sql(self
            .connection
            .query_row(
                "SELECT payload,digest FROM replay_binding WHERE singleton=1",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional())?;
        row.map(|(s, h)| decoded(&s, &h)).transpose()
    }
    pub(crate) fn bind_replay(&mut self, b: &Value) -> Result<(), Error> {
        fields(
            b,
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
        let head = self.head()?;
        for (index, raw, h, ready) in rows {
            let v = decoded(&raw, &h)?;
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
                    && self
                        .get(execution)?
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
            result.push(json!({"step":v,"ready":ready==1}));
        }
        if journal_head != i64::try_from(result.len()).map_err(|_| err("BOUND"))?
            || last_hash != result.last().map(|s| hash(&s["step"]))
        {
            return Err(err("JOURNAL_HEAD"));
        }
        if head > execution {
            return Err(err("UNMAPPED_EXECUTION"));
        }
        Ok(result)
    }
    pub(crate) fn prepare_replay(&mut self, v: &Value) -> Result<(), Error> {
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
    pub(crate) fn complete_replay(&mut self, index: u64) -> Result<(), Error> {
        let steps = self.replay_steps()?;
        let last = steps.last().ok_or_else(|| err("MISSING_STEP"))?;
        let v = &last["step"];
        if v["index"] != index
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
        if self
            .replay_steps()?
            .last()
            .is_none_or(|s| s["ready"] != true)
        {
            return Err(err("READY_READBACK"));
        }
        Ok(())
    }
}
