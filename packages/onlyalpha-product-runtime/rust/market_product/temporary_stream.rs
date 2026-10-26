//! Pull-owned volatile subscription. No durable writer or Storage capability.
use super::*;
use crate::source_access::{Permission, Session};
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use onlyalpha_integration_contract::source::{
    HistoryRequest, IngressTiming, StreamEvent, TemporaryStream,
};
use onlyalpha_market_data_construction::*;
use serde_json::json;
use std::{collections::VecDeque, sync::Arc, time::Instant};
pub struct TemporaryStreamRequest {
    pub stream_id: String,
    pub page_id: String,
    pub window: WindowRequest,
    pub expected_window_fingerprint: String,
    pub deadline: Instant,
}
pub struct TemporaryProductStream {
    stream_id: String,
    upstream: Box<dyn TemporaryStream>,
    resolved: Arc<Resolved>,
    session: Session,
    entry: Arc<tokio::sync::Mutex<super::temporary::TemporaryEntry>>,
    epoch: super::temporary_state::TemporaryFence,
    active: Arc<super::temporary_state::TemporarySubscription>,
    book: Arc<std::sync::Mutex<super::temporary::TemporaryBook>>,
    page: String,
    pending: VecDeque<Value>,
    executor: Option<OnlyTimeBarExecutor>,
    target: onlyalpha_domain::market::OnlyBarSemantic,
    checkpoint: OnlyBar,
    ready: bool,
    incoming: Option<StreamEvent>,
    incoming_deadline: Option<Instant>,
    closed: bool,
    _permit: tokio::sync::OwnedSemaphorePermit,
}
impl Application {
    pub async fn open_temporary_stream(
        &self,
        r: Arc<Resolved>,
        session: &Session,
        request: TemporaryStreamRequest,
    ) -> Result<TemporaryProductStream> {
        if !crate::command::uuid4(&request.stream_id) {
            return Err(Error::Invalid);
        }
        session.require_selection(&r.selection, Permission::RealtimePreview)?;
        let input = self
            .cached_temporary_input(
                &r,
                session,
                &request.window,
                &request.page_id,
                &request.expected_window_fingerprint,
                request.deadline,
            )
            .await?;
        input.window.parts()?;
        let permit = Arc::clone(&self.stream_slots)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let target = request.window.semantic;
        let executor = if input.plan.recipe().is_native() {
            None
        } else {
            let edge = OnlyConstructionEdge::new(
                OnlyConstructionInput::Bar(queries::bar_type(
                    &request.window.instrument_id,
                    &queries::semantic(1)?,
                )?),
                queries::bar_type(&request.window.instrument_id, &target)?,
                input.plan.recipe().clone(),
            )
            .map_err(|_| Error::Invalid)?;
            Some(
                OnlyTimeBarExecutor::new(edge, Arc::new(r.resource.calendar().clone()))
                    .map_err(|_| Error::Invalid)?,
            )
        };
        let minutes = input
            .checkpoint
            .bar_type()
            .semantic()
            .stride_minutes()
            .map_err(|_| Error::Invalid)?
            .to_string()
            .parse::<u16>()
            .map_err(|_| Error::Invalid)?;
        let provider = HistoryRequest {
            instrument: input.instrument,
            minutes,
            start_ms: ns(*input.checkpoint.bar_start())? / 1_000_000,
            end_ms: ns(*input.checkpoint.bar_end())? / 1_000_000,
        };
        let epoch = tokio::time::timeout_at(request.deadline.into(), input.entry.lock())
            .await
            .map_err(|_| Error::Source(SourceError::Timeout))?
            .state
            .fence();
        epoch.check()?;
        let opened = tokio::time::timeout_at(
            request.deadline.into(),
            r.resource.temporary_stream(
                provider,
                input.checkpoint.clone(),
                budget(request.deadline)?,
            ),
        )
        .await
        .map_err(|_| Error::Source(SourceError::Timeout))?;
        let mut upstream = match opened {
            Ok(stream) => stream,
            Err(error) => {
                if matches!(
                    error,
                    SourceError::Gap | SourceError::RefreshRequired | SourceError::Conflict
                ) {
                    epoch.invalidate_context()?;
                }
                return Err(error.into());
            }
        };
        if let Err(error) = input.window.parts().and_then(|_| {
            session
                .require_selection(&r.selection, Permission::RealtimePreview)
                .map_err(Into::into)
        }) {
            upstream.close().await?;
            return Err(error);
        }
        let active = Arc::new(super::temporary_state::TemporarySubscription::default());
        let subscribed = self
            .temporary
            .lock()
            .map_err(|_| Error::Unavailable)?
            .subscribe(&request.page_id, &input.entry, &active);
        if let Err(error) = subscribed {
            upstream.close().await?;
            return Err(error);
        }
        let subscribed = json!({"schema_version":2,"event":"SUBSCRIBED","source_kind":"TEMPORARY_MARKET_DATA",
            "authority":"DISPLAY_ONLY","publication_status":"NOT_A_RESEARCH_RESULT","stream_id":request.stream_id,
            "source_id":r.identity().source_id,"instrument_id":request.window.instrument_id,
            "resolution_mode":if executor.is_none(){"PROVIDER_NATIVE"}else{"DERIVED"},
            "resolution_plan_fingerprint":input.plan.fingerprint(),"cursor_bar_stride_minutes":minutes});
        Ok(TemporaryProductStream {
            stream_id: request.stream_id,
            upstream,
            resolved: r,
            session: session.clone(),
            entry: input.entry,
            epoch,
            active,
            book: Arc::clone(&self.temporary),
            page: request.page_id,
            pending: VecDeque::from([subscribed]),
            executor,
            target,
            checkpoint: input.checkpoint,
            ready: false,
            incoming: None,
            incoming_deadline: None,
            closed: false,
            _permit: permit,
        })
    }
}
fn same_bar(a: &OnlyBar, b: &OnlyBar) -> bool {
    let content = |bar: &OnlyBar| {
        let mut value = bar.to_record();
        value.as_object_mut().expect("bar record").remove("ts_init");
        value
    };
    content(a) == content(b)
}
impl TemporaryProductStream {
    fn authorize(&self, value: Value) -> Result<Authorized<Value>> {
        let fence = self
            .epoch
            .clone()
            .for_subscription(Arc::clone(&self.active));
        fence.check()?;
        Ok(Authorized::new(
            value,
            &self.session,
            &self.resolved,
            Permission::RealtimePreview,
        )?
        .with_temporary(fence))
    }
    fn price(
        &self,
        event: &str,
        bar: &OnlyBar,
        sequence: i64,
        timing: Option<IngressTiming>,
    ) -> Result<Value> {
        let mut value = json!({"schema_version":2,"event":event,"source_id":self.resolved.identity().source_id,
            "instrument_id":bar.instrument_id().to_string(),"bar_semantic":self.target.to_record(),
            "bar":queries::bar_row(bar)?,"timing":if self.executor.is_none(){super::stream::timing_payload(&self.stream_id,timing)}else{Value::Null}});
        if event == "BAR_CLOSED" {
            value["sequence"] = json!(sequence.to_string());
        }
        Ok(value)
    }
    async fn advance(&mut self) -> Result<()> {
        self.session
            .require_selection(&self.resolved.selection, Permission::RealtimePreview)?;
        self.epoch.check()?;
        if self.incoming.is_none() {
            let event = tokio::select! {
                _=self.session.withdrawn()=>return Err(Error::Forbidden),
                _=self.epoch.invalidated()=>return Err(Error::Conflict),
                _=self.active.closed()=>return Err(Error::Source(SourceError::Stopped)),
                event=self.upstream.next()=>match event{Ok(event)=>event,Err(error)=>StreamEvent::Lost(error)},
            };
            self.incoming = Some(event);
        }
        // A Provider close may arrive before the local clock reaches its end.
        // Retain the exact event, publish nothing early, and keep one 10s budget
        // across cancellation. No history invalidation or clock tolerance applies.
        if let Some(StreamEvent::Closed(bar, _, _)) = &self.incoming {
            let end = ns(*bar.bar_end())?;
            loop {
                let now = self.resolved.clock.now_ns()?;
                if end <= now {
                    break;
                }
                let deadline = *self
                    .incoming_deadline
                    .get_or_insert_with(|| Instant::now() + std::time::Duration::from_secs(10));
                let delay = std::time::Duration::from_nanos(
                    u64::try_from(i128::from(end) - i128::from(now)).map_err(|_| Error::Invalid)?,
                );
                let left = deadline
                    .checked_duration_since(Instant::now())
                    .ok_or(Error::Source(SourceError::Timeout))?;
                if delay > left {
                    return Err(Error::Source(SourceError::Timeout));
                }
                tokio::select! {
                    _=self.session.withdrawn()=>return Err(Error::Forbidden),
                    _=self.epoch.invalidated()=>return Err(Error::Conflict),
                    _=self.active.closed()=>return Err(Error::Source(SourceError::Stopped)),
                    _=tokio::time::sleep(delay)=>{},
                }
            }
        }
        // Preserve a consumed Source event across cancellation while another
        // page owns the cache lock. Construction and merge below contain no await.
        let owned = Arc::clone(&self.entry);
        let mut entry = owned.lock().await;
        let event = self.incoming.take().ok_or(Error::Corrupt)?;
        self.incoming_deadline = None;
        self.session
            .require_selection(&self.resolved.selection, Permission::RealtimePreview)?;
        self.epoch.check()?;
        let outcome = (|| -> Result<()> {
            match event {
                StreamEvent::Recovering => {
                    self.ready = false;
                    self.pending.push_back(
                        json!({"schema_version":2,"event":"STATE","state":"RECOVERING"}),
                    );
                }
                StreamEvent::Ready => {
                    entry.window.live_frontier = Some(ns(*self.checkpoint.bar_end())?);
                    self.ready = true;
                    self.pending
                        .push_back(json!({"schema_version":2,"event":"STATE","state":"READY"}));
                }
                StreamEvent::Lost(error) => return Err(Error::Source(error)),
                StreamEvent::Preview(bar, sequence, timing) => {
                    if *bar.is_closed()
                        || bar.instrument_id() != self.checkpoint.instrument_id()
                        || bar.bar_type() != self.checkpoint.bar_type()
                        || bar.bar_start() != self.checkpoint.bar_end()
                    {
                        return Err(Error::Corrupt);
                    }
                    if self.ready {
                        let preview = if let Some(owner) = &self.executor {
                            owner
                                .preview(&bar)
                                .map_err(|_| Error::Corrupt)?
                                .map(|b| (*b).clone())
                        } else {
                            Some(bar)
                        };
                        if let Some(bar) = preview {
                            self.pending.push_back(self.price(
                                "BAR_PREVIEW",
                                &bar,
                                sequence,
                                timing,
                            )?);
                        }
                    }
                }
                StreamEvent::Closed(bar, sequence, timing) => {
                    if !*bar.is_closed()
                        || bar.instrument_id() != self.checkpoint.instrument_id()
                        || bar.bar_type() != self.checkpoint.bar_type()
                    {
                        return Err(Error::Corrupt);
                    }
                    if ns(*bar.bar_end())? > self.resolved.clock.now_ns()? {
                        return Err(Error::Source(SourceError::Timeout));
                    }
                    if bar.bar_start() == self.checkpoint.bar_start() {
                        if !same_bar(&bar, &self.checkpoint) {
                            return Err(Error::Conflict);
                        }
                        return Ok(());
                    }
                    if bar.bar_start() != self.checkpoint.bar_end() {
                        return Err(Error::Source(SourceError::RefreshRequired));
                    }
                    let outputs = if let Some(owner) = self.executor.as_mut() {
                        let init = OnlyTimestamp::from_datetime(*bar.ts_event());
                        owner
                            .process(&OnlyConstructionFact::Bar(Arc::new(bar.clone())), &init)
                            .map_err(|_| Error::Corrupt)?
                            .into_iter()
                            .map(|b| (*b).clone())
                            .collect::<Vec<_>>()
                    } else {
                        vec![bar.clone()]
                    };
                    self.epoch.check()?;
                    entry.window.merge(
                        outputs.clone(),
                        &bar.instrument_id().to_string(),
                        &self.target,
                        self.resolved.clock.now_ns()?,
                        ns(*bar.bar_end())?,
                    )?;
                    entry.window.live_frontier = Some(ns(*bar.bar_end())?);
                    if self.executor.is_some() {
                        for output in &outputs {
                            entry
                                .checkpoints
                                .insert(ns(*output.bar_end())?, bar.clone());
                        }
                    }
                    let retained = entry
                        .window
                        .bars
                        .keys()
                        .map(|(_, end)| *end)
                        .collect::<std::collections::BTreeSet<_>>();
                    entry.checkpoints.retain(|end, _| retained.contains(end));
                    self.checkpoint = bar;
                    for output in outputs {
                        self.pending.push_back(self.price(
                            "BAR_CLOSED",
                            &output,
                            sequence,
                            timing,
                        )?);
                    }
                }
            }
            Ok(())
        })();
        if matches!(
            outcome,
            Err(Error::Corrupt
                | Error::Conflict
                | Error::Source(
                    SourceError::Gap | SourceError::RefreshRequired | SourceError::Conflict
                ))
        ) {
            self.epoch.invalidate_context()?;
        }
        outcome
    }
    pub async fn next(&mut self) -> Result<Option<Authorized<Value>>> {
        if !self.active.is_active() {
            return Ok(None);
        }
        loop {
            if let Some(event) = self.pending.pop_front() {
                return self.authorize(event).map(Some);
            }
            if let Err(error) = self.advance().await {
                self.close().await?;
                return Err(error);
            }
            tokio::task::yield_now().await;
        }
    }
    /// Cleanup deliberately does not require a still-valid Source grant.
    pub async fn close(&mut self) -> Result<()> {
        self.book
            .lock()
            .map_err(|_| Error::Unavailable)?
            .unsubscribe(&self.page, &self.active, Instant::now());
        self.pending.clear();
        self.incoming = None;
        self.incoming_deadline = None;
        if !self.closed {
            self.upstream.close().await?;
            self.closed = true;
        }
        Ok(())
    }
}
impl Drop for TemporaryProductStream {
    fn drop(&mut self) {
        if let Ok(mut book) = self.book.lock() {
            book.unsubscribe(&self.page, &self.active, Instant::now());
        } else {
            self.active.cancel();
        }
    }
}
