//! USD-M 历史 HTTP 采集。每次操作共用绝对 deadline，原响应先交 owning recorder。
use crate::spot_rest::{Error, PublicResponse, PublicRest, RequestContext, Result};
use onlyalpha_integration_contract::source::Trust;
use serde_json::{Value, value::RawValue};
use std::time::Instant;
/// 不同端点不可互换；Index 使用 pair，其他端点使用 symbol。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum History {
    Contract,
    Mark,
    Index,
    Funding,
}
pub struct UsdmRest {
    transport: PublicRest,
    page_size: usize,
}
impl UsdmRest {
    pub fn from_configuration(input: &RawValue, work: usize, trust: &Trust) -> Result<Self> {
        let transport = PublicRest::usdm(input, work, trust)?;
        let v: Value = serde_json::from_str(input.get()).map_err(|_| Error::Configuration)?;
        let page_size = v["rest_page_size"].as_u64().unwrap_or(1000) as usize;
        Ok(Self {
            transport,
            page_size,
        })
    }
    /// Public rule input only; interpretation and Authority belong to the market plugin.
    pub async fn exchange_info_observed<F>(
        &self,
        deadline: Instant,
        capture: &mut F,
    ) -> Result<PublicResponse>
    where
        F: FnMut(&RequestContext, &[u8]) -> Result<()>,
    {
        let response = self
            .transport
            .get_observed("/fapi/v1/exchangeInfo", &[], deadline, capture)
            .await?;
        let rows = response.value()["symbols"].as_array().ok_or(Error::Shape)?;
        let mut seen = std::collections::BTreeSet::new();
        for row in rows {
            let symbol = row["symbol"]
                .as_str()
                .filter(|s| crate::spot_rest::symbol(s))
                .ok_or(Error::Shape)?;
            if !seen.insert(symbol) {
                return Err(Error::Shape);
            }
        }
        Ok(response)
    }
    /// Public funding interval evidence; no private account/bracket queries here.
    pub async fn funding_info_observed<F>(
        &self,
        deadline: Instant,
        capture: &mut F,
    ) -> Result<PublicResponse>
    where
        F: FnMut(&RequestContext, &[u8]) -> Result<()>,
    {
        let response = self
            .transport
            .get_observed("/fapi/v1/fundingInfo", &[], deadline, capture)
            .await?;
        let rows = response.value().as_array().ok_or(Error::Shape)?;
        let mut seen = std::collections::BTreeSet::new();
        for row in rows {
            let symbol = row["symbol"]
                .as_str()
                .filter(|s| crate::spot_rest::symbol(s))
                .ok_or(Error::Shape)?;
            if !seen.insert(symbol) {
                return Err(Error::Shape);
            }
        }
        Ok(response)
    }
    /// 历史范围采用 [start,end)。Bar 仅 1m；Funding 保留完整原记录。
    /// 空页/短页不授予 COMPLETE 证明；Recorder 失败立即停止，不发下一页。
    pub async fn history_observed<F>(
        &self,
        kind: History,
        symbol: &str,
        start: i64,
        end: i64,
        deadline: Instant,
        capture: &mut F,
    ) -> Result<Vec<PublicResponse>>
    where
        F: FnMut(&RequestContext, &[u8]) -> Result<()>,
    {
        if !crate::spot_rest::symbol(symbol) || start < 0 || start >= end {
            return Err(Error::Range);
        }
        let funding = kind == History::Funding;
        if !funding && (start % 60_000 != 0 || end % 60_000 != 0) {
            return Err(Error::Range);
        }
        let (path, parameter) = match kind {
            History::Contract => ("/fapi/v1/klines", "symbol"),
            History::Mark => ("/fapi/v1/markPriceKlines", "symbol"),
            History::Index => ("/fapi/v1/indexPriceKlines", "pair"),
            History::Funding => ("/fapi/v1/fundingRate", "symbol"),
        };
        let limit = self.page_size.min(if funding { 1000 } else { 1500 });
        let mut cursor = start;
        let mut pages = Vec::new();
        let mut total = 0usize;
        while cursor < end {
            let mut parameters = vec![
                (parameter, symbol.into()),
                ("startTime", cursor.to_string()),
                ("endTime", (end - 1).to_string()),
                ("limit", limit.to_string()),
            ];
            if !funding {
                parameters.push(("interval", "1m".into()));
            }
            let response = self
                .transport
                .get_observed(path, &parameters, deadline, capture)
                .await?;
            total = total
                .checked_add(response.bytes().len())
                .filter(|n| *n <= 8 * 1024 * 1024)
                .ok_or(Error::TooLarge)?;
            let rows = response
                .value()
                .as_array()
                .filter(|r| r.len() <= limit)
                .ok_or(Error::Shape)?;
            let mut previous = None;
            for row in rows {
                let time = if funding {
                    if row["symbol"].as_str() != Some(symbol) {
                        return Err(Error::Shape);
                    }
                    row["fundingTime"].as_i64().ok_or(Error::Shape)?
                } else {
                    let row = row
                        .as_array()
                        .filter(|r| r.len() >= 11)
                        .ok_or(Error::Shape)?;
                    let opened = row[0].as_i64().ok_or(Error::Shape)?;
                    if opened % 60_000 != 0 || opened.checked_add(59_999) != row[6].as_i64() {
                        return Err(Error::Range);
                    }
                    opened
                };
                if time < cursor || time >= end {
                    return Err(Error::Range);
                }
                if previous.is_some_and(|p| time <= p) {
                    return Err(Error::Order);
                }
                previous = Some(time);
            }
            let count = rows.len();
            let next = previous
                .map(|p: i64| {
                    p.checked_add(if funding { 1 } else { 60_000 })
                        .ok_or(Error::Range)
                })
                .transpose()?;
            pages.push(response);
            match next {
                Some(n) if n > cursor => cursor = n,
                None => break,
                _ => return Err(Error::Order),
            }
            if count < limit {
                break;
            }
        }
        Ok(pages)
    }
    #[cfg(test)]
    pub(crate) fn test_transport(base: &str, page_size: usize) -> Self {
        Self {
            transport: PublicRest::test_transport(base),
            page_size,
        }
    }
}
#[cfg(test)]
#[path = "tests/usdm_rest.rs"]
mod tests;
