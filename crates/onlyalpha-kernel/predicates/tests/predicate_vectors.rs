use onlyalpha_predicates::predicate::{Predicate, PredicateError};
use std::{fs, path::Path};

fn scalar(token: &str) -> Option<bool> {
    match token {
        "true" => Some(true),
        "false" => Some(false),
        "null" => None,
        _ => panic!("malformed recorded scalar: {token}"),
    }
}

#[test]
fn recorded_vectors_are_exact_in_both_orders_and_repeated_evaluations() {
    let path =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../test-data/predicate/boolean-v1.tsv");
    let corpus = fs::read_to_string(path).expect("shared immutable vectors must exist");
    let mut lines = corpus.lines();
    assert_eq!(
        lines.next(),
        Some("case_id\ttype_id\tsemantic_version\tleft\tright\texpected")
    );
    let mut rows: Vec<_> = lines.collect();
    assert_eq!(rows.len(), 30);
    for _ in 0..2 {
        for _ in 0..2 {
            for row in &rows {
                let fields: Vec<_> = row.split('\t').collect();
                assert_eq!(fields.len(), 6);
                let op = Predicate::resolve(fields[1], fields[2]).expect("exact declared identity");
                let left = scalar(fields[3]);
                let inputs = if op.arity() == 2 {
                    vec![left, scalar(fields[4])]
                } else {
                    vec![left]
                };
                assert_eq!(op.evaluate(&inputs), Ok(scalar(fields[5])), "{}", fields[0]);
            }
        }
        rows.reverse();
    }
}

#[test]
fn unknown_identity_or_version_never_falls_back() {
    assert_eq!(
        Predicate::resolve("onlyalpha.predicate.internal.boolean.and", "2"),
        Err(PredicateError::UnknownVersion)
    );
    assert_eq!(
        Predicate::resolve("onlyalpha.predicate.internal.boolean.AND", "1"),
        Err(PredicateError::UnknownType)
    );
    assert_eq!(
        Predicate::resolve("onlyalpha.predicate.internal.boolean.unknown", "2"),
        Err(PredicateError::UnknownType)
    );
    assert_eq!(
        Predicate::resolve("", "1"),
        Err(PredicateError::UnknownType)
    );
}

#[test]
fn wrong_arity_is_an_error_instead_of_missing_or_false() {
    for (name, arity) in [
        ("boolean.and", 2),
        ("boolean.or", 2),
        ("boolean.not", 1),
        ("terminal.eligibility", 1),
        ("terminal.entry_signal", 1),
        ("terminal.exit_signal", 1),
    ] {
        let op = Predicate::resolve(&format!("onlyalpha.predicate.internal.{name}"), "1").unwrap();
        assert_eq!(op.arity(), arity);
        for size in 0..=3 {
            if size != arity {
                assert_eq!(
                    op.evaluate(&vec![None; size]),
                    Err(PredicateError::InvalidArity)
                );
            }
        }
    }
}

#[test]
fn terminal_roles_remain_distinct_even_when_scalar_outputs_match() {
    for (name, expected) in [
        ("terminal.eligibility", Predicate::Eligibility),
        ("terminal.entry_signal", Predicate::EntrySignal),
        ("terminal.exit_signal", Predicate::ExitSignal),
    ] {
        assert_eq!(
            Predicate::resolve(&format!("onlyalpha.predicate.internal.{name}"), "1"),
            Ok(expected)
        );
    }
    assert_eq!(
        Predicate::resolve("onlyalpha.indicator.boolean.and", "1"),
        Err(PredicateError::UnknownType)
    );
}
