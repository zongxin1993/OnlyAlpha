//! 同一显式永续 Run 的只读行情原件和原 Broker Journal。
use onlyalpha_broker::{AppendIntent, Broker, Error as BrokerError, Journal, Record, Scope};
use onlyalpha_execution::{Components, Error, MarketSourceCut, Prepared};
use serde_json::{Value, json};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
};

pub(crate) const LIMIT: u64 = 32 * 1024 * 1024;
fn failed(e: impl std::fmt::Display) -> Error {
    Error(format!("RUNTIME_PERPETUAL_EVIDENCE: {e}"))
}
fn broker_error(e: impl std::fmt::Display) -> BrokerError {
    BrokerError::new(&format!("BROKER_JOURNAL_IO: {e}"))
}
fn read(path: &Path) -> Result<Vec<u8>, Error> {
    if !fs::symlink_metadata(path).map_err(failed)?.is_file() {
        return Err(failed("original is not a regular file"));
    }
    let mut bytes = Vec::new();
    File::open(path)
        .map_err(failed)?
        .take(LIMIT + 1)
        .read_to_end(&mut bytes)
        .map_err(failed)?;
    if bytes.len() as u64 > LIMIT {
        return Err(failed("original size"));
    }
    Ok(bytes)
}
/// 原 Broker 拥有的串行 Journal。只接纳 Broker 已验证的 AppendIntent。
pub struct BrokerJournal {
    root: PathBuf,
}
impl BrokerJournal {
    pub fn create(root: &Path) -> Result<Self, BrokerError> {
        let root = root.canonicalize().map_err(broker_error)?;
        File::create_new(root.join("broker.jsonl"))
            .and_then(|f| f.sync_all())
            .map_err(broker_error)?;
        File::open(&root)
            .and_then(|f| f.sync_all())
            .map_err(broker_error)?;
        Ok(Self { root })
    }
    pub fn open(root: &Path) -> Result<Self, BrokerError> {
        let journal = Self {
            root: root.canonicalize().map_err(broker_error)?,
        };
        journal.records()?;
        Ok(journal)
    }
}
impl Journal for BrokerJournal {
    fn records(&self) -> Result<Vec<Record>, BrokerError> {
        let bytes = read(&self.root.join("broker.jsonl")).map_err(broker_error)?;
        if !bytes.is_empty() && !bytes.ends_with(b"\n") {
            return Err(broker_error("incomplete record"));
        }
        std::str::from_utf8(&bytes)
            .map_err(broker_error)?
            .lines()
            .map(|line| Record::decode(&serde_json::from_str(line).map_err(broker_error)?))
            .collect()
    }
    fn append(&mut self, intent: &AppendIntent) -> Result<(), BrokerError> {
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(self.root.join("broker.lock"))
            .map_err(broker_error)?;
        lock.try_lock().map_err(broker_error)?;
        let records = self.records()?;
        let next = Record::new(intent).record();
        let last = records
            .last()
            .map(|r| r.record()["hash"].clone())
            .unwrap_or_else(|| json!("0".repeat(64)));
        if next["sequence"] != records.len() + 1 || next["previous"] != last {
            return Err(broker_error("journal predecessor"));
        }
        let path = self.root.join("broker.jsonl");
        let mut bytes = read(&path).map_err(broker_error)?;
        serde_json::to_writer(&mut bytes, &next).map_err(broker_error)?;
        bytes.push(b'\n');
        if bytes.len() as u64 > LIMIT {
            return Err(broker_error("journal limit"));
        }
        let tmp = self.root.join("broker.jsonl.pending");
        // 固定暂存文件只在持有原 Journal 锁时处置，崩溃残留没有写入资格。
        if tmp.exists() {
            fs::remove_file(&tmp).map_err(broker_error)?;
        }
        let mut f = File::create_new(&tmp).map_err(broker_error)?;
        f.write_all(&bytes)
            .and_then(|_| f.sync_all())
            .map_err(broker_error)?;
        fs::rename(tmp, path).map_err(broker_error)?;
        File::open(&self.root)
            .and_then(|f| f.sync_all())
            .map_err(broker_error)
    }
}
pub(crate) fn prepare(
    root: &Path,
    cfg: &Value,
    owners: &Components,
    prefix: &crate::store::Replay,
    input: &Value,
) -> Result<Prepared, Error> {
    if cfg["schema_version"] != 3 {
        return owners.prepare(prefix, input);
    }
    let terms = &cfg["perpetual"];
    let cut = MarketSourceCut::read(
        &read(&root.join("market-source-cut.json"))?,
        terms["source_cut_sha256"]
            .as_str()
            .ok_or_else(|| failed("missing source cut"))?,
    )
    .map_err(failed)?;
    let mut scope = json!({});
    for k in [
        "engine",
        "runtime",
        "gateway",
        "account",
        "generation",
        "runtime_kind",
    ] {
        scope[k] = cfg[k].clone();
    }
    let scope = Scope::decode(&scope).map_err(failed)?;
    let binding = terms["execution_source_binding"]
        .as_str()
        .ok_or_else(|| failed("execution source binding"))?;
    let journal = crate::BoundBrokerJournal::open(root, binding).map_err(failed)?;
    let broker = Broker::recover(scope.clone(), &journal, 65536).map_err(failed)?;
    let source = if input["op"] == "FUNDING" {
        let boundary = onlyalpha_execution::funding_boundary(&input["payload"]["fact"])?;
        let visible = input["time"]
            .as_u64()
            .ok_or_else(|| failed("funding visibility"))?;
        Some(
            journal
                .history(scope, Some((boundary, visible)))
                .map_err(failed)?,
        )
    } else {
        None
    };
    if let Some(source) = source {
        let draft = onlyalpha_execution::ProjectionData::new(owners, prefix.records())
            .evaluate_funding(input, &cut, &broker, &source)?;
        return Prepared::decode(&serde_json::to_vec(draft.value())?);
    }
    if prefix.has_funding() {
        return onlyalpha_execution::ProjectionData::new(owners, prefix.records())
            .evaluate_perpetual(input, &cut, &broker);
    }
    owners.prepare_perpetual(prefix, input, &cut, &broker)
}

use onlyalpha_broker as broker;
fn owned_order(runtime: &crate::Runtime, order: &str) -> Result<Value, broker::Error> {
    let (components, _) = runtime.fork_ready().map_err(unavailable)?;
    let cp = components.checkpoint().map_err(unavailable)?;
    let rows = cp["components"][0]["state"]["orders"]
        .as_array()
        .ok_or_else(|| unavailable("orders"))?;
    rows.iter()
        .find(|r| r["snapshot"]["order_id"]["value"] == order)
        .cloned()
        .ok_or_else(|| unavailable("order"))
}

fn unavailable(_: impl std::fmt::Display) -> broker::Error {
    broker::Error::new("READY_ORDER_EVIDENCE_UNAVAILABLE")
}
fn require_perpetual_reader(runtime: &crate::Runtime) -> Result<(), broker::Error> {
    let cfg = &runtime.store.identity()["configuration"];
    if cfg["schema_version"] != 3 || cfg["runtime_kind"] != "BACKTEST" {
        return Err(unavailable("explicit perpetual BACKTEST required"));
    }
    runtime.require_healthy().map_err(unavailable)
}
// 查询和派发均从本 Run 原 Ready ADMIT 取得范围与完整请求。
fn ready_order_source(
    runtime: &crate::Runtime,
    command: &broker::BrokerCommand,
) -> Result<(onlyalpha_execution::Record, Value), broker::Error> {
    let original = runtime
        .records()
        .map_err(unavailable)?
        .into_iter()
        .find(|r| {
            r.prepared().input()["op"] == "ADMIT"
                && r.prepared().input()["payload"]["order"] == command.order()
        })
        .ok_or_else(|| unavailable("admission"))?;
    let input = original.prepared().input();
    let scope = command.scope().record();
    if [
        "engine",
        "runtime",
        "account",
        "gateway",
        "generation",
        "runtime_kind",
    ]
    .iter()
    .any(|key| scope[*key] != input[*key])
    {
        return Err(unavailable("scope"));
    }
    let request = &command.record()["request"];
    match command.operation() {
        broker::Operation::Submit if *request != input["payload"]["request"] => {
            return Err(unavailable("submit request"));
        }
        broker::Operation::Cancel if request["order_id"]["value"] != command.order() => {
            return Err(unavailable("cancel order"));
        }
        _ => {}
    }
    let row = owned_order(runtime, command.order())?;
    if row["snapshot"]["client_order_id"]["value"] != command.client()
        || row["snapshot"]["order_id"]["value"] != command.order()
    {
        return Err(unavailable("order"));
    }
    Ok((original, row))
}
impl broker::RuntimeReader for crate::Runtime {
    fn ready_intent(
        &self,
        command: &broker::BrokerCommand,
    ) -> Result<broker::ReadyIntent, broker::Error> {
        require_perpetual_reader(self)?;
        let (original, row) = ready_order_source(self, command)?;
        if command.operation() != broker::Operation::Submit
            || row["snapshot"]["status"] != "SUBMITTED"
            || row["submission"] != "DISPATCHING"
        {
            return Err(unavailable("dispatch state"));
        }
        broker::ReadyIntent::new(
            command.clone(),
            original.prepared().id().into(),
            original.prepared().record()["payload_hash"]
                .as_str()
                .ok_or_else(|| unavailable("payload_hash"))?
                .into(),
        )?
        .at_admission(&original.prepared().input()["time"])
    }
    fn application_receipt(
        &self,
        fact: &broker::Fact,
    ) -> Result<Option<broker::ApplicationReceipt>, broker::Error> {
        require_perpetual_reader(self)?;
        for record in self.records().map_err(unavailable)? {
            let p = record.prepared();
            let proof = &p.input()["payload"]["broker"];
            if proof["id"] == fact.identity() {
                if proof["record"] != fact.record() || proof["fingerprint"] != fact.fingerprint() {
                    return Err(unavailable("original fact"));
                }
                return broker::ApplicationReceipt::new(
                    fact,
                    p.id().into(),
                    p.record()["payload_hash"]
                        .as_str()
                        .ok_or_else(|| unavailable("payload_hash"))?
                        .into(),
                    broker::ApplicationStatus::Applied,
                )
                .map(Some);
            }
        }
        Ok(None)
    }
    fn order_view(
        &self,
        c: &broker::BrokerCommand,
    ) -> Result<Option<broker::OrderView>, broker::Error> {
        require_perpetual_reader(self)?;
        let (original, row) = ready_order_source(self, c)?;
        let input = original.prepared().input();
        let mut scope = json!({});
        for key in [
            "engine",
            "runtime",
            "account",
            "gateway",
            "generation",
            "runtime_kind",
        ] {
            scope[key] = input[key].clone();
        }
        let s = &row["snapshot"];
        if s["venue_order_id"].is_null() {
            return Ok(None);
        }
        broker::OrderView::decode(
            &json!({"scope":scope,"order":s["order_id"]["value"],"client":s["client_order_id"]["value"],
            "venue":s["venue_order_id"]["value"],"request":input["payload"]["request"],
            "filled":s["filled_quantity"]["value"],"status":s["status"]}),
        )
        .map(Some)
    }
}
