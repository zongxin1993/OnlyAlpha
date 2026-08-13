"""Exact MarketData completion boundary for Backtest causal recovery."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.data.models import OnlyMarketDataInboundUpdate
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution.causal_recovery import (
    OnlyExecutionRecoveryPhase,
    OnlyExecutionRecoverySession,
)
from onlyalpha.runtime.backtest.checkpoint import OnlyBacktestReplayCursor
from onlyalpha.runtime.backtest.result_progress import OnlyBacktestBarCompletion


class OnlyBacktestRecoveryError(RuntimeError):
    """The causal replay did not observe its exact MarketData boundary."""


@dataclass(frozen=True, slots=True)
class OnlyBacktestRecoveryBoundary:
    source_id: OnlyMarketDataSourceId
    data_version: OnlyDataVersion
    update_id: OnlyMarketDataUpdateId
    source_sequence: int
    ts_event: OnlyTimestamp

    def __post_init__(self) -> None:
        if self.source_sequence < 1:
            raise ValueError("Recovery boundary source sequence must be positive")

    @classmethod
    def from_record(cls, record: OnlyMarketDataInboundUpdate) -> OnlyBacktestRecoveryBoundary:
        return cls(
            record.source_id,
            record.data_version,
            record.update_id,
            int(record.source_sequence),
            record.ts_event,
        )

    @property
    def identity(self) -> tuple[OnlyMarketDataSourceId, OnlyDataVersion, OnlyMarketDataUpdateId, int]:
        return self.source_id, self.data_version, self.update_id, self.source_sequence


class OnlyBacktestRecoveryPhase(StrEnum):
    MATCHING_PERSISTED_TAIL = "MATCHING_PERSISTED_TAIL"
    TAIL_RESOLVED_BOUNDARY_OPEN = "TAIL_RESOLVED_BOUNDARY_OPEN"
    BOUNDARY_COMPLETED = "BOUNDARY_COMPLETED"
    FAILED = "FAILED"


class OnlyBacktestRecoverySession:
    """Combines execution-tail progress with exact Backtest Bar completion."""

    def __init__(
        self,
        execution_session: OnlyExecutionRecoverySession,
        checkpoint_cursor: OnlyBacktestReplayCursor,
    ) -> None:
        self.execution_session = execution_session
        self._checkpoint_cursor = checkpoint_cursor
        self._current_boundary: OnlyBacktestRecoveryBoundary | None = None
        self._final_boundary: OnlyBacktestRecoveryBoundary | None = None
        self._last_completed_sequence = checkpoint_cursor.last_source_sequence
        self._entered_identities: set[tuple[OnlyMarketDataSourceId, OnlyDataVersion, OnlyMarketDataUpdateId, int]] = (
            set()
        )
        self._terminal_phase: OnlyBacktestRecoveryPhase | None = None

    @property
    def phase(self) -> OnlyBacktestRecoveryPhase:
        if self._terminal_phase is not None:
            return self._terminal_phase
        if self.execution_session.phase is OnlyExecutionRecoveryPhase.FAILED:
            return OnlyBacktestRecoveryPhase.FAILED
        if self.execution_session.phase is OnlyExecutionRecoveryPhase.MATCHING_PERSISTED_TAIL:
            return OnlyBacktestRecoveryPhase.MATCHING_PERSISTED_TAIL
        return OnlyBacktestRecoveryPhase.TAIL_RESOLVED_BOUNDARY_OPEN

    @property
    def current_boundary(self) -> OnlyBacktestRecoveryBoundary | None:
        return self._current_boundary

    @property
    def final_boundary(self) -> OnlyBacktestRecoveryBoundary | None:
        return self._final_boundary

    def enter_boundary(self, boundary: OnlyBacktestRecoveryBoundary) -> None:
        self._require_active()
        if self._current_boundary is not None:
            self._fail("RECOVERY_BOUNDARY_ALREADY_OPEN")
        if boundary.identity in self._entered_identities:
            self._fail("RECOVERY_BOUNDARY_IDENTITY_MISMATCH: duplicate boundary")
        if (
            boundary.source_id != self._checkpoint_cursor.source_id
            or boundary.data_version != self._checkpoint_cursor.data_version
        ):
            self._fail("RECOVERY_BOUNDARY_IDENTITY_MISMATCH: checkpoint cursor scope")
        if boundary.source_sequence <= self._last_completed_sequence:
            self._fail("RECOVERY_BOUNDARY_IDENTITY_MISMATCH: source sequence did not advance")
        self._entered_identities.add(boundary.identity)
        self._current_boundary = boundary

    def observe_completion(self, completion: OnlyBacktestBarCompletion) -> None:
        self._require_active()
        current = self._current_boundary
        if current is None:
            self._fail("RECOVERY_BOUNDARY_NOT_ENTERED")
        if (
            completion.source_id != current.source_id
            or completion.data_version != current.data_version
            or completion.update_id != current.update_id
            or completion.source_sequence != current.source_sequence
            or completion.ts_event != current.ts_event
        ):
            self._fail("RECOVERY_BOUNDARY_IDENTITY_MISMATCH")
        self._last_completed_sequence = current.source_sequence
        self._current_boundary = None
        if self.execution_session.tail_resolved:
            self._final_boundary = current
            self._terminal_phase = OnlyBacktestRecoveryPhase.BOUNDARY_COMPLETED

    def require_boundary_callback(self) -> None:
        if self.phase is OnlyBacktestRecoveryPhase.FAILED:
            raise OnlyBacktestRecoveryError("RECOVERY_SESSION_FAILED")
        if self._current_boundary is not None:
            self._fail("RECOVERY_BOUNDARY_CALLBACK_MISSING")

    def require_boundary_completed(self) -> None:
        if self.phase is not OnlyBacktestRecoveryPhase.BOUNDARY_COMPLETED:
            if self.phase is OnlyBacktestRecoveryPhase.FAILED:
                raise OnlyBacktestRecoveryError("RECOVERY_SESSION_FAILED")
            raise OnlyBacktestRecoveryError("RECOVERY_BOUNDARY_INCOMPLETE")

    def _require_active(self) -> None:
        if self.phase is OnlyBacktestRecoveryPhase.FAILED:
            raise OnlyBacktestRecoveryError("RECOVERY_SESSION_FAILED")
        if self.phase is OnlyBacktestRecoveryPhase.BOUNDARY_COMPLETED:
            raise OnlyBacktestRecoveryError("RECOVERY_PROCESS_AFTER_BOUNDARY_COMPLETE")

    def _fail(self, message: str) -> NoReturn:
        self._terminal_phase = OnlyBacktestRecoveryPhase.FAILED
        raise OnlyBacktestRecoveryError(message)


__all__ = [
    "OnlyBacktestRecoveryBoundary",
    "OnlyBacktestRecoveryError",
    "OnlyBacktestRecoveryPhase",
    "OnlyBacktestRecoverySession",
]
