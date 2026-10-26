//! Read-only Product observations and blocking algorithm composition.
use crate::application::chart::{ChartInput, ChartSource};
use crate::application::private_assets::PrivateAssets;
use crate::application::source_access::{Reference, Session};
use crate::persistence::integration_postgres::Snapshot;
use crate::persistence::market_data::{Catalog, Storage};
use crate::security::human_access;
use crate::security::ingress::{self, Release};
use crate::transport::host::{
    Failure, Host, ROWS, WORK, chart_permit, invalid, now_ns, parameters, required,
};
use crate::transport::wire::ChartStudyEvaluateRequestDto;
use axum::{
    Json,
    body::{Body, to_bytes},
    response::{IntoResponse, Response},
};
use http::{Request, StatusCode};
use serde_json::Value;
use std::{sync::Arc, time::Instant};
impl From<crate::application::private_assets::Error> for Failure {
    fn from(e: crate::application::private_assets::Error) -> Self {
        use crate::application::private_assets::Error;
        let status = match e {
            Error::Invalid => StatusCode::BAD_REQUEST,
            Error::Forbidden => StatusCode::FORBIDDEN,
            Error::NotFound => StatusCode::NOT_FOUND,
            Error::Mismatch => StatusCode::CONFLICT,
            Error::Corrupt | Error::Unavailable => StatusCode::SERVICE_UNAVAILABLE,
        };
        Self::with_status(status, e.code())
    }
}
impl Host {
    pub(crate) fn source_descriptions(
        &self,
        snapshots: &[Snapshot],
        session: &Session,
    ) -> Result<
        (
            Vec<crate::application::market_product::Resolved>,
            crate::application::market_product::AuthorizedBatch,
        ),
        Failure,
    > {
        let mut identities = vec![];
        for snapshot in snapshots {
            let owner = snapshot.integration().record();
            if owner.lifecycle != crate::application::integration_configuration::Lifecycle::Active
                || owner.type_id.value() != "binance.spot.market_data"
            {
                continue;
            }
            for (revision, _) in snapshot.history() {
                let reference = Reference::new(
                    owner.integration_id.value(),
                    &revision.record().revision_fingerprint,
                    Some(owner.type_id.value()),
                )?;
                identities.push((reference.clone(), Self::identity(snapshot, &reference)?));
            }
        }
        self.resolver
            .sources_with_history(snapshots, session, &identities)
            .map_err(Into::into)
    }
    pub(crate) async fn chart_evaluate(
        self: &Arc<Self>,
        request: Request<Body>,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        let human = request
            .extensions()
            .get::<human_access::Session>()
            .ok_or_else(|| {
                Failure::with_status(StatusCode::UNAUTHORIZED, "LOCAL_READ_UNAUTHORIZED")
            })?
            .clone();
        let raw = String::from_utf8(
            to_bytes(request.into_body(), 65536)
                .await
                .map_err(|_| invalid())?
                .to_vec(),
        )
        .map_err(|_| invalid())?;
        let _: ChartStudyEvaluateRequestDto = serde_json::from_str(&raw).map_err(|_| invalid())?;
        let parsed: Value = serde_json::from_str(&raw).map_err(|_| invalid())?;
        let reference = Reference::new(
            parsed["source_reference"]["integration_id"]
                .as_str()
                .ok_or_else(invalid)?,
            parsed["source_reference"]["integration_revision_fingerprint"]
                .as_str()
                .ok_or_else(invalid)?,
            parsed["source_reference"]["expected_type_id"].as_str(),
        )?;
        let preview = parsed["preview_stream_id"]
            .as_str()
            .and_then(|id| self.previews.lock().ok()?.get(id).cloned());
        let permit = chart_permit(Arc::clone(&self.chart_gate), deadline).await?;
        if !self.admitted() {
            return Err(Failure::unavailable("PRODUCT_NODE_NOT_READY"));
        }
        human.subject_id()?;
        let host = Arc::clone(self);
        let handle = tokio::runtime::Handle::current();
        let (mut value, mut fence) = tokio::task::spawn_blocking(move || -> Result<_, Failure> {
            let _permit = permit;
            let prepared = handle.block_on(async {
                let snapshots = host.snapshots().await?;
                let session = host.source_session().await;
                let snapshot = snapshots
                    .iter()
                    .find(|s| {
                        s.integration().record().integration_id.value()
                            == reference.integration_id()
                    })
                    .ok_or_else(|| {
                        Failure::with_status(
                            StatusCode::NOT_FOUND,
                            "MARKET_DATA_SOURCE_SELECTION_UNRESOLVED",
                        )
                    })?;
                let current = host.resolver.resolve(snapshot, &reference, &session, None);
                let mut read = host.reader.lock().await;
                let client = read
                    .as_mut()
                    .ok_or_else(|| Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
                let mut store =
                    Storage::new(Catalog::new(client, ROWS, WORK)?, &host.clickhouse, 100000)?;
                let history = if current.is_err() {
                    Some(
                        crate::application::market_product::HistoryContext::select(
                            snapshot,
                            &reference,
                            &session,
                            &mut store,
                            Host::identity(snapshot, &reference)?,
                            onlyalpha_plugin_binance::spot_source::spot_calendar().map_err(
                                |_| Failure::unavailable("MARKET_DATA_HISTORY_CONTEXT_UNPROVABLE"),
                            )?,
                            parsed["instrument_id"].as_str().ok_or_else(invalid)?,
                            &onlyalpha_domain::market::OnlyBarSemantic::from_record(
                                &parsed["bar_semantic"],
                            )
                            .map_err(|_| invalid())?,
                        )
                        .await?,
                    )
                } else {
                    None
                };
                let source = match (&current, &history) {
                    (Ok(r), _) => ChartSource::Current(r),
                    (_, Some(h)) => ChartSource::History(h),
                    _ => {
                        return Err(Failure::unavailable(
                            "MARKET_DATA_HISTORY_CONTEXT_UNPROVABLE",
                        ));
                    }
                };
                host.chart
                    .prepare_before(
                        &host.app,
                        source,
                        &session,
                        &mut store,
                        ChartInput {
                            raw: &raw,
                            preview_stream: preview.as_ref(),
                            clock_ns: now_ns()?,
                        },
                        deadline,
                    )
                    .await
                    .map_err(|e| Failure::unavailable(e.code()))
            })?;
            prepared
                .execute()
                .and_then(|result| result.into_parts())
                .map_err(|e| Failure::unavailable(e.code()))
        })
        .await
        .map_err(|_| Failure::unavailable("CHART_STUDY_QUERY_UNAVAILABLE"))??;
        fence
            .prepare_send(&mut value)
            .map_err(|e| Failure::unavailable(e.code()))?;
        Ok(ingress::attach(
            Json(value).into_response(),
            Release::Chart(fence),
        ))
    }
    pub(crate) async fn private_assets(
        &self,
        request: Request<Body>,
        human: &human_access::Session,
    ) -> Result<Response, Failure> {
        let p = parameters(request.uri())?;
        let path = request.uri().path();
        let session = human.metadata_session();
        let mut read = self.reader.lock().await;
        let client = read
            .as_mut()
            .ok_or_else(|| Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
        let mut store = PrivateAssets::new(client);
        let result = if path == "/api/v2/private-assets" {
            store.current_registry(&session).await?
        } else {
            let parts: Vec<_> = path.split('/').collect();
            match parts.as_slice() {
                [
                    "",
                    "api",
                    "v2",
                    "private-assets",
                    "factors",
                    id,
                    "revisions",
                    revision,
                ] => {
                    store
                        .factor_revision(
                            &session,
                            id,
                            revision,
                            required(&p, "content_fingerprint")?,
                        )
                        .await?
                }
                _ => return Err(invalid()),
            }
        };
        let (value, fence) = result.into_parts()?;
        Ok(ingress::attach(
            Json(value).into_response(),
            Release::Asset(fence),
        ))
    }
}
use onlyalpha_domain::base::OnlyDomainModel;
