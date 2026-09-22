"""Hermetic smoke tests for the deterministic OpenAI-compatible provider fixture."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from types import MappingProxyType
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from onlyalpha_agent_orchestrator.provider_integration import OnlyOpenAICompatibleAgentProviderProbe

from onlyalpha.plugin.integration import OnlyIntegrationProbeCheck
from onlyalpha.plugin.integration_probe import (
    OnlyIntegrationProbeCheckStatus,
    OnlyIntegrationProbePolicy,
    OnlyIntegrationProbeRequest,
    OnlyIntegrationProbeStatus,
)
from tests.runtime_support.openai_compatible_provider_fixture import (
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_VERSION,
    DEFAULT_TOKEN,
    only_create_openai_compatible_provider_server,
)


@contextmanager
def _running_fixture(**overrides: str) -> Iterator[ThreadingHTTPServer]:
    server = only_create_openai_compatible_provider_server("127.0.0.1", 0, **overrides)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _base_url(server: ThreadingHTTPServer) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}/v1"


def _get(url: str, token: str | None) -> tuple[int, bytes]:
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, headers=headers, method="GET"), timeout=5) as response:  # noqa: S310
            return int(response.status), response.read()
    except HTTPError as error:
        return int(error.code), error.read()


def _post(url: str, token: str | None, payload: object) -> tuple[int, bytes]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode("utf-8")
    try:
        with urlopen(Request(url, data=body, headers=headers, method="POST"), timeout=5) as response:  # noqa: S310
            return int(response.status), response.read()
    except HTTPError as error:
        return int(error.code), error.read()


def _probe_request(base_url: str, token: str) -> OnlyIntegrationProbeRequest:
    return OnlyIntegrationProbeRequest(
        probe_attempt_id=str(uuid.uuid4()),
        integration_id=str(uuid.uuid4()),
        revision_fingerprint="a" * 64,
        type_id="openai.compatible.agent_provider",
        type_descriptor_fingerprint="b" * 64,
        public_configuration=MappingProxyType({"base_url": base_url}),
        probe_configuration=None,
        required_checks=(
            OnlyIntegrationProbeCheck.CONNECTIVITY,
            OnlyIntegrationProbeCheck.AUTHENTICATION,
            OnlyIntegrationProbeCheck.MODEL_DISCOVERY,
        ),
        probe_instrument="models",
        policy=OnlyIntegrationProbePolicy(),
        deadline_monotonic=time.monotonic() + 5.0,
        resolved_secrets=MappingProxyType({"api_credential": token}),
    )


def test_models_endpoint_requires_exact_bearer_token() -> None:
    with _running_fixture() as server:
        url = _base_url(server) + "/models"
        assert _get(url, None)[0] == HTTPStatus.UNAUTHORIZED
        assert _get(url, "wrong-token")[0] == HTTPStatus.UNAUTHORIZED
        status, payload = _get(url, DEFAULT_TOKEN)
        assert status == HTTPStatus.OK
        assert json.loads(payload) == {
            "object": "list",
            "data": [{"id": DEFAULT_MODEL_ID, "object": "model", "owned_by": "onlyalpha-fixture"}],
        }


def test_health_endpoint_is_open_and_reports_configured_model_identity() -> None:
    with _running_fixture() as server:
        status, payload = _get(f"http://127.0.0.1:{server.server_address[1]}/health", None)
        assert status == HTTPStatus.OK
        assert json.loads(payload) == {
            "status": "ready",
            "model_id": DEFAULT_MODEL_ID,
            "model_version": DEFAULT_MODEL_VERSION,
        }


def test_chat_completion_is_deterministic_and_adapter_parseable() -> None:
    request_body = {
        "messages": [{"content": "ping", "role": "system"}],
        "model": DEFAULT_MODEL_ID,
    }
    with _running_fixture() as server:
        url = _base_url(server) + "/chat/completions"
        assert _post(url, None, request_body)[0] == HTTPStatus.UNAUTHORIZED
        status, payload = _post(url, DEFAULT_TOKEN, request_body)
        assert status == HTTPStatus.OK
        repeat_status, repeat_payload = _post(url, DEFAULT_TOKEN, request_body)
        assert (repeat_status, repeat_payload) == (status, payload)
        envelope = json.loads(payload)
        assert envelope["object"] == "chat.completion"
        assert envelope["model"] == DEFAULT_MODEL_ID
        choices = envelope["choices"]
        assert isinstance(choices, list) and len(choices) == 1
        message = choices[0]["message"]
        assert message["refusal"] is None
        assert isinstance(message["content"], str)
        assert isinstance(json.loads(message["content"]), dict)


def test_real_probe_certifies_fixture_ready_and_rejects_wrong_credential() -> None:
    probe = OnlyOpenAICompatibleAgentProviderProbe()
    with _running_fixture() as server:
        ready = probe.probe(_probe_request(_base_url(server), DEFAULT_TOKEN))
        assert ready.overall_status is OnlyIntegrationProbeStatus.READY
        assert {check.check for check in ready.checks} == {
            OnlyIntegrationProbeCheck.CONNECTIVITY,
            OnlyIntegrationProbeCheck.AUTHENTICATION,
            OnlyIntegrationProbeCheck.MODEL_DISCOVERY,
        }
        assert all(check.status is OnlyIntegrationProbeCheckStatus.PASS for check in ready.checks)

        rejected = probe.probe(_probe_request(_base_url(server), "wrong-token"))
        assert rejected.overall_status is not OnlyIntegrationProbeStatus.READY
        assert all(check.status is OnlyIntegrationProbeCheckStatus.FAIL for check in rejected.checks)


def test_custom_token_and_model_identity_are_honored() -> None:
    with _running_fixture(token="custom-secret", model_id="custom-model", model_version="9.9.9") as server:
        assert _get(_base_url(server) + "/models", DEFAULT_TOKEN)[0] == HTTPStatus.UNAUTHORIZED
        status, payload = _get(_base_url(server) + "/models", "custom-secret")
        assert status == HTTPStatus.OK
        assert json.loads(payload)["data"][0]["id"] == "custom-model"
        probe = OnlyOpenAICompatibleAgentProviderProbe()
        result = probe.probe(_probe_request(_base_url(server), "custom-secret"))
        assert result.overall_status is OnlyIntegrationProbeStatus.READY
