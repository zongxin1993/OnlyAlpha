//! Read projections contain no execution permit. Exact artifacts remain canonical text.
use serde::{Deserialize, Serialize};
use serde_json::Value;
use utoipa::ToSchema;

#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategyCreationContextView {
    pub schema_version: u8,
    pub factor_name: String,
    pub formula: String,
    pub factor_proposal_fingerprint: String,
    pub study_proposal_fingerprint: String,
    pub draft: crate::transport::wire::PrivateStrategyDraftDto,
    pub source: crate::application::factor_studies::Source,
    pub research_context: Value,
    pub release_manifest_fingerprint: String,
    pub expected_active_generation: Option<String>,
    pub initialize_fresh_runtime: bool,
    pub existing_preparations: Vec<Value>,
}

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

/// Strategy preparation projects the original owning operation, not a Run grant.
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategyResearchPreparationView {
    pub schema_version: u8,
    pub profile: String,
    pub command_id: String,
    pub revision: String,
    pub state: String,
    pub phase: String,
    pub strategy_id: String,
    pub strategy_revision_fingerprint: String,
    pub definition_fingerprint: String,
    pub context: Value,
    pub source: crate::application::factor_studies::Source,
    pub research_command_id: String,
    pub reserved_run_id: String,
    pub prepared_study_fingerprint: Option<String>,
    pub research_outcome: String,
    pub run_id: Option<String>,
    pub accepted_at: String,
    pub detail: Value,
    pub readiness: FactorResearchReadiness,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategyResearchPreparationRevisionInput {
    pub schema_version: u8,
    pub preparation_command_id: String,
    pub expected_revision: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategyResearchConfirmationInput {
    pub schema_version: u8,
    pub preparation_command_id: String,
    pub prepared_study_fingerprint: String,
}

#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategyResearchConfirmationOutcome {
    pub schema_version: u8,
    pub research_command_id: String,
    pub state: String,
    pub run_id: Option<String>,
}

/// Read-only history. Current Source selection grants no access to these facts.
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategyWorkflowView {
    pub schema_version: u8,
    pub strategy_id: String,
    pub authoring: crate::transport::wire::PrivateStrategyAuthoringStateDto,
    pub preparations: Vec<StrategyResearchPreparationView>,
    pub backtest_preparations: Vec<BacktestPreparationView>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategyWorkflowInventoryView {
    pub schema_version: u8,
    pub items: Vec<StrategyWorkflowView>,
}

#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategyFreezeInput {
    pub research_run_id: String,
    pub candidate_fingerprint: String,
    pub comment: Option<String>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategyFreezeView {
    pub schema_version: u8,
    pub command_id: String,
    pub strategy_fingerprint: String,
    pub freeze_relation_fingerprint: String,
    pub accepted_at: String,
    pub replayed: bool,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategyFreezeOutcomeView {
    pub state: String,
    pub request: Option<StrategyFreezeInput>,
    pub result: Option<StrategyFreezeView>,
}

#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategyResearchReport {
    pub candidate_fingerprint: String,
    pub research_result_fingerprint: String,
    pub start_at: String,
    pub end_at: String,
    pub observation_count: u64,
    pub warmup_bars: u64,
    pub node_count: u64,
    pub execution_graph_verified: bool,
    pub limitations: Vec<String>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategyResearchRunView {
    pub schema_version: u8,
    pub kind: String,
    pub run_id: String,
    pub state: String,
    pub revision: String,
    pub report_status: FactorResearchReportAvailability,
    pub report: Option<StrategyResearchReport>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(untagged)]
pub enum ResearchRunView {
    Factor(Box<FactorResearchRunView>),
    Strategy(Box<StrategyResearchRunView>),
}

#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestCancellationInput {
    pub schema_version: u8,
    pub run_id: String,
}
impl BacktestCancellationInput {
    pub(crate) fn validate(&self, run: &str) -> Result<(), &'static str> {
        if self.schema_version != 1
            || self.run_id != run
            || !crate::application::command::uuid4(run)
        {
            return Err("BACKTEST_RUN_INPUT_INVALID");
        }
        Ok(())
    }
}

#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ManualStrategyContextView {
    pub schema_version: u8,
    pub factor_locator: crate::transport::wire::PrivateAssetLocatorDto,
    pub factor_name: String,
    #[serde(deserialize_with = "Option::deserialize")]
    #[schema(required = true)]
    pub formula: Option<String>,
    pub draft: crate::transport::wire::PrivateStrategyDraftDto,
    pub release_manifest_fingerprint: String,
    #[serde(deserialize_with = "Option::deserialize")]
    #[schema(required = true)]
    pub expected_active_generation: Option<String>,
    pub initialize_fresh_runtime: bool,
    pub existing_preparations: Vec<BacktestPreparationView>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestInputDefaultsV2 {
    pub schema_version: u8,
    pub profile: String,
    pub origin: crate::application::backtest_preparation::BacktestOrigin,
    pub release_manifest_fingerprint: String,
    #[serde(deserialize_with = "Option::deserialize")]
    #[schema(required = true)]
    pub expected_active_generation: Option<String>,
    pub initialize_fresh_runtime: bool,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestCreationContextV2 {
    pub schema_version: u8,
    pub strategy_name: String,
    pub input_defaults: BacktestInputDefaultsV2,
    pub sample_start_at: String,
    pub sample_end_at: String,
    pub initial_cash: String,
    pub quantity: String,
    pub fee_bps: u16,
    pub slippage_bps: u16,
    pub limitations: Vec<String>,
    pub existing_preparations: Vec<BacktestPreparationView>,
}

#[derive(Deserialize, Serialize, ToSchema)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum BacktestReportState {
    Pending,
    NotChecked,
    Verified,
    NotApplicable,
    Unavailable,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestReportAvailability {
    pub state: BacktestReportState,
    pub code: Option<String>,
}
/// Host lifecycle observation only; never an authoritative Run transition.
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum BacktestWorkerState {
    Starting,
    Idle,
    Running,
    Unknown,
    Unavailable,
    Stopped,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestWorkerObservation {
    pub state: BacktestWorkerState,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub code: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub run_id: Option<String>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestRunView {
    pub schema_version: u8,
    pub run_id: String,
    pub strategy_fingerprint: String,
    pub state: String,
    pub revision: String,
    pub accepted_at: String,
    pub preparation_command_id: Option<String>,
    pub report_status: BacktestReportAvailability,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub worker_observation: Option<BacktestWorkerObservation>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestRunInventory {
    pub schema_version: u8,
    pub items: Vec<BacktestRunView>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestSample {
    pub instrument: String,
    pub start_at: String,
    pub end_at: String,
    pub quantity: String,
    pub rule_observed_at: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestMetrics {
    pub initial_equity: String,
    pub final_equity: String,
    pub return_since_start: Option<String>,
    pub net_pnl: String,
    pub realized_pnl: String,
    pub unrealized_pnl: String,
    pub fees: String,
    pub maximum_drawdown: Option<String>,
    pub fill_count: u64,
    pub roundtrip_count: u64,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestCurvePoint {
    pub at_ns: String,
    pub nav: String,
    pub drawdown: Option<String>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestBaseline {
    pub final_equity: String,
    pub net_pnl: String,
    pub return_since_start: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestTradeView {
    pub ordinal: u64,
    pub time_ns: String,
    pub side: String,
    pub quantity: String,
    pub price: String,
    pub fee: String,
    pub signal_time_ns: String,
    pub signal: String,
    pub order_id: String,
    pub trade_id: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestPositionView {
    pub instrument: String,
    pub quantity: String,
    pub average_price: Option<String>,
    pub state: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestResultView {
    pub schema_version: u8,
    pub run_id: String,
    pub strategy_fingerprint: String,
    pub evidence_fingerprint: String,
    pub result_fingerprint: String,
    pub determinism_fingerprint: String,
    pub state: String,
    pub sample: BacktestSample,
    pub metrics: BacktestMetrics,
    pub curve: Vec<BacktestCurvePoint>,
    pub baseline: Option<BacktestBaseline>,
    pub trades: Vec<BacktestTradeView>,
    pub positions: Vec<BacktestPositionView>,
    pub limitations: Vec<String>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestEvidenceView {
    pub schema_version: u8,
    pub run_id: String,
    pub manifest: Value,
}

/// This invocation was refused before acceptance. It is not a durable Command
/// cancellation, and a missing/lost response never establishes this outcome.
#[derive(Clone, Copy, Deserialize, Serialize, ToSchema)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum BacktestPrepareRefusalReason {
    ConditionsChanged,
    SourceUnavailable,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum BacktestPrepareRefusalState {
    NotAccepted,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestPrepareRefusal {
    pub schema_version: u8,
    pub state: BacktestPrepareRefusalState,
    pub command_id: String,
    pub input: crate::application::backtest_preparation::BacktestPrepareInput,
    pub reason: BacktestPrepareRefusalReason,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(untagged)]
pub enum BacktestPrepareReply {
    Accepted(Box<BacktestPreparationView>),
    NotAccepted(Box<BacktestPrepareRefusal>),
}

/// Original queue projection only. None of these portable values grants a Run.
#[derive(Deserialize, Serialize, ToSchema)]
#[schema(as=BacktestPreparationViewV2)]
#[serde(deny_unknown_fields)]
pub struct BacktestPreparationView {
    pub schema_version: u8,
    pub command_id: String,
    pub profile: String,
    pub origin: crate::application::backtest_preparation::BacktestOrigin,
    pub strategy_fingerprint: Option<String>,
    pub validation_fingerprint: Option<String>,
    pub freeze_relation_fingerprint: Option<String>,
    pub qualification_decision_fingerprint: Option<String>,
    pub promotion_fingerprint: Option<String>,
    pub source: crate::application::factor_studies::Source,
    pub revision: String,
    pub state: String,
    pub phase: String,
    pub backtest_command_id: String,
    pub reserved_run_id: String,
    pub preparation_fingerprint: Option<String>,
    pub detail: Value,
    pub backtest_outcome: String,
    pub readiness: FactorResearchReadiness,
    pub run_id: Option<String>,
    pub accepted_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cleanup: Option<BacktestPreparationCleanup>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestPreparationCleanup {
    pub state: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub work_id: Option<String>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestPreparationRevisionInput {
    pub schema_version: u8,
    pub preparation_command_id: String,
    pub expected_revision: String,
}
impl BacktestPreparationRevisionInput {
    pub(crate) fn validate(
        &self,
        command: &crate::application::command::CommandId,
    ) -> Result<i64, &'static str> {
        let n = self
            .expected_revision
            .parse::<i64>()
            .map_err(|_| "BACKTEST_PREPARATION_INVALID")?;
        if self.schema_version != 1
            || self.preparation_command_id != command.value()
            || n < 0
            || n.to_string() != self.expected_revision
        {
            return Err("BACKTEST_PREPARATION_INVALID");
        }
        Ok(n)
    }
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestConfirmationInput {
    pub schema_version: u8,
    pub preparation_command_id: String,
    pub preparation_fingerprint: String,
}
impl BacktestConfirmationInput {
    pub(crate) fn validate(
        &self,
        command: &crate::application::command::CommandId,
    ) -> Result<(), &'static str> {
        if self.schema_version != 1
            || self.preparation_command_id != command.value()
            || !crate::is_sha256_hex(&self.preparation_fingerprint)
        {
            return Err("BACKTEST_PREPARATION_INVALID");
        }
        Ok(())
    }
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestConfirmationOutcome {
    pub schema_version: u8,
    pub backtest_command_id: String,
    pub state: String,
    pub run_id: Option<String>,
}

/// Human selects exact existing scientific facts. Counts and conclusions are
/// intentionally absent; the owning evaluator reads them from durable evidence.
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct QualificationInput {
    pub schema_version: u8,
    pub research_run_id: String,
    pub freeze_relation_fingerprint: String,
    pub policy_id: String,
    pub policy_version: String,
}
impl QualificationInput {
    pub fn validate(&self, subject: &str) -> Result<(), &'static str> {
        qualification_selection(
            self.schema_version,
            &self.research_run_id,
            subject,
            &self.freeze_relation_fingerprint,
            &self.policy_id,
            &self.policy_version,
        )
    }
}
fn qualification_selection(
    schema: u8,
    run: &str,
    subject: &str,
    relation: &str,
    policy: &str,
    revision: &str,
) -> Result<(), &'static str> {
    if schema != 1
        || !crate::application::command::uuid4(run)
        || !crate::is_sha256_hex(subject)
        || !crate::is_sha256_hex(relation)
        || policy.is_empty()
        || policy.len() > 128
        || !policy.as_bytes()[0].is_ascii_alphanumeric()
        || !policy.bytes().all(|b| {
            b.is_ascii_lowercase() || b.is_ascii_digit() || matches!(b, b'.' | b'_' | b'-')
        })
        || revision.is_empty()
        || revision.len() > 128
        || revision.starts_with('0')
        || !revision.bytes().all(|b| b.is_ascii_digit())
    {
        return Err("QUALIFICATION_REQUEST_INVALID");
    }
    Ok(())
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct QualificationResumeInput {
    pub schema_version: u8,
    pub research_run_id: String,
}
impl QualificationResumeInput {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.schema_version != 1 || !crate::application::command::uuid4(&self.research_run_id) {
            return Err("QUALIFICATION_REQUEST_INVALID");
        }
        Ok(())
    }
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct QualifiedPromotionInput {
    pub schema_version: u8,
    pub research_run_id: String,
    pub freeze_relation_fingerprint: String,
    pub policy_id: String,
    pub policy_version: String,
    pub qualification_decision_fingerprint: String,
    pub reason: String,
}
impl QualifiedPromotionInput {
    pub fn validate(&self, subject: &str) -> Result<(), &'static str> {
        qualification_selection(
            self.schema_version,
            &self.research_run_id,
            subject,
            &self.freeze_relation_fingerprint,
            &self.policy_id,
            &self.policy_version,
        )?;
        if !crate::is_sha256_hex(&self.qualification_decision_fingerprint)
            || self.reason.trim().is_empty()
            || self.reason.len() > 4096
            || self.reason.contains('\0')
        {
            return Err("PROMOTION_REQUEST_INVALID");
        }
        Ok(())
    }
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum QualificationCommandState {
    NotSubmitted,
    Prepared,
    Completed,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct QualificationEvidenceReference {
    pub kind: String,
    pub evidence_fingerprint: String,
    pub locator_fingerprint: String,
    pub subject_binding_fingerprint: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct QualificationCommandRequest {
    pub subject_strategy_fingerprint: String,
    pub policy_id: String,
    pub policy_version: String,
    pub evidence: Vec<QualificationEvidenceReference>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct QualificationCommandView {
    pub schema_version: u8,
    pub command_id: String,
    pub strategy_fingerprint: String,
    pub state: QualificationCommandState,
    pub request: Option<QualificationCommandRequest>,
    pub prepared_at: Option<String>,
    pub completed_at: Option<String>,
    pub decision_fingerprint: Option<String>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct QualificationCommandListView {
    pub schema_version: u8,
    pub strategy_fingerprint: String,
    pub items: Vec<QualificationCommandView>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum QualifiedPromotionCommandState {
    NotSubmitted,
    OutcomeUnknown,
    Completed,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct QualifiedPromotionCommandView {
    pub schema_version: u8,
    pub command_id: String,
    pub strategy_fingerprint: String,
    pub state: QualifiedPromotionCommandState,
    pub record: Option<Value>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum QualificationDecisionReadState {
    Verified,
    LocatorRequired,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct QualificationDecisionReadView {
    pub schema_version: u8,
    pub decision_fingerprint: String,
    pub state: QualificationDecisionReadState,
    pub decision: Option<Value>,
    pub research_run_id: Option<String>,
    pub research_run_candidates: Vec<String>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct QualificationPolicyCriterionView {
    pub criterion_id: String,
    pub evidence_kind: String,
    pub metric: String,
    pub comparison: String,
    pub threshold: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct QualificationPolicyView {
    pub schema_version: u8,
    pub policy_id: String,
    pub policy_version: String,
    pub gate: String,
    pub missing_evidence_behavior: String,
    pub aggregation: String,
    pub criteria: Vec<QualificationPolicyCriterionView>,
    pub policy_fingerprint: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct QualificationPolicyListView {
    pub schema_version: u8,
    pub policies: Vec<QualificationPolicyView>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategyQualifiedView {
    pub schema_version: u8,
    pub strategy_fingerprint: String,
    pub stage: String,
    pub source_revision: Value,
    pub freeze_relations: Vec<Value>,
    pub promotion_records: Vec<Value>,
    pub qualification_commands: Vec<QualificationCommandView>,
}

/// Read-only verified absence of an original Backtest preparation Command.
/// This is an observation, not a refusal, revocation or accepted operation.
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum BacktestCommandObservationState {
    NotAccepted,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestCommandNotAccepted {
    pub schema_version: u8,
    pub command_id: String,
    pub state: BacktestCommandObservationState,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(untagged)]
pub enum BacktestPreparationCommandReply {
    Accepted(Box<BacktestPreparationView>),
    NotAccepted(BacktestCommandNotAccepted),
}
