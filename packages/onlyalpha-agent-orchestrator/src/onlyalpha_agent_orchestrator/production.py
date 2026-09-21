"""Production composition root for the independently deployable Agent node."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.agent.application import (
    OnlyAgentDecisionApplicationServiceV1,
    OnlyAgentEvidenceCausalVerifierV1,
    OnlyAgentExperimentLaunchServiceV1,
)
from onlyalpha.research.agent.decision import OnlyAgentEvaluationPathKind
from onlyalpha.research.agent.decision_store import (
    OnlyJsonAgentDecisionStore,
    OnlyJsonAgentExperimentLaunchStore,
)
from onlyalpha.research.agent.errors import OnlyAgentContextError
from onlyalpha.research.agent.occurrence import OnlyAgentExactAuthorityReference
from onlyalpha.research.agent.occurrence_service import (
    OnlyAgentModelOccurrenceServiceV1,
    OnlyAgentToolOccurrenceServiceV1,
)
from onlyalpha.research.agent.occurrence_store import (
    OnlyJsonAgentModelOccurrenceStore,
    OnlyJsonAgentToolOccurrenceStore,
)
from onlyalpha.research.agent.session_state import OnlyAgentSessionReducerV1
from onlyalpha.research.agent.store import (
    OnlyJsonAgentOrchestrationResourceStore,
    OnlyJsonAgentResearchBriefStore,
    OnlyJsonAgentSessionManifestStore,
)
from onlyalpha.research.agent.verification import (
    OnlyAgentResearchBriefReferenceReadersV1,
    OnlyVerifiedAgentDecisionContextV1,
)
from onlyalpha.research.experiment.model import only_search_experiment_manifest_from_dict

from .adapters.openai_compatible import OnlyOpenAICompatibleModelAdapterV1
from .adapters.product_api import OnlyContractDrivenProductApiAdapterV1, OnlyProductApiContractV2
from .adapters.transport import OnlyRawHttpTransportV1
from .authority_readers import (
    OnlyAgentProductControlPlaneClient,
    OnlyAgentProductHttpControlPlaneClientV1,
    OnlyApiBackedAgentBriefReferenceReaderV1,
    OnlyApiBackedAgentResearchStateReaderV1,
    OnlyApiBackedAgentSearchStateReaderV1,
)
from .config import OnlyOpenAICompatibleEndpointConfigV1, OnlyProductApiEndpointConfigV1
from .coordination import OnlyAgentSessionExecutionCoordinatorV1
from .driver import OnlyAgentSessionDriverV1
from .materialization import OnlyAgentWorkflowActionMaterializerV1
from .node_service import OnlyAgentNodeControlServiceV1, OnlyAgentNodeDriver
from .provider_integration import (
    OnlyAgentModelProfileV1,
    OnlyAgentProviderRuntimeAuthority,
    OnlyJsonAgentModelProfileStoreV1,
    OnlyJsonAgentProviderBindingStoreV1,
    OnlyResolvedAgentProviderRuntimeV1,
)
from .runtime import build_current_agent_workflow_implementation_manifest
from .semantic_bundle import load_production_semantic_bundle_v1


class _LateBindingProxy:
    target: object | None = None

    def __getattr__(self, name: str) -> Any:
        if self.target is None:
            raise RuntimeError("AGENT_PRODUCTION_COMPOSITION_INCOMPLETE")
        return getattr(self.target, name)


class _VerifiedSessionContextCache:
    """Process-local cache of fully verified immutable Session context."""

    def __init__(self, sessions: OnlyJsonAgentSessionManifestStore) -> None:
        self._sessions = sessions
        self._verified: dict[str, OnlyVerifiedAgentDecisionContextV1] = {}

    def load_session_manifest_verified(self, fingerprint: str) -> OnlyVerifiedAgentDecisionContextV1:
        cached = self._verified.get(fingerprint)
        if cached is not None:
            return cached
        context = self._sessions.load_session_manifest_verified(fingerprint)
        self._verified[fingerprint] = context
        return context


class _RequestScopedVerifiedReaderCache:
    """Memoize fully verified immutable reads only within one control request."""

    def __init__(self, target: object, methods: frozenset[str]) -> None:
        self._target = target
        self._methods = methods
        self._verified: dict[tuple[object, ...], object] = {}

    def clear(self) -> None:
        self._verified.clear()

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._target, name)
        if name not in self._methods:
            return target

        def load(*args: object, **kwargs: object) -> object:
            key = (name, args, tuple(sorted(kwargs.items())))
            cached = self._verified.get(key)
            if cached is not None:
                return cached
            value = target(*args, **kwargs)
            self._verified[key] = value
            return value

        return load


class _RequestScopedVerificationDriver:
    def __init__(
        self,
        driver: OnlyAgentSessionDriverV1,
        caches: tuple[_RequestScopedVerifiedReaderCache, ...],
    ) -> None:
        self._driver = driver
        self._caches = caches

    def advance_once(self, session_fingerprint: str):  # type: ignore[no-untyped-def]
        for cache in self._caches:
            cache.clear()
        try:
            return self._driver.advance_once(session_fingerprint)
        finally:
            for cache in self._caches:
                cache.clear()


class OnlyApiBackedAgentRuntimeGenerationReaderV1:
    def __init__(self, client: OnlyAgentProductControlPlaneClient) -> None:
        self._client = client

    def read_current_new_work_runtime_generation_fingerprint(self) -> str:
        payload = self._client.get_json_verified("/api/v2/research/runtime-generations/active")
        value = payload.get("runtime_generation_fingerprint")
        if payload.get("schema_version") != 1 or not isinstance(value, str):
            raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", "Runtime Generation projection")
        return value

    def require_new_work_generation(self, runtime_generation_fingerprint: str) -> object:
        current = self.read_current_new_work_runtime_generation_fingerprint()
        if current != runtime_generation_fingerprint:
            raise OnlyAgentContextError("AGENT_SEARCH_RUNTIME_GENERATION_INVALID", runtime_generation_fingerprint)
        return current


class OnlyAgentProductionContextReaderV1:
    """Resolve Agent-owned facts locally and Product-owned facts through API only."""

    def __init__(
        self,
        *,
        client: OnlyAgentProductControlPlaneClient,
        briefs: OnlyJsonAgentResearchBriefStore,
        models: _LateBindingProxy,
        tools: _LateBindingProxy,
    ) -> None:
        self._client = client
        self._briefs = briefs
        self._models = models
        self._tools = tools
        self._immutable_product_payloads: dict[tuple[str, int, str], bytes] = {}

    def verify_exact_reference(self, reference: OnlyAgentExactAuthorityReference) -> None:
        if reference.reference_kind == "SEARCH_EXPECTED_STATE":
            if reference.reference_schema_version != 1:
                raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", reference.locator_value)
            # This is a canonical causal-input fingerprint, not a standalone
            # Authority.  Its complete value is verified against the paired
            # Search Authority projection during new-tool admission.
            return
        self.load_semantic_payload_verified(reference)

    def verify_completed_evaluation_path(
        self,
        reference: OnlyAgentExactAuthorityReference,
        _path_kind: OnlyAgentEvaluationPathKind,
    ) -> None:
        self.verify_exact_reference(reference)

    def load_exact_response_verified(self, reference: OnlyAgentExactAuthorityReference) -> Mapping[str, object]:
        return self.load_semantic_payload_verified(reference)

    def load_model_context_projection_verified(
        self, reference: OnlyAgentExactAuthorityReference
    ) -> Mapping[str, object]:
        return self.load_semantic_payload_verified(reference)

    def load_semantic_payload_verified(self, reference: OnlyAgentExactAuthorityReference) -> Mapping[str, object]:
        key = (reference.reference_kind, reference.reference_schema_version, reference.locator_value)
        if reference.reference_kind != "RESEARCH_RUN":
            cached = self._immutable_product_payloads.get(key)
            if cached is not None:
                value = json.loads(cached)
                if not isinstance(value, dict):  # pragma: no cover - written only after verified mapping
                    raise RuntimeError("AGENT_IMMUTABLE_CONTEXT_CACHE_CORRUPT")
                return cast(Mapping[str, object], value)
        value = self._load_semantic_payload_uncached(reference)
        if reference.reference_kind != "RESEARCH_RUN":
            self._immutable_product_payloads[key] = only_canonical_json(value).encode("utf-8")
        return value

    def _load_semantic_payload_uncached(self, reference: OnlyAgentExactAuthorityReference) -> Mapping[str, object]:
        kind = reference.reference_kind
        value = reference.locator_value
        if kind == "SEARCH_EXPECTED_STATE":
            raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", value)
        if kind == "AGENT_RESEARCH_BRIEF":
            return self._briefs.load_research_brief_verified(value).to_dict()
        if kind == "AGENT_MODEL_CALL_RESULT":
            return cast(Mapping[str, object], self._models.load_result_by_fingerprint_verified(value).to_dict())
        if kind == "AGENT_TOOL_CALL_RESULT":
            return cast(Mapping[str, object], self._tools.load_result_by_fingerprint_verified(value).to_dict())
        paths = {
            "CATALOG_GENERATION": f"/api/v2/research/catalog-context/exact/{value}",
            "DATASET_SNAPSHOT": f"/api/v2/research/datasets/{value}",
            "RESEARCH_RUN": f"/api/v2/research/runs/{value}",
            "SEARCH_EXPERIMENT": f"/api/v2/research/search/experiments/{value}",
            "RESEARCH_RESULT": f"/api/v2/research/artifacts/{value}",
        }
        if kind == "RESEARCH_STATISTICS":
            envelope = self._client.get_json_verified(f"/api/v2/research/statistics/{value}")
            if (
                envelope.get("schema_version") != 1
                or envelope.get("statistics_result_fingerprint") != value
                or not isinstance(envelope.get("payload"), Mapping)
            ):
                raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", value)
            return cast(Mapping[str, object], envelope["payload"])
        if kind == "SEARCH_ITERATION_RESULT":
            envelope = self._client.get_json_verified(
                f"/api/v2/research/search/iteration-results/{quote(value, safe='')}"
            )
            if (
                envelope.get("schema_version") != 1
                or envelope.get("iteration_result_fingerprint") != value
                or not isinstance(envelope.get("payload"), Mapping)
            ):
                raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", value)
            return cast(Mapping[str, object], envelope["payload"])
        if kind == "SEARCH_TERMINAL_PROJECTION":
            envelope = self._client.get_json_verified(
                f"/api/v2/research/search/iteration-results/terminal-projections/{quote(value, safe='')}"
            )
            if (
                envelope.get("schema_version") != 1
                or envelope.get("terminal_projection_fingerprint") != value
                or not isinstance(envelope.get("payload"), Mapping)
            ):
                raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", value)
            return cast(Mapping[str, object], envelope["payload"])
        if kind == "RUNTIME_GENERATION":
            envelope = self._client.get_json_verified(f"/api/v2/research/runtime-generations/{quote(value, safe='')}")
            if envelope.get("schema_version") != 1 or envelope.get("runtime_generation_fingerprint") != value:
                raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", value)
            return envelope
        path = paths.get(kind)
        if path is None:
            if kind not in {
                "SYMBOLIC_SEARCH_SPACE",
                "PARAMETER_SEARCH_SPACE",
                "SEARCH_POLICY",
                "SEARCH_ALGORITHM",
                "RESEARCH_EVALUATION",
            }:
                raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", value)
            path = f"/api/v2/research/search/authoring/{quote(kind, safe='')}/{quote(value, safe='')}"
            envelope = self._client.get_json_verified(path)
            if (
                envelope.get("schema_version") != 1
                or envelope.get("reference_kind") != kind
                or envelope.get("reference_fingerprint") != value
                or not isinstance(envelope.get("payload"), Mapping)
            ):
                raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", value)
            return cast(Mapping[str, object], envelope["payload"])
        return self._client.get_json_verified(path)

    def load_experiment_verified(self, experiment_fingerprint: str):  # type: ignore[no-untyped-def]
        payload = self._client.get_json_verified(
            f"/api/v2/research/search/experiments/{quote(experiment_fingerprint, safe='')}"
        )
        experiment = payload.get("experiment")
        if not isinstance(experiment, Mapping):
            raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", "Search Experiment projection")
        value = only_search_experiment_manifest_from_dict(cast(Mapping[str, object], experiment))
        if value.experiment_fingerprint != experiment_fingerprint:
            raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", experiment_fingerprint)
        return value


@dataclass(frozen=True, slots=True)
class OnlyAgentProductionRuntimeV1:
    control: OnlyAgentNodeControlServiceV1
    workflow_implementation_fingerprint: str
    durable_root: Path
    coordination_root: Path
    product_contract_path: Path
    product_contract_fingerprint: str

    def is_ready(self) -> bool:
        """Re-prove local operational invariants without remote Product or model I/O."""

        try:
            roots_usable = all(
                root.is_absolute() and root.is_dir() and not root.is_symlink() and os.access(root, os.W_OK | os.X_OK)
                for root in (self.durable_root, self.coordination_root)
            )
            if not roots_usable:
                return False
            current = build_current_agent_workflow_implementation_manifest()
            if current.implementation_fingerprint != self.workflow_implementation_fingerprint:
                return False
            contract = OnlyProductApiContractV2(self.product_contract_path)
            return contract.fingerprint == self.product_contract_fingerprint
        except Exception:
            return False

    @classmethod
    def compose(
        cls,
        *,
        durable_root: Path,
        coordination_root: Path,
        product: OnlyProductApiEndpointConfigV1,
        model: OnlyOpenAICompatibleEndpointConfigV1,
        provider_runtime: OnlyResolvedAgentProviderRuntimeV1 | None = None,
        provider_resolver: OnlyAgentProviderRuntimeAuthority | None = None,
    ) -> OnlyAgentProductionRuntimeV1:
        if not durable_root.is_absolute() or not coordination_root.is_absolute():
            raise ValueError("AGENT_PRODUCTION_ROOT_INVALID")
        if provider_runtime is not None and provider_runtime.endpoint != model:
            raise ValueError("AGENT_WORKFLOW_RUNTIME_MISMATCH")
        durable_root.mkdir(parents=True, exist_ok=True)
        client = OnlyAgentProductHttpControlPlaneClientV1(product)
        brief_references = OnlyApiBackedAgentBriefReferenceReaderV1(client)
        reference_readers = OnlyAgentResearchBriefReferenceReadersV1(
            brief_references,
            brief_references,
            brief_references,
            brief_references,
        )
        resources = OnlyJsonAgentOrchestrationResourceStore(durable_root)
        briefs = OnlyJsonAgentResearchBriefStore(durable_root, reference_readers)
        sessions = OnlyJsonAgentSessionManifestStore(durable_root, briefs=briefs, resources=resources)
        session_contexts = _VerifiedSessionContextCache(sessions)
        model_store = OnlyJsonAgentModelOccurrenceStore(durable_root)
        tool_store = OnlyJsonAgentToolOccurrenceStore(durable_root)
        decision_store = OnlyJsonAgentDecisionStore(durable_root)
        launch_store = OnlyJsonAgentExperimentLaunchStore(durable_root)
        bundle = load_production_semantic_bundle_v1()
        for role in ("RESEARCH_PLANNER", "SEARCH_ROUTER", "FACTOR_DESIGNER", "EVIDENCE_ANALYST"):
            binding = bundle.invocation_bindings.load_model_invocation_binding_verified(role)
            if (
                binding.provider_id != model.expected_provider_id
                or binding.model_id != model.expected_model_id
                or binding.model_version != model.expected_model_version
            ):
                raise ValueError("AGENT_MODEL_BINDING_MISMATCH")
        model_proxy = _LateBindingProxy()
        tool_proxy = _LateBindingProxy()
        decision_proxy = _LateBindingProxy()
        contexts = OnlyAgentProductionContextReaderV1(
            client=client,
            briefs=briefs,
            models=model_proxy,
            tools=tool_proxy,
        )
        search_states = OnlyApiBackedAgentSearchStateReaderV1(client)
        research_states = OnlyApiBackedAgentResearchStateReaderV1(client)
        product_contract = OnlyProductApiContractV2(product.contract_path)
        causality = OnlyAgentEvidenceCausalVerifierV1(
            tools=tool_proxy,
            launches=launch_store,
            semantic_inputs=contexts,
            research_states=research_states,
            search_states=search_states,
        )
        decision_service = OnlyAgentDecisionApplicationServiceV1(
            sessions=session_contexts,
            models=model_proxy,
            tools=tool_proxy,
            references=contexts,
            store=decision_store,
            search_states=search_states,
            research_states=research_states,
            runtime_generations=OnlyApiBackedAgentRuntimeGenerationReaderV1(client),
            evidence_causality=causality,
        )
        decision_cache = _RequestScopedVerifiedReaderCache(
            decision_service,
            frozenset(
                {
                    "load_decision_verified",
                    "load_decision_by_session_ordinal_verified",
                    "load_decision_authorization_verified",
                }
            ),
        )
        decisions = cast(Any, decision_cache)
        decision_proxy.target = decisions
        model_service = OnlyAgentModelOccurrenceServiceV1(
            sessions=session_contexts,
            resources=resources,
            references=contexts,
            decisions=decision_proxy,
            store=model_store,
        )
        model_cache = _RequestScopedVerifiedReaderCache(
            model_service,
            frozenset(
                {
                    "load_plan_verified",
                    "load_result_verified",
                    "load_result_by_fingerprint_verified",
                    "load_plan_by_session_ordinal_verified",
                }
            ),
        )
        models = cast(Any, model_cache)
        tool_service = OnlyAgentToolOccurrenceServiceV1(
            sessions=session_contexts,
            decisions=decision_proxy,
            product_contracts=product_contract,
            references=contexts,
            response_references=contexts,
            store=tool_store,
        )
        tool_cache = _RequestScopedVerifiedReaderCache(
            tool_service,
            frozenset(
                {
                    "load_plan_verified",
                    "load_result_verified",
                    "load_result_by_fingerprint_verified",
                    "load_plan_by_session_ordinal_verified",
                }
            ),
        )
        tools = cast(Any, tool_cache)
        model_proxy.target = models
        tool_proxy.target = tools
        launches = OnlyAgentExperimentLaunchServiceV1(
            sessions=session_contexts,
            decisions=decisions,
            tools=tools,
            child_searches=contexts,
            store=launch_store,
        )
        reducer = OnlyAgentSessionReducerV1(
            sessions=session_contexts,
            models=models,
            tools=tools,
            decision_service=decisions,
            decision_store=decision_store,
            launch_service=launches,
            search_states=search_states,
            research_states=research_states,
        )
        product_transport = OnlyRawHttpTransportV1(
            connect_timeout_seconds=product.connect_timeout_seconds,
            read_timeout_seconds=product.read_timeout_seconds,
            verify_tls=product.verify_tls,
            ca_bundle_path=product.ca_bundle_path,
        )
        product_adapter = OnlyContractDrivenProductApiAdapterV1(product, product_transport)
        materializer = OnlyAgentWorkflowActionMaterializerV1(
            sessions=session_contexts,
            models=models,
            tools=tools,
            decisions=decisions,
            launches=launches,
            invocation_bindings=bundle.invocation_bindings,
            product_contracts=product_contract,
            semantic_inputs=contexts,
            runtime_generations=OnlyApiBackedAgentRuntimeGenerationReaderV1(client),
            search_states=search_states,
            research_states=research_states,
            evidence_causality=causality,
            product_api_contract_fingerprint=product_contract.fingerprint,
        )

        def driver_for(endpoint: OnlyOpenAICompatibleEndpointConfigV1) -> OnlyAgentNodeDriver:
            model_transport = OnlyRawHttpTransportV1(
                connect_timeout_seconds=endpoint.connect_timeout_seconds,
                read_timeout_seconds=endpoint.read_timeout_seconds,
                verify_tls=endpoint.verify_tls,
                ca_bundle_path=endpoint.ca_bundle_path,
            )
            driver = OnlyAgentSessionDriverV1(
                reducer=reducer,
                sessions=session_contexts,
                materializer=materializer,
                model_occurrences=models,
                tool_occurrences=tools,
                model_adapter=OnlyOpenAICompatibleModelAdapterV1(
                    config=endpoint,
                    resources=resources,
                    contexts=contexts,
                    transport=model_transport,
                ),
                product_adapter=product_adapter,
                coordination=OnlyAgentSessionExecutionCoordinatorV1(coordination_root),
            )
            return _RequestScopedVerificationDriver(driver, (decision_cache, model_cache, tool_cache))

        request_driver = driver_for(model)
        control = OnlyAgentNodeControlServiceV1(
            resources=resources,
            briefs=briefs,
            sessions=sessions,
            semantic_bundle=bundle,
            driver=request_driver,
            provider_runtime=provider_runtime,
            provider_resolver=provider_resolver,
            provider_bindings=(None if provider_runtime is None else OnlyJsonAgentProviderBindingStoreV1(durable_root)),
            model_profiles=(None if provider_runtime is None else OnlyJsonAgentModelProfileStoreV1(durable_root)),
            product_contract_fingerprint=(None if provider_runtime is None else product_contract.fingerprint),
            provider_driver_factory=(None if provider_runtime is None else driver_for),
        )
        control.bootstrap()
        workflow = build_current_agent_workflow_implementation_manifest()
        return cls(
            control,
            workflow.implementation_fingerprint,
            durable_root,
            coordination_root,
            product.contract_path,
            product_contract.fingerprint,
        )

    @classmethod
    def compose_from_integration(
        cls,
        *,
        durable_root: Path,
        coordination_root: Path,
        product: OnlyProductApiEndpointConfigV1,
        provider_resolver: OnlyAgentProviderRuntimeAuthority,
        model_profile: OnlyAgentModelProfileV1,
    ) -> OnlyAgentProductionRuntimeV1:
        provider_runtime = provider_resolver.admit_new(model_profile)
        return cls.compose(
            durable_root=durable_root,
            coordination_root=coordination_root,
            product=product,
            model=provider_runtime.endpoint,
            provider_runtime=provider_runtime,
            provider_resolver=provider_resolver,
        )


__all__ = [name for name in globals() if name.startswith("OnlyAgent")]
