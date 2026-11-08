//! 新绑定模拟场所的只读来源与原 Broker 协议介质。来源写者只在具体场所宿主内。
use onlyalpha_broker::{
    AppendIntent, Broker, BrokerCommand, Discovery, DiscoveryPort, Error, Fact, Journal, Record,
    Scope, digest,
    source::{
        QueryPhase, SourceHistory, SourceStep, decode_source_json, source_fact_link,
        source_query_id, source_step_digest,
    },
};
use rusqlite::{Connection, OpenFlags, OptionalExtension, TransactionBehavior, params};
use serde_json::Value;
use std::path::{Path, PathBuf};
fn failed(e: impl std::fmt::Display) -> Error {
    Error::new(&format!("BROKER_SOURCE_STORE: {e}"))
}
fn invalid(code: &str) -> Error {
    Error::new(code)
}
pub struct BoundBrokerJournal {
    path: PathBuf,
    binding: String,
}
impl BoundBrokerJournal {
    pub fn open(root: &Path, expected: &str) -> Result<Self, Error> {
        let journal = Self {
            path: root.canonicalize().map_err(failed)?.join("broker.sqlite3"),
            binding: expected.into(),
        };
        journal.connection(false)?;
        Ok(journal)
    }
    /// 在这份原 Run 的真实 Ready Reader 上派发。普通 Journal 的记录端口没有新命令资格。
    pub fn dispatch(
        &mut self,
        broker: &mut onlyalpha_broker::Broker,
        runtime: &crate::Runtime,
        adapter: &mut impl onlyalpha_broker::TradingPort,
        command: &onlyalpha_broker::BrokerCommand,
    ) -> Result<onlyalpha_broker::CommandState, Error> {
        self.require_runtime(runtime)?;
        broker.dispatch(
            &mut OriginalAppend(self, Admission::Dispatch),
            runtime,
            adapter,
            command,
        )
    }
    fn connection(&self, write: bool) -> Result<Connection, Error> {
        let metadata = std::fs::symlink_metadata(&self.path).map_err(failed)?;
        #[cfg(unix)]
        if std::os::unix::fs::MetadataExt::nlink(&metadata) != 1 {
            return Err(invalid("BROKER_SOURCE_HARD_LINK"));
        }
        if !metadata.is_file() {
            return Err(invalid("BROKER_SOURCE_NOT_REGULAR"));
        }
        let mode = if write {
            OpenFlags::SQLITE_OPEN_READ_WRITE
        } else {
            OpenFlags::SQLITE_OPEN_READ_ONLY
        };
        let db = Connection::open_with_flags(&self.path, mode | OpenFlags::SQLITE_OPEN_NOFOLLOW)
            .map_err(failed)?;
        db.busy_timeout(std::time::Duration::ZERO).map_err(failed)?;
        db.execute_batch("PRAGMA trusted_schema=OFF; PRAGMA foreign_keys=ON;")
            .map_err(failed)?;
        if write {
            db.execute_batch("PRAGMA synchronous=FULL;")
                .map_err(failed)?;
        }
        let version: u32 = db
            .pragma_query_value(None, "user_version", |r| r.get(0))
            .map_err(failed)?;
        let original: String = db
            .query_row(
                "SELECT binding FROM source_genesis WHERE singleton=1",
                [],
                |r| r.get(0),
            )
            .map_err(failed)?;
        if version != 2 || digest(&decode_source_json(&original)?) != self.binding {
            return Err(invalid("BROKER_SOURCE_GENESIS"));
        }
        Ok(db)
    }
    pub(crate) fn check_run(&self, cfg: &Value, create: bool) -> Result<(), Error> {
        let db = self.connection(false)?;
        let original: String = db
            .query_row(
                "SELECT binding FROM source_genesis WHERE singleton=1",
                [],
                |r| r.get(0),
            )
            .map_err(failed)?;
        let original = decode_source_json(&original)?;
        if [
            "engine",
            "runtime",
            "account",
            "gateway",
            "generation",
            "runtime_kind",
        ]
        .iter()
        .any(|key| original["scope"][*key] != cfg[*key])
        {
            return Err(invalid("BROKER_SOURCE_GENESIS_SCOPE"));
        }
        if create && db.query_row("SELECT EXISTS(SELECT 1 FROM protocol_records UNION ALL SELECT 1 FROM source_steps)",[],|r|r.get::<_,bool>(0)).map_err(failed)?{
            return Err(invalid("BROKER_SOURCE_EXISTING_GENERATION"));
        }
        Ok(())
    }
    pub(crate) fn history(
        &self,
        scope: Scope,
        boundary: Option<(u64, u64)>,
    ) -> Result<SourceHistory, Error> {
        let mut db = self.connection(false)?;
        let tx = db.transaction().map_err(failed)?;
        let genesis: String = tx
            .query_row(
                "SELECT binding FROM source_genesis WHERE singleton=1",
                [],
                |r| r.get(0),
            )
            .map_err(failed)?;
        let mut history = SourceHistory::new(
            scope,
            &decode_source_json(&genesis)?,
            &self.binding,
            boundary,
        )?;
        let orphan: bool = tx
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM pragma_foreign_key_check)",
                [],
                |r| r.get(0),
            )
            .map_err(failed)?;
        if orphan {
            return Err(invalid("BROKER_SOURCE_ORPHAN_FACT"));
        }
        let mut steps=tx.prepare("SELECT s.sequence,s.previous,s.input,s.fact_count,s.hash,s.witness,p.record,p.hash,p.admitted_at,r.outcome FROM source_steps s LEFT JOIN protocol_records p ON p.sequence=s.witness LEFT JOIN source_results r ON r.step=s.sequence ORDER BY s.sequence").map_err(failed)?;
        let mut rows = steps.query([]).map_err(failed)?;
        let mut facts=tx.prepare("SELECT ordinal,identity,fact,stream_at FROM source_facts WHERE step=?1 ORDER BY ordinal").map_err(failed)?;
        let mut observations = tx
            .prepare("SELECT record FROM protocol_records WHERE source_step=?1 ORDER BY sequence")
            .map_err(failed)?;
        while let Some(row) = rows.next().map_err(failed)? {
            let (seq, prev, input, count, hash): (i64, String, String, i64, String) = (
                row.get(0).map_err(failed)?,
                row.get(1).map_err(failed)?,
                row.get(2).map_err(failed)?,
                row.get(3).map_err(failed)?,
                row.get(4).map_err(failed)?,
            );
            let children = facts
                .query_map([seq], |r| {
                    Ok((
                        r.get::<_, i64>(0)?,
                        r.get::<_, String>(1)?,
                        r.get::<_, String>(2)?,
                        r.get::<_, String>(3)?,
                    ))
                })
                .map_err(failed)?;
            let input = decode_source_json(&input)?;
            let witness_number: Option<i64> = row.get(5).map_err(failed)?;
            let record: Option<String> = row.get(6).map_err(failed)?;
            let witness_hash: Option<String> = row.get(7).map_err(failed)?;
            let admitted: Option<String> = row.get(8).map_err(failed)?;
            let outcome: Option<String> = row.get(9).map_err(failed)?;
            if matches!(input[0].as_str(), Some("COMMAND" | "NOT_READY")) != outcome.is_some() {
                return Err(invalid("BROKER_SOURCE_COMMAND_RESULT"));
            }
            let bound_witness = witness_hash.as_ref().map(|h| {
                let witness = digest(&serde_json::json!([h, admitted]));
                match &outcome {
                    Some(result) => digest(&serde_json::json!([witness, result])),
                    None => witness,
                }
            });
            let protocol = record
                .as_deref()
                .map(serde_json::from_str::<Value>)
                .transpose()?;
            if protocol.as_ref().and_then(|r| r["sequence"].as_i64()) != witness_number
                || protocol.as_ref().and_then(|r| r["hash"].as_str()) != witness_hash.as_deref()
            {
                return Err(invalid("BROKER_SOURCE_PROTOCOL_RELATION"));
            }
            match input[0].as_str() {
                Some("COMMAND" | "NOT_READY") => {
                    let r = protocol
                        .as_ref()
                        .ok_or_else(|| invalid("BROKER_SOURCE_ORIGINAL_DISPATCH_REQUIRED"))?;
                    let command = onlyalpha_broker::BrokerCommand::decode(&input[1])?;
                    if r["event"]["kind"] != "DISPATCHED"
                        || r["event"]["command_id"] != command.id()
                    {
                        return Err(invalid("BROKER_SOURCE_ORIGINAL_DISPATCH_REQUIRED"));
                    }
                    let original:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM protocol_records WHERE sequence<?1 AND json_extract(record,'$.event.kind')='INTENT' AND json_extract(record,'$.event.intent.command')=json(?2))",params![witness_number,command.record().to_string()],|r|r.get(0)).map_err(failed)?;
                    if !original {
                        return Err(invalid("BROKER_SOURCE_ORIGINAL_DISPATCH_REQUIRED"));
                    }
                    if command.operation() == onlyalpha_broker::Operation::Submit {
                        history.check_admission(&serde_json::from_str(
                            admitted
                                .as_deref()
                                .ok_or_else(|| invalid("BROKER_SOURCE_ADMISSION_REQUIRED"))?,
                        )?)?;
                    }
                }
                Some("PUBLISHED") => {
                    let r = protocol
                        .as_ref()
                        .ok_or_else(|| invalid("BROKER_SOURCE_ORIGINAL_INGRESS_REQUIRED"))?;
                    let facts = match r["event"]["kind"].as_str() {
                        Some("INGRESS") => &r["event"]["facts"],
                        Some("DISCOVERY" | "RESOLVE") => &r["event"]["discovery"]["facts"],
                        _ => return Err(invalid("BROKER_SOURCE_ORIGINAL_INGRESS_REQUIRED")),
                    };
                    if !facts.as_array().is_some_and(|facts| {
                        facts.iter().any(|v| {
                            Fact::decode(v).is_ok_and(|f| {
                                input[1] == f.identity() && input[2] == f.fingerprint()
                            })
                        })
                    }) {
                        return Err(invalid("BROKER_SOURCE_ORIGINAL_INGRESS_REQUIRED"));
                    }
                }
                _ if witness_number.is_some() => {
                    return Err(invalid("BROKER_SOURCE_UNEXPECTED_PROTOCOL_RELATION"));
                }
                _ => {}
            }
            history.accept_step(
                SourceStep {
                    sequence: u64::try_from(seq).map_err(failed)?,
                    previous: &prev,
                    input: &input,
                    fact_count: u64::try_from(count).map_err(failed)?,
                    hash: &hash,
                    protocol_hash: bound_witness.as_deref(),
                },
                children.enumerate().map(|(index, child)| {
                    let (ordinal, id, raw, stream_at) = child.map_err(failed)?;
                    let fact = Fact::decode(&decode_source_json(&raw)?)?;
                    if usize::try_from(ordinal).map_err(failed)? != index || id != fact.identity() {
                        return Err(invalid("BROKER_SOURCE_OUTPUT_RELATION"));
                    }
                    Ok((fact, decode_source_json(&stream_at)?))
                }),
            )?;
            let observed = observations
                .query_map([seq], |r| r.get::<_, String>(0))
                .map_err(failed)?;
            for raw in observed {
                let r: Value = serde_json::from_str(&raw.map_err(failed)?)?;
                let event = &r["event"];
                let facts = if event["kind"] == "INGRESS" {
                    &event["facts"]
                } else {
                    &event["discovery"]["facts"]
                };
                for raw in facts
                    .as_array()
                    .ok_or_else(|| invalid("BROKER_SOURCE_FACTS"))?
                {
                    history.observe(&Fact::decode(raw)?)?;
                }
            }
        }
        Ok(history)
    }
    fn check_dispatch(
        db: &Connection,
        event: &Value,
        admitted_at: Option<&Value>,
    ) -> Result<(), Error> {
        if event["kind"] != "DISPATCHED" {
            return Ok(());
        }
        let id = event["command_id"]
            .as_str()
            .ok_or_else(|| invalid("BROKER_SOURCE_COMMAND"))?;
        let intent:String=db.query_row("SELECT record FROM protocol_records WHERE json_extract(record,'$.event.kind')='INTENT' AND json_extract(record,'$.event.intent.command.command_id')=?1",[id],|r|r.get(0)).map_err(failed)?;
        let raw: Value = serde_json::from_str(&intent)?;
        if raw["event"]["intent"]["command"]["operation"] != "SUBMIT" {
            return Ok(());
        }
        let r = &raw["event"]["intent"];
        let latest:Option<String>=db.query_row("SELECT input FROM source_steps WHERE json_extract(input,'$[0]') IN ('CLOCK','BAR') ORDER BY sequence DESC LIMIT 1",[],|r|r.get(0)).optional().map_err(failed)?;
        let scope = Scope::decode(&r["command"]["scope"])?;
        let step = if let Some(input) = latest {
            decode_source_json(&input)?
        } else {
            serde_json::json!(["CLOCK", 0])
        };
        onlyalpha_broker::source::check_admission_clock(
            &scope,
            &step,
            admitted_at.ok_or_else(|| invalid("BROKER_SOURCE_ADMISSION_REQUIRED"))?,
        )
    }
    fn check_observations(
        db: &Connection,
        event: &Value,
        source_step: Option<i64>,
    ) -> Result<(), Error> {
        let facts = match event["kind"].as_str() {
            Some("INGRESS") => &event["facts"],
            Some("DISCOVERY" | "RESOLVE") => &event["discovery"]["facts"],
            _ => return Ok(()),
        };
        let mut existing = db
            .prepare("SELECT fact,step FROM source_facts WHERE identity=?1")
            .map_err(failed)?;
        for value in facts
            .as_array()
            .ok_or_else(|| invalid("BROKER_SOURCE_FACTS"))?
        {
            let fact = Fact::decode(value)?;
            let original: Option<(String, i64)> = existing
                .query_row([fact.identity()], |r| Ok((r.get(0)?, r.get(1)?)))
                .optional()
                .map_err(failed)?;
            let (raw, birth) =
                original.ok_or_else(|| invalid("BROKER_SOURCE_ORIGINAL_FACT_REQUIRED"))?;
            let canonical_fact = serde_json::to_vec(value)?;
            if birth <= 0
                || source_step.is_none_or(|s| s < birth)
                || raw.as_bytes() != canonical_fact.as_slice()
            {
                return Err(invalid("BROKER_SOURCE_ORIGINAL_FACT_REQUIRED"));
            }
        }
        Ok(())
    }
}
enum Admission<'a> {
    Ordinary,
    Dispatch,
    Query(&'a str),
    Ack,
}
struct OriginalAppend<'a>(&'a mut BoundBrokerJournal, Admission<'a>);
impl Journal for OriginalAppend<'_> {
    fn records(&self) -> Result<Vec<Record>, Error> {
        self.0.records()
    }
    fn append(&mut self, intent: &AppendIntent) -> Result<(), Error> {
        self.0.append_record(intent, &self.1)
    }
}
struct OriginalDiscovery(Discovery);
impl DiscoveryPort for OriginalDiscovery {
    fn discover(&mut self, command: &BrokerCommand) -> Result<Discovery, Error> {
        if self.0.header()["command"] != command.record() {
            return Err(invalid("BROKER_SOURCE_QUERY_COMMAND"));
        }
        Ok(self.0.clone())
    }
}
struct Query {
    phase: QueryPhase,
    step: i64,
    protocol: i64,
    discovery: Discovery,
}
impl Query {
    fn read(db: &Connection, key: &str) -> Result<Self, Error> {
        let (step, source_head, protocol, protocol_head, phase, raw):
            (i64,String,i64,String,String,String) = db.query_row(
            "SELECT q.step,s.hash,q.protocol,p.hash,q.phase,q.header FROM source_queries q JOIN source_steps s ON s.sequence=q.step JOIN protocol_records p ON p.sequence=q.protocol WHERE q.id=?1",
            [key], |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?))).map_err(failed)?;
        let phase = QueryPhase::parse(&phase)?;
        let mut value = decode_source_json(&raw)?;
        let command = BrokerCommand::decode(&value["command"])?;
        let original:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM protocol_records i JOIN protocol_records d ON i.sequence<d.sequence WHERE d.sequence<=?1 AND json_extract(i.record,'$.event.kind')='INTENT' AND json_extract(i.record,'$.event.intent.command')=json(?2) AND json_extract(d.record,'$.event.kind')='DISPATCHED' AND json_extract(d.record,'$.event.command_id')=?3)",params![protocol,command.record().to_string(),command.id()],|r|r.get(0)).map_err(failed)?;
        if !original || value["as_of"] != step {
            return Err(invalid("BROKER_SOURCE_QUERY_COMMAND"));
        }
        let mut statement=db.prepare("SELECT q.ordinal,q.identity,f.fact,f.step FROM source_query_facts q LEFT JOIN source_facts f ON f.identity=q.identity WHERE q.query_id=?1 ORDER BY q.ordinal").map_err(failed)?;
        let mut facts = Vec::new();
        let mut rows = statement.query([key]).map_err(failed)?;
        while let Some(row) = rows.next().map_err(failed)? {
            let raw: String = row.get(2).map_err(failed)?;
            let fact = Fact::decode(&decode_source_json(&raw)?)?;
            if row.get::<_, i64>(0).map_err(failed)?
                != i64::try_from(facts.len()).map_err(failed)?
                || row.get::<_, String>(1).map_err(failed)? != fact.identity()
                || row.get::<_, i64>(3).map_err(failed)? > step
            {
                return Err(invalid("BROKER_SOURCE_QUERY_FACT"));
            }
            facts.push(fact.record());
        }
        value["facts"] = Value::Array(facts);
        let discovery = Discovery::decode(&value)?;
        if source_query_id(phase, &source_head, &protocol_head, &discovery) != key {
            return Err(invalid("BROKER_SOURCE_QUERY_ID"));
        }
        Ok(Self {
            phase,
            step,
            protocol,
            discovery,
        })
    }
}
impl BoundBrokerJournal {
    fn require_runtime(&self, runtime: &crate::Runtime) -> Result<(), Error> {
        if self.path.parent() != Some(runtime.store.root())
            || runtime.store.identity()["configuration"]["perpetual"]["execution_source_binding"]
                != self.binding
        {
            return Err(invalid("BROKER_SOURCE_RUNTIME_SCOPE"));
        }
        runtime.require_healthy().map_err(failed)
    }
    fn original_query(
        &self,
        phase: QueryPhase,
        id: &str,
        key: &str,
    ) -> Result<(OriginalDiscovery, bool), Error> {
        let mut db = self.connection(false)?;
        let tx = db.transaction().map_err(failed)?;
        let q = Query::read(&tx, key)?;
        if q.phase != phase || q.discovery.header()["command"]["command_id"] != id {
            return Err(invalid("BROKER_SOURCE_QUERY_RELATION"));
        }
        let consumed: bool = tx
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM protocol_records WHERE query_id=?1)",
                [key],
                |r| r.get(0),
            )
            .map_err(failed)?;
        Ok((OriginalDiscovery(q.discovery), consumed))
    }
    pub fn reconcile_original(
        &mut self,
        broker: &mut Broker,
        id: &str,
        key: &str,
    ) -> Result<(), Error> {
        let (mut query, consumed) = self.original_query(QueryPhase::Discovery, id, key)?;
        if consumed {
            return broker.refresh(self);
        }
        broker.reconcile(
            &mut OriginalAppend(self, Admission::Query(key)),
            &mut query,
            id,
        )
    }
    pub fn acknowledge_original(
        &mut self,
        broker: &mut Broker,
        runtime: &crate::Runtime,
        id: &str,
    ) -> Result<(), Error> {
        self.require_runtime(runtime)?;
        broker.acknowledge(&mut OriginalAppend(self, Admission::Ack), runtime, id)
    }
    pub fn resolve_original(
        &mut self,
        broker: &mut Broker,
        runtime: &crate::Runtime,
        id: &str,
        key: &str,
    ) -> Result<(), Error> {
        self.require_runtime(runtime)?;
        let (mut query, consumed) = self.original_query(QueryPhase::Resolve, id, key)?;
        if consumed {
            return broker.refresh(self);
        }
        broker.resolve(
            &mut OriginalAppend(self, Admission::Query(key)),
            runtime,
            &mut query,
            id,
        )
    }
    fn check_original(
        db: &Connection,
        record: &Value,
        step: Option<i64>,
        key: Option<&str>,
    ) -> Result<(), Error> {
        let e = &record["event"];
        if e["kind"] == "RESULT" && e["result"] != "UNKNOWN" {
            let cmd = e["command_id"]
                .as_str()
                .ok_or_else(|| invalid("BROKER_SOURCE_COMMAND"))?;
            let mut read=db.prepare("SELECT s.sequence,s.previous,s.input,s.fact_count,s.hash,d.hash,d.admitted_at,r.outcome FROM source_results r JOIN source_steps s ON s.sequence=r.step JOIN protocol_records d ON d.sequence=s.witness JOIN protocol_records i ON i.sequence<d.sequence AND json_extract(i.record,'$.event.kind')='INTENT' AND json_extract(i.record,'$.event.intent.command')=json_extract(s.input,'$[1]') WHERE json_extract(s.input,'$[0]') IN ('COMMAND','NOT_READY') AND json_extract(d.record,'$.event.kind')='DISPATCHED' AND json_extract(d.record,'$.event.command_id')=?1 AND json_extract(s.input,'$[1].command_id')=?1 AND d.sequence<?2").map_err(failed)?;
            let mut rows = read
                .query(params![cmd, record["sequence"].as_i64()])
                .map_err(failed)?;
            let row = rows
                .next()
                .map_err(failed)?
                .ok_or_else(|| invalid("BROKER_SOURCE_COMMAND_RESULT"))?;
            let (seq, prev, input, count, hash, dispatched, admitted, result): (
                i64,
                String,
                String,
                i64,
                String,
                String,
                Option<String>,
                String,
            ) = (
                row.get(0).map_err(failed)?,
                row.get(1).map_err(failed)?,
                row.get(2).map_err(failed)?,
                row.get(3).map_err(failed)?,
                row.get(4).map_err(failed)?,
                row.get(5).map_err(failed)?,
                row.get(6).map_err(failed)?,
                row.get(7).map_err(failed)?,
            );
            if e["result"] != result || rows.next().map_err(failed)?.is_some() {
                return Err(invalid("BROKER_SOURCE_COMMAND_RESULT"));
            }
            let witness = digest(&serde_json::json!([
                digest(&serde_json::json!([dispatched, admitted])),
                result
            ]));
            let mut children=db.prepare("SELECT ordinal,identity,fact,stream_at FROM source_facts WHERE step=?1 ORDER BY ordinal").map_err(failed)?;
            let mut children = children.query([seq]).map_err(failed)?;
            let mut found = 0_i64;
            let mut links = String::new();
            while let Some(child) = children.next().map_err(failed)? {
                let fact = Fact::decode(&decode_source_json(
                    &child.get::<_, String>(2).map_err(failed)?,
                )?)?;
                if child.get::<_, i64>(0).map_err(failed)? != found
                    || child.get::<_, String>(1).map_err(failed)? != fact.identity()
                {
                    return Err(invalid("BROKER_SOURCE_OUTPUT_RELATION"));
                }
                links = source_fact_link(
                    &links,
                    &fact,
                    &decode_source_json(&child.get::<_, String>(3).map_err(failed)?)?,
                );
                found += 1;
            }
            if found != count
                || source_step_digest(
                    &prev,
                    u64::try_from(seq).map_err(failed)?,
                    &decode_source_json(&input)?,
                    u64::try_from(count).map_err(failed)?,
                    &links,
                    Some(&witness),
                ) != hash
            {
                return Err(invalid("BROKER_SOURCE_COMMAND_RESULT"));
            }
        }
        if matches!(e["kind"].as_str(), Some("DISCOVERY" | "RESOLVE")) {
            let q = Query::read(
                db,
                key.ok_or_else(|| invalid("BROKER_SOURCE_ORIGINAL_QUERY_REQUIRED"))?,
            )?;
            if e["kind"] != q.phase.kind()
                || q.protocol.checked_add(1) != record["sequence"].as_i64()
                || Some(q.step) != step
                || e["discovery"] != q.discovery.record()
                || e["command_id"] != e["discovery"]["command"]["command_id"]
            {
                return Err(invalid("BROKER_SOURCE_QUERY_RELATION"));
            }
        } else if key.is_some() {
            return Err(invalid("BROKER_SOURCE_QUERY_RELATION"));
        }
        if e["kind"] == "RESOLVE" {
            for receipt in e["receipts"]
                .as_array()
                .ok_or_else(|| invalid("BROKER_SOURCE_APPLICATION_RECEIPT"))?
            {
                let ack:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM protocol_records WHERE sequence<?1 AND json_extract(record,'$.event.kind')='ACK' AND json_extract(record,'$.event.receipt')=json(?2))",
                    params![record["sequence"].as_i64(),receipt.to_string()],|r|r.get(0)).map_err(failed)?;
                if !ack {
                    return Err(invalid("BROKER_SOURCE_APPLICATION_ACK_REQUIRED"));
                }
            }
        }
        Ok(())
    }
}
impl Journal for BoundBrokerJournal {
    fn records(&self) -> Result<Vec<Record>, Error> {
        let mut db = self.connection(false)?;
        let tx = db.transaction().map_err(failed)?;
        let mut query=tx.prepare("SELECT sequence,hash,record,byte_total,source_step,query_id FROM protocol_records ORDER BY sequence").map_err(failed)?;
        let mut rows = query.query([]).map_err(failed)?;
        let mut records = Vec::new();
        let mut total = 0i64;
        while let Some(row) = rows.next().map_err(failed)? {
            let (seq, hash, raw, size): (i64, String, String, i64) = (
                row.get(0).map_err(failed)?,
                row.get(1).map_err(failed)?,
                row.get(2).map_err(failed)?,
                row.get(3).map_err(failed)?,
            );
            total = total
                .checked_add(i64::try_from(raw.len()).map_err(failed)?)
                .and_then(|n| n.checked_add(1))
                .ok_or_else(|| invalid("BROKER_JOURNAL_LIMIT"))?;
            let record = decode_source_json(&raw)?;
            if i64::try_from(records.len()).map_err(failed)?.checked_add(1) != Some(seq)
                || record["sequence"].as_i64() != Some(seq)
                || record["hash"] != hash
                || size != total
                || u64::try_from(total).map_err(failed)? > super::perpetual_sources::LIMIT
            {
                return Err(invalid("BROKER_SOURCE_PROTOCOL_ROW"));
            }
            let step = row.get(4).map_err(failed)?;
            let query: Option<String> = row.get(5).map_err(failed)?;
            Self::check_original(&tx, &record, step, query.as_deref())?;
            Self::check_observations(&tx, &record["event"], step)?;
            records.push(Record::decode(&record)?);
        }
        Ok(records)
    }
    fn append(&mut self, intent: &AppendIntent) -> Result<(), Error> {
        self.append_record(intent, &Admission::Ordinary)
    }
}
impl BoundBrokerJournal {
    fn append_record(&mut self, intent: &AppendIntent, admission: &Admission) -> Result<(), Error> {
        let mut db = self.connection(true)?;
        let tx = db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(failed)?;
        let record = Record::new(intent).record();
        let event = &record["event"];
        let query = match (event["kind"].as_str(), admission) {
            (Some("INTENT" | "DISPATCHED" | "RESULT"), Admission::Dispatch) => None,
            (Some("INTENT" | "DISPATCHED" | "RESULT"), _) => {
                return Err(invalid("BROKER_SOURCE_RUNTIME_DISPATCH_REQUIRED"));
            }
            (Some("DISCOVERY" | "RESOLVE"), Admission::Query(key)) => Some(*key),
            (Some("DISCOVERY" | "RESOLVE"), _) => {
                return Err(invalid("BROKER_SOURCE_ORIGINAL_QUERY_REQUIRED"));
            }
            (Some("ACK"), Admission::Ack) => None,
            (Some("ACK"), _) => return Err(invalid("BROKER_SOURCE_RUNTIME_ACK_REQUIRED")),
            _ => None,
        };
        let (n,head,bytes)=tx.query_row("SELECT sequence,hash,byte_total FROM protocol_records ORDER BY sequence DESC LIMIT 1",[],|r|Ok((r.get::<_,i64>(0)?,r.get::<_,String>(1)?,r.get::<_,i64>(2)?))).optional().map_err(failed)?.unwrap_or((0,"0".repeat(64),0));
        let next = n
            .checked_add(1)
            .ok_or_else(|| invalid("BROKER_SOURCE_PROTOCOL_PREDECESSOR_OR_LIMIT"))?;
        let raw = record.to_string();
        let total = bytes
            .checked_add(i64::try_from(raw.len()).map_err(failed)?)
            .and_then(|n| n.checked_add(1))
            .ok_or_else(|| invalid("BROKER_JOURNAL_LIMIT"))?;
        if n < 0
            || bytes < 0
            || record["sequence"] != next
            || record["previous"] != head
            || u64::try_from(total).map_err(failed)? > super::perpetual_sources::LIMIT
        {
            return Err(invalid("BROKER_SOURCE_PROTOCOL_PREDECESSOR_OR_LIMIT"));
        }
        Self::check_dispatch(&tx, &record["event"], intent.admitted_at())?;
        let observed = matches!(
            event["kind"].as_str(),
            Some("INGRESS" | "DISCOVERY" | "RESOLVE")
        );
        let step: Option<i64> = if observed {
            tx.query_row("SELECT MAX(sequence) FROM source_steps", [], |r| r.get(0))
                .map_err(failed)?
        } else {
            None
        };
        Self::check_original(&tx, &record, step, query)?;
        Self::check_observations(&tx, event, step)?;
        if observed && step.is_none() {
            return Err(invalid("BROKER_SOURCE_ORIGINAL_FACT_REQUIRED"));
        }
        if event["kind"] == "INGRESS" {
            let latest:String=tx.query_row("SELECT input FROM source_steps WHERE json_extract(input,'$[0]') IN ('CLOCK','BAR') ORDER BY sequence DESC LIMIT 1",[],|r|r.get(0)).map_err(failed)?;
            let clock = decode_source_json(&latest)?;
            let scope = Scope::decode(&record["scope"])?;
            for v in event["facts"]
                .as_array()
                .ok_or_else(|| invalid("BROKER_SOURCE_FACTS"))?
            {
                let f = Fact::decode(v)?;
                let at: String = tx
                    .query_row(
                        "SELECT stream_at FROM source_facts WHERE identity=?1",
                        [f.identity()],
                        |r| r.get(0),
                    )
                    .map_err(failed)?;
                onlyalpha_broker::source::check_admission_clock(
                    &scope,
                    &clock,
                    &decode_source_json(&at)?,
                )
                .map_err(|_| invalid("BROKER_SOURCE_PUBLICATION_NOT_DUE"))?;
            }
        }
        tx.execute(
            "INSERT INTO protocol_records VALUES(?1,?2,?3,?4,?5,?6,?7)",
            params![
                next,
                record["hash"].as_str(),
                raw,
                total,
                intent.admitted_at().map(Value::to_string),
                step,
                query
            ],
        )
        .map_err(failed)?;
        if observed {
            let children = if event["kind"] == "INGRESS" {
                &event["facts"]
            } else {
                &event["discovery"]["facts"]
            };
            let mut index = tx
                .prepare(
                    "INSERT INTO protocol_ingress VALUES(?1,?2) ON CONFLICT(identity) DO NOTHING",
                )
                .map_err(failed)?;
            for raw in children
                .as_array()
                .ok_or_else(|| invalid("BROKER_SOURCE_FACTS"))?
            {
                index
                    .execute(params![Fact::decode(raw)?.identity(), next])
                    .map_err(failed)?;
            }
        }
        tx.commit().map_err(failed)
    }
}
