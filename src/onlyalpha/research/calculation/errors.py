"""Deterministic fail-closed Research Calculation errors."""

from __future__ import annotations


class OnlyResearchCalculationError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class OnlyResearchCalculationResultStoreError(OnlyResearchCalculationError):
    """Stable public failure contract for immutable Result persistence."""
