//! USD-M 交易所/资金费率/账户费档及模式四份协议输入的关系和归一化。
use crate::reference_capture::{keyed, rows, text};
use onlyalpha_domain::{
    numeric::{OnlyDecimal, only_divide, only_multiply},
    time::OnlyUtcDateTime,
};
use onlyalpha_market_crypto::reference::{Kind, Reference, Result, decimal_text, fingerprint, iso};
use serde_json::{Value, json};
fn number(v: &Value) -> Result<OnlyDecimal> {
    decimal_text(v)?.parse().map_err(|_| "BINANCE_USDM_DECIMAL")
}
// 杠杆档接口的名义上下限为 JSON integer，比例与累计值为 JSON number。
// 已记录的早期字符串形态继续按十进制读取，完整响应的摘要仍来自原字节。
fn bracket_number(v: &Value, integral: bool) -> Result<OnlyDecimal> {
    let literal = match v {
        Value::Number(n) => n.to_string(),
        Value::String(s) => s.clone(),
        _ => return Err("BINANCE_USDM_BRACKET_NUMBER"),
    };
    if integral && !literal.bytes().all(|b| b.is_ascii_digit()) && v.is_number() {
        return Err("BINANCE_USDM_BRACKET_INTEGER");
    }
    let result = number(&json!(literal))?;
    if integral
        && result
            .to_string()
            .parse::<bigdecimal::BigDecimal>()
            .map_err(|_| "BINANCE_USDM_BRACKET_INTEGER")?
            .normalized()
            .as_bigint_and_exponent()
            .1
            > 0
    {
        return Err("BINANCE_USDM_BRACKET_INTEGER");
    }
    Ok(result)
}
fn optional(v: &Value) -> Result<Value> {
    let n = number(v)?;
    if n.is_negative() && !n.is_zero() {
        return Err("BINANCE_USDM_NEGATIVE_BOUND");
    }
    Ok(if n.is_zero() {
        Value::Null
    } else {
        json!(n.to_string())
    })
}
fn segments(bracket: &Value, leverage: &OnlyDecimal) -> Result<Vec<Value>> {
    let one: OnlyDecimal = "1".parse().map_err(|_| "BINANCE_USDM_DECIMAL")?;
    if leverage < &one {
        return Err("BINANCE_USDM_LEVERAGE");
    }
    let coefficient = match bracket.get("notionalCoef") {
        None => one.clone(),
        Some(v) if v.is_number() => number(&json!(v.to_string()))?,
        Some(v) => number(v)?,
    };
    if coefficient.is_zero() || coefficient.is_negative() {
        return Err("BINANCE_USDM_BRACKET_COEFFICIENT");
    }
    let initial = only_divide(&one, leverage)
        .map_err(|_| "BINANCE_USDM_LEVERAGE")?
        .to_string();
    let mut out = Vec::new();
    for r in rows(&bracket["brackets"])? {
        let max = r["initialLeverage"]
            .as_u64()
            .ok_or("BINANCE_USDM_MAX_LEVERAGE")?;
        let max: OnlyDecimal = max
            .to_string()
            .parse()
            .map_err(|_| "BINANCE_USDM_MAX_LEVERAGE")?;
        if leverage > &max {
            return Err("BINANCE_USDM_LEVERAGE_EXCEEDS_BRACKET");
        }
        let scaled = |k: &str| {
            only_multiply(&bracket_number(&r[k], k != "cum")?, &coefficient)
                .map_err(|_| "BINANCE_USDM_BRACKET_SCALE")
        };
        let cumulative = scaled("cum")?;
        let neg = if cumulative.is_zero() {
            cumulative.to_string().trim_start_matches('-').to_string()
        } else {
            format!("-{cumulative}")
        };
        let maintenance = bracket_number(&r["maintMarginRatio"], false)?;
        if maintenance.is_negative() || cumulative.is_negative() {
            return Err("BINANCE_USDM_MARGIN_NEGATIVE");
        }
        out.push(json!({"lower_bound":scaled("notionalFloor")?.to_string(),"upper_bound":scaled("notionalCap")?.to_string(),"initial_slope":initial,"initial_intercept":"0","maintenance_slope":maintenance.to_string(),"maintenance_intercept":neg}));
    }
    if out.is_empty() {
        return Err("BINANCE_USDM_BRACKETS_REQUIRED");
    }
    Ok(out)
}
pub(crate) fn normalize(
    raw: [&Value; 4],
    hashes: &[String; 4],
    at: OnlyUtcDateTime,
    start: OnlyUtcDateTime,
    end: Option<OnlyUtcDateTime>,
) -> Result<(Reference, Reference)> {
    let [exchange, funding, brackets, account] = raw;
    let symbols = keyed(&exchange["symbols"], "symbol")?;
    let adjustments = keyed(funding, "symbol")?;
    let brackets = keyed(brackets, "symbol")?;
    let accounts = keyed(&account["symbols"], "symbol")?;
    let mode = text(&account["positionMode"])?;
    let revision = match exchange.get("serverTime") {
        None => "UNVERSIONED".to_owned(),
        Some(v) if v.is_u64() || v.is_i64() => v.to_string(),
        _ => return Err("BINANCE_USDM_REVISION"),
    };
    let account_source = fingerprint(&json!(&hashes[2..]))?;
    let mut public = Vec::new();
    let mut private = Vec::new();
    for (symbol, r) in symbols {
        if r["contractType"] != "PERPETUAL" {
            return Err("BINANCE_USDM_CONTRACT_TYPE");
        }
        let filters = keyed(&r["filters"], "filterType")?;
        if filters.keys().any(|k| {
            !matches!(
                *k,
                "PRICE_FILTER"
                    | "LOT_SIZE"
                    | "MARKET_LOT_SIZE"
                    | "MAX_NUM_ORDERS"
                    | "MAX_NUM_ALGO_ORDERS"
                    | "MIN_NOTIONAL"
                    | "PERCENT_PRICE"
            )
        }) {
            return Err("BINANCE_USDM_FILTER_UNSUPPORTED");
        }
        let price = filters
            .get("PRICE_FILTER")
            .ok_or("BINANCE_USDM_PRICE_FILTER")?;
        let lot = filters.get("LOT_SIZE").ok_or("BINANCE_USDM_LOT_SIZE")?;
        let min = filters
            .get("MIN_NOTIONAL")
            .ok_or("BINANCE_USDM_MIN_NOTIONAL")?;
        let (hours, source) = if let Some(row) = adjustments.get(symbol) {
            (
                row["fundingIntervalHours"]
                    .as_u64()
                    .ok_or("BINANCE_USDM_INTERVAL")?,
                format!("BINANCE_USDM_FUNDING_INFO@{revision}"),
            )
        } else {
            (
                8,
                "BINANCE_USDM_DEFAULT_FUNDING_INTERVAL@2026-09-01".to_owned(),
            )
        };
        let interval = hours
            .checked_mul(3600)
            .filter(|n| *n > 0)
            .ok_or("BINANCE_USDM_INTERVAL")?;
        let common = json!({"instrument_id":format!("{symbol}-PERP.BINANCE"),"coverage_start":iso(start),"coverage_end":end.map(iso),"observed_at":iso(at),"provider_revision":revision,"normalizer_semantic_version":"BINANCE_USDM_REFERENCE_NORMALIZER@2","provider_schema_semantic_version":"BINANCE_USDM_FAPI_REFERENCE@2026-09-01"});
        let mut p = common.clone();
        let specific = json!({"raw_symbol":symbol,"provider_status":text(&r["status"])?,"settlement_currency":text(&r["marginAsset"])?,"contract_multiplier":"1","price_tick":decimal_text(&price["tickSize"])?,"minimum_price":optional(&price["minPrice"])?,"maximum_price":optional(&price["maxPrice"])?,"quantity_step":decimal_text(&lot["stepSize"])?,"minimum_quantity":decimal_text(&lot["minQty"])?,"maximum_quantity":optional(&lot["maxQty"])?,"minimum_notional":optional(&min["notional"])?,"funding_schedule":{"interval_seconds":interval,"boundary_offset_seconds":0,"valuation_price_kind":"MARK","provider_semantic_version":source},"published_at":iso(at),"source_raw_fingerprints":&hashes[..2]});
        p.as_object_mut()
            .expect("object")
            .extend(specific.as_object().expect("object").clone());
        public.push(p);
        let a = accounts.get(symbol).ok_or("BINANCE_USDM_ACCOUNT_SCOPE")?;
        let b = brackets.get(symbol).ok_or("BINANCE_USDM_BRACKET_SCOPE")?;
        let leverage = number(&a["leverage"])?;
        let mut p = common;
        p["effective_inputs"] = json!({"position_mode":mode,"margin_mode":text(&a["marginMode"])?,"leverage":leverage.to_string(),"source_fingerprint":account_source});
        p["margin_segments"] = json!(segments(b, &leverage)?);
        p["source_raw_fingerprints"] = json!(&hashes[2..]);
        private.push(p);
    }
    Ok((
        Reference::usdm(Kind::Public, public)?,
        Reference::usdm(Kind::Account, private)?,
    ))
}
