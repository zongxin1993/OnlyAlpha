use onlyalpha_execution::{CommitIntent, Components, Error, Record, Store, digest, recover};
use rusqlite::{Connection, OpenFlags, OptionalExtension, TransactionBehavior, params};
use serde_json::{Value, json};
use std::{
    cell::RefCell,
    collections::BTreeMap,
    fs::{File, OpenOptions},
    path::Path,
    time::Duration,
};
const APPLICATION: i64 = 0x4f415250;
const SCHEMA: &[&str] = &[
    "CREATE TABLE meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL, digest TEXT NOT NULL) STRICT",
    "CREATE TABLE state (singleton INTEGER PRIMARY KEY CHECK(singleton=1), head INTEGER NOT NULL CHECK(head>=0), last_hash TEXT) STRICT",
    "CREATE TABLE records (sequence INTEGER PRIMARY KEY CHECK(sequence>0), input_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, digest TEXT NOT NULL) STRICT",
    "CREATE TABLE checkpoints (sequence INTEGER PRIMARY KEY CHECK(sequence>=0), payload TEXT NOT NULL, digest TEXT NOT NULL) STRICT",
];
const REPLAY_SCHEMA: &[&str] = &[
    "CREATE TABLE replay_binding (singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL, digest TEXT NOT NULL, head INTEGER NOT NULL CHECK(head>=0), last_hash TEXT) STRICT",
    "CREATE TABLE replay_steps (sequence INTEGER PRIMARY KEY CHECK(sequence>0), payload TEXT NOT NULL, digest TEXT NOT NULL, ready INTEGER NOT NULL CHECK(ready IN (0,1))) STRICT",
];
fn error(message: &str) -> Error {
    Error(format!("RUNTIME_STORE_{message}"))
}
fn sql<T>(r: rusqlite::Result<T>) -> Result<T, Error> {
    r.map_err(|e| error(&format!("SQL: {e}")))
}
fn io<T, E: std::fmt::Display>(r: Result<T, E>) -> Result<T, Error> {
    r.map_err(|e| error(&format!("IO: {e}")))
}
fn integer(n: u64) -> Result<i64, Error> {
    i64::try_from(n).map_err(|_| error("SEQUENCE_OVERFLOW"))
}
fn hash(v: &Value) -> String {
    digest(v.to_string().as_bytes())
}
fn identity(config: Value, artifact: &str) -> Result<Value, Error> {
    Components::new(config.clone())?;
    if artifact.len() != 64
        || !artifact
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(error("ARTIFACT"));
    }
    Ok(
        json!({"schema_version":1,"family":"RUST_EXECUTION_RUNTIME","configuration":config,"kernel_artifact":artifact}),
    )
}
fn decoded(raw: &str, expected: &str) -> Result<Value, Error> {
    let v: Value = serde_json::from_str(raw)?;
    let canonical = serde_json::to_string(&v)?;
    if canonical != raw || digest(canonical.as_bytes()) != expected {
        return Err(error("DIGEST_OR_NONCANONICAL"));
    }
    Ok(v)
}
struct DecodedRow {
    input: String,
    payload: String,
    digest: String,
    record: Record,
}

/// Sole native durable Store. Holds an OS inode lock until drop; never swaps database files.
pub struct SqliteStore {
    decoded_rows: RefCell<BTreeMap<u64, DecodedRow>>,
    pub(crate) connection: Connection,
    pub(crate) identity: Value,
    _lease: File,
}
impl SqliteStore {
    pub fn create(root: &Path, config: Value, artifact: &str) -> Result<Self, Error> {
        Self::connect(root, config, artifact, true, false)
    }
    pub fn open(root: &Path, config: Value, artifact: &str) -> Result<Self, Error> {
        Self::connect(root, config, artifact, false, false)
    }
    /// Explicit schema1 -> schema2 migration; never called by open.
    pub fn migrate(root: &Path, config: Value, artifact: &str) -> Result<Self, Error> {
        Self::connect(root, config, artifact, false, true)
    }
    fn connect(
        root: &Path,
        config: Value,
        artifact: &str,
        create: bool,
        migrate: bool,
    ) -> Result<Self, Error> {
        if !cfg!(target_os = "linux") {
            return Err(error("PLATFORM_UNSUPPORTED"));
        }
        let identity = identity(config, artifact)?;
        let root = io(root.canonicalize())?;
        if !root.is_dir() {
            return Err(error("STATE_ROOT"));
        }
        let path = root.join("runtime.sqlite3");
        if path.is_symlink() {
            return Err(error("DATABASE_SYMLINK"));
        }
        let lease = io(OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(create)
            .open(&path))?;
        #[cfg(target_os = "linux")]
        {
            use std::os::unix::fs::MetadataExt;
            if io(lease.metadata())?.nlink() != 1 {
                return Err(error("DATABASE_HARD_LINK"));
            }
        }
        io(lease.try_lock())?;
        let connection = sql(Connection::open_with_flags(
            &path,
            OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        ))?;
        sql(connection.busy_timeout(Duration::ZERO))?;
        let mut store = Self {
            decoded_rows: RefCell::new(BTreeMap::new()),
            connection,
            identity,
            _lease: lease,
        };
        if create {
            store.configure()?;
            let tx = sql(store
                .connection
                .transaction_with_behavior(TransactionBehavior::Immediate))?;
            for statement in SCHEMA.iter().chain(REPLAY_SCHEMA) {
                sql(tx.execute_batch(statement))?;
            }
            sql(tx.pragma_update(None, "application_id", APPLICATION))?;
            sql(tx.pragma_update(None, "user_version", 2))?;
            sql(tx.execute(
                "INSERT INTO meta VALUES(1,?1,?2)",
                params![store.identity.to_string(), hash(&store.identity)],
            ))?;
            sql(tx.execute("INSERT INTO state VALUES(1,0,NULL)", []))?;
            sql(tx.commit())?;
            io(File::open(&root).and_then(|f| f.sync_all()))?;
        }
        if migrate {
            store.validate_schema_version(1)?;
            store.validate_checkpoints()?;
            store.configure()?;
            let tx = sql(store
                .connection
                .transaction_with_behavior(TransactionBehavior::Immediate))?;
            for statement in REPLAY_SCHEMA {
                sql(tx.execute_batch(statement))?;
            }
            sql(tx.pragma_update(None, "user_version", 2))?;
            sql(tx.commit())?;
        }
        store.validate_schema()?;
        store.validate_checkpoints()?;
        if !create {
            store.configure()?;
        }
        Ok(store)
    }
    fn configure(&self) -> Result<(), Error> {
        let journal: String =
            sql(self
                .connection
                .query_row("PRAGMA journal_mode=DELETE", [], |r| r.get(0)))?;
        if journal != "delete" {
            return Err(error("JOURNAL_MODE"));
        }
        sql(self.connection.execute_batch(
            "PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON; PRAGMA trusted_schema=OFF;",
        ))?;
        Ok(())
    }
    fn validate_schema(&self) -> Result<(), Error> {
        self.validate_schema_version(2)
    }
    fn validate_schema_version(&self, expected_version: i64) -> Result<(), Error> {
        let app: i64 = sql(self
            .connection
            .pragma_query_value(None, "application_id", |r| r.get(0)))?;
        let version: i64 = sql(self
            .connection
            .pragma_query_value(None, "user_version", |r| r.get(0)))?;
        if app != APPLICATION || version != expected_version {
            return Err(error("SCHEMA"));
        }
        let check: String = sql(self
            .connection
            .query_row("PRAGMA quick_check", [], |r| r.get(0)))?;
        if check != "ok" {
            return Err(error("INTEGRITY"));
        }
        let mut query = sql(self
            .connection
            .prepare("SELECT sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY sql"))?;
        let actual = sql(sql(query.query_map([], |r| r.get::<_, String>(0)))?
            .collect::<rusqlite::Result<Vec<_>>>())?;
        let mut expected: Vec<_> = SCHEMA.iter().map(|s| s.to_string()).collect();
        if expected_version == 2 {
            expected.extend(REPLAY_SCHEMA.iter().map(|s| s.to_string()));
        }
        expected.sort();
        if actual != expected {
            return Err(error("SCHEMA_OBJECTS"));
        }
        self.validate_identity()
    }
    fn validate_identity(&self) -> Result<(), Error> {
        let mut query = sql(self
            .connection
            .prepare("SELECT singleton,payload,digest FROM meta"))?;
        let rows = sql(sql(query.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        }))?
        .collect::<rusqlite::Result<Vec<_>>>())?;
        if rows.len() != 1 || rows[0].0 != 1 || decoded(&rows[0].1, &rows[0].2)? != self.identity {
            return Err(error("IDENTITY"));
        }
        Ok(())
    }
    pub(crate) fn identity(&self) -> &Value {
        &self.identity
    }
    fn decode_record(
        &self,
        sequence: u64,
        input_id: &str,
        payload: &str,
        expected: &str,
    ) -> Result<Record, Error> {
        // Re-read every durable row. Reuse decoding only for the exact previously verified bytes and index.
        if let Some(cached) = self.decoded_rows.borrow().get(&sequence)
            && cached.input == input_id
            && cached.payload == payload
            && cached.digest == expected
        {
            return Ok(cached.record.clone());
        }
        let record = Record::decode(&decoded(payload, expected)?)?;
        let prepared = record.prepared();
        let p = prepared.record();
        let input = prepared.input();
        let config = &self.identity["configuration"];
        if sequence == 0
            || prepared.sequence() != sequence
            || p["predecessor"] != sequence - 1
            || input["input_id"] != input_id
            || p["config_hash"] != hash(config)
        {
            return Err(error("SEQUENCE_OR_IDENTITY_INDEX"));
        }
        for key in [
            "engine",
            "runtime",
            "account",
            "gateway",
            "generation",
            "runtime_kind",
        ] {
            if input[key] != config[key] {
                return Err(error("FACT_SCOPE"));
            }
        }
        let cluster = input["cluster"].as_str().ok_or_else(|| error("CLUSTER"))?;
        if config["profiles"].get(cluster).is_none()
            || input["revision"] != config["profiles"][cluster]["revision"]
        {
            return Err(error("CLUSTER_REVISION"));
        }
        self.decoded_rows.borrow_mut().insert(
            sequence,
            DecodedRow {
                input: input_id.into(),
                payload: payload.into(),
                digest: expected.into(),
                record: record.clone(),
            },
        );
        Ok(record)
    }
    fn read_one(&self, sequence: u64) -> Result<Option<Record>, Error> {
        let row: Option<(String, String, String)> = sql(self
            .connection
            .query_row(
                "SELECT input_id,payload,digest FROM records WHERE sequence=?1",
                [integer(sequence)?],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .optional())?;
        row.map(|(id, raw, h)| self.decode_record(sequence, &id, &raw, &h))
            .transpose()
    }
    fn verified_head(&self) -> Result<u64, Error> {
        self.validate_identity()?;
        let mut statement = sql(self
            .connection
            .prepare("SELECT singleton,head,last_hash FROM state"))?;
        let rows = sql(sql(statement.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, i64>(1)?,
                r.get::<_, Option<String>>(2)?,
            ))
        }))?
        .collect::<rusqlite::Result<Vec<_>>>())?;
        if rows.len() != 1 || rows[0].0 != 1 {
            return Err(error("HEAD_COMPLETENESS"));
        }
        let head = u64::try_from(rows[0].1).map_err(|_| error("HEAD_COMPLETENESS"))?;
        let (count, max): (i64, Option<i64>) = sql(self.connection.query_row(
            "SELECT count(*),max(sequence) FROM records",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        ))?;
        if count != integer(head)?
            || max
                != if head == 0 {
                    None
                } else {
                    Some(integer(head)?)
                }
        {
            return Err(error("HEAD_COMPLETENESS"));
        }
        let last = if head == 0 {
            None
        } else {
            Some(hash(
                &self
                    .read_one(head)?
                    .ok_or_else(|| error("HEAD_COMPLETENESS"))?
                    .prepared()
                    .record(),
            ))
        };
        if last != rows[0].2 {
            return Err(error("HEAD_COMPLETENESS"));
        }
        Ok(head)
    }
    fn genesis_hashes(&self) -> Result<Vec<String>, Error> {
        Ok(
            Components::new(self.identity["configuration"].clone())?.checkpoint()?["components"]
                .as_array()
                .ok_or_else(|| error("GENESIS"))?
                .iter()
                .map(hash)
                .collect(),
        )
    }
    fn read_records(&self) -> Result<Vec<Record>, Error> {
        self.validate_identity()?;
        let mut statement = sql(self
            .connection
            .prepare("SELECT sequence,input_id,payload,digest FROM records ORDER BY sequence"))?;
        let rows = sql(sql(statement.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
            ))
        }))?
        .collect::<rusqlite::Result<Vec<_>>>())?;
        let mut records = Vec::with_capacity(rows.len());
        let mut before = self.genesis_hashes()?;
        let mut input_ids = std::collections::BTreeSet::new();
        for (i, (sequence, input_id, payload, expected)) in rows.into_iter().enumerate() {
            let sequence = u64::try_from(sequence).map_err(|_| error("SEQUENCE"))?;
            if sequence != i as u64 + 1 || !input_ids.insert(input_id.clone()) {
                return Err(error("SEQUENCE_OR_IDENTITY_INDEX"));
            }
            let record = self.decode_record(sequence, &input_id, &payload, &expected)?;
            let p = record.prepared().record();
            for (j, previous) in before.iter_mut().enumerate() {
                if p["projections"][j]["before_hash"] != *previous {
                    return Err(error("LINEAGE"));
                }
                *previous = p["projections"][j]["result_hash"]
                    .as_str()
                    .ok_or_else(|| error("PROJECTION_HASH"))?
                    .into();
            }
            if records.last().is_some_and(|r: &Record| !r.ready()) {
                return Err(error("UNREADY_PREDECESSOR"));
            }
            records.push(record);
        }
        let mut statement = sql(self
            .connection
            .prepare("SELECT singleton,head,last_hash FROM state"))?;
        let states = sql(sql(statement.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, i64>(1)?,
                r.get::<_, Option<String>>(2)?,
            ))
        }))?
        .collect::<rusqlite::Result<Vec<_>>>())?;
        let last = records.last().map(|r| hash(&r.prepared().record()));
        if states.len() != 1
            || states[0]
                != (
                    1,
                    i64::try_from(records.len()).map_err(|_| error("SEQUENCE_OVERFLOW"))?,
                    last,
                )
        {
            return Err(error("HEAD_COMPLETENESS"));
        }
        Ok(records)
    }
    fn checkpoint_value(&self, c: &Components, records: &[Record]) -> Result<Value, Error> {
        Ok(
            json!({"schema_version":1,"identity":hash(&self.identity),"sequence":records.len(),"source":records.last().map(|r|hash(&r.prepared().record())),"components":c.checkpoint()?}),
        )
    }
    fn validate_checkpoints(&self) -> Result<(), Error> {
        let records = self.read_records()?;
        let mut statement = sql(self
            .connection
            .prepare("SELECT sequence,payload,digest FROM checkpoints ORDER BY sequence"))?;
        let rows = sql(sql(statement.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        }))?
        .collect::<rusqlite::Result<Vec<_>>>())?;
        for (n, raw, expected) in rows {
            let value = decoded(&raw, &expected)?;
            let prefix = records
                .get(..usize::try_from(n).map_err(|_| error("CHECKPOINT_SEQUENCE"))?)
                .ok_or_else(|| error("CHECKPOINT_AHEAD"))?;
            if prefix.iter().any(|r| !r.ready()) {
                return Err(error("CHECKPOINT_UNREADY"));
            }
            let c = replay(self.identity["configuration"].clone(), prefix)?;
            if value != self.checkpoint_value(&c, prefix)? {
                return Err(error("CHECKPOINT_SOURCE_OR_COMPONENTS"));
            }
        }
        Ok(())
    }
    pub fn save_checkpoint(&mut self, c: &Components) -> Result<Value, Error> {
        self.validate_checkpoints()?;
        let records = self.read_records()?;
        if records.iter().any(|r| !r.ready()) {
            return Err(error("CHECKPOINT_UNREADY"));
        }
        let exact = replay(self.identity["configuration"].clone(), &records)?;
        if exact.checkpoint()? != c.checkpoint()? {
            return Err(error("CHECKPOINT_OWNER_CONFLICT"));
        }
        let value = self.checkpoint_value(c, &records)?;
        let tx = sql(self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate))?;
        let n = i64::try_from(records.len()).map_err(|_| error("SEQUENCE_OVERFLOW"))?;
        let existing: Option<(String, String)> = sql(tx
            .query_row(
                "SELECT payload,digest FROM checkpoints WHERE sequence=?1",
                [n],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional())?;
        if let Some((raw, h)) = existing {
            if decoded(&raw, &h)? != value {
                return Err(error("CHECKPOINT_CONFLICT"));
            }
        } else {
            sql(tx.execute(
                "INSERT INTO checkpoints VALUES(?1,?2,?3)",
                params![n, value.to_string(), hash(&value)],
            ))?;
        }
        sql(tx.commit())?;
        let (raw, h): (String, String) = sql(self.connection.query_row(
            "SELECT payload,digest FROM checkpoints WHERE sequence=?1",
            [n],
            |r| Ok((r.get(0)?, r.get(1)?)),
        ))?;
        if decoded(&raw, &h)? != value {
            return Err(error("CHECKPOINT_READBACK"));
        }
        Ok(value)
    }
    pub(crate) fn recover_components(&mut self) -> Result<Components, Error> {
        self.validate_schema()?;
        self.validate_checkpoints()?;
        let records = self.read_records()?;
        // First prove every owner transition on an isolated replay. Only then may the real tail become Ready.
        replay(self.identity["configuration"].clone(), &records)?;
        let mut c = Components::new(self.identity["configuration"].clone())?;
        let latest: Option<(String, String)> = sql(self
            .connection
            .query_row(
                "SELECT payload,digest FROM checkpoints ORDER BY sequence DESC LIMIT 1",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional())?;
        if let Some((raw, expected)) = latest {
            let checkpoint = decoded(&raw, &expected)?;
            c.restore(&checkpoint["components"], &hash(&checkpoint["components"]))?;
        }
        recover(self, &mut c)?;
        Ok(c)
    }
    fn change_flag(&mut self, sequence: u64, flag: &str) -> Result<(), Error> {
        let records = self.read_records()?;
        let i = usize::try_from(sequence.checked_sub(1).ok_or_else(|| error("SEQUENCE"))?)
            .map_err(|_| error("SEQUENCE"))?;
        let old = records.get(i).ok_or_else(|| error("MISSING_RECORD"))?;
        if records[..i].iter().any(|r| !r.ready()) || (flag == "delivered" && !old.ready()) {
            return Err(error("NOT_READY"));
        }
        let mut v = old.record();
        v[flag] = json!(true);
        Record::decode(&v)?;
        let tx = sql(self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate))?;
        sql(tx.execute(
            "UPDATE records SET payload=?1,digest=?2 WHERE sequence=?3",
            params![v.to_string(), hash(&v), integer(sequence)?],
        ))?;
        sql(tx.commit())
    }
}
impl Store for SqliteStore {
    fn head(&self) -> Result<u64, Error> {
        self.verified_head()
    }
    fn get(&self, sequence: u64) -> Result<Option<Record>, Error> {
        if sequence == 0 {
            return Err(error("SEQUENCE"));
        }
        let head = self.verified_head()?;
        if sequence > head {
            return Ok(None);
        }
        self.read_one(sequence)?
            .map(Some)
            .ok_or_else(|| error("MISSING_RECORD"))
    }
    fn commit(&mut self, intent: &CommitIntent) -> Result<Record, Error> {
        let records = self.read_records()?;
        let p = intent.prepared();
        if let Some(old) = records
            .iter()
            .find(|r| r.prepared().input()["input_id"] == p.input()["input_id"])
        {
            if old.prepared() != p {
                return Err(error("IDENTITY_CONFLICT"));
            }
            return Ok(old.clone());
        }
        if p.sequence() != records.len() as u64 + 1
            || records.last().is_some_and(|r| !r.ready())
            || p.record()["config_hash"] != hash(&self.identity["configuration"])
        {
            return Err(error("COMMIT_CONTEXT_OR_PREDECESSOR"));
        }
        let before = if let Some(last) = records.last() {
            last.prepared().record()["projections"]
                .as_array()
                .ok_or_else(|| error("PREDECESSOR_PROJECTIONS"))?
                .iter()
                .map(|v| {
                    v["result_hash"]
                        .as_str()
                        .map(str::to_owned)
                        .ok_or_else(|| error("PREDECESSOR_HASH"))
                })
                .collect::<Result<Vec<_>, Error>>()?
        } else {
            self.genesis_hashes()?
        };
        let incoming = p.record();
        if before
            .iter()
            .enumerate()
            .any(|(i, previous)| incoming["projections"][i]["before_hash"] != *previous)
        {
            return Err(error("COMMIT_DESTINATION_LINEAGE"));
        }
        let record = Record::new(intent);
        let v = record.record();
        let tx = sql(self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate))?;
        sql(tx.execute(
            "INSERT INTO records VALUES(?1,?2,?3,?4)",
            params![
                integer(p.sequence())?,
                p.input()["input_id"].as_str(),
                v.to_string(),
                hash(&v)
            ],
        ))?;
        sql(tx.execute(
            "UPDATE state SET head=?1,last_hash=?2 WHERE singleton=1",
            params![integer(p.sequence())?, hash(&p.record())],
        ))?;
        sql(tx.commit())?;
        Ok(record)
    }
    fn mark_ready(&mut self, sequence: u64) -> Result<(), Error> {
        self.change_flag(sequence, "ready")
    }
    fn acknowledge(&mut self, sequence: u64) -> Result<(), Error> {
        self.change_flag(sequence, "delivered")
    }
}
// Isolated proof replay only. It cannot commit new authority or publish external Events.
struct Replay {
    rows: Vec<Record>,
}
impl Store for Replay {
    fn head(&self) -> Result<u64, Error> {
        Ok(self.rows.len() as u64)
    }
    fn get(&self, n: u64) -> Result<Option<Record>, Error> {
        Ok(self
            .rows
            .get(n.checked_sub(1).ok_or_else(|| error("SEQUENCE"))? as usize)
            .cloned())
    }
    fn commit(&mut self, _: &CommitIntent) -> Result<Record, Error> {
        Err(error("READ_ONLY_REPLAY"))
    }
    fn mark_ready(&mut self, n: u64) -> Result<(), Error> {
        let mut v = self.rows[n as usize - 1].record();
        v["ready"] = json!(true);
        self.rows[n as usize - 1] = Record::decode(&v)?;
        Ok(())
    }
    fn acknowledge(&mut self, _: u64) -> Result<(), Error> {
        Err(error("READ_ONLY_REPLAY"))
    }
}
fn replay(config: Value, records: &[Record]) -> Result<Components, Error> {
    let mut c = Components::new(config)?;
    let mut view = Replay {
        rows: records.to_vec(),
    };
    recover(&mut view, &mut c)?;
    c.reconcile(&view)?;
    Ok(c)
}
