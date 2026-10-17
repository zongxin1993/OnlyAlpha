use onlyalpha_kernel::integer_predicate::{IntegerOperand, IntegerPredicate};
use onlyalpha_kernel::predicate::PredicateError;

fn operand(value: &str) -> Option<IntegerOperand<'_>> {
    if value == "null" {
        None
    } else {
        Some(IntegerOperand::parse(value).unwrap())
    }
}

#[test]
fn exact_recorded_integer_comparisons_survive_order_and_repetition() {
    let mut rows: Vec<_> = include_str!("../../../test-data/predicate/integer-refs-v1.tsv")
        .lines()
        .skip(1)
        .collect();
    assert_eq!(rows.len(), 216);
    for _ in 0..2 {
        for _ in 0..2 {
            for row in &rows {
                let fields: Vec<_> = row.split('\t').collect();
                assert_eq!(fields.len(), 6);
                let predicate = IntegerPredicate::resolve(fields[1], fields[2]).unwrap();
                let expected = match fields[5] {
                    "true" => Some(true),
                    "false" => Some(false),
                    "null" => None,
                    _ => panic!("bad expectation"),
                };
                assert_eq!(
                    predicate.evaluate(&[operand(fields[3]), operand(fields[4])]),
                    Ok(expected),
                    "{}",
                    fields[0]
                );
            }
        }
        rows.reverse();
    }
}

#[test]
fn invalid_integer_encodings_are_errors_not_missing_values() {
    for value in [
        "", "-", "+1", "-0", "00", "01", "-01", "1.0", "1e3", " 1", "1\n", "true", "null", "１２",
        "١",
    ] {
        assert_eq!(
            IntegerOperand::parse(value),
            Err(PredicateError::InvalidInteger),
            "{value:?}"
        );
    }
}

#[test]
fn integer_type_version_and_arity_never_fall_back() {
    for op in ["eq", "ne", "lt", "le", "gt", "ge"] {
        let id = format!("onlyalpha.predicate.internal.compare.{op}.integer.refs");
        assert_eq!(
            IntegerPredicate::resolve(&id, "2"),
            Err(PredicateError::UnknownVersion)
        );
        let predicate = IntegerPredicate::resolve(&id, "1").unwrap();
        for count in [0, 1, 3] {
            assert_eq!(
                predicate.evaluate(&vec![None; count]),
                Err(PredicateError::InvalidArity)
            );
        }
        for other in [
            id.replace("integer", "decimal"),
            id.replace("refs", "literal"),
            id.replace("predicate", "indicator"),
        ] {
            assert_eq!(
                IntegerPredicate::resolve(&other, "1"),
                Err(PredicateError::UnknownType)
            );
        }
    }
}
