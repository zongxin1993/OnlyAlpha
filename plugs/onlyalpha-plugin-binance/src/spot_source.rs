//! Installed native Spot Source. Protocol, interval cursors and reconnect remain
//! plugin-owned. No Product stores, grants, Command or Trading authority.
use crate::{
    spot_normalize,
    spot_rest::{self, PublicRest},
};
use futures_util::{FutureExt, SinkExt, StreamExt};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::OnlyTradingCalendar,
    instrument::OnlyInstrument,
    market::{OnlyBar, OnlyBarSemantic},
    time::OnlyTimestamp,
};
use onlyalpha_integration_contract::{Descriptor, source::*};
use onlyalpha_market_data_construction::OnlyConstructionCapability;
use rustls::pki_types::pem::PemObject;
use serde_json::{Value, json, value::RawValue};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, VecDeque},
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::net::TcpStream;
use tokio_tungstenite::{
    Connector, MaybeTlsStream, WebSocketStream,
    tungstenite::{Message, protocol::WebSocketConfig},
};
#[path = "spot_temporary.rs"]
mod temporary;
use temporary::TemporaryBars;
fn end(budget: Budget) -> Instant {
    Instant::now() + Duration::from_millis(budget.millis())
}
fn budget(end: Instant) -> Result<Budget, SourceError> {
    let ms = end
        .checked_duration_since(Instant::now())
        .ok_or(SourceError::Timeout)?
        .as_millis();
    Budget::from_millis(
        u64::try_from(ms)
            .map_err(|_| SourceError::Timeout)?
            .min(60000),
    )
    .map_err(|_| SourceError::Timeout)
}
const WORK: usize = 64 * 1024 * 1024;
fn hash(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
fn fp(v: &Value) -> Result<String, SourceError> {
    Ok(hash(
        onlyalpha_metadata_json::canonical_json(&v.to_string(), WORK)
            .map_err(|_| SourceError::Invalid)?
            .as_bytes(),
    ))
}
impl From<spot_rest::Error> for SourceError {
    fn from(e: spot_rest::Error) -> Self {
        match e {
            spot_rest::Error::Deadline => Self::Timeout,
            spot_rest::Error::Evidence => Self::Evidence,
            spot_rest::Error::Configuration | spot_rest::Error::Range => Self::Invalid,
            _ => Self::Unavailable,
        }
    }
}
pub struct SpotFactory {
    descriptor: Descriptor,
    implementation: String,
}
impl SpotFactory {
    pub fn installed() -> Result<Self, SourceError> {
        let registration = crate::spot_authoring(WORK).map_err(|_| SourceError::Unavailable)?;
        let descriptor = Descriptor::from_json(registration.descriptor().document().get(), WORK)
            .map_err(|_| SourceError::Unavailable)?;
        // This identifies the implemented native contract, not executable bytes.
        // The Product Installed owner independently requires the Host's actual artifact.
        Ok(Self {
            descriptor,
            implementation: fp(
                &json!({"implementation":"onlyalpha.binance.spot.native","contract_version":1}),
            )?,
        })
    }
}
impl Factory for SpotFactory {
    fn descriptor(&self) -> &Descriptor {
        &self.descriptor
    }
    fn implementation_fingerprint(&self) -> &str {
        &self.implementation
    }
    fn validate_configuration(&self, configuration: &RawValue) -> Result<(), SourceError> {
        crate::spot_authoring(WORK)
            .and_then(|r| r.validate_public_configuration(configuration, WORK))
            .map_err(|_| SourceError::Invalid)
    }
    fn create(
        &self,
        configuration: &RawValue,
        trust: &Trust,
        clock: Arc<dyn Clock>,
    ) -> Result<Arc<dyn Resource>, SourceError> {
        Ok(Arc::new(Spot::new(configuration, trust, clock)?))
    }
}
#[derive(Clone)]
struct Spot {
    rest: PublicRest,
    identity: MarketIdentity,
    calendar: OnlyTradingCalendar,
    capabilities: Vec<OnlyConstructionCapability>,
    clock: Arc<dyn Clock>,
    tls: Arc<rustls::ClientConfig>,
    ws_base: String,
    timeout: Duration,
    ws_limit: usize,
    buffer_limit: usize,
    resume_limit: u16,
    reconnect_initial: Duration,
    reconnect_max: Duration,
}
impl Spot {
    fn new(raw: &RawValue, trust: &Trust, clock: Arc<dyn Clock>) -> Result<Self, SourceError> {
        let rest = PublicRest::from_configuration(raw, WORK, trust)?;
        let c: Value = serde_json::from_str(raw.get()).map_err(|_| SourceError::Invalid)?;
        let environment = c["environment"].as_str().unwrap_or("GLOBAL");
        let profile = c["endpoint_profile"]
            .as_str()
            .unwrap_or(if environment == "GLOBAL" {
                "PUBLIC_MARKET_DATA"
            } else {
                "DEFAULT"
            });
        let ws_base = match (environment, profile) {
            ("GLOBAL", "PUBLIC_MARKET_DATA") => "wss://data-stream.binance.vision",
            ("GLOBAL", _) => "wss://stream.binance.com:9443",
            ("US", _) => "wss://stream.binance.us:9443",
            ("SPOT_TESTNET", _) => "wss://stream.testnet.binance.vision",
            _ => return Err(SourceError::Invalid),
        };
        let identity = MarketIdentity {
            provider: "binance".into(),
            venue: "BINANCE".into(),
            market: "SPOT".into(),
            environment: environment.into(),
            source_id: rest.source_id().into(),
        };
        let calendar = spot_calendar()?;
        let calendar_fp = hash(calendar.to_record().to_string().as_bytes());
        let capabilities = spot_rest::NATIVE_MINUTES
            .into_iter()
            .map(|m| {
                OnlyConstructionCapability::new(
                    semantic(m)?,
                    true,
                    true,
                    &calendar_fp,
                    Some(0.into()),
                )
                .map_err(|_| SourceError::Invalid)
            })
            .collect::<Result<_, _>>()?;
        let mut roots = rustls::RootCertStore::empty();
        for pem in trust.roots_pem() {
            let mut count = 0;
            for cert in rustls::pki_types::CertificateDer::pem_slice_iter(pem) {
                roots
                    .add(cert.map_err(|_| SourceError::Invalid)?)
                    .map_err(|_| SourceError::Invalid)?;
                count += 1;
            }
            if count == 0 {
                return Err(SourceError::Invalid);
            }
        }
        let tls = rustls::ClientConfig::builder_with_provider(Arc::new(
            rustls::crypto::aws_lc_rs::default_provider(),
        ))
        .with_safe_default_protocol_versions()
        .map_err(|_| SourceError::Invalid)?
        .with_root_certificates(roots)
        .with_no_client_auth();
        let duration = |key: &str, default: f64| {
            Duration::try_from_secs_f64(c[key].as_f64().unwrap_or(default))
                .map_err(|_| SourceError::Invalid)
        };
        let integer = |key: &str, default: u64| max_integer(&c, key, default);
        Ok(Self {
            rest,
            identity,
            calendar,
            capabilities,
            clock,
            tls: Arc::new(tls),
            ws_base: ws_base.into(),
            timeout: duration("timeout_seconds", 10.0)?,
            ws_limit: integer("max_ws_message_bytes", 1024 * 1024)?.min(1024 * 1024),
            buffer_limit: integer("recovery_buffer_max_events", 100000)?.min(100000),
            resume_limit: u16::try_from(integer("realtime_resume_max_bars", 120)?)
                .map_err(|_| SourceError::Invalid)?,
            reconnect_initial: duration("reconnect_initial_seconds", 0.5)?,
            reconnect_max: duration("reconnect_max_seconds", 30.0)?,
        })
    }
    async fn connect(&self, stream: &str, deadline: Instant) -> Result<Socket, SourceError> {
        let config = WebSocketConfig::default()
            .read_buffer_size(16 * 1024)
            .write_buffer_size(16 * 1024)
            .max_write_buffer_size(self.ws_limit + 16 * 1024)
            .max_message_size(Some(self.ws_limit))
            .max_frame_size(Some(self.ws_limit))
            .accept_unmasked_frames(false);
        let url = reqwest::Url::parse(&format!("{}/ws/{stream}", self.ws_base))
            .map_err(|_| SourceError::Invalid)?;
        let future = tokio_tungstenite::connect_async_tls_with_config(
            url.as_str(),
            Some(config),
            true,
            Some(Connector::Rustls(Arc::clone(&self.tls))),
        );
        let (socket, _) = tokio::time::timeout_at(deadline.into(), future)
            .await
            .map_err(|_| SourceError::Timeout)?
            .map_err(|_| SourceError::Unavailable)?;
        Ok(socket)
    }
    fn observation(
        &self,
        stream: &str,
        event_type: &str,
        bytes: Vec<u8>,
        bars: Vec<OnlyBar>,
        receive_ns: i64,
        event_ns: Option<i64>,
    ) -> Observation {
        Observation {
            identity: self.identity.clone(),
            stream: stream.into(),
            event_type: event_type.into(),
            provider_event_id: None,
            provider_sequence: None,
            event_ns,
            receive_ns,
            bytes,
            bars,
        }
    }
    fn frame(
        &self,
        bytes: Vec<u8>,
        request: &HistoryRequest,
        recorder: &mut dyn Recorder,
    ) -> Result<Option<StreamEvent>, SourceError> {
        self.frame_at(bytes, self.clock.now_ns()?, request, recorder)
    }
    fn frame_at(
        &self,
        bytes: Vec<u8>,
        received: i64,
        request: &HistoryRequest,
        recorder: &mut dyn Recorder,
    ) -> Result<Option<StreamEvent>, SourceError> {
        let decoded = spot_rest::decode_json(&bytes);
        let event_type = decoded
            .as_ref()
            .ok()
            .and_then(|v| v["e"].as_str())
            .filter(|v| !v.is_empty())
            .unwrap_or("UNKNOWN")
            .to_owned();
        let parsed = decoded
            .map_err(SourceError::from)
            .and_then(|v| ws_bar(&v, &request.instrument, request.minutes));
        let (bars, event_time) = match &parsed {
            Ok((bar, _, event)) if *bar.is_closed() => (vec![bar.clone()], Some(*event)),
            Ok((_, _, event)) => (vec![], Some(*event)),
            Err(_) => (vec![], None),
        };
        recorder.record(self.observation(
            "websocket",
            &event_type,
            bytes,
            bars,
            received,
            event_time,
        ))?;
        parsed.map(|(bar, sequence, event)| {
            Some(if *bar.is_closed() {
                StreamEvent::Closed(
                    bar,
                    sequence,
                    Some(IngressTiming {
                        provider_event_ns: event,
                        ingress_received_ns: received,
                    }),
                )
            } else {
                StreamEvent::Preview(
                    bar,
                    sequence,
                    Some(IngressTiming {
                        provider_event_ns: event,
                        ingress_received_ns: received,
                    }),
                )
            })
        })
    }
}
fn ns(t: onlyalpha_domain::time::OnlyUtcDateTime) -> Result<i64, SourceError> {
    OnlyTimestamp::from_datetime(t)
        .unix_nanos()
        .to_string()
        .parse()
        .map_err(|_| SourceError::Invalid)
}
fn max_integer(c: &Value, key: &str, default: u64) -> Result<usize, SourceError> {
    c.get(key)
        .map(|v| {
            v.as_u64()
                .and_then(|n| usize::try_from(n).ok())
                .filter(|n| *n > 0)
                .ok_or(SourceError::Invalid)
        })
        .unwrap_or(usize::try_from(default).map_err(|_| SourceError::Invalid))
}
pub fn semantic(minutes: u16) -> Result<OnlyBarSemantic, SourceError> {
    OnlyBarSemantic::from_record(&json!({"schema_version":3,"formation":{"schema_version":1,"kind":"FIXED_DURATION","window_minutes":minutes,"stride_minutes":minutes,"alignment":"SESSION_START"},"price_type":"LAST","adjustment_policy":"RAW"})).map_err(|_|SourceError::Invalid)
}
impl Resource for Spot {
    fn identity(&self) -> &MarketIdentity {
        &self.identity
    }
    fn calendar(&self) -> &OnlyTradingCalendar {
        &self.calendar
    }
    fn capabilities(&self) -> &[OnlyConstructionCapability] {
        &self.capabilities
    }
    fn resume_max_bars(&self) -> u16 {
        self.resume_limit
    }
    fn instruments<'a>(
        &'a self,
        symbols: &'a [String],
        deadline: Budget,
    ) -> FutureResult<'a, Vec<OnlyInstrument>> {
        Box::pin(async move {
            let deadline = end(deadline);
            let response = self.rest.exchange_info(symbols, deadline).await?;
            let rows = response.value()["symbols"]
                .as_array()
                .filter(|r| r.len() <= 10001)
                .ok_or(SourceError::Unavailable)?;
            rows.iter()
                .map(|r| spot_normalize::instrument(r).map_err(Into::into))
                .collect()
        })
    }
    fn quotes<'a>(
        &'a self,
        symbols: &'a [String],
        deadline: Budget,
    ) -> FutureResult<'a, Vec<Quote>> {
        Box::pin(async move {
            let deadline = end(deadline);
            let response = self.rest.tickers(symbols, deadline).await?;
            response
                .value()
                .as_array()
                .ok_or(SourceError::Unavailable)?
                .iter()
                .map(|r| {
                    let q = spot_normalize::quote(r)?;
                    Ok(Quote {
                        instrument_id: q.instrument_id,
                        last_price: q.last_price,
                        change_pct: q.change_pct,
                        event_ns: q.ts_event_ns,
                    })
                })
                .collect()
        })
    }
    fn history<'a>(
        &'a self,
        request: &'a HistoryRequest,
        deadline: Budget,
        recorder: &'a mut dyn Recorder,
    ) -> FutureResult<'a, Vec<OnlyBar>> {
        Box::pin(async move {
            let deadline = end(deadline);
            let mut bars = vec![];
            let mut observed_error = None;
            let symbol = request.instrument.specification().raw_symbol().value();
            self.rest
                .historical_interval_observed(
                    symbol,
                    request.minutes,
                    request.start_ms,
                    request.end_ms,
                    deadline,
                    &mut |context, bytes| {
                        let receive = self
                            .clock
                            .now_ns()
                            .map_err(|_| spot_rest::Error::Evidence)?;
                        let parsed = (|| {
                            if context.source_id() != self.identity.source_id
                                || context.parameter("symbol") != Some(symbol)
                                || context.parameter("interval")
                                    != Some(spot_rest::native_interval(request.minutes)?.0)
                            {
                                return Err(spot_rest::Error::Shape);
                            }
                            let page_start = context
                                .parameter("startTime")
                                .and_then(|v| v.parse::<i64>().ok())
                                .filter(|v| *v >= request.start_ms && *v < request.end_ms)
                                .ok_or(spot_rest::Error::Range)?;
                            let page_end = context
                                .parameter("endTime")
                                .and_then(|v| v.parse::<i64>().ok())
                                .filter(|v| *v == request.end_ms - 1)
                                .ok_or(spot_rest::Error::Range)?;
                            let page_limit = context
                                .parameter("limit")
                                .and_then(|v| v.parse::<usize>().ok())
                                .filter(|v| *v > 0 && *v <= 1000)
                                .ok_or(spot_rest::Error::Range)?;
                            let v = spot_rest::decode_json(bytes)?;
                            let rows = v
                                .as_array()
                                .filter(|r| r.len() <= page_limit)
                                .ok_or(spot_rest::Error::Shape)?;
                            let mut previous = None;
                            rows.iter()
                                .map(|v| {
                                    let bar = spot_normalize::rest_bar_interval(
                                        v,
                                        &request.instrument,
                                        request.minutes,
                                    )?;
                                    let start = bar.bar_start().to_string();
                                    let ms = OnlyTimestamp::from_datetime(*bar.bar_start())
                                        .unix_nanos()
                                        .to_string()
                                        .parse::<i64>()
                                        .map_err(|_| spot_rest::Error::Range)?
                                        / 1_000_000;
                                    if ms < page_start
                                        || ms > page_end
                                        || previous.as_ref().is_some_and(|p: &String| p >= &start)
                                    {
                                        return Err(spot_rest::Error::Order);
                                    }
                                    previous = Some(start);
                                    Ok(bar)
                                })
                                .collect::<spot_rest::Result<Vec<_>>>()
                        })();
                        recorder
                            .record(self.observation(
                                "rest",
                                "/api/v3/klines",
                                bytes.to_vec(),
                                parsed.as_ref().cloned().unwrap_or_default(),
                                receive,
                                None,
                            ))
                            .map_err(|e| {
                                observed_error = Some(e);
                                spot_rest::Error::Evidence
                            })?;
                        match parsed {
                            Ok(mut rows) => {
                                bars.append(&mut rows);
                                Ok(())
                            }
                            Err(e) => {
                                observed_error = Some(e.into());
                                Err(e)
                            }
                        }
                    },
                )
                .await
                .map_err(|e| observed_error.unwrap_or(e.into()))?;
            Ok(bars)
        })
    }
    fn temporary_history<'a>(
        &'a self,
        request: &'a HistoryRequest,
        deadline: Budget,
    ) -> FutureResult<'a, Vec<OnlyBar>> {
        Box::pin(async move {
            let response = self
                .rest
                .temporary_klines(
                    request.instrument.specification().raw_symbol().value(),
                    request.minutes,
                    request.start_ms,
                    request.end_ms,
                    end(deadline),
                )
                .await?;
            let bars = response.canonical_bars(&self.identity.source_id, &request.instrument)?;
            let stride = spot_rest::native_interval(request.minutes)?.1;
            let expected = usize::try_from((request.end_ms - request.start_ms) / stride)
                .map_err(|_| SourceError::Invalid)?;
            let mut previous = None;
            if bars.len() > expected {
                return Err(SourceError::Invalid);
            }
            for bar in &bars {
                let opened = OnlyTimestamp::from_datetime(*bar.bar_start())
                    .unix_nanos()
                    .to_string()
                    .parse::<i64>()
                    .map_err(|_| SourceError::Invalid)?
                    / 1_000_000;
                if opened < request.start_ms
                    || opened >= request.end_ms
                    || previous.is_some_and(|p| p >= opened)
                {
                    return Err(SourceError::Invalid);
                }
                previous = Some(opened);
            }
            Ok(bars)
        })
    }
    fn temporary_stream<'a>(
        &'a self,
        request: HistoryRequest,
        checkpoint: OnlyBar,
        deadline: Budget,
    ) -> FutureResult<'a, Box<dyn TemporaryStream>> {
        Box::pin(async move {
            if !*checkpoint.is_closed()
                || checkpoint.instrument_id() != request.instrument.specification().instrument_id()
                || checkpoint.bar_type().semantic() != &semantic(request.minutes)?
            {
                return Err(SourceError::Invalid);
            }
            let (_, stride) = spot_rest::native_interval(request.minutes)?;
            let closed_end = ns(*checkpoint.bar_end())? / 1_000_000;
            if closed_end <= 0 || closed_end % stride != 0 {
                return Err(SourceError::Invalid);
            }
            let cursor = closed_end / stride - 1;
            let last = (self.clock.now_ns()? / 1_000_000).div_euclid(stride) - 1;
            if cursor > last {
                return Err(SourceError::Invalid);
            }
            if last - cursor > i64::from(self.resume_limit.min(temporary::MAX_RECOVERY_INPUTS)) {
                return Err(SourceError::RefreshRequired);
            }
            let inner = Bars {
                source: self.clone(),
                request,
                socket: None,
                pending: VecDeque::from([StreamEvent::Recovering]),
                cursor: Some(cursor),
                known: BTreeMap::from([(cursor, checkpoint.to_record())]),
                recovering: true,
                stopped: false,
                bootstrap_deadline: Some(end(deadline)),
                delay: self.reconnect_initial,
            };
            Ok(Box::new(TemporaryBars { inner }) as Box<dyn TemporaryStream>)
        })
    }
    fn stream<'a>(
        &'a self,
        request: HistoryRequest,
        resume: Option<i64>,
        deadline: Budget,
    ) -> FutureResult<'a, Box<dyn Stream>> {
        Box::pin(async move {
            let deadline = end(deadline);
            let (_, stride) = spot_rest::native_interval(request.minutes)?;
            let last = (self.clock.now_ns()? / 1_000_000).div_euclid(stride) - 1;
            if last < 0 || resume.is_some_and(|c| c < 0 || c > last) {
                return Err(SourceError::Invalid);
            }
            if resume.is_some_and(|c| last - c > i64::from(self.resume_limit)) {
                return Err(SourceError::RefreshRequired);
            }
            let stream = Bars {
                source: self.clone(),
                request,
                socket: None,
                pending: VecDeque::from([StreamEvent::Recovering]),
                cursor: resume,
                known: BTreeMap::new(),
                recovering: true,
                stopped: false,
                bootstrap_deadline: Some(deadline),
                delay: self.reconnect_initial,
            };
            Ok(Box::new(stream) as Box<dyn Stream>)
        })
    }
    fn probe<'a>(&'a self, symbol: &'a str, deadline: Budget) -> FutureResult<'a, Value> {
        Box::pin(async move {
            let deadline = end(deadline);
            let started = self.clock.now_ns()?;
            let total = deadline.min(Instant::now() + Duration::from_secs(15));
            let mut checks = vec![];
            let mut server_ms = None;
            let mut reference = None;
            for check in [
                "CONNECTIVITY",
                "REFERENCE_DATA",
                "HISTORICAL_DATA",
                "REALTIME_DATA",
            ] {
                let at = self.clock.now_ns()?;
                let end = total.min(Instant::now() + Duration::from_secs(5));
                let result = async {
                    match check {
                        "CONNECTIVITY" => {
                            self.rest.ping(end).await?;
                            server_ms = Some(self.rest.server_time(end).await?);
                        }
                        "REFERENCE_DATA" => {
                            let rows = self.instruments(&[symbol.into()], budget(end)?).await?;
                            if rows.len() != 1 {
                                return Err(SourceError::Unavailable);
                            }
                            reference = rows.into_iter().next();
                        }
                        "HISTORICAL_DATA" => {
                            let now = server_ms.ok_or(SourceError::Unavailable)?;
                            let end_ms = now.div_euclid(60000) * 60000;
                            let start_ms = end_ms - 120000;
                            let instrument = reference.as_ref().ok_or(SourceError::Unavailable)?;
                            let rows = self
                                .rest
                                .historical_klines_observed(
                                    symbol,
                                    start_ms,
                                    end_ms,
                                    end,
                                    &mut |_, _| Ok(()),
                                )
                                .await?;
                            let bars = rows
                                .iter()
                                .map(|page| {
                                    page.canonical_bars(&self.identity.source_id, instrument)
                                })
                                .collect::<spot_rest::Result<Vec<_>>>()?
                                .into_iter()
                                .flatten()
                                .collect::<Vec<_>>();
                            if bars.len() != 2
                                || ns(*bars[0].bar_start())? != start_ms * 1_000_000
                                || ns(*bars[1].bar_end())? != end_ms * 1_000_000
                            {
                                return Err(SourceError::Unavailable);
                            }
                        }
                        _ => {
                            let mut ws = self
                                .connect(
                                    &format!("{}@depth5@100ms", symbol.to_ascii_lowercase()),
                                    end,
                                )
                                .await?;
                            let result = async {
                                let mut count = 0;
                                while count < 8 {
                                    let message = tokio::time::timeout_at(end.into(), ws.next())
                                        .await
                                        .map_err(|_| SourceError::Timeout)?
                                        .ok_or(SourceError::Unavailable)?
                                        .map_err(|_| SourceError::Unavailable)?;
                                    count += 1;
                                    match message {
                                        Message::Text(t) => {
                                            let v = spot_rest::decode_json(t.as_bytes())?;
                                            if v["lastUpdateId"].as_u64().is_none() {
                                                return Err(SourceError::Unavailable);
                                            }
                                            for side in ["bids", "asks"] {
                                                let rows = v[side]
                                                    .as_array()
                                                    .filter(|r| !r.is_empty() && r.len() <= 5)
                                                    .ok_or(SourceError::Unavailable)?;
                                                for row in rows {
                                                    let pair = row
                                                        .as_array()
                                                        .filter(|r| r.len() == 2)
                                                        .ok_or(SourceError::Unavailable)?;
                                                    for value in pair {
                                                        let n = value
                                                            .as_str()
                                                            .filter(|s| s.len() <= 128)
                                                            .and_then(|s| {
                                                                s.parse::<bigdecimal::BigDecimal>()
                                                                    .ok()
                                                            })
                                                            .filter(|n| {
                                                                n >= &bigdecimal::BigDecimal::from(
                                                                    0,
                                                                )
                                                            })
                                                            .ok_or(SourceError::Unavailable)?;
                                                        if n.as_bigint_and_exponent()
                                                            .1
                                                            .unsigned_abs()
                                                            > 128
                                                        {
                                                            return Err(SourceError::Unavailable);
                                                        }
                                                    }
                                                }
                                            }
                                            return Ok(());
                                        }
                                        Message::Ping(p) => ws
                                            .send(Message::Pong(p))
                                            .await
                                            .map_err(|_| SourceError::Unavailable)?,
                                        Message::Close(_) => return Err(SourceError::Unavailable),
                                        _ => {}
                                    }
                                }
                                Err(SourceError::Unavailable)
                            }
                            .await;
                            let _ = tokio::time::timeout_at(end.into(), ws.close(None)).await;
                            result?;
                        }
                    }
                    Ok::<(), SourceError>(())
                }
                .await;
                checks.push(json!({"check":check,"status":if result.is_ok(){"READY"}else{"UNAVAILABLE"},"started_at_ns":at,"completed_at_ns":self.clock.now_ns()?,"detail":result.err().map(SourceError::code)}));
            }
            let ready = checks.iter().all(|c| c["status"] == "READY");
            Ok(
                json!({"schema_version":1,"status":if ready{"READY"}else{"UNAVAILABLE"},"started_at_ns":started,"completed_at_ns":self.clock.now_ns()?,"checks":checks}),
            )
        })
    }
}
type Socket = WebSocketStream<MaybeTlsStream<TcpStream>>;
struct Bars {
    source: Spot,
    request: HistoryRequest,
    socket: Option<Socket>,
    pending: VecDeque<StreamEvent>,
    cursor: Option<i64>,
    known: BTreeMap<i64, Value>,
    recovering: bool,
    stopped: bool,
    bootstrap_deadline: Option<Instant>,
    delay: Duration,
}
// A short synchronous borrow serializes the existing recorder's atomic append.
// No guard is held while either provider operation waits.
#[derive(Default)]
struct RecoveryBuffer {
    events: Vec<StreamEvent>,
    bytes: usize,
    observed: usize,
}
struct SharedRecorder<'a>(std::sync::Arc<std::sync::Mutex<&'a mut dyn Recorder>>);
impl Recorder for SharedRecorder<'_> {
    fn record(&mut self, observation: Observation) -> Result<(), SourceError> {
        self.0
            .lock()
            .map_err(|_| SourceError::Evidence)?
            .record(observation)
    }
    fn finish(&mut self) -> Result<(), SourceError> {
        self.0.lock().map_err(|_| SourceError::Evidence)?.finish()
    }
}
fn recovery_deadline(bootstrap: &mut Option<Instant>, timeout: Duration) -> Instant {
    let attempt = Instant::now() + timeout;
    bootstrap
        .take()
        .map_or(attempt, |initial| initial.min(attempt))
}
impl Bars {
    async fn reconnect(&mut self) -> StreamEvent {
        self.socket = None;
        self.recovering = true;
        tokio::time::sleep(self.delay).await;
        self.delay = (self.delay * 2).min(self.source.reconnect_max);
        StreamEvent::Recovering
    }
    fn admit(&mut self, event: StreamEvent) -> Result<(), SourceError> {
        match event {
            StreamEvent::Closed(bar, seq, timing) => {
                let value = bar.to_record();
                if let Some(old) = self.known.get(&seq) {
                    if old != &value {
                        return Err(SourceError::Conflict);
                    }
                    return Ok(());
                }
                if self.cursor.is_some_and(|last| seq <= last) {
                    return Err(SourceError::RefreshRequired);
                }
                if self
                    .cursor
                    .is_some_and(|last| Some(seq) != last.checked_add(1))
                {
                    return Err(SourceError::Gap);
                }
                self.cursor = Some(seq);
                self.known.insert(seq, value);
                while self.known.len() > usize::from(self.source.resume_limit) + 1 {
                    self.known.pop_first();
                }
                self.pending
                    .push_back(StreamEvent::Closed(bar, seq, timing));
            }
            StreamEvent::Preview(bar, seq, timing) => {
                if self.cursor.is_some_and(|last| seq > last.saturating_add(1)) {
                    return Err(SourceError::Gap);
                }
                if self.cursor.is_none_or(|last| seq > last) {
                    self.pending
                        .retain(|e| !matches!(e, StreamEvent::Preview(_, _, _)));
                    self.pending
                        .push_back(StreamEvent::Preview(bar, seq, timing));
                }
            }
            _ => {}
        }
        Ok(())
    }
    async fn buffer(
        &self,
        socket: &mut Socket,
        message: Message,
        buffered: &mut RecoveryBuffer,
        deadline: Instant,
        recorder: &mut dyn Recorder,
    ) -> Result<(), SourceError> {
        let receive = self.source.clock.now_ns()?;
        // The original observation is durable even if baseline, capacity or
        // cancellation prevents this suffix from ever becoming visible.
        let length = message.len();
        match message {
            Message::Text(text) => {
                if let Some(event) = self.source.frame_at(
                    text.as_bytes().to_vec(),
                    receive,
                    &self.request,
                    recorder,
                )? {
                    buffered.events.push(event);
                }
                buffered.bytes = buffered.bytes.checked_add(length).ok_or(SourceError::Gap)?;
            }
            Message::Binary(data) => {
                recorder.record(self.source.observation(
                    "websocket",
                    "UNKNOWN",
                    data.to_vec(),
                    vec![],
                    receive,
                    None,
                ))?;
                return Err(SourceError::Invalid);
            }
            Message::Ping(p) => {
                tokio::time::timeout_at(deadline.into(), socket.send(Message::Pong(p)))
                    .await
                    .map_err(|_| SourceError::Timeout)?
                    .map_err(|_| SourceError::Unavailable)?;
            }
            Message::Pong(_) => {}
            _ => return Err(SourceError::Unavailable),
        }
        buffered.observed = buffered.observed.checked_add(1).ok_or(SourceError::Gap)?;
        if buffered.observed > self.source.buffer_limit || buffered.bytes > 8 * 1024 * 1024 {
            return Err(SourceError::Gap);
        }
        // Original receive sampling and its atomic record are already complete.
        // Ready socket buffers must not starve Host revocation or shutdown.
        tokio::task::yield_now().await;
        Ok(())
    }
    async fn recover(&mut self, recorder: &mut dyn Recorder) -> Result<(), SourceError> {
        let source = self.source.clone();
        let mut request = self.request.clone();
        let (_, stride) = spot_rest::native_interval(request.minutes)?;
        let last = (source.clock.now_ns()? / 1_000_000).div_euclid(stride) - 1;
        if self.cursor.is_some_and(|c| c > last) {
            return Err(SourceError::Invalid);
        }
        let first = self.cursor.unwrap_or(last);
        if last - first > i64::from(source.resume_limit) {
            return Err(SourceError::RefreshRequired);
        }
        let deadline = recovery_deadline(&mut self.bootstrap_deadline, source.timeout);
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
            .await?;
        request.start_ms = first * stride;
        request.end_ms = (last + 1) * stride;
        let mut buffered = RecoveryBuffer::default();
        let shared = std::sync::Arc::new(std::sync::Mutex::new(recorder));
        let mut history_recorder = SharedRecorder(std::sync::Arc::clone(&shared));
        let mut suffix_recorder = SharedRecorder(shared);
        let baseline = {
            let history = async {
                if first <= last {
                    source
                        .history(&request, budget(deadline)?, &mut history_recorder)
                        .await
                } else {
                    Ok(vec![])
                }
            };
            tokio::pin!(history);
            loop {
                tokio::select! {
                    result=&mut history=>break result?,
                    message=socket.next()=>{
                        let message=message.ok_or(SourceError::Unavailable)?.map_err(|_|SourceError::Unavailable)?;
                        self.buffer(&mut socket, message, &mut buffered, deadline,&mut suffix_recorder).await?;
                    }
                }
            }
        };
        // Reconcile the already available suffix before publishing the cutover.
        // Every observed control/data frame consumes the same finite recovery budget.
        while let Some(message) = socket.next().now_or_never() {
            let message = message
                .ok_or(SourceError::Unavailable)?
                .map_err(|_| SourceError::Unavailable)?;
            self.buffer(
                &mut socket,
                message,
                &mut buffered,
                deadline,
                &mut suffix_recorder,
            )
            .await?;
        }

        let actual = baseline
            .iter()
            .map(|b| {
                OnlyTimestamp::from_datetime(*b.bar_start())
                    .unix_nanos()
                    .to_string()
                    .parse::<i64>()
                    .map(|n| n / (stride * 1_000_000))
                    .map_err(|_| SourceError::Invalid)
            })
            .collect::<Result<Vec<_>, _>>()?;
        if actual != (first..=last).collect::<Vec<_>>() {
            return Err(SourceError::Gap);
        }
        for (bar, seq) in baseline.into_iter().zip(actual) {
            if self.cursor == Some(seq) && !self.known.contains_key(&seq) {
                self.known.insert(seq, bar.to_record());
            } else {
                self.admit(StreamEvent::Closed(bar, seq, None))?;
            }
        }
        for event in buffered.events {
            self.admit(event)?;
            tokio::task::yield_now().await;
        }
        self.socket = Some(socket);
        self.recovering = false;
        self.delay = source.reconnect_initial;
        self.pending.push_back(StreamEvent::Ready);
        Ok(())
    }
}

impl Stream for Bars {
    fn next<'a>(&'a mut self, recorder: &'a mut dyn Recorder) -> FutureResult<'a, StreamEvent> {
        Box::pin(async move {
            loop {
                tokio::task::yield_now().await;
                if self.stopped {
                    return Err(SourceError::Stopped);
                }
                if let Some(event) = self.pending.pop_front() {
                    return Ok(event);
                }
                if self.recovering {
                    match self.recover(recorder).await {
                        Ok(()) => continue,
                        Err(error) => {
                            self.stopped = true;
                            self.socket = None;
                            return Ok(StreamEvent::Lost(error));
                        }
                    }
                }
                let message = match self.socket.as_mut() {
                    Some(socket) => socket.next().await,
                    None => None,
                };
                match message {
                    Some(Ok(Message::Text(text))) => {
                        let source = self.source.clone();
                        match source.frame(text.as_bytes().to_vec(), &self.request, recorder) {
                            Ok(Some(event)) => {
                                if let Err(error) = self.admit(event) {
                                    self.stopped = true;
                                    return Ok(StreamEvent::Lost(error));
                                }
                            }
                            Ok(None) => {}
                            Err(error) => {
                                self.stopped = true;
                                return Ok(StreamEvent::Lost(error));
                            }
                        }
                    }
                    Some(Ok(Message::Binary(bytes))) => {
                        let receive = self.source.clock.now_ns()?;
                        let captured = recorder.record(self.source.observation(
                            "websocket",
                            "UNKNOWN",
                            bytes.to_vec(),
                            vec![],
                            receive,
                            None,
                        ));
                        self.stopped = true;
                        self.socket = None;
                        return Ok(StreamEvent::Lost(
                            captured.err().unwrap_or(SourceError::Invalid),
                        ));
                    }
                    Some(Ok(Message::Ping(payload))) => {
                        let end = Instant::now() + self.source.timeout;
                        if !matches!(
                            tokio::time::timeout_at(
                                end.into(),
                                self.socket
                                    .as_mut()
                                    .ok_or(SourceError::Stopped)?
                                    .send(Message::Pong(payload)),
                            )
                            .await,
                            Ok(Ok(()))
                        ) {
                            return Ok(self.reconnect().await);
                        }
                    }
                    Some(Ok(Message::Pong(_))) => {}
                    _ => {
                        return Ok(self.reconnect().await);
                    }
                }
            }
        })
    }
    fn close<'a>(&'a mut self) -> FutureResult<'a, ()> {
        Box::pin(async move {
            self.stopped = true;
            self.pending.clear();
            if let Some(mut socket) = self.socket.take() {
                let end = Instant::now() + self.source.timeout;
                let result = tokio::time::timeout_at(end.into(), socket.close(None))
                    .await
                    .map_err(|_| SourceError::Timeout)
                    .and_then(|result| result.map_err(|_| SourceError::Unavailable));
                result?;
            }
            Ok(())
        })
    }
}
/// Kline open time is a cursor, never a fabricated provider event occurrence.
fn ws_bar(
    raw: &Value,
    instrument: &OnlyInstrument,
    minutes: u16,
) -> Result<(OnlyBar, i64, i64), SourceError> {
    let (interval, stride) = spot_rest::native_interval(minutes)?;
    let k = &raw["k"];
    if raw["e"] != "kline"
        || raw["s"] != instrument.specification().raw_symbol().value()
        || k["s"] != raw["s"]
        || k["i"] != interval
    {
        return Err(SourceError::Invalid);
    }
    let event = raw["E"]
        .as_i64()
        .filter(|n| *n >= 0)
        .and_then(|n| n.checked_mul(1_000_000))
        .ok_or(SourceError::Invalid)?;
    let closed = k["x"].as_bool().ok_or(SourceError::Invalid)?;
    let row = json!([
        k["t"], k["o"], k["h"], k["l"], k["c"], k["v"], k["T"], k["q"], k["n"], k["V"], k["Q"], "0"
    ]);
    let bar = spot_normalize::rest_bar_interval(&row, instrument, minutes)?;
    let mut record = bar.to_record();
    record["is_closed"] = json!(closed);
    let sequence = k["t"].as_i64().ok_or(SourceError::Invalid)? / stride;
    Ok((
        OnlyBar::from_record(&record).map_err(|_| SourceError::Invalid)?,
        sequence,
        event,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    struct FixedClock;
    impl Clock for FixedClock {
        fn now_ns(&self) -> Result<i64, SourceError> {
            Ok(1_800_000_000_000_000_000)
        }
    }
    pub(super) const CERT: &[u8] = br#"-----BEGIN CERTIFICATE-----
MIICxDCCAawCCQCBzawSxhZ1wTANBgkqhkiG9w0BAQsFADAkMSIwIAYDVQQDDBlP
bmx5QWxwaGFDb250cm9sbGVkU291cmNlMB4XDTI2MTAyMjA2MDQxMloXDTM2MTAx
OTA2MDQxMlowJDEiMCAGA1UEAwwZT25seUFscGhhQ29udHJvbGxlZFNvdXJjZTCC
ASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBALWQDj15xcljhxyDGzHrafnS
LtBk0C3BAIIPyq+oW+iv4WPCsn/+bl3sFvvDA0OOsMfWrmLt+WxdKPGd4I9r8lWw
p1qI+WB8B2M+K1ZARHcZlY9c2fKt2xssUYPW4LIzsc8LixhXyQRic+fbsx2vTdKR
oodNp3HZNKl/ARCX5jaBVPeTztV2g+61MGAxkPYfdGvXW8Z3QgV06cZSHThyRuKx
jYbtqZhxa9dNHWsKEfM5DsNZgU+U/9h1n/oHEM+3EMoZiNvguwd3F7AaKnqqCMGV
iYT2EFIIoI9Yb/vovIe2a0Uu1TaiuYhdGbPuyhagSrwgxL85jPkgbJnqlIERNTsC
AwEAATANBgkqhkiG9w0BAQsFAAOCAQEAI2+r8DRj/2EyyQvpg+Xy0OwMbtm7fCgD
0WEwJ/KQUHVd4RL2uO5iR5/heDdOoq3cmiLOoQp2HX+/z21flKzozla4/YcFybuk
ePmU8jkDTg86WEqFihJs8hwdS8MObAMt+Ju9HB0rlDXlDoHOmhB5F6fbeJKtN7Zz
9U3ZW6UnFvr9f3NFQz0jqqroX9B9qunhtcI/7c7ieuDwZygh4vwPKWKF1SMl3BmA
VHTbObMrXpXfdbWm0Et+xpvEbfSjeIbGuVTPxcoDxj+NQPAqgQEAO5O0vhF4Idn6
eyGs1dw4kT66b00SPSBhiQVOIM+W+yC2GWPG+iDnVsHtzQ0GFFTCmw==
-----END CERTIFICATE-----
"#;
    fn runtime() -> tokio::runtime::Runtime {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
    }
    fn source(base: &str) -> Spot {
        let mut s = Spot::new(
            RawValue::from_string("{}".into()).unwrap().as_ref(),
            &Trust::explicit_roots(vec![CERT.to_vec()]).unwrap(),
            Arc::new(FixedClock),
        )
        .unwrap();
        s.rest = PublicRest::test_transport(base);
        s
    }
    fn instrument() -> OnlyInstrument {
        spot_normalize::instrument(&json!({"symbol":"BTCUSDT","baseAsset":"BTC","quoteAsset":"USDT","status":"TRADING","filters":[{"filterType":"PRICE_FILTER","tickSize":"0.01"},{"filterType":"LOT_SIZE","stepSize":"0.00001","minQty":"0.00001"}]})).unwrap()
    }
    fn http(bodies: Vec<String>) -> (String, std::thread::JoinHandle<Vec<String>>) {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let task = std::thread::spawn(move || {
            let mut requests = vec![];
            for body in bodies {
                let (mut client, _) = listener.accept().unwrap();
                let mut request = vec![];
                let mut byte = [0];
                while !request.ends_with(b"\r\n\r\n") {
                    client.read_exact(&mut byte).unwrap();
                    request.extend_from_slice(&byte);
                    assert!(request.len() < 16384);
                }
                requests.push(String::from_utf8(request).unwrap());
                write!(client,"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body).unwrap();
            }
            requests
        });
        (url, task)
    }
    #[test]
    fn unicode_spot_catalog_does_not_hide_or_reject_other_instruments() {
        runtime().block_on(async {
            let mut unicode = json!({"symbol":"币安人生USDT","baseAsset":"币安人生","quoteAsset":"USDT","status":"TRADING","filters":[{"filterType":"PRICE_FILTER","tickSize":"0.01"},{"filterType":"LOT_SIZE","stepSize":"0.00001","minQty":"0.00001"}]});
            let mut ascii = unicode.clone();
            ascii["symbol"] = json!("BTCUSDT");
            ascii["baseAsset"] = json!("BTC");
            let (url, server) = http(vec![json!({"symbols":[ascii, unicode.take()]}).to_string()]);
            let s = source(&url);
            let rows = s.instruments(&[], Budget::from_millis(5000).unwrap()).await.unwrap();
            assert_eq!(rows.len(), 2);
            assert_eq!(rows[0].specification().raw_symbol().value(), "BTCUSDT");
            assert_eq!(rows[1].specification().raw_symbol().value(), "币安人生USDT");
            let requests = server.join().unwrap();
            assert!(requests[0].contains("showPermissionSets=false"));
            assert!(requests[0].contains("permissions=SPOT"));
        });
    }
    #[test]
    fn unicode_spot_websocket_handshake_uses_an_encoded_exact_stream_path() {
        runtime().block_on(async {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let mut s = source("http://127.0.0.1:1");
            s.ws_base = format!("ws://{}", listener.local_addr().unwrap());
            let server = async {
                let (socket, _) = listener
                    .accept()
                    .await
                    .map_err(|_| SourceError::Unavailable)?;
                let mut path = String::new();
                // Tungstenite requires its full HTTP error response for this callback;
                // the fixture only observes the path and always accepts the handshake.
                #[allow(clippy::result_large_err)]
                let _socket = tokio_tungstenite::accept_hdr_async(
                    socket,
                    |request: &tokio_tungstenite::tungstenite::handshake::server::Request,
                     response| {
                        path = request.uri().path().to_owned();
                        Ok(response)
                    },
                )
                .await
                .map_err(|_| SourceError::Unavailable)?;
                Ok::<_, SourceError>(path)
            };
            let (_, path) = tokio::try_join!(
                s.connect(
                    "币安人生usdt@kline_1m",
                    Instant::now() + Duration::from_secs(5)
                ),
                server
            )
            .unwrap();
            assert_eq!(
                path,
                "/ws/%E5%B8%81%E5%AE%89%E4%BA%BA%E7%94%9Fusdt@kline_1m"
            );
        });
    }
    #[derive(Default)]
    struct Captures {
        observations: Vec<Observation>,
        fail: bool,
    }
    impl Recorder for Captures {
        fn record(&mut self, o: Observation) -> Result<(), SourceError> {
            self.observations.push(o);
            if self.fail {
                Err(SourceError::Evidence)
            } else {
                Ok(())
            }
        }
        fn finish(&mut self) -> Result<(), SourceError> {
            Ok(())
        }
    }
    fn request(minutes: u16, start: i64, count: i64) -> HistoryRequest {
        HistoryRequest {
            instrument: instrument(),
            minutes,
            start_ms: start,
            end_ms: start + i64::from(minutes) * 60000 * count,
        }
    }
    fn row(start: i64, minutes: u16) -> Value {
        json!([
            start,
            "10",
            "11",
            "9",
            "10.5",
            "1.23",
            start + i64::from(minutes) * 60000 - 1,
            "12.915",
            3,
            "0",
            "0",
            "0"
        ])
    }
    #[test]
    fn temporary_history_uses_the_exact_provider_response_without_a_durable_recorder() {
        runtime().block_on(async {
            let bytes = json!([row(0, 1), row(60_000, 1)]).to_string();
            let (url, server) = http(vec![bytes]);
            let s = source(&url);
            let bars = s
                .temporary_history(&request(1, 0, 2), Budget::from_millis(5000).unwrap())
                .await
                .unwrap();
            assert_eq!(bars.len(), 2);
            assert_eq!(bars[0].instrument_id().to_string(), "BTCUSDT.BINANCE");
            assert_eq!(bars[1].bar_start().to_string(), "1970-01-01T00:01:00Z");
            let requests = server.join().unwrap();
            assert_eq!(requests.len(), 1);
            assert!(requests[0].contains("symbol=BTCUSDT"));
        })
    }
    #[test]
    fn actual_history_records_one_original_response_and_all_rows_before_visibility() {
        runtime().block_on(async {
            for minutes in spot_rest::NATIVE_MINUTES {
                let bytes =
                    json!([row(0, minutes), row(i64::from(minutes) * 60000, minutes)]).to_string();
                let (url, server) = http(vec![bytes.clone()]);
                let s = source(&url);
                let mut recorder = Captures::default();
                let bars = s
                    .history(
                        &request(minutes, 0, 2),
                        Budget::from_millis(5000).unwrap(),
                        &mut recorder,
                    )
                    .await
                    .unwrap();
                assert_eq!(bars.len(), 2);
                assert_eq!(recorder.observations.len(), 1);
                assert_eq!(recorder.observations[0].bytes, bytes.as_bytes());
                assert_eq!(recorder.observations[0].bars, bars);
                assert!(recorder.observations[0].provider_event_id.is_none());
                let requests = server.join().unwrap();
                assert!(requests[0].contains(&format!(
                    "interval={}",
                    spot_rest::native_interval(minutes).unwrap().0
                )));
            }
        })
    }
    #[test]
    fn malformed_or_normalization_invalid_is_retained_raw_with_zero_facts() {
        runtime().block_on(async {
            for bytes in [
                "not-json".to_string(),
                json!([row(1, 1)]).to_string(),
                json!([row(0, 1), row(0, 1)]).to_string(),
            ] {
                let (url, server) = http(vec![bytes.clone()]);
                let s = source(&url);
                let mut recorder = Captures::default();
                assert!(
                    s.history(
                        &request(1, 0, 2),
                        Budget::from_millis(5000).unwrap(),
                        &mut recorder
                    )
                    .await
                    .is_err()
                );
                assert_eq!(recorder.observations.len(), 1);
                assert_eq!(recorder.observations[0].bytes, bytes.as_bytes());
                assert!(recorder.observations[0].bars.is_empty());
                server.join().unwrap();
            }
        })
    }
    #[test]
    fn earlier_page_row_is_retained_without_canonical_facts() {
        runtime().block_on(async {
            let bytes = json!([row(0, 1)]).to_string();
            let (url, server) = http(vec![bytes.clone(), bytes.clone()]);
            let mut s = source(&url);
            s.rest.page_size_for_test(1);
            let mut recorder = Captures::default();
            assert!(
                s.history(
                    &request(1, 0, 2),
                    Budget::from_millis(5000).unwrap(),
                    &mut recorder
                )
                .await
                .is_err()
            );
            assert_eq!(recorder.observations.len(), 2);
            assert_eq!(recorder.observations[0].bars.len(), 1);
            assert_eq!(recorder.observations[1].bytes, bytes.as_bytes());
            assert!(recorder.observations[1].bars.is_empty());
            let requests = server.join().unwrap();
            assert!(requests[1].contains("startTime=60000"));
        })
    }
    #[test]
    fn recorder_failure_prevents_success_and_later_pages() {
        runtime().block_on(async {
            let (url, server) = http(vec![json!([row(0, 1)]).to_string()]);
            let mut s = source(&url);
            s.rest.page_size_for_test(1);
            let mut recorder = Captures {
                fail: true,
                ..Default::default()
            };
            assert_eq!(
                s.history(
                    &request(1, 0, 2),
                    Budget::from_millis(5000).unwrap(),
                    &mut recorder
                )
                .await
                .err(),
                Some(SourceError::Evidence)
            );
            assert_eq!(server.join().unwrap().len(), 1);
        })
    }
    #[test]
    fn current_factory_advertises_only_executable_chart_capabilities() {
        let factory = SpotFactory::installed().unwrap();
        let d: Value = serde_json::from_str(factory.descriptor.document().get()).unwrap();
        assert_eq!(d["implementation_id"], "binance-native");
        assert!(
            !d["capabilities"]
                .as_array()
                .unwrap()
                .iter()
                .any(|c| c == "HISTORICAL_TICKS" || c == "LIVE_TICKS")
        );
        let s = source("http://127.0.0.1:1");
        assert_eq!(s.capabilities.len(), 8);
        assert!(Trust::explicit_roots(vec![]).is_err());
        assert!(
            factory
                .create(
                    RawValue::from_string("{}".into()).unwrap().as_ref(),
                    &Trust::explicit_roots(vec![b"not a root".to_vec()]).unwrap(),
                    Arc::new(FixedClock)
                )
                .is_err()
        );
    }
    #[test]
    fn websocket_preview_and_closed_share_canonical_values_and_original_time_semantics() {
        let s = source("http://127.0.0.1:1");
        let request = request(15, 0, 1);
        let mut recorder = Captures::default();
        for closed in [false, true] {
            let event = json!({"e":"kline","E":900001,"s":"BTCUSDT","k":{"s":"BTCUSDT","i":"15m","t":0,"T":899999,"o":"10","h":"11","l":"9","c":"10.5","v":"1.23","q":"12.915","n":3,"V":"0","Q":"0","x":closed}});
            let result = s
                .frame(event.to_string().into_bytes(), &request, &mut recorder)
                .unwrap()
                .unwrap();
            match result {
                StreamEvent::Closed(bar, 0, _) => {
                    assert!(closed);
                    assert_eq!(
                        bar,
                        spot_normalize::rest_bar_interval(&row(0, 15), &instrument(), 15).unwrap()
                    );
                }
                StreamEvent::Preview(bar, 0, _) => assert!(!bar.is_closed()),
                _ => panic!("unexpected event"),
            };
            assert_eq!(
                recorder.observations.last().unwrap().bars.len(),
                usize::from(closed)
            );
            assert!(
                recorder
                    .observations
                    .last()
                    .unwrap()
                    .provider_event_id
                    .is_none()
            );
            assert_eq!(
                recorder.observations.last().unwrap().event_ns,
                Some(900001000000)
            );
        }
        let count = recorder.observations.len();
        assert!(
            s.frame(b"malformed".to_vec(), &request, &mut recorder)
                .is_err()
        );
        assert_eq!(recorder.observations.len(), count + 1);
        assert!(recorder.observations.last().unwrap().bars.is_empty());
    }
    fn kline(start: i64, minutes: u16, closed: bool) -> Message {
        Message::Text(json!({"e":"kline","E":start+i64::from(minutes)*60000,"s":"BTCUSDT","k":{"s":"BTCUSDT","i":spot_rest::native_interval(minutes).unwrap().0,"t":start,"T":start+i64::from(minutes)*60000-1,"o":"10","h":"11","l":"9","c":"10.5","v":"1.23","q":"12.915","n":3,"V":"0","Q":"0","x":closed}}).to_string().into())
    }
    struct MovingClock(std::sync::atomic::AtomicI64);
    impl Clock for MovingClock {
        fn now_ns(&self) -> Result<i64, SourceError> {
            Ok(self.0.load(std::sync::atomic::Ordering::SeqCst))
        }
    }
    #[test]
    fn temporary_stream_caps_small_gap_at_120_even_with_a_larger_formal_resume_setting() {
        runtime().block_on(async {
            let mut s = source("http://127.0.0.1:1");
            s.resume_limit = 1000;
            // Checkpoint closes interval 2; latest closed interval is 123.
            s.clock = Arc::new(MovingClock(std::sync::atomic::AtomicI64::new(
                124 * 60_000_000_000,
            )));
            let checkpoint =
                spot_normalize::rest_bar_interval(&row(120_000, 1), &instrument(), 1).unwrap();
            assert!(matches!(
                s.temporary_stream(
                    request(1, 0, 1),
                    checkpoint,
                    Budget::from_millis(5000).unwrap()
                )
                .await,
                Err(SourceError::RefreshRequired)
            ));
        });
    }
    #[test]
    fn temporary_stream_recovers_from_the_owned_bar_and_rejects_changed_checkpoint_values() {
        runtime().block_on(async {
            for changed in [false, true] {
                let checkpoint =
                    spot_normalize::rest_bar_interval(&row(120_000, 1), &instrument(), 1).unwrap();
                let mut first = row(120_000, 1);
                if changed {
                    first[4] = json!("10.4");
                }
                let (url, http_task) = http(vec![json!([first, row(180_000, 1)]).to_string()]);
                let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
                let mut s = source(&url);
                s.ws_base = format!("ws://{}", listener.local_addr().unwrap());
                s.clock = Arc::new(MovingClock(std::sync::atomic::AtomicI64::new(
                    239_000_000_000,
                )));
                let peer = tokio::spawn(async move {
                    let (tcp, _) = listener.accept().await.unwrap();
                    let mut socket = tokio_tungstenite::accept_async(tcp).await.unwrap();
                    // Provider has crossed the next interval while the local
                    // clock is still behind it. The connected socket is the
                    // explicit cutover marker, not a guessed local latest bar.
                    socket.send(kline(240_000, 1, false)).await.unwrap();
                    let terminal = socket.next().await;
                    if !changed {
                        assert!(matches!(terminal, Some(Ok(Message::Close(_)))));
                    }
                });
                let mut stream = s
                    .temporary_stream(
                        request(1, 0, 1),
                        checkpoint,
                        Budget::from_millis(5000).unwrap(),
                    )
                    .await
                    .unwrap();
                assert!(matches!(
                    stream.next().await.unwrap(),
                    StreamEvent::Recovering
                ));
                if changed {
                    assert!(matches!(
                        stream.next().await.unwrap(),
                        StreamEvent::Lost(SourceError::Conflict)
                    ));
                } else {
                    assert!(matches!(
                        stream.next().await.unwrap(),
                        StreamEvent::Closed(_, 3, _)
                    ));
                    assert!(matches!(
                        stream.next().await.unwrap(),
                        StreamEvent::Preview(_, 4, _)
                    ));
                    assert!(matches!(stream.next().await.unwrap(), StreamEvent::Ready));
                }
                stream.close().await.unwrap();
                peer.await.unwrap();
                http_task.join().unwrap();
            }
        });
    }
    #[test]
    fn temporary_recovery_keeps_its_deadline_across_client_control_cancellation() {
        runtime().block_on(async {
            let (url, http_task) = http(vec![json!([row(120_000, 1)]).to_string()]);
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let mut source = source(&url);
            source.ws_base = format!("ws://{}", listener.local_addr().unwrap());
            source.timeout = Duration::from_secs(60);
            source.clock = Arc::new(MovingClock(std::sync::atomic::AtomicI64::new(
                180_000_000_000,
            )));
            let controls = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let client = TcpStream::connect(controls.local_addr().unwrap())
                .await
                .unwrap();
            let (server, _) = controls.accept().await.unwrap();
            let mut browser = WebSocketStream::from_raw_socket(
                client,
                tokio_tungstenite::tungstenite::protocol::Role::Client,
                None,
            )
            .await;
            let mut transport = WebSocketStream::from_raw_socket(
                server,
                tokio_tungstenite::tungstenite::protocol::Role::Server,
                None,
            )
            .await;
            let (cancelled, mut cancellation) = tokio::sync::mpsc::channel(1);
            let peer = tokio::spawn(async move {
                for control in [Message::Ping(vec![1].into()), Message::Pong(vec![2].into())] {
                    let (tcp, _) = listener.accept().await.unwrap();
                    let socket = tokio_tungstenite::accept_async(tcp).await.unwrap();
                    // The Provider handshake is the barrier: recovery has already
                    // selected its deadline before the client frame cancels next().
                    browser.send(control).await.unwrap();
                    cancellation.recv().await.unwrap();
                    drop(socket);
                }
                let (tcp, _) = listener.accept().await.unwrap();
                let mut socket = tokio_tungstenite::accept_async(tcp).await.unwrap();
                socket.send(kline(180_000, 1, false)).await.unwrap();
                assert!(matches!(
                    socket.next().await.unwrap().unwrap(),
                    Message::Close(_)
                ));
            });
            let checkpoint =
                spot_normalize::rest_bar_interval(&row(120_000, 1), &instrument(), 1).unwrap();
            let original = Instant::now() + Duration::from_secs(30);
            let mut stream = TemporaryBars {
                inner: Bars {
                    source,
                    request: request(1, 0, 1),
                    socket: None,
                    pending: VecDeque::from([StreamEvent::Recovering]),
                    cursor: Some(2),
                    known: BTreeMap::from([(2, checkpoint.to_record())]),
                    recovering: true,
                    stopped: false,
                    bootstrap_deadline: Some(original),
                    delay: Duration::ZERO,
                },
            };
            assert!(matches!(
                stream.next().await.unwrap(),
                StreamEvent::Recovering
            ));
            for ping in [true, false] {
                let control = tokio::select! { biased;
                    message = transport.next() => message.unwrap().unwrap(),
                    _ = stream.next() => panic!("Provider must wait at the controlled frontier"),
                };
                assert!(matches!(
                    (&control, ping),
                    (Message::Ping(_), true) | (Message::Pong(_), false)
                ));
                assert_eq!(stream.inner.bootstrap_deadline, Some(original));
                assert!(stream.inner.recovering);
                assert!(!stream.inner.stopped);
                cancelled.send(()).await.unwrap();
            }
            assert!(matches!(
                stream.next().await.unwrap(),
                StreamEvent::Preview(_, 3, _)
            ));
            assert!(matches!(stream.next().await.unwrap(), StreamEvent::Ready));
            assert_eq!(stream.inner.bootstrap_deadline, None);
            assert!(!stream.inner.recovering);
            stream.close().await.unwrap();
            peer.await.unwrap();
            http_task.join().unwrap();
        });
    }
    #[test]
    fn temporary_recovery_timeout_is_terminal_instead_of_starting_another_budget() {
        runtime().block_on(async {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let mut source = source("http://127.0.0.1:1");
            source.ws_base = format!("ws://{}", listener.local_addr().unwrap());
            source.clock = Arc::new(MovingClock(std::sync::atomic::AtomicI64::new(
                180_000_000_000,
            )));
            let mut stream = TemporaryBars {
                inner: Bars {
                    source,
                    request: request(1, 0, 1),
                    socket: None,
                    pending: VecDeque::new(),
                    cursor: Some(2),
                    known: BTreeMap::new(),
                    recovering: true,
                    stopped: false,
                    bootstrap_deadline: Some(Instant::now() - Duration::from_secs(1)),
                    delay: Duration::ZERO,
                },
            };
            assert!(matches!(
                stream.next().await.unwrap(),
                StreamEvent::Lost(SourceError::Timeout)
            ));
            assert!(stream.inner.stopped);
            assert!(stream.inner.socket.is_none());
            assert_eq!(stream.inner.bootstrap_deadline, None);
            assert!(matches!(stream.next().await, Err(SourceError::Stopped)));
            stream.close().await.unwrap();
        });
    }
    #[test]
    fn bootstrap_expiry_is_not_reused_by_any_later_recovery_entry() {
        let expired = Instant::now() - Duration::from_secs(1);
        let mut initial = Some(expired);
        assert_eq!(
            recovery_deadline(&mut initial, Duration::from_secs(5)),
            expired
        );
        assert!(initial.is_none());
        // All later entries, including a failed Pong write, consume this same owner.
        let before = Instant::now();
        assert!(recovery_deadline(&mut initial, Duration::from_secs(5)) > before);
        assert!(initial.is_none());
    }
    #[test]
    fn actual_pong_write_failure_announces_recovery_and_does_not_reuse_expired_bootstrap() {
        runtime().block_on(async {
            let (url, http_task) = http(vec![json!([row(120000, 1)]).to_string()]);
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let mut source = source(&url);
            source.ws_base = format!("ws://{}", listener.local_addr().unwrap());
            source.clock = Arc::new(MovingClock(std::sync::atomic::AtomicI64::new(
                180_000_000_000,
            )));
            source.reconnect_initial = Duration::ZERO;
            let (release, released) = tokio::sync::oneshot::channel();
            let peer = tokio::spawn(async move {
                let (tcp, _) = listener.accept().await.unwrap();
                let mut first = tokio_tungstenite::accept_async(tcp).await.unwrap();
                released.await.unwrap();
                first.send(Message::Ping(vec![7].into())).await.unwrap();
                let (tcp, _) = listener.accept().await.unwrap();
                let mut next = tokio_tungstenite::accept_async(tcp).await.unwrap();
                drop(first);
                assert!(matches!(
                    next.next().await.unwrap().unwrap(),
                    Message::Close(_)
                ));
            });
            let mut socket = source
                .connect("btcusdt@kline_1m", Instant::now() + Duration::from_secs(5))
                .await
                .unwrap();
            // Exact owning transport fault: reads remain available while any Pong
            // write must fail after the local TCP write half has been shut down.
            let MaybeTlsStream::Plain(tcp) = socket.get_mut() else {
                panic!("controlled plain transport")
            };
            tokio::io::AsyncWriteExt::shutdown(tcp).await.unwrap();
            let expired = Instant::now() - Duration::from_secs(1);
            let mut bootstrap = Some(expired);
            assert_eq!(recovery_deadline(&mut bootstrap, source.timeout), expired);
            let mut stream = Bars {
                request: request(1, 0, 1),
                source,
                socket: Some(socket),
                pending: VecDeque::new(),
                cursor: Some(2),
                known: BTreeMap::new(),
                recovering: false,
                stopped: false,
                bootstrap_deadline: bootstrap,
                delay: Duration::ZERO,
            };
            let mut recorder = Captures::default();
            release.send(()).unwrap();
            assert!(matches!(
                stream.next(&mut recorder).await.unwrap(),
                StreamEvent::Recovering
            ));
            assert!(matches!(
                stream.next(&mut recorder).await.unwrap(),
                StreamEvent::Ready
            ));
            assert_eq!(recorder.observations.len(), 1);
            assert_eq!(recorder.observations[0].stream, "rest");
            stream.close().await.unwrap();
            peer.await.unwrap();
            http_task.join().unwrap();
        });
    }
    #[test]
    fn actual_socket_cutover_keeps_receive_time_and_reconnect_deduplicates_exact_interval() {
        runtime().block_on(async {
            let minutes=15; let stride=i64::from(minutes)*60000;
            let clock=Arc::new(MovingClock(std::sync::atomic::AtomicI64::new(3*stride*1_000_000)));
            let (release, released)=std::sync::mpsc::channel();
            let http_listener=std::net::TcpListener::bind("127.0.0.1:0").unwrap();
            let base=format!("http://{}",http_listener.local_addr().unwrap());
            let http_task=std::thread::spawn(move || {
                let mut requests=vec![];
                for index in 0..2 {
                    let (mut client,_)=http_listener.accept().unwrap();let mut bytes=vec![];let mut b=[0];
                    while !bytes.ends_with(b"\r\n\r\n") {client.read_exact(&mut b).unwrap();bytes.extend(b);}
                    requests.push(String::from_utf8(bytes).unwrap());
                    if index==0 { released.recv().unwrap(); }
                    let body=json!([row((index+2)*stride,minutes)]).to_string();
                    write!(client,"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body).unwrap();
                }
                requests
            });
            let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let ws=format!("ws://{}",listener.local_addr().unwrap());
            let (advance,mut advanced)=tokio::sync::mpsc::channel(1);
            let server_clock=Arc::clone(&clock);
            let socket_task=tokio::spawn(async move {
                let (tcp,_)=listener.accept().await.unwrap();
                let mut socket=tokio_tungstenite::accept_async(tcp).await.unwrap();
                socket.send(kline(3*stride,minutes,false)).await.unwrap();
                socket.send(kline(3*stride,minutes,true)).await.unwrap();
                socket.send(Message::Ping(vec![9].into())).await.unwrap();
                assert!(matches!(socket.next().await.unwrap().unwrap(),Message::Pong(_)));
                server_clock.0.store(4*stride*1_000_000,std::sync::atomic::Ordering::SeqCst);
                release.send(()).unwrap();
                advanced.recv().await.unwrap();
                socket.send(kline(3*stride,minutes,true)).await.unwrap();
                socket.close(None).await.unwrap();
                let (tcp,_)=listener.accept().await.unwrap();
                let mut socket=tokio_tungstenite::accept_async(tcp).await.unwrap();
                assert!(matches!(socket.next().await.unwrap().unwrap(),Message::Close(_)));
            });
            let mut s=source(&base);s.ws_base=ws;s.clock=clock;s.reconnect_initial=Duration::ZERO;
            let mut stream=s.stream(request(minutes,0,1),None,Budget::from_millis(5000).unwrap()).await.unwrap();
            let mut captures=Captures::default();
            assert!(matches!(stream.next(&mut captures).await.unwrap(),StreamEvent::Recovering));
            assert!(matches!(stream.next(&mut captures).await.unwrap(),StreamEvent::Closed(_, 2, _)));
            assert!(matches!(stream.next(&mut captures).await.unwrap(),StreamEvent::Preview(_, 3, _)));
            assert!(matches!(stream.next(&mut captures).await.unwrap(),StreamEvent::Closed(_, 3, _)));
            assert!(matches!(stream.next(&mut captures).await.unwrap(),StreamEvent::Ready));
            let ws_captures=captures.observations.iter().filter(|o|o.stream=="websocket").collect::<Vec<_>>();
            assert_eq!(ws_captures.len(),2);
            assert!(ws_captures.iter().all(|o|o.receive_ns==3*stride*1_000_000));
            advance.send(()).await.unwrap();
            assert!(matches!(stream.next(&mut captures).await.unwrap(),StreamEvent::Recovering));
            assert!(matches!(stream.next(&mut captures).await.unwrap(),StreamEvent::Ready));
            stream.close().await.unwrap();socket_task.await.unwrap();
            let requests=http_task.join().unwrap();
            assert!(requests.iter().all(|r|r.contains("interval=15m")));
            assert!(requests[0].contains(&format!("startTime={}",2*stride)));
            assert!(requests[1].contains(&format!("startTime={}",3*stride)));
        });
    }
    #[test]
    fn actual_socket_binary_is_raw_only_terminal_loss_and_invalid_resume_has_no_io() {
        runtime().block_on(async {
            let (url, http_task) = http(vec![json!([row(2 * 60000, 1)]).to_string()]);
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let mut s = source(&url);
            s.ws_base = format!("ws://{}", listener.local_addr().unwrap());
            s.clock = Arc::new(MovingClock(std::sync::atomic::AtomicI64::new(
                180_000_000_000,
            )));
            for resume in [Some(-1), Some(3)] {
                assert!(matches!(
                    s.stream(request(1, 0, 1), resume, Budget::from_millis(5000).unwrap())
                        .await,
                    Err(SourceError::Invalid)
                ));
            }
            let (send, receive) = tokio::sync::oneshot::channel();
            let server = tokio::spawn(async move {
                let (tcp, _) = listener.accept().await.unwrap();
                let mut socket = tokio_tungstenite::accept_async(tcp).await.unwrap();
                receive.await.unwrap();
                socket
                    .send(Message::Binary(vec![0, 255, 1].into()))
                    .await
                    .unwrap();
            });
            let mut stream = s
                .stream(request(1, 0, 1), None, Budget::from_millis(5000).unwrap())
                .await
                .unwrap();
            let mut captures = Captures::default();
            assert!(matches!(
                stream.next(&mut captures).await.unwrap(),
                StreamEvent::Recovering
            ));
            assert!(matches!(
                stream.next(&mut captures).await.unwrap(),
                StreamEvent::Closed(_, 2, _)
            ));
            assert!(matches!(
                stream.next(&mut captures).await.unwrap(),
                StreamEvent::Ready
            ));
            send.send(()).unwrap();
            assert!(matches!(
                stream.next(&mut captures).await.unwrap(),
                StreamEvent::Lost(SourceError::Invalid)
            ));
            let raw = captures.observations.last().unwrap();
            assert_eq!(raw.bytes, vec![0, 255, 1]);
            assert!(raw.bars.is_empty());
            assert_eq!(raw.event_type, "UNKNOWN");
            stream.close().await.unwrap();
            server.await.unwrap();
            http_task.join().unwrap();
        });
    }
}

/// Controlled external inputs for the frozen technical integration consumer.
/// This module is absent from every shipped plugin build.
#[cfg(test)]
pub mod test_support {
    use super::*;
    pub fn controlled_factory(rest: &str, websocket: &str, page_size: usize) -> Arc<dyn Factory> {
        assert!(rest.starts_with("http://127.0.0.1:"));
        assert!(websocket.starts_with("ws://127.0.0.1:"));
        struct Controlled {
            installed: SpotFactory,
            rest: String,
            websocket: String,
            page_size: usize,
        }
        impl Factory for Controlled {
            fn descriptor(&self) -> &Descriptor {
                self.installed.descriptor()
            }
            fn implementation_fingerprint(&self) -> &str {
                self.installed.implementation_fingerprint()
            }
            fn validate_configuration(&self, c: &RawValue) -> Result<(), SourceError> {
                self.installed.validate_configuration(c)
            }
            fn create(
                &self,
                c: &RawValue,
                trust: &Trust,
                clock: Arc<dyn Clock>,
            ) -> Result<Arc<dyn Resource>, SourceError> {
                let mut source = Spot::new(c, trust, clock)?;
                source.rest = PublicRest::test_transport(&self.rest);
                source.rest.page_size_for_test(self.page_size);
                source.ws_base = self.websocket.clone();
                Ok(Arc::new(source))
            }
        }
        Arc::new(Controlled {
            installed: SpotFactory::installed().unwrap(),
            rest: rest.into(),
            websocket: websocket.into(),
            page_size,
        })
    }
    pub fn trust() -> Trust {
        Trust::explicit_roots(vec![super::tests::CERT.to_vec()]).unwrap()
    }
}

/// Pure explicit calendar candidate. Historical readers must match its original pin.
pub fn spot_calendar() -> Result<OnlyTradingCalendar, SourceError> {
    OnlyTradingCalendar::from_record(&json!({"schema_version":1,"calendar_id":{"schema_version":1,"value":"BINANCE-SPOT-24X7"},"venue_id":{"schema_version":1,"value":"BINANCE"},"timezone":{"schema_version":1,"name":"UTC"},"sessions":[{"schema_version":1,"name":"continuous","opens_at":"00:00:00","closes_at":"00:00:00","session_type":"CONTINUOUS","belongs_to_trading_day_offset":0,"allows_orders":true,"allows_market_data":true}],"holidays":[],"weekend_days":[],"session_profile_id":null,"special_schedules":[],"calendar_version":1,"effective_from":null,"effective_to":null})).map_err(|_|SourceError::Invalid)
}
