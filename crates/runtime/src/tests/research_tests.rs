use super::*;
use StatisticStatus::{
    InsufficientObservations, NoValidObservations, Valid, ZeroVariance, ZeroVarianceFeature,
    ZeroVarianceTarget,
};
use std::str::FromStr;

const SNAPSHOT: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

fn d(text: &str) -> Decimal {
    Decimal::from_str(text).unwrap()
}

fn values(items: &[&str]) -> Vec<Cell> {
    items
        .iter()
        .map(|item| if *item == "null" { None } else { Some(d(item)) })
        .collect()
}

fn cohort(columns: &[(&str, &[&str])]) -> Cohort {
    columns
        .iter()
        .map(|(name, items)| ((*name).to_string(), values(items)))
        .collect()
}

fn timestamps(times: &[i64]) -> Vec<OnlyTimestamp> {
    times
        .iter()
        .map(|&t| OnlyTimestamp::from_unix_nanos(t.into()))
        .collect()
}

type InstrumentData = (OnlyInstrumentId, Vec<OnlyTimestamp>, Cohort);

fn instrument(id: &str, times: &[i64], columns: Cohort) -> InstrumentData {
    (id.parse().unwrap(), timestamps(times), columns)
}

fn panel(instruments: Vec<Cohort>) -> ResearchPanel {
    let data = instruments
        .into_iter()
        .enumerate()
        .map(|(i, columns)| {
            let len = columns.values().next().unwrap().len() as i64;
            instrument(
                &format!("S{i}.TEST"),
                &(1..=len).collect::<Vec<_>>(),
                columns,
            )
        })
        .collect();
    ResearchPanel::new(SNAPSHOT, data, 0).unwrap()
}

fn plan(
    factors: &[(&str, &str)],
    targets: &[(&str, &str)],
    minimum: usize,
) -> Result<ResearchPlan, Error> {
    ResearchPlan::new(
        factors
            .iter()
            .map(|&(name, source)| (name.into(), FactorExpr::compile(source).unwrap()))
            .collect(),
        targets
            .iter()
            .map(|&(name, source)| (name.into(), TargetExpr::compile(source).unwrap()))
            .collect(),
        minimum,
    )
}

fn run(panel: &ResearchPanel, factor: &str, target: &str, minimum: usize) -> ResearchReport {
    let plan = plan(&[("signal", factor)], &[("label", target)], minimum).unwrap();
    ResearchEngine::new().unwrap().run(panel, &plan).unwrap()
}

fn assert_row(
    row: &StatisticRow,
    count: usize,
    status: StatisticStatus,
    ic: Option<&str>,
    rank_ic: Option<&str>,
) {
    assert_eq!(row.sample_count, count);
    assert_eq!(row.status, status);
    assert_eq!(row.ic, ic.map(d));
    assert_eq!(row.rank_ic, rank_ic.map(d));
}

#[test]
fn linear_relation_gives_full_ic_and_a_flat_ic_series() {
    let panel = panel(vec![
        cohort(&[("close", &["1", "2", "3", "4", "5"])]),
        cohort(&[("close", &["2", "3", "4", "5", "6"])]),
        cohort(&[("close", &["3", "4", "5", "6", "7"])]),
        cohort(&[("close", &["4", "5", "6", "7", "8"])]),
    ]);
    let report = run(&panel, "$close", "Ref($close, -1)", 2);
    assert_eq!(report.instruments().len(), 4);
    assert_eq!(report.timestamps().len(), 5);
    assert_eq!(
        report.factors()[0].values[0],
        values(&["1", "2", "3", "4", "5"])
    );
    assert_eq!(
        report.targets()[0].values[0],
        values(&["2", "3", "4", "5", "null"])
    );
    let result = &report.comparisons()[0];
    assert_eq!(result.rows.len(), 5);
    for row in &result.rows[..4] {
        assert_row(row, 4, Valid, Some("1"), Some("1"));
    }
    assert_row(&result.rows[4], 0, InsufficientObservations, None, None);
    assert_eq!(result.ic_statistics, result.rank_ic_statistics);
    let stats = &result.ic_statistics;
    assert_eq!(stats.observations, 4);
    assert_eq!(stats.mean, Some(d("1")));
    assert_eq!(stats.mean_status, Valid);
    assert_eq!(stats.std, Some(d("0")));
    assert_eq!(stats.std_status, Valid);
    assert_eq!(stats.ir, None);
    assert_eq!(stats.ir_status, ZeroVariance);
}

#[test]
fn rank_ic_removes_monotone_distortion_and_one_observation_has_only_a_mean() {
    let panel = panel(vec![
        cohort(&[("close", &["1", "1"])]),
        cohort(&[("close", &["2", "4"])]),
        cohort(&[("close", &["3", "9"])]),
        cohort(&[("close", &["4", "16"])]),
    ]);
    let report = run(&panel, "$close", "Ref($close, -1)", 2);
    let result = &report.comparisons()[0];
    // 平方变换保留秩序。Pearson 系数为 25 / sqrt(645)。
    assert_row(&result.rows[0], 4, Valid, Some("0.984374038698"), Some("1"));
    assert_row(&result.rows[1], 0, InsufficientObservations, None, None);
    for (stats, mean) in [
        (&result.ic_statistics, &result.rows[0].ic),
        (&result.rank_ic_statistics, &result.rows[0].rank_ic),
    ] {
        assert_eq!(stats.observations, 1);
        assert_eq!(&stats.mean, mean);
        assert_eq!(stats.mean_status, Valid);
        assert_eq!(stats.std, None);
        assert_eq!(stats.std_status, InsufficientObservations);
        assert_eq!(stats.ir, None);
        assert_eq!(stats.ir_status, InsufficientObservations);
    }
}

#[test]
fn missing_first_instrument_does_not_hide_valid_ic() {
    let panel = panel(vec![
        cohort(&[("close", &["null"]), ("volume", &["5"])]),
        cohort(&[("close", &["1"]), ("volume", &["3"])]),
        cohort(&[("close", &["2"]), ("volume", &["1"])]),
    ]);
    let report = run(&panel, "$close", "$volume", 2);
    assert_row(
        &report.comparisons()[0].rows[0],
        2,
        Valid,
        Some("-1"),
        Some("-1"),
    );
}

#[test]
fn rank_ic_and_minimum_use_only_instruments_with_both_values() {
    let panel = panel(vec![
        cohort(&[("close", &["1"]), ("volume", &["10"])]),
        cohort(&[("close", &["2"]), ("volume", &["null"])]),
        cohort(&[("close", &["3"]), ("volume", &["20"])]),
        cohort(&[("close", &["4"]), ("volume", &["30"])]),
        cohort(&[("close", &["null"]), ("volume", &["25"])]),
    ]);
    let accepted = run(&panel, "$close", "$volume", 3);
    assert_eq!(accepted.comparisons()[0].rows[0].rank_ic, Some(d("1")));
    assert_eq!(accepted.comparisons()[0].rows[0].sample_count, 3);
    let insufficient = run(&panel, "$close", "$volume", 4);
    assert_row(
        &insufficient.comparisons()[0].rows[0],
        3,
        InsufficientObservations,
        None,
        None,
    );
}

#[test]
fn ic_preserves_small_differences_at_large_offsets() {
    let a = "9000000000000000.000000000001";
    let b = "9000000000000000.000000000002";
    let panel = panel(vec![
        cohort(&[("close", &["null", "null"]), ("volume", &["0", "0"])]),
        cohort(&[("close", &[a, a]), ("volume", &[a, b])]),
        cohort(&[("close", &[a, b]), ("volume", &[a, a])]),
    ]);
    let report = run(&panel, "$close", "$volume", 2);
    let rows = &report.comparisons()[0].rows;
    assert_row(&rows[0], 2, ZeroVarianceFeature, None, None);
    assert_row(&rows[1], 2, Valid, Some("-1"), Some("-1"));
}

#[test]
fn rank_ic_uses_exact_average_ranks_for_ties() {
    let panel = panel(vec![
        cohort(&[("close", &["null"]), ("volume", &["1"])]),
        cohort(&[("close", &["0"]), ("volume", &["0"])]),
        cohort(&[("close", &["1"]), ("volume", &["0"])]),
        cohort(&[("close", &["2"]), ("volume", &["1"])]),
        cohort(&[("close", &["3"]), ("volume", &["0"])]),
    ]);
    let report = run(&panel, "$close", "$volume", 2);
    // 有效秩为 (1,2,3,4) 和 (2,2,4,2)，相关系数是 1/sqrt(15)。
    assert_row(
        &report.comparisons()[0].rows[0],
        4,
        Valid,
        Some("0.258198889747"),
        Some("0.258198889747"),
    );
}

#[test]
fn rank_ic_assigns_midpoints_to_ties_and_preserves_later_rank_positions() {
    let panel = panel(vec![
        cohort(&[("close", &["1"]), ("volume", &["1"])]),
        cohort(&[("close", &["2"]), ("volume", &["1"])]),
        cohort(&[("close", &["3"]), ("volume", &["2"])]),
        cohort(&[("close", &["4"]), ("volume", &["3"])]),
    ]);
    let report = run(&panel, "$close", "$volume", 2);
    // 标签的平均秩为 (1.5, 1.5, 3, 4)，RankIC 为 3/√10。稠密秩会给出原始 IC。
    assert_row(
        &report.comparisons()[0].rows[0],
        4,
        Valid,
        Some("0.943879807449"),
        Some("0.948683298051"),
    );
}

#[test]
fn statistics_cover_every_defined_event_and_ignore_the_rest() {
    let panel = panel(vec![
        cohort(&[("close", &["1", "null", "3"]), ("volume", &["1", "2", "3"])]),
        cohort(&[("close", &["2", "null", "4"]), ("volume", &["2", "3", "4"])]),
        cohort(&[("close", &["3", "3", "2"]), ("volume", &["3", "4", "5"])]),
    ]);
    let report = run(&panel, "$close", "$volume", 2);
    let result = &report.comparisons()[0];
    assert_row(&result.rows[0], 3, Valid, Some("1"), Some("1"));
    assert_row(&result.rows[1], 1, InsufficientObservations, None, None);
    assert_row(&result.rows[2], 3, Valid, Some("-0.5"), Some("-0.5"));
    for stats in [&result.ic_statistics, &result.rank_ic_statistics] {
        assert_eq!(stats.observations, 2);
        assert_eq!(stats.mean, Some(d("0.25")));
        // 两个有效时点的样本标准差为 3√2/4，非年化 IR 为 √2/6。
        assert_eq!(stats.std, Some(d("1.060660171780")));
        assert_eq!(stats.ir, Some(d("0.235702260396")));
        assert_eq!(stats.mean_status, Valid);
        assert_eq!(stats.std_status, Valid);
        assert_eq!(stats.ir_status, Valid);
    }
}

#[test]
fn information_ratio_uses_the_unrounded_sample_deviation() {
    let panel = panel(vec![
        cohort(&[("close", &["1", "1"]), ("volume", &["1", "1"])]),
        cohort(&[("close", &["2", "2"]), ("volume", &["2", "2"])]),
        cohort(&[("close", &["3", "3"]), ("volume", &["3", "1"])]),
    ]);
    let report = run(&panel, "$close", "$volume", 2);
    let result = &report.comparisons()[0];
    assert_row(&result.rows[0], 3, Valid, Some("1"), Some("1"));
    assert_row(&result.rows[1], 3, Valid, Some("0"), Some("0"));
    // (1,0) 的样本标准差和 IR 都等于 √2/2。先舍入分母会使 IR 的末位变为 6。
    for stats in [&result.ic_statistics, &result.rank_ic_statistics] {
        assert_eq!(stats.observations, 2);
        assert_eq!(stats.mean, Some(d("0.5")));
        assert_eq!(stats.std, Some(d("0.707106781187")));
        assert_eq!(stats.ir, Some(d("0.707106781187")));
    }
}

#[test]
fn constant_sides_and_empty_pairs_preserve_the_reason_for_absent_statistics() {
    let panel = panel(vec![
        cohort(&[("close", &["1", "1", "null"]), ("volume", &["1", "4", "1"])]),
        cohort(&[("close", &["1", "2", "null"]), ("volume", &["2", "4", "2"])]),
        cohort(&[("close", &["1", "3", "null"]), ("volume", &["3", "4", "3"])]),
    ]);
    let report = run(&panel, "$close", "$volume", 2);
    let result = &report.comparisons()[0];
    assert_row(&result.rows[0], 3, ZeroVarianceFeature, None, None);
    assert_row(&result.rows[1], 3, ZeroVarianceTarget, None, None);
    assert_row(&result.rows[2], 0, InsufficientObservations, None, None);
    for stats in [&result.ic_statistics, &result.rank_ic_statistics] {
        assert_eq!(stats.observations, 0);
        assert_eq!(stats.mean, None);
        assert_eq!(stats.mean_status, NoValidObservations);
        assert_eq!(stats.std, None);
        assert_eq!(stats.std_status, InsufficientObservations);
        assert_eq!(stats.ir, None);
        assert_eq!(stats.ir_status, InsufficientObservations);
    }
}

#[test]
fn cross_section_factors_run_over_the_aligned_panel() {
    let panel = panel(vec![
        cohort(&[("close", &["1", "2"])]),
        cohort(&[("close", &["2", "4"])]),
        cohort(&[("close", &["3", "1"])]),
        cohort(&[("close", &["4", "3"])]),
    ]);
    let report = run(&panel, "CSDemean($close)", "$close", 2);
    assert_eq!(report.factors()[0].values[0], values(&["-1.5", "-0.5"]));
    for row in &report.comparisons()[0].rows {
        assert_row(row, 4, Valid, Some("1"), Some("1"));
    }
}

#[test]
fn each_factor_target_pair_uses_its_frozen_definitions_axes_and_sample() {
    let times = [10, 30];
    let axes = vec![
        instrument(
            "A.TEST",
            &times,
            cohort(&[
                ("close", &["1", "3"]),
                ("volume", &["0", "3"]),
                ("open", &["5", "1"]),
            ]),
        ),
        instrument(
            "B.TEST",
            &times,
            cohort(&[
                ("close", &["3", "5"]),
                ("volume", &["0", "1"]),
                ("open", &["5", "3"]),
            ]),
        ),
        instrument(
            "C.TEST",
            &times,
            cohort(&[
                ("close", &["5", "7"]),
                ("volume", &["0", "2"]),
                ("open", &["5", "2"]),
            ]),
        ),
    ];
    let ids: Vec<_> = axes.iter().map(|(id, _, _)| id.clone()).collect();
    let ordered = ResearchPanel::new(SNAPSHOT, axes.clone(), 1).unwrap();
    let panel = ResearchPanel::new(SNAPSHOT, axes.into_iter().rev().collect(), 1).unwrap();
    panel.verify_content(ordered.content_digest()).unwrap();
    let plan = plan(
        &[("price", "Mean($close, 2)"), ("quantity", "$volume")],
        &[("today", "$close"), ("opening", "$open")],
        3,
    )
    .unwrap();
    let engine = ResearchEngine::new().unwrap();
    let report = engine.run(&panel, &plan).unwrap();
    assert_eq!(engine.run(&panel, &plan).unwrap(), report);
    assert_eq!(panel.instrument_ids(), ids.as_slice());
    assert_eq!(panel.timestamps(), timestamps(&times).as_slice());
    assert_eq!(report.instruments(), ids);
    assert_eq!(report.timestamps(), timestamps(&times));
    assert_eq!(report.snapshot(), SNAPSHOT);
    assert_eq!(report.content_digest(), panel.content_digest());
    panel.verify_content(report.content_digest()).unwrap();
    assert_eq!(report.warmup(), 1);
    assert_eq!(report.minimum_observations(), 3);
    assert_eq!(report.factors().len(), 2);
    assert_eq!(report.targets().len(), 2);
    for (series, name, fingerprint, matrix) in [
        (
            &report.factors()[0],
            "price",
            FactorExpr::compile("Mean($close, 2)")
                .unwrap()
                .fingerprint()
                .to_owned(),
            [
                values(&["null", "2"]),
                values(&["null", "4"]),
                values(&["null", "6"]),
            ],
        ),
        (
            &report.factors()[1],
            "quantity",
            FactorExpr::compile("$volume")
                .unwrap()
                .fingerprint()
                .to_owned(),
            [
                values(&["0", "3"]),
                values(&["0", "1"]),
                values(&["0", "2"]),
            ],
        ),
        (
            &report.targets()[0],
            "today",
            TargetExpr::compile("$close")
                .unwrap()
                .fingerprint()
                .to_owned(),
            [
                values(&["1", "3"]),
                values(&["3", "5"]),
                values(&["5", "7"]),
            ],
        ),
        (
            &report.targets()[1],
            "opening",
            TargetExpr::compile("$open")
                .unwrap()
                .fingerprint()
                .to_owned(),
            [
                values(&["5", "1"]),
                values(&["5", "3"]),
                values(&["5", "2"]),
            ],
        ),
    ] {
        assert_eq!(series.name, name);
        assert_eq!(series.fingerprint, fingerprint);
        assert_eq!(series.values, matrix);
    }
    let expected = [["1", "0.5"], ["-0.5", "-1"]];
    assert_eq!(report.comparisons().len(), 4);
    let mut seen = BTreeSet::new();
    for pair in report.comparisons() {
        assert!(seen.insert((pair.factor_index, pair.target_index)));
        let value = expected[pair.factor_index][pair.target_index];
        assert_eq!(pair.rows.len(), 1);
        assert_row(&pair.rows[0], 3, Valid, Some(value), Some(value));
        for stats in [&pair.ic_statistics, &pair.rank_ic_statistics] {
            assert_eq!(stats.observations, 1);
            assert_eq!(stats.mean, Some(d(value)));
        }
    }
}

#[test]
fn frozen_content_digest_binds_the_sample_axes_fields_and_values() {
    let make = |id, times: &[i64], field, first, last, warmup| {
        let columns = cohort(&[(field, &[first, last])]);
        ResearchPanel::new(SNAPSHOT, vec![instrument(id, times, columns)], warmup).unwrap()
    };
    let original = make("A.TEST", &[10, 20], "close", "1", "null", 0);
    let digest = original.content_digest();
    assert_eq!(digest.len(), 64);
    assert!(
        digest
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    );
    make("A.TEST", &[10, 20], "close", "1.00", "null", 0)
        .verify_content(digest)
        .unwrap();
    for changed in [
        make("B.TEST", &[10, 20], "close", "1", "null", 0),
        make("A.TEST", &[10, 21], "close", "1", "null", 0),
        make("A.TEST", &[10, 20], "open", "1", "null", 0),
        make("A.TEST", &[10, 20], "close", "1", "0", 0),
        make("A.TEST", &[10, 20], "close", "1", "null", 1),
    ] {
        assert_ne!(changed.content_digest(), digest);
        assert!(changed.verify_content(digest).is_err());
    }
}

#[test]
fn plans_reject_duplicate_names_empty_definitions_and_invalid_minimum() {
    let factors = [("x", "$close"), ("x", "$volume")];
    let targets = [("y", "$close"), ("y", "$volume")];
    assert!(plan(&factors, &targets[..1], 2).is_err());
    assert!(plan(&factors[..1], &targets, 2).is_err());
    assert!(plan(&[], &targets[..1], 2).is_err());
    assert!(plan(&factors[..1], &[], 2).is_err());
    assert!(plan(&factors[..1], &targets[..1], 1).is_err());
    assert!(plan(&[("", "$close")], &targets[..1], 2).is_err());
}

#[test]
fn plan_rejects_a_cross_section_operator_nested_in_a_target() {
    let targets = [
        ("next_close", "Ref($close, -1)"),
        ("adjusted", "Mean(CSDemean($close), 2)"),
    ];
    let failure = plan(&[("price", "$close")], &targets, 2).unwrap_err();
    assert_eq!(failure, Error("RESEARCH_TARGET_SHAPE".into()));
}

#[test]
fn cumulative_dag_budget_counts_both_factor_and_target_work() {
    // 256 个单元格上，一个十万期窗口约需 2560 万工作量，两者叠加超过 5000 万。
    let panel = panel(vec![Cohort::from([("close".into(), vec![None; 256])])]);
    let rolling = "Mean($close, 100000)";
    let engine = ResearchEngine::new().unwrap();
    for (factor, target) in [(rolling, "$close"), ("$close", rolling)] {
        let single_window = plan(&[("price", factor)], &[("label", target)], 2).unwrap();
        engine.run(&panel, &single_window).unwrap();
    }
    let both_windows = plan(&[("price", rolling)], &[("label", rolling)], 2).unwrap();
    let failure = engine.run(&panel, &both_windows).unwrap_err();
    assert_eq!(failure, Error("RESEARCH_RESOURCE_BUDGET".into()));
}

#[test]
fn constant_dags_count_the_panel_columns_scanned_to_determine_series_length() {
    use onlyalpha_operators::algebra::{MAX_CELLS, MAX_WINDOW_WORK};

    let field_count = 5000;
    let columns = (0..field_count)
        .map(|i| (format!("f{i}"), vec![None]))
        .collect();
    let panel = panel(vec![columns]);
    let constant = FactorExpr::compile("1").unwrap();
    assert!(constant.inputs().is_empty());
    let constant_count = MAX_WINDOW_WORK / field_count + 1;
    // 首个因子缺列。若遗漏预算检查，会直接返回缺列错误，避免实际执行全部扫描。
    let mut factors = vec![("missing".into(), FactorExpr::compile("$close").unwrap())];
    factors.extend((0..constant_count).map(|i| (format!("k{i}"), constant.clone())));
    let targets = vec![("label".into(), TargetExpr::compile("1").unwrap())];
    // 单标的、单时点的矩阵格数等于定义数，配对槽位等于因子数乘以标签数。
    assert!(factors.len() + targets.len() < MAX_CELLS);
    assert!(factors.len() * targets.len() < MAX_WINDOW_WORK);
    assert!(constant_count * field_count > MAX_WINDOW_WORK);
    let plan = ResearchPlan::new(factors, targets, 2).unwrap();
    let failure = ResearchEngine::new()
        .unwrap()
        .run(&panel, &plan)
        .unwrap_err();
    assert_eq!(failure, Error("RESEARCH_RESOURCE_BUDGET".into()));
}

#[test]
fn panel_field_name_accepts_the_byte_limit_and_rejects_one_extra_byte() {
    use onlyalpha_calculation::factor_expr::MAX_IDENT_LEN;

    let make = |name: &str| {
        let data = instrument("A.TEST", &[1], cohort(&[(name, &["1"])]));
        ResearchPanel::new(SNAPSHOT, vec![data], 0)
    };
    let at_limit = "x".repeat(MAX_IDENT_LEN);
    make(&at_limit).unwrap();
    let failure = make(&format!("{at_limit}x")).unwrap_err();
    assert_eq!(failure, Error("RESEARCH_PANEL_SCHEMA".into()));
}

#[test]
fn input_budget_counts_every_field_before_digesting_any_cell() {
    let periods = 1000;
    let field_count = onlyalpha_operators::algebra::MAX_CELLS / periods + 1;
    let mut columns: Cohort = (0..field_count)
        .map(|i| (format!("field{i}"), vec![None; periods]))
        .collect();
    // 摘要函数会拒绝此数值。如果先计算摘要，此处会得到数值错误而非预算错误。
    columns.get_mut("field0").unwrap()[0] = Some(d("1e1025"));
    let times: Vec<_> = (0..periods as i64).collect();
    let failure =
        ResearchPanel::new(SNAPSHOT, vec![instrument("A.TEST", &times, columns)], 0).unwrap_err();
    assert_eq!(failure, Error("RESEARCH_RESOURCE_BUDGET".into()));
}

#[test]
fn panel_time_axis_accepts_both_i64_nanosecond_endpoints_and_rejects_their_neighbors() {
    let endpoints = [i64::MIN, i64::MAX];
    let data = instrument("A.TEST", &endpoints, cohort(&[("close", &["1", "2"])]));
    let panel = ResearchPanel::new(SNAPSHOT, vec![data], 0).unwrap();
    assert_eq!(panel.timestamps(), timestamps(&endpoints));
    for outside in [i128::from(i64::MIN) - 1, i128::from(i64::MAX) + 1] {
        let axis = vec![OnlyTimestamp::from_unix_nanos(outside.into())];
        let data = (
            "A.TEST".parse().unwrap(),
            axis,
            cohort(&[("close", &["1"])]),
        );
        let failure = ResearchPanel::new(SNAPSHOT, vec![data], 0).unwrap_err();
        assert_eq!(failure, Error("RESEARCH_PANEL_TIME_AXIS".into()));
    }
}

#[test]
fn a_batch_above_the_comparison_budget_is_rejected_before_evaluation() {
    let panel = panel(vec![cohort(&[("close", &["2"])])]);
    // 缺少 volume 列能区分预算检查和表达式求值，避免测试错误地分配百万个结果。
    let factor = FactorExpr::compile("$volume").unwrap();
    let target = TargetExpr::compile("$close").unwrap();
    let factors = (0..1001)
        .map(|i| (format!("f{i}"), factor.clone()))
        .collect();
    let targets = (0..1000)
        .map(|i| (format!("t{i}"), target.clone()))
        .collect();
    let plan = ResearchPlan::new(factors, targets, 2).unwrap();
    let failure = ResearchEngine::new()
        .unwrap()
        .run(&panel, &plan)
        .unwrap_err();
    assert_eq!(failure, Error("RESEARCH_RESOURCE_BUDGET".into()));
}

#[test]
fn runtime_reports_observed_pairs_signs_and_the_last_timestamp_slice() {
    let times = [i64::MAX - 3, i64::MAX - 2, i64::MAX - 1, i64::MAX];
    let panel = ResearchPanel::new(
        SNAPSHOT,
        vec![
            instrument(
                "A.TEST",
                &times,
                cohort(&[
                    ("close", &["1", "1", "1", "null"]),
                    ("volume", &["1", "3", "2", "1"]),
                ]),
            ),
            instrument(
                "B.TEST",
                &times,
                cohort(&[
                    ("close", &["2", "2", "2", "2"]),
                    ("volume", &["2", "2", "1", "null"]),
                ]),
            ),
            instrument(
                "C.TEST",
                &times,
                cohort(&[
                    ("close", &["3", "3", "3", "3"]),
                    ("volume", &["3", "1", "2", "3"]),
                ]),
            ),
        ],
        0,
    )
    .unwrap();
    let base = plan(
        &[("price", "$close"), ("quantity", "$volume")],
        &[("label", "$volume")],
        2,
    )
    .unwrap();
    let slices = vec![
        TimeSlice {
            start_ns: 0,
            end_ns: 1,
        },
        TimeSlice {
            start_ns: times[0],
            end_ns: times[1].into(),
        },
        TimeSlice {
            start_ns: times[1],
            end_ns: times[2].into(),
        },
        TimeSlice {
            start_ns: times[2],
            end_ns: times[3].into(),
        },
        TimeSlice {
            start_ns: times[3],
            end_ns: i128::from(i64::MAX) + 1,
        },
    ];
    let runtime = crate::OnlyAlphaRuntime::new().unwrap();
    let run_pair = |first: &str, second: &str| {
        let statistics =
            StatisticsPlan::new(slices.clone(), vec![(first.into(), second.into())]).unwrap();
        runtime
            .run_research(&panel, &base.clone().with_statistics(statistics).unwrap())
            .unwrap()
    };
    let report = run_pair("price", "quantity");
    let stats = report.factor_report();
    assert_eq!(stats, run_pair("quantity", "price").factor_report());
    assert_eq!(stats.pairs().len(), 1);
    let pair = &stats.pairs()[0];
    assert!(
        stats.factors()[pair.first_index].fingerprint
            < stats.factors()[pair.second_index].fingerprint
    );
    let comparison = &report.comparisons()[0];
    for (row, pair_row) in comparison.rows.iter().zip(&pair.rows) {
        assert_eq!(pair_row.correlation, row.ic);
        assert_eq!(pair_row.rank_correlation, row.rank_ic);
    }
    let signs = &comparison.ic_statistics.signs;
    assert_eq!(
        (signs.positive_count, signs.negative_count, signs.zero_count),
        (1, 1, 1)
    );
    let coverage = &comparison.coverage;
    assert_eq!(
        (
            coverage.total_timestamp_count,
            coverage.valid_timestamp_count,
            coverage.pair_count_total
        ),
        (4, 3, 10)
    );
    let stability = comparison.stability.as_ref().unwrap();
    assert_eq!(stability.slices[0].coverage.total_timestamp_count, 0);
    assert_eq!(stability.ic.valid_slice_count, 3);
    assert_eq!(stability.ic.min_slice_mean, Some(d("-1")));
    assert_eq!(stability.slices[4].coverage.insufficient_timestamp_count, 1);
    assert_eq!(
        stats.slice_view(0, 4).unwrap()["interval"]["end_ns"],
        "9223372036854775808"
    );
}

#[test]
fn runtime_checks_slice_summary_budget_before_evaluating_missing_fields() {
    let panel = panel(vec![cohort(&[("close", &["2"])])]);
    let factor = FactorExpr::compile("$volume").unwrap();
    let factors = (0..1000)
        .map(|i| (format!("f{i}"), factor.clone()))
        .collect();
    let targets = vec![("label".into(), TargetExpr::compile("$close").unwrap())];
    let slices = (0..999)
        .map(|i| TimeSlice {
            start_ns: i,
            end_ns: i128::from(i) + 1,
        })
        .collect();
    let statistics = StatisticsPlan::new(slices, vec![]).unwrap();
    let plan = ResearchPlan::new(factors, targets, 2)
        .unwrap()
        .with_statistics(statistics)
        .unwrap();
    let failure = crate::OnlyAlphaRuntime::new()
        .unwrap()
        .run_research(&panel, &plan)
        .unwrap_err();
    assert_eq!(failure, Error("RESEARCH_RESOURCE_BUDGET".into()));
}

#[test]
fn panels_require_a_snapshot_and_aligned_unique_instrument_and_time_axes() {
    let data = |id, times: &[i64]| instrument(id, times, cohort(&[("close", &["1", "2"])]));
    for snapshot in [
        "",
        &SNAPSHOT[..63],
        &SNAPSHOT.to_uppercase(),
        &"g".repeat(64),
    ] {
        assert!(ResearchPanel::new(snapshot, vec![data("A.TEST", &[1, 2])], 0).is_err());
    }
    assert!(ResearchPanel::new(SNAPSHOT, vec![], 0).is_err());
    assert!(ResearchPanel::new(SNAPSHOT, vec![data("A.TEST", &[1, 2])], 2).is_err());
    for times in [&[1, 1][..], &[2, 1], &[1], &[]] {
        assert!(ResearchPanel::new(SNAPSHOT, vec![data("A.TEST", times)], 0).is_err());
    }
    for second in [data("A.TEST", &[1, 2]), data("B.TEST", &[1, 3])] {
        assert!(ResearchPanel::new(SNAPSHOT, vec![data("A.TEST", &[1, 2]), second], 0).is_err());
    }
}

#[test]
fn panel_shape_and_schema_are_strict() {
    let no_fields = instrument("A.TEST", &[1, 2], Cohort::new());
    assert_eq!(
        ResearchPanel::new(SNAPSHOT, vec![no_fields], 0).unwrap_err(),
        Error("RESEARCH_PANEL_NO_FIELDS".into())
    );
    let first = instrument("A.TEST", &[1, 2], cohort(&[("close", &["1", "2"])]));
    for columns in [
        cohort(&[("volume", &["1", "2"])]),
        cohort(&[("close", &["1"])]),
    ] {
        let other = instrument("B.TEST", &[1, 2], columns);
        assert!(ResearchPanel::new(SNAPSHOT, vec![first.clone(), other], 0).is_err());
    }
    let empty = instrument("A.TEST", &[], cohort(&[("close", &[])]));
    assert!(ResearchPanel::new(SNAPSHOT, vec![empty], 0).is_err());
}
