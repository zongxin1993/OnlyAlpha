from __future__ import annotations

import copy
import dataclasses
import json
import pickle
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import onlyalpha_agent_orchestrator.runtime as runtime_module
import pytest
from onlyalpha_agent_orchestrator import (
    ONLY_AGENT_WORKFLOW_ID,
    ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1,
    ONLY_AGENT_WORKFLOW_SEMANTIC_VERSION,
    OnlyAgentAdmittedRuntimeV1,
    OnlyAgentOrchestratorOperationalConfigV1,
    OnlyAgentRuntimeExecutionPermit,
    OnlyAgentWorkflowResourceSpecV1,
    assert_current_runtime_admitted_for_session,
    assert_runtime_execution_permit,
    build_current_agent_workflow_implementation_manifest,
    build_current_agent_workflow_runtime_resources,
    execute_after_runtime_admission,
)
from onlyalpha_agent_orchestrator.closure import _build_agent_workflow_runtime_resources
from onlyalpha_agent_orchestrator.provenance import (
    OnlyAgentOrchestratorPackagedBuildProvenanceV1,
)

import onlyalpha.research.agent.workflow as workflow_module
from onlyalpha.build_provenance import OnlyPackagedBuildProvenanceV1
from onlyalpha.distribution import OnlyArtifactSourceProvenanceAuthority
from onlyalpha.research.agent import (
    OnlyAgentContextError,
    OnlyAgentOrchestrationResourceKind,
    OnlyAgentOrchestrationResourceV1,
    OnlyAgentWorkflowExecutableResourceV1,
    OnlyAgentWorkflowImplementationManifestV1,
    derive_agent_workflow_implementation_manifest,
)


def _provenance(revision: str = "1" * 40) -> OnlyPackagedBuildProvenanceV1:
    return OnlyPackagedBuildProvenanceV1(
        OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        "OnlyAlpha",
        revision,
        "onlyalpha",
        "0.9.9",
    )


def _orchestrator_provenance(
    revision: str = "1" * 40,
    version: str = "0.9.9",
) -> OnlyAgentOrchestratorPackagedBuildProvenanceV1:
    return OnlyAgentOrchestratorPackagedBuildProvenanceV1(
        OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        "OnlyAlpha",
        revision,
        "onlyalpha-agent-orchestrator",
        version,
    )


@pytest.fixture(autouse=True)
def _fixed_packaged_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow_module, "only_packaged_build_provenance", _provenance)
    monkeypatch.setattr(
        runtime_module,
        "only_agent_orchestrator_packaged_build_provenance",
        _orchestrator_provenance,
    )


def _bytes_by_locator(
    declaration: tuple[OnlyAgentWorkflowResourceSpecV1, ...] = ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1,
) -> dict[tuple[str, str], bytes]:
    return {
        (item.package, item.relative_name): f"semantic bytes for {item.logical_resource_identity}\n".encode()
        for item in declaration
    }


def _runtime_resources(
    declaration: tuple[OnlyAgentWorkflowResourceSpecV1, ...] = ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1,
    content: dict[tuple[str, str], bytes] | None = None,
):
    values = _bytes_by_locator(declaration) if content is None else content
    return _build_agent_workflow_runtime_resources(declaration, lambda package, name: values[(package, name)])


def _manifest(resources):
    return derive_agent_workflow_implementation_manifest(
        workflow_id=ONLY_AGENT_WORKFLOW_ID,
        workflow_semantic_version=ONLY_AGENT_WORKFLOW_SEMANTIC_VERSION,
        runtime_resources=resources,
    )


class _ResourceReader:
    def __init__(self, resource: OnlyAgentOrchestrationResourceV1) -> None:
        self.resource = resource

    def load_resource_verified(self, resource_kind, resource_fingerprint):  # type: ignore[no-untyped-def]
        assert resource_kind is OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST
        assert resource_fingerprint == self.resource.resource_fingerprint
        return self.resource


class _SessionReader:
    def __init__(
        self,
        resource: OnlyAgentOrchestrationResourceV1,
        session_fingerprint: str = "1" * 64,
    ) -> None:
        self.context = SimpleNamespace(
            session=SimpleNamespace(session_fingerprint=session_fingerprint),
            workflow_resource=resource,
        )

    def load_session_manifest_verified(self, session_fingerprint):  # type: ignore[no-untyped-def]
        assert session_fingerprint == self.context.session.session_fingerprint
        return self.context


def test_production_closure_loads_exact_packaged_bytes_and_is_canonically_ordered() -> None:
    resources = build_current_agent_workflow_runtime_resources()
    identities = tuple(item.logical_resource_identity for item in resources)
    assert identities == tuple(item.logical_resource_identity for item in ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1)
    assert identities == tuple(sorted(identities))
    closure = next(item for item in resources if item.logical_resource_identity.endswith(".closure.py"))
    assert closure.content == Path(runtime_module.__file__).with_name("closure.py").read_bytes()
    assert all(item.content for item in resources)


def test_manifest_is_deterministic_across_fresh_packaged_resource_construction(monkeypatch) -> None:
    first = build_current_agent_workflow_implementation_manifest()
    second = build_current_agent_workflow_implementation_manifest()
    assert first == second
    assert first.implementation_fingerprint == second.implementation_fingerprint
    assert tuple(item.distribution_name for item in first.distribution_provenance) == (
        "onlyalpha",
        "onlyalpha-agent-orchestrator",
    )


def test_resource_loading_and_manifest_identity_are_absolute_path_independent(monkeypatch, tmp_path: Path) -> None:
    roots = (tmp_path / "checkout-a", tmp_path / "different" / "installed-b")
    for root in roots:
        for spec in ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1:
            target = root / spec.package.replace(".", "/") / spec.relative_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f"semantic bytes for {spec.logical_resource_identity}\n".encode())

    def load(root: Path):
        return _build_agent_workflow_runtime_resources(
            ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1,
            lambda package, name: (root / package.replace(".", "/") / name).read_bytes(),
        )

    manifests = []
    for root in roots:
        monkeypatch.setattr(
            runtime_module, "build_current_agent_workflow_runtime_resources", lambda root=root: load(root)
        )
        manifests.append(build_current_agent_workflow_implementation_manifest())
    assert manifests[0] == manifests[1]


@pytest.mark.parametrize(
    "logical_identity",
    (
        "onlyalpha.research.agent.application.py",
        "onlyalpha.build_provenance.py",
        "onlyalpha.research.agent.semantic_translation.py",
        "onlyalpha.research.agent.occurrence_service.py",
        "onlyalpha.research.agent.session_state.py",
        "onlyalpha.research.agent.occurrence.py",
    ),
)
def test_each_required_semantic_category_mutation_changes_manifest(monkeypatch, logical_identity: str) -> None:
    monkeypatch.setattr(workflow_module, "only_packaged_build_provenance", _provenance)
    original = _bytes_by_locator()
    changed = dict(original)
    spec = next(
        item for item in ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1 if item.logical_resource_identity == logical_identity
    )
    changed[(spec.package, spec.relative_name)] += b"semantic mutation\n"
    assert (
        _manifest(_runtime_resources(content=original)).implementation_fingerprint
        != _manifest(_runtime_resources(content=changed)).implementation_fingerprint
    )


@pytest.mark.parametrize("mutation", ("add", "remove", "replace"))
def test_closure_declaration_mutation_changes_manifest(monkeypatch, mutation: str) -> None:
    monkeypatch.setattr(workflow_module, "only_packaged_build_provenance", _provenance)
    original_declaration = ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1
    if mutation == "add":
        candidate = (*original_declaration, OnlyAgentWorkflowResourceSpecV1("onlyalpha.zzz.py", "onlyalpha", "zzz.py"))
        changed_declaration = tuple(sorted(candidate, key=lambda item: item.logical_resource_identity))
    elif mutation == "remove":
        changed_declaration = original_declaration[:-1]
    else:
        changed_declaration = tuple(
            replace(item, relative_name="replacement.py")
            if item.logical_resource_identity == "onlyalpha.research.agent.workflow.py"
            else item
            for item in original_declaration
        )
    original_content = _bytes_by_locator(original_declaration)
    changed_content = _bytes_by_locator(changed_declaration)
    closure_locator = ("onlyalpha_agent_orchestrator", "closure.py")
    changed_content[closure_locator] = repr(changed_declaration).encode()
    assert (
        _manifest(_runtime_resources(original_declaration, original_content)).implementation_fingerprint
        != _manifest(_runtime_resources(changed_declaration, changed_content)).implementation_fingerprint
    )


def test_noncanonical_declaration_order_fails_closed() -> None:
    declaration = tuple(reversed(ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1))
    with pytest.raises(OnlyAgentContextError) as raised:
        _runtime_resources(declaration)
    assert raised.value.code == "AGENT_ORCHESTRATION_RESOURCE_MISMATCH"


def test_undeclared_resource_does_not_change_executable_identity_under_fixed_provenance(monkeypatch) -> None:
    content = _bytes_by_locator()
    monkeypatch.setattr(
        runtime_module,
        "build_current_agent_workflow_runtime_resources",
        lambda: _runtime_resources(content=content),
    )
    before = build_current_agent_workflow_implementation_manifest()
    content[("onlyalpha_agent_orchestrator", "operator_cli_formatting.py")] = b"unrelated mutation"
    after = build_current_agent_workflow_implementation_manifest()
    assert before == after


@pytest.mark.parametrize("failure", (FileNotFoundError, PermissionError))
def test_missing_or_unreadable_required_resource_fails_closed(failure) -> None:  # type: ignore[no-untyped-def]
    def unavailable(package: str, name: str) -> bytes:
        raise failure(f"{package}:{name}")

    with pytest.raises(OnlyAgentContextError) as raised:
        _build_agent_workflow_runtime_resources(ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1, unavailable)
    assert raised.value.code == "AGENT_ORCHESTRATION_RESOURCE_MISSING"


def test_duplicate_identity_and_conflicting_locator_fail_closed() -> None:
    first = ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1[0]
    duplicate_identity = tuple(
        sorted((*ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1, first), key=lambda x: x.logical_resource_identity)
    )
    conflict = OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.copy.py", first.package, first.relative_name
    )
    duplicate_locator = tuple(
        sorted((*ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1, conflict), key=lambda x: x.logical_resource_identity)
    )
    for declaration in (duplicate_identity, duplicate_locator):
        with pytest.raises(OnlyAgentContextError) as raised:
            _runtime_resources(declaration)
        assert raised.value.code == "AGENT_ORCHESTRATION_RESOURCE_MISMATCH"


def test_unsupported_resource_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RESOURCE_SPEC_INVALID"):
        OnlyAgentWorkflowResourceSpecV1(
            "onlyalpha.agent.unsupported",
            "onlyalpha",
            "canonical.py",
            "BYTECODE",  # type: ignore[arg-type]
        )


def test_exact_historical_manifest_is_admitted(monkeypatch) -> None:
    current = build_current_agent_workflow_implementation_manifest()
    historical = OnlyAgentOrchestrationResourceV1(
        OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST,
        1,
        "1.0.0",
        current,
    )
    assert_current_runtime_admitted_for_session(
        historical.resource_fingerprint,
        _ResourceReader(historical),
    )


def test_runtime_admission_boundary_runs_matching_continuation_exactly_once(monkeypatch) -> None:
    current = build_current_agent_workflow_implementation_manifest()
    historical = OnlyAgentOrchestrationResourceV1(
        OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST,
        1,
        "1.0.0",
        current,
    )
    calls = 0
    minted = 0
    original_mint = runtime_module._mint_runtime_execution_permit

    def mint(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal minted
        minted += 1
        return original_mint(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "_mint_runtime_execution_permit", mint)

    def continuation(admitted):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        assert admitted.agent_session_fingerprint == "1" * 64
        assert admitted.historical_workflow_resource_fingerprint == historical.resource_fingerprint
        return admitted.workflow_implementation_fingerprint

    result = execute_after_runtime_admission(
        "1" * 64,
        _SessionReader(historical),  # type: ignore[arg-type]
        continuation,
    )
    assert result == current.implementation_fingerprint
    assert calls == 1
    assert minted == 1


def test_admitted_runtime_cannot_be_constructed_without_runtime_admission() -> None:
    with pytest.raises((TypeError, OnlyAgentContextError)):
        OnlyAgentAdmittedRuntimeV1(
            "1" * 64,
            "2" * 64,
            "3" * 64,
            "4" * 40,
        )


def test_fresh_runtime_import_does_not_execute_unrelated_onlyalpha_semantics() -> None:
    program = """
import json
import sys
import onlyalpha_agent_orchestrator.runtime
print(json.dumps(sorted(
    name for name in sys.modules
    if name == "onlyalpha" or name.startswith("onlyalpha.")
    or name == "onlyalpha_agent_orchestrator" or name.startswith("onlyalpha_agent_orchestrator.")
)))
"""
    loaded = set(json.loads(subprocess.check_output([sys.executable, "-c", program], text=True)))
    assert loaded == {
        "onlyalpha",
        "onlyalpha.application",
        "onlyalpha.application.product_command_receipt",
        "onlyalpha.build_provenance",
        "onlyalpha.canonical",
        "onlyalpha.distribution",
        "onlyalpha.research",
        "onlyalpha.research.agent",
        "onlyalpha.research.agent.application",
        "onlyalpha.research.agent.authority_state",
        "onlyalpha.research.agent.decision",
        "onlyalpha.research.agent.decision_store",
        "onlyalpha.research.agent.errors",
        "onlyalpha.research.agent.model",
        "onlyalpha.research.agent.occurrence",
        "onlyalpha.research.agent.occurrence_service",
        "onlyalpha.research.agent.occurrence_store",
        "onlyalpha.research.agent.semantic_translation",
        "onlyalpha.research.agent.session_state",
        "onlyalpha.research.agent.store",
        "onlyalpha.research.agent.verification",
        "onlyalpha.research.agent.workflow",
        "onlyalpha.research.experiment",
        "onlyalpha.research.experiment.model",
        "onlyalpha_agent_orchestrator",
        "onlyalpha_agent_orchestrator.closure",
        "onlyalpha_agent_orchestrator.provenance",
        "onlyalpha_agent_orchestrator.runtime",
    }


def test_runtime_execution_permit_rejects_wrong_seal_cross_session_and_reconstruction() -> None:
    with pytest.raises(OnlyAgentContextError, match="AGENT_POLICY_VIOLATION"):
        OnlyAgentRuntimeExecutionPermit("1" * 64, "2" * 64, "3" * 64, "4" * 40, _seal=object())

    current = build_current_agent_workflow_implementation_manifest()
    historical = OnlyAgentOrchestrationResourceV1(
        OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST,
        1,
        "1.0.0",
        current,
    )
    permit = execute_after_runtime_admission(
        "1" * 64,
        _SessionReader(historical),  # type: ignore[arg-type]
        lambda admitted: admitted,
    )
    assert type(permit) is OnlyAgentRuntimeExecutionPermit
    with pytest.raises(OnlyAgentContextError, match="AGENT_POLICY_VIOLATION"):
        assert_runtime_execution_permit(
            permit,
            agent_session_fingerprint="2" * 64,
            historical_workflow_resource_fingerprint=historical.resource_fingerprint,
            workflow_implementation_fingerprint=current.implementation_fingerprint,
            source_revision=current.source_revision,
        )
    with pytest.raises(OnlyAgentContextError, match="AGENT_POLICY_VIOLATION"):
        assert_runtime_execution_permit(
            permit,
            agent_session_fingerprint="1" * 64,
            historical_workflow_resource_fingerprint=historical.resource_fingerprint,
            workflow_implementation_fingerprint="0" * 64,
            source_revision=current.source_revision,
        )
    with pytest.raises(OnlyAgentContextError, match="AGENT_POLICY_VIOLATION"):
        assert_runtime_execution_permit(
            SimpleNamespace(
                agent_session_fingerprint="1" * 64,
                historical_workflow_resource_fingerprint=historical.resource_fingerprint,
                workflow_implementation_fingerprint=current.implementation_fingerprint,
                source_revision=current.source_revision,
            ),
            agent_session_fingerprint="1" * 64,
            historical_workflow_resource_fingerprint=historical.resource_fingerprint,
            workflow_implementation_fingerprint=current.implementation_fingerprint,
            source_revision=current.source_revision,
        )
    for reconstruct in (
        lambda: copy.copy(permit),
        lambda: copy.deepcopy(permit),
        lambda: pickle.dumps(permit),
        lambda: dataclasses.replace(permit),  # type: ignore[arg-type]
    ):
        with pytest.raises((TypeError, ValueError)):
            reconstruct()
    assert not hasattr(permit, "__dict__")
    assert not hasattr(permit, "to_dict")
    assert not hasattr(type(permit), "from_dict")
    with pytest.raises(AttributeError):
        permit.agent_session_fingerprint = "2" * 64  # type: ignore[misc]


def test_valid_permit_validation_requires_all_exact_bindings() -> None:
    current = build_current_agent_workflow_implementation_manifest()
    historical = OnlyAgentOrchestrationResourceV1(
        OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST,
        1,
        "1.0.0",
        current,
    )
    permit = execute_after_runtime_admission(
        "1" * 64,
        _SessionReader(historical),  # type: ignore[arg-type]
        lambda admitted: admitted,
    )
    assert_runtime_execution_permit(
        permit,
        agent_session_fingerprint="1" * 64,
        historical_workflow_resource_fingerprint=historical.resource_fingerprint,
        workflow_implementation_fingerprint=current.implementation_fingerprint,
        source_revision=current.source_revision,
    )


def test_public_package_imports_keep_canonical_objects_and_export_counts() -> None:
    import onlyalpha
    import onlyalpha.application as application
    import onlyalpha.research as research
    import onlyalpha.research.agent as agent
    import onlyalpha.research.experiment as experiment
    from onlyalpha.application.product_command_receipt import OnlyProductCommandId
    from onlyalpha.core.clock import OnlyClock
    from onlyalpha.research.agent.errors import OnlyAgentContextError as CanonicalAgentContextError
    from onlyalpha.research.experiment.model import OnlySearchBudgetV1
    from onlyalpha.research.workload import OnlyResearchWorkloadPlan

    assert len(onlyalpha.__all__) == 17
    assert len(research.__all__) == 518
    assert len(experiment.__all__) == 52
    assert len(agent.__all__) == 118
    assert len(application.__all__) == 21
    assert onlyalpha.OnlyClock is OnlyClock
    assert research.OnlyResearchWorkloadPlan is OnlyResearchWorkloadPlan
    assert experiment.OnlySearchBudgetV1 is OnlySearchBudgetV1
    assert agent.OnlyAgentContextError is CanonicalAgentContextError
    assert application.OnlyProductCommandId is OnlyProductCommandId


def test_mismatch_blocks_admission_continuation(monkeypatch) -> None:
    historical_manifest = _manifest(_runtime_resources())
    historical = OnlyAgentOrchestrationResourceV1(
        OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST,
        1,
        "1.0.0",
        historical_manifest,
    )
    current = _manifest(
        _runtime_resources(
            content={
                **_bytes_by_locator(),
                ("onlyalpha.research.agent", "application.py"): b"different executable semantics",
            }
        )
    )
    monkeypatch.setattr(runtime_module, "build_current_agent_workflow_implementation_manifest", lambda: current)
    calls = 0
    minted = 0
    original_mint = runtime_module._mint_runtime_execution_permit

    def mint(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal minted
        minted += 1
        return original_mint(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "_mint_runtime_execution_permit", mint)

    def continuation(_admitted):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1

    with pytest.raises(OnlyAgentContextError) as raised:
        execute_after_runtime_admission(
            "1" * 64,
            _SessionReader(historical),  # type: ignore[arg-type]
            continuation,
        )
    assert raised.value.code == "AGENT_WORKFLOW_RUNTIME_MISMATCH"
    assert calls == 0
    assert minted == 0


@pytest.mark.parametrize(
    "failure",
    ("missing_historical", "invalid_historical", "session_mismatch", "current_load"),
)
def test_admission_failures_never_reach_continuation(monkeypatch, failure: str) -> None:
    current = build_current_agent_workflow_implementation_manifest()
    historical = OnlyAgentOrchestrationResourceV1(
        OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST,
        1,
        "1.0.0",
        current,
    )
    reader: object = _SessionReader(historical)
    if failure == "missing_historical":
        reader = SimpleNamespace(
            load_session_manifest_verified=lambda *_args: (_ for _ in ()).throw(
                OnlyAgentContextError("AGENT_ORCHESTRATION_RESOURCE_MISSING", "historical workflow")
            )
        )
    elif failure == "invalid_historical":
        reader = SimpleNamespace(
            load_session_manifest_verified=lambda *_args: SimpleNamespace(
                session=SimpleNamespace(session_fingerprint="1" * 64),
                workflow_resource=SimpleNamespace(
                    resource_kind="INVALID",
                    canonical_payload=current,
                    resource_fingerprint="0" * 64,
                ),
            )
        )
    elif failure == "session_mismatch":
        reader = SimpleNamespace(
            load_session_manifest_verified=lambda *_args: SimpleNamespace(
                session=SimpleNamespace(session_fingerprint="2" * 64),
                workflow_resource=historical,
            )
        )
    else:
        monkeypatch.setattr(
            runtime_module,
            "build_current_agent_workflow_implementation_manifest",
            lambda: (_ for _ in ()).throw(
                OnlyAgentContextError("AGENT_ORCHESTRATION_RESOURCE_MISSING", "current workflow")
            ),
        )
    calls = 0
    minted = 0
    original_mint = runtime_module._mint_runtime_execution_permit

    def mint(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal minted
        minted += 1
        return original_mint(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "_mint_runtime_execution_permit", mint)

    def continuation(_admitted):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1

    with pytest.raises(OnlyAgentContextError):
        execute_after_runtime_admission(
            "1" * 64,
            reader,  # type: ignore[arg-type]
            continuation,
        )
    assert calls == 0
    assert minted == 0


def test_orchestrator_provenance_mismatch_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_module,
        "only_agent_orchestrator_packaged_build_provenance",
        lambda: _orchestrator_provenance("2" * 40),
    )
    with pytest.raises(OnlyAgentContextError) as raised:
        build_current_agent_workflow_implementation_manifest()
    assert raised.value.code == "BUILD_PROVENANCE_PREREQUISITE"


def test_orchestrator_distribution_version_changes_manifest_identity(monkeypatch) -> None:
    first = build_current_agent_workflow_implementation_manifest()
    monkeypatch.setattr(
        runtime_module,
        "only_agent_orchestrator_packaged_build_provenance",
        lambda: _orchestrator_provenance(version="0.9.10"),
    )
    second = build_current_agent_workflow_implementation_manifest()
    assert first.implementation_fingerprint != second.implementation_fingerprint


def test_operational_secret_is_not_semantic_serialized_or_represented(monkeypatch) -> None:
    monkeypatch.setattr(workflow_module, "only_packaged_build_provenance", _provenance)
    first = OnlyAgentOrchestratorOperationalConfigV1("https://product.invalid", "secret-one")
    second = OnlyAgentOrchestratorOperationalConfigV1("https://product.invalid", "secret-two")
    first_manifest = build_current_agent_workflow_implementation_manifest()
    second_manifest = build_current_agent_workflow_implementation_manifest()
    serialized = json.dumps(first_manifest.to_dict(), sort_keys=True)
    assert first != second
    assert first_manifest == second_manifest
    assert "secret-one" not in repr(first)
    assert "secret-one" not in serialized
    assert "secret-two" not in repr(second)


def test_invalid_runtime_resource_content_fails_closed() -> None:
    with pytest.raises(OnlyAgentContextError) as raised:
        _build_agent_workflow_runtime_resources(
            ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1,
            lambda _package, _name: b"",
        )
    assert raised.value.code == "AGENT_ORCHESTRATION_RESOURCE_MISMATCH"


def test_invalid_resource_or_implementation_fingerprint_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(workflow_module, "only_packaged_build_provenance", _provenance)
    manifest = _manifest(_runtime_resources())
    resource_payload = manifest.ordered_executable_resources[0].to_dict()
    resource_payload["byte_sha256"] = "invalid"
    with pytest.raises(ValueError, match="lower-case SHA256"):
        OnlyAgentWorkflowExecutableResourceV1.from_dict(resource_payload)
    manifest_payload = manifest.to_dict()
    manifest_payload["implementation_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="AGENT_WORKFLOW_IMPLEMENTATION_FINGERPRINT_MISMATCH"):
        OnlyAgentWorkflowImplementationManifestV1.from_dict(manifest_payload)
