//! 原 Run 的模拟场所写者。来源步和实际事实先原子提交，再向调用方公开。
use super::{VirtualBroker, plan::err};
use onlyalpha_broker::{
    self as broker, Broker, BrokerCommand, Capabilities, Connection, ConnectionPort,
    DispatchResult, Error, Journal, ReadyIntent, Scope, TradingPort,
    source::{
        QueryPhase, decode_source_json, source_fact_link, source_query_id, source_step_digest,
    },
};
use onlyalpha_domain::{
    base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp, value::OnlyMoney,
};
use rusqlite::{Connection as Db, OpenFlags, OptionalExtension, TransactionBehavior, params};
use serde_json::{Value, json};
use std::{fs::File, path::Path};

const SCHEMA:&str="
CREATE TABLE source_genesis(singleton INTEGER PRIMARY KEY CHECK(singleton=1),binding TEXT NOT NULL) STRICT;
CREATE TABLE protocol_records(sequence INTEGER PRIMARY KEY,hash TEXT NOT NULL,record TEXT NOT NULL,byte_total INTEGER NOT NULL,admitted_at TEXT,source_step INTEGER REFERENCES source_steps(sequence),query_id TEXT UNIQUE REFERENCES source_queries(id)) STRICT;
CREATE TABLE source_steps(sequence INTEGER PRIMARY KEY,previous TEXT NOT NULL,input TEXT NOT NULL,fact_count INTEGER NOT NULL,hash TEXT NOT NULL UNIQUE,witness INTEGER REFERENCES protocol_records(sequence)) STRICT;
CREATE TABLE source_facts(step INTEGER NOT NULL REFERENCES source_steps(sequence),ordinal INTEGER NOT NULL,identity TEXT NOT NULL UNIQUE,fact TEXT NOT NULL,stream_at TEXT NOT NULL,PRIMARY KEY(step,ordinal)) STRICT;
CREATE TABLE source_results(step INTEGER PRIMARY KEY REFERENCES source_steps(sequence),outcome TEXT NOT NULL CHECK(outcome IN ('RECEIVED','REJECTED'))) STRICT;
CREATE TABLE source_queries(id TEXT PRIMARY KEY,step INTEGER NOT NULL REFERENCES source_steps(sequence),protocol INTEGER NOT NULL REFERENCES protocol_records(sequence),phase TEXT NOT NULL CHECK(phase IN ('DISCOVERY','RESOLVE')),header TEXT NOT NULL,UNIQUE(step,protocol,phase,header)) STRICT;
CREATE INDEX source_query_step ON source_queries(step);
CREATE TABLE source_query_facts(query_id TEXT NOT NULL REFERENCES source_queries(id),ordinal INTEGER NOT NULL,identity TEXT NOT NULL REFERENCES source_facts(identity),PRIMARY KEY(query_id,ordinal)) STRICT;
CREATE TABLE protocol_ingress(identity TEXT PRIMARY KEY REFERENCES source_facts(identity),sequence INTEGER NOT NULL REFERENCES protocol_records(sequence)) STRICT;
CREATE INDEX dispatched_command ON protocol_records(json_extract(record,'$.event.command_id')) WHERE json_extract(record,'$.event.kind')='DISPATCHED';
CREATE INDEX admitted_command ON protocol_records(json_extract(record,'$.event.intent.command.command_id')) WHERE json_extract(record,'$.event.kind')='INTENT';
CREATE INDEX observed_source_step ON protocol_records(source_step) WHERE source_step IS NOT NULL;
CREATE INDEX source_bar_sequence ON source_steps(json_extract(input,'$[1]')) WHERE json_extract(input,'$[0]')='BAR';
PRAGMA user_version=2;";
fn io(e: impl std::fmt::Display) -> Error {
    Error::new(&format!("VIRTUAL_SOURCE_IO: {e}"))
}
fn connect(root: &Path) -> Result<Db, Error> {
    let path = root.join("broker.sqlite3");
    let metadata = std::fs::symlink_metadata(&path).map_err(io)?;
    #[cfg(unix)]
    if std::os::unix::fs::MetadataExt::nlink(&metadata) != 1 {
        return Err(err("VIRTUAL_SOURCE_HARD_LINK"));
    }
    if !metadata.is_file() {
        return Err(err("VIRTUAL_SOURCE_NOT_REGULAR"));
    }
    let db = Db::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NOFOLLOW,
    )
    .map_err(io)?;
    db.busy_timeout(std::time::Duration::ZERO).map_err(io)?;
    db.execute_batch("PRAGMA foreign_keys=ON; PRAGMA trusted_schema=OFF; PRAGMA synchronous=FULL;")
        .map_err(io)?;
    Ok(db)
}
/// 取得本介质中对应原命令或原发布的确定记录；空 CLOCK/BAR 不需要伪造协议事件。
fn original_observation(db: &Db, id: &str) -> Result<Option<(i64, String)>, Error> {
    db.query_row("SELECT p.sequence,p.hash FROM protocol_ingress i JOIN protocol_records p ON p.sequence=i.sequence JOIN source_facts s ON s.identity=i.identity JOIN json_each(CASE json_extract(p.record,'$.event.kind') WHEN 'INGRESS' THEN json_extract(p.record,'$.event.facts') ELSE json_extract(p.record,'$.event.discovery.facts') END) f ON f.value=s.fact WHERE i.identity=?1 AND json_extract(p.record,'$.event.kind') IN ('INGRESS','DISCOVERY','RESOLVE')",[id],|r|Ok((r.get(0)?,r.get(1)?))).optional().map_err(io)
}
fn protocol_witness(db: &Db, input: &Value, now: i64) -> Result<Option<(i64, String)>, Error> {
    match input[0].as_str() {
        Some("COMMAND" | "NOT_READY") => {
            let c = BrokerCommand::decode(&input[1])?;
            let found:Option<(i64,String,Option<String>)>=db.query_row("SELECT d.sequence,d.hash,d.admitted_at FROM protocol_records p JOIN protocol_records d ON d.sequence>p.sequence WHERE json_extract(p.record,'$.event.kind')='INTENT' AND json_extract(p.record,'$.event.intent.command.command_id')=?1 AND json_extract(d.record,'$.event.kind')='DISPATCHED' AND json_extract(d.record,'$.event.command_id')=?1 AND json_extract(p.record,'$.event.intent.command')=json(?2) ORDER BY d.sequence LIMIT 1",params![c.id(),c.record().to_string()],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional().map_err(io)?;
            let (sequence, hash, admission) =
                found.ok_or_else(|| err("VIRTUAL_SOURCE_ORIGINAL_DISPATCH_REQUIRED"))?;
            if c.operation() == broker::Operation::Submit {
                let at: Value = serde_json::from_str(
                    admission
                        .as_deref()
                        .ok_or_else(|| err("VIRTUAL_SOURCE_ADMISSION_REQUIRED"))?,
                )?;
                broker::source::check_admission_clock(c.scope(), &json!(["CLOCK", now]), &at)?;
            }
            Ok(Some((sequence, broker::digest(&json!([hash, admission])))))
        }
        Some("PUBLISHED") => {
            let witness = original_observation(
                db,
                input[1]
                    .as_str()
                    .ok_or_else(|| err("VIRTUAL_SOURCE_PUBLICATION"))?,
            )?;
            let (n, hash) =
                witness.ok_or_else(|| err("VIRTUAL_SOURCE_ORIGINAL_INGRESS_REQUIRED"))?;
            Ok(Some((n, broker::digest(&json!([hash, Value::Null])))))
        }
        _ => Ok(None),
    }
}
fn command_outcome(venue: &VirtualBroker, input: &Value) -> Option<&'static str> {
    if !matches!(input[0].as_str(), Some("COMMAND" | "NOT_READY")) {
        return None;
    }
    let id = input[1]["command_id"].as_str()?;
    Some(if venue.state.rejected.contains(id) {
        "REJECTED"
    } else {
        "RECEIVED"
    })
}
fn binding_witness(witness: &Option<(i64, String)>, outcome: Option<&str>) -> Option<String> {
    witness.as_ref().map(|(_, hash)| match outcome {
        Some(result) => broker::digest(&json!([hash, result])),
        None => hash.clone(),
    })
}
fn protocol_prefix(db: &Db, end: i64) -> Result<(Vec<broker::Record>, String), Error> {
    let mut read = db.prepare("SELECT sequence,hash,record FROM protocol_records WHERE sequence<=?1 ORDER BY sequence").map_err(io)?;
    let mut rows = read.query([end]).map_err(io)?;
    let mut prefix = Vec::new();
    let mut head = "0".repeat(64);
    let mut size = 0usize;
    while let Some(row) = rows.next().map_err(io)? {
        let raw: String = row.get(2).map_err(io)?;
        size = size
            .checked_add(raw.len())
            .and_then(|n| n.checked_add(1))
            .filter(|n| *n <= 32 * 1024 * 1024)
            .ok_or_else(|| err("VIRTUAL_SOURCE_QUERY_PROTOCOL_LIMIT"))?;
        let record = decode_source_json(&raw)?;
        let sequence: i64 = row.get(0).map_err(io)?;
        let hash: String = row.get(1).map_err(io)?;
        if i64::try_from(prefix.len()).map_err(io)?.checked_add(1) != Some(sequence)
            || record["sequence"] != sequence
            || record["hash"] != hash
            || record["previous"] != head
        {
            return Err(err("VIRTUAL_SOURCE_PROTOCOL_RELATION"));
        }
        let mut body = record.clone();
        body.as_object_mut()
            .ok_or_else(|| err("VIRTUAL_SOURCE_PROTOCOL_RELATION"))?
            .remove("hash");
        if broker::digest(&body) != hash {
            return Err(err("VIRTUAL_SOURCE_PROTOCOL_RELATION"));
        }
        head = hash;
        prefix.push(broker::Record::decode(&record)?);
    }
    if i64::try_from(prefix.len()).map_err(io)? != end {
        return Err(err("VIRTUAL_SOURCE_PROTOCOL_RELATION"));
    }
    Ok((prefix, head))
}
fn check_query_children(db: &Db, key: &str, discovery: &broker::Discovery) -> Result<(), Error> {
    let mut q = db
        .prepare(
            "SELECT ordinal,identity FROM source_query_facts WHERE query_id=?1 ORDER BY ordinal",
        )
        .map_err(io)?;
    let mut rows = q.query([key]).map_err(io)?;
    for (n, fact) in discovery.facts().iter().enumerate() {
        let row = rows
            .next()
            .map_err(io)?
            .ok_or_else(|| err("VIRTUAL_SOURCE_QUERY_FACTS"))?;
        if row.get::<_, i64>(0).map_err(io)? != i64::try_from(n).map_err(io)?
            || row.get::<_, String>(1).map_err(io)? != fact.identity()
        {
            return Err(err("VIRTUAL_SOURCE_QUERY_FACTS"));
        }
    }
    if rows.next().map_err(io)?.is_some() {
        return Err(err("VIRTUAL_SOURCE_QUERY_FACTS"));
    }
    Ok(())
}
/// 已运行实际撮合后的候选，只有本模块能形成。事实由场所状态借出，逐行持久化。
struct AppliedVenueStep<'a> {
    input: &'a Value,
    facts: &'a [broker::Fact],
    stream_at: &'a [i64],
    sequence: u64,
    previous: &'a str,
    now: i64,
    outcome: Option<&'static str>,
}
impl AppliedVenueStep<'_> {
    fn commit(&self, db: &mut Db) -> Result<String, Error> {
        let tx = db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(io)?;
        let stored_sequence = i64::try_from(self.sequence).map_err(io)?;
        let last: Option<(i64, String)> = tx
            .query_row(
                "SELECT sequence,hash FROM source_steps ORDER BY sequence DESC LIMIT 1",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()
            .map_err(io)?;
        if !match last {
            None => self.sequence == 1,
            Some((n, hash)) => n.checked_add(1) == Some(stored_sequence) && hash == self.previous,
        } {
            return Err(err("VIRTUAL_SOURCE_PREDECESSOR"));
        }
        let witness = protocol_witness(&tx, self.input, self.now)?;
        if self.outcome.is_some() {
            let tip: i64 = tx
                .query_row("SELECT MAX(sequence) FROM protocol_records", [], |r| {
                    r.get(0)
                })
                .map_err(io)?;
            if witness.as_ref().map(|(seq, _)| *seq) != Some(tip) {
                return Err(err("VIRTUAL_SOURCE_DISPATCH_NO_LONGER_CURRENT"));
            }
        }
        let mut outputs = String::new();
        for (fact, at) in self.facts.iter().zip(self.stream_at) {
            outputs = source_fact_link(&outputs, fact, &json!(at));
        }
        let witness_hash = binding_witness(&witness, self.outcome);
        let hash = source_step_digest(
            self.previous,
            self.sequence,
            self.input,
            u64::try_from(self.facts.len()).map_err(io)?,
            &outputs,
            witness_hash.as_deref(),
        );
        tx.execute(
            "INSERT INTO source_steps VALUES(?1,?2,?3,?4,?5,?6)",
            params![
                stored_sequence,
                self.previous,
                self.input.to_string(),
                i64::try_from(self.facts.len()).map_err(io)?,
                hash,
                witness.map(|(n, _)| n)
            ],
        )
        .map_err(io)?;
        if let Some(outcome) = self.outcome {
            tx.execute(
                "INSERT INTO source_results VALUES(?1,?2)",
                params![stored_sequence, outcome],
            )
            .map_err(io)?;
        }
        {
            let mut write = tx
                .prepare("INSERT INTO source_facts VALUES(?1,?2,?3,?4,?5)")
                .map_err(io)?;
            for (ordinal, f) in self.facts.iter().enumerate() {
                write
                    .execute(params![
                        stored_sequence,
                        i64::try_from(ordinal).map_err(io)?,
                        f.identity(),
                        f.record().to_string(),
                        self.stream_at[ordinal].to_string()
                    ])
                    .map_err(io)?;
            }
        }
        let commit = tx.commit();
        // COMMIT 的返回值可能遗失，按同一 occurrence 读回原 hash，不另开写事务。
        let actual: Option<String> = db
            .query_row(
                "SELECT hash FROM source_steps WHERE sequence=?1",
                [stored_sequence],
                |r| r.get(0),
            )
            .optional()
            .map_err(io)?;
        if actual.as_ref() == Some(&hash) {
            return Ok(hash);
        }
        commit.map_err(io)?;
        Err(err("VIRTUAL_SOURCE_OUTCOME_UNAVAILABLE"))
    }
}
/// 绑定代际的确定性场所。内部状态只在持久提交后可观察。
pub struct BoundVirtualActor {
    venue: VirtualBroker,
    db: Db,
    head: String,
    sequence: u64,
    confirmed_clock: i64,
    healthy: bool,
}
impl BoundVirtualActor {
    fn initial(
        root: &Path,
        scope: Scope,
        artifact: &str,
        cash: OnlyMoney,
        config: &Value,
        expected: &str,
        create: bool,
    ) -> Result<Self, Error> {
        let venue = VirtualBroker::new(scope, artifact, cash, config)?;
        let head = broker::digest(venue.source_binding());
        if head != expected || venue.scope.record()["runtime_kind"] != "BACKTEST" {
            return Err(err("VIRTUAL_SOURCE_BINDING"));
        }
        if create {
            if root.join("broker.jsonl").exists() || root.join("runtime.sqlite3").exists() {
                return Err(err("VIRTUAL_SOURCE_EXISTING_RUN"));
            }
            File::create_new(root.join("broker.sqlite3")).map_err(io)?;
        }
        let mut db = connect(root)?;
        if create {
            let tx = db
                .transaction_with_behavior(TransactionBehavior::Immediate)
                .map_err(io)?;
            tx.execute_batch(SCHEMA).map_err(io)?;
            tx.execute(
                "INSERT INTO source_genesis VALUES(1,?1)",
                [venue.source_binding().to_string()],
            )
            .map_err(io)?;
            tx.commit().map_err(io)?;
            File::open(root)
                .and_then(|directory| directory.sync_all())
                .map_err(io)?;
        }
        let version: u32 = db
            .pragma_query_value(None, "user_version", |r| r.get(0))
            .map_err(io)?;
        let binding: String = db
            .query_row(
                "SELECT binding FROM source_genesis WHERE singleton=1",
                [],
                |r| r.get(0),
            )
            .map_err(io)?;
        let canonical_binding = serde_json::to_vec(venue.source_binding())?;
        if version != 2 || binding.as_bytes() != canonical_binding.as_slice() {
            return Err(err("VIRTUAL_SOURCE_BINDING"));
        }
        Ok(Self {
            venue,
            db,
            head,
            sequence: 0,
            confirmed_clock: 0,
            healthy: true,
        })
    }
    pub fn create(
        root: &Path,
        scope: Scope,
        artifact: &str,
        cash: OnlyMoney,
        config: &Value,
        expected: &str,
    ) -> Result<Self, Error> {
        Self::initial(root, scope, artifact, cash, config, expected, true)
    }
    pub fn open(
        root: &Path,
        scope: Scope,
        artifact: &str,
        cash: OnlyMoney,
        config: &Value,
        expected: &str,
    ) -> Result<Self, Error> {
        let mut owner = Self::initial(root, scope, artifact, cash, config, expected, false)?;
        let tx = owner.db.transaction().map_err(io)?;
        {
            let orphan: bool = tx
                .query_row(
                    "SELECT EXISTS(SELECT 1 FROM pragma_foreign_key_check)",
                    [],
                    |r| r.get(0),
                )
                .map_err(io)?;
            if orphan {
                return Err(err("VIRTUAL_SOURCE_ORPHAN_FACT"));
            }
            let mut steps=tx.prepare("SELECT sequence,previous,input,fact_count,hash,witness FROM source_steps ORDER BY sequence").map_err(io)?;
            let mut rows = steps.query([]).map_err(io)?;
            let mut results = tx
                .prepare("SELECT outcome FROM source_results WHERE step=?1")
                .map_err(io)?;
            let mut queries = tx
                .prepare(
                    "SELECT id,protocol,phase,header FROM source_queries WHERE step=?1 ORDER BY id",
                )
                .map_err(io)?;
            let mut children=tx.prepare("SELECT ordinal,fact,identity,stream_at FROM source_facts WHERE step=?1 ORDER BY ordinal").map_err(io)?;
            while let Some(row) = rows.next().map_err(io)? {
                let (seq, previous, input, count, h, witness): (
                    i64,
                    String,
                    String,
                    i64,
                    String,
                    Option<i64>,
                ) = (
                    row.get(0).map_err(io)?,
                    row.get(1).map_err(io)?,
                    row.get(2).map_err(io)?,
                    row.get(3).map_err(io)?,
                    row.get(4).map_err(io)?,
                    row.get(5).map_err(io)?,
                );
                let input = decode_source_json(&input)?;
                let sequence = u64::try_from(seq).map_err(io)?;
                let count = u64::try_from(count).map_err(io)?;
                if owner.sequence.checked_add(1) != Some(sequence) || previous != owner.head {
                    return Err(err("VIRTUAL_SOURCE_PREDECESSOR"));
                }
                let old = owner.venue.state.facts.len();
                let proof = protocol_witness(&tx, &input, owner.venue.now())?;
                if proof.as_ref().map(|(n, _)| *n) != witness {
                    return Err(err("VIRTUAL_SOURCE_PROTOCOL_RELATION"));
                }
                owner.venue.apply_bound_input(&input)?;
                let actual_outcome = command_outcome(&owner.venue, &input);
                let persisted: Option<String> = results
                    .query_row([seq], |r| r.get(0))
                    .optional()
                    .map_err(io)?;
                if actual_outcome != persisted.as_deref() {
                    return Err(err("VIRTUAL_SOURCE_RESULT_CONFLICT"));
                }
                let witness_hash = binding_witness(&proof, actual_outcome);
                let mut actual = children.query([seq]).map_err(io)?;
                let mut outputs = String::new();
                let born = &owner.venue.state.facts[old..];
                for (index, fact) in born.iter().enumerate() {
                    let child = actual
                        .next()
                        .map_err(io)?
                        .ok_or_else(|| err("VIRTUAL_SOURCE_OUTPUT_MISSING"))?;
                    let canonical_fact = serde_json::to_vec(&fact.record())?;
                    if child.get::<_, i64>(0).map_err(io)? != i64::try_from(index).map_err(io)?
                        || child.get::<_, String>(1).map_err(io)?.as_bytes()
                            != canonical_fact.as_slice()
                        || child.get::<_, String>(2).map_err(io)? != fact.identity()
                    {
                        return Err(err("VIRTUAL_SOURCE_OUTPUT_CONFLICT"));
                    }
                    let stream_at = owner.venue.state.stream_at[old + index];
                    if child.get::<_, String>(3).map_err(io)? != stream_at.to_string() {
                        return Err(err("VIRTUAL_SOURCE_OUTPUT_CONFLICT"));
                    }
                    outputs = source_fact_link(&outputs, fact, &json!(stream_at));
                }
                if actual.next().map_err(io)?.is_some()
                    || count != u64::try_from(born.len()).map_err(io)?
                    || source_step_digest(
                        &previous,
                        sequence,
                        &input,
                        count,
                        &outputs,
                        witness_hash.as_deref(),
                    ) != h
                {
                    return Err(err("VIRTUAL_SOURCE_OUTPUT_CONFLICT"));
                }
                owner.sequence = sequence;
                owner.head = h;
                owner.confirmed_clock = owner.venue.now();
                let mut found = queries.query([seq]).map_err(io)?;
                while let Some(row) = found.next().map_err(io)? {
                    let id: String = row.get(0).map_err(io)?;
                    let protocol: i64 = row.get(1).map_err(io)?;
                    let phase: String = row.get(2).map_err(io)?;
                    let raw: String = row.get(3).map_err(io)?;
                    let header = decode_source_json(&raw)?;
                    let command = header["command"]["command_id"]
                        .as_str()
                        .ok_or_else(|| err("VIRTUAL_SOURCE_QUERY_COMMAND"))?;
                    let (prefix, protocol_head) = protocol_prefix(&tx, protocol)?;
                    let discovery = owner.venue.bound_query(prefix, sequence, command)?;
                    if header != discovery.header()
                        || source_query_id(
                            QueryPhase::parse(&phase)?,
                            &owner.head,
                            &protocol_head,
                            &discovery,
                        ) != id
                    {
                        return Err(err("VIRTUAL_SOURCE_QUERY_CONFLICT"));
                    }
                    check_query_children(&tx, &id, &discovery)?;
                }
            }
        }
        tx.commit().map_err(io)?;
        Ok(owner)
    }
    /// 原介质的紧凑读取位置，恢复仍要求完整原来源库并逐步重放。
    pub fn checkpoint(&self) -> Value {
        json!({"schema_version":1,"binding":self.venue.binding,"sequence":self.sequence,"hash":self.head})
    }
    pub fn now(&self) -> i64 {
        self.confirmed_clock
    }
    fn ensure_head(&self) -> Result<(), Error> {
        if !self.healthy {
            return Err(err("VIRTUAL_SOURCE_REOPEN_REQUIRED"));
        }
        let latest: Option<(i64, String)> = self
            .db
            .query_row(
                "SELECT sequence,hash FROM source_steps ORDER BY sequence DESC LIMIT 1",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()
            .map_err(io)?;
        if latest
            != if self.sequence == 0 {
                None
            } else {
                Some((i64::try_from(self.sequence).map_err(io)?, self.head.clone()))
            }
        {
            return Err(err("VIRTUAL_SOURCE_PREDECESSOR"));
        }
        Ok(())
    }
    fn apply(&mut self, input: Value) -> Result<(), Error> {
        self.ensure_head()?;
        let sequence = self
            .sequence
            .checked_add(1)
            .ok_or_else(|| err("VIRTUAL_SOURCE_SEQUENCE"))?;
        let start = self.venue.state.facts.len();
        self.healthy = false;
        self.venue.apply_bound_input(&input)?;
        let candidate = AppliedVenueStep {
            input: &input,
            facts: &self.venue.state.facts[start..],
            stream_at: &self.venue.state.stream_at[start..],
            sequence,
            previous: &self.head,
            now: self.venue.now(),
            outcome: command_outcome(&self.venue, &input),
        };
        let hash = candidate.commit(&mut self.db)?;
        self.head = hash;
        self.sequence = sequence;
        self.confirmed_clock = self.venue.now();
        self.healthy = true;
        Ok(())
    }
    pub fn advance(&mut self, at: i64) -> Result<(), Error> {
        self.ensure_head()?;
        if at < self.now() {
            return Err(err("VIRTUAL_CLOCK_REGRESSION"));
        }
        self.apply(json!(["CLOCK", at]))
    }
    pub fn on_bar(&mut self, sequence: u64, bar: &OnlyBar) -> Result<(), Error> {
        self.ensure_head()?;
        let input = json!(["BAR", sequence, bar.to_record()]);
        if sequence <= self.venue.state.bar_sequence {
            let old:Option<String>=self.db.query_row("SELECT input FROM source_steps WHERE json_extract(input,'$[0]')='BAR' AND json_extract(input,'$[1]')=?1",[i64::try_from(sequence).map_err(io)?],|r|r.get(0)).optional().map_err(io)?;
            if old.as_deref().map(decode_source_json).transpose()?.as_ref() == Some(&input) {
                return Ok(());
            }
            return Err(err("VIRTUAL_BAR_CONFLICT"));
        }
        if OnlyTimestamp::from_datetime(*bar.ts_event()).to_unix_nanos() < self.now().into() {
            return Err(err("VIRTUAL_CLOCK_REGRESSION"));
        }
        self.apply(input)
    }
    pub fn publish(&mut self, broker: &mut Broker, j: &mut impl Journal) -> Result<usize, Error> {
        self.ensure_head()?;
        let mut count = 0;
        while let Some((_, index)) = self.venue.next_publication() {
            let f = &self.venue.state.facts[index];
            let input = json!(["PUBLISHED", f.identity(), f.fingerprint()]);
            // 已在原介质但游标未推进的发布只补来源步，不二次发布。
            if original_observation(&self.db, f.identity())?.is_none() {
                broker.ingest(j, std::slice::from_ref(f))?;
            }
            self.apply(input)?;
            count += 1;
        }
        Ok(count)
    }
    /// 在本来源与协议的同一原快照登记查询，返回可交给原 Journal 的 occurrence 索引。
    pub fn observe_command(&mut self, phase: QueryPhase, id: &str) -> Result<String, Error> {
        self.ensure_head()?;
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(io)?;
        let step = i64::try_from(self.sequence).map_err(io)?;
        let current: Option<(i64, String)> = tx
            .query_row(
                "SELECT sequence,hash FROM source_steps ORDER BY sequence DESC LIMIT 1",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()
            .map_err(io)?;
        if current
            .as_ref()
            .is_none_or(|(n, h)| *n != step || h != &self.head)
        {
            return Err(err("VIRTUAL_SOURCE_PREDECESSOR"));
        }
        let protocol: i64 = tx
            .query_row("SELECT MAX(sequence) FROM protocol_records", [], |r| {
                r.get(0)
            })
            .map_err(io)?;
        let (prefix, protocol_head) = protocol_prefix(&tx, protocol)?;
        let discovery = self.venue.bound_query(prefix, self.sequence, id)?;
        let key = source_query_id(phase, &self.head, &protocol_head, &discovery);
        let header = discovery.header().to_string();
        let inserted = tx
            .execute(
                "INSERT INTO source_queries VALUES(?1,?2,?3,?4,?5) ON CONFLICT(id) DO NOTHING",
                params![key, step, protocol, phase.kind(), header],
            )
            .map_err(io)?;
        if inserted == 1 {
            let mut write = tx
                .prepare("INSERT INTO source_query_facts VALUES(?1,?2,?3)")
                .map_err(io)?;
            for (n, fact) in discovery.facts().iter().enumerate() {
                write
                    .execute(params![key, i64::try_from(n).map_err(io)?, fact.identity()])
                    .map_err(io)?;
            }
        } else {
            let same:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM source_queries WHERE id=?1 AND step=?2 AND protocol=?3 AND phase=?4 AND header=?5)",params![key,step,protocol,phase.kind(),header],|r|r.get(0)).map_err(io)?;
            if !same {
                return Err(err("VIRTUAL_SOURCE_QUERY_CONFLICT"));
            }
            check_query_children(&tx, &key, &discovery)?;
        }
        let committed = tx.commit();
        let found:bool=self.db.query_row("SELECT EXISTS(SELECT 1 FROM source_queries WHERE id=?1 AND step=?2 AND protocol=?3 AND phase=?4 AND header=?5)",params![key,step,protocol,phase.kind(),header],|r|r.get(0)).map_err(io)?;
        if !found {
            committed.map_err(io)?;
            return Err(err("VIRTUAL_SOURCE_QUERY_OUTCOME_UNAVAILABLE"));
        }
        check_query_children(&self.db, &key, &discovery)?;
        Ok(key)
    }
}
impl ConnectionPort for BoundVirtualActor {
    fn connect(&mut self) -> Result<Connection, Error> {
        self.ensure_head()?;
        self.venue.connect()
    }
    fn authenticate(&mut self) -> Result<Connection, Error> {
        self.ensure_head()?;
        self.venue.authenticate()
    }
    fn disconnect(&mut self) -> Result<(), Error> {
        self.venue.disconnect()
    }
}
impl TradingPort for BoundVirtualActor {
    fn capabilities(&self) -> Capabilities {
        self.venue.capabilities()
    }
    fn check_dispatch(&self, intent: &ReadyIntent) -> Result<(), Error> {
        self.ensure_head()?;
        let at = intent
            .admitted_at()
            .ok_or_else(|| err("VIRTUAL_SOURCE_ADMISSION_REQUIRED"))?;
        broker::source::check_admission_clock(&self.venue.scope, &json!(["CLOCK", self.now()]), at)
    }
    fn dispatch(&mut self, c: &BrokerCommand) -> Result<DispatchResult, Error> {
        self.ensure_head()?;
        if let Some(old) = self.venue.state.commands.get(c.id()) {
            if old != c {
                return Err(err("VIRTUAL_COMMAND_CONFLICT"));
            }
        } else {
            let op = if self.venue.connection == Connection::Ready {
                "COMMAND"
            } else {
                "NOT_READY"
            };
            let input = json!([op, c.record()]);
            protocol_witness(&self.db, &input, self.now())?;
            self.apply(input)?;
        }
        Ok(if self.venue.state.rejected.contains(c.id()) {
            DispatchResult::Rejected
        } else {
            DispatchResult::Received
        })
    }
}
