"""Current Agent workflow manifest assembly and pre-I/O admission boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from onlyalpha.research.agent.errors import OnlyAgentContextError
from onlyalpha.research.agent.model import (
    OnlyAgentDistributionProvenanceV1,
    OnlyAgentOrchestrationResourceKind,
    OnlyAgentWorkflowImplementationManifestV1,
)
from onlyalpha.research.agent.occurrence_service import OnlyAgentSessionContextReader
from onlyalpha.research.agent.verification import OnlyAgentOrchestrationResourceReader
from onlyalpha.research.agent.workflow import (
    admit_agent_workflow_runtime,
    derive_agent_workflow_implementation_manifest,
)

from .closure import build_current_agent_workflow_runtime_resources
from .provenance import only_agent_orchestrator_packaged_build_provenance

ONLY_AGENT_WORKFLOW_ID = "ONLYALPHA_AGENT_V1"
ONLY_AGENT_WORKFLOW_SEMANTIC_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class OnlyAgentOrchestratorOperationalConfigV1:
    """Deployment-only values that never participate in Agent semantic identity."""

    product_api_endpoint: str
    product_api_bearer_token: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.product_api_endpoint or not self.product_api_bearer_token:
            raise ValueError("AGENT_ORCHESTRATOR_OPERATIONAL_CONFIG_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyAgentAdmittedRuntimeV1:
    """Ephemeral proof that one Session-bound workflow equals this runtime."""

    agent_session_fingerprint: str
    historical_workflow_resource_fingerprint: str
    workflow_implementation_fingerprint: str
    source_revision: str


def build_current_agent_workflow_implementation_manifest() -> OnlyAgentWorkflowImplementationManifestV1:
    """Derive the ADR 0123 manifest from the actual installed executable bytes."""

    core_manifest = derive_agent_workflow_implementation_manifest(
        workflow_id=ONLY_AGENT_WORKFLOW_ID,
        workflow_semantic_version=ONLY_AGENT_WORKFLOW_SEMANTIC_VERSION,
        runtime_resources=build_current_agent_workflow_runtime_resources(),
    )
    try:
        packaged = only_agent_orchestrator_packaged_build_provenance()
        orchestrator = OnlyAgentDistributionProvenanceV1(
            packaged.distribution_name,
            packaged.distribution_version,
            packaged.source_provenance_authority.value,
            packaged.source_repository,
            packaged.source_revision,
        )
        distributions = tuple(sorted((*core_manifest.distribution_provenance, orchestrator)))
        return OnlyAgentWorkflowImplementationManifestV1(
            core_manifest.workflow_id,
            core_manifest.workflow_semantic_version,
            core_manifest.source_revision,
            core_manifest.ordered_executable_resources,
            distributions,
        )
    except ValueError as exc:
        raise OnlyAgentContextError("BUILD_PROVENANCE_PREREQUISITE", str(exc)) from exc


def assert_current_runtime_admitted_for_session(
    historical_workflow_manifest_fingerprint: str,
    resource_reader: OnlyAgentOrchestrationResourceReader,
) -> None:
    """Fail before external Model/Tool/Product I/O unless current equals historical."""

    historical = resource_reader.load_resource_verified(
        OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST,
        historical_workflow_manifest_fingerprint,
    )
    current = build_current_agent_workflow_implementation_manifest()
    admit_agent_workflow_runtime(historical, current)


def execute_after_runtime_admission[ResultT](
    agent_session_fingerprint: str,
    session_reader: OnlyAgentSessionContextReader,
    continuation: Callable[[OnlyAgentAdmittedRuntimeV1], ResultT],
) -> ResultT:
    """The sole boundary through which future external execution may continue."""

    context = session_reader.load_session_manifest_verified(agent_session_fingerprint)
    if context.session.session_fingerprint != agent_session_fingerprint:
        raise OnlyAgentContextError("AGENT_ORCHESTRATION_RESOURCE_MISMATCH", agent_session_fingerprint)
    current = build_current_agent_workflow_implementation_manifest()
    admit_agent_workflow_runtime(context.workflow_resource, current)
    admitted = OnlyAgentAdmittedRuntimeV1(
        agent_session_fingerprint,
        context.workflow_resource.resource_fingerprint,
        current.implementation_fingerprint,
        current.source_revision,
    )
    return continuation(admitted)


__all__ = [
    "ONLY_AGENT_WORKFLOW_ID",
    "ONLY_AGENT_WORKFLOW_SEMANTIC_VERSION",
    "OnlyAgentAdmittedRuntimeV1",
    "OnlyAgentOrchestratorOperationalConfigV1",
    "assert_current_runtime_admitted_for_session",
    "build_current_agent_workflow_implementation_manifest",
    "execute_after_runtime_admission",
]
