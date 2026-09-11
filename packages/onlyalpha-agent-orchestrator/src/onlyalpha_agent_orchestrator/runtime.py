"""Current Agent workflow manifest assembly and pre-I/O admission boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Never, SupportsIndex

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


_ADMISSION_SEAL = object()
_EXTERNAL_IO_SEAL = object()


class OnlyAgentRuntimeExecutionPermit:
    """Read-only process-local capability issued by runtime admission only."""

    __slots__ = (
        "_agent_session_fingerprint",
        "_historical_workflow_resource_fingerprint",
        "_workflow_implementation_fingerprint",
        "_source_revision",
        "_seal",
    )
    _agent_session_fingerprint: str
    _historical_workflow_resource_fingerprint: str
    _workflow_implementation_fingerprint: str
    _source_revision: str
    _seal: object

    def __init__(
        self,
        agent_session_fingerprint: str,
        historical_workflow_resource_fingerprint: str,
        workflow_implementation_fingerprint: str,
        source_revision: str,
        *,
        _seal: object | None = None,
    ) -> None:
        if _seal is not _ADMISSION_SEAL:
            raise OnlyAgentContextError("AGENT_POLICY_VIOLATION", "runtime execution permit construction")
        object.__setattr__(self, "_agent_session_fingerprint", agent_session_fingerprint)
        object.__setattr__(
            self,
            "_historical_workflow_resource_fingerprint",
            historical_workflow_resource_fingerprint,
        )
        object.__setattr__(self, "_workflow_implementation_fingerprint", workflow_implementation_fingerprint)
        object.__setattr__(self, "_source_revision", source_revision)
        object.__setattr__(self, "_seal", _seal)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("OnlyAgentRuntimeExecutionPermit is read-only")

    def __copy__(self) -> Never:
        raise TypeError("OnlyAgentRuntimeExecutionPermit cannot be reconstructed")

    def __deepcopy__(self, _memo: object) -> Never:
        raise TypeError("OnlyAgentRuntimeExecutionPermit cannot be reconstructed")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> Never:
        raise TypeError("OnlyAgentRuntimeExecutionPermit cannot be serialized")

    @property
    def agent_session_fingerprint(self) -> str:
        return self._agent_session_fingerprint

    @property
    def historical_workflow_resource_fingerprint(self) -> str:
        return self._historical_workflow_resource_fingerprint

    @property
    def workflow_implementation_fingerprint(self) -> str:
        return self._workflow_implementation_fingerprint

    @property
    def source_revision(self) -> str:
        return self._source_revision


# Import compatibility only: this is the same sealed capability, not the former DTO.
OnlyAgentAdmittedRuntimeV1 = OnlyAgentRuntimeExecutionPermit


class OnlyAgentExternalIoPermit:
    """Process-local proof that Permit and Prepared validation both completed."""

    __slots__ = ("_agent_session_fingerprint", "_consumed", "_seal")
    _agent_session_fingerprint: str
    _consumed: bool
    _seal: object

    def __init__(self, agent_session_fingerprint: str, *, _seal: object | None = None) -> None:
        if _seal is not _EXTERNAL_IO_SEAL:
            raise OnlyAgentContextError("AGENT_POLICY_VIOLATION", "external I/O permit construction")
        object.__setattr__(self, "_agent_session_fingerprint", agent_session_fingerprint)
        object.__setattr__(self, "_consumed", False)
        object.__setattr__(self, "_seal", _seal)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("OnlyAgentExternalIoPermit is read-only")

    def __copy__(self) -> Never:
        raise TypeError("OnlyAgentExternalIoPermit cannot be reconstructed")

    def __deepcopy__(self, _memo: object) -> Never:
        raise TypeError("OnlyAgentExternalIoPermit cannot be reconstructed")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> Never:
        raise TypeError("OnlyAgentExternalIoPermit cannot be serialized")

    @property
    def agent_session_fingerprint(self) -> str:
        return self._agent_session_fingerprint


def _mint_external_io_permit(
    permit: OnlyAgentRuntimeExecutionPermit,
    *,
    agent_session_fingerprint: str,
) -> OnlyAgentExternalIoPermit:
    """Mint only from the continuation reached after consuming a Prepared seal."""

    assert_runtime_execution_permit_for_session(
        permit,
        agent_session_fingerprint=agent_session_fingerprint,
    )
    return OnlyAgentExternalIoPermit(agent_session_fingerprint, _seal=_EXTERNAL_IO_SEAL)


def assert_external_io_permit(
    permit: object,
    *,
    agent_session_fingerprint: str | None = None,
    consume: bool = False,
) -> None:
    if (
        type(permit) is not OnlyAgentExternalIoPermit
        or permit._seal is not _EXTERNAL_IO_SEAL
        or permit._consumed
        or (agent_session_fingerprint is not None and permit.agent_session_fingerprint != agent_session_fingerprint)
    ):
        raise OnlyAgentContextError("AGENT_POLICY_VIOLATION", "external I/O permit validation")
    if consume:
        object.__setattr__(permit, "_consumed", True)


def _mint_runtime_execution_permit(
    agent_session_fingerprint: str,
    historical_workflow_resource_fingerprint: str,
    workflow_implementation_fingerprint: str,
    source_revision: str,
) -> OnlyAgentRuntimeExecutionPermit:
    return OnlyAgentRuntimeExecutionPermit(
        agent_session_fingerprint,
        historical_workflow_resource_fingerprint,
        workflow_implementation_fingerprint,
        source_revision,
        _seal=_ADMISSION_SEAL,
    )


def assert_runtime_execution_permit(
    permit: object,
    *,
    agent_session_fingerprint: str,
    historical_workflow_resource_fingerprint: str,
    workflow_implementation_fingerprint: str,
    source_revision: str,
) -> None:
    """Validate the exact admission capability required by future external I/O."""

    if (
        type(permit) is not OnlyAgentRuntimeExecutionPermit
        or permit._seal is not _ADMISSION_SEAL
        or permit.agent_session_fingerprint != agent_session_fingerprint
        or permit.historical_workflow_resource_fingerprint != historical_workflow_resource_fingerprint
        or permit.workflow_implementation_fingerprint != workflow_implementation_fingerprint
        or permit.source_revision != source_revision
    ):
        raise OnlyAgentContextError("AGENT_POLICY_VIOLATION", "runtime execution permit validation")


def assert_runtime_execution_permit_for_session(
    permit: object,
    *,
    agent_session_fingerprint: str,
) -> None:
    """Verify permit authenticity and occurrence Session binding at the I/O gate."""

    if (
        type(permit) is not OnlyAgentRuntimeExecutionPermit
        or permit._seal is not _ADMISSION_SEAL
        or permit.agent_session_fingerprint != agent_session_fingerprint
    ):
        raise OnlyAgentContextError("AGENT_POLICY_VIOLATION", "runtime execution permit validation")


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
    continuation: Callable[[OnlyAgentRuntimeExecutionPermit], ResultT],
) -> ResultT:
    """The sole boundary through which future external execution may continue."""

    context = session_reader.load_session_manifest_verified(agent_session_fingerprint)
    if context.session.session_fingerprint != agent_session_fingerprint:
        raise OnlyAgentContextError("AGENT_ORCHESTRATION_RESOURCE_MISMATCH", agent_session_fingerprint)
    current = build_current_agent_workflow_implementation_manifest()
    admit_agent_workflow_runtime(context.workflow_resource, current)
    admitted = _mint_runtime_execution_permit(
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
    "OnlyAgentExternalIoPermit",
    "OnlyAgentOrchestratorOperationalConfigV1",
    "OnlyAgentRuntimeExecutionPermit",
    "assert_current_runtime_admitted_for_session",
    "assert_external_io_permit",
    "assert_runtime_execution_permit",
    "assert_runtime_execution_permit_for_session",
    "build_current_agent_workflow_implementation_manifest",
    "execute_after_runtime_admission",
]
