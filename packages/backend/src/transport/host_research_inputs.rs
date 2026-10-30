//! Compose the existing admitted acquisition and immutable Dataset owners.
//! Human preparation intent remains owned by the calling durable Command.
use crate::{
    application::{
        command::CommandId,
        factor_studies::Source,
        research_dataset::{MaterializedDataset, NativeMaterializationPlan},
        research_factor::InputWindow,
        source_access::{Permission, Reference, Session},
    },
    persistence::{
        market_data::{Catalog, Scope, Storage},
        research_dataset::Store,
    },
    security::human_access,
    transport::host::{Failure, Host, ROWS, WORK, now},
};
use axum::body::{Body, to_bytes};
use http::Request;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::OnlyBarSemantic,
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use serde_json::{Value, json};
use std::{sync::Arc, time::Instant};

const INVALID: &str = "RESEARCH_DATA_PREPARATION_INPUT_MISMATCH";
pub(crate) struct ResearchInputs {
    pub materialized: MaterializedDataset,
    /// Original acquisition receipt and exact immutable selection, never a Run permit.
    pub selection: Value,
}
pub(crate) enum ResearchInputOutcome {
    Prepared(Box<ResearchInputs>),
    Pending(Value),
    Unavailable(Value),
}
pub(crate) struct ResearchInputRequest<'a> {
    pub human: human_access::Session,
    pub session: &'a Session,
    pub source: &'a Source,
    pub window: &'a InputWindow,
    pub definition: &'a Value,
    pub command: &'a CommandId,
    pub datasets: &'a Store,
    pub deadline: Instant,
}

// Dataset time ranges label close events; acquisition scopes label bar starts.
fn acquisition_bounds(start: u64, end: u64, bar: u64) -> Result<(i64, i64), &'static str> {
    if bar == 0 || start >= end || !(end - start).is_multiple_of(bar) {
        return Err(INVALID);
    }
    let start = start.checked_sub(bar).ok_or(INVALID)?;
    let end = end.checked_sub(bar).ok_or(INVALID)?;
    Ok((
        i64::try_from(start).map_err(|_| INVALID)?,
        i64::try_from(end).map_err(|_| INVALID)?,
    ))
}
fn fail(code: &'static str) -> Failure {
    Failure::unavailable(code)
}
fn acquisition_failure(error: Failure) -> Result<ResearchInputOutcome, Failure> {
    if error.code() == crate::application::market_product::Error::Unknown.code() {
        // This is the original owner's incomplete outcome, not a completed
        // acquisition receipt. The caller retains its accepted preparation identity.
        Ok(ResearchInputOutcome::Pending(json!({"code":error.code()})))
    } else {
        Err(error)
    }
}
fn time_ns(value: &Value) -> Result<u64, Failure> {
    let at: OnlyUtcDateTime = value
        .as_str()
        .ok_or_else(|| fail(INVALID))?
        .parse()
        .map_err(|_| fail(INVALID))?;
    OnlyTimestamp::from_datetime(at)
        .unix_nanos()
        .to_string()
        .parse()
        .map_err(|_| fail(INVALID))
}

impl Host {
    /// The caller retains its accepted preparation Command and explicit Human session.
    /// Missing data follows the original acquisition lifecycle; no chart cache is consulted.
    pub(crate) async fn research_inputs(
        self: &Arc<Self>,
        request: ResearchInputRequest<'_>,
    ) -> Result<ResearchInputOutcome, Failure> {
        let ResearchInputRequest {
            human,
            session,
            source,
            window,
            definition,
            command,
            datasets,
            deadline,
        } = request;
        let reference = Reference::new(
            &source.integration_id,
            &source.integration_revision_fingerprint,
            Some(&source.expected_type_id),
        )?;
        let (resolved, _) = self.resolve(&reference).await?;
        if resolved.selection().source_id() != source.source_id
            || resolved.selection().environment() != source.environment
            || definition["instruments"] != json!([source.instrument_id])
            || time_ns(&definition["time_range"]["start"])? != window.dataset_start_ns()
            || time_ns(&definition["time_range"]["end"])? != window.dataset_end_ns()
        {
            return Err(fail(INVALID));
        }
        session.require_selection(resolved.selection(), Permission::ClosedHistory)?;
        let semantic =
            OnlyBarSemantic::from_record(&definition["bar_semantic"]).map_err(|_| fail(INVALID))?;
        let bar = window.to_record()["bar_ns"]
            .as_str()
            .ok_or_else(|| fail(INVALID))?
            .parse::<u64>()
            .map_err(|_| fail(INVALID))?;
        let semantic_record = semantic.to_record();
        if semantic_record["formation"]["kind"] != "FIXED_DURATION"
            || semantic_record["formation"]["window_minutes"]
                != semantic_record["formation"]["stride_minutes"]
            || semantic_record["formation"]["stride_minutes"]
                .as_u64()
                .and_then(|m| m.checked_mul(60_000_000_000))
                != Some(bar)
        {
            return Err(fail(INVALID));
        }
        let (start, end) =
            acquisition_bounds(window.dataset_start_ns(), window.dataset_end_ns(), bar)
                .map_err(fail)?;
        let raw = json!({"source_reference":{"integration_id":source.integration_id,
            "integration_revision_fingerprint":source.integration_revision_fingerprint,"expected_type_id":source.expected_type_id},
            "instrument_id":source.instrument_id,"bar_semantic":semantic.to_record(),
            "start_ns":start.to_string(),"end_ns":end.to_string(),"provenance":"REST_BACKFILL"});
        // Reuse the actual lease/WAL/capture/publication and UNKNOWN behavior intact.
        let request = Request::builder()
            .body(Body::from(raw.to_string()))
            .map_err(|_| fail(INVALID))?;
        let response = match self.acquisition(request, human, deadline).await {
            Ok(response) => response,
            Err(error) => return acquisition_failure(error),
        };
        let receipt: Value = serde_json::from_slice(
            &to_bytes(response.into_body(), WORK)
                .await
                .map_err(|_| fail(INVALID))?,
        )
        .map_err(|_| fail(INVALID))?;
        let acquisition: crate::transport::wire::MarketDataAcquisitionDto =
            serde_json::from_value(receipt.clone()).map_err(|_| fail(INVALID))?;
        if acquisition.source_id != source.source_id
            || acquisition.instrument_id != source.instrument_id
            || acquisition.start_ns != start.to_string()
            || acquisition.end_ns != end.to_string()
        {
            return Err(fail("RESEARCH_DATA_ACQUISITION_NOT_COMPLETE"));
        }
        match receipt["status"].as_str() {
            Some("PENDING" | "RUNNING") => return Ok(ResearchInputOutcome::Pending(receipt)),
            Some("FAILED") => return Ok(ResearchInputOutcome::Unavailable(receipt)),
            Some("COMPLETE") => {}
            _ => return Err(fail(INVALID)),
        }
        let revision = receipt["revision_id"]
            .as_str()
            .ok_or_else(|| fail(INVALID))?;
        let mut writer = self.writer.lock().await;
        let client = writer
            .as_mut()
            .ok_or_else(|| fail("PRODUCT_AUTHORITY_UNAVAILABLE"))?
            .client_mut()
            .await
            .map_err(|_| fail("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
        session.require_selection(resolved.selection(), Permission::ClosedHistory)?;
        let mut storage =
            Storage::new(Catalog::new(client, ROWS, WORK)?, &self.clickhouse, 100000)?;
        let selected = storage.catalog().revision(revision).await?;
        let record = selected.revision();
        let scope = Scope::from_record(&record["scope"])?;
        if record["fingerprint"] != receipt["revision_fingerprint"]
            || selected.seal()["seal_id"] != receipt["seal_id"]
            || scope.start_ns() != start
            || scope.end_ns() != end
            || scope.to_record()["source_id"] != source.source_id
            || scope.to_record()["bar_construction"]["plan"]["integration_revision_fingerprint"]
                != source.integration_revision_fingerprint
        {
            return Err(fail(INVALID));
        }
        let plan = NativeMaterializationPlan::new(definition, revision, scope.clone(), 8192)
            .map_err(fail)?;
        let materialized = plan
            .materialize(&mut storage, datasets, &now()?.to_string())
            .await
            .map_err(fail)?;
        session.require_selection(resolved.selection(), Permission::ClosedHistory)?;
        Ok(ResearchInputOutcome::Prepared(Box::new(ResearchInputs {
            materialized,
            selection: json!({"preparation_command_id":command.value(),
            "source":source,"acquisition":receipt,"scope":scope.to_record(),"revision":record,"seal":selected.seal()}),
        })))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn pending_acquisition_remains_input_pending_without_claiming_a_receipt() {
        let outcome =
            acquisition_failure(crate::application::market_product::Error::Unknown.into());
        match outcome {
            Ok(ResearchInputOutcome::Pending(detail)) => {
                assert_eq!(detail, json!({"code":"MARKET_DATA_ACQUISITION_PENDING"}));
                assert!(detail.get("acquisition_id").is_none());
                assert!(detail.get("revision_id").is_none());
            }
            _ => panic!("The acquisition owner has not completed the original input request"),
        }
    }
    #[test]
    fn acquisition_failure_mapping_does_not_reinterpret_other_owner_errors() {
        for code in [
            "MARKET_DATA_ACQUISITION_PENDING_OTHER",
            "MARKET_DATA_STORE_OUTCOME_UNKNOWN",
            "MARKET_DATA_SOURCE_CATALOG_UNAVAILABLE",
            "SOURCE_PERMISSION_DENIED",
        ] {
            match acquisition_failure(Failure::unavailable(code)) {
                Err(error) => assert_eq!(error.code(), code),
                _ => panic!("Only the exact owning acquisition pending outcome is input pending"),
            }
        }
    }
    #[test]
    fn close_event_window_maps_to_the_exact_start_labelled_acquisition_scope() {
        assert_eq!(acquisition_bounds(120, 300, 60).unwrap(), (60, 240));
        assert!(acquisition_bounds(0, 180, 60).is_err());
        assert!(acquisition_bounds(120, 301, 60).is_err());
        assert!(acquisition_bounds(120, 300, 0).is_err());
        assert!(acquisition_bounds(i64::MAX as u64 + 120, i64::MAX as u64 + 180, 60).is_err());
    }
}
