use super::{authority_session::AuthoritySession, postgres};
use onlyalpha_broker::{
    AccountPort, AppendIntent, Broker, BrokerCommand, Capabilities, CommandState, ConnectionPort,
    DispatchObservation, DispatchResult, Error, Journal, PositionPort, ReadyIntent, Record,
    RuntimeReader, Scope, Snapshot, TradingPort, digest, source::decode_source_json,
};
use onlyalpha_broker_virtual::VirtualBroker;
use onlyalpha_domain::{market::OnlyBar, value::OnlyMoney};
use onlyalpha_runtime::durability::TradingBinding;
use serde_json::{Value, json};
use std::{cell::RefCell, collections::BTreeMap, rc::Rc};
use tokio::sync::{mpsc, oneshot};
use tokio_postgres::Transaction;

type Result<T> = std::result::Result<T, Error>;
fn genesis_previous() -> String { "0".repeat(64) }
fn conflict() -> Error { Error::new("SIM_VENUE_HISTORY_CONFLICT") }
fn unavailable() -> Error { Error::new("SIM_VENUE_UNAVAILABLE") }

fn check_scope(binding: &TradingBinding, scope: &Value) -> Result<()> {
    let config = binding.configuration().record();
    if scope["runtime_kind"] != "SIM" || ["engine", "runtime", "gateway", "account", "generation", "runtime_kind"]
        .iter().any(|key| scope[*key] != config[*key]) {
        return Err(conflict());
    }
    Ok(())
}

fn document(key: &str, sequence: i64, previous: &str, kind: &str, body: Value) -> Value {
    json!({"scope_key":key,"sequence":sequence,"previous":previous,"kind":kind,"body":body})
}

fn genesis(binding: &TradingBinding, venue: &VirtualBroker) -> Result<Value> {
    let source = venue.source_binding();
    check_scope(binding, &source["scope"])?;
    let cut = venue.checkpoint();
    if cut["inputs"] != json!([]) { return Err(conflict()); }
    Ok(document(binding.key(), 0, &genesis_previous(), "OPEN", json!({"trading_binding":binding.fingerprint(),
        "source_binding":source,"checkpoint":digest(&cut)})))
}

async fn insert(tx: &Transaction<'_>, value: &Value) -> Result<()> {
    let key = value["scope_key"].as_str().ok_or_else(conflict)?;
    let sequence = value["sequence"].as_i64().ok_or_else(conflict)?;
    let previous = value["previous"].as_str().ok_or_else(conflict)?;
    tx.execute("INSERT INTO public.sim_venue_log (scope_key,sequence,previous,fingerprint,document)
        VALUES ($1,$2,$3,$4,$5)", &[&key,&sequence,&previous,&digest(value),&value.to_string()])
        .await.map_err(|error| if error.as_db_error().is_some_and(|e| e.code().code().starts_with("23")) {
            conflict()
        } else { unavailable() })?;
    Ok(())
}

pub(super) async fn initialize_in_transaction(
    tx: &Transaction<'_>, binding: &TradingBinding, venue: &VirtualBroker,
) -> std::result::Result<(), super::sim_run::Error> {
    use super::sim_run::Error;
    let expected = genesis(binding, venue).map_err(|_| Error::Mismatch)?;
    insert(tx, &expected).await.map_err(|e| if e == unavailable() { Error::Unavailable } else { Error::Integrity })?;
    verify_open_in_transaction(tx, binding, venue).await
}

pub(super) async fn verify_open_in_transaction(
    tx: &Transaction<'_>, binding: &TradingBinding, venue: &VirtualBroker,
) -> std::result::Result<(), super::sim_run::Error> {
    use super::sim_run::Error;
    let expected = genesis(binding, venue).map_err(|_| Error::Mismatch)?;
    let row = tx.query_opt("SELECT l.document, l.fingerprint FROM public.sim_venue_log l
        JOIN public.sim_run_admission a USING (scope_key)
        WHERE l.scope_key=$1 AND l.sequence=0 AND a.binding_fingerprint=$2",
        &[&binding.key(), &binding.fingerprint()]).await.map_err(|_| Error::Unavailable)?.ok_or(Error::Missing)?;
    if row.try_get::<_, &str>(0).map_err(|_| Error::Integrity)? != expected.to_string()
        || row.try_get::<_, &str>(1).map_err(|_| Error::Integrity)? != digest(&expected) {
        return Err(Error::Mismatch);
    }
    Ok(())
}

struct WriteRequest {
    value: Value,
    reply: oneshot::Sender<Result<()>>,
}

struct Writer {
    key: String,
    sequence: i64,
    previous: String,
    sender: mpsc::Sender<WriteRequest>,
    healthy: bool,
    protocol_tip: Option<(Value, Option<Value>)>,
}

impl Writer {
    fn require_ready(&self) -> Result<()> {
        if self.healthy { Ok(()) } else { Err(unavailable()) }
    }

    fn append(&mut self, kind: &str, body: Value) -> Result<()> {
        self.require_ready()?;
        let sequence = self.sequence.checked_add(1).ok_or_else(conflict)?;
        let value = document(&self.key, sequence, &self.previous, kind, body);
        let fingerprint = digest(&value);
        let (reply, result) = oneshot::channel();
        self.healthy = false;
        self.sender.blocking_send(WriteRequest { value, reply }).map_err(|_| unavailable())?;
        result.blocking_recv().map_err(|_| unavailable())??;
        self.healthy = true;
        self.previous = fingerprint;
        self.sequence = sequence;
        Ok(())
    }
}

pub(crate) struct SimJournal {
    writer: Rc<RefCell<Writer>>,
    records: Vec<Record>,
    discoveries: BTreeMap<String, String>,
    dispatch_times: BTreeMap<String, Value>,
    checkpoint: Rc<RefCell<String>>,
}

fn dispatch_admission<'a>(event: &'a Value, at: Option<&'a Value>) -> Result<Option<(&'a str, &'a Value)>> {
    match (event["kind"].as_str(), at) {
        (Some("DISPATCHED"), Some(at)) => Ok(Some((event["command_id"].as_str().ok_or_else(conflict)?, at))),
        (Some("DISPATCHED"), None) | (_, Some(_)) => Err(conflict()),
        (_, None) => Ok(None),
    }
}

impl SimJournal {
    pub(crate) fn dispatch_admission_time(&self, command_id: &str) -> Option<&Value> {
        self.dispatch_times.get(command_id)
    }

    pub(crate) fn commands(&self) -> Result<Vec<BrokerCommand>> {
        self.writer.borrow().require_ready()?;
        self.records.iter().filter_map(|record| {
            let row = record.record();
            (row["event"]["kind"] == "INTENT").then(|| BrokerCommand::decode(&row["event"]["intent"]["command"]))
        }).collect()
    }
}

impl Journal for SimJournal {
    fn records(&self) -> Result<Vec<Record>> {
        self.writer.borrow().require_ready()?;
        Ok(self.records.clone())
    }

    fn append(&mut self, intent: &AppendIntent) -> Result<()> {
        let record = Record::new(intent);
        let raw = record.record();
        let checkpoint = self.checkpoint.borrow().clone();
        let dispatch = dispatch_admission(&raw["event"], intent.admitted_at())?;
        let mut writer = self.writer.borrow_mut();
        writer.append("PROTOCOL", json!({"record":raw,"admitted_at":intent.admitted_at(),"checkpoint":checkpoint}))?;
        if let Some((id, at)) = dispatch {
            self.dispatch_times.insert(id.to_owned(), at.clone());
        }
        if raw["event"]["kind"] == "DISCOVERY" {
            self.discoveries.insert(raw["event"]["command_id"].as_str().ok_or_else(conflict)?.into(), checkpoint);
        }
        writer.protocol_tip = Some((raw, intent.admitted_at().cloned()));
        self.records.push(record);
        Ok(())
    }
}

pub(crate) struct SimVenue {
    venue: VirtualBroker,
    scope: Scope,
    writer: Rc<RefCell<Writer>>,
    checkpoint: Rc<RefCell<String>>,
    inputs: usize,
}

impl SimVenue {
    fn save(&mut self) -> Result<()> {
        let cut = self.venue.checkpoint();
        let inputs = cut["inputs"].as_array().ok_or_else(conflict)?;
        let additional = inputs.get(self.inputs..).ok_or_else(conflict)?;
        let next = digest(&cut);
        if additional.is_empty() {
            return if next == *self.checkpoint.borrow() { Ok(()) } else { Err(conflict()) };
        }
        self.writer.borrow_mut().append("VENUE", json!({"inputs":additional,"checkpoint":next}))?;
        self.inputs = inputs.len();
        *self.checkpoint.borrow_mut() = next;
        Ok(())
    }

    pub(crate) fn advance(&mut self, at: i64) -> Result<()> {
        self.writer.borrow().require_ready()?;
        self.venue.advance(at)?;
        self.save()
    }

    pub(crate) fn on_bar(&mut self, sequence: u64, bar: &OnlyBar) -> Result<()> {
        self.writer.borrow().require_ready()?;
        self.venue.on_bar(sequence, bar)?;
        self.save()
    }

    pub(crate) fn account(&self) -> Result<Snapshot> {
        self.writer.borrow().require_ready()?;
        self.venue.account(&self.scope)
    }

    pub(crate) fn positions(&self) -> Result<Vec<Snapshot>> {
        self.writer.borrow().require_ready()?;
        self.venue.positions(&self.scope)
    }

    pub(crate) fn reconcile(&self, broker: &mut Broker, journal: &mut SimJournal, id: &str) -> Result<()> {
        self.writer.borrow().require_ready()?;
        if broker.command_state(id) == Some(CommandState::Reconciling)
            && journal.discoveries.get(id) == Some(&*self.checkpoint.borrow()) { return Ok(()); }
        self.venue.reconcile(broker, journal, id)
    }

    pub(crate) fn resolve(&self, broker: &mut Broker, journal: &mut SimJournal, runtime: &impl RuntimeReader, id: &str) -> Result<()> {
        self.writer.borrow().require_ready()?;
        self.venue.resolve(broker, journal, runtime, id)
    }

    pub(crate) fn publish(&mut self, broker: &mut Broker, journal: &mut SimJournal) -> Result<usize> {
        self.writer.borrow().require_ready()?;
        match self.venue.publish(broker, journal) {
            Ok(count) => { self.save()?; Ok(count) }
            Err(error) => { self.writer.borrow_mut().healthy = false; Err(error) }
        }
    }
}

impl TradingPort for SimVenue {
    fn capabilities(&self) -> Capabilities { self.venue.capabilities() }

    fn check_dispatch(&self, intent: &ReadyIntent) -> Result<()> {
        self.writer.borrow().require_ready()?;
        let at = intent.admitted_at().ok_or_else(|| Error::new("SIM_VENUE_ADMISSION_CLOCK_REQUIRED"))?;
        onlyalpha_broker::source::check_admission_clock(&self.scope, &json!(["CLOCK",self.venue.now()]), at)
    }

    fn dispatch(&mut self, _: &BrokerCommand) -> Result<DispatchResult> {
        Err(Error::new("SIM_VENUE_DISPATCH_OBSERVATION_REQUIRED"))
    }

    fn dispatch_observed(&mut self, command: &BrokerCommand, observed: &DispatchObservation) -> Result<DispatchResult> {
        {
            let writer = self.writer.borrow();
            writer.require_ready()?;
            let (tip, at) = writer.protocol_tip.as_ref().ok_or_else(conflict)?;
            if command != observed.command() || command.scope() != &self.scope || tip != &observed.record()
                || tip["event"] != json!({"kind":"DISPATCHED","command_id":command.id()}) || at.as_ref() != observed.admitted_at() {
                return Err(conflict());
            }
        }
        let result = self.venue.dispatch(command)?;
        self.save()?;
        Ok(result)
    }
}

struct History {
    documents: Vec<Value>,
}

impl History {
    async fn load(authority: &mut AuthoritySession, binding: &TradingBinding) -> Result<Self> {
        let tx = authority.client_mut().await.map_err(|_| unavailable())?.transaction().await.map_err(|_| unavailable())?;
        postgres::bounds(&tx).await.map_err(|_| unavailable())?;
        let rows = tx.query("SELECT l.sequence,l.previous,l.fingerprint,l.document FROM public.sim_run_admission a
            JOIN public.sim_venue_log l USING(scope_key) WHERE a.scope_key=$1 AND a.binding_fingerprint=$2 ORDER BY l.sequence",
            &[&binding.key(),&binding.fingerprint()]).await.map_err(|_| unavailable())?;
        let mut documents = Vec::with_capacity(rows.len());
        let mut previous = genesis_previous();
        for row in rows {
            let sequence = i64::try_from(documents.len()).map_err(|_| conflict())?;
            let value = decode_source_json(row.try_get(3).map_err(|_| conflict())?)?;
            let pin = digest(&value);
            if value["scope_key"] != binding.key() || value["sequence"] != sequence || value["previous"] != previous
                || row.try_get::<_, i64>(0).map_err(|_| conflict())? != sequence
                || row.try_get::<_, &str>(1).map_err(|_| conflict())? != previous
                || row.try_get::<_, &str>(2).map_err(|_| conflict())? != pin { return Err(conflict()); }
            previous = pin;
            documents.push(value);
        }
        AuthoritySession::verify_transaction(&tx).await.map_err(|_| unavailable())?;
        tx.commit().await.map_err(|_| unavailable())?;
        Ok(Self { documents })
    }

    fn open(self, binding: TradingBinding, scope: Scope, artifact: String, cash: OnlyMoney, config: Value,
        sender: mpsc::Sender<WriteRequest>) -> Result<(SimJournal, SimVenue)> {
        let mut venue = VirtualBroker::new(scope.clone(), &artifact, cash, &config)?;
        let (open, rest) = self.documents.split_first().ok_or_else(|| Error::new("SIM_VENUE_GENESIS_MISSING"))?;
        if open != &genesis(&binding, &venue)? { return Err(conflict()); }
        let mut checkpoint = digest(&venue.checkpoint());
        let mut records = Vec::new();
        let mut discoveries = BTreeMap::new();
        let mut dispatch_times = BTreeMap::new();
        let mut commands = BTreeMap::new();
        let mut dispatched = std::collections::BTreeSet::new();
        let mut observed_tip = None;
        let mut input_count = 0;
        for value in rest {
            let body = &value["body"];
            match value["kind"].as_str() {
                Some("PROTOCOL") => {
                    if body["checkpoint"] != checkpoint { return Err(conflict()); }
                    let record = Record::decode(&body["record"])?;
                    let event = &body["record"]["event"];
                    let at = body.get("admitted_at").ok_or_else(conflict)?;
                    let admission = (!at.is_null()).then_some(at);
                    if let Some((id, at)) = dispatch_admission(event, admission)? {
                        onlyalpha_broker::source::check_admission_clock(&scope, &json!(["CLOCK", venue.now()]), at)?;
                        if dispatch_times.insert(id.to_owned(), at.clone()).is_some() {
                            return Err(conflict());
                        }
                    }
                    match event["kind"].as_str() {
                        Some("INTENT") => {
                            let command = BrokerCommand::decode(&event["intent"]["command"])?;
                            commands.insert(command.id().to_owned(), command);
                        }
                        Some("RESULT") => {
                            let id = event["command_id"].as_str().ok_or_else(conflict)?;
                            let command = commands.get(id).ok_or_else(conflict)?;
                            let expected = match event["result"].as_str() {
                                Some("RECEIVED") => Some(DispatchResult::Received),
                                Some("REJECTED") => Some(DispatchResult::Rejected),
                                Some("UNKNOWN") => None,
                                _ => return Err(conflict()),
                            };
                            if expected.is_some() && venue.dispatch_result(command)? != expected {
                                return Err(conflict());
                            }
                        }
                        Some(kind @ ("DISCOVERY" | "RESOLVE")) => {
                            let id = event["command_id"].as_str().ok_or_else(conflict)?;
                            let command = commands.get(id).ok_or_else(conflict)?;
                            venue.verify_discovery(&records, command, &event["discovery"])?;
                            if kind == "DISCOVERY" {
                                discoveries.insert(id.to_owned(), checkpoint.clone());
                            }
                        }
                        _ => {}
                    }
                    observed_tip = Some((record.record(), admission.cloned()));
                    records.push(record);
                }
                Some("VENUE") => {
                    let additional = body["inputs"].as_array().filter(|v| !v.is_empty()).ok_or_else(conflict)?;
                    for input in additional {
                        if matches!(input[0].as_str(), Some("COMMAND" | "NOT_READY")) {
                            let command = BrokerCommand::decode(&input[1])?;
                            let (record, _) = observed_tip.as_ref().ok_or_else(conflict)?;
                            if additional.len() != 1 || !dispatched.insert(command.id().to_owned())
                                || commands.get(command.id()) != Some(&command)
                                || record["event"] != json!({"kind":"DISPATCHED","command_id":command.id()}) { return Err(conflict()); }
                        }
                    }
                    let expected = body["checkpoint"].as_str().ok_or_else(conflict)?;
                    venue = venue.restore_input_segment(additional, expected)?;
                    input_count += additional.len();
                    checkpoint = expected.to_owned();
                }
                _ => return Err(conflict()),
            }
        }
        venue.connect()?;
        venue.authenticate()?;
        let tip = self.documents.last().ok_or_else(conflict)?;
        let writer = Rc::new(RefCell::new(Writer { key:binding.key().into(), sequence:tip["sequence"].as_i64().ok_or_else(conflict)?,
            previous:digest(tip), sender, healthy:true, protocol_tip:observed_tip }));
        let checkpoint = Rc::new(RefCell::new(checkpoint));
        Ok((SimJournal { writer:writer.clone(), records, discoveries, dispatch_times, checkpoint:checkpoint.clone() },
            SimVenue { venue, scope, writer, checkpoint, inputs: input_count }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use onlyalpha_domain::base::OnlyDomainModel;
    use onlyalpha_runtime::RunConfiguration;

    #[test]
    fn correct_final_checkpoint_cannot_hide_a_wrong_intermediate_checkpoint() {
        let currency = json!({"schema_version":1,"code":"CNY","precision":2,"currency_type":"FIAT"});
        let scope = Scope::decode(&json!({"engine":"engine","runtime":"run","gateway":"virtual",
            "account":"account","generation":"a".repeat(64),"runtime_kind":"SIM"})).unwrap();
        let mut configuration = scope.record();
        configuration.as_object_mut().unwrap().extend(json!({"schema_version":1,"currency":currency,
            "initial_cash":"1000.00","capitals":{"cluster":"1000.00"},"profiles":{"cluster":{
                "schema_version":1,"revision":"revision","instruments":["600000.XSHG"],"rules":[]}},
            "instruments":[{"schema_version":1,"id":"600000.XSHG","price_precision":2,
                "quantity_precision":0,"multiplier":"1"}]}).as_object().unwrap().clone());
        let artifact = "b".repeat(64);
        let binding = TradingBinding::new(RunConfiguration::from_record(configuration).unwrap(), &artifact).unwrap();
        let cash = OnlyMoney::from_record(&json!({"schema_version":1,"amount":"1000.00","currency":currency})).unwrap();
        let config = json!({});
        let mut original = VirtualBroker::new(scope.clone(), &artifact, cash.clone(), &config).unwrap();
        let open = genesis(&binding, &original).unwrap();
        original.advance(1).unwrap();
        let first_pin = digest(&original.checkpoint());
        original.advance(2).unwrap();
        let last_pin = digest(&original.checkpoint());
        let restore = |first_pin: &str| {
            let first = document(binding.key(), 1, &digest(&open), "VENUE",
                json!({"inputs":[["CLOCK",1]],"checkpoint":first_pin}));
            let last = document(binding.key(), 2, &digest(&first), "VENUE",
                json!({"inputs":[["CLOCK",2]],"checkpoint":last_pin}));
            let (sender, _) = mpsc::channel(1);
            History { documents: vec![open.clone(), first, last] }.open(binding.clone(), scope.clone(),
                artifact.clone(), cash.clone(), config.clone(), sender)
        };
        assert!(restore(&first_pin).is_ok());
        assert!(restore(&last_pin).is_err());
    }
}

async fn append(authority: &mut AuthoritySession, value: &Value) -> Result<()> {
    let tx = authority.client_mut().await.map_err(|_| unavailable())?.transaction().await.map_err(|_| unavailable())?;
    postgres::bounds(&tx).await.map_err(|_| unavailable())?;
    postgres::ensure_commit_durability(&tx).await.map_err(|_| unavailable())?;
    insert(&tx, value).await?;
    AuthoritySession::verify_transaction(&tx).await.map_err(|_| unavailable())?;
    tx.commit().await.map_err(|_| Error::new("SIM_VENUE_COMMIT_UNKNOWN"))
}

pub(crate) async fn with_recovered<T, F>(authority: &mut AuthoritySession, binding: &TradingBinding,
    scope: Scope, artifact: &str, cash: OnlyMoney, config: &Value, capacity: usize, work: F) -> Result<T>
where T: Send + 'static, F: FnOnce(&mut Broker, &mut SimJournal, &mut SimVenue) -> Result<T> + Send + 'static {
    let history = History::load(authority, binding).await?;
    let (sender, mut receiver) = mpsc::channel::<WriteRequest>(1);
    let binding = binding.clone();
    let artifact = artifact.to_owned();
    let config = config.clone();
    let task = tokio::task::spawn_blocking(move || {
        let (mut journal, mut venue) = history.open(binding, scope.clone(), artifact, cash, config, sender)?;
        let mut broker = Broker::recover(scope, &journal, capacity)?;
        let result = work(&mut broker, &mut journal, &mut venue)?;
        journal.writer.borrow().require_ready()?;
        Ok(result)
    });
    while let Some(request) = receiver.recv().await {
        let result = append(authority, &request.value).await;
        if let Err(error) = result {
            let _ = request.reply.send(Err(error.clone()));
            drop(receiver);
            let _ = task.await;
            return Err(error);
        }
        let _ = request.reply.send(Ok(()));
    }
    let result = task.await.map_err(|_| unavailable())?;
    authority.verify().await.map_err(|_| unavailable())?;
    result
}

#[cfg(test)]
pub(crate) fn with_memory_log<T>(
    binding: &TradingBinding,
    scope: &Scope,
    cash: &OnlyMoney,
    documents: &mut Vec<Value>,
    work: impl FnOnce(&mut Broker, &mut SimJournal, &mut SimVenue) -> T,
) -> Result<T> {
    let config = json!({});
    if documents.is_empty() {
        let venue = VirtualBroker::new(scope.clone(), binding.kernel_artifact(), cash.clone(), &config)?;
        documents.push(genesis(binding, &venue)?);
    }
    let history = History { documents: documents.clone() };
    let (sender, mut receiver) = mpsc::channel::<WriteRequest>(1);
    std::thread::scope(|threads| {
        threads.spawn(move || {
            while let Some(request) = receiver.blocking_recv() {
                documents.push(request.value);
                request.reply.send(Ok(())).unwrap();
            }
        });
        let (mut journal, mut venue) = history.open(binding.clone(), scope.clone(), binding.kernel_artifact().into(),
            cash.clone(), config, sender)?;
        let mut broker = Broker::recover(scope.clone(), &journal, 8)?;
        Ok(work(&mut broker, &mut journal, &mut venue))
    })
}
