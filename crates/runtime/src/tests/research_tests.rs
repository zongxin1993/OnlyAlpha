use super::*;
use std::str::FromStr;

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

fn panel(instruments: Vec<Cohort>) -> ResearchPanel {
    ResearchPanel::new(instruments).unwrap()
}

fn engine() -> ResearchEngine {
    ResearchEngine::new().unwrap()
}

fn run(panel: &ResearchPanel, factor: &str, target: &str) -> ResearchReport {
    engine()
        .run(
            panel,
            &FactorExpr::compile(factor).unwrap(),
            &TargetExpr::compile(target).unwrap(),
        )
        .unwrap()
}

#[test]
fn linear_relation_gives_full_ic_and_a_flat_ic_series() {
    let panel = panel(vec![
        cohort(&[("close", &["1", "2", "3", "4", "5"])]),
        cohort(&[("close", &["2", "3", "4", "5", "6"])]),
        cohort(&[("close", &["3", "4", "5", "6", "7"])]),
        cohort(&[("close", &["4", "5", "6", "7", "8"])]),
    ]);
    assert_eq!(panel.instrument_count(), 4);
    assert_eq!(panel.periods(), 5);
    let report = run(&panel, "$close", "Ref($close, -1)");
    assert_eq!(report.factors()[0], values(&["1", "2", "3", "4", "5"]));
    assert_eq!(report.ic(), values(&["1", "1", "1", "1", "null"]));
    assert_eq!(report.rank_ic(), values(&["1", "1", "1", "1", "null"]));
    assert_eq!(
        report.ic_statistics(),
        &SeriesStatistics {
            observations: 4,
            mean: Some(d("1")),
            std: Some(d("0")),
            ir: None,
        }
    );
    assert_eq!(report.ic_statistics(), report.rank_ic_statistics());
}

#[test]
fn rank_ic_removes_the_monotone_distortion_that_ic_keeps() {
    let panel = panel(vec![
        cohort(&[("close", &["1", "1"])]),
        cohort(&[("close", &["2", "4"])]),
        cohort(&[("close", &["3", "9"])]),
        cohort(&[("close", &["4", "16"])]),
    ]);
    let report = run(&panel, "$close", "Ref($close, -1)");
    assert_eq!(report.ic()[1], None, "the last label is still forward");
    assert_eq!(report.rank_ic()[0], Some(d("1")));
    let ic = report.ic()[0].as_ref().expect("one defined event").clone();
    assert!(
        ic > d("0.98") && ic < d("1"),
        "Pearson keeps curvature: {ic}"
    );
}

#[test]
fn statistics_cover_every_defined_event_and_ignore_the_rest() {
    let panel = panel(vec![
        cohort(&[("close", &["1", "null", "3"]), ("volume", &["1", "2", "3"])]),
        cohort(&[("close", &["2", "null", "4"]), ("volume", &["2", "3", "4"])]),
        cohort(&[("close", &["3", "3", "2"]), ("volume", &["3", "4", "5"])]),
    ]);
    let report = run(&panel, "$close", "$volume");
    // The middle event keeps a single complete pair, which carries no correlation.
    assert_eq!(report.ic(), values(&["1", "null", "-0.5"]));
    assert_eq!(report.rank_ic(), values(&["1", "null", "-0.5"]));
    assert_eq!(
        report.ic_statistics(),
        &SeriesStatistics {
            observations: 2,
            mean: Some(d("0.25")),
            std: Some(d("0.75")),
            ir: Some(d("0.333333333333")),
        }
    );
}

#[test]
fn a_constant_factor_reports_no_evidence_instead_of_zero() {
    let panel = panel(vec![
        cohort(&[("close", &["1", "1"])]),
        cohort(&[("close", &["1", "1"])]),
        cohort(&[("close", &["1", "1"])]),
    ]);
    let report = run(&panel, "$close", "Ref($close, -1)");
    assert_eq!(report.ic(), values(&["null", "null"]));
    assert_eq!(
        report.ic_statistics(),
        &SeriesStatistics {
            observations: 0,
            mean: None,
            std: None,
            ir: None,
        }
    );
}

#[test]
fn cross_section_factors_run_over_the_aligned_panel() {
    let panel = panel(vec![
        cohort(&[("close", &["1", "2"])]),
        cohort(&[("close", &["2", "4"])]),
        cohort(&[("close", &["3", "1"])]),
        cohort(&[("close", &["4", "3"])]),
    ]);
    // Demeaning is a linear transform of the same cross-section, so the
    // correlation is unchanged while the factor values are not.
    let report = run(&panel, "CSDemean($close)", "$close");
    assert_eq!(report.factors()[0], values(&["-1.5", "-0.5"]));
    assert_eq!(report.ic(), values(&["1", "1"]));
    assert_eq!(report.rank_ic(), values(&["1", "1"]));
}

#[test]
fn panel_shape_and_schema_are_strict() {
    assert_eq!(
        ResearchPanel::new(Vec::new()).unwrap_err(),
        Error("RESEARCH_PANEL_EMPTY".into())
    );
    assert_eq!(
        ResearchPanel::new(vec![Cohort::new()]).unwrap_err(),
        Error("RESEARCH_PANEL_NO_FIELDS".into())
    );
    assert_eq!(
        ResearchPanel::new(vec![
            cohort(&[("close", &["1", "2"])]),
            cohort(&[("volume", &["1", "2"])]),
        ])
        .unwrap_err(),
        Error("RESEARCH_PANEL_SCHEMA".into())
    );
    assert_eq!(
        ResearchPanel::new(vec![
            cohort(&[("close", &["1", "2"])]),
            cohort(&[("close", &["1"])]),
        ])
        .unwrap_err(),
        Error("RESEARCH_PANEL_LENGTH".into())
    );
}
