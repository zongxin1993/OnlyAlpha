from __future__ import annotations

from dataclasses import replace

import pytest

import onlyalpha.research.agent.workflow as workflow_module
from onlyalpha.research.agent import (
    OnlyAgentBudgetV1,
    OnlyAgentContextError,
    OnlyAgentOrchestrationResourceKind,
    OnlyAgentOrchestrationResourceV1,
    OnlyAgentPromptTemplatePayloadV1,
    OnlyAgentRuntimeResourceV1,
    OnlyAgentSearchMethod,
    OnlyAgentWorkflowResourceKind,
    admit_agent_workflow_runtime,
    derive_agent_workflow_implementation_manifest,
)

from .support import make_context, packaged_provenance


def test_identity_is_deterministic_domain_separated_and_semantic(tmp_path) -> None:
    context = make_context(tmp_path)
    original = context.resources[0]
    same = OnlyAgentOrchestrationResourceV1.from_dict(original.to_dict())
    assert same == original

    payload = original.canonical_payload
    assert isinstance(payload, OnlyAgentPromptTemplatePayloadV1)
    changed = OnlyAgentOrchestrationResourceV1(
        original.resource_kind,
        1,
        "1.0.0",
        replace(payload, template_content="changed"),
    )
    assert changed.resource_fingerprint != original.resource_fingerprint
    other_kind = dict(original.to_dict())
    other_kind["resource_kind"] = OnlyAgentOrchestrationResourceKind.ROLE_POLICY.value
    with pytest.raises(ValueError):
        OnlyAgentOrchestrationResourceV1.from_dict(other_kind)


def test_strict_unknown_invalid_hash_enum_and_budget_are_rejected(tmp_path) -> None:
    context = make_context(tmp_path)
    payload = context.brief.to_dict()
    payload["unknown"] = True
    with pytest.raises(ValueError, match="fields are invalid"):
        type(context.brief).from_dict(payload)
    with pytest.raises(ValueError, match="AGENT_BUDGET_INVALID"):
        OnlyAgentBudgetV1(1, 1, 2)
    with pytest.raises(ValueError):
        replace(context.brief, catalog_generation_fingerprint="not-a-sha")
    brief_payload = context.brief.to_dict()
    brief_payload["allowed_search_methods"] = ["CAPABILITY_GAP"]
    with pytest.raises(ValueError):
        type(context.brief).from_dict(brief_payload)


def test_nested_structured_schema_content_is_immutable(tmp_path) -> None:
    context = make_context(tmp_path)
    schema = context.resources[1].canonical_payload
    with pytest.raises(TypeError):
        schema.exact_schema["type"] = "array"  # type: ignore[index, union-attr]
    required = schema.exact_schema["required"]  # type: ignore[union-attr]
    assert isinstance(required, tuple)


def test_catalog_dataset_and_evaluation_each_change_brief_identity(tmp_path) -> None:
    context = make_context(tmp_path)
    original = context.brief
    variants = (
        replace(original, catalog_generation_fingerprint="d" * 64, research_brief_fingerprint=""),
        replace(original, dataset_snapshot_fingerprint="d" * 64, research_brief_fingerprint=""),
        replace(
            original,
            evaluation_context_reference=replace(
                original.evaluation_context_reference, evaluation_fingerprint="d" * 64
            ),
            research_brief_fingerprint="",
        ),
    )
    assert len({original.research_brief_fingerprint, *(item.research_brief_fingerprint for item in variants)}) == 4


def test_set_semantics_require_canonical_order(tmp_path) -> None:
    context = make_context(tmp_path)
    with pytest.raises(ValueError, match="canonically ordered"):
        replace(
            context.brief,
            allowed_search_methods=(
                OnlyAgentSearchMethod.SYMBOLIC_SEARCH,
                OnlyAgentSearchMethod.REUSE_EXISTING,
            ),
            research_brief_fingerprint="",
        )


@pytest.mark.parametrize("change", ["bytes", "revision", "semantic_version", "distribution"])
def test_runtime_admission_requires_complete_exact_manifest(monkeypatch, tmp_path, change: str) -> None:
    context = make_context(tmp_path)
    workflow = context.resources[-1]
    historical = workflow.canonical_payload
    resources = (
        OnlyAgentRuntimeResourceV1(
            "onlyalpha.agent.workflow",
            OnlyAgentWorkflowResourceKind.SOURCE,
            b"def workflow(): return 'v1'\n" if change != "bytes" else b"changed\n",
        ),
    )
    provenance = packaged_provenance(
        revision="2" * 40 if change == "revision" else "1" * 40,
        version="0.9.10" if change == "distribution" else "0.9.9",
    )
    monkeypatch.setattr(workflow_module, "only_packaged_build_provenance", lambda: provenance)
    current = derive_agent_workflow_implementation_manifest(
        workflow_id="ONLYALPHA_AGENT_V1",
        workflow_semantic_version="2.0.0" if change == "semantic_version" else "1.0.0",
        runtime_resources=resources,
    )
    assert historical != current
    with pytest.raises(OnlyAgentContextError) as raised:
        admit_agent_workflow_runtime(workflow, current)
    assert raised.value.code == "AGENT_WORKFLOW_RUNTIME_MISMATCH"


def test_runtime_admission_passes_exact_manifest_and_does_not_affect_history(monkeypatch, tmp_path) -> None:
    context = make_context(tmp_path)
    workflow = context.resources[-1]
    monkeypatch.setattr(workflow_module, "only_packaged_build_provenance", packaged_provenance)
    current = derive_agent_workflow_implementation_manifest(
        workflow_id="ONLYALPHA_AGENT_V1",
        workflow_semantic_version="1.0.0",
        runtime_resources=(
            OnlyAgentRuntimeResourceV1(
                "onlyalpha.agent.workflow",
                OnlyAgentWorkflowResourceKind.SOURCE,
                b"def workflow(): return 'v1'\n",
            ),
        ),
    )
    admit_agent_workflow_runtime(workflow, current)


def test_workflow_derivation_consumes_packaged_offline_build_provenance(monkeypatch) -> None:
    monkeypatch.setattr(workflow_module, "only_packaged_build_provenance", packaged_provenance)
    manifest = derive_agent_workflow_implementation_manifest(
        workflow_id="ONLYALPHA_AGENT_V1",
        workflow_semantic_version="1.0.0",
        runtime_resources=(
            OnlyAgentRuntimeResourceV1(
                "onlyalpha.agent.workflow",
                OnlyAgentWorkflowResourceKind.SOURCE,
                b"explicit runtime bytes",
            ),
        ),
    )
    assert len(manifest.source_revision) == 40
    assert manifest.distribution_provenance[0].distribution_name == "onlyalpha"
    assert manifest.distribution_provenance[0].source_revision == manifest.source_revision


def test_workflow_derivation_fails_closed_without_packaged_provenance(monkeypatch) -> None:
    def unavailable():
        raise ValueError("ONLYALPHA_BUILD_PROVENANCE_UNAVAILABLE")

    monkeypatch.setattr(workflow_module, "only_packaged_build_provenance", unavailable)
    with pytest.raises(OnlyAgentContextError) as raised:
        derive_agent_workflow_implementation_manifest(
            workflow_id="ONLYALPHA_AGENT_V1",
            workflow_semantic_version="1.0.0",
            runtime_resources=(
                OnlyAgentRuntimeResourceV1(
                    "onlyalpha.agent.workflow",
                    OnlyAgentWorkflowResourceKind.SOURCE,
                    b"explicit runtime bytes",
                ),
            ),
        )
    assert raised.value.code == "BUILD_PROVENANCE_PREREQUISITE"
