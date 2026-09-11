from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import MappingProxyType
from typing import cast

import pytest
from onlyalpha_agent_orchestrator import runtime
from onlyalpha_agent_orchestrator.adapters.transport import (
    OnlyHttpDispatchClassification,
    OnlyHttpRequestV1,
    OnlyHttpResponseV1,
    OnlyHttpTransportOutcomeV1,
    OnlyRawHttpTransportV1,
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

    def response_effect_verified(self, _plan, status_code):  # type: ignore[no-untyped-def]
        from onlyalpha_agent_orchestrator.adapters.product_api import OnlyProductResponseEffect

        if 200 <= status_code < 300:
            return OnlyProductResponseEffect.COMMITTED_RESPONSE
        if status_code in {500, 502, 503, 504}:
            return OnlyProductResponseEffect.EFFECT_UNKNOWN
        return OnlyProductResponseEffect.DEFINITIVE_PRE_ADMISSION_REJECTION


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
        OnlyHttpDispatchClassification.RESPONSE_RECEIVED,
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


@pytest.mark.parametrize("status", [500, 503])
def test_post_dispatch_product_command_server_failure_remains_unresolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    context, _model, tool, _model_store, _tool_store, _identity, owner, *_ = _services(tmp_path)
    permit = _permit(monkeypatch, tool, context)
    prepared = _prepare_tool(tool, context, OnlyAgentToolClass.RESEARCH_RUN_SUBMIT, 0, command=COMMAND_ID)
    adapter = _Adapter(
        OnlyHttpTransportOutcomeV1(
            OnlyHttpDispatchClassification.RESPONSE_RECEIVED,
            OnlyHttpResponseV1(status, (), b"{}"),
        ),
        owner,
    )

    outcome = execute_external_tool_occurrence(
        permit=permit,
        prepared=prepared,
        occurrences=tool,
        adapter=adapter,  # type: ignore[arg-type]
    )

    assert outcome.disposition is OnlyToolExternalExecutionDisposition.AMBIGUOUS_NON_TERMINAL
    assert outcome.result is None
    assert (
        tool.prepare_recovery(
            prepared.plan.tool_call_plan_fingerprint,
            current_workflow_manifest=context.resources[-1].canonical_payload,  # type: ignore[arg-type]
        ).plan
        == prepared.plan
    )


def test_commit_then_503_recovery_has_one_effect_identity_plan_and_terminal_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, object] = {"requests": 0, "effects": set(), "commands": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            command = self.headers.get("Idempotency-Key")
            cast(list[str | None], state["commands"]).append(command)
            cast(set[str | None], state["effects"]).add(command)
            state["requests"] = cast(int, state["requests"]) + 1
            status = 503 if state["requests"] == 1 else 200
            body = json.dumps({"request_id": "a" * 64, "result": "canonical"}).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        context, _model, tool, _model_store, tool_store, _identity, owner, *_ = _services(tmp_path)
        prepared = _prepare_tool(tool, context, OnlyAgentToolClass.RESEARCH_RUN_SUBMIT, 0, command=COMMAND_ID)

        class HttpAdapter:
            contract = _Contract(owner)
            transport = OnlyRawHttpTransportV1(
                connect_timeout_seconds=1, read_timeout_seconds=1, verify_tls=True, ca_bundle_path=None
            )

            def invoke(self, plan, permit):  # type: ignore[no-untyped-def]
                host, port = server.server_address
                return self.transport.send(
                    OnlyHttpRequestV1(
                        "POST",
                        f"http://{host}:{port}/command",
                        MappingProxyType({"Idempotency-Key": cast(str, plan.product_command_id_or_idempotency_key)}),
                        b"{}",
                    ),
                    permit,
                )

        adapter = HttpAdapter()
        first = execute_external_tool_occurrence(
            permit=_permit(monkeypatch, tool, context),
            prepared=prepared,
            occurrences=tool,
            adapter=adapter,  # type: ignore[arg-type]
        )
        assert first.disposition is OnlyToolExternalExecutionDisposition.AMBIGUOUS_NON_TERMINAL
        recovered = tool.prepare_recovery(
            prepared.plan.tool_call_plan_fingerprint,
            current_workflow_manifest=context.resources[-1].canonical_payload,  # type: ignore[arg-type]
        )
        final = execute_external_tool_occurrence(
            permit=_permit(monkeypatch, tool, context),
            prepared=recovered,
            occurrences=tool,
            adapter=adapter,  # type: ignore[arg-type]
        )
        assert state["effects"] == {COMMAND_ID}
        assert set(cast(list[str], state["commands"])) == {COMMAND_ID}
        assert recovered.plan.tool_call_plan_fingerprint == prepared.plan.tool_call_plan_fingerprint
        assert final.result is not None and final.result.outcome is OnlyAgentToolCallOutcome.SUCCEEDED
        assert tool_store.load_result_for_plan_verified(prepared.plan.tool_call_plan_fingerprint) == final.result
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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
