//! Immutable canonical market facts. External names, acquisition and publication stay outside Domain.
use crate::{
    base::{domain_model, invalid, whitespace},
    enums::{OnlyBookType, OnlyOrderSide, domain_enum},
    errors::OnlyDomainError,
    identifiers::{OnlyInstrumentId, OnlyTradeId},
    numeric::OnlyDecimal,
    time::OnlyUtcDateTime,
    trading::OnlyReferencePriceKind,
    value::{OnlyPrice, OnlyQuantity},
};
use bigdecimal::num_bigint::BigInt;

domain_model!(OnlyTick,OnlyTickInput,1,None,{instrument_id:OnlyInstrumentId,ts_event:OnlyUtcDateTime,ts_init:OnlyUtcDateTime,sequence:BigInt,source:String});
domain_model!(OnlyTradeTick,OnlyTradeTickInput,1,None,{instrument_id:OnlyInstrumentId,ts_event:OnlyUtcDateTime,ts_init:OnlyUtcDateTime,sequence:BigInt,source:String,price:OnlyPrice,quantity:OnlyQuantity,aggressor_side:Option<OnlyOrderSide>,trade_id:OnlyTradeId});
domain_model!(OnlyQuoteTick,OnlyQuoteTickInput,1,None,{instrument_id:OnlyInstrumentId,ts_event:OnlyUtcDateTime,ts_init:OnlyUtcDateTime,sequence:BigInt,source:String,bid_price:OnlyPrice,bid_quantity:OnlyQuantity,ask_price:OnlyPrice,ask_quantity:OnlyQuantity});
domain_enum! {OnlyMarketReferenceKind{VenueReferencePrice=>"VENUE_REFERENCE_PRICE"}}
domain_model!(OnlyMarketReferenceTick,OnlyMarketReferenceTickInput,1,None,{instrument_id:OnlyInstrumentId,ts_event:OnlyUtcDateTime,ts_init:OnlyUtcDateTime,sequence:BigInt,source:String,reference_kind:OnlyMarketReferenceKind,price:Option<OnlyPrice>});
fn validate_tick(
    event: OnlyUtcDateTime,
    init: OnlyUtcDateTime,
    sequence: &BigInt,
    source: &str,
) -> Result<(), OnlyDomainError> {
    if init < event || sequence < &BigInt::from(0) || source.trim_matches(whitespace).is_empty() {
        return Err(invalid("tick timestamps, sequence or source are invalid"));
    }
    Ok(())
}
impl OnlyTick {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        validate_tick(
            *self.ts_event(),
            *self.ts_init(),
            self.sequence(),
            self.source(),
        )
    }
}
impl OnlyMarketReferenceTick {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        validate_tick(
            *self.ts_event(),
            *self.ts_init(),
            self.sequence(),
            self.source(),
        )
    }
}
impl OnlyTradeTick {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        validate_tick(
            *self.ts_event(),
            *self.ts_init(),
            self.sequence(),
            self.source(),
        )?;
        if self.quantity().value().is_zero() {
            return Err(invalid("trade tick quantity must be positive"));
        }
        Ok(())
    }
}
impl OnlyQuoteTick {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        validate_tick(
            *self.ts_event(),
            *self.ts_init(),
            self.sequence(),
            self.source(),
        )?;
        if self.bid_price().precision() != self.ask_price().precision() {
            return Err(invalid("quote prices must share precision"));
        }
        Ok(())
    }
}

domain_model!(OnlyReferencePriceFact,OnlyReferencePriceFactInput,2,None,{
 fact_id:String,instrument_id:OnlyInstrumentId,kind:OnlyReferencePriceKind,value:OnlyPrice,ts_event:OnlyUtcDateTime,ts_init:OnlyUtcDateTime,source:String,source_sequence:BigInt,data_version:String,revision:BigInt,provider_evidence_id:Option<String>,source_record_hash:Option<String>,
});
domain_model!(OnlyFundingRateFact,OnlyFundingRateFactInput,2,None,{
 fact_id:String,instrument_id:OnlyInstrumentId,rate:OnlyDecimal,funding_time:OnlyUtcDateTime,ts_init:OnlyUtcDateTime,source:String,source_sequence:BigInt,data_version:String,revision:BigInt,provider_evidence_id:Option<String>,source_record_hash:Option<String>,
});
fn validate_lineage(evidence: Option<&str>, hash: Option<&str>) -> Result<(), OnlyDomainError> {
    match (evidence, hash) {
        (None, None) => Ok(()),
        (Some(evidence), Some(hash))
            if !evidence.trim_matches(whitespace).is_empty()
                && hash.len() == 64
                && hash
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)) =>
        {
            Ok(())
        }
        _ => Err(invalid("provider lineage must be complete and valid")),
    }
}
impl OnlyReferencePriceFact {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        validate_tick(
            *self.ts_event(),
            *self.ts_init(),
            self.source_sequence(),
            self.source(),
        )?;
        if self.fact_id().trim_matches(whitespace).is_empty()
            || self.data_version().trim_matches(whitespace).is_empty()
            || self.revision() < &BigInt::from(0)
            || self.value().value().is_zero()
            || self.value().value().is_negative()
        {
            return Err(invalid("reference-price identity/value is invalid"));
        }
        validate_lineage(
            self.provider_evidence_id().as_deref(),
            self.source_record_hash().as_deref(),
        )
    }
    pub fn stable_order(&self) -> (OnlyUtcDateTime, u8, &BigInt, &str) {
        let priority = match self.kind() {
            OnlyReferencePriceKind::Index => 10,
            OnlyReferencePriceKind::Mark => 11,
            OnlyReferencePriceKind::Settlement => 12,
            OnlyReferencePriceKind::Trade => 13,
        };
        (
            *self.ts_event(),
            priority,
            self.source_sequence(),
            self.fact_id(),
        )
    }
}
impl OnlyFundingRateFact {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        validate_tick(
            *self.funding_time(),
            *self.ts_init(),
            self.source_sequence(),
            self.source(),
        )?;
        if self.fact_id().trim_matches(whitespace).is_empty()
            || self.data_version().trim_matches(whitespace).is_empty()
            || self.revision() < &BigInt::from(0)
        {
            return Err(invalid("funding-rate identity/value is invalid"));
        }
        validate_lineage(
            self.provider_evidence_id().as_deref(),
            self.source_record_hash().as_deref(),
        )
    }
    pub fn stable_order(&self) -> (OnlyUtcDateTime, u8, &BigInt, &str) {
        (
            *self.funding_time(),
            20,
            self.source_sequence(),
            self.fact_id(),
        )
    }
}
domain_model!(OnlyOrderBookLevel,OnlyOrderBookLevelInput,1,None,{price:OnlyPrice,quantity:OnlyQuantity,order_count:Option<BigInt>});
impl OnlyOrderBookLevel {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if self.quantity().value().is_zero()
            || self
                .order_count()
                .as_ref()
                .is_some_and(|count| count < &BigInt::from(0))
        {
            return Err(invalid("order book level quantity/count is invalid"));
        }
        Ok(())
    }
}
domain_model!(OnlyOrderBook,OnlyOrderBookInput,1,None,{instrument_id:OnlyInstrumentId,book_type:OnlyBookType,bids:Vec<OnlyOrderBookLevel>,asks:Vec<OnlyOrderBookLevel>,sequence:BigInt,event_time:OnlyUtcDateTime});
impl OnlyOrderBook {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if self.sequence() < &BigInt::from(0)
            || self
                .bids()
                .windows(2)
                .any(|pair| pair[0].price().value() <= pair[1].price().value())
            || self
                .asks()
                .windows(2)
                .any(|pair| pair[0].price().value() >= pair[1].price().value())
        {
            return Err(invalid("order book sequence/sort is invalid"));
        }
        Ok(())
    }
    pub fn is_crossed(&self) -> bool {
        matches!((self.bids().first(),self.asks().first()),(Some(bid),Some(ask)) if bid.price().value()>=ask.price().value())
    }
}

use std::str::FromStr;

use crate::{
    base::{OnlyDomainModel, record, text},
    enums::{OnlyAdjustmentType, OnlyPriceType, OnlySessionType},
    value::OnlyMoney,
};
use serde_json::{Value, json};
domain_enum! {OnlyBarFormationKind{FixedDuration=>"FIXED_DURATION",CalendarPeriod=>"CALENDAR_PERIOD",TickCount=>"TICK_COUNT",Volume=>"VOLUME",Value=>"VALUE"}}
domain_enum! {OnlyBarAlignment{Utc=>"UTC",SessionStart=>"SESSION_START"}}
domain_enum! {OnlyCalendarPeriodUnit{Day=>"DAY",Week=>"WEEK",Month=>"MONTH"}}
domain_model!(OnlyFixedDurationBarFormation,OnlyFixedDurationBarFormationInput,1,None,{window_minutes:BigInt,stride_minutes:BigInt,alignment:OnlyBarAlignment,kind:OnlyBarFormationKind});
impl OnlyFixedDurationBarFormation {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if *self.kind() != OnlyBarFormationKind::FixedDuration
            || self.window_minutes() < &BigInt::from(1)
            || self.stride_minutes() < &BigInt::from(1)
            || self.stride_minutes() > self.window_minutes()
        {
            return Err(invalid("fixed-duration Bar formation is invalid"));
        }
        Ok(())
    }
}
domain_model!(OnlyCalendarPeriodBarFormation,OnlyCalendarPeriodBarFormationInput,1,None,{unit:OnlyCalendarPeriodUnit,count:BigInt,alignment:OnlyBarAlignment,kind:OnlyBarFormationKind});
impl OnlyCalendarPeriodBarFormation {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if *self.kind() != OnlyBarFormationKind::CalendarPeriod || self.count() < &BigInt::from(1) {
            return Err(invalid("calendar-period Bar formation is invalid"));
        }
        Ok(())
    }
}
domain_model!(OnlyTickCountBarFormation,OnlyTickCountBarFormationInput,1,None,{count:BigInt,kind:OnlyBarFormationKind});
impl OnlyTickCountBarFormation {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if *self.kind() != OnlyBarFormationKind::TickCount || self.count() < &BigInt::from(1) {
            return Err(invalid("tick-count Bar formation is invalid"));
        }
        Ok(())
    }
}
domain_model!(OnlyVolumeBarFormation,OnlyVolumeBarFormationInput,2,None,{quantity:OnlyDecimal,kind:OnlyBarFormationKind},prepare=OnlyVolumeBarFormation::prepare_fields);
impl OnlyVolumeBarFormation {
    fn prepare_fields(
        mut fields: OnlyVolumeBarFormationInput,
    ) -> Result<OnlyVolumeBarFormationInput, OnlyDomainError> {
        fields.quantity = fields.quantity.canonical();
        Ok(fields)
    }
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if *self.kind() != OnlyBarFormationKind::Volume
            || self.quantity().is_zero()
            || self.quantity().is_negative()
        {
            return Err(invalid("volume Bar formation is invalid"));
        }
        Ok(())
    }
}
domain_model!(OnlyValueBarFormation,OnlyValueBarFormationInput,2,None,{value:OnlyDecimal,kind:OnlyBarFormationKind},prepare=OnlyValueBarFormation::prepare_fields);
impl OnlyValueBarFormation {
    fn prepare_fields(
        mut fields: OnlyValueBarFormationInput,
    ) -> Result<OnlyValueBarFormationInput, OnlyDomainError> {
        fields.value = fields.value.canonical();
        Ok(fields)
    }
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if *self.kind() != OnlyBarFormationKind::Value
            || self.value().is_zero()
            || self.value().is_negative()
        {
            return Err(invalid("value Bar formation is invalid"));
        }
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OnlyBarFormation {
    FixedDuration(OnlyFixedDurationBarFormation),
    CalendarPeriod(OnlyCalendarPeriodBarFormation),
    TickCount(OnlyTickCountBarFormation),
    Volume(OnlyVolumeBarFormation),
    Value(OnlyValueBarFormation),
}
impl OnlyDomainModel for OnlyBarFormation {
    fn to_record(&self) -> Value {
        match self {
            Self::FixedDuration(f) => f.to_record(),
            Self::CalendarPeriod(f) => f.to_record(),
            Self::TickCount(f) => f.to_record(),
            Self::Volume(f) => f.to_record(),
            Self::Value(f) => f.to_record(),
        }
    }
    fn from_record(value: &Value) -> Result<Self, OnlyDomainError> {
        (|| {
            let kind: OnlyBarFormationKind = text(
                value
                    .get("kind")
                    .ok_or_else(|| invalid("missing Bar formation kind"))?,
                "kind",
            )?
            .parse()?;
            Ok(match kind {
                OnlyBarFormationKind::FixedDuration => {
                    Self::FixedDuration(OnlyFixedDurationBarFormation::from_record(value)?)
                }
                OnlyBarFormationKind::CalendarPeriod => {
                    Self::CalendarPeriod(OnlyCalendarPeriodBarFormation::from_record(value)?)
                }
                OnlyBarFormationKind::TickCount => {
                    Self::TickCount(OnlyTickCountBarFormation::from_record(value)?)
                }
                OnlyBarFormationKind::Volume => {
                    Self::Volume(OnlyVolumeBarFormation::from_record(value)?)
                }
                OnlyBarFormationKind::Value => {
                    Self::Value(OnlyValueBarFormation::from_record(value)?)
                }
            })
        })()
        .map_err(crate::value::serialization)
    }
}
crate::base::domain_field!(OnlyBarFormation);
domain_model!(OnlyBarSemantic,OnlyBarSemanticInput,3,None,{formation:OnlyBarFormation,price_type:OnlyPriceType,adjustment_policy:OnlyAdjustmentType},exact_record=true);
impl OnlyBarSemantic {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
    /// Schema-3 identity hashes the one canonical parameter record.
    pub fn fingerprint(&self) -> Result<String, OnlyDomainError> {
        use sha2::{Digest, Sha256};
        use std::fmt::Write;
        let bytes = serde_json::to_vec(&self.to_record())
            .map_err(|error| OnlyDomainError::Serialization(error.to_string()))?;
        let digest = Sha256::digest(bytes);
        let mut result = String::with_capacity(64);
        for byte in digest {
            write!(&mut result, "{byte:02x}").expect("writing a string cannot fail");
        }
        Ok(result)
    }
    pub fn is_fixed_duration(&self) -> bool {
        matches!(self.formation(), OnlyBarFormation::FixedDuration(_))
    }
    pub fn window_minutes(&self) -> Result<&BigInt, OnlyDomainError> {
        if let OnlyBarFormation::FixedDuration(f) = self.formation() {
            Ok(f.window_minutes())
        } else {
            Err(invalid("Bar semantic is not fixed-duration"))
        }
    }
    pub fn stride_minutes(&self) -> Result<&BigInt, OnlyDomainError> {
        if let OnlyBarFormation::FixedDuration(f) = self.formation() {
            Ok(f.stride_minutes())
        } else {
            Err(invalid("Bar semantic is not fixed-duration"))
        }
    }
    pub fn is_aligned(&self) -> bool {
        matches!(self.formation(),OnlyBarFormation::FixedDuration(f) if f.window_minutes()==f.stride_minutes())
    }
    pub fn fixed_duration(
        window_minutes: BigInt,
        stride_minutes: Option<BigInt>,
    ) -> Result<Self, OnlyDomainError> {
        Self::new(OnlyBarSemanticInput {
            formation: OnlyBarFormation::FixedDuration(OnlyFixedDurationBarFormation::new(
                OnlyFixedDurationBarFormationInput {
                    stride_minutes: stride_minutes.unwrap_or_else(|| window_minutes.clone()),
                    window_minutes,
                    alignment: OnlyBarAlignment::SessionStart,
                    kind: OnlyBarFormationKind::FixedDuration,
                },
            )?),
            price_type: OnlyPriceType::Last,
            adjustment_policy: OnlyAdjustmentType::Raw,
        })
    }
}
domain_model!(OnlyBarType,OnlyBarTypeInput,2,None,{instrument_id:OnlyInstrumentId,semantic:OnlyBarSemantic});
impl OnlyBarType {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
}
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct OnlyTradeSemantic;
impl OnlyDomainModel for OnlyTradeSemantic {
    fn to_record(&self) -> Value {
        json!({"schema_version":1,"kind":"TRADE"})
    }
    fn from_record(value: &Value) -> Result<Self, OnlyDomainError> {
        if value == &Self.to_record() {
            Ok(Self)
        } else {
            Err(invalid("Trade semantic is invalid"))
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyTradeInputType {
    instrument_id: OnlyInstrumentId,
    semantic: OnlyTradeSemantic,
}
impl OnlyTradeInputType {
    pub fn new(instrument_id: OnlyInstrumentId) -> Self {
        Self {
            instrument_id,
            semantic: OnlyTradeSemantic,
        }
    }
    pub fn instrument_id(&self) -> &OnlyInstrumentId {
        &self.instrument_id
    }
    pub const fn semantic(&self) -> OnlyTradeSemantic {
        self.semantic
    }
}
impl OnlyDomainModel for OnlyTradeInputType {
    fn to_record(&self) -> Value {
        json!({"schema_version":1,"instrument_id":self.instrument_id.to_string(),"semantic":self.semantic.to_record()})
    }
    fn from_record(value: &Value) -> Result<Self, OnlyDomainError> {
        (|| {
            let row = record(value, 1, &["instrument_id", "semantic"])?;
            OnlyTradeSemantic::from_record(&row["semantic"])?;
            let result = Self::new(text(&row["instrument_id"], "instrument_id")?.parse()?);
            if result.to_record() != *value {
                return Err(invalid("Trade input is invalid"));
            }
            Ok(result)
        })()
        .map_err(crate::value::serialization)
    }
}

domain_model!(OnlyBar,OnlyBarInput,1,None,{
 bar_type:OnlyBarType,open:OnlyPrice,high:OnlyPrice,low:OnlyPrice,close:OnlyPrice,volume:OnlyQuantity,quote_volume:Option<OnlyQuantity>,turnover:Option<OnlyMoney>,trade_count:Option<BigInt>,open_interest:Option<OnlyQuantity>,bar_start:OnlyUtcDateTime,bar_end:OnlyUtcDateTime,ts_event:OnlyUtcDateTime,ts_init:OnlyUtcDateTime,is_closed:bool,revision:BigInt,adjustment_type:OnlyAdjustmentType,trading_day:jiff::civil::Date,session_type:OnlySessionType,
});
impl OnlyBar {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        let f = &self.fields;
        if f.bar_start >= f.bar_end {
            return Err(invalid("bar interval must be increasing"));
        }
        if f.ts_event < f.bar_start || f.revision < BigInt::from(0) || f.ts_init < f.ts_event {
            return Err(invalid("bar event time, init time or revision is invalid"));
        }
        if [f.high.precision(), f.low.precision(), f.close.precision()]
            .iter()
            .any(|precision| *precision != f.open.precision())
        {
            return Err(invalid("bar prices must share one precision"));
        }
        if [f.open.value(), f.close.value(), f.low.value()]
            .iter()
            .any(|value| f.high.value() < *value)
        {
            return Err(invalid("bar high is below another OHLC value"));
        }
        if [f.open.value(), f.close.value(), f.high.value()]
            .iter()
            .any(|value| f.low.value() > *value)
        {
            return Err(invalid("bar low is above another OHLC value"));
        }
        if f.trade_count
            .as_ref()
            .is_some_and(|count| count < &BigInt::from(0))
        {
            return Err(invalid("bar trade_count cannot be negative"));
        }
        if !f.is_closed && f.revision != BigInt::from(0) {
            return Err(invalid("an updating bar cannot carry a revision"));
        }
        if f.adjustment_type != *f.bar_type.semantic().adjustment_policy() {
            return Err(invalid("bar adjustment does not match Bar semantic"));
        }
        Ok(())
    }
    pub fn instrument_id(&self) -> &OnlyInstrumentId {
        self.bar_type().instrument_id()
    }
    pub fn contains(&self, timestamp: OnlyUtcDateTime) -> bool {
        *self.bar_start() <= timestamp && timestamp < *self.bar_end()
    }
}
