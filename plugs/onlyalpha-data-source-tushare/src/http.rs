//! Authenticated HTTPS boundary. No ambient credentials, proxies or roots.
use onlyalpha_integration_contract::source::{Budget, Trust};
use reqwest::{Client, redirect, retry};
use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet},
    future::Future,
    pin::Pin,
    time::{Duration, Instant},
};
use zeroize::Zeroizing;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Configuration,
    Request,
    Deadline,
    Status,
    TooLarge,
    Shape,
    Permission,
    Provider,
    Conflict,
    Calendar,
    Empty,
    CacheMiss,
    Evidence,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Configuration => "TUSHARE_CONFIG_INVALID",
            Self::Request => "TUSHARE_REQUEST_FAILED",
            Self::Deadline => "TUSHARE_DEADLINE_EXCEEDED",
            Self::Status => "TUSHARE_HTTP_STATUS",
            Self::TooLarge => "TUSHARE_RESPONSE_TOO_LARGE",
            Self::Shape => "TUSHARE_RESPONSE_INVALID",
            Self::Permission => "TUSHARE_PERMISSION_DENIED",
            Self::Provider => "TUSHARE_PROVIDER_ERROR",
            Self::Conflict => "TUSHARE_DUPLICATE_CONFLICT",
            Self::Calendar => "TUSHARE_CALENDAR_INVALID",
            Self::Empty => "TUSHARE_EMPTY_RESPONSE",
            Self::CacheMiss => "TUSHARE_CACHE_MISS",
            Self::Evidence => "TUSHARE_EVIDENCE_INVALID",
        }
    }
}
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}
pub type Result<T> = std::result::Result<T, Error>;
pub type ResponseFuture<'a> = Pin<Box<dyn Future<Output = Result<Vec<u8>>> + Send + 'a>>;
pub const MAX_RESPONSE: usize = 8 * 1024 * 1024;
/// Non-secret request context; the credential is never part of evidence.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Query {
    pub api: String,
    pub parameters: BTreeMap<String, String>,
    pub fields: String,
}
impl Query {
    pub(crate) fn record(&self) -> Value {
        serde_json::json!({"api_name":self.api,"params":self.parameters,"fields":self.fields})
    }
    pub(crate) fn restore(value: &Value) -> Result<Self> {
        let query = Self::new(
            value["api_name"].as_str().ok_or(Error::Configuration)?,
            serde_json::from_value(value["params"].clone()).map_err(|_| Error::Configuration)?,
            value["fields"].as_str().ok_or(Error::Configuration)?,
        )?;
        if query.record() != *value {
            return Err(Error::Configuration);
        }
        Ok(query)
    }
    pub fn new(api: &str, parameters: BTreeMap<String, String>, fields: &str) -> Result<Self> {
        if !matches!(
            api,
            "daily" | "fund_daily" | "adj_factor" | "stock_basic" | "fund_basic" | "trade_cal"
        ) || parameters.keys().any(|k| {
            !matches!(
                k.as_str(),
                "ts_code" | "start_date" | "end_date" | "exchange" | "list_status" | "market"
            )
        }) || parameters.values().any(|v| v.len() > 128)
            || fields.len() > 1024
        {
            return Err(Error::Configuration);
        }
        Ok(Self {
            api: api.into(),
            parameters,
            fields: fields.into(),
        })
    }
}
/// A controlled provider boundary for deterministic replay/test input. Production
/// construction uses HttpTransport; this port confers no Product admission.
pub trait Transport: Send + Sync {
    fn post<'a>(&'a self, query: &'a Query, deadline: Instant) -> ResponseFuture<'a>;
}
pub struct HttpTransport {
    client: Client,
    token: Zeroizing<String>,
    #[cfg(test)]
    test_endpoint: Option<String>,
}
impl HttpTransport {
    /// Host must resolve an admitted exact Secret binding before calling this.
    /// No Debug, serialization, environment lookup or HTTP fallback is provided.
    pub fn new(secret: &str, trust: &Trust) -> Result<Self> {
        if secret.is_empty()
            || secret.len() > 4096
            || secret.trim() != secret
            || secret.chars().any(char::is_control)
        {
            return Err(Error::Configuration);
        }
        let mut certs = Vec::new();
        for root in trust.roots_pem() {
            // reqwest/rustls from_pem merely stores bytes, and its builder
            // accepts a PEM with zero certificates as an empty root store.
            // Require an actual certificate in every explicit root bundle.
            // The builder then validates each DER through RootCertStore::add.
            let bundle =
                reqwest::Certificate::from_pem_bundle(root).map_err(|_| Error::Configuration)?;
            if bundle.is_empty() {
                return Err(Error::Configuration);
            }
            certs.extend(bundle);
        }
        let client = Client::builder()
            .https_only(true)
            .no_proxy()
            .http1_only()
            .redirect(redirect::Policy::none())
            .retry(retry::never())
            .tls_certs_only(certs)
            .tls_sslkeylogfile(false)
            .build()
            .map_err(|_| Error::Configuration)?;
        Ok(Self {
            client,
            token: Zeroizing::new(secret.into()),
            #[cfg(test)]
            test_endpoint: None,
        })
    }
}
impl Transport for HttpTransport {
    fn post<'a>(&'a self, query: &'a Query, deadline: Instant) -> ResponseFuture<'a> {
        Box::pin(async move {
            // Revalidate public fields: Query is intentionally transparent for replay.
            Query::new(&query.api, query.parameters.clone(), &query.fields)?;
            let remaining = deadline
                .checked_duration_since(Instant::now())
                .filter(|d| !d.is_zero())
                .ok_or(Error::Deadline)?;
            let operation = async {
                // Build secret JSON in a zeroizing byte buffer. Never retain request bytes.
                let token = Zeroizing::new(
                    serde_json::to_string(self.token.as_str()).map_err(|_| Error::Configuration)?,
                );
                let params =
                    serde_json::to_string(&query.parameters).map_err(|_| Error::Configuration)?;
                let fields =
                    serde_json::to_string(&query.fields).map_err(|_| Error::Configuration)?;
                let body = Zeroizing::new(
                    format!(
                        "{{\"api_name\":\"{}\",\"token\":{},\"params\":{},\"fields\":{}}}",
                        query.api,
                        token.as_str(),
                        params,
                        fields
                    )
                    .into_bytes(),
                );
                let endpoint = "https://api.tushare.pro";
                #[cfg(test)]
                let endpoint = self.test_endpoint.as_deref().unwrap_or(endpoint);
                let mut response = self
                    .client
                    .post(endpoint)
                    .header("content-type", "application/json")
                    .header("accept", "application/json")
                    .timeout(remaining)
                    .body(body.to_vec())
                    .send()
                    .await
                    .map_err(|e| {
                        if e.is_timeout() {
                            Error::Deadline
                        } else {
                            Error::Request
                        }
                    })?;
                if !response.status().is_success() {
                    return Err(Error::Status);
                }
                if response
                    .content_length()
                    .is_some_and(|n| n > MAX_RESPONSE as u64)
                {
                    return Err(Error::TooLarge);
                }
                let content = response
                    .headers()
                    .get("content-type")
                    .and_then(|h| h.to_str().ok())
                    .ok_or(Error::Shape)?;
                if content.split(';').next().map(str::trim) != Some("application/json")
                    || response
                        .headers()
                        .get("content-encoding")
                        .is_some_and(|v| v != "identity")
                {
                    return Err(Error::Shape);
                }
                let mut bytes = Zeroizing::new(Vec::new());
                while let Some(chunk) = response.chunk().await.map_err(|_| Error::Request)? {
                    if bytes
                        .len()
                        .checked_add(chunk.len())
                        .is_none_or(|n| n > MAX_RESPONSE)
                    {
                        return Err(Error::TooLarge);
                    }
                    bytes.extend_from_slice(&chunk);
                }
                // Never alter provider evidence. Echoed secrets fail closed before escape.
                let value: Value = serde_json::from_slice(&bytes).map_err(|_| Error::Shape)?;
                if bytes
                    .windows(self.token.len())
                    .any(|w| w == self.token.as_bytes())
                    || contains_secret(&value, self.token.as_str())
                {
                    return Err(Error::Evidence);
                }
                Table::decode(&bytes)?;
                success(deadline, bytes.to_vec())
            };
            let response =
                tokio::time::timeout_at(tokio::time::Instant::from_std(deadline), operation)
                    .await
                    .map_err(|_| Error::Deadline)??;
            success(deadline, response)
        })
    }
}
fn contains_secret(value: &Value, secret: &str) -> bool {
    match value {
        Value::String(s) => s.contains(secret),
        Value::Array(v) => v.iter().any(|v| contains_secret(v, secret)),
        Value::Object(v) => v
            .iter()
            .any(|(k, v)| k.contains(secret) || contains_secret(v, secret)),
        _ => false,
    }
}
/// Every admitted success, including synchronous decoding after the final
/// await, must still belong to the original absolute monotonic budget.
pub(crate) fn success<T>(deadline: Instant, value: T) -> Result<T> {
    success_at(deadline, Instant::now(), value)
}
fn success_at<T>(deadline: Instant, observed: Instant, value: T) -> Result<T> {
    if observed >= deadline {
        Err(Error::Deadline)
    } else {
        Ok(value)
    }
}
pub fn deadline(budget: Budget) -> Result<Instant> {
    Instant::now()
        .checked_add(Duration::from_millis(budget.millis()))
        .ok_or(Error::Deadline)
}
/// Exact JSON number lexemes are preserved by serde_json/arbitrary_precision.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Table {
    pub fields: Vec<String>,
    pub rows: Vec<BTreeMap<String, Value>>,
}
impl Table {
    pub fn decode(bytes: &[u8]) -> Result<Self> {
        if bytes.len() > MAX_RESPONSE {
            return Err(Error::TooLarge);
        }
        let raw = std::str::from_utf8(bytes).map_err(|_| Error::Shape)?;
        onlyalpha_metadata_json::canonical_json(raw, MAX_RESPONSE).map_err(|_| Error::Shape)?;
        let v: Value = serde_json::from_str(raw).map_err(|_| Error::Shape)?;
        match v["code"].as_i64() {
            Some(0) => (),
            Some(2002) => return Err(Error::Permission),
            Some(_) => return Err(Error::Provider),
            None => return Err(Error::Shape),
        }
        let fields = v["data"]["fields"]
            .as_array()
            .filter(|v| !v.is_empty() && v.len() <= 64)
            .ok_or(Error::Shape)?
            .iter()
            .map(|v| {
                v.as_str()
                    .filter(|s| !s.is_empty() && s.len() <= 128)
                    .map(str::to_owned)
                    .ok_or(Error::Shape)
            })
            .collect::<Result<Vec<_>>>()?;
        if fields.iter().collect::<BTreeSet<_>>().len() != fields.len() {
            return Err(Error::Shape);
        }
        let items = v["data"]["items"]
            .as_array()
            .filter(|v| v.len() <= 6000)
            .ok_or(Error::TooLarge)?;
        let rows = items
            .iter()
            .map(|item| {
                let cells = item
                    .as_array()
                    .filter(|v| v.len() == fields.len())
                    .ok_or(Error::Shape)?;
                Ok(fields.iter().cloned().zip(cells.iter().cloned()).collect())
            })
            .collect::<Result<Vec<_>>>()?;
        Ok(Self { fields, rows })
    }
    pub fn require(&self, fields: &[&str]) -> Result<()> {
        if fields.iter().any(|f| !self.fields.iter().any(|v| v == f)) {
            Err(Error::Shape)
        } else {
            Ok(())
        }
    }
}

/// 纯重放测试的 transport。不允许该路径执行任何源端 I/O。
#[cfg(test)]
pub(crate) struct Offline;
#[cfg(test)]
impl Transport for Offline {
    fn post<'a>(&'a self, _: &'a Query, _: Instant) -> ResponseFuture<'a> {
        panic!("封存输入重放不能访问源端")
    }
}

#[cfg(test)]
#[path = "tests/http.rs"]
mod tests;
