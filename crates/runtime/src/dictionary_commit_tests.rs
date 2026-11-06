//! Same-call canonical data reuse, never a Source, Record or Ready grant.
use super::*;
use onlyalpha_execution::coordinate;
const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[path = "../../execution/tests/support/mod.rs"]
mod support;

fn plans() -> (Prepared, Prepared) {
    let mut history = support::Harness::new(support::config()).unwrap();
    let first = history.prepare(&support::open(1, "BUY")).unwrap();
    coordinate(&mut history.store, &mut history.components, &first).unwrap();
    let second = history.prepare(&support::stage(2, 1, "UNKNOWN")).unwrap();
    (first, second)
}
fn summary(prepared: &Prepared) -> Value {
    json!({"kind":"EXECUTION_PREPARED","sequence":prepared.sequence(),"input_id":prepared.input()["input_id"]})
}
fn reset() {
    CANONICAL_VALUE_READS.with(|n| n.set(0));
    KNOWN_BYTE_MATCHES.with(|n| n.set(0));
    crate::codec::DECODED_BYTES.with(|n| n.set(0));
}
#[test]
fn exact_known_bytes_skip_only_the_second_tree_and_keep_actual_anchor_and_full_decompression() {
    let (first, second) = plans();
    let encoded = first.encode().unwrap();
    let raw = encode_bytes(&encoded, summary(&first), 1, None).unwrap();
    let frame = inspect(&raw, &digest(raw.as_bytes()), 1).unwrap();
    reset();
    let (value, anchor) = decode_for_commit(&frame, None, &first).unwrap();
    assert!(value.is_none());
    let anchor = anchor.unwrap();
    assert_eq!(anchor.bytes(), encoded);
    assert_eq!(anchor.physical(), digest(raw.as_bytes()));
    assert_eq!(anchor.logical(), digest(&encoded));
    assert_eq!(CANONICAL_VALUE_READS.with(std::cell::Cell::get), 0);
    assert_eq!(KNOWN_BYTE_MATCHES.with(std::cell::Cell::get), 1);
    assert_eq!(
        crate::codec::DECODED_BYTES.with(std::cell::Cell::get),
        encoded.len() as u64
    );
    let delta_bytes = second.encode().unwrap();
    let delta = encode_bytes(&delta_bytes, summary(&second), 2, Some(&anchor)).unwrap();
    let delta = inspect(&delta, &digest(delta.as_bytes()), 2).unwrap();
    reset();
    let (value, next_anchor) = decode_for_commit(&delta, Some(&anchor), &second).unwrap();
    assert!(value.is_none() && next_anchor.is_none());
    assert_eq!(CANONICAL_VALUE_READS.with(std::cell::Cell::get), 0);
    assert_eq!(KNOWN_BYTE_MATCHES.with(std::cell::Cell::get), 1);
    assert_eq!(
        crate::codec::DECODED_BYTES.with(std::cell::Cell::get),
        delta_bytes.len() as u64
    );
    reset();
    assert_eq!(decode(&delta, Some(&anchor)).unwrap(), *second.value());
    assert_eq!(CANONICAL_VALUE_READS.with(std::cell::Cell::get), 1);
    assert_eq!(KNOWN_BYTE_MATCHES.with(std::cell::Cell::get), 0);
}
#[test]
fn different_known_body_uses_the_original_value_reader_before_full_value_comparison() {
    let (first, second) = plans();
    let raw = encode_bytes(&first.encode().unwrap(), summary(&first), 1, None).unwrap();
    let frame = inspect(&raw, &digest(raw.as_bytes()), 1).unwrap();
    reset();
    let (value, anchor) = decode_for_commit(&frame, None, &second).unwrap();
    assert_eq!(value.unwrap(), *first.value());
    assert!(anchor.is_some());
    assert_eq!(CANONICAL_VALUE_READS.with(std::cell::Cell::get), 1);
    assert_eq!(KNOWN_BYTE_MATCHES.with(std::cell::Cell::get), 0);
}
#[test]
fn same_sequence_with_a_different_valid_body_uses_the_original_value_reader() {
    let mut history = support::Harness::new(support::config()).unwrap();
    let first_input = support::open(1, "BUY");
    let first = history.prepare(&first_input).unwrap();
    let mut changed_first_input = first_input;
    changed_first_input["source_ref"] = json!("different-source-1");
    let different_first = history.prepare(&changed_first_input).unwrap();
    coordinate(&mut history.store, &mut history.components, &first).unwrap();

    let second_input = support::stage(2, 1, "UNKNOWN");
    let second = history.prepare(&second_input).unwrap();
    let mut changed_second_input = second_input;
    changed_second_input["source_ref"] = json!("different-source-2");
    let different_second = history.prepare(&changed_second_input).unwrap();

    let first_raw = encode_bytes(&first.encode().unwrap(), summary(&first), 1, None).unwrap();
    let first_frame = inspect(&first_raw, &digest(first_raw.as_bytes()), 1).unwrap();
    let (_, anchor) = decode_anchor(&first_frame).unwrap();
    let second_raw = encode_bytes(
        &second.encode().unwrap(),
        summary(&second),
        2,
        Some(&anchor),
    )
    .unwrap();
    let second_frame = inspect(&second_raw, &digest(second_raw.as_bytes()), 2).unwrap();

    for (frame, base, actual, known) in [
        (&first_frame, None, &first, &different_first),
        (&second_frame, Some(&anchor), &second, &different_second),
    ] {
        assert_eq!(actual.sequence(), known.sequence());
        assert_eq!(actual.input()["input_id"], known.input()["input_id"]);
        assert_ne!(actual.value(), known.value());
        assert_ne!(actual.encode().unwrap(), known.encode().unwrap());
        assert_eq!(
            Prepared::decode(&known.encode().unwrap()).unwrap().value(),
            known.value()
        );
        let original_value = decode(frame, base).unwrap();
        reset();

        let (value, observed_anchor) = decode_for_commit(frame, base, known).unwrap();

        // The Store's unchanged full-value comparison must receive the actual
        // body and reject it against known, rather than adopting known's body.
        assert_eq!(value.as_ref(), Some(&original_value));
        assert_eq!(value.as_ref(), Some(actual.value()));
        assert_ne!(value.as_ref(), Some(known.value()));
        assert_eq!(observed_anchor.is_some(), actual.sequence() == 1);
        if let Some(observed_anchor) = observed_anchor {
            assert_eq!(observed_anchor.bytes(), actual.encode().unwrap());
        }
        assert_eq!(CANONICAL_VALUE_READS.with(std::cell::Cell::get), 1);
        assert_eq!(KNOWN_BYTE_MATCHES.with(std::cell::Cell::get), 0);
    }
}
#[test]
fn mismatching_actual_bytes_keep_original_syntax_private_tokens_depth_and_canonical_errors() {
    let (first, _) = plans();
    let mut deep = b"null".to_vec();
    for _ in 0..140 {
        let mut next = b"[".to_vec();
        next.extend(deep);
        next.push(b']');
        deep = next;
    }
    let mut trailing = first.encode().unwrap();
    trailing.push(b' ');
    for bytes in [
        b"{".to_vec(),
        b"{ \"x\": 1}".to_vec(),
        b"{\"x\":1,\"x\":1}".to_vec(),
        b"{\"$serde_json::private::Number\":\"1\"}".to_vec(),
        b"\"\xff\"".to_vec(),
        deep,
        trailing,
    ] {
        let raw = encode_bytes(&bytes, summary(&first), 1, None).unwrap();
        let frame = inspect(&raw, &digest(raw.as_bytes()), 1).unwrap();
        let expected = decode_anchor(&frame).err().unwrap();
        reset();
        assert_eq!(
            decode_for_commit(&frame, None, &first).err().unwrap(),
            expected
        );
        assert_eq!(CANONICAL_VALUE_READS.with(std::cell::Cell::get), 1);
        assert_eq!(KNOWN_BYTE_MATCHES.with(std::cell::Cell::get), 0);
    }
}
#[test]
fn known_data_cannot_hide_changed_bases_or_physical_zstd_base64_size_or_logical_failures() {
    let (first, second) = plans();
    let raw = encode_bytes(&first.encode().unwrap(), summary(&first), 1, None).unwrap();
    let frame = inspect(&raw, &digest(raw.as_bytes()), 1).unwrap();
    let (_, anchor) = decode_anchor(&frame).unwrap();
    let delta = encode_bytes(
        &second.encode().unwrap(),
        summary(&second),
        2,
        Some(&anchor),
    )
    .unwrap();
    let mut changed: Value = serde_json::from_str(&raw).unwrap();
    changed["summary"]["another_actual_source"] = json!(true);
    let changed = changed.to_string();
    let (_, changed_anchor) =
        decode_anchor(&inspect(&changed, &digest(changed.as_bytes()), 1).unwrap()).unwrap();
    let delta_frame = inspect(&delta, &digest(delta.as_bytes()), 2).unwrap();
    assert_eq!(
        decode_for_commit(&delta_frame, Some(&changed_anchor), &second).err(),
        decode(&delta_frame, Some(&changed_anchor)).err()
    );
    assert_eq!(
        decode_for_commit(&delta_frame, None, &second).err(),
        decode(&delta_frame, None).err()
    );
    for (sequence, original, base, known) in [
        (1, raw.as_str(), None, &first),
        (2, delta.as_str(), Some(&anchor), &second),
    ] {
        for fault in [
            "truncated",
            "tail",
            "extra-frame",
            "base64",
            "size",
            "logical",
            "physical",
            "extra-key",
        ] {
            let mut value: Value = serde_json::from_str(original).unwrap();
            match fault {
                "truncated" | "tail" | "extra-frame" => {
                    let mut data = STANDARD.decode(value["data"].as_str().unwrap()).unwrap();
                    if fault == "truncated" {
                        data.pop();
                    } else if fault == "tail" {
                        data.push(0);
                    } else {
                        let extra = data.clone();
                        data.extend(extra);
                    }
                    value["data"] = json!(STANDARD.encode(data));
                }
                "base64" => value["data"] = json!("!!!!"),
                "size" => value["logical_size"] = json!(1),
                "logical" => value["logical_sha256"] = json!("f".repeat(64)),
                "extra-key" => value["extra"] = json!(true),
                _ => (),
            }
            let changed = value.to_string();
            let physical = if fault == "physical" {
                "f".repeat(64)
            } else {
                digest(changed.as_bytes())
            };
            let old = inspect(&changed, &physical, sequence).and_then(|frame| decode(&frame, base));
            reset();
            let actual = inspect(&changed, &physical, sequence)
                .and_then(|frame| decode_for_commit(&frame, base, known));
            assert_eq!(
                actual.err().unwrap(),
                old.err().unwrap(),
                "{sequence}/{fault}"
            );
            assert_eq!(KNOWN_BYTE_MATCHES.with(std::cell::Cell::get), 0);
        }
    }
}
