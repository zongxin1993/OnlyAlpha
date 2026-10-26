//! Actual admitted acquisition orchestration. External I/O never holds the
//! singleton business Client; the second PG connection is only an execution lock.
use crate::application::market_product::{
    self, AcquisitionRequest, CaptureRequest, MutationAdmission, ProbeAdmission,
};
use crate::application::source_access::{Reference, Selection};
use crate::persistence::market_data::{Catalog, Scope, Storage};
use crate::security::human_access;
use crate::security::ingress::{self, Release};
use crate::transport::host::{Failure, Host, ROWS, WORK, invalid, now, now_ns};
use crate::transport::wire::MarketDataAcquisitionRequestDto;
use axum::{
    Json,
    body::{Body, to_bytes},
    response::{IntoResponse, Response},
};
use http::Request;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBarSemantic};
use std::{sync::Arc, time::Instant};
pub(crate) enum Operation {
    Acquisition(Selection),
    Probe(Selection, String),
}
pub(crate) struct OwnerAdmission {
    pub human: human_access::Session,
    pub operation: Operation,
}
impl OwnerAdmission {
    fn human(&self) -> Result<(), market_product::Error> {
        if self.human.subject_id().ok() != Some("local-developer") {
            return Err(market_product::Error::Forbidden);
        }
        Ok(())
    }
}
impl MutationAdmission for OwnerAdmission {
    fn require_acquisition(
        &self,
        selection: &Selection,
        _: &Scope,
    ) -> Result<(), market_product::Error> {
        self.human()?;
        if !matches!(&self.operation,Operation::Acquisition(expected) if expected==selection) {
            return Err(market_product::Error::Forbidden);
        }
        Ok(())
    }
}
impl ProbeAdmission for OwnerAdmission {
    fn require_probe(
        &self,
        selection: &Selection,
        attempt: &str,
    ) -> Result<(), market_product::Error> {
        self.human()?;
        if !matches!(&self.operation,Operation::Probe(expected,id) if expected==selection&&id==attempt)
        {
            return Err(market_product::Error::Forbidden);
        }
        Ok(())
    }
}
impl Host {
    pub(crate) async fn acquisition(
        self: &Arc<Self>,
        request: Request<Body>,
        human: human_access::Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        let bytes = to_bytes(request.into_body(), 65536)
            .await
            .map_err(|_| invalid())?;
        let _: MarketDataAcquisitionRequestDto =
            serde_json::from_slice(&bytes).map_err(|_| invalid())?;
        let raw: serde_json::Value = serde_json::from_slice(&bytes).map_err(|_| invalid())?;
        let source = &raw["source_reference"];
        let reference = Reference::new(
            source["integration_id"].as_str().ok_or_else(invalid)?,
            source["integration_revision_fingerprint"]
                .as_str()
                .ok_or_else(invalid)?,
            source["expected_type_id"].as_str(),
        )?;
        let (resolved, session) = self.resolve(&reference).await?;
        let admission = Arc::new(OwnerAdmission {
            human,
            operation: Operation::Acquisition(resolved.selection().clone()),
        });
        let semantic = OnlyBarSemantic::from_record(&raw["bar_semantic"]).map_err(|_| invalid())?;
        let ns = |name: &str| -> Result<i64, Failure> {
            let s = raw[name].as_str().ok_or_else(invalid)?;
            let n: i64 = s.parse().map_err(|_| invalid())?;
            if n < 0 || n.to_string() != s {
                return Err(invalid());
            }
            Ok(n)
        };
        let at = now()?.to_string();
        let mut work = {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or_else(|| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?
                .client_mut()
                .await
                .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
            if deadline <= Instant::now() {
                return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
            }
            let mut store =
                Storage::new(Catalog::new(client, ROWS, WORK)?, &self.clickhouse, 100000)?;
            self.app
                .prepare_acquisition(
                    Arc::clone(&resolved),
                    session.clone(),
                    admission,
                    &mut store,
                    AcquisitionRequest {
                        instrument_id: raw["instrument_id"].as_str().ok_or_else(invalid)?,
                        semantic: &semantic,
                        start_ns: ns("start_ns")?,
                        end_ns: ns("end_ns")?,
                        clock_ns: now_ns()?,
                        admitted_at: &at,
                    },
                )
                .await?
        };
        let lease = self
            .database
            .lease(work.id(), self.inputs.namespace())
            .await?;
        let result = async {
            {
                let mut writer = self.writer.lock().await;
                let client = writer
                    .as_mut()
                    .ok_or_else(|| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?
                    .client_mut()
                    .await
                    .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
                let mut store =
                    Storage::new(Catalog::new(client, ROWS, WORK)?, &self.clickhouse, 100000)?;
                let status = self
                    .app
                    .acquisition_status(&resolved, &session, &mut store, work.id(), Some(&lease))
                    .await?;
                if status.parts()?.0["status"] == "COMPLETE" {
                    return Ok(status);
                }
                work.start(&mut store, &lease, &at).await?;
            }
            let mut wal = self.capture_wal(resolved.identity().source_id.as_str(), None)?;
            let segment = crate::transport::host::uuid()?;
            let capture = crate::transport::host::uuid()?;
            let captured = match work
                .capture(
                    &self.app,
                    &mut wal,
                    CaptureRequest {
                        segment_id: &segment,
                        capture_id: &capture,
                        created_at: &at,
                        deadline,
                    },
                    &lease,
                )
                .await
            {
                Ok(captured) => captured,
                Err(error) => {
                    if !matches!(
                        error,
                        market_product::Error::Unknown
                            | market_product::Error::Store(
                                crate::persistence::market_data::Error::Unknown
                            )
                    ) {
                        let mut writer = self.writer.lock().await;
                        let client = writer
                            .as_mut()
                            .ok_or_else(|| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?
                            .client_mut()
                            .await
                            .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
                        let mut store = Storage::new(
                            Catalog::new(client, ROWS, WORK)?,
                            &self.clickhouse,
                            100000,
                        )?;
                        work.record_failure(&mut store, &lease, error, &now()?.to_string())
                            .await?;
                    }
                    return Err(error.into());
                }
            };
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or_else(|| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?
                .client_mut()
                .await
                .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
            let mut store =
                Storage::new(Catalog::new(client, ROWS, WORK)?, &self.clickhouse, 100000)?;
            work.publish(&mut store, &wal, &captured, &now()?.to_string())
                .await
                .map_err(Failure::from)
        }
        .await;
        let closed = lease.close().await;
        let result = result?;
        closed?;
        let (value, fence) = result.into_parts()?;
        Ok(ingress::attach(
            Json(value).into_response(),
            Release::Source(fence),
        ))
    }
}
