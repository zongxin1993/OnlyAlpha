"""Fail-closed Search Experiment provenance errors."""

from __future__ import annotations


class OnlySearchProvenanceError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class OnlySearchProvenanceStoreError(OnlySearchProvenanceError):
    """Stable failure contract for immutable Search provenance persistence."""
