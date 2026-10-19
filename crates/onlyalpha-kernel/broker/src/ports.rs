use crate::{BrokerCommand, Error, Fact, OrderView, Scope, Snapshot, model::*};
use serde_json::{Value, json};
use std::collections::BTreeSet;
/// Owning Runtime reader. Implementations MUST read committed Ready records and validate exact
/// scope/request/application relations and current dispatch eligibility. Historical Ready intent
/// is insufficient after dispatch, UNKNOWN/reconciliation or a terminal transition. Cancel must
/// bind the current pending request's complete canonical payload, including reason/metadata.
/// A matching caller-supplied digest is not this authority.
/// An unavailable or non-Ready proof returns Err/None, never a synthetic success.
pub trait RuntimeReader {
    fn ready_intent(&self, command: &BrokerCommand) -> Result<ReadyIntent, Error>;
    fn application_receipt(&self, fact: &Fact) -> Result<Option<ApplicationReceipt>, Error>;
    fn order_view(&self, command: &BrokerCommand) -> Result<Option<OrderView>, Error>;
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReadyIntent {
    pub(crate) command: BrokerCommand,
    pub(crate) transaction: String,
    pub(crate) payload_hash: String,
}
impl ReadyIntent {
    pub fn new(
        command: BrokerCommand,
        transaction: String,
        payload_hash: String,
    ) -> Result<Self, Error> {
        id(&json!(transaction))?;
        fp(&json!(payload_hash))?;
        Ok(Self {
            command,
            transaction,
            payload_hash,
        })
    }
    pub(crate) fn record(&self) -> Value {
        json!({"command":self.command.record(),"transaction":self.transaction,"payload_hash":self.payload_hash})
    }
    pub(crate) fn decode(v: &Value) -> Result<Self, Error> {
        row(v, &["command", "transaction", "payload_hash"])?;
        Self::new(
            BrokerCommand::decode(&v["command"])?,
            text(&v["transaction"])?.into(),
            text(&v["payload_hash"])?.into(),
        )
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ApplicationStatus {
    Applied,
    Duplicate,
}
/// A relation read from the owning Runtime, not an acknowledgement by update ID alone.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ApplicationReceipt {
    pub(crate) scope: Scope,
    pub(crate) identity: String,
    pub(crate) fingerprint: String,
    pub(crate) transaction: String,
    pub(crate) payload_hash: String,
    pub(crate) status: ApplicationStatus,
}
impl ApplicationReceipt {
    pub fn new(
        fact: &Fact,
        transaction: String,
        payload_hash: String,
        status: ApplicationStatus,
    ) -> Result<Self, Error> {
        id(&json!(transaction))?;
        fp(&json!(payload_hash))?;
        Ok(Self {
            scope: fact.scope(),
            identity: fact.identity().into(),
            fingerprint: fact.fingerprint().into(),
            transaction,
            payload_hash,
            status,
        })
    }
    pub(crate) fn matches(&self, f: &Fact) -> bool {
        self.scope == f.scope()
            && self.identity == f.identity()
            && self.fingerprint == f.fingerprint()
    }
    pub(crate) fn record(&self) -> Value {
        json!({"scope":self.scope.record(),"identity":self.identity,"fingerprint":self.fingerprint,"transaction":self.transaction,"payload_hash":self.payload_hash,"status":if self.status==ApplicationStatus::Applied{"APPLIED"}else{"DUPLICATE"}})
    }
    pub(crate) fn decode(v: &Value) -> Result<Self, Error> {
        row(
            v,
            &[
                "scope",
                "identity",
                "fingerprint",
                "transaction",
                "payload_hash",
                "status",
            ],
        )?;
        let status = match text(&v["status"])? {
            "APPLIED" => ApplicationStatus::Applied,
            "DUPLICATE" => ApplicationStatus::Duplicate,
            _ => return Err(err("BROKER_RECEIPT_STATUS")),
        };
        id(&v["identity"])?;
        id(&v["transaction"])?;
        fp(&v["fingerprint"])?;
        fp(&v["payload_hash"])?;
        Ok(Self {
            scope: Scope::decode(&v["scope"])?,
            identity: text(&v["identity"])?.into(),
            fingerprint: text(&v["fingerprint"])?.into(),
            transaction: text(&v["transaction"])?.into(),
            payload_hash: text(&v["payload_hash"])?.into(),
            status,
        })
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DispatchResult {
    Received,
    Rejected,
    Unknown,
}
/// External adapters must declare unsupported capabilities before dispatch. Once entered, errors
/// are UNKNOWN; Received is only command receipt, never an Accepted/Cancelled trading fact.
pub trait TradingPort {
    fn capabilities(&self) -> Capabilities;
    fn dispatch(&mut self, command: &BrokerCommand) -> Result<DispatchResult, Error>;
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Capabilities(BTreeSet<String>);
impl Capabilities {
    pub fn new(names: &[&str]) -> Result<Self, Error> {
        let allowed = [
            "CONNECT",
            "AUTHENTICATE",
            "SUBMIT_ORDER",
            "CANCEL_ORDER",
            "QUERY_ACCOUNT",
            "QUERY_BALANCES",
            "QUERY_POSITIONS",
            "QUERY_OPEN_ORDERS",
            "QUERY_ORDERS",
            "QUERY_TRADES",
            "QUERY_FEE_EVIDENCE",
            "PUSH_ORDER_UPDATES",
            "PUSH_TRADE_UPDATES",
            "PUSH_ACCOUNT_UPDATES",
            "PUSH_POSITION_UPDATES",
            "MARKET_ORDER",
            "LIMIT_ORDER",
            "PARTIAL_FILL",
        ];
        if names.iter().any(|n| !allowed.contains(n)) {
            return Err(err("BROKER_CAPABILITY"));
        }
        let set = names.iter().map(|s| s.to_string()).collect::<BTreeSet<_>>();
        if set.len() != names.len() {
            return Err(err("BROKER_CAPABILITY_DUPLICATE"));
        }
        Ok(Self(set))
    }
    pub fn contains(&self, name: &str) -> bool {
        self.0.contains(name)
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Connection {
    Disconnected,
    Connecting,
    Connected,
    Authenticating,
    Ready,
    Reconnecting,
    Failed,
}
pub trait ConnectionPort {
    fn connect(&mut self) -> Result<Connection, Error>;
    fn authenticate(&mut self) -> Result<Connection, Error>;
    fn disconnect(&mut self) -> Result<(), Error>;
}
/// Query records are validated normalized Broker records, never mutable manager handles.
pub trait AccountPort {
    fn account(&self, scope: &Scope) -> Result<Snapshot, Error>;
    fn balances(&self, scope: &Scope) -> Result<Vec<Snapshot>, Error>;
}
pub trait PositionPort {
    fn positions(&self, scope: &Scope) -> Result<Vec<Snapshot>, Error>;
}
pub trait OrderQueryPort {
    fn orders(&self, scope: &Scope, open_only: bool) -> Result<Vec<OrderView>, Error>;
}
pub trait TradeQueryPort {
    fn trades(&self, scope: &Scope, since_sequence: Option<u64>) -> Result<Vec<Fact>, Error>;
}
pub trait FeeEvidencePort {
    fn fee_evidence(&self, scope: &Scope, order: &str) -> Result<Vec<Value>, Error>;
}
pub fn fee_evidence_port<'a>(
    capabilities: &Capabilities,
    port: Option<&'a dyn FeeEvidencePort>,
) -> Result<&'a dyn FeeEvidencePort, Error> {
    if !capabilities.contains("QUERY_FEE_EVIDENCE") {
        return Err(err("BROKER_UNSUPPORTED_CAPABILITY"));
    }
    port.ok_or_else(|| err("BROKER_CAPABILITY_PORT_MISSING"))
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Presence {
    Present,
    AbsentProven,
    Inconclusive,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Discovery {
    pub(crate) command: BrokerCommand,
    pub(crate) proof: String,
    pub(crate) as_of: u64,
    pub(crate) presence: Presence,
    pub(crate) view: Option<OrderView>,
    pub(crate) facts: Vec<Fact>,
}
impl Discovery {
    pub fn new(
        command: BrokerCommand,
        proof: String,
        as_of: u64,
        presence: Presence,
        view: Option<OrderView>,
        facts: Vec<Fact>,
    ) -> Result<Self, Error> {
        id(&json!(proof))?;
        if as_of == 0 {
            return Err(err("BROKER_DISCOVERY_WATERMARK"));
        }
        if (presence == Presence::Present) != view.is_some()
            || (presence != Presence::Present && !facts.is_empty())
            || view.as_ref().is_some_and(|v| !v.matches(&command))
        {
            return Err(err("BROKER_DISCOVERY_VIEW"));
        }
        let mut seen = BTreeSet::new();
        for f in &facts {
            if f.scope() != *command.scope()
                || f.order() != Some(command.order())
                || !seen.insert(f.identity())
            {
                return Err(err("BROKER_DISCOVERY_FACT_SCOPE"));
            }
            if let Some(v) = &view {
                let venue = if f.value["kind"] == "TRADE" {
                    &f.value["payload"]["fill"]["venue_order_id"]["value"]
                } else {
                    &f.value["payload"]["venue"]
                };
                if !venue.is_null() && *venue != v.record()["venue"] {
                    return Err(err("BROKER_DISCOVERY_VENUE"));
                }
            }
        }
        Ok(Self {
            command,
            proof,
            as_of,
            presence,
            view,
            facts,
        })
    }
    pub(crate) fn record(&self) -> Value {
        json!({"command":self.command.record(),"proof":self.proof,"as_of":self.as_of,"presence":match self.presence{Presence::Present=>"PRESENT",Presence::AbsentProven=>"ABSENT_PROVEN",Presence::Inconclusive=>"INCONCLUSIVE"},"view":self.view.as_ref().map(OrderView::record),"facts":self.facts.iter().map(Fact::record).collect::<Vec<_>>()})
    }
    pub(crate) fn decode(v: &Value) -> Result<Self, Error> {
        row(
            v,
            &["command", "proof", "as_of", "presence", "view", "facts"],
        )?;
        let presence = match text(&v["presence"])? {
            "PRESENT" => Presence::Present,
            "ABSENT_PROVEN" => Presence::AbsentProven,
            "INCONCLUSIVE" => Presence::Inconclusive,
            _ => return Err(err("BROKER_PRESENCE")),
        };
        let view = if v["view"].is_null() {
            None
        } else {
            Some(OrderView::decode(&v["view"])?)
        };
        Self::new(
            BrokerCommand::decode(&v["command"])?,
            text(&v["proof"])?.into(),
            v["as_of"]
                .as_u64()
                .ok_or_else(|| err("BROKER_DISCOVERY_WATERMARK"))?,
            presence,
            view,
            v["facts"]
                .as_array()
                .ok_or_else(|| err("BROKER_FACTS"))?
                .iter()
                .map(Fact::decode)
                .collect::<Result<_, _>>()?,
        )
    }
}
/// Provider-owned discovery must prove absence, bind client identity across sessions, and return
/// the complete missing fact set at its watermark. Inconclusive queries never prove absence.
pub trait DiscoveryPort {
    fn discover(&mut self, command: &BrokerCommand) -> Result<Discovery, Error>;
}
