from __future__ import annotations

from pathlib import Path

from onlyalpha.research import OnlyResearchQueryService
from tests.research.artifact.support import artifact_case


def query_case(root: Path):  # type: ignore[no-untyped-def]
    plan, research_result, statistics_store, materializer, candidate, store = artifact_case(root)
    store.commit(candidate)
    service = OnlyResearchQueryService(store)
    return plan, research_result, statistics_store, materializer, candidate, store, service
