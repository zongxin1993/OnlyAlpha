from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import onlyalpha_agent_orchestrator.runtime as runtime_module
import pytest
from onlyalpha_agent_orchestrator import (
    ONLY_AGENT_WORKFLOW_ID,
    ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1,
    ONLY_AGENT_WORKFLOW_SEMANTIC_VERSION,
    OnlyAgentOrchestratorOperationalConfigV1,
    OnlyAgentWorkflowResourceSpecV1,
    assert_current_runtime_admitted_for_session,
    build_current_agent_workflow_implementation_manifest,
    build_current_agent_workflow_runtime_resources,
)
from onlyalpha_agent_orchestrator.closure import _build_agent_workflow_runtime_resources

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


def test_production_closure_loads_exact_packaged_bytes_and_is_canonically_ordered() -> None:
    resources = build_current_agent_workflow_runtime_resources()
    identities = tuple(item.logical_resource_identity for item in resources)
    assert identities == tuple(item.logical_resource_identity for item in ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1)
    assert identities == tuple(sorted(identities))
    closure = next(item for item in resources if item.logical_resource_identity.endswith(".closure.py"))
    assert closure.content == Path(runtime_module.__file__).with_name("closure.py").read_bytes()
    assert all(item.content for item in resources)


def test_manifest_is_deterministic_across_fresh_packaged_resource_construction(monkeypatch) -> None:
    monkeypatch.setattr(workflow_module, "only_packaged_build_provenance", _provenance)
    first = build_current_agent_workflow_implementation_manifest()
    second = build_current_agent_workflow_implementation_manifest()
    assert first == second
    assert first.implementation_fingerprint == second.implementation_fingerprint


def test_resource_loading_and_manifest_identity_are_absolute_path_independent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(workflow_module, "only_packaged_build_provenance", _provenance)
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

    assert _manifest(load(roots[0])) == _manifest(load(roots[1]))


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


def test_unrelated_file_does_not_change_manifest(monkeypatch) -> None:
    monkeypatch.setattr(workflow_module, "only_packaged_build_provenance", _provenance)
    content = _bytes_by_locator()
    before = _manifest(_runtime_resources(content=content))
    content[("onlyalpha_agent_orchestrator", "operator_cli_formatting.py")] = b"unrelated mutation"
    after = _manifest(_runtime_resources(content=content))
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
    monkeypatch.setattr(workflow_module, "only_packaged_build_provenance", _provenance)
    current = build_current_agent_workflow_implementation_manifest()
    historical = OnlyAgentOrchestrationResourceV1(
        OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST,
        1,
        "1.0.0",
        current,
    )
    assert_current_runtime_admitted_for_session(historical.resource_fingerprint, _ResourceReader(historical))


def test_mismatch_blocks_before_hypothetical_external_side_effect(monkeypatch) -> None:
    monkeypatch.setattr(workflow_module, "only_packaged_build_provenance", _provenance)
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
    side_effects: list[str] = []
    with pytest.raises(OnlyAgentContextError) as raised:
        assert_current_runtime_admitted_for_session(historical.resource_fingerprint, _ResourceReader(historical))
        side_effects.append("external model/tool/product call")
    assert raised.value.code == "AGENT_WORKFLOW_RUNTIME_MISMATCH"
    assert side_effects == []


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
