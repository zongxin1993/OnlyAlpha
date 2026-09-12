from __future__ import annotations

from collections.abc import Mapping

from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server.agent_gateway import create_agent_gateway_router

SESSION = "a" * 64


class _Gateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def post_json_verified(self, path: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        self.calls.append((path, payload))
        if path.endswith("/advance"):
            return {
                "schema_version": 1,
                "session_fingerprint": SESSION,
                "derived_status": "ACTIVE",
                "next_action_kind": "PREPARE_MODEL_CALL",
                "failure_code": None,
            }
        brief = payload["research_brief"]
        assert isinstance(brief, dict)
        return {
            "schema_version": 1,
            "session_fingerprint": SESSION,
            "research_brief_fingerprint": brief["research_brief_fingerprint"],
            "session_disposition": "CREATED",
            "workflow_implementation_fingerprint": "b" * 64,
        }


def test_public_advance_is_one_exact_private_forward_without_local_authority() -> None:
    gateway = _Gateway()
    app = FastAPI()
    app.include_router(create_agent_gateway_router(gateway))
    response = TestClient(app).post(f"/api/v2/agent/sessions/{SESSION}/advance")
    assert response.status_code == 200
    assert response.json()["next_action_kind"] == "PREPARE_MODEL_CALL"
    assert gateway.calls == [(f"/internal/v1/sessions/{SESSION}/advance", {})]
