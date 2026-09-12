from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import onlyalpha_agent_orchestrator.driver as driver_module
import pytest
from onlyalpha_agent_orchestrator.adapters.product_api import (
    OnlyContractDrivenProductApiAdapterV1,
    OnlyProductApiContractV2,
)
from onlyalpha_agent_orchestrator.adapters.transport import (
    OnlyHttpDispatchClassification,
    OnlyHttpResponseV1,
    OnlyHttpTransportOutcomeV1,
)
from onlyalpha_agent_orchestrator.bindings import (
    OnlyAgentModelInvocationBindingV1,
    OnlyStaticAgentModelInvocationBindingReaderV1,
)
from onlyalpha_agent_orchestrator.config import OnlyProductApiEndpointConfigV1
from onlyalpha_agent_orchestrator.driver import OnlyAgentSessionDriverV1
from onlyalpha_agent_orchestrator.execution import execute_external_tool_occurrence
from onlyalpha_agent_orchestrator.materialization import OnlyAgentWorkflowActionMaterializerV1
from onlyalpha_agent_orchestrator.runtime import (
    _mint_runtime_execution_permit,
    assert_external_io_permit,
)

from onlyalpha.application.search_product import (
    OnlyAdvanceSearchExperimentV1,
    OnlyGetSearchIterationLedgerV1,
    OnlyGetSearchTerminalDecisionV1,
    OnlySearchBoundedOperationV1,
    OnlySearchMethodV1,
    OnlySearchTerminalKindV1,
)
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.agent import (
    OnlyAgentBudgetV1,
    OnlyAgentCapabilityGapDirectiveV1,
    OnlyAgentContextError,
    OnlyAgentContextReferenceV1,
    OnlyAgentDecisionApplicationServiceV1,
    OnlyAgentDecisionAuthorizationV1,
    OnlyAgentDecisionKind,
    OnlyAgentDecisionV1,
    OnlyAgentDerivedSessionStatus,
    OnlyAgentEvaluationContextReferenceV1,
    OnlyAgentEvaluationPathKind,
    OnlyAgentEvidenceCausalVerifierV1,
    OnlyAgentEvidenceObservationCodeV1,
    OnlyAgentEvidenceObservationV1,
    OnlyAgentExactAuthorityReference,
    OnlyAgentExactAuthorityReferenceV2,
    OnlyAgentExperimentLaunchRecordV1,
    OnlyAgentExperimentLaunchServiceV1,
    OnlyAgentFollowUpBriefDeltaV1,
    OnlyAgentModelCallOutcome,
    OnlyAgentModelCallPlanV1,
    OnlyAgentModelCallResultV1,
    OnlyAgentModelOccurrenceServiceV1,
    OnlyAgentModelSettingBindingV1,
    OnlyAgentModelSettingState,
    OnlyAgentNextActionKind,
    OnlyAgentNextActionV1,
    OnlyAgentNextExperimentProposalV1,
    OnlyAgentObservedResponseStorageKind,
    OnlyAgentParameterSearchDirectiveV1,
    OnlyAgentProductOperationContractV1,
    OnlyAgentProductRequestSemanticProjectionV1,
    OnlyAgentReferenceLocatorKind,
    OnlyAgentResearchPlanV1,
    OnlyAgentResearchRunAuthorityReaderV1,
    OnlyAgentReuseDirectiveV1,
    OnlyAgentRolePolicyPayloadV1,
    OnlyAgentRouterAction,
    OnlyAgentSearchAuthorityViewV1,
    OnlyAgentSearchDirectiveV1,
    OnlyAgentSearchMethod,
    OnlyAgentSessionManifestV1,
    OnlyAgentSessionReducerV1,
    OnlyAgentStructuredHypothesisV1,
    OnlyAgentSymbolicSearchDirectiveV1,
    OnlyAgentToolCallOutcome,
    OnlyAgentToolCallPlanV1,
    OnlyAgentToolCallResultV1,
    OnlyAgentToolClass,
    OnlyAgentToolOccurrenceServiceV1,
    OnlyAgentToolRecoveryClass,
    OnlyJsonAgentOrchestrationResourceStore,
    OnlyVerifiedAgentDecisionContextV1,
    expected_agent_search_submit_semantics,
    translate_agent_hypothesis_to_search_hypothesis,
)
from onlyalpha.research.agent.decision_store import (
    OnlyJsonAgentDecisionStore,
    OnlyJsonAgentExperimentLaunchStore,
)
from onlyalpha.research.agent.occurrence_store import (
    OnlyJsonAgentModelOccurrenceStore,
    OnlyJsonAgentToolOccurrenceStore,
)
from onlyalpha.research.command.query import OnlyResearchRunQueryService
from onlyalpha.research.experiment import (
    OnlySearchAlgorithmBindingV1,
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchEvaluationContextReferenceV1,
    OnlySearchExperimentManifestV2,
    OnlySearchExperimentManifestV3,
    OnlySearchHypothesisV1,
    OnlySearchPolicyReferenceV1,
    OnlySearchRandomnessMode,
    OnlySearchSpaceReferenceV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.run import OnlyResearchRunState
from tests.research.run.test_contract import NOW as RUN_NOW
from tests.research.run.test_contract import _queued as queued_research_run
from tests.research.search.parameter.test_search_product_adapter import _product_case as parameter_product_case
from tests.research.search.symbolic.test_search_product_adapter import (
    _case as symbolic_product_case,
)
from tests.research.search.symbolic.test_search_product_adapter import (
    _command_id as product_command_id,
)
from tests.research.search.symbolic.test_search_product_adapter import (
    _reconcile_expected as symbolic_reconcile_expected,
)

from .support import ContextFixture, make_context, packaged_provenance, resource


class SemanticProductContracts:
    def __init__(
        self,
        exact: tuple[OnlyAgentContextReferenceV1, ...],
        context: OnlyVerifiedAgentDecisionContextV1,
        directive: OnlyAgentDecisionV1,
    ) -> None:
        self._exact = exact
        assert isinstance(directive.structured_payload, OnlyAgentSearchDirectiveV1)
        self.projection = expected_agent_search_submit_semantics(
            operation_identity="symbolic_search.v1",
            context=context,
            directive=directive.structured_payload,
            runtime_generation_fingerprint=RuntimeGenerations.fingerprint,
        )
        properties: dict[str, object] = {
            "hypothesis": {
                "additionalProperties": False,
                "properties": {
                    key: (
                        {"type": "integer"}
                        if key == "schema_version"
                        else {"type": "array", "items": {"type": "string"}}
                        if key in {"universe_assumptions", "falsification_criteria"}
                        else {"type": "string"}
                    )
                    for key in (
                        "schema_version",
                        "hypothesis_id",
                        "statement",
                        "rationale",
                        "expected_relationship",
                        "universe_assumptions",
                        "falsification_criteria",
                    )
                },
                "required": [
                    "schema_version",
                    "hypothesis_id",
                    "statement",
                    "rationale",
                    "expected_relationship",
                    "universe_assumptions",
                    "falsification_criteria",
                ],
                "type": "object",
            }
        }
        for index, reference in enumerate(exact):
            properties["id" if index == 0 else f"identity_{index}"] = {
                "type": "string",
                "x-onlyalpha-reference-kind": reference.reference_kind,
                "x-onlyalpha-reference-schema-version": reference.reference_schema_version,
            }
        self.schema = {
            "additionalProperties": False,
            "properties": properties,
            "required": list(properties),
            "type": "object",
        }

    def load_operation_verified(self, major: int, fingerprint: str, operation: str):  # type: ignore[no-untyped-def]
        assert major == 2 and fingerprint == "d" * 64 and operation == "symbolic_search.v1"
        return OnlyAgentProductOperationContractV1(
            2,
            "d" * 64,
            operation,
            OnlyAgentToolClass.SYMBOLIC_SEARCH,
            OnlyAgentToolRecoveryClass.IDEMPOTENT_COMMAND,
            self.schema,
            {"additionalProperties": False, "properties": {}, "required": [], "type": "object"},
            True,
            ("SEARCH_EXPERIMENT",),
        )

    def project_request_semantics_verified(self, **kwargs):  # type: ignore[no-untyped-def]
        bindings = dict(self.projection.semantic_bindings)
        request = kwargs["canonical_validated_request"]
        hypothesis_payload = request["hypothesis"]
        hypothesis = OnlyAgentStructuredHypothesisV1(
            hypothesis_payload["hypothesis_id"],
            hypothesis_payload["statement"],
            hypothesis_payload["rationale"],
            hypothesis_payload["expected_relationship"],
            tuple(hypothesis_payload["universe_assumptions"]),
            tuple(hypothesis_payload["falsification_criteria"]),
            hypothesis_payload["schema_version"],
        )
        bindings["search_hypothesis_fingerprint"] = translate_agent_hypothesis_to_search_hypothesis(
            hypothesis
        ).hypothesis_fingerprint
        return OnlyAgentProductRequestSemanticProjectionV1(kwargs["operation_identity"], bindings)

    def verify_response_binding(self, plan, response, references):  # type: ignore[no-untyped-def]
        del plan, response, references


class RuntimeGenerations:
    fingerprint = "e" * 64

    def require_new_work_generation(self, runtime_generation_fingerprint: str) -> object:
        if runtime_generation_fingerprint != self.fingerprint:
            raise LookupError(runtime_generation_fingerprint)
        return object()


class DifferentRuntimeGenerations:
    def require_new_work_generation(self, runtime_generation_fingerprint: str) -> object:
        if runtime_generation_fingerprint != "f" * 64:
            raise LookupError(runtime_generation_fingerprint)
        return object()


def ref(kind: str, fingerprint: str) -> OnlyAgentContextReferenceV1:
    return OnlyAgentContextReferenceV1(kind, 1, fingerprint)


class Sessions:
    def __init__(self, context: OnlyVerifiedAgentDecisionContextV1) -> None:
        self.context = context

    def load_session_manifest_verified(self, fingerprint: str) -> OnlyVerifiedAgentDecisionContextV1:
        if fingerprint != self.context.session.session_fingerprint:
            raise LookupError(fingerprint)
        return self.context


class References:
    def verify_exact_reference(self, reference: OnlyAgentContextReferenceV1) -> None:
        if reference.reference_fingerprint == "0" * 64:
            raise LookupError(reference.reference_fingerprint)

    def verify_completed_evaluation_path(
        self,
        reference: OnlyAgentContextReferenceV1,
        path_kind: OnlyAgentEvaluationPathKind,
    ) -> None:
        expected = {
            OnlyAgentEvaluationPathKind.DIRECT_REUSE_RESEARCH: "RESEARCH_RUN_RESULT",
            OnlyAgentEvaluationPathKind.CHILD_SEARCH: "SEARCH_TERMINAL_PROJECTION",
        }[path_kind]
        if reference.reference_kind != expected:
            raise LookupError(reference.reference_fingerprint)


class Children:
    def __init__(self, *children: OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3) -> None:
        self.children = {item.experiment_fingerprint: item for item in children}

    def load_experiment_verified(
        self, fingerprint: str
    ) -> OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3:
        return self.children[fingerprint]


class Models:
    def __init__(self) -> None:
        self.plans: list[OnlyAgentModelCallPlanV1] = []
        self.results: dict[str, OnlyAgentModelCallResultV1] = {}

    def add(self, plan: OnlyAgentModelCallPlanV1, result: OnlyAgentModelCallResultV1 | None = None) -> None:
        self.plans.append(plan)
        if result is not None:
            self.results[result.model_call_result_fingerprint] = result

    def load_plan_verified(self, fingerprint: str) -> OnlyAgentModelCallPlanV1:
        return next(item for item in self.plans if item.model_call_plan_fingerprint == fingerprint)

    def load_result_by_fingerprint_verified(self, fingerprint: str) -> OnlyAgentModelCallResultV1:
        return self.results[fingerprint]

    def load_plan_by_session_ordinal_verified(self, session: str, ordinal: int) -> OnlyAgentModelCallPlanV1:
        plan = self.plans[ordinal]
        assert plan.agent_session_fingerprint == session and plan.call_ordinal == ordinal
        return plan

    def result_exists(self, plan_fingerprint: str) -> bool:
        return any(item.model_call_plan_fingerprint == plan_fingerprint for item in self.results.values())

    def load_result_verified(self, plan_fingerprint: str) -> OnlyAgentModelCallResultV1:
        return next(item for item in self.results.values() if item.model_call_plan_fingerprint == plan_fingerprint)

    def budget_consumed(self, session_fingerprint: str) -> int:
        return sum(item.agent_session_fingerprint == session_fingerprint for item in self.plans)


class Tools:
    def __init__(self) -> None:
        self.plans: list[OnlyAgentToolCallPlanV1] = []
        self.results: dict[str, OnlyAgentToolCallResultV1] = {}

    def add(self, plan: OnlyAgentToolCallPlanV1, result: OnlyAgentToolCallResultV1 | None = None) -> None:
        self.plans.append(plan)
        if result is not None:
            self.results[result.tool_call_result_fingerprint] = result

    def load_plan_verified(self, fingerprint: str) -> OnlyAgentToolCallPlanV1:
        return next(item for item in self.plans if item.tool_call_plan_fingerprint == fingerprint)

    def load_result_by_fingerprint_verified(self, fingerprint: str) -> OnlyAgentToolCallResultV1:
        return self.results[fingerprint]

    def load_plan_by_session_ordinal_verified(self, session: str, ordinal: int) -> OnlyAgentToolCallPlanV1:
        plan = self.plans[ordinal]
        assert plan.agent_session_fingerprint == session and plan.tool_call_ordinal == ordinal
        return plan

    def result_exists(self, plan_fingerprint: str) -> bool:
        return any(item.tool_call_plan_fingerprint == plan_fingerprint for item in self.results.values())

    def load_result_verified(self, plan_fingerprint: str) -> OnlyAgentToolCallResultV1:
        return next(item for item in self.results.values() if item.tool_call_plan_fingerprint == plan_fingerprint)

    def budget_consumed(self, session_fingerprint: str) -> int:
        return sum(item.agent_session_fingerprint == session_fingerprint for item in self.plans)

    def recovery_class(self, plan_fingerprint: str):  # type: ignore[no-untyped-def]
        plan = self.load_plan_verified(plan_fingerprint)
        if plan.tool_class in {OnlyAgentToolClass.RESEARCH_RUN_QUERY, OnlyAgentToolClass.SEARCH_QUERY}:
            return OnlyAgentToolRecoveryClass.MUTABLE_OBSERVATION_QUERY
        return OnlyAgentToolRecoveryClass.IMMUTABLE_EXACT_QUERY


class ProductSearchStates:
    def __init__(self, query) -> None:  # type: ignore[no-untyped-def]
        self.query = query

    def load_search_state_verified(self, experiment_fingerprint: str) -> OnlyAgentSearchAuthorityViewV1:
        terminal = self.query.get_terminal(OnlyGetSearchTerminalDecisionV1(experiment_fingerprint))
        ledger = self.query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment_fingerprint))
        operation = None
        if terminal.terminal_kind is OnlySearchTerminalKindV1.NON_TERMINAL:
            if terminal.method is OnlySearchMethodV1.SYMBOLIC:
                operation = (
                    OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE
                    if ledger.results and ledger.results[-1] is None
                    else OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE
                )
            else:
                operation = (
                    OnlySearchBoundedOperationV1.RECONCILE_OPEN_PARAMETER_BATCH
                    if ledger.plans and any(result is None for result in ledger.results)
                    else OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION
                )
        return OnlyAgentSearchAuthorityViewV1(terminal, ledger.expected_state, operation)


class ResearchRunStore:
    def __init__(self, run) -> None:  # type: ignore[no-untyped-def]
        self.run = run

    def load(self, run_id):  # type: ignore[no-untyped-def]
        if run_id != self.run.run_id:
            raise LookupError(run_id)
        return self.run

    def list_recent(self, *, limit, after):  # type: ignore[no-untyped-def]
        del limit, after
        return (self.run,)


class ProductResearchStates:
    def __init__(self, query: OnlyResearchRunQueryService) -> None:
        self.reader = OnlyAgentResearchRunAuthorityReaderV1(query)

    def load_research_run_verified(self, reference):  # type: ignore[no-untyped-def]
        return self.reader.load_research_run_verified(reference)


class SemanticInputs:
    def __init__(self, payloads: dict[tuple[str, str], dict[str, object]] | None = None) -> None:
        self.payloads = payloads or {}

    def load_semantic_payload_verified(self, reference):  # type: ignore[no-untyped-def]
        return self.payloads[(reference.reference_kind, reference.locator_value)]


def decision_context(tmp_path: Path) -> tuple[ContextFixture, OnlyVerifiedAgentDecisionContextV1]:
    fixture = make_context(tmp_path)
    planner = fixture.resources[4]
    planner_payload = planner.canonical_payload
    assert isinstance(planner_payload, OnlyAgentRolePolicyPayloadV1)
    roles = [planner]
    for role_id in ("SEARCH_ROUTER", "FACTOR_DESIGNER", "EVIDENCE_ANALYST"):
        roles.append(
            resource(
                planner.resource_kind,
                replace(
                    planner_payload,
                    logical_role_id=role_id,
                    responsibility_boundary=f"{role_id} bounded responsibility",
                    output_contract=f"ONE_STRICT_{role_id}_OUTPUT",
                ),
            )
        )
    brief = replace(
        fixture.brief,
        allowed_search_methods=tuple(sorted(OnlyAgentSearchMethod, key=lambda item: item.value)),
        agent_budget=OnlyAgentBudgetV1(4, 10),
        research_brief_fingerprint="",
    )
    session = OnlyAgentSessionManifestV1(
        brief.research_brief_fingerprint,
        fixture.session.agent_workflow_id,
        fixture.session.agent_workflow_semantic_version,
        fixture.session.agent_workflow_implementation_fingerprint,
        fixture.session.agent_workflow_source_revision,
        fixture.session.workflow_implementation_resource_fingerprint,
        fixture.session.tool_policy_fingerprint,
        tuple(item.resource_fingerprint for item in roles),
    )
    context = OnlyVerifiedAgentDecisionContextV1(
        session,
        brief,
        fixture.resources[-1],
        fixture.resources[3],
        tuple(roles),
        fixture.resources[:3],
    )
    return fixture, context


def model_occurrence(
    fixture: ContextFixture,
    context: OnlyVerifiedAgentDecisionContextV1,
    *,
    ordinal: int,
    role: str,
    role_fingerprint: str,
    refs: tuple[OnlyAgentContextReferenceV1, ...],
    output: dict[str, object],
    parent: str | None = None,
) -> tuple[OnlyAgentModelCallPlanV1, OnlyAgentModelCallResultV1]:
    plan = OnlyAgentModelCallPlanV1(
        context.session.session_fingerprint,
        ordinal,
        role,
        role_fingerprint,
        "provider-a",
        "model-a",
        "2026-09-01",
        fixture.resources[0].resource_fingerprint,
        fixture.resources[1].resource_fingerprint,
        context.session.tool_policy_fingerprint,
        fixture.resources[2].resource_fingerprint,
        (OnlyAgentModelSettingBindingV1("temperature", OnlyAgentModelSettingState.VALUE, "0"),),
        refs,
        parent,
    )
    return plan, OnlyAgentModelCallResultV1(
        plan.model_call_plan_fingerprint,
        OnlyAgentModelCallOutcome.RETURNED,
        validated_structured_output=output,
    )


def tool_occurrence(
    context: OnlyVerifiedAgentDecisionContextV1,
    *,
    ordinal: int,
    decision: str,
    tool_class: OnlyAgentToolClass,
    owner: OnlyAgentExactAuthorityReference,
) -> tuple[OnlyAgentToolCallPlanV1, OnlyAgentToolCallResultV1]:
    plan = OnlyAgentToolCallPlanV1(
        context.session.session_fingerprint,
        ordinal,
        decision,
        tool_class,
        2,
        "d" * 64,
        f"{tool_class.value.lower()}.v1",
        {"id": owner.locator_value},
        exact_identity_inputs=(owner,),
        tool_policy_fingerprint=context.session.tool_policy_fingerprint,
    )
    response = {"identity": owner.locator_value}
    result = OnlyAgentToolCallResultV1(
        plan.tool_call_plan_fingerprint,
        OnlyAgentToolCallOutcome.SUCCEEDED,
        OnlyAgentObservedResponseStorageKind.INLINE_CANONICAL_RESPONSE,
        response,
        canonical_response_fingerprint=only_canonical_fingerprint(response),
        owning_authority_references=(owner,),
    )
    return plan, result


def service(tmp_path: Path):  # type: ignore[no-untyped-def]
    fixture, context = decision_context(tmp_path)
    models = Models()
    tools = Tools()
    store = OnlyJsonAgentDecisionStore(tmp_path)
    application = OnlyAgentDecisionApplicationServiceV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        references=References(),
        store=store,
        runtime_generations=RuntimeGenerations(),
    )
    return fixture, context, models, tools, store, application


def derive_plan(
    fixture: ContextFixture,
    context: OnlyVerifiedAgentDecisionContextV1,
    models: Models,
    application: OnlyAgentDecisionApplicationServiceV1,
) -> OnlyAgentDecisionV1:
    brief_ref = ref("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint)
    plan, result = model_occurrence(
        fixture,
        context,
        ordinal=0,
        role="RESEARCH_PLANNER",
        role_fingerprint=context.session.ordered_role_policy_fingerprints[0],
        refs=(brief_ref,),
        output={"action": "PLAN"},
    )
    models.add(plan, result)
    decision, _ = application.derive_research_plan(
        session_fingerprint=context.session.session_fingerprint,
        planner_model_result_fingerprint=result.model_call_result_fingerprint,
        current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
    )
    return decision


def action_payload(
    action: OnlyAgentRouterAction, context: OnlyVerifiedAgentDecisionContextV1
) -> OnlyAgentReuseDirectiveV1 | OnlyAgentSymbolicSearchDirectiveV1 | OnlyAgentParameterSearchDirectiveV1:
    evaluation = ref("RESEARCH_EVALUATION", context.research_brief.evaluation_context_reference.evaluation_fingerprint)

    def generic(kind: str, digit: str) -> OnlyAgentContextReferenceV1:
        return ref(kind, digit * 64)

    if action is OnlyAgentRouterAction.REUSE_EXISTING:
        return OnlyAgentReuseDirectiveV1((generic("QUANT_ASSET", "1"),), generic("RESEARCH_DEFINITION", "2"))
    if action is OnlyAgentRouterAction.SYMBOLIC_SEARCH:
        return OnlyAgentSymbolicSearchDirectiveV1(
            generic("SYMBOLIC_SEARCH_SPACE", "9"),
            evaluation,
            generic("SEARCH_ALGORITHM", "8"),
            ref("SEARCH_BUDGET", only_canonical_fingerprint(OnlySearchBudgetV1(1, 1, 1).to_dict())),
        )
    return OnlyAgentParameterSearchDirectiveV1(
        generic("PARAMETER_SEARCH_SPACE", "9"),
        evaluation,
        generic("SEARCH_POLICY", "a"),
        generic("SEARCH_ALGORITHM", "8"),
        ref("SEARCH_BUDGET", only_canonical_fingerprint(OnlySearchBudgetV1(1, 1, 1).to_dict())),
    )


def derive_directive(
    fixture: ContextFixture,
    context: OnlyVerifiedAgentDecisionContextV1,
    models: Models,
    tools: Tools,
    application: OnlyAgentDecisionApplicationServiceV1,
    action: OnlyAgentRouterAction,
    *,
    directive_payload: (
        OnlyAgentReuseDirectiveV1 | OnlyAgentSymbolicSearchDirectiveV1 | OnlyAgentParameterSearchDirectiveV1 | None
    ) = None,
) -> tuple[OnlyAgentDecisionV1, OnlyAgentToolCallResultV1]:
    plan_decision = derive_plan(fixture, context, models, application)
    catalog_owner = ref("CATALOG_GENERATION", context.research_brief.catalog_generation_fingerprint)
    catalog_plan, catalog_result = tool_occurrence(
        context,
        ordinal=0,
        decision=plan_decision.decision_fingerprint,
        tool_class=OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
        owner=catalog_owner,
    )
    tools.add(catalog_plan, catalog_result)
    brief_ref = ref("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint)
    catalog_ref = ref("AGENT_TOOL_CALL_RESULT", catalog_result.tool_call_result_fingerprint)
    router_payload: dict[str, object] = {"router_action": action.value}
    designer_result_fingerprint = None
    if action is OnlyAgentRouterAction.CAPABILITY_GAP:
        router_payload["action_payload"] = OnlyAgentCapabilityGapDirectiveV1(
            (ref("MISSING_CAPABILITY", "7" * 64),), ("FACTOR",), ("MISSING_L3",)
        ).to_dict()
    router_plan, router_result = model_occurrence(
        fixture,
        context,
        ordinal=1,
        role="SEARCH_ROUTER",
        role_fingerprint=context.session.ordered_role_policy_fingerprints[1],
        refs=(brief_ref, catalog_ref),
        output=router_payload,
        parent=plan_decision.decision_fingerprint,
    )
    models.add(router_plan, router_result)
    if action is not OnlyAgentRouterAction.CAPABILITY_GAP:
        payload = directive_payload if directive_payload is not None else action_payload(action, context)
        designer_plan, designer_result = model_occurrence(
            fixture,
            context,
            ordinal=2,
            role="FACTOR_DESIGNER",
            role_fingerprint=context.session.ordered_role_policy_fingerprints[2],
            refs=(brief_ref, catalog_ref, ref("AGENT_MODEL_CALL_RESULT", router_result.model_call_result_fingerprint)),
            output={"action_payload": payload.to_dict()},
            parent=plan_decision.decision_fingerprint,
        )
        models.add(designer_plan, designer_result)
        designer_result_fingerprint = designer_result.model_call_result_fingerprint
    decision, _ = application.derive_search_directive(
        session_fingerprint=context.session.session_fingerprint,
        router_model_result_fingerprint=router_result.model_call_result_fingerprint,
        catalog_tool_result_fingerprint=catalog_result.tool_call_result_fingerprint,
        factor_designer_model_result_fingerprint=designer_result_fingerprint,
        current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
    )
    return decision, catalog_result


def child_experiment(
    context: OnlyVerifiedAgentDecisionContextV1,
    action: OnlyAgentRouterAction,
    *,
    catalog: str | None = None,
    search_space: str = "9" * 64,
) -> OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3:
    common = (
        OnlySearchHypothesisV1("bounded Agent-created child Search"),
        OnlySearchAlgorithmBindingV1("deterministic.search", "1.0.0", "8" * 64, "revision-1"),
        OnlySearchSpaceReferenceV1("ONLYALPHA_SEARCH_SPACE", 1, search_space),
        OnlySearchEvaluationContextReferenceV1(
            context.research_brief.evaluation_context_reference.evaluation_kind,
            context.research_brief.evaluation_context_reference.evaluation_schema_version,
            context.research_brief.evaluation_context_reference.evaluation_fingerprint,
        ),
    )
    suffix = (
        OnlySearchRandomnessMode.NONE,
        None,
        OnlySearchBudgetV1(1, 1, 1),
        catalog or context.research_brief.catalog_generation_fingerprint,
        context.research_brief.dataset_snapshot_fingerprint,
        OnlySearchWorkflowBindingV1("agent.child.search", "1"),
        OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.DETERMINISTIC),
    )
    if action is OnlyAgentRouterAction.SYMBOLIC_SEARCH:
        return OnlySearchExperimentManifestV2(*common, *suffix)
    return OnlySearchExperimentManifestV3(
        *common,
        OnlySearchPolicyReferenceV1("ONLYALPHA_PARAMETER_SEARCH_POLICY", 1, "a" * 64),
        *suffix,
    )


def launch_application(
    root: Path,
    context: OnlyVerifiedAgentDecisionContextV1,
    application: OnlyAgentDecisionApplicationServiceV1,
    tools: Tools,
    *children: OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3,
) -> OnlyAgentExperimentLaunchServiceV1:
    return OnlyAgentExperimentLaunchServiceV1(
        sessions=Sessions(context),
        decisions=application,
        tools=tools,
        child_searches=Children(*children),
        store=OnlyJsonAgentExperimentLaunchStore(root),
    )


def test_decision_identity_and_tagged_union_are_strict(tmp_path: Path) -> None:
    fixture, context = decision_context(tmp_path)
    roles = tuple(
        item.canonical_payload.logical_role_id  # type: ignore[union-attr]
        for item in context.ordered_role_policy_resources
    )
    payload = OnlyAgentResearchPlanV1(
        context.research_brief.research_brief_fingerprint,
        roles,
        tuple(OnlyAgentRouterAction),
        context.research_brief.agent_budget,
    )
    decision = OnlyAgentDecisionV1(
        context.session.session_fingerprint,
        0,
        OnlyAgentDecisionKind.RESEARCH_PLAN,
        "RESEARCH_PLANNER",
        context.session.ordered_role_policy_fingerprints[0],
        ("1" * 64,),
        (),
        (ref("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint),),
        payload,
        fixture.resources[-1].canonical_payload.implementation_fingerprint,  # type: ignore[union-attr]
    )
    assert OnlyAgentDecisionV1.from_dict(decision.to_dict()) == decision
    assert (
        replace(
            decision, ordered_model_call_result_fingerprints=("2" * 64,), decision_fingerprint=""
        ).decision_fingerprint
        != decision.decision_fingerprint
    )
    gap = OnlyAgentCapabilityGapDirectiveV1((ref("MISSING_CAPABILITY", "3" * 64),), ("FACTOR",), ("MISSING_L3",))
    directive = OnlyAgentSearchDirectiveV1(OnlyAgentRouterAction.CAPABILITY_GAP, "4" * 64, gap)
    assert OnlyAgentSearchDirectiveV1.from_dict(directive.to_dict()) == directive
    with pytest.raises(ValueError):
        OnlyAgentSearchDirectiveV1(OnlyAgentRouterAction.REUSE_EXISTING, "4" * 64, gap)
    invalid = directive.to_dict()
    invalid["unexpected"] = True
    with pytest.raises(ValueError):
        OnlyAgentSearchDirectiveV1.from_dict(invalid)


def test_decision_store_put_once_contiguous_conflict_and_tamper(tmp_path: Path) -> None:
    fixture, context = decision_context(tmp_path)
    payload = OnlyAgentResearchPlanV1(
        context.research_brief.research_brief_fingerprint,
        ("RESEARCH_PLANNER", "SEARCH_ROUTER", "FACTOR_DESIGNER", "EVIDENCE_ANALYST"),
        tuple(OnlyAgentRouterAction),
        context.research_brief.agent_budget,
    )
    d0 = OnlyAgentDecisionV1(
        context.session.session_fingerprint,
        0,
        OnlyAgentDecisionKind.RESEARCH_PLAN,
        "RESEARCH_PLANNER",
        context.session.ordered_role_policy_fingerprints[0],
        ("1" * 64,),
        (),
        (),
        payload,
        fixture.resources[-1].canonical_payload.implementation_fingerprint,  # type: ignore[union-attr]
    )
    store = OnlyJsonAgentDecisionStore(tmp_path)
    assert store.commit_decision(d0).disposition.value == "CREATED"
    assert store.commit_decision(d0).disposition.value == "REUSED"
    assert store.load_decision_by_session_ordinal_verified(context.session.session_fingerprint, 0) == d0
    conflict = replace(d0, ordered_model_call_result_fingerprints=("2" * 64,), decision_fingerprint="")
    with pytest.raises(OnlyAgentContextError, match="AGENT_DECISION_ORDINAL_CONFLICT"):
        store.commit_decision(conflict)
    manifest = next(tmp_path.glob("research/agent-orchestration/decisions/sha256/*/*/manifest.json"))
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(OnlyAgentContextError):
        store.load_decision_verified(d0.decision_fingerprint)


def test_research_plan_derives_from_exact_result_and_current_runtime(tmp_path: Path) -> None:
    fixture, context, models, _tools, store, application = service(tmp_path)
    brief_ref = ref("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint)
    plan, result = model_occurrence(
        fixture,
        context,
        ordinal=0,
        role="RESEARCH_PLANNER",
        role_fingerprint=context.session.ordered_role_policy_fingerprints[0],
        refs=(brief_ref,),
        output={"action": "PLAN"},
    )
    models.add(plan, result)
    decision, outcome = application.derive_research_plan(
        session_fingerprint=context.session.session_fingerprint,
        planner_model_result_fingerprint=result.model_call_result_fingerprint,
        current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
    )
    assert outcome.disposition.value == "CREATED"
    assert application.load_decision_authorization_verified(decision.decision_fingerprint).permitted_tool_classes == (
        OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
    )
    assert store.load_decision_verified(decision.decision_fingerprint) == decision
    mismatched = replace(
        fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
        workflow_semantic_version="2.0.0",
        implementation_fingerprint="",
    )
    with pytest.raises(OnlyAgentContextError, match="AGENT_WORKFLOW_RUNTIME_MISMATCH"):
        application.derive_research_plan(
            session_fingerprint=context.session.session_fingerprint,
            planner_model_result_fingerprint=result.model_call_result_fingerprint,
            current_workflow_manifest=mismatched,
        )


def test_launch_value_and_store_enforce_one_child(tmp_path: Path) -> None:
    store = OnlyJsonAgentExperimentLaunchStore(tmp_path)
    first = OnlyAgentExperimentLaunchRecordV1("1" * 64, "2" * 64, "3" * 64, "4" * 64)
    assert store.commit_launch_record(first).disposition.value == "CREATED"
    assert store.commit_launch_record(first).disposition.value == "REUSED"
    assert OnlyAgentExperimentLaunchRecordV1.from_dict(first.to_dict()) == first
    second = OnlyAgentExperimentLaunchRecordV1("1" * 64, "2" * 64, "5" * 64, "6" * 64)
    with pytest.raises(OnlyAgentContextError, match="AGENT_EXPERIMENT_LAUNCH_CONFLICT"):
        store.commit_launch_record(second)


@pytest.mark.parametrize(
    "action",
    [
        OnlyAgentRouterAction.REUSE_EXISTING,
        OnlyAgentRouterAction.SYMBOLIC_SEARCH,
        OnlyAgentRouterAction.PARAMETER_SEARCH,
        OnlyAgentRouterAction.CAPABILITY_GAP,
    ],
)
def test_all_router_branches_derive_exact_decision_and_least_privilege(
    tmp_path: Path, action: OnlyAgentRouterAction
) -> None:
    fixture, context, models, tools, _store, application = service(tmp_path)
    decision, _ = derive_directive(fixture, context, models, tools, application, action)
    loaded = application.load_decision_verified(decision.decision_fingerprint)
    assert loaded == decision
    assert isinstance(loaded.structured_payload, OnlyAgentSearchDirectiveV1)
    assert loaded.structured_payload.router_action is action
    authorization = application.load_decision_authorization_verified(decision.decision_fingerprint)
    policy = context.tool_policy_resource.canonical_payload
    assert all(item in policy.allowed_tool_classes for item in authorization.permitted_tool_classes)  # type: ignore[union-attr]
    if action is OnlyAgentRouterAction.CAPABILITY_GAP:
        assert authorization.permitted_tool_classes == ()


def test_decision_store_rejects_gap_noncanonical_and_symlink(tmp_path: Path) -> None:
    fixture, context = decision_context(tmp_path)
    proposal = OnlyAgentNextExperimentProposalV1(
        OnlyAgentEvaluationPathKind.DIRECT_REUSE_RESEARCH,
        ref("RESEARCH_PATH", "1" * 64),
        (ref("RESEARCH_RESULT", "2" * 64),),
        (ref("RESEARCH_STATISTICS", "3" * 64),),
        (
            OnlyAgentEvidenceObservationV1(
                OnlyAgentEvidenceObservationCodeV1.FOLLOW_UP_RECOMMENDED,
                (ref("RESEARCH_STATISTICS", "3" * 64),),
            ),
        ),
        OnlyAgentFollowUpBriefDeltaV1("refine", "bounded evidence", ("narrow universe",)),
    )
    gap = OnlyAgentDecisionV1(
        context.session.session_fingerprint,
        2,
        OnlyAgentDecisionKind.NEXT_EXPERIMENT_PROPOSAL,
        "EVIDENCE_ANALYST",
        context.session.ordered_role_policy_fingerprints[3],
        ("4" * 64,),
        (),
        (),
        proposal,
        fixture.resources[-1].canonical_payload.implementation_fingerprint,  # type: ignore[union-attr]
    )
    store = OnlyJsonAgentDecisionStore(tmp_path)
    with pytest.raises(OnlyAgentContextError, match="AGENT_DECISION_ORDINAL_CONFLICT"):
        store.commit_decision(gap)

    plan = OnlyAgentDecisionV1(
        context.session.session_fingerprint,
        0,
        OnlyAgentDecisionKind.RESEARCH_PLAN,
        "RESEARCH_PLANNER",
        context.session.ordered_role_policy_fingerprints[0],
        ("5" * 64,),
        (),
        (),
        OnlyAgentResearchPlanV1(
            context.research_brief.research_brief_fingerprint,
            ("RESEARCH_PLANNER", "SEARCH_ROUTER", "FACTOR_DESIGNER", "EVIDENCE_ANALYST"),
            tuple(OnlyAgentRouterAction),
            context.research_brief.agent_budget,
        ),
        fixture.resources[-1].canonical_payload.implementation_fingerprint,  # type: ignore[union-attr]
    )
    store.commit_decision(plan)
    manifest = next(tmp_path.glob("research/agent-orchestration/decisions/sha256/*/*/manifest.json"))
    canonical = manifest.read_text(encoding="utf-8")
    manifest.write_text(f" {canonical}", encoding="utf-8")
    with pytest.raises(OnlyAgentContextError, match="AGENT_DECISION_CONFLICT"):
        store.load_decision_verified(plan.decision_fingerprint)
    manifest.unlink()
    manifest.symlink_to(tmp_path / "outside.json")
    with pytest.raises(OnlyAgentContextError, match="AGENT_DECISION_CONFLICT"):
        store.load_decision_verified(plan.decision_fingerprint)


def test_historical_decision_load_reproves_causal_model_result(tmp_path: Path) -> None:
    fixture, context, models, _tools, _store, application = service(tmp_path)
    decision = derive_plan(fixture, context, models, application)
    assert application.load_decision_verified(decision.decision_fingerprint) == decision
    models.results.clear()
    with pytest.raises((KeyError, OnlyAgentContextError)):
        application.load_decision_verified(decision.decision_fingerprint)


@pytest.mark.parametrize("defect", ["cross_session", "wrong_role", "wrong_stage", "extra_context", "failed"])
def test_decision_derivation_rejects_non_exact_causal_inputs(tmp_path: Path, defect: str) -> None:
    fixture, context, models, _tools, _store, application = service(tmp_path)
    brief_ref = ref("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint)
    plan, result = model_occurrence(
        fixture,
        context,
        ordinal=0,
        role="RESEARCH_PLANNER",
        role_fingerprint=context.session.ordered_role_policy_fingerprints[0],
        refs=(brief_ref,),
        output={"action": "PLAN"},
    )
    changes: dict[str, object] = {"model_call_plan_fingerprint": ""}
    if defect == "cross_session":
        changes["agent_session_fingerprint"] = "f" * 64
    elif defect == "wrong_role":
        changes["logical_role"] = "SEARCH_ROUTER"
    elif defect == "wrong_stage":
        changes["call_ordinal"] = 1
    elif defect == "extra_context":
        changes["ordered_context_references"] = (brief_ref, ref("UNRELATED", "e" * 64))
    plan = replace(plan, **changes)  # type: ignore[arg-type]
    if defect == "failed":
        result = OnlyAgentModelCallResultV1(
            plan.model_call_plan_fingerprint,
            OnlyAgentModelCallOutcome.FAILED,
            failure_code="AGENT_MODEL_CALL_FAILED",
        )
    else:
        result = OnlyAgentModelCallResultV1(
            plan.model_call_plan_fingerprint,
            OnlyAgentModelCallOutcome.RETURNED,
            validated_structured_output={"action": "PLAN"},
        )
    models.add(plan, result)
    with pytest.raises(OnlyAgentContextError):
        application.derive_research_plan(
            session_fingerprint=context.session.session_fingerprint,
            planner_model_result_fingerprint=result.model_call_result_fingerprint,
            current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
        )


def test_all_decision_kinds_bind_every_identity_input(tmp_path: Path) -> None:
    fixture, context = decision_context(tmp_path)
    plan_payload = OnlyAgentResearchPlanV1(
        context.research_brief.research_brief_fingerprint,
        ("RESEARCH_PLANNER", "SEARCH_ROUTER", "FACTOR_DESIGNER", "EVIDENCE_ANALYST"),
        tuple(OnlyAgentRouterAction),
        context.research_brief.agent_budget,
    )
    directive_payload = OnlyAgentSearchDirectiveV1(
        OnlyAgentRouterAction.CAPABILITY_GAP,
        "1" * 64,
        OnlyAgentCapabilityGapDirectiveV1((ref("MISSING_CAPABILITY", "2" * 64),), ("FACTOR",), ("MISSING_L3",)),
    )
    proposal_payload = OnlyAgentNextExperimentProposalV1(
        OnlyAgentEvaluationPathKind.DIRECT_REUSE_RESEARCH,
        ref("RESEARCH_RUN_RESULT", "3" * 64),
        (ref("RESEARCH_RESULT", "4" * 64),),
        (ref("RESEARCH_STATISTICS", "5" * 64),),
        (
            OnlyAgentEvidenceObservationV1(
                OnlyAgentEvidenceObservationCodeV1.ROBUSTNESS_UNCERTAIN,
                (ref("RESEARCH_STATISTICS", "5" * 64),),
            ),
        ),
        OnlyAgentFollowUpBriefDeltaV1("refine", "evidence", ("narrow scope",)),
    )
    for ordinal, kind, role, payload in (
        (0, OnlyAgentDecisionKind.RESEARCH_PLAN, "RESEARCH_PLANNER", plan_payload),
        (1, OnlyAgentDecisionKind.SEARCH_DIRECTIVE, "SEARCH_ROUTER", directive_payload),
        (2, OnlyAgentDecisionKind.NEXT_EXPERIMENT_PROPOSAL, "EVIDENCE_ANALYST", proposal_payload),
    ):
        decision = OnlyAgentDecisionV1(
            context.session.session_fingerprint,
            ordinal,
            kind,
            role,
            context.session.ordered_role_policy_fingerprints[ordinal if ordinal < 2 else 3],
            ("6" * 64,),
            ("7" * 64,),
            (ref("EXACT_CONTEXT", "8" * 64),),
            payload,
            fixture.resources[-1].canonical_payload.implementation_fingerprint,  # type: ignore[union-attr]
        )
        assert OnlyAgentDecisionV1.from_dict(decision.to_dict()).decision_fingerprint == decision.decision_fingerprint
        changed = replace(decision, workflow_implementation_fingerprint="9" * 64, decision_fingerprint="")
        assert changed.decision_fingerprint != decision.decision_fingerprint


def test_store_rejects_unsafe_semantic_root_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    store = OnlyJsonAgentExperimentLaunchStore(alias)
    launch = OnlyAgentExperimentLaunchRecordV1("1" * 64, "2" * 64, "3" * 64, "4" * 64)
    with pytest.raises(OnlyAgentContextError, match="AGENT_CONTEXT_UNSAFE_PATH"):
        store.commit_launch_record(launch)


@pytest.mark.parametrize(
    ("action", "tool_class"),
    [
        (OnlyAgentRouterAction.SYMBOLIC_SEARCH, OnlyAgentToolClass.SYMBOLIC_SEARCH),
        (OnlyAgentRouterAction.PARAMETER_SEARCH, OnlyAgentToolClass.PARAMETER_SEARCH),
    ],
)
def test_launch_reconstruction_exact_child_and_fresh_service_reuse(
    tmp_path: Path,
    action: OnlyAgentRouterAction,
    tool_class: OnlyAgentToolClass,
) -> None:
    fixture, context, models, tools, _decision_store, application = service(tmp_path)
    directive, _ = derive_directive(fixture, context, models, tools, application, action)
    child = child_experiment(context, action)
    submit_plan, submit_result = tool_occurrence(
        context,
        ordinal=1,
        decision=directive.decision_fingerprint,
        tool_class=tool_class,
        owner=ref("SEARCH_EXPERIMENT", child.experiment_fingerprint),
    )
    tools.add(submit_plan, submit_result)
    launch_service = launch_application(tmp_path, context, application, tools, child)
    reducer = OnlyAgentSessionReducerV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        decision_service=application,
        decision_store=OnlyJsonAgentDecisionStore(tmp_path),
        launch_service=launch_service,
    )
    recovery = reducer.derive(context.session.session_fingerprint)
    assert recovery.next_action is not None
    assert recovery.next_action.action_kind is OnlyAgentNextActionKind.RECONSTRUCT_LAUNCH_RECORD
    assert recovery.next_action.occurrence_fingerprint == submit_result.tool_call_result_fingerprint
    mismatched = replace(
        fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
        workflow_semantic_version="2.0.0",
        implementation_fingerprint="",
    )
    with pytest.raises(OnlyAgentContextError, match="AGENT_WORKFLOW_RUNTIME_MISMATCH"):
        launch_service.reconstruct_launch_record(
            session_fingerprint=context.session.session_fingerprint,
            agent_decision_fingerprint=directive.decision_fingerprint,
            tool_call_result_fingerprint=submit_result.tool_call_result_fingerprint,
            child_search_experiment_fingerprint=child.experiment_fingerprint,
            current_workflow_manifest=mismatched,
        )
    launch, outcome = launch_service.reconstruct_launch_record(
        session_fingerprint=context.session.session_fingerprint,
        agent_decision_fingerprint=directive.decision_fingerprint,
        tool_call_result_fingerprint=submit_result.tool_call_result_fingerprint,
        child_search_experiment_fingerprint=child.experiment_fingerprint,
        current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
    )
    assert outcome.disposition.value == "CREATED"
    reopened = OnlyAgentExperimentLaunchServiceV1(
        sessions=Sessions(context),
        decisions=application,
        tools=tools,
        child_searches=Children(child),
        store=OnlyJsonAgentExperimentLaunchStore(tmp_path),
    )
    same, reused = reopened.reconstruct_launch_record(
        session_fingerprint=context.session.session_fingerprint,
        agent_decision_fingerprint=directive.decision_fingerprint,
        tool_call_result_fingerprint=submit_result.tool_call_result_fingerprint,
        child_search_experiment_fingerprint=child.experiment_fingerprint,
        current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
    )
    assert same == launch
    assert reused.disposition.value == "REUSED"
    illegal_plan, illegal_result = tool_occurrence(
        context,
        ordinal=2,
        decision=directive.decision_fingerprint,
        tool_class=tool_class,
        owner=ref("SEARCH_EXPERIMENT", "f" * 64),
    )
    tools.add(illegal_plan, illegal_result)
    assert application.load_decision_verified(directive.decision_fingerprint) == directive
    assert reopened.load_launch_record_verified(launch.experiment_launch_record_fingerprint) == launch
    with pytest.raises(OnlyAgentContextError, match="AGENT_HISTORY_CONTRADICTORY"):
        reducer.derive(context.session.session_fingerprint)


@pytest.mark.parametrize("mismatch", ["catalog", "search_space"])
def test_launch_rejects_wrong_child_configuration_and_reuse_has_no_launch(tmp_path: Path, mismatch: str) -> None:
    fixture, context, models, tools, _store, application = service(tmp_path)
    directive, _ = derive_directive(fixture, context, models, tools, application, OnlyAgentRouterAction.SYMBOLIC_SEARCH)
    child = child_experiment(
        context,
        OnlyAgentRouterAction.SYMBOLIC_SEARCH,
        catalog="f" * 64 if mismatch == "catalog" else None,
        search_space="f" * 64 if mismatch == "search_space" else "9" * 64,
    )
    submit_plan, submit_result = tool_occurrence(
        context,
        ordinal=1,
        decision=directive.decision_fingerprint,
        tool_class=OnlyAgentToolClass.SYMBOLIC_SEARCH,
        owner=ref("SEARCH_EXPERIMENT", child.experiment_fingerprint),
    )
    tools.add(submit_plan, submit_result)
    launch_service = OnlyAgentExperimentLaunchServiceV1(
        sessions=Sessions(context),
        decisions=application,
        tools=tools,
        child_searches=Children(child),
        store=OnlyJsonAgentExperimentLaunchStore(tmp_path),
    )
    with pytest.raises(OnlyAgentContextError, match="AGENT_EXPERIMENT_LAUNCH_INVALID"):
        launch_service.reconstruct_launch_record(
            session_fingerprint=context.session.session_fingerprint,
            agent_decision_fingerprint=directive.decision_fingerprint,
            tool_call_result_fingerprint=submit_result.tool_call_result_fingerprint,
            child_search_experiment_fingerprint=child.experiment_fingerprint,
            current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
        )

    reuse_root = tmp_path / "reuse"
    reuse_root.mkdir()
    fixture2, context2, models2, tools2, _store2, application2 = service(reuse_root)
    reuse, _ = derive_directive(fixture2, context2, models2, tools2, application2, OnlyAgentRouterAction.REUSE_EXISTING)
    invalid = OnlyAgentExperimentLaunchRecordV1(
        context2.session.session_fingerprint, reuse.decision_fingerprint, "1" * 64, "2" * 64
    )
    OnlyJsonAgentExperimentLaunchStore(reuse_root).commit_launch_record(invalid)
    reducer = OnlyAgentSessionReducerV1(
        sessions=Sessions(context2),
        models=models2,
        tools=tools2,
        decision_service=application2,
        decision_store=OnlyJsonAgentDecisionStore(reuse_root),
        launch_service=launch_application(reuse_root, context2, application2, tools2),
    )
    with pytest.raises(OnlyAgentContextError, match="AGENT_HISTORY_CONTRADICTORY"):
        reducer.derive(context2.session.session_fingerprint)


def test_reducer_derives_one_action_for_early_legal_prefixes(tmp_path: Path) -> None:
    fixture, context, models, tools, store, application = service(tmp_path)
    reducer = OnlyAgentSessionReducerV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        decision_service=application,
        decision_store=store,
        launch_service=launch_application(tmp_path, context, application, tools),
    )
    state = reducer.derive(context.session.session_fingerprint)
    assert state.status is OnlyAgentDerivedSessionStatus.ACTIVE
    assert state.next_action is not None
    assert state.next_action.action_kind is OnlyAgentNextActionKind.PREPARE_MODEL_CALL

    plan_decision = derive_plan(fixture, context, models, application)
    state = reducer.derive(context.session.session_fingerprint)
    assert state.next_action is not None
    assert state.next_action.action_kind is OnlyAgentNextActionKind.PREPARE_TOOL_CALL
    assert state.next_action.tool_class is OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY

    catalog_plan, catalog_result = tool_occurrence(
        context,
        ordinal=0,
        decision=plan_decision.decision_fingerprint,
        tool_class=OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
        owner=ref("CATALOG_GENERATION", context.research_brief.catalog_generation_fingerprint),
    )
    tools.add(catalog_plan, catalog_result)
    state = reducer.derive(context.session.session_fingerprint)
    assert state.next_action is not None
    assert state.next_action.action_kind is OnlyAgentNextActionKind.PREPARE_MODEL_CALL
    assert state.next_action.logical_role == "SEARCH_ROUTER"


@pytest.mark.parametrize(
    "outcome",
    [
        OnlyAgentModelCallOutcome.FAILED,
        OnlyAgentModelCallOutcome.OUTCOME_UNKNOWN,
        OnlyAgentModelCallOutcome.RESPONSE_INVALID,
    ],
)
def test_reducer_model_terminal_failures_have_no_continuation(
    tmp_path: Path, outcome: OnlyAgentModelCallOutcome
) -> None:
    fixture, context, models, tools, store, application = service(tmp_path)
    plan, _ = model_occurrence(
        fixture,
        context,
        ordinal=0,
        role="RESEARCH_PLANNER",
        role_fingerprint=context.session.ordered_role_policy_fingerprints[0],
        refs=(ref("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint),),
        output={"action": "PLAN"},
    )
    result = OnlyAgentModelCallResultV1(
        plan.model_call_plan_fingerprint,
        outcome,
        failure_code={
            OnlyAgentModelCallOutcome.FAILED: "AGENT_MODEL_CALL_FAILED",
            OnlyAgentModelCallOutcome.OUTCOME_UNKNOWN: "AGENT_MODEL_CALL_OUTCOME_UNKNOWN",
            OnlyAgentModelCallOutcome.RESPONSE_INVALID: "AGENT_MODEL_RESPONSE_INVALID",
        }[outcome],
    )
    models.add(plan, result)
    reducer = OnlyAgentSessionReducerV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        decision_service=application,
        decision_store=store,
        launch_service=launch_application(tmp_path, context, application, tools),
    )
    state = reducer.derive(context.session.session_fingerprint)
    assert state.status is OnlyAgentDerivedSessionStatus.FAILED
    assert state.next_action is None
    assert state.failure_code == result.failure_code


def test_reducer_recovers_open_occurrences_without_repeating_effect(tmp_path: Path) -> None:
    fixture, context, models, tools, store, application = service(tmp_path)
    brief_ref = ref("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint)
    pending_plan, _ = model_occurrence(
        fixture,
        context,
        ordinal=0,
        role="RESEARCH_PLANNER",
        role_fingerprint=context.session.ordered_role_policy_fingerprints[0],
        refs=(brief_ref,),
        output={"action": "PLAN"},
    )
    models.add(pending_plan)
    reducer = OnlyAgentSessionReducerV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        decision_service=application,
        decision_store=store,
        launch_service=launch_application(tmp_path, context, application, tools),
    )
    model_recovery = reducer.derive(context.session.session_fingerprint)
    assert model_recovery.next_action is not None
    assert model_recovery.next_action.action_kind is OnlyAgentNextActionKind.RECOVER_MODEL_OUTCOME_UNKNOWN
    assert model_recovery.next_action.occurrence_fingerprint == pending_plan.model_call_plan_fingerprint

    tool_root = tmp_path / "tool"
    tool_root.mkdir()
    fixture2, context2, models2, tools2, store2, application2 = service(tool_root)
    decision = derive_plan(fixture2, context2, models2, application2)
    pending_tool, _ = tool_occurrence(
        context2,
        ordinal=0,
        decision=decision.decision_fingerprint,
        tool_class=OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
        owner=ref("CATALOG_GENERATION", context2.research_brief.catalog_generation_fingerprint),
    )
    tools2.add(pending_tool)
    reducer2 = OnlyAgentSessionReducerV1(
        sessions=Sessions(context2),
        models=models2,
        tools=tools2,
        decision_service=application2,
        decision_store=store2,
        launch_service=launch_application(tool_root, context2, application2, tools2),
    )
    tool_recovery = reducer2.derive(context2.session.session_fingerprint)
    assert tool_recovery.next_action is not None
    assert tool_recovery.next_action.action_kind is OnlyAgentNextActionKind.RECOVER_TOOL_OCCURRENCE
    assert tool_recovery.next_action.occurrence_fingerprint == pending_tool.tool_call_plan_fingerprint


@pytest.mark.parametrize(
    ("outcome", "failure_code"),
    [
        (OnlyAgentToolCallOutcome.FAILED, "AGENT_TOOL_CALL_FAILED"),
        (OnlyAgentToolCallOutcome.RESULT_INVALID, "AGENT_TOOL_RESULT_INVALID"),
    ],
)
def test_reducer_tool_terminal_failures_have_no_continuation(
    tmp_path: Path, outcome: OnlyAgentToolCallOutcome, failure_code: str
) -> None:
    fixture, context, models, tools, store, application = service(tmp_path)
    decision = derive_plan(fixture, context, models, application)
    plan, _ = tool_occurrence(
        context,
        ordinal=0,
        decision=decision.decision_fingerprint,
        tool_class=OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
        owner=ref("CATALOG_GENERATION", context.research_brief.catalog_generation_fingerprint),
    )
    result = OnlyAgentToolCallResultV1(plan.tool_call_plan_fingerprint, outcome, failure_code=failure_code)
    tools.add(plan, result)
    reducer = OnlyAgentSessionReducerV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        decision_service=application,
        decision_store=store,
        launch_service=launch_application(tmp_path, context, application, tools),
    )
    state = reducer.derive(context.session.session_fingerprint)
    assert state.status is OnlyAgentDerivedSessionStatus.FAILED
    assert state.next_action is None
    assert state.failure_code == failure_code
    router_plan, router_result = model_occurrence(
        fixture,
        context,
        ordinal=1,
        role="SEARCH_ROUTER",
        role_fingerprint=context.session.ordered_role_policy_fingerprints[1],
        refs=(
            ref("AGENT_RESEARCH_BRIEF", context.research_brief.research_brief_fingerprint),
            ref("AGENT_TOOL_CALL_RESULT", result.tool_call_result_fingerprint),
        ),
        output={"router_action": OnlyAgentRouterAction.REUSE_EXISTING.value},
        parent=decision.decision_fingerprint,
    )
    models.add(router_plan, router_result)
    with pytest.raises(OnlyAgentContextError, match="AGENT_HISTORY_CONTRADICTORY"):
        reducer.derive(context.session.session_fingerprint)


def test_reducer_projects_budget_exhaustion_before_new_occurrence(tmp_path: Path) -> None:
    fixture, context = decision_context(tmp_path)
    brief = replace(
        context.research_brief,
        agent_budget=OnlyAgentBudgetV1(1, 6),
        research_brief_fingerprint="",
    )
    session = OnlyAgentSessionManifestV1(
        brief.research_brief_fingerprint,
        context.session.agent_workflow_id,
        context.session.agent_workflow_semantic_version,
        context.session.agent_workflow_implementation_fingerprint,
        context.session.agent_workflow_source_revision,
        context.session.workflow_implementation_resource_fingerprint,
        context.session.tool_policy_fingerprint,
        context.session.ordered_role_policy_fingerprints,
    )
    bounded = OnlyVerifiedAgentDecisionContextV1(
        session,
        brief,
        context.workflow_resource,
        context.tool_policy_resource,
        context.ordered_role_policy_resources,
        context.supporting_resources,
    )
    models = Models()
    tools = Tools()
    store = OnlyJsonAgentDecisionStore(tmp_path)
    application = OnlyAgentDecisionApplicationServiceV1(
        sessions=Sessions(bounded),
        models=models,
        tools=tools,
        references=References(),
        store=store,
    )
    decision = derive_plan(fixture, bounded, models, application)
    catalog_plan, catalog_result = tool_occurrence(
        bounded,
        ordinal=0,
        decision=decision.decision_fingerprint,
        tool_class=OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
        owner=ref("CATALOG_GENERATION", bounded.research_brief.catalog_generation_fingerprint),
    )
    tools.add(catalog_plan, catalog_result)
    reducer = OnlyAgentSessionReducerV1(
        sessions=Sessions(bounded),
        models=models,
        tools=tools,
        decision_service=application,
        decision_store=store,
        launch_service=launch_application(tmp_path, bounded, application, tools),
    )
    state = reducer.derive(bounded.session.session_fingerprint)
    assert state.status is OnlyAgentDerivedSessionStatus.FAILED
    assert state.failure_code == "AGENT_BUDGET_EXHAUSTED"
    assert state.next_action is None


def test_reuse_evidence_proposal_is_terminal_and_non_executable(tmp_path: Path) -> None:
    fixture, context, models, tools, store, application = service(tmp_path)
    directive, _ = derive_directive(fixture, context, models, tools, application, OnlyAgentRouterAction.REUSE_EXISTING)
    statistics = ref("RESEARCH_STATISTICS", "5" * 64)
    research_result = ref("RESEARCH_RESULT", "4" * 64)
    run = OnlyAgentExactAuthorityReferenceV2(
        "RESEARCH_RUN",
        1,
        OnlyAgentReferenceLocatorKind.UUID4,
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    branch = (
        (OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE, ref("RESEARCH_DEFINITION", "1" * 64)),
        (OnlyAgentToolClass.RESEARCH_RUN_SUBMIT, run),
        (OnlyAgentToolClass.RESEARCH_RUN_QUERY, run),
        (OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY, research_result),
    )
    for ordinal, (tool_class, owner) in enumerate(branch, start=1):
        plan, result = tool_occurrence(
            context,
            ordinal=ordinal,
            decision=directive.decision_fingerprint,
            tool_class=tool_class,
            owner=owner,
        )
        if tool_class is OnlyAgentToolClass.RESEARCH_RUN_QUERY:
            response = {
                "run_id": run.locator_value,
                "state": "COMPLETED",
                "result_ref": research_result.locator_value,
            }
            result = replace(
                result,
                canonical_validated_response=response,
                canonical_response_fingerprint=only_canonical_fingerprint(response),
                tool_call_result_fingerprint="",
            )
        elif tool_class is OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY:
            response = {
                "research_result_fingerprint": owner.locator_value,
                "statistics": (
                    {
                        "statistics_fingerprint": "6" * 64,
                        "statistics_result_fingerprint": statistics.locator_value,
                    },
                ),
            }
            result = replace(
                result,
                canonical_validated_response=response,
                canonical_response_fingerprint=only_canonical_fingerprint(response),
                owning_authority_references=(owner,),
                tool_call_result_fingerprint="",
            )
        tools.add(plan, result)
    completed_run = SimpleNamespace(
        state=SimpleNamespace(value="COMPLETED"),
        research_result_fingerprint=research_result.locator_value,
    )
    causality = OnlyAgentEvidenceCausalVerifierV1(
        tools=tools,
        launches=OnlyJsonAgentExperimentLaunchStore(tmp_path),
        semantic_inputs=SemanticInputs(),
        research_states=SimpleNamespace(load_research_run_verified=lambda _reference: completed_run),
    )
    application = OnlyAgentDecisionApplicationServiceV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        references=References(),
        store=store,
        evidence_causality=causality,
    )
    proposal = OnlyAgentNextExperimentProposalV1(
        OnlyAgentEvaluationPathKind.DIRECT_REUSE_RESEARCH,
        ref("RESEARCH_RUN_RESULT", research_result.locator_value),
        (research_result,),
        (statistics,),
        (
            OnlyAgentEvidenceObservationV1(
                OnlyAgentEvidenceObservationCodeV1.FOLLOW_UP_RECOMMENDED,
                (statistics,),
            ),
        ),
        OnlyAgentFollowUpBriefDeltaV1(
            "Refine the hypothesis scope.",
            "The exact evidence identifies a bounded uncertainty.",
            ("Narrow the eligible universe.",),
        ),
    )
    analyst_refs = (
        proposal.completed_path_reference,
        *proposal.research_result_references,
        *proposal.research_statistics_references,
    )
    analyst_plan, analyst_result = model_occurrence(
        fixture,
        context,
        ordinal=3,
        role="EVIDENCE_ANALYST",
        role_fingerprint=context.session.ordered_role_policy_fingerprints[3],
        refs=analyst_refs,
        output=proposal.to_dict(),
        parent=directive.decision_fingerprint,
    )
    models.add(analyst_plan, analyst_result)
    final, _ = application.derive_next_experiment_proposal(
        session_fingerprint=context.session.session_fingerprint,
        evidence_analyst_model_result_fingerprint=analyst_result.model_call_result_fingerprint,
        current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
    )
    assert final.structured_payload == proposal
    reopened = OnlyAgentDecisionApplicationServiceV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        references=References(),
        store=OnlyJsonAgentDecisionStore(tmp_path),
        evidence_causality=causality,
    )
    assert reopened.load_decision_verified(final.decision_fingerprint) == final
    reducer = OnlyAgentSessionReducerV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        decision_service=reopened,
        decision_store=store,
        launch_service=launch_application(tmp_path, context, reopened, tools),
    )
    complete = reducer.derive(context.session.session_fingerprint)
    assert complete.status is OnlyAgentDerivedSessionStatus.COMPLETE
    assert complete.next_action is None
    extra_plan, extra_result = tool_occurrence(
        context,
        ordinal=5,
        decision=directive.decision_fingerprint,
        tool_class=OnlyAgentToolClass.RESEARCH_RUN_QUERY,
        owner=branch[1][1],
    )
    tools.add(extra_plan, extra_result)
    assert (
        reopened.load_decision_by_session_ordinal_verified(context.session.session_fingerprint, 0).decision_kind
        is OnlyAgentDecisionKind.RESEARCH_PLAN
    )
    assert (
        reopened.load_decision_by_session_ordinal_verified(context.session.session_fingerprint, 1).decision_kind
        is OnlyAgentDecisionKind.SEARCH_DIRECTIVE
    )
    assert reopened.load_decision_verified(final.decision_fingerprint) == final
    with pytest.raises(OnlyAgentContextError, match="AGENT_HISTORY_CONTRADICTORY"):
        reducer.derive(context.session.session_fingerprint)


def test_production_evidence_occurrence_closes_statistics_before_analyst_plan(tmp_path: Path) -> None:
    fixture, original = decision_context(tmp_path)
    contract_path = Path(__file__).resolve().parents[3] / "contracts/product-api/v2/openapi.json"
    contract = OnlyProductApiContractV2(contract_path)
    evidence_operation = "statistics_catalog_api_v2_research_artifacts__research_result_fingerprint__statistics_get"
    run_operation = "get_run_api_v2_research_runs__run_id__get"
    policy = original.tool_policy_resource.canonical_payload
    constraints = tuple(
        sorted(
            (
                replace(
                    item,
                    operation_identity=(
                        evidence_operation
                        if item.tool_class is OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY
                        else run_operation
                        if item.tool_class is OnlyAgentToolClass.RESEARCH_RUN_QUERY
                        else item.operation_identity
                    ),
                    identity_requirements=(
                        ("research_result_fingerprint",)
                        if item.tool_class is OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY
                        else ("run_id",)
                        if item.tool_class is OnlyAgentToolClass.RESEARCH_RUN_QUERY
                        else item.identity_requirements
                    ),
                )
                for item in policy.operation_constraints  # type: ignore[union-attr]
            ),
            key=lambda item: item.operation_identity,
        )
    )
    tool_policy_resource = resource(
        original.tool_policy_resource.resource_kind,
        replace(policy, operation_constraints=constraints),  # type: ignore[arg-type]
    )
    session = replace(
        original.session,
        tool_policy_fingerprint=tool_policy_resource.resource_fingerprint,
        session_fingerprint="",
    )
    context = replace(original, session=session, tool_policy_resource=tool_policy_resource)
    result_reference = ref("RESEARCH_RESULT", "7" * 64)
    statistics_reference = ref("RESEARCH_STATISTICS", "9" * 64)
    run_reference = OnlyAgentExactAuthorityReferenceV2(
        "RESEARCH_RUN",
        1,
        OnlyAgentReferenceLocatorKind.UUID4,
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    directive = SimpleNamespace(
        agent_session_fingerprint=session.session_fingerprint,
        decision_fingerprint="d" * 64,
        decision_kind=OnlyAgentDecisionKind.SEARCH_DIRECTIVE,
        structured_payload=OnlyAgentSearchDirectiveV1(
            OnlyAgentRouterAction.REUSE_EXISTING,
            "c" * 64,
            OnlyAgentReuseDirectiveV1(
                (ref("QUANT_ASSET", "1" * 64),),
                ref("RESEARCH_DEFINITION", "2" * 64),
            ),
        ),
    )

    class ExactInputs(SemanticInputs):
        def verify_exact_reference(self, _reference):  # type: ignore[no-untyped-def]
            return None

        def load_exact_response_verified(self, _reference):  # type: ignore[no-untyped-def]
            raise LookupError(_reference)

    inputs = ExactInputs(
        {
            ("RESEARCH_STATISTICS", statistics_reference.locator_value): {
                "statistics_result_fingerprint": statistics_reference.locator_value
            }
        }
    )
    tool_store = OnlyJsonAgentToolOccurrenceStore(tmp_path / "production-evidence")
    run_plan = OnlyAgentToolCallPlanV1(
        session.session_fingerprint,
        0,
        directive.decision_fingerprint,
        OnlyAgentToolClass.RESEARCH_RUN_QUERY,
        2,
        contract.fingerprint,
        run_operation,
        {"run_id": run_reference.locator_value},
        exact_identity_inputs=(run_reference,),
        tool_policy_fingerprint=session.tool_policy_fingerprint,
    )
    run_response = {
        "schema_version": 2,
        "run_id": run_reference.locator_value,
        "revision": "1",
        "state": "COMPLETED",
        "specification_schema_version": 2,
        "specification_fingerprint": "1" * 64,
        "admission_resolution_fingerprint": "2" * 64,
        "specification": {},
        "queued_at": "2026-09-12T00:00:00Z",
        "started_at": "2026-09-12T00:00:01Z",
        "cancel_requested_at": None,
        "finished_at": "2026-09-12T00:00:02Z",
        "result_ref": result_reference.locator_value,
        "artifact_ref": "3" * 64,
        "failure": None,
    }
    run_result = OnlyAgentToolCallResultV1(
        run_plan.tool_call_plan_fingerprint,
        OnlyAgentToolCallOutcome.SUCCEEDED,
        OnlyAgentObservedResponseStorageKind.INLINE_CANONICAL_RESPONSE,
        run_response,
        canonical_response_fingerprint=only_canonical_fingerprint(run_response),
        owning_authority_references=(run_reference,),
    )
    tool_store.commit_plan(run_plan)
    tool_store.commit_result(run_result)

    class ToolProxy:
        target = None

        def __getattr__(self, name):  # type: ignore[no-untyped-def]
            return getattr(self.target, name)

    proxy = ToolProxy()
    research_states = SimpleNamespace(
        load_research_run_verified=lambda _reference: SimpleNamespace(
            state=SimpleNamespace(value="COMPLETED"),
            research_result_fingerprint=result_reference.locator_value,
        )
    )
    causality = OnlyAgentEvidenceCausalVerifierV1(
        tools=proxy,  # type: ignore[arg-type]
        launches=OnlyJsonAgentExperimentLaunchStore(tmp_path),
        semantic_inputs=inputs,
        research_states=research_states,
    )

    class Decisions:
        def load_decision_by_session_ordinal_verified(self, _session, ordinal):  # type: ignore[no-untyped-def]
            assert ordinal == 1
            return directive

        def load_decision_authorization_verified(self, fingerprint):  # type: ignore[no-untyped-def]
            assert fingerprint == directive.decision_fingerprint
            return OnlyAgentDecisionAuthorizationV1(
                fingerprint,
                session.session_fingerprint,
                session.agent_workflow_implementation_fingerprint,
                (
                    OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY,
                    OnlyAgentToolClass.RESEARCH_RUN_QUERY,
                ),
                (evidence_operation, run_operation),
            )

        def admit_new_tool_intent(self, **kwargs):  # type: ignore[no-untyped-def]
            causality.verify_evidence_query_target(
                decision=directive,  # type: ignore[arg-type]
                tool_call_ordinal=kwargs["tool_call_ordinal"],
                exact_identity_inputs=kwargs["exact_identity_inputs"],
            )

        def verify_historical_tool_intent(self, **_kwargs):  # type: ignore[no-untyped-def]
            return None

    decisions = Decisions()
    tools = OnlyAgentToolOccurrenceServiceV1(
        sessions=Sessions(context),
        decisions=decisions,
        product_contracts=contract,
        references=inputs,
        response_references=inputs,
        store=tool_store,
    )
    proxy.target = tools

    resources = OnlyJsonAgentOrchestrationResourceStore(tmp_path / "production-model")
    for item in (
        *context.supporting_resources,
        context.tool_policy_resource,
        *context.ordered_role_policy_resources,
        context.workflow_resource,
    ):
        resources.commit_resource(item)
    models = OnlyAgentModelOccurrenceServiceV1(
        sessions=Sessions(context),
        resources=resources,
        references=inputs,
        decisions=decisions,
        store=OnlyJsonAgentModelOccurrenceStore(tmp_path / "production-model"),
    )
    analyst_role = context.ordered_role_policy_resources[3]
    binding = OnlyAgentModelInvocationBindingV1(
        "EVIDENCE_ANALYST",
        "provider-a",
        "model-a",
        "2026-09-01",
        fixture.resources[0].resource_fingerprint,
        fixture.resources[1].resource_fingerprint,
        fixture.resources[2].resource_fingerprint,
        (OnlyAgentModelSettingBindingV1("temperature", OnlyAgentModelSettingState.VALUE, "0"),),
    )
    materializer = OnlyAgentWorkflowActionMaterializerV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        decisions=decisions,  # type: ignore[arg-type]
        launches=OnlyJsonAgentExperimentLaunchStore(tmp_path),  # type: ignore[arg-type]
        invocation_bindings=OnlyStaticAgentModelInvocationBindingReaderV1((binding,)),
        product_contracts=contract,
        semantic_inputs=inputs,
        runtime_generations=SimpleNamespace(read_current_new_work_runtime_generation_fingerprint=lambda: "e" * 64),
        research_states=research_states,  # type: ignore[arg-type]
        evidence_causality=causality,
        product_api_contract_fingerprint=contract.fingerprint,
    )
    manifest = context.workflow_resource.canonical_payload
    unrelated = ref("RESEARCH_RESULT", "6" * 64)
    with pytest.raises(OnlyAgentContextError, match="AGENT_EVIDENCE_UNAVAILABLE"):
        tools.prepare_tool_call(
            session_fingerprint=session.session_fingerprint,
            current_workflow_manifest=manifest,  # type: ignore[arg-type]
            tool_call_ordinal=1,
            authorizing_agent_decision_fingerprint=directive.decision_fingerprint,
            tool_class=OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY,
            product_api_major=2,
            product_api_contract_fingerprint=contract.fingerprint,
            operation_identity=evidence_operation,
            canonical_request={"research_result_fingerprint": unrelated.locator_value},
            exact_identity_inputs=(unrelated,),
            product_command_id_or_idempotency_key=None,
        )
    assert tools.budget_consumed(session.session_fingerprint) == 1
    assert models.budget_consumed(session.session_fingerprint) == 0

    evidence_prepared = materializer.prepare_tool_call(
        session_fingerprint=session.session_fingerprint,
        action=OnlyAgentNextActionV1(
            OnlyAgentNextActionKind.PREPARE_TOOL_CALL,
            tool_class=OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY,
        ),
        current_workflow_manifest=manifest,  # type: ignore[arg-type]
    )
    assert tools.load_plan_verified(evidence_prepared.plan.tool_call_plan_fingerprint) == evidence_prepared.plan
    with pytest.raises(OnlyAgentContextError, match="AGENT_EVIDENCE_UNAVAILABLE"):
        materializer.prepare_model_call(
            session_fingerprint=session.session_fingerprint,
            action=OnlyAgentNextActionV1(
                OnlyAgentNextActionKind.PREPARE_MODEL_CALL,
                logical_role="EVIDENCE_ANALYST",
            ),
            current_workflow_manifest=manifest,  # type: ignore[arg-type]
        )
    assert models.budget_consumed(session.session_fingerprint) == 0

    evidence_response = {
        "schema_version": 2,
        "research_result_fingerprint": result_reference.locator_value,
        "statistics": [
            {
                "statistics_fingerprint": "8" * 64,
                "statistics_result_fingerprint": statistics_reference.locator_value,
                "result_content_fingerprint": "a" * 64,
                "statistics_result_schema_version": 2,
                "row_count": 1,
                "feature": {
                    "calculation_fingerprint": "b" * 64,
                    "node_fingerprint": "c" * 64,
                    "output_name": "feature",
                },
                "target": {
                    "calculation_fingerprint": "d" * 64,
                    "node_fingerprint": "e" * 64,
                    "output_name": "target",
                },
                "definition": {
                    "method": "PEARSON",
                    "minimum_observations": 1,
                    "pairing_policy": "PAIRWISE_COMPLETE",
                    "universe_policy": "PER_INSTRUMENT",
                    "rank_tie_method": "AVERAGE",
                    "weighting": "EQUAL",
                    "numeric": {
                        "representation": "DECIMAL",
                        "precision": 18,
                        "output_quantum": "0.000000000001",
                        "rounding": "ROUND_HALF_EVEN",
                    },
                },
            }
        ],
    }

    class Transport:
        calls = 0

        def send(self, _request, permit):  # type: ignore[no-untyped-def]
            assert_external_io_permit(permit, consume=True)
            self.calls += 1
            return OnlyHttpTransportOutcomeV1(
                OnlyHttpDispatchClassification.RESPONSE_RECEIVED,
                OnlyHttpResponseV1(200, (), json.dumps(evidence_response).encode()),
            )

    transport = Transport()
    adapter = OnlyContractDrivenProductApiAdapterV1(
        OnlyProductApiEndpointConfigV1("https://product.invalid", "secret", contract_path),
        transport,  # type: ignore[arg-type]
    )
    permit = _mint_runtime_execution_permit(
        session.session_fingerprint,
        context.workflow_resource.resource_fingerprint,
        session.agent_workflow_implementation_fingerprint,
        session.agent_workflow_source_revision,
    )
    executed = execute_external_tool_occurrence(
        permit=permit,
        prepared=evidence_prepared,
        occurrences=tools,
        adapter=adapter,
    )
    assert transport.calls == 1
    assert executed.result is not None
    assert executed.result.outcome is OnlyAgentToolCallOutcome.SUCCEEDED, executed.result
    assert tuple((item.reference_kind, item.locator_value) for item in executed.result.owning_authority_references) == (
        (result_reference.reference_kind, result_reference.locator_value),
    )
    assert tools.load_result_verified(evidence_prepared.plan.tool_call_plan_fingerprint) == executed.result

    statistics_key = ("RESEARCH_STATISTICS", statistics_reference.locator_value)
    exact_statistics = inputs.payloads.pop(statistics_key)
    with pytest.raises(OnlyAgentContextError, match="AGENT_EVIDENCE_UNAVAILABLE"):
        materializer.prepare_model_call(
            session_fingerprint=session.session_fingerprint,
            action=OnlyAgentNextActionV1(
                OnlyAgentNextActionKind.PREPARE_MODEL_CALL,
                logical_role="EVIDENCE_ANALYST",
            ),
            current_workflow_manifest=manifest,  # type: ignore[arg-type]
        )
    assert models.budget_consumed(session.session_fingerprint) == 0
    inputs.payloads[statistics_key] = exact_statistics

    model_prepared = materializer.prepare_model_call(
        session_fingerprint=session.session_fingerprint,
        action=OnlyAgentNextActionV1(
            OnlyAgentNextActionKind.PREPARE_MODEL_CALL,
            logical_role="EVIDENCE_ANALYST",
        ),
        current_workflow_manifest=manifest,  # type: ignore[arg-type]
    )
    assert model_prepared.plan.role_policy_fingerprint == analyst_role.resource_fingerprint
    assert model_prepared.plan.ordered_context_references == (
        ref("RESEARCH_RUN_RESULT", result_reference.locator_value),
        result_reference,
        statistics_reference,
    )


def test_typed_evidence_observation_is_closed_and_reference_backed() -> None:
    statistics = ref("RESEARCH_STATISTICS", "1" * 64)
    observation = OnlyAgentEvidenceObservationV1(
        OnlyAgentEvidenceObservationCodeV1.LIMITED_COVERAGE,
        (statistics,),
    )
    assert OnlyAgentEvidenceObservationV1.from_dict(observation.to_dict()) == observation
    unknown = observation.to_dict()
    unknown["observation_code"] = "IC_EQUALS_POINT_TWO"
    with pytest.raises(ValueError):
        OnlyAgentEvidenceObservationV1.from_dict(unknown)
    numeric = observation.to_dict()
    numeric["sharpe"] = 1.2
    with pytest.raises(ValueError):
        OnlyAgentEvidenceObservationV1.from_dict(numeric)
    with pytest.raises(ValueError):
        OnlyAgentEvidenceObservationV1(
            OnlyAgentEvidenceObservationCodeV1.LIMITED_COVERAGE,
            (ref("RESEARCH_RESULT", "2" * 64),),
        )
    arbitrary = observation.to_dict()
    arbitrary["categorical_assessment"] = "FOLLOW_UP_REQUIRED"
    with pytest.raises(ValueError):
        OnlyAgentEvidenceObservationV1.from_dict(arbitrary)


def test_decision_exact_intent_rejects_independently_valid_search_b(tmp_path: Path) -> None:
    fixture, context, models, tools, _store, application = service(tmp_path)
    decision, _ = derive_directive(fixture, context, models, tools, application, OnlyAgentRouterAction.SYMBOLIC_SEARCH)
    payload = decision.structured_payload.action_payload  # type: ignore[union-attr]
    assert isinstance(payload, OnlyAgentSymbolicSearchDirectiveV1)
    exact = (
        payload.search_space_reference,
        payload.evaluation_reference,
        payload.algorithm_reference,
        payload.search_budget_reference,
        ref("CATALOG_GENERATION", context.research_brief.catalog_generation_fingerprint),
        ref("DATASET_SNAPSHOT", context.research_brief.dataset_snapshot_fingerprint),
        ref("RUNTIME_GENERATION", RuntimeGenerations.fingerprint),
    )
    assert isinstance(decision.structured_payload, OnlyAgentSearchDirectiveV1)
    semantics = dict(
        expected_agent_search_submit_semantics(
            operation_identity="symbolic_search.v1",
            context=context,
            directive=decision.structured_payload,
            runtime_generation_fingerprint=RuntimeGenerations.fingerprint,
        ).semantic_bindings
    )
    application.verify_historical_tool_intent(
        decision_fingerprint=decision.decision_fingerprint,
        tool_class=OnlyAgentToolClass.SYMBOLIC_SEARCH,
        operation_identity="symbolic_search.v1",
        semantic_projection=OnlyAgentProductRequestSemanticProjectionV1("symbolic_search.v1", semantics),
        exact_identity_inputs=exact,
        tool_call_ordinal=0,
    )
    search_b = tuple(
        ref(item.reference_kind, "f" * 64) if item is payload.search_space_reference else item for item in exact
    )
    with pytest.raises(OnlyAgentContextError, match="AGENT_TOOL_OPERATION_NOT_ALLOWED"):
        changed_semantics = dict(semantics)
        changed_semantics["search_space_fingerprint"] = "f" * 64
        application.verify_historical_tool_intent(
            decision_fingerprint=decision.decision_fingerprint,
            tool_class=OnlyAgentToolClass.SYMBOLIC_SEARCH,
            operation_identity="symbolic_search.v1",
            semantic_projection=OnlyAgentProductRequestSemanticProjectionV1("symbolic_search.v1", changed_semantics),
            exact_identity_inputs=search_b,
            tool_call_ordinal=0,
        )


def test_real_tool_occurrence_rejects_changed_non_reference_semantics_before_commit(tmp_path: Path) -> None:
    fixture, context, models, tools, _store, application = service(tmp_path)
    decision, _ = derive_directive(fixture, context, models, tools, application, OnlyAgentRouterAction.SYMBOLIC_SEARCH)
    payload = decision.structured_payload.action_payload  # type: ignore[union-attr]
    assert isinstance(payload, OnlyAgentSymbolicSearchDirectiveV1)
    exact = (
        payload.search_space_reference,
        payload.evaluation_reference,
        payload.algorithm_reference,
        payload.search_budget_reference,
        ref("CATALOG_GENERATION", context.research_brief.catalog_generation_fingerprint),
        ref("DATASET_SNAPSHOT", context.research_brief.dataset_snapshot_fingerprint),
        ref("RUNTIME_GENERATION", RuntimeGenerations.fingerprint),
    )
    contracts = SemanticProductContracts(exact, context, decision)
    occurrence_store = OnlyJsonAgentToolOccurrenceStore(tmp_path / "semantic-tool")
    occurrence = OnlyAgentToolOccurrenceServiceV1(
        sessions=Sessions(context),
        decisions=application,
        product_contracts=contracts,
        references=References(),
        response_references=References(),
        store=occurrence_store,
    )
    request: dict[str, object] = {"hypothesis": context.research_brief.hypothesis.to_dict()}
    request.update(
        {
            "id" if index == 0 else f"identity_{index}": reference.reference_fingerprint
            for index, reference in enumerate(exact)
        }
    )
    prepared = occurrence.prepare_tool_call(
        session_fingerprint=context.session.session_fingerprint,
        current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
        tool_call_ordinal=0,
        authorizing_agent_decision_fingerprint=decision.decision_fingerprint,
        tool_class=OnlyAgentToolClass.SYMBOLIC_SEARCH,
        product_api_major=2,
        product_api_contract_fingerprint="d" * 64,
        operation_identity="symbolic_search.v1",
        canonical_request=request,
        exact_identity_inputs=exact,
        product_command_id_or_idempotency_key="00000000-0000-4000-8000-000000000001",
    )
    assert prepared.plan.tool_call_ordinal == 0
    suffix = replace(
        prepared.plan,
        tool_call_ordinal=1,
        product_command_id_or_idempotency_key="00000000-0000-4000-8000-000000000002",
        tool_call_plan_fingerprint="",
    )
    occurrence_store.commit_plan(suffix)
    changed_runtime_application = OnlyAgentDecisionApplicationServiceV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        references=References(),
        store=OnlyJsonAgentDecisionStore(tmp_path),
        runtime_generations=DifferentRuntimeGenerations(),
    )
    historical_occurrence = OnlyAgentToolOccurrenceServiceV1(
        sessions=Sessions(context),
        decisions=changed_runtime_application,
        product_contracts=contracts,
        references=References(),
        response_references=References(),
        store=occurrence_store,
    )
    assert historical_occurrence.load_plan_verified(prepared.plan.tool_call_plan_fingerprint) == prepared.plan
    changed = dict(request)
    changed_hypothesis = dict(context.research_brief.hypothesis.to_dict())
    changed_hypothesis["statement"] = "A different semantic hypothesis."
    changed["hypothesis"] = changed_hypothesis
    with pytest.raises(OnlyAgentContextError, match="AGENT_TOOL_OPERATION_NOT_ALLOWED"):
        occurrence.prepare_tool_call(
            session_fingerprint=context.session.session_fingerprint,
            current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
            tool_call_ordinal=1,
            authorizing_agent_decision_fingerprint=decision.decision_fingerprint,
            tool_class=OnlyAgentToolClass.SYMBOLIC_SEARCH,
            product_api_major=2,
            product_api_contract_fingerprint="d" * 64,
            operation_identity="symbolic_search.v1",
            canonical_request=changed,
            exact_identity_inputs=exact,
            product_command_id_or_idempotency_key="00000000-0000-4000-8000-000000000002",
        )
    assert occurrence.budget_consumed(context.session.session_fingerprint) == 2


def test_reuse_mutable_observation_loss_allows_new_plan_and_later_result(tmp_path: Path) -> None:
    fixture, context, models, tools, store, application = service(tmp_path)
    directive, _ = derive_directive(fixture, context, models, tools, application, OnlyAgentRouterAction.REUSE_EXISTING)
    run_store = ResearchRunStore(
        queued_research_run().transition(OnlyResearchRunState.RUNNING, at=RUN_NOW + timedelta(seconds=1))
    )
    run_reference = OnlyAgentExactAuthorityReferenceV2(
        "RESEARCH_RUN",
        1,
        OnlyAgentReferenceLocatorKind.UUID4,
        run_store.run.run_id.value,
    )
    branch = (
        (OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE, ref("RESEARCH_DEFINITION", "1" * 64)),
        (OnlyAgentToolClass.RESEARCH_RUN_SUBMIT, run_reference),
    )
    for ordinal, (tool_class, owner) in enumerate(branch, start=1):
        plan, result = tool_occurrence(
            context,
            ordinal=ordinal,
            decision=directive.decision_fingerprint,
            tool_class=tool_class,
            owner=owner,
        )
        tools.add(plan, result)
    lost, _ = tool_occurrence(
        context,
        ordinal=3,
        decision=directive.decision_fingerprint,
        tool_class=OnlyAgentToolClass.RESEARCH_RUN_QUERY,
        owner=branch[1][1],
    )
    tools.add(lost)
    run_states = ProductResearchStates(OnlyResearchRunQueryService(run_store))
    causality = OnlyAgentEvidenceCausalVerifierV1(
        tools=tools,
        launches=OnlyJsonAgentExperimentLaunchStore(tmp_path),
        semantic_inputs=SemanticInputs(),
        research_states=run_states,
    )
    application = OnlyAgentDecisionApplicationServiceV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        references=References(),
        store=store,
        evidence_causality=causality,
    )
    reducer = OnlyAgentSessionReducerV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        decision_service=application,
        decision_store=store,
        launch_service=launch_application(tmp_path, context, application, tools),
        research_states=run_states,
    )
    state = reducer.derive(context.session.session_fingerprint)
    assert state.next_action is not None
    assert state.next_action.action_kind is OnlyAgentNextActionKind.PREPARE_NEW_TOOL_OBSERVATION
    later, later_result = tool_occurrence(
        context,
        ordinal=4,
        decision=directive.decision_fingerprint,
        tool_class=OnlyAgentToolClass.RESEARCH_RUN_QUERY,
        owner=branch[1][1],
    )
    tools.add(later, later_result)
    run_store.run = run_store.run.transition(
        OnlyResearchRunState.COMPLETED,
        at=RUN_NOW + timedelta(seconds=2),
        research_result_fingerprint="3" * 64,
        artifact_content_fingerprint="4" * 64,
    )
    completed = OnlyAgentSessionReducerV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        decision_service=application,
        decision_store=store,
        launch_service=launch_application(tmp_path, context, application, tools),
        research_states=run_states,
    ).derive(context.session.session_fingerprint)
    assert completed.next_action is not None
    assert completed.next_action.action_kind is OnlyAgentNextActionKind.PREPARE_NEW_TOOL_OBSERVATION
    terminal_plan, terminal_result = tool_occurrence(
        context,
        ordinal=5,
        decision=directive.decision_fingerprint,
        tool_class=OnlyAgentToolClass.RESEARCH_RUN_QUERY,
        owner=branch[1][1],
    )
    terminal_path = ref("RESEARCH_RUN_RESULT", "3" * 64)
    terminal_response = {
        "run_id": run_reference.locator_value,
        "state": "COMPLETED",
        "result_ref": "3" * 64,
    }
    terminal_result = replace(
        terminal_result,
        canonical_validated_response=terminal_response,
        canonical_response_fingerprint=only_canonical_fingerprint(terminal_response),
        owning_authority_references=(run_reference,),
        tool_call_result_fingerprint="",
    )
    tools.add(terminal_plan, terminal_result)
    observed = reducer.derive(context.session.session_fingerprint)
    assert observed.next_action is not None
    assert observed.next_action.tool_class is OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY
    statistics = ref("RESEARCH_STATISTICS", "5" * 64)
    research_result = ref("RESEARCH_RESULT", "3" * 64)
    evidence_plan, evidence_result = tool_occurrence(
        context,
        ordinal=6,
        decision=directive.decision_fingerprint,
        tool_class=OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY,
        owner=research_result,
    )
    evidence_response = {
        "research_result_fingerprint": research_result.locator_value,
        "statistics": (
            {
                "statistics_fingerprint": "9" * 64,
                "statistics_result_fingerprint": statistics.locator_value,
            },
        ),
    }
    evidence_result = replace(
        evidence_result,
        canonical_validated_response=evidence_response,
        canonical_response_fingerprint=only_canonical_fingerprint(evidence_response),
        owning_authority_references=(research_result,),
        tool_call_result_fingerprint="",
    )
    tools.add(evidence_plan, evidence_result)
    proposal = OnlyAgentNextExperimentProposalV1(
        OnlyAgentEvaluationPathKind.DIRECT_REUSE_RESEARCH,
        terminal_path,
        (research_result,),
        (statistics,),
        (
            OnlyAgentEvidenceObservationV1(
                OnlyAgentEvidenceObservationCodeV1.FOLLOW_UP_RECOMMENDED,
                (statistics,),
            ),
        ),
        OnlyAgentFollowUpBriefDeltaV1("refine", "evidence", ("narrow scope",)),
    )
    analyst_plan, analyst_result = model_occurrence(
        fixture,
        context,
        ordinal=3,
        role="EVIDENCE_ANALYST",
        role_fingerprint=context.session.ordered_role_policy_fingerprints[3],
        refs=(terminal_path, research_result, statistics),
        output=proposal.to_dict(),
        parent=directive.decision_fingerprint,
    )
    models.add(analyst_plan, analyst_result)
    final, _ = application.derive_next_experiment_proposal(
        session_fingerprint=context.session.session_fingerprint,
        evidence_analyst_model_result_fingerprint=analyst_result.model_call_result_fingerprint,
        current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
    )
    assert lost.tool_call_plan_fingerprint not in {
        tools.load_result_by_fingerprint_verified(item).tool_call_plan_fingerprint
        for item in final.ordered_tool_call_result_fingerprints
    }
    assert reducer.derive(context.session.session_fingerprint).status is OnlyAgentDerivedSessionStatus.COMPLETE


def test_reducer_composes_real_symbolic_product_nonterminal_and_reconcile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    product_root = tmp_path / "product"
    product_root.mkdir()
    search_commands, search_queries, _authority, _runs, submit = symbolic_product_case(product_root)
    created = search_commands.submit(submit)
    assert created.terminal.terminal_kind is OnlySearchTerminalKindV1.NON_TERMINAL
    child = created.experiment

    agent_root = tmp_path / "agent"
    agent_root.mkdir()
    fixture, original = decision_context(agent_root)
    evaluation = OnlyAgentEvaluationContextReferenceV1(
        child.evaluation_context_reference.evaluation_kind,
        child.evaluation_context_reference.evaluation_schema_version,
        child.evaluation_context_reference.evaluation_fingerprint,
    )
    brief = replace(
        original.research_brief,
        catalog_generation_fingerprint=child.catalog_generation_fingerprint,
        dataset_snapshot_fingerprint=child.dataset_snapshot_fingerprint,
        evaluation_context_reference=evaluation,
        allowed_search_methods=(OnlyAgentSearchMethod.SYMBOLIC_SEARCH,),
        agent_budget=OnlyAgentBudgetV1(4, 10),
        research_brief_fingerprint="",
    )
    session = replace(
        original.session,
        research_brief_fingerprint=brief.research_brief_fingerprint,
        session_fingerprint="",
    )
    context = replace(original, session=session, research_brief=brief)
    models = Models()
    tools = Tools()
    store = OnlyJsonAgentDecisionStore(agent_root)
    application = OnlyAgentDecisionApplicationServiceV1(
        sessions=Sessions(context), models=models, tools=tools, references=References(), store=store
    )

    def exact_payload(_action, _context):  # type: ignore[no-untyped-def]
        return OnlyAgentSymbolicSearchDirectiveV1(
            ref("SYMBOLIC_SEARCH_SPACE", child.search_space_reference.search_space_fingerprint),
            ref("RESEARCH_EVALUATION", child.evaluation_context_reference.evaluation_fingerprint),
            ref("SEARCH_ALGORITHM", child.search_algorithm_binding.implementation_fingerprint),
            ref("SEARCH_BUDGET", only_canonical_fingerprint(child.search_budget.to_dict())),
        )

    monkeypatch.setattr(__import__(__name__, fromlist=["action_payload"]), "action_payload", exact_payload)
    directive, _ = derive_directive(fixture, context, models, tools, application, OnlyAgentRouterAction.SYMBOLIC_SEARCH)
    submit_plan, submit_result = tool_occurrence(
        context,
        ordinal=1,
        decision=directive.decision_fingerprint,
        tool_class=OnlyAgentToolClass.SYMBOLIC_SEARCH,
        owner=ref("SEARCH_EXPERIMENT", child.experiment_fingerprint),
    )
    tools.add(submit_plan, submit_result)
    launches = launch_application(agent_root, context, application, tools, child)
    launches.reconstruct_launch_record(
        session_fingerprint=context.session.session_fingerprint,
        agent_decision_fingerprint=directive.decision_fingerprint,
        tool_call_result_fingerprint=submit_result.tool_call_result_fingerprint,
        child_search_experiment_fingerprint=child.experiment_fingerprint,
        current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
    )
    reducer = OnlyAgentSessionReducerV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        decision_service=application,
        decision_store=store,
        launch_service=launches,
        search_states=ProductSearchStates(search_queries),
    )
    advance = reducer.derive(context.session.session_fingerprint)
    assert advance.next_action is not None
    assert advance.next_action.action_kind is OnlyAgentNextActionKind.PREPARE_AUTHORITY_TOOL_CALL
    assert advance.next_action.operation_identity == OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE

    search_commands.advance(
        OnlyAdvanceSearchExperimentV1(
            product_command_id(),
            OnlySearchMethodV1.SYMBOLIC,
            OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
            created.ledger.expected_state,
        )
    )
    reconcile = reducer.derive(context.session.session_fingerprint)
    assert reconcile.next_action is not None
    assert reconcile.next_action.operation_identity == OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE

    nonterminal_plan, nonterminal_result = tool_occurrence(
        context,
        ordinal=2,
        decision=directive.decision_fingerprint,
        tool_class=OnlyAgentToolClass.SEARCH_QUERY,
        owner=ref(
            "SEARCH_TERMINAL_PROJECTION",
            only_canonical_fingerprint(
                {
                    "method": created.terminal.method.value,
                    "experiment_fingerprint": created.terminal.experiment_fingerprint,
                    "terminal_kind": created.terminal.terminal_kind.value,
                    "stop_reason": created.terminal.stop_reason,
                }
            ),
        ),
    )
    tools.add(nonterminal_plan, nonterminal_result)

    for _ in range(10):
        ledger = search_queries.get_ledger(OnlyGetSearchIterationLedgerV1(child.experiment_fingerprint))
        if ledger.results and ledger.results[-1] is None:
            _runs.state = OnlyResearchRunState.COMPLETED
            _runs.complete_and_release()
            search_commands.advance(
                OnlyAdvanceSearchExperimentV1(
                    product_command_id(),
                    OnlySearchMethodV1.SYMBOLIC,
                    OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE,
                    symbolic_reconcile_expected(
                        ledger.expected_state,
                        ledger.plans[-1].iteration_plan_fingerprint,
                    ),
                )
            )
        else:
            current_terminal = search_queries.get_terminal(
                OnlyGetSearchTerminalDecisionV1(child.experiment_fingerprint)
            )
            if current_terminal.terminal_kind is not OnlySearchTerminalKindV1.NON_TERMINAL:
                break
            search_commands.advance(
                OnlyAdvanceSearchExperimentV1(
                    product_command_id(),
                    OnlySearchMethodV1.SYMBOLIC,
                    OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
                    ledger.expected_state,
                )
            )
    else:
        raise AssertionError("real Symbolic Product did not reach its bounded terminal projection")

    requires_terminal_observation = reducer.derive(context.session.session_fingerprint)
    assert requires_terminal_observation.next_action is not None
    assert requires_terminal_observation.next_action.action_kind is OnlyAgentNextActionKind.PREPARE_NEW_TOOL_OBSERVATION
    assert requires_terminal_observation.next_action.tool_class is OnlyAgentToolClass.SEARCH_QUERY

    terminal = search_queries.get_terminal(OnlyGetSearchTerminalDecisionV1(child.experiment_fingerprint))
    terminal_projection_fingerprint = only_canonical_fingerprint(
        {
            "method": terminal.method.value,
            "experiment_fingerprint": terminal.experiment_fingerprint,
            "terminal_kind": terminal.terminal_kind.value,
            "stop_reason": terminal.stop_reason,
        }
    )
    terminal_plan, terminal_result = tool_occurrence(
        context,
        ordinal=3,
        decision=directive.decision_fingerprint,
        tool_class=OnlyAgentToolClass.SEARCH_QUERY,
        owner=ref("SEARCH_TERMINAL_PROJECTION", terminal_projection_fingerprint),
    )
    tools.add(terminal_plan, terminal_result)
    evidence = reducer.derive(context.session.session_fingerprint)
    assert evidence.next_action is not None
    assert evidence.next_action.action_kind is OnlyAgentNextActionKind.PREPARE_TOOL_CALL
    assert evidence.next_action.tool_class is OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY


def test_reducer_composes_real_parameter_product_frontier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from onlyalpha.research.search.parameter import algorithm as parameter_algorithm

    monkeypatch.setattr(parameter_algorithm, "only_packaged_build_provenance", packaged_provenance)
    product_root = tmp_path / "parameter-product"
    product_root.mkdir()
    search_commands, search_queries, _authority, _runs, _commands, submit, _adapter = parameter_product_case(
        product_root
    )
    created = search_commands.submit(submit)
    child = created.experiment
    agent_root = tmp_path / "parameter-agent"
    agent_root.mkdir()
    fixture, original = decision_context(agent_root)
    brief = replace(
        original.research_brief,
        catalog_generation_fingerprint=child.catalog_generation_fingerprint,
        dataset_snapshot_fingerprint=child.dataset_snapshot_fingerprint,
        evaluation_context_reference=OnlyAgentEvaluationContextReferenceV1(
            child.evaluation_context_reference.evaluation_kind,
            child.evaluation_context_reference.evaluation_schema_version,
            child.evaluation_context_reference.evaluation_fingerprint,
        ),
        allowed_search_methods=(OnlyAgentSearchMethod.PARAMETER_SEARCH,),
        agent_budget=OnlyAgentBudgetV1(4, 10),
        research_brief_fingerprint="",
    )
    context = replace(
        original,
        session=replace(
            original.session,
            research_brief_fingerprint=brief.research_brief_fingerprint,
            session_fingerprint="",
        ),
        research_brief=brief,
    )
    models, tools, store = Models(), Tools(), OnlyJsonAgentDecisionStore(agent_root)
    application = OnlyAgentDecisionApplicationServiceV1(
        sessions=Sessions(context), models=models, tools=tools, references=References(), store=store
    )

    def exact_payload(_action, _context):  # type: ignore[no-untyped-def]
        return OnlyAgentParameterSearchDirectiveV1(
            ref("PARAMETER_SEARCH_SPACE", child.search_space_reference.search_space_fingerprint),
            ref("RESEARCH_EVALUATION", child.evaluation_context_reference.evaluation_fingerprint),
            ref("SEARCH_POLICY", child.search_policy_reference.policy_fingerprint),
            ref("SEARCH_ALGORITHM", child.search_algorithm_binding.implementation_fingerprint),
            ref("SEARCH_BUDGET", only_canonical_fingerprint(child.search_budget.to_dict())),
        )

    monkeypatch.setattr(__import__(__name__, fromlist=["action_payload"]), "action_payload", exact_payload)
    directive, _ = derive_directive(
        fixture, context, models, tools, application, OnlyAgentRouterAction.PARAMETER_SEARCH
    )
    submit_plan, submit_result = tool_occurrence(
        context,
        ordinal=1,
        decision=directive.decision_fingerprint,
        tool_class=OnlyAgentToolClass.PARAMETER_SEARCH,
        owner=ref("SEARCH_EXPERIMENT", child.experiment_fingerprint),
    )
    tools.add(submit_plan, submit_result)
    launches = launch_application(agent_root, context, application, tools, child)
    launches.reconstruct_launch_record(
        session_fingerprint=context.session.session_fingerprint,
        agent_decision_fingerprint=directive.decision_fingerprint,
        tool_call_result_fingerprint=submit_result.tool_call_result_fingerprint,
        child_search_experiment_fingerprint=child.experiment_fingerprint,
        current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
    )
    reducer = OnlyAgentSessionReducerV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        decision_service=application,
        decision_store=store,
        launch_service=launches,
        search_states=ProductSearchStates(search_queries),
    )
    initial = reducer.derive(context.session.session_fingerprint)
    assert initial.next_action is not None
    assert initial.next_action.operation_identity == OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION
    advanced = search_commands.advance(
        OnlyAdvanceSearchExperimentV1(
            product_command_id(),
            OnlySearchMethodV1.PARAMETER,
            OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION,
            created.ledger.expected_state,
        )
    )
    assert advanced.ledger.expected_state.ordered_feedback_decision_fingerprints  # type: ignore[union-attr]
    reconcile = reducer.derive(context.session.session_fingerprint)
    assert reconcile.next_action is not None
    assert reconcile.next_action.operation_identity == OnlySearchBoundedOperationV1.RECONCILE_OPEN_PARAMETER_BATCH


class DurableBranchModels(Models):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self._path = root / "model-facts.json"
        if self._path.is_file():
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            self.plans = [OnlyAgentModelCallPlanV1.from_dict(item) for item in payload["plans"]]
            loaded = [OnlyAgentModelCallResultV1.from_dict(item) for item in payload["results"]]
            self.results = {item.model_call_result_fingerprint: item for item in loaded}

    def add(self, plan: OnlyAgentModelCallPlanV1, result: OnlyAgentModelCallResultV1 | None = None) -> None:
        super().add(plan, result)
        self._path.write_text(
            json.dumps(
                {
                    "plans": [item.to_dict() for item in self.plans],
                    "results": [item.to_dict() for item in self.results.values()],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )


class DurableBranchTools(Tools):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self._path = root / "tool-facts.json"
        if self._path.is_file():
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            self.plans = [OnlyAgentToolCallPlanV1.from_dict(item) for item in payload["plans"]]
            loaded = [OnlyAgentToolCallResultV1.from_dict(item) for item in payload["results"]]
            self.results = {item.tool_call_result_fingerprint: item for item in loaded}

    def add(self, plan: OnlyAgentToolCallPlanV1, result: OnlyAgentToolCallResultV1 | None = None) -> None:
        super().add(plan, result)
        self._path.write_text(
            json.dumps(
                {
                    "plans": [item.to_dict() for item in self.plans],
                    "results": [item.to_dict() for item in self.results.values()],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )


class BranchDriverMaterializer:
    """Test-only external boundary; Reducer remains the sole progress grammar."""

    def __init__(self, root: Path, branch: OnlyAgentRouterAction) -> None:
        self._root = root
        self.fixture, self.context = decision_context(root)
        self.models, self.tools = DurableBranchModels(root), DurableBranchTools(root)
        self.decisions = OnlyJsonAgentDecisionStore(root)
        self.branch = branch
        self.child = (
            child_experiment(self.context, branch)
            if branch in {OnlyAgentRouterAction.SYMBOLIC_SEARCH, OnlyAgentRouterAction.PARAMETER_SEARCH}
            else None
        )
        self.command_ids: list[str] = []
        self.terminal_path = ref(
            "SEARCH_TERMINAL_PROJECTION" if self.child is not None else "RESEARCH_RUN_RESULT",
            ("6" if self.child is not None else "7") * 64,
        )
        self.research_result = ref("RESEARCH_RESULT", "7" * 64)
        self.statistics = ref("RESEARCH_STATISTICS", "8" * 64)
        self.run = OnlyAgentExactAuthorityReferenceV2(
            "RESEARCH_RUN",
            1,
            OnlyAgentReferenceLocatorKind.UUID4,
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )
        self.search_states = (
            DurableAdvancingSearchStates(root, self.child.experiment_fingerprint, branch)
            if self.child is not None
            else None
        )
        self.research_states = SimpleNamespace(
            load_research_run_verified=lambda _reference: SimpleNamespace(
                state=SimpleNamespace(value="COMPLETED"),
                research_result_fingerprint=self.research_result.locator_value,
            )
        )
        self.semantic_inputs = SemanticInputs(
            {
                ("SEARCH_ITERATION_RESULT", "5" * 64): {
                    "research_result_reference": {"result_fingerprint": self.research_result.locator_value}
                }
            }
        )
        self._build_application(root)
        children = () if self.child is None else (self.child,)
        self.launches = launch_application(root, self.context, self.application, self.tools, *children)

    @classmethod
    def reopen(cls, root: Path, branch: OnlyAgentRouterAction) -> BranchDriverMaterializer:
        """Construct a wholly new semantic graph from durable roots and immutable config."""

        return cls(root, branch)

    def refresh_application_services(self, root: Path) -> None:
        """Rebuild every fact reader/service over the same durable test roots."""

        self.models = DurableBranchModels(root)
        self.tools = DurableBranchTools(root)
        self.decisions = OnlyJsonAgentDecisionStore(root)
        self.search_states = (
            DurableAdvancingSearchStates(root, self.child.experiment_fingerprint, self.branch)
            if self.child is not None
            else None
        )
        self._build_application(root)
        children = () if self.child is None else (self.child,)
        self.launches = launch_application(root, self.context, self.application, self.tools, *children)

    def _build_application(self, root: Path) -> None:
        causality = OnlyAgentEvidenceCausalVerifierV1(
            tools=self.tools,
            launches=OnlyJsonAgentExperimentLaunchStore(root),
            semantic_inputs=self.semantic_inputs,
            research_states=self.research_states if self.child is None else None,
            search_states=self.search_states,
        )
        self.application = OnlyAgentDecisionApplicationServiceV1(
            sessions=Sessions(self.context),
            models=self.models,
            tools=self.tools,
            references=References(),
            store=self.decisions,
            evidence_causality=causality,
        )

    def prepare_model_call(self, *, action, **_kwargs):  # type: ignore[no-untyped-def]
        ordinal = self.models.budget_consumed(self.context.session.session_fingerprint)
        role = action.logical_role
        if role == "RESEARCH_PLANNER":
            output: dict[str, object] = {"action": "PLAN"}
        elif role == "SEARCH_ROUTER":
            output = {"router_action": self.branch.value}
            if self.branch is OnlyAgentRouterAction.CAPABILITY_GAP:
                output["action_payload"] = OnlyAgentCapabilityGapDirectiveV1(
                    (ref("MISSING_CAPABILITY", "9" * 64),), ("FACTOR",), ("MISSING_L3",)
                ).to_dict()
        elif role == "FACTOR_DESIGNER":
            output = {"action_payload": action_payload(self.branch, self.context).to_dict()}
        else:
            output = self._proposal().to_dict()
        return model_occurrence(
            self.fixture,
            self.context,
            ordinal=ordinal,
            role=role,
            role_fingerprint=self.context.session.ordered_role_policy_fingerprints[
                {"RESEARCH_PLANNER": 0, "SEARCH_ROUTER": 1, "FACTOR_DESIGNER": 2, "EVIDENCE_ANALYST": 3}[role]
            ],
            refs=self._model_references(role),
            output=output,
            parent=(
                None
                if role == "RESEARCH_PLANNER"
                else self.application.load_decision_by_session_ordinal_verified(
                    self.context.session.session_fingerprint, 1 if role == "EVIDENCE_ANALYST" else 0
                ).decision_fingerprint
            ),
        )

    def prepare_tool_call(self, *, action, **_kwargs):  # type: ignore[no-untyped-def]
        ordinal = self.tools.budget_consumed(self.context.session.session_fingerprint)
        decision = self.application.load_decision_by_session_ordinal_verified(
            self.context.session.session_fingerprint,
            0 if action.tool_class is OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY else 1,
        )
        plan, result = tool_occurrence(
            self.context,
            ordinal=ordinal,
            decision=decision.decision_fingerprint,
            tool_class=action.tool_class,
            owner=self._tool_owner(action.tool_class),
        )
        if action.tool_class in {
            OnlyAgentToolClass.RESEARCH_RUN_SUBMIT,
            OnlyAgentToolClass.SYMBOLIC_SEARCH,
            OnlyAgentToolClass.PARAMETER_SEARCH,
        }:
            command_id = str(uuid.UUID(int=ordinal + 1, version=4))
            self.command_ids.append(command_id)
            plan = replace(
                plan,
                operation_identity=(
                    action.operation_identity if action.operation_identity is not None else plan.operation_identity
                ),
                product_command_id_or_idempotency_key=command_id,
                tool_call_plan_fingerprint="",
            )
            result = replace(
                result,
                tool_call_plan_fingerprint=plan.tool_call_plan_fingerprint,
                tool_call_result_fingerprint="",
            )
        if action.tool_class is OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY:
            response = {
                "research_result_fingerprint": self.research_result.locator_value,
                "statistics": (
                    {
                        "statistics_fingerprint": "9" * 64,
                        "statistics_result_fingerprint": self.statistics.locator_value,
                    },
                ),
            }
            result = replace(
                result,
                canonical_validated_response=response,
                canonical_response_fingerprint=only_canonical_fingerprint(response),
                owning_authority_references=(self.research_result,),
                tool_call_result_fingerprint="",
            )
        elif action.tool_class is OnlyAgentToolClass.RESEARCH_RUN_QUERY:
            response = {
                "run_id": self.run.locator_value,
                "state": "COMPLETED",
                "result_ref": self.research_result.locator_value,
            }
            result = replace(
                result,
                canonical_validated_response=response,
                canonical_response_fingerprint=only_canonical_fingerprint(response),
                owning_authority_references=(self.run,),
                tool_call_result_fingerprint="",
            )
        elif action.tool_class is OnlyAgentToolClass.SEARCH_QUERY:
            assert self.search_states is not None
            terminal = self.search_states.load_search_state_verified(
                self.child.experiment_fingerprint  # type: ignore[union-attr]
            ).terminal
            response = {
                "schema_version": 1,
                "experiment_fingerprint": terminal.experiment_fingerprint,
                "method": terminal.method.value,
                "terminal_kind": terminal.terminal_kind.value,
                "terminal_fact": terminal.terminal_fact.to_dict(),
                "stop_reason": terminal.stop_reason,
            }
            result = replace(
                result,
                canonical_validated_response=response,
                canonical_response_fingerprint=only_canonical_fingerprint(response),
                owning_authority_references=(
                    ref("SEARCH_EXPERIMENT", self.child.experiment_fingerprint),  # type: ignore[union-attr]
                ),
                tool_call_result_fingerprint="",
            )
        return plan, result

    def derive_decision(self, *, decision_kind, **_kwargs):  # type: ignore[no-untyped-def]
        session = self.context.session.session_fingerprint
        manifest = self.fixture.resources[-1].canonical_payload
        if decision_kind is OnlyAgentDecisionKind.RESEARCH_PLAN:
            result = self.models.load_result_verified(self.models.plans[0].model_call_plan_fingerprint)
            self.application.derive_research_plan(
                session_fingerprint=session,
                planner_model_result_fingerprint=result.model_call_result_fingerprint,
                current_workflow_manifest=manifest,  # type: ignore[arg-type]
            )
        elif decision_kind is OnlyAgentDecisionKind.SEARCH_DIRECTIVE:
            router = self.models.load_result_verified(self.models.plans[1].model_call_plan_fingerprint)
            catalog = self.tools.load_result_verified(self.tools.plans[0].tool_call_plan_fingerprint)
            factor = (
                None
                if self.branch is OnlyAgentRouterAction.CAPABILITY_GAP
                else self.models.load_result_verified(
                    self.models.plans[2].model_call_plan_fingerprint
                ).model_call_result_fingerprint
            )
            self.application.derive_search_directive(
                session_fingerprint=session,
                router_model_result_fingerprint=router.model_call_result_fingerprint,
                catalog_tool_result_fingerprint=catalog.tool_call_result_fingerprint,
                factor_designer_model_result_fingerprint=factor,
                current_workflow_manifest=manifest,  # type: ignore[arg-type]
            )
        else:
            analyst = self.models.load_result_verified(self.models.plans[3].model_call_plan_fingerprint)
            self.application.derive_next_experiment_proposal(
                session_fingerprint=session,
                evidence_analyst_model_result_fingerprint=analyst.model_call_result_fingerprint,
                current_workflow_manifest=manifest,  # type: ignore[arg-type]
            )

    def reconstruct_launch(self, *, tool_result_fingerprint, **_kwargs):  # type: ignore[no-untyped-def]
        assert self.child is not None
        directive = self.application.load_decision_by_session_ordinal_verified(
            self.context.session.session_fingerprint, 1
        )
        self.launches.reconstruct_launch_record(
            session_fingerprint=self.context.session.session_fingerprint,
            agent_decision_fingerprint=directive.decision_fingerprint,
            tool_call_result_fingerprint=tool_result_fingerprint,
            child_search_experiment_fingerprint=self.child.experiment_fingerprint,
            current_workflow_manifest=self.fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
        )

    def _model_references(self, role: str):  # type: ignore[no-untyped-def]
        brief = ref("AGENT_RESEARCH_BRIEF", self.context.research_brief.research_brief_fingerprint)
        if role == "RESEARCH_PLANNER":
            return (brief,)
        catalog = self.tools.load_result_verified(self.tools.plans[0].tool_call_plan_fingerprint)
        if role == "SEARCH_ROUTER":
            return (brief, ref("AGENT_TOOL_CALL_RESULT", catalog.tool_call_result_fingerprint))
        if role == "FACTOR_DESIGNER":
            router = self.models.load_result_verified(self.models.plans[1].model_call_plan_fingerprint)
            return (
                brief,
                ref("AGENT_TOOL_CALL_RESULT", catalog.tool_call_result_fingerprint),
                ref("AGENT_MODEL_CALL_RESULT", router.model_call_result_fingerprint),
            )
        return self.terminal_path, self.research_result, self.statistics

    def _tool_owner(self, tool_class: OnlyAgentToolClass) -> OnlyAgentContextReferenceV1:
        if tool_class is OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY:
            return ref("CATALOG_GENERATION", self.context.research_brief.catalog_generation_fingerprint)
        if tool_class is OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE:
            return ref("RESEARCH_DEFINITION", "2" * 64)
        if tool_class is OnlyAgentToolClass.RESEARCH_RUN_SUBMIT:
            return self.run
        if tool_class is OnlyAgentToolClass.RESEARCH_RUN_QUERY:
            return self.run
        if tool_class is OnlyAgentToolClass.SEARCH_QUERY:
            assert self.child is not None
            return ref("SEARCH_EXPERIMENT", self.child.experiment_fingerprint)
        if tool_class is OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY:
            return self.research_result
        assert self.child is not None
        return ref("SEARCH_EXPERIMENT", self.child.experiment_fingerprint)

    def _proposal(self) -> OnlyAgentNextExperimentProposalV1:
        return OnlyAgentNextExperimentProposalV1(
            OnlyAgentEvaluationPathKind.CHILD_SEARCH
            if self.child is not None
            else OnlyAgentEvaluationPathKind.DIRECT_REUSE_RESEARCH,
            self.terminal_path,
            (self.research_result,),
            (self.statistics,),
            (
                OnlyAgentEvidenceObservationV1(
                    OnlyAgentEvidenceObservationCodeV1.FOLLOW_UP_RECOMMENDED,
                    (self.statistics,),
                ),
            ),
            OnlyAgentFollowUpBriefDeltaV1("refine", "bounded evidence", ("narrow scope",)),
        )


class NoOpDriverCoordinator:
    @contextmanager
    def acquire(self, _session: str):  # type: ignore[no-untyped-def]
        yield


class DurableAdvancingSearchStates:
    """Durable owning-Authority stand-in whose state changes only after Product effects."""

    def __init__(self, root: Path, child_fingerprint: str, branch: OnlyAgentRouterAction) -> None:
        self._path = root / "search-authority.json"
        self.child_fingerprint = child_fingerprint
        self.branch = branch
        self.completed_operations = (
            json.loads(self._path.read_text(encoding="utf-8"))["completed_operations"] if self._path.is_file() else 0
        )

    def record_completed_operation(self) -> None:
        self.completed_operations += 1
        self._path.write_text(
            json.dumps({"completed_operations": self.completed_operations}),
            encoding="utf-8",
        )

    def load_search_state_verified(self, child_fingerprint: str):  # type: ignore[no-untyped-def]
        assert child_fingerprint == self.child_fingerprint
        symbolic = self.branch is OnlyAgentRouterAction.SYMBOLIC_SEARCH
        operations = (
            (
                OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
                OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE,
            )
            if symbolic
            else (
                OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION,
                OnlySearchBoundedOperationV1.RECONCILE_OPEN_PARAMETER_BATCH,
            )
        )
        terminal_kind = "NON_TERMINAL" if self.completed_operations < 2 else "TERMINAL_STOP"
        terminal_payload = (
            {
                "selected_anchor_iteration_result_fingerprint": "5" * 64,
                "ordered_input_iteration_result_fingerprints": ("5" * 64,),
            }
            if not symbolic
            else {"terminal": self.completed_operations >= 2}
        )
        terminal = SimpleNamespace(
            experiment_fingerprint=self.child_fingerprint,
            method=SimpleNamespace(value="SYMBOLIC" if symbolic else "PARAMETER"),
            terminal_kind=SimpleNamespace(value=terminal_kind),
            terminal_fact=SimpleNamespace(
                to_dict=lambda: terminal_payload,
                terminal_fingerprint="6" * 64,
            ),
            stop_reason=None if self.completed_operations < 2 else "SEARCH_SPACE_EXHAUSTED",
        )
        return SimpleNamespace(
            terminal=terminal,
            expected_state=SimpleNamespace(
                ordered_plan_states=(SimpleNamespace(result_fingerprint="5" * 64),),
                to_dict=lambda: {
                    "schema_version": 1,
                    "completed_operations": self.completed_operations,
                },
            ),
            next_bounded_operation=(operations[self.completed_operations] if self.completed_operations < 2 else None),
        )


def test_fresh_process_recovery_builder_reconstructs_a_complete_new_object_graph(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fresh-process"
    root.mkdir()
    graph_a = BranchDriverMaterializer(root, OnlyAgentRouterAction.REUSE_EXISTING)

    graph_b = BranchDriverMaterializer.reopen(root, OnlyAgentRouterAction.REUSE_EXISTING)

    assert graph_b is not graph_a
    assert graph_b.context is not graph_a.context
    assert graph_b.models is not graph_a.models
    assert graph_b.tools is not graph_a.tools
    assert graph_b.application is not graph_a.application
    assert graph_b.launches is not graph_a.launches


@pytest.mark.parametrize("case", ("C14", "C15"))
def test_c14_c15_fresh_object_graphs_fail_closed_without_external_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    root = tmp_path / case.lower()
    root.mkdir()
    graph_a = BranchDriverMaterializer(root, OnlyAgentRouterAction.REUSE_EXISTING)
    if case == "C15":
        corrupt_plan, corrupt_result = tool_occurrence(
            graph_a.context,
            ordinal=0,
            decision="d" * 64,
            tool_class=OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
            owner=ref(
                "CATALOG_GENERATION",
                graph_a.context.research_brief.catalog_generation_fingerprint,
            ),
        )
        graph_a.tools.add(corrupt_plan, corrupt_result)

    graph_b = BranchDriverMaterializer.reopen(root, OnlyAgentRouterAction.REUSE_EXISTING)
    reducer = OnlyAgentSessionReducerV1(
        sessions=Sessions(graph_b.context),
        models=graph_b.models,
        tools=graph_b.tools,
        decision_service=graph_b.application,
        decision_store=graph_b.decisions,
        launch_service=graph_b.launches,
    )
    io_calls: list[str] = []
    monkeypatch.setattr(
        driver_module,
        "execute_external_model_occurrence",
        lambda **_kwargs: io_calls.append("model"),
    )
    monkeypatch.setattr(
        driver_module,
        "execute_external_tool_occurrence",
        lambda **_kwargs: io_calls.append("tool"),
    )
    session = graph_b.context.session.session_fingerprint
    if case == "C14":
        monkeypatch.setattr(
            driver_module,
            "execute_after_runtime_admission",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OnlyAgentContextError("AGENT_WORKFLOW_RUNTIME_MISMATCH", session)
            ),
        )
        driver = OnlyAgentSessionDriverV1(
            reducer=reducer,
            sessions=Sessions(graph_b.context),
            materializer=graph_b,  # type: ignore[arg-type]
            model_occurrences=graph_b.models,  # type: ignore[arg-type]
            tool_occurrences=graph_b.tools,  # type: ignore[arg-type]
            model_adapter=object(),  # type: ignore[arg-type]
            product_adapter=object(),  # type: ignore[arg-type]
            coordination=NoOpDriverCoordinator(),  # type: ignore[arg-type]
        )
        with pytest.raises(OnlyAgentContextError, match="AGENT_WORKFLOW_RUNTIME_MISMATCH"):
            driver.advance_once(session)
    else:
        with pytest.raises(OnlyAgentContextError, match="AGENT_HISTORY_CONTRADICTORY"):
            reducer.derive(session)

    reopened = BranchDriverMaterializer.reopen(root, OnlyAgentRouterAction.REUSE_EXISTING)
    assert reopened.models.budget_consumed(session) == 0
    assert reopened.decisions.contiguous_count(session) == 0
    assert not reopened.launches.launch_exists(session)
    assert io_calls == []


@pytest.mark.parametrize(
    ("branch", "expected_status", "expected_models", "expected_tools", "expected_launches"),
    (
        (OnlyAgentRouterAction.CAPABILITY_GAP, OnlyAgentDerivedSessionStatus.CAPABILITY_GAP, 2, 1, 0),
        (OnlyAgentRouterAction.REUSE_EXISTING, OnlyAgentDerivedSessionStatus.COMPLETE, 4, 5, 0),
        (OnlyAgentRouterAction.SYMBOLIC_SEARCH, OnlyAgentDerivedSessionStatus.COMPLETE, 4, 6, 1),
        (OnlyAgentRouterAction.PARAMETER_SEARCH, OnlyAgentDerivedSessionStatus.COMPLETE, 4, 6, 1),
    ),
)
def test_all_four_branches_advance_by_fresh_one_step_drivers_with_exact_fact_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    branch: OnlyAgentRouterAction,
    expected_status: OnlyAgentDerivedSessionStatus,
    expected_models: int,
    expected_tools: int,
    expected_launches: int,
) -> None:
    root = tmp_path / branch.value.lower()
    root.mkdir()
    materializer = BranchDriverMaterializer(root, branch)
    session = materializer.context.session.session_fingerprint
    completed_run = SimpleNamespace(state=SimpleNamespace(value="COMPLETED"), research_result_fingerprint="7" * 64)
    research_states = SimpleNamespace(load_research_run_verified=lambda _reference: completed_run)
    manifest = SimpleNamespace(implementation_fingerprint="4" * 64, source_revision="5" * 40)
    permit = SimpleNamespace(historical_workflow_resource_fingerprint="6" * 64)
    monkeypatch.setattr(driver_module, "build_current_agent_workflow_implementation_manifest", lambda: manifest)
    monkeypatch.setattr(driver_module, "assert_runtime_execution_permit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        driver_module,
        "execute_after_runtime_admission",
        lambda _session, _reader, continuation: continuation(permit),
    )
    monkeypatch.setattr(
        driver_module,
        "execute_external_model_occurrence",
        lambda **kwargs: materializer.models.add(*kwargs["prepared"]),
    )

    def execute_tool(**kwargs):  # type: ignore[no-untyped-def]
        plan, result = kwargs["prepared"]
        materializer.tools.add(plan, result)
        if search_states is not None and plan.operation_identity in {
            OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
            OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE,
            OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION,
            OnlySearchBoundedOperationV1.RECONCILE_OPEN_PARAMETER_BATCH,
        }:
            search_states.record_completed_operation()

    monkeypatch.setattr(driver_module, "execute_external_tool_occurrence", execute_tool)

    action_trace: list[OnlyAgentNextActionKind] = []
    for _ in range(20):
        materializer = BranchDriverMaterializer.reopen(root, branch)
        search_states = (
            DurableAdvancingSearchStates(root, materializer.child.experiment_fingerprint, branch)
            if materializer.child is not None
            else None
        )
        reducer = OnlyAgentSessionReducerV1(
            sessions=Sessions(materializer.context),
            models=materializer.models,
            tools=materializer.tools,
            decision_service=materializer.application,
            decision_store=OnlyJsonAgentDecisionStore(root),
            launch_service=materializer.launches,
            search_states=search_states,
            research_states=research_states if branch is OnlyAgentRouterAction.REUSE_EXISTING else None,
        )
        inspected = reducer.derive(session)
        if inspected.next_action is not None:
            action_trace.append(inspected.next_action.action_kind)
        state = OnlyAgentSessionDriverV1(
            reducer=reducer,
            sessions=Sessions(materializer.context),
            materializer=materializer,  # type: ignore[arg-type]
            model_occurrences=materializer.models,  # type: ignore[arg-type]
            tool_occurrences=materializer.tools,  # type: ignore[arg-type]
            model_adapter=object(),  # type: ignore[arg-type]
            product_adapter=object(),  # type: ignore[arg-type]
            coordination=NoOpDriverCoordinator(),  # type: ignore[arg-type]
        ).advance_once(session)
        if state.status is not OnlyAgentDerivedSessionStatus.ACTIVE:
            break
    else:
        raise AssertionError("branch did not reach its bounded terminal state")

    expected_decisions = 2 if branch is OnlyAgentRouterAction.CAPABILITY_GAP else 3
    expected_commands = (
        0
        if branch is OnlyAgentRouterAction.CAPABILITY_GAP
        else 1
        if branch is OnlyAgentRouterAction.REUSE_EXISTING
        else 3
    )
    assert state.status is expected_status, (
        action_trace,
        [plan.operation_identity for plan in materializer.tools.plans],
    )
    assert len(materializer.models.plans) == len(materializer.models.results) == expected_models
    assert len(materializer.tools.plans) == len(materializer.tools.results) == expected_tools
    assert materializer.decisions.contiguous_count(session) == expected_decisions
    assert int(materializer.launches.launch_exists(session)) == expected_launches
    assert int(materializer.child is not None) == expected_launches
    command_ids = tuple(
        plan.product_command_id_or_idempotency_key
        for plan in materializer.tools.plans
        if plan.product_command_id_or_idempotency_key is not None
    )
    assert len(command_ids) == expected_commands
    assert len(set(command_ids)) == len(command_ids)
    assert action_trace.count(OnlyAgentNextActionKind.DERIVE_DECISION) == expected_decisions
    assert action_trace[0] is OnlyAgentNextActionKind.PREPARE_MODEL_CALL
    if expected_launches:
        assert action_trace.count(OnlyAgentNextActionKind.RECONSTRUCT_LAUNCH_RECORD) == 1
        assert OnlyAgentNextActionKind.PREPARE_AUTHORITY_TOOL_CALL in action_trace
        assert OnlyAgentNextActionKind.PREPARE_NEW_TOOL_OBSERVATION in action_trace
    if branch is OnlyAgentRouterAction.REUSE_EXISTING:
        assert OnlyAgentNextActionKind.PREPARE_NEW_TOOL_OBSERVATION in action_trace
