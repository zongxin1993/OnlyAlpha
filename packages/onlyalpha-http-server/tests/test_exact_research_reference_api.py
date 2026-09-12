from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server.research.exact_reference_routes import create_exact_reference_router

SHA = "a" * 64


@dataclass(frozen=True)
class _Dataset:
    snapshot_fingerprint: str


@dataclass(frozen=True)
class _Evaluation:
    evaluation_contract_fingerprint: str
    schema_version: int = 1


class _Datasets:
    def load(self, fingerprint: str) -> _Dataset:
        return _Dataset(fingerprint)


class _Evaluations:
    def load_evaluation_contract_intrinsic_verified(self, fingerprint: str) -> _Evaluation:
        return _Evaluation(fingerprint)


def test_exact_brief_reference_routes_project_only_verified_identities() -> None:
    app = FastAPI()
    app.include_router(create_exact_reference_router(_Datasets(), _Evaluations()))
    client = TestClient(app)
    dataset = client.get(f"/api/v2/research/datasets/{SHA}")
    assert dataset.status_code == 200
    assert dataset.json() == {"schema_version": 1, "snapshot_fingerprint": SHA}
    evaluation = client.get(f"/api/v2/research/evaluations/ONLY_SYMBOLIC_RESEARCH_EVALUATION_CONTRACT/1/{SHA}")
    assert evaluation.status_code == 200
    assert evaluation.json() == {
        "schema_version": 1,
        "evaluation_kind": "ONLY_SYMBOLIC_RESEARCH_EVALUATION_CONTRACT",
        "evaluation_schema_version": 1,
        "evaluation_fingerprint": SHA,
    }
