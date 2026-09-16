"""Read and transition ports for durable Research Run operational facts."""

from __future__ import annotations

from typing import Protocol

from .model import OnlyResearchRun, OnlyResearchRunId


class OnlyResearchRunReader(Protocol):
    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun: ...


class OnlyResearchRunTransitionStore(OnlyResearchRunReader, Protocol):
    def commit_transition(self, previous: OnlyResearchRun, transitioned: OnlyResearchRun) -> OnlyResearchRun: ...


__all__ = ["OnlyResearchRunReader", "OnlyResearchRunTransitionStore"]
