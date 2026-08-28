from __future__ import annotations

from typing import Any

import httpx
import pytest
from onlyalpha_client import (
    OnlyAlphaApiError,
    OnlyAlphaClient,
    OnlyAlphaProtocolError,
    OnlyAlphaTransportError,
)


def _run(run_id: str = "00000000-0000-4000-8000-000000000601") -> dict[str, Any]:
    return {
        "schema_version": 2,
        "run_id": run_id,
        "revision": "0",
        "state": "QUEUED",
        "specification_schema_version": 1,
        "specification_fingerprint": "a" * 64,
        "admission_resolution_fingerprint": "b" * 64,
        "specification": {"schema_version": 1},
        "queued_at": "2026-08-28T00:00:00Z",
        "started_at": None,
        "cancel_requested_at": None,
        "finished_at": None,
        "result_ref": None,
        "artifact_ref": None,
        "failure": None,
    }


def test_client_uses_generated_operation_and_preserves_explicit_command_identity() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json={"submission_disposition": "CREATED", "run": _run()})

    transport = httpx.Client(transport=httpx.MockTransport(handle))
    client = OnlyAlphaClient(base_url="https://product.example/", transport=transport)
    response = client.research.create(
        specification={"schema_version": 1},
        idempotency_key="00000000-0000-4000-8000-000000000600",
    )

    assert response["run"]["state"] == "QUEUED"
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/api/v2/research/runs"
    assert requests[0].headers["Idempotency-Key"] == "00000000-0000-4000-8000-000000000600"


def test_mutation_transport_failure_is_not_retried_or_fallback_executed() -> None:
    calls = 0

    def unavailable(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=request)

    client = OnlyAlphaClient(
        base_url="https://unavailable.example",
        transport=httpx.Client(transport=httpx.MockTransport(unavailable)),
    )
    with pytest.raises(OnlyAlphaTransportError, match="unavailable"):
        client.research.cancel("00000000-0000-4000-8000-000000000601")
    assert calls == 1


def test_contract_shaped_api_error_is_stable() -> None:
    def conflict(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            headers={"X-Request-ID": "request-1"},
            json={"error": {"phase": "COMMAND", "code": "PRODUCT_COMMAND_CONFLICT", "detail": "conflict"}},
        )

    client = OnlyAlphaClient(
        base_url="https://product.example",
        transport=httpx.Client(transport=httpx.MockTransport(conflict)),
    )
    with pytest.raises(OnlyAlphaApiError) as raised:
        client.research.get("00000000-0000-4000-8000-000000000601")
    assert raised.value.status_code == 409
    assert raised.value.code == "PRODUCT_COMMAND_CONFLICT"
    assert raised.value.phase == "COMMAND"
    assert raised.value.request_id == "request-1"


def test_success_response_must_match_generated_schema() -> None:
    def malformed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"run_id": "missing-required-fields"})

    client = OnlyAlphaClient(
        base_url="https://product.example",
        transport=httpx.Client(transport=httpx.MockTransport(malformed)),
    )
    with pytest.raises(OnlyAlphaProtocolError, match="missing required fields"):
        client.research.get("00000000-0000-4000-8000-000000000601")
