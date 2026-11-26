use crate::{Error, err};
use onlyalpha_domain::base::OnlyDomainModel;
use onlyalpha_execution::{CommitIntent, Components, Prepared, Record, Store, coordinate, recover};
use serde_json::Value;

#[derive(Clone)]
struct Memory {
    records: Vec<Record>,
}
impl Store for Memory {
    fn head(&self) -> Result<u64, Error> {
        Ok(self.records.len() as u64)
    }
    fn get(&self, n: u64) -> Result<Option<Record>, Error> {
        if n == 0 {
            return Err(err("SEQUENCE"));
        }
        Ok(self
            .records
            .get(usize::try_from(n - 1).map_err(|_| err("BOUND"))?)
            .map(Record::compact_snapshot))
    }
    fn commit(&mut self, i: &CommitIntent) -> Result<Record, Error> {
        let n = i.prepared().sequence();
        if let Some(r) = self.get(n)? {
            if r.prepared() != i.prepared() {
                return Err(err("CANDIDATE_CONFLICT"));
            }
            return Ok(r);
        }
        if n != self.head()? + 1 || self.records.last().is_some_and(|r| !r.ready()) {
            return Err(err("CANDIDATE_PREDECESSOR"));
        }
        let r = Record::new(i);
        self.records.push(r.clone());
        Ok(r)
    }
    fn mark_ready(&mut self, n: u64) -> Result<(), Error> {
        let i = usize::try_from(n.checked_sub(1).ok_or_else(|| err("SEQUENCE"))?)
            .map_err(|_| err("BOUND"))?;
        let r = self.records.get(i).ok_or_else(|| err("MISSING"))?;
        self.records[i] = r.observation_snapshot(true, r.delivered())?;
        Ok(())
    }
    fn acknowledge(&mut self, _: u64) -> Result<(), Error> {
        Err(err("CANDIDATE_CANNOT_DELIVER"))
    }
}

/// Rebuildable isolated Kernel preflight, never a durable writer or dispatch permission.
pub struct Candidate {
    components: Components,
    store: Memory,
    configuration: Value,
    plans: Vec<Prepared>,
}
impl Candidate {
    pub(crate) fn new(configuration: Value, records: Vec<Record>) -> Result<Self, Error> {
        let mut store = Memory { records };
        let mut components = Components::new(configuration.clone())?;
        recover(&mut store, &mut components)?;
        Ok(Self {
            components,
            store,
            configuration,
            plans: Vec::new(),
        })
    }
    pub fn apply(&mut self, input: &Value) -> Result<(), Error> {
        if self.plans.len() >= 512 {
            return Err(err("INPUTS"));
        }
        if let Some(previous) = self.plans.last_mut() {
            *previous = previous.compact_clone();
        }
        let p = self.components.prepare(&self.store, input)?;
        coordinate(&mut self.store, &mut self.components, &p)?;
        self.plans.push(p);
        Ok(())
    }
    pub fn state(&self) -> Result<Value, Error> {
        self.components.state(&self.store)
    }
    pub(crate) fn position_order_view(&self) -> Result<Value, Error> {
        self.components.position_order_view(&self.store)
    }
    pub fn checkpoint(&self) -> Result<Value, Error> {
        self.components.checkpoint()
    }
    pub fn fee_order_preview(
        &self,
        cluster: &str,
        request: &Value,
        at: u64,
    ) -> Result<Value, Error> {
        Ok(self
            .components
            .fee_order_preview(&self.store, cluster, request, at)?
            .to_record())
    }
    pub fn configuration(&self) -> &Value {
        &self.configuration
    }
    pub fn records(&self) -> &[Record] {
        &self.store.records
    }
    pub fn order(&self, cluster: &str, order: &str) -> Result<Value, Error> {
        Ok(self
            .components
            .order_snapshot(&self.store, cluster, order)?
            .to_record())
    }
}
