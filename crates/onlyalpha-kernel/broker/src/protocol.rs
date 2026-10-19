use crate::{model::*, ports::*};
use serde_json::{Value, json};
use std::collections::BTreeMap;
/// The sole append capability is constructed after validation of the current owning prefix.
/// Decoding a Record does not grant this capability.
/// ```compile_fail
/// use onlyalpha_broker::AppendIntent;
/// let forged = AppendIntent { value: serde_json::json!({}) };
/// ```
pub struct AppendIntent {
    value: Value,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Record(Value);
impl Record {
    pub fn new(intent: &AppendIntent) -> Self {
        Self(intent.value.clone())
    }
    pub fn record(&self) -> Value {
        self.0.clone()
    }
    pub fn decode(v: &Value) -> Result<Self, Error> {
        row(
            v,
            &[
                "schema_version",
                "sequence",
                "previous",
                "scope",
                "event",
                "hash",
            ],
        )?;
        if v["schema_version"] != 1 || v["sequence"].as_u64().is_none_or(|n| n == 0) {
            return Err(err("BROKER_RECORD"));
        }
        Scope::decode(&v["scope"])?;
        fp(&v["previous"])?;
        fp(&v["hash"])?;
        bounded(v)?;
        Ok(Self(v.clone()))
    }
}
/// A serialized, scoped owning journal. Append is atomic, contiguous, immutable and queryable.
/// Drivers must retain the exact record and reject changed payloads/sequence aliases. Err may
/// mean committed: callers reload; they never mint another command identity to bypass uncertainty.
pub trait Journal {
    fn records(&self) -> Result<Vec<Record>, Error>;
    fn append(&mut self, intent: &AppendIntent) -> Result<(), Error>;
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CommandState {
    Durable,
    Unknown,
    Known,
    Reconciling,
    Resolved,
}
#[derive(Clone, Debug)]
struct Entry {
    intent: ReadyIntent,
    state: CommandState,
    result_recorded: bool,
    discovery: Option<Discovery>,
}
#[derive(Clone, Default)]
struct State {
    commands: BTreeMap<String, Entry>,
    pending: Vec<Fact>,
    seen: BTreeMap<String, String>,
    venues: BTreeMap<String, String>,
    order_venues: BTreeMap<String, String>,
    trades: BTreeMap<String, String>,
    conflict: bool,
}
fn add_facts(
    state: &mut State,
    scope: &Scope,
    facts: &[Fact],
    capacity: usize,
) -> Result<(), Error> {
    for f in facts {
        if f.scope() != *scope {
            return Err(err("BROKER_FACT_SCOPE"));
        }
        if let Some(order) = f.order() {
            let p = &f.value["payload"];
            let venue = if f.value["kind"] == "TRADE" {
                p["fill"]["venue_order_id"]["value"].as_str()
            } else {
                p["venue"].as_str()
            };
            if let Some(venue) = venue {
                if state.venues.get(venue).is_some_and(|old| old != order)
                    || state
                        .order_venues
                        .get(order)
                        .is_some_and(|old| old != venue)
                {
                    return Err(err("BROKER_FACT_CONFLICT"));
                }
                state.venues.insert(venue.into(), order.into());
                state.order_venues.insert(order.into(), venue.into());
            }
            if f.value["kind"] == "TRADE" {
                for (field, prefix) in [("trade_id", "TRADE"), ("venue_trade_id", "VENUE_TRADE")] {
                    if let Some(trade) = p["fill"][field]["value"].as_str() {
                        let key = format!("{prefix}:{trade}");
                        if state.trades.get(&key).is_some_and(|old| old != order) {
                            return Err(err("BROKER_FACT_CONFLICT"));
                        }
                        state.trades.insert(key, order.into());
                    }
                }
            }
        }
        if let Some(fp) = state.seen.get(f.identity()) {
            if fp != f.fingerprint() {
                return Err(err("BROKER_FACT_CONFLICT"));
            }
            continue;
        }
        if state.pending.len() == capacity {
            return Err(err("BROKER_INBOUND_OVERFLOW"));
        }
        state
            .seen
            .insert(f.identity().into(), f.fingerprint().into());
        state.pending.push(f.clone());
    }
    Ok(())
}
fn apply(state: &mut State, scope: &Scope, event: &Value, capacity: usize) -> Result<(), Error> {
    let kind = text(&event["kind"])?;
    match kind {
        "INTENT" => {
            row(event, &["kind", "intent"])?;
            let i = ReadyIntent::decode(&event["intent"])?;
            let c = i.command.clone();
            if c.scope() != scope || state.commands.contains_key(c.id()) {
                return Err(err("BROKER_INTENT_CONFLICT"));
            }
            for e in state.commands.values() {
                if (e.intent.command.client() == c.client()
                    && e.intent.command.order() != c.order())
                    || e.intent.command.value["request"]["request_id"]
                        == c.value["request"]["request_id"]
                {
                    return Err(err("BROKER_ORDER_COMMAND_CONFLICT"));
                }
                if e.intent.command.order() == c.order()
                    && (e.intent.command.client() != c.client()
                        || c.operation() == Operation::Submit
                        || (e.intent.command.operation() == c.operation()
                            && e.state != CommandState::Resolved))
                {
                    return Err(err("BROKER_ORDER_COMMAND_CONFLICT"));
                }
            }
            state.commands.insert(
                c.id().into(),
                Entry {
                    intent: i,
                    state: CommandState::Durable,
                    result_recorded: false,
                    discovery: None,
                },
            );
        }
        "DISPATCHED" | "RESULT" | "DISCOVERY" | "RESOLVE" => {
            let key = text(&event["command_id"])?;
            let e = state
                .commands
                .get_mut(key)
                .ok_or_else(|| err("BROKER_COMMAND_MISSING"))?;
            match kind {
                "DISPATCHED" => {
                    row(event, &["kind", "command_id"])?;
                    if e.state != CommandState::Durable {
                        return Err(err("BROKER_DISPATCH_TRANSITION"));
                    }
                    e.state = CommandState::Unknown;
                }
                "RESULT" => {
                    row(event, &["kind", "command_id", "result"])?;
                    if e.state != CommandState::Unknown
                        || e.result_recorded
                        || e.discovery.is_some()
                    {
                        return Err(err("BROKER_RESULT_TRANSITION"));
                    }
                    e.result_recorded = true;
                    match text(&event["result"])? {
                        "RECEIVED" | "REJECTED" => e.state = CommandState::Known,
                        "UNKNOWN" => (),
                        _ => return Err(err("BROKER_RESULT")),
                    }
                }
                "DISCOVERY" => {
                    row(event, &["kind", "command_id", "discovery"])?;
                    if !matches!(
                        e.state,
                        CommandState::Unknown | CommandState::Known | CommandState::Reconciling
                    ) {
                        return Err(err("BROKER_DISCOVERY_TRANSITION"));
                    }
                    let mut d = Discovery::decode(&event["discovery"])?;
                    if d.command != e.intent.command
                        || e.discovery
                            .as_ref()
                            .is_some_and(|old| old.proof == d.proof || d.as_of < old.as_of)
                    {
                        return Err(err("BROKER_DISCOVERY_COMMAND"));
                    }
                    if let Some(old) = &e.discovery {
                        if old.presence == Presence::Present && d.presence != Presence::Present {
                            return Err(err("BROKER_DISCOVERY_REGRESSION"));
                        }
                        let mut cumulative = old.facts.clone();
                        for f in &d.facts {
                            if let Some(previous) =
                                cumulative.iter().find(|p| p.identity() == f.identity())
                            {
                                if previous.fingerprint() != f.fingerprint() {
                                    return Err(err("BROKER_FACT_CONFLICT"));
                                }
                            } else {
                                cumulative.push(f.clone());
                            }
                        }
                        d.facts = cumulative;
                    }
                    e.discovery = Some(d.clone());
                    e.state = CommandState::Reconciling;
                    add_facts(state, scope, &d.facts, capacity)?;
                }
                "RESOLVE" => {
                    row(
                        event,
                        &["kind", "command_id", "discovery", "local", "receipts"],
                    )?;
                    if e.state != CommandState::Reconciling {
                        return Err(err("BROKER_RESOLVE_TRANSITION"));
                    }
                    let old = e
                        .discovery
                        .as_ref()
                        .ok_or_else(|| err("BROKER_DISCOVERY_MISSING"))?;
                    let d = Discovery::decode(&event["discovery"])?;
                    if d.command != e.intent.command || d.proof == old.proof || d.as_of < old.as_of
                    {
                        return Err(err("BROKER_STALE_DISCOVERY"));
                    }
                    let receipts = event["receipts"]
                        .as_array()
                        .ok_or_else(|| err("BROKER_RECEIPTS"))?
                        .iter()
                        .map(ApplicationReceipt::decode)
                        .collect::<Result<Vec<_>, _>>()?;
                    if d.presence == Presence::AbsentProven
                        && old.presence == Presence::AbsentProven
                        && e.intent.command.operation() == Operation::Submit
                    {
                        if !receipts.is_empty()
                            || !event["local"].is_null()
                            || !old.facts.is_empty()
                            || !d.facts.is_empty()
                        {
                            return Err(err("BROKER_ABSENCE_PROOF"));
                        }
                    } else {
                        let local = OrderView::decode(&event["local"])?;
                        if d.presence != Presence::Present
                            || old.presence != Presence::Present
                            || d.view.as_ref() != Some(&local)
                            || old.view != d.view
                            || !d.facts.is_empty()
                            || receipts.len() != old.facts.len()
                        {
                            return Err(err("BROKER_NOT_CONVERGED"));
                        }
                        for (f, r) in old.facts.iter().zip(&receipts) {
                            if !r.matches(f) {
                                return Err(err("BROKER_RECEIPT_RELATION"));
                            }
                        }
                    }
                    let identities = old
                        .facts
                        .iter()
                        .map(|f| f.identity().to_string())
                        .collect::<Vec<_>>();
                    e.state = CommandState::Resolved;
                    state
                        .pending
                        .retain(|f| !identities.iter().any(|id| id == f.identity()));
                }
                _ => unreachable!(),
            }
        }
        "INGRESS" => {
            row(event, &["kind", "facts"])?;
            let facts = event["facts"]
                .as_array()
                .ok_or_else(|| err("BROKER_FACTS"))?
                .iter()
                .map(Fact::decode)
                .collect::<Result<Vec<_>, _>>()?;
            add_facts(state, scope, &facts, capacity)?;
        }
        "ACK" => {
            row(event, &["kind", "receipt"])?;
            let r = ApplicationReceipt::decode(&event["receipt"])?;
            let f = state
                .pending
                .iter()
                .find(|f| f.identity() == r.identity)
                .ok_or_else(|| err("BROKER_PENDING_MISSING"))?;
            if !r.matches(f) {
                return Err(err("BROKER_RECEIPT_RELATION"));
            }
            state.pending.retain(|f| f.identity() != r.identity);
        }
        "CONFLICT" => {
            row(event, &["kind"])?;
            state.conflict = true;
        }
        _ => return Err(err("BROKER_EVENT_KIND")),
    }
    Ok(())
}
pub struct Broker {
    scope: Scope,
    capacity: usize,
    state: State,
    history: Vec<Record>,
    connection: Connection,
    account_known: bool,
    discovery_complete: bool,
    stream_trusted: bool,
}
impl Broker {
    pub fn recover(scope: Scope, journal: &impl Journal, capacity: usize) -> Result<Self, Error> {
        if capacity == 0 || capacity > 65536 {
            return Err(err("BROKER_CAPACITY"));
        }
        let mut b = Self {
            scope,
            capacity,
            state: State::default(),
            history: vec![],
            connection: Connection::Disconnected,
            account_known: false,
            discovery_complete: false,
            stream_trusted: false,
        };
        b.refresh(journal)?;
        Ok(b)
    }
    fn reload(&mut self, j: &impl Journal) -> Result<(), Error> {
        let records = j.records()?;
        if !records.starts_with(&self.history) {
            self.stream_trusted = false;
            return Err(err("BROKER_HISTORY_REWRITTEN"));
        }
        let mut state = State::default();
        let mut previous = "0".repeat(64);
        for (n, r) in records.iter().enumerate() {
            let v = &r.0;
            Record::decode(v)?;
            let mut body = v.clone();
            body.as_object_mut().expect("object").remove("hash");
            if v["sequence"] != (n + 1) as u64
                || v["scope"] != self.scope.record()
                || v["previous"] != previous
                || v["hash"] != digest(&body)
            {
                return Err(err("BROKER_JOURNAL_CHAIN"));
            }
            apply(&mut state, &self.scope, &v["event"], self.capacity)?;
            previous = text(&v["hash"])?.into();
        }
        self.state = state;
        self.history = records;
        Ok(())
    }
    fn refresh(&mut self, j: &impl Journal) -> Result<(), Error> {
        let result = self.reload(j);
        if result.is_err() {
            self.stream_trusted = false;
        }
        result
    }
    fn append(&mut self, j: &mut impl Journal, event: Value) -> Result<(), Error> {
        self.refresh(j)?;
        let mut candidate = self.state.clone();
        apply(&mut candidate, &self.scope, &event, self.capacity)?;
        let mut v = json!({"schema_version":1,"sequence":self.history.len()+1,"previous":self.history.last().map(|r|text(&r.0["hash"]).expect("validated")).unwrap_or(&"0".repeat(64)),"scope":self.scope.record(),"event":event});
        v["hash"] = json!(digest(&v));
        Record::decode(&v)?;
        let intent = AppendIntent { value: v.clone() };
        if let Err(e) = j.append(&intent) {
            self.stream_trusted = false;
            return Err(e);
        }
        self.refresh(j)?;
        if self.history.last() != Some(&Record(v)) {
            self.stream_trusted = false;
            return Err(err("BROKER_APPEND_NOT_OBSERVABLE"));
        }
        Ok(())
    }
    pub fn set_connection(&mut self, connection: Connection) {
        if self.connection != connection {
            self.account_known = false;
            self.discovery_complete = false;
            self.stream_trusted = false;
        }
        self.connection = connection;
    }
    /// Explicit transport/account/discovery observations, never an order-convergence proof.
    pub fn set_health(
        &mut self,
        account_known: bool,
        discovery_complete: bool,
        stream_trusted: bool,
    ) {
        self.account_known = account_known;
        self.discovery_complete = discovery_complete;
        self.stream_trusted = stream_trusted;
    }
    pub fn ready(&self) -> bool {
        self.connection == Connection::Ready
            && self.account_known
            && self.discovery_complete
            && self.stream_trusted
            && !self.state.conflict
            && !self
                .state
                .commands
                .values()
                .any(|e| matches!(e.state, CommandState::Unknown | CommandState::Reconciling))
    }
    pub fn command_state(&self, id: &str) -> Option<CommandState> {
        self.state.commands.get(id).map(|e| e.state)
    }
    pub fn pending(&self) -> &[Fact] {
        &self.state.pending
    }
    pub fn dispatch(
        &mut self,
        j: &mut impl Journal,
        runtime: &impl RuntimeReader,
        adapter: &mut impl TradingPort,
        command: &BrokerCommand,
    ) -> Result<CommandState, Error> {
        self.refresh(j)?;
        if command.scope() != &self.scope {
            return Err(err("BROKER_COMMAND_SCOPE"));
        }
        if let Some(e) = self.state.commands.get(command.id()) {
            if e.intent.command != *command {
                return Err(err("BROKER_COMMAND_PAYLOAD_CONFLICT"));
            }
            if e.state != CommandState::Durable {
                return Ok(e.state);
            }
        }
        let capabilities = adapter.capabilities();
        let required = if command.operation() == Operation::Submit {
            "SUBMIT_ORDER"
        } else {
            "CANCEL_ORDER"
        };
        if !capabilities.contains(required)
            || (command.operation() == Operation::Submit
                && !capabilities.contains(if command.value["request"]["order_type"] == "LIMIT" {
                    "LIMIT_ORDER"
                } else {
                    "MARKET_ORDER"
                }))
        {
            return Err(err("BROKER_UNSUPPORTED_CAPABILITY"));
        }
        if command.operation() == Operation::Submit && !self.ready() {
            return Err(err("BROKER_NOT_READY"));
        }
        let intent = runtime.ready_intent(command)?;
        if intent.command != *command
            || self
                .state
                .commands
                .get(command.id())
                .is_some_and(|e| e.intent != intent)
        {
            return Err(err("BROKER_RUNTIME_INTENT_RELATION"));
        }
        if !self.state.commands.contains_key(command.id()) {
            self.append(j, json!({"kind":"INTENT","intent":intent.record()}))?;
        }
        self.append(j, json!({"kind":"DISPATCHED","command_id":command.id()}))?;
        let outcome = adapter.dispatch(command).unwrap_or(DispatchResult::Unknown);
        self.append(j,json!({"kind":"RESULT","command_id":command.id(),"result":match outcome{DispatchResult::Received=>"RECEIVED",DispatchResult::Rejected=>"REJECTED",DispatchResult::Unknown=>"UNKNOWN"}}))?;
        Ok(self.state.commands[command.id()].state)
    }
    pub fn ingest(&mut self, j: &mut impl Journal, facts: &[Fact]) -> Result<(), Error> {
        let event =
            json!({"kind":"INGRESS","facts":facts.iter().map(Fact::record).collect::<Vec<_>>()});
        match self.append(j, event) {
            Err(e) if e.to_string() == "BROKER_FACT_CONFLICT" => {
                self.append(j, json!({"kind":"CONFLICT"}))?;
                Err(e)
            }
            result => {
                if result.is_err() {
                    self.stream_trusted = false;
                }
                result
            }
        }
    }
    pub fn acknowledge(
        &mut self,
        j: &mut impl Journal,
        runtime: &impl RuntimeReader,
        identity: &str,
    ) -> Result<(), Error> {
        self.refresh(j)?;
        let f = self
            .state
            .pending
            .iter()
            .find(|f| f.identity() == identity)
            .ok_or_else(|| err("BROKER_PENDING_MISSING"))?;
        let r = runtime
            .application_receipt(f)?
            .ok_or_else(|| err("BROKER_APPLICATION_NOT_READY"))?;
        self.append(j, json!({"kind":"ACK","receipt":r.record()}))
    }
    pub fn reconcile(
        &mut self,
        j: &mut impl Journal,
        discovery: &mut impl DiscoveryPort,
        command_id: &str,
    ) -> Result<(), Error> {
        self.refresh(j)?;
        let command = self
            .state
            .commands
            .get(command_id)
            .ok_or_else(|| err("BROKER_COMMAND_MISSING"))?
            .intent
            .command
            .clone();
        if !matches!(
            self.command_state(command_id),
            Some(CommandState::Unknown | CommandState::Known | CommandState::Reconciling)
        ) {
            return Err(err("BROKER_DISCOVERY_TRANSITION"));
        }
        // Starting a new discovery invalidates the previous aggregate completeness assertion.
        // Neither query failure nor resolving one Order can certify all Gateway discovery.
        self.discovery_complete = false;
        let d = discovery.discover(&command)?;
        let result = self.append(
            j,
            json!({"kind":"DISCOVERY","command_id":command_id,"discovery":d.record()}),
        );
        if result
            .as_ref()
            .is_err_and(|e| e.to_string() == "BROKER_FACT_CONFLICT")
        {
            self.append(j, json!({"kind":"CONFLICT"}))?;
        }
        result
    }
    pub fn resolve(
        &mut self,
        j: &mut impl Journal,
        runtime: &impl RuntimeReader,
        discovery: &mut impl DiscoveryPort,
        command_id: &str,
    ) -> Result<(), Error> {
        self.refresh(j)?;
        let e = self
            .state
            .commands
            .get(command_id)
            .ok_or_else(|| err("BROKER_COMMAND_MISSING"))?;
        let old = e
            .discovery
            .as_ref()
            .ok_or_else(|| err("BROKER_DISCOVERY_MISSING"))?;
        let mut receipts = vec![];
        for f in &old.facts {
            let receipt = runtime
                .application_receipt(f)?
                .ok_or_else(|| err("BROKER_APPLICATION_NOT_READY"))?;
            if !receipt.matches(f) {
                return Err(err("BROKER_RECEIPT_RELATION"));
            }
            receipts.push(receipt.record());
        }
        let d = discovery.discover(&e.intent.command)?;
        let local = runtime.order_view(&e.intent.command)?;
        self.append(j,json!({"kind":"RESOLVE","command_id":command_id,"discovery":d.record(),"local":local.map(|v|v.record()),"receipts":receipts}))
    }
}
