"""Exact Reducer-action materialization from durable facts and owning inputs."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Never, Protocol, cast

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.agent.application import (
    OnlyAgentDecisionApplicationServiceV1,
    OnlyAgentEvidenceCausalVerifierV1,
    OnlyAgentEvidenceQueryCausalVerifier,
    OnlyAgentExperimentLaunchServiceV1,
    OnlyAgentVerifiedEvidencePathV1,
)
from onlyalpha.research.agent.authority_state import (
    OnlyAgentResearchStateReader,
    OnlyAgentSearchStateReader,
)
from onlyalpha.research.agent.decision import (
    OnlyAgentDecisionKind,
    OnlyAgentParameterSearchDirectiveV1,
    OnlyAgentReuseDirectiveV1,
    OnlyAgentSearchDirectiveV1,
    OnlyAgentSymbolicSearchDirectiveV1,
)
from onlyalpha.research.agent.errors import OnlyAgentContextError
from onlyalpha.research.agent.model import (
    OnlyAgentRolePolicyPayloadV1,
    OnlyAgentToolClass,
    OnlyAgentWorkflowImplementationManifestV1,
)
from onlyalpha.research.agent.occurrence import (
    OnlyAgentContextReferenceV1,
    OnlyAgentExactAuthorityReference,
    OnlyAgentToolCallOutcome,
    OnlyAgentToolCallPlanV1,
    OnlyAgentToolCallResultV1,
)
from onlyalpha.research.agent.occurrence_service import (
    OnlyAgentModelOccurrenceServiceV1,
    OnlyAgentProductApiContractReader,
    OnlyAgentSessionContextReader,
    OnlyAgentToolOccurrenceServiceV1,
    OnlyPreparedAgentModelCallV1,
    OnlyPreparedAgentToolCallV1,
)
from onlyalpha.research.agent.semantic_translation import (
    ONLYAGENT_PARAMETER_SEARCH_WORKFLOW_BINDING_V1,
    ONLYAGENT_SEARCH_DECISION_ENGINE_BINDING_V1,
    ONLYAGENT_SYMBOLIC_SEARCH_WORKFLOW_BINDING_V1,
    translate_agent_hypothesis_to_search_hypothesis,
)
from onlyalpha.research.agent.session_state import (
    OnlyAgentNextActionKind,
    OnlyAgentNextActionV1,
)
from onlyalpha.research.agent.verification import OnlyVerifiedAgentDecisionContextV1

from .bindings import OnlyAgentModelInvocationBindingReader

_CATALOG_OPERATION = "get_complete_exact_catalog_context_v2"
_RESOLVE_OPERATION = "resolve_definition_api_v2_research_definitions_resolve_post"
_RESEARCH_SUBMIT_OPERATION = "submit_research_run_command_v2"
_RESEARCH_OBSERVE_OPERATION = "get_run_api_v2_research_runs__run_id__get"
_EVIDENCE_OPERATION = "statistics_catalog_api_v2_research_artifacts__research_result_fingerprint__statistics_get"
_SYMBOLIC_SUBMIT_OPERATION = "submit_symbolic_search_experiment_v2"
_PARAMETER_SUBMIT_OPERATION = "submit_parameter_search_experiment_v2"
_SYMBOLIC_ADVANCE_OPERATION = "advance_symbolic_search_experiment_v2"
_PARAMETER_ADVANCE_OPERATION = "advance_parameter_search_experiment_v2"
_SEARCH_TERMINAL_OPERATION = "get_search_terminal_v2"


class OnlyAgentNewWorkRuntimeGenerationReader(Protocol):
    """Read-only current new-work input; the owning Runtime still admits it."""

    def read_current_new_work_runtime_generation_fingerprint(self) -> str: ...


class OnlyAgentWorkflowSemanticInputReader(Protocol):
    """Narrow exact-load port for request payloads owned outside Orchestrator."""

    def load_semantic_payload_verified(self, reference: OnlyAgentExactAuthorityReference) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class OnlyAgentMaterializedToolIntentV1:
    operation_identity: str
    canonical_request: Mapping[str, object]
    exact_identity_inputs: tuple[OnlyAgentExactAuthorityReference, ...]
    product_command_id: str | None


class OnlyAgentWorkflowActionMaterializerV1:
    """Materialize one exact formal intent without deriving workflow progress."""

    def __init__(
        self,
        *,
        sessions: OnlyAgentSessionContextReader,
        models: OnlyAgentModelOccurrenceServiceV1,
        tools: OnlyAgentToolOccurrenceServiceV1,
        decisions: OnlyAgentDecisionApplicationServiceV1,
        launches: OnlyAgentExperimentLaunchServiceV1,
        invocation_bindings: OnlyAgentModelInvocationBindingReader,
        product_contracts: OnlyAgentProductApiContractReader,
        semantic_inputs: OnlyAgentWorkflowSemanticInputReader,
        runtime_generations: OnlyAgentNewWorkRuntimeGenerationReader,
        search_states: OnlyAgentSearchStateReader | None = None,
        research_states: OnlyAgentResearchStateReader | None = None,
        evidence_causality: OnlyAgentEvidenceQueryCausalVerifier | None = None,
        product_api_major: int = 2,
        product_api_contract_fingerprint: str,
        uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._sessions = sessions
        self._models = models
        self._tools = tools
        self._decisions = decisions
        self._launches = launches
        self._bindings = invocation_bindings
        self._contracts = product_contracts
        self._semantic_inputs = semantic_inputs
        self._runtime_generations = runtime_generations
        self._search_states = search_states
        self._research_states = research_states
        self._evidence_causality = evidence_causality or OnlyAgentEvidenceCausalVerifierV1(
            tools=tools,
            launches=launches,
            semantic_inputs=semantic_inputs,
            research_states=research_states,
            search_states=search_states,
        )
        self._product_api_major = product_api_major
        self._product_api_contract_fingerprint = product_api_contract_fingerprint
        self._uuid_factory = uuid_factory

    def prepare_model_call(
        self,
        *,
        session_fingerprint: str,
        action: OnlyAgentNextActionV1,
        current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1,
    ) -> OnlyPreparedAgentModelCallV1:
        if action.action_kind is not OnlyAgentNextActionKind.PREPARE_MODEL_CALL or action.logical_role is None:
            raise OnlyAgentContextError("AGENT_POLICY_VIOLATION", "Reducer action is not a Model preparation")
        binding = self._bindings.load_model_invocation_binding_verified(action.logical_role)
        if binding.logical_role != action.logical_role:
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Invocation Binding role differs")
        context = self._sessions.load_session_manifest_verified(session_fingerprint)
        matching_roles = tuple(
            resource
            for resource in context.ordered_role_policy_resources
            if isinstance(resource.canonical_payload, OnlyAgentRolePolicyPayloadV1)
            and resource.canonical_payload.logical_role_id == action.logical_role
        )
        if len(matching_roles) != 1:
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Role Policy is ambiguous")
        ordinal = self._models.budget_consumed(session_fingerprint)
        parent = None
        references: tuple[OnlyAgentContextReferenceV1, ...]
        if action.logical_role == "RESEARCH_PLANNER":
            references = (_sha_reference("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint),)
        elif action.logical_role == "SEARCH_ROUTER":
            parent = self._decisions.load_decision_by_session_ordinal_verified(
                session_fingerprint, 0
            ).decision_fingerprint
            catalog = self._tools.load_result_verified(
                self._tools.load_plan_by_session_ordinal_verified(session_fingerprint, 0).tool_call_plan_fingerprint
            )
            references = (
                _sha_reference("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint),
                _sha_reference("AGENT_TOOL_CALL_RESULT", catalog.tool_call_result_fingerprint),
            )
        elif action.logical_role == "FACTOR_DESIGNER":
            parent = self._decisions.load_decision_by_session_ordinal_verified(
                session_fingerprint, 0
            ).decision_fingerprint
            catalog = self._tools.load_result_verified(
                self._tools.load_plan_by_session_ordinal_verified(session_fingerprint, 0).tool_call_plan_fingerprint
            )
            router = self._models.load_result_verified(
                self._models.load_plan_by_session_ordinal_verified(session_fingerprint, 1).model_call_plan_fingerprint
            )
            references = (
                _sha_reference("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint),
                _sha_reference("AGENT_TOOL_CALL_RESULT", catalog.tool_call_result_fingerprint),
                _sha_reference("AGENT_MODEL_CALL_RESULT", router.model_call_result_fingerprint),
            )
        elif action.logical_role == "EVIDENCE_ANALYST":
            parent = self._decisions.load_decision_by_session_ordinal_verified(
                session_fingerprint, 1
            ).decision_fingerprint
            references = self._derive_evidence_model_context(session_fingerprint)
        else:
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Unknown logical role")
        return self._models.prepare_model_call(
            session_fingerprint=session_fingerprint,
            current_workflow_manifest=current_workflow_manifest,
            call_ordinal=ordinal,
            logical_role=action.logical_role,
            role_policy_fingerprint=matching_roles[0].resource_fingerprint,
            provider_id=binding.provider_id,
            model_id=binding.model_id,
            model_version=binding.model_version,
            prompt_template_fingerprint=binding.prompt_template_fingerprint,
            structured_output_schema_fingerprint=binding.structured_output_schema_fingerprint,
            model_execution_policy_fingerprint=binding.model_execution_policy_fingerprint,
            response_affecting_settings=binding.response_affecting_settings,
            ordered_context_references=references,
            parent_agent_decision_fingerprint=parent,
        )

    def prepare_tool_call(
        self,
        *,
        session_fingerprint: str,
        action: OnlyAgentNextActionV1,
        current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1,
    ) -> OnlyPreparedAgentToolCallV1:
        if action.action_kind not in {
            OnlyAgentNextActionKind.PREPARE_TOOL_CALL,
            OnlyAgentNextActionKind.PREPARE_NEW_TOOL_OBSERVATION,
            OnlyAgentNextActionKind.PREPARE_AUTHORITY_TOOL_CALL,
        }:
            raise OnlyAgentContextError("AGENT_POLICY_VIOLATION", "Reducer action is not a Tool preparation")
        intent = self._materialize_tool_intent(session_fingerprint, action)
        ordinal = self._tools.budget_consumed(session_fingerprint)
        authorizing = self._decisions.load_decision_by_session_ordinal_verified(
            session_fingerprint,
            0 if action.tool_class is OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY else 1,
        )
        return self._tools.prepare_tool_call(
            session_fingerprint=session_fingerprint,
            current_workflow_manifest=current_workflow_manifest,
            tool_call_ordinal=ordinal,
            authorizing_agent_decision_fingerprint=authorizing.decision_fingerprint,
            tool_class=cast(OnlyAgentToolClass, action.tool_class),
            product_api_major=self._product_api_major,
            product_api_contract_fingerprint=self._product_api_contract_fingerprint,
            operation_identity=intent.operation_identity,
            canonical_request=intent.canonical_request,
            exact_identity_inputs=intent.exact_identity_inputs,
            product_command_id_or_idempotency_key=intent.product_command_id,
        )

    def derive_decision(
        self,
        *,
        session_fingerprint: str,
        decision_kind: OnlyAgentDecisionKind,
        current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1,
    ) -> None:
        if decision_kind is OnlyAgentDecisionKind.RESEARCH_PLAN:
            model = self._models.load_result_verified(
                self._models.load_plan_by_session_ordinal_verified(session_fingerprint, 0).model_call_plan_fingerprint
            )
            self._decisions.derive_research_plan(
                session_fingerprint=session_fingerprint,
                planner_model_result_fingerprint=model.model_call_result_fingerprint,
                current_workflow_manifest=current_workflow_manifest,
            )
            return
        if decision_kind is OnlyAgentDecisionKind.SEARCH_DIRECTIVE:
            router = self._models.load_result_verified(
                self._models.load_plan_by_session_ordinal_verified(session_fingerprint, 1).model_call_plan_fingerprint
            )
            catalog = self._tools.load_result_verified(
                self._tools.load_plan_by_session_ordinal_verified(session_fingerprint, 0).tool_call_plan_fingerprint
            )
            factor = None
            if self._models.budget_consumed(session_fingerprint) > 2:
                factor = self._models.load_result_verified(
                    self._models.load_plan_by_session_ordinal_verified(
                        session_fingerprint, 2
                    ).model_call_plan_fingerprint
                ).model_call_result_fingerprint
            self._decisions.derive_search_directive(
                session_fingerprint=session_fingerprint,
                router_model_result_fingerprint=router.model_call_result_fingerprint,
                catalog_tool_result_fingerprint=catalog.tool_call_result_fingerprint,
                factor_designer_model_result_fingerprint=factor,
                current_workflow_manifest=current_workflow_manifest,
            )
            return
        if decision_kind is OnlyAgentDecisionKind.NEXT_EXPERIMENT_PROPOSAL:
            analyst = self._models.load_result_verified(
                self._models.load_plan_by_session_ordinal_verified(session_fingerprint, 3).model_call_plan_fingerprint
            )
            self._decisions.derive_next_experiment_proposal(
                session_fingerprint=session_fingerprint,
                evidence_analyst_model_result_fingerprint=analyst.model_call_result_fingerprint,
                current_workflow_manifest=current_workflow_manifest,
            )
            return
        raise OnlyAgentContextError("AGENT_POLICY_VIOLATION", "Unknown Decision kind")

    def reconstruct_launch(
        self,
        *,
        session_fingerprint: str,
        tool_result_fingerprint: str,
        current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1,
    ) -> None:
        decision = self._decisions.load_decision_by_session_ordinal_verified(session_fingerprint, 1)
        result = self._tools.load_result_by_fingerprint_verified(tool_result_fingerprint)
        children = tuple(
            reference
            for reference in result.owning_authority_references
            if reference.reference_kind == "SEARCH_EXPERIMENT"
        )
        if len(children) != 1:
            raise OnlyAgentContextError("AGENT_EXPERIMENT_LAUNCH_INVALID", "child Search reference")
        self._launches.reconstruct_launch_record(
            session_fingerprint=session_fingerprint,
            agent_decision_fingerprint=decision.decision_fingerprint,
            tool_call_result_fingerprint=tool_result_fingerprint,
            child_search_experiment_fingerprint=children[0].locator_value,
            current_workflow_manifest=current_workflow_manifest,
        )

    def _materialize_tool_intent(
        self, session_fingerprint: str, action: OnlyAgentNextActionV1
    ) -> OnlyAgentMaterializedToolIntentV1:
        context = self._sessions.load_session_manifest_verified(session_fingerprint)
        if action.tool_class is OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY:
            reference = _sha_reference("CATALOG_GENERATION", context.research_brief.catalog_generation_fingerprint)
            return OnlyAgentMaterializedToolIntentV1(
                _CATALOG_OPERATION,
                {"catalog_generation_fingerprint": reference.reference_fingerprint},
                (reference,),
                None,
            )
        decision = self._decisions.load_decision_by_session_ordinal_verified(session_fingerprint, 1)
        directive = cast(OnlyAgentSearchDirectiveV1, decision.structured_payload)
        payload = directive.action_payload
        if action.tool_class is OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE:
            if not isinstance(payload, OnlyAgentReuseDirectiveV1):
                self._invalid_tool(action)
            assert isinstance(payload, OnlyAgentReuseDirectiveV1)
            reference = payload.research_definition_reference
            return OnlyAgentMaterializedToolIntentV1(
                _RESOLVE_OPERATION,
                self._semantic_inputs.load_semantic_payload_verified(reference),
                (reference, *payload.reused_capability_references),
                None,
            )
        if action.tool_class is OnlyAgentToolClass.RESEARCH_RUN_SUBMIT:
            resolved = self._first_successful_result(
                session_fingerprint, OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE
            )
            response = resolved.canonical_validated_response
            if response is None or not isinstance(response.get("exact_specification"), Mapping):
                raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", "resolved Specification")
            return OnlyAgentMaterializedToolIntentV1(
                _RESEARCH_SUBMIT_OPERATION,
                {"specification": response["exact_specification"]},
                resolved.owning_authority_references,
                self._new_product_command_id(),
            )
        if action.tool_class is OnlyAgentToolClass.RESEARCH_RUN_QUERY:
            submitted = self._first_successful_result(session_fingerprint, OnlyAgentToolClass.RESEARCH_RUN_SUBMIT)
            runs = tuple(
                reference
                for reference in submitted.owning_authority_references
                if reference.reference_kind == "RESEARCH_RUN"
            )
            if len(runs) != 1:
                raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", "Research Run reference")
            return OnlyAgentMaterializedToolIntentV1(
                _RESEARCH_OBSERVE_OPERATION, {"run_id": runs[0].locator_value}, runs, None
            )
        if action.tool_class is OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY:
            evidence_reference = self._derive_evidence_query_reference(session_fingerprint)
            return OnlyAgentMaterializedToolIntentV1(
                _EVIDENCE_OPERATION,
                {"research_result_fingerprint": evidence_reference.locator_value},
                (evidence_reference,),
                None,
            )
        if action.tool_class in {OnlyAgentToolClass.SYMBOLIC_SEARCH, OnlyAgentToolClass.PARAMETER_SEARCH}:
            if action.action_kind is OnlyAgentNextActionKind.PREPARE_AUTHORITY_TOOL_CALL:
                return self._search_advance_intent(session_fingerprint, action)
            return self._search_submit_intent(context, directive)
        if action.tool_class is OnlyAgentToolClass.SEARCH_QUERY:
            launch = self._launches.load_launch_record_by_session_verified(session_fingerprint)
            reference = _sha_reference("SEARCH_EXPERIMENT", launch.child_search_experiment_fingerprint)
            return OnlyAgentMaterializedToolIntentV1(
                _SEARCH_TERMINAL_OPERATION,
                {"experiment_fingerprint": reference.reference_fingerprint},
                (reference,),
                None,
            )
        self._invalid_tool(action)

    def _derive_evidence_query_reference(self, session_fingerprint: str) -> OnlyAgentContextReferenceV1:
        return self._derive_evidence_path(session_fingerprint).research_result_reference

    def _derive_evidence_model_context(self, session_fingerprint: str) -> tuple[OnlyAgentContextReferenceV1, ...]:
        path = self._derive_evidence_path(session_fingerprint)
        evidence_occurrences = self._tool_occurrences(session_fingerprint, OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY)
        if len(evidence_occurrences) != 1:
            self._evidence_unavailable("Evidence query occurrence")
        plan, result = evidence_occurrences[0]
        if (
            plan.tool_call_ordinal <= path.observation_ordinal
            or result is None
            or result.outcome is not OnlyAgentToolCallOutcome.SUCCEEDED
            or sum(
                _same_reference(reference, path.research_result_reference) for reference in plan.exact_identity_inputs
            )
            != 1
            or any(
                reference.reference_kind == "RESEARCH_RESULT"
                and not _same_reference(reference, path.research_result_reference)
                for reference in plan.exact_identity_inputs
            )
            or sum(
                _same_reference(reference, path.research_result_reference)
                for reference in result.owning_authority_references
            )
            != 1
        ):
            self._evidence_unavailable("Evidence query causal closure")
        response = result.canonical_validated_response
        if (
            not isinstance(response, Mapping)
            or response.get("research_result_fingerprint") != path.research_result_reference.reference_fingerprint
        ):
            self._evidence_unavailable("Evidence response identity")
        try:
            response_references = self._contracts.response_references_verified(plan, response)
        except Exception as exc:
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Evidence response reference schema") from exc
        canonical_references = tuple(
            _sha_reference(reference.reference_kind, reference.locator_value) for reference in response_references
        )
        if canonical_references.count(path.research_result_reference) != 1:
            self._evidence_unavailable("Research Result response reference")
        statistics = tuple(
            reference for reference in canonical_references if reference.reference_kind == "RESEARCH_STATISTICS"
        )
        if not statistics:
            self._evidence_unavailable("Research Statistics references")
        if len(statistics) != len(set(statistics)):
            self._evidence_unavailable("Duplicate Research Statistics reference")
        try:
            for reference in statistics:
                self._semantic_inputs.load_semantic_payload_verified(reference)
        except Exception as exc:
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Research Statistics Authority") from exc
        return (
            path.completed_path_reference,
            path.research_result_reference,
            *statistics,
        )

    def _derive_evidence_path(self, session_fingerprint: str) -> OnlyAgentVerifiedEvidencePathV1:
        decision = self._decisions.load_decision_by_session_ordinal_verified(session_fingerprint, 1)
        return self._evidence_causality.derive_evidence_path(decision)

    def _tool_occurrences(
        self, session_fingerprint: str, tool_class: OnlyAgentToolClass
    ) -> tuple[tuple[OnlyAgentToolCallPlanV1, OnlyAgentToolCallResultV1 | None], ...]:
        occurrences: list[tuple[OnlyAgentToolCallPlanV1, OnlyAgentToolCallResultV1 | None]] = []
        for ordinal in range(self._tools.budget_consumed(session_fingerprint)):
            plan = self._tools.load_plan_by_session_ordinal_verified(session_fingerprint, ordinal)
            if plan.tool_class is not tool_class:
                continue
            result = (
                self._tools.load_result_verified(plan.tool_call_plan_fingerprint)
                if self._tools.result_exists(plan.tool_call_plan_fingerprint)
                else None
            )
            occurrences.append((plan, result))
        return tuple(occurrences)

    @staticmethod
    def _evidence_unavailable(detail: str) -> Never:
        raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", detail)

    def _search_submit_intent(
        self,
        context: OnlyVerifiedAgentDecisionContextV1,
        directive: OnlyAgentSearchDirectiveV1,
    ) -> OnlyAgentMaterializedToolIntentV1:
        payload = directive.action_payload
        if isinstance(payload, OnlyAgentSymbolicSearchDirectiveV1):
            operation = _SYMBOLIC_SUBMIT_OPERATION
            workflow = ONLYAGENT_SYMBOLIC_SEARCH_WORKFLOW_BINDING_V1
            method_payload: dict[str, object] = {}
        elif isinstance(payload, OnlyAgentParameterSearchDirectiveV1):
            operation = _PARAMETER_SUBMIT_OPERATION
            workflow = ONLYAGENT_PARAMETER_SEARCH_WORKFLOW_BINDING_V1
            method_payload = {
                "search_policy": self._semantic_inputs.load_semantic_payload_verified(payload.search_policy_reference)
            }
        else:
            raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", "Search Submit")
        generation = self._runtime_generations.read_current_new_work_runtime_generation_fingerprint()
        generation_reference = _sha_reference("RUNTIME_GENERATION", generation)
        catalog_reference = _sha_reference("CATALOG_GENERATION", context.research_brief.catalog_generation_fingerprint)
        dataset_reference = _sha_reference("DATASET_SNAPSHOT", context.research_brief.dataset_snapshot_fingerprint)
        references = tuple(
            item
            for item in (
                payload.search_space_reference,
                payload.evaluation_reference,
                getattr(payload, "search_policy_reference", None),
                payload.algorithm_reference,
                payload.search_budget_reference,
                catalog_reference,
                dataset_reference,
                generation_reference,
            )
            if item is not None
        )
        request = {
            "schema_version": 2,
            "hypothesis": translate_agent_hypothesis_to_search_hypothesis(context.research_brief.hypothesis).to_dict(),
            "catalog_generation_fingerprint": catalog_reference.reference_fingerprint,
            "dataset_snapshot_fingerprint": dataset_reference.reference_fingerprint,
            "search_space": self._semantic_inputs.load_semantic_payload_verified(payload.search_space_reference),
            "evaluation_contract": self._semantic_inputs.load_semantic_payload_verified(payload.evaluation_reference),
            "algorithm_manifest": self._semantic_inputs.load_semantic_payload_verified(payload.algorithm_reference),
            "search_budget": self._semantic_inputs.load_semantic_payload_verified(payload.search_budget_reference),
            "workflow_binding": workflow.to_dict(),
            "decision_engine_binding": ONLYAGENT_SEARCH_DECISION_ENGINE_BINDING_V1.to_dict(),
            "parent_experiment_fingerprint": None,
            "runtime_generation_fingerprint": generation,
            **method_payload,
        }
        return OnlyAgentMaterializedToolIntentV1(
            operation,
            request,
            cast(tuple[OnlyAgentExactAuthorityReference, ...], references),
            self._new_product_command_id(),
        )

    def _search_advance_intent(
        self, session_fingerprint: str, action: OnlyAgentNextActionV1
    ) -> OnlyAgentMaterializedToolIntentV1:
        if self._search_states is None or action.operation_identity is None:
            raise OnlyAgentContextError("AGENT_SEARCH_FAILED", session_fingerprint)
        launch = self._launches.load_launch_record_by_session_verified(session_fingerprint)
        authority = self._search_states.load_search_state_verified(launch.child_search_experiment_fingerprint)
        if (
            authority.next_bounded_operation is None
            or authority.next_bounded_operation.value != action.operation_identity
        ):
            raise OnlyAgentContextError("AGENT_SEARCH_FAILED", "stale Reducer action")
        expected = authority.expected_state.to_dict()
        expected_fingerprint = only_canonical_fingerprint(expected)
        child = _sha_reference("SEARCH_EXPERIMENT", launch.child_search_experiment_fingerprint)
        expected_reference = _sha_reference("SEARCH_EXPECTED_STATE", expected_fingerprint)
        method = authority.terminal.method.value
        operation = (
            _SYMBOLIC_ADVANCE_OPERATION
            if action.tool_class is OnlyAgentToolClass.SYMBOLIC_SEARCH
            else _PARAMETER_ADVANCE_OPERATION
        )
        return OnlyAgentMaterializedToolIntentV1(
            operation,
            {
                "schema_version": 1,
                "experiment_fingerprint": launch.child_search_experiment_fingerprint,
                "method": method,
                "operation": action.operation_identity,
                "expected_state": expected,
            },
            (child, expected_reference),
            self._new_product_command_id(),
        )

    def _first_successful_result(
        self, session_fingerprint: str, tool_class: OnlyAgentToolClass
    ) -> OnlyAgentToolCallResultV1:
        for ordinal in range(self._tools.budget_consumed(session_fingerprint)):
            plan = self._tools.load_plan_by_session_ordinal_verified(session_fingerprint, ordinal)
            if plan.tool_class is tool_class and self._tools.result_exists(plan.tool_call_plan_fingerprint):
                return self._tools.load_result_verified(plan.tool_call_plan_fingerprint)
        raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", tool_class.value)

    def _new_product_command_id(self) -> str:
        value = self._uuid_factory()
        if not isinstance(value, uuid.UUID) or value.version != 4:
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", "Product Command ID factory")
        return str(value)

    @staticmethod
    def _invalid_tool(action: OnlyAgentNextActionV1) -> Never:
        raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", repr(action))


def _sha_reference(kind: str, fingerprint: str) -> OnlyAgentContextReferenceV1:
    return OnlyAgentContextReferenceV1(kind, 1, fingerprint)


def _same_reference(
    left: OnlyAgentExactAuthorityReference,
    right: OnlyAgentExactAuthorityReference,
) -> bool:
    return (
        left.reference_kind,
        left.reference_schema_version,
        left.locator_kind,
        left.locator_value,
    ) == (
        right.reference_kind,
        right.reference_schema_version,
        right.locator_kind,
        right.locator_value,
    )


__all__ = [name for name in globals() if name.startswith("OnlyAgent")]
