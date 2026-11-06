use crate::*;
use onlyalpha_domain::{identifiers::OnlyInstrumentId, numeric::only_remainder};

#[derive(Clone, Debug)]
pub struct Reference {
    record: Value,
    instrument: OnlyInstrumentId,
    start: OnlyTradingDay,
    end: Option<OnlyTradingDay>,
}
impl Reference {
    pub fn from_record(raw: &Value) -> Result<Self, Error> {
        fields(
            raw,
            &[
                "instrument_id",
                "exchange",
                "security_type",
                "board",
                "lot_size",
                "price_tick",
                "st_status",
                "suspended",
                "previous_close",
                "effective_from",
                "effective_to",
                "source",
                "source_version",
                "data_version",
            ],
            &["record_fingerprint", "content_fingerprint"],
            "REFERENCE_INVALID",
        )?;
        let instrument: OnlyInstrumentId =
            boundary(text(&raw["instrument_id"], "REFERENCE_INVALID")?.parse())?;
        let exchange = match text(&raw["exchange"], "REFERENCE_EXCHANGE_UNSUPPORTED")?
            .to_uppercase()
            .as_str()
        {
            "SSE" | "XSHG" => "SSE",
            "SZSE" | "XSHE" => "SZSE",
            _ => return Err(bad("REFERENCE_EXCHANGE_UNSUPPORTED")),
        };
        let board_text = text(&raw["board"], "REFERENCE_BOARD_MISSING")?.to_uppercase();
        let board = if board_text == "MAIN" {
            if exchange == "SSE" {
                "SSE_MAIN"
            } else {
                "SZSE_MAIN"
            }
        } else {
            &board_text
        };
        if !matches!(
            (exchange, board),
            ("SSE", "SSE_MAIN" | "STAR") | ("SZSE", "SZSE_MAIN" | "CHINEXT")
        ) {
            return Err(bad("REFERENCE_BOARD_UNSUPPORTED"));
        }
        if instrument.venue().to_string() != if exchange == "SSE" { "XSHG" } else { "XSHE" } {
            return Err(bad("REFERENCE_EXCHANGE_UNSUPPORTED"));
        }
        if raw["security_type"] != "COMMON_STOCK" {
            return Err(bad("REFERENCE_SECURITY_TYPE_UNSUPPORTED"));
        }
        let (lot, lot_text) = decimal(&raw["lot_size"], "REFERENCE_LOT_SIZE_INVALID")?;
        if !boundary(only_remainder(&lot, &boundary("1".parse())?))?.is_zero() {
            return Err(bad("REFERENCE_LOT_SIZE_INVALID"));
        }
        let (_, tick) = decimal(&raw["price_tick"], "REFERENCE_PRICE_TICK_INVALID")?;
        let (_, close) = decimal(&raw["previous_close"], "REFERENCE_PREVIOUS_CLOSE_INVALID")?;
        let st = raw["st_status"]
            .as_bool()
            .ok_or_else(|| bad("REFERENCE_ST_STATUS_UNKNOWN"))?;
        let suspended = raw["suspended"]
            .as_bool()
            .ok_or_else(|| bad("REFERENCE_SUSPENSION_STATUS_UNKNOWN"))?;
        let start = day(&raw["effective_from"])?;
        let end = if raw["effective_to"].is_null() {
            None
        } else {
            Some(day(&raw["effective_to"])?)
        };
        if end.is_some_and(|end| end <= start) {
            return Err(bad("REFERENCE_EFFECTIVE_RANGE_INVALID"));
        }
        let source = text(&raw["source"], "REFERENCE_SOURCE_INVALID")?.to_uppercase();
        if !matches!(
            source.as_str(),
            "CONFIG" | "MINIQMT" | "TUSHARE" | "GOLDEN_DATASET" | "SCENARIO"
        ) {
            return Err(bad("REFERENCE_SOURCE_INVALID"));
        }
        let record = json!({"instrument_id":instrument.to_string(),"exchange":exchange,"security_type":"COMMON_STOCK",
            "board":board,"lot_size":lot_text,"price_tick":tick,"st_status":st,"suspended":suspended,"previous_close":close,
            "effective_from":day_text(start),"effective_to":end.map(day_text),"source":source,
            "source_version":text(&raw["source_version"],"REFERENCE_SOURCE_VERSION_MISSING")?,
            "data_version":text(&raw["data_version"],"REFERENCE_DATA_VERSION_MISSING")?});
        for field in ["record_fingerprint", "content_fingerprint"] {
            if let Some(supplied) = raw.get(field)
                && !supplied.is_null()
                && supplied != ""
                && supplied.as_str() != Some(digest(&record).as_str())
            {
                return Err(bad("REFERENCE_FINGERPRINT_MISMATCH"));
            }
        }
        Ok(Self {
            record,
            instrument,
            start,
            end,
        })
    }
    pub fn record(&self) -> Value {
        self.record.clone()
    }
    pub fn fingerprint(&self) -> String {
        digest(&self.record)
    }
    pub fn instrument(&self) -> &OnlyInstrumentId {
        &self.instrument
    }
    pub fn is_effective_on(&self, day: OnlyTradingDay) -> bool {
        self.start <= day && self.end.is_none_or(|end| day < end)
    }
}
#[derive(Clone, Debug)]
pub struct ReferenceAuthority {
    references: Vec<Reference>,
}
impl ReferenceAuthority {
    pub fn new(mut references: Vec<Reference>) -> Result<Self, Error> {
        if references.is_empty() || references.len() > 4096 {
            return Err(bad("REFERENCE_INVALID"));
        }
        references.sort_by_key(|r| (r.instrument.to_string(), r.start));
        for pair in references.windows(2) {
            if pair[0].instrument == pair[1].instrument
                && pair[0].end.is_none_or(|end| pair[1].start < end)
            {
                return Err(bad("REFERENCE_EFFECTIVE_RANGE_OVERLAP"));
            }
        }
        Ok(Self { references })
    }
    pub fn resolve(
        &self,
        instrument: &OnlyInstrumentId,
        day: OnlyTradingDay,
    ) -> Result<&Reference, Error> {
        self.references
            .iter()
            .find(|reference| {
                reference.instrument() == instrument && reference.is_effective_on(day)
            })
            .ok_or_else(|| bad("REFERENCE_NOT_FOUND"))
    }
    pub fn record(&self) -> Value {
        json!({"schema_version":1,"kind":"CN_A_SHARE_REFERENCE","references":self.references.iter().map(Reference::record).collect::<Vec<_>>()})
    }
    pub fn fingerprint(&self) -> String {
        digest(&self.record())
    }
}
