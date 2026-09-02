from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from onlyalpha_http_server import create_research_app
from onlyalpha_http_server.health import OnlyKernelResearchReadinessProjection

from onlyalpha.application.product_boundary import only_compose_research_product_boundary
from onlyalpha.backtest import (
    OnlyBacktestAdmissionResolution,
    OnlyBacktestCommandService,
    OnlyBacktestEvidenceStore,
    OnlyBacktestQueryService,
    OnlyInMemoryBacktestCommandStore,
)
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.kernel import OnlyAlphaKernelHost
from onlyalpha.research.definition import OnlyResearchDefinitionResolver
from onlyalpha.research.operations.readiness import OnlyResearchReadiness, OnlyResearchReadinessStatus

NOW = datetime(2026, 9, 2, tzinfo=UTC)
KEY = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class _Admission:
    def resolve(self, specification):  # type: ignore[no-untyped-def]
        return OnlyBacktestAdmissionResolution(
            1,
            specification.strategy_fingerprint,
            specification.dataset_binding_fingerprint,
            "d" * 64,
            "e" * 64,
            "1" * 64,
            "2" * 64,
            "3" * 64,
            "kernel-v1",
            (),
        )


class _Reader:
    def load_verified(self, fingerprint: str):  # type: ignore[no-untyped-def]
        raise RuntimeError(fingerprint)


class _Definitions:
    universe_resolver = None

    def resolve_verified(self, value: object) -> object:
        return value


def _client(tmp_path):  # type: ignore[no-untyped-def]
    store = OnlyInMemoryBacktestCommandStore()
    command = OnlyBacktestCommandService(admission=_Admission(), store=store, now_utc=lambda: NOW)  # type: ignore[arg-type]
    query = OnlyBacktestQueryService(store, OnlyBacktestEvidenceStore(tmp_path))
    kernel = OnlyAlphaKernelHost()
    kernel.start()
    boundary = only_compose_research_product_boundary(
        admission=kernel,
        commands=object(),  # type: ignore[arg-type]
        queries=object(),  # type: ignore[arg-type]
    )
    app = create_research_app(
        _Reader(),  # type: ignore[arg-type]
        boundary,
        OnlyCalculationRegistry(),
        OnlyResearchDefinitionResolver(OnlyCalculationRegistry(), _Definitions()),  # type: ignore[arg-type]
        OnlyKernelResearchReadinessProjection(
            kernel,
            OnlyResearchReadiness(OnlyResearchReadinessStatus.READY, ()),
        ),
        backtest_commands=command,
        backtest_queries=query,
    )
    return store, TestClient(app)


def _payload() -> dict[str, object]:
    reference = {"profile_id": "profile", "version": "1"}
    return {
        "schema_version": 1,
        "strategy_fingerprint": "a" * 64,
        "dataset_binding_fingerprint": "b" * 64,
        "market_product_configuration_fingerprint": "c" * 64,
        "portfolio_profile": reference,
        "risk_profile": reference,
        "execution_profile": reference,
        "initial_account": {"base_currency": "USDT", "capital": "100"},
        "runtime_options": {"ordered_fact_policy": "ORDERED_FACTS_V1"},
    }


def test_backtest_http_admission_is_async_idempotent_and_queryable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, client = _client(tmp_path)
    created = client.post("/api/v2/backtest/runs", headers={"Idempotency-Key": KEY}, json=_payload())
    replay = client.post("/api/v2/backtest/runs", headers={"Idempotency-Key": KEY}, json=_payload())

    assert created.status_code == replay.status_code == 202
    assert created.json()["backtest_run_id"] == replay.json()["backtest_run_id"]
    assert created.json()["disposition"] == "CREATED"
    assert replay.json()["disposition"] == "REPLAYED"
    run_id = created.json()["backtest_run_id"]
    assert created.headers["location"] == f"/api/v2/backtest/runs/{run_id}"
    queried = client.get(f"/api/v2/backtest/runs/{run_id}")
    assert queried.status_code == 200
    assert queried.json()["state"] == "QUEUED"


def test_backtest_http_same_command_different_intent_conflicts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, client = _client(tmp_path)
    assert client.post("/api/v2/backtest/runs", headers={"Idempotency-Key": KEY}, json=_payload()).status_code == 202
    changed = _payload()
    changed["initial_account"] = {"base_currency": "USDT", "capital": "101"}
    conflict = client.post("/api/v2/backtest/runs", headers={"Idempotency-Key": KEY}, json=changed)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "PRODUCT_COMMAND_CONFLICT"


def test_backtest_http_validation_uses_stable_product_error(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, client = _client(tmp_path)
    invalid = _payload()
    invalid["unexpected"] = True
    response = client.post("/api/v2/backtest/runs", headers={"Idempotency-Key": KEY}, json=invalid)
    assert response.status_code == 400
    assert response.json() == {
        "schema_version": 1,
        "error": {
            "phase": "COMMAND",
            "code": "PRODUCT_REQUEST_INVALID",
            "detail": "HTTP request validation failed",
        },
    }

    invalid_path = client.get("/api/v2/backtest/runs/not-a-uuid")
    assert invalid_path.status_code == 400
    assert invalid_path.json()["error"]["code"] == "PRODUCT_REQUEST_INVALID"
