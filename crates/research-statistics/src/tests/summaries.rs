use super::*;
use crate::{Decimal, StatisticsPlan};
use StatisticStatus::{
    InsufficientObservations, NoValidObservations, Valid, ZeroVarianceFeature, ZeroVarianceTarget,
};
use std::str::FromStr;

fn d(text: &str) -> Decimal {
    Decimal::from_str(text).unwrap()
}

fn valid(ic: &str, rank_ic: &str) -> StatisticRow {
    StatisticRow {
        sample_count: 4,
        status: Valid,
        ic: Some(d(ic)),
        rank_ic: Some(d(rank_ic)),
    }
}

fn invalid(status: StatisticStatus, sample_count: usize) -> StatisticRow {
    StatisticRow {
        sample_count,
        status,
        ic: None,
        rank_ic: None,
    }
}

#[test]
fn a_positive_deviation_that_rounds_to_zero_still_gives_a_valid_ir() {
    let observations = ["1", "1", "1", "1", "0.999999999999"].map(|v| Some(d(v)));
    let summary = summarize(observations.into_iter()).unwrap();
    assert_eq!(summary.observations, 5);
    assert_eq!(summary.mean_status, Valid);
    assert_eq!(summary.mean, Some(d("1")));
    assert_eq!(summary.std_status, Valid);
    assert_eq!(summary.std, Some(d("0")));
    assert_eq!(summary.ir_status, Valid);
    assert_eq!(summary.ir, Some(d("2236067977499.342482813674")));
}

#[test]
fn effect_counts_source_rows_and_signs_use_only_valid_values() {
    let effect =
        summarize([Some(d("1")), None, Some(d("-0.1")), None, Some(d("0"))].into_iter()).unwrap();
    assert_eq!((effect.total_count, effect.observations), (5, 3));
    assert_eq!(
        (
            effect.signs.positive_count,
            effect.signs.negative_count,
            effect.signs.zero_count
        ),
        (1, 1, 1)
    );
    for ratio in [
        &effect.signs.positive_ratio,
        &effect.signs.negative_ratio,
        &effect.signs.zero_ratio,
    ] {
        assert_eq!(*ratio, Some(d("0.333333333333")));
    }
    assert_eq!(effect.signs.ratio_status, Valid);
    let empty = summarize([None, None].into_iter()).unwrap();
    assert_eq!((empty.total_count, empty.observations), (2, 0));
    assert_eq!(empty.signs.positive_ratio, None);
    assert_eq!(empty.signs.ratio_status, NoValidObservations);
}

#[test]
fn coverage_preserves_invalid_rows_in_pair_counts_and_reasons() {
    let rows = [
        valid("0", "0"),
        invalid(InsufficientObservations, 1),
        invalid(ZeroVarianceFeature, 3),
        invalid(ZeroVarianceTarget, 4),
    ];
    let report = coverage(&rows).unwrap();
    assert_eq!(
        (report.total_timestamp_count, report.valid_timestamp_count),
        (4, 1)
    );
    assert_eq!(
        (
            report.insufficient_timestamp_count,
            report.zero_variance_feature_count,
            report.zero_variance_target_count
        ),
        (1, 1, 1)
    );
    assert_eq!(report.valid_timestamp_ratio, Some(d("0.25")));
    assert_eq!(report.pair_count_mean, Some(d("3")));
    assert_eq!(report.pair_count_total, 12);
    assert_eq!(
        (report.pair_count_min, report.pair_count_max),
        (Some(1), Some(4))
    );
    let no_valid = coverage(&[invalid(InsufficientObservations, 0)]).unwrap();
    assert_eq!(no_valid.valid_timestamp_ratio, Some(d("0")));
    assert_eq!(no_valid.observation_status, Valid);
    let empty = coverage(&[]).unwrap();
    assert_eq!(empty.observation_status, NoValidObservations);
    assert_eq!(empty.valid_timestamp_ratio, None);
    assert_eq!(empty.pair_count_min, None);
    assert_eq!(empty.pair_count_mean, None);
}

#[test]
fn intervals_are_half_open_and_cross_slice_dispersion_uses_published_means() {
    let times = [1, 2, 3, 4, 5].map(|t| OnlyTimestamp::from_unix_nanos(t.into()));
    let rows = [
        valid("1", "1"),
        valid("0", "-1"),
        valid("0.000000000001", "-1"),
        valid("0", "1"),
        valid("-0.000000000001", "1"),
    ];
    let ranges = [(0, 1), (2, 4), (4, 6)].map(|(start_ns, end_ns)| TimeSlice { start_ns, end_ns });
    let report = stability(&times, &rows, &ranges).unwrap();
    assert_eq!(
        report.slices[0].coverage.observation_status,
        NoValidObservations
    );
    assert_eq!(report.slices[1].coverage.pair_count_total, 8);
    assert_eq!(report.ic.slice_count, 3);
    assert_eq!(report.ic.valid_slice_count, 2);
    assert_eq!(report.ic.signs.zero_count, 2);
    assert_eq!(report.ic.min_slice_mean, Some(d("0")));
    assert_eq!(report.ic.max_slice_mean, Some(d("0")));
    assert_eq!(report.ic.stddev_of_slice_means, Some(d("0")));
    assert_eq!(report.ic.stddev_status, Valid);
    assert_eq!(report.rank_ic.min_slice_mean, Some(d("-1")));
    assert_eq!(report.rank_ic.max_slice_mean, Some(d("1")));
    assert_eq!(report.rank_ic.signs.negative_ratio, Some(d("0.5")));
    assert_eq!(
        report.rank_ic.stddev_of_slice_means,
        Some(d("1.414213562373"))
    );
    let single = stability(&times, &rows, &ranges[..2]).unwrap();
    assert_eq!(single.ic.stddev_of_slice_means, None);
    assert_eq!(single.ic.stddev_status, InsufficientObservations);
}

#[test]
fn last_timestamp_is_counted_only_by_the_slice_ending_at_max_plus_one() {
    let last = i64::MAX;
    let times = [last - 1, last].map(|t| OnlyTimestamp::from_unix_nanos(t.into()));
    let slices = vec![
        TimeSlice {
            start_ns: last - 1,
            end_ns: last.into(),
        },
        TimeSlice {
            start_ns: last,
            end_ns: i128::from(last) + 1,
        },
    ];
    let plan = StatisticsPlan::new(slices, vec![]).unwrap();
    let report = stability(&times, &[valid("-1", "-1"), valid("1", "1")], plan.slices()).unwrap();
    for (slice, expected) in report.slices.iter().zip(["-1", "1"]) {
        assert_eq!(slice.coverage.total_timestamp_count, 1);
        assert_eq!(slice.ic.mean, Some(d(expected)));
    }
    for end_ns in [i128::from(last), i128::from(last) + 2, i128::MIN, i128::MAX] {
        let invalid = TimeSlice {
            start_ns: last,
            end_ns,
        };
        assert_eq!(
            StatisticsPlan::new(vec![invalid], vec![]).unwrap_err().0,
            "RESEARCH_STATISTICS_INTERVAL"
        );
    }
}

#[test]
fn summary_budget_counts_comparisons_factor_pairs_and_empty_slices_before_evaluation() {
    let plain = StatisticsPlan::default();
    assert!(plain.check_budget(1, 1, 0, 125, 250).is_ok());
    assert_eq!(
        plain.check_budget(1, 1, 0, 125, 251).unwrap_err().0,
        "RESEARCH_RESOURCE_BUDGET"
    );
    let paired = StatisticsPlan::new(vec![], vec![("a".into(), "b".into())]).unwrap();
    assert_eq!(
        paired.check_budget(1, 1, 0, 125, 250).unwrap_err().0,
        "RESEARCH_RESOURCE_BUDGET"
    );
    assert!(paired.check_budget(1, 1, 0, 125, 249).is_ok());

    let single_slice = StatisticsPlan::new(
        vec![TimeSlice {
            start_ns: 0,
            end_ns: 1,
        }],
        vec![],
    )
    .unwrap();
    assert!(single_slice.check_budget(1, 1, 0, 11_627, 1).is_ok());
    assert_eq!(
        single_slice.check_budget(1, 1, 0, 11_628, 1).unwrap_err().0,
        "RESEARCH_RESOURCE_BUDGET"
    );

    let slices = (1..=100)
        .map(|start_ns| TimeSlice {
            start_ns,
            end_ns: i128::from(start_ns) + 1,
        })
        .collect();
    let partitioned = StatisticsPlan::new(slices, vec![]).unwrap();
    assert!(partitioned.check_budget(1, 1, 0, 1, 1).is_ok());
    assert_eq!(
        partitioned.check_budget(1, 1, 0, 20, 20).unwrap_err().0,
        "RESEARCH_RESOURCE_BUDGET"
    );
}
