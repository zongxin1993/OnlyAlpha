//! Pure provider-neutral public Integration declarations; no runtime admission.
use bigdecimal::BigDecimal;
use onlyalpha_metadata_json as metadata;
use serde::Deserialize;
use serde_json::value::RawValue;
use std::{collections::BTreeMap, fmt, str::FromStr};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Type,
    Configuration,
    Probe,
    Unavailable,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Type => "INTEGRATION_TYPE_CONTRACT_INVALID",
            Self::Configuration => "INTEGRATION_CONFIGURATION_CONTRACT_INVALID",
            Self::Probe => "INTEGRATION_PROBE_CONTRACT_INVALID",
            Self::Unavailable => "INTEGRATION_CONTRACT_UNAVAILABLE",
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}
fn metadata_error(error: metadata::Error) -> Error {
    match error {
        metadata::Error::Invalid => Error::Type,
        metadata::Error::Unavailable => Error::Unavailable,
    }
}
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct IntegrationTypeId(String);
impl IntegrationTypeId {
    pub fn new(value: &str) -> Result<Self, Error> {
        if value.split(['.', '_']).any(|part| {
            part.is_empty()
                || part == "latest"
                || !part
                    .bytes()
                    .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
        }) {
            Err(Error::Type)
        } else {
            Ok(Self(value.into()))
        }
    }
    pub fn value(&self) -> &str {
        &self.0
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Category {
    DataSource,
    Broker,
    AgentProvider,
}
impl Category {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::DataSource => "DATA_SOURCE",
            Self::Broker => "BROKER",
            Self::AgentProvider => "AGENT_PROVIDER",
        }
    }
}
impl FromStr for Category {
    type Err = Error;
    fn from_str(value: &str) -> Result<Self, Error> {
        match value {
            "DATA_SOURCE" => Ok(Self::DataSource),
            "BROKER" => Ok(Self::Broker),
            "AGENT_PROVIDER" => Ok(Self::AgentProvider),
            _ => Err(Error::Type),
        }
    }
}
pub fn valid_field_id(value: &str) -> bool {
    let mut bytes = value.bytes();
    bytes.next().is_some_and(|b| b.is_ascii_lowercase())
        && bytes.all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
}
fn stable(value: &str) -> bool {
    !value.split(['.', '_', '-']).any(|part| {
        part.is_empty()
            || !part
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit())
    })
}
fn nonblank(value: &str) -> bool {
    value
        .chars()
        .any(|c| !(c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}')))
}
type Fields<'a> = BTreeMap<String, &'a RawValue>;
fn object(raw: &RawValue) -> Result<Fields<'_>, Error> {
    metadata::object_fields(raw.get()).map_err(metadata_error)
}
fn read<'a, T: Deserialize<'a>>(fields: &Fields<'a>, key: &str) -> Result<T, Error> {
    serde_json::from_str(fields.get(key).ok_or(Error::Type)?.get()).map_err(|_| Error::Type)
}
fn closed(fields: &Fields<'_>, keys: &[&str]) -> Result<(), Error> {
    if fields.len() != keys.len() || keys.iter().any(|key| !fields.contains_key(*key)) {
        Err(Error::Type)
    } else {
        Ok(())
    }
}
fn sorted<T: Ord>(values: &[T]) -> bool {
    values.windows(2).all(|pair| pair[0] < pair[1])
}
fn component(fields: &Fields<'_>, work: usize) -> Result<String, Error> {
    let declared: String = read(fields, "fingerprint")?;
    let content: BTreeMap<_, _> = fields
        .iter()
        .filter(|(key, _)| key.as_str() != "fingerprint")
        .collect();
    let raw = serde_json::to_string(&content).map_err(|_| Error::Type)?;
    let actual = metadata::fingerprint(&raw, work).map_err(metadata_error)?;
    if actual != declared {
        Err(Error::Type)
    } else {
        Ok(actual)
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ValueKind {
    String,
    Integer,
    Number,
    Boolean,
    Enum,
    Duration,
    Path,
    StringIntegerMap,
}
impl FromStr for ValueKind {
    type Err = Error;
    fn from_str(value: &str) -> Result<Self, Error> {
        match value {
            "STRING" => Ok(Self::String),
            "INTEGER" => Ok(Self::Integer),
            "NUMBER" => Ok(Self::Number),
            "BOOLEAN" => Ok(Self::Boolean),
            "ENUM" => Ok(Self::Enum),
            "DURATION" => Ok(Self::Duration),
            "PATH" => Ok(Self::Path),
            "STRING_INTEGER_MAP" => Ok(Self::StringIntegerMap),
            _ => Err(Error::Configuration),
        }
    }
}
fn integer(value: &RawValue) -> bool {
    let value = value.get().trim();
    matches!(value.as_bytes().first(), Some(b'-' | b'0'..=b'9')) && !value.contains(['.', 'e', 'E'])
}
fn number(value: &RawValue) -> Option<BigDecimal> {
    let text = value.get().trim();
    if !matches!(text.as_bytes().first(), Some(b'-' | b'0'..=b'9')) {
        return None;
    }
    if integer(value) {
        text.parse().ok()
    } else {
        let value: f64 = text.parse().ok()?;
        BigDecimal::try_from(value).ok()
    }
}
pub struct Field {
    id: String,
    kind: ValueKind,
    required: bool,
    secret: bool,
    default: Option<Box<RawValue>>,
    enum_values: Vec<String>,
    minimum: Option<BigDecimal>,
    maximum: Option<BigDecimal>,
    exclusive_minimum: bool,
}
impl Field {
    fn restore(raw: &RawValue) -> Result<Self, Error> {
        let fields = object(raw)?;
        closed(
            &fields,
            &[
                "field_id",
                "value_kind",
                "required",
                "default",
                "secret",
                "advanced",
                "display_name",
                "description",
                "enum_values",
                "minimum",
                "maximum",
                "exclusive_minimum",
            ],
        )?;
        let id: String = read(&fields, "field_id")?;
        let display: String = read(&fields, "display_name")?;
        let _: String = read(&fields, "description")?;
        let _: bool = read(&fields, "advanced")?;
        let kind: ValueKind = read::<String>(&fields, "value_kind")?.parse()?;
        let required: bool = read(&fields, "required")?;
        let secret: bool = read(&fields, "secret")?;
        let enum_values: Vec<String> = read(&fields, "enum_values")?;
        let exclusive_minimum: bool = read(&fields, "exclusive_minimum")?;
        let optional = |key: &str| -> Result<Option<&RawValue>, Error> {
            let value = *fields.get(key).ok_or(Error::Type)?;
            Ok((value.get() != "null").then_some(value))
        };
        let default = optional("default")?.map(RawValue::to_owned);
        let minimum = optional("minimum")?
            .map(|value| number(value).ok_or(Error::Configuration))
            .transpose()?;
        let maximum = optional("maximum")?
            .map(|value| number(value).ok_or(Error::Configuration))
            .transpose()?;
        let numeric = matches!(
            kind,
            ValueKind::Integer | ValueKind::Number | ValueKind::Duration
        );
        if !valid_field_id(&id)
            || !nonblank(&display)
            || !sorted(&enum_values)
            || enum_values.iter().any(String::is_empty)
            || (kind == ValueKind::Enum && enum_values.is_empty())
            || (kind != ValueKind::Enum && !enum_values.is_empty())
            || (!numeric && (minimum.is_some() || maximum.is_some()))
            || (exclusive_minimum && minimum.is_none())
            || minimum
                .as_ref()
                .zip(maximum.as_ref())
                .is_some_and(|(min, max)| min > max)
            || (secret && default.is_some())
        {
            return Err(Error::Configuration);
        }
        let field = Self {
            id,
            kind,
            required,
            secret,
            default,
            enum_values,
            minimum,
            maximum,
            exclusive_minimum,
        };
        if let Some(default) = field.default.as_ref() {
            if kind == ValueKind::StringIntegerMap || !field.matches_kind(default) {
                return Err(Error::Configuration);
            }
            if numeric {
                // The existing SPI checks numeric defaults through Python binary64,
                // including integer defaults. Runtime value normalization is separate.
                let value: f64 = default.get().parse().map_err(|_| Error::Configuration)?;
                let exact = BigDecimal::try_from(value).map_err(|_| Error::Configuration)?;
                if !field.in_bounds(&exact) {
                    return Err(Error::Configuration);
                }
            }
        }
        Ok(field)
    }
    fn matches_kind(&self, value: &RawValue) -> bool {
        match self.kind {
            ValueKind::String | ValueKind::Path => {
                serde_json::from_str::<String>(value.get()).is_ok()
            }
            ValueKind::Enum => serde_json::from_str::<String>(value.get())
                .is_ok_and(|text| self.enum_values.contains(&text)),
            ValueKind::Boolean => serde_json::from_str::<bool>(value.get()).is_ok(),
            ValueKind::Integer => integer(value),
            ValueKind::Number | ValueKind::Duration => {
                number(value).is_some() && value.get().parse::<f64>().is_ok_and(f64::is_finite)
            }
            ValueKind::StringIntegerMap => object(value).is_ok_and(|values| {
                values
                    .iter()
                    .all(|(key, value)| !key.is_empty() && integer(value))
            }),
        }
    }
    fn in_bounds(&self, value: &BigDecimal) -> bool {
        !self
            .minimum
            .as_ref()
            .is_some_and(|min| value < min || (self.exclusive_minimum && value == min))
            && !self.maximum.as_ref().is_some_and(|max| value > max)
    }
    /// Input must already have passed the caller's full JSON/work validation.
    pub fn accepts(&self, value: &RawValue) -> bool {
        self.matches_kind(value)
            && (!matches!(
                self.kind,
                ValueKind::Integer | ValueKind::Number | ValueKind::Duration
            ) || number(value).is_some_and(|value| self.in_bounds(&value)))
    }
    pub fn id(&self) -> &str {
        &self.id
    }
    pub fn kind(&self) -> ValueKind {
        self.kind
    }
    pub fn required(&self) -> bool {
        self.required
    }
    pub fn secret(&self) -> bool {
        self.secret
    }
    pub fn default(&self) -> Option<&RawValue> {
        self.default.as_deref()
    }
}
pub struct Probe {
    default_instrument: String,
    user_selectable: bool,
    fingerprint: String,
}
impl Probe {
    fn restore(raw: &RawValue, work: usize) -> Result<Self, Error> {
        let fields = object(raw)?;
        closed(
            &fields,
            &[
                "probe_version",
                "probe_mode",
                "default_probe_instrument",
                "user_selectable_probe_instrument",
                "probe_checks",
                "fingerprint",
            ],
        )?;
        let version: u32 = read(&fields, "probe_version")?;
        let mode: String = read(&fields, "probe_mode")?;
        let default_instrument: String = read(&fields, "default_probe_instrument")?;
        let user_selectable: bool = read(&fields, "user_selectable_probe_instrument")?;
        let checks: Vec<String> = read(&fields, "probe_checks")?;
        if version != 1
            || mode != "DEFAULT_INSTRUMENT"
            || !nonblank(&default_instrument)
            || checks.is_empty()
            || !sorted(&checks)
            || checks.iter().any(|check| {
                !matches!(
                    check.as_str(),
                    "CONNECTIVITY"
                        | "AUTHENTICATION"
                        | "REFERENCE_DATA"
                        | "HISTORICAL_DATA"
                        | "REALTIME_DATA"
                        | "MODEL_DISCOVERY"
                )
            })
        {
            return Err(Error::Probe);
        }
        Ok(Self {
            default_instrument,
            user_selectable,
            fingerprint: component(&fields, work)?,
        })
    }
    pub fn default_instrument(&self) -> &str {
        &self.default_instrument
    }
    pub fn user_selectable(&self) -> bool {
        self.user_selectable
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
}
pub struct Descriptor {
    document: Box<RawValue>,
    id: IntegrationTypeId,
    category: Category,
    fields: Vec<Field>,
    probe: Option<Probe>,
    fingerprint: String,
    configuration_fingerprint: String,
}
impl Descriptor {
    pub fn from_json(input: &str, work: usize) -> Result<Self, Error> {
        let fingerprint = metadata::fingerprint(input, work).map_err(metadata_error)?;
        let document = RawValue::from_string(input.into()).map_err(|_| Error::Type)?;
        let fields = object(&document)?;
        closed(
            &fields,
            &[
                "schema_version",
                "type_id",
                "category",
                "display_name",
                "description",
                "provider_id",
                "implementation_id",
                "implementation_version",
                "public_api_version",
                "capabilities",
                "configuration_contract",
                "probe_contract",
            ],
        )?;
        let version: u32 = read(&fields, "schema_version")?;
        let id = IntegrationTypeId::new(&read::<String>(&fields, "type_id")?)?;
        let category = read::<String>(&fields, "category")?.parse()?;
        for key in [
            "display_name",
            "description",
            "implementation_version",
            "public_api_version",
        ] {
            if !nonblank(&read::<String>(&fields, key)?) {
                return Err(Error::Type);
            }
        }
        for key in ["provider_id", "implementation_id"] {
            if !stable(&read::<String>(&fields, key)?) {
                return Err(Error::Type);
            }
        }
        let capabilities: Vec<String> = read(&fields, "capabilities")?;
        if version != 1
            || !sorted(&capabilities)
            || capabilities.iter().any(|value| !capability(value))
        {
            return Err(Error::Type);
        }
        let contract = object(fields.get("configuration_contract").ok_or(Error::Type)?)?;
        closed(&contract, &["schema_version", "fields", "fingerprint"])?;
        if read::<u32>(&contract, "schema_version")? != 1 {
            return Err(Error::Configuration);
        }
        let declared: Vec<&RawValue> = read(&contract, "fields")?;
        let definitions: Vec<_> = declared
            .iter()
            .map(|raw| {
                Field::restore(raw).map_err(|error| {
                    if error == Error::Unavailable {
                        error
                    } else {
                        Error::Configuration
                    }
                })
            })
            .collect::<Result<_, _>>()?;
        if !definitions.windows(2).all(|pair| pair[0].id < pair[1].id) {
            return Err(Error::Configuration);
        }
        let configuration_fingerprint = component(&contract, work)?;
        let probe_raw = *fields.get("probe_contract").ok_or(Error::Type)?;
        let probe = if probe_raw.get() == "null" {
            None
        } else {
            Some(Probe::restore(probe_raw, work).map_err(|error| {
                if error == Error::Unavailable {
                    error
                } else {
                    Error::Probe
                }
            })?)
        };
        Ok(Self {
            document,
            id,
            category,
            fields: definitions,
            probe,
            fingerprint,
            configuration_fingerprint,
        })
    }
    pub fn document(&self) -> &RawValue {
        &self.document
    }
    pub fn id(&self) -> &IntegrationTypeId {
        &self.id
    }
    pub fn category(&self) -> Category {
        self.category
    }
    pub fn fields(&self) -> &[Field] {
        &self.fields
    }
    pub fn probe(&self) -> Option<&Probe> {
        self.probe.as_ref()
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn configuration_fingerprint(&self) -> &str {
        &self.configuration_fingerprint
    }
}
fn capability(value: &str) -> bool {
    let mut parts = value.split(':');
    let base = parts.next().unwrap_or("");
    let mut bytes = base.bytes();
    if !bytes.next().is_some_and(|b| b.is_ascii_uppercase())
        || !bytes.all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'_')
    {
        return false;
    }
    match parts.next() {
        None => true,
        Some(suffix) => {
            !suffix.is_empty()
                && suffix.bytes().all(|b| {
                    b.is_ascii_uppercase() || b.is_ascii_digit() || matches!(b, b'_' | b'.' | b'-')
                })
                && parts.next().is_none()
        }
    }
}

pub mod authoring;

pub mod source;
