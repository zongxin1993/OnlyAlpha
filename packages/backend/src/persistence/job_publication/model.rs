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
impl PublicationError {
    pub(crate) fn code(self) -> &'static str {
        match self {
            Self::Denied => "JOB_RESULT_ACCESS_DENIED",
            Self::MissingEvidence => "JOB_RESULT_MISSING_EVIDENCE",
            Self::Unavailable => "JOB_RESULT_UNAVAILABLE",
            Self::Integrity => "JOB_RESULT_CORRUPT",
            Self::Mismatch => "JOB_RESULT_MISMATCH",
            Self::Conflict => "JOB_RESULT_CONFLICT",
            Self::OwnershipLost => "JOB_RESULT_OWNERSHIP_LOST",
            Self::OutcomeUnknown => "JOB_RESULT_OUTCOME_UNKNOWN",
            Self::BudgetExceeded => "JOB_RESULT_BUDGET_EXCEEDED",
        }
    }
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
/// Operational association captured from the real opaque Claim before input
/// preparation. No parser, raw constructor or permission setter is exposed.
/// It is absent from canonical content and grants no input or publication access.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AttemptExecutionBinding {
    kind: JobKind,
    run: String,
    attempt: String,
    worker: String,
    number: i32,
    fence: i64,
    generation: String,
}
impl AttemptExecutionBinding {
    pub fn capture(claim: &AttemptClaim<'_>) -> Result<Self> {
        if !claim.certain() {
            return Err(PublicationError::OutcomeUnknown);
        }
        #[cfg(test)]
        if matches!(claim.source, ClaimSource::Fixture) {
            return Err(PublicationError::Denied);
        }
        Ok(Self {
            kind: claim.locator.kind,
            run: claim.locator.run.clone(),
            attempt: claim.attempt.clone(),
            worker: claim.worker.clone(),
            number: claim.number,
            fence: claim.fence,
            generation: claim.generation.clone(),
        })
    }
    pub(crate) fn matches(&self, claim: &AttemptClaim<'_>) -> bool {
        #[cfg(test)]
        if matches!(claim.source, ClaimSource::Fixture) {
            return false;
        }
        self.kind == claim.locator.kind
            && self.run == claim.locator.run
            && self.attempt == claim.attempt
            && self.worker == claim.worker
            && self.number == claim.number
            && self.fence == claim.fence
            && self.generation == claim.generation
            && claim.certain()
    }
    pub(crate) fn check_binding(&self, binding: &FrozenJobBinding) -> Result<()> {
        if self.kind != binding.kind()
            || self.run != binding.run_id()
            || binding.record()["runtime_generation"] != self.generation
        {
            return Err(PublicationError::Mismatch);
        }
        Ok(())
    }
}
/// Constructed only by the admitted input owner (not yet enabled in production).
pub struct FrozenBindingRegistration {
    pub(super) binding: FrozenJobBinding,
    pub(super) specification: String,
    pub(super) admission: String,
}
impl FrozenBindingRegistration {
    pub(crate) async fn from_research(
        tx: &crate::persistence::build_fact_read::BuildFactRead<'_, '_>,
        namespace: &SemanticStoreId,
        run: &crate::application::research_run::VerifiedRun,
        inputs: &crate::application::research_admission::PreparedInputs,
        datasets: &crate::persistence::research_dataset::Store,
        context: &crate::persistence::research_submission::Context<'_>,
    ) -> Result<Self> {
        let binding = crate::persistence::research_submission::strategy::frozen_binding(
            tx, namespace, run, inputs, datasets, context,
        )
        .await?;
        Ok(Self {
            binding,
            specification: run.specification_fingerprint().into(),
            admission: run.admission_resolution_fingerprint().into(),
        })
    }
    /// Only the original admission's retained input owners can authenticate this
    /// description. No caller JSON, preloaded PreparedJobInput or new Claim is used.
    pub(crate) async fn from_backtest(
        tx: &crate::persistence::build_fact_read::BuildFactRead<'_, '_>,
        inputs: &crate::application::backtest_run::Inputs<'_>,
        request: &crate::application::backtest_run::CreateRequest,
        context: &crate::application::backtest_run::Context<'_>,
    ) -> Result<Self> {
        let binding = inputs.frozen_binding(tx, request, context).await?;
        let owner = context.owner().map_err(owner_error)?;
        let resolution = inputs
            .resolve(owner, context.selection)
            .map_err(owner_error)?;
        Ok(Self {
            binding,
            specification: request.specification().fingerprint().map_err(owner_error)?,
            admission: crate::application::factor_content::hash(&resolution)
                .map_err(owner_error)?,
        })
    }
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
    /// Research 科学结果身份（写入 Run 的 research_result_fingerprint）；Backtest 为 None。
    pub(super) research_result: Option<String>,
    pub(super) ended_at: SystemTime,
    pub(super) owner: Option<std::sync::Arc<crate::application::finite_job::JoinedCut>>,
}

pub(crate) fn owner_error(
    error: impl Into<crate::application::research_admission::PreparationError>,
) -> PublicationError {
    let error = error.into();
    if error.code().contains("UNKNOWN") {
        PublicationError::OutcomeUnknown
    } else if error.code().contains("CANCEL") {
        PublicationError::Conflict
    } else if error.code().contains("MISMATCH") {
        PublicationError::Mismatch
    } else {
        PublicationError::Unavailable
    }
}

impl CompletedJobCandidate {
    pub(crate) fn from_joined(
        joined: crate::application::finite_job::JoinedFiniteJob,
    ) -> Result<Self> {
        let (binding, values, research_result, owner) =
            joined.into_parts().map_err(owner_error)?;
        let mut members = Vec::new();
        let mut bytes = 0usize;
        for (descriptor, body) in values {
            let descriptor_raw = encode(
                &serde_json::to_value(&descriptor).map_err(|_| PublicationError::Integrity)?,
                8192,
            )?;
            let content = encode(&body, CONTENT_LIMIT)?;
            bytes = bytes
                .checked_add(content.len())
                .filter(|n| *n <= CONTENT_LIMIT)
                .ok_or(PublicationError::BudgetExceeded)?;
            members.push(PreparedMember {
                descriptor,
                descriptor_raw,
                content_fingerprint: digest(content.as_bytes()),
                content,
            });
        }
        let manifest = super::reader::manifest(&binding, &members)?;
        let fingerprint = digest(manifest.as_bytes());
        owner.verify().map_err(owner_error)?;
        Ok(Self {
            binding,
            members,
            manifest,
            fingerprint,
            research_result,
            ended_at: SystemTime::now(),
            owner: Some(owner),
        })
    }
    #[cfg(test)]
    pub(crate) fn with_test_economic_result(&self, alter: impl FnOnce(&mut Value)) -> Self {
        let mut candidate = self.clone();
        let economic = candidate.members.iter_mut()
            .find(|member| member.descriptor.key() == "economic_result")
            .unwrap();
        let original = economic.content_fingerprint.clone();
        let mut body: Value = serde_json::from_str(&economic.content).unwrap();
        alter(&mut body["body"]["economic_result"]);
        economic.content = encode(&body, CONTENT_LIMIT).unwrap();
        economic.content_fingerprint = digest(economic.content.as_bytes());
        let changed = economic.content_fingerprint.clone();
        assert_ne!(changed, original);

        let causal = candidate.members.iter_mut()
            .find(|member| member.descriptor.key() == "causal_evidence")
            .unwrap();
        let mut body: Value = serde_json::from_str(&causal.content).unwrap();
        let references = body["body"]["members"].as_array_mut().unwrap();
        let reference = references.iter_mut()
            .find(|reference| reference["key"] == "economic_result")
            .unwrap();
        assert_eq!(reference["content"], original);
        reference["content"] = Value::String(changed);
        causal.content = encode(&body, CONTENT_LIMIT).unwrap();
        causal.content_fingerprint = digest(causal.content.as_bytes());
        candidate.manifest = super::reader::manifest(&candidate.binding, &candidate.members).unwrap();
        candidate.fingerprint = digest(candidate.manifest.as_bytes());
        assert_ne!(candidate.fingerprint, self.fingerprint);
        candidate
    }
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
}
#[derive(Clone, Debug)]
pub(super) struct PublicationAttempt {
    pub attempt: String,
    pub worker: String,
    pub number: i32,
    pub fence: i64,
}

#[derive(Clone, Debug)]
pub struct PublishedJobResult {
    pub(super) binding: FrozenJobBinding,
    pub(super) winner: PublicationAttempt,
    pub(super) specification: String,
    pub(super) admission: String,
    pub(super) fingerprint: String,
    pub(super) manifest: Value,
    pub(super) research_result: Option<String>,
    pub(super) members: Vec<PreparedMember>,
}
impl PublishedJobResult {
    pub(crate) fn manifest(&self) -> &Value {
        &self.manifest
    }
    /// 本 Run 正式列中的 Research 科学结果身份；读取方须在成员正文上重算并核对后才能消费。
    pub(crate) fn research_result_column(&self) -> Option<&str> {
        self.research_result.as_deref()
    }
    pub(crate) fn content_fingerprint(&self, key: &str) -> Option<&str> {
        self.members
            .iter()
            .find(|member| member.descriptor.key() == key)
            .map(|member| member.content_fingerprint.as_str())
    }
    pub fn specification_fingerprint(&self) -> &str {
        &self.specification
    }
    pub fn admission_fingerprint(&self) -> &str {
        &self.admission
    }
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
    pub(crate) fn member_keys(&self, kind: MemberKind) -> impl Iterator<Item = &str> {
        self.members
            .iter()
            .filter(move |member| member.descriptor.kind() == kind)
            .map(|member| member.descriptor.key())
    }
    pub(super) fn same(&self, c: &CompletedJobCandidate) -> bool {
        self.fingerprint == c.fingerprint
            && self.research_result == c.research_result
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
    pub(super) attempts: i32,
    pub(super) active_attempts: i64,
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
    pub fn attempts(&self) -> i32 {
        self.attempts
    }
    pub fn active_attempts(&self) -> i64 {
        self.active_attempts
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
    pub guard_check_ns: u128,
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
