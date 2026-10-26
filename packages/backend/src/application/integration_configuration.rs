//! Immutable Integration metadata and exact identities, never runtime admission.
use crate::application::command::CommandId;
use crate::is_sha256_hex;
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_integration_contract::{Category, IntegrationTypeId, valid_field_id};
use onlyalpha_metadata_json as document_identity;
use serde::{Deserialize, Serialize};
use serde_json::{
    json,
    value::{RawValue, to_raw_value},
};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fmt,
    str::FromStr,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    InvalidId,
    InvalidBinding,
    InvalidDocument,
    PersistenceConflict,
    RevisionCorrupt,
    RuntimeBindingInvalid,
    Unavailable,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::InvalidId => "INTEGRATION_ID_INVALID",
            Self::InvalidBinding => "INTEGRATION_SECRET_BINDING_INVALID",
            Self::InvalidDocument => "INTEGRATION_CONFIGURATION_DOCUMENT_INVALID",
            Self::PersistenceConflict => "INTEGRATION_PERSISTENCE_CONFLICT",
            Self::RevisionCorrupt => "INTEGRATION_REVISION_CORRUPT",
            Self::RuntimeBindingInvalid => "INTEGRATION_RUNTIME_BINDING_INVALID",
            Self::Unavailable => "INTEGRATION_PERSISTENCE_UNAVAILABLE",
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct IntegrationId(String);
impl IntegrationId {
    pub fn new(value: &str) -> Result<Self, Error> {
        CommandId::new(value).map_err(|_| Error::InvalidId)?;
        Ok(Self(value.into()))
    }
    pub fn value(&self) -> &str {
        &self.0
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Lifecycle {
    Active,
    Disabled,
    Archived,
}
impl Lifecycle {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Active => "ACTIVE",
            Self::Disabled => "DISABLED",
            Self::Archived => "ARCHIVED",
        }
    }
}
impl FromStr for Lifecycle {
    type Err = Error;
    fn from_str(value: &str) -> Result<Self, Error> {
        match value {
            "ACTIVE" => Ok(Self::Active),
            "DISABLED" => Ok(Self::Disabled),
            "ARCHIVED" => Ok(Self::Archived),
            _ => Err(Error::PersistenceConflict),
        }
    }
}
#[derive(Clone, PartialEq, Eq)]
pub struct IntegrationRecord {
    pub integration_id: IntegrationId,
    pub type_id: IntegrationTypeId,
    pub display_name: String,
    pub lifecycle: Lifecycle,
    pub current_revision_fingerprint: Option<String>,
    pub created_at: OnlyUtcDateTime,
    pub updated_at: OnlyUtcDateTime,
}
pub struct Integration(IntegrationRecord);
impl Integration {
    pub fn restore(record: IntegrationRecord) -> Result<Self, Error> {
        if !record
            .display_name
            .chars()
            .any(|c| !(c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}')))
            || record.updated_at < record.created_at
            || record
                .current_revision_fingerprint
                .as_deref()
                .is_some_and(|fp| !is_sha256_hex(fp))
        {
            return Err(Error::PersistenceConflict);
        }
        Ok(Self(record))
    }
    pub fn record(&self) -> &IntegrationRecord {
        &self.0
    }
}

// No Debug/Display/DTO conversion: source text may be rejected for declared secrets.
#[derive(Clone)]
pub struct ObjectDocument {
    raw: Box<RawValue>,
    canonical: Box<RawValue>,
}
impl ObjectDocument {
    pub fn new(input: &str, max_work: usize) -> Result<Self, Error> {
        let canonical =
            document_identity::canonical_json(input, max_work).map_err(document_error)?;
        document_identity::object_fields(input).map_err(document_error)?;
        Ok(Self {
            raw: RawValue::from_string(input.into()).map_err(|_| Error::InvalidDocument)?,
            canonical: RawValue::from_string(canonical).map_err(|_| Error::InvalidDocument)?,
        })
    }
    pub fn raw(&self) -> &RawValue {
        &self.raw
    }
    pub fn fingerprint(&self) -> String {
        digest(self.canonical.get())
    }
}
fn document_error(error: document_identity::Error) -> Error {
    match error {
        document_identity::Error::Invalid => Error::InvalidDocument,
        document_identity::Error::Unavailable => Error::Unavailable,
    }
}
fn digest(value: &str) -> String {
    Sha256::digest(value.as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
fn raw<T: Serialize + ?Sized>(value: &T) -> Result<Box<RawValue>, Error> {
    to_raw_value(value).map_err(|_| Error::InvalidDocument)
}
fn fields_fingerprint<const N: usize>(fields: [(&str, Box<RawValue>); N]) -> Result<String, Error> {
    let fields: BTreeMap<_, _> = fields.into_iter().collect();
    Ok(digest(
        &serde_json::to_string(&fields).map_err(|_| Error::InvalidDocument)?,
    ))
}
fn read<'a, T: Deserialize<'a>>(
    fields: &BTreeMap<String, &'a RawValue>,
    key: &str,
) -> Result<T, Error> {
    serde_json::from_str(fields.get(key).ok_or(Error::InvalidDocument)?.get())
        .map_err(|_| Error::InvalidDocument)
}
#[derive(Clone, PartialEq, Eq)]
pub struct SecretBinding {
    field_id: String,
    credential_id: IntegrationId,
    credential_generation: i32,
}
impl SecretBinding {
    pub fn new(field: &str, credential: &str, generation: i32) -> Result<Self, Error> {
        if !valid_field_id(field) || generation < 1 {
            return Err(Error::InvalidBinding);
        }
        Ok(Self {
            field_id: field.into(),
            credential_id: IntegrationId::new(credential).map_err(|_| Error::InvalidBinding)?,
            credential_generation: generation,
        })
    }
    pub fn field_id(&self) -> &str {
        &self.field_id
    }
    pub fn credential_id(&self) -> &IntegrationId {
        &self.credential_id
    }
    pub fn generation(&self) -> i32 {
        self.credential_generation
    }
}
pub fn binding_fingerprint(bindings: &[SecretBinding]) -> Result<String, Error> {
    let mut sorted: BTreeMap<&str, &SecretBinding> = BTreeMap::new();
    for binding in bindings {
        if sorted.insert(&binding.field_id, binding).is_some() {
            return Err(Error::InvalidBinding);
        }
    }
    let records:Vec<_>=sorted.values().map(|binding|json!({"field_id":binding.field_id,"credential_id":binding.credential_id.value(),"credential_generation":binding.credential_generation})).collect();
    Ok(digest(
        &serde_json::to_string(&records).map_err(|_| Error::InvalidBinding)?,
    ))
}
fn reject_secrets(
    descriptor: &ObjectDocument,
    public: &ObjectDocument,
    probe: Option<&ObjectDocument>,
) -> Result<IntegrationTypeId, Error> {
    let fields = document_identity::object_fields(descriptor.raw.get()).map_err(document_error)?;
    let version: u32 = read(&fields, "schema_version")?;
    if version != 1 {
        return Err(Error::InvalidDocument);
    }
    let id: String = read(&fields, "type_id")?;
    let id = IntegrationTypeId::new(&id).map_err(|_| Error::InvalidDocument)?;
    let contract = document_identity::object_fields(
        fields
            .get("configuration_contract")
            .ok_or(Error::InvalidDocument)?
            .get(),
    )
    .map_err(document_error)?;
    let declarations: Vec<&RawValue> = read(&contract, "fields")?;
    let public = document_identity::object_fields(public.raw.get()).map_err(document_error)?;
    let probe = probe
        .map(|doc| document_identity::object_fields(doc.raw.get()).map_err(document_error))
        .transpose()?;
    let mut seen = BTreeSet::new();
    for declaration in declarations {
        let fields = document_identity::object_fields(declaration.get()).map_err(document_error)?;
        let field: String = read(&fields, "field_id")?;
        let secret: bool = read(&fields, "secret")?;
        if !valid_field_id(&field) || !seen.insert(field.clone()) {
            return Err(Error::InvalidDocument);
        }
        if secret
            && (public.contains_key(&field)
                || probe
                    .as_ref()
                    .is_some_and(|probe| probe.contains_key(&field)))
        {
            return Err(Error::InvalidDocument);
        }
    }
    Ok(id)
}

#[derive(Clone)]
pub struct DraftRecord {
    pub integration_id: IntegrationId,
    pub base_revision_fingerprint: Option<String>,
    pub type_descriptor_fingerprint: String,
    pub type_descriptor_document: ObjectDocument,
    pub public_configuration_document: ObjectDocument,
    pub probe_configuration_document: Option<ObjectDocument>,
    pub draft_version: i32,
    pub draft_fingerprint: String,
    pub created_at: OnlyUtcDateTime,
    pub updated_at: OnlyUtcDateTime,
}
pub struct Draft(DraftRecord);
impl Draft {
    pub fn restore(record: DraftRecord, bindings: &[SecretBinding]) -> Result<Self, Error> {
        if record.draft_version < 1
            || record.updated_at < record.created_at
            || !is_sha256_hex(&record.draft_fingerprint)
            || !is_sha256_hex(&record.type_descriptor_fingerprint)
            || record
                .base_revision_fingerprint
                .as_deref()
                .is_some_and(|fp| !is_sha256_hex(fp))
            || record.type_descriptor_fingerprint != record.type_descriptor_document.fingerprint()
        {
            return Err(Error::PersistenceConflict);
        }
        reject_secrets(
            &record.type_descriptor_document,
            &record.public_configuration_document,
            record.probe_configuration_document.as_ref(),
        )?;
        if Self::derive_fingerprint(&record, bindings)? != record.draft_fingerprint {
            return Err(Error::PersistenceConflict);
        }
        Ok(Self(record))
    }
    pub fn derive_fingerprint(
        record: &DraftRecord,
        bindings: &[SecretBinding],
    ) -> Result<String, Error> {
        fields_fingerprint([
            ("integration_id", raw(record.integration_id.value())?),
            (
                "base_revision_fingerprint",
                raw(&record.base_revision_fingerprint)?,
            ),
            (
                "type_descriptor_fingerprint",
                raw(&record.type_descriptor_fingerprint)?,
            ),
            (
                "type_descriptor_document",
                record.type_descriptor_document.canonical.clone(),
            ),
            (
                "public_configuration_document",
                record.public_configuration_document.canonical.clone(),
            ),
            (
                "probe_configuration_document",
                match &record.probe_configuration_document {
                    Some(doc) => doc.canonical.clone(),
                    None => raw(&Option::<String>::None)?,
                },
            ),
            (
                "secret_binding_fingerprint",
                raw(&binding_fingerprint(bindings)?)?,
            ),
        ])
    }
    pub fn record(&self) -> &DraftRecord {
        &self.0
    }
}
#[derive(Clone)]
pub struct RevisionRecord {
    pub revision_fingerprint: String,
    pub integration_id: IntegrationId,
    pub revision_sequence: i32,
    pub type_id: IntegrationTypeId,
    pub type_descriptor_fingerprint: String,
    pub type_descriptor_document: ObjectDocument,
    pub configuration_fingerprint: String,
    pub configuration_document: ObjectDocument,
    pub runtime_configuration_fingerprint: String,
    pub probe_configuration_fingerprint: Option<String>,
    pub probe_configuration_document: Option<ObjectDocument>,
    pub secret_binding_fingerprint: String,
    pub created_at: OnlyUtcDateTime,
}
pub struct Revision(RevisionRecord);
impl Revision {
    pub fn restore(record: RevisionRecord, bindings: &[SecretBinding]) -> Result<Self, Error> {
        if record.revision_sequence < 1
            || [
                &record.revision_fingerprint,
                &record.type_descriptor_fingerprint,
                &record.configuration_fingerprint,
                &record.runtime_configuration_fingerprint,
                &record.secret_binding_fingerprint,
            ]
            .iter()
            .any(|fp| !is_sha256_hex(fp))
            || record
                .probe_configuration_fingerprint
                .as_deref()
                .is_some_and(|fp| !is_sha256_hex(fp))
        {
            return Err(Error::RevisionCorrupt);
        }
        let type_id = reject_secrets(
            &record.type_descriptor_document,
            &record.configuration_document,
            record.probe_configuration_document.as_ref(),
        )?;
        if type_id != record.type_id
            || record.type_descriptor_fingerprint != record.type_descriptor_document.fingerprint()
            || record.configuration_fingerprint != record.configuration_document.fingerprint()
            || record.probe_configuration_fingerprint
                != record
                    .probe_configuration_document
                    .as_ref()
                    .map(ObjectDocument::fingerprint)
            || record.secret_binding_fingerprint != binding_fingerprint(bindings)?
            || record.revision_fingerprint != Self::derive_fingerprint(&record)?
        {
            return Err(Error::RevisionCorrupt);
        }
        Ok(Self(record))
    }
    pub fn derive_fingerprint(record: &RevisionRecord) -> Result<String, Error> {
        RevisionIdentity {
            integration_id: &record.integration_id,
            type_id: &record.type_id,
            type_descriptor_fingerprint: &record.type_descriptor_fingerprint,
            type_descriptor_document: &record.type_descriptor_document,
            configuration_fingerprint: &record.configuration_fingerprint,
            configuration_document: &record.configuration_document,
            runtime_configuration_fingerprint: &record.runtime_configuration_fingerprint,
            probe_configuration_fingerprint: record.probe_configuration_fingerprint.as_deref(),
            probe_configuration_document: record.probe_configuration_document.as_ref(),
            secret_binding_fingerprint: &record.secret_binding_fingerprint,
        }
        .fingerprint()
    }
    pub(crate) fn resolved_fingerprint(
        id: &IntegrationId,
        type_id: &IntegrationTypeId,
        descriptor: &ObjectDocument,
        public: &ObjectDocument,
        probe: Option<&ObjectDocument>,
        bindings: &[SecretBinding],
    ) -> Result<String, Error> {
        let descriptor_fingerprint = descriptor.fingerprint();
        let configuration_fingerprint = public.fingerprint();
        let runtime_fingerprint =
            runtime_configuration_fingerprint(type_id, descriptor, public, bindings)?;
        let probe_fingerprint = probe.map(ObjectDocument::fingerprint);
        let binding_fingerprint = binding_fingerprint(bindings)?;
        RevisionIdentity {
            integration_id: id,
            type_id,
            type_descriptor_fingerprint: &descriptor_fingerprint,
            type_descriptor_document: descriptor,
            configuration_fingerprint: &configuration_fingerprint,
            configuration_document: public,
            runtime_configuration_fingerprint: &runtime_fingerprint,
            probe_configuration_fingerprint: probe_fingerprint.as_deref(),
            probe_configuration_document: probe,
            secret_binding_fingerprint: &binding_fingerprint,
        }
        .fingerprint()
    }
    pub fn record(&self) -> &RevisionRecord {
        &self.0
    }
}
// A borrowed projection of the one Revision identity, never stored or serialized.
struct RevisionIdentity<'a> {
    integration_id: &'a IntegrationId,
    type_id: &'a IntegrationTypeId,
    type_descriptor_fingerprint: &'a str,
    type_descriptor_document: &'a ObjectDocument,
    configuration_fingerprint: &'a str,
    configuration_document: &'a ObjectDocument,
    runtime_configuration_fingerprint: &'a str,
    probe_configuration_fingerprint: Option<&'a str>,
    probe_configuration_document: Option<&'a ObjectDocument>,
    secret_binding_fingerprint: &'a str,
}
impl RevisionIdentity<'_> {
    fn fingerprint(self) -> Result<String, Error> {
        fields_fingerprint([
            ("integration_id", raw(self.integration_id.value())?),
            ("type_id", raw(self.type_id.value())?),
            (
                "type_descriptor_fingerprint",
                raw(&self.type_descriptor_fingerprint)?,
            ),
            (
                "type_descriptor_document",
                self.type_descriptor_document.canonical.clone(),
            ),
            (
                "configuration_fingerprint",
                raw(&self.configuration_fingerprint)?,
            ),
            (
                "configuration_document",
                self.configuration_document.canonical.clone(),
            ),
            (
                "runtime_configuration_fingerprint",
                raw(&self.runtime_configuration_fingerprint)?,
            ),
            (
                "probe_configuration_fingerprint",
                raw(&self.probe_configuration_fingerprint)?,
            ),
            (
                "probe_configuration_document",
                match &self.probe_configuration_document {
                    Some(doc) => doc.canonical.clone(),
                    None => raw(&Option::<String>::None)?,
                },
            ),
            (
                "secret_binding_fingerprint",
                raw(&self.secret_binding_fingerprint)?,
            ),
        ])
    }
}

pub fn runtime_configuration_fingerprint(
    type_id: &IntegrationTypeId,
    descriptor: &ObjectDocument,
    public: &ObjectDocument,
    bindings: &[SecretBinding],
) -> Result<String, Error> {
    fields_fingerprint([
        (
            "domain",
            raw("ONLYALPHA_INTEGRATION_RUNTIME_CONFIGURATION_V1")?,
        ),
        ("type_id", raw(type_id.value())?),
        (
            "type_descriptor_fingerprint",
            raw(&descriptor.fingerprint())?,
        ),
        ("public_configuration", public.canonical.clone()),
        (
            "secret_binding_fingerprint",
            raw(&binding_fingerprint(bindings)?)?,
        ),
    ])
}
#[derive(Clone)]
pub struct RuntimeBindingRecord {
    pub integration_id: IntegrationId,
    pub revision_fingerprint: String,
    pub type_id: IntegrationTypeId,
    pub category: Category,
    pub type_descriptor_fingerprint: String,
    pub runtime_configuration_fingerprint: String,
    pub runtime_generation_fingerprint: Option<String>,
}
pub struct RuntimeBinding {
    record: RuntimeBindingRecord,
    fingerprint: String,
}
impl RuntimeBinding {
    pub fn new(record: RuntimeBindingRecord) -> Result<Self, Error> {
        if [
            &record.revision_fingerprint,
            &record.type_descriptor_fingerprint,
            &record.runtime_configuration_fingerprint,
        ]
        .iter()
        .any(|fp| !is_sha256_hex(fp))
            || record
                .runtime_generation_fingerprint
                .as_deref()
                .is_some_and(|fp| !is_sha256_hex(fp))
        {
            return Err(Error::RuntimeBindingInvalid);
        }
        let fingerprint = fields_fingerprint([
            ("schema_version", raw(&1_u32)?),
            (
                "identity_domain",
                raw("ONLYALPHA_INTEGRATION_RUNTIME_BINDING_V1")?,
            ),
            ("integration_id", raw(record.integration_id.value())?),
            ("revision_fingerprint", raw(&record.revision_fingerprint)?),
            ("type_id", raw(record.type_id.value())?),
            ("category", raw(record.category.as_str())?),
            (
                "type_descriptor_fingerprint",
                raw(&record.type_descriptor_fingerprint)?,
            ),
            (
                "runtime_configuration_fingerprint",
                raw(&record.runtime_configuration_fingerprint)?,
            ),
            (
                "runtime_generation_fingerprint",
                raw(&record.runtime_generation_fingerprint)?,
            ),
        ])?;
        Ok(Self {
            record,
            fingerprint,
        })
    }
    pub fn from_revision(
        revision: &Revision,
        category: Category,
        generation: Option<&str>,
    ) -> Result<Self, Error> {
        let record = revision.record();
        Self::new(RuntimeBindingRecord {
            integration_id: record.integration_id.clone(),
            revision_fingerprint: record.revision_fingerprint.clone(),
            type_id: record.type_id.clone(),
            category,
            type_descriptor_fingerprint: record.type_descriptor_fingerprint.clone(),
            runtime_configuration_fingerprint: record.runtime_configuration_fingerprint.clone(),
            runtime_generation_fingerprint: generation.map(str::to_owned),
        })
    }
    pub fn record(&self) -> &RuntimeBindingRecord {
        &self.record
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
}
