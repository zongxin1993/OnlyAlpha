use onlyalpha_execution::{CommitIntent, Components, Error, Prepared, Record, Store, digest, recover};
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
const ENCODED_RECORD_TABLE:&str="CREATE TABLE records (sequence INTEGER PRIMARY KEY CHECK(sequence>0), input_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, digest TEXT NOT NULL, ready INTEGER NOT NULL CHECK(ready IN (0,1)), delivered INTEGER NOT NULL CHECK(delivered IN (0,1) AND delivered<=ready)) STRICT";
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
// Borrow SQLite's exact Text only for the current Row lifetime. Invalid
// type/UTF-8 stays an error; no reference leaves a decode operation.
pub(crate) fn text_column<'row>(row:&'row rusqlite::Row<'_>,index:usize)->Result<&'row str,Error>{
    sql(row.get_ref(index))?.as_str().map_err(|cause|error(&format!("SQL: {cause}")))
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
#[cfg(test)]
std::thread_local! {
    static PREPARED_SOURCE_ENCODINGS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    static COMMIT_LEGACY_RECORD_CONSTRUCTIONS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    // Actual SQLite work only; no clocks, grants or production state.
    static SOURCE_HEAD_AGGREGATES: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    pub(crate) static SOURCE_RAW_ROWS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    static SOURCE_OWNED_PAYLOAD_BYTES: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    static SOURCE_PROJECTION_COPIES: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}
fn prepared_hash(prepared: &Prepared) -> Result<String, Error> {
    #[cfg(test)]
    PREPARED_SOURCE_ENCODINGS.with(|count| count.set(count.get() + 1));
    Ok(digest(&prepared.encode()?))
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
// The complete logical Record retains its original 8 MiB budget. Both flags
// are actual independently observed columns; false is one byte longer than true.
fn record_bound(prepared_size: usize, ready: bool, delivered: bool) -> Result<(), Error> {
    const ENVELOPE: usize = br#"{"schema_version":1,"prepared":null,"ready":false,"delivered":false}"#.len() - 4;
    let envelope = ENVELOPE - usize::from(ready) - usize::from(delivered);
    if prepared_size.checked_add(envelope).is_none_or(|size| size > crate::codec::LIMIT) {
        return Err(error("RECORD_BOUND"));
    }
    Ok(())
}
// Pure codec bytes tied to one actually observed complete anchor row. The
// same Arc is shared by the block; it is never a Ready or source-proof cache.
struct DictionaryAnchorSource {
    raw: String,
    anchor: crate::dictionary_codec::Anchor,
}
struct DecodedRow {
    version: u32,
    // Exact canonical Prepared length from the verified encoded frame, not a source proof.
    prepared_size: Option<usize>,
    dictionary: Option<std::sync::Arc<DictionaryAnchorSource>>,
    input: String,
    payload: String,
    digest: String,
    prepared_digest: String,
    projection_hashes: Vec<(String,String)>,
    flags:Option<(i64,i64)>,
    record: Record,
}

/// Sole native durable Store. Holds an OS inode lock until drop; never swaps database files.
pub struct SqliteStore {
    pub(crate) storage_version:u32,
    decoded_rows: RefCell<BTreeMap<u64, DecodedRow>>,
    pub(crate) decoded_replay_rows: RefCell<BTreeMap<i64, crate::replay::DecodedReplayRow>>,
    pub(crate) replay_anchors: RefCell<BTreeMap<u64,(String,std::sync::Arc<crate::dictionary_codec::Anchor>)>>,
    pub(crate) replay_reference_metadata: RefCell<BTreeMap<i64, crate::references::CachedReplayReference>>,
    pub(crate) connection: Connection,
    pub(crate) identity: Value,
    _lease: File,
}
#[path="checkpoint_data.rs"]
mod checkpoint_data;
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
        let storage_version=if create {4}else{sql(connection.pragma_query_value(None,"user_version",|row|row.get(0)))?};
        let mut store = Self {
            storage_version,
            decoded_rows: RefCell::new(BTreeMap::new()),
            decoded_replay_rows: RefCell::new(BTreeMap::new()),
            replay_anchors: RefCell::new(BTreeMap::new()),
            replay_reference_metadata: RefCell::new(BTreeMap::new()),
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
                sql(tx.execute_batch(if statement.starts_with("CREATE TABLE records "){ENCODED_RECORD_TABLE}else{statement}))?;
            }
            sql(tx.pragma_update(None, "application_id", APPLICATION))?;
            sql(tx.pragma_update(None, "user_version", 4))?;
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
            store.storage_version=2;
        }
        store.validate_schema()?;
        store.validate_checkpoints()?;
        if !create {
            store.configure()?;
        }
        Ok(store)
    }
    // A separate constructor is essential: ordinary open configures SQLite and
    // forward-recovers readiness. This read path performs neither operation.
    pub(crate) fn read_only(root:&Path,config:Value,artifact:&str)->Result<Self,Error> {
        let identity=identity(config,artifact)?;
        let path=crate::readonly::source_path(root)?;
        let lease=io(OpenOptions::new().read(true).open(&path))?;
        io(lease.try_lock_shared())?;
        crate::readonly::verify_file(&path,&lease)?;
        let connection=sql(Connection::open_with_flags(&path,OpenFlags::SQLITE_OPEN_READ_ONLY|OpenFlags::SQLITE_OPEN_NO_MUTEX|OpenFlags::SQLITE_OPEN_PRIVATE_CACHE|OpenFlags::SQLITE_OPEN_NOFOLLOW))?;
        sql(connection.busy_timeout(Duration::ZERO))?;
        sql(connection.execute_batch("PRAGMA query_only=ON; PRAGMA trusted_schema=OFF; PRAGMA temp_store=MEMORY;"))?;
        let journal:String=sql(connection.pragma_query_value(None,"journal_mode",|row|row.get(0)))?;
        if journal!="delete"{return Err(error("READ_ONLY_JOURNAL"));}
        let storage_version=sql(connection.pragma_query_value(None,"user_version",|row|row.get(0)))?;
        let store=Self{storage_version,decoded_rows:RefCell::new(BTreeMap::new()),decoded_replay_rows:RefCell::new(BTreeMap::new()),replay_reference_metadata:RefCell::new(BTreeMap::new()),replay_anchors:RefCell::new(BTreeMap::new()),connection,identity,_lease:lease};
        store.validate_schema()?;
        crate::readonly::verify_file(&path,&store._lease)?;
        Ok(store)
    }
    pub(crate) fn read_lease(&self)->Result<File,Error>{io(self._lease.try_clone())}
    /// Reconstruct only already-Ready owners from actual retained checkpoints.
    /// No Store recovery, planner, projection completion or acknowledgement runs.
    pub(crate) fn read_ready_components(&self)->Result<(Components,Vec<Record>,Value),Error>{
        let records=self.read_records()?;
        if records.iter().any(|record|!record.ready()||!record.delivered()){return Err(error("READ_ONLY_DRAIN_REQUIRED"));}
        let mut statement=sql(self.connection.prepare("SELECT sequence,payload,digest FROM checkpoints ORDER BY sequence"))?;
        let rows=sql(sql(statement.query_map([],|row|Ok((row.get::<_,i64>(0)?,row.get::<_,String>(1)?,row.get::<_,String>(2)?))))?.collect::<rusqlite::Result<Vec<_>>>())?;
        let mut current=None;let mut witnesses=Vec::new();
        for (sequence,raw,expected) in rows {
            let checkpoint=decoded(&raw,&expected)?;
            let end=usize::try_from(sequence).map_err(|_|error("CHECKPOINT_SEQUENCE"))?;
            let prefix=records.get(..end).ok_or_else(||error("CHECKPOINT_AHEAD"))?;
            let mut components=Components::new(self.identity["configuration"].clone())?;
            components.restore(&checkpoint["components"],&hash(&checkpoint["components"]))?;
            // The existing owning source/reconciliation readers bind all six
            // typed owners to this actual Ready prefix, including Fee history.
            let view=Replay{rows:prefix.to_vec()};components.reconcile(&view)?;
            if self.checkpoint_value(&components,prefix)?!=checkpoint{return Err(error("CHECKPOINT_SOURCE_OR_COMPONENTS"));}
            witnesses.push(json!({"sequence":sequence,"digest":expected}));
            if end==records.len(){current=Some(components);}
        }
        let components=current.ok_or_else(||error("READ_ONLY_HEAD_CHECKPOINT_REQUIRED"))?;
        Ok((components,records,Value::Array(witnesses)))
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
        if !matches!(self.storage_version,2|3|4){return Err(error("SCHEMA"));}
        self.validate_schema_version(i64::from(self.storage_version))
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
        let mut expected: Vec<_> = SCHEMA.iter().map(|s|if matches!(expected_version,3|4)&&s.starts_with("CREATE TABLE records "){ENCODED_RECORD_TABLE.to_owned()}else{s.to_string()}).collect();
        if matches!(expected_version,2|3|4) {
            expected.extend(REPLAY_SCHEMA.iter().map(|s| s.to_string()));
        }
        expected.sort();
        if actual != expected {
            return Err(error("SCHEMA_OBJECTS"));
        }
        self.validate_identity()
    }
    fn validate_identity(&self) -> Result<(), Error> {
        let app:i64=sql(self.connection.pragma_query_value(None,"application_id",|row|row.get(0)))?;
        let version:u32=sql(self.connection.pragma_query_value(None,"user_version",|row|row.get(0)))?;
        if app!=APPLICATION||version!=self.storage_version{return Err(error("SCHEMA"));}
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
    pub(crate) fn validate_identity_for_reference(&self)->Result<(),Error>{self.validate_identity()}
    pub(crate) fn identity(&self) -> &Value {
        &self.identity
    }
    fn decode_record(
        &self,
        sequence: u64,
        input_id: &str,
        payload: &str,
        expected: &str,
        flags:Option<(i64,i64)>,
        dictionary:Option<&std::sync::Arc<DictionaryAnchorSource>>,
    ) -> Result<(Record, String), Error> {
        // Re-read every durable row. Reuse decoding only for the exact previously verified bytes and index.
        if let Some((ready,delivered))=flags {if !matches!(ready,0|1)||!matches!(delivered,0|1)||delivered>ready{return Err(error("FLAGS"));}}
        if let Some(cached) = self.decoded_rows.borrow().get(&sequence)
            && cached.version == self.storage_version
            && (self.storage_version != 4 || match (&cached.dictionary, dictionary) {
                (Some(old), Some(actual)) => old.raw == actual.raw && old.anchor.physical() == actual.anchor.physical()
                    && old.anchor.sequence() == actual.anchor.sequence() && old.anchor.logical() == actual.anchor.logical(),
                (Some(old), None) => old.anchor.sequence() == sequence && old.raw == payload && old.anchor.physical() == expected,
                _ => false,
            })
            && cached.input == input_id
            && cached.payload == payload
            && cached.digest == expected
            && (matches!(self.storage_version,3|4) || cached.flags == flags)
        {
            // Encoded-record flags are freshly observed columns, not immutable body
            // bytes. Share only the exact verified Prepared, never old flags.
            let record = if matches!(self.storage_version,3|4) {
                let (ready, delivered) = flags.ok_or_else(|| error("FLAGS"))?;
                record_bound(cached.prepared_size.ok_or_else(|| error("CODEC_SCOPE"))?, ready == 1, delivered == 1)?;
                cached.record.with_observed_flags(ready == 1, delivered == 1)?
            } else {
                cached.record.clone()
            };
            return Ok((record, cached.prepared_digest.clone()));
        }
        // Actual row equality may reuse only the immutable codec result.
        // A changed row still takes the original complete physical verifier.
        if self.storage_version==3&&{
            #[cfg(test)] crate::codec::PHYSICAL_HASHES.with(|count|count.set(count.get()+1));
            digest(payload.as_bytes())!=expected
        }{return Err(error("DIGEST"));}
        let mut actual_dictionary = None;
        let mut prepared_size = None;
        let mut verified_logical = None;
        let record=if self.storage_version==4 {
            let (ready,delivered)=flags.ok_or_else(||error("FLAGS"))?;
            let frame=crate::dictionary_codec::inspect(payload,expected,sequence)?;
            record_bound(frame.size, ready == 1, delivered == 1)?;
            prepared_size = Some(frame.size);
            if frame.summary!=json!({"kind":"EXECUTION_PREPARED","sequence":sequence,"input_id":input_id}){return Err(error("CODEC_SCOPE"));}
            let prepared=if crate::dictionary_codec::anchor_sequence(sequence)?==sequence {
                if dictionary.is_some(){return Err(error("DICTIONARY_BASE"));}
                let (value,anchor)=crate::dictionary_codec::decode_anchor(&frame)?;
                actual_dictionary=Some(std::sync::Arc::new(DictionaryAnchorSource{raw:payload.into(),anchor}));
                value
            }else{
                let anchor=dictionary.ok_or_else(||error("DICTIONARY_BASE"))?;
                let value=crate::dictionary_codec::decode(&frame,Some(&anchor.anchor))?;
                actual_dictionary=Some(std::sync::Arc::clone(anchor));value
            };
            let record=Record::decode(&json!({"schema_version":1,"prepared":prepared,"ready":ready==1,"delivered":delivered==1}))?;
            // The codec proved the complete canonical bytes; Record validation
            // retains that exact body. Scope checks below still precede use.
            verified_logical=Some(frame.logical);record
        }else if self.storage_version==3 {
            let (ready,delivered)=flags.ok_or_else(||error("FLAGS"))?;
            let frame=crate::codec::inspect(payload,expected)?;
            record_bound(frame.size, ready == 1, delivered == 1)?;
            prepared_size = Some(frame.size);
            let prepared=crate::codec::decode(&frame)?;
            if frame.summary!=json!({"kind":"EXECUTION_PREPARED","sequence":sequence,"input_id":input_id}){return Err(error("CODEC_SCOPE"));}
            let record=Record::decode(&json!({"schema_version":1,"prepared":prepared,"ready":ready==1,"delivered":delivered==1}))?;
            // The codec proved the complete canonical bytes; Record validation
            // retains that exact body. Scope checks below still precede use.
            verified_logical=Some(frame.logical);record
        }else{Record::decode(&decoded(payload,expected)?)?};
        let prepared = record.prepared();
        let p = prepared.value();
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
        let prepared_digest = match verified_logical {Some(logical)=>logical,None=>prepared_hash(prepared)?};
        let projection_hashes = p["projections"].as_array().ok_or_else(||error("PROJECTION_HASH"))?
            .iter().map(|projection|Ok((
                projection["before_hash"].as_str().ok_or_else(||error("PROJECTION_HASH"))?.to_owned(),
                projection["result_hash"].as_str().ok_or_else(||error("PROJECTION_HASH"))?.to_owned(),
            ))).collect::<Result<Vec<_>,Error>>()?;
        let cached_payload=payload.to_owned();
        #[cfg(test)] SOURCE_OWNED_PAYLOAD_BYTES.with(|count|count.set(count.get()+cached_payload.len() as u64));
        self.decoded_rows.borrow_mut().insert(
            sequence,
            DecodedRow {
                version: self.storage_version,
                prepared_size,
                dictionary: actual_dictionary,
                input: input_id.into(),
                payload: cached_payload,
                digest: expected.into(),
                prepared_digest: prepared_digest.clone(),
                projection_hashes,
                flags,
                record: record.clone(),
            },
        );
        Ok((record, prepared_digest))
    }
    fn read_one(&self, sequence: u64) -> Result<Option<(Record, String)>, Error> {
        let mut statement=sql(self.connection.prepare(
            if matches!(self.storage_version,3|4) {"SELECT input_id,payload,digest,ready,delivered FROM records WHERE sequence=?1"}else{"SELECT input_id,payload,digest,NULL,NULL FROM records WHERE sequence=?1"}
        ))?;
        let mut rows=sql(statement.query([integer(sequence)?]))?;
        let Some(row)=sql(rows.next())? else{return Ok(None);};
        let input_id=text_column(row,0)?;let payload=text_column(row,1)?;let expected=text_column(row,2)?;
        let ready:Option<i64>=sql(row.get(3))?;let delivered:Option<i64>=sql(row.get(4))?;
        #[cfg(test)] SOURCE_RAW_ROWS.with(|count|count.set(count.get()+1));
        // Keep the target SELECT active while observing its actual anchor, so
        // both reads share this connection's native SQLite read snapshot.
        let dictionary=self.dictionary_anchor_for(sequence)?;
        self.decode_record(sequence,input_id,payload,expected,ready.zip(delivered),dictionary.as_ref()).map(Some)
    }
    fn dictionary_anchor_for(&self,sequence:u64)->Result<Option<std::sync::Arc<DictionaryAnchorSource>>,Error>{
        if self.storage_version!=4{return Ok(None);}
        let base=crate::dictionary_codec::anchor_sequence(sequence)?;
        if base==sequence{return Ok(None);}
        self.read_one(base)?.ok_or_else(||error("DICTIONARY_BASE_MISSING"))?;
        self.decoded_rows.borrow().get(&base).and_then(|row|row.dictionary.as_ref()).cloned()
            .filter(|source|source.anchor.sequence()==base).map(Some).ok_or_else(||error("DICTIONARY_BASE"))
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
        #[cfg(test)]
        SOURCE_HEAD_AGGREGATES.with(|count|count.set(count.get()+1));
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
            Some(self.read_one(head)?
                .ok_or_else(|| error("HEAD_COMPLETENESS"))?.1)
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
    pub(crate) fn read_records(&self) -> Result<Vec<Record>, Error> {
        self.validate_identity()?;
        let mut statement = sql(self
            .connection
            .prepare(if matches!(self.storage_version,3|4) {"SELECT sequence,input_id,payload,digest,ready,delivered FROM records ORDER BY sequence"}else{"SELECT sequence,input_id,payload,digest,NULL,NULL FROM records ORDER BY sequence"}))?;
        let mut rows=sql(statement.query([]))?;
        let mut records=Vec::new();
        let mut last = None;
        let mut before = self.genesis_hashes()?;
        let mut input_ids = std::collections::BTreeSet::new();
        let mut dictionary: Option<std::sync::Arc<DictionaryAnchorSource>> = None;
        while let Some(row)=sql(rows.next())? {
            let sequence=u64::try_from(sql(row.get::<_,i64>(0))?).map_err(|_|error("SEQUENCE"))?;
            let input_id=text_column(row,1)?;let payload=text_column(row,2)?;let expected=text_column(row,3)?;
            let ready:Option<i64>=sql(row.get(4))?;let delivered:Option<i64>=sql(row.get(5))?;
            if sequence != records.len() as u64 + 1 || !input_ids.insert(input_id.to_owned()) {
                return Err(error("SEQUENCE_OR_IDENTITY_INDEX"));
            }
            #[cfg(test)]
            SOURCE_RAW_ROWS.with(|count|count.set(count.get()+1));
            if self.storage_version==4 && crate::dictionary_codec::anchor_sequence(sequence)?==sequence { dictionary=None; }
            let (record, prepared_digest) = self.decode_record(sequence,input_id,payload,expected,ready.zip(delivered),dictionary.as_ref())?;
            if self.storage_version==4 && crate::dictionary_codec::anchor_sequence(sequence)?==sequence {
                dictionary=self.decoded_rows.borrow().get(&sequence).and_then(|row|row.dictionary.as_ref()).cloned();
                if dictionary.is_none(){return Err(error("DICTIONARY_BASE"));}
            }
            // Only exact freshly read row bytes/index/digest can select this
            // immutable decoded value and its derived projection hashes.
            let decoded=self.decoded_rows.borrow();
            let projections=&decoded.get(&sequence).ok_or_else(||error("PROJECTION_HASH"))?.projection_hashes;
            if projections.len()!=before.len(){return Err(error("PROJECTION_HASH"));}
            for (previous,(expected,next)) in before.iter_mut().zip(projections) {
                if previous!=expected{return Err(error("LINEAGE"));}
                previous.clone_from(next);
            }
            drop(decoded);
            if records.last().is_some_and(|r: &Record| !r.ready()) {
                return Err(error("UNREADY_PREDECESSOR"));
            }
            records.push(record);
            last = Some(prepared_digest);
        }
        drop(rows);drop(statement);
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
        let source = records.last().map(|r| prepared_hash(r.prepared())).transpose()?;
        Ok(
            json!({"schema_version":1,"identity":hash(&self.identity),"sequence":records.len(),"source":source,"components":c.checkpoint()?}),
        )
    }
    fn validate_checkpoints(&self) -> Result<(), Error> {
        let records = self.read_records()?;
        self.verified_checkpoint_prefix(&records).map(|_| ())
    }
    // Every call starts from the actual SQL rows and configured genesis. The
    // isolated view grows only forward; no checkpoint is adopted as its seed.
    fn verified_checkpoint_prefix(
        &self,
        records: &[Record],
    ) -> Result<(Components, Replay), Error> {
        if let Some(validated)=self.data_checkpoint_prefix(records)? { return Ok(validated); }
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
        let mut exact = Components::new(self.identity["configuration"].clone())?;
        let mut view = Replay { rows: Vec::new() };
        if rows.is_empty() {
            recover(&mut view, &mut exact)?;
            exact.reconcile(&view)?;
        }
        for (n, raw, expected) in rows {
            let value = decoded(&raw, &expected)?;
            let prefix = records
                .get(..usize::try_from(n).map_err(|_| error("CHECKPOINT_SEQUENCE"))?)
                .ok_or_else(|| error("CHECKPOINT_AHEAD"))?;
            let suffix = prefix
                .get(view.rows.len()..)
                .ok_or_else(|| error("CHECKPOINT_SEQUENCE"))?;
            if suffix.iter().any(|r| !r.ready()) {
                return Err(error("CHECKPOINT_UNREADY"));
            }
            view.rows.extend_from_slice(suffix);
            recover(&mut view, &mut exact)?;
            exact.reconcile(&view)?;
            if value != self.checkpoint_value(&exact, prefix)? {
                return Err(error("CHECKPOINT_SOURCE_OR_COMPONENTS"));
            }
        }
        Ok((exact, view))
    }
    /// A local observation of the actual complete SQL source. Only internal
    /// pure readers run here; no view survives a write, observer or public call.
    pub(crate) fn with_ready_source<T>(&self,current:&Components,read:impl FnOnce(&Replay)->Result<T,Error>)->Result<T,Error> {
        let view=Replay{rows:self.read_records()?};
        current.reconcile(&view)?;
        read(&view)
    }
    pub(crate) fn fork_ready(&self, current: &Components) -> Result<(Components, Vec<Record>), Error> {
        let records = self.read_records()?;
        if records.iter().any(|record| !record.ready()) { return Err(error("CHECKPOINT_UNREADY")); }
        let view = Replay { rows: records.clone() };
        let isolated = current.fork_ready(&view)?;
        isolated.reconcile(&view)?;
        Ok((isolated, records))
    }
    pub fn save_checkpoint(&mut self, c: &Components) -> Result<Value, Error> {
        let records = self.read_records()?;
        let (mut exact, mut view) = self.verified_checkpoint_prefix(&records)?;
        if records.iter().any(|r| !r.ready()) {
            return Err(error("CHECKPOINT_UNREADY"));
        }
        if view.rows.len() < records.len() {
            view.rows.extend_from_slice(&records[view.rows.len()..]);
            recover(&mut view, &mut exact)?;
            exact.reconcile(&view)?;
        }
        drop(view);
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
        if matches!(self.storage_version,3|4) {
            let statement=match flag {"ready"=>"UPDATE records SET ready=1 WHERE sequence=?1","delivered"=>"UPDATE records SET delivered=1 WHERE sequence=?1",_=>return Err(error("FLAGS"))};
            let tx=sql(self.connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
            if sql(tx.execute(statement,[integer(sequence)?]))?!=1{return Err(error("MISSING_RECORD"));}
            return sql(tx.commit());
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
            .map(|(record, _)| Some(record))
            .ok_or_else(|| error("MISSING_RECORD"))
    }
    fn read_prefix(&self, sequence: u64) -> Result<Option<Vec<Record>>, Error> {
        // This operation always observes the complete actual source first,
        // including header/head and any legal pending tail, even for zero.
        let mut records=self.read_records()?;
        let end=usize::try_from(sequence).map_err(|_|error("SEQUENCE_OVERFLOW"))?;
        if end>records.len(){return Err(error("MISSING_RECORD"));}
        records.truncate(end);
        Ok(Some(records))
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
            || p.value()["config_hash"] != hash(&self.identity["configuration"])
        {
            return Err(error("COMMIT_CONTEXT_OR_PREDECESSOR"));
        }
        let before = if let Some(last) = records.last() {
            last.prepared().value()["projections"]
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
        let incoming = p.value();
        if before
            .iter()
            .enumerate()
            .any(|(i, previous)| incoming["projections"][i]["before_hash"] != *previous)
        {
            return Err(error("COMMIT_DESTINATION_LINEAGE"));
        }
        let record = Record::new(intent);
        let prepared_bytes=if matches!(self.storage_version,3|4) {
            let bytes=p.encode()?;record_bound(bytes.len(),false,false)?;Some(bytes)
        }else{None};
        let legacy=if self.storage_version==2 {
            #[cfg(test)] COMMIT_LEGACY_RECORD_CONSTRUCTIONS.with(|count|count.set(count.get()+1));
            Some(record.record())
        }else{None};
        let summary=json!({"kind":"EXECUTION_PREPARED","sequence":p.sequence(),"input_id":p.input()["input_id"]});
        let dictionary=self.dictionary_anchor_for(p.sequence())?;
        let encoded=match prepared_bytes.as_deref() {
            Some(bytes) if self.storage_version==4=>Some(crate::dictionary_codec::encode_bytes(bytes,summary,p.sequence(),dictionary.as_ref().map(|source|&source.anchor))?),
            Some(bytes)=>Some(crate::codec::encode_bytes(bytes,summary)?),
            None=>None,
        };
        let prepared_digest=prepared_bytes.as_deref().map(digest);
        drop(prepared_bytes);
        let tx = sql(self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate))?;
        if let Some(raw)=encoded.as_ref() {
            sql(tx.execute("INSERT INTO records VALUES(?1,?2,?3,?4,0,0)",params![integer(p.sequence())?,p.input()["input_id"].as_str(),&raw,digest(raw.as_bytes())]))?;
        }else {
            let v=legacy.as_ref().ok_or_else(||error("SCHEMA"))?;
            sql(tx.execute("INSERT INTO records VALUES(?1,?2,?3,?4)",params![integer(p.sequence())?,p.input()["input_id"].as_str(),v.to_string(),hash(v)]))?;
        }
        let prepared_digest=match prepared_digest {Some(logical)=>logical,None=>prepared_hash(p)?};
        sql(tx.execute(
            "UPDATE state SET head=?1,last_hash=?2 WHERE singleton=1",
            params![integer(p.sequence())?, prepared_digest],
        ))?;
        sql(tx.commit())?;
        if self.storage_version==4 {
            // The actual just-published row and base must pass the same complete
            // codec/scope reader before sharing the original passive body. Only
            // its data-valid slot may be shared; planner/typed authority is dropped.
            let observed=self.read_one(p.sequence())?.ok_or_else(||error("COMMIT_READBACK"))?.0;
            let raw=encoded.as_ref().ok_or_else(||error("COMMIT_READBACK"))?;
            let mut rows=self.decoded_rows.borrow_mut();
            let cached=rows.get_mut(&p.sequence()).ok_or_else(||error("COMMIT_READBACK"))?;
            if cached.payload!=*raw||cached.digest!=digest(raw.as_bytes())||observed.prepared()!=p{return Err(error("COMMIT_READBACK"));}
            cached.record=record.observation_snapshot(observed.ready(),observed.delivered())?;
        }
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
pub(crate) struct Replay {
    rows: Vec<Record>,
}
impl Replay {
    pub(crate) fn records(&self)->&[Record]{&self.rows}
}
#[cfg(test)]
std::thread_local! {
    static CHECKPOINT_PROOF_GETS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}
impl Store for Replay {
    fn head(&self) -> Result<u64, Error> {
        Ok(self.rows.len() as u64)
    }
    fn get(&self, n: u64) -> Result<Option<Record>, Error> {
        #[cfg(test)]
        CHECKPOINT_PROOF_GETS.with(|reads| reads.set(reads.get() + 1));
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

#[cfg(test)]
#[path = "../tests/support/checkpoint_work.rs"]
mod checkpoint_work_tests;
