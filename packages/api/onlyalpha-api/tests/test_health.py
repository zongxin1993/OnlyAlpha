from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_api.health import create_health_router

from onlyalpha.research.operations.readiness import (
    OnlyResearchReadiness,
    OnlyResearchReadinessCheck,
    OnlyResearchReadinessStatus,
    OnlyResearchRequiredRoot,
    OnlyResearchServiceReadinessProbe,
)


class Probe:
    def __init__(self, readiness: OnlyResearchReadiness) -> None:
        self.readiness = readiness

    def inspect(self) -> OnlyResearchReadiness:
        return self.readiness


def _client(readiness: OnlyResearchReadiness) -> TestClient:
    app = FastAPI()
    app.include_router(create_health_router(Probe(readiness)))
    return TestClient(app)


def test_liveness_is_independent_of_database_readiness() -> None:
    client = _client(
        OnlyResearchReadiness(
            OnlyResearchReadinessStatus.NOT_READY,
            (OnlyResearchReadinessCheck("postgres", "UNAVAILABLE"),),
            "POSTGRES_UNAVAILABLE",
        )
    )
    assert client.get("/health/live").json() == {
        "status": "LIVE",
        "checks": {"http": "LIVE"},
        "reason": None,
    }
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json() == {
        "status": "NOT_READY",
        "checks": {"postgres": "UNAVAILABLE"},
        "reason": "POSTGRES_UNAVAILABLE",
    }


def test_ready_contract_is_strict_and_deterministic() -> None:
    response = _client(
        OnlyResearchReadiness(
            OnlyResearchReadinessStatus.READY,
            (
                OnlyResearchReadinessCheck("postgres", "READY"),
                OnlyResearchReadinessCheck("schema", "COMPATIBLE"),
            ),
        )
    ).get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {"postgres": "READY", "schema": "COMPATIBLE"}


def test_readiness_probe_fails_closed_for_database_schema_root_and_registry(tmp_path) -> None:  # type: ignore[no-untyped-def]
    class Status:
        compatible = True
        verdict = "COMPATIBLE"

    unavailable = OnlyResearchServiceReadinessProbe(
        schema_status=lambda: (_ for _ in ()).throw(RuntimeError("secret dsn")),
        deployment_check=lambda: None,
        required_roots=(),
        registry_check=lambda: None,
    ).inspect()
    assert unavailable.reason == "POSTGRES_UNAVAILABLE"

    class Incompatible:
        compatible = False
        verdict = "AHEAD"

    incompatible = OnlyResearchServiceReadinessProbe(
        schema_status=Incompatible,
        deployment_check=lambda: None,
        required_roots=(),
        registry_check=lambda: None,
    ).inspect()
    assert incompatible.reason == "SCHEMA_INCOMPATIBLE"

    missing = OnlyResearchServiceReadinessProbe(
        schema_status=Status,
        deployment_check=lambda: None,
        required_roots=(OnlyResearchRequiredRoot("dataset_root", tmp_path / "missing", False),),
        registry_check=lambda: None,
    ).inspect()
    assert missing.reason == "REQUIRED_ROOT_UNUSABLE"

    invalid_registry = OnlyResearchServiceReadinessProbe(
        schema_status=Status,
        deployment_check=lambda: None,
        required_roots=(OnlyResearchRequiredRoot("dataset_root", tmp_path, False),),
        registry_check=lambda: (_ for _ in ()).throw(RuntimeError("bad plugin")),
    ).inspect()
    assert invalid_registry.reason == "REGISTRY_INVALID"
