//! Distinct immutable identifiers; Instrument text is injective across Symbol/Venue.
//!
//! ```compile_fail
//! use onlyalpha_domain::identifiers::{OnlyOrderId, OnlyTradeId};
//! let order: OnlyOrderId = OnlyTradeId::new("same").unwrap();
//! ```
use crate::{
    base::{OnlyDomainModel, invalid, record, text, whitespace},
    errors::OnlyDomainError,
};
use serde_json::{Value, json};
use std::{fmt, str::FromStr};

macro_rules! identifier {
    ($($name:ident),+ $(,)?) => {$ (
        #[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
        pub struct $name(String);
        $crate::base::domain_field!($name);
        impl $name {
            pub fn new(value: &str) -> Result<Self, OnlyDomainError> {
                let value = value.trim_matches(whitespace);
                if value.is_empty() || value.chars().count() > 128 || value.chars().any(whitespace)
                    || (stringify!($name) == "OnlyVenueId" && value.contains('.')) {
                    return Err(invalid(concat!("invalid ", stringify!($name))));
                }
                Ok(Self(value.to_owned()))
            }
            pub fn value(&self) -> &str { &self.0 }
        }
        impl FromStr for $name {
            type Err = OnlyDomainError;
            fn from_str(value: &str) -> Result<Self, Self::Err> { Self::new(value) }
        }
        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { f.write_str(&self.0) }
        }
        impl OnlyDomainModel for $name {
            fn to_record(&self) -> Value { json!({"schema_version":1,"value":self.0}) }
            fn from_record(value: &Value) -> Result<Self, OnlyDomainError> {
                (|| { let row = record(value, 1, &["value"])?; Self::new(text(&row["value"], "value")?) })()
                    .map_err(|e: OnlyDomainError| OnlyDomainError::Serialization(e.to_string()))
            }
        }
    )+};
}
identifier!(
    OnlyIdentifier,
    OnlySymbol,
    OnlyRawSymbol,
    OnlyVenueId,
    OnlyCalendarId,
    OnlySessionProfileId,
    OnlyOrderId,
    OnlyClientOrderId,
    OnlyOrderRequestId,
    OnlyOrderEventId,
    OnlyVenueOrderId,
    OnlyVenueTradeId,
    OnlyTradeId,
    OnlyPositionId,
    OnlyAccountId,
    OnlyClusterId,
    OnlyRuntimeId,
    OnlyEngineId
);

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct OnlyInstrumentId {
    symbol: OnlySymbol,
    venue: OnlyVenueId,
}
impl OnlyInstrumentId {
    pub fn new(symbol: OnlySymbol, venue: OnlyVenueId) -> Self {
        Self { symbol, venue }
    }
    pub fn symbol(&self) -> &OnlySymbol {
        &self.symbol
    }
    pub fn venue(&self) -> &OnlyVenueId {
        &self.venue
    }
}
impl fmt::Display for OnlyInstrumentId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}.{}", self.symbol, self.venue)
    }
}
impl FromStr for OnlyInstrumentId {
    type Err = OnlyDomainError;
    fn from_str(value: &str) -> Result<Self, Self::Err> {
        let (symbol, venue) = value
            .rsplit_once('.')
            .ok_or_else(|| invalid("instrument id must use SYMBOL.VENUE"))?;
        Ok(Self::new(
            OnlySymbol::new(symbol)?,
            OnlyVenueId::new(venue)?,
        ))
    }
}
impl OnlyDomainModel for OnlyInstrumentId {
    fn to_record(&self) -> Value {
        json!({"schema_version":1,"symbol":self.symbol.to_record(),"venue":self.venue.to_record()})
    }
    fn from_record(value: &Value) -> Result<Self, OnlyDomainError> {
        (|| {
            let row = record(value, 1, &["symbol", "venue"])?;
            Ok(Self::new(
                OnlySymbol::from_record(&row["symbol"])?,
                OnlyVenueId::from_record(&row["venue"])?,
            ))
        })()
        .map_err(|e: OnlyDomainError| OnlyDomainError::Serialization(e.to_string()))
    }
}

crate::base::domain_field!(OnlyInstrumentId);
