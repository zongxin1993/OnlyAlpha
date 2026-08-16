"""Fail-closed Research Artifact errors."""

from __future__ import annotations


class OnlyResearchArtifactError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class OnlyResearchArtifactStoreError(OnlyResearchArtifactError):
    """Stable failure contract for immutable Research Artifact persistence."""
