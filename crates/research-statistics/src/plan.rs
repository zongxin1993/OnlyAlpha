use super::{Error, SeriesBinding, TimeSlice, error, input::valid_name};
use onlyalpha_operators::algebra::{MAX_CELLS, MAX_WINDOW_WORK};
use std::collections::BTreeMap;

// 按结果中的数值槽位计费；空分期仍物化完整摘要，限额沿用矩阵的 MAX_CELLS。
const SERIES_STATISTICS_CELLS: usize = 11;
const COVERAGE_CELLS: usize = 10;
const SLICE_MEAN_CELLS: usize = 11;
const FACTOR_PAIR_CELLS: usize = 2 * SERIES_STATISTICS_CELLS;
const FACTOR_TARGET_CELLS: usize = FACTOR_PAIR_CELLS + COVERAGE_CELLS;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StatisticsPlan {
    slices: Vec<TimeSlice>,
    pairs: Vec<(String, String)>,
}

impl StatisticsPlan {
    pub fn new(slices: Vec<TimeSlice>, mut pairs: Vec<(String, String)>) -> Result<Self, Error> {
        if slices.len() > MAX_CELLS || pairs.len() > MAX_CELLS {
            return Err(error("RESEARCH_RESOURCE_BUDGET"));
        }
        if slices
            .iter()
            .any(|s| i128::from(s.start_ns) >= s.end_ns || s.end_ns > i128::from(i64::MAX) + 1)
            || slices
                .windows(2)
                .any(|p| p[0].end_ns > i128::from(p[1].start_ns))
        {
            return Err(error("RESEARCH_STATISTICS_INTERVAL"));
        }
        for (first, second) in &mut pairs {
            if !valid_name(first) || !valid_name(second) || first == second {
                return Err(error("RESEARCH_FACTOR_PAIR"));
            }
            if first > second {
                std::mem::swap(first, second);
            }
        }
        pairs.sort_unstable();
        if pairs.windows(2).any(|p| p[0] == p[1]) {
            return Err(error("RESEARCH_FACTOR_PAIR"));
        }
        Ok(Self { slices, pairs })
    }

    pub fn pairs(&self) -> &[(String, String)] {
        &self.pairs
    }
    pub fn slices(&self) -> &[TimeSlice] {
        &self.slices
    }

    pub fn check_budget(
        &self,
        instruments: usize,
        periods: usize,
        warmup: usize,
        factors: usize,
        targets: usize,
    ) -> Result<(), Error> {
        if instruments == 0 || warmup >= periods || factors == 0 || targets == 0 {
            return Err(error("RESEARCH_PLAN_INVALID"));
        }
        let comparisons = factors.saturating_mul(targets);
        let all_pairs = comparisons.saturating_add(self.pairs.len());
        let rows = all_pairs.saturating_mul(periods - warmup);
        let slice_results = comparisons.saturating_mul(self.slices.len());
        let matrices = factors
            .saturating_add(targets)
            .saturating_mul(instruments)
            .saturating_mul(periods);
        let cross_slice_cells = if self.slices.is_empty() {
            0
        } else {
            comparisons.saturating_mul(2 * SLICE_MEAN_CELLS)
        };
        let summary_cells = comparisons
            .saturating_add(slice_results)
            .saturating_mul(FACTOR_TARGET_CELLS)
            .saturating_add(self.pairs.len().saturating_mul(FACTOR_PAIR_CELLS))
            .saturating_add(cross_slice_cells);
        if matrices > MAX_CELLS
            || rows.saturating_add(slice_results) > MAX_CELLS
            || rows.saturating_mul(instruments) > MAX_WINDOW_WORK
            || summary_cells > MAX_CELLS
        {
            return Err(error("RESEARCH_RESOURCE_BUDGET"));
        }
        Ok(())
    }

    pub(crate) fn resolve_pairs(
        &self,
        factors: &[SeriesBinding],
    ) -> Result<Vec<(usize, usize)>, Error> {
        if self.pairs.is_empty() {
            return Ok(Vec::new());
        }
        let indices: BTreeMap<_, _> = factors
            .iter()
            .enumerate()
            .map(|(i, b)| (b.name.as_str(), i))
            .collect();
        let mut ordered = BTreeMap::new();
        for (a, b) in &self.pairs {
            let lookup = |name: &str| {
                indices
                    .get(name)
                    .copied()
                    .ok_or_else(|| error("RESEARCH_FACTOR_PAIR"))
            };
            let (mut first, mut second) = (lookup(a)?, lookup(b)?);
            if factors[first].fingerprint > factors[second].fingerprint {
                std::mem::swap(&mut first, &mut second);
            }
            let key = (&factors[first].fingerprint, &factors[second].fingerprint);
            if key.0 == key.1 || ordered.insert(key, (first, second)).is_some() {
                return Err(error("RESEARCH_FACTOR_PAIR"));
            }
        }
        Ok(ordered.into_values().collect())
    }
}
