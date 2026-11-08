use super::{BoundBrokerJournal, Runtime};
use onlyalpha_broker::{ConnectionPort, Scope};
use onlyalpha_broker_virtual::{BoundVirtualActor, VirtualBroker};
use onlyalpha_domain::{
    base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp, value::OnlyMoney,
};
use serde_json::{Value, json};
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

const EXAMPLE: &str = include_str!("../../../../test-data/execution/linear-perpetual.json");
static NEXT: AtomicU64 = AtomicU64::new(0);
pub(super) struct Root(pub(super) PathBuf);
impl Root {
    pub(super) fn new() -> Self {
        let p = std::env::temp_dir().join(format!(
            "onlyalpha-runtime-linear-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&p).unwrap();
        Self(p)
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
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
// 离线源把原始经济行与从它得到的规范事实一起冻结；Runtime 另读磁盘原件。
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
pub(super) fn prepare_prefix(cfg: &Value, inputs: &[Value], cut: usize) -> (Root, Runtime) {
    prepare_venue_prefix(cfg, inputs, cut, true)
}
pub(super) fn prepare_venue_prefix(
    cfg: &Value,
    inputs: &[Value],
    cut: usize,
    close: bool,
) -> (Root, Runtime) {
    let root = Root::new();
    fs::write(
        root.0.join("market-source-cut.json"),
        serde_json::to_vec(&cfg["perpetual"]["source_rows"]).unwrap(),
    )
    .unwrap();
    let (scope, cash, settings) = venue_config(inputs);
    let binding = cfg["perpetual"]["execution_source_binding"]
        .as_str()
        .unwrap();
    let mut venue = BoundVirtualActor::create(
        &root.0,
        scope.clone(),
        &"f".repeat(64),
        cash,
        &settings,
        binding,
    )
    .unwrap();
    venue.connect().unwrap();
    venue.authenticate().unwrap();
    let mut journal = BoundBrokerJournal::open(&root.0, binding).unwrap();
    let mut broker = onlyalpha_broker::Broker::recover(scope.clone(), &journal, 512).unwrap();
    broker.set_connection(onlyalpha_broker::Connection::Ready);
    broker.set_health(true, true, true);
    let mut rt = Runtime::create(&root.0, cfg.clone(), &artifact()).unwrap();
    for v in &inputs[..cut] {
        rt.apply(v).unwrap();
        if v["op"] == "ADMIT" {
            let ready = rt.fork_ready().unwrap().0.checkpoint().unwrap();
            let row = &ready["components"][0]["state"]["orders"][0]["snapshot"];
            let req = &v["payload"]["request"];
            let command=onlyalpha_broker::BrokerCommand::decode(&json!({"schema_version":1,"scope":scope.record(),"operation":"SUBMIT","command_id":"original-submit","order":v["payload"]["order"],"client":row["client_order_id"]["value"],"request":req})).unwrap();
            let at = v["time"].as_i64().unwrap();
            venue.advance(at).unwrap();
            journal
                .dispatch(&mut broker, &rt, &mut venue, &command)
                .unwrap();
            venue.advance(at).unwrap();
            for (index, obs) in inputs.iter().filter(|i| i["op"] == "FILL").enumerate() {
                let at = obs["payload"]["broker"]["record"]["ts_event"]
                    .as_i64()
                    .unwrap();
                let seq = u64::try_from(index).unwrap() + 1;
                venue.on_bar(seq, &venue_bar(req, seq, at)).unwrap();
            }
            venue.publish(&mut broker, &mut journal).unwrap();
            let expected = inputs
                .iter()
                .filter(|i| matches!(i["op"].as_str(), Some("ACCEPT" | "FILL" | "TERMINAL")))
                .map(|i| i["payload"]["broker"]["record"].clone())
                .collect::<Vec<_>>();
            assert_eq!(
                broker
                    .pending()
                    .iter()
                    .map(onlyalpha_broker::Fact::record)
                    .collect::<Vec<_>>(),
                expected
            );
            if close && let Some(funding) = inputs.iter().find(|i| i["op"] == "FUNDING") {
                let through = i64::try_from(
                    onlyalpha_execution::funding_boundary(&funding["payload"]["fact"]).unwrap(),
                )
                .unwrap();
                if venue.now() <= through {
                    venue.advance(through + 1).unwrap();
                }
            }
        }
    }
    (root, rt)
}
