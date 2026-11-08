use crate::{Result, err};
use hmac::{Hmac, KeyInit, Mac};
use onlyalpha_broker::DispatchResult;
use serde_json::Value;
use sha2::Sha256;
use std::collections::BTreeMap;
use zeroize::Zeroizing;

/// 宿主从当前 Slot 解析内存凭据；无 Debug、序列化和环境变量回退。
pub struct Credentials {
    pub(crate) key: Zeroizing<String>,
    secret: Zeroizing<String>,
}
impl Credentials {
    pub fn new(key: String, secret: String) -> Result<Self> {
        let key = Zeroizing::new(key);
        let secret = Zeroizing::new(secret);
        if [&key, &secret]
            .iter()
            .any(|s| s.is_empty() || s.len() > 4096 || !s.bytes().all(|b| b.is_ascii_graphic()))
        {
            return Err(err("BINANCE_INVALID_CREDENTIALS"));
        }
        Ok(Self { key, secret })
    }
    pub(crate) fn sign(&self, data: &[u8]) -> Result<String> {
        signature(self.secret.as_bytes(), data)
    }
}
pub(crate) fn signature(secret: &[u8], payload: &[u8]) -> Result<String> {
    let mut mac =
        Hmac::<Sha256>::new_from_slice(secret).map_err(|_| err("BINANCE_SIGNING_ERROR"))?;
    mac.update(payload);
    Ok(crate::hex(&mac.finalize().into_bytes()))
}
pub(crate) fn signed_query(
    keys: &Credentials,
    params: &BTreeMap<String, String>,
    timestamp: u64,
    window: u64,
) -> Result<Zeroizing<String>> {
    if !(1..=60_000).contains(&window)
        || params.keys().any(|k| {
            matches!(
                k.as_str(),
                "recvWindow" | "timestamp" | "signature" | "apiKey"
            )
        })
    {
        return Err(err("BINANCE_REQUEST_PARAMETERS"));
    }
    let mut params = params.clone();
    params.insert("recvWindow".into(), window.to_string());
    params.insert("timestamp".into(), timestamp.to_string());
    let mut url = reqwest::Url::parse("https://localhost").expect("fixed URL");
    url.query_pairs_mut().extend_pairs(params.iter());
    let query = url.query().ok_or_else(|| err("BINANCE_QUERY"))?;
    Ok(Zeroizing::new(format!(
        "{query}&signature={}",
        keys.sign(query.as_bytes())?
    )))
}
pub(crate) fn error_outcome(status: u16, code: Option<i64>) -> DispatchResult {
    match (status, code) {
        // 明确的签名、时钟、权限或参数拦截；未知 code、重复 client 和代理错误保留原操作。
        (
            400 | 401 | 403,
            Some(
                -1021 | -1022 | -1100 | -1101 | -1102 | -1103 | -1104 | -1105 | -1106 | -1111
                | -1114 | -1115 | -1116 | -1117 | -1121 | -1130 | -2014 | -2015,
            ),
        ) => DispatchResult::Rejected,
        _ => DispatchResult::Unknown,
    }
}
pub(crate) fn wire_json(bytes: &[u8]) -> Result<Value> {
    if bytes.is_empty() || bytes.len() > 8 * 1024 * 1024 {
        return Err(err("BINANCE_RESPONSE_SIZE"));
    }
    let raw = std::str::from_utf8(bytes).map_err(|_| err("BINANCE_RESPONSE_UTF8"))?;
    onlyalpha_metadata_json::canonical_json(raw, bytes.len().saturating_mul(16))
        .map_err(|_| err("BINANCE_RESPONSE_AMBIGUOUS"))?;
    serde_json::from_slice(bytes).map_err(|_| err("BINANCE_RESPONSE_JSON"))
}
#[cfg(test)]
#[path = "tests/private_protocol.rs"]
mod tests;

use crate::stream::Socket;
use crate::{Config, Environment};
use onlyalpha_integration_contract::source::{Clock, Trust};
use reqwest::{
    Client, Method,
    header::{CONTENT_ENCODING, CONTENT_TYPE, HeaderValue, RETRY_AFTER},
    redirect, retry,
};
use rustls::pki_types::{CertificateDer, pem::PemObject};
use std::{
    cell::{Cell, RefCell},
    future::Future,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::runtime::{Builder, Handle, Runtime};

/// 一次公开操作共享截止时刻和请求次数，翻页只消费同一个预算。
pub(crate) struct Budget {
    pub(crate) until: Instant,
    calls: Cell<usize>,
}
impl Budget {
    pub(crate) fn new(timeout_ms: u64, calls: usize) -> Self {
        Self {
            until: Instant::now() + Duration::from_millis(timeout_ms),
            calls: Cell::new(calls),
        }
    }
    fn take(&self) -> Result<Duration> {
        let remaining = self
            .until
            .checked_duration_since(Instant::now())
            .filter(|d| !d.is_zero())
            .ok_or_else(|| err("BINANCE_DEADLINE"))?;
        self.calls.set(
            self.calls
                .get()
                .checked_sub(1)
                .ok_or_else(|| err("BINANCE_REQUEST_BUDGET"))?,
        );
        Ok(remaining)
    }
}
pub(crate) struct Response {
    pub status: u16,
    pub bytes: Vec<u8>,
    pub retry_after_ms: Option<u64>,
}
pub(crate) trait Exchange {
    fn request(
        &self,
        method: &str,
        path: &str,
        params: &BTreeMap<String, String>,
        budget: &Budget,
    ) -> Result<Response>;
    fn subscribe(&self, id: &str, budget: &Budget) -> Result<Vec<u8>>;
    fn next(&self, budget: &Budget) -> Result<Vec<u8>>;
    fn close(&self);
    fn preflight(&self, budget: &Budget) -> Result<()>;
}
pub(crate) struct Native {
    client: Client,
    pub(crate) keys: Credentials,
    pub(crate) clock: Arc<dyn Clock>,
    rt: Option<Runtime>,
    pub(crate) tls: Arc<rustls::ClientConfig>,
    pub(crate) socket: RefCell<Option<Socket>>,
    rest: String,
    pub(crate) ws: String,
    pub(crate) window: u64,
    pub(crate) limit: usize,
    blocked_until: Cell<Option<Instant>>,
}
impl Native {
    pub(crate) fn new(
        c: &Config,
        keys: Credentials,
        trust: &Trust,
        clock: Arc<dyn Clock>,
    ) -> Result<Self> {
        let mut certs = Vec::new();
        let mut roots = rustls::RootCertStore::empty();
        for pem in trust.roots_pem() {
            let bundle =
                reqwest::Certificate::from_pem_bundle(pem).map_err(|_| err("BINANCE_TLS_ROOT"))?;
            if bundle.is_empty() {
                return Err(err("BINANCE_TLS_ROOT"));
            }
            certs.extend(bundle);
            for cert in CertificateDer::pem_slice_iter(pem) {
                roots
                    .add(cert.map_err(|_| err("BINANCE_TLS_ROOT"))?)
                    .map_err(|_| err("BINANCE_TLS_ROOT"))?;
            }
        }
        let tls = rustls::ClientConfig::builder_with_provider(Arc::new(
            rustls::crypto::aws_lc_rs::default_provider(),
        ))
        .with_safe_default_protocol_versions()
        .map_err(|_| err("BINANCE_TLS_CONFIG"))?
        .with_root_certificates(roots)
        .with_no_client_auth();
        let client = Client::builder()
            .https_only(true)
            .no_proxy()
            .http1_only()
            .redirect(redirect::Policy::none())
            .retry(retry::never())
            .tls_certs_only(certs)
            .tls_sslkeylogfile(false)
            .build()
            .map_err(|_| err("BINANCE_HTTP_CONFIG"))?;
        let (rest, ws) = match c.environment {
            Environment::SpotTestnet => (
                "https://testnet.binance.vision",
                "wss://ws-api.testnet.binance.vision/ws-api/v3",
            ),
            Environment::Live => (
                "https://api.binance.com",
                "wss://ws-api.binance.com:443/ws-api/v3",
            ),
        };
        let rt = Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|_| err("BINANCE_IO_RUNTIME"))?;
        Ok(Self {
            client,
            keys,
            clock,
            rt: Some(rt),
            tls: Arc::new(tls),
            socket: RefCell::new(None),
            rest: rest.into(),
            ws: ws.into(),
            window: c.recv_window_ms,
            limit: c.max_bytes,
            blocked_until: Cell::new(None),
        })
    }
    fn executor_ready(&self, b: &Budget) -> Result<()> {
        if Handle::try_current().is_ok() {
            return Err(err("BINANCE_SYNCHRONOUS_OWNER_REQUIRED"));
        }
        if b.until <= Instant::now() {
            return Err(err("BINANCE_DEADLINE"));
        }
        Ok(())
    }
    pub(crate) fn sync<T>(
        &self,
        budget: &Budget,
        work: impl Future<Output = Result<T>>,
    ) -> Result<T> {
        self.executor_ready(budget)?;
        self.rt
            .as_ref()
            .ok_or_else(|| err("BINANCE_IO_CLOSED"))?
            .block_on(async {
                tokio::time::timeout_at(budget.until.into(), work)
                    .await
                    .map_err(|_| err("BINANCE_DEADLINE"))?
            })
    }
    pub(crate) fn timestamp(&self) -> Result<u64> {
        let ns = self.clock.now_ns().map_err(|_| err("BINANCE_CLOCK"))?;
        Ok(u64::try_from(ns).map_err(|_| err("BINANCE_CLOCK"))? / 1_000_000)
    }
    async fn rest_call(
        &self,
        method: Method,
        path: &str,
        params: &BTreeMap<String, String>,
        remaining: Duration,
    ) -> Result<Response> {
        let query = signed_query(&self.keys, params, self.timestamp()?, self.window)?;
        let mut key =
            HeaderValue::from_str(self.keys.key.as_str()).map_err(|_| err("BINANCE_API_KEY"))?;
        key.set_sensitive(true);
        let mut url = reqwest::Url::parse(&self.rest).map_err(|_| err("BINANCE_ENDPOINT"))?;
        url.set_path(path);
        url.set_query(Some(query.as_str()));
        let mut response = self
            .client
            .request(method, url)
            .header("X-MBX-APIKEY", key)
            .header("accept", "application/json")
            .timeout(remaining)
            .send()
            .await
            .map_err(|_| err("BINANCE_HTTP_UNCERTAIN"))?;
        let status = response.status().as_u16();
        let retry_after_ms = response
            .headers()
            .get(RETRY_AFTER)
            .and_then(|x| x.to_str().ok())
            .and_then(|x| x.parse::<u64>().ok())
            .and_then(|s| s.checked_mul(1000));
        if matches!(status, 418 | 429) {
            let until =
                retry_after_ms.and_then(|n| Instant::now().checked_add(Duration::from_millis(n)));
            self.blocked_until.set(until);
        }
        if response
            .content_length()
            .is_some_and(|n| n > self.limit as u64)
            || response
                .headers()
                .get(CONTENT_ENCODING)
                .is_some_and(|v| v != "identity")
            || response
                .headers()
                .get(CONTENT_TYPE)
                .and_then(|v| v.to_str().ok())
                .and_then(|v| v.split(';').next())
                != Some("application/json")
        {
            return Err(err("BINANCE_HTTP_SHAPE"));
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = response
            .chunk()
            .await
            .map_err(|_| err("BINANCE_HTTP_UNCERTAIN"))?
        {
            if bytes.len().saturating_add(chunk.len()) > self.limit {
                return Err(err("BINANCE_RESPONSE_SIZE"));
            }
            bytes.extend_from_slice(&chunk);
        }
        Ok(Response {
            status,
            bytes,
            retry_after_ms,
        })
    }
}
impl Drop for Native {
    fn drop(&mut self) {
        self.socket.get_mut().take();
        if let Some(rt) = self.rt.take() {
            rt.shutdown_background();
        }
    }
}
impl Exchange for Native {
    fn preflight(&self, b: &Budget) -> Result<()> {
        self.executor_ready(b)?;
        if self
            .blocked_until
            .get()
            .is_some_and(|until| until > Instant::now())
        {
            return Err(err("BINANCE_RATE_LIMIT"));
        }
        if b.calls.get() == 0 {
            return Err(err("BINANCE_REQUEST_BUDGET"));
        }
        self.timestamp()?;
        Ok(())
    }
    fn request(
        &self,
        m: &str,
        path: &str,
        p: &BTreeMap<String, String>,
        budget: &Budget,
    ) -> Result<Response> {
        self.preflight(budget)?;
        let method = match (m, path) {
            (
                "GET",
                "/api/v3/account" | "/api/v3/openOrders" | "/api/v3/order" | "/api/v3/myTrades",
            ) => Method::GET,
            ("POST", "/api/v3/order") => Method::POST,
            ("DELETE", "/api/v3/order") => Method::DELETE,
            _ => return Err(err("BINANCE_ENDPOINT")),
        };
        let remaining = budget.take()?;
        self.sync(budget, self.rest_call(method, path, p, remaining))
    }
    fn subscribe(&self, id: &str, b: &Budget) -> Result<Vec<u8>> {
        b.take()?;
        self.open_socket(id, b)
    }
    fn next(&self, b: &Budget) -> Result<Vec<u8>> {
        b.take()?;
        self.read_socket(b)
    }
    fn close(&self) {
        self.socket.borrow_mut().take();
    }
}
#[cfg(test)]
#[path = "tests/loopback_tls.rs"]
mod loopback_tls;
#[cfg(test)]
#[path = "tests/spot_testnet_external.rs"]
mod spot_testnet_external;
