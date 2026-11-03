//! Owning Strategy execution handoff; parsed values cannot construct this product.
use super::{INVALID,Result,verify_executor_image};
use crate::application::{research_admission::PreparedInputs,research_run::VerifiedRun,strategy_research::StrategyEvaluation};
use onlyalpha_domain::time::OnlyUtcDateTime;
use serde_json::Value;

pub struct ExecutedStrategy {
    run:VerifiedRun,
    inputs:PreparedInputs,
    observation:Value,
    created_at:OnlyUtcDateTime,
}
impl ExecutedStrategy {
    pub(crate) fn into_parts(self)->(VerifiedRun,PreparedInputs,Value,OnlyUtcDateTime) {
        (self.run,self.inputs,self.observation,self.created_at)
    }
}
/// Consume only the actual evaluator's opaque output and original accepted Run.
/// Persistence validates and publishes the complete immutable scientific closure.
pub fn execute_strategy(run:VerifiedRun,evaluation:StrategyEvaluation,created_at:OnlyUtcDateTime)->Result<ExecutedStrategy> {
    evaluation.verify_runtime()?;
    let (inputs,observation)=evaluation.into_parts();
    let specification=run.strategy_specification()?;
    if inputs.record()!=&run.prepared_inputs
        || inputs.record()["run_specification_fingerprint"]!=run.specification_fingerprint()
        || inputs.record()["runtime_work_binding"]["work_id"]!=run.run_id()
        || inputs.record()["runtime_work_binding"]["reason"]!="research"
        || inputs.record()["runtime_generation_fingerprint"]!=specification.record()["runtime_generation_fingerprint"]
        || inputs.record()["dataset_snapshot_fingerprint"]!=specification.record()["scientific_specification"]["dataset_snapshot_fingerprint"]
        || observation["schema_version"]!=1 || observation["contract"]!="ONLYALPHA_STRATEGY_EVALUATION_OBSERVATION_V1"
        || observation["run_specification_fingerprint"]!=run.specification_fingerprint()
        || observation["dataset_snapshot_fingerprint"]!=inputs.record()["dataset_snapshot_fingerprint"]
        || observation["input_window"]!=inputs.record()["input_window"]
        || observation["producer"]["algorithm_artifact_fingerprint"]!=specification.record()["algorithm_artifact_fingerprint"] {
        return Err(INVALID);
    }
    verify_executor_image(&observation["producer"]["native_image"],&specification.record()["execution_binding"])?;
    inputs.verify_runtime()?;
    Ok(ExecutedStrategy{run,inputs,observation,created_at})
}
