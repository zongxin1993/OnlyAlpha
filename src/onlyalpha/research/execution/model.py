"""Research execution-attempt ownership and immutable history domain."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from onlyalpha.research.run import OnlyResearchRunFailure, OnlyResearchRunId


@dataclass(frozen=True, order=True, slots=True)
class OnlyResearchRunAttemptId:
    value: str

    def __post_init__(self) -> None:
        _uuid4(self.value, "Research Run Attempt ID")

    @classmethod
    def new(cls) -> OnlyResearchRunAttemptId:
        return cls(str(uuid.uuid4()))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, order=True, slots=True)
class OnlyResearchWorkerInstanceId:
    value: str

    def __post_init__(self) -> None:
        _uuid4(self.value, "Research Worker Instance ID")

    @classmethod
    def new(cls) -> OnlyResearchWorkerInstanceId:
        return cls(str(uuid.uuid4()))

    def __str__(self) -> str:
        return self.value


class OnlyResearchRunAttemptState(StrEnum):
    ACTIVE = "ACTIVE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self is not self.ACTIVE


@dataclass(frozen=True, slots=True)
class OnlyResearchRunAttempt:
    attempt_id: OnlyResearchRunAttemptId
    run_id: OnlyResearchRunId
    attempt_number: int
    state: OnlyResearchRunAttemptState
    worker_instance_id: OnlyResearchWorkerInstanceId
    claimed_at: datetime
    last_heartbeat_at: datetime
    lease_expires_at: datetime
    finished_at: datetime | None = None
    failure: OnlyResearchRunFailure | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.attempt_id, OnlyResearchRunAttemptId):
            raise ValueError("Attempt ID is invalid")
        if not isinstance(self.run_id, OnlyResearchRunId):
            raise ValueError("Run ID is invalid")
        if isinstance(self.attempt_number, bool) or not isinstance(self.attempt_number, int) or self.attempt_number < 1:
            raise ValueError("attempt_number must be a positive integer")
        if not isinstance(self.state, OnlyResearchRunAttemptState):
            raise ValueError("Attempt state is invalid")
        if not isinstance(self.worker_instance_id, OnlyResearchWorkerInstanceId):
            raise ValueError("Worker Instance ID is invalid")
        for name in ("claimed_at", "last_heartbeat_at", "lease_expires_at"):
            _utc(getattr(self, name), name)
        if self.finished_at is not None:
            _utc(self.finished_at, "finished_at")
        if self.last_heartbeat_at < self.claimed_at:
            raise ValueError("last_heartbeat_at precedes claimed_at")
        if self.lease_expires_at < self.last_heartbeat_at:
            raise ValueError("lease_expires_at precedes last_heartbeat_at")
        if self.state is self.state.ACTIVE:
            if self.finished_at is not None or self.failure is not None:
                raise ValueError("ACTIVE Attempt contains terminal facts")
        else:
            if self.finished_at is None:
                raise ValueError("terminal Attempt requires finished_at")
            if self.finished_at < self.claimed_at:
                raise ValueError("finished_at precedes claimed_at")
            requires_failure = self.state in {self.state.FAILED, self.state.EXPIRED}
            if requires_failure != (self.failure is not None):
                raise ValueError("FAILED/EXPIRED Attempt requires failure and other terminal states forbid it")


@dataclass(frozen=True, slots=True)
class OnlyResearchExecutionClaim:
    attempt: OnlyResearchRunAttempt

    def __post_init__(self) -> None:
        if self.attempt.state is not OnlyResearchRunAttemptState.ACTIVE:
            raise ValueError("Execution Claim requires an ACTIVE Attempt")


def _uuid4(value: object, name: str) -> None:
    try:
        parsed = uuid.UUID(value)  # type: ignore[arg-type]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a canonical UUID") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError(f"{name} must be a canonical UUID4")


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{name} must be timezone-aware UTC")
    return value


__all__ = [name for name in globals() if name.startswith("Only")]
