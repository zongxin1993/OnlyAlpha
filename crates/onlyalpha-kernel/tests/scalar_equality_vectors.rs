use onlyalpha_kernel::boolean_equality::{
    BooleanEqualityPredicate, BooleanLiteralEqualityPredicate,
};
use onlyalpha_kernel::predicate::PredicateError;
use onlyalpha_kernel::string_equality::{StringEqualityPredicate, StringLiteralEqualityPredicate};

fn boolean(token: &str) -> Option<bool> {
    match token {
        "true" => Some(true),
        "false" => Some(false),
        "null" => None,
        _ => panic!("bad Boolean token"),
    }
}

fn string(token: &str) -> Option<String> {
    if token == "null" {
        return None;
    }
    let hex = token.strip_prefix("utf8:").unwrap();
    let (pairs, remainder) = hex.as_bytes().as_chunks::<2>();
    assert!(remainder.is_empty());
    let bytes: Vec<_> = pairs
        .iter()
        .map(|pair| u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap())
        .collect();
    Some(String::from_utf8(bytes).unwrap())
}

#[test]
fn all_independent_scalar_equalities_survive_repetition_and_reverse_order() {
    let mut rows: Vec<_> = include_str!("../../../test-data/predicate/scalar-equality-v1.tsv")
        .lines()
        .skip(1)
        .collect();
    assert_eq!(rows.len(), 250);
    for _ in 0..2 {
        for row in &rows {
            let f: Vec<_> = row.split('\t').collect();
            assert_eq!(f.len(), 8);
            let expected = boolean(f[7]);
            for _ in 0..2 {
                let actual = if f[1].contains(".boolean.") {
                    if f[1].ends_with(".refs") {
                        BooleanEqualityPredicate::resolve(f[1], f[2])
                            .unwrap()
                            .evaluate(&[boolean(f[3]), boolean(f[4])])
                    } else {
                        BooleanLiteralEqualityPredicate::resolve(
                            f[1],
                            f[2],
                            boolean(f[5]).unwrap(),
                            boolean(f[6]).unwrap(),
                        )
                        .unwrap()
                        .evaluate(&[boolean(f[3])])
                    }
                } else {
                    let left = string(f[3]);
                    if f[1].ends_with(".refs") {
                        let right = string(f[4]);
                        StringEqualityPredicate::resolve(f[1], f[2])
                            .unwrap()
                            .evaluate(&[left.as_deref(), right.as_deref()])
                    } else {
                        let literal = string(f[5]).unwrap();
                        StringLiteralEqualityPredicate::resolve(
                            f[1],
                            f[2],
                            &literal,
                            boolean(f[6]).unwrap(),
                        )
                        .unwrap()
                        .evaluate(&[left.as_deref()])
                    }
                };
                assert_eq!(actual, Ok(expected), "{}", f[0]);
            }
        }
        rows.reverse();
    }
}

#[test]
fn exact_family_layout_operator_and_version_are_required() {
    type Resolve = fn(&str, &str) -> Result<(), PredicateError>;
    let families: [(&str, &str, Resolve); 4] = [
        ("boolean", "refs", |id, version| {
            BooleanEqualityPredicate::resolve(id, version).map(|_| ())
        }),
        ("boolean", "literal", |id, version| {
            BooleanLiteralEqualityPredicate::resolve(id, version, false, false).map(|_| ())
        }),
        ("string", "refs", |id, version| {
            StringEqualityPredicate::resolve(id, version).map(|_| ())
        }),
        ("string", "literal", |id, version| {
            StringLiteralEqualityPredicate::resolve(id, version, "", false).map(|_| ())
        }),
    ];
    for (family, layout, resolve) in families {
        for op in ["eq", "ne"] {
            let id = format!("onlyalpha.predicate.internal.compare.{op}.{family}.{layout}");
            assert_eq!(resolve(&id, "1"), Ok(()));
            for version in ["2", "01", ""] {
                assert_eq!(resolve(&id, version), Err(PredicateError::UnknownVersion));
            }
            for other in [
                id.replace(
                    family,
                    if family == "boolean" {
                        "string"
                    } else {
                        "boolean"
                    },
                ),
                id.replace(layout, if layout == "refs" { "literal" } else { "refs" }),
                id.replace("predicate", "indicator"),
                id.replace(&format!(".{op}."), ".lt."),
            ] {
                assert_eq!(resolve(&other, "1"), Err(PredicateError::UnknownType));
            }
        }
    }
}

#[test]
fn arity_is_checked_before_missing_propagation_for_every_type() {
    for op in ["eq", "ne"] {
        let prefix = format!("onlyalpha.predicate.internal.compare.{op}");
        let b = BooleanEqualityPredicate::resolve(&format!("{prefix}.boolean.refs"), "1").unwrap();
        let s = StringEqualityPredicate::resolve(&format!("{prefix}.string.refs"), "1").unwrap();
        for count in [0, 1, 3] {
            assert_eq!(
                b.evaluate(&vec![None; count]),
                Err(PredicateError::InvalidArity)
            );
            assert_eq!(
                s.evaluate(&vec![None; count]),
                Err(PredicateError::InvalidArity)
            );
        }
        for position in [false, true] {
            let b = BooleanLiteralEqualityPredicate::resolve(
                &format!("{prefix}.boolean.literal"),
                "1",
                false,
                position,
            )
            .unwrap();
            let s = StringLiteralEqualityPredicate::resolve(
                &format!("{prefix}.string.literal"),
                "1",
                "",
                position,
            )
            .unwrap();
            for count in [0, 2, 3] {
                assert_eq!(
                    b.evaluate(&vec![None; count]),
                    Err(PredicateError::InvalidArity)
                );
                assert_eq!(
                    s.evaluate(&vec![None; count]),
                    Err(PredicateError::InvalidArity)
                );
            }
            assert_eq!(b.evaluate(&[None]), Ok(None));
            assert_eq!(s.evaluate(&[None]), Ok(None));
        }
    }
}

#[test]
fn literal_position_remains_explicit_configuration_even_for_symmetric_operators() {
    for op in ["eq", "ne"] {
        let boolean_id = format!("onlyalpha.predicate.internal.compare.{op}.boolean.literal");
        let string_id = format!("onlyalpha.predicate.internal.compare.{op}.string.literal");
        assert_ne!(
            BooleanLiteralEqualityPredicate::resolve(&boolean_id, "1", false, false).unwrap(),
            BooleanLiteralEqualityPredicate::resolve(&boolean_id, "1", false, true).unwrap()
        );
        assert_ne!(
            StringLiteralEqualityPredicate::resolve(&string_id, "1", "", false).unwrap(),
            StringLiteralEqualityPredicate::resolve(&string_id, "1", "", true).unwrap()
        );
    }
}
