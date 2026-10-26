//! Provider-neutral Draft/publication metadata; no credential or runtime admission.
use crate::application::integration_configuration::{
    self as model, IntegrationId, ObjectDocument, Revision, RevisionRecord, SecretBinding,
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_integration_contract::{Descriptor, Field, IntegrationTypeId, ValueKind};
use onlyalpha_metadata_json as metadata;
use serde_json::value::{RawValue, to_raw_value};
use std::{
    collections::{BTreeMap, BTreeSet},
    fmt,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Invalid,
    Incomplete,
    ProbeInvalid,
    BindingInvalid,
    SecretRequired,
    Unavailable,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "INTEGRATION_CONFIGURATION_INVALID",
            Self::Incomplete => "INTEGRATION_CONFIGURATION_INCOMPLETE",
            Self::ProbeInvalid => "INTEGRATION_PROBE_CONFIGURATION_INVALID",
            Self::BindingInvalid => "INTEGRATION_SECRET_BINDING_INVALID",
            Self::SecretRequired => "INTEGRATION_SECRET_REQUIRED",
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
fn metadata_error(error: metadata::Error) -> Error {
    match error {
        metadata::Error::Invalid => Error::Invalid,
        metadata::Error::Unavailable => Error::Unavailable,
    }
}
fn model_error(error: model::Error) -> Error {
    if error == model::Error::Unavailable {
        Error::Unavailable
    } else {
        Error::Invalid
    }
}
fn field<'a>(descriptor: &'a Descriptor, id: &str) -> Option<&'a Field> {
    descriptor
        .fields()
        .binary_search_by(|field| field.id().cmp(id))
        .ok()
        .map(|index| &descriptor.fields()[index])
}
fn value(field: &Field, input: &RawValue, work: usize) -> Result<Box<RawValue>, Error> {
    if !field.accepts(input) {
        return Err(Error::Invalid);
    }
    if matches!(field.kind(), ValueKind::Number | ValueKind::Duration)
        && input.get().contains(['.', 'e', 'E'])
    {
        let number: f64 = input.get().parse().map_err(|_| Error::Invalid)?;
        if number.fract() == 0.0 {
            // Precision zero formats the actual integral binary64 value, not its
            // shortest round-trip representative. Python int(-0.0) is zero.
            let text = if number == 0.0 {
                "0".into()
            } else {
                format!("{number:.0}")
            };
            return RawValue::from_string(text).map_err(|_| Error::Invalid);
        }
        return Ok(input.to_owned());
    }
    // These kinds contain no floating numbers, so metadata canonicalization is
    // also their ordinary JSON normalization (including integral negative zero).
    let text = metadata::canonical_json(input.get(), work).map_err(metadata_error)?;
    RawValue::from_string(text).map_err(|_| Error::Invalid)
}
fn public_values(
    descriptor: &Descriptor,
    public: &ObjectDocument,
    work: usize,
) -> Result<BTreeMap<String, Box<RawValue>>, Error> {
    let input = metadata::object_fields(public.raw().get()).map_err(metadata_error)?;
    let mut values = BTreeMap::new();
    for (key, input) in input {
        let field = field(descriptor, &key).ok_or(Error::Invalid)?;
        if field.secret() {
            return Err(Error::Invalid);
        }
        values.insert(key, value(field, input, work)?);
    }
    Ok(values)
}
fn document(fields: BTreeMap<String, Box<RawValue>>, work: usize) -> Result<ObjectDocument, Error> {
    // Check the exact output size before allocating the combined buffer. A
    // compact exponent can expand into a 309-digit normalized integer.
    let mut size = 2usize;
    for (index, (key, value)) in fields.iter().enumerate() {
        let key = serde_json::to_string(key).map_err(|_| Error::Invalid)?;
        size = size
            .checked_add(key.len())
            .and_then(|n| n.checked_add(1))
            .and_then(|n| n.checked_add(value.get().len()))
            .and_then(|n| n.checked_add(usize::from(index != 0)))
            .ok_or(Error::Unavailable)?;
        if size > work {
            return Err(Error::Unavailable);
        }
    }
    if size > work {
        return Err(Error::Unavailable);
    }
    let text = serde_json::to_string(&fields).map_err(|_| Error::Invalid)?;
    ObjectDocument::new(&text, work).map_err(model_error)
}
fn probe_values(
    descriptor: &Descriptor,
    probe: Option<&ObjectDocument>,
    publish: bool,
) -> Result<Option<BTreeMap<String, Box<RawValue>>>, Error> {
    let input = probe
        .map(|probe| metadata::object_fields(probe.raw().get()).map_err(metadata_error))
        .transpose()?
        .unwrap_or_default();
    let Some(contract) = descriptor.probe() else {
        return if input.is_empty() {
            Ok(None)
        } else {
            Err(Error::ProbeInvalid)
        };
    };
    if input.keys().any(|key| key != "instrument") {
        return Err(Error::ProbeInvalid);
    }
    let instrument = input
        .get("instrument")
        .filter(|value| value.get() != "null")
        .map(|value| serde_json::from_str::<String>(value.get()).map_err(|_| Error::ProbeInvalid))
        .transpose()?;
    let instrument = match instrument {
        Some(value) => value,
        None if publish => contract.default_instrument().into(),
        None => return Ok(probe.map(|_| BTreeMap::new())),
    };
    if !instrument
        .chars()
        .any(|c| !(c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}')))
        || (!contract.user_selectable() && instrument != contract.default_instrument())
    {
        return Err(Error::ProbeInvalid);
    }
    Ok(Some(BTreeMap::from([(
        "instrument".into(),
        to_raw_value(&instrument).map_err(|_| Error::ProbeInvalid)?,
    )])))
}
pub fn validate_draft(
    descriptor: &Descriptor,
    public: &ObjectDocument,
    probe: Option<&ObjectDocument>,
    work: usize,
) -> Result<(ObjectDocument, Option<ObjectDocument>), Error> {
    let public = public_values(descriptor, public, work)?;
    let probe = probe_values(descriptor, probe, false)?;
    Ok((
        document(public, work)?,
        probe.map(|probe| document(probe, work)).transpose()?,
    ))
}
/// Resolved metadata can become an immutable Revision only with explicit owner
/// sequence/time. It neither verifies current credentials nor grants READY.
pub struct Publication {
    id: IntegrationId,
    type_id: IntegrationTypeId,
    descriptor: ObjectDocument,
    public: ObjectDocument,
    probe: Option<ObjectDocument>,
    bindings: Vec<SecretBinding>,
}
impl Publication {
    pub(crate) fn public_configuration(&self) -> &ObjectDocument {
        &self.public
    }
    pub fn bindings(&self) -> &[SecretBinding] {
        &self.bindings
    }
    /// Semantic identity has no sequence or observation time.
    pub fn revision_fingerprint(&self) -> Result<String, model::Error> {
        Revision::resolved_fingerprint(
            &self.id,
            &self.type_id,
            &self.descriptor,
            &self.public,
            self.probe.as_ref(),
            &self.bindings,
        )
    }
    pub fn into_revision(
        self,
        sequence: i32,
        created_at: OnlyUtcDateTime,
    ) -> Result<Revision, model::Error> {
        let revision_fingerprint = self.revision_fingerprint()?;
        let runtime_fingerprint = model::runtime_configuration_fingerprint(
            &self.type_id,
            &self.descriptor,
            &self.public,
            &self.bindings,
        )?;
        let record = RevisionRecord {
            revision_fingerprint,
            integration_id: self.id,
            revision_sequence: sequence,
            type_id: self.type_id,
            type_descriptor_fingerprint: self.descriptor.fingerprint(),
            type_descriptor_document: self.descriptor,
            configuration_fingerprint: self.public.fingerprint(),
            configuration_document: self.public,
            runtime_configuration_fingerprint: runtime_fingerprint,
            probe_configuration_fingerprint: self.probe.as_ref().map(ObjectDocument::fingerprint),
            probe_configuration_document: self.probe,
            secret_binding_fingerprint: model::binding_fingerprint(&self.bindings)?,
            created_at,
        };
        Revision::restore(record, &self.bindings)
    }
}
pub fn resolve_publication(
    id: IntegrationId,
    descriptor: &Descriptor,
    public: &ObjectDocument,
    probe: Option<&ObjectDocument>,
    bindings: &[SecretBinding],
    work: usize,
) -> Result<Publication, Error> {
    let mut public = public_values(descriptor, public, work)?;
    // Match Draft validation before checking publication completeness.
    probe_values(descriptor, probe, false)?;
    for field in descriptor.fields() {
        if !field.secret() && !public.contains_key(field.id()) {
            if let Some(default) = field.default() {
                public.insert(field.id().into(), value(field, default, work)?);
            } else if field.required() {
                return Err(Error::Incomplete);
            }
        }
    }
    let mut seen = BTreeSet::new();
    for binding in bindings {
        if !seen.insert(binding.field_id())
            || !field(descriptor, binding.field_id()).is_some_and(Field::secret)
        {
            return Err(Error::BindingInvalid);
        }
    }
    if descriptor
        .fields()
        .iter()
        .any(|field| field.secret() && field.required() && !seen.contains(field.id()))
    {
        return Err(Error::SecretRequired);
    }
    let probe = probe_values(descriptor, probe, true)?
        .map(|probe| document(probe, work))
        .transpose()?;
    let mut bindings = bindings.to_vec();
    bindings.sort_by(|a, b| a.field_id().cmp(b.field_id()));
    Ok(Publication {
        id,
        type_id: descriptor.id().clone(),
        descriptor: ObjectDocument::new(descriptor.document().get(), work).map_err(model_error)?,
        public: document(public, work)?,
        probe,
        bindings,
    })
}

/// A new publication may reuse immutable bytes only after their actual typed
/// projections satisfy their own stored declaration. Metadata hashes alone can
/// alias nonintegral numbers and strings. Historical runtime identity is opaque.
pub(crate) fn validate_reused_revision(
    revision: &Revision,
    bindings: &[SecretBinding],
    work: usize,
) -> Result<(), model::Error> {
    let record = revision.record();
    let descriptor = Descriptor::from_json(record.type_descriptor_document.raw().get(), work)
        .map_err(|error| match error {
            onlyalpha_integration_contract::Error::Unavailable => model::Error::Unavailable,
            _ => model::Error::RevisionCorrupt,
        })?;
    let resolved = resolve_publication(
        record.integration_id.clone(),
        &descriptor,
        &record.configuration_document,
        record.probe_configuration_document.as_ref(),
        bindings,
        work,
    )
    .map_err(|error| match error {
        Error::Unavailable => model::Error::Unavailable,
        _ => model::Error::RevisionCorrupt,
    })?;
    if resolved.type_id != record.type_id
        || resolved.descriptor.fingerprint() != record.type_descriptor_fingerprint
        || resolved.public.fingerprint() != record.configuration_fingerprint
        || resolved.probe.as_ref().map(ObjectDocument::fingerprint)
            != record.probe_configuration_fingerprint
        || model::binding_fingerprint(&resolved.bindings)? != record.secret_binding_fingerprint
    {
        return Err(model::Error::RevisionCorrupt);
    }
    Ok(())
}
