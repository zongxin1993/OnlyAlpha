//! Explicit provider identities and joined historical Reference conversion.
use crate::http::{Error, Result};
use onlyalpha_market_cn_ashare::Reference;
use serde_json::{Value, json};

pub fn symbol(instrument_id: &str) -> Result<String> {
    let (code, venue) = instrument_id.rsplit_once('.').ok_or(Error::Configuration)?;
    if code.len() != 6 || !code.bytes().all(|c| c.is_ascii_digit()) {
        return Err(Error::Configuration);
    }
    let suffix = match venue {
        "XSHG" => "SH",
        "XSHE" => "SZ",
        "XBSE" => "BJ",
        _ => return Err(Error::Configuration),
    };
    Ok(format!("{code}.{suffix}"))
}
/// Requires explicitly joined historical ST/suspension/effective/version fields.
/// Current stock name and price Bars never substitute for historical Reference.
pub fn ashare_reference(raw: &Value) -> Result<Reference> {
    let code = raw["ts_code"].as_str().ok_or(Error::Shape)?;
    let (number, suffix) = code.split_once('.').ok_or(Error::Shape)?;
    let venue = match suffix {
        "SH" => "XSHG",
        "SZ" => "XSHE",
        _ => return Err(Error::Shape),
    };
    let instrument = format!("{number}.{venue}");
    if symbol(&instrument)? != code {
        return Err(Error::Shape);
    }
    let exchange = raw["exchange"].as_str().ok_or(Error::Shape)?;
    let board = match (exchange, raw["market"].as_str()) {
        ("SSE", Some("主板")) => "SSE_MAIN",
        ("SZSE", Some("主板")) => "SZSE_MAIN",
        ("SSE", Some("科创板")) => "STAR",
        ("SZSE", Some("创业板")) => "CHINEXT",
        _ => return Err(Error::Shape),
    };
    let record = json!({"instrument_id":instrument,"exchange":exchange,"security_type":raw["security_type"],"board":board,"lot_size":raw["lot_size"],"price_tick":raw["price_tick"],"st_status":raw["st_status"],"suspended":raw["suspended"],"previous_close":raw["pre_close"],"effective_from":raw["trade_date"],"effective_to":raw["effective_to"],"source":"TUSHARE","source_version":raw["source_version"],"data_version":raw["data_version"]});
    Reference::from_record(&record).map_err(|_| Error::Shape)
}
