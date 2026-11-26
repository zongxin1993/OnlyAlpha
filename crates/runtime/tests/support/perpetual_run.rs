use onlyalpha_broker::Scope;
use onlyalpha_broker_virtual::{MemoryVirtualActor, VirtualBroker};
use onlyalpha_domain::{
    base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp, value::OnlyMoney,
};
use onlyalpha_execution::{Error, MarketSourceCut, funding_boundary};
use onlyalpha_runtime::{RunBinding, RunConfiguration, Session, TradingInput};
use serde_json::{Value, json};

const EXAMPLE: &str = include_str!("../../../../test-data/execution/linear-perpetual.json");

pub(super) fn scenario() -> (Value, Vec<Value>) {
    let mut s: Value = serde_json::from_str(EXAMPLE).unwrap();
    let mut cfg = s["config"].take();
    let inputs = s["inputs"].as_array().unwrap().clone();
    bind_offline_source(&mut cfg, &inputs);
    (cfg, inputs)
}
pub(super) fn artifact() -> String {
    "e".repeat(64)
}
// 离线源把原始经济行与从它得到的规范事实一起冻结；固定源切口即唯一输入。
pub(super) fn bind_offline_source(cfg: &mut Value, inputs: &[Value]) {
    bind_venue(cfg, inputs);
    let mut rows = Vec::new();
    for input in inputs.iter().filter(|v| v["op"] == "MARK") {
        let mark = &input["payload"]["fact"];
        let rate = inputs
            .iter()
            .find(|v| v["op"] == "FUNDING" && v["payload"]["mark_fact_id"] == mark["fact_id"])
            .map(|v| &v["payload"]["fact"]);
        let mut facts = vec![mark.clone()];
        let mut raw = json!({"at":mark["ts_event"],"price":mark["value"]["value"]});
        if let Some(rate) = rate {
            raw["rate"] = rate["rate"].clone();
            facts.push(rate.clone());
        }
        let raw = raw.to_string();
        rows.push(json!({"raw":raw,"raw_sha256":onlyalpha_execution::digest(raw.as_bytes()),"facts":facts}));
    }
    cfg["perpetual"]["source_cut_sha256"] = json!(onlyalpha_execution::digest(
        &serde_json::to_vec(&rows).unwrap()
    ));
    cfg["perpetual"]["source_rows"] = json!(rows);
}
pub(super) fn venue_config(inputs: &[Value]) -> (Scope, OnlyMoney, Value) {
    let scope = Scope::decode(&inputs[3]["payload"]["broker"]["record"]["scope"]).unwrap();
    let cash=OnlyMoney::from_record(&json!({"schema_version":1,"currency":{"schema_version":1,"currency_type":"FIAT","code":"USD","precision":8},"amount":"1000000.00000000"})).unwrap();
    let original = &inputs[1]["payload"]["request"]["quantity"]["value"];
    let first = &inputs[4]["payload"]["broker"]["record"]["payload"]["fill"]["quantity"]["value"];
    let cfg = if original == first {
        json!({})
    } else {
        json!({"maximum_fill_quantity":first})
    };
    (scope, cash, cfg)
}
pub(super) fn bind_venue(cfg: &mut Value, inputs: &[Value]) {
    let (scope, cash, settings) = venue_config(inputs);
    let source = VirtualBroker::new(scope, &"f".repeat(64), cash, &settings).unwrap();
    cfg["perpetual"]["execution_source_binding"] =
        json!(onlyalpha_broker::digest(source.source_binding()));
}
pub(super) fn venue_bar(request: &Value, sequence: u64, event: i64) -> OnlyBar {
    let time = |at: i64| {
        OnlyTimestamp::from_unix_nanos(at.into())
            .to_datetime()
            .unwrap()
            .to_string()
    };
    let mut record = serde_json::from_str::<Value>(EXAMPLE).unwrap()["venue_bar"].clone();
    let end = event - 60_000_000 + 1_000 * i64::try_from(sequence).unwrap();
    record["bar_start"] = json!(time(end - 60_000_000_000));
    record["bar_end"] = json!(time(end));
    record["ts_event"] = json!(time(event));
    record["ts_init"] = record["ts_event"].clone();
    record["trading_day"] = json!(&time(event)[..10]);
    record["bar_type"]["instrument_id"] = request["instrument_id"].clone();
    for k in ["open", "high", "low", "close"] {
        record[k] = request["price"].clone();
    }
    OnlyBar::from_record(&record).unwrap()
}

/// 内存驱动的一步：接受输入，或测试直接对内存场所做的操作。
enum Step {
    Input(Value),
    Bar(u64, Box<OnlyBar>),
    Dispatch(onlyalpha_broker::BrokerCommand),
    Advance(i64),
    Publish,
}

/// 内存驱动的有限工作：Session 持有经济状态，MemoryVirtualActor 承担原始场所。
/// 丢失即按同一冻结输入确定性重算，不存在可重新读取的持久前缀。
pub(super) struct Driver {
    pub(super) session: Session,
    pub(super) venue: MemoryVirtualActor,
    pub(super) cut: MarketSourceCut,
    config: Value,
    inputs: Vec<Value>,
    scope: Scope,
    order: Option<String>,
    close: bool,
    orchestrate: bool,
    applied: Vec<Value>,
    steps: Vec<Step>,
}
impl Driver {
    pub(super) fn prefix(cfg: &Value, inputs: &[Value], cut: usize) -> Self {
        Self::build(cfg, inputs, cut, true, true)
    }
    pub(super) fn prefix_closing(
        cfg: &Value,
        inputs: &[Value],
        prefix: usize,
        close: bool,
    ) -> Self {
        Self::build(cfg, inputs, prefix, close, true)
    }
    /// 只建立准入所需的配置与证据，不向内存场所派发命令。
    fn build(
        cfg: &Value,
        inputs: &[Value],
        prefix: usize,
        close: bool,
        orchestrate: bool,
    ) -> Self {
        let (scope, cash, settings) = venue_config(inputs);
        let binding = cfg["perpetual"]["execution_source_binding"]
            .as_str()
            .unwrap();
        let mut venue =
            MemoryVirtualActor::new(scope.clone(), &"f".repeat(64), cash, &settings, binding).unwrap();
        venue.connect().unwrap();
        venue.authenticate().unwrap();
        let configuration = RunConfiguration::from_record(cfg.clone()).unwrap();
        let pins = RunBinding::new(
            &configuration,
            &artifact(),
            &"c".repeat(64),
            &"d".repeat(64),
        )
        .unwrap();
        let session = Session::new(&configuration, &pins).unwrap();
        let cut = MarketSourceCut::read(
            &serde_json::to_vec(&cfg["perpetual"]["source_rows"]).unwrap(),
            cfg["perpetual"]["source_cut_sha256"].as_str().unwrap(),
        )
        .unwrap();
        let mut driver = Self {
            session,
            venue,
            cut,
            config: cfg.clone(),
            inputs: inputs.to_vec(),
            scope,
            order: None,
            close,
            orchestrate,
            applied: Vec::new(),
            steps: Vec::new(),
        };
        for input in &inputs[..prefix] {
            driver.apply(input).unwrap();
        }
        driver
    }
    /// 按同一配置和已执行步骤从头重算；这是内存工作唯一的恢复语义。
    pub(super) fn recompute(&self) -> Self {
        let mut restored =
            Self::build(&self.config, &self.inputs, 0, self.close, self.orchestrate);
        for (index, step) in self.steps.iter().enumerate() {
            match step {
                Step::Input(input) => {
                    if let Err(e) = restored.apply(input) {
                        fail(index, e);
                    }
                }
                Step::Bar(sequence, bar) => {
                    if let Err(e) = restored.bar(*sequence, bar) {
                        fail(index, e);
                    }
                }
                Step::Dispatch(command) => {
                    if let Err(e) = restored.dispatch(command) {
                        fail(index, e);
                    }
                }
                Step::Advance(at) => {
                    if let Err(e) = restored.advance(*at) {
                        fail(index, e);
                    }
                }
                Step::Publish => {
                    if let Err(e) = restored.publish() {
                        fail(index, e);
                    }
                }
            }
        }
        restored
    }
    /// 已接受并生效的有限输入前缀；被拒绝的输入不得改变它。
    pub(super) fn applied(&self) -> &[Value] {
        &self.applied
    }
    /// 会话实际保留的事实数；幂等重放不增加。
    pub(super) fn retained(&self) -> usize {
        self.session.retained_facts().len()
    }
    pub(super) fn state(&self) -> Result<Value, Error> {
        self.session.state()
    }
    pub(super) fn position_order_view(&self) -> Result<Value, Error> {
        self.session.position_order_view()
    }
    pub(super) fn order(&self, cluster: &str, order: &str) -> Result<Value, Error> {
        self.session.order(cluster, order)
    }
    pub(super) fn now(&self) -> i64 {
        self.venue.now()
    }
    pub(super) fn advance(&mut self, at: i64) -> Result<(), Error> {
        self.venue.advance(at).map_err(broker)?;
        self.steps.push(Step::Advance(at));
        Ok(())
    }
    pub(super) fn publish(&mut self) -> Result<usize, Error> {
        let count = self.venue.publish().map_err(broker)?;
        self.steps.push(Step::Publish);
        Ok(count)
    }
    pub(super) fn dispatch(
        &mut self,
        command: &onlyalpha_broker::BrokerCommand,
    ) -> Result<(), Error> {
        self.venue
            .dispatch(&self.session, command)
            .map(|_| ())
            .map_err(broker)?;
        self.steps.push(Step::Dispatch(command.clone()));
        Ok(())
    }
    pub(super) fn bar(&mut self, sequence: u64, bar: &OnlyBar) -> Result<(), Error> {
        self.venue.on_bar(sequence, bar).map_err(broker)?;
        self.steps.push(Step::Bar(sequence, Box::new(bar.clone())));
        Ok(())
    }
    pub(super) fn pending(&self) -> &[onlyalpha_broker::Fact] {
        self.venue.pending()
    }
    pub(super) fn apply(&mut self, input: &Value) -> Result<u64, Error> {
        let original = matches!(
            input["op"].as_str(),
            Some("MARK" | "FUNDING" | "ACCEPT" | "FILL" | "TERMINAL")
        );
        let event = if original {
            let source = if input["op"] == "FUNDING" {
                Some(self.venue.funding_history(
                    funding_boundary(&input["payload"]["fact"])?,
                    input["time"].as_u64().unwrap(),
                ).map_err(broker)?)
            } else {
                None
            };
            self.session.apply_original(
                &TradingInput::from_record(input.clone())?,
                &self.cut,
                self.venue.broker(),
                source.as_ref(),
            )?
        } else {
            self.session
                .apply(&TradingInput::from_record(input.clone())?)?
        };
        let sequence = event.sequence();
        self.session.acknowledge(sequence)?;
        if input["op"] == "ADMIT" {
            let order = input["payload"]["order"].as_str().unwrap();
            if self.order.is_none() {
                self.order = Some(order.to_owned());
            }
            if self.orchestrate && self.order.as_deref() == Some(order) {
                self.submit(input)?;
            }
        }
        if let Some(id) = input["payload"]["broker"]["id"].as_str() {
            self.venue.acknowledge(&self.session, id).map_err(broker)?;
        }
        self.applied.push(input.clone());
        self.steps.push(Step::Input(input.clone()));
        Ok(sequence)
    }
    fn submit(&mut self, input: &Value) -> Result<(), Error> {
        let order = input["payload"]["order"].as_str().unwrap();
        let request = input["payload"]["request"].clone();
        let snapshot = self.session.order("cluster", order)?;
        let command = onlyalpha_broker::BrokerCommand::decode(&json!({
            "schema_version":1,
            "scope":self.scope.record(),
            "operation":"SUBMIT",
            "command_id":"original-submit",
            "order":order,
            "client":snapshot["client_order_id"]["value"],
            "request":request
        })).map_err(broker)?;
        let at = input["time"].as_i64().unwrap();
        self.venue.advance(at).map_err(broker)?;
        self.venue.dispatch(&self.session, &command).map_err(broker)?;
        self.venue.advance(at).map_err(broker)?;
        for (index, fill) in self
            .inputs
            .iter()
            .filter(|v| v["op"] == "FILL")
            .enumerate()
        {
            let sequence = u64::try_from(index).unwrap() + 1;
            let event = fill["payload"]["broker"]["record"]["ts_event"]
                .as_i64()
                .unwrap();
            self.venue
                .on_bar(sequence, &venue_bar(&request, sequence, event))
                .map_err(broker)?;
        }
        self.venue.publish().map_err(broker)?;
        let expected = self
            .inputs
            .iter()
            .filter(|i| matches!(i["op"].as_str(), Some("ACCEPT" | "FILL" | "TERMINAL")))
            .map(|i| i["payload"]["broker"]["record"].clone())
            .collect::<Vec<_>>();
        assert_eq!(
            self.venue
                .pending()
                .iter()
                .map(onlyalpha_broker::Fact::record)
                .collect::<Vec<_>>(),
            expected
        );
        if self.close
            && let Some(funding) = self.inputs.iter().find(|i| i["op"] == "FUNDING")
        {
            let through = i64::try_from(funding_boundary(&funding["payload"]["fact"])?).unwrap();
            if self.venue.now() <= through {
                self.venue.advance(through + 1).map_err(broker)?;
            }
        }
        Ok(())
    }
}
fn broker(e: impl std::fmt::Display) -> Error {
    Error(e.to_string())
}
fn fail(index: usize, e: Error) -> ! {
    panic!("recompute step {index} failed: {e}")
}
