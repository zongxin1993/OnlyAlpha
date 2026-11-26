use onlyalpha_operators::algebra::{Decimal, Error, Kernel, Parameters, Stream};
use onlyalpha_operators::execution::{EventKernel, VectorKernel};
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
            period: if spec.parameter == ParameterKind::Period {
                three()
            } else {
                None
            },
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
    if spec.inputs == 2 {
        columns.push(values(&["2", "4", "6", "8", "10", "3", "0", "2", "2"]));
    }
    columns
}

/// Complete, strictly positive, non-repeating observations isolate warmup.
fn complete(spec: &OpSpec) -> Vec<Vec<Cell>> {
    let mut columns = vec![values(&["1", "2", "3", "4", "5", "6", "7", "8"])];
    if spec.inputs == 2 {
        columns.push(values(&["2", "3", "4", "5", "6", "7", "8", "9"]));
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
    if spec.parameter == ParameterKind::Period {
        three()
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
        if spec.inputs == 2 {
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
fn cross_section_operators_are_research_only_for_event_execution() {
    for spec in registry::all()
        .iter()
        .filter(|spec| spec.shape == ExecutionShape::CrossSection)
    {
        assert_eq!(spec.state(), StateCapability::ResearchOnly);
        assert_eq!(
            Stream::new(kernel(spec)).unwrap_err(),
            Error::ResearchOnly,
            "{}",
            spec.name
        );
    }
}

fn check(name: &str, parameters: Parameters, columns: Vec<Vec<Cell>>, expected: &[&str]) {
    let spec = registry::lookup(&format!("onlyalpha.operator.{name}")).unwrap();
    let kernel = Kernel::new(spec.operator, parameters).unwrap();
    assert_eq!(
        VectorKernel::evaluate(&kernel, &columns).unwrap(),
        values(expected),
        "{name}"
    );
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
