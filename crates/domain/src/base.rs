//! Strict versioned JSON records. Financial fields never pass through floating point.
use crate::errors::OnlyDomainError;
use serde_json::{Map, Value};

pub trait OnlyDomainModel: Sized {
    fn to_record(&self) -> Value;
    fn from_record(value: &Value) -> Result<Self, OnlyDomainError>;
    fn to_json(&self) -> Result<String, OnlyDomainError> {
        serde_json::to_string(&self.to_record())
            .map_err(|e| OnlyDomainError::Serialization(e.to_string()))
    }
    fn from_json(input: &str) -> Result<Self, OnlyDomainError> {
        let value = serde_json::from_str(input)
            .map_err(|e| OnlyDomainError::Serialization(e.to_string()))?;
        Self::from_record(&value).map_err(|e| OnlyDomainError::Serialization(e.to_string()))
    }
}

pub(crate) fn record<'a>(
    value: &'a Value,
    version: u64,
    fields: &[&str],
) -> Result<&'a Map<String, Value>, OnlyDomainError> {
    let object = value
        .as_object()
        .ok_or_else(|| invalid("domain record must be an object"))?;
    if object.get("schema_version").and_then(Value::as_u64) != Some(version)
        || object.len() != fields.len() + 1
        || fields.iter().any(|name| !object.contains_key(*name))
    {
        return Err(invalid("unexpected fields or domain schema version"));
    }
    Ok(object)
}
pub(crate) fn text<'a>(value: &'a Value, name: &str) -> Result<&'a str, OnlyDomainError> {
    value
        .as_str()
        .ok_or_else(|| invalid(&format!("{name} must be a string")))
}
pub(crate) fn precision(value: &Value) -> Result<u8, OnlyDomainError> {
    value
        .as_u64()
        .filter(|n| *n <= 18)
        .map(|n| n as u8)
        .ok_or_else(|| invalid("precision must be an integer in 0..18"))
}
pub(crate) fn invalid(message: &str) -> OnlyDomainError {
    OnlyDomainError::Validation(message.to_owned())
}

pub(crate) fn whitespace(c: char) -> bool {
    c.is_whitespace() || ('\u{001c}'..='\u{001f}').contains(&c)
}
pub(crate) fn alphanumeric(c: char) -> bool {
    let point = u32::from(c);
    let ranges = crate::unicode_data::ALPHANUMERIC;
    let index = ranges.partition_point(|(_, end)| *end < point);
    ranges
        .get(index)
        .is_some_and(|(start, end)| *start <= point && point <= *end)
}
pub(crate) fn uppercase(value: &str) -> String {
    let table = crate::unicode_data::UPPERCASE;
    let mut result = String::new();
    for character in value.chars() {
        match table.binary_search_by_key(&u32::from(character), |(point, _)| *point) {
            Ok(index) => result.push_str(table[index].1),
            Err(_) => result.push(character),
        }
    }
    result
}

pub(crate) fn decimal_digit(c: char) -> Option<char> {
    let point = u32::from(c);
    let ranges = crate::unicode_data::DECIMAL_DIGITS;
    let index = ranges.partition_point(|(_, end)| *end < point);
    ranges
        .get(index)
        .filter(|(start, end)| *start <= point && point <= *end)
        .and_then(|(start, _)| char::from_u32(u32::from('0') + point - start))
}

// Shared strict record mechanics for the Domain's concrete, typed immutable models.
// This is deliberately not a dynamic model registry or an application serialization layer.
pub(crate) trait OnlyField: Sized {
    fn encode_field(&self) -> Value;
    fn decode_field(value: &Value) -> Result<Self, OnlyDomainError>;
    fn validate_field(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
}
impl OnlyField for String {
    fn encode_field(&self) -> Value {
        Value::String(self.clone())
    }
    fn decode_field(value: &Value) -> Result<Self, OnlyDomainError> {
        Ok(text(value, "string field")?.into())
    }
}
impl OnlyField for bool {
    fn encode_field(&self) -> Value {
        Value::Bool(*self)
    }
    fn decode_field(value: &Value) -> Result<Self, OnlyDomainError> {
        value
            .as_bool()
            .ok_or_else(|| invalid("boolean field required"))
    }
}
impl OnlyField for bigdecimal::num_bigint::BigInt {
    fn encode_field(&self) -> Value {
        use std::str::FromStr;
        Value::Number(
            serde_json::Number::from_str(&self.to_string())
                .expect("BigInt has a valid JSON integer spelling"),
        )
    }
    fn decode_field(value: &Value) -> Result<Self, OnlyDomainError> {
        value
            .as_number()
            .ok_or_else(|| invalid("integer field required"))?
            .to_string()
            .parse()
            .map_err(|_| invalid("integer field required"))
    }
}
impl OnlyField for crate::numeric::OnlyDecimal {
    fn encode_field(&self) -> Value {
        Value::String(self.to_string())
    }
    fn decode_field(value: &Value) -> Result<Self, OnlyDomainError> {
        text(value, "financial decimal")?.parse()
    }
}
impl<T: OnlyField> OnlyField for Option<T> {
    fn encode_field(&self) -> Value {
        self.as_ref().map_or(Value::Null, OnlyField::encode_field)
    }
    fn decode_field(value: &Value) -> Result<Self, OnlyDomainError> {
        if value.is_null() {
            Ok(None)
        } else {
            Ok(Some(T::decode_field(value)?))
        }
    }
    fn validate_field(&self) -> Result<(), OnlyDomainError> {
        if let Some(value) = self {
            value.validate_field()?;
        }
        Ok(())
    }
}
impl<T: OnlyField> OnlyField for Vec<T> {
    fn encode_field(&self) -> Value {
        Value::Array(self.iter().map(OnlyField::encode_field).collect())
    }
    fn decode_field(value: &Value) -> Result<Self, OnlyDomainError> {
        value
            .as_array()
            .ok_or_else(|| invalid("array field required"))?
            .iter()
            .map(T::decode_field)
            .collect()
    }
    fn validate_field(&self) -> Result<(), OnlyDomainError> {
        for value in self {
            value.validate_field()?;
        }
        Ok(())
    }
}
impl<A: OnlyField, B: OnlyField> OnlyField for (A, B) {
    fn encode_field(&self) -> Value {
        Value::Array(vec![self.0.encode_field(), self.1.encode_field()])
    }
    fn decode_field(value: &Value) -> Result<Self, OnlyDomainError> {
        let values = value
            .as_array()
            .filter(|values| values.len() == 2)
            .ok_or_else(|| invalid("two-element tuple required"))?;
        Ok((A::decode_field(&values[0])?, B::decode_field(&values[1])?))
    }
    fn validate_field(&self) -> Result<(), OnlyDomainError> {
        self.0.validate_field()?;
        self.1.validate_field()
    }
}
impl<T: OnlyField> OnlyField for std::collections::BTreeMap<String, T> {
    fn encode_field(&self) -> Value {
        Value::Object(
            self.iter()
                .map(|(key, value)| (key.clone(), value.encode_field()))
                .collect(),
        )
    }
    fn decode_field(value: &Value) -> Result<Self, OnlyDomainError> {
        value
            .as_object()
            .ok_or_else(|| invalid("object field required"))?
            .iter()
            .map(|(key, value)| Ok((key.clone(), T::decode_field(value)?)))
            .collect()
    }
    fn validate_field(&self) -> Result<(), OnlyDomainError> {
        for value in self.values() {
            value.validate_field()?;
        }
        Ok(())
    }
}
impl OnlyField for crate::time::OnlyUtcDateTime {
    fn encode_field(&self) -> Value {
        Value::String(self.to_string())
    }
    fn decode_field(value: &Value) -> Result<Self, OnlyDomainError> {
        text(value, "UTC datetime")?.parse()
    }
}
impl OnlyField for jiff::civil::Date {
    fn encode_field(&self) -> Value {
        Value::String(self.to_string())
    }
    fn decode_field(value: &Value) -> Result<Self, OnlyDomainError> {
        let input = text(value, "date")?;
        if !crate::time::date_spelling(input) {
            return Err(invalid("date requires YYYY-MM-DD text"));
        }
        let date: Self = input.parse().map_err(crate::time::time_error)?;
        date.validate_field()?;
        Ok(date)
    }
    fn validate_field(&self) -> Result<(), OnlyDomainError> {
        if self.year() < 1 {
            Err(invalid("date requires year 1..9999"))
        } else {
            Ok(())
        }
    }
}
impl OnlyField for jiff::civil::Time {
    fn encode_field(&self) -> Value {
        let mut value = format!(
            "{:02}:{:02}:{:02}",
            self.hour(),
            self.minute(),
            self.second()
        );
        let micros = self.subsec_nanosecond() / 1000;
        if micros != 0 {
            value.push_str(&format!(".{micros:06}"));
        }
        Value::String(value)
    }
    fn decode_field(value: &Value) -> Result<Self, OnlyDomainError> {
        let text = text(value, "wall time")?;
        if !crate::time::wall_spelling(text) {
            return Err(invalid("invalid local wall time"));
        }
        let time: Self = text.parse().map_err(crate::time::time_error)?;
        time.validate_field()?;
        Ok(time)
    }
    fn validate_field(&self) -> Result<(), OnlyDomainError> {
        if self.subsec_nanosecond() % 1000 != 0 {
            Err(invalid("wall time requires microsecond precision"))
        } else {
            Ok(())
        }
    }
}

macro_rules! domain_field {
    ($name:ty) => {
        impl $crate::base::OnlyField for $name {
            fn encode_field(&self) -> serde_json::Value {
                <$name as $crate::base::OnlyDomainModel>::to_record(self)
            }
            fn decode_field(
                value: &serde_json::Value,
            ) -> Result<Self, $crate::errors::OnlyDomainError> {
                <$name as $crate::base::OnlyDomainModel>::from_record(value)
            }
        }
    };
}
pub(crate) use domain_field;

macro_rules! domain_model {
 ($name:ident,$input:ident,$version:literal,$tag:expr,{$($field:ident:$ty:ty),*$(,)?}$(,prepare=$prepare:path)?$(,exact_record=$exact_record:literal)?)=> {
  #[derive(Clone,Debug,PartialEq,Eq)]
  pub struct $input {$(pub $field:$ty),*}
  #[derive(Clone,Debug,PartialEq,Eq)]
  pub struct $name {fields:$input}
  impl $name {
   pub fn new(fields:$input)->Result<Self,$crate::errors::OnlyDomainError> {
    $(let fields=$prepare(fields)?;)?
    $($crate::base::OnlyField::validate_field(&fields.$field)?;)*
    let value=Self{fields};value.validate()?;Ok(value)
   }
   pub fn input(&self)->$input {self.fields.clone()}
   $(pub fn $field(&self)->&$ty {&self.fields.$field})*
  }
  impl $crate::base::OnlyDomainModel for $name {
   fn to_record(&self)->serde_json::Value {
    let mut row=serde_json::Map::new();row.insert("schema_version".into(),serde_json::json!($version));
    let tag:Option<&str>=$tag;
    if let Some(tag)=tag {row.insert("model_type".into(),serde_json::Value::String(tag.into()));}
    $(row.insert(stringify!($field).into(),$crate::base::OnlyField::encode_field(&self.fields.$field));)*
    serde_json::Value::Object(row)
   }
   fn from_record(value:&serde_json::Value)->Result<Self,$crate::errors::OnlyDomainError> {
    (|| {
     let mut names=vec![$(stringify!($field)),*];let tag:Option<&str>=$tag;
     if tag.is_some(){names.push("model_type");}
     let row=$crate::base::record(value,$version,&names)?;
     if tag.is_some_and(|tag|row["model_type"].as_str()!=Some(tag)){return Err($crate::base::invalid("instrument model_type mismatch"));}
     let result=Self::new($input {$($field: <$ty as $crate::base::OnlyField>::decode_field(&row[stringify!($field)])?),*})?;
     $(if $exact_record && result.to_record()!=*value {return Err($crate::base::invalid("noncanonical domain record"));})?
     Ok(result)
    })().map_err($crate::value::serialization)
   }
  }
  $crate::base::domain_field!($name);
 };
}
pub(crate) use domain_model;

impl OnlyField for i8 {
    fn encode_field(&self) -> Value {
        serde_json::json!(*self)
    }
    fn decode_field(value: &Value) -> Result<Self, OnlyDomainError> {
        value
            .as_i64()
            .and_then(|value| i8::try_from(value).ok())
            .ok_or_else(|| invalid("bounded integer field required"))
    }
}

impl OnlyField for u8 {
    fn encode_field(&self) -> Value {
        serde_json::json!(*self)
    }
    fn decode_field(value: &Value) -> Result<Self, OnlyDomainError> {
        value
            .as_u64()
            .and_then(|value| u8::try_from(value).ok())
            .ok_or_else(|| invalid("bounded unsigned integer field required"))
    }
}
