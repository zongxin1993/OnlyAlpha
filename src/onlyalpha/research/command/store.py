"""Business-shaped persistence port for Research submission and operational reads."""

from __future__ import annotations

from typing import Protocol

from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunId
from onlyalpha.research.run.store import OnlyResearchRunStore

from .model import OnlyResearchRunPageCursor, OnlyResearchSubmissionKey, OnlyResearchSubmissionRecord


class OnlyResearchRunReader(Protocol):
    def list_recent(
        self, *, limit: int, after: OnlyResearchRunPageCursor | None = None
    ) -> tuple[OnlyResearchRun, ...]: ...

    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun: ...


class OnlyResearchCommandStore(OnlyResearchRunStore, OnlyResearchRunReader, Protocol):
    def find_submission(self, submission_key: OnlyResearchSubmissionKey) -> OnlyResearchSubmissionRecord | None: ...

    def create_queued_submission(
        self,
        run: OnlyResearchRun,
        submission_key: OnlyResearchSubmissionKey,
        command_fingerprint: str,
    ) -> OnlyResearchSubmissionRecord: ...


__all__ = ["OnlyResearchCommandStore", "OnlyResearchRunReader"]
