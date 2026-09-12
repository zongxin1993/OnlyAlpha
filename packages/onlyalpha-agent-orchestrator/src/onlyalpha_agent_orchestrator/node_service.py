"""Private request-driven control service for one production Agent node."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.research.agent.model import (
    OnlyAgentOrchestrationResourceKind,
    OnlyAgentOrchestrationResourceV1,
    OnlyAgentResearchBriefV1,
    OnlyAgentSessionManifestV1,
)
from onlyalpha.research.agent.session_state import OnlyAgentDerivedSessionStateV1
from onlyalpha.research.agent.store import (
    OnlyAgentCommitDisposition,
    OnlyJsonAgentOrchestrationResourceStore,
    OnlyJsonAgentResearchBriefStore,
    OnlyJsonAgentSessionManifestStore,
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
    ) -> None:
        self._resources = resources
        self._briefs = briefs
        self._sessions = sessions
        self._bundle = semantic_bundle
        self._driver = driver

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

    def admit_session(self, brief: OnlyAgentResearchBriefV1) -> OnlyAgentSessionAdmissionOutcomeV1:
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
        outcome = self._sessions.commit_session_manifest(session)
        return OnlyAgentSessionAdmissionOutcomeV1(
            session.session_fingerprint,
            brief.research_brief_fingerprint,
            outcome.disposition,
            manifest.implementation_fingerprint,
        )

    def advance_once(self, session_fingerprint: str) -> OnlyAgentDerivedSessionStateV1:
        return self._driver.advance_once(session_fingerprint)


__all__ = [name for name in globals() if name.startswith("OnlyAgent")]
