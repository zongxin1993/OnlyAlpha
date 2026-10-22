//! Local human read credentials and exact Source grants, never Command authority.
use crate::is_sha256_hex;
use sha2::{Digest, Sha256};
use std::{
    fmt,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};
use subtle::ConstantTimeEq;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    InvalidConfiguration,
    InvalidReference,
    Unauthorized,
    Forbidden,
    ProofUnavailable,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::InvalidConfiguration => "LOCAL_READ_CONFIG_INVALID",
            Self::InvalidReference => "MARKET_DATA_SOURCE_REFERENCE_INVALID",
            Self::Unauthorized => "LOCAL_READ_UNAUTHORIZED",
            Self::Forbidden => "LOCAL_READ_FORBIDDEN",
            Self::ProofUnavailable => "LOCAL_READ_PROOF_UNAVAILABLE",
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}

// Match Python str.strip, including its four extra ASCII information separators.
fn whitespace(value: char) -> bool {
    value.is_whitespace() || matches!(value, '\u{1c}'..='\u{1f}')
}
fn configured_text(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.chars().take(maximum + 1).count() <= maximum
        && !value.contains('*')
        && !value.starts_with(whitespace)
        && !value.ends_with(whitespace)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Reference {
    integration_id: String,
    revision: String,
    expected_type_id: Option<String>,
}
impl Reference {
    pub fn new(
        integration_id: &str,
        revision: &str,
        expected_type_id: Option<&str>,
    ) -> Result<Self, Error> {
        if !integration_id.chars().any(|c| !whitespace(c))
            || !is_sha256_hex(revision)
            || expected_type_id.is_some_and(|value| !value.chars().any(|c| !whitespace(c)))
        {
            return Err(Error::InvalidReference);
        }
        Ok(Self {
            integration_id: integration_id.into(),
            revision: revision.into(),
            expected_type_id: expected_type_id.map(String::from),
        })
    }
    pub fn integration_id(&self) -> &str {
        &self.integration_id
    }
    pub fn revision(&self) -> &str {
        &self.revision
    }
    pub fn expected_type_id(&self) -> Option<&str> {
        self.expected_type_id.as_deref()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Selection {
    reference: Reference,
    source_id: String,
    environment: String,
}
impl Selection {
    pub fn new(reference: Reference, source_id: &str, environment: &str) -> Result<Self, Error> {
        if reference.expected_type_id.is_none() || source_id.is_empty() || environment.is_empty() {
            return Err(Error::ProofUnavailable);
        }
        Ok(Self {
            reference,
            source_id: source_id.into(),
            environment: environment.into(),
        })
    }
    pub fn reference(&self) -> &Reference {
        &self.reference
    }
    pub fn source_id(&self) -> &str {
        &self.source_id
    }
    pub fn environment(&self) -> &str {
        &self.environment
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Permission {
    ClosedHistory,
    RealtimePreview,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Grant {
    selection: Selection,
    permissions: Box<[Permission]>,
}
impl Grant {
    pub fn new(selection: Selection, permissions: Vec<Permission>) -> Result<Self, Error> {
        let reference = &selection.reference;
        if !configured_text(&reference.integration_id, 256)
            || !reference
                .expected_type_id
                .as_deref()
                .is_some_and(|value| configured_text(value, 256))
            || !configured_text(&selection.source_id, 256)
            || !configured_text(&selection.environment, 256)
            || permissions.is_empty()
            || permissions
                .iter()
                .enumerate()
                .any(|(index, value)| permissions[..index].contains(value))
        {
            return Err(Error::InvalidConfiguration);
        }
        Ok(Self {
            selection,
            permissions: permissions.into_boxed_slice(),
        })
    }
    pub fn selection(&self) -> &Selection {
        &self.selection
    }
    pub fn permissions(&self) -> &[Permission] {
        &self.permissions
    }
}

// No Debug/serialization: credentials and issuance state never become DTOs or logs.
struct State {
    subject_id: String,
    bearer_sha256: String,
    grants: Box<[Grant]>,
    active: AtomicBool,
    revoked: tokio::sync::Notify,
}
#[derive(Clone)]
pub struct Authority {
    state: Arc<State>,
}
#[derive(Clone)]
pub struct Session {
    state: Arc<State>,
}
impl Authority {
    pub fn new(subject_id: &str, bearer_sha256: &str, grants: Vec<Grant>) -> Result<Self, Error> {
        // Subject allows '*' in the existing contract; unlike Source identifiers it
        // is a bounded explicit name, not a selection pattern.
        if subject_id.is_empty()
            || subject_id.chars().take(129).count() > 128
            || subject_id.starts_with(whitespace)
            || subject_id.ends_with(whitespace)
            || !is_sha256_hex(bearer_sha256)
            || grants.len() > 32
            || grants.iter().enumerate().any(|(index, grant)| {
                grants[..index]
                    .iter()
                    .any(|other| other.selection.reference == grant.selection.reference)
            })
        {
            return Err(Error::InvalidConfiguration);
        }
        Ok(Self {
            state: Arc::new(State {
                subject_id: subject_id.into(),
                bearer_sha256: bearer_sha256.into(),
                grants: grants.into_boxed_slice(),
                active: AtomicBool::new(true),
                revoked: tokio::sync::Notify::new(),
            }),
        })
    }
    pub fn grants(&self) -> &[Grant] {
        &self.state.grants
    }
    pub fn authenticate(&self, authorization: &str) -> Result<Session, Error> {
        let credential = authorization
            .strip_prefix("Bearer ")
            .filter(|value| is_sha256_hex(value))
            .ok_or(Error::Unauthorized)?;
        // Hash the 64 ASCII credential characters, never hex-decoded token bytes.
        // Both hexdigests have fixed public length 64. Use upstream constant-time
        // equality, with its release-mode/platform limitations documented.
        let actual: String = Sha256::digest(credential.as_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        if !bool::from(actual.as_bytes().ct_eq(self.state.bearer_sha256.as_bytes())) {
            return Err(Error::Unauthorized);
        }
        let session = Session {
            state: Arc::clone(&self.state),
        };
        self.check_session(&session)?;
        Ok(session)
    }
    pub fn check_session(&self, session: &Session) -> Result<(), Error> {
        if !Arc::ptr_eq(&self.state, &session.state) {
            return Err(Error::Unauthorized);
        }
        session.check_active()
    }
    /// One-way logical withdrawal. Ingress must fence outbound release first
    /// and owns wakeup/cleanup; this method is not a global drain ACK.
    pub fn withdraw(&self) {
        self.state.active.store(false, Ordering::Release);
        self.state.revoked.notify_waiters();
    }
}
impl Session {
    pub fn require_permission(&self, permission: Permission) -> Result<(), Error> {
        self.check_active()?;
        if !self
            .state
            .grants
            .iter()
            .any(|g| g.permissions.contains(&permission))
        {
            return Err(Error::Forbidden);
        }
        Ok(())
    }
    /// Wait on this exact issuing authority; no polling or replacement grants.
    pub async fn withdrawn(&self) {
        let notified = self.state.revoked.notified();
        if self.state.active.load(Ordering::Acquire) {
            notified.await;
        }
    }
    pub fn subject_id(&self) -> Result<&str, Error> {
        self.check_active()?;
        Ok(&self.state.subject_id)
    }
    pub fn check_active(&self) -> Result<(), Error> {
        if self.state.active.load(Ordering::Acquire) {
            Ok(())
        } else {
            Err(Error::Unauthorized)
        }
    }
    pub fn require_reference(
        &self,
        reference: &Reference,
        permission: Permission,
    ) -> Result<&Grant, Error> {
        self.check_active()?;
        let grant = self
            .state
            .grants
            .iter()
            .find(|grant| &grant.selection.reference == reference)
            .ok_or(Error::Forbidden)?;
        if !grant.permissions.contains(&permission) {
            return Err(Error::Forbidden);
        }
        Ok(grant)
    }
    pub fn require_selection(
        &self,
        selection: &Selection,
        permission: Permission,
    ) -> Result<(), Error> {
        let grant = self.require_reference(&selection.reference, permission)?;
        if &grant.selection != selection {
            return Err(Error::Forbidden);
        }
        Ok(())
    }
}
