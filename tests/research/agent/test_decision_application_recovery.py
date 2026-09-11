from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

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
    OnlyAgentDecisionKind,
    OnlyAgentDecisionV1,
    OnlyAgentDerivedSessionStatus,
    OnlyAgentEvaluationContextReferenceV1,
    OnlyAgentEvaluationPathKind,
    OnlyAgentEvidenceObservationCodeV1,
    OnlyAgentEvidenceObservationV1,
    OnlyAgentExperimentLaunchRecordV1,
    OnlyAgentExperimentLaunchServiceV1,
    OnlyAgentFollowUpBriefDeltaV1,
    OnlyAgentModelCallOutcome,
    OnlyAgentModelCallPlanV1,
    OnlyAgentModelCallResultV1,
    OnlyAgentModelSettingBindingV1,
    OnlyAgentModelSettingState,
    OnlyAgentNextActionKind,
    OnlyAgentNextExperimentProposalV1,
    OnlyAgentObservedResponseStorageKind,
    OnlyAgentParameterSearchDirectiveV1,
    OnlyAgentProductOperationContractV1,
    OnlyAgentProductRequestSemanticProjectionV1,
    OnlyAgentResearchPlanV1,
    OnlyAgentReuseDirectiveV1,
    OnlyAgentRolePolicyPayloadV1,
    OnlyAgentRouterAction,
    OnlyAgentSearchAuthorityViewV1,
    OnlyAgentSearchDirectiveV1,
    OnlyAgentSearchMethod,
    OnlyAgentSessionManifestV1,
    OnlyAgentSessionReducerV1,
    OnlyAgentSymbolicSearchDirectiveV1,
    OnlyAgentToolCallOutcome,
    OnlyAgentToolCallPlanV1,
    OnlyAgentToolCallResultV1,
    OnlyAgentToolClass,
    OnlyAgentToolOccurrenceServiceV1,
    OnlyAgentToolRecoveryClass,
    OnlyVerifiedAgentDecisionContextV1,
)
from onlyalpha.research.agent.decision_store import (
    OnlyJsonAgentDecisionStore,
    OnlyJsonAgentExperimentLaunchStore,
)
from onlyalpha.research.agent.occurrence_store import OnlyJsonAgentToolOccurrenceStore
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
    def __init__(self, exact: tuple[OnlyAgentContextReferenceV1, ...]) -> None:
        self._exact = exact
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
        request = kwargs["canonical_validated_request"]
        return OnlyAgentProductRequestSemanticProjectionV1(
            kwargs["operation_identity"],
            {
                "method": "SYMBOLIC",
                "hypothesis": request["hypothesis"],
                "search_space_fingerprint": self._exact[0].reference_fingerprint,
                "evaluation_fingerprint": self._exact[1].reference_fingerprint,
                "algorithm_fingerprint": self._exact[2].reference_fingerprint,
                "search_budget_fingerprint": self._exact[3].reference_fingerprint,
                "catalog_generation_fingerprint": self._exact[4].reference_fingerprint,
                "dataset_snapshot_fingerprint": self._exact[5].reference_fingerprint,
                "workflow_binding": {"workflow_id": "SYMBOLIC_RESEARCH"},
                "decision_engine_binding": {"mode": "DETERMINISTIC"},
                "parent_experiment_fingerprint": None,
            },
        )

    def verify_response_binding(self, plan, response, references):  # type: ignore[no-untyped-def]
        del plan, response, references


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
    def __init__(self, query: OnlyResearchRunQueryService, run_id) -> None:  # type: ignore[no-untyped-def]
        self.query = query
        self.run_id = run_id

    def load_research_run_verified(self, _reference):  # type: ignore[no-untyped-def]
        return self.query.get_run(self.run_id)


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
    owner: OnlyAgentContextReferenceV1,
) -> tuple[OnlyAgentToolCallPlanV1, OnlyAgentToolCallResultV1]:
    plan = OnlyAgentToolCallPlanV1(
        context.session.session_fingerprint,
        ordinal,
        decision,
        tool_class,
        2,
        "d" * 64,
        f"{tool_class.value.lower()}.v1",
        {"id": owner.reference_fingerprint},
        exact_identity_inputs=(owner,),
        tool_policy_fingerprint=context.session.tool_policy_fingerprint,
    )
    response = {"identity": owner.reference_fingerprint}
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
        sessions=Sessions(context), models=models, tools=tools, references=References(), store=store
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
        designer_plan, designer_result = model_occurrence(
            fixture,
            context,
            ordinal=2,
            role="FACTOR_DESIGNER",
            role_fingerprint=context.session.ordered_role_policy_fingerprints[2],
            refs=(brief_ref, catalog_ref, ref("AGENT_MODEL_CALL_RESULT", router_result.model_call_result_fingerprint)),
            output={"action_payload": action_payload(action, context).to_dict()},
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
    branch = (
        (OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE, ref("RESEARCH_DEFINITION", "1" * 64)),
        (OnlyAgentToolClass.RESEARCH_RUN_SUBMIT, ref("RESEARCH_RUN", "2" * 64)),
        (OnlyAgentToolClass.RESEARCH_RUN_QUERY, ref("RESEARCH_RUN_RESULT", "3" * 64)),
        (OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY, ref("RESEARCH_RESULT", "4" * 64)),
    )
    for ordinal, (tool_class, owner) in enumerate(branch, start=1):
        plan, result = tool_occurrence(
            context,
            ordinal=ordinal,
            decision=directive.decision_fingerprint,
            tool_class=tool_class,
            owner=owner,
        )
        if tool_class is OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY:
            result = replace(
                result,
                owning_authority_references=(owner, statistics),
                tool_call_result_fingerprint="",
            )
        tools.add(plan, result)
    proposal = OnlyAgentNextExperimentProposalV1(
        OnlyAgentEvaluationPathKind.DIRECT_REUSE_RESEARCH,
        branch[2][1],
        (branch[3][1],),
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
    with pytest.raises(OnlyAgentContextError, match="AGENT_HISTORY_CONTRADICTORY"):
        reducer.derive(context.session.session_fingerprint)


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
    )
    semantics = {
        "method": "SYMBOLIC",
        "hypothesis": context.research_brief.hypothesis.to_dict(),
        "search_space_fingerprint": exact[0].reference_fingerprint,
        "evaluation_fingerprint": exact[1].reference_fingerprint,
        "algorithm_fingerprint": exact[2].reference_fingerprint,
        "search_budget_fingerprint": exact[3].reference_fingerprint,
        "catalog_generation_fingerprint": exact[4].reference_fingerprint,
        "dataset_snapshot_fingerprint": exact[5].reference_fingerprint,
        "workflow_binding": {"workflow_id": "SYMBOLIC_RESEARCH"},
        "decision_engine_binding": {"mode": "DETERMINISTIC"},
        "parent_experiment_fingerprint": None,
    }
    application.verify_historical_tool_intent(
        decision_fingerprint=decision.decision_fingerprint,
        tool_class=OnlyAgentToolClass.SYMBOLIC_SEARCH,
        operation_identity="symbolic_search.v1",
        semantic_projection=OnlyAgentProductRequestSemanticProjectionV1("symbolic_search.v1", semantics),
        exact_identity_inputs=exact,
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
    )
    contracts = SemanticProductContracts(exact)
    occurrence = OnlyAgentToolOccurrenceServiceV1(
        sessions=Sessions(context),
        decisions=application,
        product_contracts=contracts,
        references=References(),
        response_references=References(),
        store=OnlyJsonAgentToolOccurrenceStore(tmp_path / "semantic-tool"),
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
    assert occurrence.budget_consumed(context.session.session_fingerprint) == 1


def test_reuse_mutable_observation_loss_allows_new_plan_and_later_result(tmp_path: Path) -> None:
    fixture, context, models, tools, store, application = service(tmp_path)
    directive, _ = derive_directive(fixture, context, models, tools, application, OnlyAgentRouterAction.REUSE_EXISTING)
    branch = (
        (OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE, ref("RESEARCH_DEFINITION", "1" * 64)),
        (OnlyAgentToolClass.RESEARCH_RUN_SUBMIT, ref("RESEARCH_RUN", "2" * 64)),
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
    run_store = ResearchRunStore(
        queued_research_run().transition(OnlyResearchRunState.RUNNING, at=RUN_NOW + timedelta(seconds=1))
    )
    run_states = ProductResearchStates(OnlyResearchRunQueryService(run_store), run_store.run.run_id)
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
    terminal_result = replace(
        terminal_result,
        owning_authority_references=(terminal_path,),
        tool_call_result_fingerprint="",
    )
    tools.add(terminal_plan, terminal_result)
    observed = reducer.derive(context.session.session_fingerprint)
    assert observed.next_action is not None
    assert observed.next_action.tool_class is OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY
    statistics = ref("RESEARCH_STATISTICS", "5" * 64)
    evidence_plan, evidence_result = tool_occurrence(
        context,
        ordinal=6,
        decision=directive.decision_fingerprint,
        tool_class=OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY,
        owner=terminal_path,
    )
    research_result = ref("RESEARCH_RESULT", "4" * 64)
    evidence_result = replace(
        evidence_result,
        owning_authority_references=(research_result, statistics),
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
