use super::*;
use onlyalpha_broker::{self as broker, AppendIntent, ApplicationReceipt, Record};
use serde_json::json;

#[derive(Default)]
struct Store {
    rows: Vec<Record>,
    unavailable: bool,
}

impl Journal for Store {
    fn records(&self) -> std::result::Result<Vec<Record>, broker::Error> {
        if self.unavailable {
            return Err(broker::Error::new("STORE_UNAVAILABLE"));
        }
        Ok(self.rows.clone())
    }
    fn append(&mut self, intent: &AppendIntent) -> std::result::Result<(), broker::Error> {
        self.rows.push(Record::new(intent));
        Ok(())
    }
}

struct Venue {
    scope: Scope,
    reports: Vec<Fact>,
}

impl TradingPort for Venue {
    fn capabilities(&self) -> broker::Capabilities {
        broker::Capabilities::new(&[]).unwrap()
    }
    fn dispatch(
        &mut self,
        _: &BrokerCommand,
    ) -> std::result::Result<broker::DispatchResult, broker::Error> {
        unreachable!()
    }
}

impl SimulatedTradingPort<Store> for Venue {
    fn scope(&self) -> &Scope {
        &self.scope
    }
    fn prepare_market(&mut self, _: &MarketBar) -> Result<()> {
        unreachable!()
    }
    fn publish(&mut self, broker: &mut Broker, store: &mut Store) -> Result<()> {
        if !self.reports.is_empty() {
            broker.ingest(store, &self.reports).map_err(boundary)?;
            self.reports.clear();
        }
        Ok(())
    }
}

struct Owner {
    scope: Scope,
    binding: TradingBinding,
    applied: Vec<Fact>,
    unavailable: bool,
    receipt_ready: bool,
}

impl EconomicOwner for Owner {
    fn scope(&self) -> &Scope {
        &self.scope
    }
    fn account(&self, _: &OnlyTimestamp) -> Result<ReadonlyAccountState> {
        unreachable!()
    }
    fn admit(&mut self, _: &OrderIntent, _: &OnlyTimestamp) -> Result<Admission> {
        unreachable!()
    }
    fn apply_venue(&mut self, fact: &Fact) -> Result<()> {
        if self.unavailable {
            return Err(error("ECONOMIC_UNAVAILABLE"));
        }
        if !self.applied.contains(fact) {
            self.applied.push(fact.clone());
        }
        Ok(())
    }
}

impl RuntimeReader for Owner {
    fn ready_intent(
        &self,
        _: &BrokerCommand,
    ) -> std::result::Result<broker::ReadyIntent, broker::Error> {
        unreachable!()
    }
    fn order_view(
        &self,
        _: &BrokerCommand,
    ) -> std::result::Result<Option<broker::OrderView>, broker::Error> {
        unreachable!()
    }
    fn application_receipt(
        &self,
        fact: &Fact,
    ) -> std::result::Result<Option<ApplicationReceipt>, broker::Error> {
        if self.receipt_ready && self.applied.contains(fact) {
            return ApplicationReceipt::new(
                fact,
                "applied".to_owned(),
                "c".repeat(64),
                broker::ApplicationStatus::Applied,
            )
            .map(Some);
        }
        Ok(None)
    }
}

impl DurableEconomicOwner for Owner {
    fn binding(&self) -> &TradingBinding {
        &self.binding
    }
}

fn report(scope: &Scope, n: u64, state: &str) -> Fact {
    Fact::decode(&json!({"scope":scope.record(), "session":"session", "update_id":format!("update-{n}"), "source_sequence":n, "ts_event":n, "ts_init":n, "correlation":"connection", "causation":"venue", "quality":[], "kind":"CONNECTION", "payload":{"state":state}})).unwrap()
}

fn execution() -> VirtualExecution<Owner, JournaledVirtualVenue<Store, Venue>> {
    let mut config = crate::support::config();
    config["runtime_kind"] = json!("SIM");
    let scope = Scope::decode(&json!({"engine":config["engine"],"runtime":config["runtime"],"gateway":config["gateway"],"account":config["account"],"generation":config["generation"],"runtime_kind":config["runtime_kind"]})).unwrap();
    let binding = TradingBinding::new(
        crate::RunConfiguration::from_record(config).unwrap(),
        &"b".repeat(64),
    )
    .unwrap();
    let reports = vec![report(&scope, 1, "CONNECTED"), report(&scope, 2, "READY")];
    let venue = Venue {
        scope: scope.clone(),
        reports,
    };
    VirtualExecution::new(
        Owner {
            scope,
            binding,
            applied: vec![],
            unavailable: false,
            receipt_ready: true,
        },
        JournaledVirtualVenue::new(Store::default(), venue, 2).unwrap(),
    )
    .unwrap()
}

#[test]
fn only_original_published_reports_apply_in_order_and_acknowledged_replays_are_inert() {
    let mut execution = execution();
    let first = report(execution.scope(), 1, "CONNECTED");
    let second = report(execution.scope(), 2, "READY");
    let forged = report(execution.scope(), 3, "FAILED");
    assert_eq!(
        execution.observe_venue(&forged).unwrap_err().to_string(),
        "TRADING_VENUE_UNOBSERVED"
    );
    assert_eq!(
        execution.observe_venue(&second).unwrap_err().to_string(),
        "TRADING_VENUE_OUT_OF_ORDER"
    );
    let mut raw = first.record();
    raw["ts_init"] = json!(9);
    let reordered = Fact::decode(&raw).unwrap();
    assert_eq!(first.fingerprint(), reordered.fingerprint());
    assert_eq!(
        execution.observe_venue(&reordered).unwrap_err().to_string(),
        "BROKER_FACT_PROVENANCE"
    );
    assert!(execution.owner.applied.is_empty());
    assert_eq!(execution.pending_venue().unwrap(), Some(first.clone()));
    execution.observe_venue(&first).unwrap();
    execution.owner.unavailable = true;
    assert_eq!(
        execution.observe_venue(&reordered).unwrap_err().to_string(),
        "BROKER_FACT_PROVENANCE"
    );
    execution.observe_venue(&first).unwrap();
    execution.owner.unavailable = false;
    assert_eq!(execution.pending_venue().unwrap(), Some(second.clone()));
    execution.observe_venue(&second).unwrap();
    assert_eq!(execution.pending_venue().unwrap(), None);
    let (owner, venue) = execution.into_parts();
    assert_eq!(owner.applied, [first.clone(), second]);
    assert_eq!(venue.journal.rows.len(), 3);
    let recovered = Broker::recover(owner.scope, &venue.journal, 2).unwrap();
    assert_eq!(
        ObservationState::from_broker(&recovered, &first).unwrap(),
        Some(ObservationState::Acknowledged)
    );
    assert_eq!(
        ObservationState::from_broker(&recovered, &reordered)
            .unwrap_err()
            .to_string(),
        "BROKER_FACT_PROVENANCE"
    );
    assert!(!recovered.has_observed(&forged).unwrap());
}

#[test]
fn journal_read_economic_apply_and_missing_receipt_failures_preserve_the_original_head() {
    let mut execution = execution();
    let first = execution.pending_venue().unwrap().unwrap();
    execution.venue.journal.unavailable = true;
    assert_eq!(
        execution.observe_venue(&first).unwrap_err().to_string(),
        "STORE_UNAVAILABLE"
    );
    execution.venue.journal.unavailable = false;
    execution.owner.unavailable = true;
    assert_eq!(
        execution.observe_venue(&first).unwrap_err().to_string(),
        "ECONOMIC_UNAVAILABLE"
    );
    assert!(execution.owner.applied.is_empty());
    execution.owner.unavailable = false;
    execution.owner.receipt_ready = false;
    assert_eq!(
        execution.observe_venue(&first).unwrap_err().to_string(),
        "BROKER_APPLICATION_NOT_READY"
    );
    assert_eq!(execution.pending_venue().unwrap(), Some(first.clone()));
    assert_eq!(execution.venue.journal.rows.len(), 1);
    execution.owner.receipt_ready = true;
    execution.observe_venue(&first).unwrap();
    assert_eq!(execution.owner.applied, [first]);
    assert_eq!(execution.venue.journal.rows.len(), 2);
}

#[test]
fn prefix_query_rejects_foreign_scope_changed_payload_and_a_conflicted_journal() {
    let mut execution = execution();
    let first = execution.pending_venue().unwrap().unwrap();
    let changed = report(execution.scope(), 1, "FAILED");
    let mut raw = first.record();
    raw["scope"]["generation"] = json!("e".repeat(64));
    let foreign = Fact::decode(&raw).unwrap();
    let (broker, journal, _) = execution.venue.parts_mut();
    assert_eq!(
        broker.has_observed(&foreign).unwrap_err().to_string(),
        "BROKER_FACT_SCOPE"
    );
    assert_eq!(
        broker.has_observed(&changed).unwrap_err().to_string(),
        "BROKER_FACT_CONFLICT"
    );
    assert!(broker.has_observed(&first).unwrap());
    assert_eq!(
        broker.ingest(journal, &[changed]).unwrap_err().to_string(),
        "BROKER_FACT_CONFLICT"
    );
    assert_eq!(
        broker.has_observed(&first).unwrap_err().to_string(),
        "BROKER_FACT_CONFLICT"
    );
}
