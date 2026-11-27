use super::*;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

pub(super) fn slice_plan_digest(slices: &[TimeSlice]) -> String {
    let mut hash = Sha256::new();
    hash.update(b"onlyalpha.research.slice-plan.v1\0");
    for slice in slices {
        hash.update(i128::from(slice.start_ns).to_be_bytes());
        hash.update(slice.end_ns.to_be_bytes());
    }
    input::finish_digest(hash)
}

/// 当前报告的比较下标，可从摘要中的 comparison_ref 取得。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ComparisonRef {
    FactorTarget(usize),
    FactorPair(usize),
}

// 限制一次构造的 JSON 大小；大报告仍可按比较、分期或日期读取。
const MAX_VIEW_UNITS: usize = 4096;

#[derive(Clone, Copy)]
enum Method {
    Ic,
    RankIc,
    Correlation,
    RankCorrelation,
}

impl Method {
    fn prefix(self) -> &'static str {
        match self {
            Self::Ic => "research.factor.ic",
            Self::RankIc => "research.factor.rank_ic",
            Self::Correlation => "research.factor_pair.correlation",
            Self::RankCorrelation => "research.factor_pair.rank_correlation",
        }
    }

    fn metric_id(self, field: &str) -> String {
        format!("{}.{field}@1", self.prefix())
    }
}

fn status_name(status: StatisticStatus) -> &'static str {
    match status {
        StatisticStatus::Valid => "VALID",
        StatisticStatus::InsufficientObservations => "INSUFFICIENT_OBSERVATIONS",
        StatisticStatus::ZeroVarianceFeature => "ZERO_VARIANCE_FEATURE",
        StatisticStatus::ZeroVarianceTarget => "ZERO_VARIANCE_TARGET",
        StatisticStatus::NoValidObservations => "NO_VALID_OBSERVATIONS",
        StatisticStatus::ZeroVariance => "ZERO_VARIANCE",
    }
}

fn pair_status_name(status: PairStatus) -> &'static str {
    match status {
        PairStatus::Valid => "VALID",
        PairStatus::InsufficientObservations => "INSUFFICIENT_OBSERVATIONS",
        PairStatus::ZeroVarianceFirstFactor => "ZERO_VARIANCE_FIRST_FACTOR",
        PairStatus::ZeroVarianceSecondFactor => "ZERO_VARIANCE_SECOND_FACTOR",
    }
}

fn decimal_text(value: &Decimal) -> String {
    value.normalized().to_plain_string()
}

fn decimal(method: Method, field: &str, value: &Cell, status: StatisticStatus) -> Value {
    let mut scalar = json!({"metric_id": method.metric_id(field), "value_kind": "DECIMAL", "status": status_name(status)});
    if let Some(value) = value {
        scalar["decimal_value"] = json!(decimal_text(value));
    }
    scalar
}

fn integer(method: Method, field: &str, value: Option<usize>, status: StatisticStatus) -> Value {
    let mut scalar = json!({"metric_id": method.metric_id(field), "value_kind": "INTEGER", "status": status_name(status)});
    if let Some(value) = value {
        scalar["integer_value"] = json!(value);
    }
    scalar
}

fn count(method: Method, field: &str, value: usize) -> Value {
    integer(method, field, Some(value), StatisticStatus::Valid)
}

fn effect(method: Method, stats: &SeriesStatistics) -> Value {
    let signs = &stats.signs;
    json!({
        "total_count":count(method,"total_count",stats.total_count),
        "valid_count":count(method,"valid_count",stats.observations),
        "mean":decimal(method,"mean",&stats.mean,stats.mean_status),
        "stddev_sample":decimal(method,"stddev_sample",&stats.std,stats.std_status),
        "ir":decimal(method,"ir",&stats.ir,stats.ir_status),
        "positive_count":count(method,"positive_count",signs.positive_count),
        "negative_count":count(method,"negative_count",signs.negative_count),
        "zero_count":count(method,"zero_count",signs.zero_count),
        "positive_ratio":decimal(method,"positive_ratio",&signs.positive_ratio,signs.ratio_status),
        "negative_ratio":decimal(method,"negative_ratio",&signs.negative_ratio,signs.ratio_status),
        "zero_ratio":decimal(method,"zero_ratio",&signs.zero_ratio,signs.ratio_status),
    })
}

fn coverage(method: Method, coverage: &CoverageSummary) -> Value {
    let status = coverage.observation_status;
    json!({
        "total_timestamp_count":count(method,"coverage.total_timestamp_count",coverage.total_timestamp_count),
        "valid_timestamp_count":count(method,"coverage.valid_timestamp_count",coverage.valid_timestamp_count),
        "valid_timestamp_ratio":decimal(method,"coverage.valid_timestamp_ratio",&coverage.valid_timestamp_ratio,status),
        "insufficient_timestamp_count":count(method,"coverage.insufficient_timestamp_count",coverage.insufficient_timestamp_count),
        "zero_variance_feature_count":count(method,"coverage.zero_variance_feature_count",coverage.zero_variance_feature_count),
        "zero_variance_target_count":count(method,"coverage.zero_variance_target_count",coverage.zero_variance_target_count),
        "pair_count_total":count(method,"coverage.pair_count_total",coverage.pair_count_total),
        "pair_count_min":integer(method,"coverage.pair_count_min",coverage.pair_count_min,status),
        "pair_count_max":integer(method,"coverage.pair_count_max",coverage.pair_count_max,status),
        "pair_count_mean":decimal(method,"coverage.pair_count_mean",&coverage.pair_count_mean,status),
    })
}

fn slice_means(method: Method, stats: &SliceMeanStatistics) -> Value {
    let signs = &stats.signs;
    json!({
        "slice_count":count(method,"stability.slice_count",stats.slice_count),
        "valid_slice_count":count(method,"stability.valid_slice_count",stats.valid_slice_count),
        "positive_mean_slice_count":count(method,"stability.positive_mean_slice_count",signs.positive_count),
        "negative_mean_slice_count":count(method,"stability.negative_mean_slice_count",signs.negative_count),
        "zero_mean_slice_count":count(method,"stability.zero_mean_slice_count",signs.zero_count),
        "positive_mean_slice_ratio":decimal(method,"stability.positive_mean_slice_ratio",&signs.positive_ratio,signs.ratio_status),
        "negative_mean_slice_ratio":decimal(method,"stability.negative_mean_slice_ratio",&signs.negative_ratio,signs.ratio_status),
        "zero_mean_slice_ratio":decimal(method,"stability.zero_mean_slice_ratio",&signs.zero_ratio,signs.ratio_status),
        "min_slice_mean":decimal(method,"stability.min_slice_mean",&stats.min_slice_mean,stats.range_status),
        "max_slice_mean":decimal(method,"stability.max_slice_mean",&stats.max_slice_mean,stats.range_status),
        "stddev_of_slice_means":decimal(method,"stability.stddev_of_slice_means",&stats.stddev_of_slice_means,stats.stddev_status),
    })
}

fn pair_effect(method: Method, stats: &SeriesStatistics) -> Value {
    json!({
        "mean":decimal(method,"mean",&stats.mean,stats.mean_status),
        "stddev_sample":decimal(method,"stddev_sample",&stats.std,stats.std_status),
    })
}

fn interval(slice: &TimeSlice) -> Value {
    json!({"start_ns":slice.start_ns.to_string(),"end_ns":slice.end_ns.to_string()})
}

fn axis_bound(ts: &OnlyTimestamp) -> i128 {
    i128::from(i64::try_from(ts.unix_nanos()).expect("统计输入已校验时间轴"))
}

fn subject(index: usize, binding: &SeriesBinding) -> Value {
    json!({"index":index,"name":binding.name,"expression_fingerprint":binding.fingerprint,"values_digest":binding.values_digest})
}

impl FactorReport {
    fn conditions_view(&self) -> Value {
        json!({
            "schema":"onlyalpha.research.factor-report-view@1",
            "scope":"IN_MEMORY_RESEARCH",
            "dataset_snapshot":self.snapshot,
            "panel_content_digest":self.content_digest,
            "universe":"OBSERVED_PAIRWISE",
            "weighting":"EQUAL", "pairing":"PAIRWISE_COMPLETE", "rank_ties":"AVERAGE",
            "numeric_policy":{"precision":38,"decimal_places":12,"rounding":"HALF_EVEN","annualized_ir":false},
            "instrument_count":self.instruments.len(),"total_timestamps":self.timestamps.len(),
            "sample_first_ns":axis_bound(&self.timestamps[self.warmup]).to_string(),
            "sample_last_ns":self.timestamps.last().map(|t| axis_bound(t).to_string()),
            "warmup":self.warmup,"minimum_observations":self.minimum_observations,
            "factor_target_comparison_count":self.comparisons.len(),"factor_pair_count":self.pairs.len(),
            "slice_count":self.slices.len(), "slice_plan_digest":self.slice_plan_digest,
        })
    }

    fn comparison_ref_view(&self, reference: ComparisonRef) -> Result<Value, Error> {
        let unknown = || error("RESEARCH_VIEW_UNKNOWN_COMPARISON");
        match reference {
            ComparisonRef::FactorTarget(index) => {
                let result = self.comparisons.get(index).ok_or_else(unknown)?;
                Ok(json!({"kind":"FACTOR_TARGET","index":index,
                    "factor":subject(result.factor_index,&self.factors[result.factor_index]),
                    "target":subject(result.target_index,&self.targets[result.target_index])}))
            }
            ComparisonRef::FactorPair(index) => {
                let result = self.pairs.get(index).ok_or_else(unknown)?;
                Ok(json!({"kind":"FACTOR_PAIR","index":index,
                    "first_factor":subject(result.first_index,&self.factors[result.first_index]),
                    "second_factor":subject(result.second_index,&self.factors[result.second_index])}))
            }
        }
    }

    fn comparison_payload(&self, reference: ComparisonRef) -> Result<Value, Error> {
        let locator = self.comparison_ref_view(reference)?;
        Ok(match reference {
            ComparisonRef::FactorTarget(index) => {
                let result = &self.comparisons[index];
                let stability = match &result.stability {
                    None => json!({"request":"NOT_REQUESTED"}),
                    Some(stability) => json!({"request":"REQUESTED",
                        "ic":slice_means(Method::Ic,&stability.ic),
                        "rank_ic":slice_means(Method::RankIc,&stability.rank_ic)}),
                };
                json!({"comparison_ref":locator,
                    "ic":effect(Method::Ic,&result.ic_statistics),
                    "rank_ic":effect(Method::RankIc,&result.rank_ic_statistics),
                    "ic_coverage":coverage(Method::Ic,&result.coverage),
                    "rank_ic_coverage":coverage(Method::RankIc,&result.coverage),
                    "stability":stability})
            }
            ComparisonRef::FactorPair(index) => {
                let result = &self.pairs[index];
                json!({"comparison_ref":locator,
                    "correlation":pair_effect(Method::Correlation,&result.correlation),
                    "rank_correlation":pair_effect(Method::RankCorrelation,&result.rank_correlation)})
            }
        })
    }

    /// 摘要含各比较的结果定位信息；大报告可按 comparison_view 和 slice_view 分别读取。
    pub fn summary_view(&self) -> Result<Value, Error> {
        // 每个比较展开数十项类型化标量，日期明细与分期明细另取。
        let units = self
            .comparisons
            .len()
            .saturating_add(self.pairs.len())
            .saturating_mul(32)
            .saturating_add(self.slices.len());
        if units > MAX_VIEW_UNITS {
            return Err(error("RESEARCH_VIEW_BUDGET"));
        }
        let comparisons = (0..self.comparisons.len())
            .map(ComparisonRef::FactorTarget)
            .chain((0..self.pairs.len()).map(ComparisonRef::FactorPair))
            .map(|reference| self.comparison_payload(reference))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(
            json!({"conditions":self.conditions_view(),"comparisons":comparisons,
            "slices":self.slices.iter().map(interval).collect::<Vec<_>>(),
            "factor_pairs_requested":!self.pairs.is_empty()}),
        )
    }

    pub fn comparison_view(&self, reference: ComparisonRef) -> Result<Value, Error> {
        Ok(
            json!({"conditions":self.conditions_view(),"comparison":self.comparison_payload(reference)?}),
        )
    }

    /// 读取一个因子对标签比较在指定分期的效果及观测覆盖。
    pub fn slice_view(&self, comparison_index: usize, slice_index: usize) -> Result<Value, Error> {
        let locator = self.comparison_ref_view(ComparisonRef::FactorTarget(comparison_index))?;
        let stability = self.comparisons[comparison_index]
            .stability
            .as_ref()
            .ok_or_else(|| error("RESEARCH_VIEW_NOT_REQUESTED"))?;
        let slice = stability
            .slices
            .get(slice_index)
            .ok_or_else(|| error("RESEARCH_VIEW_UNKNOWN_SLICE"))?;
        Ok(
            json!({"conditions":self.conditions_view(),"comparison_ref":locator,
            "slice_index":slice_index,"interval":interval(&slice.interval),
            "ic":effect(Method::Ic,&slice.ic),"rank_ic":effect(Method::RankIc,&slice.rank_ic),
            "ic_coverage":coverage(Method::Ic,&slice.coverage),"rank_ic_coverage":coverage(Method::RankIc,&slice.coverage)}),
        )
    }

    /// 取冻结轴内 [start_ns, end_ns) 的已发布行；i64::MAX + 1 可作最后时点的右边界。
    pub fn detail_view(
        &self,
        reference: ComparisonRef,
        start_ns: i128,
        end_ns: i128,
    ) -> Result<Value, Error> {
        if start_ns >= end_ns
            || start_ns < i128::from(i64::MIN)
            || end_ns > i128::from(i64::MAX) + 1
        {
            return Err(error("RESEARCH_VIEW_INTERVAL"));
        }
        let locator = self.comparison_ref_view(reference)?;
        let axis = &self.timestamps[self.warmup..];
        let start = axis.partition_point(|t| axis_bound(t) < start_ns);
        let end = axis.partition_point(|t| axis_bound(t) < end_ns);
        if end - start > MAX_VIEW_UNITS {
            return Err(error("RESEARCH_VIEW_BUDGET"));
        }
        let rows: Vec<_> = (start..end).map(|i| {
            let time = axis_bound(&axis[i]).to_string();
            match reference {
                ComparisonRef::FactorTarget(index) => {
                    let row = &self.comparisons[index].rows[i];
                    json!({"ts_event_ns":time,"sample_count":row.sample_count,"status":status_name(row.status),
                        "ic":row.ic.as_ref().map(decimal_text),"rank_ic":row.rank_ic.as_ref().map(decimal_text)})
                }
                ComparisonRef::FactorPair(index) => {
                    let row = &self.pairs[index].rows[i];
                    json!({"ts_event_ns":time,"sample_count":row.sample_count,"status":pair_status_name(row.status),
                        "correlation":row.correlation.as_ref().map(decimal_text),"rank_correlation":row.rank_correlation.as_ref().map(decimal_text)})
                }
            }
        }).collect();
        Ok(
            json!({"conditions":self.conditions_view(),"comparison_ref":locator,
            "interval":{"start_ns":start_ns.to_string(),"end_ns":end_ns.to_string()},"rows":rows}),
        )
    }
}

#[cfg(test)]
#[path = "tests/view.rs"]
mod tests;
