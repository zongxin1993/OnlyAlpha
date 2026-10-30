use onlyalpha_backend::application::research_statistics::{
    Comparison, Metric, Observation, Plan, Status, evaluate,
};
mod research_dataset;
mod research_factor;
mod research_runtime_lifecycle;

fn plan() -> Plan {
    serde_json::from_value(serde_json::json!({
        "schema_version":1,
        "bindings":{"dataset":"11".repeat(32),"feature_result":"22".repeat(32),
            "target_result":"33".repeat(32),"factor_revision":"44".repeat(32),"study":"55".repeat(32)},
        "start_ns":0,"end_ns":100,"bar_ns":1,"horizon_bars":1,
        "expected_block_length":4,"replicates":400,"confidence_bps":8000,"seed":"00".repeat(32),
        "family":[{"start_ns":0,"end_ns":100,"horizon_bars":1,"metric":"PEARSON"},
                  {"start_ns":0,"end_ns":100,"horizon_bars":1,"metric":"SPEARMAN"}]
    })).unwrap()
}
fn rows(values: &[(&str, &str)]) -> Vec<Observation> {
    values
        .iter()
        .enumerate()
        .map(|(i, (x, y))| Observation {
            at_ns: i as u64,
            feature: Some((*x).into()),
            target: Some((*y).into()),
        })
        .collect()
}
fn full() -> Vec<Observation> {
    (0..100)
        .map(|i| Observation {
            at_ns: i,
            feature: Some(((i * 7) % 13).to_string()),
            target: Some(((i * 11 + i / 3) % 17).to_string()),
        })
        .collect()
}
#[test]
fn exact_moments_and_average_ties_preserve_distinct_time_series_semantics() {
    let p = plan();
    let r = evaluate(
        &p,
        &rows(&[("1", "10"), ("1", "20"), ("3", "30"), ("4", "40")]),
    )
    .unwrap();
    assert_eq!(r.pearson.value.as_deref(), Some("0.946729262406"));
    assert_eq!(r.spearman.value.as_deref(), Some("0.948683298051"));
    assert_eq!(r.pearson.uncertainty_status, Status::InsufficientBlocks);
}
#[test]
fn forecast_boundary_and_numeric_normalization_bind_actual_input_content() {
    let mut p = plan();
    p.end_ns = 5;
    for item in &mut p.family {
        item.end_ns = 5;
    }
    let a = rows(&[
        ("1", "2"),
        ("2", "4"),
        ("3", "6"),
        ("4", "8"),
        ("999", "-999"),
    ]);
    let r = evaluate(&p, &a).unwrap();
    assert_eq!(r.pearson.value.as_deref(), Some("1.000000000000"));
    assert_eq!(r.diagnostics.boundary_excluded, 1);
    assert_eq!(r.diagnostics.complete_pairs, 4);
    let mut b = a.clone();
    b[0].feature = Some("01.000".into());
    assert_eq!(r, evaluate(&p, &b).unwrap());
    b[4].feature = Some("1000".into());
    assert_ne!(
        r.input_fingerprint,
        evaluate(&p, &b).unwrap().input_fingerprint
    );
}
#[test]
fn stationary_bootstrap_replays_exactly_and_binds_seed_and_family() {
    let p = plan();
    let input = full();
    let r = evaluate(&p, &input).unwrap();
    assert_eq!(r, evaluate(&p, &input).unwrap());
    assert_eq!(r.pearson.uncertainty_status, Status::Available);
    assert_eq!(r.spearman.uncertainty_status, Status::Available);
    assert!(r.pearson.interval.is_some());
    // Independent 80-digit Decimal reference, not Rust executor output.
    assert_eq!(r.pearson.value.as_deref(), Some("-0.011592265439"));
    assert_eq!(r.spearman.value.as_deref(), Some("-0.009769059597"));
    assert_eq!(
        r.pearson.interval,
        Some(["-0.159528965104".into(), "0.113261523038".into()])
    );
    assert_eq!(
        r.spearman.interval,
        Some(["-0.159953701717".into(), "0.121416335786".into()])
    );
    let mut changed = p.clone();
    changed.seed = "01".repeat(32);
    assert_ne!(
        r.plan_fingerprint,
        evaluate(&changed, &input).unwrap().plan_fingerprint
    );
    changed = p.clone();
    changed.family.push(Comparison {
        start_ns: 100,
        end_ns: 200,
        horizon_bars: 1,
        metric: Metric::Pearson,
    });
    let wider = evaluate(&changed, &input).unwrap();
    assert_eq!(
        wider.pearson.uncertainty_status,
        Status::TailResolutionInsufficient
    );
    assert_ne!(r.plan_fingerprint, wider.plan_fingerprint);
}
#[test]
fn missing_pairs_and_axis_gaps_never_become_iid_confidence() {
    let p = plan();
    let mut input = full();
    input[30].feature = None;
    let r = evaluate(&p, &input).unwrap();
    assert_eq!(r.pearson.uncertainty_status, Status::IncompletePairs);
    assert!(r.pearson.interval.is_none());
    assert_eq!(r.diagnostics.missing_feature, 1);
    input = full();
    input.remove(30);
    assert_eq!(
        evaluate(&p, &input).unwrap().pearson.uncertainty_status,
        Status::GappedAxis
    );
}
#[test]
fn zero_variance_short_samples_and_perfect_resamples_do_not_claim_certainty() {
    let p = plan();
    let mut input = full();
    for r in &mut input {
        r.feature = Some("7".into());
    }
    let result = evaluate(&p, &input).unwrap();
    assert_eq!(result.pearson.point_status, Status::ZeroVarianceFeature);
    assert!(result.pearson.value.is_none());
    input = full();
    for r in &mut input {
        r.target = r.feature.clone();
    }
    assert_eq!(
        evaluate(&p, &input).unwrap().pearson.uncertainty_status,
        Status::BootstrapDistributionDegenerate
    );
    let mut p = plan();
    p.expected_block_length = 10;
    assert_eq!(
        evaluate(&p, &full()).unwrap().pearson.uncertainty_status,
        Status::InsufficientBlocks
    );
}
#[test]
fn malformed_scopes_numbers_and_work_are_rejected_before_resampling() {
    let p = plan();
    let mut input = full();
    input[3].at_ns = 2;
    assert!(evaluate(&p, &input).is_err());
    for bad in ["NaN", "1e999999999", " 1", "+1", "0.0000000000000000001"] {
        input = full();
        input[0].feature = Some(bad.into());
        assert!(evaluate(&p, &input).is_err());
    }
    let mut bad = p.clone();
    bad.family.pop();
    assert!(evaluate(&bad, &full()).is_err());
    bad = p.clone();
    bad.family.push(bad.family[0].clone());
    assert!(evaluate(&bad, &full()).is_err());
    bad = p.clone();
    bad.horizon_bars = 4;
    assert!(evaluate(&bad, &full()).is_err());
    bad = p.clone();
    bad.bindings.dataset = "00".repeat(31);
    assert!(evaluate(&bad, &full()).is_err());
    bad = p;
    bad.replicates = 8193;
    assert!(evaluate(&bad, &full()).is_err());
}

#[test]
fn decimal_translation_and_sign_do_not_lose_sub_float_precision() {
    let mut p = plan();
    p.end_ns = 5;
    for c in &mut p.family {
        c.end_ns = 5;
    }
    let input = rows(&[
        ("1000000000000000000.000000000000000001", "-1"),
        ("1000000000000000000.000000000000000002", "-2"),
        ("1000000000000000000.000000000000000003", "-3"),
        ("1000000000000000000.000000000000000004", "-4"),
        ("0", "999"),
    ]);
    let r = evaluate(&p, &input).unwrap();
    assert_eq!(r.pearson.value.as_deref(), Some("-1.000000000000"));
    assert_eq!(r.spearman.value.as_deref(), Some("-1.000000000000"));
}

#[test]
fn every_forecast_label_crossing_the_partition_is_excluded() {
    let mut p = plan();
    p.horizon_bars = 3;
    for c in &mut p.family {
        c.horizon_bars = 3;
    }
    let mut input = full();
    let first = evaluate(&p, &input).unwrap();
    assert_eq!(first.diagnostics.boundary_excluded, 3);
    assert_eq!(first.diagnostics.complete_pairs, 97);
    for row in &mut input[97..] {
        row.target = Some("999999".into());
    }
    let changed = evaluate(&p, &input).unwrap();
    assert_eq!(first.pearson, changed.pearson);
    assert_eq!(first.spearman, changed.spearman);
    assert_ne!(first.input_fingerprint, changed.input_fingerprint);
}

#[test]
fn missing_warmup_and_tail_are_counted_without_compressing_interior_time() {
    let mut input = full();
    input[0].feature = None;
    input[98].target = None;
    let r = evaluate(&plan(), &input).unwrap();
    assert_eq!(r.diagnostics.complete_pairs, 97);
    assert_eq!(r.diagnostics.missing_feature, 1);
    assert_eq!(r.diagnostics.missing_target, 1);
    assert_eq!(r.pearson.uncertainty_status, Status::Available);
}

#[test]
fn undefined_resamples_are_counted_and_never_replaced_or_dropped() {
    let mut input = full();
    for r in &mut input {
        r.feature = Some(if r.at_ns == 40 { "1" } else { "0" }.into());
    }
    let r = evaluate(&plan(), &input).unwrap();
    assert_eq!(r.pearson.point_status, Status::Available);
    assert_eq!(
        r.pearson.uncertainty_status,
        Status::UndefinedBootstrapReplicates
    );
    assert!(r.pearson.undefined_replicates > 0);
    assert!(r.pearson.interval.is_none());
    assert_eq!(
        r.pearson.undefined_replicates,
        r.spearman.undefined_replicates
    );
}

#[test]
fn declared_family_order_is_canonical_and_more_comparisons_cannot_narrow_intervals() {
    let mut p = plan();
    p.replicates = 800;
    let first = evaluate(&p, &full()).unwrap();
    p.family.reverse();
    assert_eq!(first, evaluate(&p, &full()).unwrap());
    for metric in [Metric::Pearson, Metric::Spearman] {
        p.family.push(Comparison {
            start_ns: 100,
            end_ns: 200,
            horizon_bars: 1,
            metric,
        });
    }
    let wider = evaluate(&p, &full()).unwrap();
    for (a, b) in [
        (first.pearson, wider.pearson),
        (first.spearman, wider.spearman),
    ] {
        let a = a.interval.unwrap();
        let b = b.interval.unwrap();
        let number = |s: &str| s.parse::<bigdecimal::BigDecimal>().unwrap();
        assert!(number(&b[0]) <= number(&a[0]));
        assert!(number(&b[1]) >= number(&a[1]));
    }
}

#[test]
fn malformed_json_and_excessive_work_have_no_numeric_result() {
    let mut value = serde_json::to_value(plan()).unwrap();
    value["inference_fallback"] = serde_json::json!("IID");
    assert!(serde_json::from_value::<Plan>(value).is_err());
    let mut p = plan();
    p.end_ns = 4096;
    p.replicates = 8192;
    for c in &mut p.family {
        c.end_ns = 4096;
    }
    let input: Vec<_> = (0..4096)
        .map(|i| Observation {
            at_ns: i,
            feature: Some("1".into()),
            target: Some("2".into()),
        })
        .collect();
    assert_eq!(
        evaluate(&p, &input).unwrap_err(),
        "STATISTICS_RESOURCE_OR_SCOPE_INVALID"
    );
}

#[test]
fn fresh_process_reproduces_complete_statistical_output() {
    let expected = serde_json::to_string(&evaluate(&plan(), &full()).unwrap()).unwrap();
    if std::env::var_os("ONLYALPHA_STATISTICS_CHILD").is_some() {
        println!("STATISTICS_RECORD={expected}");
        return;
    }
    let output = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "fresh_process_reproduces_complete_statistical_output",
            "--nocapture",
            "--test-threads=1",
        ])
        .env("ONLYALPHA_STATISTICS_CHILD", "1")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        String::from_utf8(output.stdout)
            .unwrap()
            .contains(&format!("STATISTICS_RECORD={expected}"))
    );
}

#[test]
fn excluded_forecast_tail_and_trimmed_edges_preserve_contiguous_inference() {
    let p = plan();
    let mut input = full();
    let complete = evaluate(&p, &input).unwrap();
    input.pop(); // timestamp99 never supplies a within-partition label.
    let without_tail = evaluate(&p, &input).unwrap();
    assert_eq!(without_tail.pearson, complete.pearson);
    assert_eq!(without_tail.spearman, complete.spearman);
    assert_eq!(without_tail.diagnostics.axis_gaps, 1);
    input.remove(0);
    assert_eq!(
        evaluate(&p, &input).unwrap().pearson.uncertainty_status,
        Status::Available
    );
    input.remove(30);
    assert_eq!(
        evaluate(&p, &input).unwrap().pearson.uncertainty_status,
        Status::GappedAxis
    );
}

mod research_runtime;

mod research_specification;
#[path = "research_namespace.rs"]
mod research_namespace;
