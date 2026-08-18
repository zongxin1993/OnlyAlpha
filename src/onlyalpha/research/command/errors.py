"""Stable transport-neutral Research Command errors."""

from __future__ import annotations

from enum import StrEnum


class OnlyResearchCommandPhase(StrEnum):
    COMMAND = "COMMAND"
    ADMISSION = "ADMISSION"
    PERSISTENCE = "PERSISTENCE"
    QUERY = "QUERY"


class OnlyResearchCommandError(RuntimeError):
    def __init__(self, phase: OnlyResearchCommandPhase, code: str, detail: str) -> None:
        super().__init__(detail)
        self.phase = phase
        self.code = code
        self.detail = detail


class OnlyResearchSubmissionConflictError(OnlyResearchCommandError):
    def __init__(self) -> None:
        super().__init__(
            OnlyResearchCommandPhase.COMMAND,
            "RESEARCH_SUBMISSION_KEY_CONFLICT",
            "Idempotency Key is already bound to a different Research command",
        )


class OnlyResearchCancellationConflictError(OnlyResearchCommandError):
    def __init__(self, detail: str = "terminal Research Run cannot be cancelled") -> None:
        super().__init__(OnlyResearchCommandPhase.COMMAND, "RESEARCH_RUN_CANCELLATION_CONFLICT", detail)


class OnlyResearchCommandConcurrencyError(OnlyResearchCommandError):
    def __init__(self) -> None:
        super().__init__(
            OnlyResearchCommandPhase.PERSISTENCE,
            "RESEARCH_RUN_CONCURRENT_CHANGE",
            "Research Run changed concurrently too many times",
        )


class OnlyResearchRunCursorError(OnlyResearchCommandError):
    def __init__(self, detail: str = "Research Run cursor is invalid") -> None:
        super().__init__(OnlyResearchCommandPhase.QUERY, "RESEARCH_RUN_CURSOR_INVALID", detail)


class OnlyResearchRunPageLimitError(OnlyResearchCommandError):
    def __init__(self) -> None:
        super().__init__(
            OnlyResearchCommandPhase.QUERY,
            "RESEARCH_RUN_PAGE_LIMIT_INVALID",
            "Research Run page limit must be an integer between 1 and 100",
        )


__all__ = [name for name in globals() if name.startswith("Only")]
