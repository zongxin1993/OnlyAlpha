from __future__ import annotations

import json
from uuid import uuid4

import pytest
from onlyalpha_agent import model, workflow
from onlyalpha_agent.security import Denied, authenticate, issue_token


@pytest.mark.parametrize(
    "url",
    ["http://remote.invalid", "https://user:secret@example.com", "https://example.com/?key=x", "file:///etc/passwd"],
)
def test_reject_unprotected_or_credential_endpoints(url):
    with pytest.raises(ValueError):
        model.endpoint(url)


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"n":NaN}', '{"n":Infinity}'])
def test_json_does_not_reinterpret_noncanonical_values(raw):
    with pytest.raises(ValueError):
        model.strict_json(raw)


def test_credential_expiry_signature_and_audience():
    key = b"s" * 32
    token = issue_token(
        key,
        subject="owner",
        audience="onlyalpha-agent",
        kind="human",
        scopes=["chat:read"],
        token_id=str(uuid4()),
        expires_at=1,
    )
    with pytest.raises(Denied):
        authenticate(key, "Bearer " + token)
    with pytest.raises(Denied):
        authenticate(b"x" * 32, "Bearer " + token)


def test_model_invalid_reply_is_not_scientific_evidence(model_server):
    result = model.invoke({"base_url": model_server.url}, "secret", {"model": "controlled"})
    assert result["response"] == {"message": "需要明确观察周期", "candidate": None}
    assert len(model_server.requests) == 1


def test_workflow_identity_ignores_unrelated_packages_and_detects_code(monkeypatch):
    first = workflow.current_identity()
    monkeypatch.setattr(
        workflow.importlib.metadata,
        "distributions",
        lambda: (_ for _ in ()).throw(AssertionError("whole environment scan")),
    )
    assert workflow.current_identity() == first
    monkeypatch.setattr(workflow.platform, "python_version", lambda: "different-exact-interpreter")
    assert workflow.current_identity() != first
    assert json.loads(json.dumps({"identity": first}))["identity"] == first


def test_native_dependency_bytes_and_data_are_part_of_exact_workflow(tmp_path, monkeypatch):
    from pathlib import PurePosixPath
    from types import SimpleNamespace

    library = tmp_path / "libpq.so.5.17"
    library.write_bytes(b"old native artifact")
    data = tmp_path / "calendar.dat"
    data.write_bytes(b"original dependency data")
    original = workflow.importlib.metadata.distribution

    def distribution(name):
        if name == "onlyalpha-agent":
            return SimpleNamespace(requires=["native-test==1"])
        assert name == "native-test"
        return SimpleNamespace(
            version="1",
            requires=[],
            files=[PurePosixPath(library.name), PurePosixPath(data.name)],
            locate_file=lambda p: tmp_path / str(p),
        )

    monkeypatch.setattr(workflow.importlib.metadata, "distribution", distribution)
    monkeypatch.setattr(workflow.importlib.metadata, "version", lambda name: "1")
    first = workflow.current_identity()
    library.write_bytes(b"changed native artifact")
    second = workflow.current_identity()
    assert first != second
    data.write_bytes(b"changed dependency data")
    assert workflow.current_identity() != second
    assert original is not None


def test_agent_openapi_documents_protected_typed_protocol():
    from pathlib import Path

    from onlyalpha_agent.app import create_app
    from onlyalpha_agent.config import Settings

    schema = create_app(Settings("unused", b"e" * 32, b"s" * 32)).openapi()
    assert schema == json.loads(
        (Path(__file__).resolve().parents[3] / "contracts/agent-api/v1/openapi.json").read_text()
    )
    for path, operations in schema["paths"].items():
        if path.endswith("/health"):
            continue
        for op in operations.values():
            assert op["security"] == [{"HTTPBearer": []}]
            assert op["responses"]["200"]["content"]["application/json"]["schema"]
            if path.endswith("/messages") or path.endswith("/{sid}") and "put" in operations or path.endswith("/{mid}"):
                if op.get("operationId", "").startswith(("configure_", "create_", "message_")):
                    assert any(p["name"] == "Idempotency-Key" and p["required"] for p in op["parameters"])


def test_request_limit_stops_stream_before_buffering_the_rest():
    import asyncio

    from onlyalpha_agent.app import BoundedBody

    received = []
    sent = []

    async def downstream(scope, receive, send):
        raise AssertionError("oversized input reached application")

    async def receive():
        received.append(1)
        assert len(received) <= 2, "must stop reading after the bound"
        return {"type": "http.request", "body": b"x" * 9000, "more_body": True}

    async def send(message):
        sent.append(message)

    asyncio.run(BoundedBody(downstream)({"type": "http", "method": "POST"}, receive, send))
    assert sent[0]["status"] == 413 and len(received) == 2
