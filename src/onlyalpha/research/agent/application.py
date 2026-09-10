"""Deterministic Agent Decision application and launch reconstruction services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from typing import Protocol, cast

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.experiment import (
    OnlySearchDecisionMode,
    OnlySearchExperimentManifestV2,
    OnlySearchExperimentManifestV3,
)

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
    OnlyAgentModelCallOutcome,
    OnlyAgentModelCallPlanV1,
    OnlyAgentModelCallResultV1,
    OnlyAgentToolCallOutcome,
    OnlyAgentToolCallPlanV1,
    OnlyAgentToolCallResultV1,
)
from .occurrence_service import OnlyAgentDecisionAuthorizationV1, OnlyAgentSessionContextReader
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


class OnlyAgentExactContextReaderV1(Protocol):
    def verify_exact_reference(self, reference: OnlyAgentContextReferenceV1) -> None: ...

    def verify_completed_evaluation_path(
        self,
        reference: OnlyAgentContextReferenceV1,
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
    ) -> None:
        self._sessions = sessions
        self._models = models
        self._tools = tools
        self._references = references
        self._store = store

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
            item.reference_fingerprint == context.research_brief.catalog_generation_fingerprint
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
        tool_results = self._terminal_tool_result_prefix(context)
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
        expected = self._reconstruct_historical_decision(decision, context)
        if expected != decision:
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", decision_fingerprint)
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

    def _admit(
        self, session_fingerprint: str, manifest: OnlyAgentWorkflowImplementationManifestV1
    ) -> OnlyVerifiedAgentDecisionContextV1:
        context = self._sessions.load_session_manifest_verified(session_fingerprint)
        admit_agent_workflow_runtime(context.workflow_resource, manifest)
        return context

    def _reconstruct_historical_decision(
        self,
        decision: OnlyAgentDecisionV1,
        context: OnlyVerifiedAgentDecisionContextV1,
    ) -> OnlyAgentDecisionV1:
        """Re-derive one historical Decision without applying current-runtime admission."""

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
                item.reference_fingerprint == context.research_brief.catalog_generation_fingerprint
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
        tool_results = self._terminal_tool_result_prefix(context)
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
        if (
            result.outcome is not OnlyAgentModelCallOutcome.RETURNED
            or result.validated_structured_output is None
            or plan.agent_session_fingerprint != context.session.session_fingerprint
            or plan.logical_role != expected_role
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
        references = tuple(value for value in values if isinstance(value, OnlyAgentContextReferenceV1)) + tuple(
            item
            for value in values
            if isinstance(value, tuple)
            for item in value
            if isinstance(item, OnlyAgentContextReferenceV1)
        )
        for reference in references:
            self._references.verify_exact_reference(reference)
        evaluation = getattr(payload, "evaluation_reference", None)
        if isinstance(evaluation, OnlyAgentContextReferenceV1) and (
            evaluation.reference_fingerprint
            != context.research_brief.evaluation_context_reference.evaluation_fingerprint
        ):
            raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Evaluation binding")

    def _terminal_tool_result_prefix(self, context: OnlyVerifiedAgentDecisionContextV1) -> tuple[str, ...]:
        results: list[str] = []
        for ordinal in range(self._tools.budget_consumed(context.session.session_fingerprint)):
            plan = self._tools.load_plan_by_session_ordinal_verified(context.session.session_fingerprint, ordinal)
            if not self._tools.result_exists(plan.tool_call_plan_fingerprint):
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Open Tool occurrence")
            result = self._tools.load_result_verified(plan.tool_call_plan_fingerprint)
            if result.outcome is not OnlyAgentToolCallOutcome.SUCCEEDED:
                raise OnlyAgentContextError("AGENT_DECISION_CAUSAL_INPUT_INVALID", "Failed Tool occurrence")
            results.append(result.tool_call_result_fingerprint)
        return tuple(results)

    def _verify_evidence_closure(
        self,
        context: OnlyVerifiedAgentDecisionContextV1,
        payload: OnlyAgentNextExperimentProposalV1,
    ) -> None:
        count = self._tools.budget_consumed(context.session.session_fingerprint)
        if count < 2:
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "No evaluation Tool facts")
        results: list[OnlyAgentToolCallResultV1] = []
        plans: list[OnlyAgentToolCallPlanV1] = []
        for ordinal in range(count):
            plan = self._tools.load_plan_by_session_ordinal_verified(context.session.session_fingerprint, ordinal)
            if not self._tools.result_exists(plan.tool_call_plan_fingerprint):
                raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Open Tool occurrence")
            plans.append(plan)
            results.append(self._tools.load_result_verified(plan.tool_call_plan_fingerprint))
        if (
            plans[-1].tool_class is not OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY
            or results[-1].outcome is not OnlyAgentToolCallOutcome.SUCCEEDED
        ):
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Evidence query is not complete")
        evidence_references = results[-1].owning_authority_references
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
        required_evidence = (
            *payload.research_result_references,
            *payload.research_statistics_references,
        )
        if any(evidence_references.count(reference) != 1 for reference in required_evidence):
            raise OnlyAgentContextError("AGENT_EVIDENCE_UNAVAILABLE", "Evidence reference closure")
        expected_path_tool = {
            OnlyAgentEvaluationPathKind.DIRECT_REUSE_RESEARCH: OnlyAgentToolClass.RESEARCH_RUN_QUERY,
            OnlyAgentEvaluationPathKind.CHILD_SEARCH: OnlyAgentToolClass.SEARCH_QUERY,
        }[payload.evaluation_path_kind]
        if (
            plans[-2].tool_class is not expected_path_tool
            or results[-2].owning_authority_references.count(payload.completed_path_reference) != 1
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
            payload.search_space_reference.reference_fingerprint
            != child.search_space_reference.search_space_fingerprint
            or payload.algorithm_reference.reference_fingerprint
            != child.search_algorithm_binding.implementation_fingerprint
            or payload.search_budget_reference.reference_fingerprint != expected_budget_fingerprint
            or child.decision_engine_binding.mode is not OnlySearchDecisionMode.DETERMINISTIC
        )
        policy_invalid = isinstance(payload, OnlyAgentParameterSearchDirectiveV1) and (
            not isinstance(child, OnlySearchExperimentManifestV3)
            or payload.search_policy_reference.reference_fingerprint != child.search_policy_reference.policy_fingerprint
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
                reference.reference_fingerprint == launch.child_search_experiment_fingerprint
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
