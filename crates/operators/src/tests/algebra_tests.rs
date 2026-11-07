use super::*;
use std::str::FromStr;
fn d(s: &str) -> Decimal {
    Decimal::from_str(s).unwrap()
}
fn values(s: &[&str]) -> Vec<Cell> {
    s.iter()
        .map(|s| if *s == "null" { None } else { Some(d(s)) })
        .collect()
}
fn kernel(op: Operator, p: Option<usize>) -> Kernel {
    Kernel::new(
        op,
        Parameters {
            period: p.map(|p| NonZeroUsize::new(p).unwrap()),
            ..Parameters::default()
        },
    )
    .unwrap()
}
fn check(op: Operator, p: Option<usize>, input: &[&str], expected: &[&str]) {
    assert_eq!(
        kernel(op, p).evaluate(&[values(input)]).unwrap(),
        values(expected)
    );
}
#[test]
fn pointwise_domains_and_half_even() {
    let a = values(&["1.0000000000005", "1.0000000000015", "null", "0"]);
    let b = values(&["0", "0", "2", "0"]);
    assert_eq!(
        kernel(Operator::Add, None).evaluate(&[a, b]).unwrap(),
        values(&["1", "1.000000000002", "null", "0"])
    );
    assert_eq!(
        kernel(Operator::Divide, None)
            .evaluate(&[values(&["2", "2", "null"]), values(&["3", "0", "1"])])
            .unwrap(),
        values(&["0.666666666667", "null", "null"])
    );
    check(
        Operator::Log,
        None,
        &["1", "0", "-2", "2", "0.5", "10"],
        &[
            "0",
            "null",
            "null",
            "0.693147180560",
            "-0.693147180560",
            "2.302585092994",
        ],
    );
    check(
        Operator::Abs,
        None,
        &["-2", "null", "0"],
        &["2", "null", "0"],
    );
    check(Operator::Sign, None, &["-2", "0", "3"], &["-1", "0", "1"]);
}
#[test]
fn complete_windows_population_and_ties() {
    let input = ["1", "2", "3", "null", "5", "6", "7"];
    check(
        Operator::RollingSum,
        Some(3),
        &input,
        &["null", "null", "6", "null", "null", "null", "18"],
    );
    check(
        Operator::RollingMean,
        Some(3),
        &input,
        &["null", "null", "2", "null", "null", "null", "6"],
    );
    check(
        Operator::RollingVar,
        Some(3),
        &["1", "2", "3"],
        &["null", "null", "0.666666666667"],
    );
    check(
        Operator::RollingStd,
        Some(3),
        &["1", "2", "3"],
        &["null", "null", "0.816496580928"],
    );
    check(
        Operator::RollingMin,
        Some(2),
        &["3", "1", "2"],
        &["null", "1", "1"],
    );
    check(
        Operator::RollingMax,
        Some(2),
        &["3", "1", "2"],
        &["null", "3", "2"],
    );
    check(
        Operator::DecayLinear,
        Some(3),
        &["1", "2", "3"],
        &["null", "null", "2.333333333333"],
    );
    check(
        Operator::TSRank,
        Some(3),
        &["1", "2", "2"],
        &["null", "null", "0.75"],
    );
    check(Operator::TSRank, Some(1), &["7"], &["0.5"]);
    check(
        Operator::Delay,
        Some(2),
        &["1", "null", "3", "4"],
        &["null", "null", "1", "null"],
    );
    check(
        Operator::Delta,
        Some(2),
        &["1", "null", "3", "4"],
        &["null", "null", "2", "null"],
    );
}
#[test]
fn paired_population_and_zero_variance() {
    let c = [values(&["1", "2", "3"]), values(&["2", "4", "6"])];
    assert_eq!(
        kernel(Operator::RollingCovariance, Some(3))
            .evaluate(&c)
            .unwrap(),
        values(&["null", "null", "1.333333333333"])
    );
    assert_eq!(
        kernel(Operator::RollingCorrelation, Some(3))
            .evaluate(&c)
            .unwrap(),
        values(&["null", "null", "1"])
    );
    assert_eq!(
        kernel(Operator::RollingCorrelation, Some(2))
            .evaluate(&[values(&["1", "1"]), values(&["2", "3"])])
            .unwrap(),
        values(&["null", "null"])
    );
}
#[test]
fn cross_section_nulls_ties_and_singleton() {
    check(
        Operator::CrossSectionRank,
        None,
        &["3", "null", "1", "3"],
        &["0.75", "null", "0", "0.75"],
    );
    check(
        Operator::CrossSectionRank,
        None,
        &["null", "4"],
        &["null", "0.5"],
    );
    check(
        Operator::CrossSectionDemean,
        None,
        &["3", "null", "1"],
        &["1", "null", "-1"],
    );
    check(
        Operator::CrossSectionZScore,
        None,
        &["3", "null", "1"],
        &["1", "null", "-1"],
    );
    check(
        Operator::CrossSectionZScore,
        None,
        &["3", "3"],
        &["null", "null"],
    );
    let k = Kernel::new(
        Operator::CrossSectionPercentile,
        Parameters {
            lower_is_better: true,
            ..Parameters::default()
        },
    )
    .unwrap();
    assert_eq!(
        k.evaluate(&[values(&["1", "3", "3"])]).unwrap(),
        values(&["1", "0.25", "0.25"])
    );
}
#[test]
fn stream_batch_checkpoint_equivalence_all_time_series() {
    let ops = [
        Operator::Add,
        Operator::Subtract,
        Operator::Multiply,
        Operator::Divide,
        Operator::Abs,
        Operator::Sign,
        Operator::Log,
        Operator::Delay,
        Operator::Delta,
        Operator::RollingMean,
        Operator::RollingSum,
        Operator::RollingStd,
        Operator::RollingVar,
        Operator::RollingMin,
        Operator::RollingMax,
        Operator::RollingCovariance,
        Operator::RollingCorrelation,
        Operator::TSRank,
        Operator::Scale,
        Operator::DecayLinear,
    ];
    for op in ops {
        let k = kernel(op, op.needs_period().then_some(3));
        let unary = values(&["1", "2", "null", "3", "4", "5", "6"]);
        let mut c = vec![unary.clone()];
        if op.input_count() == 2 {
            c.push(unary);
        }
        let batch = k.evaluate(&c).unwrap();
        let mut stream = Stream::new(k.clone()).unwrap();
        let mut actual = vec![];
        for i in 0..c[0].len() {
            if i == 4 {
                let state = stream.checkpoint();
                stream = Stream::new(k.clone()).unwrap();
                stream.restore(state).unwrap();
            }
            actual.push(
                stream
                    .push(&c.iter().map(|c| c[i].clone()).collect::<Vec<_>>())
                    .unwrap(),
            );
        }
        assert_eq!(batch, actual, "{op:?}");
    }
}
#[test]
fn failures_do_not_commit_candidates() {
    let k = kernel(Operator::RollingSum, Some(2));
    let mut stream = Stream::new(k).unwrap();
    stream.push(&values(&["1"])).unwrap();
    let before = stream.checkpoint();
    assert_eq!(
        stream.push(&values(&["10000000000000000"])),
        Err(Error::NumericFailure)
    );
    assert_eq!(stream.checkpoint(), before);
    assert_eq!(
        stream.push(&values(&["1e2000"])),
        Err(Error::BudgetExceeded)
    );
    assert_eq!(stream.checkpoint(), before);
    assert_eq!(
        stream.restore(vec![values(&["1", "2", "3"])]),
        Err(Error::InvalidInputs)
    );
    assert_eq!(stream.checkpoint(), before);
    assert_eq!(
        stream.restore(vec![values(&["1", "10000000000000000"])]),
        Err(Error::NumericFailure)
    );
    assert_eq!(stream.checkpoint(), before);
    assert_eq!(stream.push(&values(&["2"])).unwrap(), Some(d("3")));
}
#[test]
fn intermediate_precision_is_not_only_output_quantization() {
    // Exact sum is 1; precision-28 addition loses the unit before subtraction.
    let a = Decimal::from_str("10000000000000000000000000000").unwrap();
    assert_eq!(sub(&add(&a, &d("1")), &a), d("0"));
    assert_eq!(
        div(&d("1"), &d("7")).unwrap(),
        d("0.1428571428571428571428571429")
    );
    assert_eq!(ln(&d("2")).unwrap(), d("0.6931471805599453094172321215"));
    assert_eq!(ln(&d("10")).unwrap(), d("2.302585092994045684017991455"));
}
#[test]
fn parameters_and_shape_are_strict() {
    assert_eq!(
        Kernel::new(Operator::Delay, Parameters::default()),
        Err(Error::InvalidParameters)
    );
    assert_eq!(
        kernel(Operator::Add, None).evaluate(&[values(&["1"])]),
        Err(Error::InvalidInputs)
    );
    assert_eq!(
        kernel(Operator::Add, None).evaluate(&[values(&["1"]), vec![]]),
        Err(Error::InvalidInputs)
    );
    assert!(matches!(
        Stream::new(kernel(Operator::CrossSectionRank, None)),
        Err(Error::ResearchOnly)
    ));
}

#[test]
fn delay_depends_only_on_the_delayed_value_including_after_restore() {
    let k = kernel(Operator::Delay, Some(1));
    assert_eq!(
        k.evaluate(&[values(&["7", "null", "2"])]).unwrap(),
        values(&["null", "7", "null"])
    );
    let mut stream = Stream::new(k.clone()).unwrap();
    assert_eq!(stream.push(&values(&["7"])).unwrap(), None);
    let checkpoint = stream.checkpoint();
    let mut restored = Stream::new(k).unwrap();
    restored.restore(checkpoint).unwrap();
    assert_eq!(stream.push(&values(&["null"])).unwrap(), Some(d("7")));
    assert_eq!(restored.push(&values(&["null"])).unwrap(), Some(d("7")));
}

#[test]
fn logarithm_retains_relative_precision_close_to_one() {
    let above = d(&format!("1.{}1", "0".repeat(254)));
    let below = d(&format!("0.{}", "9".repeat(255)));
    assert_eq!(ln(&above).unwrap(), d("1e-255"));
    assert_eq!(ln(&below).unwrap(), d("-1e-255"));
    check(
        Operator::Log,
        None,
        &[&above.to_string(), &below.to_string()],
        &["0", "0"],
    );
}
#[test]
fn admitted_extremes_zero_and_division_domain() {
    check(
        Operator::Log,
        None,
        &[
            "1e1024",
            "1e-1024",
            "0.9999999999999999999999999999",
            "1.000000000000000000000000001",
        ],
        &["2357.847135225903", "-2357.847135225903", "0", "0"],
    );
    assert_eq!(
        kernel(Operator::Divide, None)
            .evaluate(&[
                values(&["1e-1024", "0", "0", "1"]),
                values(&["1e1024", "2", "0", "0"])
            ])
            .unwrap(),
        values(&["0", "0", "null", "null"])
    );
    assert_eq!(
        kernel(Operator::Divide, None).evaluate(&[values(&["1e1024"]), values(&["1e-1024"])]),
        Err(Error::NumericFailure)
    );
    assert_eq!(
        ln(&d("1.000000000000000000000000001")).unwrap(),
        d("9.999999999999999999999999995e-28")
    );
    assert_eq!(
        ln(&d("0.9999999999999999999999999999")).unwrap(),
        d("-1.000000000000000000000000000e-28")
    );
}
#[test]
fn all_operators_preserve_missing_values() {
    let ops = [
        Operator::Add,
        Operator::Subtract,
        Operator::Multiply,
        Operator::Divide,
        Operator::Abs,
        Operator::Sign,
        Operator::Log,
        Operator::Delay,
        Operator::Delta,
        Operator::RollingMean,
        Operator::RollingSum,
        Operator::RollingStd,
        Operator::RollingVar,
        Operator::RollingMin,
        Operator::RollingMax,
        Operator::RollingCovariance,
        Operator::RollingCorrelation,
        Operator::TSRank,
        Operator::Scale,
        Operator::DecayLinear,
        Operator::CrossSectionPercentile,
        Operator::CrossSectionRank,
        Operator::CrossSectionZScore,
        Operator::CrossSectionDemean,
    ];
    for op in ops {
        let k = kernel(op, op.needs_period().then_some(2));
        assert_eq!(
            k.evaluate(&vec![vec![None; 3]; op.input_count()]).unwrap(),
            vec![None; 3],
            "{op:?}"
        );
        assert_eq!(
            k.evaluate(&vec![vec![]; op.input_count()]).unwrap(),
            vec![],
            "{op:?}"
        );
    }
    let scale = Kernel::new(
        Operator::Scale,
        Parameters {
            factor: Some(d("-2")),
            ..Parameters::default()
        },
    )
    .unwrap();
    assert_eq!(
        scale.evaluate(&[values(&["3", "null", "0"])]).unwrap(),
        values(&["-6", "null", "0"])
    );
}

#[test]
fn exact_sqrt_proves_both_midpoint_sides_and_half_even() {
    for increment in [2u8, 3u8] {
        let floor = pow10(27) + increment;
        let twice_plus_one = (&floor << 1) + 1;
        let midpoint = Decimal::new(&twice_plus_one * &twice_plus_one * 25, 56);
        let epsilon = d("1e-100");
        assert_eq!(
            sqrt(&(&midpoint - &epsilon)).unwrap(),
            Decimal::new(floor.clone(), 27)
        );
        assert_eq!(
            sqrt(&midpoint).unwrap(),
            Decimal::new(
                if floor.is_odd() {
                    &floor + 1
                } else {
                    floor.clone()
                },
                27
            )
        );
        assert_eq!(
            sqrt(&(&midpoint + &epsilon)).unwrap(),
            Decimal::new(&floor + 1, 27)
        );
    }
    assert_eq!(sqrt(&d("1e-1024")).unwrap(), d("1e-512"));
    assert_eq!(sqrt(&d("1e1024")).unwrap(), d("1e512"));
    assert_eq!(sqrt(&d("-1")), Err(Error::NumericFailure));
}
#[test]
fn native_semantics_canonicalize_all_numeric_zero_to_positive_zero() {
    let zero = |cell: Cell| {
        let value = cell.unwrap();
        assert!(value.is_zero());
        assert_eq!(value.sign(), Sign::NoSign);
        assert!(!value.to_string().starts_with('-'));
    };
    zero(
        kernel(Operator::Divide, None)
            .evaluate(&[values(&["-0"]), values(&["1"])])
            .unwrap()
            .pop()
            .unwrap(),
    );
    zero(
        kernel(Operator::Add, None)
            .evaluate(&[values(&["-0"]), values(&["-0"])])
            .unwrap()
            .pop()
            .unwrap(),
    );
    zero(
        kernel(Operator::Scale, None)
            .evaluate(&[values(&["-0.0000000000001"])])
            .unwrap()
            .pop()
            .unwrap(),
    );
    let k = Kernel::new(
        Operator::Scale,
        Parameters {
            factor: Some(d("-1")),
            ..Parameters::default()
        },
    )
    .unwrap();
    let mut stream = Stream::new(k.clone()).unwrap();
    zero(stream.push(&values(&["0"])).unwrap());
    let checkpoint = stream.checkpoint();
    let mut restored = Stream::new(k).unwrap();
    restored.restore(checkpoint).unwrap();
    zero(restored.push(&values(&["-0"])).unwrap());
}

#[test]
fn explicit_host_interruption_discards_partial_batch_and_leaves_kernel_unchanged() {
    let kernel = kernel(Operator::RollingMean, Some(2));
    let original = kernel.clone();
    let columns = [values(&["1", "2", "3", "4"])];
    let mut calls = 0;
    assert_eq!(
        kernel.evaluate_controlled(&columns, || {
            calls += 1;
            if calls == 4 {
                Err(Error::Interrupted)
            } else {
                Ok(())
            }
        }),
        Err(Error::Interrupted)
    );
    assert_eq!(calls, 4, "initial check and checks before rows 0, 1, 2");
    assert_eq!(kernel, original);
    let expected = values(&["null", "1.5", "2.5", "3.5"]);
    assert_eq!(kernel.evaluate(&columns).unwrap(), expected);
    assert_eq!(
        kernel.evaluate_controlled(&columns, || Ok(())).unwrap(),
        expected
    );
    let mut initial = 0;
    assert_eq!(
        kernel.evaluate_controlled(&[], || {
            initial += 1;
            Err(Error::Interrupted)
        }),
        Err(Error::Interrupted)
    );
    assert_eq!(
        initial, 1,
        "host check precedes even invalid input admission"
    );
}
