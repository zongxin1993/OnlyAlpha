from __future__ import annotations

import ipaddress
import json
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from onlyalpha_agent_orchestrator.provider_integration import (
    OnlyAgentModelProfileV1,
    OnlyAgentProviderRuntimeAuthorityConfigV1,
    OnlyAgentProviderRuntimeResolverV1,
    OnlyAgentSessionProviderBindingV1,
    OnlyHttpAgentProviderRuntimeAuthorityV1,
    OnlyJsonAgentModelProfileStoreV1,
    OnlyJsonAgentProviderBindingStoreV1,
    OnlyOpenAICompatibleAgentProviderProbe,
)

from onlyalpha.application.integration_configuration import (
    OnlyIntegration,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationRevision,
    OnlyIntegrationSecretBinding,
)
from onlyalpha.application.integration_probe import OnlyIntegrationProbeAttempt
from onlyalpha.application.integration_runtime import OnlyIntegrationRuntimeBindingV1, OnlyIntegrationRuntimeResolver
from onlyalpha.plugin.agent_provider import OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE
from onlyalpha.plugin.integration import OnlyIntegrationCategory
from onlyalpha.plugin.integration_probe import OnlyIntegrationProbePolicy, OnlyIntegrationProbeRequest

NOW = datetime(2026, 9, 21, tzinfo=UTC)
INTEGRATION_ID = OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
CREDENTIAL_ID = "ba13b6b1-af9a-450f-833d-48f5002297dc"


class _State:
    def __init__(self, integration: OnlyIntegration) -> None:
        self.integration = integration
        self.revisions: dict[str, OnlyIntegrationRevision] = {}
        self.bindings: dict[str, tuple[OnlyIntegrationSecretBinding, ...]] = {}

    def load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration:
        if integration_id != self.integration.integration_id:
            raise LookupError
        return self.integration

    def load_revision(self, fingerprint: str) -> OnlyIntegrationRevision:
        return self.revisions[fingerprint]

    def load_revision_secret_bindings(self, fingerprint: str) -> tuple[OnlyIntegrationSecretBinding, ...]:
        return self.bindings[fingerprint]


class _Credentials:
    def __init__(self) -> None:
        self.available = {3, 4}
        self.reads: list[int] = []

    def read_secret(self, _credential_id: str, generation: int) -> str:
        self.reads.append(generation)
        if generation not in self.available:
            raise LookupError
        return f"credential-generation-{generation}"


class _Catalog:
    @staticmethod
    def require(type_id: str):
        if type_id != OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE.type_id.value:
            raise LookupError
        return OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE


class _Probes:
    def __init__(self) -> None:
        self.attempts: dict[str, OnlyIntegrationProbeAttempt] = {}

    def latest_probe_attempt(self, _integration_id: OnlyIntegrationId, fingerprint: str):
        return self.attempts.get(fingerprint)


def _revision(
    sequence: int,
    generation: int,
    *,
    base_url: str = "https://provider.example/v1",
) -> tuple[OnlyIntegrationRevision, tuple[OnlyIntegrationSecretBinding, ...]]:
    bindings = (OnlyIntegrationSecretBinding("api_credential", CREDENTIAL_ID, generation),)
    revision = OnlyIntegrationRevision.from_resolved(
        integration_id=INTEGRATION_ID,
        revision_sequence=sequence,
        type_id=OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE.type_id.value,
        type_descriptor_fingerprint=OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE.fingerprint,
        type_descriptor_document=OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE.to_dict(include_fingerprint=False),
        configuration_document={
            "base_url": base_url,
            "connect_timeout_seconds": 2.0,
            "read_timeout_seconds": 5.0,
            "verify_tls": True,
        },
        probe_configuration_document=None,
        secret_bindings=bindings,
        created_at=NOW,
    )
    return revision, bindings


def _ready_attempt(revision: OnlyIntegrationRevision, generation: int) -> OnlyIntegrationProbeAttempt:
    request = OnlyIntegrationProbeRequest.create(
        probe_attempt_id=f"8ec96368-f447-45fe-9fc2-2596a7c7b9b{generation}",
        integration_id=INTEGRATION_ID.value,
        revision=revision,
        resolved_secrets={"api_credential": f"credential-generation-{generation}"},
        policy=OnlyIntegrationProbePolicy(),
        deadline_monotonic=10_000_000_000,
    )
    calls: list[tuple[str, str]] = []

    def transport(url, headers, _timeout, _verify_tls):
        calls.append((url, headers["Authorization"]))
        assert url.endswith("/models")
        return 200, b'{"data":[{"id":"model-a"}]}'

    result = OnlyOpenAICompatibleAgentProviderProbe(transport).probe(request)
    base_url = str(revision.configuration_document["base_url"])
    assert calls == [(f"{base_url}/models", f"Bearer credential-generation-{generation}")]
    return OnlyIntegrationProbeAttempt.from_result(result, revision)


def _profile(revision: OnlyIntegrationRevision, model_id: str) -> OnlyAgentModelProfileV1:
    return OnlyAgentModelProfileV1(
        INTEGRATION_ID.value,
        revision.revision_fingerprint,
        revision.runtime_configuration_fingerprint,
        model_id,
        "2026-09-01",
        ("CHAT", "STRUCTURED_OUTPUT"),
    )


def test_model_profile_parser_rejects_non_string_identity_fields() -> None:
    document = _profile(_revision(1, 3)[0], "model-a").to_dict()
    document["model_id"] = 7

    with pytest.raises(ValueError, match="AGENT_MODEL_PROFILE_INVALID"):
        OnlyAgentModelProfileV1.from_dict(document)


def test_provider_and_model_profiles_are_separate_exact_session_evidence(tmp_path) -> None:
    r1, b1 = _revision(1, 3)
    r2, b2 = _revision(2, 4)
    state = _State(
        OnlyIntegration(
            INTEGRATION_ID,
            r1.type_id,
            "Provider",
            OnlyIntegrationLifecycleState.ACTIVE,
            r1.revision_fingerprint,
            NOW,
            NOW,
        )
    )
    state.revisions = {r1.revision_fingerprint: r1, r2.revision_fingerprint: r2}
    state.bindings = {r1.revision_fingerprint: b1, r2.revision_fingerprint: b2}
    probes = _Probes()
    probes.attempts = {
        r1.revision_fingerprint: _ready_attempt(r1, 3),
        r2.revision_fingerprint: _ready_attempt(r2, 4),
    }
    credentials = _Credentials()
    resolver = OnlyAgentProviderRuntimeResolverV1(
        OnlyIntegrationRuntimeResolver(state, credentials, _Catalog(), probes=probes)
    )
    model_a = _profile(r1, "model-a")
    model_b = _profile(r1, "model-b")

    runtime_r1 = resolver.admit_new(model_a)
    evidence = OnlyAgentSessionProviderBindingV1(
        "a" * 64,
        "b" * 64,
        "c" * 64,
        runtime_r1.binding,
        model_a.model_profile_fingerprint,
    )
    store = OnlyJsonAgentProviderBindingStoreV1(tmp_path)
    profiles = OnlyJsonAgentModelProfileStoreV1(tmp_path)
    profiles.commit(model_a)
    store.commit(evidence)
    assert store.load("a" * 64) == evidence
    assert profiles.load(model_a.model_profile_fingerprint) == model_a
    assert model_a.model_profile_fingerprint != model_b.model_profile_fingerprint
    assert "credential-generation-3" not in repr(runtime_r1)
    assert (
        "credential-generation-3"
        not in (tmp_path / "research/agent-orchestration/provider-bindings" / ("a" * 64) / "manifest.json").read_text()
    )

    state.integration = replace(state.integration, current_revision_fingerprint=r2.revision_fingerprint)
    continued = resolver.continue_exact(store.load("a" * 64), model_a)
    runtime_r2 = resolver.admit_new(_profile(r2, "model-c"))

    assert continued.endpoint.api_credential == "credential-generation-3"
    assert runtime_r2.endpoint.api_credential == "credential-generation-4"
    assert continued.binding != runtime_r2.binding
    assert set(credentials.reads) == {3, 4}

    credentials.available.remove(3)
    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_MISMATCH"):
        resolver.continue_exact(evidence, model_a)


def test_provider_probe_is_get_only_and_never_executes_tools_or_broker_actions() -> None:
    revision, _bindings = _revision(1, 3)
    request = OnlyIntegrationProbeRequest.create(
        probe_attempt_id="8ec96368-f447-45fe-9fc2-2596a7c7b9b3",
        integration_id=INTEGRATION_ID.value,
        revision=revision,
        resolved_secrets={"api_credential": "exact-secret"},
        policy=OnlyIntegrationProbePolicy(),
        deadline_monotonic=10_000_000_000,
    )
    calls: list[str] = []

    def transport(url, _headers, _timeout, _verify_tls):
        calls.append(url)
        return 200, b'{"data":[]}'

    result = OnlyOpenAICompatibleAgentProviderProbe(transport).probe(request)

    assert result.overall_status.value == "READY"
    assert calls == ["https://provider.example/v1/models"]


CREDENTIAL_SENTINEL = "provider-secret-sentinel"
BEARER_SENTINEL = "bootstrap-bearer-sentinel"


def test_production_configuration_rejects_plain_http_authority() -> None:
    with pytest.raises(ValueError, match="AGENT_PROVIDER_AUTHORITY_TRANSPORT_INSECURE"):
        OnlyAgentProviderRuntimeAuthorityConfigV1(
            "http://runtime-authority.internal/internal/v1/agent-provider-runtime", "token"
        )


def test_production_configuration_rejects_unverified_tls() -> None:
    with pytest.raises(ValueError, match="AGENT_PROVIDER_AUTHORITY_TRANSPORT_INSECURE"):
        OnlyAgentProviderRuntimeAuthorityConfigV1("https://runtime-authority.internal/x", "token", verify_tls=False)


def test_explicit_development_configuration_may_allow_plain_http() -> None:
    config = OnlyAgentProviderRuntimeAuthorityConfigV1("http://127.0.0.1:1/x", "token", allow_insecure_transport=True)

    assert config.base_url == "http://127.0.0.1:1/x"


def test_https_configuration_accepted_and_bearer_still_required() -> None:
    config = OnlyAgentProviderRuntimeAuthorityConfigV1("https://runtime-authority.internal/x", "token")

    assert config.verify_tls is True
    with pytest.raises(ValueError, match="AGENT_PROVIDER_AUTHORITY_CONFIG_INVALID"):
        OnlyAgentProviderRuntimeAuthorityConfigV1("https://runtime-authority.internal/x", "")


def _create_tls_identity(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    certificate_path = directory / "authority.crt"
    private_key_path = directory / "authority.key"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private_key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return certificate_path, private_key_path


@contextmanager
def _tls_authority_server(tmp_path: Path, body: bytes) -> Iterator[tuple[str, Path]]:
    class _Server(ThreadingHTTPServer):
        def handle_error(self, *_args: object) -> None:  # TLS handshake failures are expected
            return

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler hook
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    certificate_path, private_key_path = _create_tls_identity(tmp_path / "tls")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate_path, private_key_path)
    server = _Server(("127.0.0.1", 0), _Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_port}", certificate_path
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _admit_new_response(profile: OnlyAgentModelProfileV1) -> bytes:
    revision, _bindings = _revision(1, 3)
    assert profile == _profile(revision, profile.model_id)
    binding = OnlyIntegrationRuntimeBindingV1.from_revision(revision, OnlyIntegrationCategory.AGENT_PROVIDER)
    return json.dumps(
        {
            "schema_version": 1,
            "provider_binding": binding.to_dict(),
            "model_profile": profile.to_dict(),
            "endpoint": {
                "base_url": "https://provider.example/v1",
                "api_credential": CREDENTIAL_SENTINEL,
                "expected_provider_id": OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE.provider_id,
                "expected_model_id": profile.model_id,
                "expected_model_version": profile.model_version,
                "connect_timeout_seconds": 2.0,
                "read_timeout_seconds": 5.0,
                "verify_tls": True,
            },
        }
    ).encode("utf-8")


def test_untrusted_certificate_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    profile = _profile(_revision(1, 3)[0], "model-a")

    with _tls_authority_server(tmp_path, _admit_new_response(profile)) as (base_url, _certificate):
        config = OnlyAgentProviderRuntimeAuthorityConfigV1(base_url, BEARER_SENTINEL)
        client = OnlyHttpAgentProviderRuntimeAuthorityV1(config)
        with pytest.raises(ValueError, match="AGENT_PROVIDER_AUTHORITY_UNAVAILABLE") as raised:
            client.admit_new(profile)

    assert CREDENTIAL_SENTINEL not in str(raised.value)
    assert BEARER_SENTINEL not in str(raised.value)
    assert BEARER_SENTINEL not in repr(config)


def test_trusted_ca_https_transport_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    profile = _profile(_revision(1, 3)[0], "model-a")

    with _tls_authority_server(tmp_path, _admit_new_response(profile)) as (base_url, certificate):
        monkeypatch.setenv("SSL_CERT_FILE", str(certificate))
        config = OnlyAgentProviderRuntimeAuthorityConfigV1(base_url, BEARER_SENTINEL)
        resolved = OnlyHttpAgentProviderRuntimeAuthorityV1(config).admit_new(profile)

    assert resolved.endpoint.base_url == "https://provider.example/v1"
    assert resolved.endpoint.api_credential == CREDENTIAL_SENTINEL
    assert resolved.model_profile == profile
    assert CREDENTIAL_SENTINEL not in repr(config)
    assert CREDENTIAL_SENTINEL not in repr(resolved)
    assert BEARER_SENTINEL not in repr(config)
    assert BEARER_SENTINEL not in repr(resolved)
