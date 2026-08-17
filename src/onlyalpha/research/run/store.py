"""Persistence port for durable Research Run operational facts."""

from __future__ import annotations

from typing import Protocol

from .model import OnlyResearchRun, OnlyResearchRunId


class OnlyResearchRunStore(Protocol):
    def create_queued(self, run: OnlyResearchRun) -> OnlyResearchRun: ...

    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun: ...

    def commit_transition(self, previous: OnlyResearchRun, transitioned: OnlyResearchRun) -> OnlyResearchRun: ...


__all__ = ["OnlyResearchRunStore"]
