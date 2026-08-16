from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from onlyalpha.research import (
    OnlyParquetResearchArtifactStore,
    OnlyResearchArtifactMaterializer,
)
from tests.research.result.support import result_case


def artifact_case(root: Path, *, year: int = 2026):
    plan, _, result_store, research_result, statistics_store = result_case(root)
    result_store.commit(research_result)
    materializer = OnlyResearchArtifactMaterializer(result_store, statistics_store)
    candidate = materializer.materialize(plan.fingerprint)
    store = OnlyParquetResearchArtifactStore(
        root / "research-artifacts",
        audit_time=lambda: datetime(year, 8, 16, tzinfo=UTC),
    )
    return plan, research_result, statistics_store, materializer, candidate, store


def artifact_target(root: Path, research_result_fingerprint: str) -> Path:
    return (
        root
        / "research-artifacts"
        / "research-statistics-v1"
        / "sha256"
        / research_result_fingerprint[:2]
        / research_result_fingerprint
    )
