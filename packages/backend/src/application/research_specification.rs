//! Frozen time-series study intent. No input, permission or execution grant.
use crate::application::{
    factor_content::hash,
    research_statistics::{Comparison, Metric},
};
use serde::{Deserialize, Serialize};
use serde_json::json;
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "RESEARCH_STUDY_INVALID";
#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Role {
    Development,
    OutOfSample,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Sample {
    pub role: Role,
    pub start_ns: u64,
    pub end_ns: u64,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Study {
    pub schema_version: u32,
    pub bar_ns: u64,
    pub horizon_bars: u32,
    pub samples: Vec<Sample>,
    pub protected_start_ns: u64,
    pub protected_end_ns: u64,
    pub expected_block_length: u32,
    pub replicates: u32,
    pub confidence_bps: u32,
    pub seed: String,
}
impl Study {
    /// This first finite study does not grant protected holdout access.
    /// Family membership is complete by construction, never a caller-selected subset.
    pub fn comparison_family(&self) -> Result<Vec<Comparison>> {
        if self.schema_version != 1
            || self.bar_ns == 0
            || self.horizon_bars == 0
            || self.samples.len() != 2
            || self.samples[0].role != Role::Development
            || self.samples[1].role != Role::OutOfSample
            || self.expected_block_length < 2
            || self.expected_block_length <= self.horizon_bars
            || !(400..=8192).contains(&self.replicates)
            || !(8000..=9900).contains(&self.confidence_bps)
            || !crate::is_sha256_hex(&self.seed)
            || self.protected_start_ns >= self.protected_end_ns
            || self.samples[0].end_ns > self.samples[1].start_ns
            || self.samples[1].end_ns > self.protected_start_ns
        {
            return Err(INVALID);
        }
        let mut family = Vec::with_capacity(4);
        let mut total = 0u64;
        for s in &self.samples {
            let width = s
                .end_ns
                .checked_sub(s.start_ns)
                .filter(|n| *n > 0)
                .ok_or(INVALID)?;
            if s.start_ns % self.bar_ns != 0 || width % self.bar_ns != 0 {
                return Err(INVALID);
            }
            let count = width / self.bar_ns;
            total = total.checked_add(count).ok_or(INVALID)?;
            if count > 4096 || count <= u64::from(self.horizon_bars) {
                return Err(INVALID);
            }
            for metric in [Metric::Pearson, Metric::Spearman] {
                family.push(Comparison {
                    start_ns: s.start_ns,
                    end_ns: s.end_ns,
                    horizon_bars: self.horizon_bars,
                    metric,
                });
            }
        }
        if total
            .checked_mul(u64::from(self.replicates))
            .is_none_or(|n| n > 8_388_608)
        {
            return Err("RESEARCH_STUDY_BUDGET_EXCEEDED");
        }
        Ok(family)
    }
    pub fn logical_fingerprint(&self) -> Result<String> {
        let family = self.comparison_family()?;
        hash(
            &json!({"contract":"ONLYALPHA_TIME_SERIES_STUDY_V1", "study":self,"comparison_family":family}),
        )
    }
}
