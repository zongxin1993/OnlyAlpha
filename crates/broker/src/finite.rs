//! Exclusive finite protocol work; no Journal or durable dispatch token escapes.
use crate::*;
use serde_json::Value;
struct NoJournal;
impl Journal for NoJournal {
    fn records(&self) -> Result<Vec<Record>, Error> {
        Err(Error::new("FINITE_NO_JOURNAL"))
    }
    fn append(&mut self, _: &AppendIntent) -> Result<(), Error> {
        Err(Error::new("FINITE_NO_JOURNAL"))
    }
}
struct Reader<'a, T: FiniteRuntimeReader>(&'a T);
impl<T: FiniteRuntimeReader> RuntimeReader for Reader<'_, T> {
    fn ready_intent(&self, c: &BrokerCommand) -> Result<ReadyIntent, Error> {
        Ok(self.0.simulation_intent(c)?.0)
    }
    fn application_receipt(&self, f: &Fact) -> Result<Option<ApplicationReceipt>, Error> {
        self.0.simulation_receipt(f)
    }
    fn order_view(&self, c: &BrokerCommand) -> Result<Option<OrderView>, Error> {
        self.0.simulation_order(c)
    }
}
pub struct MemoryBroker {
    broker: Broker,
    source_binding: String,
}
/// Actual finite protocol drain, never a durable receipt.
pub struct CompletedMemoryBroker {
    summary: Value,
    records: Vec<Record>,
}
impl CompletedMemoryBroker {
    pub fn summary(&self) -> &Value {
        &self.summary
    }
    pub fn records(&self) -> &[Record] {
        &self.records
    }
}
impl MemoryBroker {
    pub fn new(
        scope: Scope,
        binding: &Value,
        expected: &str,
        capacity: usize,
    ) -> Result<Self, Error> {
        if crate::digest(binding) != expected || binding["scope"] != scope.record() {
            return Err(Error::new("BROKER_SOURCE_GENESIS"));
        }
        Ok(Self {
            broker: Broker::finite(scope, capacity)?,
            source_binding: expected.into(),
        })
    }
    pub fn source_binding(&self) -> &str {
        &self.source_binding
    }
    pub fn original(&self) -> &Broker {
        &self.broker
    }
    pub fn pending(&self) -> &[Fact] {
        self.broker.pending()
    }
    pub fn set_connection(&mut self, c: Connection) {
        self.broker.set_connection(c);
    }
    pub fn set_health(&mut self, account: bool, discovery: bool, stream: bool) {
        self.broker.set_health(account, discovery, stream);
    }
    pub fn dispatch(
        &mut self,
        runtime: &impl FiniteRuntimeReader,
        port: &mut impl TradingPort,
        command: &BrokerCommand,
    ) -> Result<CommandState, Error> {
        self.broker
            .dispatch(&mut NoJournal, &Reader(runtime), port, command)
    }
    pub fn ingest(&mut self, facts: &[Fact]) -> Result<(), Error> {
        self.broker.ingest(&mut NoJournal, facts)
    }
    pub fn acknowledge(
        &mut self,
        runtime: &impl FiniteRuntimeReader,
        id: &str,
    ) -> Result<(), Error> {
        self.broker
            .acknowledge(&mut NoJournal, &Reader(runtime), id)
    }
    pub fn finish(self) -> Result<CompletedMemoryBroker, Error> {
        let summary = self.broker.finite_summary()?;
        Ok(CompletedMemoryBroker {
            summary,
            records: self.broker.into_finite_records(),
        })
    }
}
