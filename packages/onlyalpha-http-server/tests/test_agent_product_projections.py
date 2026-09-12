from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from onlyalpha_http_server.research.runtime_generation_routes import create_runtime_generation_router
from onlyalpha_http_server.research.search_authoring_routes import create_search_authoring_router

SHA = "a" * 64


@dataclass(frozen=True)
class _Projection:
    active_for_new_work: str | None


class _RuntimeGenerations:
    def __init__(self, active: str | None) -> None:
        self.active = active

    def projection(self) -> _Projection:
        return _Projection(self.active)


@dataclass(frozen=True)
class _Input:
    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "search_space_fingerprint": SHA}


class _Inputs:
    def load_search_authoring_input_verified(self, kind: str, fingerprint: str) -> _Input:
        assert (kind, fingerprint) == ("SYMBOLIC_SEARCH_SPACE", SHA)
        return _Input()


def test_runtime_generation_and_search_authoring_are_exact_read_only_product_projections() -> None:
    app = FastAPI()
    app.include_router(create_runtime_generation_router(_RuntimeGenerations(SHA)))
    app.include_router(create_search_authoring_router(_Inputs()))
    client = TestClient(app)
    assert client.get("/api/v2/research/runtime-generations/active").json() == {
        "schema_version": 1,
        "runtime_generation_fingerprint": SHA,
    }
    response = client.get(f"/api/v2/research/search/authoring/SYMBOLIC_SEARCH_SPACE/{SHA}")
    assert response.status_code == 200
    assert response.json()["payload"]["search_space_fingerprint"] == SHA


def test_absent_active_runtime_generation_fails_closed() -> None:
    app = FastAPI()
    app.include_router(create_runtime_generation_router(_RuntimeGenerations(None)))
    assert TestClient(app).get("/api/v2/research/runtime-generations/active").status_code == 503
