from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import onlyalpha_agent_orchestrator.runtime as runtime_module
import pytest
from fastapi.testclient import TestClient
from onlyalpha_agent_orchestrator.adapters.product_api import OnlyProductApiContractV2
from onlyalpha_agent_orchestrator.config import OnlyOpenAICompatibleEndpointConfigV1
from onlyalpha_agent_orchestrator.node_app import create_agent_node_app
from onlyalpha_agent_orchestrator.node_main import main as node_main
from onlyalpha_agent_orchestrator.node_service import OnlyAgentNodeControlServiceV1
from onlyalpha_agent_orchestrator.production import OnlyAgentProductionRuntimeV1
from onlyalpha_agent_orchestrator.provenance import OnlyAgentOrchestratorPackagedBuildProvenanceV1
from onlyalpha_agent_orchestrator.provider_integration import (
    OnlyAgentModelProfileV1,
    OnlyAgentSessionProviderBindingV1,
    OnlyJsonAgentModelProfileStoreV1,
    OnlyJsonAgentProviderBindingStoreV1,
    OnlyResolvedAgentProviderRuntimeV1,
)
from onlyalpha_agent_orchestrator.semantic_bundle import load_production_semantic_bundle_v1

import onlyalpha.research.agent.workflow as workflow_module
from onlyalpha.application.integration_configuration import OnlyIntegrationId
from onlyalpha.application.integration_runtime import OnlyIntegrationRuntimeBindingV1
from onlyalpha.build_provenance import OnlyPackagedBuildProvenanceV1
from onlyalpha.canonical import only_canonical_json
from onlyalpha.distribution import OnlyArtifactSourceProvenanceAuthority
from onlyalpha.plugin.integration import OnlyIntegrationCategory
from onlyalpha.research.agent.model import (
    OnlyAgentBudgetV1,
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
from onlyalpha.research.experiment.model import OnlySearchEvaluationContextReferenceV1

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

    def load_evaluation_context_verified(self, reference: OnlySearchEvaluationContextReferenceV1) -> _Identity:
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
        OnlySearchEvaluationContextReferenceV1("ONLY_SYMBOLIC_RESEARCH_EVALUATION_CONTRACT", 1, SHA_C),
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


def _service(
    root: Path,
    *,
    driver: object | None = None,
    provider_runtime: object | None = None,
    provider_resolver: object | None = None,
    provider_driver_factory: object | None = None,
) -> OnlyAgentNodeControlServiceV1:
    references = _References()
    readers = OnlyAgentResearchBriefReferenceReadersV1(references, references, references, references)
    resources = OnlyJsonAgentOrchestrationResourceStore(root)
    briefs = OnlyJsonAgentResearchBriefStore(root, readers)
    sessions = OnlyJsonAgentSessionManifestStore(root, briefs=briefs, resources=resources)
    selected_driver = _Driver() if driver is None else driver
    return OnlyAgentNodeControlServiceV1(
        resources=resources,
        briefs=briefs,
        sessions=sessions,
        semantic_bundle=load_production_semantic_bundle_v1(),
        driver=selected_driver,  # type: ignore[arg-type]
        provider_runtime=provider_runtime,  # type: ignore[arg-type]
        provider_resolver=provider_resolver,  # type: ignore[arg-type]
        provider_bindings=(None if provider_runtime is None else OnlyJsonAgentProviderBindingStoreV1(root)),
        model_profiles=(None if provider_runtime is None else OnlyJsonAgentModelProfileStoreV1(root)),
        product_contract_fingerprint=(None if provider_runtime is None else SHA_C),
        provider_driver_factory=(
            None if provider_runtime is None else (provider_driver_factory or (lambda _endpoint: selected_driver))
        ),  # type: ignore[arg-type]
    )


def test_session_admission_is_put_once_and_converges_to_one_identity(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.admit_session(_brief())
    second = service.admit_session(_brief())
    assert first.session_fingerprint == second.session_fingerprint
    assert first.session_disposition is OnlyAgentCommitDisposition.CREATED
    assert second.session_disposition is OnlyAgentCommitDisposition.REUSED


def test_canonical_session_admission_persists_and_revalidates_exact_provider_binding(tmp_path: Path) -> None:
    binding = OnlyIntegrationRuntimeBindingV1(
        OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
        "d" * 64,
        "openai.compatible.agent_provider",
        OnlyIntegrationCategory.AGENT_PROVIDER,
        "e" * 64,
        "f" * 64,
    )
    profile = OnlyAgentModelProfileV1(
        binding.integration_id.value,
        binding.revision_fingerprint,
        binding.runtime_configuration_fingerprint,
        "model-a",
        "2026-09-01",
        ("CHAT", "STRUCTURED_OUTPUT"),
    )
    provider_runtime = OnlyResolvedAgentProviderRuntimeV1(
        binding,
        profile,
        OnlyOpenAICompatibleEndpointConfigV1(
            "https://provider.example/v1",
            "NEVER_PERSIST_RUNTIME_SECRET",
            "openai-compatible",
            profile.model_id,
            profile.model_version,
        ),
    )

    class ProviderResolver:
        calls = 0
        runtime = provider_runtime

        def continue_exact(
            self, persisted: OnlyAgentSessionProviderBindingV1, selected: OnlyAgentModelProfileV1
        ) -> OnlyResolvedAgentProviderRuntimeV1:
            self.calls += 1
            assert persisted.provider_binding == binding
            assert selected == profile
            return self.runtime

    class Driver:
        calls = 0

        def advance_once(self, _fingerprint: str):  # type: ignore[no-untyped-def]
            self.calls += 1
            return _Identity()

    resolver = ProviderResolver()
    driver = Driver()
    service = _service(
        tmp_path,
        driver=driver,
        provider_runtime=provider_runtime,
        provider_resolver=resolver,
    )
    admitted = service.admit_session(_brief())
    persisted = OnlyJsonAgentProviderBindingStoreV1(tmp_path).load(admitted.session_fingerprint)

    assert persisted.provider_binding == binding
    assert persisted.model_profile_fingerprint == profile.model_profile_fingerprint
    assert "NEVER_PERSIST_RUNTIME_SECRET" not in str(persisted.to_dict())
    service.advance_once(admitted.session_fingerprint)
    assert resolver.calls == 1 and driver.calls == 1

    manifest_path = (
        tmp_path / "research/agent-orchestration/provider-bindings" / admitted.session_fingerprint / "manifest.json"
    )
    for workflow_fingerprint, product_fingerprint in (
        ("9" * 64, SHA_C),
        (persisted.workflow_manifest_fingerprint, "9" * 64),
    ):
        mismatched = OnlyAgentSessionProviderBindingV1(
            admitted.session_fingerprint,
            workflow_fingerprint,
            product_fingerprint,
            binding,
            profile.model_profile_fingerprint,
        )
        manifest_path.write_text(only_canonical_json(mismatched.to_dict()), encoding="utf-8")
        with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_MISMATCH"):
            service.advance_once(admitted.session_fingerprint)
    assert resolver.calls == 1 and driver.calls == 1


def test_restarted_node_runs_old_and_new_sessions_with_their_own_exact_provider(tmp_path: Path) -> None:
    def runtime(marker: str, model_id: str) -> OnlyResolvedAgentProviderRuntimeV1:
        binding = OnlyIntegrationRuntimeBindingV1(
            OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
            marker * 64,
            "openai.compatible.agent_provider",
            OnlyIntegrationCategory.AGENT_PROVIDER,
            "e" * 64,
            ("1" if marker == "a" else "2") * 64,
        )
        profile = OnlyAgentModelProfileV1(
            binding.integration_id.value,
            binding.revision_fingerprint,
            binding.runtime_configuration_fingerprint,
            model_id,
            "2026-09-01",
            ("CHAT", "STRUCTURED_OUTPUT"),
        )
        return OnlyResolvedAgentProviderRuntimeV1(
            binding,
            profile,
            OnlyOpenAICompatibleEndpointConfigV1(
                f"https://{model_id}.example/v1",
                f"secret-{model_id}",
                "openai-compatible",
                model_id,
                "2026-09-01",
            ),
        )

    r1 = runtime("a", "model-a")
    r2 = runtime("b", "model-b")
    runtimes = {item.binding.revision_fingerprint: item for item in (r1, r2)}

    class Resolver:
        def continue_exact(self, binding, profile):  # type: ignore[no-untyped-def]
            resolved = runtimes[binding.provider_binding.revision_fingerprint]
            assert resolved.model_profile == profile
            return resolved

    used_models: list[str] = []

    class Driver:
        def __init__(self, model_id: str) -> None:
            self._model_id = model_id

        def advance_once(self, _session_fingerprint: str):  # type: ignore[no-untyped-def]
            used_models.append(self._model_id)
            return _Identity()

    def driver_for(endpoint):  # type: ignore[no-untyped-def]
        return Driver(endpoint.expected_model_id)

    first_node = _service(
        tmp_path,
        provider_runtime=r1,
        provider_resolver=Resolver(),
        provider_driver_factory=driver_for,
    )
    s1 = first_node.admit_session(_brief())
    restarted_node = _service(
        tmp_path,
        provider_runtime=r2,
        provider_resolver=Resolver(),
        provider_driver_factory=driver_for,
    )
    s2 = restarted_node.admit_session(_brief_v2())

    restarted_node.advance_once(s1.session_fingerprint)
    restarted_node.advance_once(s2.session_fingerprint)

    assert used_models == ["model-a", "model-b"]


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


def test_unconfigured_node_is_alive_but_rejects_readiness_and_operations(tmp_path: Path) -> None:
    client = TestClient(
        create_agent_node_app(
            None,
            control_bearer_token=None,
            readiness=lambda: False,
            configured=False,
        )
    )
    assert client.get("/internal/v1/healthz").json() == {"status": "ALIVE"}
    ready = client.get("/internal/v1/readyz")
    assert ready.status_code == 503
    assert ready.json() == {"detail": "AGENT_NOT_CONFIGURED"}
    rejected = client.post("/internal/v1/sessions", json={"research_brief": _brief().to_dict()})
    assert rejected.status_code == 503
    assert rejected.json() == {"detail": "AGENT_NOT_CONFIGURED"}


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
                "--model-configuration-mode",
                "LEGACY",
                "--model-token-file",
                str(tmp_path / "missing-model-secret"),
                "--control-token-file",
                str(tmp_path / "missing-control-secret"),
                "--replica-count",
                "2",
            ]
        )


def test_process_entrypoint_canonical_mode_uses_injected_integration_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    product_token = tmp_path / "product-token"
    control_token = tmp_path / "control-token"
    runtime_token = tmp_path / "runtime-token"
    profile_path = tmp_path / "model-profile.json"
    product_token.write_text("product-secret\n", encoding="utf-8")
    control_token.write_text("control-secret\n", encoding="utf-8")
    runtime_token.write_text("runtime-secret\n", encoding="utf-8")
    binding = OnlyIntegrationRuntimeBindingV1(
        OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
        "d" * 64,
        "openai.compatible.agent_provider",
        OnlyIntegrationCategory.AGENT_PROVIDER,
        "e" * 64,
        "f" * 64,
    )
    profile = OnlyAgentModelProfileV1(
        binding.integration_id.value,
        binding.revision_fingerprint,
        binding.runtime_configuration_fingerprint,
        "onlyalpha-research-v1",
        "2026-09-01",
        ("CHAT", "STRUCTURED_OUTPUT"),
    )
    profile_path.write_text(only_canonical_json(profile.to_dict()), encoding="utf-8")
    called: dict[str, object] = {}

    class Runtime:
        control = _service(tmp_path / "control")

        @staticmethod
        def is_ready() -> bool:
            return True

    def compose(_cls, **kwargs):  # type: ignore[no-untyped-def]
        called.update(kwargs)
        return Runtime()

    monkeypatch.setattr(OnlyAgentProductionRuntimeV1, "compose_from_integration", classmethod(compose))
    monkeypatch.setattr("onlyalpha_agent_orchestrator.node_main.uvicorn.run", lambda *_args, **_kwargs: None)

    assert (
        node_main(
            [
                "serve",
                "--durable-root",
                str((tmp_path / "state").resolve()),
                "--coordination-root",
                str((tmp_path / "locks").resolve()),
                "--product-api-url",
                "http://product.invalid",
                "--product-api-contract",
                str((tmp_path / "product-openapi.json").resolve()),
                "--product-token-file",
                str(product_token.resolve()),
                "--control-token-file",
                str(control_token.resolve()),
                "--model-configuration-mode",
                "INTEGRATION_REVISION",
                "--integration-runtime-authority-url",
                "http://runtime-authority.invalid/internal/v1/agent-provider-runtime",
                "--integration-runtime-authority-token-file",
                str(runtime_token.resolve()),
                "--model-profile-file",
                str(profile_path.resolve()),
            ],
        )
        == 0
    )
    assert called["provider_resolver"].__class__.__name__ == "OnlyHttpAgentProviderRuntimeAuthorityV1"
    assert called["model_profile"] == profile


def test_process_entrypoint_rejects_mixed_model_configuration_modes(tmp_path: Path) -> None:
    for name in ("product", "model", "control"):
        (tmp_path / name).write_text(f"{name}-secret\n", encoding="utf-8")

    with pytest.raises(ValueError, match="CONFIGURATION_MODE_CONFLICT"):
        node_main(
            [
                "serve",
                "--durable-root",
                str((tmp_path / "state").resolve()),
                "--coordination-root",
                str((tmp_path / "locks").resolve()),
                "--product-api-url",
                "http://product.invalid",
                "--product-api-contract",
                str((tmp_path / "product-openapi.json").resolve()),
                "--product-token-file",
                str((tmp_path / "product").resolve()),
                "--control-token-file",
                str((tmp_path / "control").resolve()),
                "--model-configuration-mode",
                "INTEGRATION_REVISION",
                "--model-api-url",
                "http://model.invalid",
                "--model-token-file",
                str((tmp_path / "model").resolve()),
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
