from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server.main import _SearchAuthoringInputReader
from onlyalpha_http_server.research.exact_statistics_routes import create_exact_statistics_router
from onlyalpha_http_server.research.runtime_generation_routes import create_runtime_generation_router
from onlyalpha_http_server.research.search_authoring_routes import create_search_authoring_router
from onlyalpha_http_server.research.search_provenance_routes import create_search_provenance_router

from onlyalpha.research.evaluation.errors import OnlyResearchStatisticsResultStoreError
from onlyalpha.research.search.symbolic.errors import OnlySymbolicSearchStoreError

SHA = "a" * 64


@dataclass(frozen=True)
class _Projection:
    active_for_new_work: str | None


class _RuntimeGenerations:
    def __init__(self, active: str | None) -> None:
        self.active = active

    def projection(self) -> _Projection:
        return _Projection(self.active)

    def require_runtime_generation(self, runtime_generation_fingerprint: str) -> object:
        if runtime_generation_fingerprint != SHA:
            raise KeyError(runtime_generation_fingerprint)
        return type("Manifest", (), {"runtime_generation_fingerprint": runtime_generation_fingerprint})()


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
    assert client.get(f"/api/v2/research/runtime-generations/{SHA}").json() == {
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


def test_unknown_exact_runtime_generation_fails_closed() -> None:
    app = FastAPI()
    app.include_router(create_runtime_generation_router(_RuntimeGenerations(SHA)))
    assert TestClient(app).get(f"/api/v2/research/runtime-generations/{'b' * 64}").status_code == 404


class _SymbolicInputs:
    def load_search_space_intrinsic_verified(self, fingerprint: str) -> _Input:
        return _Input()

    def load_evaluation_contract_intrinsic_verified(self, fingerprint: str) -> _Input:
        return _Input()

    def load_algorithm_implementation_manifest_intrinsic_verified(self, fingerprint: str) -> _Input:
        raise OnlySymbolicSearchStoreError("SEARCH_ALGORITHM_MANIFEST_NOT_FOUND", fingerprint)


class _ParameterInputs:
    def load_search_space_intrinsic_verified(self, fingerprint: str) -> _Input:
        return _Input()

    def load_policy_intrinsic_verified(self, fingerprint: str) -> _Input:
        return _Input()

    def load_algorithm_manifest_intrinsic_verified(self, fingerprint: str) -> _Input:
        return _Input()


def test_production_search_authoring_reader_dispatches_only_existing_authorities() -> None:
    reader = _SearchAuthoringInputReader(_SymbolicInputs(), _ParameterInputs())  # type: ignore[arg-type]
    assert reader.load_search_authoring_input_verified("SYMBOLIC_SEARCH_SPACE", SHA).to_dict()
    assert reader.load_search_authoring_input_verified("PARAMETER_SEARCH_SPACE", SHA).to_dict()
    assert reader.load_search_authoring_input_verified("RESEARCH_EVALUATION", SHA).to_dict()
    assert reader.load_search_authoring_input_verified("SEARCH_POLICY", SHA).to_dict()
    assert reader.load_search_authoring_input_verified("SEARCH_ALGORITHM", SHA).to_dict()
    with pytest.raises(LookupError, match="SEARCH_BUDGET"):
        reader.load_search_authoring_input_verified("SEARCH_BUDGET", SHA)


@dataclass(frozen=True)
class _StatisticsManifest:
    statistics_result_fingerprint: str = SHA

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "statistics_result_fingerprint": self.statistics_result_fingerprint}


@dataclass(frozen=True)
class _StatisticsRow:
    def to_dict(self) -> dict[str, object]:
        return {"metric": "0.125"}


@dataclass(frozen=True)
class _StatisticsResult:
    manifest: _StatisticsManifest = _StatisticsManifest()
    rows: tuple[_StatisticsRow, ...] = (_StatisticsRow(),)


class _StatisticsReader:
    def load_verified(self, fingerprint: str) -> _StatisticsResult:
        assert fingerprint == SHA
        return _StatisticsResult()


def test_exact_statistics_route_projects_existing_authority_without_recomputing() -> None:
    app = FastAPI()
    app.include_router(create_exact_statistics_router(_StatisticsReader()))
    response = TestClient(app).get(f"/api/v2/research/statistics/{SHA}")
    assert response.status_code == 200
    assert response.json() == {
        "schema_version": 1,
        "statistics_result_fingerprint": SHA,
        "payload": {
            "manifest": {"schema_version": 1, "statistics_result_fingerprint": SHA},
            "rows": [{"metric": "0.125"}],
        },
    }


@pytest.mark.parametrize(
    ("code", "status", "detail"),
    (
        ("STATISTICS_RESULT_NOT_FOUND", 404, "RESEARCH_STATISTICS_NOT_FOUND"),
        ("STATISTICS_RESULT_CORRUPT", 500, "RESEARCH_STATISTICS_CORRUPT"),
    ),
)
def test_exact_statistics_route_keeps_missing_and_corrupt_authority_distinct(
    code: str,
    status: int,
    detail: str,
) -> None:
    class FailingReader:
        def load_verified(self, _fingerprint: str) -> object:
            raise OnlyResearchStatisticsResultStoreError(code, SHA)

    app = FastAPI()
    app.include_router(create_exact_statistics_router(FailingReader()))
    response = TestClient(app).get(f"/api/v2/research/statistics/{SHA}")
    assert response.status_code == status
    assert response.json()["detail"] == detail


@dataclass(frozen=True)
class _IterationResult:
    iteration_result_fingerprint: str = SHA

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "iteration_result_fingerprint": self.iteration_result_fingerprint,
            "research_result_reference": {"result_fingerprint": "b" * 64},
        }


class _IterationResults:
    def load_iteration_result_verified(self, fingerprint: str) -> _IterationResult:
        assert fingerprint == SHA
        return _IterationResult()

    def load_terminal_projection_verified(self, fingerprint: str) -> _IterationResult:
        assert fingerprint == SHA
        return _IterationResult()


def test_exact_search_iteration_result_projects_existing_search_provenance_authority() -> None:
    app = FastAPI()
    app.include_router(create_search_provenance_router(_IterationResults(), _IterationResults()))
    response = TestClient(app).get(f"/api/v2/research/search/iteration-results/{SHA}")
    assert response.status_code == 200
    assert response.json() == {
        "schema_version": 1,
        "iteration_result_fingerprint": SHA,
        "payload": _IterationResult().to_dict(),
    }
    terminal = TestClient(app).get(f"/api/v2/research/search/iteration-results/terminal-projections/{SHA}")
    assert terminal.status_code == 200
    assert terminal.json()["terminal_projection_fingerprint"] == SHA
