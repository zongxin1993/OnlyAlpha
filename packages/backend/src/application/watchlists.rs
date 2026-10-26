//! Durable Owner presentation configuration, never Source permission or trading truth.
use crate::application::command::CommandId;
use crate::application::source_access::Reference;
use onlyalpha_domain::identifiers::OnlyInstrumentId;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::fmt;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Invalid,
    HistoryCorrupt,
    CommandConflict,
    CommandUnknown,
    VersionConflict,
    Unavailable,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "WATCHLIST_INVALID",
            Self::HistoryCorrupt => "WATCHLIST_HISTORY_CORRUPT",
            Self::CommandConflict => "WATCHLIST_COMMAND_CONFLICT",
            Self::CommandUnknown => "WATCHLIST_COMMAND_UNKNOWN",
            Self::VersionConflict => "WATCHLIST_VERSION_CONFLICT",
            Self::Unavailable => "WATCHLIST_UNAVAILABLE",
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Member {
    source: Reference,
    instrument_id: String,
}
impl Member {
    pub fn new(source: Reference, instrument_id: &str) -> Result<Self, Error> {
        if source.expected_type_id().is_none()
            || !instrument_id
                .parse::<OnlyInstrumentId>()
                .is_ok_and(|id| id.to_string() == instrument_id)
        {
            return Err(Error::Invalid);
        }
        Ok(Self {
            source,
            instrument_id: instrument_id.into(),
        })
    }
    pub fn source(&self) -> &Reference {
        &self.source
    }
    pub fn instrument_id(&self) -> &str {
        &self.instrument_id
    }
    fn to_record(&self) -> Value {
        json!({"source":reference_record(&self.source),"instrument_id":self.instrument_id})
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct List {
    list_id: String,
    name: String,
    members: Box<[Member]>,
}
impl List {
    pub fn new(list_id: &str, name: &str, members: Vec<Member>) -> Result<Self, Error> {
        // UUID4 syntax is shared with Commands; a List is never a Command identity/grant.
        if CommandId::new(list_id).is_err()
            || name.is_empty()
            || name.chars().take(65).count() > 64
            || name.starts_with(whitespace)
            || name.ends_with(whitespace)
            || name.chars().any(|c| c < ' ')
            || members.len() > 100
            || members
                .iter()
                .enumerate()
                .any(|(i, v)| members[..i].contains(v))
        {
            return Err(Error::Invalid);
        }
        Ok(Self {
            list_id: list_id.into(),
            name: name.into(),
            members: members.into_boxed_slice(),
        })
    }
    pub fn list_id(&self) -> &str {
        &self.list_id
    }
    pub fn name(&self) -> &str {
        &self.name
    }
    pub fn members(&self) -> &[Member] {
        &self.members
    }
    fn to_record(&self) -> Value {
        json!({"list_id":self.list_id,"name":self.name,"members":self.members.iter().map(Member::to_record).collect::<Vec<_>>()})
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Book {
    version: u64,
    lists: Box<[List]>,
}
impl Book {
    pub fn new(version: u64, lists: Vec<List>) -> Result<Self, Error> {
        if version > i64::MAX as u64
            || lists.len() > 20
            || lists.iter().map(|v| v.members.len()).sum::<usize>() > 200
            || lists.iter().enumerate().any(|(i, v)| {
                lists[..i]
                    .iter()
                    .any(|old| old.list_id == v.list_id || old.name == v.name)
            })
        {
            return Err(Error::Invalid);
        }
        Ok(Self {
            version,
            lists: lists.into_boxed_slice(),
        })
    }
    pub fn version(&self) -> u64 {
        self.version
    }
    pub fn lists(&self) -> &[List] {
        &self.lists
    }
    pub fn to_record(&self) -> Value {
        json!({"version":self.version,"lists":self.lists.iter().map(List::to_record).collect::<Vec<_>>()})
    }
    /// Strict representation decoder. The owning store must additionally prove the
    /// original payload hash and Command lineage before exposing projected history.
    pub fn from_record(record: &Value, representation: i16) -> Result<Self, Error> {
        if !matches!(representation, 1 | 2) {
            return Err(Error::Invalid);
        }
        let row = object(record, &["version", "lists"])?;
        let version = row["version"].as_u64().ok_or(Error::Invalid)?;
        let input = row["lists"]
            .as_array()
            .filter(|v| v.len() <= 20)
            .ok_or(Error::Invalid)?;
        let mut lists = Vec::with_capacity(input.len());
        for item in input {
            let keys = if representation == 1 {
                &["list_id", "name", "source", "instrument_ids"][..]
            } else {
                &["list_id", "name", "members"][..]
            };
            let item = object(item, keys)?;
            let members = if representation == 1 {
                let source = reference(&item["source"])?;
                item["instrument_ids"]
                    .as_array()
                    .filter(|v| v.len() <= 100)
                    .ok_or(Error::Invalid)?
                    .iter()
                    .map(|v| Member::new(source.clone(), v.as_str().ok_or(Error::Invalid)?))
                    .collect::<Result<Vec<_>, _>>()?
            } else {
                item["members"]
                    .as_array()
                    .filter(|v| v.len() <= 100)
                    .ok_or(Error::Invalid)?
                    .iter()
                    .map(|v| {
                        let row = object(v, &["source", "instrument_id"])?;
                        Member::new(
                            reference(&row["source"])?,
                            row["instrument_id"].as_str().ok_or(Error::Invalid)?,
                        )
                    })
                    .collect::<Result<Vec<_>, _>>()?
            };
            lists.push(List::new(
                item["list_id"].as_str().ok_or(Error::Invalid)?,
                item["name"].as_str().ok_or(Error::Invalid)?,
                members,
            )?);
        }
        Self::new(version, lists)
    }
    pub fn fingerprint(&self, namespace: &str) -> Result<String, Error> {
        Self::record_fingerprint(namespace, &self.to_record())
    }
    /// Hash only a strict original Watchlist record, with its original representation.
    pub fn record_fingerprint(namespace: &str, payload: &Value) -> Result<String, Error> {
        namespace_id(namespace)?;
        Ok(fingerprint(
            &json!({"namespace_id":namespace,"book":payload}),
        ))
    }
    pub fn intent_fingerprint(
        namespace: &str,
        expected_version: u64,
        lists: &Value,
    ) -> Result<String, Error> {
        namespace_id(namespace)?;
        if expected_version > i64::MAX as u64 {
            return Err(Error::Invalid);
        }
        Ok(fingerprint(
            &json!({"namespace_id":namespace,"expected_version":expected_version,"lists":lists}),
        ))
    }
    /// An outcome-less representation-1 admission can be compared only when its
    /// original Source can be reconstructed exactly; empty lists do not contain it.
    pub fn historical_intent(
        &self,
        namespace: &str,
        expected_version: u64,
    ) -> Result<Option<String>, Error> {
        let mut lists = Vec::with_capacity(self.lists.len());
        for list in self.lists.iter() {
            let Some(first) = list.members.first() else {
                return Ok(None);
            };
            if list.members.iter().any(|m| m.source != first.source) {
                return Ok(None);
            }
            lists.push(json!({"list_id":list.list_id,"name":list.name,"source":reference_record(&first.source),"instrument_ids":list.members.iter().map(|m|m.instrument_id.as_str()).collect::<Vec<_>>()}));
        }
        Self::intent_fingerprint(namespace, expected_version, &Value::Array(lists)).map(Some)
    }
}
pub(crate) fn namespace_id(value: &str) -> Result<(), Error> {
    CommandId::new(value)
        .map(|_| ())
        .map_err(|_| Error::Invalid)
}
fn whitespace(value: char) -> bool {
    value.is_whitespace() || matches!(value, '\u{1c}'..='\u{1f}')
}
fn object<'a>(value: &'a Value, keys: &[&str]) -> Result<&'a Map<String, Value>, Error> {
    let row = value.as_object().ok_or(Error::Invalid)?;
    if row.len() != keys.len() || keys.iter().any(|key| !row.contains_key(*key)) {
        return Err(Error::Invalid);
    }
    Ok(row)
}
fn reference(value: &Value) -> Result<Reference, Error> {
    let row = object(
        value,
        &[
            "integration_id",
            "integration_revision_fingerprint",
            "expected_type_id",
        ],
    )?;
    Reference::new(
        row["integration_id"].as_str().ok_or(Error::Invalid)?,
        row["integration_revision_fingerprint"]
            .as_str()
            .ok_or(Error::Invalid)?,
        Some(row["expected_type_id"].as_str().ok_or(Error::Invalid)?),
    )
    .map_err(|_| Error::Invalid)
}
fn reference_record(value: &Reference) -> Value {
    json!({"integration_id":value.integration_id(),"integration_revision_fingerprint":value.revision(),"expected_type_id":value.expected_type_id()})
}
fn fingerprint(value: &Value) -> String {
    // Watchlist records contain only validated strings/integers, arrays and objects.
    // serde_json's ordered maps and UTF-8 encoding preserve this family's canonical
    // Python preimages. There is no financial float/Decimal canonicalization here.
    Sha256::digest(value.to_string().as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
