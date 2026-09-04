"""Generation-specific composition for the existing Product Research admission authority."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from onlyalpha.research.dataset import OnlyResearchDatasetSnapshotStore
from onlyalpha.research.run.admission import OnlyResearchRunAdmissionService
from onlyalpha.research.run.model import OnlyResearchRunId
from onlyalpha.research.run.store import OnlyResearchRunStore
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver

from .generation import (
    OnlyAuthoringExecutionGeneration,
    OnlyAuthoringExecutionGenerationRegistry,
    OnlyAuthoringExecutionGenerationStore,
)


def only_compose_authoring_research_admission(
    *,
    generation: OnlyAuthoringExecutionGeneration,
    generation_store: OnlyAuthoringExecutionGenerationStore,
    default_resolver: OnlyResearchSpecificationResolver,
    dataset_store: OnlyResearchDatasetSnapshotStore,
    run_store: OnlyResearchRunStore,
    now_utc: Callable[[], datetime],
    run_id_factory: Callable[[], OnlyResearchRunId] = OnlyResearchRunId.new,
) -> OnlyResearchRunAdmissionService:
    """Verify the same immutable generation before exposing Product admission."""

    generation_store.verify(generation)
    return OnlyResearchRunAdmissionService(
        resolver=default_resolver,
        dataset_store=dataset_store,
        run_store=run_store,
        now_utc=now_utc,
        run_id_factory=run_id_factory,
        authoring_generation_resolver=OnlyAuthoringExecutionGenerationRegistry((generation,)),
    )


__all__ = ["only_compose_authoring_research_admission"]
