from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import onlyalpha_agent_orchestrator.runtime as runtime_module
import pytest
from fastapi.testclient import TestClient
from onlyalpha_agent_orchestrator.adapters.product_api import OnlyProductApiContractV2
from onlyalpha_agent_orchestrator.node_app import create_agent_node_app
from onlyalpha_agent_orchestrator.node_main import main as node_main
from onlyalpha_agent_orchestrator.node_service import OnlyAgentNodeControlServiceV1
from onlyalpha_agent_orchestrator.production import OnlyAgentProductionRuntimeV1
from onlyalpha_agent_orchestrator.provenance import OnlyAgentOrchestratorPackagedBuildProvenanceV1
from onlyalpha_agent_orchestrator.semantic_bundle import load_production_semantic_bundle_v1

import onlyalpha.research.agent.workflow as workflow_module
from onlyalpha.build_provenance import OnlyPackagedBuildProvenanceV1
from onlyalpha.distribution import OnlyArtifactSourceProvenanceAuthority
from onlyalpha.research.agent.model import (
    OnlyAgentBudgetV1,
    OnlyAgentEvaluationContextReferenceV1,
    OnlyAgentResearchBriefV1,
    OnlyAgentResearchBriefV2,
    OnlyAgentSearchMethod,
    OnlyAgentStructuredHypothesisV1,
)
from onlyalpha.research.agent.occurrence import OnlyAgentContextReferenceV1
from onlyalpha.research.agent.store import (
    OnlyAgentCommitDisposition,
    OnlyAgentResearchBriefReferenceReadersV1,
    OnlyJsonAgentOrchestrationResourceStore,
    OnlyJsonAgentResearchBriefStore,
    OnlyJsonAgentSessionManifestStore,
)
from onlyalpha.research.experiment import OnlySearchBudgetV1

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


@pytest.fixture(autouse=True)
def _fixed_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT
    revision = "1" * 40
    monkeypatch.setattr(
        workflow_module,
        "only_packaged_build_provenance",
        lambda: OnlyPackagedBuildProvenanceV1(authority, "OnlyAlpha", revision, "onlyalpha", "0.9.9"),
    )
    monkeypatch.setattr(
        runtime_module,
        "only_agent_orchestrator_packaged_build_provenance",
        lambda: OnlyAgentOrchestratorPackagedBuildProvenanceV1(
            authority, "OnlyAlpha", revision, "onlyalpha-agent-orchestrator", "0.9.9"
        ),
    )


@dataclass(frozen=True)
class _Identity:
    generation_fingerprint: str = ""
    snapshot_fingerprint: str = ""
    evaluation_kind: str = ""
    evaluation_schema_version: int = 1
    evaluation_fingerprint: str = ""
    reference_kind: str = ""
    reference_schema_version: int = 1
    reference_fingerprint: str = ""

    @property
    def snapshot(self) -> _Identity:
        return self


class _References:
    def generation(self, fingerprint: str) -> _Identity:
        assert fingerprint == SHA_A
        return _Identity(generation_fingerprint=fingerprint)

    def load_verified_table(self, fingerprint: str) -> _Identity:
        assert fingerprint == SHA_B
        return _Identity(snapshot_fingerprint=fingerprint)

    def load_evaluation_context_verified(self, reference: OnlyAgentEvaluationContextReferenceV1) -> _Identity:
        assert reference.evaluation_fingerprint == SHA_C
        return _Identity(
            evaluation_kind=reference.evaluation_kind,
            evaluation_schema_version=reference.evaluation_schema_version,
            evaluation_fingerprint=reference.evaluation_fingerprint,
        )

    def load_search_authoring_reference_verified(self, reference: OnlyAgentContextReferenceV1) -> _Identity:
        assert reference in _brief_v2().ordered_search_authoring_references
        return _Identity(
            reference_kind=reference.reference_kind,
            reference_schema_version=reference.reference_schema_version,
            reference_fingerprint=reference.reference_fingerprint,
        )


class _Driver:
    def advance_once(self, _fingerprint: str):  # type: ignore[no-untyped-def]
        raise AssertionError("not used")


def _brief() -> OnlyAgentResearchBriefV1:
    return OnlyAgentResearchBriefV1(
        OnlyAgentStructuredHypothesisV1(
            "reversal",
            "Recent losers may reverse.",
            "Liquidity pressure is temporary.",
            "Lower lagged return predicts higher forward return.",
            ("liquid instruments",),
            ("rank IC is non-positive",),
        ),
        SHA_A,
        SHA_B,
        OnlyAgentEvaluationContextReferenceV1("ONLY_SYMBOLIC_RESEARCH_EVALUATION_CONTRACT", 1, SHA_C),
        (OnlyAgentSearchMethod.SYMBOLIC_SEARCH,),
        OnlyAgentBudgetV1(4, 8),
    )


def _brief_v2() -> OnlyAgentResearchBriefV2:
    original = _brief()
    return OnlyAgentResearchBriefV2(
        original.hypothesis,
        original.catalog_generation_fingerprint,
        original.dataset_snapshot_fingerprint,
        original.evaluation_context_reference,
        original.allowed_search_methods,
        original.agent_budget,
        OnlySearchBudgetV1(4, 3, 2),
        (
            OnlyAgentContextReferenceV1("SEARCH_ALGORITHM", 1, "d" * 64),
            OnlyAgentContextReferenceV1("SYMBOLIC_SEARCH_SPACE", 1, "e" * 64),
        ),
    )


def _service(root: Path) -> OnlyAgentNodeControlServiceV1:
    references = _References()
    readers = OnlyAgentResearchBriefReferenceReadersV1(references, references, references, references)
    resources = OnlyJsonAgentOrchestrationResourceStore(root)
    briefs = OnlyJsonAgentResearchBriefStore(root, readers)
    sessions = OnlyJsonAgentSessionManifestStore(root, briefs=briefs, resources=resources)
    return OnlyAgentNodeControlServiceV1(
        resources=resources,
        briefs=briefs,
        sessions=sessions,
        semantic_bundle=load_production_semantic_bundle_v1(),
        driver=_Driver(),  # type: ignore[arg-type]
    )


def test_session_admission_is_put_once_and_converges_to_one_identity(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.admit_session(_brief())
    second = service.admit_session(_brief())
    assert first.session_fingerprint == second.session_fingerprint
    assert first.session_disposition is OnlyAgentCommitDisposition.CREATED
    assert second.session_disposition is OnlyAgentCommitDisposition.REUSED


def test_private_control_requires_operational_bearer_without_leaking_it(tmp_path: Path) -> None:
    token = "private-secret-token"
    client = TestClient(create_agent_node_app(_service(tmp_path), control_bearer_token=token, readiness=lambda: True))
    assert client.get("/internal/v1/healthz").json() == {"status": "ALIVE"}
    assert client.get("/internal/v1/readyz").json() == {"status": "READY"}
    unauthorized = client.post("/internal/v1/sessions", json={"research_brief": _brief().to_dict()})
    assert unauthorized.status_code == 401
    assert token not in unauthorized.text
    admitted = client.post(
        "/internal/v1/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={"research_brief": _brief().to_dict()},
    )
    assert admitted.status_code == 200
    assert admitted.json()["session_disposition"] == "CREATED"


def test_private_control_admits_forward_only_brief_v2_and_preserves_budget(tmp_path: Path) -> None:
    token = "private-secret-token"
    service = _service(tmp_path)
    client = TestClient(create_agent_node_app(service, control_bearer_token=token, readiness=lambda: True))
    brief = _brief_v2()
    admitted = client.post(
        "/internal/v1/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={"research_brief": brief.to_dict()},
    )
    assert admitted.status_code == 200
    assert admitted.json()["research_brief_fingerprint"] == brief.research_brief_fingerprint


def test_process_entrypoint_rejects_unsupported_replicas_before_loading_secrets(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="AGENT_UNSUPPORTED_REPLICA_COUNT"):
        node_main(
            [
                "serve",
                "--durable-root",
                str(tmp_path / "state"),
                "--coordination-root",
                str(tmp_path / "locks"),
                "--product-api-url",
                "http://product.invalid",
                "--product-api-contract",
                str(tmp_path / "missing-contract"),
                "--product-token-file",
                str(tmp_path / "missing-product-secret"),
                "--model-api-url",
                "http://model.invalid",
                "--model-token-file",
                str(tmp_path / "missing-model-secret"),
                "--control-token-file",
                str(tmp_path / "missing-control-secret"),
                "--replica-count",
                "2",
            ]
        )


def test_production_readiness_reproves_local_roots_workflow_and_product_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    durable = tmp_path / "durable"
    coordination = tmp_path / "coordination"
    durable.mkdir()
    coordination.mkdir()
    contract = tmp_path / "openapi.json"
    canonical_contract = Path(__file__).resolve().parents[3] / "contracts/product-api/v2/openapi.json"
    contract.write_bytes(canonical_contract.read_bytes())

    parsed = OnlyProductApiContractV2(contract)
    workflow = runtime_module.build_current_agent_workflow_implementation_manifest()
    runtime = OnlyAgentProductionRuntimeV1(
        _service(tmp_path / "service"),
        workflow.implementation_fingerprint,
        durable,
        coordination,
        contract,
        parsed.fingerprint,
    )
    assert runtime.is_ready()

    coordination.rmdir()
    assert not runtime.is_ready()
    coordination.mkdir()
    contract.write_text("{}", encoding="utf-8")
    assert not runtime.is_ready()

    contract.write_bytes(canonical_contract.read_bytes())
    monkeypatch.setattr(
        "onlyalpha_agent_orchestrator.production.build_current_agent_workflow_implementation_manifest",
        lambda: type("Manifest", (), {"implementation_fingerprint": "0" * 64})(),
    )
    assert not runtime.is_ready()
