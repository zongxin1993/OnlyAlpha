use crate::{Components, Prepared, model::*};
use serde_json::{Value, json};
/// Opaque persistence capability, created only after canonical coordinator admission.
/// Decoded derived payloads cannot manufacture a new writer authority.
/// ```compile_fail
/// use onlyalpha_execution::{CommitIntent, Prepared};
/// fn forge(prepared: Prepared) -> CommitIntent { CommitIntent { prepared } }
/// ```
pub struct CommitIntent {
    prepared: Prepared,
}
impl CommitIntent {
    pub fn prepared(&self) -> &Prepared {
        &self.prepared
    }
}

/// The sole durable transaction record. Drivers must atomically commit Prepared plus pending Events.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Record {
    prepared: Prepared,
    ready: bool,
    delivered: bool,
}
impl Record {
    pub fn new(intent: &CommitIntent) -> Self {
        Self {
            prepared: intent.prepared.clone(),
            ready: false,
            delivered: false,
        }
    }
    pub fn prepared(&self) -> &Prepared {
        &self.prepared
    }
    pub fn ready(&self) -> bool {
        self.ready
    }
    pub fn record(&self) -> Value {
        json!({"schema_version":1,"prepared":self.prepared.record(),"ready":self.ready,"delivered":self.delivered})
    }
    pub fn decode(v: &Value) -> Result<Self, Error> {
        row(v, &["prepared", "ready", "delivered"])?;
        let ready = v["ready"]
            .as_bool()
            .ok_or_else(|| err("EXECUTION_READY_TYPE"))?;
        let delivered = v["delivered"]
            .as_bool()
            .ok_or_else(|| err("EXECUTION_DELIVERY_TYPE"))?;
        if delivered && !ready {
            return Err(err("EXECUTION_DELIVERY_BEFORE_READY"));
        }
        Ok(Self {
            prepared: Prepared::decode(&serde_json::to_vec(&v["prepared"])?)?,
            ready,
            delivered,
        })
    }
}
/// A scoped, serialized owning Store boundary; implementations must retain immutable exact payloads.
/// Same input identity and exact payload is idempotent; any changed scope/payload is a conflict.
/// Commit assigns the exact contiguous sequence and atomically persists Events, initially hidden.
/// Errors may be UNKNOWN after persistence: callers query/recover and never create a second identity.
pub trait Store {
    fn head(&self) -> Result<u64, Error>;
    fn commit(&mut self, intent: &CommitIntent) -> Result<Record, Error>;
    fn get(&self, sequence: u64) -> Result<Option<Record>, Error>;
    fn mark_ready(&mut self, sequence: u64) -> Result<(), Error>;
    fn acknowledge(&mut self, sequence: u64) -> Result<(), Error>;
}
fn resume<S: Store>(store: &mut S, c: &mut Components, record: Record) -> Result<(), Error> {
    let p = record.prepared();
    let observed = store
        .get(p.sequence())?
        .ok_or_else(|| err("EXECUTION_COMMIT_NOT_OBSERVABLE"))?;
    if observed != record {
        return Err(err("EXECUTION_STORE_PAYLOAD_CONFLICT"));
    }
    if p.sequence() > 1 {
        let previous = store
            .get(p.sequence() - 1)?
            .ok_or_else(|| err("EXECUTION_PREDECESSOR_MISSING"))?;
        if !previous.ready() {
            return Err(err("EXECUTION_PREDECESSOR_UNREADY"));
        }
    }
    Components::ready_prefix(store, &c.config, p.sequence() - 1)?;
    if c.sequence >= p.sequence() {
        c.ready_source(store)?;
        if c.meta["transactions"][p.sequence().to_string()] != p.id() {
            return Err(err("EXECUTION_APPLIED_IDENTITY_CONFLICT"));
        }
        if !record.ready() {
            return Err(err("EXECUTION_LOCAL_AHEAD_OF_STORE"));
        }
        return Ok(());
    }
    if c.pending.is_none() {
        c.pending = Some((p.id().into(), 0));
    }
    for i in 0..p.projection_count() {
        c.install_projection(store, p, i)?;
    }
    if !record.ready() {
        store.mark_ready(p.sequence())?;
    }
    let ready = store
        .get(p.sequence())?
        .ok_or_else(|| err("EXECUTION_READY_MISSING"))?;
    if !ready.ready() || ready.prepared() != p {
        return Err(err("EXECUTION_READY_NOT_OBSERVABLE"));
    }
    c.complete(store, p)
}
/// Commit never mutates components until the exact durable record can be queried.
pub fn coordinate<S: Store>(store: &mut S, c: &mut Components, p: &Prepared) -> Result<(), Error> {
    p.validate()?;
    if p.value["config_hash"] != hash(&c.config) {
        return Err(err("EXECUTION_CONTEXT"));
    }
    let existing = store.get(p.sequence())?;
    if let Some(record) = existing {
        if record.prepared() != p {
            return Err(err("EXECUTION_COMMIT_PAYLOAD_CONFLICT"));
        }
        return resume(store, c, record);
    }
    if !p.planned {
        return Err(err("EXECUTION_PLANNER_AUTHORITY_REQUIRED"));
    }
    c.ready_source(store)?;
    if p.value["predecessor"] != c.sequence {
        return Err(err("EXECUTION_PREDECESSOR_UNAPPLIED"));
    }
    for (i, value) in c.payloads()?.iter().enumerate() {
        if p.value["projections"][i]["before_hash"] != hash(value) {
            return Err(err("EXECUTION_BEFORE_SOURCE_CONFLICT"));
        }
    }
    let intent = CommitIntent {
        prepared: p.clone(),
    };
    let record = store.commit(&intent)?;
    if record.prepared() != p {
        return Err(err("EXECUTION_COMMIT_PAYLOAD_CONFLICT"));
    }
    resume(store, c, record)
}
/// Rehydrate Ready history and forward-recover the unfinished tail from immutable committed payloads.
pub fn recover<S: Store>(store: &mut S, c: &mut Components) -> Result<(), Error> {
    let head = store.head()?;
    if c.sequence > head {
        return Err(err("EXECUTION_CHECKPOINT_AHEAD_OF_STORE"));
    }
    while c.sequence < head {
        let next = c
            .sequence
            .checked_add(1)
            .ok_or_else(|| err("EXECUTION_SEQUENCE_OVERFLOW"))?;
        let record = store
            .get(next)?
            .ok_or_else(|| err("EXECUTION_COMMITTED_SEQUENCE_GAP"))?;
        if record.prepared().sequence() != next {
            return Err(err("EXECUTION_STORE_SEQUENCE"));
        }
        resume(store, c, record)?;
    }
    if c.pending.is_some() {
        return Err(err("EXECUTION_PENDING_WITHOUT_COMMIT"));
    }
    c.ready_source(store)
}
/// Diagnostic/outbox read: only Ready records expose their stable Events. Delivery is at least once.
pub fn pending_events<S: Store>(store: &S, c: &Components) -> Result<Vec<Value>, Error> {
    let mut result = vec![];
    let mut ready_count = 0;
    for sequence in 1..=store.head()? {
        let record = store
            .get(sequence)?
            .ok_or_else(|| err("EXECUTION_COMMITTED_SEQUENCE_GAP"))?;
        if record.prepared().sequence() != sequence {
            return Err(err("EXECUTION_STORE_SEQUENCE"));
        }
        if !record.ready() {
            break;
        }
        ready_count = sequence;
        if !record.delivered {
            result.extend(
                record
                    .prepared()
                    .events()
                    .as_array()
                    .expect("validated")
                    .iter()
                    .cloned(),
            );
        }
    }
    Components::ready_prefix(store, &c.config, ready_count)?;
    Ok(result)
}
