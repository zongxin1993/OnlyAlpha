"""Backtest Attempt ownership, deterministic worker control and outcomes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from .model import OnlyBacktestRun, OnlyBacktestRunFailure, OnlyBacktestRunId


@dataclass(frozen=True, order=True, slots=True)
class OnlyBacktestAttemptId:
    value: str

    def __post_init__(self) -> None:
        _uuid4(self.value, "Backtest Attempt ID")

    @classmethod
    def new(cls) -> OnlyBacktestAttemptId:
        return cls(str(uuid.uuid4()))


@dataclass(frozen=True, order=True, slots=True)
class OnlyBacktestWorkerInstanceId:
    value: str

    def __post_init__(self) -> None:
        _uuid4(self.value, "Backtest Worker Instance ID")

    @classmethod
    def new(cls) -> OnlyBacktestWorkerInstanceId:
        return cls(str(uuid.uuid4()))


class OnlyBacktestAttemptState(StrEnum):
    ACTIVE = "ACTIVE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class OnlyBacktestAttempt:
    attempt_id: OnlyBacktestAttemptId
    run_id: OnlyBacktestRunId
    attempt_number: int
    state: OnlyBacktestAttemptState
    worker_instance_id: OnlyBacktestWorkerInstanceId
    fencing_token: int
    claimed_at: datetime
    last_heartbeat_at: datetime
    lease_expires_at: datetime
    finished_at: datetime | None = None
    failure_code: str | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if self.attempt_number < 1 or self.fencing_token < 1:
            raise ValueError("BACKTEST_ATTEMPT_SEQUENCE_INVALID")
        for name in ("claimed_at", "last_heartbeat_at", "lease_expires_at"):
            _utc(getattr(self, name), name)
        if self.finished_at is not None:
            _utc(self.finished_at, "finished_at")
        if self.last_heartbeat_at < self.claimed_at or self.lease_expires_at < self.last_heartbeat_at:
            raise ValueError("BACKTEST_ATTEMPT_TIME_INVALID")
        if self.state is self.state.ACTIVE:
            if self.finished_at is not None or self.failure_code is not None or self.failure_detail is not None:
                raise ValueError("ACTIVE Backtest Attempt contains terminal facts")
        elif self.finished_at is None:
            raise ValueError("terminal Backtest Attempt requires finished_at")
        requires_failure = self.state in {self.state.FAILED, self.state.EXPIRED}
        if requires_failure != (self.failure_code is not None and self.failure_detail is not None):
            raise ValueError("Backtest Attempt failure fields differ from state")


@dataclass(frozen=True, slots=True)
class OnlyBacktestExecutionClaim:
    run: OnlyBacktestRun
    attempt: OnlyBacktestAttempt

    def __post_init__(self) -> None:
        if self.run.run_id != self.attempt.run_id or self.attempt.state is not OnlyBacktestAttemptState.ACTIVE:
            raise ValueError("BACKTEST_EXECUTION_CLAIM_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyBacktestExecutionPolicy:
    lease_duration: timedelta = timedelta(seconds=30)
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if self.lease_duration <= timedelta(0) or self.max_attempts < 1:
            raise ValueError("BACKTEST_EXECUTION_POLICY_INVALID")


class OnlyBacktestExecutionStore(Protocol):
    def claim_next(
        self,
        worker_instance_id: OnlyBacktestWorkerInstanceId,
        attempt_id: OnlyBacktestAttemptId,
        policy: OnlyBacktestExecutionPolicy,
    ) -> OnlyBacktestExecutionClaim | None: ...

    def heartbeat(self, claim: OnlyBacktestExecutionClaim, lease_duration: timedelta) -> OnlyBacktestAttempt: ...

    def complete(
        self,
        claim: OnlyBacktestExecutionClaim,
        *,
        evidence_fingerprint: str,
        result_fingerprint: str,
        determinism_fingerprint: str,
    ) -> OnlyBacktestRun: ...

    def fail(self, claim: OnlyBacktestExecutionClaim, failure: OnlyBacktestRunFailure) -> OnlyBacktestRun: ...

    def cancel(self, claim: OnlyBacktestExecutionClaim) -> OnlyBacktestRun: ...


def _uuid4(value: object, name: str) -> None:
    try:
        parsed = uuid.UUID(value)  # type: ignore[arg-type]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a canonical UUID4") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError(f"{name} must be a canonical UUID4")


def _utc(value: object, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{name} must be timezone-aware UTC")


__all__ = [name for name in globals() if name.startswith("Only")]
