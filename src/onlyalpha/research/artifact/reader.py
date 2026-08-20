"""Bounded V1/V2 Research Artifact profile dispatch for read-only consumers."""

from __future__ import annotations

from pathlib import Path

from .errors import OnlyResearchArtifactStoreError
from .scientific_store import OnlyParquetResearchScientificArtifactStore
from .store import OnlyParquetResearchArtifactStore


class OnlyResearchArtifactProfileReader:
    def __init__(self, root: Path) -> None:
        self._scientific = OnlyParquetResearchScientificArtifactStore(root)
        self._statistics = OnlyParquetResearchArtifactStore(root)

    def load_verified(self, research_result_fingerprint: str):  # type: ignore[no-untyped-def]
        try:
            return self._scientific.load_verified(research_result_fingerprint)
        except OnlyResearchArtifactStoreError as exc:
            if exc.code != "ARTIFACT_NOT_FOUND":
                raise
        return self._statistics.load_verified(research_result_fingerprint)


__all__ = ["OnlyResearchArtifactProfileReader"]
