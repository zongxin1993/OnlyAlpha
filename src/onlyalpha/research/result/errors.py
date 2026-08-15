"""Fail-closed Research Result authority errors."""

from __future__ import annotations


class OnlyResearchResultError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class OnlyResearchResultStoreError(OnlyResearchResultError):
    """Stable failure contract for immutable Research Result persistence."""
