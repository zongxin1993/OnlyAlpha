//! 固定输入切片的完整内容读取。摘要由调用方从原 Run 配置提供。
use crate::{
    base::{OnlyDomainModel, invalid},
    errors::OnlyDomainError,
    market::{OnlyFundingRateFact, OnlyReferencePriceFact},
};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

fn sha(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
/// 从已冻结源工件的实际字节读取。解码单条行情 DTO 不能得到该切片。
pub struct OnlyMarketSourceCut {
    fingerprint: String,

    facts: BTreeMap<String, Value>,
}
impl OnlyMarketSourceCut {
    pub fn read(bytes: &[u8], expected: &str) -> Result<Self, OnlyDomainError> {
        if bytes.len() > 32 * 1024 * 1024 || sha(bytes) != expected {
            return Err(invalid("market source cut digest or size"));
        }
        let rows: Vec<Value> =
            serde_json::from_slice(bytes).map_err(|_| invalid("market source cut encoding"))?;
        let mut facts = BTreeMap::new();

        for row in rows {
            let raw = row["raw"]
                .as_str()
                .ok_or_else(|| invalid("market source original row"))?;
            let raw_hash = sha(raw.as_bytes());
            if row.as_object().is_none_or(|r| r.len() != 3) || row["raw_sha256"] != raw_hash {
                return Err(invalid("market source original hash"));
            }
            let entries = row["facts"]
                .as_array()
                .filter(|r| !r.is_empty() && r.len() <= 2)
                .ok_or_else(|| invalid("market source facts"))?;
            for value in entries {
                let canonical = if value.get("funding_time").is_some() {
                    OnlyFundingRateFact::from_record(value)?.to_record()
                } else {
                    OnlyReferencePriceFact::from_record(value)?.to_record()
                };
                let id = value["fact_id"]
                    .as_str()
                    .ok_or_else(|| invalid("market source fact id"))?;
                if canonical != *value || facts.insert(id.into(), canonical).is_some() {
                    return Err(invalid("market source duplicate or noncanonical fact"));
                }
            }
        }
        Ok(Self {
            fingerprint: expected.into(),
            facts,
        })
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn fact(&self, id: &str) -> Option<&Value> {
        self.facts.get(id)
    }
    pub fn contains(&self, raw: &Value) -> bool {
        raw["fact_id"].as_str().and_then(|id| self.facts.get(id)) == Some(raw)
    }
}
