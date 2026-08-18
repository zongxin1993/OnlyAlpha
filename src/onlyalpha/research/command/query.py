"""Operational Research Run query application boundary."""

from __future__ import annotations

from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunId

from .errors import OnlyResearchRunPageLimitError
from .model import OnlyResearchRunPage, OnlyResearchRunPageCursor
from .store import OnlyResearchCommandStore

MAX_RESEARCH_RUN_PAGE_SIZE = 100
DEFAULT_RESEARCH_RUN_PAGE_SIZE = 50


class OnlyResearchRunQueryService:
    def __init__(self, store: OnlyResearchCommandStore) -> None:
        self._store = store

    def get_run(self, run_id: OnlyResearchRunId) -> OnlyResearchRun:
        return self._store.load(run_id)

    def list_runs(
        self, *, limit: int = DEFAULT_RESEARCH_RUN_PAGE_SIZE, cursor: str | None = None
    ) -> OnlyResearchRunPage:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESEARCH_RUN_PAGE_SIZE:
            raise OnlyResearchRunPageLimitError()
        after = None if cursor is None else OnlyResearchRunPageCursor.decode(cursor)
        candidates = self._store.list_recent(limit=limit + 1, after=after)
        runs = candidates[:limit]
        has_more = len(candidates) > limit
        next_cursor = (
            OnlyResearchRunPageCursor(runs[-1].queued_at, runs[-1].run_id).encode() if has_more and runs else None
        )
        return OnlyResearchRunPage(runs, has_more, next_cursor)


__all__ = [name for name in globals() if name.startswith(("Only", "MAX_", "DEFAULT_"))]
