//! Explicit UTC instants and IANA rules from the pinned shared TZif dataset.
use crate::{
    base::{OnlyDomainModel, OnlyField, invalid, record, text},
    errors::OnlyDomainError,
    value::serialization,
};
use bigdecimal::num_bigint::BigInt;
use jiff::civil::{Date, DateTime};
use num_integer::Integer;
use serde_json::{Number, Value, json};
use std::{
    cmp::Ordering,
    fmt,
    hash::{Hash, Hasher},
    str::FromStr,
};
use tz::{TimeZone, UtcDateTime, datetime::FoundDateTimeKind};

pub const ONLY_TIMEZONE_DATASET: &str = "tzdata-2026.3-iana-2026c";

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct OnlyTimestamp {
    unix_nanos: BigInt,
}
impl OnlyTimestamp {
    pub fn from_unix_nanos(value: BigInt) -> Self {
        Self { unix_nanos: value }
    }
    pub fn from_unix_micros(value: BigInt) -> Self {
        Self::from_unix_nanos(value * 1000_u32)
    }
    pub fn from_unix_millis(value: BigInt) -> Self {
        Self::from_unix_nanos(value * 1_000_000_u32)
    }
    pub fn from_unix_seconds(value: BigInt) -> Self {
        Self::from_unix_nanos(value * 1_000_000_000_u32)
    }
    pub fn from_datetime(value: OnlyUtcDateTime) -> Self {
        Self::from_unix_nanos(BigInt::from(value.0.total_nanoseconds()))
    }
    pub fn unix_nanos(&self) -> &BigInt {
        &self.unix_nanos
    }
    pub fn to_unix_nanos(&self) -> BigInt {
        self.unix_nanos.clone()
    }
    pub fn to_unix_micros(&self) -> BigInt {
        self.unix_nanos.div_floor(&BigInt::from(1000_u32))
    }
    pub fn to_unix_millis(&self) -> BigInt {
        self.unix_nanos.div_floor(&BigInt::from(1_000_000_u32))
    }
    pub fn to_unix_seconds(&self) -> BigInt {
        self.unix_nanos.div_floor(&BigInt::from(1_000_000_000_u32))
    }
    pub fn to_datetime(&self) -> Result<OnlyUtcDateTime, OnlyDomainError> {
        let micros = self
            .to_unix_micros()
            .to_string()
            .parse::<i64>()
            .map_err(|_| invalid("datetime is outside years 1..9999"))?;
        OnlyUtcDateTime::new(
            UtcDateTime::from_total_nanoseconds(i128::from(micros) * 1000).map_err(time_error)?,
        )
    }
}
impl OnlyDomainModel for OnlyTimestamp {
    fn to_record(&self) -> Value {
        let integer = Number::from_str(&self.unix_nanos.to_string())
            .expect("BigInt always has a valid JSON integer spelling");
        json!({"schema_version":1,"unix_nanos":integer})
    }
    fn from_record(value: &Value) -> Result<Self, OnlyDomainError> {
        (|| {
            let row = record(value, 1, &["unix_nanos"])?;
            let number = row["unix_nanos"]
                .as_number()
                .ok_or_else(|| invalid("unix_nanos must be an integer"))?;
            let value = BigInt::from_str(&number.to_string())
                .map_err(|_| invalid("unix_nanos must be an integer"))?;
            Ok(Self::from_unix_nanos(value))
        })()
        .map_err(serialization)
    }
}

/// A Python datetime-compatible absolute UTC time; microseconds and years 1..9999.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct OnlyUtcDateTime(pub(crate) UtcDateTime);
impl OnlyUtcDateTime {
    pub(crate) fn new(timestamp: UtcDateTime) -> Result<Self, OnlyDomainError> {
        if !(1..=9999).contains(&timestamp.year())
            || timestamp.second() >= 60
            || !timestamp.nanoseconds().is_multiple_of(1000)
        {
            return Err(invalid(
                "UTC datetime requires years 1..9999, seconds 0..59 and microsecond precision",
            ));
        }
        Ok(Self(timestamp))
    }
    pub fn timestamp(self) -> UtcDateTime {
        self.0
    }
    pub fn date(self) -> Date {
        Date::new(
            self.0.year() as i16,
            self.0.month() as i8,
            self.0.month_day() as i8,
        )
        .expect("validated UTC date is representable")
    }
    pub(crate) fn from_zoned(local: &tz::DateTime) -> Result<Self, OnlyDomainError> {
        if !(1..=9999).contains(&local.year())
            || local.second() >= 60
            || !local.nanoseconds().is_multiple_of(1000)
        {
            return Err(invalid(
                "local datetime is outside the canonical date/precision range",
            ));
        }
        Self::new(
            UtcDateTime::from_timespec(local.unix_time(), local.nanoseconds())
                .map_err(time_error)?,
        )
    }
}
impl Hash for OnlyUtcDateTime {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.0.total_nanoseconds().hash(state);
    }
}
pub(crate) fn date_spelling(value: &str) -> bool {
    value.len() == 10
        && value.bytes().enumerate().all(|(index, byte)| {
            if matches!(index, 4 | 7) {
                byte == b'-'
            } else {
                byte.is_ascii_digit()
            }
        })
}
pub(crate) fn wall_spelling(value: &str) -> bool {
    let (clock, fraction) = value
        .split_once('.')
        .map_or((value, None), |(clock, fraction)| (clock, Some(fraction)));
    clock.len() == 8
        && clock.bytes().enumerate().all(|(index, byte)| {
            if matches!(index, 2 | 5) {
                byte == b':'
            } else {
                byte.is_ascii_digit()
            }
        })
        && clock.get(0..2).is_some_and(|hour| hour < "24")
        && clock.get(3..5).is_some_and(|minute| minute < "60")
        && clock.get(6..8).is_some_and(|second| second < "60")
        && fraction.is_none_or(|fraction| {
            (1..=6).contains(&fraction.len()) && fraction.bytes().all(|byte| byte.is_ascii_digit())
        })
}
impl FromStr for OnlyUtcDateTime {
    type Err = OnlyDomainError;
    fn from_str(value: &str) -> Result<Self, Self::Err> {
        let body = value
            .strip_suffix('Z')
            .or_else(|| value.strip_suffix("+00:00"))
            .ok_or_else(|| invalid("absolute datetime requires an explicit UTC suffix"))?;
        let (date, time) = body
            .split_once('T')
            .ok_or_else(|| invalid("absolute datetime requires UTC ISO text"))?;
        if !date_spelling(date) || !wall_spelling(time) {
            return Err(invalid(
                "absolute datetime requires UTC ISO text and at most microsecond precision",
            ));
        }
        let civil: DateTime = body.parse().map_err(time_error)?;
        Self::new(
            UtcDateTime::new(
                i32::from(civil.year()),
                civil.month() as u8,
                civil.day() as u8,
                civil.hour() as u8,
                civil.minute() as u8,
                civil.second() as u8,
                civil.subsec_nanosecond() as u32,
            )
            .map_err(time_error)?,
        )
    }
}
impl fmt::Display for OnlyUtcDateTime {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}",
            self.0.year(),
            self.0.month(),
            self.0.month_day(),
            self.0.hour(),
            self.0.minute(),
            self.0.second()
        )?;
        let micros = self.0.nanoseconds() / 1000;
        if micros != 0 {
            write!(f, ".{micros:06}")?;
        }
        f.write_str("Z")
    }
}

#[derive(Clone, Debug)]
pub struct OnlyTimeZone {
    name: String,
    zone: TimeZone,
}
impl PartialEq for OnlyTimeZone {
    fn eq(&self, other: &Self) -> bool {
        self.name == other.name
    }
}
impl Eq for OnlyTimeZone {}
impl PartialOrd for OnlyTimeZone {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
impl Ord for OnlyTimeZone {
    fn cmp(&self, other: &Self) -> Ordering {
        self.name.cmp(&other.name)
    }
}
impl Hash for OnlyTimeZone {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.name.hash(state);
    }
}
impl OnlyTimeZone {
    pub fn new(name: &str) -> Result<Self, OnlyDomainError> {
        let name = name.trim_matches(crate::base::whitespace);
        let zones = crate::tzdb_rules::ZONES;
        let index = zones
            .binary_search_by_key(&name, |(key, _)| *key)
            .map_err(|_| invalid("unknown IANA timezone in the pinned dataset"))?;
        let zone = TimeZone::from_tz_data(zones[index].1).map_err(time_error)?;
        Ok(Self {
            name: name.into(),
            zone,
        })
    }
    pub fn name(&self) -> &str {
        &self.name
    }
    pub fn to_local(&self, value: OnlyUtcDateTime) -> Result<tz::DateTime, OnlyDomainError> {
        let local = value.0.project(self.zone.as_ref()).map_err(time_error)?;
        if !(1..=9999).contains(&local.year()) {
            return Err(invalid("local datetime is outside years 1..9999"));
        }
        Ok(local)
    }
    /// Wall time for calendar arithmetic. Use `to_local` to retain the absolute instant.
    pub fn to_civil(&self, value: OnlyUtcDateTime) -> Result<DateTime, OnlyDomainError> {
        let local = self.to_local(value)?;
        DateTime::new(
            local.year() as i16,
            local.month() as i8,
            local.month_day() as i8,
            local.hour() as i8,
            local.minute() as i8,
            local.second() as i8,
            local.nanoseconds() as i32,
        )
        .map_err(time_error)
    }
    /// Projections only bound unresolved boundaries; they never resolve gaps/folds.
    pub(crate) fn boundary_projections(
        &self,
        local: DateTime,
    ) -> Result<Vec<i128>, OnlyDomainError> {
        let found = tz::DateTime::find(
            i32::from(local.year()),
            local.month() as u8,
            local.day() as u8,
            local.hour() as u8,
            local.minute() as u8,
            local.second() as u8,
            local.subsec_nanosecond() as u32,
            self.zone.as_ref(),
        )
        .map_err(time_error)?
        .into_inner();
        if found.is_empty() {
            return Err(invalid("local datetime has no UTC mapping"));
        }
        let mut projections = Vec::new();
        for item in found {
            let offsets = match item {
                FoundDateTimeKind::Normal(value) => vec![*value.local_time_type()],
                FoundDateTimeKind::Skipped {
                    before_transition,
                    after_transition,
                } => vec![
                    *before_transition.local_time_type(),
                    *after_transition.local_time_type(),
                ],
            };
            for offset in offsets {
                let projection = tz::DateTime::new(
                    i32::from(local.year()),
                    local.month() as u8,
                    local.day() as u8,
                    local.hour() as u8,
                    local.minute() as u8,
                    local.second() as u8,
                    local.subsec_nanosecond() as u32,
                    offset,
                )
                .map_err(time_error)?;
                let nanos = i128::from(projection.unix_time()) * 1_000_000_000
                    + i128::from(projection.nanoseconds());
                projections.push(nanos);
            }
        }
        projections.sort_unstable();
        projections.dedup();
        Ok(projections)
    }
    pub fn to_utc(
        &self,
        local: DateTime,
        fold: Option<u8>,
    ) -> Result<OnlyUtcDateTime, OnlyDomainError> {
        if local.year() < 1 || local.subsec_nanosecond() % 1000 != 0 {
            return Err(invalid(
                "local datetime is outside the canonical date/precision range",
            ));
        }
        if fold.is_some_and(|value| value > 1) {
            return Err(invalid("requested fold is invalid"));
        }
        let found = tz::DateTime::find(
            i32::from(local.year()),
            local.month() as u8,
            local.day() as u8,
            local.hour() as u8,
            local.minute() as u8,
            local.second() as u8,
            local.subsec_nanosecond() as u32,
            self.zone.as_ref(),
        )
        .map_err(time_error)?
        .into_inner();
        let mut candidates = Vec::new();
        for item in found {
            match item {
                FoundDateTimeKind::Normal(value) => candidates.push(
                    UtcDateTime::from_timespec(value.unix_time(), value.nanoseconds())
                        .map_err(time_error)?,
                ),
                FoundDateTimeKind::Skipped { .. } => {
                    return Err(invalid("local datetime does not exist in market timezone"));
                }
            }
        }
        candidates.sort_unstable();
        candidates.dedup();
        let timestamp = match candidates.as_slice() {
            [only] => *only,
            [earlier, later] => match fold {
                Some(0) => *earlier,
                Some(1) => *later,
                _ => return Err(invalid("local datetime is ambiguous; fold is required")),
            },
            _ => {
                return Err(invalid(
                    "local datetime has no uniquely disambiguated UTC mapping",
                ));
            }
        };
        OnlyUtcDateTime::new(timestamp)
    }
}
impl OnlyDomainModel for OnlyTimeZone {
    fn to_record(&self) -> Value {
        json!({"schema_version":1,"name":self.name})
    }
    fn from_record(value: &Value) -> Result<Self, OnlyDomainError> {
        (|| {
            let row = record(value, 1, &["name"])?;
            Self::new(text(&row["name"], "name")?)
        })()
        .map_err(serialization)
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct OnlyTradingDay {
    value: Date,
}
impl OnlyTradingDay {
    pub fn new(value: Date) -> Result<Self, OnlyDomainError> {
        if value.year() < 1 {
            return Err(invalid("date requires year 1..9999"));
        }
        Ok(Self { value })
    }
    pub fn value(self) -> Date {
        self.value
    }
}
impl OnlyDomainModel for OnlyTradingDay {
    fn to_record(&self) -> Value {
        json!({"schema_version":1,"value":self.value.to_string()})
    }
    fn from_record(value: &Value) -> Result<Self, OnlyDomainError> {
        (|| {
            let row = record(value, 1, &["value"])?;
            Self::new(Date::decode_field(&row["value"])?)
        })()
        .map_err(serialization)
    }
}
pub(crate) fn time_error(error: impl fmt::Display) -> OnlyDomainError {
    invalid(&error.to_string())
}
crate::base::domain_field!(OnlyTimestamp);
crate::base::domain_field!(OnlyTimeZone);
crate::base::domain_field!(OnlyTradingDay);

#[cfg(test)]
mod tests {
    #[test]
    fn all_pinned_tzif_files_parse_without_system_discovery() {
        for (name, _) in crate::tzdb_rules::ZONES {
            super::OnlyTimeZone::new(name).unwrap();
        }
    }
}
