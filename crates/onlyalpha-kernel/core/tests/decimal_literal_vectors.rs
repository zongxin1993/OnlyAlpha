use onlyalpha_kernel::decimal_predicate::{DecimalLiteralPredicate, DecimalOperand};
use onlyalpha_kernel::predicate::PredicateError;

#[test]
fn recorded_literals_preserve_exact_values_position_missing_and_repetition() {
    let mut rows: Vec<_> = include_str!("../../../../test-data/predicate/decimal-literal-v1.tsv")
        .lines()
        .skip(1)
        .collect();
    assert_eq!(rows.len(), 504);
    for _ in 0..2 {
        for row in &rows {
            let fields: Vec<_> = row.split('\t').collect();
            assert_eq!(fields.len(), 7);
            let literal = DecimalOperand::parse(fields[4]).unwrap();
            let value = if fields[3] == "null" {
                None
            } else {
                Some(DecimalOperand::parse(fields[3]).unwrap())
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
                    DecimalLiteralPredicate::resolve(fields[1], fields[2], literal, literal_left)
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
    let literal = DecimalOperand::parse("0").unwrap();
    for op in ["eq", "ne", "lt", "le", "gt", "ge"] {
        let id = format!("onlyalpha.predicate.internal.compare.{op}.decimal.literal");
        assert_eq!(
            DecimalLiteralPredicate::resolve(&id, "2", literal, false),
            Err(PredicateError::UnknownVersion)
        );
        for other in [
            id.replace("decimal", "integer"),
            id.replace("literal", "refs"),
            id.replace("predicate", "indicator"),
            id.replace(&format!(".{op}."), ".unknown."),
        ] {
            assert_eq!(
                DecimalLiteralPredicate::resolve(&other, "1", literal, false),
                Err(PredicateError::UnknownType)
            );
        }
        for literal_left in [false, true] {
            let predicate =
                DecimalLiteralPredicate::resolve(&id, "1", literal, literal_left).unwrap();
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

#[test]
fn literal_configuration_is_retained_even_when_outputs_coincide() {
    let id = "onlyalpha.predicate.internal.compare.eq.decimal.literal";
    let zero = DecimalOperand::parse("-0.00").unwrap();
    let one = DecimalOperand::parse("1.000").unwrap();
    let left = DecimalLiteralPredicate::resolve(id, "1", zero, true).unwrap();
    let right = DecimalLiteralPredicate::resolve(id, "1", zero, false).unwrap();
    let different = DecimalLiteralPredicate::resolve(id, "1", one, true).unwrap();
    assert_ne!(left, right);
    assert_ne!(left, different);
    assert_eq!(left.evaluate(&[None]), Ok(None));
    assert_eq!(right.evaluate(&[None]), Ok(None));
    assert_eq!(different.evaluate(&[None]), Ok(None));
    for _ in 0..3 {
        assert_eq!(left.evaluate(&[Some(zero)]), Ok(Some(true)));
        assert_eq!(different.evaluate(&[Some(zero)]), Ok(Some(false)));
    }
}
