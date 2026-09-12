"""Fact-driven one-transition Agent Session driver."""

from __future__ import annotations

from onlyalpha.research.agent.errors import OnlyAgentContextError
from onlyalpha.research.agent.occurrence_service import (
    OnlyAgentModelOccurrenceServiceV1,
    OnlyAgentSessionContextReader,
    OnlyAgentToolOccurrenceServiceV1,
)
from onlyalpha.research.agent.session_state import (
    OnlyAgentDerivedSessionStateV1,
    OnlyAgentDerivedSessionStatus,
    OnlyAgentNextActionKind,
    OnlyAgentSessionReducerV1,
)

from .adapters.openai_compatible import OnlyOpenAICompatibleModelAdapterV1
from .adapters.product_api import OnlyContractDrivenProductApiAdapterV1
from .coordination import OnlyAgentSessionExecutionCoordinatorV1
from .execution import execute_external_model_occurrence, execute_external_tool_occurrence
from .materialization import OnlyAgentWorkflowActionMaterializerV1
from .runtime import (
    OnlyAgentRuntimeExecutionPermit,
    assert_runtime_execution_permit,
    build_current_agent_workflow_implementation_manifest,
    execute_after_runtime_admission,
)


class OnlyAgentSessionDriverV1:
    """Execute at most one Reducer-derived action and one external occurrence."""

    def __init__(
        self,
        *,
        reducer: OnlyAgentSessionReducerV1,
        sessions: OnlyAgentSessionContextReader,
        materializer: OnlyAgentWorkflowActionMaterializerV1,
        model_occurrences: OnlyAgentModelOccurrenceServiceV1,
        tool_occurrences: OnlyAgentToolOccurrenceServiceV1,
        model_adapter: OnlyOpenAICompatibleModelAdapterV1,
        product_adapter: OnlyContractDrivenProductApiAdapterV1,
        coordination: OnlyAgentSessionExecutionCoordinatorV1,
    ) -> None:
        self._reducer = reducer
        self._sessions = sessions
        self._materializer = materializer
        self._models = model_occurrences
        self._tools = tool_occurrences
        self._model_adapter = model_adapter
        self._product_adapter = product_adapter
        self._coordination = coordination

    def advance_once(self, session_fingerprint: str) -> OnlyAgentDerivedSessionStateV1:
        """Admit current runtime, then derive and execute exactly one legal action."""

        with self._coordination.acquire(session_fingerprint):

            def admitted_continuation(
                permit: OnlyAgentRuntimeExecutionPermit,
            ) -> OnlyAgentDerivedSessionStateV1:
                executable = self._reducer.derive(session_fingerprint)
                if executable.status is not OnlyAgentDerivedSessionStatus.ACTIVE:
                    return executable
                action = executable.next_action
                if action is None:  # guarded by the value object's invariant
                    raise OnlyAgentContextError("AGENT_HISTORY_CONTRADICTORY", "active state without action")
                manifest = build_current_agent_workflow_implementation_manifest()
                assert_runtime_execution_permit(
                    permit,
                    agent_session_fingerprint=session_fingerprint,
                    historical_workflow_resource_fingerprint=permit.historical_workflow_resource_fingerprint,
                    workflow_implementation_fingerprint=manifest.implementation_fingerprint,
                    source_revision=manifest.source_revision,
                )
                if action.action_kind is OnlyAgentNextActionKind.PREPARE_MODEL_CALL:
                    prepared_model = self._materializer.prepare_model_call(
                        session_fingerprint=session_fingerprint,
                        action=action,
                        current_workflow_manifest=manifest,
                    )
                    execute_external_model_occurrence(
                        permit=permit,
                        prepared=prepared_model,
                        occurrences=self._models,
                        adapter=self._model_adapter,
                    )
                elif action.action_kind is OnlyAgentNextActionKind.DERIVE_DECISION:
                    if action.decision_kind is None:
                        raise OnlyAgentContextError("AGENT_HISTORY_CONTRADICTORY", "Decision kind missing")
                    self._materializer.derive_decision(
                        session_fingerprint=session_fingerprint,
                        decision_kind=action.decision_kind,
                        current_workflow_manifest=manifest,
                    )
                elif action.action_kind in {
                    OnlyAgentNextActionKind.PREPARE_TOOL_CALL,
                    OnlyAgentNextActionKind.PREPARE_NEW_TOOL_OBSERVATION,
                    OnlyAgentNextActionKind.PREPARE_AUTHORITY_TOOL_CALL,
                }:
                    prepared_tool = self._materializer.prepare_tool_call(
                        session_fingerprint=session_fingerprint,
                        action=action,
                        current_workflow_manifest=manifest,
                    )
                    execute_external_tool_occurrence(
                        permit=permit,
                        prepared=prepared_tool,
                        occurrences=self._tools,
                        adapter=self._product_adapter,
                    )
                elif action.action_kind is OnlyAgentNextActionKind.RECOVER_MODEL_OUTCOME_UNKNOWN:
                    if action.occurrence_fingerprint is None:
                        raise OnlyAgentContextError("AGENT_HISTORY_CONTRADICTORY", "Model occurrence missing")
                    self._models.recover_outcome_unknown(
                        action.occurrence_fingerprint,
                        current_workflow_manifest=manifest,
                    )
                elif action.action_kind is OnlyAgentNextActionKind.RECOVER_TOOL_OCCURRENCE:
                    if action.occurrence_fingerprint is None:
                        raise OnlyAgentContextError("AGENT_HISTORY_CONTRADICTORY", "Tool occurrence missing")
                    prepared_recovery = self._tools.prepare_recovery(
                        action.occurrence_fingerprint,
                        current_workflow_manifest=manifest,
                    )
                    execute_external_tool_occurrence(
                        permit=permit,
                        prepared=prepared_recovery,
                        occurrences=self._tools,
                        adapter=self._product_adapter,
                    )
                elif action.action_kind is OnlyAgentNextActionKind.RECONSTRUCT_LAUNCH_RECORD:
                    if action.occurrence_fingerprint is None:
                        raise OnlyAgentContextError("AGENT_HISTORY_CONTRADICTORY", "Launch occurrence missing")
                    self._materializer.reconstruct_launch(
                        session_fingerprint=session_fingerprint,
                        tool_result_fingerprint=action.occurrence_fingerprint,
                        current_workflow_manifest=manifest,
                    )
                else:
                    raise OnlyAgentContextError("AGENT_HISTORY_CONTRADICTORY", "unsupported Reducer action")
                return self._reducer.derive(session_fingerprint)

            return execute_after_runtime_admission(
                session_fingerprint,
                self._sessions,
                admitted_continuation,
            )


__all__ = ["OnlyAgentSessionDriverV1"]
