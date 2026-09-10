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
    from onlyalpha.research.run import OnlyResearchRun

from .occurrence import OnlyAgentContextReferenceV1


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
    def load_research_run_verified(self, run_reference: OnlyAgentContextReferenceV1) -> OnlyResearchRun: ...


__all__ = [name for name in globals() if name.startswith("OnlyAgent")]
