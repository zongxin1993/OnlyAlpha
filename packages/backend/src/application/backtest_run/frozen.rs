//! Original admission input owner; metadata freezing is not execution readiness.
use super::*;
use crate::application::{finite_job, job_contract::{FrozenJobBinding, JobKind}};
use crate::persistence::{job_publication::{PublicationError, owner_error}, market_data};
use onlyalpha_domain::time::{OnlyTimestamp, OnlyUtcDateTime};
type FreezeResult<T> = std::result::Result<T, PublicationError>;
fn mismatch<T>(_:T) -> PublicationError { PublicationError::Mismatch }
fn timestamp(value:&Value) -> FreezeResult<i64> {
    let utc:OnlyUtcDateTime = value.as_str().ok_or(PublicationError::Mismatch)?.parse().map_err(mismatch)?;
    OnlyTimestamp::from_datetime(utc).unix_nanos().try_into().map_err(mismatch)
}
impl Inputs<'_> {
    pub(crate) async fn frozen_binding(
        &self,tx:&crate::persistence::build_fact_read::BuildFactRead<'_, '_>,request:&CreateRequest,context:&Context<'_>,
    ) -> FreezeResult<FrozenJobBinding> {
        // The test-only value variant cannot become a production input proof.
        let (prepared,admission,dataset,operation,validation) = match &self.holds {
            Holds::Owners {prepared,admission,dataset,operation,validation,..} =>
                (prepared,admission,dataset,operation,validation),
            #[cfg(test)]
            Holds::Value {..} => return Err(PublicationError::MissingEvidence),
        };
        context.source().map_err(|_|PublicationError::Denied)?;
        self.verify_transaction(tx,self.namespace()).await.map_err(owner_error)?;
        let owner = context.owner().map_err(|_|PublicationError::Denied)?;
        if request.specification().record()!=self.specification.record()
            || operation.request.reserved_run_id()!=request.run_id()
            || operation.request.future_command()!=request.command_id().value()
            || prepared.source_revision().to_record()!=admission.source_revision().to_record() {
            return Err(PublicationError::Mismatch);
        }
        self.resolve(owner,context.selection).map_err(owner_error)?;
        let retained = &dataset.verified().manifest()["provenance"][0]["source_metadata"]["sealed_input"];
        let revision = market_data::verify_frozen_input_metadata(
            tx,&retained["evidence"],&retained["segments"],32*1024*1024,
        ).await.map_err(|error|match error {
            market_data::Error::NotFound|market_data::Error::MissingEvidence=>PublicationError::MissingEvidence,
            market_data::Error::Unavailable|market_data::Error::Busy=>PublicationError::Unavailable,
            market_data::Error::Unknown=>PublicationError::OutcomeUnknown,
            market_data::Error::BudgetExceeded=>PublicationError::BudgetExceeded,
            _=>PublicationError::Mismatch,
        })?;
        let original = revision.revision();
        let scope = &original["scope"];
        let references = dataset.lineage()["market_data_revision_bindings"].as_array().ok_or(PublicationError::Mismatch)?;
        if retained["scope"]!=*scope || references.len()!=1
            || references[0]!=json!({"source_id":scope["source_id"],"instrument_id":scope["instrument_id"],"data_kind":"BAR","revision_id":original["revision_id"],"revision_fingerprint":original["fingerprint"]}) {
            return Err(PublicationError::Mismatch);
        }
        let values = dataset.verified().dataset();
        let axis = values.rows().iter().map(|row|json!([
            row["instrument_id"],row["bar_start_ns"],row["bar_end_ns"],row["ts_event_ns"],row["revision"],
        ])).collect::<Vec<_>>();
        let warmup = prepared.record()["window"]["warmup_bars"].as_u64().ok_or(PublicationError::Mismatch)?;
        let skip = usize::try_from(warmup).map_err(mismatch)?;
        let sample = axis.get(skip..).ok_or(PublicationError::Mismatch)?;
        let plan = finite_job::plan_members(JobKind::Backtest,&json!(axis),&json!(sample),0)?;
        // A fresh manual validation occurrence overrides the retained grant's
        // original occurrence. Both are opaque, transaction-checked owners.
        let calculations = match validation {
            Some(value)=>&value.record()["prepared_inputs"],
            None=>admission.validated_calculations().map_err(owner_error)?,
        };
        let factors = finite_job::calculation_factor_inputs(calculations).map_err(owner_error)?.0;
        let seal = revision.seal();
        let mut raw = json!({"schema_version":1,"kind":"BACKTEST","scope":{"namespace":self.namespace().value(),"owner":owner,"run_id":request.run_id()},"factor_bindings":factors,
            "market":{"dataset_snapshot":values.snapshot_fingerprint(),"source_revision":original["fingerprint"],"bar_semantic":hash(&values.definition()["bar_semantic"]).map_err(owner_error)?,"instruments":values.definition()["instruments"],"start_ns":timestamp(&values.definition()["time_range"]["start"])? ,"end_ns":timestamp(&values.definition()["time_range"]["end"])? ,"versions":[hash(&scope["data_version"]).map_err(owner_error)?],"seals":[seal["seal_id"].as_str().and_then(|s|s.strip_prefix("seal:")).ok_or(PublicationError::Mismatch)?],"segments":original["segment_refs"].as_array().ok_or(PublicationError::Mismatch)?.iter().map(hash).collect::<Result<Vec<_>>>().map_err(owner_error)?,"rows":axis.len(),"warmup_rows":warmup,"sample_rows":sample.len(),"axis":hash(&json!(axis)).map_err(owner_error)?,"content":values.content_fingerprint()},"result_plan":plan.record()});
        let execution = finite_job::backtest_execution_values(prepared,text(&self.resolution["backtest_binding"],"executor_artifact_sha256").map_err(owner_error)?).map_err(owner_error)?;
        for (key,value) in execution.as_object().ok_or(PublicationError::Mismatch)? { raw[key]=value.clone(); }
        self.verify_cut().map_err(owner_error)?;
        FrozenJobBinding::from_record(&raw).map_err(mismatch)
    }
}
