use super::*;

fn report(slices: &[TimeSlice]) -> FactorReport {
    let instruments = ["A.TEST", "B.TEST", "C.TEST"].map(|s| s.parse().unwrap());
    let timestamps = [0, 1, 2, 3, i64::MAX].map(|t| OnlyTimestamp::from_unix_nanos(t.into()));
    let snapshot = "a".repeat(64);
    let content_digest = "b".repeat(64);
    let axis = EvaluationAxis {
        snapshot: &snapshot,
        content_digest: &content_digest,
        instruments: &instruments,
        timestamps: &timestamps,
        warmup: 1,
    };
    let fingerprints = ["1", "2", "3"].map(|s| s.repeat(64));
    let mut x = Vec::new();
    let mut y = Vec::new();
    let mut label = Vec::new();
    for n in 1..=3 {
        let value = Some(Decimal::from(n));
        x.push(vec![value.clone(); 5]);
        y.push(vec![
            value.clone(),
            value.clone(),
            value.clone(),
            value.clone(),
            Some(Decimal::from(0)),
        ]);
        let orthogonal = if n == 2 { -2 } else { 1 };
        label.push(vec![
            None,
            value,
            Some(Decimal::from(-n)),
            Some(Decimal::from(orthogonal)),
            None,
        ]);
    }
    let first = SeriesRef {
        axis,
        name: "x",
        fingerprint: &fingerprints[0],
        values: &x,
    };
    let second = SeriesRef {
        axis,
        name: "y",
        fingerprint: &fingerprints[1],
        values: &y,
    };
    let target = SeriesRef {
        axis,
        name: "label",
        fingerprint: &fingerprints[2],
        values: &label,
    };
    let input = EvaluationInput {
        axis,
        factors: &[FactorSeriesRef(first), FactorSeriesRef(second)],
        targets: &[TargetSeriesRef(target)],
        minimum_observations: 3,
    };
    let plan = StatisticsPlan::new(slices.to_vec(), vec![("y".into(), "x".into())]).unwrap();
    evaluate(input, &plan).unwrap()
}

fn coverage_report(
    factor: &[Vec<Cell>],
    label: &[Vec<Cell>],
    add_empty_target: bool,
) -> FactorReport {
    let instruments: Vec<_> = (0..factor.len())
        .map(|n| format!("A{n:02}.TEST").parse().unwrap())
        .collect();
    let timestamps = [0, 1, 2].map(|n| OnlyTimestamp::from_unix_nanos(n.into()));
    let fingerprints = ["1", "2", "3"].map(|s| s.repeat(64));
    let axis = EvaluationAxis {
        snapshot: &fingerprints[0],
        content_digest: &fingerprints[1],
        instruments: &instruments,
        timestamps: &timestamps,
        warmup: 1,
    };
    let feature = SeriesRef {
        axis,
        name: "x",
        fingerprint: &fingerprints[0],
        values: factor,
    };
    let mut targets = vec![TargetSeriesRef(SeriesRef {
        axis,
        name: "y",
        fingerprint: &fingerprints[1],
        values: label,
    })];
    let empty = vec![vec![None; 3]; factor.len()];
    if add_empty_target {
        targets.push(TargetSeriesRef(SeriesRef {
            axis,
            name: "empty",
            fingerprint: &fingerprints[2],
            values: &empty,
        }));
    }
    let input = EvaluationInput {
        axis,
        factors: &[FactorSeriesRef(feature)],
        targets: &targets,
        minimum_observations: 2,
    };
    let slices = [1, 2].map(|start_ns| TimeSlice {
        start_ns,
        end_ns: i128::from(start_ns) + 1,
    });
    evaluate(
        input,
        &StatisticsPlan::new(slices.to_vec(), vec![]).unwrap(),
    )
    .unwrap()
}

#[test]
fn observed_missing_counts_partition_rows_and_aggregate_invalid_samples_after_warmup() {
    let values =
        |rows: [[Option<i32>; 3]; 4]| rows.map(|row| row.map(|v| v.map(Decimal::from)).to_vec());
    let factor = values([
        [None, Some(1), Some(3)],
        [None, None, Some(3)],
        [None, Some(3), Some(3)],
        [None, None, Some(3)],
    ]);
    let label = values([
        [None, Some(2), Some(1)],
        [None, Some(4), Some(2)],
        [None, None, Some(3)],
        [None, None, Some(4)],
    ]);
    let report = coverage_report(&factor, &label, false);
    let reference = ComparisonRef::FactorTarget(0);
    let detail = report.detail_view(reference, 0, 3).unwrap();
    let rows = detail["rows"].as_array().unwrap();
    let once = json!({"missing_factor_only":1,"missing_target_only":1,"missing_both":1});
    let zero = json!({"missing_factor_only":0,"missing_target_only":0,"missing_both":0});
    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0]["status"], "INSUFFICIENT_OBSERVATIONS");
    assert_eq!(rows[0]["sample_count"], 1);
    assert_eq!(rows[0]["missing_counts"], once);
    assert_eq!(rows[1]["status"], "ZERO_VARIANCE_FEATURE");
    assert_eq!(rows[1]["sample_count"], 4);
    assert_eq!(rows[1]["missing_counts"], zero);
    assert_eq!(report.comparisons()[0].coverage.pair_count_total, 5);
    assert_eq!(
        report.comparison_view(reference).unwrap()["comparison"]["missing_counts"],
        once
    );
    assert_eq!(report.slice_view(0, 0).unwrap()["missing_counts"], once);
    assert_eq!(report.slice_view(0, 1).unwrap()["missing_counts"], zero);
}

#[test]
fn equal_pair_counts_distinguish_the_missing_side_and_are_independent_per_target() {
    let mut factor = Vec::new();
    let mut label = Vec::new();
    for n in 0..10 {
        let full = Some(Decimal::from(n));
        let sparse = (n < 2).then(|| Decimal::from(n));
        factor.push(vec![None, sparse.clone(), full.clone()]);
        label.push(vec![None, full, sparse]);
    }
    let report = coverage_report(&factor, &label, false);
    let both = coverage_report(&factor, &label, true);
    let comparison = &report.comparisons()[0];
    assert_eq!(comparison, &both.comparisons()[0]);
    let [first, second] = comparison.rows.as_slice() else {
        panic!("应有两条样本行")
    };
    for row in [first, second] {
        assert_eq!(row.sample_count, 2);
        assert_eq!(row.ic, Some(Decimal::from(1)));
        assert_eq!(row.rank_ic, row.ic);
    }
    assert_eq!(
        first.missing_counts,
        MissingCounts {
            missing_factor_only: 8,
            ..Default::default()
        }
    );
    assert_eq!(
        second.missing_counts,
        MissingCounts {
            missing_target_only: 8,
            ..Default::default()
        }
    );
}

#[test]
fn factor_pair_projects_exact_registered_metrics_and_binds_rows_to_operands() {
    let report = report(&[]);
    let reference = ComparisonRef::FactorPair(0);
    let single = report.comparison_view(reference).unwrap();
    let comparison = &single["comparison"];
    assert_eq!(
        report.summary_view().unwrap()["comparisons"][2],
        *comparison
    );
    for method in ["correlation", "rank_correlation"] {
        let scalars = comparison[method].as_object().unwrap();
        assert_eq!(scalars.len(), 2);
        for field in ["mean", "stddev_sample"] {
            assert_eq!(
                scalars[field]["metric_id"],
                format!("research.factor_pair.{method}.{field}@1")
            );
        }
    }
    let max = i128::from(i64::MAX);
    let detail = report.detail_view(reference, max, max + 1).unwrap();
    let locator = &comparison["comparison_ref"];
    assert_eq!(detail["comparison_ref"], *locator);
    assert_eq!(locator["first_factor"]["name"], "x");
    assert_eq!(locator["second_factor"]["name"], "y");
    assert_eq!(
        detail["rows"],
        json!([{"ts_event_ns":max.to_string(),"sample_count":3,
        "status":"ZERO_VARIANCE_SECOND_FACTOR","correlation":null,"rank_correlation":null}])
    );
}

#[test]
fn exported_conditions_distinguish_slice_plans_and_replay_the_same_plan() {
    let first = TimeSlice {
        start_ns: 1,
        end_ns: 2,
    };
    let second = TimeSlice {
        start_ns: 2,
        end_ns: 3,
    };
    let reference = ComparisonRef::FactorTarget(0);
    let positive_report = report(&[first]);
    let positive = positive_report.comparison_view(reference).unwrap();
    let slice = positive_report.slice_view(0, 0).unwrap();
    let full = positive_report.summary_view().unwrap();
    let detail = positive_report.detail_view(reference, 1, 2).unwrap();
    for locator in [
        &full["comparisons"][0]["comparison_ref"],
        &positive["comparison"]["comparison_ref"],
        &slice["comparison_ref"],
        &detail["comparison_ref"],
    ] {
        assert_eq!(
            locator["target"].get("max_lookahead_steps"),
            Some(&Value::Null)
        );
    }
    assert_eq!(
        slice["conditions"]["slice_policy"],
        json!({
            "time_axis":"OBSERVATION_TIME", "interval":"START_INCLUSIVE_END_EXCLUSIVE",
            "target_values":"FROM_FULL_PANEL_BEFORE_SLICING"
        })
    );
    let negative = report(&[second]).comparison_view(reference).unwrap();
    assert_eq!(
        positive["conditions"]["slice_count"],
        negative["conditions"]["slice_count"]
    );
    assert_eq!(
        positive["comparison"]["stability"]["ic"]["min_slice_mean"]["decimal_value"],
        "1"
    );
    assert_eq!(
        negative["comparison"]["stability"]["ic"]["min_slice_mean"]["decimal_value"],
        "-1"
    );
    let digest = &positive["conditions"]["slice_plan_digest"];
    assert_eq!(digest.as_str().unwrap().len(), 64);
    assert_ne!(*digest, negative["conditions"]["slice_plan_digest"]);
    assert_eq!(
        positive,
        report(&[first]).comparison_view(reference).unwrap()
    );
    assert_eq!(
        positive_report.slice_view(0, 0).unwrap()["conditions"]["slice_plan_digest"],
        *digest
    );
    assert_ne!(
        slice_plan_digest(&[first, second]),
        slice_plan_digest(&[second, first])
    );
    assert_ne!(
        slice_plan_digest(&[first]),
        slice_plan_digest(&[TimeSlice {
            start_ns: 1,
            end_ns: 3
        }])
    );
    assert_ne!(
        slice_plan_digest(&[first]),
        slice_plan_digest(&[TimeSlice {
            start_ns: 0,
            end_ns: 2
        }])
    );
}

#[test]
fn detail_views_preserve_nanoseconds_and_distinguish_zero_from_missing() {
    let report = report(&[]);
    let reference = ComparisonRef::FactorTarget(0);
    let single = report.comparison_view(reference).unwrap();
    let detail = report
        .detail_view(reference, 0, i128::from(i64::MAX) + 1)
        .unwrap();
    assert_eq!(
        single["comparison"]["comparison_ref"],
        detail["comparison_ref"]
    );
    assert_eq!(
        single["comparison"]["stability"]["request"],
        "NOT_REQUESTED"
    );
    assert_eq!(
        report.slice_view(0, 0).unwrap_err().0,
        "RESEARCH_VIEW_NOT_REQUESTED"
    );
    assert_eq!(
        detail["interval"],
        json!({"start_ns":"0","end_ns":"9223372036854775808"})
    );
    let rows = detail["rows"].as_array().unwrap();
    assert_eq!(rows.len(), 4);
    assert_eq!(rows[0]["ts_event_ns"], "1");
    assert_eq!(rows[2]["ic"], "0");
    assert_eq!(rows[2]["status"], "VALID");
    assert_eq!(rows[3]["ts_event_ns"], "9223372036854775807");
    assert_eq!(rows[3]["status"], "INSUFFICIENT_OBSERVATIONS");
    assert_eq!(rows[3]["ic"], Value::Null);
    assert_eq!(
        report
            .detail_view(reference, 3, i128::from(i64::MAX))
            .unwrap()["rows"],
        json!([rows[2]])
    );
}
