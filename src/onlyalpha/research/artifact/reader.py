"""Bounded newest-to-oldest Research Artifact profile dispatch."""

from __future__ import annotations

from pathlib import Path

from .errors import OnlyResearchArtifactStoreError
from .scientific_store import OnlyParquetResearchCalculationArtifactStore, OnlyParquetResearchScientificArtifactStore
from .scientific_v3_store import OnlyParquetResearchScientificArtifactStoreV3
from .store import OnlyParquetResearchArtifactStore


class OnlyResearchArtifactProfileReader:
    def __init__(self, root: Path) -> None:
        self._scientific_v3 = OnlyParquetResearchScientificArtifactStoreV3(root)
        self._scientific = OnlyParquetResearchScientificArtifactStore(root)
        self._statistics = OnlyParquetResearchArtifactStore(root)
        self._calculation = OnlyParquetResearchCalculationArtifactStore(root)
        self._root = root

    def load_calculation_v2_verified(self, profile: str, schema_version: int, artifact_content_fingerprint: str):  # type: ignore[no-untyped-def]
        from .calculation_v2_store import OnlyParquetResearchCalculationArtifactStoreV2

        if profile != "RESEARCH_CALCULATION_V2" or type(schema_version) is not int or schema_version != 2:
            raise OnlyResearchArtifactStoreError(
                "ARTIFACT_PROFILE_UNSUPPORTED", "exact Calculation V2 locator required"
            )
        return OnlyParquetResearchCalculationArtifactStoreV2(self._root).load_verified(artifact_content_fingerprint)

    def load_verified(self, research_result_fingerprint: str):  # type: ignore[no-untyped-def]
        try:
            return self._calculation.load_verified(research_result_fingerprint)
        except OnlyResearchArtifactStoreError as exc:
            if exc.code != "ARTIFACT_NOT_FOUND":
                raise
        try:
            return self._scientific_v3.load_verified(research_result_fingerprint)
        except OnlyResearchArtifactStoreError as exc:
            if exc.code != "ARTIFACT_NOT_FOUND":
                raise
        try:
            return self._scientific.load_verified(research_result_fingerprint)
        except OnlyResearchArtifactStoreError as exc:
            if exc.code != "ARTIFACT_NOT_FOUND":
                raise
        return self._statistics.load_verified(research_result_fingerprint)


__all__ = ["OnlyResearchArtifactProfileReader"]
