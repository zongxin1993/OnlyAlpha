use onlyalpha_kernel::integer_predicate::{IntegerLiteralPredicate, IntegerOperand};
use onlyalpha_kernel::predicate::PredicateError;

#[test]
fn recorded_literals_preserve_exact_values_position_missing_and_repetition() {
    let mut rows: Vec<_> = include_str!("../../../test-data/predicate/integer-literal-v1.tsv")
        .lines()
        .skip(1)
        .collect();
    assert_eq!(rows.len(), 408);
    for _ in 0..2 {
        for row in &rows {
            let fields: Vec<_> = row.split('\t').collect();
            assert_eq!(fields.len(), 7);
            let literal = IntegerOperand::parse(fields[4]).unwrap();
            let value = if fields[3] == "null" {
                None
            } else {
                Some(IntegerOperand::parse(fields[3]).unwrap())
            };
            let literal_left = match fields[5] {
                "true" => true,
                "false" => false,
                _ => panic!("bad position"),
            };
            let expected = match fields[6] {
                "true" => Some(true),
                "false" => Some(false),
                "null" => None,
                _ => panic!("bad expectation"),
            };
            for _ in 0..2 {
                let predicate =
                    IntegerLiteralPredicate::resolve(fields[1], fields[2], literal, literal_left)
                        .unwrap();
                for _ in 0..2 {
                    assert_eq!(predicate.evaluate(&[value]), Ok(expected), "{}", fields[0]);
                }
            }
        }
        rows.reverse();
    }
}

#[test]
fn literal_type_version_and_arity_never_fall_back() {
    let literal = IntegerOperand::parse("0").unwrap();
    for op in ["eq", "ne", "lt", "le", "gt", "ge"] {
        let id = format!("onlyalpha.predicate.internal.compare.{op}.integer.literal");
        assert_eq!(
            IntegerLiteralPredicate::resolve(&id, "2", literal, false),
            Err(PredicateError::UnknownVersion)
        );
        for other in [
            id.replace("integer", "decimal"),
            id.replace("literal", "refs"),
            id.replace("predicate", "indicator"),
        ] {
            assert_eq!(
                IntegerLiteralPredicate::resolve(&other, "1", literal, false),
                Err(PredicateError::UnknownType)
            );
        }
        for literal_left in [false, true] {
            let predicate =
                IntegerLiteralPredicate::resolve(&id, "1", literal, literal_left).unwrap();
            for count in [0, 2, 3] {
                assert_eq!(
                    predicate.evaluate(&vec![None; count]),
                    Err(PredicateError::InvalidArity)
                );
            }
            assert_eq!(predicate.evaluate(&[None]), Ok(None));
        }
    }
}
