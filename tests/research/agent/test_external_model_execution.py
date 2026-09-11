from __future__ import annotations

import json
import socket
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

import pytest
from onlyalpha_agent_orchestrator import runtime
from onlyalpha_agent_orchestrator.adapters.openai_compatible import OnlyOpenAICompatibleModelAdapterV1
from onlyalpha_agent_orchestrator.adapters.transport import OnlyRawHttpTransportV1
from onlyalpha_agent_orchestrator.config import OnlyOpenAICompatibleEndpointConfigV1
from onlyalpha_agent_orchestrator.execution import execute_external_model_occurrence

from onlyalpha.research.agent import OnlyAgentContextError, OnlyAgentModelCallOutcome
from onlyalpha.research.agent.occurrence_service import OnlyPreparedAgentModelCallV1
from tests.research.agent.test_occurrence_foundation import _prepare_model, _services


@dataclass
class _ServerState:
    status: int = 200
    body: bytes = b""
    mode: str = "response"
    request_count: int = 0
    request: tuple[str, str, dict[str, str], bytes] | None = None


class _Server:
    def __init__(self, state: _ServerState) -> None:
        self.state = state
        self.release = threading.Event()

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                outer.state.request_count += 1
                outer.state.request = (self.command, self.path, dict(self.headers), body)
                if outer.state.mode == "close":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                if outer.state.mode == "block":
                    outer.release.wait(timeout=5)
                    return
                self.send_response(outer.state.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(outer.state.body)))
                self.end_headers()
                self.wfile.write(outer.state.body)

            def log_message(self, _format: str, *args: object) -> None:
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


class _Contexts:
    def load_model_context_projection_verified(self, _reference):  # type: ignore[no-untyped-def]
        return {"hypothesis": "deterministic alpha"}


def _response(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content, "refusal": None}}]}).encode()


def _adapter(model, server_url: str, *, secret: str = "test-secret", model_id: str = "model-a", read=1.0):  # type: ignore[no-untyped-def]
    config = OnlyOpenAICompatibleEndpointConfigV1(
        server_url,
        secret,
        "provider-a",
        model_id,
        "2026-09-01",
        connect_timeout_seconds=0.2,
        read_timeout_seconds=read,
    )
    return (
        config,
        OnlyOpenAICompatibleModelAdapterV1(
            config=config,
            resources=model._resources,  # noqa: SLF001
            contexts=_Contexts(),
            transport=OnlyRawHttpTransportV1(
                connect_timeout_seconds=config.connect_timeout_seconds,
                read_timeout_seconds=config.read_timeout_seconds,
                verify_tls=True,
                ca_bundle_path=None,
            ),
        ),
    )


def _permit(monkeypatch: pytest.MonkeyPatch, model, context):  # type: ignore[no-untyped-def]
    manifest = context.resources[-1].canonical_payload
    monkeypatch.setattr(runtime, "build_current_agent_workflow_implementation_manifest", lambda: manifest)
    return runtime.execute_after_runtime_admission(
        context.session.session_fingerprint,
        model._sessions,  # noqa: SLF001
        lambda permit: permit,
    )


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"action":"PLAN"}', OnlyAgentModelCallOutcome.RETURNED),
        ('{"action":"BAD"}', OnlyAgentModelCallOutcome.RESPONSE_INVALID),
        ("not-json", OnlyAgentModelCallOutcome.RESPONSE_INVALID),
    ],
)
def test_model_complete_response_closes_once_through_durable_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    expected: OnlyAgentModelCallOutcome,
) -> None:
    state = _ServerState(body=_response(content))
    server = _Server(state)
    try:
        context, model, _, _, _, reference, *_ = _services(tmp_path)
        prepared = _prepare_model(model, context, reference)
        _config, adapter = _adapter(model, server.url)
        result = execute_external_model_occurrence(
            permit=_permit(monkeypatch, model, context),
            prepared=prepared,
            occurrences=model,
            adapter=adapter,
        )
        assert result.outcome is expected
        assert model.load_result_verified(prepared.plan.model_call_plan_fingerprint) == result
        assert state.request_count == 1
        with pytest.raises(OnlyAgentContextError):
            execute_external_model_occurrence(
                permit=_permit(monkeypatch, model, context),
                prepared=prepared,
                occurrences=model,
                adapter=adapter,
            )
        assert state.request_count == 1
    finally:
        server.close()


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_ServerState(status=401, body=b"{}"), OnlyAgentModelCallOutcome.FAILED),
        (_ServerState(mode="close"), OnlyAgentModelCallOutcome.OUTCOME_UNKNOWN),
        (_ServerState(mode="block"), OnlyAgentModelCallOutcome.OUTCOME_UNKNOWN),
    ],
)
def test_model_transport_classification_has_no_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: _ServerState,
    expected: OnlyAgentModelCallOutcome,
) -> None:
    server = _Server(state)
    try:
        context, model, _, _, _, reference, *_ = _services(tmp_path)
        prepared = _prepare_model(model, context, reference)
        _config, adapter = _adapter(model, server.url, read=0.05)
        result = execute_external_model_occurrence(
            permit=_permit(monkeypatch, model, context),
            prepared=prepared,
            occurrences=model,
            adapter=adapter,
        )
        assert result.outcome is expected
        assert state.request_count == 1
    finally:
        server.close()


def test_connect_failure_is_definite_failed_without_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    host, port = listener.getsockname()
    listener.close()
    context, model, _, _, _, reference, *_ = _services(tmp_path)
    prepared = _prepare_model(model, context, reference)
    _config, adapter = _adapter(model, f"http://{host}:{port}")
    result = execute_external_model_occurrence(
        permit=_permit(monkeypatch, model, context),
        prepared=prepared,
        occurrences=model,
        adapter=adapter,
    )
    assert result.outcome is OnlyAgentModelCallOutcome.FAILED


def test_every_invalid_pre_io_capability_and_binding_produces_zero_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _ServerState(body=_response('{"action":"PLAN"}'))
    server = _Server(state)
    try:
        context, model, _, _, _, reference, *_ = _services(tmp_path / "one")
        prepared = _prepare_model(model, context, reference)
        permit = _permit(monkeypatch, model, context)
        _config, adapter = _adapter(model, server.url)
        with pytest.raises(OnlyAgentContextError):
            execute_external_model_occurrence(
                permit=cast(runtime.OnlyAgentRuntimeExecutionPermit, object()),
                prepared=prepared,
                occurrences=model,
                adapter=adapter,
            )
        with pytest.raises(OnlyAgentContextError):
            execute_external_model_occurrence(
                permit=permit,
                prepared=cast(OnlyPreparedAgentModelCallV1, object()),
                occurrences=model,
                adapter=adapter,
            )
        other_context, other_model, *_rest = _services(tmp_path / "two")
        other_reference = _rest[3]
        wrong_service_prepared = _prepare_model(other_model, other_context, other_reference)
        with pytest.raises(OnlyAgentContextError):
            execute_external_model_occurrence(
                permit=_permit(monkeypatch, other_model, other_context),
                prepared=wrong_service_prepared,
                occurrences=model,
                adapter=adapter,
            )
        assert state.request_count == 0

        mismatch_prepared = _prepare_model(model, context, reference, ordinal=1)
        _config, mismatched = _adapter(model, server.url, model_id="other-model")
        result = execute_external_model_occurrence(
            permit=permit,
            prepared=mismatch_prepared,
            occurrences=model,
            adapter=mismatched,
        )
        assert result.outcome is OnlyAgentModelCallOutcome.FAILED
        assert state.request_count == 0
    finally:
        server.close()


def test_model_wire_projection_is_exact_strict_and_secret_safe(tmp_path: Path) -> None:
    context, model, _, _, _, reference, *_ = _services(tmp_path)
    prepared = _prepare_model(model, context, reference)
    secret = "credential-must-not-leak"
    config, adapter = _adapter(model, "https://model.invalid", secret=secret)
    first = adapter.project_request_verified(prepared.plan)
    second = adapter.project_request_verified(prepared.plan)
    assert first == second
    assert first.url == "https://model.invalid/chat/completions"
    body = json.loads(first.body)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert secret not in repr(config)
    assert secret not in repr(first)
    assert secret not in json.dumps(prepared.plan.to_dict())
    assert not hasattr(config, "fallback_url")
    assert not hasattr(config, "fallback_model")
