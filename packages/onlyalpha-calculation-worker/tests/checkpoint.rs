use onlyalpha_calculation::{CalculationState, ExecutionBinding};
use onlyalpha_calculation_worker::{Checkpoint, fingerprint};
use serde_json::{Value, json};
fn bundle() -> Value {
    let binding = ExecutionBinding::new(
        std::array::from_fn(|_| "a".repeat(64)),
        "runtime/cluster/sma",
    )
    .unwrap();
    let mut state = CalculationState::new(binding);
    let batch = state.prepare(&["1"], &"b".repeat(64)).unwrap();
    let mut cursor = state.cursor().capture();
    cursor["revision"] = json!(1);
    cursor["samples"] = json!(1);
    cursor["last_event_ns"] = json!("1");
    state.commit(&batch, &json!({"cursor":cursor,"input_digest":"b".repeat(64),"outputs":{"value":{"type":"DECIMAL","value":"1"}},"ready":false,"quality_flags":[]})).unwrap();
    json!({"schema_version":2,"state":state.capture(),"worker":{"schema_version":1,"cursor":cursor,"plugin_state":{"snapshot":{"indicator_id":"runtime/cluster/sma","ts_event_ns":1,"samples":1,"ready":false,"value":"1.000000000000"}}}})
}
fn decode(v: &Value) -> Result<Checkpoint, onlyalpha_calculation_worker::WorkerError> {
    let raw = v.to_string();
    Checkpoint::from_bytes(raw.as_bytes(), &fingerprint(raw.as_bytes()))
}
#[test]
fn paired_checkpoint_rejects_nested_relations_even_with_matching_byte_digest() {
    let valid = bundle();
    let saved = decode(&valid).unwrap();
    assert_eq!(saved.to_bytes(), valid.to_string().as_bytes());
    assert!(Checkpoint::from_bytes(&saved.to_bytes(), &"c".repeat(64)).is_err());
    for field in [
        "value",
        "ready",
        "samples",
        "scope",
        "time",
        "cursor",
        "state_binding",
        "state_outcome",
        "extra",
        "old_schema",
    ] {
        let mut v = valid.clone();
        match field {
            "value" => v["worker"]["plugin_state"]["snapshot"]["value"] = json!("2"),
            "ready" => v["worker"]["plugin_state"]["snapshot"]["ready"] = json!(true),
            "samples" => v["worker"]["plugin_state"]["snapshot"]["samples"] = json!(2),
            "scope" => v["worker"]["plugin_state"]["snapshot"]["indicator_id"] = json!("foreign"),
            "time" => v["worker"]["plugin_state"]["snapshot"]["ts_event_ns"] = json!(2),
            "cursor" => v["worker"]["cursor"]["revision"] = json!(2),
            "state_binding" => v["state"]["cursor"]["binding"]["scope"] = json!("foreign"),
            "state_outcome" => v["state"]["outcome"] = json!("READY"),
            "extra" => v["extra"] = Value::Null,
            _ => v = v["worker"].clone(),
        }
        assert!(decode(&v).is_err(), "{field}");
    }
}

#[test]
fn zero_sample_checkpoint_projection_is_not_an_unchecked_envelope() {
    let mut valid = bundle();
    let binding = ExecutionBinding::from_record(&valid["worker"]["cursor"]["binding"]).unwrap();
    let empty = CalculationState::new(binding);
    valid["state"] = empty.capture();
    valid["worker"]["cursor"] = empty.cursor().capture();
    valid["worker"]["plugin_state"]["snapshot"] = json!({"indicator_id":"runtime/cluster/sma","ts_event_ns":null,"samples":0,"ready":false,"value":null});
    decode(&valid).unwrap();
    for field in [
        "samples",
        "indicator_id",
        "ready",
        "ts_event_ns",
        "value",
        "extra",
    ] {
        let mut bad = valid.clone();
        bad["worker"]["plugin_state"]["snapshot"][field] = match field {
            "samples" => json!(1),
            "indicator_id" => json!("foreign"),
            "ready" => json!(true),
            "ts_event_ns" => json!(0),
            "value" => json!("1"),
            _ => Value::Null,
        };
        assert!(decode(&bad).is_err(), "{field}");
    }
}
#[test]
fn nonempty_sma_checkpoint_cannot_claim_a_null_result() {
    let mut malformed = bundle();
    malformed["worker"]["plugin_state"]["snapshot"]["value"] = Value::Null;
    malformed["state"]["receipt"]["outputs"]["value"] = json!({"type":"NULL","value":null});
    assert!(decode(&malformed).is_err());
}
