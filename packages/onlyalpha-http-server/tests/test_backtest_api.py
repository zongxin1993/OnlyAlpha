from __future__ import annotations

from datetime import UTC, datetime

import pytest
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
from onlyalpha.backtest.errors import (
    OnlyBacktestIntegrityError,
    OnlyBacktestNotFoundError,
    OnlyBacktestStateConflictError,
    OnlyBacktestStoreUnavailableError,
)
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.kernel import OnlyAlphaKernelHost
from onlyalpha.research.definition import OnlyResearchDefinitionResolver
from onlyalpha.research.operations.readiness import OnlyResearchReadiness, OnlyResearchReadinessStatus
from onlyalpha.strategy.errors import OnlyStrategyError

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


class _RuntimeGenerations:
    def __init__(self) -> None:
        self.work: set[str] = set()

    def bind_new_work(self, work_id, **_):  # type: ignore[no-untyped-def]
        self.work.add(work_id)

    def release_work(self, work_id, **_):  # type: ignore[no-untyped-def]
        self.work.discard(work_id)

    def require_work_binding(self, work_id):  # type: ignore[no-untyped-def]
        if work_id not in self.work:
            raise ValueError("RUNTIME_WORK_GENERATION_UNBOUND")


def _client(tmp_path):  # type: ignore[no-untyped-def]
    store = OnlyInMemoryBacktestCommandStore()
    command = OnlyBacktestCommandService(
        admission=_Admission(),
        store=store,
        now_utc=lambda: NOW,
        runtime_generations=_RuntimeGenerations(),  # type: ignore[arg-type]
    )  # type: ignore[arg-type]
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


class _FailingProductQuery:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def get(self, _identity: object) -> object:
        raise self._error


def _error_client(tmp_path, *, family: str, error: Exception) -> TestClient:  # type: ignore[no-untyped-def]
    kernel = OnlyAlphaKernelHost()
    kernel.start()
    boundary = only_compose_research_product_boundary(
        admission=kernel,
        commands=object(),  # type: ignore[arg-type]
        queries=object(),  # type: ignore[arg-type]
    )
    options: dict[str, object]
    if family == "backtest":
        options = {
            "backtest_commands": object(),
            "backtest_queries": _FailingProductQuery(error),
        }
    else:
        options = {
            "strategy_freeze": object(),
            "strategy_promotion": object(),
            "strategy_query": _FailingProductQuery(error),
            "qualification": object(),
            "qualification_query": object(),
        }
    app = create_research_app(
        _Reader(),  # type: ignore[arg-type]
        boundary,
        OnlyCalculationRegistry(),
        OnlyResearchDefinitionResolver(OnlyCalculationRegistry(), _Definitions()),  # type: ignore[arg-type]
        OnlyKernelResearchReadinessProjection(
            kernel,
            OnlyResearchReadiness(OnlyResearchReadinessStatus.READY, ()),
        ),
        **options,  # type: ignore[arg-type]
    )
    return TestClient(app)


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


@pytest.mark.parametrize(
    ("family", "error", "status"),
    (
        ("backtest", OnlyBacktestNotFoundError("missing"), 404),
        ("backtest", OnlyBacktestStateConflictError("conflict"), 409),
        ("backtest", OnlyBacktestStoreUnavailableError("offline"), 503),
        ("backtest", OnlyBacktestIntegrityError("BACKTEST_EVIDENCE_CORRUPT", "corrupt"), 500),
        ("strategy", OnlyStrategyError("STRATEGY_NOT_FOUND"), 404),
        ("strategy", OnlyStrategyError("STRATEGY_CONFLICT"), 409),
        ("strategy", OnlyStrategyError("STRATEGY_AUTHORITY_UNAVAILABLE"), 503),
        ("strategy", OnlyStrategyError("STRATEGY_CORRUPT"), 500),
    ),
)
def test_product_domain_errors_match_declared_envelope(
    tmp_path,
    family: str,
    error: Exception,
    status: int,  # type: ignore[no-untyped-def]
) -> None:
    client = _error_client(tmp_path, family=family, error=error)
    if family == "backtest":
        path = "/api/v2/backtest/runs/00000000-0000-4000-8000-000000000001"
        contract_path = "/api/v2/backtest/runs/{run_id}"
    else:
        path = f"/api/v2/strategies/{'a' * 64}"
        contract_path = "/api/v2/strategies/{strategy_fingerprint}"

    response = client.get(path)

    assert response.status_code == status
    assert response.json()["schema_version"] == 1
    assert set(response.json()["error"]) == {"phase", "code", "detail"}
    operation = client.app.openapi()["paths"][contract_path]["get"]
    assert operation["responses"][str(status)]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ProductErrorEnvelopeDto"
    }


def test_backtest_openapi_matches_product_error_and_evidence_runtime_contract(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, client = _client(tmp_path)
    document = client.app.openapi()
    operations = [
        operation
        for path, item in document["paths"].items()
        if path.startswith("/api/v2/backtest/")
        for operation in item.values()
    ]

    for operation in operations:
        assert "422" not in operation["responses"]
        for status in ("400", "404", "409", "500", "503"):
            schema = operation["responses"][status]["content"]["application/json"]["schema"]
            assert schema == {"$ref": "#/components/schemas/ProductErrorEnvelopeDto"}

    manifest = document["components"]["schemas"]["BacktestEvidenceManifestDto"]
    assert manifest["additionalProperties"] is False
    assert set(manifest["required"]) == {
        "backtest_run_id",
        "specification_fingerprint",
        "admission_resolution_fingerprint",
        "strategy_fingerprint",
        "dataset_binding_fingerprint",
        "base_dataset_snapshot_fingerprint",
        "market_product_composition_fingerprint",
        "portfolio_profile_fingerprint",
        "risk_profile_fingerprint",
        "execution_profile_fingerprint",
        "kernel_semantics_version",
        "implementation_fingerprints",
        "result_fingerprint",
        "determinism_fingerprint",
        "artifacts",
        "evidence_fingerprint",
    }
