"""Workflow implementation derivation and exact runtime admission."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from onlyalpha.build_provenance import OnlyPackagedBuildProvenanceV1, only_packaged_build_provenance

from .errors import OnlyAgentContextError
from .model import (
    OnlyAgentDistributionProvenanceV1,
    OnlyAgentOrchestrationResourceKind,
    OnlyAgentOrchestrationResourceV1,
    OnlyAgentWorkflowExecutableResourceV1,
    OnlyAgentWorkflowImplementationManifestV1,
    OnlyAgentWorkflowResourceKind,
)


@dataclass(frozen=True, slots=True)
class OnlyAgentRuntimeResourceV1:
    logical_resource_identity: str
    resource_kind: OnlyAgentWorkflowResourceKind
    content: bytes

    def __post_init__(self) -> None:
        if (
            not self.logical_resource_identity
            or any(character.isspace() for character in self.logical_resource_identity)
            or not isinstance(self.resource_kind, OnlyAgentWorkflowResourceKind)
            or not isinstance(self.content, bytes)
        ):
            raise ValueError("AGENT_RUNTIME_RESOURCE_INVALID")


def derive_agent_workflow_implementation_manifest(
    *,
    workflow_id: str,
    workflow_semantic_version: str,
    runtime_resources: tuple[OnlyAgentRuntimeResourceV1, ...],
    build_provenance: OnlyPackagedBuildProvenanceV1 | None = None,
) -> OnlyAgentWorkflowImplementationManifestV1:
    """Derive identity only from explicit bytes plus packaged offline provenance."""

    try:
        provenance = build_provenance or only_packaged_build_provenance()
    except Exception as exc:
        raise OnlyAgentContextError("BUILD_PROVENANCE_PREREQUISITE", str(exc)) from exc
    if not runtime_resources or len({item.logical_resource_identity for item in runtime_resources}) != len(
        runtime_resources
    ):
        raise OnlyAgentContextError("AGENT_WORKFLOW_MANIFEST_INVALID", "runtime resource identities")
    resources = tuple(
        sorted(
            (
                OnlyAgentWorkflowExecutableResourceV1(
                    item.logical_resource_identity,
                    item.resource_kind,
                    hashlib.sha256(item.content).hexdigest(),
                )
                for item in runtime_resources
            ),
            key=lambda item: item.logical_resource_identity,
        )
    )
    distribution = OnlyAgentDistributionProvenanceV1.from_packaged(provenance)
    return OnlyAgentWorkflowImplementationManifestV1(
        workflow_id,
        workflow_semantic_version,
        provenance.source_revision,
        resources,
        (distribution,),
    )


def admit_agent_workflow_runtime(
    historical_workflow_resource: OnlyAgentOrchestrationResourceV1,
    current_manifest: OnlyAgentWorkflowImplementationManifestV1,
) -> None:
    """Admit execution only on complete historical/current manifest equality."""

    if (
        historical_workflow_resource.resource_kind
        is not OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST
        or not isinstance(
            historical_workflow_resource.canonical_payload,
            OnlyAgentWorkflowImplementationManifestV1,
        )
        or historical_workflow_resource.canonical_payload != current_manifest
    ):
        raise OnlyAgentContextError(
            "AGENT_WORKFLOW_RUNTIME_MISMATCH",
            historical_workflow_resource.resource_fingerprint,
        )


__all__ = [
    "OnlyAgentRuntimeResourceV1",
    "admit_agent_workflow_runtime",
    "derive_agent_workflow_implementation_manifest",
]
