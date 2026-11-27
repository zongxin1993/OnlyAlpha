use super::math::{
    MissingCounts, SeriesStatistics, SignStatistics, StatisticRow, StatisticStatus, ratio,
    summarize,
};
use super::{Cell, Error, error};
use onlyalpha_domain::time::OnlyTimestamp;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct TimeSlice {
    pub start_ns: i64,
    pub end_ns: i128,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CoverageSummary {
    pub total_timestamp_count: usize,
    pub valid_timestamp_count: usize,
    pub insufficient_timestamp_count: usize,
    pub zero_variance_feature_count: usize,
    pub zero_variance_target_count: usize,
    pub pair_count_total: usize,
    pub missing_counts: MissingCounts,
    pub valid_timestamp_ratio: Cell,
    pub pair_count_mean: Cell,
    pub pair_count_min: Option<usize>,
    pub pair_count_max: Option<usize>,
    pub observation_status: StatisticStatus,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SliceStatistics {
    pub interval: TimeSlice,
    pub ic: SeriesStatistics,
    pub rank_ic: SeriesStatistics,
    pub coverage: CoverageSummary,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SliceMeanStatistics {
    pub slice_count: usize,
    pub valid_slice_count: usize,
    pub signs: SignStatistics,
    pub min_slice_mean: Cell,
    pub max_slice_mean: Cell,
    pub stddev_of_slice_means: Cell,
    pub range_status: StatisticStatus,
    pub stddev_status: StatisticStatus,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StabilitySummary {
    pub slices: Vec<SliceStatistics>,
    pub ic: SliceMeanStatistics,
    pub rank_ic: SliceMeanStatistics,
}

pub(crate) fn coverage(rows: &[StatisticRow]) -> Result<CoverageSummary, Error> {
    let mut valid = 0;
    let mut insufficient = 0;
    let mut constant_feature = 0;
    let mut constant_target = 0;
    let mut pair_count_total = 0;
    let mut missing_counts = MissingCounts::default();
    for row in rows {
        match row.status {
            StatisticStatus::Valid => valid += 1,
            StatisticStatus::InsufficientObservations => insufficient += 1,
            StatisticStatus::ZeroVarianceFeature => constant_feature += 1,
            StatisticStatus::ZeroVarianceTarget => constant_target += 1,
            StatisticStatus::NoValidObservations | StatisticStatus::ZeroVariance => {
                return Err(error("RESEARCH_STATISTIC_ROW_STATUS"));
            }
        }
        pair_count_total += row.sample_count;
        missing_counts.missing_factor_only += row.missing_counts.missing_factor_only;
        missing_counts.missing_target_only += row.missing_counts.missing_target_only;
        missing_counts.missing_both += row.missing_counts.missing_both;
    }
    Ok(CoverageSummary {
        total_timestamp_count: rows.len(),
        valid_timestamp_count: valid,
        insufficient_timestamp_count: insufficient,
        zero_variance_feature_count: constant_feature,
        zero_variance_target_count: constant_target,
        pair_count_total,
        missing_counts,
        valid_timestamp_ratio: ratio(valid, rows.len())?,
        pair_count_mean: ratio(pair_count_total, rows.len())?,
        pair_count_min: rows.iter().map(|r| r.sample_count).min(),
        pair_count_max: rows.iter().map(|r| r.sample_count).max(),
        observation_status: if rows.is_empty() {
            StatisticStatus::NoValidObservations
        } else {
            StatisticStatus::Valid
        },
    })
}

fn slice_means<'a>(
    means: impl Iterator<Item = &'a Cell> + Clone,
) -> Result<SliceMeanStatistics, Error> {
    let min_slice_mean = means.clone().filter_map(Option::as_ref).min().cloned();
    let max_slice_mean = means.clone().filter_map(Option::as_ref).max().cloned();
    let summary = summarize(means.cloned())?;
    Ok(SliceMeanStatistics {
        slice_count: summary.total_count,
        valid_slice_count: summary.observations,
        min_slice_mean,
        max_slice_mean,
        signs: summary.signs,
        stddev_of_slice_means: summary.std,
        range_status: summary.mean_status,
        stddev_status: summary.std_status,
    })
}

pub(crate) fn stability(
    times: &[OnlyTimestamp],
    rows: &[StatisticRow],
    slices: &[TimeSlice],
) -> Result<StabilitySummary, Error> {
    let mut results = Vec::with_capacity(slices.len());
    for &interval in slices {
        let start_ns = interval.start_ns.into();
        let end_ns = interval.end_ns.into();
        let start = times.partition_point(|t| t.unix_nanos() < &start_ns);
        let end = times.partition_point(|t| t.unix_nanos() < &end_ns);
        let slice = &rows[start..end];
        results.push(SliceStatistics {
            interval,
            ic: summarize(slice.iter().map(|r| r.ic.clone()))?,
            rank_ic: summarize(slice.iter().map(|r| r.rank_ic.clone()))?,
            coverage: coverage(slice)?,
        });
    }
    Ok(StabilitySummary {
        ic: slice_means(results.iter().map(|s| &s.ic.mean))?,
        rank_ic: slice_means(results.iter().map(|s| &s.rank_ic.mean))?,
        slices: results,
    })
}

#[cfg(test)]
#[path = "tests/summaries.rs"]
mod tests;
