"""Deterministic Agent Decision application and launch reconstruction services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from typing import Protocol, cast

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.experiment.model import (
    OnlySearchDecisionMode,
    OnlySearchExperimentManifestV2,
    OnlySearchExperimentManifestV3,
)

from .authority_state import OnlyAgentResearchStateReader, OnlyAgentSearchStateReader
from .decision import (
    OnlyAgentCapabilityGapDirectiveV1,
    OnlyAgentDecisionKind,
    OnlyAgentDecisionV1,
    OnlyAgentEvaluationPathKind,
    OnlyAgentExperimentLaunchRecordV1,
    OnlyAgentNextExperimentProposalV1,
    OnlyAgentParameterSearchDirectiveV1,
    OnlyAgentResearchPlanV1,
    OnlyAgentReuseDirectiveV1,
    OnlyAgentRouterAction,
    OnlyAgentSearchDirectivePayloadV1,
    OnlyAgentSearchDirectiveV1,
    OnlyAgentSymbolicSearchDirectiveV1,
)
from .decision_store import OnlyJsonAgentDecisionStore, OnlyJsonAgentExperimentLaunchStore
from .errors import OnlyAgentContextError
from .model import (
    OnlyAgentRolePolicyPayloadV1,
    OnlyAgentSearchMethod,
    OnlyAgentToolClass,
    OnlyAgentToolPolicyPayloadV1,
    OnlyAgentWorkflowImplementationManifestV1,
)
from .occurrence import (
    OnlyAgentContextReferenceV1,
    OnlyAgentExactAuthorityReference,
    OnlyAgentModelCallOutcome,
    OnlyAgentModelCallPlanV1,
    OnlyAgentModelCallResultV1,
    OnlyAgentToolCallOutcome,
    OnlyAgentToolCallPlanV1,
    OnlyAgentToolCallResultV1,
)
from .occurrence_service import (
    OnlyAgentDecisionAuthorizationV1,
    OnlyAgentProductRequestSemanticProjectionV1,
    OnlyAgentSessionContextReader,
)
from .semantic_translation import (
    OnlyAgentSearchRuntimeGenerationAuthority,
    expected_agent_search_submit_semantics,
)
from .store import OnlyAgentCommitOutcome
from .verification import OnlyVerifiedAgentDecisionContextV1
from .workflow import admit_agent_workflow_runtime


class OnlyAgentModelOccurrenceReaderV1(Protocol):
    def load_plan_verified(self, plan_fingerprint: str) -> OnlyAgentModelCallPlanV1: ...

    def load_result_by_fingerprint_verified(self, result_fingerprint: str) -> OnlyAgentModelCallResultV1: ...

    def load_plan_by_session_ordinal_verified(
        self, session_fingerprint: str, ordinal: int
    ) -> OnlyAgentModelCallPlanV1: ...

    def result_exists(self, plan_fingerprint: str) -> bool: ...

    def load_result_verified(self, plan_fingerprint: str) -> OnlyAgentModelCallResultV1: ...

    def budget_consumed(self, session_fingerprint: str) -> int: ...


class OnlyAgentToolOccurrenceReaderV1(Protocol):
    def load_plan_verified(self, plan_fingerprint: str) -> OnlyAgentToolCallPlanV1: ...

    def load_result_by_fingerprint_verified(self, result_fingerprint: str) -> OnlyAgentToolCallResultV1: ...

    def load_plan_by_session_ordinal_verified(
        self, session_fingerprint: str, ordinal: int
    ) -> OnlyAgentToolCallPlanV1: ...

    def result_exists(self, plan_fingerprint: str) -> bool: ...

    def load_result_verified(self, plan_fingerprint: str) -> OnlyAgentToolCallResultV1: ...

    def budget_consumed(self, session_fingerprint: str) -> int: ...

    def recovery_class(self, plan_fingerprint: str): ...  # type: ignore[no-untyped-def]


class OnlyAgentExactContextReaderV1(Protocol):
    def verify_exact_reference(self, reference: OnlyAgentExactAuthorityReference) -> None: ...

    def verify_completed_evaluation_path(
        self,
        reference: OnlyAgentExactAuthorityReference,
        path_kind: OnlyAgentEvaluationPathKind,
    ) -> None: ...


class OnlyAgentChildSearchExperimentReader(Protocol):
    def load_experiment_verified(
        self, experiment_fingerprint: str
    ) -> OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3: ...


_EXPECTED_DECISION_ROLES = {
    OnlyAgentDecisionKind.RESEARCH_PLAN: "RESEARCH_PLANNER",
    OnlyAgentDecisionKind.SEARCH_DIRECTIVE: "SEARCH_ROUTER",
    OnlyAgentDecisionKind.NEXT_EXPERIMENT_PROPOSAL: "EVIDENCE_ANALYST",
}


def _role(context: OnlyVerifiedAgentDecisionContextV1, logical_role: str) -> tuple[str, OnlyAgentRolePolicyPayloadV1]:
    matches = tuple(
        resource
        for resource in context.ordered_role_policy_resources
        if isinstance(resource.canonical_payload, OnlyAgentRolePolicyPayloadV1)
        and resource.canonical_payload.logical_role_id == logical_role
    )
    if len(matches) != 1:
        raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", logical_role)
    return matches[0].resource_fingerprint, cast(OnlyAgentRolePolicyPayloadV1, matches[0].canonical_payload)


def _reference(kind: str, fingerprint: str) -> OnlyAgentContextReferenceV1:
    return OnlyAgentContextReferenceV1(kind, 1, fingerprint)


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


def _action_payload(value: object, action: OnlyAgentRouterAction) -> OnlyAgentSearchDirectivePayloadV1:
    if not isinstance(value, Mapping):
        raise OnlyAgentContextError("AGENT_MODEL_RESPONSE_INVALID", "action_payload")
    try:
        payload = cast(Mapping[str, object], _plain_json(value))
        if action is OnlyAgentRouterAction.REUSE_EXISTING:
            return OnlyAgentReuseDirectiveV1.from_dict(payload)
        if action is OnlyAgentRouterAction.SYMBOLIC_SEARCH:
            return OnlyAgentSymbolicSearchDirectiveV1.from_dict(payload)
        if action is OnlyAgentRouterAction.PARAMETER_SEARCH:
            return OnlyAgentParameterSearchDirectiveV1.from_dict(payload)
        return OnlyAgentCapabilityGapDirectiveV1.from_dict(payload)
    except Exception as exc:
        raise OnlyAgentContextError("AGENT_MODEL_RESPONSE_INVALID", "Search Directive payload") from exc


class OnlyAgentDecisionApplicationServiceV1:
    """The only production path that may derive and publish an Agent Decision."""

    def __init__(
        self,
        *,
        sessions: OnlyAgentSessionContextReader,
        models: OnlyAgentModelOccurrenceReaderV1,
        tools: OnlyAgentToolOccurrenceReaderV1,
        references: OnlyAgentExactContextReaderV1,
        store: OnlyJsonAgentDecisionStore,
        search_states: OnlyAgentSearchStateReader | None = None,
        research_states: OnlyAgentResearchStateReader | None = None,
        runtime_generations: OnlyAgentSearchRuntimeGenerationAuthority | None = None,
    ) -> None:
        self._sessions = sessions
        self._models = models
        self._tools = tools
        self._references = references
        self._store = store
        self._search_states = search_states
        self._research_states = research_states
        self._runtime_generations = runtime_generations

    def derive_research_plan(
        self,
        *,
        session_fingerprint: str,
        planner_model_result_fingerprint: str,
        current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1,
    ) -> tuple[OnlyAgentDecisionV1, OnlyAgentCommitOutcome]:
        context = self._admit(session_fingerprint, current_workflow_manifest)
        result, plan = self._returned_model(
            planner_model_result_fingerprint,
            context,
            expected_role="RESEARCH_PLANNER",
            expected_call_ordinal=0,
            expected_parent=None,
        )
        expected_context = (_reference("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint),)
        if plan.ordered_context_references != expected_context:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Planner context")
        roles = tuple(
            cast(OnlyAgentRolePolicyPayloadV1, item.canonical_payload).logical_role_id
            for item in context.ordered_role_policy_resources
        )
        required = ("RESEARCH_PLANNER", "SEARCH_ROUTER", "FACTOR_DESIGNER", "EVIDENCE_ANALYST")
        if roles != required:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Workflow role order")
        allowed = tuple(OnlyAgentRouterAction(item.value) for item in context.research_brief.allowed_search_methods) + (
            OnlyAgentRouterAction.CAPABILITY_GAP,
        )
        payload = OnlyAgentResearchPlanV1(
            context.research_brief.research_brief_fingerprint,
            roles,
            allowed,
            context.research_brief.agent_budget,
        )
        decision = self._decision(
            context,
            ordinal=0,
            kind=OnlyAgentDecisionKind.RESEARCH_PLAN,
            model_results=(result.model_call_result_fingerprint,),
            tool_results=(),
            context_references=expected_context,
            payload=payload,
        )
        return self._publish(decision)

    def derive_search_directive(
        self,
        *,
        session_fingerprint: str,
        router_model_result_fingerprint: str,
        catalog_tool_result_fingerprint: str,
        current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1,
        factor_designer_model_result_fingerprint: str | None = None,
    ) -> tuple[OnlyAgentDecisionV1, OnlyAgentCommitOutcome]:
        context = self._admit(session_fingerprint, current_workflow_manifest)
        plan_decision = self.load_decision_by_session_ordinal_verified(session_fingerprint, 0)
        catalog_result, catalog_plan = self._succeeded_tool(
            catalog_tool_result_fingerprint,
            context,
            OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
            plan_decision.decision_fingerprint,
        )
        if not any(
            item.locator_value == context.research_brief.catalog_generation_fingerprint
            for item in catalog_result.owning_authority_references
        ):
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Catalog Generation binding")
        router_result, router_plan = self._returned_model(
            router_model_result_fingerprint,
            context,
            expected_role="SEARCH_ROUTER",
            expected_call_ordinal=1,
            expected_parent=plan_decision.decision_fingerprint,
        )
        router_output = cast(Mapping[str, object], router_result.validated_structured_output)
        if set(router_output) not in ({"router_action"}, {"router_action", "action_payload"}):
            raise OnlyAgentContextError("AGENT_MODEL_RESPONSE_INVALID", "Router output")
        try:
            action = OnlyAgentRouterAction(str(router_output["router_action"]))
        except Exception as exc:
            raise OnlyAgentContextError("AGENT_MODEL_RESPONSE_INVALID", "Router action") from exc
        executable = {
            OnlyAgentRouterAction.REUSE_EXISTING,
            OnlyAgentRouterAction.SYMBOLIC_SEARCH,
            OnlyAgentRouterAction.PARAMETER_SEARCH,
        }
        if (
            action in executable
            and OnlyAgentSearchMethod(action.value) not in context.research_brief.allowed_search_methods
        ):
            raise OnlyAgentContextError("AGENT_POLICY_VIOLATION", action.value)
        expected_router_context = (
            _reference("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint),
            _reference("AGENT_TOOL_CALL_RESULT", catalog_result.tool_call_result_fingerprint),
        )
        if router_plan.ordered_context_references != expected_router_context:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Router context")
        model_results = [router_result.model_call_result_fingerprint]
        context_references = list(expected_router_context)
        if action is OnlyAgentRouterAction.CAPABILITY_GAP:
            if factor_designer_model_result_fingerprint is not None or "action_payload" not in router_output:
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Capability Gap branch")
            action_payload = _action_payload(router_output["action_payload"], action)
        else:
            if factor_designer_model_result_fingerprint is None or "action_payload" in router_output:
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Factor Designer branch")
            designer_result, designer_plan = self._returned_model(
                factor_designer_model_result_fingerprint,
                context,
                expected_role="FACTOR_DESIGNER",
                expected_call_ordinal=2,
                expected_parent=plan_decision.decision_fingerprint,
            )
            designer_output = cast(Mapping[str, object], designer_result.validated_structured_output)
            if set(designer_output) != {"action_payload"}:
                raise OnlyAgentContextError("AGENT_MODEL_RESPONSE_INVALID", "Factor Designer output")
            expected_designer_context = (
                *expected_router_context,
                _reference("AGENT_MODEL_CALL_RESULT", router_result.model_call_result_fingerprint),
            )
            if designer_plan.ordered_context_references != expected_designer_context:
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Factor Designer context")
            action_payload = _action_payload(designer_output["action_payload"], action)
            model_results.append(designer_result.model_call_result_fingerprint)
            context_references.extend(expected_designer_context[len(expected_router_context) :])
        self._verify_action_references(action_payload, context)
        payload = OnlyAgentSearchDirectiveV1(action, catalog_result.tool_call_result_fingerprint, action_payload)
        decision = self._decision(
            context,
            ordinal=1,
            kind=OnlyAgentDecisionKind.SEARCH_DIRECTIVE,
            model_results=tuple(model_results),
            tool_results=(catalog_result.tool_call_result_fingerprint,),
            context_references=tuple(context_references),
            payload=payload,
        )
        if catalog_plan.agent_session_fingerprint != session_fingerprint:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Catalog Tool Session")
        return self._publish(decision)

    def derive_next_experiment_proposal(
        self,
        *,
        session_fingerprint: str,
        evidence_analyst_model_result_fingerprint: str,
        current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1,
    ) -> tuple[OnlyAgentDecisionV1, OnlyAgentCommitOutcome]:
        context = self._admit(session_fingerprint, current_workflow_manifest)
        directive_decision = self.load_decision_by_session_ordinal_verified(session_fingerprint, 1)
        directive = cast(OnlyAgentSearchDirectiveV1, directive_decision.structured_payload)
        if directive.router_action is OnlyAgentRouterAction.CAPABILITY_GAP:
            raise OnlyAgentContextError("AGENT_POLICY_VIOLATION", "Capability Gap is terminal")
        expected_call_ordinal = 3
        analyst_result, analyst_plan = self._returned_model(
            evidence_analyst_model_result_fingerprint,
            context,
            expected_role="EVIDENCE_ANALYST",
            expected_call_ordinal=expected_call_ordinal,
            expected_parent=directive_decision.decision_fingerprint,
        )
        output = cast(Mapping[str, object], _plain_json(analyst_result.validated_structured_output))
        try:
            payload = OnlyAgentNextExperimentProposalV1.from_dict(output)
        except Exception as exc:
            raise OnlyAgentContextError("AGENT_MODEL_RESPONSE_INVALID", "Next Experiment Proposal") from exc
        expected_path = (
            OnlyAgentEvaluationPathKind.DIRECT_REUSE_RESEARCH
            if directive.router_action is OnlyAgentRouterAction.REUSE_EXISTING
            else OnlyAgentEvaluationPathKind.CHILD_SEARCH
        )
        if payload.evaluation_path_kind is not expected_path:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Evaluation path")
        for reference in (
            payload.completed_path_reference,
            *payload.research_result_references,
            *payload.research_statistics_references,
        ):
            self._references.verify_exact_reference(reference)
        expected_context = (
            payload.completed_path_reference,
            *payload.research_result_references,
            *payload.research_statistics_references,
        )
        if analyst_plan.ordered_context_references != expected_context:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Evidence Analyst context")
        self._verify_evidence_closure(context, payload)
        tool_results = self._consumed_tool_results(context)
        decision = self._decision(
            context,
            ordinal=2,
            kind=OnlyAgentDecisionKind.NEXT_EXPERIMENT_PROPOSAL,
            model_results=(analyst_result.model_call_result_fingerprint,),
            tool_results=tool_results,
            context_references=expected_context,
            payload=payload,
        )
        return self._publish(decision)

    def load_decision_verified(self, decision_fingerprint: str) -> OnlyAgentDecisionV1:
        decision = self._store.load_decision_verified(decision_fingerprint)
        context = self._sessions.load_session_manifest_verified(decision.agent_session_fingerprint)
        if decision.workflow_implementation_fingerprint != context.session.agent_workflow_implementation_fingerprint:
            raise OnlyAgentContextError("AGENT_DECISION_INVALID", decision_fingerprint)
        role_fingerprint, _ = _role(context, _EXPECTED_DECISION_ROLES[decision.decision_kind])
        if decision.role_policy_fingerprint != role_fingerprint:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision_fingerprint)
        self._verify_historical_decision(decision, context)
        return decision

    def load_decision_by_session_ordinal_verified(self, session_fingerprint: str, ordinal: int) -> OnlyAgentDecisionV1:
        value = self._store.load_decision_by_session_ordinal_verified(session_fingerprint, ordinal)
        return self.load_decision_verified(value.decision_fingerprint)

    def load_decision_authorization_verified(self, decision_fingerprint: str) -> OnlyAgentDecisionAuthorizationV1:
        decision = self.load_decision_verified(decision_fingerprint)
        context = self._sessions.load_session_manifest_verified(decision.agent_session_fingerprint)
        allowed: set[OnlyAgentToolClass]
        if decision.decision_kind is OnlyAgentDecisionKind.RESEARCH_PLAN:
            allowed = {OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY}
        elif decision.decision_kind is OnlyAgentDecisionKind.SEARCH_DIRECTIVE:
            directive = cast(OnlyAgentSearchDirectiveV1, decision.structured_payload)
            allowed = {
                OnlyAgentRouterAction.REUSE_EXISTING: {
                    OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE,
                    OnlyAgentToolClass.RESEARCH_RUN_SUBMIT,
                    OnlyAgentToolClass.RESEARCH_RUN_QUERY,
                    OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY,
                },
                OnlyAgentRouterAction.SYMBOLIC_SEARCH: {
                    OnlyAgentToolClass.SYMBOLIC_SEARCH,
                    OnlyAgentToolClass.SEARCH_QUERY,
                    OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY,
                },
                OnlyAgentRouterAction.PARAMETER_SEARCH: {
                    OnlyAgentToolClass.PARAMETER_SEARCH,
                    OnlyAgentToolClass.SEARCH_QUERY,
                    OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY,
                },
                OnlyAgentRouterAction.CAPABILITY_GAP: set(),
            }[directive.router_action]
        else:
            allowed = set()
        policy = context.tool_policy_resource.canonical_payload
        if not isinstance(policy, OnlyAgentToolPolicyPayloadV1):
            raise OnlyAgentContextError("AGENT_POLICY_VIOLATION", decision_fingerprint)
        allowed.intersection_update(policy.allowed_tool_classes)
        _, role_policy = _role(context, decision.logical_role)
        allowed.intersection_update(role_policy.allowed_tool_classes)
        operations = tuple(
            item.operation_identity for item in policy.operation_constraints if item.tool_class in allowed
        )
        return OnlyAgentDecisionAuthorizationV1(
            decision.decision_fingerprint,
            decision.agent_session_fingerprint,
            decision.workflow_implementation_fingerprint,
            tuple(sorted(allowed, key=lambda item: item.value)),
            operations,
        )

    def verify_historical_tool_intent(
        self,
        *,
        decision_fingerprint: str,
        tool_class: OnlyAgentToolClass,
        operation_identity: str,
        semantic_projection: OnlyAgentProductRequestSemanticProjectionV1,
        exact_identity_inputs: tuple[OnlyAgentExactAuthorityReference, ...],
        tool_call_ordinal: int,
    ) -> None:
        """Verify a stored intent using immutable facts only."""

        authorization = self.load_decision_authorization_verified(decision_fingerprint)
        if (
            tool_class not in authorization.permitted_tool_classes
            or operation_identity not in authorization.permitted_operation_identities
            or semantic_projection.operation_identity != operation_identity
        ):
            raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
        decision = self.load_decision_verified(decision_fingerprint)
        context = self._sessions.load_session_manifest_verified(decision.agent_session_fingerprint)
        supplied = set(exact_identity_inputs)
        required: set[OnlyAgentExactAuthorityReference] = set()
        if decision.decision_kind is OnlyAgentDecisionKind.RESEARCH_PLAN:
            required = {_reference("CATALOG_GENERATION", context.research_brief.catalog_generation_fingerprint)}
        elif decision.decision_kind is OnlyAgentDecisionKind.SEARCH_DIRECTIVE:
            directive = cast(OnlyAgentSearchDirectiveV1, decision.structured_payload)
            payload = directive.action_payload
            if tool_class is OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE:
                if not isinstance(payload, OnlyAgentReuseDirectiveV1):
                    raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
                required = {payload.research_definition_reference}
            elif tool_class is OnlyAgentToolClass.RESEARCH_RUN_SUBMIT:
                if not isinstance(payload, OnlyAgentReuseDirectiveV1):
                    raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
                required = {
                    reference
                    for ordinal in range(tool_call_ordinal)
                    for plan in (
                        self._tools.load_plan_by_session_ordinal_verified(decision.agent_session_fingerprint, ordinal),
                    )
                    if plan.tool_class is OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE
                    and self._tools.result_exists(plan.tool_call_plan_fingerprint)
                    for reference in self._tools.load_result_verified(
                        plan.tool_call_plan_fingerprint
                    ).owning_authority_references
                }
                if not required:
                    raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
            elif tool_class in {OnlyAgentToolClass.SYMBOLIC_SEARCH, OnlyAgentToolClass.PARAMETER_SEARCH}:
                if not isinstance(payload, (OnlyAgentSymbolicSearchDirectiveV1, OnlyAgentParameterSearchDirectiveV1)):
                    raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
                configuration = {
                    value
                    for value in (getattr(payload, field.name) for field in fields(payload))
                    if isinstance(value, OnlyAgentExactAuthorityReference)
                }
                configuration.update(
                    {
                        _reference("CATALOG_GENERATION", context.research_brief.catalog_generation_fingerprint),
                        _reference("DATASET_SNAPSHOT", context.research_brief.dataset_snapshot_fingerprint),
                    }
                )
                children = tuple(reference for reference in supplied if reference.reference_kind == "SEARCH_EXPERIMENT")
                if not children:
                    runtime_references = tuple(
                        reference for reference in supplied if reference.reference_kind == "RUNTIME_GENERATION"
                    )
                    runtime_generation = semantic_projection.semantic_bindings.get("runtime_generation_fingerprint")
                    if (
                        len(runtime_references) != 1
                        or not isinstance(runtime_generation, str)
                        or runtime_references[0].locator_value != runtime_generation
                    ):
                        raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
                    configuration.add(runtime_references[0])
                prior_children = {
                    reference
                    for ordinal in range(tool_call_ordinal)
                    for plan in (
                        self._tools.load_plan_by_session_ordinal_verified(decision.agent_session_fingerprint, ordinal),
                    )
                    if plan.tool_class
                    in {
                        OnlyAgentToolClass.SYMBOLIC_SEARCH,
                        OnlyAgentToolClass.PARAMETER_SEARCH,
                    }
                    and self._tools.result_exists(plan.tool_call_plan_fingerprint)
                    for reference in self._tools.load_result_verified(
                        plan.tool_call_plan_fingerprint
                    ).owning_authority_references
                    if reference.reference_kind == "SEARCH_EXPERIMENT"
                }
                required = configuration if configuration.issubset(supplied) else prior_children
                if not required:
                    raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
            else:
                # Query/reconcile intent must bind a concrete owning fact produced by the
                # already-authorized path; a bare caller-selected identity is not enough.
                source_classes = {
                    OnlyAgentToolClass.RESEARCH_RUN_QUERY: {OnlyAgentToolClass.RESEARCH_RUN_SUBMIT},
                    OnlyAgentToolClass.SEARCH_QUERY: {
                        OnlyAgentToolClass.SYMBOLIC_SEARCH,
                        OnlyAgentToolClass.PARAMETER_SEARCH,
                    },
                    OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY: {
                        OnlyAgentToolClass.RESEARCH_RUN_QUERY,
                        OnlyAgentToolClass.SEARCH_QUERY,
                    },
                }.get(tool_class, set())
                prior_owned = {
                    reference
                    for ordinal in range(tool_call_ordinal)
                    for plan in (
                        self._tools.load_plan_by_session_ordinal_verified(decision.agent_session_fingerprint, ordinal),
                    )
                    if plan.tool_class in source_classes
                    if self._tools.result_exists(plan.tool_call_plan_fingerprint)
                    for reference in self._tools.load_result_verified(
                        plan.tool_call_plan_fingerprint
                    ).owning_authority_references
                }
                if not supplied.intersection(prior_owned):
                    raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
                required = set()
        else:
            raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
        brief_kinds = {
            "CATALOG_GENERATION": context.research_brief.catalog_generation_fingerprint,
            "DATASET_SNAPSHOT": context.research_brief.dataset_snapshot_fingerprint,
            "RESEARCH_EVALUATION": context.research_brief.evaluation_context_reference.evaluation_fingerprint,
        }
        if any(
            reference.reference_kind in brief_kinds and reference.locator_value != brief_kinds[reference.reference_kind]
            for reference in supplied
        ):
            raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
        if not required.issubset(supplied):
            raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
        self._verify_projected_semantics(
            context=context,
            decision=decision,
            tool_class=tool_class,
            projection=semantic_projection,
            exact_identity_inputs=exact_identity_inputs,
        )

    def admit_new_tool_intent(
        self,
        *,
        decision_fingerprint: str,
        tool_class: OnlyAgentToolClass,
        operation_identity: str,
        semantic_projection: OnlyAgentProductRequestSemanticProjectionV1,
        exact_identity_inputs: tuple[OnlyAgentExactAuthorityReference, ...],
        tool_call_ordinal: int,
    ) -> None:
        """Admit new work, adding current owning-Authority constraints when needed."""

        self.verify_historical_tool_intent(
            decision_fingerprint=decision_fingerprint,
            tool_class=tool_class,
            operation_identity=operation_identity,
            semantic_projection=semantic_projection,
            exact_identity_inputs=exact_identity_inputs,
            tool_call_ordinal=tool_call_ordinal,
        )
        if tool_class not in {OnlyAgentToolClass.SYMBOLIC_SEARCH, OnlyAgentToolClass.PARAMETER_SEARCH}:
            return
        children = tuple(
            reference for reference in exact_identity_inputs if reference.reference_kind == "SEARCH_EXPERIMENT"
        )
        expected_states = tuple(
            reference for reference in exact_identity_inputs if reference.reference_kind == "SEARCH_EXPECTED_STATE"
        )
        if not children and not expected_states:
            runtime_generation = semantic_projection.semantic_bindings.get("runtime_generation_fingerprint")
            if not isinstance(runtime_generation, str) or self._runtime_generations is None:
                raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
            try:
                self._runtime_generations.require_new_work_generation(runtime_generation)
            except Exception as exc:
                raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity) from exc
            return
        if len(children) != 1 or len(expected_states) != 1 or self._search_states is None:
            raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
        authority = self._search_states.load_search_state_verified(children[0].locator_value)
        expected = only_canonical_fingerprint(authority.expected_state.to_dict())
        operation = authority.next_bounded_operation
        if (
            expected_states[0].locator_value != expected
            or operation is None
            or operation_identity not in {operation.value, f"search.{operation.value.lower()}.v1"}
            or semantic_projection.semantic_bindings["child_experiment_fingerprint"] != children[0].locator_value
            or semantic_projection.semantic_bindings["expected_search_state_fingerprint"] != expected
            or semantic_projection.semantic_bindings["bounded_operation"] != operation.value
        ):
            raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)

    @staticmethod
    def _verify_projected_semantics(
        *,
        context: OnlyVerifiedAgentDecisionContextV1,
        decision: OnlyAgentDecisionV1,
        tool_class: OnlyAgentToolClass,
        projection: OnlyAgentProductRequestSemanticProjectionV1,
        exact_identity_inputs: tuple[OnlyAgentExactAuthorityReference, ...],
    ) -> None:
        bindings = projection.semantic_bindings
        expected_scalars = {
            "catalog_generation_fingerprint": context.research_brief.catalog_generation_fingerprint,
            "dataset_snapshot_fingerprint": context.research_brief.dataset_snapshot_fingerprint,
        }
        for name, expected in expected_scalars.items():
            if name in bindings and bindings[name] != expected:
                raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", projection.operation_identity)
        if "parent_experiment_fingerprint" in bindings and bindings["parent_experiment_fingerprint"] is not None:
            raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", projection.operation_identity)
        if isinstance(bindings.get("decision_engine_binding"), Mapping):
            mode = cast(Mapping[str, object], bindings["decision_engine_binding"]).get("mode")
            if mode != "DETERMINISTIC":
                raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", projection.operation_identity)
        if decision.decision_kind is OnlyAgentDecisionKind.SEARCH_DIRECTIVE:
            directive = cast(OnlyAgentSearchDirectiveV1, decision.structured_payload)
            expected_method = {
                OnlyAgentRouterAction.SYMBOLIC_SEARCH: {"SYMBOLIC", "SYMBOLIC_SEARCH"},
                OnlyAgentRouterAction.PARAMETER_SEARCH: {"PARAMETER", "PARAMETER_SEARCH"},
            }.get(directive.router_action)
            if expected_method is not None and "method" in bindings and bindings["method"] not in expected_method:
                raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", projection.operation_identity)
            directive_payload = directive.action_payload
            if tool_class in {OnlyAgentToolClass.SYMBOLIC_SEARCH, OnlyAgentToolClass.PARAMETER_SEARCH} and isinstance(
                directive_payload,
                (OnlyAgentSymbolicSearchDirectiveV1, OnlyAgentParameterSearchDirectiveV1),
            ):
                children = tuple(
                    reference for reference in exact_identity_inputs if reference.reference_kind == "SEARCH_EXPERIMENT"
                )
                if not children:
                    runtime_generation = bindings.get("runtime_generation_fingerprint")
                    if not isinstance(runtime_generation, str):
                        raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", projection.operation_identity)
                    compiled_semantics = expected_agent_search_submit_semantics(
                        operation_identity=projection.operation_identity,
                        context=context,
                        directive=directive,
                        runtime_generation_fingerprint=runtime_generation,
                    )
                    if bindings != compiled_semantics.semantic_bindings:
                        raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", projection.operation_identity)
                else:
                    required = {
                        "method",
                        "child_experiment_fingerprint",
                        "expected_search_state_fingerprint",
                        "bounded_operation",
                    }
                    if not required.issubset(bindings):
                        raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", projection.operation_identity)

    def _admit(
        self, session_fingerprint: str, manifest: OnlyAgentWorkflowImplementationManifestV1
    ) -> OnlyVerifiedAgentDecisionContextV1:
        context = self._sessions.load_session_manifest_verified(session_fingerprint)
        admit_agent_workflow_runtime(context.workflow_resource, manifest)
        return context

    def _verify_historical_decision(
        self,
        decision: OnlyAgentDecisionV1,
        context: OnlyVerifiedAgentDecisionContextV1,
    ) -> None:
        """Verify frozen causal facts without executing the current transformation."""

        expected_shape = {
            OnlyAgentDecisionKind.RESEARCH_PLAN: (0, 1, 0),
            OnlyAgentDecisionKind.SEARCH_DIRECTIVE: (1, None, 1),
            OnlyAgentDecisionKind.NEXT_EXPERIMENT_PROPOSAL: (2, 1, None),
        }[decision.decision_kind]
        if decision.decision_ordinal != expected_shape[0]:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
        if expected_shape[1] is not None and len(decision.ordered_model_call_result_fingerprints) != expected_shape[1]:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
        if expected_shape[2] is not None and len(decision.ordered_tool_call_result_fingerprints) != expected_shape[2]:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
        if decision.decision_kind is OnlyAgentDecisionKind.SEARCH_DIRECTIVE and len(
            decision.ordered_model_call_result_fingerprints
        ) not in (1, 2):
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
        for fingerprint in decision.ordered_model_call_result_fingerprints:
            model_result = self._models.load_result_by_fingerprint_verified(fingerprint)
            model_plan = self._models.load_plan_verified(model_result.model_call_plan_fingerprint)
            if (
                model_result.outcome is not OnlyAgentModelCallOutcome.RETURNED
                or model_plan.agent_session_fingerprint != decision.agent_session_fingerprint
            ):
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", fingerprint)
        for fingerprint in decision.ordered_tool_call_result_fingerprints:
            tool_result = self._tools.load_result_by_fingerprint_verified(fingerprint)
            tool_plan = self._tools.load_plan_verified(tool_result.tool_call_plan_fingerprint)
            if (
                tool_result.outcome is not OnlyAgentToolCallOutcome.SUCCEEDED
                or tool_plan.agent_session_fingerprint != decision.agent_session_fingerprint
            ):
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", fingerprint)
        for reference in decision.ordered_context_references:
            self._references.verify_exact_reference(reference)
        if decision.decision_kind is OnlyAgentDecisionKind.RESEARCH_PLAN:
            result, plan = self._returned_model(
                decision.ordered_model_call_result_fingerprints[0],
                context,
                expected_role="RESEARCH_PLANNER",
                expected_call_ordinal=0,
                expected_parent=None,
            )
            del result
            planner_context = (_reference("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint),)
            research_plan_payload = cast(OnlyAgentResearchPlanV1, decision.structured_payload)
            frozen_roles = tuple(
                cast(OnlyAgentRolePolicyPayloadV1, resource.canonical_payload).logical_role_id
                for resource in context.ordered_role_policy_resources
            )
            permitted = set(research_plan_payload.permitted_router_actions)
            brief_permitted = {
                OnlyAgentRouterAction(method.value) for method in context.research_brief.allowed_search_methods
            } | {OnlyAgentRouterAction.CAPABILITY_GAP}
            if (
                plan.ordered_context_references != planner_context
                or decision.ordered_context_references != planner_context
                or research_plan_payload.research_brief_fingerprint != context.research_brief.research_brief_fingerprint
                or research_plan_payload.ordered_logical_role_sequence != frozen_roles
                or permitted != brief_permitted
                or research_plan_payload.agent_budget != context.research_brief.agent_budget
                or research_plan_payload.terminal_boundary != "ONE_EVALUATION_PATH_THEN_ADVISORY_PROPOSAL"
            ):
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
            return

        plan_decision = self.load_decision_by_session_ordinal_verified(context.session.session_fingerprint, 0)
        if decision.decision_kind is OnlyAgentDecisionKind.SEARCH_DIRECTIVE:
            directive = cast(OnlyAgentSearchDirectiveV1, decision.structured_payload)
            catalog_result, _ = self._succeeded_tool(
                decision.ordered_tool_call_result_fingerprints[0],
                context,
                OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
                plan_decision.decision_fingerprint,
            )
            if (
                directive.exact_catalog_context_tool_result_fingerprint != catalog_result.tool_call_result_fingerprint
                or sum(
                    reference.locator_value == context.research_brief.catalog_generation_fingerprint
                    for reference in catalog_result.owning_authority_references
                )
                != 1
            ):
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
            router_result, router_plan = self._returned_model(
                decision.ordered_model_call_result_fingerprints[0],
                context,
                expected_role="SEARCH_ROUTER",
                expected_call_ordinal=1,
                expected_parent=plan_decision.decision_fingerprint,
            )
            expected_router_context = (
                _reference("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint),
                _reference("AGENT_TOOL_CALL_RESULT", catalog_result.tool_call_result_fingerprint),
            )
            router_output = cast(Mapping[str, object], router_result.validated_structured_output)
            if router_output.get("router_action") != directive.router_action.value:
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
            executable = directive.router_action is not OnlyAgentRouterAction.CAPABILITY_GAP
            if router_plan.ordered_context_references != expected_router_context or executable != (
                len(decision.ordered_model_call_result_fingerprints) == 2
            ):
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
            directive_context = list(expected_router_context)
            if executable:
                designer_result, designer_plan = self._returned_model(
                    decision.ordered_model_call_result_fingerprints[1],
                    context,
                    expected_role="FACTOR_DESIGNER",
                    expected_call_ordinal=2,
                    expected_parent=plan_decision.decision_fingerprint,
                )
                designer_context = (
                    *expected_router_context,
                    _reference("AGENT_MODEL_CALL_RESULT", router_result.model_call_result_fingerprint),
                )
                if designer_plan.ordered_context_references != designer_context:
                    raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
                designer_output = cast(Mapping[str, object], designer_result.validated_structured_output)
                if (
                    set(designer_output) != {"action_payload"}
                    or _action_payload(designer_output["action_payload"], directive.router_action)
                    != directive.action_payload
                ):
                    raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
                directive_context.append(designer_context[-1])
                if (
                    OnlyAgentSearchMethod(directive.router_action.value)
                    not in context.research_brief.allowed_search_methods
                ):
                    raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
            elif (
                set(router_output) != {"router_action", "action_payload"}
                or _action_payload(router_output["action_payload"], directive.router_action) != directive.action_payload
            ):
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
            if decision.ordered_context_references != tuple(directive_context):
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
            self._verify_action_references(directive.action_payload, context)
            return

        directive_decision = self.load_decision_by_session_ordinal_verified(context.session.session_fingerprint, 1)
        directive = cast(OnlyAgentSearchDirectiveV1, directive_decision.structured_payload)
        proposal_payload = cast(OnlyAgentNextExperimentProposalV1, decision.structured_payload)
        analyst_result, analyst_plan = self._returned_model(
            decision.ordered_model_call_result_fingerprints[0],
            context,
            expected_role="EVIDENCE_ANALYST",
            expected_call_ordinal=3,
            expected_parent=directive_decision.decision_fingerprint,
        )
        try:
            historical_payload = OnlyAgentNextExperimentProposalV1.from_dict(
                cast(Mapping[str, object], _plain_json(analyst_result.validated_structured_output))
            )
        except Exception as exc:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint) from exc
        analyst_context = (
            proposal_payload.completed_path_reference,
            *proposal_payload.research_result_references,
            *proposal_payload.research_statistics_references,
        )
        expected_path = (
            OnlyAgentEvaluationPathKind.DIRECT_REUSE_RESEARCH
            if directive.router_action is OnlyAgentRouterAction.REUSE_EXISTING
            else OnlyAgentEvaluationPathKind.CHILD_SEARCH
        )
        if (
            directive.router_action is OnlyAgentRouterAction.CAPABILITY_GAP
            or historical_payload != proposal_payload
            or proposal_payload.evaluation_path_kind is not expected_path
            or analyst_plan.ordered_context_references != analyst_context
            or decision.ordered_context_references != analyst_context
        ):
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
        historical_plans = tuple(
            self._tools.load_plan_verified(
                self._tools.load_result_by_fingerprint_verified(fingerprint).tool_call_plan_fingerprint
            )
            for fingerprint in decision.ordered_tool_call_result_fingerprints
        )
        if not historical_plans:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
        publication_boundary = max(plan.tool_call_ordinal for plan in historical_plans) + 1
        self._verify_evidence_closure(
            context,
            proposal_payload,
            before_tool_ordinal=publication_boundary,
        )
        if decision.ordered_tool_call_result_fingerprints != self._consumed_tool_results(
            context, before_tool_ordinal=publication_boundary
        ):
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)

    def _derive_decision_from_exact_inputs(
        self,
        decision: OnlyAgentDecisionV1,
        context: OnlyVerifiedAgentDecisionContextV1,
    ) -> OnlyAgentDecisionV1:
        """Derive using executable semantics; callers must perform runtime admission."""

        if decision.decision_kind is OnlyAgentDecisionKind.RESEARCH_PLAN:
            if (
                len(decision.ordered_model_call_result_fingerprints) != 1
                or decision.ordered_tool_call_result_fingerprints
            ):
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
            result, plan = self._returned_model(
                decision.ordered_model_call_result_fingerprints[0],
                context,
                expected_role="RESEARCH_PLANNER",
                expected_call_ordinal=0,
                expected_parent=None,
            )
            expected_context = (_reference("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint),)
            if plan.ordered_context_references != expected_context:
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Planner context")
            roles = tuple(
                cast(OnlyAgentRolePolicyPayloadV1, item.canonical_payload).logical_role_id
                for item in context.ordered_role_policy_resources
            )
            if roles != ("RESEARCH_PLANNER", "SEARCH_ROUTER", "FACTOR_DESIGNER", "EVIDENCE_ANALYST"):
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Workflow role order")
            allowed = tuple(
                OnlyAgentRouterAction(item.value) for item in context.research_brief.allowed_search_methods
            ) + (OnlyAgentRouterAction.CAPABILITY_GAP,)
            return self._decision(
                context,
                ordinal=0,
                kind=OnlyAgentDecisionKind.RESEARCH_PLAN,
                model_results=(result.model_call_result_fingerprint,),
                tool_results=(),
                context_references=expected_context,
                payload=OnlyAgentResearchPlanV1(
                    context.research_brief.research_brief_fingerprint,
                    roles,
                    allowed,
                    context.research_brief.agent_budget,
                ),
            )

        if decision.decision_kind is OnlyAgentDecisionKind.SEARCH_DIRECTIVE:
            if len(decision.ordered_tool_call_result_fingerprints) != 1 or len(
                decision.ordered_model_call_result_fingerprints
            ) not in (1, 2):
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
            plan_decision = self.load_decision_by_session_ordinal_verified(context.session.session_fingerprint, 0)
            catalog_result, _ = self._succeeded_tool(
                decision.ordered_tool_call_result_fingerprints[0],
                context,
                OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
                plan_decision.decision_fingerprint,
            )
            if not any(
                item.locator_value == context.research_brief.catalog_generation_fingerprint
                for item in catalog_result.owning_authority_references
            ):
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Catalog Generation binding")
            router_result, router_plan = self._returned_model(
                decision.ordered_model_call_result_fingerprints[0],
                context,
                expected_role="SEARCH_ROUTER",
                expected_call_ordinal=1,
                expected_parent=plan_decision.decision_fingerprint,
            )
            router_output = cast(Mapping[str, object], router_result.validated_structured_output)
            if set(router_output) not in ({"router_action"}, {"router_action", "action_payload"}):
                raise OnlyAgentContextError("AGENT_MODEL_RESPONSE_INVALID", "Router output")
            try:
                action = OnlyAgentRouterAction(str(router_output["router_action"]))
            except Exception as exc:
                raise OnlyAgentContextError("AGENT_MODEL_RESPONSE_INVALID", "Router action") from exc
            executable = {
                OnlyAgentRouterAction.REUSE_EXISTING,
                OnlyAgentRouterAction.SYMBOLIC_SEARCH,
                OnlyAgentRouterAction.PARAMETER_SEARCH,
            }
            if (
                action in executable
                and OnlyAgentSearchMethod(action.value) not in context.research_brief.allowed_search_methods
            ):
                raise OnlyAgentContextError("AGENT_POLICY_VIOLATION", action.value)
            expected_router_context = (
                _reference("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint),
                _reference("AGENT_TOOL_CALL_RESULT", catalog_result.tool_call_result_fingerprint),
            )
            if router_plan.ordered_context_references != expected_router_context:
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Router context")
            model_results = [router_result.model_call_result_fingerprint]
            directive_context = list(expected_router_context)
            if action is OnlyAgentRouterAction.CAPABILITY_GAP:
                if len(decision.ordered_model_call_result_fingerprints) != 1 or "action_payload" not in router_output:
                    raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Capability Gap branch")
                action_payload = _action_payload(router_output["action_payload"], action)
            else:
                if len(decision.ordered_model_call_result_fingerprints) != 2 or "action_payload" in router_output:
                    raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Factor Designer branch")
                designer_result, designer_plan = self._returned_model(
                    decision.ordered_model_call_result_fingerprints[1],
                    context,
                    expected_role="FACTOR_DESIGNER",
                    expected_call_ordinal=2,
                    expected_parent=plan_decision.decision_fingerprint,
                )
                designer_output = cast(Mapping[str, object], designer_result.validated_structured_output)
                if set(designer_output) != {"action_payload"}:
                    raise OnlyAgentContextError("AGENT_MODEL_RESPONSE_INVALID", "Factor Designer output")
                designer_context = (
                    *expected_router_context,
                    _reference("AGENT_MODEL_CALL_RESULT", router_result.model_call_result_fingerprint),
                )
                if designer_plan.ordered_context_references != designer_context:
                    raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Factor Designer context")
                action_payload = _action_payload(designer_output["action_payload"], action)
                model_results.append(designer_result.model_call_result_fingerprint)
                directive_context.append(designer_context[-1])
            self._verify_action_references(action_payload, context)
            return self._decision(
                context,
                ordinal=1,
                kind=OnlyAgentDecisionKind.SEARCH_DIRECTIVE,
                model_results=tuple(model_results),
                tool_results=(catalog_result.tool_call_result_fingerprint,),
                context_references=tuple(directive_context),
                payload=OnlyAgentSearchDirectiveV1(action, catalog_result.tool_call_result_fingerprint, action_payload),
            )

        if len(decision.ordered_model_call_result_fingerprints) != 1:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision.decision_fingerprint)
        directive_decision = self.load_decision_by_session_ordinal_verified(context.session.session_fingerprint, 1)
        directive = cast(OnlyAgentSearchDirectiveV1, directive_decision.structured_payload)
        if directive.router_action is OnlyAgentRouterAction.CAPABILITY_GAP:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Capability Gap is terminal")
        analyst_result, analyst_plan = self._returned_model(
            decision.ordered_model_call_result_fingerprints[0],
            context,
            expected_role="EVIDENCE_ANALYST",
            expected_call_ordinal=3,
            expected_parent=directive_decision.decision_fingerprint,
        )
        try:
            payload = OnlyAgentNextExperimentProposalV1.from_dict(
                cast(Mapping[str, object], _plain_json(analyst_result.validated_structured_output))
            )
        except Exception as exc:
            raise OnlyAgentContextError("AGENT_MODEL_RESPONSE_INVALID", "Next Experiment Proposal") from exc
        expected_path = (
            OnlyAgentEvaluationPathKind.DIRECT_REUSE_RESEARCH
            if directive.router_action is OnlyAgentRouterAction.REUSE_EXISTING
            else OnlyAgentEvaluationPathKind.CHILD_SEARCH
        )
        if payload.evaluation_path_kind is not expected_path:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Evaluation path")
        evidence_context = (
            payload.completed_path_reference,
            *payload.research_result_references,
            *payload.research_statistics_references,
        )
        for reference in evidence_context:
            self._references.verify_exact_reference(reference)
        if analyst_plan.ordered_context_references != evidence_context:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Evidence Analyst context")
        self._verify_evidence_closure(context, payload)
        tool_results = self._consumed_tool_results(context)
        return self._decision(
            context,
            ordinal=2,
            kind=OnlyAgentDecisionKind.NEXT_EXPERIMENT_PROPOSAL,
            model_results=(analyst_result.model_call_result_fingerprint,),
            tool_results=tool_results,
            context_references=evidence_context,
            payload=payload,
        )

    def _returned_model(
        self,
        result_fingerprint: str,
        context: OnlyVerifiedAgentDecisionContextV1,
        *,
        expected_role: str,
        expected_call_ordinal: int,
        expected_parent: str | None,
    ) -> tuple[OnlyAgentModelCallResultV1, OnlyAgentModelCallPlanV1]:
        result = self._models.load_result_by_fingerprint_verified(result_fingerprint)
        plan = self._models.load_plan_verified(result.model_call_plan_fingerprint)
        expected_role_fingerprint, _ = _role(context, expected_role)
        if (
            result.outcome is not OnlyAgentModelCallOutcome.RETURNED
            or result.validated_structured_output is None
            or plan.agent_session_fingerprint != context.session.session_fingerprint
            or plan.logical_role != expected_role
            or plan.role_policy_fingerprint != expected_role_fingerprint
            or plan.call_ordinal != expected_call_ordinal
            or plan.parent_agent_decision_fingerprint != expected_parent
        ):
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", result_fingerprint)
        return result, plan

    def _succeeded_tool(
        self,
        result_fingerprint: str,
        context: OnlyVerifiedAgentDecisionContextV1,
        expected_class: OnlyAgentToolClass,
        expected_decision: str,
    ) -> tuple[OnlyAgentToolCallResultV1, OnlyAgentToolCallPlanV1]:
        result = self._tools.load_result_by_fingerprint_verified(result_fingerprint)
        plan = self._tools.load_plan_verified(result.tool_call_plan_fingerprint)
        if (
            result.outcome is not OnlyAgentToolCallOutcome.SUCCEEDED
            or plan.agent_session_fingerprint != context.session.session_fingerprint
            or plan.tool_class is not expected_class
            or plan.authorizing_agent_decision_fingerprint != expected_decision
        ):
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", result_fingerprint)
        return result, plan

    def _verify_action_references(
        self, payload: OnlyAgentSearchDirectivePayloadV1, context: OnlyVerifiedAgentDecisionContextV1
    ) -> None:
        values = tuple(getattr(payload, field.name) for field in fields(payload))
        references = tuple(value for value in values if isinstance(value, OnlyAgentExactAuthorityReference)) + tuple(
            item
            for value in values
            if isinstance(value, tuple)
            for item in value
            if isinstance(item, OnlyAgentExactAuthorityReference)
        )
        for reference in references:
            self._references.verify_exact_reference(reference)
        evaluation = getattr(payload, "evaluation_reference", None)
        if isinstance(evaluation, OnlyAgentExactAuthorityReference) and (
            evaluation.locator_value != context.research_brief.evaluation_context_reference.evaluation_fingerprint
        ):
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Evaluation binding")

    @staticmethod
    def _observation_target(plan: OnlyAgentToolCallPlanV1) -> tuple[object, ...]:
        return (
            plan.tool_class,
            plan.operation_identity,
            plan.authorizing_agent_decision_fingerprint,
            tuple(
                reference
                for reference in plan.exact_identity_inputs
                if reference.reference_kind != "SEARCH_EXPECTED_STATE"
            ),
        )

    def _consumed_tool_results(
        self,
        context: OnlyVerifiedAgentDecisionContextV1,
        *,
        before_tool_ordinal: int | None = None,
    ) -> tuple[str, ...]:
        """Return successful Results consumed by Decision #2, tolerating superseded mutable gaps."""

        count = self._tools.budget_consumed(context.session.session_fingerprint)
        if before_tool_ordinal is not None:
            if before_tool_ordinal < 0 or before_tool_ordinal > count:
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Tool causal prefix")
            count = before_tool_ordinal
        plans = tuple(
            self._tools.load_plan_by_session_ordinal_verified(context.session.session_fingerprint, ordinal)
            for ordinal in range(count)
        )
        latest_mutable: dict[tuple[object, ...], int] = {}
        for plan in plans:
            if self._tools.recovery_class(plan.tool_call_plan_fingerprint).value == "MUTABLE_OBSERVATION_QUERY":
                latest_mutable[self._observation_target(plan)] = plan.tool_call_ordinal
        results: list[str] = []
        for plan in plans:
            mutable = self._tools.recovery_class(plan.tool_call_plan_fingerprint).value == "MUTABLE_OBSERVATION_QUERY"
            if not self._tools.result_exists(plan.tool_call_plan_fingerprint):
                if (
                    not mutable
                    or latest_mutable.get(self._observation_target(plan), plan.tool_call_ordinal)
                    <= plan.tool_call_ordinal
                ):
                    raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Open Tool occurrence")
                continue
            result = self._tools.load_result_verified(plan.tool_call_plan_fingerprint)
            if result.outcome is not OnlyAgentToolCallOutcome.SUCCEEDED:
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Failed Tool occurrence")
            if mutable and latest_mutable[self._observation_target(plan)] != plan.tool_call_ordinal:
                continue
            results.append(result.tool_call_result_fingerprint)
        return tuple(results)

    def _verify_evidence_closure(
        self,
        context: OnlyVerifiedAgentDecisionContextV1,
        payload: OnlyAgentNextExperimentProposalV1,
        *,
        before_tool_ordinal: int | None = None,
    ) -> None:
        count = self._tools.budget_consumed(context.session.session_fingerprint)
        if before_tool_ordinal is not None:
            if before_tool_ordinal < 0 or before_tool_ordinal > count:
                raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Tool causal prefix")
            count = before_tool_ordinal
        if count < 2:
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "No evaluation Tool facts")
        results: list[OnlyAgentToolCallResultV1] = []
        plans: list[OnlyAgentToolCallPlanV1] = []
        for ordinal in range(count):
            plan = self._tools.load_plan_by_session_ordinal_verified(context.session.session_fingerprint, ordinal)
            if not self._tools.result_exists(plan.tool_call_plan_fingerprint):
                if self._tools.recovery_class(plan.tool_call_plan_fingerprint).value != "MUTABLE_OBSERVATION_QUERY":
                    raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Open Tool occurrence")
                continue
            plans.append(plan)
            results.append(self._tools.load_result_verified(plan.tool_call_plan_fingerprint))
        if (
            plans[-1].tool_class is not OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY
            or results[-1].outcome is not OnlyAgentToolCallOutcome.SUCCEEDED
        ):
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Evidence query is not complete")
        evidence_result = results[-1]
        evidence_response = evidence_result.canonical_validated_response
        if not isinstance(evidence_response, Mapping):
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Evidence response is unavailable")
        result_fingerprint = evidence_response.get("research_result_fingerprint")
        raw_statistics = evidence_response.get("statistics")
        if not isinstance(result_fingerprint, str) or not isinstance(raw_statistics, tuple) or not raw_statistics:
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Evidence response reference closure")
        try:
            derived_results = (_reference("RESEARCH_RESULT", result_fingerprint),)
            derived_statistics = tuple(
                _reference(
                    "RESEARCH_STATISTICS",
                    cast(str, cast(Mapping[str, object], descriptor)["statistics_result_fingerprint"]),
                )
                for descriptor in raw_statistics
                if isinstance(descriptor, Mapping)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Evidence response reference closure") from exc
        if (
            len(derived_statistics) != len(raw_statistics)
            or len(derived_statistics) != len(set(derived_statistics))
            or evidence_result.owning_authority_references.count(derived_results[0]) != 1
            or any(
                evidence_result.owning_authority_references.count(reference) != 1 for reference in derived_statistics
            )
        ):
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Evidence response reference closure")
        try:
            self._references.verify_completed_evaluation_path(
                payload.completed_path_reference, payload.evaluation_path_kind
            )
        except Exception as exc:
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Authoritative terminal path") from exc
        if any(reference.reference_kind != "RESEARCH_RESULT" for reference in payload.research_result_references):
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Research Result reference kind")
        if any(
            reference.reference_kind != "RESEARCH_STATISTICS" for reference in payload.research_statistics_references
        ):
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Research Statistics reference kind")
        if (
            payload.research_result_references != derived_results
            or payload.research_statistics_references != derived_statistics
        ):
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Evidence reference closure")
        statistics = set(payload.research_statistics_references)
        if any(
            not set(observation.supporting_authority_references).issubset(statistics)
            for observation in payload.qualitative_observations
        ):
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Observation support closure")
        expected_path_tool = {
            OnlyAgentEvaluationPathKind.DIRECT_REUSE_RESEARCH: OnlyAgentToolClass.RESEARCH_RUN_QUERY,
            OnlyAgentEvaluationPathKind.CHILD_SEARCH: OnlyAgentToolClass.SEARCH_QUERY,
        }[payload.evaluation_path_kind]
        if not any(
            plan.tool_class is expected_path_tool
            and result.owning_authority_references.count(payload.completed_path_reference) == 1
            for plan, result in zip(plans[:-1], results[:-1], strict=True)
        ):
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Authoritative terminal path closure")

    @staticmethod
    def _verify_child_configuration(
        directive: OnlyAgentSearchDirectiveV1,
        child: OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3,
    ) -> None:
        payload = directive.action_payload
        if not isinstance(payload, (OnlyAgentSymbolicSearchDirectiveV1, OnlyAgentParameterSearchDirectiveV1)):
            raise OnlyAgentContextError("AGENT_EXPERIMENT_LAUNCH_INVALID", "Directive is not executable Search")
        expected_budget_fingerprint = only_canonical_fingerprint(child.search_budget.to_dict())
        common_invalid = (
            payload.search_space_reference.locator_value != child.search_space_reference.search_space_fingerprint
            or payload.algorithm_reference.locator_value != child.search_algorithm_binding.implementation_fingerprint
            or payload.search_budget_reference.locator_value != expected_budget_fingerprint
            or child.decision_engine_binding.mode is not OnlySearchDecisionMode.DETERMINISTIC
        )
        policy_invalid = isinstance(payload, OnlyAgentParameterSearchDirectiveV1) and (
            not isinstance(child, OnlySearchExperimentManifestV3)
            or payload.search_policy_reference.locator_value != child.search_policy_reference.policy_fingerprint
        )
        if common_invalid or policy_invalid:
            raise OnlyAgentContextError("AGENT_EXPERIMENT_LAUNCH_INVALID", "Child configuration differs")

    def _decision(
        self,
        context: OnlyVerifiedAgentDecisionContextV1,
        *,
        ordinal: int,
        kind: OnlyAgentDecisionKind,
        model_results: tuple[str, ...],
        tool_results: tuple[str, ...],
        context_references: tuple[OnlyAgentContextReferenceV1, ...],
        payload: object,
    ) -> OnlyAgentDecisionV1:
        role_fingerprint, _ = _role(context, _EXPECTED_DECISION_ROLES[kind])
        return OnlyAgentDecisionV1(
            context.session.session_fingerprint,
            ordinal,
            kind,
            _EXPECTED_DECISION_ROLES[kind],
            role_fingerprint,
            model_results,
            tool_results,
            context_references,
            payload,  # type: ignore[arg-type]
            context.session.agent_workflow_implementation_fingerprint,
        )

    def _publish(self, decision: OnlyAgentDecisionV1) -> tuple[OnlyAgentDecisionV1, OnlyAgentCommitOutcome]:
        outcome = self._store.commit_decision(decision)
        exact = self.load_decision_verified(decision.decision_fingerprint)
        return exact, outcome


class OnlyAgentExperimentLaunchServiceV1:
    def __init__(
        self,
        *,
        sessions: OnlyAgentSessionContextReader,
        decisions: OnlyAgentDecisionApplicationServiceV1,
        tools: OnlyAgentToolOccurrenceReaderV1,
        child_searches: OnlyAgentChildSearchExperimentReader,
        store: OnlyJsonAgentExperimentLaunchStore,
    ) -> None:
        self._sessions = sessions
        self._decisions = decisions
        self._tools = tools
        self._children = child_searches
        self._store = store

    def reconstruct_launch_record(
        self,
        *,
        session_fingerprint: str,
        agent_decision_fingerprint: str,
        tool_call_result_fingerprint: str,
        child_search_experiment_fingerprint: str,
        current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1,
    ) -> tuple[OnlyAgentExperimentLaunchRecordV1, OnlyAgentCommitOutcome]:
        context = self._sessions.load_session_manifest_verified(session_fingerprint)
        admit_agent_workflow_runtime(context.workflow_resource, current_workflow_manifest)
        launch = OnlyAgentExperimentLaunchRecordV1(
            session_fingerprint,
            agent_decision_fingerprint,
            tool_call_result_fingerprint,
            child_search_experiment_fingerprint,
        )
        self._verify_launch_historical(launch)
        outcome = self._store.commit_launch_record(launch)
        exact = self.load_launch_record_verified(launch.experiment_launch_record_fingerprint)
        return exact, outcome

    def load_launch_record_verified(self, fingerprint: str) -> OnlyAgentExperimentLaunchRecordV1:
        launch = self._store.load_launch_record_verified(fingerprint)
        self._verify_launch_historical(launch)
        return launch

    def load_launch_record_by_session_verified(self, session_fingerprint: str) -> OnlyAgentExperimentLaunchRecordV1:
        launch = self._store.load_launch_record_by_session_verified(session_fingerprint)
        return self.load_launch_record_verified(launch.experiment_launch_record_fingerprint)

    def launch_exists(self, session_fingerprint: str) -> bool:
        return self._store.launch_exists(session_fingerprint)

    def _verify_launch_historical(self, launch: OnlyAgentExperimentLaunchRecordV1) -> None:
        context = self._sessions.load_session_manifest_verified(launch.agent_session_fingerprint)
        decision = self._decisions.load_decision_verified(launch.agent_decision_fingerprint)
        if (
            decision.agent_session_fingerprint != context.session.session_fingerprint
            or decision.decision_kind is not OnlyAgentDecisionKind.SEARCH_DIRECTIVE
            or decision.decision_ordinal != 1
        ):
            raise OnlyAgentContextError("AGENT_EXPERIMENT_LAUNCH_INVALID", launch.experiment_launch_record_fingerprint)
        directive = cast(OnlyAgentSearchDirectiveV1, decision.structured_payload)
        expected = {
            OnlyAgentRouterAction.SYMBOLIC_SEARCH: (
                OnlyAgentToolClass.SYMBOLIC_SEARCH,
                OnlySearchExperimentManifestV2,
            ),
            OnlyAgentRouterAction.PARAMETER_SEARCH: (
                OnlyAgentToolClass.PARAMETER_SEARCH,
                OnlySearchExperimentManifestV3,
            ),
        }.get(directive.router_action)
        if expected is None:
            raise OnlyAgentContextError("AGENT_EXPERIMENT_LAUNCH_INVALID", launch.experiment_launch_record_fingerprint)
        result = self._tools.load_result_by_fingerprint_verified(launch.tool_call_result_fingerprint)
        plan = self._tools.load_plan_verified(result.tool_call_plan_fingerprint)
        child = self._children.load_experiment_verified(launch.child_search_experiment_fingerprint)
        self._decisions._verify_child_configuration(directive, child)
        if (
            result.outcome is not OnlyAgentToolCallOutcome.SUCCEEDED
            or plan.agent_session_fingerprint != launch.agent_session_fingerprint
            or plan.tool_call_ordinal != 1
            or plan.authorizing_agent_decision_fingerprint != launch.agent_decision_fingerprint
            or plan.tool_class is not expected[0]
            or sum(
                reference.locator_value == launch.child_search_experiment_fingerprint
                for reference in result.owning_authority_references
            )
            != 1
            or not isinstance(child, expected[1])
            or child.experiment_fingerprint != launch.child_search_experiment_fingerprint
            or child.catalog_generation_fingerprint != context.research_brief.catalog_generation_fingerprint
            or child.dataset_snapshot_fingerprint != context.research_brief.dataset_snapshot_fingerprint
            or child.evaluation_context_reference != context.research_brief.evaluation_context_reference
            or context.research_brief.agent_budget.child_experiment_limit != 1
        ):
            raise OnlyAgentContextError("AGENT_EXPERIMENT_LAUNCH_INVALID", launch.experiment_launch_record_fingerprint)


__all__ = [name for name in globals() if name.startswith("OnlyAgent")]
