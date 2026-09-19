"""Canonical Product Command/Query composition over existing authorities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from onlyalpha.application.catalog_context import (
    OnlyExactCatalogContextQueryService,
    OnlyExactCatalogContextV1,
)
from onlyalpha.application.private_strategy_research import OnlyPrivateStrategyResearchOutcome
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.research_advisory import (
    OnlyGetResearchNearDuplicateAdvisoryV1,
    OnlyResearchNearDuplicateAdvisoryBundleV2,
    OnlyResearchNearDuplicateQueryService,
)
from onlyalpha.application.search_product import (
    OnlyAdvanceSearchExperimentV1,
    OnlyGetSearchExperimentV1,
    OnlyGetSearchIterationLedgerV1,
    OnlyGetSearchTerminalDecisionV1,
    OnlySearchExperimentProjectionV1,
    OnlySearchIterationLedgerProjectionV1,
    OnlySearchProductCommandServiceV1,
    OnlySearchProductOutcomeV1,
    OnlySearchProductQueryServiceV1,
    OnlySearchTerminalProjectionV1,
    OnlySubmitParameterSearchExperimentV1,
    OnlySubmitParameterSearchExperimentV2,
    OnlySubmitSymbolicSearchExperimentV1,
    OnlySubmitSymbolicSearchExperimentV2,
)
from onlyalpha.kernel.command import (
    OnlyProductCommand,
    OnlyProductCommandBinding,
    OnlyProductCommandDispatcher,
    OnlyProductMutationAdmission,
)
from onlyalpha.kernel.query import OnlyProductQuery, OnlyProductQueryBinding, OnlyProductQueryDispatcher
from onlyalpha.quant_assets.private import OnlyPrivateAssetRevisionReferenceV1
from onlyalpha.quant_assets.private_strategy import OnlyPrivateStrategyResearchContextV1
from onlyalpha.research.command.model import (
    OnlyResearchRunPage,
    OnlyResearchSubmitOutcome,
)
from onlyalpha.research.command.query import DEFAULT_RESEARCH_RUN_PAGE_SIZE, OnlyResearchRunQueryService
from onlyalpha.research.command.service import OnlyResearchCommandService
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunId
from onlyalpha.research.specification.model import OnlyResearchSpecification


@dataclass(frozen=True, slots=True)
class OnlyCreateResearchRun(OnlyProductCommand):
    submission_key: OnlyProductCommandId
    specification: OnlyResearchSpecification
    authoring_generation_fingerprint: str | None = None

    def __post_init__(self) -> None:
        value = self.authoring_generation_fingerprint
        if value is not None and (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError("AUTHORING_EXECUTION_GENERATION_IDENTITY_INVALID")


@dataclass(frozen=True, slots=True)
class OnlySubmitPrivateStrategyResearch(OnlyProductCommand):
    submission_key: OnlyProductCommandId
    strategy_revision: OnlyPrivateAssetRevisionReferenceV1
    research_context: OnlyPrivateStrategyResearchContextV1
    authoring_generation_fingerprint: str

    def __post_init__(self) -> None:
        if len(self.authoring_generation_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in self.authoring_generation_fingerprint
        ):
            raise ValueError("AUTHORING_EXECUTION_GENERATION_IDENTITY_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyCancelResearchRun(OnlyProductCommand):
    run_id: OnlyResearchRunId
    command_id: OnlyProductCommandId | None = None


class _PrivateStrategyResearchSubmission(Protocol):
    def submit_reference(
        self,
        submission_key: OnlyProductCommandId,
        strategy_revision: OnlyPrivateAssetRevisionReferenceV1,
        research_context: OnlyPrivateStrategyResearchContextV1,
        authoring_generation_fingerprint: str,
    ) -> OnlyPrivateStrategyResearchOutcome: ...


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

    def submit_private_strategy_research(self, command: OnlySubmitPrivateStrategyResearch) -> OnlyResearchSubmitOutcome:
        return cast(OnlyResearchSubmitOutcome, self.commands.dispatch(command))


def only_compose_research_product_boundary(
    *,
    admission: OnlyProductMutationAdmission,
    commands: OnlyResearchCommandService,
    queries: OnlyResearchRunQueryService,
    exact_catalog_context: OnlyExactCatalogContextQueryService | None = None,
    search_commands: OnlySearchProductCommandServiceV1 | None = None,
    search_queries: OnlySearchProductQueryServiceV1 | None = None,
    near_duplicate_queries: OnlyResearchNearDuplicateQueryService | None = None,
    strategy_research: _PrivateStrategyResearchSubmission | None = None,
) -> OnlyResearchProductBoundary:
    """Freeze the one legal Research Product binding topology."""

    def create(command: OnlyCreateResearchRun) -> OnlyResearchSubmitOutcome:
        return commands.submit_research_run(
            command.submission_key,
            command.specification,
            command.authoring_generation_fingerprint,
        )

    def cancel(command: OnlyCancelResearchRun) -> OnlyResearchRun:
        return commands.request_research_run_cancellation(command.run_id, command.command_id)

    def submit_private_strategy(command: OnlySubmitPrivateStrategyResearch) -> OnlyResearchSubmitOutcome:
        if strategy_research is None:  # excluded from bindings below
            raise RuntimeError("PRIVATE_STRATEGY_RESEARCH_AUTHORITY_UNAVAILABLE")
        result = strategy_research.submit_reference(
            command.submission_key,
            command.strategy_revision,
            command.research_context,
            command.authoring_generation_fingerprint,
        )
        return result.submission

    def get(query: OnlyGetResearchRun) -> OnlyResearchRun:
        return queries.get_run(query.run_id)

    def list_runs(query: OnlyListResearchRuns) -> OnlyResearchRunPage:
        return queries.list_runs(limit=query.limit, cursor=query.cursor)

    def get_exact_catalog_context(query: OnlyGetExactCatalogContext) -> OnlyExactCatalogContextV1:
        if exact_catalog_context is None:  # excluded from bindings below
            raise RuntimeError("EXACT_CATALOG_CONTEXT_UNAVAILABLE")
        return exact_catalog_context.get_exact_catalog_context(query.catalog_generation_fingerprint)

    def submit_symbolic(
        command: OnlySubmitSymbolicSearchExperimentV1 | OnlySubmitSymbolicSearchExperimentV2,
    ) -> OnlySearchProductOutcomeV1:
        if search_commands is None:  # excluded from bindings below
            raise RuntimeError("SEARCH_PRODUCT_AUTHORITY_UNAVAILABLE")
        return search_commands.submit(command)

    def submit_parameter(
        command: OnlySubmitParameterSearchExperimentV1 | OnlySubmitParameterSearchExperimentV2,
    ) -> OnlySearchProductOutcomeV1:
        if search_commands is None:  # excluded from bindings below
            raise RuntimeError("SEARCH_PRODUCT_AUTHORITY_UNAVAILABLE")
        return search_commands.submit(command)

    def advance_search(command: OnlyAdvanceSearchExperimentV1) -> OnlySearchProductOutcomeV1:
        if search_commands is None:  # excluded from bindings below
            raise RuntimeError("SEARCH_PRODUCT_AUTHORITY_UNAVAILABLE")
        return search_commands.advance(command)

    def get_search_experiment(query: OnlyGetSearchExperimentV1) -> OnlySearchExperimentProjectionV1:
        if search_queries is None:  # excluded from bindings below
            raise RuntimeError("SEARCH_PRODUCT_AUTHORITY_UNAVAILABLE")
        return search_queries.get_experiment(query)

    def get_search_ledger(query: OnlyGetSearchIterationLedgerV1) -> OnlySearchIterationLedgerProjectionV1:
        if search_queries is None:  # excluded from bindings below
            raise RuntimeError("SEARCH_PRODUCT_AUTHORITY_UNAVAILABLE")
        return search_queries.get_ledger(query)

    def get_search_terminal(query: OnlyGetSearchTerminalDecisionV1) -> OnlySearchTerminalProjectionV1:
        if search_queries is None:  # excluded from bindings below
            raise RuntimeError("SEARCH_PRODUCT_AUTHORITY_UNAVAILABLE")
        return search_queries.get_terminal(query)

    def get_near_duplicates(
        query: OnlyGetResearchNearDuplicateAdvisoryV1,
    ) -> OnlyResearchNearDuplicateAdvisoryBundleV2:
        if near_duplicate_queries is None:  # excluded from bindings below
            raise RuntimeError("RESEARCH_ADVISORY_QUERY_UNAVAILABLE")
        return near_duplicate_queries.get(query)

    query_bindings: tuple[OnlyProductQueryBinding[Any, Any], ...] = (
        OnlyProductQueryBinding(OnlyGetResearchRun, get),
        OnlyProductQueryBinding(OnlyListResearchRuns, list_runs),
    )
    if exact_catalog_context is not None:
        query_bindings += (OnlyProductQueryBinding(OnlyGetExactCatalogContext, get_exact_catalog_context),)
    if search_queries is not None:
        query_bindings += (
            OnlyProductQueryBinding(OnlyGetSearchExperimentV1, get_search_experiment),
            OnlyProductQueryBinding(OnlyGetSearchIterationLedgerV1, get_search_ledger),
            OnlyProductQueryBinding(OnlyGetSearchTerminalDecisionV1, get_search_terminal),
        )
    if near_duplicate_queries is not None:
        query_bindings += (OnlyProductQueryBinding(OnlyGetResearchNearDuplicateAdvisoryV1, get_near_duplicates),)

    command_bindings: tuple[OnlyProductCommandBinding[Any, Any], ...] = (
        OnlyProductCommandBinding(OnlyCreateResearchRun, create),
        OnlyProductCommandBinding(OnlyCancelResearchRun, cancel),
    )
    if strategy_research is not None:
        command_bindings += (OnlyProductCommandBinding(OnlySubmitPrivateStrategyResearch, submit_private_strategy),)
    if search_commands is not None:
        command_bindings += (
            OnlyProductCommandBinding(OnlySubmitSymbolicSearchExperimentV1, submit_symbolic),
            OnlyProductCommandBinding(OnlySubmitSymbolicSearchExperimentV2, submit_symbolic),
            OnlyProductCommandBinding(OnlySubmitParameterSearchExperimentV1, submit_parameter),
            OnlyProductCommandBinding(OnlySubmitParameterSearchExperimentV2, submit_parameter),
            OnlyProductCommandBinding(OnlyAdvanceSearchExperimentV1, advance_search),
        )

    return OnlyResearchProductBoundary(
        commands=OnlyProductCommandDispatcher(
            admission,
            command_bindings,
        ),
        queries=OnlyProductQueryDispatcher(query_bindings),
    )


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
