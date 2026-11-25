use super::{admit, binding, binding_for_generation, economics, node_session, serial, virtual_venue_executable};
use onlyalpha_backend::persistence::trading_facts::TradingFactRepository;
use onlyalpha_runtime::durability::{DurabilityError, DurableFactPort, RecoveryFacts, TradingBinding};
use serde_json::{Value, json};
use std::{
    io::{BufRead, BufReader, Write},
    process::{Child, ChildStdout, Command, Stdio},
};

const SUBMIT: &str = "SUBMIT_ORIGINAL_ORDER ";

fn scoped(binding: &TradingBinding, mut input: Value) -> Value {
    let config = binding.configuration().record();
    input["runtime_kind"] = config["runtime_kind"].clone();
    input["generation"] = config["generation"].clone();
    input
}

fn command(recovery: &RecoveryFacts) -> Value {
    let first = &recovery.records()[0];
    assert!(first.ready());
    let plan = first.prepared();
    let input = plan.input();
    assert_eq!(input["op"], "ADMIT");
    let snapshot = &plan.order_snapshot_data()[0]["snapshot"];
    assert_eq!(snapshot["order_id"]["value"], input["payload"]["order"]);
    let mut scope = json!({});
    for key in ["engine", "runtime", "gateway", "account", "generation", "runtime_kind"] {
        scope[key] = input[key].clone();
    }
    json!({"schema_version": 1, "scope": scope, "operation": "SUBMIT", "command_id": plan.id(),
        "order": input["payload"]["order"], "client": snapshot["client_order_id"]["value"],
        "request": input["payload"]["request"]})
}

async fn apply(repository: &mut TradingFactRepository<'_>, binding: &TradingBinding, input: &Value) {
    let original = repository.load_recovery(binding).await.unwrap();
    let prepared = original.prepare(input).unwrap();
    repository.commit(&prepared).await.unwrap();
    let committed = repository.load_recovery(binding).await.unwrap();
    assert_eq!(committed.unprojected().unwrap().prepared(), prepared.prepared());
    repository.mark_projected(&committed).await.unwrap();
}

fn read_message(output: &mut impl BufRead, marker: &str) -> Value {
    for line in output.lines() {
        if let Some((_, body)) = line.unwrap().split_once(marker) {
            return serde_json::from_str(body).unwrap();
        }
    }
    panic!("child process closed stdout before {marker}");
}

#[test]
fn compiled_virtual_venue_descriptor_satisfies_the_product_contract() {
    use onlyalpha_integration_contract::{Category, Descriptor};

    let output = Command::new(virtual_venue_executable())
        .args(["--exact", "product_descriptor", "--ignored", "--nocapture"])
        .output().unwrap();
    assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
    let mut document = read_message(&mut output.stdout.as_slice(), "VENUE_DESCRIPTOR ");
    let descriptor = Descriptor::from_json(&document.to_string(), 1024 * 1024).unwrap();
    assert_eq!(descriptor.id().value(), "onlyalpha.virtual_broker");
    assert_eq!(descriptor.category(), Category::Broker);
    assert_eq!(descriptor.configuration_fingerprint(), document["configuration_contract"]["fingerprint"].as_str().unwrap());
    document["configuration_contract"]["fields"][0]["display_name"] = json!("其他名称");
    assert!(matches!(Descriptor::from_json(&document.to_string(), 1024 * 1024), Err(onlyalpha_integration_contract::Error::Type)));
}

struct Venue {
    process: Child,
    output: BufReader<ChildStdout>,
}

impl Venue {
    fn start(binary: &std::path::Path, binding: &TradingBinding, command: &Value) -> Self {
        let mut process = Command::new(binary)
            .args(["--exact", "controlled_venue", "--ignored", "--nocapture"])
            .stdin(Stdio::piped()).stdout(Stdio::piped()).spawn().unwrap();
        let config = binding.configuration().record();
        let init = json!({"scope": command["scope"], "artifact": binding.kernel_artifact(),
            "cash": {"schema_version": 1, "amount": config["initial_cash"], "currency": config["currency"]}});
        writeln!(process.stdin.as_mut().unwrap(), "{init}").unwrap();
        let output = BufReader::new(process.stdout.take().unwrap());
        Self { process, output }
    }

    fn request(&mut self, action: &str, command: &Value) -> Value {
        let request = json!({"action": action, "command": command});
        writeln!(self.process.stdin.as_mut().unwrap(), "{request}").unwrap();
        let result = read_message(&mut self.output, "VENUE_REPLY ");
        assert_eq!(result["dispatch_calls"], 1);
        result
    }

    fn close(mut self) {
        drop(self.process.stdin.take());
        assert!(self.process.wait().unwrap().success());
    }
}

fn observed_inputs(binding: &TradingBinding, order: &Value, observed: &Value) -> [Value; 2] {
    let accepted = &observed["accepted"];
    let trade = &observed["trade"];
    for fact in [accepted, trade] {
        let record = &fact["record"];
        assert_eq!(record["scope"], order["scope"]);
        assert_eq!(record["payload"]["order"], order["order"]);
        assert_eq!(record["correlation"], order["order"]);
    }
    let source = &trade["record"]["payload"]["fill"];
    let venue_order = &accepted["record"]["payload"]["venue"];
    assert_eq!(*venue_order, source["venue_order_id"]["value"]);
    let mut accept = scoped(binding, economics::input(3, "ACCEPT", json!({
        "schema_version": 1, "order": order["order"], "venue_order": venue_order,
    })));
    accept["input_id"] = accepted["identity"].clone();
    accept["source_ref"] = accepted["fingerprint"].clone();
    let mut fill = scoped(binding, economics::fill(4, 1, source["quantity"]["value"].as_str().unwrap(),
        source["price"]["value"].as_str().unwrap(), "0.00"));
    fill["input_id"] = trade["identity"].clone();
    fill["source_ref"] = trade["fingerprint"].clone();
    let payload = &mut fill["payload"];
    payload["trade"] = source["trade_id"]["value"].clone();
    payload["venue_trade"] = source["venue_trade_id"]["value"].clone();
    payload["venue_order"] = venue_order.clone();
    for name in ["fees", "settlement", "valuation"] {
        let proof = &mut payload[name];
        if proof.get("trade").is_some() {
            proof["trade"] = source["trade_id"]["value"].clone();
        }
        proof["scope"]["runtime_kind"] = order["scope"]["runtime_kind"].clone();
        proof["scope"]["generation"] = order["scope"]["generation"].clone();
        proof.as_object_mut().unwrap().remove("source_digest");
        proof["source_digest"] = json!(onlyalpha_execution::digest(proof.to_string().as_bytes()));
    }
    [accept, fill]
}

#[tokio::test]
async fn lost_submit_response_recovers_original_virtual_fill_across_processes() {
    let _guard = serial().await;
    let binary = virtual_venue_executable();
    let binding = binding("virtual-venue");
    let mut submitter = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "trading_venue::submit_without_receipt_in_child", "--ignored", "--nocapture"])
        .env("ONLYALPHA_TEST_TRADING_GENERATION", binding.configuration().record()["generation"].as_str().unwrap())
        .stdin(Stdio::piped()).stdout(Stdio::piped()).spawn().unwrap();
    let original = read_message(&mut BufReader::new(submitter.stdout.as_mut().unwrap()), SUBMIT);
    let mut venue = Venue::start(&binary, &binding, &original);
    let unknown = venue.request("SUBMIT", &original);
    writeln!(submitter.stdin.take().unwrap(), "{unknown}").unwrap();
    assert!(submitter.wait().unwrap().success());

    let mut session = node_session().await;
    let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
    let recovered = repository.load_recovery(&binding).await.unwrap();
    assert_eq!(recovered.records().len(), 2);
    assert_eq!(recovered.records()[1].prepared().input(), &scoped(&binding, economics::stage(2, 1, "UNKNOWN")));
    let query = command(&recovered);
    assert_eq!(query, original);
    let observed = venue.request("QUERY", &query);
    let [accept, fill] = observed_inputs(&binding, &query, &observed);
    apply(&mut repository, &binding, &accept).await;
    let before_fill = repository.load_recovery(&binding).await.unwrap();
    apply(&mut repository, &binding, &fill).await;
    let settled = repository.load_recovery(&binding).await.unwrap();
    assert!(settled.unprojected().is_none());
    assert_eq!(settled.records().len(), 4);
    assert_eq!(settled.records()[2].prepared().input(), &accept);
    assert_eq!(settled.records()[3].prepared().input(), &fill);
    let state = settled.state().unwrap();
    assert_eq!(observed["cash"], "960.00");
    assert_eq!(observed["quantity"], "4");
    assert_eq!(state["account"]["snapshot"]["cash"], observed["cash"]);
    assert_eq!(state["position"]["accounts"][0]["snapshot"]["quantity"], observed["quantity"]);

    let repeated = venue.request("QUERY", &query);
    assert_eq!(repeated, observed);
    let [_, repeated_fill] = observed_inputs(&binding, &query, &repeated);
    let current = repository.load_recovery(&binding).await.unwrap();
    let existing = current.observe_input(&repeated_fill).unwrap().unwrap();
    assert_eq!(existing, &settled.records()[3]);
    let retry = before_fill.prepare(&repeated_fill).unwrap();
    let receipt = repository.commit(&retry).await.unwrap();
    assert!(receipt.ready());
    assert_eq!(receipt.transaction_id(), settled.records()[3].prepared().id());
    assert_eq!(receipt.sequence(), 4);

    let conflicting = venue.request("CONFLICTING_QUERY", &query);
    let [_, conflicting_fill] = observed_inputs(&binding, &query, &conflicting);
    assert_eq!(conflicting_fill["input_id"], fill["input_id"]);
    assert_ne!(conflicting_fill["source_ref"], fill["source_ref"]);
    assert_ne!(conflicting_fill["payload"]["price"], fill["payload"]["price"]);
    assert!(current.observe_input(&conflicting_fill).is_err());
    let conflict = before_fill.prepare(&conflicting_fill).unwrap();
    assert_eq!(repository.commit(&conflict).await.unwrap_err(),
        DurabilityError::Rejected("TRADING_FACT_CONFLICT".into()));
    let final_recovery = repository.load_recovery(&binding).await.unwrap();
    assert_eq!(final_recovery.records(), settled.records());
    assert_eq!(final_recovery.state().unwrap(), state);
    assert_eq!(venue.request("QUERY", &query), observed);
    session.close().await.unwrap();
    venue.close();
}

#[tokio::test]
#[ignore = "由受控场所恢复测试启动原提交进程"]
async fn submit_without_receipt_in_child() {
    let generation = std::env::var("ONLYALPHA_TEST_TRADING_GENERATION").unwrap();
    let binding = binding_for_generation(&generation);
    let mut session = node_session().await;
    let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
    repository.register(&binding).await.unwrap();
    let mut admission = admit(&binding);
    admission["payload"]["request"]["account_id"] = json!({"schema_version": 1, "value": admission["account"]});
    economics::refresh_market(&mut admission);
    apply(&mut repository, &binding, &admission).await;
    let original = command(&repository.load_recovery(&binding).await.unwrap());
    println!("{SUBMIT}{original}");
    std::io::stdout().flush().unwrap();
    let mut line = String::new();
    std::io::stdin().read_line(&mut line).unwrap();
    let reply: Value = serde_json::from_str(&line).unwrap();
    assert_eq!(reply["outcome"], "UNKNOWN");
    let unknown = scoped(&binding, economics::stage(2, 1, reply["outcome"].as_str().unwrap()));
    apply(&mut repository, &binding, &unknown).await;
    session.close().await.unwrap();
}
