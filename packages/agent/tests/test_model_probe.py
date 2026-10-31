"""Connection checks are transient, bounded and never configure a model."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from onlyalpha_agent.app import create_app
from onlyalpha_agent.security import issue_token


def headers(settings, kind="human"):
    return {
        "Authorization": "Bearer "
        + issue_token(
            settings.signing_key,
            subject="owner",
            audience="onlyalpha-agent",
            kind=kind,
            scopes=["chat:read", "model:write"],
            token_id=str(uuid4()),
            expires_at=4_000_000_000,
        )
    }


pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_probe_uses_one_plain_completion_without_saving(settings, model_server):
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/agent/models/test",
            headers=headers(settings),
            json={
                "base_url": model_server.url,
                "model_id": "controlled",
                "secret": "probe-key",
            },
        )
        assert response.status_code == 200, response.text
        assert isinstance(response.json()["reply"], str)
        assert model_server.calls == 1
        assert model_server.requests[0] == {
            "model": "controlled",
            "messages": [{"role": "user", "content": "请只回复：连接成功。"}],
            "max_tokens": 64,
        }
        assert client.get("/api/v1/agent/models", headers=headers(settings)).json() == {"items": []}
        assert client.get("/api/v1/agent/sessions", headers=headers(settings)).json() == {"items": []}
        assert (
            client.post(
                "/api/v1/agent/models/test",
                headers=headers(settings, kind="service"),
                json={
                    "base_url": model_server.url,
                    "model_id": "controlled",
                    "secret": "probe-key",
                },
            ).status_code
            == 403
        )
        assert model_server.calls == 1


def test_probe_rejects_invalid_endpoint_without_sending(settings, model_server):
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/agent/models/test",
            headers=headers(settings),
            json={
                "base_url": "http://8.8.8.8:58080/v1",
                "model_id": "controlled",
                "secret": "probe-key",
            },
        )
        assert response.status_code == 400
        assert response.json() == {"detail": "AGENT_MODEL_ENDPOINT_INVALID"}
        assert model_server.calls == 0


@pytest.mark.parametrize(
    "content", ["", " " * 3, None, {"text": "not text"}, "a" * 2001, "private-key", "prefix private-key tail"]
)
def test_probe_rejects_invalid_plain_replies(monkeypatch, content):
    from onlyalpha_agent import model

    monkeypatch.setattr(model, "completion", lambda *args: {"choices": [{"message": {"content": content}}]})
    assert model.probe({"base_url": "https://model.example/v1", "model_id": "m"}, "private-key") == {
        "error": "MODEL_RESPONSE_INVALID"
    }


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "MODEL_AUTH_FAILED"),
        (403, "MODEL_AUTH_FAILED"),
        (404, "MODEL_ENDPOINT_NOT_FOUND"),
        (429, "MODEL_BUSY"),
        (500, "MODEL_REJECTED"),
    ],
)
def test_probe_classifies_provider_errors_without_exposing_body(monkeypatch, status, code):
    from urllib.error import HTTPError

    from onlyalpha_agent import model

    def reject(*args):
        raise HTTPError("https://model.example/v1", status, "private provider detail", {}, None)

    monkeypatch.setattr(model, "completion", reject)
    assert model.probe({"base_url": "https://model.example/v1", "model_id": "m"}, "private-key") == {"error": code}


def test_probe_never_returns_a_json_escaped_credential(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from onlyalpha_agent import model

    @contextmanager
    def response(*args, **kwargs):
        yield SimpleNamespace(read=lambda size: b'{"choices":[{"message":{"content":"\\u0070rivate-key"}}]}')

    monkeypatch.setattr(model, "build_opener", lambda *args: SimpleNamespace(open=response))
    assert model.probe({"base_url": "https://model.example/v1", "model_id": "m"}, "private-key") == {
        "error": "MODEL_RESPONSE_INVALID"
    }


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.3.116:58080/v1",
        "http://10.0.0.2:8080/v1",
        "http://172.16.0.1/v1",
        "http://172.31.255.254/v1",
        "http://[fd00::1]:8080/v1",
        "http://127.0.0.1:1234/v1",
        "http://localhost:1234/v1",
    ],
)
def test_local_http_model_addresses_are_supported(url):
    from onlyalpha_agent.model import endpoint

    assert endpoint(url) == url + "/chat/completions"


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/v1",
        "http://model.example/v1",
        "http://169.254.169.254/v1",
        "http://0.0.0.0/v1",
        "http://[::]/v1",
        "http://192.0.2.1/v1",
        "http://172.32.0.1/v1",
        "http://192.168.3.116:99999/v1",
        "http://u:p@192.168.3.116/v1",
        "http://192.168.3.116/v1?key=x",
        "http://192.168.3.116/v1#x",
    ],
)
def test_unprotected_external_or_ambiguous_model_addresses_stay_rejected(url):
    from onlyalpha_agent.model import endpoint

    with pytest.raises(ValueError):
        endpoint(url)
