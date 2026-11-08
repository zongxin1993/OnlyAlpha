//! USD-M 历史事实转换。保留旧事实 ID 算法与 funding 原记录配对证据。
use crate::spot_rest::{Error, Result};
use onlyalpha_domain::{
    identifiers::OnlyInstrumentId,
    market::{
        OnlyFundingRateFact, OnlyFundingRateFactInput, OnlyReferencePriceFact,
        OnlyReferencePriceFactInput,
    },
    time::OnlyUtcDateTime,
    trading::OnlyReferencePriceKind,
    value::OnlyPrice,
};
use serde_json::Value;
use sha2::{Digest, Sha256};
fn hash(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
fn instrument(id: &OnlyInstrumentId) -> Result<()> {
    let s = id.to_string();
    if !s.ends_with("-PERP.BINANCE") || s.len() <= "-PERP.BINANCE".len() {
        return Err(Error::Shape);
    }
    Ok(())
}
fn python_time(t: OnlyUtcDateTime) -> String {
    let text = t.to_string();
    let text = text.strip_suffix('Z').unwrap_or(&text);
    let (base, fraction) = text.split_once('.').unwrap_or((text, ""));
    if fraction.is_empty() {
        format!("{base}+00:00")
    } else {
        format!("{base}.{fraction:0<6}+00:00")
    }
}
fn identity(
    family: &str,
    id: &OnlyInstrumentId,
    kind: &str,
    time: OnlyUtcDateTime,
    sequence: i64,
    version: &str,
) -> String {
    let input = format!(
        "{family}\x1f{id}\x1f{kind}\x1f{}\x1f{sequence}\x1f{version}",
        python_time(time)
    );
    format!("BINANCE-USDM-{family}-{}", hash(input.as_bytes()))
}
fn price(raw: &Value) -> Result<OnlyPrice> {
    let value = crate::spot_normalize::raw_decimal(raw, false)?;
    let precision = raw
        .as_str()
        .ok_or(Error::Shape)?
        .parse::<bigdecimal::BigDecimal>()
        .map_err(|_| Error::Shape)?
        .as_bigint_and_exponent()
        .1
        .max(0);
    OnlyPrice::new(value, u8::try_from(precision).map_err(|_| Error::Shape)?)
        .map_err(|_| Error::Shape)
}
/// 显式的冻结输入；时间、版本、序列不得从环境隐式取得。
pub struct Context<'a> {
    pub instrument_id: &'a OnlyInstrumentId,
    pub data_version: &'a str,
    pub source_sequence: i64,
    pub received_at: OnlyUtcDateTime,
}
impl Context<'_> {
    fn validate(&self) -> Result<()> {
        instrument(self.instrument_id)?;
        if self.source_sequence < 0 || self.data_version.trim().is_empty() {
            return Err(Error::Shape);
        }
        Ok(())
    }
}
/// `T,p/i` 参考价输入；仅支持 MARK/INDEX，拒绝其他价格语义。
pub fn reference_price(
    raw: &Value,
    kind: OnlyReferencePriceKind,
    c: &Context<'_>,
) -> Result<OnlyReferencePriceFact> {
    c.validate()?;
    let field = match kind {
        OnlyReferencePriceKind::Mark => "p",
        OnlyReferencePriceKind::Index => "i",
        _ => return Err(Error::Shape),
    };
    let time = crate::spot_facts::milliseconds(&raw["T"])?;
    OnlyReferencePriceFact::new(OnlyReferencePriceFactInput {
        fact_id: identity(
            "REFERENCE_PRICE",
            c.instrument_id,
            if field == "p" { "MARK" } else { "INDEX" },
            time,
            c.source_sequence,
            c.data_version,
        ),
        instrument_id: c.instrument_id.clone(),
        kind,
        value: price(&raw[field])?,
        ts_event: time,
        ts_init: c.received_at,
        source: "BINANCE_USDM".into(),
        source_sequence: c.source_sequence.into(),
        data_version: c.data_version.into(),
        revision: 0.into(),
        provider_evidence_id: None,
        source_record_hash: None,
    })
    .map_err(|_| Error::Shape)
}
/// 返回 (exact funding mark, funding)；原记录哈希相同，稳定顺序由 Domain 定义。
pub fn funding_boundary(
    raw: &Value,
    c: &Context<'_>,
) -> Result<(OnlyReferencePriceFact, OnlyFundingRateFact)> {
    c.validate()?;
    if let Some(symbol) = raw.get("symbol") {
        let id = c.instrument_id.to_string();
        if symbol.as_str() != id.strip_suffix("-PERP.BINANCE") {
            return Err(Error::Shape);
        }
    }
    if raw
        .get("rateType")
        .is_some_and(|v| v != "REGULAR" && v != "FUNDING_RATE")
    {
        return Err(Error::Shape);
    }
    let time = crate::spot_facts::milliseconds(&raw["fundingTime"])?;
    let canonical = onlyalpha_metadata_json::python_json(&raw.to_string(), 8 * 1024 * 1024)
        .map_err(|_| Error::Shape)?;
    let record_hash = hash(canonical.as_bytes());
    let evidence = format!("BINANCE-USDM-FUNDING-{record_hash}");
    let mark = OnlyReferencePriceFact::new(OnlyReferencePriceFactInput {
        fact_id: identity(
            "FUNDING_MARK",
            c.instrument_id,
            "MARK",
            time,
            c.source_sequence,
            c.data_version,
        ),
        instrument_id: c.instrument_id.clone(),
        kind: OnlyReferencePriceKind::Mark,
        value: price(&raw["markPrice"])?,
        ts_event: time,
        ts_init: c.received_at,
        source: "BINANCE_USDM".into(),
        source_sequence: c.source_sequence.into(),
        data_version: c.data_version.into(),
        revision: 1.into(),
        provider_evidence_id: Some(evidence.clone()),
        source_record_hash: Some(record_hash.clone()),
    })
    .map_err(|_| Error::Shape)?;
    let funding = OnlyFundingRateFact::new(OnlyFundingRateFactInput {
        fact_id: identity(
            "FUNDING_RATE",
            c.instrument_id,
            "FUNDING",
            time,
            c.source_sequence,
            c.data_version,
        ),
        instrument_id: c.instrument_id.clone(),
        rate: crate::spot_normalize::raw_decimal(&raw["fundingRate"], false)?,
        funding_time: time,
        ts_init: c.received_at,
        source: "BINANCE_USDM".into(),
        source_sequence: c.source_sequence.into(),
        data_version: c.data_version.into(),
        revision: 0.into(),
        provider_evidence_id: Some(evidence),
        source_record_hash: Some(record_hash),
    })
    .map_err(|_| Error::Shape)?;
    Ok((mark, funding))
}

/// USD-M contract 的闭合 1m Bar；校验衍生品身份，不借用 Spot 标的身份。
pub fn contract_bar(
    raw: &Value,
    instrument: &onlyalpha_domain::instrument::OnlyInstrument,
) -> Result<onlyalpha_domain::market::OnlyBar> {
    crate::spot_normalize::bar_interval(raw, instrument, 1, false)
}

/// 从收到的原始行捕获冻结切片。原文 SHA 与已有规范身份分别保留。
pub fn source_cut_row(
    raw: &[u8],
    kind: Option<OnlyReferencePriceKind>,
    context: &Context<'_>,
) -> Result<Value> {
    let source = std::str::from_utf8(raw).map_err(|_| Error::Shape)?;
    let v = onlyalpha_market_crypto::reference::read_json(raw).map_err(|_| Error::Shape)?;
    use onlyalpha_domain::base::OnlyDomainModel;
    let facts = if let Some(kind) = kind {
        vec![reference_price(&v, kind, context)?.to_record()]
    } else {
        let (mark, rate) = funding_boundary(&v, context)?;
        vec![mark.to_record(), rate.to_record()]
    };
    Ok(serde_json::json!({"raw":source,"raw_sha256":hash(raw),"facts":facts}))
}
