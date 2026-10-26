//! Real owned stream worker, bounded reliable output, coalesced previews and
//! cancellation/join. No socket connection is interpreted as Product READY.
use super::queries::{self, Application, Authorized};
use super::*;
use crate::application::source_access::{Permission, Session};
use crate::persistence::market_data::{CoverageStatus, Storage};
use onlyalpha_domain::{
    base::OnlyDomainModel, instrument::OnlyInstrument, market::OnlyBarSemantic, time::OnlyTimestamp,
};
use onlyalpha_integration_contract::source::{HistoryRequest, Recorder, Stream, StreamEvent};
use onlyalpha_market_data_construction::*;
use serde_json::json;
use std::{
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    time::Instant,
};
pub struct StreamRequest {
    pub stream_id: String,
    pub semantic: OnlyBarSemantic,
    pub resume_after_sequence: Option<i64>,
    pub resume_plan_fingerprint: Option<String>,
    pub clock_ns: i64,
    pub deadline: Instant,
    pub segment_id: String,
    pub capture_id: String,
    pub created_at: String,
}
struct State {
    cancel: AtomicBool,
    preview_generation: AtomicU64,
    wake: tokio::sync::Notify,
    preview: Mutex<Option<(Value, u64)>>,
    loss: Mutex<Option<Error>>,
    closed: AtomicBool,
}
pub(super) struct PreviewFence {
    state: Arc<State>,
    generation: u64,
}
impl PreviewFence {
    pub(super) fn check(&self) -> Result<()> {
        StreamFence {
            state: Arc::clone(&self.state),
        }
        .check()?;
        if self.state.preview_generation.load(Ordering::Acquire) != self.generation {
            return Err(Error::PreviewSuperseded);
        }
        Ok(())
    }
}
impl State {
    fn next_preview_generation(&self) -> Result<u64> {
        self.preview_generation
            .try_update(Ordering::AcqRel, Ordering::Acquire, |n| n.checked_add(1))
            .map(|n| n + 1)
            .map_err(|_| Error::Unavailable)
    }
    fn clear_preview(&self) -> Result<()> {
        let mut preview = self.preview.lock().map_err(|_| Error::Unavailable)?;
        self.next_preview_generation()?;
        *preview = None;
        Ok(())
    }
    fn retain_loss(&self, error: Error) -> Result<()> {
        let cleared = self.clear_preview();
        let stored = self
            .loss
            .lock()
            .map(|mut loss| *loss = Some(error))
            .map_err(|_| Error::Unavailable);
        self.wake.notify_waiters();
        cleared.and(stored)
    }
    fn preview(&self, value: Value) -> Result<()> {
        let mut preview = self.preview.lock().map_err(|_| Error::Unavailable)?;
        let generation = self.next_preview_generation()?;
        *preview = Some((value, generation));
        Ok(())
    }
}
pub struct PendingStreamEvent {
    payload: Value,
    preview: Option<PreviewFence>,
    state: Arc<State>,
    ordinal: u64,
}
pub(super) struct StreamFence {
    state: Arc<State>,
}
impl StreamFence {
    pub(super) fn check(&self) -> Result<()> {
        if self.state.cancel.load(Ordering::Acquire)
            || self.state.closed.load(Ordering::Acquire)
            || self
                .state
                .loss
                .lock()
                .map_err(|_| Error::Unavailable)?
                .is_some()
        {
            return Err(Error::Source(SourceError::Stopped));
        }
        Ok(())
    }
}
pub struct ProductStream {
    stream_id: String,
    plan_fingerprint: String,
    issued: u64,
    issued_preview_generation: u64,
    pending: Option<u64>,
    sealed: crate::persistence::market_data_wal::SealedWal,
    segment_prefix: String,
    capture: String,
    receiver: tokio::sync::mpsc::Receiver<Value>,
    state: Arc<State>,
    worker: Option<tokio::task::JoinHandle<Result<()>>>,
    session: Session,
    resolved: Arc<Resolved>,
    error_delivered: bool,
    failed_delivered: bool,
    _permit: Arc<tokio::sync::OwnedSemaphorePermit>,
}
// Observations of existing owners only; this snapshot grants no readiness.
impl std::fmt::Debug for ProductStream {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let loss = self
            .state
            .loss
            .lock()
            .ok()
            .and_then(|value| value.map(Error::code));
        f.debug_struct("ProductStream")
            .field("queued_reliable", &self.receiver.len())
            .field("loss", &loss)
            .field("writer_closed", &self.state.closed.load(Ordering::Acquire))
            .field(
                "worker_finished",
                &self
                    .worker
                    .as_ref()
                    .is_none_or(tokio::task::JoinHandle::is_finished),
            )
            .field("worker_joined", &self.worker.is_none())
            .finish()
    }
}
impl Application {
    /// Own the actual WAL writer and sealed-only drain capability for this stream.
    pub async fn open_stream(
        &self,
        r: Arc<Resolved>,
        reference: Authorized<OnlyInstrument>,
        store: &mut Storage<'_>,
        request: StreamRequest,
        wal: crate::persistence::market_data_wal::Wal,
    ) -> Result<ProductStream> {
        let StreamRequest {
            stream_id,
            semantic: target,
            resume_after_sequence: resume,
            resume_plan_fingerprint,
            clock_ns,
            deadline,
            segment_id,
            capture_id,
            created_at,
        } = request;
        let resume_plan = resume_plan_fingerprint.as_deref();
        if !crate::application::command::uuid4(&stream_id) {
            return Err(Error::Invalid);
        }
        let (instrument, session) = reference.for_resource(&r, Permission::ClosedHistory)?;
        let permit = Arc::new(
            Arc::clone(&self.stream_slots)
                .try_acquire_owned()
                .map_err(|_| Error::Busy)?,
        );
        session.require_selection(&r.selection, Permission::RealtimePreview)?;
        let id = instrument.specification().instrument_id().to_string();
        let p = queries::plan(&r, &id, &target)?;
        if resume.is_some() != resume_plan.is_some()
            || resume_plan.is_some_and(|fp| fp != p.fingerprint())
        {
            return Err(Error::Invalid);
        }
        let provider_plan = if p.recipe().is_native() {
            p.clone()
        } else {
            queries::plan(&r, &id, &queries::semantic(1)?)?
        };
        let mut executor = None;
        let mut cursor = resume;
        if !p.recipe().is_native() {
            let edge = OnlyConstructionEdge::new(
                OnlyConstructionInput::Bar(queries::bar_type(&id, &queries::semantic(1)?)?),
                queries::bar_type(&id, &target)?,
                p.recipe().clone(),
            )
            .map_err(|_| Error::Invalid)?;
            let mut owner = OnlyTimeBarExecutor::new(edge, Arc::new(r.resource.calendar().clone()))
                .map_err(|_| Error::Invalid)?;
            let window: i64 = target
                .stride_minutes()
                .map_err(|_| Error::Invalid)?
                .to_string()
                .parse::<i64>()
                .map_err(|_| Error::Invalid)?
                .checked_mul(60_000_000_000)
                .ok_or(Error::Invalid)?;
            let end = if let Some(cursor) = resume {
                cursor
                    .checked_add(1)
                    .and_then(|n| n.checked_mul(60_000_000_000))
                    .filter(|n| *n <= clock_ns)
                    .ok_or(Error::Invalid)?
            } else {
                clock_ns.div_euclid(60_000_000_000) * 60_000_000_000
            };
            let day = end.div_euclid(86_400_000_000_000) * 86_400_000_000_000;
            let start = day + (end - day).div_euclid(window) * window;
            if start < end {
                let family = queries::scope(&r, &id, start, end, &provider_plan)?;
                let verified = store
                    .read_range(&family, &queries::native_intervals(&family)?)
                    .await?;
                if verified.coverage_status != CoverageStatus::Complete {
                    return Err(Error::Source(SourceError::RefreshRequired));
                }
                for fact in verified.facts {
                    let bar = onlyalpha_domain::market::OnlyBar::from_record(
                        &fact["canonical_payload"]["payload"]["value"],
                    )
                    .map_err(|_| Error::Corrupt)?;
                    let sequence = fact["canonical_payload"]["source_sequence"]
                        .as_i64()
                        .ok_or(Error::Corrupt)?;
                    let init = OnlyTimestamp::from_datetime(*bar.ts_event());
                    owner
                        .process(&OnlyConstructionFact::Bar(Arc::new(bar)), &init)
                        .map_err(|_| Error::Corrupt)?;
                    if resume.is_none() {
                        cursor = Some(sequence);
                    }
                }
            }
            executor = Some(owner);
        }
        let provider_minutes = provider_plan
            .target()
            .stride_minutes()
            .map_err(|_| Error::Invalid)?
            .to_string()
            .parse::<u16>()
            .map_err(|_| Error::Invalid)?;
        let stride = i64::from(provider_minutes) * 60_000_000_000;
        let latest = clock_ns.div_euclid(stride) - 1;
        if cursor.is_some_and(|c| c > latest || c < 0) {
            return Err(Error::Invalid);
        }
        if cursor.is_some_and(|c| latest - c > i64::from(r.resource.resume_max_bars())) {
            return Err(Error::Source(SourceError::RefreshRequired));
        }
        let request = HistoryRequest {
            instrument,
            minutes: provider_minutes,
            start_ms: latest * stride / 1_000_000,
            end_ms: (latest + 1) * stride / 1_000_000,
        };
        let mut upstream = r
            .resource
            .stream(request, cursor, budget(deadline)?)
            .await?;
        session.require_selection(&r.selection, Permission::RealtimePreview)?;
        let recorder_scope = queries::scope(
            &r,
            &id,
            latest * stride,
            (latest + 1) * stride,
            &provider_plan,
        )?;
        let sealed = wal.sealed_handle().map_err(|_| Error::Unavailable)?;
        let recorder = WalRecorder::owned(
            wal,
            &r,
            session.clone(),
            recorder_scope,
            &segment_id,
            &capture_id,
            &created_at,
        )?;
        let (sender, receiver) = tokio::sync::mpsc::channel(256);
        let state = Arc::new(State {
            cancel: AtomicBool::new(false),
            preview_generation: AtomicU64::new(0),
            wake: tokio::sync::Notify::new(),
            preview: Mutex::new(None),
            loss: Mutex::new(None),
            closed: AtomicBool::new(false),
        });
        let worker_state = Arc::clone(&state);
        let worker_r = Arc::clone(&r);
        let worker_session = session.clone();
        let fingerprint = p.fingerprint();
        sender.try_send(json!({"schema_version":2,"event":"SUBSCRIBED","stream_id":stream_id,"source_id":r.identity().source_id,"instrument_id":id,"resolution_mode":if p.recipe().is_native(){"PROVIDER_NATIVE"}else{"DERIVED"},"resolution_plan_fingerprint":fingerprint,"cursor_bar_stride_minutes":provider_minutes})).map_err(|_|Error::Unavailable)?;
        let retained_stream_id = stream_id.clone();
        let retained_plan_fingerprint = fingerprint.clone();
        let worker_permit = Arc::clone(&permit);
        let worker = tokio::spawn(async move {
            let _permit = worker_permit;
            let mut recorder = recorder;
            let mut last_preview = None;
            let mut ready = false;
            let outcome=async {
                loop {
                    if worker_state.cancel.load(Ordering::Acquire) { break; }
                    worker_session.require_selection(&worker_r.selection,Permission::RealtimePreview)?;
                    let event=tokio::select! {
                        _=worker_session.withdrawn()=>return Err(Error::Forbidden),
                        _=worker_state.wake.notified()=>{if worker_state.cancel.load(Ordering::Acquire){break;}continue;},
                        event=upstream.next(&mut recorder)=>event?,
                    };
                    worker_session.require_selection(&worker_r.selection,Permission::RealtimePreview)?;
                    let reliable=match event {
                        StreamEvent::Recovering=>{
                            ready=false;
                            last_preview=None;
                            worker_state.clear_preview()?;
                            Some(json!({"schema_version":2,"event":"STATE","state":"RECOVERING"}))
                        },
                        StreamEvent::Ready=>{ready=true;Some(json!({"schema_version":2,"event":"STATE","state":"READY"}))},
                        StreamEvent::Lost(e)=>return Err(Error::Source(e)),
                        StreamEvent::Preview(bar,sequence,timing)=>{
                            let order=(sequence,timing.map(|t|t.provider_event_ns).unwrap_or(i64::MIN));
                            if ready && last_preview.is_none_or(|last|order>=last) {
                                let projected=if let Some(owner)=executor.as_ref(){owner.preview(&bar).map_err(|_|Error::Corrupt)?.map(|b|(*b).clone())}else{Some(bar)};
                                if let Some(bar)=projected {
                                    worker_state.preview(json!({"schema_version":2,"event":"BAR_PREVIEW","source_id":worker_r.identity().source_id,"instrument_id":id,"bar_semantic":target.to_record(),"bar":queries::bar_row(&bar)?,"timing":if executor.is_none(){timing_payload(&stream_id,timing)}else{Value::Null}}))?;
                                    last_preview=Some(order);
                                    worker_state.wake.notify_waiters();
                                }
                            }
                            None
                        },
                        StreamEvent::Closed(bar,sequence,timing)=>{
                            let native=executor.is_none();
                            let bars=if let Some(owner)=executor.as_mut(){
                                let init=OnlyTimestamp::from_datetime(*bar.ts_event());
                                let bars=owner.process(&OnlyConstructionFact::Bar(Arc::new(bar)),&init).map_err(|_|Error::Corrupt)?.into_iter().map(|b|(*b).clone()).collect();
                                sender.try_send(json!({"schema_version":2,"event":"BASE_CURSOR","sequence":sequence.to_string()})).map_err(|_|Error::Backpressure)?;
                                bars
                            }else{vec![bar]};
                            if last_preview.is_some_and(|(last,_)|last<=sequence) {
                                worker_state.clear_preview()?;
                                last_preview=None;
                            }
                            for bar in bars {
                                sender.try_send(json!({"schema_version":2,"event":"BAR_CLOSED","source_id":worker_r.identity().source_id,"instrument_id":id,"bar_semantic":target.to_record(),"bar":queries::bar_row(&bar)?,"sequence":sequence.to_string(),"timing":if native{timing_payload(&stream_id,timing)}else{Value::Null}})).map_err(|_|Error::Backpressure)?;
                            }
                            None
                        },
                    };
                    if let Some(event)=reliable {sender.try_send(event).map_err(|_|Error::Backpressure)?;}
                    tokio::task::yield_now().await;
                }
                Ok(())
            }.await;
            close_worker(&worker_state, outcome, upstream.as_mut(), &mut recorder).await
        });
        Ok(ProductStream {
            stream_id: retained_stream_id,
            plan_fingerprint: retained_plan_fingerprint,
            issued: 0,
            issued_preview_generation: 0,
            pending: None,
            sealed,
            segment_prefix: format!("{segment_id}-"),
            capture: format!("native:{}:{capture_id}", r.implementation),
            receiver,
            state,
            worker: Some(worker),
            session,
            resolved: r,
            error_delivered: false,
            failed_delivered: false,
            _permit: permit,
        })
    }
}
impl ProductStream {
    /// Join two real original owners by complete Source/context identity. Arc
    /// resource equality is an issuance detail, not a canonical Source identity.
    /// Borrow-free read handle for the same original retained occurrence. It
    /// owns no provider/writer and is invalidated by the same stream fences.
    pub fn preview_source(&self) -> PreviewSource {
        PreviewSource {
            state: Arc::clone(&self.state),
            resolved: Arc::clone(&self.resolved),
            session: self.session.clone(),
            stream_id: self.stream_id.clone(),
            plan_fingerprint: self.plan_fingerprint.clone(),
        }
    }
    pub fn retained_preview(
        &self,
        history: &Authorized<Value>,
        stream_id: &str,
    ) -> Result<Option<Authorized<Value>>> {
        self.preview_source().retained_preview(history, stream_id)
    }

    /// Host serially borrows its original business Client. Facts accepted before
    /// Source withdrawal must still be persisted; this never grants display access.
    pub async fn drain(&mut self, store: &mut Storage<'_>, at: &str) -> Result<usize> {
        let result = self.drain_sealed(store, at).await;
        if let Err(error) = result {
            self.state.clear_preview()?;
            *self.state.loss.lock().map_err(|_| Error::Unavailable)? = Some(error);
            self.state.cancel.store(true, Ordering::Release);
            self.state.wake.notify_waiters();
        }
        result
    }
    async fn drain_sealed(&mut self, store: &mut Storage<'_>, at: &str) -> Result<usize> {
        let mut ids = self
            .sealed
            .published_sealed()
            .map_err(|_| Error::Unavailable)?;
        ids.sort();
        let mut drained = 0;
        for id in ids
            .into_iter()
            .filter(|id| id.starts_with(&self.segment_prefix))
        {
            let segment = market_data::Segment::from_record(
                &self
                    .sealed
                    .load_segment(&id)
                    .map_err(|_| Error::Unavailable)?,
            )?;
            let metadata = segment.to_record();
            if metadata["capture_session_id"] != self.capture
                || metadata["integration_binding_fingerprint"]
                    != self.resolved.binding.fingerprint()
                || metadata["source_id"] != self.resolved.identity().source_id
            {
                return Err(Error::Conflict);
            }
            drain_market_capture(&mut self.sealed, store, &[id], at).await?;
            drained += 1;
        }
        Ok(drained)
    }
    fn issue(
        &mut self,
        payload: Value,
        preview: Option<PreviewFence>,
    ) -> Result<Option<PendingStreamEvent>> {
        self.issued = self.issued.checked_add(1).ok_or(Error::Unavailable)?;
        self.pending = Some(self.issued);
        Ok(Some(PendingStreamEvent {
            payload,
            preview,
            state: Arc::clone(&self.state),
            ordinal: self.issued,
        }))
    }
    /// No payload is available until the actual Host storage release succeeds.
    /// Only one original delivery can be outstanding, so order cannot be changed.
    pub async fn release(
        &mut self,
        event: PendingStreamEvent,
        store: &mut Storage<'_>,
        at: &str,
    ) -> Result<Authorized<Value>> {
        if !Arc::ptr_eq(&event.state, &self.state) || self.pending != Some(event.ordinal) {
            return Err(Error::Conflict);
        }
        self.pending = None;
        self.session
            .require_selection(&self.resolved.selection, Permission::RealtimePreview)?;
        let market = matches!(
            event.payload["event"].as_str(),
            Some("BAR_CLOSED" | "BAR_PREVIEW" | "BASE_CURSOR")
        ) || event.payload["state"] == "READY";
        if market {
            self.drain(store, at).await?;
        }
        let mut authorized = Authorized::new(
            event.payload,
            &self.session,
            &self.resolved,
            Permission::RealtimePreview,
        )?;
        if market {
            let fence = StreamFence {
                state: Arc::clone(&self.state),
            };
            fence.check()?;
            authorized = authorized.with_stream(fence);
        }
        if let Some(preview) = event.preview {
            preview.check()?;
            authorized = authorized.with_preview(preview);
        }
        Ok(authorized)
    }
    pub async fn next(&mut self) -> Result<Option<PendingStreamEvent>> {
        if self.pending.is_some() {
            return Err(Error::Busy);
        }
        loop {
            self.session
                .require_selection(&self.resolved.selection, Permission::RealtimePreview)?;
            let loss = *self.state.loss.lock().map_err(|_| Error::Unavailable)?;
            if let Some(error) = loss {
                while self.receiver.try_recv().is_ok() {}
                return match terminal_event(
                    error,
                    &mut self.failed_delivered,
                    &mut self.error_delivered,
                ) {
                    Some(event) => self.issue(event, None),
                    None => Ok(None),
                };
            }

            if let Ok(event) = self.receiver.try_recv() {
                return self.issue(event, None);
            }
            let preview = self
                .state
                .preview
                .lock()
                .map_err(|_| Error::Unavailable)?
                .as_ref()
                .filter(|(_, generation)| *generation != self.issued_preview_generation)
                .cloned();
            if let Some((event, generation)) = preview {
                self.issued_preview_generation = generation;
                return self.issue(
                    event,
                    Some(PreviewFence {
                        state: Arc::clone(&self.state),
                        generation,
                    }),
                );
            }
            if self.state.closed.load(Ordering::Acquire) {
                return Ok(None);
            }
            // Register wakeup before examining work again to avoid lost preview/shutdown
            // notifications. Reliable messages remain in the actual bounded receiver.
            let wake = Arc::clone(&self.state);
            let notified = wake.wake.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            if self
                .state
                .preview
                .lock()
                .map_err(|_| Error::Unavailable)?
                .as_ref()
                .is_some_and(|(_, generation)| *generation != self.issued_preview_generation)
                || self.state.closed.load(Ordering::Acquire)
            {
                continue;
            }
            tokio::select! {_ = self.session.withdrawn()=>return Err(Error::Forbidden),event=self.receiver.recv()=>{if let Some(event)=event{return self.issue(event,None)}},_=notified=>{}}
        }
    }
    pub async fn close(&mut self) -> Result<()> {
        self.pending = None;
        self.state.cancel.store(true, Ordering::Release);
        self.state.wake.notify_waiters();
        let preview = self.state.clear_preview();
        self.receiver.close();
        finish_close(preview, &mut self.worker).await
    }
}
// Never return a state-cleanup failure before attempting both original resource
// cleanups. An expected withdrawal cannot hide any failed cleanup operation.
async fn close_worker(
    state: &State,
    outcome: Result<()>,
    upstream: &mut dyn Stream,
    recorder: &mut dyn Recorder,
) -> Result<()> {
    if let Err(error) = outcome {
        eprintln!("MARKET_DATA_STREAM_FAILED {error}");
    }
    let invalidated = match outcome {
        Err(error) => state.retain_loss(error),
        Ok(()) => Ok(()),
    };
    let closed = upstream.close().await;
    let recorded = recorder.finish();
    let cleanup = closed
        .map_err(Error::from)
        .and(recorded.map_err(Error::from))
        .and(invalidated);
    let failure = cleanup.and(outcome);
    let retained = match failure {
        Err(error) => state.retain_loss(error),
        Ok(()) => Ok(()),
    };
    state.closed.store(true, Ordering::Release);
    state.wake.notify_waiters();
    retained.and(cleanup)
}
// A terminal provider failure remains visible on the original stream. It does
// not restart consumption and is independent of successful resource cleanup.
fn terminal_event(error: Error, failed: &mut bool, delivered: &mut bool) -> Option<Value> {
    if !*failed {
        *failed = true;
        Some(json!({"schema_version":2,"event":"STATE","state":"FAILED"}))
    } else if !*delivered {
        *delivered = true;
        Some(json!({"schema_version":2,"event":"ERROR","code":error.code()}))
    } else {
        None
    }
}
// Retain the real handle in ProductStream across await: cancellation still
// aborts it through Drop. Preview cleanup failure never skips the actual join.
async fn finish_close(
    preview: Result<()>,
    worker: &mut Option<tokio::task::JoinHandle<Result<()>>>,
) -> Result<()> {
    let joined = match worker.as_mut() {
        Some(task) => task
            .await
            .map_err(|_| Error::Unavailable)
            .and_then(|result| result),
        None => Ok(()),
    };
    worker.take();
    preview.and(joined)
}
#[cfg(test)]
mod close_join_tests {
    use super::*;
    use std::{future::Future, task::Poll};
    #[tokio::test(flavor = "current_thread")]
    async fn superseded_preview_is_distinct_from_a_stopped_original_stream() {
        let state = Arc::new(State {
            cancel: AtomicBool::new(false),
            preview_generation: AtomicU64::new(0),
            wake: tokio::sync::Notify::new(),
            preview: Mutex::new(None),
            loss: Mutex::new(None),
            closed: AtomicBool::new(false),
        });
        state.preview(json!({"preview": "A"})).unwrap();
        let original = PreviewFence {
            state: Arc::clone(&state),
            generation: state.preview_generation.load(Ordering::Acquire),
        };
        let (issued, admitted) = tokio::sync::oneshot::channel();
        let (release, proceed) = tokio::sync::oneshot::channel();
        let pending = tokio::spawn(async move {
            original.check().unwrap();
            issued.send(()).unwrap();
            proceed.await.unwrap();
            original.check()
        });
        admitted.await.unwrap();
        state.preview(json!({"preview": "B"})).unwrap();
        release.send(()).unwrap();
        assert_eq!(
            pending.await.unwrap().unwrap_err().code(),
            "MARKET_DATA_PREVIEW_SUPERSEDED"
        );
        let current = PreviewFence {
            state: Arc::clone(&state),
            generation: state.preview_generation.load(Ordering::Acquire),
        };
        current.check().unwrap();
        assert_eq!(
            state.preview.lock().unwrap().as_ref().unwrap().0,
            json!({"preview": "B"})
        );
        // A real stream failure must dominate an obsolete preview generation.
        let obsolete = PreviewFence {
            state: Arc::clone(&state),
            generation: 0,
        };
        state.cancel.store(true, Ordering::Release);
        assert_eq!(obsolete.check(), Err(Error::Source(SourceError::Stopped)));
        state.cancel.store(false, Ordering::Release);
        state.closed.store(true, Ordering::Release);
        assert_eq!(obsolete.check(), Err(Error::Source(SourceError::Stopped)));
        state.closed.store(false, Ordering::Release);
        *state.loss.lock().unwrap() = Some(Error::Source(SourceError::Evidence));
        assert_eq!(obsolete.check(), Err(Error::Source(SourceError::Stopped)));
    }
    #[test]
    fn terminal_timeout_is_reported_then_the_original_stream_ends() {
        let mut failed = false;
        let mut delivered = false;
        let error = Error::Source(SourceError::Timeout);
        assert_eq!(
            terminal_event(error, &mut failed, &mut delivered),
            Some(json!({"schema_version":2,"event":"STATE","state":"FAILED"}))
        );
        assert_eq!(
            terminal_event(error, &mut failed, &mut delivered),
            Some(json!({"schema_version":2,"event":"ERROR","code":"MARKET_DATA_SOURCE_TIMEOUT"}))
        );
        assert_eq!(terminal_event(error, &mut failed, &mut delivered), None);
    }
    #[tokio::test(flavor = "current_thread")]
    async fn panicked_worker_cannot_certify_successful_cleanup() {
        let mut worker = Some(tokio::spawn(async { panic!("worker join fault") }));
        assert_eq!(
            finish_close(Ok(()), &mut worker).await,
            Err(Error::Unavailable)
        );
        assert!(worker.is_none());
    }
    struct ClosingSource {
        entered: Option<tokio::sync::oneshot::Sender<()>>,
        proceed: Option<tokio::sync::oneshot::Receiver<()>>,
        closed: Arc<AtomicBool>,
        result: std::result::Result<(), SourceError>,
    }
    impl Stream for ClosingSource {
        fn next<'a>(
            &'a mut self,
            _: &'a mut dyn Recorder,
        ) -> onlyalpha_integration_contract::source::FutureResult<'a, StreamEvent> {
            Box::pin(async { panic!("cleanup must not resume provider reads") })
        }
        fn close<'a>(&'a mut self) -> onlyalpha_integration_contract::source::FutureResult<'a, ()> {
            Box::pin(async move {
                self.entered.take().unwrap().send(()).unwrap();
                self.proceed.take().unwrap().await.unwrap();
                self.closed.store(true, Ordering::Release);
                self.result
            })
        }
    }
    struct ClosingRecorder {
        finished: Arc<AtomicBool>,
        result: std::result::Result<(), SourceError>,
    }
    impl Recorder for ClosingRecorder {
        fn record(
            &mut self,
            _: onlyalpha_integration_contract::source::Observation,
        ) -> std::result::Result<(), SourceError> {
            panic!("cleanup must not manufacture an observation")
        }
        fn finish(&mut self) -> std::result::Result<(), SourceError> {
            self.finished.store(true, Ordering::Release);
            self.result
        }
    }
    #[tokio::test(flavor = "current_thread")]
    async fn every_state_and_resource_cleanup_outcome_attempts_both_resources_and_joins() {
        for outcome in [
            Ok(()),
            Err(Error::Forbidden),
            Err(Error::Source(SourceError::Timeout)),
        ] {
            for state_failure in [false, true] {
                for close_failure in [
                    None,
                    Some(SourceError::Unavailable),
                    Some(SourceError::Timeout),
                ] {
                    for recorder_failure in [false, true] {
                        let state = Arc::new(State {
                            cancel: AtomicBool::new(true),
                            preview_generation: AtomicU64::new(if state_failure {
                                u64::MAX
                            } else {
                                0
                            }),
                            wake: tokio::sync::Notify::new(),
                            preview: Mutex::new(None),
                            loss: Mutex::new(None),
                            closed: AtomicBool::new(false),
                        });
                        let (entered, wait) = tokio::sync::oneshot::channel();
                        let (release, proceed) = tokio::sync::oneshot::channel();
                        let closed = Arc::new(AtomicBool::new(false));
                        let finished = Arc::new(AtomicBool::new(false));
                        let mut upstream = ClosingSource {
                            entered: Some(entered),
                            proceed: Some(proceed),
                            closed: Arc::clone(&closed),
                            result: close_failure.map_or(Ok(()), Err),
                        };
                        let mut recorder = ClosingRecorder {
                            finished: Arc::clone(&finished),
                            result: if recorder_failure {
                                Err(SourceError::Evidence)
                            } else {
                                Ok(())
                            },
                        };
                        let worker_state = Arc::clone(&state);
                        let worker = tokio::spawn(async move {
                            close_worker(&worker_state, outcome, &mut upstream, &mut recorder).await
                        });
                        wait.await.unwrap();
                        assert!(!closed.load(Ordering::Acquire));
                        assert!(!finished.load(Ordering::Acquire));
                        assert!(!worker.is_finished());
                        release.send(()).unwrap();
                        let result = worker.await.unwrap();
                        assert!(closed.load(Ordering::Acquire));
                        assert!(finished.load(Ordering::Acquire));
                        assert!(state.closed.load(Ordering::Acquire));
                        if state_failure
                            && (outcome.is_err() || close_failure.is_some() || recorder_failure)
                        {
                            assert_eq!(result, Err(Error::Unavailable));
                        } else if let Some(error) = close_failure {
                            assert_eq!(result, Err(Error::Source(error)));
                        } else if recorder_failure {
                            assert_eq!(result, Err(Error::Source(SourceError::Evidence)));
                        } else {
                            // Provider failure is retained for the original stream,
                            // but successful close/finish is a successful lifecycle.
                            assert_eq!(result, Ok(()));
                        }
                        let loss = *state.loss.lock().unwrap();
                        if !state_failure && close_failure.is_none() && !recorder_failure {
                            assert_eq!(loss, outcome.err());
                        }
                        if let Some(error) = close_failure {
                            assert_eq!(loss, Some(Error::Source(error)));
                        } else if recorder_failure {
                            assert_eq!(loss, Some(Error::Source(SourceError::Evidence)));
                        }
                    }
                }
            }
        }
    }
    #[tokio::test(flavor = "current_thread")]
    async fn preview_generation_failure_still_waits_for_actual_worker() {
        let state = State {
            cancel: AtomicBool::new(true),
            preview_generation: AtomicU64::new(u64::MAX),
            wake: tokio::sync::Notify::new(),
            preview: Mutex::new(None),
            loss: Mutex::new(None),
            closed: AtomicBool::new(false),
        };
        let (release, wait) = tokio::sync::oneshot::channel();
        let joined = Arc::new(AtomicBool::new(false));
        let observed = Arc::clone(&joined);
        let mut worker = Some(tokio::spawn(async move {
            wait.await.unwrap();
            observed.store(true, Ordering::Release);
            Ok(())
        }));
        let mut closing = Box::pin(finish_close(state.clear_preview(), &mut worker));
        let first = std::future::poll_fn(|cx| Poll::Ready(closing.as_mut().poll(cx))).await;
        assert!(first.is_pending());
        assert!(!joined.load(Ordering::Acquire));
        release.send(()).unwrap();
        assert!(matches!(closing.await, Err(Error::Unavailable)));
        assert!(joined.load(Ordering::Acquire));
        assert!(worker.is_none());
    }
    #[tokio::test(flavor = "current_thread")]
    async fn worker_failure_is_preserved_after_successful_preview_cleanup() {
        let mut worker = Some(tokio::spawn(async { Err(Error::Unavailable) }));
        assert!(matches!(
            finish_close(Ok(()), &mut worker).await,
            Err(Error::Unavailable)
        ));
        assert!(worker.is_none());
    }
}
impl Drop for ProductStream {
    fn drop(&mut self) {
        self.state.cancel.store(true, Ordering::Release);
        self.state.wake.notify_waiters();
        if let Some(worker) = self.worker.take() {
            worker.abort();
        }
    }
}

/// Persist exact published sealed occurrences during normal drain or startup.
/// The Host owns the admitted root and original business Client; no Source grant
/// is required to preserve accepted facts. Never substitute bare Storage::drain:
/// the old/new canonical identity proof precedes publication in both lifecycles.
pub async fn drain_market_capture(
    wal: &mut crate::persistence::market_data_wal::SealedWal,
    store: &mut Storage<'_>,
    ids: &[String],
    at: &str,
) -> Result<usize> {
    drain_capture(wal, store, ids, at, "REALTIME_STREAM").await
}
/// Original historical capture retains REST_BACKFILL provenance through startup.
pub async fn drain_historical_capture(
    wal: &mut crate::persistence::market_data_wal::SealedWal,
    store: &mut market_data::Storage<'_>,
    ids: &[String],
    at: &str,
) -> Result<usize> {
    drain_capture(wal, store, ids, at, "REST_BACKFILL").await
}
async fn drain_capture(
    wal: &mut crate::persistence::market_data_wal::SealedWal,
    store: &mut market_data::Storage<'_>,
    ids: &[String],
    at: &str,
    reason: &str,
) -> Result<usize> {
    if ids.is_empty() {
        return Ok(0);
    }
    let mut ids = ids.to_vec();
    ids.sort();
    if ids.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(Error::Invalid);
    }
    let mut drained = 0;
    for id in ids {
        let segment = market_data::Segment::from_record(
            &wal.load_segment(&id).map_err(|_| Error::Unavailable)?,
        )?;
        let metadata = segment.to_record();
        if metadata["capture_mode"] != reason {
            return Err(Error::Corrupt);
        }
        let scope = if metadata["canonical_count"].as_u64().ok_or(Error::Corrupt)? == 0 {
            None
        } else {
            Some(segment.recovery_scope()?)
        };
        if let Some(scope) = &scope {
            let prior = store
                .read_range(scope, &queries::native_intervals(scope)?)
                .await?;
            if prior.coverage_status == CoverageStatus::Unprovable {
                return Err(Error::Store(market_data::Error::Unprovable));
            }
            let mut facts = prior.facts;
            if prior.coverage_status == CoverageStatus::Incomplete {
                for evidence in prior.evidence {
                    let (revision, original) = store
                        .read_exact(evidence["revision_id"].as_str().ok_or(Error::Corrupt)?)
                        .await?;
                    let record = revision.manifest().to_record();
                    let selected = market_data::Scope::from_record(&record["scope"])?;
                    if !selected.family_matches(scope) {
                        return Err(Error::Store(market_data::Error::Unprovable));
                    }
                    for fact in original {
                        let bar = onlyalpha_domain::market::OnlyBar::from_record(
                            &fact["canonical_payload"]["payload"]["value"],
                        )
                        .map_err(|_| Error::Corrupt)?;
                        if ns(*bar.bar_start())? >= scope.start_ns()
                            && ns(*bar.bar_end())? <= scope.end_ns()
                        {
                            facts.push(fact);
                        }
                    }
                }
            }
            for bundle in wal.read_sealed(&id).map_err(|_| Error::Unavailable)? {
                facts.extend(
                    bundle["canonical_facts"]
                        .as_array()
                        .ok_or(Error::Corrupt)?
                        .iter()
                        .cloned(),
                );
            }
            // Compare complete canonical payload identity before any new Store
            // publication, including facts selected from earlier native builds.
            market_data::deduplicate_facts(&facts)?;
        }
        store
            .drain(
                wal,
                &[id],
                scope.as_ref(),
                market_data::RevisionPublication {
                    parent: None,
                    reason,
                    at,
                },
                |_| true,
            )
            .await?;
        drained += 1;
    }
    Ok(drained)
}

pub(super) fn timing_payload(
    stream_id: &str,
    timing: Option<onlyalpha_integration_contract::source::IngressTiming>,
) -> Value {
    timing.map(|t|json!({"stream_id":stream_id,"provider_event_ns":t.provider_event_ns.to_string(),"ingress_received_ns":t.ingress_received_ns.to_string()})).unwrap_or(Value::Null)
}

#[derive(Clone)]
pub struct PreviewSource {
    state: Arc<State>,
    resolved: Arc<Resolved>,
    session: Session,
    stream_id: String,
    plan_fingerprint: String,
}
impl PreviewSource {
    pub fn retained_preview(
        &self,
        history: &Authorized<Value>,
        stream_id: &str,
    ) -> Result<Option<Authorized<Value>>> {
        let (window, fence) = history.parts()?;
        fence.same_source(&self.resolved, &self.session)?;
        self.session
            .require_selection(&self.resolved.selection, Permission::RealtimePreview)?;
        if fence.permission() != Permission::ClosedHistory
            || stream_id != self.stream_id
            || window["resolution_mode"] != "PROVIDER_NATIVE"
            || window["resolution_plan_fingerprint"] != self.plan_fingerprint
        {
            return Err(Error::Selection);
        }
        let stream = StreamFence {
            state: Arc::clone(&self.state),
        };
        if stream.check().is_err() {
            return Ok(None);
        }
        let retained = self
            .state
            .preview
            .lock()
            .map_err(|_| Error::Unavailable)?
            .clone();
        let Some((value, generation)) = retained else {
            return Ok(None);
        };
        let bar = &value["bar"];
        let start = window["resolved_start_ns"]
            .as_str()
            .and_then(|v| v.parse::<i64>().ok())
            .ok_or(Error::Corrupt)?;
        let end = window["resolved_end_ns"]
            .as_str()
            .and_then(|v| v.parse::<i64>().ok())
            .ok_or(Error::Corrupt)?;
        let count = window["requested_bar_count"]
            .as_i64()
            .ok_or(Error::Corrupt)?;
        let bar_start = bar["bar_start_ns"]
            .as_str()
            .and_then(|v| v.parse::<i64>().ok())
            .ok_or(Error::Corrupt)?;
        let bar_end = bar["bar_end_ns"]
            .as_str()
            .and_then(|v| v.parse::<i64>().ok())
            .ok_or(Error::Corrupt)?;
        if count <= 0
            || value["instrument_id"] != window["instrument_id"]
            || value["bar_semantic"] != window["bar_semantic"]
            || value["source_id"] != window["source_selection"]["source_id"]
            || bar["closed"] != false
            || bar_start != end
            || bar_end.checked_sub(bar_start) != end.checked_sub(start).map(|n| n / count)
        {
            return Ok(None);
        }
        let preview = PreviewFence {
            state: Arc::clone(&self.state),
            generation,
        };
        preview.check()?;
        let payload = json!({"stream_id":self.stream_id,"revision_fingerprint":fp(&json!({"stream_id":self.stream_id,"generation":generation,"bar":bar}))?,"bar":bar});
        Ok(Some(
            Authorized::new(
                payload,
                &self.session,
                &self.resolved,
                Permission::RealtimePreview,
            )?
            .with_stream(stream)
            .with_preview(preview),
        ))
    }
}
