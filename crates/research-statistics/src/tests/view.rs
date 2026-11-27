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
