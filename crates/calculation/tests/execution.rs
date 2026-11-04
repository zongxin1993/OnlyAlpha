use onlyalpha_calculation::{ExecutionBinding, ExecutionCursor};
fn binding() -> ExecutionBinding {
    ExecutionBinding::new(
        [
            "a".repeat(64),
            "b".repeat(64),
            "c".repeat(64),
            "d".repeat(64),
            "e".repeat(64),
            "f".repeat(64),
        ],
        "runtime/cluster/indicator",
    )
    .unwrap()
}
#[test]
fn batches_commit_only_exact_ordered_receipts() {
    let mut cursor = ExecutionCursor::new(binding());
    let batch = cursor.prepare(&["1", "2"], &"1".repeat(64)).unwrap();
    assert_eq!(cursor.revision(), 0);
    assert!(
        cursor
            .commit(&batch, &binding(), 2, &["1", "2"], 2, &"1".repeat(64))
            .is_err()
    );
    assert_eq!(cursor.revision(), 0);
    cursor
        .commit(&batch, &binding(), 1, &["1", "2"], 2, &"1".repeat(64))
        .unwrap();
    assert_eq!(cursor.revision(), 1);
    assert!(
        cursor
            .commit(&batch, &binding(), 1, &["1", "2"], 2, &"1".repeat(64))
            .is_err()
    );
    for times in [
        vec!["2"],
        vec!["4", "3"],
        vec![],
        vec!["3", "3"],
        vec!["+3"],
        vec!["03"],
    ] {
        assert!(cursor.prepare(&times, &"1".repeat(64)).is_err());
    }
}
#[test]
fn scope_and_capture_are_exact_and_bounded() {
    assert!(
        ExecutionBinding::new(
            [
                "a".repeat(64),
                "b".repeat(64),
                "c".repeat(64),
                "d".repeat(64),
                "e".repeat(64),
                "wrong".into()
            ],
            "scope"
        )
        .is_err()
    );
    let mut cursor = ExecutionCursor::new(binding());
    let batch = cursor.prepare(&["-2", "-1"], &"1".repeat(64)).unwrap();
    let foreign = ExecutionBinding::new(
        [
            "a".repeat(64),
            "b".repeat(64),
            "c".repeat(64),
            "d".repeat(64),
            "e".repeat(64),
            "f".repeat(64),
        ],
        "another",
    )
    .unwrap();
    assert!(
        cursor
            .commit(&batch, &foreign, 1, &["-2", "-1"], 2, &"1".repeat(64))
            .is_err()
    );
    cursor
        .commit(&batch, &binding(), 1, &["-2", "-1"], 2, &"1".repeat(64))
        .unwrap();
    let checkpoint = cursor.capture();
    let mut fresh = ExecutionCursor::new(binding());
    fresh.restore(&checkpoint).unwrap();
    assert_eq!(fresh.capture(), checkpoint);
    assert!(fresh.restore(&checkpoint).is_err());
    fresh.reset(2).unwrap();
    assert_eq!(fresh.samples(), 0);
    assert!(fresh.prepare(&["-5"], &"1".repeat(64)).is_ok());
}

#[test]
fn receipt_must_bind_the_exact_prepared_input_digest() {
    let mut cursor = ExecutionCursor::new(binding());
    let batch = cursor.prepare(&["1"], &"1".repeat(64)).unwrap();
    assert!(
        cursor
            .commit(&batch, &binding(), 1, &["1"], 1, &"2".repeat(64))
            .is_err()
    );
    assert_eq!(cursor.revision(), 0);
    cursor
        .commit(&batch, &binding(), 1, &["1"], 1, &"1".repeat(64))
        .unwrap();
}

#[test]
fn empty_cursor_restore_rejects_missing_and_unknown_fields_atomically() {
    let mut fresh = ExecutionCursor::new(binding());
    let original = fresh.capture();
    let mut malformed = original.clone();
    malformed.as_object_mut().unwrap().remove("last_event_ns");
    malformed["extra"] = serde_json::Value::Null;
    assert!(fresh.restore(&malformed).is_err());
    assert_eq!(fresh.capture(), original);
    fresh.restore(&original).unwrap();
}
