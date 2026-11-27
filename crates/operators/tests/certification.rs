use onlyalpha_operators::algebra::{Decimal, Error, Kernel, Parameters, Stream};
use onlyalpha_operators::execution::{CrossSectionStream, EventKernel, VectorKernel};
use onlyalpha_operators::registry::{self, ExecutionShape, OpSpec, ParameterKind, StateCapability};
use std::num::NonZeroUsize;
use std::str::FromStr;

type Cell = Option<Decimal>;

fn d(text: &str) -> Decimal {
    Decimal::from_str(text).unwrap()
}

fn values(items: &[&str]) -> Vec<Cell> {
    items
        .iter()
        .map(|item| if *item == "null" { None } else { Some(d(item)) })
        .collect()
}

fn three() -> Option<NonZeroUsize> {
    NonZeroUsize::new(3)
}

fn kernel(spec: &OpSpec) -> Kernel {
    Kernel::new(
        spec.operator,
        Parameters {
            period: declared_period(spec),
            weight: NonZeroUsize::new(2).filter(|_| spec.parameter == ParameterKind::PeriodWeight),
            factor: (spec.parameter == ParameterKind::Factor).then(|| d("-2")),
            quantile: (spec.parameter == ParameterKind::PeriodQuantile).then(|| d("0.2")),
            ..Default::default()
        },
    )
    .unwrap()
}

fn period_parameters() -> Parameters {
    Parameters {
        period: three(),
        ..Default::default()
    }
}

/// Missing values, ties and a zero denominator exercise every declared boundary.
fn systematic(spec: &OpSpec) -> Vec<Vec<Cell>> {
    let mut columns = vec![values(&["3", "1", "2", "2", "5", "null", "4", "1", "6"])];
    if spec.inputs >= 2 {
        columns.push(values(&["2", "4", "6", "8", "10", "3", "0", "2", "2"]));
    }
    if spec.inputs >= 3 {
        columns.push(values(&["-1", "0", "5", "null", "7", "8", "9", "-2", "4"]));
    }
    if spec.inputs == 4 {
        columns.push(values(&["1", "4", "2", "9", "0", "3", "4", "5", "6"]));
    }
    columns
}

/// Complete, strictly positive, non-repeating observations isolate warmup.
fn complete(spec: &OpSpec) -> Vec<Vec<Cell>> {
    let mut columns = vec![values(&["1", "2", "3", "4", "5", "6", "7", "8"])];
    if spec.inputs >= 2 {
        columns.push(values(&["2", "3", "4", "5", "6", "7", "8", "9"]));
    }
    if spec.inputs >= 3 {
        columns.push(values(&["1", "1", "1", "2", "1", "2", "1", "1"]));
    }
    if spec.inputs == 4 {
        columns.push(values(&["3", "6", "4", "9", "2", "7", "1", "8"]));
    }
    columns
}

fn time_series() -> impl Iterator<Item = &'static OpSpec> {
    registry::all()
        .iter()
        .filter(|spec| spec.shape == ExecutionShape::TimeSeries)
}

fn step(stream: &mut Stream, columns: &[Vec<Cell>], index: usize) -> Cell {
    EventKernel::step(
        stream,
        &columns
            .iter()
            .map(|column| column[index].clone())
            .collect::<Vec<_>>(),
    )
    .unwrap()
}

fn declared_period(spec: &OpSpec) -> Option<NonZeroUsize> {
    if spec.operator.needs_period() {
        NonZeroUsize::new(3.max(spec.operator.minimum_period()))
    } else {
        None
    }
}

#[test]
fn vector_and_event_kernels_agree_pointwise_for_every_time_series_operator() {
    for spec in time_series() {
        let kernel = kernel(spec);
        let columns = systematic(spec);
        let batch = VectorKernel::evaluate(&kernel, &columns).unwrap();
        let mut stream = Stream::new(kernel).unwrap();
        let event = (0..columns[0].len())
            .map(|index| step(&mut stream, &columns, index))
            .collect::<Vec<_>>();
        assert_eq!(batch, event, "{}", spec.name);
    }
}

#[test]
fn every_time_series_output_depends_only_on_its_own_prefix() {
    for spec in time_series() {
        let kernel = kernel(spec);
        let columns = systematic(spec);
        let full = VectorKernel::evaluate(&kernel, &columns).unwrap();
        for length in 1..=columns[0].len() {
            let prefix = columns
                .iter()
                .map(|column| column[..length].to_vec())
                .collect::<Vec<_>>();
            assert_eq!(
                VectorKernel::evaluate(&kernel, &prefix).unwrap(),
                full[..length],
                "{} vector prefix {length}",
                spec.name
            );
            let mut stream = Stream::new(kernel.clone()).unwrap();
            let event = (0..length)
                .map(|index| step(&mut stream, &columns, index))
                .collect::<Vec<_>>();
            assert_eq!(event, full[..length], "{} event prefix {length}", spec.name);
        }
    }
}

#[test]
fn warmup_boundary_matches_declared_minimum_observations() {
    for spec in time_series() {
        let kernel = kernel(spec);
        let columns = complete(spec);
        let minimum = spec
            .operator
            .spec()
            .minimum_observations(declared_period(spec))
            .unwrap();
        let batch = VectorKernel::evaluate(&kernel, &columns).unwrap();
        assert!(
            batch[..minimum - 1].iter().all(Option::is_none),
            "{} vector output before warmup",
            spec.name
        );
        assert!(batch[minimum - 1].is_some(), "{} vector warmup", spec.name);
        let mut stream = Stream::new(kernel).unwrap();
        for index in 0..minimum - 1 {
            assert_eq!(step(&mut stream, &columns, index), None, "{}", spec.name);
        }
        assert!(
            step(&mut stream, &columns, minimum - 1).is_some(),
            "{} event warmup",
            spec.name
        );
    }
}

#[test]
fn completely_missing_inputs_produce_no_output() {
    for spec in time_series() {
        let kernel = kernel(spec);
        let mut columns = vec![vec![None; 6]];
        for _ in 1..spec.inputs {
            columns.push(values(&["1", "2", "3", "4", "5", "6"]));
        }
        assert!(
            VectorKernel::evaluate(&kernel, &columns)
                .unwrap()
                .iter()
                .all(Option::is_none),
            "{} with a missing first input",
            spec.name
        );
        if spec.inputs == 2 {
            let mut columns = vec![values(&["1", "2", "3", "4", "5", "6"])];
            columns.push(vec![None; 6]);
            assert!(
                VectorKernel::evaluate(&kernel, &columns)
                    .unwrap()
                    .iter()
                    .all(Option::is_none),
                "{} with a missing second input",
                spec.name
            );
        }
    }
}

#[test]
fn checkpoint_restore_preserves_every_suffix() {
    for spec in time_series() {
        let kernel = kernel(spec);
        let columns = systematic(spec);
        let expected = VectorKernel::evaluate(&kernel, &columns).unwrap();
        let length = columns[0].len();
        for split in 0..=length {
            let mut running = Stream::new(kernel.clone()).unwrap();
            let prefix = (0..split)
                .map(|index| step(&mut running, &columns, index))
                .collect::<Vec<_>>();
            let state = EventKernel::capture_state(&running);
            let mut restored = Stream::new(kernel.clone()).unwrap();
            EventKernel::restore_state(&mut restored, state.clone()).unwrap();
            assert_eq!(
                EventKernel::capture_state(&restored),
                state,
                "{} split {split} state round trip",
                spec.name
            );
            let suffix = (split..length)
                .map(|index| step(&mut restored, &columns, index))
                .collect::<Vec<_>>();
            assert_eq!(prefix, expected[..split], "{} split {split}", spec.name);
            assert_eq!(suffix, expected[split..], "{} split {split}", spec.name);
        }
    }
}

#[test]
fn cross_section_events_match_every_vector_prefix_and_restored_suffix() {
    for spec in registry::all()
        .iter()
        .filter(|s| s.shape == ExecutionShape::CrossSection)
    {
        let kernel = kernel(spec);
        assert_eq!(spec.state(), StateCapability::Stateless);
        assert_eq!(
            Stream::new(kernel.clone()).unwrap_err(),
            Error::CrossSectionRequired
        );
        let first = systematic(spec);
        let width = first[0].len();
        let reversed = first
            .iter()
            .map(|col| col.iter().rev().cloned().collect())
            .collect();
        let events = [first, vec![vec![None; width]; spec.inputs], reversed];
        let expected: Vec<_> = events
            .iter()
            .map(|plane| VectorKernel::evaluate(&kernel, plane).unwrap())
            .collect();
        assert_eq!(expected[1], vec![None; width]);
        for split in 0..=events.len() {
            let mut running = CrossSectionStream::new(kernel.clone(), width).unwrap();
            for (i, plane) in events[..split].iter().enumerate() {
                assert_eq!(
                    running.step(plane).unwrap(),
                    expected[i],
                    "{} prefix {split}, event {i}",
                    spec.name
                );
            }
            let state = running.capture_state();
            assert!(state.is_empty());
            let mut restored = CrossSectionStream::new(kernel.clone(), width).unwrap();
            restored.restore_state(state).unwrap();
            for i in split..events.len() {
                assert_eq!(
                    restored.step(&events[i]).unwrap(),
                    expected[i],
                    "{} suffix {split}, event {i}",
                    spec.name
                );
            }
        }
        let mut running = CrossSectionStream::new(kernel.clone(), width).unwrap();
        assert_eq!(
            running.restore_state(vec![vec![]]),
            Err(Error::InvalidInputs)
        );
        assert_eq!(running.step(&[]), Err(Error::InvalidInputs));
        assert_eq!(
            running.step(&vec![vec![None; width - 1]; spec.inputs]),
            Err(Error::InvalidInputs)
        );
        assert_eq!(running.step(&events[0]).unwrap(), expected[0]);
        let empty_columns = vec![Vec::new(); spec.inputs];
        assert!(
            VectorKernel::evaluate(&kernel, &empty_columns)
                .unwrap()
                .is_empty()
        );
        assert_eq!(
            CrossSectionStream::new(kernel.clone(), 0).unwrap_err(),
            Error::InvalidInputs
        );
        assert_eq!(
            CrossSectionStream::new(kernel, usize::MAX).unwrap_err(),
            Error::BudgetExceeded
        );
    }
}

fn check(name: &str, parameters: Parameters, columns: Vec<Vec<Cell>>, expected: &[&str]) {
    let spec = registry::lookup(&format!("onlyalpha.operator.{name}")).unwrap();
    let kernel = Kernel::new(spec.operator, parameters).unwrap();
    let expected = values(expected);
    assert_eq!(
        VectorKernel::evaluate(&kernel, &columns).unwrap(),
        expected,
        "{name}"
    );
    if spec.shape == ExecutionShape::CrossSection {
        let mut event = CrossSectionStream::new(kernel, columns[0].len()).unwrap();
        assert_eq!(event.step(&columns).unwrap(), expected, "{name} event");
    } else {
        let mut event = Stream::new(kernel).unwrap();
        for (i, want) in expected.into_iter().enumerate() {
            assert_eq!(step(&mut event, &columns, i), want, "{name} event {i}");
        }
    }
}

#[test]
fn centered_statistics_preserve_large_levels_and_half_even_ties() {
    let a = "9000000000000000.000000000001";
    let b = "9000000000000000.000000000002";
    let below = "8999999999999999.999999000001";
    let above = "9000000000000000.000001000001";
    let twice_above = "9000000000000000.000002000001";
    let window = |p| Parameters {
        period: NonZeroUsize::new(p),
        ..Default::default()
    };
    check(
        "rolling_mean",
        window(2),
        vec![values(&[a, a, b])],
        &["null", a, b],
    );
    check(
        "rolling_std",
        window(2),
        vec![values(&[a, a, b])],
        &["null", "0", "0"],
    );
    check(
        "rolling_var",
        window(4),
        vec![values(&[below, above, a, a])],
        &["null", "null", "null", "0"],
    );
    check(
        "rolling_covariance",
        window(2),
        vec![values(&[a, twice_above]), values(&[a, above])],
        &["null", "0"],
    );
    for (op, expected) in [
        ("cross_section_demean", "0"),
        ("cross_section_zscore", "null"),
    ] {
        check(
            op,
            Parameters::default(),
            vec![values(&[a, "null", a])],
            &[expected, "null", expected],
        );
    }
    check(
        "cross_section_demean",
        Parameters::default(),
        vec![values(&[a, b])],
        &["0", "0"],
    );
    check(
        "cross_section_zscore",
        Parameters::default(),
        vec![values(&[a, b])],
        &["-1", "1"],
    );
}

#[test]
fn singleton_cross_section_matches_each_operators_defined_value() {
    for (name, expected) in [
        ("cross_section_percentile", "0.5"),
        ("cross_section_rank", "0.5"),
        ("cross_section_demean", "0"),
        ("cross_section_zscore", "null"),
    ] {
        check(
            name,
            Parameters::default(),
            vec![values(&["7"])],
            &[expected],
        );
    }
    check(
        "cross_section_correlation",
        Parameters::default(),
        vec![values(&["7"]), values(&["8"])],
        &["null"],
    );
}

#[test]
fn cross_section_correlation_preserves_small_differences_at_large_offsets() {
    let a = "9000000000000000.000000000001";
    let b = "9000000000000000.000000000002";
    for (x, y, expected) in [
        ([a, a, a, "null"], [a, a, "null", b], ["null"; 4]),
        (
            [a, b, a, "null"],
            [b, a, "null", b],
            ["-1", "-1", "null", "null"],
        ),
        (
            [b, a, "null", b],
            [b, a, a, "null"],
            ["1", "1", "null", "null"],
        ),
        ([a, b, "null", a], [b, b, a, "null"], ["null"; 4]),
        ([a, "null", "null", "null"], [b, b, b, b], ["null"; 4]),
    ] {
        check(
            "cross_section_correlation",
            Parameters::default(),
            vec![values(&x), values(&y)],
            &expected,
        );
    }
}

#[test]
fn rolling_correlation_preserves_small_spreads_and_requires_complete_windows() {
    let a = "9000000000000000.000000000001";
    let b = "9000000000000000.000000000002";
    let cases = [
        (
            2,
            [a, a, b, a, a],
            [a, a, a, b, a],
            ["null", "null", "null", "-1", "null"],
        ),
        (
            3,
            [a, "null", b, a, b],
            [b, a, a, b, a],
            ["null", "null", "null", "null", "-1"],
        ),
        (
            3,
            [b, a, b, a, b],
            [b, "null", b, a, b],
            ["null", "null", "null", "null", "1"],
        ),
    ];
    for (period, x, y, expected) in cases {
        let kernel = Kernel::new(
            onlyalpha_operators::algebra::Operator::RollingCorrelation,
            Parameters {
                period: NonZeroUsize::new(period),
                ..Default::default()
            },
        )
        .unwrap();
        let columns = [values(&x), values(&y)];
        let expected = values(&expected);
        assert_eq!(VectorKernel::evaluate(&kernel, &columns).unwrap(), expected);
        let mut stream = Stream::new(kernel).unwrap();
        for (i, want) in expected.into_iter().enumerate() {
            assert_eq!(
                step(&mut stream, &columns, i),
                want,
                "period {period}, index {i}"
            );
        }
    }
}

#[test]
fn pointwise_goldens_are_independently_derived() {
    let unary = || vec![values(&["2", "-4", "null", "8", "0"])];
    let binary = || {
        vec![
            values(&["2", "-4", "null", "8", "0"]),
            values(&["1", "2", "3", "4", "0"]),
        ]
    };
    check(
        "add",
        Parameters::default(),
        binary(),
        &["3", "-2", "null", "12", "0"],
    );
    check(
        "subtract",
        Parameters::default(),
        binary(),
        &["1", "-6", "null", "4", "0"],
    );
    check(
        "multiply",
        Parameters::default(),
        binary(),
        &["2", "-8", "null", "32", "0"],
    );
    check(
        "divide",
        Parameters::default(),
        binary(),
        &["2", "-2", "null", "2", "null"],
    );
    check(
        "abs",
        Parameters::default(),
        unary(),
        &["2", "4", "null", "8", "0"],
    );
    check(
        "sign",
        Parameters::default(),
        unary(),
        &["1", "-1", "null", "1", "0"],
    );
    check(
        "log",
        Parameters::default(),
        unary(),
        &["0.693147180560", "null", "null", "2.079441541680", "null"],
    );
}

#[test]
fn product_and_power_have_independent_numeric_goldens() {
    check(
        "rolling_product",
        period_parameters(),
        vec![values(&["-2", "0.5", "3", "0", "null", "2", "-4", "0.5"])],
        &["null", "null", "-3", "0", "null", "null", "null", "-4"],
    );
    check(
        "pow",
        Parameters::default(),
        vec![
            values(&["-2", "-2", "4", "2", "0", "-4", "null"]),
            values(&["3", "2", "0.5", "-3", "2", "0.5", "1"]),
        ],
        &["-8", "4", "2", "0.125", "0", "null", "null"],
    );
}

#[test]
fn regression_and_conditional_recurrence_have_independent_goldens() {
    check(
        "regression_residual3",
        Parameters {
            period: NonZeroUsize::new(5),
            ..Default::default()
        },
        vec![
            values(&["10", "12", "7", "15", "22"]),
            values(&["0", "1", "0", "0", "1"]),
            values(&["0", "0", "1", "0", "1"]),
            values(&["0", "0", "0", "1", "1"]),
        ],
        &["null", "null", "null", "null", "1"],
    );
    check(
        "conditional_beta",
        Parameters {
            period: NonZeroUsize::new(6),
            ..Default::default()
        },
        vec![
            values(&["7", "100", "13", "999", "null", "19"]),
            values(&["1", "5", "3", "null", "8", "5"]),
            values(&["1", "2", "1", "1", "1", "1"]),
        ],
        &["null", "null", "null", "null", "null", "3"],
    );
    check(
        "cum_product_if",
        Parameters::default(),
        vec![
            values(&["null", "2", "-3", "8", "5", "6", "0.5"]),
            values(&["1", "0", "1", "null", "0", "2", "1"]),
        ],
        &["null", "1", "-3", "null", "-3", "-3", "-1.5"],
    );
}

#[test]
fn sma_preserves_prior_across_missing_observations() {
    check(
        "sma",
        Parameters {
            period: NonZeroUsize::new(4),
            weight: NonZeroUsize::new(3),
            ..Default::default()
        },
        vec![values(&["null", "8", "0", "null", "6", "-1"])],
        &["null", "8", "2", "null", "5", "0.5"],
    );
}

#[test]
fn scale_and_group_demean_use_only_eligible_cohort_members() {
    check(
        "cross_section_scale",
        Parameters::default(),
        vec![values(&["-2", "null", "0", "6"])],
        &["-0.25", "null", "0", "0.75"],
    );
    check(
        "cross_section_scale",
        Parameters::default(),
        vec![values(&["0", "null", "0"])],
        &["null", "null", "null"],
    );
    check(
        "group_demean",
        Parameters::default(),
        vec![
            values(&["2", "5", "null", "8", "-3", "9", "6"]),
            values(&["1", "2", "1", "1.0", "2", "null", "3"]),
        ],
        &["-3", "4", "null", "3", "-4", "null", "0"],
    );
}

#[test]
fn lag_and_window_goldens_are_independently_derived() {
    let lagged = || vec![values(&["2", "4", "null", "8", "6"])];
    check(
        "delay",
        period_parameters(),
        lagged(),
        &["null", "null", "null", "2", "4"],
    );
    check(
        "delta",
        period_parameters(),
        lagged(),
        &["null", "null", "null", "6", "2"],
    );
    let windowed = || vec![values(&["3", "1", "2", "2", "5"])];
    check(
        "rolling_sum",
        period_parameters(),
        windowed(),
        &["null", "null", "6", "5", "9"],
    );
    check(
        "rolling_mean",
        period_parameters(),
        windowed(),
        &["null", "null", "2", "1.666666666667", "3"],
    );
    check(
        "rolling_var",
        period_parameters(),
        windowed(),
        &["null", "null", "0.666666666667", "0.222222222222", "2"],
    );
    check(
        "rolling_std",
        period_parameters(),
        windowed(),
        &[
            "null",
            "null",
            "0.816496580928",
            "0.471404520791",
            "1.414213562373",
        ],
    );
    check(
        "rolling_min",
        period_parameters(),
        windowed(),
        &["null", "null", "1", "1", "2"],
    );
    check(
        "rolling_max",
        period_parameters(),
        windowed(),
        &["null", "null", "3", "2", "5"],
    );
    check(
        "ts_rank",
        period_parameters(),
        windowed(),
        &["null", "null", "0.5", "0.75", "1"],
    );
    check(
        "decay_linear",
        period_parameters(),
        windowed(),
        &["null", "null", "1.833333333333", "1.833333333333", "3.5"],
    );
    check(
        "rolling_slope",
        period_parameters(),
        windowed(),
        &["null", "null", "-0.5", "0.5", "1.5"],
    );
    check(
        "rolling_slope",
        Parameters {
            period: NonZeroUsize::new(4),
            ..Default::default()
        },
        vec![values(&["1", "2", "4", "8"])],
        &["null", "null", "null", "2.3"],
    );
}

#[test]
fn rolling_regression_preserves_offsets_and_signed_endpoint_residuals() {
    for input in [
        ["3", "1", "2", "2", "5"],
        [
            "100000000000000000000000000000003",
            "100000000000000000000000000000001",
            "100000000000000000000000000000002",
            "100000000000000000000000000000002",
            "100000000000000000000000000000005",
        ],
    ] {
        check(
            "rolling_r_squared",
            period_parameters(),
            vec![values(&input)],
            &["null", "null", "0.25", "0.75", "0.75"],
        );
        check(
            "rolling_residual",
            period_parameters(),
            vec![values(&input)],
            &["null", "null", "0.5", "-0.166666666667", "0.5"],
        );
    }
    for (name, expected) in [
        (
            "rolling_r_squared",
            ["null", "null", "1", "0", "0.75", "null"],
        ),
        (
            "rolling_residual",
            [
                "null",
                "null",
                "0",
                "0.333333333333",
                "-0.166666666667",
                "0",
            ],
        ),
    ] {
        check(
            name,
            period_parameters(),
            vec![values(&["3", "2", "1", "2", "2", "2"])],
            &expected,
        );
        check(
            name,
            Parameters {
                period: NonZeroUsize::new(1),
                ..Default::default()
            },
            vec![values(&["7", "8"])],
            &["null", "null"],
        );
    }
}

#[test]
fn rolling_quantile_interpolates_adjacent_order_statistics() {
    for (quantile, expected) in [
        ("0", "-3"),
        ("1", "7"),
        ("0.5", "1"),
        ("0.2", "-1.4"),
        ("0.8", "4.6"),
    ] {
        check(
            "rolling_quantile",
            Parameters {
                quantile: Some(d(quantile)),
                ..period_parameters()
            },
            vec![values(&["7", "-3", "1", "null"])],
            &["null", "null", expected, "null"],
        );
    }
    check(
        "rolling_quantile",
        Parameters {
            period: NonZeroUsize::new(1),
            quantile: Some(d("0.8")),
            ..Default::default()
        },
        vec![values(&["2", "null", "-1"])],
        &["2", "null", "-1"],
    );
}

#[test]
fn rolling_statistics_round_to_precision_28_before_q12_in_both_kernels() {
    use onlyalpha_operators::algebra::Operator;

    for (operator, quantile, input, expected) in [
        (
            Operator::RollingQuantile,
            Some("0.00000000000050000000000000001"),
            &["1", "2"][..],
            "1.000000000000",
        ),
        (
            Operator::RollingQuantile,
            Some("0.500000000000000000000000000001"),
            &["-1e30", "0", "1e30"][..],
            "2.000000000000",
        ),
        (
            Operator::RollingQuantile,
            Some("0.5"),
            &[
                "-9000000000000000.000000000001",
                "9000000000000000.000000000001",
            ][..],
            "-0.000000000001",
        ),
        (
            Operator::RollingResidual,
            None,
            &["0", "0", "6.00000000000300000000000000006"][..],
            "1.000000000000",
        ),
        (
            Operator::RollingRSquared,
            None,
            &["0", "1.9999999999986666666666666666", "2"][..],
            "0.750000000000",
        ),
    ] {
        let kernel = Kernel::new(
            operator,
            Parameters {
                period: NonZeroUsize::new(input.len()),
                quantile: quantile.map(d),
                ..Default::default()
            },
        )
        .unwrap();
        let columns = [values(input)];
        let mut golden = vec![None; input.len() - 1];
        golden.push(Some(d(expected)));
        assert_eq!(
            VectorKernel::evaluate(&kernel, &columns).unwrap(),
            golden,
            "{operator:?}"
        );
        let mut stream = Stream::new(kernel).unwrap();
        for (index, cell) in golden.iter().enumerate() {
            assert_eq!(
                &step(&mut stream, &columns, index),
                cell,
                "{operator:?} at {index}"
            );
        }
    }
}

#[test]
fn rolling_extrema_report_first_position_in_each_complete_window() {
    let input = ["3", "3", "1", "1", "4", "0", "null", "2", "4", "6"];
    check(
        "rolling_arg_max",
        period_parameters(),
        vec![values(&input)],
        &[
            "null", "null", "1", "1", "3", "2", "null", "null", "null", "3",
        ],
    );
    check(
        "rolling_arg_min",
        period_parameters(),
        vec![values(&input)],
        &[
            "null", "null", "3", "2", "1", "3", "null", "null", "null", "1",
        ],
    );
}

#[test]
fn rolling_quantile_requires_a_bounded_decimal_and_a_period() {
    use onlyalpha_operators::algebra::Operator;

    for quantile in [
        None,
        Some(d("-1e-60")),
        Some(d("1.000000000000000000000000000001")),
    ] {
        assert_eq!(
            Kernel::new(
                Operator::RollingQuantile,
                Parameters {
                    quantile,
                    ..period_parameters()
                }
            ),
            Err(Error::InvalidParameters)
        );
    }
    let quantile = Some(d("0.5"));
    assert_eq!(
        Kernel::new(
            Operator::RollingQuantile,
            Parameters {
                quantile: quantile.clone(),
                ..Default::default()
            }
        ),
        Err(Error::InvalidParameters)
    );
    assert_eq!(
        Kernel::new(
            Operator::RollingMean,
            Parameters {
                quantile,
                ..period_parameters()
            }
        ),
        Err(Error::InvalidParameters)
    );
    assert_eq!(
        Kernel::new(
            Operator::RollingQuantile,
            Parameters {
                quantile: Some(d("1e-1025")),
                ..period_parameters()
            }
        ),
        Err(Error::BudgetExceeded)
    );
}

#[test]
fn conditional_and_recursive_goldens_are_independently_derived() {
    check(
        "where",
        Parameters::default(),
        vec![
            values(&["1", "0", "-2", "null", "3", "-1"]),
            values(&["10", "null", "30", "40", "null", "60"]),
            values(&["null", "200", "300", "400", "500", "null"]),
        ],
        &["10", "200", "300", "null", "null", "null"],
    );
    check(
        "ema",
        period_parameters(),
        vec![values(&["10", "14", "10", "null", "18"])],
        &["10", "12", "11", "null", "14.5"],
    );
    check(
        "rma",
        period_parameters(),
        vec![values(&["2", "4", "6", "null", "9"])],
        &["null", "null", "4", "null", "5.666666666667"],
    );
    check(
        "rma",
        Parameters {
            period: NonZeroUsize::new(2),
            ..Default::default()
        },
        vec![values(&["2", "null", "4", "6"])],
        &["null", "null", "3", "4.5"],
    );
    check(
        "cumsum",
        Parameters::default(),
        vec![values(&["3", "null", "-1", "2.5"])],
        &["3", "null", "2", "4.5"],
    );
}

#[test]
fn recurrence_long_zero_decay_self_recovers_and_rejects_tampered_checkpoints() {
    use onlyalpha_operators::algebra::{Error, Operator};

    for op in [Operator::EMA, Operator::RMA] {
        let kernel = Kernel::new(
            op,
            Parameters {
                period: NonZeroUsize::new(2),
                ..Default::default()
            },
        )
        .unwrap();
        let mut series = Vec::with_capacity(2600);
        series.push(Some(d("1")));
        series.push(Some(d("1")));
        series.resize(2500, Some(d("0")));
        series.push(Some(d("10")));

        let batch = kernel.evaluate(&[series.clone()]).unwrap();
        let mut stream = Stream::new(kernel.clone()).unwrap();
        for cell in &series[..2400] {
            stream.push(std::slice::from_ref(cell)).unwrap();
        }
        let cp = stream.checkpoint();
        let mut restored = Stream::new(kernel).unwrap();
        restored.restore(cp).unwrap();
        for (i, cell) in series.iter().enumerate().skip(2400) {
            let actual = restored.push(std::slice::from_ref(cell)).unwrap();
            assert_eq!(
                actual, batch[i],
                "{op:?} mismatch after long decay restore at {i}"
            );
        }
    }

    // Tampered recurrence checkpoints MUST fail-closed.
    let rma2 = Kernel::new(
        Operator::RMA,
        Parameters {
            period: NonZeroUsize::new(2),
            ..Default::default()
        },
    )
    .unwrap();
    let mut rma_stream = Stream::new(rma2).unwrap();
    // Empty seed payload `[Some(0)]` is never emitted by `checkpoint()` and MUST be rejected.
    assert_eq!(
        rma_stream.restore(vec![vec![Some(d("0"))]]),
        Err(Error::InvalidInputs)
    );
    // Out-of-domain prior `1e200` MUST be rejected on restore.
    assert_eq!(
        rma_stream.restore(vec![vec![Some(d("1")), Some(d("1e200"))]]),
        Err(Error::NumericFailure)
    );
    // Seeded RMA at step_count < period MUST fail step_count validation.
    rma_stream
        .restore(vec![vec![Some(d("1")), Some(d("5"))]])
        .unwrap();
    assert_eq!(rma_stream.validate_step_count(0), Err(Error::InvalidInputs));
    assert_eq!(rma_stream.validate_step_count(1), Err(Error::InvalidInputs));
    assert!(rma_stream.validate_step_count(2).is_ok());

    let ema2 = Kernel::new(
        Operator::EMA,
        Parameters {
            period: NonZeroUsize::new(2),
            ..Default::default()
        },
    )
    .unwrap();
    let mut ema_stream = Stream::new(ema2).unwrap();
    assert_eq!(
        ema_stream.restore(vec![vec![Some(d("1e200"))]]),
        Err(Error::NumericFailure)
    );
    ema_stream.restore(vec![vec![Some(d("10"))]]).unwrap();
    assert_eq!(ema_stream.validate_step_count(0), Err(Error::InvalidInputs));
    assert!(ema_stream.validate_step_count(1).is_ok());
}

#[test]
fn constant_window_goldens_cover_ties_zero_variance_and_missing_values() {
    use onlyalpha_operators::algebra::Operator;

    for (op, constant, varying) in [
        (Operator::TSRank, "0.5", "1"),
        (Operator::RollingSlope, "0", "1.5"),
        (Operator::RollingVar, "0", "2"),
        (Operator::RollingStd, "0", "1.414213562373"),
        (Operator::RollingCovariance, "0", "1"),
        (Operator::RollingCorrelation, "null", "0.866025403784"),
    ] {
        let mut columns = vec![values(&["4", "4", "4", "null", "4", "4", "4", "7"])];
        if op.input_count() == 2 {
            columns.push(values(&["1", "2", "3", "4", "5", "6", "7", "8"]));
        }
        let expected = values(&[
            "null", "null", constant, "null", "null", "null", constant, varying,
        ]);
        let kernel = Kernel::new(op, period_parameters()).unwrap();
        assert_eq!(
            VectorKernel::evaluate(&kernel, &columns).unwrap(),
            expected,
            "{op:?}"
        );
        let mut stream = Stream::new(kernel).unwrap();
        for (index, value) in expected.into_iter().enumerate() {
            assert_eq!(
                step(&mut stream, &columns, index),
                value,
                "{op:?} at {index}"
            );
        }
    }
}

#[test]
fn paired_window_goldens_are_independently_derived() {
    let paired = || {
        vec![
            values(&["3", "1", "2", "2", "5"]),
            values(&["2", "4", "6", "8", "10"]),
        ]
    };
    check(
        "rolling_covariance",
        period_parameters(),
        paired(),
        &["null", "null", "-0.666666666667", "0.666666666667", "2"],
    );
    check(
        "rolling_correlation",
        period_parameters(),
        paired(),
        &["null", "null", "-0.5", "0.866025403784", "0.866025403784"],
    );
    check(
        "rolling_correlation",
        period_parameters(),
        vec![values(&["1", "2", "3"]), values(&["2", "2", "2"])],
        &["null", "null", "null"],
    );
}

#[test]
fn scale_and_cross_section_goldens_are_independently_derived() {
    check(
        "scale",
        Parameters {
            factor: Some(d("2")),
            ..Default::default()
        },
        vec![values(&["1", "2", "null", "3", "4"])],
        &["2", "4", "null", "6", "8"],
    );
    let plane = || vec![values(&["3", "null", "1", "3", "2"])];
    check(
        "cross_section_percentile",
        Parameters::default(),
        plane(),
        &[
            "0.833333333333",
            "null",
            "0",
            "0.833333333333",
            "0.333333333333",
        ],
    );
    check(
        "cross_section_rank",
        Parameters::default(),
        plane(),
        &[
            "0.833333333333",
            "null",
            "0",
            "0.833333333333",
            "0.333333333333",
        ],
    );
    check(
        "cross_section_demean",
        Parameters::default(),
        plane(),
        &["0.75", "null", "-1.25", "0.75", "-0.25"],
    );
    check(
        "cross_section_zscore",
        Parameters::default(),
        plane(),
        &[
            "0.904534033733",
            "null",
            "-1.507556722889",
            "0.904534033733",
            "-0.301511344578",
        ],
    );
    // Deviations pair up as four equal 0.75 products over 4 pairs, so the
    // coefficient is exactly 0.75 / 1.25 without any rounding residue.
    check(
        "cross_section_correlation",
        Parameters::default(),
        vec![
            values(&["0", "null", "1", "2", "3"]),
            values(&["1", "7", "0", "3", "2"]),
        ],
        &["0.6", "null", "0.6", "0.6", "0.6"],
    );
    check(
        "cross_section_percentile",
        Parameters {
            lower_is_better: true,
            ..Default::default()
        },
        plane(),
        &[
            "0.166666666667",
            "null",
            "1",
            "0.166666666667",
            "0.666666666667",
        ],
    );
}
