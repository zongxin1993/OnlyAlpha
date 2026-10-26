//! Volatile socket lifecycle. Reuses native parsing/admission; no Recorder or
//! durable callback can be supplied. The formal stream is intentionally separate.
use super::*;
pub(super) const MAX_RECOVERY_INPUTS: u16 = 120;
pub(super) struct TemporaryBars {
    pub(super) inner: Bars,
}
impl TemporaryBars {
    fn event(&self, bytes: &[u8], received: i64) -> Result<StreamEvent, SourceError> {
        let raw = spot_rest::decode_json(bytes)?;
        let (bar, sequence, event_ns) = ws_bar(
            &raw,
            &self.inner.request.instrument,
            self.inner.request.minutes,
        )?;
        let timing = Some(IngressTiming {
            provider_event_ns: event_ns,
            ingress_received_ns: received,
        });
        Ok(if *bar.is_closed() {
            StreamEvent::Closed(bar, sequence, timing)
        } else {
            StreamEvent::Preview(bar, sequence, timing)
        })
    }
    async fn buffer(
        &self,
        socket: &mut Socket,
        message: Message,
        buffer: &mut RecoveryBuffer,
        deadline: Instant,
    ) -> Result<(), SourceError> {
        let received = self.inner.source.clock.now_ns()?;
        let length = message.len();
        match message {
            Message::Text(text) => {
                buffer.events.push(self.event(text.as_bytes(), received)?);
                buffer.bytes = buffer.bytes.checked_add(length).ok_or(SourceError::Gap)?;
            }
            Message::Ping(payload) => {
                tokio::time::timeout_at(deadline.into(), socket.send(Message::Pong(payload)))
                    .await
                    .map_err(|_| SourceError::Timeout)?
                    .map_err(|_| SourceError::Unavailable)?;
            }
            Message::Pong(_) => {}
            Message::Binary(_) => return Err(SourceError::Invalid),
            _ => return Err(SourceError::Unavailable),
        }
        buffer.observed = buffer.observed.checked_add(1).ok_or(SourceError::Gap)?;
        if buffer.observed > self.inner.source.buffer_limit || buffer.bytes > 8 * 1024 * 1024 {
            return Err(SourceError::Gap);
        }
        tokio::task::yield_now().await;
        Ok(())
    }
    async fn recover(&mut self) -> Result<(), SourceError> {
        let started = Instant::now();
        let source = self.inner.source.clone();
        let mut request = self.inner.request.clone();
        let (_, stride) = spot_rest::native_interval(request.minutes)?;
        let last = (source.clock.now_ns()? / 1_000_000).div_euclid(stride) - 1;
        let first = self.inner.cursor.ok_or(SourceError::Invalid)?;
        if first > last {
            return Err(SourceError::Invalid);
        }
        if last - first > i64::from(source.resume_limit.min(MAX_RECOVERY_INPUTS)) {
            return Err(SourceError::RefreshRequired);
        }
        let deadline = recovery_deadline(&mut self.inner.bootstrap_deadline, source.timeout);
        // A caller may cancel next() to service a client control frame. Retain
        // this occurrence's original budget until recovery completes or stops.
        self.inner.bootstrap_deadline = Some(deadline);
        let symbol = request.instrument.specification().raw_symbol().value();
        let mut socket = source
            .connect(
                &format!(
                    "{}@kline_{}",
                    symbol.to_ascii_lowercase(),
                    spot_rest::native_interval(request.minutes)?.0
                ),
                deadline,
            )
            .await
            .map_err(|error| {
                if error == SourceError::Timeout {
                    eprintln!(
                        "TEMPORARY_STREAM_TIMEOUT stage=connect total_ms={}",
                        started.elapsed().as_millis()
                    );
                }
                error
            })?;
        let mut buffered = RecoveryBuffer::default();
        // Pin cutover to an actual frame from the connected Provider socket.
        // Sampling the local clock before connection can miss a close during
        // the handshake (and the two clocks need not agree exactly).
        let last = loop {
            if let Some(frontier) = buffered.events.iter().find_map(|event| match event {
                StreamEvent::Closed(_, sequence, _) => Some(Ok(*sequence)),
                StreamEvent::Preview(_, sequence, _) => {
                    Some(sequence.checked_sub(1).ok_or(SourceError::Invalid))
                }
                _ => None,
            }) {
                break frontier?;
            }
            let message = tokio::time::timeout_at(deadline.into(), socket.next())
                .await
                .map_err(|_| {
                    eprintln!(
                        "TEMPORARY_STREAM_TIMEOUT stage=first_frame total_ms={}",
                        started.elapsed().as_millis()
                    );
                    SourceError::Timeout
                })?
                .ok_or(SourceError::Unavailable)?
                .map_err(|_| SourceError::Unavailable)?;
            self.buffer(&mut socket, message, &mut buffered, deadline)
                .await?;
        };
        if last < first {
            return Err(SourceError::Invalid);
        }
        if last - first > i64::from(source.resume_limit.min(MAX_RECOVERY_INPUTS)) {
            return Err(SourceError::RefreshRequired);
        }
        request.start_ms = first * stride;
        request.end_ms = (last + 1) * stride;
        let baseline = {
            let history = source.temporary_history(&request, budget(deadline)?);
            tokio::pin!(history);
            loop {
                tokio::select! {
                    result=&mut history=>break result.map_err(|error| {
                        if error == SourceError::Timeout {
                            eprintln!(
                                "TEMPORARY_STREAM_TIMEOUT stage=history total_ms={}",
                                started.elapsed().as_millis()
                            );
                        }
                        error
                    })?,
                    message=socket.next()=>{
                        let message=message.ok_or(SourceError::Unavailable)?.map_err(|_|SourceError::Unavailable)?;
                        self.buffer(&mut socket,message,&mut buffered,deadline).await?;
                    }
                }
            }
        };
        while let Some(message) = socket.next().now_or_never() {
            self.buffer(
                &mut socket,
                message
                    .ok_or(SourceError::Unavailable)?
                    .map_err(|_| SourceError::Unavailable)?,
                &mut buffered,
                deadline,
            )
            .await?;
        }
        let actual = baseline
            .iter()
            .map(|bar| ns(*bar.bar_start()).map(|n| n / (stride * 1_000_000)))
            .collect::<Result<Vec<_>, _>>()?;
        if actual != (first..=last).collect::<Vec<_>>() {
            return Err(SourceError::Gap);
        }
        for (bar, sequence) in baseline.into_iter().zip(actual) {
            self.inner.admit(StreamEvent::Closed(bar, sequence, None))?;
        }
        for event in buffered.events {
            self.inner.admit(event)?;
            tokio::task::yield_now().await;
        }
        self.inner.socket = Some(socket);
        self.inner.recovering = false;
        self.inner.bootstrap_deadline = None;
        self.inner.delay = source.reconnect_initial;
        self.inner.pending.push_back(StreamEvent::Ready);
        Ok(())
    }
}
impl TemporaryStream for TemporaryBars {
    fn next<'a>(&'a mut self) -> FutureResult<'a, StreamEvent> {
        Box::pin(async move {
            loop {
                tokio::task::yield_now().await;
                if self.inner.stopped {
                    return Err(SourceError::Stopped);
                }
                if let Some(event) = self.inner.pending.pop_front() {
                    return Ok(event);
                }
                if self.inner.recovering {
                    if let Err(error) = self.recover().await {
                        self.inner.stopped = true;
                        self.inner.socket = None;
                        self.inner.bootstrap_deadline = None;
                        return Ok(StreamEvent::Lost(error));
                    }
                    continue;
                }
                let message = match self.inner.socket.as_mut() {
                    Some(socket) => socket.next().await,
                    None => None,
                };
                match message {
                    Some(Ok(Message::Text(text))) => {
                        let received = self.inner.source.clock.now_ns()?;
                        match self
                            .event(text.as_bytes(), received)
                            .and_then(|event| self.inner.admit(event))
                        {
                            Ok(()) => {}
                            Err(error) => {
                                self.inner.stopped = true;
                                self.inner.socket = None;
                                return Ok(StreamEvent::Lost(error));
                            }
                        }
                    }
                    Some(Ok(Message::Binary(_))) => {
                        self.inner.stopped = true;
                        self.inner.socket = None;
                        return Ok(StreamEvent::Lost(SourceError::Invalid));
                    }
                    Some(Ok(Message::Ping(payload))) => {
                        let deadline = Instant::now() + self.inner.source.timeout;
                        if !matches!(
                            tokio::time::timeout_at(
                                deadline.into(),
                                self.inner
                                    .socket
                                    .as_mut()
                                    .ok_or(SourceError::Stopped)?
                                    .send(Message::Pong(payload))
                            )
                            .await,
                            Ok(Ok(()))
                        ) {
                            return Ok(self.inner.reconnect().await);
                        }
                    }
                    Some(Ok(Message::Pong(_))) => {}
                    _ => return Ok(self.inner.reconnect().await),
                }
            }
        })
    }
    fn close<'a>(&'a mut self) -> FutureResult<'a, ()> {
        Box::pin(async move {
            self.inner.bootstrap_deadline = None;
            Stream::close(&mut self.inner).await
        })
    }
}
