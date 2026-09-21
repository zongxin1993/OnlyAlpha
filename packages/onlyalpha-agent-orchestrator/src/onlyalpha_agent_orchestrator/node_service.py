"""Private request-driven control service for one production Agent node."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from onlyalpha.research.agent.model import (
    OnlyAgentOrchestrationResourceKind,
    OnlyAgentOrchestrationResourceV1,
    OnlyAgentResearchBrief,
    OnlyAgentSessionManifestV1,
)
from onlyalpha.research.agent.session_state import OnlyAgentDerivedSessionStateV1
from onlyalpha.research.agent.store import (
    OnlyAgentCommitDisposition,
    OnlyJsonAgentOrchestrationResourceStore,
    OnlyJsonAgentResearchBriefStore,
    OnlyJsonAgentSessionManifestStore,
)

from .config import OnlyOpenAICompatibleEndpointConfigV1
from .provider_integration import (
    OnlyAgentProviderRuntimeAuthority,
    OnlyAgentSessionProviderBindingV1,
    OnlyJsonAgentModelProfileStoreV1,
    OnlyJsonAgentProviderBindingStoreV1,
    OnlyResolvedAgentProviderRuntimeV1,
)
from .runtime import build_current_agent_workflow_implementation_manifest
from .semantic_bundle import OnlyAgentProductionSemanticBundleV1, commit_production_semantic_bundle_v1


@dataclass(frozen=True, slots=True)
class OnlyAgentSessionAdmissionOutcomeV1:
    session_fingerprint: str
    research_brief_fingerprint: str
    session_disposition: OnlyAgentCommitDisposition
    workflow_implementation_fingerprint: str


class OnlyAgentNodeDriver(Protocol):
    def advance_once(self, session_fingerprint: str) -> OnlyAgentDerivedSessionStateV1: ...


class OnlyAgentNodeControlServiceV1:
    """Admit immutable Sessions and perform exactly one bounded Driver advance."""

    def __init__(
        self,
        *,
        resources: OnlyJsonAgentOrchestrationResourceStore,
        briefs: OnlyJsonAgentResearchBriefStore,
        sessions: OnlyJsonAgentSessionManifestStore,
        semantic_bundle: OnlyAgentProductionSemanticBundleV1,
        driver: OnlyAgentNodeDriver,
        provider_runtime: OnlyResolvedAgentProviderRuntimeV1 | None = None,
        provider_resolver: OnlyAgentProviderRuntimeAuthority | None = None,
        provider_bindings: OnlyJsonAgentProviderBindingStoreV1 | None = None,
        model_profiles: OnlyJsonAgentModelProfileStoreV1 | None = None,
        product_contract_fingerprint: str | None = None,
        provider_driver_factory: Callable[[OnlyOpenAICompatibleEndpointConfigV1], OnlyAgentNodeDriver] | None = None,
    ) -> None:
        self._resources = resources
        self._briefs = briefs
        self._sessions = sessions
        self._bundle = semantic_bundle
        self._driver = driver
        self._provider_runtime = provider_runtime
        self._provider_resolver = provider_resolver
        self._provider_bindings = provider_bindings
        self._model_profiles = model_profiles
        self._product_contract_fingerprint = product_contract_fingerprint
        self._provider_driver_factory = provider_driver_factory
        configured = (
            provider_runtime,
            provider_resolver,
            provider_bindings,
            model_profiles,
            product_contract_fingerprint,
            provider_driver_factory,
        )
        if any(value is not None for value in configured) and not all(value is not None for value in configured):
            raise ValueError("AGENT_PROVIDER_CONFIGURATION_INCOMPLETE")

    def bootstrap(self) -> str:
        commit_production_semantic_bundle_v1(self._resources, self._bundle)
        manifest = build_current_agent_workflow_implementation_manifest()
        resource = OnlyAgentOrchestrationResourceV1(
            OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST,
            1,
            manifest.workflow_semantic_version,
            manifest,
        )
        self._resources.commit_resource(resource)
        loaded = self._resources.load_resource_verified(resource.resource_kind, resource.resource_fingerprint)
        if loaded != resource:
            raise ValueError("AGENT_PRODUCTION_RESOURCE_BOOTSTRAP_MISMATCH")
        return resource.resource_fingerprint

    def admit_session(self, brief: OnlyAgentResearchBrief) -> OnlyAgentSessionAdmissionOutcomeV1:
        workflow_resource_fingerprint = self.bootstrap()
        manifest = build_current_agent_workflow_implementation_manifest()
        brief_outcome = self._briefs.commit_research_brief(brief)
        if brief_outcome.fingerprint != brief.research_brief_fingerprint:
            raise ValueError("AGENT_RESEARCH_BRIEF_INVALID")
        session = OnlyAgentSessionManifestV1(
            brief.research_brief_fingerprint,
            manifest.workflow_id,
            manifest.workflow_semantic_version,
            manifest.implementation_fingerprint,
            manifest.source_revision,
            workflow_resource_fingerprint,
            self._bundle.tool_policy_fingerprint,
            self._bundle.role_policy_fingerprints,
        )
        if self._provider_runtime is not None:
            assert self._provider_bindings is not None
            assert self._model_profiles is not None
            assert self._product_contract_fingerprint is not None
            self._model_profiles.commit(self._provider_runtime.model_profile)
            self._provider_bindings.commit(
                OnlyAgentSessionProviderBindingV1(
                    session.session_fingerprint,
                    manifest.implementation_fingerprint,
                    self._product_contract_fingerprint,
                    self._provider_runtime.binding,
                    self._provider_runtime.model_profile.model_profile_fingerprint,
                )
            )
        outcome = self._sessions.commit_session_manifest(session)
        return OnlyAgentSessionAdmissionOutcomeV1(
            session.session_fingerprint,
            brief.research_brief_fingerprint,
            outcome.disposition,
            manifest.implementation_fingerprint,
        )

    def advance_once(self, session_fingerprint: str) -> OnlyAgentDerivedSessionStateV1:
        if self._provider_runtime is not None:
            assert self._provider_bindings is not None
            assert self._provider_resolver is not None
            assert self._model_profiles is not None
            binding = self._provider_bindings.load(session_fingerprint)
            profile = self._model_profiles.load(binding.model_profile_fingerprint)
            context = self._sessions.load_session_manifest_verified(session_fingerprint)
            if (
                binding.workflow_manifest_fingerprint != context.session.agent_workflow_implementation_fingerprint
                or binding.product_contract_fingerprint != self._product_contract_fingerprint
            ):
                raise ValueError("AGENT_WORKFLOW_RUNTIME_MISMATCH")
            resolved = self._provider_resolver.continue_exact(binding, profile)
            assert self._provider_driver_factory is not None
            return self._provider_driver_factory(resolved.endpoint).advance_once(session_fingerprint)
        return self._driver.advance_once(session_fingerprint)


__all__ = [name for name in globals() if name.startswith("OnlyAgent")]
