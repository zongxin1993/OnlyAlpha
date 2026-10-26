//! Volatile display ingress. Only Source metadata is resolved; no market Storage
//! or mutation session is borrowed by this operation.
use crate::application::market_product::WindowRequest;
use crate::security::ingress::{self, Release};
use crate::transport::host::{
    Failure, Host, invalid, now_ns, parameters, reference, required, semantic,
};
use axum::{
    Json,
    body::Body,
    response::{IntoResponse, Response},
};
use http::Request;
use std::{sync::Arc, time::Instant};
impl Host {
    pub(crate) async fn temporary_market(
        self: &Arc<Self>,
        request: Request<Body>,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        let p = parameters(request.uri())?;
        if p.keys().any(|key| {
            !matches!(
                key.as_str(),
                "page_id"
                    | "integration_id"
                    | "integration_revision_fingerprint"
                    | "expected_type_id"
                    | "instrument_id"
                    | "anchor_kind"
                    | "bar_semantic"
                    | "target_bar_count"
                    | "before_ns"
            )
        }) {
            return Err(invalid());
        }
        let before = p.get("before_ns");
        match p.get("anchor_kind").map(String::as_str) {
            Some("LATEST_CLOSED") if before.is_none() => {}
            Some("BEFORE_TIME") if before.is_some() => {}
            _ => return Err(invalid()),
        }
        let reference = reference(&p)?;
        let (resolved, session) = self.resolve(&reference).await?;
        let query = WindowRequest {
            instrument_id: required(&p, "instrument_id")?.into(),
            semantic: semantic(&p)?,
            before_ns: before
                .map(|s| s.parse().map_err(|_| invalid()))
                .transpose()?,
            bar_count: required(&p, "target_bar_count")?
                .parse()
                .map_err(|_| invalid())?,
            clock_ns: now_ns()?,
        };
        let (value, fence) = self
            .app
            .temporary_window(
                &resolved,
                &session,
                &query,
                required(&p, "page_id")?,
                deadline,
            )
            .await?
            .into_parts()?;
        Ok(ingress::attach(
            Json(value).into_response(),
            Release::Source(fence),
        ))
    }
}

use crate::application::market_product::{TemporaryProductStream, TemporaryStreamRequest};
use crate::application::source_access::{Permission, Reference, Session};
use crate::security::ingress::PhysicalConnection;
use crate::transport::host_websocket::Socket;
use crate::transport::stream_wire::{TemporaryStreamEvent, TemporaryStreamSubscribe};
use futures_util::{SinkExt, StreamExt};
use onlyalpha_domain::base::OnlyDomainModel;
use std::time::Duration;
use tokio_tungstenite::tungstenite::Message;
impl Host {
    pub(crate) async fn temporary_stream(
        self: &Arc<Self>,
        socket: &mut Socket,
        physical: &PhysicalConnection,
        session: Session,
        generation: Arc<Release>,
    ) -> Result<(), Failure> {
        let prepared:Result<Option<TemporaryProductStream>,Failure>=async{
            let opening=Instant::now()+Duration::from_secs(10);
            let deadline=(Instant::now()+Duration::from_secs(5)).min(opening);
            let text=loop{
                let message=tokio::select!{
                    _=physical.closed()=>return Ok(None),
                    message=tokio::time::timeout_at(deadline.into(),socket.next())=>message.map_err(|_|Failure::unavailable("MARKET_DATA_STREAM_HANDSHAKE_TIMEOUT"))?,
                };
                match message {
                    Some(Ok(Message::Text(text)))=>break text,
                    Some(Ok(Message::Ping(_)))=>{
                        physical.frame(Arc::clone(&generation)).map_err(|_|invalid())?;
                        physical.complete_frame(socket.flush()).await.map_err(|_|invalid())?;
                        physical.idle(Arc::clone(&generation)).map_err(|_|invalid())?;
                    },
                    Some(Ok(Message::Pong(_)))=>{},_=>return Ok(None),
                }
            };
            ingress::validate_json(text.as_bytes()).map_err(|_|invalid())?;
            let dto:TemporaryStreamSubscribe=serde_json::from_str(&text).map_err(|_|invalid())?;
            let reference=Reference::new(&dto.source_reference.integration_id,&dto.source_reference.integration_revision_fingerprint,Some(&dto.source_reference.expected_type_id))?;
            let snapshots=self.snapshots().await?;
            let snapshot=snapshots.iter().find(|s|s.integration().record().integration_id.value()==reference.integration_id()).ok_or_else(||Failure::unavailable("MARKET_DATA_SOURCE_SELECTION_UNRESOLVED"))?;
            let resolved=Arc::new(self.resolver.resolve(snapshot,&reference,&session,None)?);
            session.require_selection(resolved.selection(),Permission::RealtimePreview)?;
            let before=dto.before_ns.parse::<i64>().map_err(|_|invalid())?;
            if before.to_string()!=dto.before_ns {return Err(invalid());}
            let value:serde_json::Value=serde_json::from_str(&text).map_err(|_|invalid())?;
            let window=WindowRequest{instrument_id:dto.instrument_id,semantic:onlyalpha_domain::market::OnlyBarSemantic::from_record(&value["bar_semantic"]).map_err(|_|invalid())?,before_ns:Some(before),bar_count:usize::try_from(dto.target_bar_count).map_err(|_|invalid())?,clock_ns:now_ns()?};
            let stream=tokio::select!{
                _=physical.closed()=>return Ok(None),
                stream=self.app.open_temporary_stream(resolved,&session,TemporaryStreamRequest{stream_id:crate::transport::host::uuid()?,page_id:dto.page_id,window,expected_window_fingerprint:dto.expected_window_fingerprint,deadline:opening})=>stream?,
            };
            Ok(Some(stream))
        }.await;
        let mut stream = match prepared {
            Ok(Some(stream)) => stream,
            Ok(None) => return Ok(()),
            Err(error) => {
                self.temporary_error(socket, physical, &generation, &error.to_string())
                    .await;
                return Ok(());
            }
        };
        let mut base = Arc::clone(&generation);
        let outcome: Result<(), Failure> = async {
            loop {
                let event = {
                    // Control frames must not cancel Provider recovery or consume
                    // its original deadline by restarting the same next call.
                    let next = stream.next();
                    tokio::pin!(next);
                    loop {
                        tokio::select! { biased;
                            _ = physical.closed() => return Ok(()),
                            event = &mut next => break event?,
                            message = socket.next() => match message {
                                Some(Ok(Message::Ping(_))) => {
                                    physical.frame(Arc::clone(&base)).map_err(|_| invalid())?;
                                    physical.complete_frame(socket.flush()).await.map_err(|_| invalid())?;
                                    physical.idle(Arc::clone(&base)).map_err(|_| invalid())?;
                                },
                                Some(Ok(Message::Pong(_))) => {},
                                _ => return Ok(()),
                            },
                        }
                    }
                };
                let event = match event { Some(event) => event, None => return Ok(()) };
                let (value, fence) = event.into_parts()?;
                let text = serde_json::to_string(&value).map_err(|_| invalid())?;
                let _: TemporaryStreamEvent = serde_json::from_str(&text)
                    .map_err(|_| Failure::unavailable("MARKET_DATA_STREAM_CONTRACT_INVALID"))?;
                let proof = Arc::new(Release::Source(fence));
                if value["event"] == "SUBSCRIBED" { base = Arc::clone(&proof); }
                physical.frame(proof).map_err(|_| invalid())?;
                physical.complete_frame(socket.send(Message::Text(text.into()))).await.map_err(|_| invalid())?;
                physical.idle(Arc::clone(&base)).map_err(|_| invalid())?;
            }
        }.await;
        if let Err(error) = outcome {
            // An operational loss is visible if this exact original Source still
            // permits sending. Cleanup failure remains a distinct lifecycle error.
            self.temporary_error(socket, physical, &generation, &error.to_string())
                .await;
        }
        stream.close().await?;
        Ok(())
    }
    async fn temporary_error(
        &self,
        socket: &mut Socket,
        physical: &PhysicalConnection,
        proof: &Arc<Release>,
        code: &str,
    ) {
        let text =
            serde_json::json!({"schema_version":2,"event":"ERROR","code":code,"detail":code})
                .to_string();
        if physical.frame(Arc::clone(proof)).is_ok() {
            let _ = physical
                .complete_frame(socket.send(Message::Text(text.into())))
                .await;
            let _ = physical.idle(Arc::clone(proof));
        }
    }
}

impl Host {
    pub(crate) async fn temporary_chart_evaluate(
        self: &Arc<Self>,
        request: Request<Body>,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        use crate::security::human_access;
        use crate::transport::host::chart_permit;
        use crate::transport::wire::{
            TemporaryChartStudyBatchRequestDto, TemporaryChartStudyEvaluateRequestDto,
        };
        use axum::body::to_bytes;
        let human = request
            .extensions()
            .get::<human_access::Session>()
            .ok_or_else(invalid)?
            .clone();
        let batch = request.uri().path().ends_with("/evaluate-batch");
        let raw = String::from_utf8(
            to_bytes(request.into_body(), 65536)
                .await
                .map_err(|_| invalid())?
                .to_vec(),
        )
        .map_err(|_| invalid())?;
        if batch {
            let _: TemporaryChartStudyBatchRequestDto =
                serde_json::from_str(&raw).map_err(|_| invalid())?;
        } else {
            let _: TemporaryChartStudyEvaluateRequestDto =
                serde_json::from_str(&raw).map_err(|_| invalid())?;
        }
        let parsed: serde_json::Value = serde_json::from_str(&raw).map_err(|_| invalid())?;
        let source = &parsed["source_reference"];
        let reference = Reference::new(
            source["integration_id"].as_str().ok_or_else(invalid)?,
            source["integration_revision_fingerprint"]
                .as_str()
                .ok_or_else(invalid)?,
            source["expected_type_id"].as_str(),
        )?;
        let permit = chart_permit(Arc::clone(&self.chart_gate), deadline).await?;
        if !self.admitted() {
            return Err(Failure::unavailable("PRODUCT_NODE_NOT_READY"));
        }
        human.subject_id()?;
        let host = Arc::clone(self);
        let handle = tokio::runtime::Handle::current();
        let (mut value, mut fence) = tokio::task::spawn_blocking(move || -> Result<_, Failure> {
            let _permit = permit;
            handle.block_on(async {
                // Both Query forms use the same original owning Source fence.
                let (resolved, session) = host.resolve(&reference).await?;
                let result = if batch {
                    host.chart
                        .prepare_temporary_batch_before(
                            &host.app,
                            &resolved,
                            &session,
                            &raw,
                            now_ns()?,
                            deadline,
                        )
                        .await
                        .map_err(temporary_chart_failure)?
                        .execute()
                } else {
                    host.chart
                        .prepare_temporary_before(
                            &host.app,
                            &resolved,
                            &session,
                            &raw,
                            now_ns()?,
                            deadline,
                        )
                        .await
                        .map_err(temporary_chart_failure)?
                        .execute()
                };
                result
                    .and_then(|result| result.into_parts())
                    .map_err(temporary_chart_failure)
            })
        })
        .await
        .map_err(|_| Failure::unavailable("CHART_STUDY_QUERY_UNAVAILABLE"))??;
        fence
            .prepare_send(&mut value)
            .map_err(temporary_chart_failure)?;
        Ok(ingress::attach(
            Json(value).into_response(),
            Release::Chart(fence),
        ))
    }
}
fn temporary_chart_failure(error: crate::application::chart::Error) -> Failure {
    use crate::application::chart::Error;
    use http::StatusCode;
    let status = match &error {
        Error::Invalid => StatusCode::BAD_REQUEST,
        Error::InputChanged | Error::Changed => StatusCode::CONFLICT,
        Error::Capacity => StatusCode::TOO_MANY_REQUESTS,
        Error::Market(error) => return (*error).into(),
        _ => StatusCode::SERVICE_UNAVAILABLE,
    };
    Failure::with_status(status, error.code())
}
