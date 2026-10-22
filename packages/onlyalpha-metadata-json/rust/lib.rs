//! Product metadata JSON identity, including the existing Python binary64 string policy.
//! The caller supplies an operational parsing-work budget; exhausting it is
//! unavailable, never proof that immutable history is corrupt or absent.
use serde::{
    Deserialize, Deserializer,
    de::{MapAccess, Visitor},
};
use serde_json::value::RawValue;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, fmt};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Invalid,
    Unavailable,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "METADATA_JSON_INVALID",
            Self::Unavailable => "METADATA_JSON_UNAVAILABLE",
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        output.write_str(self.code())
    }
}
impl std::error::Error for Error {}

struct Fields<'a>(BTreeMap<String, &'a RawValue>);
impl<'de> Deserialize<'de> for Fields<'de> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct ObjectVisitor;
        impl<'de> Visitor<'de> for ObjectVisitor {
            type Value = Fields<'de>;
            fn expecting(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
                output.write_str("a JSON object")
            }
            fn visit_map<M: MapAccess<'de>>(self, mut map: M) -> Result<Self::Value, M::Error> {
                let mut fields = BTreeMap::new();
                while let Some(key) = map.next_key::<String>()? {
                    if fields.contains_key(&key) {
                        return Err(serde::de::Error::custom("duplicate JSON field"));
                    }
                    fields.insert(key, map.next_value::<&RawValue>()?);
                }
                Ok(Fields(fields))
            }
        }
        // No Value visitor: its private Number/RawValue marker keys are not JSON semantics.
        deserializer.deserialize_map(ObjectVisitor)
    }
}
pub fn object_fields(input: &str) -> Result<BTreeMap<String, &RawValue>, Error> {
    serde_json::from_str::<Fields<'_>>(input)
        .map(|fields| fields.0)
        .map_err(|_| Error::Invalid)
}
fn quoted(value: &str) -> Result<String, Error> {
    serde_json::to_string(value).map_err(|_| Error::Invalid)
}

fn python_float_text(value: f64) -> Result<String, Error> {
    if !value.is_finite() {
        return Err(Error::Invalid);
    }
    // Pinned serde_json/zmij owns shortest, nearest-even digit generation.
    // Only notation changes here: Python scientific threshold and exponent spelling.
    let mut number = serde_json::to_string(&value).map_err(|_| Error::Invalid)?;
    let (sign, absolute) = if let Some(absolute) = number.strip_prefix('-') {
        ("-", absolute)
    } else {
        ("", number.as_str())
    };
    if let Some(fraction) = absolute.strip_prefix("0.")
        && let Some(first) = fraction.bytes().position(|byte| byte != b'0')
        && first >= 4
    {
        let digits = &fraction[first..];
        let tail = if digits.len() > 1 {
            format!(".{}", &digits[1..])
        } else {
            String::new()
        };
        number = format!("{sign}{}{tail}e-{}", &digits[..1], first + 1);
    }
    if let Some((mantissa, exponent)) = number.split_once('e') {
        let exponent: i32 = exponent.parse().map_err(|_| Error::Invalid)?;
        number = format!("{mantissa}e{exponent:+03}");
    }
    Ok(number)
}
#[derive(Clone, Copy)]
enum FloatPolicy {
    Metadata,
    Integral,
}
fn scalar(raw: &str, policy: FloatPolicy) -> Result<String, Error> {
    match raw.as_bytes().first().copied() {
        Some(b'"') => quoted(&serde_json::from_str::<String>(raw).map_err(|_| Error::Invalid)?),
        Some(b'n' | b't' | b'f') => Ok(raw.to_owned()), // Already validated by RawValue.
        Some(b'-' | b'0'..=b'9') => {
            if raw.contains(['.', 'e', 'E']) {
                let value = raw.parse::<f64>().map_err(|_| Error::Invalid)?;
                if !value.is_finite() {
                    return Err(Error::Invalid);
                }
                match policy {
                    FloatPolicy::Metadata => quoted(&python_float_text(value)?),
                    FloatPolicy::Integral if value.fract() == 0.0 => Ok(if value == 0.0 {
                        "0".into()
                    } else {
                        format!("{value:.0}")
                    }),
                    FloatPolicy::Integral => python_float_text(value),
                }
            } else {
                // JSON grammar has already proved sign/digits/no leading zeros.
                Ok(if raw == "-0" {
                    "0".to_owned()
                } else {
                    raw.to_owned()
                })
            }
        }
        _ => Err(Error::Invalid),
    }
}

/// Canonical JSON for the existing Product metadata identity contract, not a generic
/// financial value codec. Work counts raw bytes traversed by maintained parsers,
/// including rescans of nested subtrees; callers must bound their operational IO.
pub fn canonical_json(input: &str, max_work: usize) -> Result<String, Error> {
    encode(input, max_work, FloatPolicy::Metadata)
}
/// Existing Python command-document JSON: integral binary64 values become exact
/// integers; other floats remain Python-spelled JSON numbers. This is separate
/// from metadata identity. The budget caps both traversal work and emitted bytes.
pub fn integral_float_json(input: &str, max_work: usize) -> Result<String, Error> {
    encode(input, max_work, FloatPolicy::Integral)
}
fn append(
    output: &mut String,
    value: &str,
    policy: FloatPolicy,
    max_work: usize,
) -> Result<(), Error> {
    if matches!(policy, FloatPolicy::Integral)
        && output
            .len()
            .checked_add(value.len())
            .is_none_or(|length| length > max_work)
    {
        return Err(Error::Unavailable);
    }
    output.push_str(value);
    Ok(())
}
fn encode(input: &str, max_work: usize, policy: FloatPolicy) -> Result<String, Error> {
    if input.len() > max_work {
        return Err(Error::Unavailable);
    }
    let root: &RawValue = serde_json::from_str(input).map_err(|_| Error::Invalid)?;
    enum Work<'a> {
        Raw(&'a RawValue),
        Text(&'static str),
        Key(String),
    }
    let mut pending = vec![Work::Raw(root)];
    let mut output = String::new();
    // Include initial whole-document validation, then reserve each subsequent scan.
    let mut work = input.len();
    while let Some(item) = pending.pop() {
        match item {
            Work::Text(value) => append(&mut output, value, policy, max_work)?,
            Work::Key(value) => append(&mut output, &quoted(&value)?, policy, max_work)?,
            Work::Raw(raw) => {
                work = work
                    .checked_add(raw.get().len())
                    .filter(|value| *value <= max_work)
                    .ok_or(Error::Unavailable)?;
                match raw.get().as_bytes().first().copied() {
                    Some(b'{') => {
                        let Fields(fields) = serde_json::from_str::<Fields<'_>>(raw.get())
                            .map_err(|_| Error::Invalid)?;
                        pending.push(Work::Text("}"));
                        for (index, (key, child)) in fields.into_iter().enumerate().rev() {
                            pending.push(Work::Raw(child));
                            pending.push(Work::Text(":"));
                            pending.push(Work::Key(key));
                            if index != 0 {
                                pending.push(Work::Text(","));
                            }
                        }
                        pending.push(Work::Text("{"));
                    }
                    Some(b'[') => {
                        let values: Vec<&RawValue> =
                            serde_json::from_str(raw.get()).map_err(|_| Error::Invalid)?;
                        pending.push(Work::Text("]"));
                        for (index, child) in values.into_iter().enumerate().rev() {
                            pending.push(Work::Raw(child));
                            if index != 0 {
                                pending.push(Work::Text(","));
                            }
                        }
                        pending.push(Work::Text("["));
                    }
                    _ => append(&mut output, &scalar(raw.get(), policy)?, policy, max_work)?,
                }
            }
        }
    }
    // The partial buffer is private and is discarded on any error. Budget exhaustion
    // before a semantic check proves unavailability, not a corrupt/absent record.
    Ok(output)
}
pub fn fingerprint(input: &str, max_work: usize) -> Result<String, Error> {
    Ok(Sha256::digest(canonical_json(input, max_work)?.as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect())
}
