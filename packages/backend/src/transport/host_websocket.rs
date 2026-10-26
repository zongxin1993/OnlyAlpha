//! Actual Hyper upgrade and maintained WebSocket framing over the same physical
//! gated socket. Retains the original Human, generation and Source occurrences.
use crate::application::market_product::{ProductStream, StreamRequest};
use crate::application::source_access::{Permission, Reference, Session};
use crate::persistence::market_data::{Catalog, Storage};
use crate::security::human_access;
use crate::security::ingress::{self, PhysicalConnection, Release};
use crate::transport::host::{Failure, Host, ROWS, WORK, invalid, now, now_ns, uuid};
use crate::transport::stream_wire::{StreamEvent, StreamSubscribe};
use axum::{body::Body, response::Response};
use futures_util::{SinkExt, StreamExt};
use http::Request;
use hyper_util::rt::TokioIo;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBarSemantic};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio_tungstenite::{
    WebSocketStream,
    tungstenite::{
        Message,
        protocol::{Role, WebSocketConfig},
    },
};
pub(crate) type Socket = WebSocketStream<TokioIo<hyper::upgrade::Upgraded>>;
impl Host {
    pub(crate) async fn websocket(
        self: &Arc<Self>,
        mut request: Request<Body>,
        human: human_access::Session,
    ) -> Result<Response, Failure> {
        if human.subject_id()?.ne("local-developer") {
            return Err(invalid());
        }
        let physical = request
            .extensions()
            .get::<PhysicalConnection>()
            .cloned()
            .ok_or_else(|| Failure::unavailable("WEBSOCKET_TRANSPORT_UNAVAILABLE"))?;
        let slot = Arc::clone(&self.socket_slots)
            .try_acquire_owned()
            .map_err(|_| Failure::unavailable("MARKET_DATA_STREAM_CAPACITY_UNAVAILABLE"))?;
        let session = self.source_session().await;
        let mut head = Request::new(());
        *head.method_mut() = request.method().clone();
        *head.uri_mut() = request.uri().clone();
        *head.version_mut() = request.version();
        *head.headers_mut() = request.headers().clone();
        let response = tokio_tungstenite::tungstenite::handshake::server::create_response(&head)
            .map_err(|_| invalid())?;
        let temporary = request.uri().path() == "/api/v2/chart/market-data/stream";
        let upgrade = hyper::upgrade::on(&mut request);
        let proof = Arc::new(Release::Generation(session.clone()));
        let host = Arc::clone(self);
        let connection = physical.clone();
        let retained = Arc::clone(&proof);
        let mut tasks = self.stream_tasks.lock().await;
        while let Some(result) = tasks.try_join_next() {
            if let Ok(Err(error)) = &result {
                eprintln!("NATIVE_STREAM_FAILED {error}");
            }
            if !matches!(result, Ok(Ok(()))) {
                *self
                    .stream_failure
                    .lock()
                    .map_err(|_| Failure::unavailable("STREAM_OWNER_UNAVAILABLE"))? =
                    Some("STREAM_DRAIN_FAILED");
            }
        }
        tasks.spawn(async move{
   let _slot=slot;
   let upgraded=tokio::select!{result=upgrade=>match result{Ok(upgraded)=>upgraded,Err(_)=>return Ok(())},_=connection.closed()=>return Ok(())};
   let mut socket=WebSocketStream::from_raw_socket(TokioIo::new(upgraded),Role::Server,Some(WebSocketConfig::default().read_buffer_size(16384).write_buffer_size(0).max_write_buffer_size(262144).max_message_size(Some(65536)).max_frame_size(Some(65536)))).await;
   if connection.upgraded(Arc::clone(&retained)).is_err(){return Ok(());}
   if temporary {host.temporary_stream(&mut socket,&connection,session,retained).await}
   else {host.stream(&mut socket,&connection,session,retained).await}
  });
        let (parts, _) = response.into_parts();
        let mut response = Response::from_parts(parts, Body::empty());
        response.extensions_mut().insert(proof);
        Ok(response)
    }
    async fn stream(
        self: &Arc<Self>,
        socket: &mut Socket,
        physical: &PhysicalConnection,
        session: Session,
        generation: Arc<Release>,
    ) -> Result<(), Failure> {
        // No Product stream exists until this preparation completes. Malformed or
        // unavailable subscriptions are ordinary client outcomes, never failed drain.
        let prepared:Result<Option<(ProductStream,String)>,Failure>=async {
  let deadline=Instant::now()+Duration::from_secs(5);
  let text=loop{let message=tokio::select!{_=physical.closed()=>return Ok(None),result=tokio::time::timeout_at(deadline.into(),socket.next())=>result.map_err(|_|Failure::unavailable("MARKET_DATA_STREAM_HANDSHAKE_TIMEOUT"))?};
   match message{Some(Ok(Message::Text(text)))=>break text,Some(Ok(Message::Ping(_)))=>{physical.frame(Arc::clone(&generation)).map_err(|_|invalid())?;physical.complete_frame(socket.flush()).await.map_err(|_|invalid())?;physical.idle(Arc::clone(&generation)).map_err(|_|invalid())?;},Some(Ok(Message::Pong(_)))=>{},_=>return Ok(None)}
  };
  if text.len()>65536{return Err(invalid());}
  // Use the same strict duplicate-key admission as ordinary JSON requests.
  ingress::validate_json(text.as_bytes()).map_err(|_|invalid())?;
  let dto:StreamSubscribe=serde_json::from_str(&text).map_err(|_|invalid())?;
  let value:serde_json::Value=serde_json::from_str(&text).map_err(|_|invalid())?;
  let reference=Reference::new(&dto.source_reference.integration_id,&dto.source_reference.integration_revision_fingerprint,Some(&dto.source_reference.expected_type_id))?;
  let snapshots=self.snapshots().await?;let snapshot=snapshots.iter().find(|s|s.integration().record().integration_id.value()==reference.integration_id()).ok_or_else(||Failure::unavailable("MARKET_DATA_SOURCE_SELECTION_UNRESOLVED"))?;
  let resolved=Arc::new(self.resolver.resolve(snapshot,&reference,&session,None)?);
  session.require_selection(resolved.selection(),Permission::RealtimePreview)?;
  let stream_id=uuid()?;let segment=uuid()?;let capture=uuid()?;let at=now()?.to_string();let opening=Instant::now()+Duration::from_secs(8);
  let genuine=self.app.reference(&resolved,&session,&dto.instrument_id,opening).await?;
  let semantic=OnlyBarSemantic::from_record(&value["bar_semantic"]).map_err(|_|invalid())?;
  let resume=dto.resume_after_sequence.parse::<i64>().map_err(|_|invalid())?;
  if resume<0 || resume.to_string()!=dto.resume_after_sequence{return Err(invalid());}
  let wal=self.capture_wal(&resolved.identity().source_id,Some(&stream_id))?;
  // open_stream reads exact bootstrap history and then opens provider I/O. The
  // explicitly read-only connection prevents borrowing the mutation Client here.
  let stream={let mut read=self.reader.lock().await;let client=read.as_mut().ok_or_else(||Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;let mut store=Storage::new(Catalog::new(client,ROWS,WORK)?,&self.clickhouse,100000)?;
   self.app.open_stream(Arc::clone(&resolved),genuine,&mut store,StreamRequest{stream_id:stream_id.clone(),semantic,resume_after_sequence:if resume==0 && value["resume_plan_fingerprint"].is_null(){None}else{Some(resume)},resume_plan_fingerprint:value["resume_plan_fingerprint"].as_str().map(String::from),clock_ns:now_ns()?,deadline:opening,segment_id:segment,capture_id:capture,created_at:at},wal).await?
  };
   Ok(Some((stream,stream_id)))
  }.await;
        let (mut stream, stream_id) = match prepared {
            Ok(Some(stream)) => stream,
            Ok(None) => return Ok(()),
            Err(error) => {
                let code = error.to_string();
                let text=serde_json::json!({"schema_version":2,"event":"ERROR","code":&code,"detail":&code}).to_string();
                if physical.frame(Arc::clone(&generation)).is_ok() {
                    let _ = physical
                        .complete_frame(socket.send(Message::Text(text.into())))
                        .await;
                    let _ = physical.idle(Arc::clone(&generation));
                }
                return Ok(());
            }
        };
        let registered = self
            .previews
            .lock()
            .map(|mut p| {
                p.insert(stream_id.clone(), stream.preview_source());
            })
            .map_err(|_| Failure::unavailable("STREAM_OWNER_UNAVAILABLE"));
        let outcome = match registered {
            Ok(()) => {
                self.stream_events(socket, physical, &mut stream, generation, &session)
                    .await
            }
            Err(error) => Err(error),
        };
        let removed = self
            .previews
            .lock()
            .map(|mut p| {
                p.remove(&stream_id);
            })
            .map_err(|_| Failure::unavailable("STREAM_OWNER_UNAVAILABLE"));
        let closed = stream.close().await;
        let drained = {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or_else(|| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?
                .client_mut()
                .await
                .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
            let mut store =
                Storage::new(Catalog::new(client, ROWS, WORK)?, &self.clickhouse, 100000)?;
            stream.drain(&mut store, &now()?.to_string()).await
        };
        closed_result(&session, closed)?;
        drained?;
        removed?;
        if let Err(error) = outcome {
            eprintln!("NATIVE_STREAM_OPERATION_FAILED {error}");
        }
        Ok(())
    }
    async fn stream_events(
        &self,
        socket: &mut Socket,
        physical: &PhysicalConnection,
        stream: &mut ProductStream,
        mut base: Arc<Release>,
        session: &Session,
    ) -> Result<(), Failure> {
        loop {
            tokio::select! {biased;
             _=physical.closed()=>return Ok(()),
             message=socket.next()=>match message{
              Some(Ok(Message::Ping(_)|Message::Close(_)))=>{if physical.frame(Arc::clone(&base)).is_err(){return Ok(());}let flushed=physical.complete_frame(socket.flush()).await;if physical.idle(Arc::clone(&base)).is_err() || flushed.is_err(){return Ok(());}},
              Some(Ok(Message::Pong(_)))=>{tokio::task::yield_now().await;},None|Some(Err(_))=>return Ok(()),_=>return Ok(())
             },
             event=stream.next()=>{
              let event=match event{Ok(Some(event))=>event,Ok(None)=>return Ok(()),Err(_)=>return Ok(())};
              let result={let mut writer=self.writer.lock().await;let client=writer.as_mut().ok_or_else(||Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?.client_mut().await.map_err(|_|Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;let mut store=Storage::new(Catalog::new(client,ROWS,WORK)?,&self.clickhouse,100000)?;stream.release(event,&mut store,&now()?.to_string()).await.and_then(|value|value.into_parts())};
              // Only coalesced, obsolete previews may be skipped. The original
              // stream and Source failures still terminate and retain cleanup.
              if matches!(result,Err(crate::application::market_product::Error::PreviewSuperseded)){continue;}
              let Some((value,fence))=source_completion(session,result)? else {return Ok(());};let text=serde_json::to_string(&value).map_err(|_|invalid())?;
              let _:StreamEvent=serde_json::from_str(&text).map_err(|_|Failure::unavailable("MARKET_DATA_STREAM_CONTRACT_INVALID"))?;
              let proof=Arc::new(Release::Source(fence));if value["event"]=="SUBSCRIBED"{base=Arc::clone(&proof);}
              if physical.frame(proof).is_err(){return Ok(());}
              if physical.complete_frame(socket.send(Message::Text(text.into()))).await.is_err(){return Ok(());}
              if physical.idle(Arc::clone(&base)).is_err(){return Ok(());}
             }
            }
        }
    }
}

// Expected withdrawal is terminal only for this exact original Source session.
// Resource close/drain results are checked independently before this outcome.
fn source_completion<T>(
    session: &Session,
    result: std::result::Result<T, crate::application::market_product::Error>,
) -> Result<Option<T>, Failure> {
    match result {
        Ok(value) => Ok(Some(value)),
        Err(crate::application::market_product::Error::Forbidden)
            if matches!(
                session.check_active(),
                Err(crate::application::source_access::Error::Unauthorized)
            ) =>
        {
            Ok(None)
        }
        Err(error) => Err(error.into()),
    }
}
fn closed_result(
    session: &Session,
    closed: std::result::Result<(), crate::application::market_product::Error>,
) -> Result<(), Failure> {
    source_completion(session, closed).map(|_| ())
}
#[cfg(test)]
mod close_tests {
    use super::*;
    use sha2::Digest;
    fn source() -> (crate::application::source_access::Authority, Session) {
        let token = "a".repeat(64);
        let hash: String = sha2::Sha256::digest(token.as_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        let authority =
            crate::application::source_access::Authority::new("test-source", &hash, vec![])
                .unwrap();
        let session = authority.authenticate(&format!("Bearer {token}")).unwrap();
        (authority, session)
    }
    #[tokio::test(flavor = "current_thread")]
    async fn withdrawal_between_release_admission_and_completion_is_normal() {
        let (authority, session) = source();
        let (started, admitted) = tokio::sync::oneshot::channel();
        let (release, proceed) = tokio::sync::oneshot::channel();
        let original = session.clone();
        let worker = tokio::spawn(async move {
            original.check_active().unwrap();
            started.send(()).unwrap();
            proceed.await.unwrap();
            let result = original
                .check_active()
                .map_err(crate::application::market_product::Error::from);
            source_completion(&original, result)
        });
        admitted.await.unwrap();
        authority.withdraw();
        release.send(()).unwrap();
        assert!(matches!(worker.await.unwrap(), Ok(None)));
    }
    #[test]
    fn withdrawn_source_completion_is_not_a_failed_drain() {
        let (authority, session) = source();
        authority.withdraw();
        assert!(
            closed_result(
                &session,
                Err(crate::application::market_product::Error::Forbidden)
            )
            .is_ok()
        );
    }
    #[test]
    fn source_close_does_not_hide_live_denial_or_resource_failure() {
        let (authority, session) = source();
        assert!(
            closed_result(
                &session,
                Err(crate::application::market_product::Error::Forbidden)
            )
            .is_err()
        );
        authority.withdraw();
        assert!(
            closed_result(
                &session,
                Err(crate::application::market_product::Error::Unavailable)
            )
            .is_err()
        );
        assert!(closed_result(&session, Ok(())).is_ok());
    }
}
