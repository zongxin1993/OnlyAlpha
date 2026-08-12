"""Immutable outcome of checkpoint restoration and exact causal replay."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.runtime.checkpoint.model import OnlyRuntimeCheckpoint
from onlyalpha.runtime.recovery.session import OnlyRuntimeRecoveryBoundary

from .orchestrator import OnlyRuntimeRecoveryDiagnostic


@dataclass(frozen=True, slots=True)
class OnlyRuntimeRecoveryOutcome:
    restored_checkpoint: OnlyRuntimeCheckpoint
    diagnostic: OnlyRuntimeRecoveryDiagnostic
    persisted_tail_start_sequence: int | None
    persisted_tail_end_sequence: int | None
    continuation_start_sequence: int | None
    continuation_end_sequence: int | None
    final_boundary: OnlyRuntimeRecoveryBoundary | None
    replay_performed: bool

    def __post_init__(self) -> None:
        self._validate_range("persisted tail", self.persisted_tail_start_sequence, self.persisted_tail_end_sequence)
        self._validate_range("continuation", self.continuation_start_sequence, self.continuation_end_sequence)
        if self.replay_performed and self.final_boundary is None:
            raise ValueError("replayed recovery requires a final boundary")
        if not self.replay_performed and self.final_boundary is not None:
            raise ValueError("non-replayed recovery cannot have a final boundary")
        if self.diagnostic.final_ready_sequence < self.restored_checkpoint.header.covered_execution_sequence:
            raise ValueError("recovery outcome final sequence precedes its checkpoint")

    @staticmethod
    def _validate_range(label: str, start: int | None, end: int | None) -> None:
        if (start is None) != (end is None):
            raise ValueError(f"{label} range endpoints must both be present or absent")
        if start is not None and (start < 1 or end is None or end < start):
            raise ValueError(f"{label} range is invalid")


__all__ = ["OnlyRuntimeRecoveryOutcome"]
