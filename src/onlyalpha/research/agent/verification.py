"""Cross-Authority exact readers and immutable Agent-context verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .errors import OnlyAgentContextError
from .model import (
    OnlyAgentEvaluationContextReferenceV1,
    OnlyAgentOrchestrationResourceKind,
    OnlyAgentOrchestrationResourceV1,
    OnlyAgentResearchBriefV1,
    OnlyAgentRolePolicyPayloadV1,
    OnlyAgentSessionManifestV1,
    OnlyAgentStructuredOutputSchemaPayloadV1,
    OnlyAgentToolPolicyPayloadV1,
    OnlyAgentWorkflowImplementationManifestV1,
)


class OnlyAgentCatalogGenerationValue(Protocol):
    @property
    def generation_fingerprint(self) -> str: ...


class OnlyAgentCatalogGenerationReader(Protocol):
    def generation(self, fingerprint: str) -> OnlyAgentCatalogGenerationValue: ...


class OnlyAgentDatasetSnapshotValue(Protocol):
    @property
    def snapshot_fingerprint(self) -> str: ...


class OnlyAgentVerifiedDatasetValue(Protocol):
    @property
    def snapshot(self) -> OnlyAgentDatasetSnapshotValue: ...


class OnlyAgentDatasetSnapshotReader(Protocol):
    def load_verified_table(self, snapshot_fingerprint: str) -> OnlyAgentVerifiedDatasetValue: ...


class OnlyAgentEvaluationContextValue(Protocol):
    @property
    def evaluation_kind(self) -> str: ...

    @property
    def evaluation_schema_version(self) -> int: ...

    @property
    def evaluation_fingerprint(self) -> str: ...


class OnlyAgentEvaluationContextReader(Protocol):
    def load_evaluation_context_verified(
        self,
        reference: OnlyAgentEvaluationContextReferenceV1,
    ) -> OnlyAgentEvaluationContextValue: ...


class OnlyAgentOrchestrationResourceReader(Protocol):
    def load_resource_verified(
        self,
        resource_kind: OnlyAgentOrchestrationResourceKind,
        resource_fingerprint: str,
    ) -> OnlyAgentOrchestrationResourceV1: ...


class OnlyAgentResearchBriefReader(Protocol):
    def load_research_brief_verified(self, research_brief_fingerprint: str) -> OnlyAgentResearchBriefV1: ...


@dataclass(frozen=True, slots=True)
class OnlyAgentResearchBriefReferenceReadersV1:
    catalogs: OnlyAgentCatalogGenerationReader
    datasets: OnlyAgentDatasetSnapshotReader
    evaluations: OnlyAgentEvaluationContextReader


@dataclass(frozen=True, slots=True)
class OnlyVerifiedAgentDecisionContextV1:
    session: OnlyAgentSessionManifestV1
    research_brief: OnlyAgentResearchBriefV1
    workflow_resource: OnlyAgentOrchestrationResourceV1
    tool_policy_resource: OnlyAgentOrchestrationResourceV1
    ordered_role_policy_resources: tuple[OnlyAgentOrchestrationResourceV1, ...]
    supporting_resources: tuple[OnlyAgentOrchestrationResourceV1, ...]


def verify_agent_research_brief_references(
    brief: OnlyAgentResearchBriefV1,
    readers: OnlyAgentResearchBriefReferenceReadersV1,
) -> None:
    """Prove all external Authority references before a Brief is admitted."""

    try:
        catalog = readers.catalogs.generation(brief.catalog_generation_fingerprint)
        if catalog.generation_fingerprint != brief.catalog_generation_fingerprint:
            raise ValueError("Catalog reader returned a different identity")
        dataset = readers.datasets.load_verified_table(brief.dataset_snapshot_fingerprint)
        if dataset.snapshot.snapshot_fingerprint != brief.dataset_snapshot_fingerprint:
            raise ValueError("Dataset reader returned a different identity")
        evaluation = readers.evaluations.load_evaluation_context_verified(brief.evaluation_context_reference)
        reference = brief.evaluation_context_reference
        if (
            evaluation.evaluation_kind != reference.evaluation_kind
            or evaluation.evaluation_schema_version != reference.evaluation_schema_version
            or evaluation.evaluation_fingerprint != reference.evaluation_fingerprint
        ):
            raise ValueError("Evaluation reader returned a different identity")
    except Exception as exc:
        if isinstance(exc, OnlyAgentContextError):
            raise
        raise OnlyAgentContextError(
            "AGENT_RESEARCH_BRIEF_REFERENCE_INVALID",
            brief.research_brief_fingerprint,
        ) from exc


def verify_agent_session_bindings(
    session: OnlyAgentSessionManifestV1,
    *,
    briefs: OnlyAgentResearchBriefReader,
    resources: OnlyAgentOrchestrationResourceReader,
) -> OnlyVerifiedAgentDecisionContextV1:
    """Resolve and verify the complete historical static context without runtime state."""

    try:
        brief = briefs.load_research_brief_verified(session.research_brief_fingerprint)
        if brief.research_brief_fingerprint != session.research_brief_fingerprint:
            raise ValueError("Brief identity differs")
        workflow = resources.load_resource_verified(
            OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST,
            session.workflow_implementation_resource_fingerprint,
        )
        manifest = workflow.canonical_payload
        if not isinstance(manifest, OnlyAgentWorkflowImplementationManifestV1) or (
            manifest.workflow_id != session.agent_workflow_id
            or manifest.workflow_semantic_version != session.agent_workflow_semantic_version
            or manifest.implementation_fingerprint != session.agent_workflow_implementation_fingerprint
            or manifest.source_revision != session.agent_workflow_source_revision
        ):
            raise ValueError("Session workflow duplicated bindings differ")
        tool_policy = resources.load_resource_verified(
            OnlyAgentOrchestrationResourceKind.TOOL_POLICY,
            session.tool_policy_fingerprint,
        )
        if not isinstance(tool_policy.canonical_payload, OnlyAgentToolPolicyPayloadV1):
            raise ValueError("Session Tool Policy payload differs")
        role_resources = tuple(
            resources.load_resource_verified(OnlyAgentOrchestrationResourceKind.ROLE_POLICY, item)
            for item in session.ordered_role_policy_fingerprints
        )
        supporting: dict[str, OnlyAgentOrchestrationResourceV1] = {}
        seen_roles: set[str] = set()
        allowed_tools = set(tool_policy.canonical_payload.allowed_tool_classes)
        for role_resource in role_resources:
            role = role_resource.canonical_payload
            if not isinstance(role, OnlyAgentRolePolicyPayloadV1) or role.logical_role_id in seen_roles:
                raise ValueError("Role Policy set is invalid")
            seen_roles.add(role.logical_role_id)
            if not set(role.allowed_tool_classes).issubset(allowed_tools):
                raise ValueError("Role Tool subset exceeds Session Tool Policy")
            bindings = (
                (OnlyAgentOrchestrationResourceKind.PROMPT_TEMPLATE, role.allowed_prompt_template_fingerprints),
                (
                    OnlyAgentOrchestrationResourceKind.STRUCTURED_OUTPUT_SCHEMA,
                    role.allowed_structured_output_schema_fingerprints,
                ),
                (
                    OnlyAgentOrchestrationResourceKind.MODEL_EXECUTION_POLICY,
                    role.allowed_model_execution_policy_fingerprints,
                ),
            )
            for kind, fingerprints in bindings:
                for fingerprint in fingerprints:
                    supporting[fingerprint] = resources.load_resource_verified(kind, fingerprint)
        if any(
            resource.resource_kind is OnlyAgentOrchestrationResourceKind.STRUCTURED_OUTPUT_SCHEMA
            and not isinstance(resource.canonical_payload, OnlyAgentStructuredOutputSchemaPayloadV1)
            for resource in supporting.values()
        ):
            raise ValueError("Structured schema payload differs")
        return OnlyVerifiedAgentDecisionContextV1(
            session,
            brief,
            workflow,
            tool_policy,
            role_resources,
            tuple(supporting[key] for key in sorted(supporting)),
        )
    except Exception as exc:
        if isinstance(exc, OnlyAgentContextError) and exc.code in {
            "AGENT_RESEARCH_BRIEF_INVALID",
            "AGENT_RESEARCH_BRIEF_REFERENCE_INVALID",
        }:
            raise OnlyAgentContextError("AGENT_SESSION_RESOURCE_MISMATCH", session.session_fingerprint) from exc
        if isinstance(exc, OnlyAgentContextError) and exc.code.startswith("AGENT_ORCHESTRATION_RESOURCE_"):
            raise OnlyAgentContextError("AGENT_SESSION_RESOURCE_MISMATCH", session.session_fingerprint) from exc
        if isinstance(exc, OnlyAgentContextError):
            raise
        raise OnlyAgentContextError("AGENT_SESSION_RESOURCE_MISMATCH", session.session_fingerprint) from exc


__all__ = [
    name
    for name in globals()
    if name.startswith("OnlyAgent") or name.startswith("OnlyVerified") or name.startswith("verify_")
]
