//! Differential accepted/rejected behavior against the original full Value reader.
use super::{FULL_VALUE_READERS, matches_value};
use serde_json::{Number, Value, json};

fn original(bytes: &[u8], expected: &Value) -> bool {
    serde_json::from_slice::<Value>(bytes).is_ok_and(|actual| actual == *expected)
}

fn check(bytes: &[u8], expected: &Value) {
    assert_eq!(
        matches_value(bytes, expected),
        original(bytes, expected),
        "reader disagreement for {} bytes, expected {expected:?}",
        bytes.len()
    );
}

fn self_roundtrip(value: &Value) {
    let bytes = serde_json::to_vec(value).unwrap();
    check(&bytes, value);
}

#[test]
fn ordinary_nested_values_use_the_mature_reader_without_a_second_value_tree() {
    let expected = json!({"array":[null,true,false,"plain","escaped\n\"\\\t","中文🙂",[],{},
        {"nested":[9007199254740993_u64,-42,0,"x"]}],"number":1.125,"object":{"a":1,"b":2}});
    let bytes = serde_json::to_vec(&expected).unwrap();
    FULL_VALUE_READERS.with(|count| count.set(0));
    for _ in 0..4 {
        assert!(matches_value(&bytes, &expected));
    }
    assert_eq!(FULL_VALUE_READERS.with(std::cell::Cell::get), 0);
    check(&bytes, &expected);
    let mut detached = expected.clone();
    detached["object"]["b"] = json!(3);
    check(&bytes, &detached);
}

#[test]
fn unchecked_numbers_keep_exact_original_lexical_and_arbitrary_precision_behavior() {
    for raw in [
        "0",
        "-0",
        "0.0",
        "-0.0",
        "1",
        "-1",
        "1.00",
        "1e0",
        "1E+00",
        "1e-0",
        "9007199254740993",
        "18446744073709551616",
        "-9223372036854775809",
        "0.1000000000000000000000000000000000000001",
        "1e400",
        "1e-400",
        "",
        "00",
        "01",
        "+1",
        "-",
        ".1",
        "1.",
        "1e",
        "1e+",
        "NaN",
        "Infinity",
        "null",
        "true",
        "\"string\"",
        "[]",
        "{}",
        "0,1",
        "0 ",
        "0,\"injected\":true",
        "{\"$serde_json::private::Number\":\"1\"}",
        "{\"$serde_json::private::RawValue\":\"1\"}",
    ] {
        let number = Value::Number(Number::from_string_unchecked(raw.into()));
        let mut object = serde_json::Map::new();
        object.insert("a".into(), number.clone());
        object.insert("z".into(), json!(1));
        for expected in [
            number.clone(),
            Value::Array(vec![number.clone()]),
            Value::Object(object),
        ] {
            self_roundtrip(&expected);
        }
        if let Ok(valid) = serde_json::from_str::<Value>(raw) {
            self_roundtrip(&valid);
            check(raw.as_bytes(), &valid);
        }
    }
}

#[test]
fn private_number_and_raw_value_objects_follow_the_original_value_visitor() {
    for token in [
        "$serde_json::private::Number",
        "$serde_json::private::RawValue",
    ] {
        for contents in [
            json!("1"),
            json!("-0.00"),
            json!("[true,null]"),
            json!("{\"x\":1}"),
            json!("{\"$serde_json::private::RawValue\":\"[1]\"}"),
            json!("invalid"),
            json!(1),
            Value::Null,
        ] {
            let mut marker = serde_json::Map::new();
            marker.insert(token.into(), contents);
            let object = Value::Object(marker);
            for expected in [
                object.clone(),
                json!([object.clone()]),
                json!({"nested":object.clone()}),
            ] {
                self_roundtrip(&expected);
            }
            let mut ordinary_first = object.clone();
            ordinary_first["!ordinary-first"] = json!(true);
            self_roundtrip(&ordinary_first);
            let mut marker_first = object;
            marker_first["z-last"] = json!(true);
            self_roundtrip(&marker_first);
        }
    }
    // Borrowing a subtree must retain Value's private RawValue reinterpretation
    // and its own inner reader, including an inner depth check when enabled.
    let mut inner = json!(null);
    for _ in 0..128 {
        inner = json!([inner]);
    }
    self_roundtrip(&json!({"$serde_json::private::RawValue":inner.to_string()}));
}

#[test]
fn array_object_and_mixed_depth_limits_are_owned_by_the_same_parser() {
    for depth in [0, 1, 126, 127, 128, 129, 140] {
        for shape in 0..3 {
            let mut expected = Value::Null;
            for index in 0..depth {
                expected = if shape == 0 || (shape == 2 && index % 2 == 0) {
                    json!([expected])
                } else {
                    json!({"a":expected})
                };
            }
            self_roundtrip(&expected);
            let bytes = serde_json::to_vec(&expected).unwrap();
            // Preserve the same nested boundary when embedded in a parent.
            let mut wrapped = b"[".to_vec();
            wrapped.extend_from_slice(&bytes);
            wrapped.push(b']');
            check(&wrapped, &json!([expected]));
        }
    }
}

#[test]
fn escapes_duplicate_keys_object_order_trailing_bytes_and_bad_syntax_match_the_oracle() {
    let expected_values = [
        Value::Null,
        json!(true),
        json!(0),
        json!(1),
        json!("a\n中文🙂"),
        json!([]),
        json!([1, 2]),
        json!({}),
        json!({"a":1}),
        json!({"a":1,"b":2}),
        json!({"x":"a\n中文🙂"}),
    ];
    let byte_inputs: &[&[u8]] = &[
        b"null",
        b"null ",
        b"null true",
        b"true",
        b"false",
        b"0",
        b"1",
        b"-0",
        b"[]",
        b"[1,2]",
        b"[1,2,]",
        b"[1]",
        b"[1,2,3]",
        b"[1,2] trailing",
        b"{}",
        b"{\"a\":1}",
        b"{\"a\":0,\"a\":1}",
        b"{\"a\":1,\"a\":0}",
        b"{\"b\":2,\"a\":1}",
        b"{\"a\":1,\"b\":2,\"a\":1}",
        b"{\"a\":1,}",
        b"\"a\\n\\u4e2d\\u6587\\ud83d\\ude42\"",
        b"{\"x\":\"a\\n\\u4e2d\\u6587\\ud83d\\ude42\"}",
        b"\"\\ud800\"",
        b"\"\\x20\"",
        b"\"\xff\"",
        b"",
        b"[",
        b"{",
        b"[[]",
        b"{\"a\" 1}",
        b"{\"$serde_json::private::Number\":\"1\"}",
        b"{\"$serde_json::private::Number\":\"1\",\"extra\":0}",
        b"{\"$serde_json::private::Number\":\"1\",\"$serde_json::private::Number\":\"1\"}",
        b"{\"$serde_json::private::Number\":\"1\"} 1",
        b"{\"$serde_json::private::RawValue\":\"1\"}",
        b"{\"$serde_json::private::RawValue\":\"1\",\"extra\":0}",
        b"{\"$serde_json::private::RawValue\":\"1\",\"$serde_json::private::RawValue\":\"1\"}",
        b"{\"$serde_json::private::RawValue\":\"1\"} 1",
    ];
    for bytes in byte_inputs {
        for expected in &expected_values {
            check(bytes, expected);
        }
        if let Ok(actual) = serde_json::from_slice::<Value>(bytes) {
            check(bytes, &actual);
        }
    }
}

#[test]
fn generated_recursive_inputs_and_single_byte_damage_match_the_original_reader() {
    let mut values = vec![
        Value::Null,
        json!(false),
        json!(true),
        json!(-0.0),
        json!("\"\\\n中文"),
        json!(9007199254740993_u64),
    ];
    for _ in 0..3 {
        let previous = values.clone();
        for value in previous {
            values.push(json!([value.clone(), null, true]));
            values.push(json!({"a":value,"b":[0,1]}));
        }
    }
    for expected in values {
        let bytes = serde_json::to_vec(&expected).unwrap();
        check(&bytes, &expected);
        for index in 0..bytes.len() {
            let mut damaged = bytes.clone();
            damaged[index] = b'#';
            check(&damaged, &expected);
        }
    }
}
