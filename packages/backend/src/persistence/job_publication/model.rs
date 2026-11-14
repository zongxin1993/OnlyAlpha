use super::*;
use crate::persistence::{backtest_run, research_execution};
use std::time::SystemTime;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PublicationError {
    Denied,
    MissingEvidence,
    Unavailable,
    Integrity,
    Mismatch,
    Conflict,
    OwnershipLost,
    OutcomeUnknown,
    BudgetExceeded,
}
impl std::fmt::Display for PublicationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "JOB_PUBLICATION_{self:?}")
    }
}
impl std::error::Error for PublicationError {}
#[derive(Clone, Debug)]
pub struct RunLocator {
    pub(super) kind: JobKind,
    pub(super) run: String,
}
impl RunLocator {
    pub fn new(kind: JobKind, run: &str) -> Result<Self> {
        // Reuse the existing UUID4 value grammar; this does not create a Command fact.
        crate::application::command::CommandId::new(run)
            .map_err(|_| PublicationError::Integrity)?;
        Ok(Self {
            kind,
            run: run.into(),
        })
    }
    pub fn run_id(&self) -> &str {
        &self.run
    }
    pub fn kind(&self) -> JobKind {
        self.kind
    }
}
pub(super) enum ClaimSource<'a> {
    Research(&'a research_execution::Claim),
    Backtest(&'a backtest_run::Claim),
    #[cfg(test)]
    Fixture,
}
/// Borrow the real opaque Claim, preserving local ownership certainty. This is
/// an adapter, not another claim/lease authority or a deserializable token.
pub struct AttemptClaim<'a> {
    pub(super) locator: RunLocator,
    pub(super) attempt: String,
    pub(super) worker: String,
    pub(super) number: i32,
    pub(super) fence: i64,
    pub(super) generation: String,
    pub(super) source: ClaimSource<'a>,
}
impl<'a> AttemptClaim<'a> {
    pub fn from_backtest(c: &'a backtest_run::Claim) -> Self {
        Self {
            locator: RunLocator {
                kind: JobKind::Backtest,
                run: c.run_id().into(),
            },
            attempt: c.attempt_id().into(),
            worker: c.worker_instance_id().into(),
            number: c.attempt_number(),
            fence: c.fencing_token(),
            generation: c.runtime_generation_fingerprint().into(),
            source: ClaimSource::Backtest(c),
        }
    }
    pub fn from_research(c: &'a research_execution::Claim) -> Self {
        Self {
            locator: RunLocator {
                kind: JobKind::Research,
                run: c.run_id().into(),
            },
            attempt: c.attempt_id().into(),
            worker: c.worker_instance_id().into(),
            number: c.attempt_number(),
            fence: i64::from(c.attempt_number()),
            generation: c.runtime_generation_fingerprint().into(),
            source: ClaimSource::Research(c),
        }
    }
    pub(super) fn certain(&self) -> bool {
        match self.source {
            ClaimSource::Backtest(c) => c.ownership_certain(),
            ClaimSource::Research(c) => c.ownership_certain(),
            #[cfg(test)]
            ClaimSource::Fixture => true,
        }
    }
}
/// Constructed only by the admitted input owner (not yet enabled in production).
pub struct FrozenBindingRegistration {
    pub(super) binding: FrozenJobBinding,
    pub(super) specification: String,
    pub(super) admission: String,
}
#[derive(Clone, Debug)]
pub(super) struct PreparedMember {
    pub descriptor: ResultMember,
    pub descriptor_raw: String,
    pub content: String,
    pub content_fingerprint: String,
}
/// Private construction belongs to the joined real execution owner. No parser,
/// boolean, receipt, StoredPublication or fixture API can construct this in production.
#[derive(Clone, Debug)]
pub struct CompletedJobCandidate {
    pub(super) binding: FrozenJobBinding,
    pub(super) members: Vec<PreparedMember>,
    pub(super) manifest: String,
    pub(super) fingerprint: String,
    pub(super) ended_at: SystemTime,
}
#[derive(Clone, Debug)]
pub struct PublishedJobResult {
    pub(super) binding: FrozenJobBinding,
    pub(super) fingerprint: String,
    pub(super) members: Vec<PreparedMember>,
}
impl PublishedJobResult {
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn binding(&self) -> &FrozenJobBinding {
        &self.binding
    }
    pub fn member_count(&self) -> usize {
        self.members.len()
    }
    pub fn content(&self, key: &str) -> Option<&str> {
        self.members
            .iter()
            .find(|m| m.descriptor.key() == key)
            .map(|m| m.content.as_str())
    }
    pub(super) fn same(&self, c: &CompletedJobCandidate) -> bool {
        self.fingerprint == c.fingerprint
            && self.binding.record() == c.binding.record()
            && self.members.len() == c.members.len()
            && self.members.iter().zip(&c.members).all(|(a, b)| {
                a.descriptor == b.descriptor
                    && a.content == b.content
                    && a.content_fingerprint == b.content_fingerprint
            })
    }
}
#[derive(Debug)]
pub struct ConfirmedUnpublished {
    pub(super) binding: FrozenJobBinding,
    pub(super) revision: i64,
    pub(super) state: String,
}
impl ConfirmedUnpublished {
    pub fn binding(&self) -> &FrozenJobBinding {
        &self.binding
    }
    pub fn run_revision(&self) -> i64 {
        self.revision
    }
    pub fn run_state(&self) -> &str {
        &self.state
    }
}
#[derive(Debug)]
pub enum PublicationObservation {
    Published(PublishedJobResult),
    ConfirmedUnpublished(ConfirmedUnpublished),
    Unresolved,
}
#[derive(Clone, Debug, Default, serde::Serialize)]
pub struct PublishTimings {
    pub lock_wait_ns: u128,
    pub members_write_ns: u128,
    pub finalization_ns: u128,
    pub commit_ns: u128,
    pub total_ns: u128,
}
#[derive(Debug)]
pub enum PublishOutcome {
    Committed {
        publication: PublishedJobResult,
        timings: PublishTimings,
    },
    AlreadyPublished(PublishedJobResult),
}
impl PublishOutcome {
    pub fn publication(&self) -> &PublishedJobResult {
        match self {
            Self::Committed { publication, .. } | Self::AlreadyPublished(publication) => {
                publication
            }
        }
    }
}
