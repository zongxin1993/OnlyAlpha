"""Explicit, self-closing executable-resource declaration for the Agent runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources

from onlyalpha.research.agent.errors import OnlyAgentContextError
from onlyalpha.research.agent.model import OnlyAgentWorkflowResourceKind
from onlyalpha.research.agent.workflow import OnlyAgentRuntimeResourceV1


@dataclass(frozen=True, slots=True)
class OnlyAgentWorkflowResourceSpecV1:
    """One stable logical identity resolved to exact bytes from an installed package."""

    logical_resource_identity: str
    package: str
    relative_name: str
    resource_kind: OnlyAgentWorkflowResourceKind = OnlyAgentWorkflowResourceKind.SOURCE

    def __post_init__(self) -> None:
        if (
            not self.logical_resource_identity
            or any(character.isspace() for character in self.logical_resource_identity)
            or not self.package
            or any(character.isspace() for character in self.package)
            or not self.relative_name
            or self.relative_name in {".", ".."}
            or "/" in self.relative_name
            or "\\" in self.relative_name
            or not isinstance(self.resource_kind, OnlyAgentWorkflowResourceKind)
        ):
            raise ValueError("AGENT_WORKFLOW_RESOURCE_SPEC_INVALID")


# The declaration is canonically ordered by logical identity. This file is itself
# a required resource, so any add/remove/replace/reorder edit changes its exact hash.
ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1 = (
    OnlyAgentWorkflowResourceSpecV1("onlyalpha.__init__.py", "onlyalpha", "__init__.py"),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.__init__.py", "onlyalpha_agent_orchestrator", "__init__.py"
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.adapters.__init__.py",
        "onlyalpha_agent_orchestrator.adapters",
        "__init__.py",
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.adapters.openai_compatible.py",
        "onlyalpha_agent_orchestrator.adapters",
        "openai_compatible.py",
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.adapters.product_api.py",
        "onlyalpha_agent_orchestrator.adapters",
        "product_api.py",
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.adapters.transport.py",
        "onlyalpha_agent_orchestrator.adapters",
        "transport.py",
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.bindings.py", "onlyalpha_agent_orchestrator", "bindings.py"
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.closure.py", "onlyalpha_agent_orchestrator", "closure.py"
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.config.py", "onlyalpha_agent_orchestrator", "config.py"
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.coordination.py",
        "onlyalpha_agent_orchestrator",
        "coordination.py",
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.driver.py", "onlyalpha_agent_orchestrator", "driver.py"
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.execution.py", "onlyalpha_agent_orchestrator", "execution.py"
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.materialization.py",
        "onlyalpha_agent_orchestrator",
        "materialization.py",
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.provenance.py", "onlyalpha_agent_orchestrator", "provenance.py"
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.agent.orchestrator.runtime.py", "onlyalpha_agent_orchestrator", "runtime.py"
    ),
    OnlyAgentWorkflowResourceSpecV1("onlyalpha.application.__init__.py", "onlyalpha.application", "__init__.py"),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.application.product_command_receipt.py", "onlyalpha.application", "product_command_receipt.py"
    ),
    OnlyAgentWorkflowResourceSpecV1("onlyalpha.build_provenance.py", "onlyalpha", "build_provenance.py"),
    OnlyAgentWorkflowResourceSpecV1("onlyalpha.canonical.py", "onlyalpha", "canonical.py"),
    OnlyAgentWorkflowResourceSpecV1("onlyalpha.distribution.py", "onlyalpha", "distribution.py"),
    OnlyAgentWorkflowResourceSpecV1("onlyalpha.research.__init__.py", "onlyalpha.research", "__init__.py"),
    OnlyAgentWorkflowResourceSpecV1("onlyalpha.research.agent.__init__.py", "onlyalpha.research.agent", "__init__.py"),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.research.agent.application.py", "onlyalpha.research.agent", "application.py"
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.research.agent.authority_state.py", "onlyalpha.research.agent", "authority_state.py"
    ),
    OnlyAgentWorkflowResourceSpecV1("onlyalpha.research.agent.decision.py", "onlyalpha.research.agent", "decision.py"),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.research.agent.decision_store.py", "onlyalpha.research.agent", "decision_store.py"
    ),
    OnlyAgentWorkflowResourceSpecV1("onlyalpha.research.agent.errors.py", "onlyalpha.research.agent", "errors.py"),
    OnlyAgentWorkflowResourceSpecV1("onlyalpha.research.agent.model.py", "onlyalpha.research.agent", "model.py"),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.research.agent.occurrence.py", "onlyalpha.research.agent", "occurrence.py"
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.research.agent.occurrence_service.py", "onlyalpha.research.agent", "occurrence_service.py"
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.research.agent.occurrence_store.py", "onlyalpha.research.agent", "occurrence_store.py"
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.research.agent.semantic_translation.py", "onlyalpha.research.agent", "semantic_translation.py"
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.research.agent.session_state.py", "onlyalpha.research.agent", "session_state.py"
    ),
    OnlyAgentWorkflowResourceSpecV1("onlyalpha.research.agent.store.py", "onlyalpha.research.agent", "store.py"),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.research.agent.verification.py", "onlyalpha.research.agent", "verification.py"
    ),
    OnlyAgentWorkflowResourceSpecV1("onlyalpha.research.agent.workflow.py", "onlyalpha.research.agent", "workflow.py"),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.research.experiment.__init__.py", "onlyalpha.research.experiment", "__init__.py"
    ),
    OnlyAgentWorkflowResourceSpecV1(
        "onlyalpha.research.experiment.model.py", "onlyalpha.research.experiment", "model.py"
    ),
)

_ResourceReader = Callable[[str, str], bytes]


def _read_packaged_resource(package: str, relative_name: str) -> bytes:
    return resources.files(package).joinpath(relative_name).read_bytes()


def _build_agent_workflow_runtime_resources(
    declaration: tuple[OnlyAgentWorkflowResourceSpecV1, ...],
    reader: _ResourceReader,
) -> tuple[OnlyAgentRuntimeResourceV1, ...]:
    identities = tuple(item.logical_resource_identity for item in declaration)
    locators = tuple((item.package, item.relative_name) for item in declaration)
    if (
        not declaration
        or identities != tuple(sorted(identities))
        or len(set(identities)) != len(identities)
        or len(set(locators)) != len(locators)
    ):
        raise OnlyAgentContextError("AGENT_ORCHESTRATION_RESOURCE_MISMATCH", "workflow resource closure declaration")
    loaded: list[OnlyAgentRuntimeResourceV1] = []
    for item in declaration:
        try:
            content = reader(item.package, item.relative_name)
        except (FileNotFoundError, ModuleNotFoundError, OSError, TypeError) as exc:
            raise OnlyAgentContextError("AGENT_ORCHESTRATION_RESOURCE_MISSING", item.logical_resource_identity) from exc
        if not isinstance(content, bytes) or not content:
            raise OnlyAgentContextError("AGENT_ORCHESTRATION_RESOURCE_MISMATCH", item.logical_resource_identity)
        loaded.append(OnlyAgentRuntimeResourceV1(item.logical_resource_identity, item.resource_kind, content))
    return tuple(loaded)


def build_current_agent_workflow_runtime_resources() -> tuple[OnlyAgentRuntimeResourceV1, ...]:
    """Load the complete current workflow closure from installed package resources."""

    return _build_agent_workflow_runtime_resources(
        ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1,
        _read_packaged_resource,
    )


__all__ = [
    "ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1",
    "OnlyAgentWorkflowResourceSpecV1",
    "build_current_agent_workflow_runtime_resources",
]
