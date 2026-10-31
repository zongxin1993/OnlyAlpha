//! Agent study suggestions are immutable input, never preparation or Research grants.
use crate::application::{
    factor_proposals::Origin,
    research_specification::{Role, Sample, Study},
    source_access,
};
use onlyalpha_domain::time::{OnlyTimestamp, OnlyUtcDateTime};
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "FACTOR_STUDY_PROPOSAL_INVALID";

#[derive(Clone, Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
#[schema(as = FactorStudySource)]
pub struct Source {
    pub integration_id: String,
    pub integration_revision_fingerprint: String,
    pub expected_type_id: String,
    pub source_id: String,
    pub environment: String,
    pub instrument_id: String,
}
#[derive(Clone, Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
#[schema(as = FactorStudySourceChoice)]
pub struct SourceChoice {
    pub integration_id: String,
    pub integration_revision_fingerprint: String,
    pub expected_type_id: String,
    pub source_id: String,
    pub environment: String,
}
#[derive(Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
#[schema(as = FactorStudyContext)]
pub struct Context {
    pub schema_version: u8,
    pub owner: String,
    pub service_subject: String,
    pub factor_proposal_fingerprint: String,
    pub factor: serde_json::Value,
    pub study_proposal_fingerprint: Option<String>,
    pub sources: Vec<SourceChoice>,
    pub supported_profile: serde_json::Value,
}
#[derive(Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
#[schema(as = FactorStudyView)]
pub struct View {
    pub schema_version: u8,
    pub fingerprint: String,
    pub snapshot: serde_json::Value,
    pub is_current: bool,
    pub withdrawn: bool,
}
#[derive(Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
#[schema(as = FactorStudySelection)]
pub struct SelectionInput {
    pub schema_version: u8,
    pub study_proposal_fingerprint: String,
}
#[derive(Clone, Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
#[schema(as = FactorStudyAdvice)]
pub struct Advice {
    pub source: Source,
    pub timeframe_minutes: u32,
    pub start_at: String,
    pub development_end_at: String,
    pub end_at: String,
    pub protected_start_at: String,
    pub protected_end_at: String,
    pub horizon_bars: u32,
    pub expected_block_length: u32,
    pub replicates: u32,
    pub confidence_bps: u32,
    pub seed: String,
    pub rationale: String,
}
#[derive(Clone, Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
#[schema(as = FactorStudyStageInput)]
pub struct StageInput {
    pub schema_version: u8,
    pub factor_proposal_fingerprint: String,
    pub origin: Origin,
    pub expected_study_fingerprint: Option<String>,
    pub advice: Advice,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub continuation_command_id: Option<String>,
}

/// Human permission to keep the same confirmed Factor in a fresh Agent workflow.
#[derive(Clone, Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
#[schema(as = FactorStudyContinuationInput)]
pub struct ContinuationInput {
    pub schema_version: u8,
    pub factor_proposal_fingerprint: String,
    pub session_id: String,
    pub workflow_fingerprint: String,
    pub model_revision: String,
    pub source_session_id: String,
    pub source_workflow_fingerprint: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_continuation_command_id: Option<String>,
}
#[derive(Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
#[schema(as = FactorStudyContinuationView)]
pub struct ContinuationView {
    pub schema_version: u8,
    pub command_id: String,
    pub operation_fingerprint: String,
    pub snapshot: serde_json::Value,
}
/// Separate explicit Human staging permission. The original Factor grant alone
/// cannot register studies, prepare/activate environments or run Research.
#[derive(Clone, Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
#[schema(as = FactorStudyGrantInput)]
pub struct GrantInput {
    pub schema_version: u8,
    pub factor_proposal_fingerprint: String,
    pub grant_id: String,
    pub proposal_limit: u32,
}
#[derive(Clone, Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
#[schema(as = FactorStudyPreparationInput)]
pub struct PrepareInput {
    pub schema_version: u8,
    pub study_proposal_fingerprint: String,
    pub release_manifest_fingerprint: String,
    pub expected_active_generation: Option<String>,
    pub initialize_fresh_runtime: bool,
    pub research_command_id: String,
}
impl Advice {
    pub fn study(&self) -> Result<Study> {
        self.source.selection()?;
        if self.source.instrument_id.trim().is_empty()
            || self.source.instrument_id.len() > 512
            || self.rationale.trim().is_empty()
            || self.rationale.len() > 8000
        {
            return Err(INVALID);
        }
        let at = |value: &str| -> Result<u64> {
            let parsed: OnlyUtcDateTime = value.parse().map_err(|_| INVALID)?;
            OnlyTimestamp::from_datetime(parsed)
                .unix_nanos()
                .to_string()
                .parse()
                .map_err(|_| INVALID)
        };
        let bar_ns = u64::from(self.timeframe_minutes)
            .checked_mul(60_000_000_000)
            .filter(|n| *n > 0)
            .ok_or(INVALID)?;
        let boundary = at(&self.development_end_at)?;
        let study = Study {
            schema_version: 1,
            bar_ns,
            horizon_bars: self.horizon_bars,
            samples: vec![
                Sample {
                    role: Role::Development,
                    start_ns: at(&self.start_at)?,
                    end_ns: boundary,
                },
                Sample {
                    role: Role::OutOfSample,
                    start_ns: boundary,
                    end_ns: at(&self.end_at)?,
                },
            ],
            protected_start_ns: at(&self.protected_start_at)?,
            protected_end_ns: at(&self.protected_end_at)?,
            expected_block_length: self.expected_block_length,
            replicates: self.replicates,
            confidence_bps: self.confidence_bps,
            seed: self.seed.clone(),
        };
        if !study.protected_start_ns.is_multiple_of(bar_ns)
            || !study.protected_end_ns.is_multiple_of(bar_ns)
        {
            return Err(INVALID);
        }
        study.comparison_family().map_err(|_| INVALID)?;
        Ok(study)
    }
}
impl Source {
    /// Input validation only; constructing a selection confers no Source permission.
    pub fn selection(&self) -> Result<source_access::Selection> {
        let reference = source_access::Reference::new(
            &self.integration_id,
            &self.integration_revision_fingerprint,
            Some(&self.expected_type_id),
        )
        .map_err(|_| INVALID)?;
        let selection =
            source_access::Selection::new(reference, &self.source_id, &self.environment)
                .map_err(|_| INVALID)?;
        source_access::Grant::new(
            selection.clone(),
            vec![source_access::Permission::ClosedHistory],
        )
        .map_err(|_| INVALID)?;
        Ok(selection)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::research_specification::Role;
    fn advice() -> Advice {
        Advice {
            source: Source {
                integration_id: "00000000-0000-4000-8000-000000000001".into(),
                integration_revision_fingerprint: "a".repeat(64),
                expected_type_id: "binance.spot.source".into(),
                source_id: "spot".into(),
                environment: "public".into(),
                instrument_id: "BTCUSDT".into(),
            },
            timeframe_minutes: 1,
            start_at: "1970-01-01T00:02:00Z".into(),
            development_end_at: "1970-01-01T01:06:00Z".into(),
            end_at: "1970-01-01T02:10:00Z".into(),
            protected_start_at: "1970-01-01T02:10:00Z".into(),
            protected_end_at: "1970-01-01T03:14:00Z".into(),
            horizon_bars: 1,
            expected_block_length: 4,
            replicates: 4096,
            confidence_bps: 9500,
            seed: "b".repeat(64),
            rationale: "固定开发和样本外区间；未授权读取保留样本。".into(),
        }
    }
    #[test]
    fn readable_dates_preserve_exact_study_and_the_complete_uncertainty_family() {
        let a = advice();
        let s = a.study().unwrap();
        assert_eq!(s.samples[0].start_ns, 120_000_000_000);
        assert_eq!(s.samples[0].end_ns, 3_960_000_000_000);
        assert_eq!(s.samples[1].role, Role::OutOfSample);
        assert_eq!(s.samples[1].end_ns, 7_800_000_000_000);
        assert_eq!(s.protected_start_ns, s.samples[1].end_ns);
        assert_eq!(s.comparison_family().unwrap().len(), 4);
        let mut equivalent = a.clone();
        equivalent.start_at = "1970-01-01T00:02:00+00:00".into();
        assert_eq!(
            s.logical_fingerprint().unwrap(),
            equivalent.study().unwrap().logical_fingerprint().unwrap()
        );
    }
    #[test]
    fn suggestions_cannot_weaken_uncertainty_or_sample_boundaries() {
        let mut a = advice();
        a.expected_block_length = 1;
        assert!(a.study().is_err());
        let mut a = advice();
        a.start_at = "1970-01-01T00:02:00.000001Z".into();
        assert!(a.study().is_err());
        let mut a = advice();
        a.replicates = 10;
        assert!(a.study().is_err());
        let mut a = advice();
        a.timeframe_minutes = 0;
        assert!(a.study().is_err());
    }
}
