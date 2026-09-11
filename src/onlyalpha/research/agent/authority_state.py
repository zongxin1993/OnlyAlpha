"""Transient views that compose owning Search and Research Authorities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from onlyalpha.application.search_product import (
        OnlySearchBoundedOperationV1,
        OnlySearchExpectedStateV1,
        OnlySearchTerminalProjectionV1,
    )
    from onlyalpha.research.command.query import OnlyResearchRunQueryService
    from onlyalpha.research.run import OnlyResearchRun

from .errors import OnlyAgentContextError
from .occurrence import (
    OnlyAgentExactAuthorityReference,
    OnlyAgentExactAuthorityReferenceV2,
    OnlyAgentReferenceLocatorKind,
)


@dataclass(frozen=True, slots=True)
class OnlyAgentSearchAuthorityViewV1:
    terminal: OnlySearchTerminalProjectionV1
    expected_state: OnlySearchExpectedStateV1
    next_bounded_operation: OnlySearchBoundedOperationV1 | None

    def __post_init__(self) -> None:
        if self.terminal.experiment_fingerprint != self.expected_state.experiment_fingerprint:
            raise ValueError("AGENT_SEARCH_FAILED")
        if self.terminal.terminal_kind.value == "NON_TERMINAL":
            if self.next_bounded_operation is None or self.next_bounded_operation.method is not self.terminal.method:
                raise ValueError("AGENT_SEARCH_FAILED")
        elif self.next_bounded_operation is not None:
            raise ValueError("AGENT_SEARCH_FAILED")


class OnlyAgentSearchStateReader(Protocol):
    def load_search_state_verified(self, experiment_fingerprint: str) -> OnlyAgentSearchAuthorityViewV1: ...


class OnlyAgentResearchStateReader(Protocol):
    def load_research_run_verified(self, run_reference: OnlyAgentExactAuthorityReference) -> OnlyResearchRun: ...


class OnlyAgentResearchRunAuthorityReaderV1:
    """Exact Agent read adapter over the canonical Research Run Query Authority."""

    def __init__(self, queries: OnlyResearchRunQueryService) -> None:
        self._queries = queries

    def load_research_run_verified(self, run_reference: OnlyAgentExactAuthorityReference) -> OnlyResearchRun:
        from onlyalpha.research.run import OnlyResearchRunId

        if (
            not isinstance(run_reference, OnlyAgentExactAuthorityReferenceV2)
            or run_reference.reference_kind != "RESEARCH_RUN"
            or run_reference.reference_schema_version != 1
            or run_reference.locator_kind is not OnlyAgentReferenceLocatorKind.UUID4
        ):
            raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", "RESEARCH_RUN")
        try:
            run_id = OnlyResearchRunId(run_reference.locator_value)
            run = self._queries.get_run(run_id)
        except Exception as exc:
            if isinstance(exc, OnlyAgentContextError):
                raise
            raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", "RESEARCH_RUN") from exc
        if run.run_id != run_id:
            raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", "RESEARCH_RUN")
        return run


__all__ = [name for name in globals() if name.startswith("OnlyAgent")]
