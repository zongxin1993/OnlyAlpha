//! Immutable dimensional financial values. Constructors validate; no implicit FX.
use crate::{
    base::{
        OnlyDomainModel, alphanumeric, invalid, precision, record, text, uppercase, whitespace,
    },
    enums::OnlyCurrencyType,
    errors::OnlyDomainError,
    numeric::{OnlyDecimal, only_add, only_divide, only_subtract},
};
use serde_json::{Value, json};
use std::str::FromStr;

pub const ONLY_MAX_PRECISION: u8 = 18;
fn validate_precision(value: &OnlyDecimal, precision: u8) -> Result<(), OnlyDomainError> {
    if precision > ONLY_MAX_PRECISION || value.fractional_precision() > i64::from(precision) {
        return Err(invalid("value exceeds declared precision"));
    }
    Ok(())
}
pub(crate) fn serialization(error: OnlyDomainError) -> OnlyDomainError {
    OnlyDomainError::Serialization(error.to_string())
}
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct OnlyCurrency {
    code: String,
    precision: u8,
    currency_type: OnlyCurrencyType,
}
impl OnlyCurrency {
    pub fn new(
        code: &str,
        precision: u8,
        currency_type: OnlyCurrencyType,
    ) -> Result<Self, OnlyDomainError> {
        let code = uppercase(code.trim_matches(whitespace));
        if code.is_empty()
            || code.chars().count() > 12
            || !code.chars().all(alphanumeric)
            || precision > 18
        {
            return Err(invalid(
                "currency requires 1..12 alphanumeric characters and precision 0..18",
            ));
        }
        Ok(Self {
            code,
            precision,
            currency_type,
        })
    }
    pub fn code(&self) -> &str {
        &self.code
    }
    pub const fn precision(&self) -> u8 {
        self.precision
    }
    pub const fn currency_type(&self) -> OnlyCurrencyType {
        self.currency_type
    }
}
impl OnlyDomainModel for OnlyCurrency {
    fn to_record(&self) -> Value {
        json!({"schema_version":1,"code":self.code,"precision":self.precision,"currency_type":self.currency_type.as_str()})
    }
    fn from_record(value: &Value) -> Result<Self, OnlyDomainError> {
        (|| {
            let row = record(value, 1, &["code", "precision", "currency_type"])?;
            Self::new(
                text(&row["code"], "code")?,
                precision(&row["precision"])?,
                OnlyCurrencyType::from_str(text(&row["currency_type"], "currency_type")?)?,
            )
        })()
        .map_err(serialization)
    }
}

macro_rules! scalar {
    ($name:ident, $predicate:expr, $message:literal) => {
        #[derive(Clone, Debug, PartialEq, Eq, Hash)]
        pub struct $name { value: OnlyDecimal, precision: u8 }
        $crate::base::domain_field!($name);
        impl $name {
            pub fn new(value: OnlyDecimal, precision: u8) -> Result<Self, OnlyDomainError> {
                validate_precision(&value, precision)?;
                if !($predicate)(&value) { return Err(invalid($message)); }
                Ok(Self { value, precision })
            }
            pub fn value(&self) -> &OnlyDecimal { &self.value }
            pub const fn precision(&self) -> u8 { self.precision }
        }
        impl OnlyDomainModel for $name {
            fn to_record(&self) -> Value { json!({"schema_version":1,"value":self.value.to_string(),"precision":self.precision}) }
            fn from_record(value: &Value) -> Result<Self, OnlyDomainError> {
                (|| {
                    let row = record(value, 1, &["value", "precision"])?;
                    Self::new(text(&row["value"], "value")?.parse()?, precision(&row["precision"])?)
                })().map_err(serialization)
            }
        }
    };
}
scalar!(OnlyPrice, |_: &OnlyDecimal| true, "invalid price");
scalar!(
    OnlyQuantity,
    |v: &OnlyDecimal| !v.is_negative() || v.is_zero(),
    "quantity cannot be negative"
);
scalar!(OnlyRate, |_: &OnlyDecimal| true, "invalid rate");
scalar!(OnlyPercentage, |_: &OnlyDecimal| true, "invalid percentage");
scalar!(
    OnlyMultiplier,
    |v: &OnlyDecimal| !v.is_negative() && !v.is_zero(),
    "multiplier must be positive"
);

impl OnlyQuantity {
    pub fn checked_add(&self, other: &Self) -> Result<Self, OnlyDomainError> {
        Self::new(
            only_add(&self.value, &other.value)?,
            self.precision.max(other.precision),
        )
    }
    pub fn checked_subtract(&self, other: &Self) -> Result<Self, OnlyDomainError> {
        Self::new(
            only_subtract(&self.value, &other.value)?,
            self.precision.max(other.precision),
        )
    }
}
impl OnlyPercentage {
    pub fn as_rate(&self) -> Result<OnlyRate, OnlyDomainError> {
        OnlyRate::new(
            only_divide(&self.value, &"100".parse()?)?,
            18.min(self.precision + 2),
        )
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct OnlyMoney {
    amount: OnlyDecimal,
    currency: OnlyCurrency,
}
impl OnlyMoney {
    pub fn new(amount: OnlyDecimal, currency: OnlyCurrency) -> Result<Self, OnlyDomainError> {
        validate_precision(&amount, currency.precision)?;
        Ok(Self { amount, currency })
    }
    pub fn amount(&self) -> &OnlyDecimal {
        &self.amount
    }
    pub fn currency(&self) -> &OnlyCurrency {
        &self.currency
    }
    fn require_currency(&self, other: &Self) -> Result<(), OnlyDomainError> {
        if self.currency != other.currency {
            return Err(OnlyDomainError::CurrencyMismatch(
                "currency conversion required".into(),
            ));
        }
        Ok(())
    }
    pub fn checked_add(&self, other: &Self) -> Result<Self, OnlyDomainError> {
        self.require_currency(other)?;
        Self::new(
            only_add(&self.amount, &other.amount)?,
            self.currency.clone(),
        )
    }
    pub fn checked_subtract(&self, other: &Self) -> Result<Self, OnlyDomainError> {
        self.require_currency(other)?;
        Self::new(
            only_subtract(&self.amount, &other.amount)?,
            self.currency.clone(),
        )
    }
}
impl OnlyDomainModel for OnlyMoney {
    fn to_record(&self) -> Value {
        json!({"schema_version":1,"amount":self.amount.to_string(),"currency":self.currency.to_record()})
    }
    fn from_record(value: &Value) -> Result<Self, OnlyDomainError> {
        (|| {
            let row = record(value, 1, &["amount", "currency"])?;
            Self::new(
                text(&row["amount"], "amount")?.parse()?,
                OnlyCurrency::from_record(&row["currency"])?,
            )
        })()
        .map_err(serialization)
    }
}

crate::base::domain_field!(OnlyCurrency);
crate::base::domain_field!(OnlyMoney);
