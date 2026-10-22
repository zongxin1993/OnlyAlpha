//! Public Spot REST acquisition. Product owns durable admission and publication;
//! these operations return original bytes and never mutate a Product store.
use onlyalpha_integration_contract::source::Trust;
use reqwest::{Client, Url, redirect, retry};
use serde_json::{Value, value::RawValue};
use std::io::Read;
use std::{
    fmt,
    time::{Duration, Instant},
};

const RESPONSE_BUDGET: usize = 8 * 1024 * 1024;
const MINUTE_MS: i64 = 60_000;
pub const NATIVE_MINUTES: [u16; 8] = [1, 3, 5, 15, 30, 60, 120, 240];
pub fn native_interval(minutes: u16) -> Result<(&'static str, i64)> {
    let interval = match minutes {
        1 => "1m",
        3 => "3m",
        5 => "5m",
        15 => "15m",
        30 => "30m",
        60 => "1h",
        120 => "2h",
        240 => "4h",
        _ => return Err(Error::Range),
    };
    Ok((interval, i64::from(minutes) * MINUTE_MS))
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Configuration,
    Request,
    Deadline,
    Status,
    MediaType,
    Encoding,
    TooLarge,
    Json,
    Shape,
    Range,
    Order,
    Evidence,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Configuration => "BINANCE_PLUGIN_CONFIG_INVALID",
            Self::Request => "BINANCE_PUBLIC_REQUEST_FAILED",
            Self::Deadline => "BINANCE_PUBLIC_REQUEST_DEADLINE_EXCEEDED",
            Self::Status => "BINANCE_HTTP_STATUS",
            Self::MediaType => "BINANCE_PUBLIC_RESPONSE_MEDIA_TYPE_INVALID",
            Self::Encoding => "BINANCE_PUBLIC_RESPONSE_ENCODING_UNSUPPORTED",
            Self::TooLarge => "BINANCE_PUBLIC_RESPONSE_TOO_LARGE",
            Self::Json => "BINANCE_PUBLIC_RESPONSE_NOT_JSON",
            Self::Shape => "BINANCE_PUBLIC_RESPONSE_SHAPE_INVALID",
            Self::Range => "BINANCE_KLINE_RANGE_INVALID",
            Self::Order => "BINANCE_KLINE_PAGE_ORDER_INVALID",
            Self::Evidence => "BINANCE_RAW_EVIDENCE_UNAVAILABLE",
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}
pub type Result<T> = std::result::Result<T, Error>;

/// Raw provider bytes are retained for the caller's durable evidence recorder.
/// Parsed values confer no canonical fact or COMPLETE coverage authority.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RequestContext {
    source_id: &'static str,
    rest_base: String,
    path: String,
    parameters: Vec<(String, String)>,
}
impl RequestContext {
    pub fn source_id(&self) -> &str {
        self.source_id
    }
    pub fn rest_base(&self) -> &str {
        &self.rest_base
    }
    pub fn path(&self) -> &str {
        &self.path
    }
    pub fn parameter(&self, key: &str) -> Option<&str> {
        self.parameters
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.as_str())
    }
}

pub struct PublicResponse {
    request: RequestContext,
    bytes: Vec<u8>,
    value: Value,
}
impl PublicResponse {
    pub fn request(&self) -> &RequestContext {
        &self.request
    }

    /// Decode only for the exact source and provider symbol that produced this
    /// private response. This does not grant Seal or storage publication authority.
    pub fn canonical_bars(
        &self,
        source_id: &str,
        instrument: &onlyalpha_domain::instrument::OnlyInstrument,
    ) -> Result<Vec<onlyalpha_domain::market::OnlyBar>> {
        if self.request.source_id() != source_id
            || self.request.path() != "/api/v3/klines"
            || self.request.parameter("symbol")
                != Some(instrument.specification().raw_symbol().value())
        {
            return Err(Error::Shape);
        }
        let minutes = NATIVE_MINUTES
            .into_iter()
            .find(|m| {
                native_interval(*m)
                    .is_ok_and(|(i, _)| Some(i) == self.request.parameter("interval"))
            })
            .ok_or(Error::Range)?;
        self.value
            .as_array()
            .ok_or(Error::Shape)?
            .iter()
            .map(|row| crate::spot_normalize::rest_bar_interval(row, instrument, minutes))
            .collect()
    }
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
    pub fn value(&self) -> &Value {
        &self.value
    }
}
#[derive(Clone)]
pub struct PublicRest {
    client: Client,
    base: Url,
    source_id: &'static str,
    timeout: Duration,
    response_limit: usize,
    page_size: usize,
}
impl PublicRest {
    #[cfg(test)]
    pub(crate) fn page_size_for_test(&mut self, n: usize) {
        self.page_size = n;
    }

    #[cfg(test)]
    pub(crate) fn test_transport(base: &str) -> Self {
        let mut client = Self::configured(
            RawValue::from_string("{}".into()).unwrap().as_ref(),
            64 * 1024 * 1024,
            &[],
        )
        .unwrap();
        client.base = Url::parse(base).unwrap();
        client
    }

    /// Consume an already selected exact Integration public configuration. No
    /// provider endpoint discovery, fallback or credential surface exists.
    /// TLS trust is immutable, explicit Host input. No ambient proxy or CA discovery.
    pub fn from_configuration(input: &RawValue, work: usize, trust: &Trust) -> Result<Self> {
        Self::configured(input, work, trust.roots_pem())
    }
    pub(crate) fn configured(input: &RawValue, work: usize, roots: &[Vec<u8>]) -> Result<Self> {
        crate::spot_authoring(work)
            .and_then(|r| r.validate_public_configuration(input, work))
            .map_err(|_| Error::Configuration)?;
        let values: Value = serde_json::from_str(input.get()).map_err(|_| Error::Configuration)?;
        let environment = values["environment"].as_str().unwrap_or("GLOBAL");
        let default_profile = if environment == "GLOBAL" {
            "PUBLIC_MARKET_DATA"
        } else {
            "DEFAULT"
        };
        let profile = values["endpoint_profile"]
            .as_str()
            .unwrap_or(default_profile);
        let (rest, source_id) = match (environment, profile) {
            ("GLOBAL", p) => {
                let rest = match p {
                    "PUBLIC_MARKET_DATA" => "https://data-api.binance.vision",
                    "STANDARD" => "https://api.binance.com",
                    "GCP" => "https://api-gcp.binance.com",
                    "API1" => "https://api1.binance.com",
                    "API2" => "https://api2.binance.com",
                    "API3" => "https://api3.binance.com",
                    "API4" => "https://api4.binance.com",
                    _ => return Err(Error::Configuration),
                };
                (rest, "binance.spot.market_data.live")
            }
            ("US", "DEFAULT") => ("https://api.binance.us", "binance.spot.market_data.us"),
            ("SPOT_TESTNET", p) if matches!(p, "DEFAULT" | "GCP") => (
                if p == "GCP" {
                    "https://api1.testnet.binance.vision"
                } else {
                    "https://testnet.binance.vision"
                },
                "binance.spot.market_data.spot_testnet",
            ),
            _ => return Err(Error::Configuration),
        };
        let seconds = values
            .get("timeout_seconds")
            .map(|v| v.as_f64().ok_or(Error::Configuration))
            .transpose()?
            .unwrap_or(10.0);
        let timeout = Duration::try_from_secs_f64(seconds).map_err(|_| Error::Configuration)?;
        let limit = values
            .get("max_response_bytes")
            .map(|v| {
                v.as_u64()
                    .and_then(|n| usize::try_from(n).ok())
                    .ok_or(Error::Configuration)
            })
            .transpose()?
            .unwrap_or(RESPONSE_BUDGET);
        let page_size = values
            .get("rest_page_size")
            .map(|v| {
                v.as_u64()
                    .and_then(|n| usize::try_from(n).ok())
                    .ok_or(Error::Configuration)
            })
            .transpose()?
            .unwrap_or(1000);
        let certs = roots
            .iter()
            .map(|r| reqwest::Certificate::from_pem(r).map_err(|_| Error::Configuration))
            .collect::<Result<Vec<_>>>()?;
        let client = Client::builder()
            .redirect(redirect::Policy::none())
            .retry(retry::never())
            .no_proxy()
            .http1_only()
            .tls_certs_only(certs)
            .tls_sslkeylogfile(false)
            .connect_timeout(timeout)
            .timeout(timeout)
            .build()
            .map_err(|_| Error::Request)?;
        Ok(Self {
            client,
            base: Url::parse(rest).map_err(|_| Error::Configuration)?,
            source_id,
            timeout,
            response_limit: limit.min(RESPONSE_BUDGET),
            page_size,
        })
    }
    pub fn source_id(&self) -> &str {
        self.source_id
    }
    pub fn rest_base(&self) -> &str {
        self.base.as_str().trim_end_matches('/')
    }

    async fn get(
        &self,
        path: &str,
        parameters: &[(&str, String)],
        deadline: Instant,
    ) -> Result<PublicResponse> {
        self.get_observed(path, parameters, deadline, &mut |_, _| Ok(()))
            .await
    }
    async fn get_observed<F>(
        &self,
        path: &str,
        parameters: &[(&str, String)],
        deadline: Instant,
        capture: &mut F,
    ) -> Result<PublicResponse>
    where
        F: FnMut(&RequestContext, &[u8]) -> Result<()>,
    {
        let request = RequestContext {
            source_id: self.source_id,
            rest_base: self.rest_base().into(),
            path: path.into(),
            parameters: parameters
                .iter()
                .map(|(k, v)| ((*k).into(), v.clone()))
                .collect(),
        };
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .filter(|d| !d.is_zero())
            .ok_or(Error::Deadline)?;
        let mut url = self.base.join(path).map_err(|_| Error::Configuration)?;
        if !parameters.is_empty() {
            let mut query = url.query_pairs_mut();
            for (key, value) in parameters {
                query.append_pair(key, value);
            }
        }
        let mut response = self
            .client
            .get(url)
            .header("Accept", "application/json")
            .header("Accept-Encoding", "gzip")
            .timeout(remaining.min(self.timeout))
            .send()
            .await
            .map_err(|e| {
                if e.is_timeout() {
                    Error::Deadline
                } else {
                    Error::Request
                }
            })?;
        if response.status() != reqwest::StatusCode::OK {
            return Err(Error::Status);
        }
        let media = response
            .headers()
            .get("content-type")
            .and_then(|h| h.to_str().ok())
            .ok_or(Error::MediaType)?
            .split(';')
            .next()
            .ok_or(Error::MediaType)?
            .trim()
            .to_ascii_lowercase();
        if media != "application/json"
            && !(media.starts_with("application/") && media.ends_with("+json"))
        {
            return Err(Error::MediaType);
        }
        let encoding = response
            .headers()
            .get("content-encoding")
            .map(|h| h.to_str().map(str::to_owned).map_err(|_| Error::Encoding))
            .transpose()?
            .unwrap_or_else(|| "identity".into());
        if !matches!(encoding.as_str(), "identity" | "gzip") {
            return Err(Error::Encoding);
        }
        if response
            .content_length()
            .is_some_and(|n| n > self.response_limit as u64)
        {
            return Err(Error::TooLarge);
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = response.chunk().await.map_err(|e| {
            if e.is_timeout() {
                Error::Deadline
            } else {
                Error::Request
            }
        })? {
            if chunk.len() > self.response_limit.saturating_sub(bytes.len()) {
                return Err(Error::TooLarge);
            }
            bytes.extend_from_slice(&chunk);
        }
        if encoding == "gzip" {
            bytes = decode_gzip(&bytes, self.response_limit)?;
        }
        if Instant::now() >= deadline {
            return Err(Error::Deadline);
        }
        // The owning recorder must finish its durable write before decode or
        // the next request. Malformed JSON remains an observed provider input.
        capture(&request, &bytes).map_err(|_| Error::Evidence)?;
        let value = decode_json(&bytes)?;
        Ok(PublicResponse {
            request,
            bytes,
            value,
        })
    }
    pub async fn ping(&self, deadline: Instant) -> Result<()> {
        let response = self.get("/api/v3/ping", &[], deadline).await?;
        if response.value != serde_json::json!({}) {
            return Err(Error::Shape);
        }
        Ok(())
    }
    pub async fn server_time(&self, deadline: Instant) -> Result<i64> {
        let response = self.get("/api/v3/time", &[], deadline).await?;
        response.value["serverTime"]
            .as_i64()
            .filter(|n| *n > 0)
            .ok_or(Error::Shape)
    }
    pub async fn exchange_info(
        &self,
        symbols: &[String],
        deadline: Instant,
    ) -> Result<PublicResponse> {
        if symbols.len() > 25
            || symbols.iter().any(|s| !symbol(s))
            || symbols
                .iter()
                .collect::<std::collections::BTreeSet<_>>()
                .len()
                != symbols.len()
        {
            return Err(Error::Range);
        }
        let mut parameters = vec![("showPermissionSets", "false".into())];
        if symbols.is_empty() {
            parameters.push(("permissions", "SPOT".into()));
        } else {
            parameters.push((
                "symbols",
                serde_json::to_string(symbols).map_err(|_| Error::Range)?,
            ));
        }
        let response = self
            .get("/api/v3/exchangeInfo", &parameters, deadline)
            .await?;
        let rows = response.value["symbols"].as_array().ok_or(Error::Shape)?;
        let mut seen = std::collections::BTreeSet::new();
        for row in rows {
            let id = row["symbol"]
                .as_str()
                .filter(|s| symbol(s))
                .ok_or(Error::Shape)?;
            if !seen.insert(id) || (!symbols.is_empty() && !symbols.iter().any(|s| s == id)) {
                return Err(Error::Shape);
            }
        }
        Ok(response)
    }
    pub async fn tickers(&self, symbols: &[String], deadline: Instant) -> Result<PublicResponse> {
        if symbols.is_empty()
            || symbols.len() > 25
            || symbols.iter().any(|s| !symbol(s))
            || symbols
                .iter()
                .collect::<std::collections::BTreeSet<_>>()
                .len()
                != symbols.len()
        {
            return Err(Error::Range);
        }
        let response = self
            .get(
                "/api/v3/ticker/24hr",
                &[(
                    "symbols",
                    serde_json::to_string(symbols).map_err(|_| Error::Range)?,
                )],
                deadline,
            )
            .await?;
        let rows = response.value.as_array().ok_or(Error::Shape)?;
        let mut seen = std::collections::BTreeSet::new();
        for row in rows {
            let id = row["symbol"].as_str().ok_or(Error::Shape)?;
            if !symbols.iter().any(|s| s == id) || !seen.insert(id) {
                return Err(Error::Shape);
            }
        }
        Ok(response)
    }
    /// Acquire only canonical provider-base 1m rows. Capture is mandatory and
    /// runs before JSON decoding; Product must supply its durable WAL recorder.
    /// The returned pages alone do not prove persistence or COMPLETE coverage.
    /// One deadline covers every page; no automatic retry or source substitution.
    pub async fn historical_klines_observed<F>(
        &self,
        symbol_id: &str,
        start_ms: i64,
        end_ms: i64,
        deadline: Instant,
        capture: &mut F,
    ) -> Result<Vec<PublicResponse>>
    where
        F: FnMut(&RequestContext, &[u8]) -> Result<()>,
    {
        self.historical_interval_observed(symbol_id, 1, start_ms, end_ms, deadline, capture)
            .await
    }
    pub async fn historical_interval_observed<F>(
        &self,
        symbol_id: &str,
        minutes: u16,
        start_ms: i64,
        end_ms: i64,
        deadline: Instant,
        capture: &mut F,
    ) -> Result<Vec<PublicResponse>>
    where
        F: FnMut(&RequestContext, &[u8]) -> Result<()>,
    {
        let (interval, stride) = native_interval(minutes)?;
        if !symbol(symbol_id)
            || start_ms < 0
            || start_ms >= end_ms
            || start_ms % stride != 0
            || end_ms % stride != 0
            || end_ms - start_ms > 7 * 24 * 60 * MINUTE_MS
        {
            return Err(Error::Range);
        }
        let mut cursor = start_ms;
        let mut pages = Vec::new();
        let mut used = 0usize;
        while cursor < end_ms {
            let response = self
                .get_observed(
                    "/api/v3/klines",
                    &[
                        ("symbol", symbol_id.into()),
                        ("interval", interval.into()),
                        ("startTime", cursor.to_string()),
                        ("endTime", (end_ms - 1).to_string()),
                        ("limit", self.page_size.to_string()),
                    ],
                    deadline,
                    capture,
                )
                .await?;
            used = used
                .checked_add(response.bytes.len())
                .filter(|n| *n <= RESPONSE_BUDGET)
                .ok_or(Error::TooLarge)?;
            let rows = response
                .value
                .as_array()
                .filter(|r| r.len() <= self.page_size)
                .ok_or(Error::Shape)?;
            let mut previous = None;
            for row in rows {
                let row = row
                    .as_array()
                    .filter(|r| r.len() >= 11)
                    .ok_or(Error::Shape)?;
                let opened = row[0].as_i64().ok_or(Error::Shape)?;
                if opened < cursor || opened >= end_ms || opened % stride != 0 {
                    return Err(Error::Range);
                }
                if previous.is_some_and(|p| p >= opened) {
                    return Err(Error::Order);
                }
                previous = Some(opened);
            }
            let count = rows.len();
            let next = previous
                .map(|p| p.checked_add(stride).ok_or(Error::Range))
                .transpose()?;
            pages.push(response);
            match next {
                Some(n) if n > cursor => cursor = n,
                None => break,
                _ => return Err(Error::Order),
            }
            if count < self.page_size {
                break;
            }
        }
        Ok(pages)
    }
}
pub(crate) fn decode_json(bytes: &[u8]) -> Result<Value> {
    let text = std::str::from_utf8(bytes).map_err(|_| Error::Json)?;
    // Reuse the existing bounded duplicate-key/number parser; do not accept
    // conflicting provider fields or replace the retained original bytes.
    let original =
        onlyalpha_metadata_json::canonical_json(text, RESPONSE_BUDGET * 8).map_err(|e| {
            if e == onlyalpha_metadata_json::Error::Unavailable {
                Error::TooLarge
            } else {
                Error::Json
            }
        })?;
    let value: Value = serde_json::from_str(text).map_err(|_| Error::Json)?;
    // Serde implementation marker keys are ordinary provider object keys.
    // Prove the decoded tree still represents the original JSON before any
    // timestamp/price/type access can grant them scalar meaning.
    let decoded = serde_json::to_string(&value).map_err(|_| Error::Json)?;
    let restored =
        onlyalpha_metadata_json::canonical_json(&decoded, RESPONSE_BUDGET * 8).map_err(|e| {
            if e == onlyalpha_metadata_json::Error::Unavailable {
                Error::TooLarge
            } else {
                Error::Json
            }
        })?;
    if original != restored {
        return Err(Error::Json);
    }
    if !value.is_array() && !value.is_object() {
        return Err(Error::Shape);
    }
    Ok(value)
}
fn decode_gzip(bytes: &[u8], limit: usize) -> Result<Vec<u8>> {
    let decoder = flate2::bufread::MultiGzDecoder::new(bytes);
    let mut out = Vec::new();
    decoder
        .take(limit as u64 + 1)
        .read_to_end(&mut out)
        .map_err(|_| Error::Encoding)?;
    if out.len() > limit {
        return Err(Error::TooLarge);
    }
    Ok(out)
}
fn symbol(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::value::RawValue;
    fn test_configuration(input: &RawValue, work: usize) -> Result<PublicRest> {
        PublicRest::configured(input, work, &[])
    }

    #[test]
    fn configured_public_transport_keeps_market_environments_distinct() {
        let global =
            test_configuration(RawValue::from_string("{}".into()).unwrap().as_ref(), 65536)
                .unwrap();
        assert_eq!(global.source_id(), "binance.spot.market_data.live");
        assert_eq!(global.rest_base(), "https://data-api.binance.vision");
        let us = test_configuration(
            RawValue::from_string(r#"{"environment":"US"}"#.into())
                .unwrap()
                .as_ref(),
            65536,
        )
        .unwrap();
        assert_eq!(us.source_id(), "binance.spot.market_data.us");
        assert_eq!(us.rest_base(), "https://api.binance.us");
        let testnet = test_configuration(
            RawValue::from_string(r#"{"environment":"SPOT_TESTNET"}"#.into())
                .unwrap()
                .as_ref(),
            65536,
        )
        .unwrap();
        assert_eq!(testnet.source_id(), "binance.spot.market_data.spot_testnet");
        assert_eq!(testnet.rest_base(), "https://testnet.binance.vision");
        assert!(
            test_configuration(
                RawValue::from_string(r#"{"environment":"US","endpoint_profile":"API1"}"#.into())
                    .unwrap()
                    .as_ref(),
                65536
            )
            .is_err()
        );
        assert!(
            test_configuration(
                RawValue::from_string(r#"{"rest_base_url":"http://127.0.0.1"}"#.into())
                    .unwrap()
                    .as_ref(),
                65536
            )
            .is_err()
        );
    }
    fn runtime() -> tokio::runtime::Runtime {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
    }
    fn fixture(
        replies: Vec<String>,
    ) -> (
        PublicRest,
        std::sync::mpsc::Receiver<String>,
        std::thread::JoinHandle<()>,
    ) {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let (tx, rx) = std::sync::mpsc::channel();
        let task = std::thread::spawn(move || {
            for reply in replies {
                let (mut stream, _) = listener.accept().unwrap();
                stream
                    .set_read_timeout(Some(std::time::Duration::from_secs(2)))
                    .unwrap();
                let mut request = Vec::new();
                let mut byte = [0];
                while !request.ends_with(b"\r\n\r\n") {
                    assert!(request.len() < 16384);
                    stream.read_exact(&mut byte).unwrap();
                    request.push(byte[0]);
                }
                tx.send(String::from_utf8(request).unwrap()).unwrap();
                stream.write_all(reply.as_bytes()).unwrap();
            }
        });
        let mut client =
            test_configuration(RawValue::from_string("{}".into()).unwrap().as_ref(), 65536)
                .unwrap();
        client.base = reqwest::Url::parse(&base).unwrap();
        (client, rx, task)
    }
    fn ok(body: &str) -> String {
        format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body
        )
    }
    #[test]
    fn real_public_transport_downloads_exact_pages_and_keeps_raw_evidence() {
        runtime().block_on(async {
            let first = r#"[[0,"1","2","1","2","3",59999,"6",4,"0","0","0"],[60000,"2","3","2","3","4",119999,"12",5,"0","0","0"]]"#;
            let second = r#"[[120000,"3","4","3","4","5",179999,"20",6,"0","0","0"]]"#;
            let (mut client, requests, server) = fixture(vec![ok(first), ok(second)]);
            client.page_size = 2;
            let pages = client.historical_klines_observed("BTCUSDT", 0, 180000, std::time::Instant::now()+std::time::Duration::from_secs(5), &mut |_, _| Ok(())).await.unwrap();
            assert_eq!(pages.len(), 2);
            assert_eq!(pages[0].bytes(), first.as_bytes());
            assert_eq!(pages[1].bytes(), second.as_bytes());
            let a = requests.recv().unwrap(); let b = requests.recv().unwrap();
            assert!(a.starts_with("GET /api/v3/klines?"));
            assert!(a.contains("symbol=BTCUSDT") && a.contains("interval=1m") && a.contains("startTime=0") && a.contains("endTime=179999"));
            assert!(b.contains("startTime=120000"));
            server.join().unwrap();
        });
    }
    #[test]
    fn public_transport_refuses_redirect_media_duplicate_keys_and_oversized_bodies() {
        runtime().block_on(async {
            for response in [
                "HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:9/stolen\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".into(),
                "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}".into(),
                ok(r#"{"serverTime":1,"serverTime":2}"#),
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 9000000\r\nConnection: close\r\n\r\n".into(),
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Encoding: br\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}".into(),
            ] {
                let (client, requests, server) = fixture(vec![response]);
                assert!(client.server_time(std::time::Instant::now()+std::time::Duration::from_secs(5)).await.is_err());
                assert!(requests.recv().unwrap().starts_with("GET /api/v3/time "));
                server.join().unwrap();
            }
        });
    }
    #[test]
    fn historical_page_conflicts_are_rejected_without_automatic_retry() {
        runtime().block_on(async {
            let row = |opened: Value| {
                serde_json::json!([
                    opened, "1", "2", "1", "2", "3", 59999, "6", 4, "0", "0", "0"
                ])
            };
            for (rows, expected) in [
                (vec![row(60000.into()), row(0.into())], Error::Order),
                (vec![row(0.into()), row(0.into())], Error::Order),
                (vec![row(180000.into())], Error::Range),
                (vec![row(1.into())], Error::Range),
                (vec![row((-60000).into())], Error::Range),
                (vec![row("0".into())], Error::Shape),
            ] {
                let (client, requests, server) =
                    fixture(vec![ok(&serde_json::to_string(&rows).unwrap())]);
                let result = client
                    .historical_klines_observed(
                        "BTCUSDT",
                        0,
                        180000,
                        Instant::now() + Duration::from_secs(5),
                        &mut |_, _| Ok(()),
                    )
                    .await;
                assert_eq!(result.err(), Some(expected));
                assert!(requests.recv().unwrap().contains("symbol=BTCUSDT"));
                server.join().unwrap();
            }
        });
    }
    #[test]
    fn capture_precedes_decode_and_survives_later_page_failure() {
        runtime().block_on(async {
            let row = r#"[[0,"1","2","1","2","3",59999,"6",4,"0","0","0"]]"#;
            let (mut client, requests, server) = fixture(vec![ok(row), ok("not JSON")]);
            client.page_size = 1;
            let mut captured = Vec::new();
            let result = client
                .historical_klines_observed(
                    "BTCUSDT",
                    0,
                    120000,
                    Instant::now() + Duration::from_secs(5),
                    &mut |request, bytes| {
                        assert_eq!(request.source_id(), "binance.spot.market_data.live");
                        assert_eq!(request.path(), "/api/v3/klines");
                        assert_eq!(request.parameter("symbol"), Some("BTCUSDT"));
                        captured.push(bytes.to_vec());
                        Ok(())
                    },
                )
                .await;
            assert_eq!(result.err(), Some(Error::Json));
            assert_eq!(
                captured,
                vec![row.as_bytes(), b"not JSON"]
                    .into_iter()
                    .map(Vec::from)
                    .collect::<Vec<_>>()
            );
            assert!(requests.recv().unwrap().contains("startTime=0"));
            assert!(requests.recv().unwrap().contains("startTime=60000"));
            server.join().unwrap();
        });
    }
    #[test]
    fn provider_json_objects_cannot_impersonate_prices_or_timestamps() {
        runtime().block_on(async {
            for body in [
                r#"[[{"$serde_json::private::Number":"0"},"1","2","1","2","3",59999,"6",4,"0","0","0"]]"#,
                r#"[[0,{"$serde_json::private::RawValue":"\"1\""},"2","1","2","3",59999,"6",4,"0","0","0"]]"#,
                r#"[[0,{"$serde_json::private::RawValue":"\"1\"","sibling":1},"2","1","2","3",59999,"6",4,"0","0","0"]]"#,
            ] {
                let (client, requests, server) = fixture(vec![ok(body)]);
                let mut captured = Vec::new();
                let result = client.historical_klines_observed("BTCUSDT", 0, 60000,
                    Instant::now()+Duration::from_secs(5), &mut |_, bytes| {
                        captured.push(bytes.to_vec()); Ok(())
                    }).await;
                assert!(result.is_err(), "provider objects must retain their original JSON kind");
                assert_eq!(captured, vec![body.as_bytes().to_vec()]);
                requests.recv().unwrap(); server.join().unwrap();
            }
            let (client, requests, server) = fixture(vec![ok(r#"{"serverTime":1,"ordinary_float":1.5}"#)]);
            assert_eq!(client.server_time(Instant::now()+Duration::from_secs(5)).await.unwrap(), 1);
            requests.recv().unwrap(); server.join().unwrap();
        });
    }
    #[test]
    fn canonical_bars_are_bound_to_the_actual_source_request_and_instrument() {
        runtime().block_on(async {
            let instrument = crate::spot_normalize::instrument(&serde_json::json!({
                "symbol":"BTCUSDT","baseAsset":"BTC","quoteAsset":"USDT","status":"TRADING",
                "filters":[{"filterType":"PRICE_FILTER","tickSize":"0.01"},
                {"filterType":"LOT_SIZE","stepSize":"0.00001","minQty":"0.00001"}]}))
            .unwrap();
            let row = r#"[[0,"1","2","1","2","3",59999,"6",4,"0","0","0"]]"#;
            for requested in ["BTCUSDT", "ETHUSDT"] {
                let (client, requests, server) = fixture(vec![ok(row)]);
                let pages = client
                    .historical_klines_observed(
                        requested,
                        0,
                        60000,
                        Instant::now() + Duration::from_secs(5),
                        &mut |_, _| Ok(()),
                    )
                    .await
                    .unwrap();
                let page = &pages[0];
                assert_eq!(page.request().parameter("symbol"), Some(requested));
                assert!(!page.request().rest_base().is_empty());
                assert_eq!(
                    page.canonical_bars("binance.spot.market_data.live", &instrument)
                        .is_ok(),
                    requested == "BTCUSDT"
                );
                assert!(
                    page.canonical_bars("binance.spot.market_data.us", &instrument)
                        .is_err()
                );
                requests.recv().unwrap();
                server.join().unwrap();
            }
        });
    }
    #[test]
    fn failed_capture_stops_before_another_request_or_success() {
        runtime().block_on(async {
            let row = r#"[[0,"1","2","1","2","3",59999,"6",4,"0","0","0"]]"#;
            let (mut client, requests, server) = fixture(vec![ok(row)]);
            client.page_size = 1;
            let result = client
                .historical_klines_observed(
                    "BTCUSDT",
                    0,
                    120000,
                    Instant::now() + Duration::from_secs(5),
                    &mut |_, _| Err(Error::Evidence),
                )
                .await;
            assert_eq!(result.err(), Some(Error::Evidence));
            requests.recv().unwrap();
            server.join().unwrap();
        });
    }
    #[test]
    fn invalid_symbols_ranges_and_expired_deadlines_cannot_start_network_io() {
        runtime().block_on(async {
            let client =
                test_configuration(RawValue::from_string("{}".into()).unwrap().as_ref(), 65536)
                    .unwrap();
            let deadline = std::time::Instant::now() + std::time::Duration::from_secs(1);
            assert!(
                client
                    .historical_klines_observed(
                        "BTCUSDT&symbol=ETHUSDT",
                        0,
                        60000,
                        deadline,
                        &mut |_, _| Ok(())
                    )
                    .await
                    .is_err()
            );
            assert!(
                client
                    .historical_klines_observed("BTCUSDT", 1, 60000, deadline, &mut |_, _| Ok(()))
                    .await
                    .is_err()
            );
            assert!(
                client
                    .historical_klines_observed("BTCUSDT", 60000, 0, deadline, &mut |_, _| Ok(()))
                    .await
                    .is_err()
            );
            assert!(
                client
                    .historical_klines_observed(
                        "BTCUSDT",
                        0,
                        60000,
                        std::time::Instant::now(),
                        &mut |_, _| Ok(())
                    )
                    .await
                    .is_err()
            );
        });
    }
}

#[cfg(test)]
mod gzip_regressions {
    use super::*;
    use std::io::Write;
    fn compressed(data: &[u8]) -> Vec<u8> {
        let mut writer = flate2::write::GzEncoder::new(vec![], flate2::Compression::default());
        writer.write_all(data).unwrap();
        writer.finish().unwrap()
    }
    #[test]
    fn complete_multimember_gzip_has_independent_bounds_and_no_partial_acceptance() {
        let a = compressed(b"[1,");
        let b = compressed(b"2]");
        let both = [a.clone(), b.clone()].concat();
        assert_eq!(decode_gzip(&both, 10).unwrap(), b"[1,2]");
        assert_eq!(decode_gzip(&both, 4), Err(Error::TooLarge));
        let mut wrong = both.clone();
        wrong[12] ^= 0xff;
        assert!(decode_gzip(&wrong, 100).is_err());
        for n in [1, 8, both.len() - 1] {
            assert!(decode_gzip(&both[..n], 100).is_err());
        }
        let mut trailing = both;
        trailing.extend_from_slice(b"garbage");
        assert!(decode_gzip(&trailing, 100).is_err());
    }
}
