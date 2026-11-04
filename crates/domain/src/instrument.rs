//! Market-neutral immutable instrument specifications. Concrete market parameters are inputs.
use crate::{
    base::{OnlyDomainModel, OnlyField, domain_model, invalid, text, whitespace},
    enums::{
        OnlyAssetClass, OnlyContractType, OnlyExerciseStyle, OnlyInstrumentType, OnlyMarketType,
        OnlyOptionType, OnlySecurityStatus, OnlySettlementType,
    },
    errors::OnlyDomainError,
    identifiers::{
        OnlyCalendarId, OnlyInstrumentId, OnlyRawSymbol, OnlySessionProfileId, OnlyVenueId,
    },
    numeric::{OnlyRoundingMode, only_increment, only_remainder},
    time::{OnlyTimeZone, OnlyUtcDateTime},
    value::{OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity, OnlyRate},
};
use bigdecimal::num_bigint::BigInt;
use serde_json::{Map, Value};

// Composition replaces Python inheritance; the wire representation remains flat and tagged.
domain_model!(OnlyInstrumentSpecification,OnlyInstrumentSpecificationInput,2,Some("OnlyInstrument"),{
 instrument_id:OnlyInstrumentId,raw_symbol:OnlyRawSymbol,asset_class:OnlyAssetClass,instrument_type:OnlyInstrumentType,market_type:OnlyMarketType,
 quote_currency:OnlyCurrency,settlement_currency:OnlyCurrency,price_precision:u8,quantity_precision:u8,tick_size:OnlyPrice,step_size:OnlyQuantity,contract_multiplier:OnlyMultiplier,
 base_currency:Option<OnlyCurrency>,margin_currency:Option<OnlyCurrency>,minimum_quantity:Option<OnlyQuantity>,maximum_quantity:Option<OnlyQuantity>,minimum_notional:Option<OnlyMoney>,maximum_notional:Option<OnlyMoney>,minimum_price:Option<OnlyPrice>,maximum_price:Option<OnlyPrice>,lot_size:Option<OnlyQuantity>,instrument_version:BigInt,activation_time:Option<OnlyUtcDateTime>,effective_from:Option<OnlyUtcDateTime>,effective_to:Option<OnlyUtcDateTime>,timezone:String,trading_calendar_id:Option<OnlyCalendarId>,session_profile_id:Option<OnlySessionProfileId>,status:OnlySecurityStatus,
});
impl OnlyInstrumentSpecification {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        let f = &self.fields;
        OnlyTimeZone::new(&f.timezone)?;
        if f.price_precision != f.tick_size.precision()
            || f.quantity_precision != f.step_size.precision()
        {
            return Err(invalid("instrument increment precision mismatch"));
        }
        if f.tick_size.value().is_negative()
            || f.tick_size.value().is_zero()
            || f.step_size.value().is_zero()
        {
            return Err(invalid("tick_size and step_size must be positive"));
        }
        if f.instrument_version < BigInt::from(1) {
            return Err(invalid("instrument_version must be positive"));
        }
        if matches!((f.effective_from,f.effective_to),(Some(start),Some(end)) if start>=end) {
            return Err(invalid("instrument effective interval must be increasing"));
        }
        for quantity in [&f.minimum_quantity, &f.maximum_quantity, &f.lot_size]
            .into_iter()
            .flatten()
        {
            if quantity.precision() != f.quantity_precision {
                return Err(invalid("instrument quantity constraint precision mismatch"));
            }
        }
        if matches!((&f.minimum_quantity,&f.maximum_quantity),(Some(min),Some(max)) if min.value()>max.value())
        {
            return Err(invalid("minimum_quantity exceeds maximum_quantity"));
        }
        for money in [&f.minimum_notional, &f.maximum_notional]
            .into_iter()
            .flatten()
        {
            if money.currency() != &f.quote_currency {
                return Err(invalid("notional limits must use quote currency"));
            }
        }
        if matches!((&f.minimum_notional,&f.maximum_notional),(Some(min),Some(max)) if min.amount()>max.amount())
        {
            return Err(invalid("minimum_notional exceeds maximum_notional"));
        }
        for price in [&f.minimum_price, &f.maximum_price].into_iter().flatten() {
            if price.precision() != f.price_precision {
                return Err(invalid("instrument price constraint precision mismatch"));
            }
        }
        if matches!((&f.minimum_price,&f.maximum_price),(Some(min),Some(max)) if min.value()>max.value())
        {
            return Err(invalid("minimum_price exceeds maximum_price"));
        }
        Ok(())
    }
    pub fn venue(&self) -> &OnlyVenueId {
        self.instrument_id().venue()
    }
    pub fn price_increment(&self) -> &OnlyPrice {
        self.tick_size()
    }
    pub fn quantity_increment(&self) -> &OnlyQuantity {
        self.step_size()
    }
    pub fn version(&self) -> &BigInt {
        self.instrument_version()
    }
    pub fn validates_price(&self, price: &OnlyPrice) -> Result<bool, OnlyDomainError> {
        Ok(price.precision() == *self.price_precision()
            && only_remainder(price.value(), self.tick_size().value())?.is_zero()
            && self
                .minimum_price()
                .as_ref()
                .is_none_or(|min| price.value() >= min.value())
            && self
                .maximum_price()
                .as_ref()
                .is_none_or(|max| price.value() <= max.value()))
    }
    pub fn is_valid_price(&self, price: &OnlyPrice) -> Result<bool, OnlyDomainError> {
        self.validates_price(price)
    }
    pub fn validates_quantity(&self, quantity: &OnlyQuantity) -> Result<bool, OnlyDomainError> {
        Ok(quantity.precision() == *self.quantity_precision()
            && only_remainder(quantity.value(), self.step_size().value())?.is_zero()
            && self
                .minimum_quantity()
                .as_ref()
                .is_none_or(|min| quantity.value() >= min.value())
            && self
                .maximum_quantity()
                .as_ref()
                .is_none_or(|max| quantity.value() <= max.value()))
    }
    pub fn is_valid_quantity(&self, quantity: &OnlyQuantity) -> Result<bool, OnlyDomainError> {
        self.validates_quantity(quantity)
    }
    pub fn quantize_price(
        &self,
        price: &OnlyPrice,
        rounding: OnlyRoundingMode,
    ) -> Result<OnlyPrice, OnlyDomainError> {
        OnlyPrice::new(
            only_increment(price.value(), self.tick_size().value(), rounding)?,
            *self.price_precision(),
        )
    }
    pub fn quantize_quantity(
        &self,
        quantity: &OnlyQuantity,
        rounding: OnlyRoundingMode,
    ) -> Result<OnlyQuantity, OnlyDomainError> {
        OnlyQuantity::new(
            only_increment(quantity.value(), self.step_size().value(), rounding)?,
            *self.quantity_precision(),
        )
    }
    pub fn is_effective_at(&self, timestamp: OnlyUtcDateTime) -> bool {
        self.effective_from().is_none_or(|start| timestamp >= start)
            && self.effective_to().is_none_or(|end| timestamp < end)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyFutureTerms {
    pub underlying: OnlyInstrumentId,
    pub expiration_time: OnlyUtcDateTime,
    pub last_trade_time: OnlyUtcDateTime,
    pub settlement_type: OnlySettlementType,
    pub contract_type: OnlyContractType,
    pub initial_margin_rate: Option<OnlyRate>,
    pub maintenance_margin_rate: Option<OnlyRate>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyOptionTerms {
    pub underlying: OnlyInstrumentId,
    pub strike_price: OnlyPrice,
    pub expiration_time: OnlyUtcDateTime,
    pub option_type: OnlyOptionType,
    pub exercise_style: OnlyExerciseStyle,
    pub settlement_type: OnlySettlementType,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OnlyInstrumentKind {
    Generic,
    Equity,
    Etf,
    Fund,
    Future(OnlyFutureTerms),
    Option(OnlyOptionTerms),
    Index,
    Commodity,
    FxPair,
    CryptoSpot,
    CryptoFuture(OnlyFutureTerms),
    CryptoPerpetual(OnlyContractType),
    Synthetic(String),
}
impl OnlyInstrumentKind {
    pub const fn model_type(&self) -> &'static str {
        match self {
            Self::Generic => "OnlyInstrument",
            Self::Equity => "OnlyEquity",
            Self::Etf => "OnlyETF",
            Self::Fund => "OnlyFund",
            Self::Future(_) => "OnlyFuture",
            Self::Option(_) => "OnlyOption",
            Self::Index => "OnlyIndex",
            Self::Commodity => "OnlyCommodity",
            Self::FxPair => "OnlyFxPair",
            Self::CryptoSpot => "OnlyCryptoSpot",
            Self::CryptoFuture(_) => "OnlyCryptoFuture",
            Self::CryptoPerpetual(_) => "OnlyCryptoPerpetual",
            Self::Synthetic(_) => "OnlySyntheticInstrument",
        }
    }
    fn fixed_classification(&self) -> Option<(OnlyInstrumentType, Option<OnlyAssetClass>)> {
        use OnlyAssetClass as A;
        use OnlyInstrumentType as I;
        Some(match self {
            Self::Generic => return None,
            Self::Equity => (I::Equity, Some(A::Equity)),
            Self::Etf => (I::Etf, Some(A::Fund)),
            Self::Fund => (I::Fund, Some(A::Fund)),
            Self::Future(_) => (I::Future, None),
            Self::Option(_) => (I::Option, None),
            Self::Index => (I::Index, Some(A::Index)),
            Self::Commodity => (I::Commodity, Some(A::Commodity)),
            Self::FxPair => (I::FxPair, Some(A::Fx)),
            Self::CryptoSpot => (I::CryptoSpot, Some(A::Cryptocurrency)),
            Self::CryptoFuture(_) => (I::CryptoFuture, Some(A::Cryptocurrency)),
            Self::CryptoPerpetual(_) => (I::CryptoPerpetual, Some(A::Cryptocurrency)),
            Self::Synthetic(_) => (I::Synthetic, Some(A::Synthetic)),
        })
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyInstrument {
    specification: OnlyInstrumentSpecification,
    kind: OnlyInstrumentKind,
}
impl OnlyInstrument {
    pub fn new(
        specification: OnlyInstrumentSpecification,
        kind: OnlyInstrumentKind,
    ) -> Result<Self, OnlyDomainError> {
        let f = &specification;
        if kind
            .fixed_classification()
            .is_some_and(|(instrument, asset)| {
                instrument != *f.instrument_type()
                    || asset.is_some_and(|asset| asset != *f.asset_class())
            })
        {
            return Err(invalid(
                "instrument classification does not match model_type",
            ));
        }
        match &kind {
            OnlyInstrumentKind::Future(terms) | OnlyInstrumentKind::CryptoFuture(terms) => {
                if terms.last_trade_time > terms.expiration_time {
                    return Err(invalid("last_trade_time cannot follow expiration_time"));
                }
                if f.margin_currency().is_none() {
                    return Err(invalid("future requires margin_currency"));
                }
                validate_contract_currencies(f, terms.contract_type)?;
            }
            OnlyInstrumentKind::Option(terms) => {
                if terms.strike_price.value().is_negative() || terms.strike_price.value().is_zero()
                {
                    return Err(invalid("option strike_price must be positive"));
                }
            }
            OnlyInstrumentKind::FxPair | OnlyInstrumentKind::CryptoSpot => {
                if f.base_currency().is_none()
                    || f.base_currency().as_ref() == Some(f.quote_currency())
                {
                    return Err(invalid("pair requires distinct base and quote currencies"));
                }
            }
            OnlyInstrumentKind::CryptoPerpetual(contract) => {
                if f.base_currency().is_none() || f.margin_currency().is_none() {
                    return Err(invalid(
                        "crypto perpetual requires base and margin currencies",
                    ));
                }
                validate_contract_currencies(f, *contract)?;
            }
            OnlyInstrumentKind::Synthetic(expression)
                if expression.trim_matches(whitespace).is_empty() =>
            {
                return Err(invalid("synthetic instrument expression is required"));
            }
            _ => {}
        }
        Ok(Self {
            specification,
            kind,
        })
    }
    pub fn specification(&self) -> &OnlyInstrumentSpecification {
        &self.specification
    }
    pub fn kind(&self) -> &OnlyInstrumentKind {
        &self.kind
    }
}
fn validate_contract_currencies(
    f: &OnlyInstrumentSpecification,
    contract: OnlyContractType,
) -> Result<(), OnlyDomainError> {
    if contract == OnlyContractType::Inverse
        && (f.base_currency().is_none()
            || f.base_currency().as_ref() != Some(f.settlement_currency()))
    {
        return Err(invalid("inverse contract must settle in base currency"));
    }
    if contract == OnlyContractType::Quanto
        && (f.settlement_currency() == f.quote_currency()
            || f.base_currency().as_ref() == Some(f.settlement_currency()))
    {
        return Err(invalid("quanto contract must settle in a third currency"));
    }
    Ok(())
}
fn take<T: OnlyField>(row: &mut Map<String, Value>, name: &str) -> Result<T, OnlyDomainError> {
    T::decode_field(
        &row.remove(name)
            .ok_or_else(|| invalid(&format!("missing {name}")))?,
    )
}
fn read_future(row: &mut Map<String, Value>) -> Result<OnlyFutureTerms, OnlyDomainError> {
    Ok(OnlyFutureTerms {
        underlying: take(row, "underlying")?,
        expiration_time: take(row, "expiration_time")?,
        last_trade_time: take(row, "last_trade_time")?,
        settlement_type: take(row, "settlement_type")?,
        contract_type: take(row, "contract_type")?,
        initial_margin_rate: take(row, "initial_margin_rate")?,
        maintenance_margin_rate: take(row, "maintenance_margin_rate")?,
    })
}
fn write_future(row: &mut Map<String, Value>, f: &OnlyFutureTerms) {
    row.insert("underlying".into(), f.underlying.encode_field());
    row.insert("expiration_time".into(), f.expiration_time.encode_field());
    row.insert("last_trade_time".into(), f.last_trade_time.encode_field());
    row.insert("settlement_type".into(), f.settlement_type.encode_field());
    row.insert("contract_type".into(), f.contract_type.encode_field());
    row.insert(
        "initial_margin_rate".into(),
        f.initial_margin_rate.encode_field(),
    );
    row.insert(
        "maintenance_margin_rate".into(),
        f.maintenance_margin_rate.encode_field(),
    );
}
impl OnlyDomainModel for OnlyInstrument {
    fn to_record(&self) -> Value {
        let mut value = self.specification.to_record();
        let row = value.as_object_mut().expect("specification is a record");
        row.insert("model_type".into(), self.kind.model_type().into());
        match &self.kind {
            OnlyInstrumentKind::Future(f) | OnlyInstrumentKind::CryptoFuture(f) => {
                write_future(row, f)
            }
            OnlyInstrumentKind::Option(f) => {
                row.insert("underlying".into(), f.underlying.encode_field());
                row.insert("strike_price".into(), f.strike_price.encode_field());
                row.insert("expiration_time".into(), f.expiration_time.encode_field());
                row.insert("option_type".into(), f.option_type.encode_field());
                row.insert("exercise_style".into(), f.exercise_style.encode_field());
                row.insert("settlement_type".into(), f.settlement_type.encode_field());
            }
            OnlyInstrumentKind::CryptoPerpetual(contract) => {
                row.insert("contract_type".into(), contract.encode_field());
            }
            OnlyInstrumentKind::Synthetic(expression) => {
                row.insert("expression".into(), expression.encode_field());
            }
            _ => {}
        }
        value
    }
    fn from_record(value: &Value) -> Result<Self, OnlyDomainError> {
        (|| {
            let mut row = value
                .as_object()
                .ok_or_else(|| invalid("instrument requires object"))?
                .clone();
            let tag = text(
                row.get("model_type")
                    .ok_or_else(|| invalid("missing model_type"))?,
                "model_type",
            )?
            .to_owned();
            let kind = match tag.as_str() {
                "OnlyInstrument" => OnlyInstrumentKind::Generic,
                "OnlyEquity" => OnlyInstrumentKind::Equity,
                "OnlyETF" => OnlyInstrumentKind::Etf,
                "OnlyFund" => OnlyInstrumentKind::Fund,
                "OnlyFuture" => OnlyInstrumentKind::Future(read_future(&mut row)?),
                "OnlyCryptoFuture" => OnlyInstrumentKind::CryptoFuture(read_future(&mut row)?),
                "OnlyOption" => OnlyInstrumentKind::Option(OnlyOptionTerms {
                    underlying: take(&mut row, "underlying")?,
                    strike_price: take(&mut row, "strike_price")?,
                    expiration_time: take(&mut row, "expiration_time")?,
                    option_type: take(&mut row, "option_type")?,
                    exercise_style: take(&mut row, "exercise_style")?,
                    settlement_type: take(&mut row, "settlement_type")?,
                }),
                "OnlyIndex" => OnlyInstrumentKind::Index,
                "OnlyCommodity" => OnlyInstrumentKind::Commodity,
                "OnlyFxPair" => OnlyInstrumentKind::FxPair,
                "OnlyCryptoSpot" => OnlyInstrumentKind::CryptoSpot,
                "OnlyCryptoPerpetual" => {
                    OnlyInstrumentKind::CryptoPerpetual(take(&mut row, "contract_type")?)
                }
                "OnlySyntheticInstrument" => {
                    OnlyInstrumentKind::Synthetic(take(&mut row, "expression")?)
                }
                _ => return Err(invalid("unknown instrument model_type")),
            };
            row.insert("model_type".into(), "OnlyInstrument".into());
            Self::new(
                OnlyInstrumentSpecification::from_record(&Value::Object(row))?,
                kind,
            )
        })()
        .map_err(crate::value::serialization)
    }
}
crate::base::domain_field!(OnlyInstrument);
