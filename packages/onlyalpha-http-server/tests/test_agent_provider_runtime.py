from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_agent_orchestrator.config import OnlyOpenAICompatibleEndpointConfigV1
from onlyalpha_agent_orchestrator.provider_integration import (
    OnlyAgentModelProfileV1,
    OnlyAgentProviderRuntimeAuthorityConfigV1,
    OnlyAgentSessionProviderBindingV1,
    OnlyHttpAgentProviderRuntimeAuthorityV1,
    OnlyResolvedAgentProviderRuntimeV1,
)
from onlyalpha_http_server.agent_provider_runtime import create_agent_provider_runtime_router

from onlyalpha.application.integration_configuration import OnlyIntegrationId
from onlyalpha.application.integration_runtime import OnlyIntegrationRuntimeBindingV1, OnlyIntegrationRuntimeError
from onlyalpha.plugin.integration import OnlyIntegrationCategory


def _runtime() -> OnlyResolvedAgentProviderRuntimeV1:
    binding = OnlyIntegrationRuntimeBindingV1(
        OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
        "a" * 64,
        "openai.compatible.agent_provider",
        OnlyIntegrationCategory.AGENT_PROVIDER,
        "b" * 64,
        "c" * 64,
    )
    profile = OnlyAgentModelProfileV1(
        binding.integration_id.value,
        binding.revision_fingerprint,
        binding.runtime_configuration_fingerprint,
        "onlyalpha-research-v1",
        "2026-09-01",
        ("CHAT", "STRUCTURED_OUTPUT"),
    )
    return OnlyResolvedAgentProviderRuntimeV1(
        binding,
        profile,
        OnlyOpenAICompatibleEndpointConfigV1(
            "https://provider.example/v1",
            "provider-secret-sentinel",
            "openai-compatible",
            profile.model_id,
            profile.model_version,
        ),
    )


def test_published_runtime_authority_contract_serves_admission_and_exact_continuation() -> None:
    runtime = _runtime()

    class Resolver:
        admissions = 0
        continuations = 0

        def admit_new(self, profile):  # type: ignore[no-untyped-def]
            self.admissions += 1
            assert profile == runtime.model_profile
            return runtime

        def continue_exact(self, binding, profile):  # type: ignore[no-untyped-def]
            self.continuations += 1
            assert binding.provider_binding == runtime.binding
            assert profile == runtime.model_profile
            return runtime

    resolver = Resolver()
    app = FastAPI()
    app.include_router(create_agent_provider_runtime_router(resolver, "bootstrap-secret"))  # type: ignore[arg-type]
    test_client = TestClient(app)

    def transport(url, headers, payload, _timeout, _verify_tls):  # type: ignore[no-untyped-def]
        response = test_client.post(url, headers=dict(headers), content=payload)
        return response.status_code, response.content

    client = OnlyHttpAgentProviderRuntimeAuthorityV1(
        OnlyAgentProviderRuntimeAuthorityConfigV1(
            "http://testserver/internal/v1/agent-provider-runtime",
            "bootstrap-secret",
            allow_insecure_transport=True,
        ),
        transport,
    )
    admitted = client.admit_new(runtime.model_profile)
    evidence = OnlyAgentSessionProviderBindingV1(
        "d" * 64,
        "e" * 64,
        "f" * 64,
        admitted.binding,
        admitted.model_profile.model_profile_fingerprint,
    )
    continued = client.continue_exact(evidence, runtime.model_profile)

    assert admitted == continued == runtime
    assert resolver.admissions == resolver.continuations == 1
    assert "provider-secret-sentinel" not in repr(admitted)


def test_runtime_authority_rejects_wrong_bootstrap_token_without_resolution() -> None:
    class Resolver:
        def admit_new(self, _profile):  # type: ignore[no-untyped-def]
            raise AssertionError("unauthorized request reached resolver")

        def continue_exact(self, _binding, _profile):  # type: ignore[no-untyped-def]
            raise AssertionError("unauthorized request reached resolver")

    app = FastAPI()
    app.include_router(create_agent_provider_runtime_router(Resolver(), "expected"))  # type: ignore[arg-type]
    response = TestClient(app).post(
        "/internal/v1/agent-provider-runtime/admit-new",
        headers={"Authorization": "Bearer wrong"},
        json={"schema_version": 1, "model_profile": _runtime().model_profile.to_dict()},
    )

    assert response.status_code == 401
    assert response.json() == {"error": {"code": "AGENT_PROVIDER_AUTHORITY_UNAUTHORIZED"}}


@pytest.mark.parametrize(
    "status, code",
    (
        (409, "INTEGRATION_RUNTIME_DISABLED"),
        (503, "INTEGRATION_RUNTIME_SECRET_UNAVAILABLE"),
    ),
)
def test_default_http_transport_preserves_stable_runtime_error(status: int, code: str) -> None:
    body = f'{{"error":{{"code":"{code}"}}}}'.encode()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = OnlyHttpAgentProviderRuntimeAuthorityV1(
            OnlyAgentProviderRuntimeAuthorityConfigV1(
                f"http://127.0.0.1:{server.server_port}",
                "bootstrap-secret",
                allow_insecure_transport=True,
            )
        )
        with pytest.raises(OnlyIntegrationRuntimeError, match=code) as raised:
            client.admit_new(_runtime().model_profile)
        assert raised.value.code == code
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
