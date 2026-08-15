"""Fail-closed Research Evaluation errors."""

from __future__ import annotations


class OnlyResearchEvaluationError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class OnlyResearchStatisticsResultStoreError(OnlyResearchEvaluationError):
    """Stable failure contract for immutable Statistics Result persistence."""
