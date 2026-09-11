"""Current Agent workflow manifest assembly and pre-I/O admission boundary."""

from __future__ import annotations

from dataclasses import dataclass, field

from onlyalpha.research.agent.model import (
    OnlyAgentOrchestrationResourceKind,
    OnlyAgentWorkflowImplementationManifestV1,
)
from onlyalpha.research.agent.verification import OnlyAgentOrchestrationResourceReader
from onlyalpha.research.agent.workflow import (
    admit_agent_workflow_runtime,
    derive_agent_workflow_implementation_manifest,
)

from .closure import build_current_agent_workflow_runtime_resources

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


def build_current_agent_workflow_implementation_manifest() -> OnlyAgentWorkflowImplementationManifestV1:
    """Derive the ADR 0123 manifest from the actual installed executable bytes."""

    return derive_agent_workflow_implementation_manifest(
        workflow_id=ONLY_AGENT_WORKFLOW_ID,
        workflow_semantic_version=ONLY_AGENT_WORKFLOW_SEMANTIC_VERSION,
        runtime_resources=build_current_agent_workflow_runtime_resources(),
    )


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


__all__ = [
    "ONLY_AGENT_WORKFLOW_ID",
    "ONLY_AGENT_WORKFLOW_SEMANTIC_VERSION",
    "OnlyAgentOrchestratorOperationalConfigV1",
    "assert_current_runtime_admitted_for_session",
    "build_current_agent_workflow_implementation_manifest",
]
