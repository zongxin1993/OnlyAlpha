//! 受控场所驱动。准入与确认均从实际 SQLite Runtime 的 Ready 前缀读取。
use onlyalpha_broker as broker;
use onlyalpha_broker::ConnectionPort;
use onlyalpha_broker_virtual::{BoundVirtualActor, VirtualBroker};
use onlyalpha_domain::{base::OnlyDomainModel, value::OnlyMoney};
use onlyalpha_runtime::Runtime;
use serde_json::{Value, json};
use std::path::Path;

pub(super) const ORDER: &str = "runtime-ORDER-000001";

pub(super) fn order_row(runtime: &Runtime) -> Value {
    let (components, _) = runtime.fork_ready().unwrap();
    let checkpoint = components.checkpoint().unwrap();
    checkpoint["components"][0]["state"]["orders"][0].clone()
}

pub(super) struct Venue {
    pub(super) simulation: BoundVirtualActor,
    pub(super) protocol: broker::Broker,
    pub(super) journal: onlyalpha_runtime::BoundBrokerJournal,
    scope: broker::Scope,
    cash: OnlyMoney,
    configuration: Value,
    artifact: String,
}
impl Venue {
    pub(super) fn binding(scope: broker::Scope, currency: &Value, cash: &str) -> String {
        let cash =
            OnlyMoney::from_record(&json!({"schema_version":1,"amount":cash,"currency":currency}))
                .unwrap();
        let origin = VirtualBroker::new(
            scope,
            &"f".repeat(64),
            cash,
            &json!({"maximum_fill_quantity":"0.001"}),
        )
        .unwrap();
        broker::digest(origin.source_binding())
    }
    pub(super) fn create(root: &Path, scope: broker::Scope, currency: &Value, cash: &str) -> Self {
        let configuration = json!({"maximum_fill_quantity":"0.001"});
        let cash =
            OnlyMoney::from_record(&json!({"schema_version":1,"amount":cash,"currency":currency}))
                .unwrap();
        let artifact = "f".repeat(64);
        let binding = Self::binding(
            scope.clone(),
            currency,
            cash.to_record()["amount"].as_str().unwrap(),
        );
        let mut simulation = BoundVirtualActor::create(
            root,
            scope.clone(),
            &artifact,
            cash.clone(),
            &configuration,
            &binding,
        )
        .unwrap();
        let journal = onlyalpha_runtime::BoundBrokerJournal::open(root, &binding).unwrap();
        simulation.connect().unwrap();
        simulation.authenticate().unwrap();
        let mut protocol = broker::Broker::recover(scope.clone(), &journal, 32).unwrap();
        protocol.set_connection(broker::Connection::Ready);
        protocol.set_health(true, true, true);
        Self {
            simulation,
            protocol,
            journal,
            scope,
            cash,
            configuration,
            artifact,
        }
    }
    pub(super) fn command(&self, runtime: &Runtime, request: &Value) -> broker::BrokerCommand {
        let snapshot = order_row(runtime);
        broker::BrokerCommand::decode(&json!({"schema_version":1,"scope":self.scope.record(),"operation":"SUBMIT","command_id":"submit",
                "order":ORDER,"client":snapshot["snapshot"]["client_order_id"]["value"],"request":request})).unwrap()
    }
    pub(super) fn dispatch_losing_receipt(&mut self, runtime: &Runtime, request: &Value) {
        struct LoseReply<'a>(&'a mut BoundVirtualActor);
        impl broker::TradingPort for LoseReply<'_> {
            fn capabilities(&self) -> broker::Capabilities {
                self.0.capabilities()
            }
            fn check_dispatch(&self, i: &broker::ReadyIntent) -> Result<(), broker::Error> {
                self.0.check_dispatch(i)
            }
            fn dispatch(
                &mut self,
                c: &broker::BrokerCommand,
            ) -> Result<broker::DispatchResult, broker::Error> {
                self.0.dispatch(c)?;
                Err(broker::Error::new("TEST_LOST_SOURCE_RESPONSE"))
            }
        }
        let command = self.command(runtime, request);
        assert_eq!(
            self.journal
                .dispatch(
                    &mut self.protocol,
                    runtime,
                    &mut LoseReply(&mut self.simulation),
                    &command
                )
                .unwrap(),
            broker::CommandState::Unknown
        );
        let original = self.simulation.checkpoint();
        assert_eq!(
            self.journal
                .dispatch(&mut self.protocol, runtime, &mut self.simulation, &command)
                .unwrap(),
            broker::CommandState::Unknown
        );
        assert_eq!(self.simulation.checkpoint(), original);
    }
    pub(super) fn dispatch(&mut self, runtime: &Runtime, request: &Value) {
        let command = self.command(runtime, request);
        assert_eq!(
            self.journal
                .dispatch(&mut self.protocol, runtime, &mut self.simulation, &command)
                .unwrap(),
            broker::CommandState::Known
        );
        self.simulation.advance(self.simulation.now()).unwrap();
    }
    pub(super) fn pending(&mut self) -> Vec<broker::Fact> {
        self.simulation
            .publish(&mut self.protocol, &mut self.journal)
            .unwrap();
        self.protocol.pending().to_vec()
    }
    pub(super) fn acknowledge(&mut self, runtime: &Runtime, fact: &broker::Fact) {
        self.journal
            .acknowledge_original(&mut self.protocol, runtime, fact.identity())
            .unwrap();
    }
    pub(super) fn restore(self, root: &Path) -> Self {
        let cp = self.simulation.checkpoint();
        let Self {
            simulation,
            protocol,
            journal,
            scope,
            cash,
            configuration,
            artifact,
        } = self;
        drop((simulation, protocol));
        let binding = broker::digest(&cp["binding"]);
        let mut simulation = BoundVirtualActor::open(
            root,
            scope.clone(),
            &artifact,
            cash.clone(),
            &configuration,
            &binding,
        )
        .unwrap();
        assert_eq!(simulation.checkpoint(), cp);
        simulation.connect().unwrap();
        simulation.authenticate().unwrap();
        let mut protocol = broker::Broker::recover(scope.clone(), &journal, 32).unwrap();
        protocol.set_connection(broker::Connection::Ready);
        protocol.set_health(true, true, true);
        Self {
            simulation,
            protocol,
            journal,
            scope,
            cash,
            configuration,
            artifact,
        }
    }
    pub(super) fn observe_economic_prefix(&mut self) {
        let key = self
            .simulation
            .observe_command(broker::source::QueryPhase::Discovery, "submit")
            .unwrap();
        self.journal
            .reconcile_original(&mut self.protocol, "submit", &key)
            .unwrap();
    }
    pub(super) fn journal_rows(&self) -> Vec<Value> {
        use broker::Journal;
        self.journal
            .records()
            .unwrap()
            .iter()
            .map(broker::Record::record)
            .collect()
    }
}
