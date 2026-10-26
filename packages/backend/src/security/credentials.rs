//! Encrypted credential envelopes and exact keyed intent identity.
//! Keys and plaintext have no logging/serialization implementation. Persistence
//! and key-file lifecycle remain outside this cryptographic value boundary.
use crate::application::command::CommandId;
use crate::application::integration_configuration::IntegrationId;
use aes_gcm::{
    Aes256Gcm, KeyInit, Nonce,
    aead::{Aead, Payload},
};
use hkdf::Hkdf;
use hmac::{Hmac, Mac};
use onlyalpha_metadata_json as metadata;
use serde_json::json;
use sha2::Sha256;
use std::fmt;
use zeroize::Zeroizing;

pub const MASTER_KEY_VERSION: i32 = 1;
const COMMITMENT_INFO: &[u8] = b"ONLYALPHA_INTEGRATION_SECRET_COMMAND_COMMITMENT_V1";
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    MasterKeyInvalid,
    SlotInvalid,
    NotFound,
    GenerationConflict,
    GenerationMismatch,
    KeyVersionUnsupported,
    CiphertextInvalid,
    PersistenceConflict,
    Unavailable,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::MasterKeyInvalid => "CREDENTIAL_MASTER_KEY_INVALID",
            Self::SlotInvalid => "CREDENTIAL_SLOT_INVALID",
            Self::NotFound => "CREDENTIAL_NOT_FOUND",
            Self::GenerationConflict => "CREDENTIAL_GENERATION_CONFLICT",
            Self::GenerationMismatch => "CREDENTIAL_GENERATION_MISMATCH",
            Self::KeyVersionUnsupported => "CREDENTIAL_KEY_VERSION_UNSUPPORTED",
            Self::CiphertextInvalid => "CREDENTIAL_CIPHERTEXT_INVALID",
            Self::PersistenceConflict => "CREDENTIAL_PERSISTENCE_CONFLICT",
            Self::Unavailable => "CREDENTIAL_PERSISTENCE_UNAVAILABLE",
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
pub struct CredentialId(String);
impl CredentialId {
    pub fn new(value: &str) -> Result<Self, Error> {
        CommandId::new(value).map_err(|_| Error::SlotInvalid)?;
        Ok(Self(value.into()))
    }
    pub fn value(&self) -> &str {
        &self.0
    }
    pub(crate) fn generate() -> Result<Self, Error> {
        let mut bytes = [0u8; 16];
        getrandom::fill(&mut bytes).map_err(|_| Error::Unavailable)?;
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        let mut value = String::with_capacity(36);
        use std::fmt::Write;
        for (index, byte) in bytes.iter().enumerate() {
            if matches!(index, 4 | 6 | 8 | 10) {
                value.push('-');
            }
            write!(&mut value, "{byte:02x}").map_err(|_| Error::Unavailable)?;
        }
        Self::new(&value)
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Slot {
    kind: String,
    subject: String,
    name: String,
}
impl Slot {
    pub fn new(kind: &str, subject: &str, name: &str) -> Result<Self, Error> {
        if [kind, subject, name].iter().any(|value| {
            value.is_empty()
                || value
                    .chars()
                    .any(|c| c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}'))
        }) || !onlyalpha_integration_contract::valid_field_id(name)
        {
            return Err(Error::SlotInvalid);
        }
        Ok(Self {
            kind: kind.into(),
            subject: subject.into(),
            name: name.into(),
        })
    }
    pub fn kind(&self) -> &str {
        &self.kind
    }
    pub fn subject(&self) -> &str {
        &self.subject
    }
    pub fn name(&self) -> &str {
        &self.name
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Context {
    id: CredentialId,
    slot: Slot,
    generation: i32,
    key_version: i32,
}
impl Context {
    pub fn new(
        id: CredentialId,
        slot: Slot,
        generation: i32,
        key_version: i32,
    ) -> Result<Self, Error> {
        if generation < 1 {
            return Err(Error::GenerationConflict);
        }
        if key_version != MASTER_KEY_VERSION {
            return Err(Error::KeyVersionUnsupported);
        }
        Ok(Self {
            id,
            slot,
            generation,
            key_version,
        })
    }
    pub fn credential_id(&self) -> &CredentialId {
        &self.id
    }
    pub fn slot(&self) -> &Slot {
        &self.slot
    }
    pub fn generation(&self) -> i32 {
        self.generation
    }
    pub fn key_version(&self) -> i32 {
        self.key_version
    }
    pub fn aad(&self, work: usize) -> Result<Vec<u8>, Error> {
        let size = self
            .id
            .value()
            .len()
            .checked_add(self.slot.kind.len())
            .and_then(|n| n.checked_add(self.slot.subject.len()))
            .and_then(|n| n.checked_add(self.slot.name.len()))
            .ok_or(Error::Unavailable)?;
        if size > work {
            return Err(Error::Unavailable);
        }
        let input=json!({"credential_id":self.id.value(),"credential_kind":self.slot.kind,"subject_id":self.slot.subject,"secret_name":self.slot.name,"generation":self.generation,"key_version":self.key_version}).to_string();
        metadata::canonical_json(&input, work)
            .map(String::into_bytes)
            .map_err(|_| Error::Unavailable)
    }
}
/// Explicit plaintext access is for the admitted provider/algorithm boundary,
/// never Product metadata or a logging/serialization surface.
pub struct Secret(Zeroizing<String>);
impl Secret {
    pub fn new(value: &str) -> Result<Self, Error> {
        if value.is_empty() {
            return Err(Error::SlotInvalid);
        }
        Ok(Self(Zeroizing::new(value.into())))
    }
    pub fn expose(&self) -> &str {
        &self.0
    }
}
pub struct Key(Zeroizing<[u8; 32]>);
impl Key {
    pub fn new(value: &[u8]) -> Result<Self, Error> {
        let value: [u8; 32] = value.try_into().map_err(|_| Error::MasterKeyInvalid)?;
        Ok(Self(Zeroizing::new(value)))
    }
    pub fn encrypt(
        &self,
        context: &Context,
        secret: &Secret,
        work: usize,
    ) -> Result<Vec<u8>, Error> {
        bound(secret.expose().len(), work)?;
        let aad = context.aad(work)?;
        let mut nonce = [0u8; 12];
        getrandom::fill(&mut nonce).map_err(|_| Error::Unavailable)?;
        let cipher =
            Aes256Gcm::new_from_slice(self.0.as_ref()).map_err(|_| Error::MasterKeyInvalid)?;
        let encrypted = cipher
            .encrypt(
                &Nonce::from(nonce),
                Payload {
                    msg: secret.expose().as_bytes(),
                    aad: &aad,
                },
            )
            .map_err(|_| Error::Unavailable)?;
        let mut envelope = Vec::with_capacity(12 + encrypted.len());
        envelope.extend_from_slice(&nonce);
        envelope.extend_from_slice(&encrypted);
        Ok(envelope)
    }
    pub fn decrypt(
        &self,
        context: &Context,
        envelope: &[u8],
        work: usize,
    ) -> Result<Secret, Error> {
        bound(envelope.len(), work)?;
        if envelope.len() < 28 {
            return Err(Error::CiphertextInvalid);
        }
        let aad = context.aad(work)?;
        let nonce: [u8; 12] = envelope[..12]
            .try_into()
            .map_err(|_| Error::CiphertextInvalid)?;
        let cipher =
            Aes256Gcm::new_from_slice(self.0.as_ref()).map_err(|_| Error::MasterKeyInvalid)?;
        let plaintext = Zeroizing::new(
            cipher
                .decrypt(
                    &Nonce::from(nonce),
                    Payload {
                        msg: &envelope[12..],
                        aad: &aad,
                    },
                )
                .map_err(|_| Error::CiphertextInvalid)?,
        );
        let value = std::str::from_utf8(&plaintext).map_err(|_| Error::CiphertextInvalid)?;
        Secret::new(value).map_err(|_| Error::CiphertextInvalid)
    }
    pub fn secret_commitment(
        &self,
        integration: &IntegrationId,
        field: &str,
        secret: &Secret,
        work: usize,
    ) -> Result<String, Error> {
        if field.is_empty() {
            return Err(Error::SlotInvalid);
        }
        bound(secret.expose().len(), work)?;
        if field
            .len()
            .checked_add(integration.value().len())
            .ok_or(Error::Unavailable)?
            > work
        {
            return Err(Error::Unavailable);
        }
        let input = json!({"integration_id":integration.value(),"field_id":field}).to_string();
        let context = metadata::canonical_json(&input, work).map_err(|_| Error::Unavailable)?;
        let derived = Hkdf::<Sha256>::new(None, self.0.as_ref());
        let mut commitment_key = Zeroizing::new([0u8; 32]);
        derived
            .expand(COMMITMENT_INFO, commitment_key.as_mut())
            .map_err(|_| Error::Unavailable)?;
        let mut mac = <Hmac<Sha256> as KeyInit>::new_from_slice(commitment_key.as_ref())
            .map_err(|_| Error::Unavailable)?;
        mac.update(context.as_bytes());
        mac.update(&[0]);
        mac.update(secret.expose().as_bytes());
        let tag = mac.finalize().into_bytes();
        let mut output = String::with_capacity(64);
        use std::fmt::Write;
        for byte in tag {
            write!(&mut output, "{byte:02x}").map_err(|_| Error::Unavailable)?;
        }
        Ok(output)
    }
}
fn bound(size: usize, work: usize) -> Result<(), Error> {
    if size.checked_add(28).is_none_or(|size| size > work) {
        Err(Error::Unavailable)
    } else {
        Ok(())
    }
}
