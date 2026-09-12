"""Production composition root for the independently deployable Agent node."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

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
from onlyalpha.research.agent.verification import OnlyAgentResearchBriefReferenceReadersV1
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
from .node_service import OnlyAgentNodeControlServiceV1
from .semantic_bundle import load_production_semantic_bundle_v1


class _LateBindingProxy:
    target: object | None = None

    def __getattr__(self, name: str) -> Any:
        if self.target is None:
            raise RuntimeError("AGENT_PRODUCTION_COMPOSITION_INCOMPLETE")
        return getattr(self.target, name)


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

    def verify_exact_reference(self, reference: OnlyAgentExactAuthorityReference) -> None:
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
        kind = reference.reference_kind
        value = reference.locator_value
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
        path = paths.get(kind)
        if path is None:
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

    @classmethod
    def compose(
        cls,
        *,
        durable_root: Path,
        coordination_root: Path,
        product: OnlyProductApiEndpointConfigV1,
        model: OnlyOpenAICompatibleEndpointConfigV1,
    ) -> OnlyAgentProductionRuntimeV1:
        if not durable_root.is_absolute() or not coordination_root.is_absolute():
            raise ValueError("AGENT_PRODUCTION_ROOT_INVALID")
        durable_root.mkdir(parents=True, exist_ok=True)
        client = OnlyAgentProductHttpControlPlaneClientV1(product)
        brief_references = OnlyApiBackedAgentBriefReferenceReaderV1(client)
        reference_readers = OnlyAgentResearchBriefReferenceReadersV1(
            brief_references,
            brief_references,
            brief_references,
        )
        resources = OnlyJsonAgentOrchestrationResourceStore(durable_root)
        briefs = OnlyJsonAgentResearchBriefStore(durable_root, reference_readers)
        sessions = OnlyJsonAgentSessionManifestStore(durable_root, briefs=briefs, resources=resources)
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
        decisions = OnlyAgentDecisionApplicationServiceV1(
            sessions=sessions,
            models=model_proxy,
            tools=tool_proxy,
            references=contexts,
            store=decision_store,
            search_states=search_states,
            research_states=research_states,
            runtime_generations=OnlyApiBackedAgentRuntimeGenerationReaderV1(client),
            evidence_causality=causality,
        )
        decision_proxy.target = decisions
        models = OnlyAgentModelOccurrenceServiceV1(
            sessions=sessions,
            resources=resources,
            references=contexts,
            decisions=decision_proxy,
            store=model_store,
        )
        tools = OnlyAgentToolOccurrenceServiceV1(
            sessions=sessions,
            decisions=decision_proxy,
            product_contracts=product_contract,
            references=contexts,
            response_references=contexts,
            store=tool_store,
        )
        model_proxy.target = models
        tool_proxy.target = tools
        launches = OnlyAgentExperimentLaunchServiceV1(
            sessions=sessions,
            decisions=decisions,
            tools=tools,
            child_searches=contexts,
            store=launch_store,
        )
        reducer = OnlyAgentSessionReducerV1(
            sessions=sessions,
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
        model_transport = OnlyRawHttpTransportV1(
            connect_timeout_seconds=model.connect_timeout_seconds,
            read_timeout_seconds=model.read_timeout_seconds,
            verify_tls=model.verify_tls,
            ca_bundle_path=model.ca_bundle_path,
        )
        product_adapter = OnlyContractDrivenProductApiAdapterV1(product, product_transport)
        model_adapter = OnlyOpenAICompatibleModelAdapterV1(
            config=model,
            resources=resources,
            contexts=contexts,
            transport=model_transport,
        )
        materializer = OnlyAgentWorkflowActionMaterializerV1(
            sessions=sessions,
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
        driver = OnlyAgentSessionDriverV1(
            reducer=reducer,
            sessions=sessions,
            materializer=materializer,
            model_occurrences=models,
            tool_occurrences=tools,
            model_adapter=model_adapter,
            product_adapter=product_adapter,
            coordination=OnlyAgentSessionExecutionCoordinatorV1(coordination_root),
        )
        control = OnlyAgentNodeControlServiceV1(
            resources=resources,
            briefs=briefs,
            sessions=sessions,
            semantic_bundle=bundle,
            driver=driver,
        )
        workflow = control.bootstrap()
        return cls(control, workflow)


__all__ = [name for name in globals() if name.startswith("OnlyAgent")]
