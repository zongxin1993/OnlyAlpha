//! Typed existing Integration Product intents, independent of installed plugins.
use crate::{
    command::{Admission, CommandId, CommandKind},
    integration_configuration::{IntegrationId, Lifecycle},
};
use onlyalpha_integration_contract::IntegrationTypeId;
use onlyalpha_metadata_json as metadata;
use serde_json::{Value, json};
use std::fmt;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    InvalidConfiguration,
    SecretField,
    BaseRevision,
    DraftVersion,
    DraftNotFound,
    TypeChanged,
    TypeUnavailable,
    TypeContractInvalid,
    Archived,
    Resolver(crate::integration_resolver::Error),
    LifecycleConflict,
    NotFound,
    Unknown,
    Model(crate::integration_configuration::Error),
    Command(crate::command::Error),
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::BaseRevision => "INTEGRATION_BASE_REVISION_CONFLICT",
            Self::SecretField => "INTEGRATION_SECRET_FIELD_INVALID",
            Self::DraftNotFound => "INTEGRATION_DRAFT_NOT_FOUND",
            Self::TypeChanged => "INTEGRATION_TYPE_CHANGED",
            Self::TypeUnavailable => "INTEGRATION_TYPE_UNAVAILABLE",
            Self::TypeContractInvalid => "INTEGRATION_TYPE_CONTRACT_INVALID",
            Self::Archived => "INTEGRATION_ARCHIVED",
            Self::Resolver(error) => error.code(),
            Self::DraftVersion => "INTEGRATION_DRAFT_VERSION_CONFLICT",
            Self::InvalidConfiguration => "INTEGRATION_CONFIGURATION_INVALID",
            Self::LifecycleConflict => "INTEGRATION_LIFECYCLE_CONFLICT",
            Self::NotFound => "INTEGRATION_NOT_FOUND",
            Self::Unknown => "PRODUCT_COMMAND_OUTCOME_UNKNOWN",
            Self::Model(e) => e.code(),
            Self::Command(e) => e.code(),
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}
impl From<crate::integration_configuration::Error> for Error {
    fn from(e: crate::integration_configuration::Error) -> Self {
        Self::Model(e)
    }
}
impl From<crate::command::Error> for Error {
    fn from(e: crate::command::Error) -> Self {
        match e {
            crate::command::Error::Unavailable => {
                Self::Model(crate::integration_configuration::Error::Unavailable)
            }
            _ => Self::Command(e),
        }
    }
}
fn admission(
    id: &CommandId,
    kind: CommandKind,
    payload: Value,
    work: usize,
) -> Result<Admission, Error> {
    let fingerprint = metadata::fingerprint(&payload.to_string(), work).map_err(metadata_error)?;
    Ok(Admission::new(id.clone(), kind, &fingerprint)?)
}
pub struct CreateIntegration {
    pub(crate) command_id: CommandId,
    pub(crate) integration_id: IntegrationId,
    pub(crate) type_id: IntegrationTypeId,
    pub(crate) display_name: String,
}
impl CreateIntegration {
    pub fn new(
        command_id: CommandId,
        integration_id: IntegrationId,
        type_id: IntegrationTypeId,
        display_name: &str,
    ) -> Result<Self, Error> {
        if !display_name
            .chars()
            .any(|c| !(c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}')))
        {
            return Err(Error::InvalidConfiguration);
        }
        Ok(Self {
            command_id,
            integration_id,
            type_id,
            display_name: display_name.into(),
        })
    }
    pub fn admission(&self, work: usize) -> Result<Admission, Error> {
        admission(
            &self.command_id,
            CommandKind::CreateIntegration,
            json!({"integration_id":self.integration_id.value(),"type_id":self.type_id.value(),"display_name":self.display_name}),
            work,
        )
    }
    pub fn integration_id(&self) -> &IntegrationId {
        &self.integration_id
    }
}
pub struct SetLifecycle {
    pub(crate) command_id: CommandId,
    pub(crate) integration_id: IntegrationId,
    pub(crate) expected: Lifecycle,
    pub(crate) target: Lifecycle,
}
impl SetLifecycle {
    pub fn new(
        command_id: CommandId,
        integration_id: IntegrationId,
        expected: Lifecycle,
        target: Lifecycle,
    ) -> Self {
        Self {
            command_id,
            integration_id,
            expected,
            target,
        }
    }
    pub fn admission(&self, work: usize) -> Result<Admission, Error> {
        admission(
            &self.command_id,
            CommandKind::SetIntegrationLifecycle,
            json!({"integration_id":self.integration_id.value(),"expected_lifecycle_state":self.expected.as_str(),"lifecycle_state":self.target.as_str()}),
            work,
        )
    }
    pub fn integration_id(&self) -> &IntegrationId {
        &self.integration_id
    }
}
pub struct CommandResult {
    pub receipt: crate::command::Receipt,
    pub replayed: bool,
}

/// Original public input stays immutable; provider validation is owning admission.
pub struct UpdateDraft {
    pub(crate) command_id: CommandId,
    pub(crate) integration_id: IntegrationId,
    pub(crate) expected_version: i32,
    pub(crate) public: crate::integration_configuration::ObjectDocument,
    pub(crate) probe: Option<crate::integration_configuration::ObjectDocument>,
}
fn version(value: i32) -> Result<(), Error> {
    if value < 1 {
        Err(Error::DraftVersion)
    } else {
        Ok(())
    }
}
fn metadata_error(error: metadata::Error) -> Error {
    match error {
        metadata::Error::Unavailable => {
            Error::Model(crate::integration_configuration::Error::Unavailable)
        }
        _ => Error::InvalidConfiguration,
    }
}
fn command_document(
    document: Option<&crate::integration_configuration::ObjectDocument>,
    work: usize,
) -> Result<String, Error> {
    metadata::integral_float_json(document.map_or("null", |v| v.raw().get()), work)
        .map_err(metadata_error)
}
impl UpdateDraft {
    pub fn new(
        command_id: CommandId,
        integration_id: IntegrationId,
        expected_version: i32,
        public: crate::integration_configuration::ObjectDocument,
        probe: Option<crate::integration_configuration::ObjectDocument>,
    ) -> Result<Self, Error> {
        version(expected_version)?;
        Ok(Self {
            command_id,
            integration_id,
            expected_version,
            public,
            probe,
        })
    }
    pub fn admission(&self, work: usize) -> Result<Admission, Error> {
        admission(
            &self.command_id,
            CommandKind::UpdateIntegrationDraft,
            json!({"integration_id":self.integration_id.value(),"expected_draft_version":self.expected_version,"public_configuration_json":command_document(Some(&self.public),work)?,"probe_configuration_json":command_document(self.probe.as_ref(),work)?}),
            work,
        )
    }
    pub fn integration_id(&self) -> &IntegrationId {
        &self.integration_id
    }
}
pub struct ResetDraftContract {
    pub(crate) command_id: CommandId,
    pub(crate) integration_id: IntegrationId,
    pub(crate) expected_version: i32,
}
impl ResetDraftContract {
    pub fn new(
        command_id: CommandId,
        integration_id: IntegrationId,
        expected_version: i32,
    ) -> Result<Self, Error> {
        version(expected_version)?;
        Ok(Self {
            command_id,
            integration_id,
            expected_version,
        })
    }
    pub fn admission(&self, work: usize) -> Result<Admission, Error> {
        admission(
            &self.command_id,
            CommandKind::ResetIntegrationDraftContract,
            json!({"integration_id":self.integration_id.value(),"expected_draft_version":self.expected_version}),
            work,
        )
    }
    pub fn integration_id(&self) -> &IntegrationId {
        &self.integration_id
    }
}

impl From<crate::integration_resolver::Error> for Error {
    fn from(error: crate::integration_resolver::Error) -> Self {
        Self::Resolver(error)
    }
}

pub struct ClearSecret {
    pub(crate) command_id: CommandId,
    pub(crate) integration_id: IntegrationId,
    pub(crate) expected_version: i32,
    pub(crate) field_id: String,
}
impl ClearSecret {
    pub fn new(
        command_id: CommandId,
        integration_id: IntegrationId,
        expected_version: i32,
        field_id: &str,
    ) -> Result<Self, Error> {
        version(expected_version)?;
        if field_id.is_empty() {
            return Err(Error::SecretField);
        }
        Ok(Self {
            command_id,
            integration_id,
            expected_version,
            field_id: field_id.into(),
        })
    }
    pub fn admission(&self, work: usize) -> Result<Admission, Error> {
        admission(
            &self.command_id,
            CommandKind::ClearIntegrationSecret,
            json!({"integration_id":self.integration_id.value(),"expected_draft_version":self.expected_version,"field_id":self.field_id}),
            work,
        )
    }
    pub fn integration_id(&self) -> &IntegrationId {
        &self.integration_id
    }
}
pub struct PublishRevision {
    pub(crate) command_id: CommandId,
    pub(crate) integration_id: IntegrationId,
    pub(crate) expected_version: i32,
}
impl PublishRevision {
    pub fn new(
        command_id: CommandId,
        integration_id: IntegrationId,
        expected_version: i32,
    ) -> Result<Self, Error> {
        version(expected_version)?;
        Ok(Self {
            command_id,
            integration_id,
            expected_version,
        })
    }
    pub fn admission(&self, work: usize) -> Result<Admission, Error> {
        admission(
            &self.command_id,
            CommandKind::PublishIntegrationRevision,
            json!({"integration_id":self.integration_id.value(),"expected_draft_version":self.expected_version}),
            work,
        )
    }
    pub fn integration_id(&self) -> &IntegrationId {
        &self.integration_id
    }
}
/// Secret material is owned by a non-debuggable, zeroizing value. Only its
/// domain-separated keyed commitment participates in the original intent.
pub struct SetSecret {
    pub(crate) command_id: CommandId,
    pub(crate) integration_id: IntegrationId,
    pub(crate) expected_version: i32,
    pub(crate) field_id: String,
    pub(crate) plaintext: crate::credentials::Secret,
}
impl SetSecret {
    pub fn new(
        command_id: CommandId,
        integration_id: IntegrationId,
        expected_version: i32,
        field_id: &str,
        plaintext: &str,
    ) -> Result<Self, Error> {
        if expected_version < 1 || field_id.is_empty() {
            return Err(Error::InvalidConfiguration);
        }
        let plaintext =
            crate::credentials::Secret::new(plaintext).map_err(|_| Error::InvalidConfiguration)?;
        Ok(Self {
            command_id,
            integration_id,
            expected_version,
            field_id: field_id.into(),
            plaintext,
        })
    }
    pub fn integration_id(&self) -> &IntegrationId {
        &self.integration_id
    }
    pub fn admission(
        &self,
        key: &crate::credentials::Key,
        work: usize,
    ) -> Result<Admission, Error> {
        let commitment = key
            .secret_commitment(&self.integration_id, &self.field_id, &self.plaintext, work)
            .map_err(|error| {
                if error == crate::credentials::Error::Unavailable {
                    Error::Model(crate::integration_configuration::Error::Unavailable)
                } else {
                    Error::InvalidConfiguration
                }
            })?;
        admission(
            &self.command_id,
            CommandKind::SetIntegrationSecret,
            json!({"integration_id":self.integration_id.value(),"expected_draft_version":self.expected_version,"field_id":self.field_id,"secret_commitment":commitment}),
            work,
        )
    }
}

impl From<onlyalpha_integration_contract::Error> for Error {
    fn from(error: onlyalpha_integration_contract::Error) -> Self {
        use onlyalpha_integration_contract::Error as Contract;
        match error {
            Contract::Configuration => Self::InvalidConfiguration,
            Contract::Unavailable => {
                Self::Model(crate::integration_configuration::Error::Unavailable)
            }
            Contract::Type | Contract::Probe => Self::TypeContractInvalid,
        }
    }
}
