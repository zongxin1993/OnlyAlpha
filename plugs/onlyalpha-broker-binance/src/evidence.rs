use super::*;
use onlyalpha_broker::{Journal, Operation, Record, digest};
use sha2::{Digest, Sha256};
use std::cell::RefCell;

/// 宿主按 binding 串行追加。append 须原子核对期望前缀，错误可能已经写入，read 应读到提交后的确切字节。
pub trait ObservationStore {
    fn len(&self, binding: &str) -> Result<u64>;
    fn read(&self, binding: &str, sequence: u64) -> Result<Observation>;
    fn append(&self, record: &Observation) -> Result<()>;
}
/// 不含请求头、签名和密钥。bytes 是场所响应或事件原文，action 仅含路由、公开参数和原命令关联。
#[derive(Clone, PartialEq, Eq)]
pub struct Observation {
    pub binding: String,
    pub sequence: u64,
    pub previous: String,
    pub action: Value,
    pub status: u16,
    pub at_ns: i64,
    pub bytes: Vec<u8>,
    pub hash: String,
}
impl Observation {
    fn checksum(&self) -> String {
        digest(&json!([
            self.binding,
            self.sequence,
            self.previous,
            self.action,
            self.status,
            self.at_ns,
            hex(&Sha256::digest(&self.bytes))
        ]))
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Checkpoint {
    pub binding: String,
    pub journal_length: u64,
    pub journal_hash: String,
    pub observation_length: u64,
    pub observation_hash: String,
}
pub(crate) struct Evidence {
    pub(crate) binding: String,
    pub(crate) store: Box<dyn ObservationStore>,
    head: RefCell<(u64, String)>,
}
impl Evidence {
    pub(crate) fn open(c: &Config, store: Box<dyn ObservationStore>) -> Self {
        Self {
            binding: c.fingerprint(),
            store,
            head: RefCell::new((0, "0".repeat(64))),
        }
    }
    pub(crate) fn head(&self) -> (u64, String) {
        self.head.borrow().clone()
    }
    pub(crate) fn verify(
        &self,
        record: &Observation,
        n: u64,
        previous: &str,
        max: usize,
    ) -> Result<()> {
        if record.binding != self.binding
            || record.sequence
                != n.checked_add(1)
                    .ok_or_else(|| err("BINANCE_EVIDENCE_OVERFLOW"))?
            || record.previous != previous
            || record.bytes.len() > max
            || record.at_ns < 0
            || record.hash != record.checksum()
        {
            return Err(err("BINANCE_EVIDENCE_PREFIX"));
        }
        Ok(())
    }
    pub(crate) fn replay(&self, record: &Observation, max: usize) -> Result<()> {
        let (n, previous) = self.head();
        self.verify(record, n, &previous, max)?;
        self.head.replace((record.sequence, record.hash.clone()));
        Ok(())
    }
    pub(crate) fn append(
        &self,
        action: Value,
        status: u16,
        at_ns: i64,
        bytes: Vec<u8>,
        max: usize,
    ) -> Result<Observation> {
        let (n, previous) = self.head();
        if self.store.len(&self.binding)? != n || at_ns < 0 || bytes.len() > max {
            return Err(err("BINANCE_EVIDENCE_PREFIX"));
        }
        let mut record = Observation {
            binding: self.binding.clone(),
            sequence: n
                .checked_add(1)
                .ok_or_else(|| err("BINANCE_EVIDENCE_OVERFLOW"))?,
            previous,
            action,
            status,
            at_ns,
            bytes,
            hash: String::new(),
        };
        record.hash = record.checksum();
        self.store.append(&record)?;
        if self.store.read(&self.binding, record.sequence)? != record {
            return Err(err("BINANCE_EVIDENCE_WRITE_UNKNOWN"));
        }
        self.replay(&record, max)?;
        Ok(record)
    }
}
pub(crate) fn journal_head(history: &[Record], length: u64) -> Result<String> {
    if length == 0 {
        return Ok("0".repeat(64));
    }
    history
        .get(usize::try_from(length - 1).map_err(|_| err("BINANCE_CHECKPOINT"))?)
        .and_then(|r| r.record()["hash"].as_str().map(str::to_owned))
        .ok_or_else(|| err("BINANCE_CHECKPOINT"))
}
#[derive(Default)]
pub(crate) struct Orders {
    pub(crate) submits: BTreeMap<String, BrokerCommand>,
    pub(crate) cancels: BTreeMap<String, BrokerCommand>,
    pub(crate) venues: BTreeMap<String, u64>,
    wire: BTreeMap<String, String>,
    dispatch_sequence: BTreeMap<String, u64>,
}
impl Orders {
    pub(crate) fn load(&mut self, journal: &impl Journal, scope: &Scope) -> Result<()> {
        for record in journal.records()? {
            let value = record.record();
            if value["scope"] != scope.record() {
                return Err(err("BINANCE_JOURNAL_SCOPE"));
            }
            match value["event"]["kind"].as_str() {
                Some("INTENT") => self.register(&BrokerCommand::decode(
                    &value["event"]["intent"]["command"],
                )?)?,
                Some("DISPATCHED") => {
                    let id = value["event"]["command_id"]
                        .as_str()
                        .ok_or_else(|| err("BINANCE_JOURNAL_COMMAND"))?;
                    let sequence = value["sequence"]
                        .as_u64()
                        .ok_or_else(|| err("BINANCE_JOURNAL_COMMAND"))?;
                    self.dispatch_sequence.insert(id.into(), sequence);
                }
                _ => (),
            }
        }
        Ok(())
    }
    pub(crate) fn check(&self, c: &BrokerCommand) -> Result<()> {
        let wire = if c.operation() == Operation::Submit {
            wire_client(c.client())
        } else {
            cancel_client(c)
        };
        if self.wire.get(&wire).is_some_and(|old| old != c.id()) {
            return Err(err("BINANCE_CLIENT_COLLISION"));
        }
        if c.operation() == Operation::Cancel {
            let sub = self.original(c)?;
            if sub.scope() != c.scope() || sub.client() != c.client() {
                return Err(err("BINANCE_CANCEL_IDENTITY"));
            }
        }
        Ok(())
    }
    pub(crate) fn register(&mut self, c: &BrokerCommand) -> Result<()> {
        self.check(c)?;
        match c.operation() {
            Operation::Submit => {
                self.wire.insert(wire_client(c.client()), c.id().into());
                self.submits.insert(c.order().into(), c.clone());
            }
            Operation::Cancel => {
                self.wire.insert(cancel_client(c), c.id().into());
                self.cancels.insert(c.id().into(), c.clone());
            }
        }
        Ok(())
    }
    pub(crate) fn original(&self, c: &BrokerCommand) -> Result<&BrokerCommand> {
        self.submits
            .get(c.order())
            .filter(|sub| sub.scope() == c.scope() && sub.client() == c.client())
            .ok_or_else(|| err("BINANCE_ORDER_MISSING"))
    }
    pub(crate) fn dispatched_at(&self, id: &str, cut: u64) -> bool {
        self.dispatch_sequence.get(id).is_some_and(|n| *n <= cut)
    }
    pub(crate) fn by_wire(&self, wire: &str, cut: u64) -> Result<&BrokerCommand> {
        let key = self
            .wire
            .get(wire)
            .ok_or_else(|| err("BINANCE_FOREIGN_ORDER"))?;
        if !self.dispatched_at(key, cut) {
            return Err(err("BINANCE_UNDISPATCHED_ORDER"));
        }
        self.submits
            .values()
            .find(|c| c.id() == key)
            .or_else(|| {
                self.cancels
                    .get(key)
                    .and_then(|c| self.submits.get(c.order()))
            })
            .filter(|c| self.dispatched_at(c.id(), cut))
            .ok_or_else(|| err("BINANCE_ORDER_MISSING"))
    }
    pub(crate) fn clients(&self, c: &BrokerCommand) -> Vec<String> {
        std::iter::once(wire_client(c.client()))
            .chain(
                self.cancels
                    .values()
                    .filter(|k| k.order() == c.order() && self.dispatched_at(k.id(), u64::MAX))
                    .map(cancel_client),
            )
            .collect()
    }
    pub(crate) fn bind(&mut self, c: &BrokerCommand, num: u64) -> Result<()> {
        let sym = symbol(c)?;
        if self.venues.get(c.order()).is_some_and(|old| *old != num)
            || self.venues.iter().any(|(order, v)| {
                *v == num
                    && order != c.order()
                    && self
                        .submits
                        .get(order)
                        .and_then(|s| symbol(s).ok())
                        .as_ref()
                        == Some(&sym)
            })
        {
            return Err(err("BINANCE_VENUE_IDENTITY_CONFLICT"));
        }
        self.venues.insert(c.order().into(), num);
        Ok(())
    }
}
