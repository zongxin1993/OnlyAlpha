use super::*;

const A: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const B: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

#[test]
fn column_digest_preserves_frozen_encoding_and_null_positions() {
    let one = Some(Decimal::from(1));
    let digest = column_digest(&[None, one.clone()]).unwrap();
    assert_eq!(
        digest,
        "37de591341054f959a44367b13017e62487787a5cc0a4f0bd64083842f80f309"
    );
    assert_eq!(
        digest,
        column_digest(&[None, Some("1.00".parse().unwrap())]).unwrap()
    );
    assert_ne!(digest, column_digest(&[one, None]).unwrap());
}

#[test]
fn series_must_match_frozen_axes_shape_and_expression_output() {
    let ids = ["A.TEST".parse().unwrap()];
    let other_ids = ["B.TEST".parse().unwrap()];
    let timestamps = [1, 2].map(|t| OnlyTimestamp::from_unix_nanos(t.into()));
    let other_times = [1, 3].map(|t| OnlyTimestamp::from_unix_nanos(t.into()));
    let axis = EvaluationAxis {
        snapshot: A,
        content_digest: B,
        instruments: &ids,
        timestamps: &timestamps,
        warmup: 0,
    };
    let values = [vec![Some(Decimal::from(1)), None]];
    let base = SeriesRef {
        axis,
        name: "signal",
        fingerprint: A,
        values: &values,
    };
    for other in [
        EvaluationAxis {
            snapshot: B,
            ..axis
        },
        EvaluationAxis {
            content_digest: A,
            ..axis
        },
        EvaluationAxis {
            instruments: &other_ids,
            ..axis
        },
        EvaluationAxis {
            timestamps: &other_times,
            ..axis
        },
        EvaluationAxis { warmup: 1, ..axis },
    ] {
        let foreign = SeriesRef {
            axis: other,
            ..base
        };
        assert_eq!(
            input::bind(axis, [foreign].into_iter()).unwrap_err().0,
            "RESEARCH_STATISTICS_BINDING"
        );
    }
    let short = [vec![None]];
    for invalid in [&[][..], &short[..]] {
        assert_eq!(
            input::bind(
                axis,
                [SeriesRef {
                    values: invalid,
                    ..base
                }]
                .into_iter()
            )
            .unwrap_err()
            .0,
            "RESEARCH_STATISTICS_SHAPE"
        );
    }
    let alias = SeriesRef {
        name: "alias",
        ..base
    };
    let bound = input::bind(axis, [base, alias].into_iter()).unwrap();
    assert_eq!(bound[0].values_digest, bound[1].values_digest);
    let changed = [vec![None, Some(Decimal::from(1))]];
    assert_eq!(
        input::bind(
            axis,
            [
                base,
                SeriesRef {
                    values: &changed,
                    ..alias
                }
            ]
            .into_iter()
        )
        .unwrap_err()
        .0,
        "RESEARCH_STATISTICS_BINDING"
    );
}

#[test]
fn evaluate_requires_a_pair_and_rejects_slices_without_targets() {
    let instruments = ["A.TEST".parse().unwrap()];
    let timestamps = [OnlyTimestamp::from_unix_nanos(1.into())];
    let axis = EvaluationAxis {
        snapshot: A,
        content_digest: B,
        instruments: &instruments,
        timestamps: &timestamps,
        warmup: 0,
    };
    let values = [vec![Some(Decimal::from(1))]];
    let factors = [("f", A), ("g", B)].map(|(name, fingerprint)| {
        FactorSeriesRef(SeriesRef {
            axis,
            name,
            fingerprint,
            values: &values,
        })
    });
    let input = || EvaluationInput {
        axis,
        factors: &factors,
        targets: &[],
        minimum_observations: 2,
    };
    let pairs = vec![("f".into(), "g".into())];
    let valid = StatisticsPlan::new(vec![], pairs.clone()).unwrap();
    assert_eq!(evaluate(input(), &valid).unwrap().pairs().len(), 1);
    let sliced = StatisticsPlan::new(
        vec![TimeSlice {
            start_ns: 1,
            end_ns: 2,
        }],
        pairs,
    )
    .unwrap();
    for invalid in [StatisticsPlan::default(), sliced] {
        assert_eq!(
            evaluate(input(), &invalid).unwrap_err().0,
            "RESEARCH_PLAN_INVALID"
        );
    }
}

#[test]
fn factor_aliases_cannot_create_self_or_duplicate_pairs() {
    let binding = |name: &str, fingerprint: &str| SeriesBinding {
        name: name.into(),
        fingerprint: fingerprint.into(),
        values_digest: B.into(),
    };
    let factors = [binding("f", B), binding("g", A), binding("alias", B)];
    let pair = |x: &str, y: &str| (x.to_owned(), y.to_owned());
    let plan = StatisticsPlan::new(vec![], vec![pair("f", "g")]).unwrap();
    assert_eq!(plan.resolve_pairs(&factors).unwrap(), [(1, 0)]);
    for requests in [
        vec![pair("alias", "f")],
        vec![pair("g", "alias"), pair("f", "g")],
    ] {
        let plan = StatisticsPlan::new(vec![], requests).unwrap();
        assert_eq!(
            plan.resolve_pairs(&factors).unwrap_err().0,
            "RESEARCH_FACTOR_PAIR"
        );
    }
}
