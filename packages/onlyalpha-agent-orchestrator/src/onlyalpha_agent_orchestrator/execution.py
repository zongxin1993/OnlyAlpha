"""Dual-capability external occurrence execution and immediate Result closure."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from onlyalpha.research.agent.occurrence import (
    OnlyAgentModelCallResultV1,
    OnlyAgentToolCallResultV1,
)
from onlyalpha.research.agent.occurrence_service import (
    OnlyAgentModelOccurrenceServiceV1,
    OnlyAgentToolOccurrenceServiceV1,
    OnlyPreparedAgentModelCallV1,
    OnlyPreparedAgentToolCallV1,
)

from .adapters.openai_compatible import (
    OnlyModelAdapterOutcomeKind,
    OnlyOpenAICompatibleModelAdapterV1,
)
from .adapters.product_api import OnlyContractDrivenProductApiAdapterV1, OnlyProductResponseEffect
from .adapters.transport import OnlyHttpDispatchClassification
from .runtime import (
    OnlyAgentRuntimeExecutionPermit,
    _mint_external_io_permit,
    assert_runtime_execution_permit_for_session,
)


class OnlyToolExternalExecutionDisposition(StrEnum):
    TERMINAL_RESULT = "TERMINAL_RESULT"
    AMBIGUOUS_NON_TERMINAL = "AMBIGUOUS_NON_TERMINAL"


@dataclass(frozen=True, slots=True)
class OnlyToolExternalExecutionOutcomeV1:
    disposition: OnlyToolExternalExecutionDisposition
    result: OnlyAgentToolCallResultV1 | None

    def __post_init__(self) -> None:
        if (self.disposition is OnlyToolExternalExecutionDisposition.TERMINAL_RESULT) != (self.result is not None):
            raise ValueError("AGENT_TOOL_EXECUTION_OUTCOME_INVALID")


def execute_external_model_occurrence(
    *,
    permit: OnlyAgentRuntimeExecutionPermit,
    prepared: OnlyPreparedAgentModelCallV1,
    occurrences: OnlyAgentModelOccurrenceServiceV1,
    adapter: OnlyOpenAICompatibleModelAdapterV1,
) -> OnlyAgentModelCallResultV1:
    def preflight(plan):  # type: ignore[no-untyped-def]
        assert_runtime_execution_permit_for_session(
            permit,
            agent_session_fingerprint=plan.agent_session_fingerprint,
        )

    def invoke(plan):  # type: ignore[no-untyped-def]
        io_permit = _mint_external_io_permit(
            permit,
            agent_session_fingerprint=plan.agent_session_fingerprint,
        )
        return adapter.invoke(plan, io_permit)

    try:
        outcome = occurrences.execute_prepared_model_call(prepared, invoke, preflight=preflight)
    except ValueError:
        return occurrences.record_failed(prepared)
    if outcome.kind is OnlyModelAdapterOutcomeKind.RETURNED:
        return occurrences.record_returned(prepared, cast(bytes, outcome.structured_response))
    if outcome.kind is OnlyModelAdapterOutcomeKind.RESPONSE_INVALID:
        return occurrences.record_returned(prepared, b"")
    if outcome.kind is OnlyModelAdapterOutcomeKind.OUTCOME_UNKNOWN:
        return occurrences.record_outcome_unknown(prepared)
    return occurrences.record_failed(prepared)


def execute_external_tool_occurrence(
    *,
    permit: OnlyAgentRuntimeExecutionPermit,
    prepared: OnlyPreparedAgentToolCallV1,
    occurrences: OnlyAgentToolOccurrenceServiceV1,
    adapter: OnlyContractDrivenProductApiAdapterV1,
) -> OnlyToolExternalExecutionOutcomeV1:
    def preflight(plan):  # type: ignore[no-untyped-def]
        assert_runtime_execution_permit_for_session(
            permit,
            agent_session_fingerprint=plan.agent_session_fingerprint,
        )

    def invoke(plan):  # type: ignore[no-untyped-def]
        io_permit = _mint_external_io_permit(
            permit,
            agent_session_fingerprint=plan.agent_session_fingerprint,
        )
        return adapter.invoke(plan, io_permit)

    try:
        transport = occurrences.execute_prepared_tool_call(prepared, invoke, preflight=preflight)
    except ValueError:
        return OnlyToolExternalExecutionOutcomeV1(
            OnlyToolExternalExecutionDisposition.TERMINAL_RESULT,
            occurrences.record_invalid(prepared),
        )
    if transport.classification is OnlyHttpDispatchClassification.POSSIBLY_DISPATCHED_RESPONSE_UNAVAILABLE:
        return OnlyToolExternalExecutionOutcomeV1(
            OnlyToolExternalExecutionDisposition.AMBIGUOUS_NON_TERMINAL,
            None,
        )
    if transport.classification is OnlyHttpDispatchClassification.DEFINITE_NOT_DISPATCHED:
        return OnlyToolExternalExecutionOutcomeV1(
            OnlyToolExternalExecutionDisposition.TERMINAL_RESULT,
            occurrences.record_failed(prepared),
        )
    assert transport.response is not None
    effect = adapter.contract.response_effect_verified(prepared.plan, transport.response.status_code)
    if effect is OnlyProductResponseEffect.EFFECT_UNKNOWN:
        return OnlyToolExternalExecutionOutcomeV1(
            OnlyToolExternalExecutionDisposition.AMBIGUOUS_NON_TERMINAL,
            None,
        )
    if effect is OnlyProductResponseEffect.DEFINITIVE_PRE_ADMISSION_REJECTION:
        return OnlyToolExternalExecutionOutcomeV1(
            OnlyToolExternalExecutionDisposition.TERMINAL_RESULT,
            occurrences.record_failed(prepared),
        )
    try:
        decoded = json.loads(transport.response.body)
        if not isinstance(decoded, dict):
            raise ValueError("Product response root")
        adapter.contract.verify_command_response_header(prepared.plan, transport)
        owners = adapter.contract.owning_references_verified(prepared.plan, decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        result = occurrences.record_invalid(prepared)
    else:
        result = occurrences.record_inline_success(prepared, decoded, owners)
    return OnlyToolExternalExecutionOutcomeV1(OnlyToolExternalExecutionDisposition.TERMINAL_RESULT, result)


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("execute_")]
