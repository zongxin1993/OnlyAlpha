from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from onlyalpha_agent_orchestrator import runtime
from onlyalpha_agent_orchestrator.adapters.transport import (
    OnlyHttpDispatchClassification,
    OnlyHttpResponseV1,
    OnlyHttpTransportOutcomeV1,
)
from onlyalpha_agent_orchestrator.execution import (
    OnlyToolExternalExecutionDisposition,
    execute_external_tool_occurrence,
)

from onlyalpha.research.agent import (
    OnlyAgentContextError,
    OnlyAgentToolCallOutcome,
    OnlyAgentToolClass,
)
from onlyalpha.research.agent.occurrence_service import OnlyPreparedAgentToolCallV1

from .test_occurrence_foundation import COMMAND_ID, CONTRACT, _prepare_tool, _services


class _Contract:
    def __init__(self, owner) -> None:  # type: ignore[no-untyped-def]
        self.owner = owner

    def verify_command_response_header(self, _plan, _outcome) -> None:  # type: ignore[no-untyped-def]
        return None

    def owning_references_verified(self, _plan, _response):  # type: ignore[no-untyped-def]
        return (self.owner,)


class _Adapter:
    def __init__(self, outcome: OnlyHttpTransportOutcomeV1, owner) -> None:  # type: ignore[no-untyped-def]
        self.outcome = outcome
        self.contract = _Contract(owner)
        self.request_count = 0
        self.command_ids: list[str | None] = []

    def invoke(self, plan, _permit):  # type: ignore[no-untyped-def]
        self.request_count += 1
        self.command_ids.append(plan.product_command_id_or_idempotency_key)
        return self.outcome


def _permit(monkeypatch: pytest.MonkeyPatch, tool, context):  # type: ignore[no-untyped-def]
    manifest = context.resources[-1].canonical_payload
    monkeypatch.setattr(runtime, "build_current_agent_workflow_implementation_manifest", lambda: manifest)
    return runtime.execute_after_runtime_admission(
        context.session.session_fingerprint,
        tool._sessions,  # noqa: SLF001
        lambda permit: permit,
    )


def _complete(body: dict[str, object]) -> OnlyHttpTransportOutcomeV1:
    return OnlyHttpTransportOutcomeV1(
        OnlyHttpDispatchClassification.COMPLETE_RESPONSE_RECEIVED,
        OnlyHttpResponseV1(200, (), json.dumps(body).encode()),
    )


def test_tool_success_uses_existing_durable_result_and_every_invalid_gate_is_zero_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _model, tool, _model_store, _tool_store, _identity, owner, *_ = _services(tmp_path / "one")
    prepared = _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 0)
    adapter = _Adapter(_complete({"request_id": "a" * 64, "result": "canonical"}), owner)
    permit = _permit(monkeypatch, tool, context)

    with pytest.raises(OnlyAgentContextError):
        execute_external_tool_occurrence(
            permit=cast(runtime.OnlyAgentRuntimeExecutionPermit, object()),
            prepared=prepared,
            occurrences=tool,
            adapter=adapter,  # type: ignore[arg-type]
        )
    with pytest.raises(OnlyAgentContextError):
        execute_external_tool_occurrence(
            permit=permit,
            prepared=cast(OnlyPreparedAgentToolCallV1, object()),
            occurrences=tool,
            adapter=adapter,  # type: ignore[arg-type]
        )
    other_context, _other_model, other_tool, *_ = _services(tmp_path / "two")
    wrong = _prepare_tool(other_tool, other_context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 0)
    with pytest.raises(OnlyAgentContextError):
        execute_external_tool_occurrence(
            permit=_permit(monkeypatch, other_tool, other_context),
            prepared=wrong,
            occurrences=tool,
            adapter=adapter,  # type: ignore[arg-type]
        )
    assert adapter.request_count == 0

    outcome = execute_external_tool_occurrence(
        permit=permit,
        prepared=prepared,
        occurrences=tool,
        adapter=adapter,  # type: ignore[arg-type]
    )
    assert outcome.disposition is OnlyToolExternalExecutionDisposition.TERMINAL_RESULT
    assert outcome.result is not None and outcome.result.outcome is OnlyAgentToolCallOutcome.SUCCEEDED
    assert tool.load_result_verified(prepared.plan.tool_call_plan_fingerprint) == outcome.result
    with pytest.raises(OnlyAgentContextError):
        execute_external_tool_occurrence(
            permit=permit,
            prepared=prepared,
            occurrences=tool,
            adapter=adapter,  # type: ignore[arg-type]
        )
    assert adapter.request_count == 1


def test_tool_ambiguity_recovery_classes_are_enforced_before_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiguous = OnlyHttpTransportOutcomeV1(OnlyHttpDispatchClassification.POSSIBLY_DISPATCHED_RESPONSE_UNAVAILABLE)
    context, _model, tool, _model_store, _tool_store, _identity, owner, *_ = _services(tmp_path)
    permit = _permit(monkeypatch, tool, context)

    exact = _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 0)
    adapter = _Adapter(ambiguous, owner)
    first = execute_external_tool_occurrence(
        permit=permit,
        prepared=exact,
        occurrences=tool,
        adapter=adapter,  # type: ignore[arg-type]
    )
    assert first.disposition is OnlyToolExternalExecutionDisposition.AMBIGUOUS_NON_TERMINAL
    with pytest.raises(OnlyAgentContextError):
        execute_external_tool_occurrence(
            permit=permit,
            prepared=exact,
            occurrences=tool,
            adapter=adapter,  # type: ignore[arg-type]
        )
    recovered = tool.prepare_recovery(
        exact.plan.tool_call_plan_fingerprint,
        current_workflow_manifest=context.resources[-1].canonical_payload,  # type: ignore[arg-type]
    )
    adapter.outcome = _complete({"request_id": "a" * 64, "result": "canonical"})
    assert (
        execute_external_tool_occurrence(
            permit=permit,
            prepared=recovered,
            occurrences=tool,
            adapter=adapter,  # type: ignore[arg-type]
        ).result.outcome
        is OnlyAgentToolCallOutcome.SUCCEEDED
    )

    mutable = _prepare_tool(tool, context, OnlyAgentToolClass.RESEARCH_RUN_QUERY, 1)
    adapter.outcome = ambiguous
    execute_external_tool_occurrence(
        permit=permit,
        prepared=mutable,
        occurrences=tool,
        adapter=adapter,  # type: ignore[arg-type]
    )
    with pytest.raises(OnlyAgentContextError, match="AGENT_TOOL_MUTABLE_OBSERVATION_REQUIRES_NEW_PLAN"):
        tool.prepare_recovery(
            mutable.plan.tool_call_plan_fingerprint,
            current_workflow_manifest=context.resources[-1].canonical_payload,  # type: ignore[arg-type]
        )
    later = _prepare_tool(tool, context, OnlyAgentToolClass.RESEARCH_RUN_QUERY, 2)
    assert later.plan.tool_call_plan_fingerprint != mutable.plan.tool_call_plan_fingerprint


def test_idempotent_recovery_reuses_plan_and_product_command_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _model, tool, _model_store, _tool_store, _identity, owner, *_ = _services(tmp_path)
    permit = _permit(monkeypatch, tool, context)
    prepared = _prepare_tool(tool, context, OnlyAgentToolClass.RESEARCH_RUN_SUBMIT, 0, command=COMMAND_ID)
    adapter = _Adapter(
        OnlyHttpTransportOutcomeV1(OnlyHttpDispatchClassification.POSSIBLY_DISPATCHED_RESPONSE_UNAVAILABLE),
        owner,
    )
    execute_external_tool_occurrence(
        permit=permit,
        prepared=prepared,
        occurrences=tool,
        adapter=adapter,  # type: ignore[arg-type]
    )
    recovered = tool.prepare_recovery(
        prepared.plan.tool_call_plan_fingerprint,
        current_workflow_manifest=context.resources[-1].canonical_payload,  # type: ignore[arg-type]
    )
    adapter.outcome = OnlyHttpTransportOutcomeV1(OnlyHttpDispatchClassification.DEFINITE_NOT_DISPATCHED)
    execute_external_tool_occurrence(
        permit=permit,
        prepared=recovered,
        occurrences=tool,
        adapter=adapter,  # type: ignore[arg-type]
    )
    assert recovered.plan == prepared.plan
    assert adapter.command_ids == [COMMAND_ID, COMMAND_ID]


@pytest.mark.parametrize(
    "change",
    [
        {"product_api_contract_fingerprint": "1" * 64},
        {"operation_identity": "missing.operation"},
    ],
)
def test_contract_or_operation_mismatch_is_rejected_before_adapter_io(
    tmp_path: Path,
    change: dict[str, object],
) -> None:
    context, _model, tool, _model_store, _tool_store, *_ = _services(tmp_path)
    adapter = _Adapter(OnlyHttpTransportOutcomeV1(OnlyHttpDispatchClassification.DEFINITE_NOT_DISPATCHED), None)
    with pytest.raises(OnlyAgentContextError):
        tool.prepare_tool_call(
            session_fingerprint=context.session.session_fingerprint,
            current_workflow_manifest=context.resources[-1].canonical_payload,  # type: ignore[arg-type]
            tool_call_ordinal=0,
            authorizing_agent_decision_fingerprint="e" * 64,
            tool_class=OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
            product_api_major=2,
            product_api_contract_fingerprint=cast(str, change.get("product_api_contract_fingerprint", CONTRACT)),
            operation_identity=cast(str, change.get("operation_identity", "exact_catalog_context_query.v1")),
            canonical_request={"id": "a" * 64},
            exact_identity_inputs=(),
            product_command_id_or_idempotency_key=None,
        )
    assert adapter.request_count == 0
