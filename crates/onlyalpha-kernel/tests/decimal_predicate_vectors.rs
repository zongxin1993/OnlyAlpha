use onlyalpha_kernel::decimal_predicate::{DecimalOperand, DecimalPredicate};
use onlyalpha_kernel::predicate::PredicateError;

#[test]
fn exact_decimal_comparisons_match_independent_vectors_with_replay_and_reversal() {
    let mut rows: Vec<_> = include_str!("../../../test-data/predicate/decimal-refs-v1.tsv")
        .lines()
        .skip(1)
        .collect();
    assert_eq!(rows.len(), 264);
    for _ in 0..2 {
        for row in &rows {
            let fields: Vec<_> = row.split('\t').collect();
            let operand = |token| {
                if token == "null" {
                    None
                } else {
                    Some(DecimalOperand::parse(token).unwrap())
                }
            };
            let operands = [operand(fields[3]), operand(fields[4])];
            let expected = match fields[5] {
                "true" => Some(true),
                "false" => Some(false),
                "null" => None,
                _ => panic!("invalid corpus"),
            };
            for _ in 0..2 {
                let op = DecimalPredicate::resolve(fields[1], fields[2]).unwrap();
                assert_eq!(op.evaluate(&operands), Ok(expected), "{}", fields[0]);
            }
        }
        rows.reverse();
    }
}

#[test]
fn decimal_parser_refuses_nonfinite_noncanonical_or_wrong_family_text() {
    for token in [
        "",
        "+1",
        "01.0",
        "-01",
        ".1",
        "1.",
        "1e2",
        "1E-2",
        "NaN",
        "sNaN",
        "Infinity",
        "-Infinity",
        "true",
        "null",
        "1_000",
        " 1",
        "1\n",
        "１",
        "1.0.0",
        "--1",
        "-",
        "1.-1",
    ] {
        assert_eq!(
            DecimalOperand::parse(token),
            Err(PredicateError::InvalidDecimal),
            "{token}"
        );
    }
    for token in ["0", "-0", "0.000", "-0.000", "10", "1.000", "-0.001"] {
        assert!(DecimalOperand::parse(token).is_ok());
    }
}

#[test]
fn decimal_resolution_and_arity_fail_before_missing_propagation() {
    for op in ["eq", "ne", "lt", "le", "gt", "ge"] {
        let id = format!("onlyalpha.predicate.internal.compare.{op}.decimal.refs");
        let parsed = DecimalPredicate::resolve(&id, "1").unwrap();
        assert_eq!(
            DecimalPredicate::resolve(&id, "2"),
            Err(PredicateError::UnknownVersion)
        );
        for inputs in [vec![], vec![None], vec![None; 3]] {
            assert_eq!(parsed.evaluate(&inputs), Err(PredicateError::InvalidArity));
        }
        assert_eq!(parsed.evaluate(&[None, None]), Ok(None));
    }
    for id in [
        "onlyalpha.predicate.internal.compare.eq.integer.refs",
        "onlyalpha.predicate.internal.compare.eq.decimal.literal",
        "onlyalpha.predicate.internal.compare.unknown.decimal.refs",
    ] {
        assert_eq!(
            DecimalPredicate::resolve(id, "1"),
            Err(PredicateError::UnknownType)
        );
    }
}

#[test]
fn hundredth_grid_agrees_with_independent_integer_ordering() {
    for a in -15_i32..=15 {
        for b in -15_i32..=15 {
            let text = |v: i32| format!("{}0.{:02}00", if v < 0 { "-" } else { "" }, v.abs());
            let left = text(a);
            let right = text(b);
            let values = [
                Some(DecimalOperand::parse(&left).unwrap()),
                Some(DecimalOperand::parse(&right).unwrap()),
            ];
            for (op, expected) in [
                (DecimalPredicate::Eq, a == b),
                (DecimalPredicate::Ne, a != b),
                (DecimalPredicate::Lt, a < b),
                (DecimalPredicate::Le, a <= b),
                (DecimalPredicate::Gt, a > b),
                (DecimalPredicate::Ge, a >= b),
            ] {
                assert_eq!(op.evaluate(&values), Ok(Some(expected)), "{left} {right}");
            }
        }
    }
}
