//! Read projections contain no execution permit. Exact artifacts remain canonical text.
use serde::{Deserialize, Serialize};
use serde_json::Value;
use utoipa::ToSchema;

#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorResearchRunView {
    pub schema_version: u8,
    pub run_id: String,
    pub state: String,
    pub revision: String,
    pub name_snapshot: Value,
    pub current_name: Option<String>,
    pub accepted_at: String,
    pub specification_fingerprint: String,
    pub runtime_generation_fingerprint: String,
    pub report: Option<FactorResearchReport>,
    pub report_status: FactorResearchReportAvailability,
    pub decision_provenance: FactorResearchDecisionProvenance,
    pub failure: Option<Value>,
    pub worker_observation: Value,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum FactorResearchReportState {
    Verified,
    Unavailable,
    NotApplicable,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorResearchReportAvailability {
    pub state: FactorResearchReportState,
    pub code: Option<String>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum FactorResearchDecisionState {
    Verified,
    Unavailable,
    NotChecked,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorResearchDecisionProvenance {
    pub state: FactorResearchDecisionState,
    pub code: Option<String>,
    pub command_id: String,
    pub group_fingerprint: String,
    pub policy_id: String,
    pub policy_version: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorResearchReport {
    pub instrument_id: String,
    pub timeframe_minutes: u64,
    pub horizon_bars: u32,
    pub research_result_fingerprint: String,
    pub artifact_content_fingerprint: String,
    pub samples: Vec<FactorResearchSample>,
    pub confidence_bps: u32,
    pub expected_block_length: u32,
    pub replicates: u32,
    pub comparison_count: usize,
    pub limitations: Vec<String>,
    pub canonical_artifact: String,
    pub canonical_specification: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorResearchSample {
    pub role: String,
    pub start_at: String,
    pub end_at: String,
    pub diagnostics: Value,
    pub pearson: Value,
    pub spearman: Value,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorResearchCancellationInput {
    pub schema_version: u8,
    pub run_id: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorResearchPreparationContext {
    pub schema_version: u8,
    pub study_proposal_fingerprint: String,
    pub factor_proposal_fingerprint: String,
    pub factor_name: String,
    pub usage_summary: String,
    pub source_label: Option<String>,
    pub advice: crate::application::factor_studies::Advice,
    pub is_current: bool,
    pub withdrawn: bool,
    pub release_manifest_fingerprint: String,
    pub backend_version: String,
    pub algorithm_artifact_fingerprint: Option<String>,
    pub expected_active_generation: Option<String>,
    pub initialize_fresh_runtime: bool,
    pub profile: Value,
    pub policy: Value,
    pub new_work_status: FactorResearchNewWorkStatus,
    pub existing_preparations: Vec<FactorResearchPreparationSummary>,
}
/// Discovery facts only. Physical readiness and submission outcomes belong to
/// the separately selected original operation, never to a history option.
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorResearchPreparationSummary {
    pub command_id: String,
    pub revision: String,
    pub state: String,
    pub study_proposal_fingerprint: String,
    pub accepted_at: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorResearchNewWorkStatus {
    pub state: String,
    pub code: Option<String>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorResearchReadiness {
    pub state: String,
    pub code: Option<String>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorResearchPreparationView {
    pub schema_version: u8,
    pub command_id: String,
    pub revision: String,
    pub state: String,
    pub phase: String,
    pub study_proposal_fingerprint: String,
    pub research_command_id: String,
    pub reserved_run_id: String,
    pub prepared_study_fingerprint: Option<String>,
    pub research_outcome: String,
    pub run_id: Option<String>,
    pub accepted_at: String,
    pub advice: crate::application::factor_studies::Advice,
    pub detail: Value,
    pub readiness: FactorResearchReadiness,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorResearchPreparationRevisionInput {
    pub schema_version: u8,
    pub preparation_command_id: String,
    pub expected_revision: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorResearchConfirmationInput {
    pub schema_version: u8,
    pub preparation_command_id: String,
    pub prepared_study_fingerprint: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct FactorResearchConfirmationOutcome {
    pub schema_version: u8,
    pub research_command_id: String,
    pub state: String,
    pub run_id: Option<String>,
}
