"""Pure projections of Agent Session state and its one legal continuation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Never, cast

from .application import (
    OnlyAgentDecisionApplicationServiceV1,
    OnlyAgentExperimentLaunchServiceV1,
    OnlyAgentModelOccurrenceReaderV1,
    OnlyAgentToolOccurrenceReaderV1,
)
from .decision import (
    OnlyAgentDecisionKind,
    OnlyAgentRouterAction,
    OnlyAgentSearchDirectiveV1,
)
from .decision_store import OnlyJsonAgentDecisionStore
from .errors import OnlyAgentContextError
from .model import OnlyAgentToolClass
from .occurrence import OnlyAgentModelCallOutcome, OnlyAgentToolCallOutcome
from .occurrence_service import OnlyAgentSessionContextReader


class OnlyAgentDerivedSessionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    CAPABILITY_GAP = "CAPABILITY_GAP"
    FAILED = "FAILED"


class OnlyAgentNextActionKind(StrEnum):
    PREPARE_MODEL_CALL = "PREPARE_MODEL_CALL"
    DERIVE_DECISION = "DERIVE_DECISION"
    PREPARE_TOOL_CALL = "PREPARE_TOOL_CALL"
    RECOVER_MODEL_OUTCOME_UNKNOWN = "RECOVER_MODEL_OUTCOME_UNKNOWN"
    RECOVER_TOOL_OCCURRENCE = "RECOVER_TOOL_OCCURRENCE"
    RECONSTRUCT_LAUNCH_RECORD = "RECONSTRUCT_LAUNCH_RECORD"
    TERMINAL_COMPLETE = "TERMINAL_COMPLETE"
    TERMINAL_CAPABILITY_GAP = "TERMINAL_CAPABILITY_GAP"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"


@dataclass(frozen=True, slots=True)
class OnlyAgentNextActionV1:
    action_kind: OnlyAgentNextActionKind
    logical_role: str | None = None
    decision_kind: OnlyAgentDecisionKind | None = None
    tool_class: OnlyAgentToolClass | None = None
    occurrence_fingerprint: str | None = None
    failure_code: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.action_kind, OnlyAgentNextActionKind):
            raise ValueError("AGENT_NEXT_ACTION_INVALID")
        fields = (
            self.logical_role,
            self.decision_kind,
            self.tool_class,
            self.occurrence_fingerprint,
            self.failure_code,
        )
        expected = {
            OnlyAgentNextActionKind.PREPARE_MODEL_CALL: (True, False, False, False, False),
            OnlyAgentNextActionKind.DERIVE_DECISION: (False, True, False, False, False),
            OnlyAgentNextActionKind.PREPARE_TOOL_CALL: (False, False, True, False, False),
            OnlyAgentNextActionKind.RECOVER_MODEL_OUTCOME_UNKNOWN: (False, False, False, True, False),
            OnlyAgentNextActionKind.RECOVER_TOOL_OCCURRENCE: (False, False, False, True, False),
            OnlyAgentNextActionKind.RECONSTRUCT_LAUNCH_RECORD: (False, False, False, True, False),
            OnlyAgentNextActionKind.TERMINAL_COMPLETE: (False, False, False, False, False),
            OnlyAgentNextActionKind.TERMINAL_CAPABILITY_GAP: (False, False, False, False, False),
            OnlyAgentNextActionKind.TERMINAL_FAILURE: (False, False, False, False, True),
        }[self.action_kind]
        if tuple(item is not None for item in fields) != expected:
            raise ValueError("AGENT_NEXT_ACTION_INVALID")
        if self.logical_role is not None and (
            not self.logical_role or any(item.isspace() for item in self.logical_role)
        ):
            raise ValueError("AGENT_NEXT_ACTION_INVALID")
        if self.occurrence_fingerprint is not None and (
            len(self.occurrence_fingerprint) != 64
            or any(item not in "0123456789abcdef" for item in self.occurrence_fingerprint)
        ):
            raise ValueError("AGENT_NEXT_ACTION_INVALID")
        if self.failure_code is not None and not self.failure_code:
            raise ValueError("AGENT_NEXT_ACTION_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyAgentDerivedSessionStateV1:
    agent_session_fingerprint: str
    status: OnlyAgentDerivedSessionStatus
    next_action: OnlyAgentNextActionV1 | None
    failure_code: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.status, OnlyAgentDerivedSessionStatus):
            raise ValueError("AGENT_DERIVED_SESSION_STATE_INVALID")
        if len(self.agent_session_fingerprint) != 64 or any(
            item not in "0123456789abcdef" for item in self.agent_session_fingerprint
        ):
            raise ValueError("AGENT_DERIVED_SESSION_STATE_INVALID")
        if (self.status is OnlyAgentDerivedSessionStatus.ACTIVE) != (self.next_action is not None):
            raise ValueError("AGENT_DERIVED_SESSION_STATE_INVALID")
        if (self.status is OnlyAgentDerivedSessionStatus.FAILED) != (self.failure_code is not None):
            raise ValueError("AGENT_DERIVED_SESSION_STATE_INVALID")
        if self.next_action is not None and self.next_action.action_kind in {
            OnlyAgentNextActionKind.TERMINAL_COMPLETE,
            OnlyAgentNextActionKind.TERMINAL_CAPABILITY_GAP,
            OnlyAgentNextActionKind.TERMINAL_FAILURE,
        }:
            raise ValueError("AGENT_DERIVED_SESSION_STATE_INVALID")


class OnlyAgentSessionReducerV1:
    """Reduce the verified immutable prefix; never persist a cursor or action."""

    def __init__(
        self,
        *,
        sessions: OnlyAgentSessionContextReader,
        models: OnlyAgentModelOccurrenceReaderV1,
        tools: OnlyAgentToolOccurrenceReaderV1,
        decision_service: OnlyAgentDecisionApplicationServiceV1,
        decision_store: OnlyJsonAgentDecisionStore,
        launch_service: OnlyAgentExperimentLaunchServiceV1,
    ) -> None:
        self._sessions = sessions
        self._models = models
        self._tools = tools
        self._decisions = decision_service
        self._decision_store = decision_store
        self._launches = launch_service

    def derive(self, session_fingerprint: str) -> OnlyAgentDerivedSessionStateV1:
        context = self._sessions.load_session_manifest_verified(session_fingerprint)
        model_count = self._models.budget_consumed(session_fingerprint)
        tool_count = self._tools.budget_consumed(session_fingerprint)
        budget = context.research_brief.agent_budget
        if model_count > budget.model_call_limit or tool_count > budget.tool_call_limit:
            self._corrupt("occurrence count exceeds Agent budget")
        decision_count = self._decision_store.contiguous_count(session_fingerprint)
        if decision_count > 3:
            self._corrupt("too many Decisions")

        model_results = []
        for ordinal in range(model_count):
            model_plan = self._models.load_plan_by_session_ordinal_verified(session_fingerprint, ordinal)
            if not self._models.result_exists(model_plan.model_call_plan_fingerprint):
                if ordinal != model_count - 1:
                    self._corrupt("Model occurrence gap")
                return self._active(
                    session_fingerprint,
                    OnlyAgentNextActionV1(
                        OnlyAgentNextActionKind.RECOVER_MODEL_OUTCOME_UNKNOWN,
                        occurrence_fingerprint=model_plan.model_call_plan_fingerprint,
                    ),
                )
            model_result = self._models.load_result_verified(model_plan.model_call_plan_fingerprint)
            model_results.append(model_result)
            if model_result.outcome is not OnlyAgentModelCallOutcome.RETURNED:
                allowed_tool_count = 0 if ordinal == 0 else 1 if ordinal <= 2 else tool_count
                if (
                    ordinal != model_count - 1
                    or decision_count > self._decision_count_before_model(ordinal)
                    or tool_count > allowed_tool_count
                ):
                    self._corrupt("continuation after terminal Model failure")
                return self._failed(session_fingerprint, cast(str, model_result.failure_code))

        tool_results = []
        for ordinal in range(tool_count):
            tool_plan = self._tools.load_plan_by_session_ordinal_verified(session_fingerprint, ordinal)
            if not self._tools.result_exists(tool_plan.tool_call_plan_fingerprint):
                if ordinal != tool_count - 1:
                    self._corrupt("Tool occurrence gap")
                return self._active(
                    session_fingerprint,
                    OnlyAgentNextActionV1(
                        OnlyAgentNextActionKind.RECOVER_TOOL_OCCURRENCE,
                        occurrence_fingerprint=tool_plan.tool_call_plan_fingerprint,
                    ),
                )
            tool_result = self._tools.load_result_verified(tool_plan.tool_call_plan_fingerprint)
            tool_results.append(tool_result)
            if tool_result.outcome is not OnlyAgentToolCallOutcome.SUCCEEDED:
                allowed_model_count = 1 if ordinal == 0 else 3
                allowed_decision_count = 1 if ordinal == 0 else 2
                if (
                    ordinal != tool_count - 1
                    or model_count > allowed_model_count
                    or decision_count > allowed_decision_count
                ):
                    self._corrupt("continuation after terminal Tool failure")
                return self._failed(session_fingerprint, cast(str, tool_result.failure_code))

        if decision_count == 0:
            if model_count == 0 and tool_count == 0:
                return self._prepare_model(
                    session_fingerprint, "RESEARCH_PLANNER", model_count, budget.model_call_limit
                )
            if model_count == 1 and tool_count == 0:
                return self._derive_decision(session_fingerprint, OnlyAgentDecisionKind.RESEARCH_PLAN)
            self._corrupt("facts precede Research Plan Decision")

        plan_decision = self._decisions.load_decision_by_session_ordinal_verified(session_fingerprint, 0)
        if plan_decision.decision_kind is not OnlyAgentDecisionKind.RESEARCH_PLAN or model_count < 1:
            self._corrupt("Research Plan prefix")
        if tool_count == 0:
            if model_count != 1:
                self._corrupt("future Model call before Catalog query")
            return self._prepare_tool(
                session_fingerprint,
                OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
                tool_count,
                budget.tool_call_limit,
            )
        catalog_plan = self._tools.load_plan_by_session_ordinal_verified(session_fingerprint, 0)
        if (
            catalog_plan.tool_class is not OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY
            or catalog_plan.authorizing_agent_decision_fingerprint != plan_decision.decision_fingerprint
        ):
            self._corrupt("Catalog query branch")

        if decision_count == 1:
            if tool_count != 1:
                self._corrupt("formal work before Search Directive")
            if model_count == 1:
                return self._prepare_model(session_fingerprint, "SEARCH_ROUTER", model_count, budget.model_call_limit)
            if model_count not in (2, 3):
                self._corrupt("Search Directive Model prefix")
            router = model_results[1]
            output = router.validated_structured_output
            if output is None or "router_action" not in output:
                self._corrupt("Router output unavailable")
            assert output is not None
            try:
                action = OnlyAgentRouterAction(str(output["router_action"]))
            except Exception as exc:
                raise OnlyAgentContextError("AGENT_HISTORY_CONTRADICTORY", "Router action") from exc
            if action is OnlyAgentRouterAction.CAPABILITY_GAP:
                if model_count != 2:
                    self._corrupt("Factor Designer after Capability Gap")
                return self._derive_decision(session_fingerprint, OnlyAgentDecisionKind.SEARCH_DIRECTIVE)
            if model_count == 2:
                return self._prepare_model(session_fingerprint, "FACTOR_DESIGNER", model_count, budget.model_call_limit)
            return self._derive_decision(session_fingerprint, OnlyAgentDecisionKind.SEARCH_DIRECTIVE)

        directive_decision = self._decisions.load_decision_by_session_ordinal_verified(session_fingerprint, 1)
        directive = cast(OnlyAgentSearchDirectiveV1, directive_decision.structured_payload)
        launch_exists = self._launches.launch_exists(session_fingerprint)
        if launch_exists:
            try:
                self._launches.load_launch_record_by_session_verified(session_fingerprint)
            except Exception as exc:
                raise OnlyAgentContextError("AGENT_HISTORY_CONTRADICTORY", "invalid Launch") from exc
        if directive.router_action is OnlyAgentRouterAction.CAPABILITY_GAP:
            if launch_exists or tool_count != 1 or model_count != 2 or decision_count != 2:
                self._corrupt("Capability Gap contradiction")
            return OnlyAgentDerivedSessionStateV1(
                session_fingerprint, OnlyAgentDerivedSessionStatus.CAPABILITY_GAP, None
            )

        if model_count < 3:
            self._corrupt("missing Factor Designer result")
        expected_tools = self._branch_tools(directive.router_action)
        if tool_count > len(expected_tools):
            self._corrupt("extra branch Tool occurrence")
        for ordinal, expected_class in enumerate(expected_tools[:tool_count]):
            branch_plan = self._tools.load_plan_by_session_ordinal_verified(session_fingerprint, ordinal)
            expected_decision = plan_decision if ordinal == 0 else directive_decision
            if (
                branch_plan.tool_class is not expected_class
                or branch_plan.authorizing_agent_decision_fingerprint != expected_decision.decision_fingerprint
            ):
                self._corrupt("branch Tool mismatch")

        is_search = directive.router_action in {
            OnlyAgentRouterAction.SYMBOLIC_SEARCH,
            OnlyAgentRouterAction.PARAMETER_SEARCH,
        }
        if not is_search and launch_exists:
            self._corrupt("REUSE with Launch")
        if is_search and tool_count >= 2 and not launch_exists:
            submit_result = tool_results[1]
            return self._active(
                session_fingerprint,
                OnlyAgentNextActionV1(
                    OnlyAgentNextActionKind.RECONSTRUCT_LAUNCH_RECORD,
                    occurrence_fingerprint=submit_result.tool_call_result_fingerprint,
                ),
            )
        if is_search and tool_count < 2 and launch_exists:
            self._corrupt("Launch before Search submit Result")
        if tool_count < len(expected_tools):
            return self._prepare_tool(
                session_fingerprint,
                expected_tools[tool_count],
                tool_count,
                budget.tool_call_limit,
            )

        if model_count == 3:
            return self._prepare_model(session_fingerprint, "EVIDENCE_ANALYST", model_count, budget.model_call_limit)
        if model_count == 4 and decision_count == 2:
            return self._derive_decision(session_fingerprint, OnlyAgentDecisionKind.NEXT_EXPERIMENT_PROPOSAL)
        if decision_count == 3:
            final = self._decisions.load_decision_by_session_ordinal_verified(session_fingerprint, 2)
            if (
                final.decision_kind is not OnlyAgentDecisionKind.NEXT_EXPERIMENT_PROPOSAL
                or model_count != 4
                or (is_search and not launch_exists)
            ):
                self._corrupt("Next Proposal closure")
            return OnlyAgentDerivedSessionStateV1(session_fingerprint, OnlyAgentDerivedSessionStatus.COMPLETE, None)
        self._corrupt("ambiguous non-terminal prefix")

    @staticmethod
    def _decision_count_before_model(ordinal: int) -> int:
        return 0 if ordinal == 0 else 1 if ordinal <= 2 else 2

    @staticmethod
    def _branch_tools(action: OnlyAgentRouterAction) -> tuple[OnlyAgentToolClass, ...]:
        suffix = {
            OnlyAgentRouterAction.REUSE_EXISTING: (
                OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE,
                OnlyAgentToolClass.RESEARCH_RUN_SUBMIT,
                OnlyAgentToolClass.RESEARCH_RUN_QUERY,
                OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY,
            ),
            OnlyAgentRouterAction.SYMBOLIC_SEARCH: (
                OnlyAgentToolClass.SYMBOLIC_SEARCH,
                OnlyAgentToolClass.SEARCH_QUERY,
                OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY,
            ),
            OnlyAgentRouterAction.PARAMETER_SEARCH: (
                OnlyAgentToolClass.PARAMETER_SEARCH,
                OnlyAgentToolClass.SEARCH_QUERY,
                OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY,
            ),
        }.get(action)
        if suffix is None:
            raise OnlyAgentContextError("AGENT_HISTORY_CONTRADICTORY", action.value)
        return (OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, *suffix)

    @staticmethod
    def _active(session: str, action: OnlyAgentNextActionV1) -> OnlyAgentDerivedSessionStateV1:
        return OnlyAgentDerivedSessionStateV1(session, OnlyAgentDerivedSessionStatus.ACTIVE, action)

    def _prepare_model(self, session: str, role: str, consumed: int, limit: int) -> OnlyAgentDerivedSessionStateV1:
        if consumed >= limit:
            return self._failed(session, "AGENT_BUDGET_EXHAUSTED")
        return self._active(
            session,
            OnlyAgentNextActionV1(OnlyAgentNextActionKind.PREPARE_MODEL_CALL, logical_role=role),
        )

    def _prepare_tool(
        self, session: str, tool_class: OnlyAgentToolClass, consumed: int, limit: int
    ) -> OnlyAgentDerivedSessionStateV1:
        if consumed >= limit:
            return self._failed(session, "AGENT_BUDGET_EXHAUSTED")
        return self._active(
            session,
            OnlyAgentNextActionV1(OnlyAgentNextActionKind.PREPARE_TOOL_CALL, tool_class=tool_class),
        )

    def _derive_decision(self, session: str, kind: OnlyAgentDecisionKind) -> OnlyAgentDerivedSessionStateV1:
        return self._active(
            session,
            OnlyAgentNextActionV1(OnlyAgentNextActionKind.DERIVE_DECISION, decision_kind=kind),
        )

    @staticmethod
    def _failed(session: str, code: str) -> OnlyAgentDerivedSessionStateV1:
        return OnlyAgentDerivedSessionStateV1(session, OnlyAgentDerivedSessionStatus.FAILED, None, code)

    @staticmethod
    def _corrupt(detail: str) -> Never:
        raise OnlyAgentContextError("AGENT_HISTORY_CONTRADICTORY", detail)


__all__ = [name for name in globals() if name.startswith("OnlyAgent")]
