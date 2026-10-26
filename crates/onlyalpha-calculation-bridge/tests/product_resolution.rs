use onlyalpha_calculation::Definition;
use onlyalpha_calculation_bridge::{StrategyNodes, Worker, WorkerError};
use onlyalpha_gateway_protocol::{
    CalculationRecord, CalculationRequest, CalculationResponse, calculation_request,
    calculation_response,
};
use onlyalpha_strategy::NodeFailure;
use prost::Message;
use serde_json::{Value, json};
use std::{
    io::{Read, Write},
    os::unix::net::UnixStream,
    thread,
    time::Duration,
};

const DEADLINE: Duration = Duration::from_secs(2);
fn request() -> Value {
    json!({"schema_version":1,"op":"RESOLVE","reference":{"kind":"INDICATOR","type_id":"example.indicator","semantic_version":"1"},"parameters":{},"input_bindings":{}})
}
fn response() -> Value {
    let native = json!({"schema_version":2,"kind":"INDICATOR","type_id":"example.indicator","semantic_version":"1",
        "parameters":{},"inputs":[],"input_bindings":{},
        "outputs":[{"name":"value","data_type":"DECIMAL","nullable":true,"dimensions":["TIME"],"semantic_type":"NUMERIC_SERIES","unit":null}],
        "warmup":{"minimum_observations":1,"ready_condition":"samples >= 1","pre_ready_output":"NULL","initialization":"first sample"},
        "missing_values":"FAIL","timestamp":"EVENT_TIME","numeric":{"representation":"DECIMAL","precision":28,"output_quantum":null,"rounding":"CONTEXT"},"factor_kind":null,"extensions":{}});
    let mut descriptor = native.clone();
    descriptor.as_object_mut().unwrap().remove("schema_version");
    descriptor.as_object_mut().unwrap().remove("input_bindings");
    descriptor.as_object_mut().unwrap().remove("warmup");
    descriptor.as_object_mut().unwrap().remove("extensions");
    descriptor["parameters"] = json!([]);
    descriptor["execution_shape"] = json!("TIME_SERIES");
    descriptor["semantic_bounds"] = json!({"value":null});
    let mut projected = native.clone();
    projected["schema_version"] = json!(3);
    let component = Definition::from_record(&projected).unwrap();
    json!({"schema_version":2,"type_declaration":{"schema_version":1,"descriptor":descriptor,"parameter_values":[]},"product_definition":native,
        "descriptor":{"schema_version":1,"definition":component.to_record(),"definition_fingerprint":component.fingerprint(),
            "native_definition":"4018d688ff521d036e25937b65b6cae0288dc1415e989beba987327e327c819e","implementation":"e".repeat(64),"state_capability":"STATELESS","checkpoint_schema_version":null}})
}
fn peer_response(value: Value) -> (Worker, thread::JoinHandle<()>) {
    let (socket, mut peer) = UnixStream::pair().unwrap();
    let task = thread::spawn(move || {
        let mut head = [0; 4];
        peer.read_exact(&mut head).unwrap();
        let mut data = vec![0; u32::from_be_bytes(head) as usize];
        peer.read_exact(&mut data).unwrap();
        let request = CalculationRequest::decode(&data[..]).unwrap();
        assert!(matches!(
            request.operation,
            Some(calculation_request::Operation::Node(_))
        ));
        let response = CalculationResponse {
            protocol_version: 1,
            generation: "a".repeat(64),
            sequence: 1,
            artifact_fingerprint: "b".repeat(64),
            diagnostic_compute_ns: 0,
            outcome: Some(calculation_response::Outcome::Result(CalculationRecord {
                record_json: value.to_string().into_bytes(),
            })),
        }
        .encode_to_vec();
        peer.write_all(&(response.len() as u32).to_be_bytes())
            .unwrap();
        peer.write_all(&response).unwrap();
    });
    (
        Worker::from_stream(socket, "a".repeat(64), "b".repeat(64)).unwrap(),
        task,
    )
}
#[test]
fn actual_strategy_adapter_checks_the_original_product_body_and_type_declaration() {
    let (mut worker, task) = peer_response(response());
    let resolved = StrategyNodes::resolve(&mut worker, request(), DEADLINE).unwrap();
    assert_eq!(
        resolved.native_definition,
        "4018d688ff521d036e25937b65b6cae0288dc1415e989beba987327e327c819e"
    );
    assert_eq!(
        resolved.definition.reference().type_id(),
        "example.indicator"
    );
    task.join().unwrap();
}
#[test]
fn substituted_product_type_body_projection_and_opaque_fingerprints_revoke_the_worker() {
    for (path, value) in [
        ("/schema_version", json!(1)),
        ("/product_definition/type_id", json!("example.other")),
        ("/type_declaration/descriptor/semantic_version", json!("2")),
        ("/descriptor/native_definition", json!("f".repeat(64))),
        ("/product_definition/warmup/minimum_observations", json!(2)),
        (
            "/product_definition/parameters",
            json!({"extra":{"type":"INTEGER","value":1}}),
        ),
    ] {
        let mut v = response();
        *v.pointer_mut(path).unwrap() = value;
        let (mut worker, task) = peer_response(v);
        assert!(
            matches!(
                StrategyNodes::resolve(&mut worker, request(), DEADLINE),
                Err(NodeFailure::Unknown)
            ),
            "{path}"
        );
        assert!(
            matches!(worker.handshake(DEADLINE), Err(WorkerError::Unknown(_))),
            "{path}"
        );
        task.join().unwrap();
    }
    // The requested exact type itself cannot be replaced with another valid response.
    let (mut worker, task) = peer_response(response());
    let mut r = request();
    r["reference"]["semantic_version"] = json!("2");
    assert!(matches!(
        StrategyNodes::resolve(&mut worker, r, DEADLINE),
        Err(NodeFailure::Unknown)
    ));
    task.join().unwrap();
}

#[test]
fn self_consistent_component_replacement_cannot_override_the_original_product_body() {
    let mut v = response();
    v["descriptor"]["definition"]["warmup"]["minimum_observations"] = json!(37);
    let changed = Definition::from_record(&v["descriptor"]["definition"]).unwrap();
    v["descriptor"]["definition_fingerprint"] = json!(changed.fingerprint());
    // The decoy is a valid component descriptor in its own right.
    assert!(onlyalpha_strategy::NodeDescriptor::from_record(&v["descriptor"]).is_ok());
    let (mut worker, task) = peer_response(v);
    assert!(matches!(
        StrategyNodes::resolve(&mut worker, request(), DEADLINE),
        Err(NodeFailure::Unknown)
    ));
    assert!(matches!(
        worker.handshake(DEADLINE),
        Err(WorkerError::Unknown(_))
    ));
    task.join().unwrap();
}
