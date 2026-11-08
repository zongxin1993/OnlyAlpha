//! Binance Spot 私有协议边界。场所观察由 Runtime 确认应用。
mod codec;
mod normalize;
mod private_http;
mod stream;
pub use codec::usdm_order_parameters;
use codec::*;
use normalize::*;
use onlyalpha_broker::{BrokerCommand, Error};
pub use private_http::Credentials;
use private_http::*;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use stream::*;

type Result<T> = std::result::Result<T, Error>;
fn err(code: &str) -> Error {
    Error::new(code)
}
mod discovery;
mod evidence;
mod gateway;
#[cfg(test)]
#[path = "tests/protocol_cases.rs"]
mod protocol_cases;
pub use evidence::{Checkpoint, Observation, ObservationStore};
pub use gateway::SpotBroker;
use onlyalpha_broker::Scope;
use onlyalpha_domain::value::OnlyCurrency;

pub const VERSION: &str = env!("CARGO_PKG_VERSION");
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Environment {
    SpotTestnet,
    Live,
}
impl Environment {
    fn name(self) -> &'static str {
        match self {
            Self::SpotTestnet => "SPOT_TESTNET",
            Self::Live => "LIVE",
        }
    }
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Access {
    ReadOnly,
    Trading,
}
impl Access {
    fn name(self) -> &'static str {
        match self {
            Self::ReadOnly => "READ_ONLY",
            Self::Trading => "TRADING",
        }
    }
}
/// 两个 Secret Slot 引用由宿主按当前 Generation 解密；引用必须精确到版本。
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Binding {
    pub access: Access,
    pub artifact_sha256: String,
    pub scope: Scope,
    pub environment: Environment,
    pub uid: u64,
    pub key_slot: String,
    pub secret_slot: String,
}
impl Binding {
    fn validate(&self) -> Result<()> {
        let kind = self.scope.record()["runtime_kind"]
            .as_str()
            .unwrap_or("")
            .to_owned();
        if self.artifact_sha256.len() != 64
            || !self
                .artifact_sha256
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
            || self.uid == 0
            || self.key_slot == self.secret_slot
            || [&self.key_slot, &self.secret_slot].iter().any(|s| {
                s.is_empty()
                    || s.len() > 256
                    || s.chars().any(|c| c.is_whitespace() || c.is_control())
            })
            || !matches!(
                (self.environment, kind.as_str()),
                (Environment::Live, "LIVE") | (Environment::SpotTestnet, "LIVE" | "SIM")
            )
        {
            return Err(err("BINANCE_BINDING"));
        }
        Ok(())
    }
    fn record(&self) -> Value {
        json!([
            self.scope.record(),
            self.environment.name(),
            self.uid,
            self.key_slot,
            self.secret_slot,
            self.access.name(),
            VERSION,
            self.artifact_sha256
        ])
    }
}
pub struct BoundCredentials {
    binding: Binding,
    keys: Credentials,
}
impl BoundCredentials {
    pub fn new(binding: Binding, api_key: String, secret: String) -> Result<Self> {
        let keys = Credentials::new(api_key, secret)?;
        binding.validate()?;
        Ok(Self { binding, keys })
    }
}
#[derive(Clone)]
pub struct Config {
    pub binding: Binding,
    pub currencies: BTreeMap<String, OnlyCurrency>,
    pub recv_window_ms: u64,
    pub timeout_ms: u64,
    pub max_bytes: usize,
    pub max_requests: usize,
}
impl std::ops::Deref for Config {
    type Target = Binding;
    fn deref(&self) -> &Binding {
        &self.binding
    }
}
impl Config {
    fn validate(&self) -> Result<()> {
        self.binding.validate()?;
        if self.currencies.is_empty()
            || self.currencies.iter().any(|(s, c)| s != c.code())
            || !(1..=60_000).contains(&self.recv_window_ms)
            || !(1..=30_000).contains(&self.timeout_ms)
            || !(1..=8 * 1024 * 1024).contains(&self.max_bytes)
            || !(1..=4096).contains(&self.max_requests)
        {
            return Err(err("BINANCE_CONFIGURATION"));
        }
        Ok(())
    }
    fn fingerprint(&self) -> String {
        use onlyalpha_domain::base::OnlyDomainModel;
        onlyalpha_broker::digest(&json!([
            "binance.spot.broker/native/1",
            self.binding.record(),
            self.currencies
                .values()
                .map(|c| c.to_record())
                .collect::<Vec<_>>(),
            self.recv_window_ms,
            self.timeout_ms,
            self.max_bytes,
            self.max_requests
        ]))
    }
    fn budget(&self) -> Budget {
        Budget::new(self.timeout_ms, self.max_requests)
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
#[cfg(test)]
#[path = "tests/venue_recovery.rs"]
mod venue_recovery;
