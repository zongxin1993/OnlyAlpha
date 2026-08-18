"""Bounded Research execution lease and retry policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from onlyalpha.research.run import OnlyResearchRunFailure


class OnlyResearchRetryDecision(StrEnum):
    RETRY = "RETRY"
    FINAL_FAIL = "FINAL_FAIL"


@dataclass(frozen=True, slots=True)
class OnlyResearchExecutionPolicy:
    lease_duration: timedelta = timedelta(minutes=2)
    heartbeat_interval: timedelta = timedelta(seconds=30)
    max_attempts: int = 3
    retryable_failure_codes: frozenset[str] = frozenset(
        {"LEASE_EXPIRED", "UNEXPECTED_WORKER_FAILURE", "RESEARCH_RUN_STORE_UNAVAILABLE"}
    )

    def __post_init__(self) -> None:
        if self.heartbeat_interval <= timedelta(0):
            raise ValueError("heartbeat_interval must be positive")
        if self.lease_duration <= self.heartbeat_interval:
            raise ValueError("heartbeat_interval must be shorter than lease_duration")
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if any(not code or code != code.upper() for code in self.retryable_failure_codes):
            raise ValueError("retryable failure codes must be stable upper-case codes")

    def retry_decision(self, failure: OnlyResearchRunFailure, *, attempt_number: int) -> OnlyResearchRetryDecision:
        if attempt_number >= self.max_attempts:
            return OnlyResearchRetryDecision.FINAL_FAIL
        return (
            OnlyResearchRetryDecision.RETRY
            if failure.code in self.retryable_failure_codes
            else OnlyResearchRetryDecision.FINAL_FAIL
        )


__all__ = [name for name in globals() if name.startswith("Only")]
