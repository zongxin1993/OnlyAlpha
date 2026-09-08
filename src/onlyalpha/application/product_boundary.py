"""Canonical Product Command/Query composition over existing authorities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from onlyalpha.application.catalog_context import (
    OnlyExactCatalogContextQueryService,
    OnlyExactCatalogContextV1,
)
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.kernel.command import (
    OnlyProductCommand,
    OnlyProductCommandBinding,
    OnlyProductCommandDispatcher,
    OnlyProductMutationAdmission,
)
from onlyalpha.kernel.query import OnlyProductQuery, OnlyProductQueryBinding, OnlyProductQueryDispatcher
from onlyalpha.research.command.model import (
    OnlyResearchRunPage,
    OnlyResearchSubmissionKey,
    OnlyResearchSubmitOutcome,
)
from onlyalpha.research.command.query import DEFAULT_RESEARCH_RUN_PAGE_SIZE, OnlyResearchRunQueryService
from onlyalpha.research.command.service import OnlyResearchCommandService
from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunId
from onlyalpha.research.specification.model import OnlyResearchSpecification


@dataclass(frozen=True, slots=True)
class OnlyCreateResearchRun(OnlyProductCommand):
    submission_key: OnlyResearchSubmissionKey
    specification: OnlyResearchSpecification
    authoring_provenance: OnlyResearchAuthoringProvenance | None = None


@dataclass(frozen=True, slots=True)
class OnlyCancelResearchRun(OnlyProductCommand):
    run_id: OnlyResearchRunId
    command_id: OnlyProductCommandId | None = None


@dataclass(frozen=True, slots=True)
class OnlyGetResearchRun(OnlyProductQuery):
    run_id: OnlyResearchRunId


@dataclass(frozen=True, slots=True)
class OnlyListResearchRuns(OnlyProductQuery):
    limit: int = DEFAULT_RESEARCH_RUN_PAGE_SIZE
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyGetExactCatalogContext(OnlyProductQuery):
    catalog_generation_fingerprint: str


@dataclass(frozen=True, slots=True)
class OnlyResearchProductBoundary:
    commands: OnlyProductCommandDispatcher
    queries: OnlyProductQueryDispatcher


def only_compose_research_product_boundary(
    *,
    admission: OnlyProductMutationAdmission,
    commands: OnlyResearchCommandService,
    queries: OnlyResearchRunQueryService,
    exact_catalog_context: OnlyExactCatalogContextQueryService | None = None,
) -> OnlyResearchProductBoundary:
    """Freeze the one legal Research Product binding topology."""

    def create(command: OnlyCreateResearchRun) -> OnlyResearchSubmitOutcome:
        return commands.submit_research_run(
            command.submission_key,
            command.specification,
            command.authoring_provenance,
        )

    def cancel(command: OnlyCancelResearchRun) -> OnlyResearchRun:
        return commands.request_research_run_cancellation(command.run_id, command.command_id)

    def get(query: OnlyGetResearchRun) -> OnlyResearchRun:
        return queries.get_run(query.run_id)

    def list_runs(query: OnlyListResearchRuns) -> OnlyResearchRunPage:
        return queries.list_runs(limit=query.limit, cursor=query.cursor)

    def get_exact_catalog_context(query: OnlyGetExactCatalogContext) -> OnlyExactCatalogContextV1:
        if exact_catalog_context is None:  # excluded from bindings below
            raise RuntimeError("EXACT_CATALOG_CONTEXT_UNAVAILABLE")
        return exact_catalog_context.get_exact_catalog_context(query.catalog_generation_fingerprint)

    query_bindings: tuple[OnlyProductQueryBinding[Any, Any], ...] = (
        OnlyProductQueryBinding(OnlyGetResearchRun, get),
        OnlyProductQueryBinding(OnlyListResearchRuns, list_runs),
    )
    if exact_catalog_context is not None:
        query_bindings += (OnlyProductQueryBinding(OnlyGetExactCatalogContext, get_exact_catalog_context),)

    return OnlyResearchProductBoundary(
        commands=OnlyProductCommandDispatcher(
            admission,
            (
                OnlyProductCommandBinding(OnlyCreateResearchRun, create),
                OnlyProductCommandBinding(OnlyCancelResearchRun, cancel),
            ),
        ),
        queries=OnlyProductQueryDispatcher(query_bindings),
    )


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
