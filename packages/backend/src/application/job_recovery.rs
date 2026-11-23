//! 原 Run 的发布观察和恢复决策；不另建租约或认领权限。
use crate::persistence::job_publication::{
    ConfirmedUnpublished, PublicationError, PublicationObservation, PublicationRepository,
    PublishedJobResult, RunLocator,
};

/// Operational policy only. Attempt limits never enter economic identity.
#[derive(Clone, Copy, Debug)]
pub struct RetryBudget(i32);
impl RetryBudget {
    pub fn new(max_attempts: i64) -> Result<Self, PublicationError> {
        let limit = i32::try_from(max_attempts).map_err(|_| PublicationError::Integrity)?;
        if limit <= 0 {
            return Err(PublicationError::Integrity);
        }
        Ok(Self(limit))
    }
    pub fn finite_job() -> Self {
        Self(3)
    }
    pub fn max_attempts(self) -> i32 {
        self.0
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RecoveryRefusal {
    Terminal,
    RetryExhausted,
}
#[derive(Debug)]
pub enum RecoveryDecision {
    AlreadyPublished(PublishedJobResult),
    RecomputeWithNewClaim(ConfirmedUnpublished),
    FinishCancellation(ConfirmedUnpublished),
    WaitForResolution,
    /// Keep the original absence proof for an exact terminal control CAS.
    Refused(RecoveryRefusal, ConfirmedUnpublished),
}
pub struct JobRecovery;
impl JobRecovery {
    /// A decision is not a Claim. The existing owning claim/cancellation
    /// transaction must recheck this original observation under the Run lock.
    pub async fn resolve(
        repository: &mut PublicationRepository<'_>,
        run: &RunLocator,
        budget: RetryBudget,
    ) -> Result<RecoveryDecision, PublicationError> {
        Self::decide(repository.observe(run).await?, budget)
    }
    pub(crate) fn decide(
        observation: PublicationObservation,
        budget: RetryBudget,
    ) -> Result<RecoveryDecision, PublicationError> {
        let proof = match observation {
            PublicationObservation::Published(result) => {
                return Ok(RecoveryDecision::AlreadyPublished(result));
            }
            PublicationObservation::Unresolved => return Ok(RecoveryDecision::WaitForResolution),
            PublicationObservation::ConfirmedUnpublished(proof) => proof,
        };
        if proof.attempts() < 0
            || proof.active_attempts() < 0
            || proof.active_attempts() > 1
            || proof.active_attempts() > i64::from(proof.attempts())
            || !matches!(proof.run_state(), "QUEUED" | "RUNNING" | "CANCEL_REQUESTED" | "FAILED" | "CANCELLED")
        {
            return Err(PublicationError::Integrity);
        }
        if matches!(proof.run_state(), "FAILED" | "CANCELLED") {
            if proof.active_attempts() != 0 {
                return Err(PublicationError::Integrity);
            }
            return Ok(RecoveryDecision::Refused(RecoveryRefusal::Terminal, proof));
        }
        if proof.active_attempts() != 0 {
            return Ok(RecoveryDecision::WaitForResolution);
        }
        if proof.run_state() == "CANCEL_REQUESTED" {
            return Ok(RecoveryDecision::FinishCancellation(proof));
        }
        if proof.attempts() >= budget.max_attempts() {
            return Ok(RecoveryDecision::Refused(RecoveryRefusal::RetryExhausted, proof));
        }
        Ok(RecoveryDecision::RecomputeWithNewClaim(proof))
    }
}

#[cfg(test)]
#[path = "../tests/job_recovery_tests.rs"]
mod tests;
