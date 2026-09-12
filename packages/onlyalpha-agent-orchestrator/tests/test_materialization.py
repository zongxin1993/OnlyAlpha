from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from onlyalpha_agent_orchestrator.bindings import (
    OnlyAgentModelInvocationBindingV1,
    OnlyStaticAgentModelInvocationBindingReaderV1,
)
from onlyalpha_agent_orchestrator.materialization import OnlyAgentWorkflowActionMaterializerV1

from onlyalpha.research.agent import (
    OnlyAgentBudgetV1,
    OnlyAgentContextReferenceV1,
    OnlyAgentDecisionKind,
    OnlyAgentExactAuthorityReferenceV2,
    OnlyAgentModelSettingBindingV1,
    OnlyAgentModelSettingState,
    OnlyAgentNextActionKind,
    OnlyAgentNextActionV1,
    OnlyAgentParameterSearchDirectiveV1,
    OnlyAgentReferenceLocatorKind,
    OnlyAgentReuseDirectiveV1,
    OnlyAgentRolePolicyPayloadV1,
    OnlyAgentSearchDirectiveV1,
    OnlyAgentStructuredHypothesisV1,
    OnlyAgentSymbolicSearchDirectiveV1,
    OnlyAgentToolCallOutcome,
    OnlyAgentToolClass,
)
from onlyalpha.research.agent.decision import OnlyAgentRouterAction

SESSION = "a" * 64
COMMAND_ID = uuid.UUID("12345678-1234-4234-9234-123456789abc")


def _ref(kind: str, character: str) -> OnlyAgentContextReferenceV1:
    return OnlyAgentContextReferenceV1(kind, 1, character * 64)


class _Inputs:
    def load_semantic_payload_verified(self, reference):  # type: ignore[no-untyped-def]
        return {"exact_reference": reference.reference_fingerprint}


class _RuntimeGeneration:
    def read_current_new_work_runtime_generation_fingerprint(self) -> str:
        return "9" * 64


def _brief():  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        hypothesis=OnlyAgentStructuredHypothesisV1(
            "hypothesis",
            "statement",
            "rationale",
            "relationship",
            ("assumption",),
            ("falsification",),
        ),
        catalog_generation_fingerprint="1" * 64,
        dataset_snapshot_fingerprint="2" * 64,
        agent_budget=OnlyAgentBudgetV1(4, 20),
        research_brief_fingerprint="3" * 64,
    )


def _directive(parameter: bool = False) -> OnlyAgentSearchDirectiveV1:
    if parameter:
        payload = OnlyAgentParameterSearchDirectiveV1(
            _ref("PARAMETER_SEARCH_SPACE", "4"),
            _ref("RESEARCH_EVALUATION", "5"),
            _ref("SEARCH_POLICY", "6"),
            _ref("SEARCH_ALGORITHM", "7"),
            _ref("SEARCH_BUDGET", "8"),
        )
        action = OnlyAgentRouterAction.PARAMETER_SEARCH
    else:
        payload = OnlyAgentSymbolicSearchDirectiveV1(
            _ref("SYMBOLIC_SEARCH_SPACE", "4"),
            _ref("RESEARCH_EVALUATION", "5"),
            _ref("SEARCH_ALGORITHM", "7"),
            _ref("SEARCH_BUDGET", "8"),
        )
        action = OnlyAgentRouterAction.SYMBOLIC_SEARCH
    return OnlyAgentSearchDirectiveV1(action, "0" * 64, payload)


def _materializer(  # type: ignore[no-untyped-def]
    *,
    sessions=None,
    decisions=None,
    models=None,
    tools=None,
    launches=None,
    search_states=None,
    research_states=None,
    semantic_inputs=None,
    product_contracts=None,
    invocation_bindings=None,
):
    binding = OnlyAgentModelInvocationBindingV1(
        "RESEARCH_PLANNER",
        "provider",
        "model",
        "version",
        "b" * 64,
        "c" * 64,
        "d" * 64,
        (OnlyAgentModelSettingBindingV1("temperature", OnlyAgentModelSettingState.VALUE, 0),),
    )
    default_sessions = SimpleNamespace(
        load_session_manifest_verified=lambda _session: SimpleNamespace(research_brief=_brief())
    )
    return OnlyAgentWorkflowActionMaterializerV1(
        sessions=sessions or default_sessions,
        models=models or object(),
        tools=tools or object(),
        decisions=decisions or object(),
        launches=launches or object(),
        invocation_bindings=invocation_bindings or OnlyStaticAgentModelInvocationBindingReaderV1((binding,)),
        product_contracts=product_contracts or object(),
        semantic_inputs=semantic_inputs or _Inputs(),
        runtime_generations=_RuntimeGeneration(),
        search_states=search_states,
        research_states=research_states,
        product_api_contract_fingerprint="f" * 64,
        uuid_factory=lambda: COMMAND_ID,
    )


@pytest.mark.parametrize("parameter", (False, True))
def test_search_submit_materialization_binds_exact_directive_and_current_runtime_generation(
    parameter: bool,
) -> None:
    context = SimpleNamespace(research_brief=_brief())
    directive = _directive(parameter)
    intent = _materializer()._search_submit_intent(context, directive)
    request = intent.canonical_request
    assert intent.operation_identity == (
        "submit_parameter_search_experiment_v2" if parameter else "submit_symbolic_search_experiment_v2"
    )
    assert request["catalog_generation_fingerprint"] == "1" * 64
    assert request["dataset_snapshot_fingerprint"] == "2" * 64
    assert request["runtime_generation_fingerprint"] == "9" * 64
    assert request["search_space"] == {"exact_reference": "4" * 64}
    assert request["evaluation_contract"] == {"exact_reference": "5" * 64}
    assert request["algorithm_manifest"] == {"exact_reference": "7" * 64}
    assert request["search_budget"] == {"exact_reference": "8" * 64}
    assert ("search_policy" in request) is parameter
    assert intent.product_command_id == str(COMMAND_ID)
    assert {item.reference_kind for item in intent.exact_identity_inputs} >= {
        "CATALOG_GENERATION",
        "DATASET_SNAPSHOT",
        "RUNTIME_GENERATION",
    }


def test_exact_catalog_materialization_uses_brief_generation() -> None:
    sessions = SimpleNamespace(load_session_manifest_verified=lambda _session: SimpleNamespace(research_brief=_brief()))
    action = OnlyAgentNextActionV1(
        OnlyAgentNextActionKind.PREPARE_TOOL_CALL,
        tool_class=OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
    )
    intent = _materializer(sessions=sessions)._materialize_tool_intent(SESSION, action)
    assert intent.canonical_request == {"catalog_generation_fingerprint": "1" * 64}
    assert intent.product_command_id is None


class _Decisions:
    def __init__(self, directive: OnlyAgentSearchDirectiveV1) -> None:
        self.directive = directive

    def load_decision_by_session_ordinal_verified(self, _session, ordinal):  # type: ignore[no-untyped-def]
        assert ordinal == 1
        return SimpleNamespace(
            agent_session_fingerprint=SESSION,
            decision_kind=OnlyAgentDecisionKind.SEARCH_DIRECTIVE,
            structured_payload=self.directive,
            decision_fingerprint="a" * 64,
        )


class _PriorTools:
    def __init__(self, tool_class: OnlyAgentToolClass, result: object) -> None:
        self.plan = SimpleNamespace(tool_class=tool_class, tool_call_plan_fingerprint="b" * 64)
        self.result = result

    def budget_consumed(self, _session):  # type: ignore[no-untyped-def]
        return 1

    def load_plan_by_session_ordinal_verified(self, _session, ordinal):  # type: ignore[no-untyped-def]
        assert ordinal == 0
        return self.plan

    def result_exists(self, fingerprint):  # type: ignore[no-untyped-def]
        return fingerprint == self.plan.tool_call_plan_fingerprint

    def load_result_verified(self, fingerprint):  # type: ignore[no-untyped-def]
        assert fingerprint == self.plan.tool_call_plan_fingerprint
        return self.result


def _reuse_directive() -> OnlyAgentSearchDirectiveV1:
    return OnlyAgentSearchDirectiveV1(
        OnlyAgentRouterAction.REUSE_EXISTING,
        "0" * 64,
        OnlyAgentReuseDirectiveV1((_ref("QUANT_ASSET", "1"),), _ref("RESEARCH_DEFINITION", "2")),
    )


def test_reuse_resolve_uses_exact_directive_reference_and_reused_capability_closure() -> None:
    directive = _reuse_directive()
    action = OnlyAgentNextActionV1(
        OnlyAgentNextActionKind.PREPARE_TOOL_CALL,
        tool_class=OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE,
    )
    intent = _materializer(decisions=_Decisions(directive))._materialize_tool_intent(SESSION, action)
    assert intent.operation_identity == "resolve_definition_api_v2_research_definitions_resolve_post"
    assert intent.canonical_request == {"exact_reference": "2" * 64}
    assert tuple(item.reference_kind for item in intent.exact_identity_inputs) == (
        "RESEARCH_DEFINITION",
        "QUANT_ASSET",
    )
    assert intent.product_command_id is None


def test_research_submit_uses_resolved_exact_specification_and_one_new_command_id() -> None:
    resolved = SimpleNamespace(
        canonical_validated_response={"exact_specification": {"schema_version": 2, "definition": "exact"}},
        owning_authority_references=(_ref("RESEARCH_DEFINITION", "2"),),
    )
    materializer = _materializer(decisions=_Decisions(_reuse_directive()))
    materializer._tools = _PriorTools(OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE, resolved)
    action = OnlyAgentNextActionV1(
        OnlyAgentNextActionKind.PREPARE_TOOL_CALL,
        tool_class=OnlyAgentToolClass.RESEARCH_RUN_SUBMIT,
    )
    intent = materializer._materialize_tool_intent(SESSION, action)
    assert intent.operation_identity == "submit_research_run_command_v2"
    assert intent.canonical_request == {"specification": {"schema_version": 2, "definition": "exact"}}
    assert intent.exact_identity_inputs == resolved.owning_authority_references
    assert intent.product_command_id == str(COMMAND_ID)


def test_research_observation_uses_exact_uuid4_from_successful_submit_result() -> None:
    run_id = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    run_reference = OnlyAgentExactAuthorityReferenceV2(
        "RESEARCH_RUN",
        1,
        OnlyAgentReferenceLocatorKind.UUID4,
        str(run_id),
    )
    submitted = SimpleNamespace(owning_authority_references=(run_reference,))
    materializer = _materializer(decisions=_Decisions(_reuse_directive()))
    materializer._tools = _PriorTools(OnlyAgentToolClass.RESEARCH_RUN_SUBMIT, submitted)
    action = OnlyAgentNextActionV1(
        OnlyAgentNextActionKind.PREPARE_NEW_TOOL_OBSERVATION,
        tool_class=OnlyAgentToolClass.RESEARCH_RUN_QUERY,
    )
    intent = materializer._materialize_tool_intent(SESSION, action)
    assert intent.operation_identity == "get_run_api_v2_research_runs__run_id__get"
    assert intent.canonical_request == {"run_id": str(run_id)}
    assert intent.exact_identity_inputs == (run_reference,)
    assert intent.product_command_id is None


class _EvidenceInputs:
    def __init__(self, payloads):  # type: ignore[no-untyped-def]
        self.payloads = payloads

    def load_semantic_payload_verified(self, reference):  # type: ignore[no-untyped-def]
        return self.payloads[(reference.reference_kind, reference.locator_value)]


class _EvidenceContracts:
    def response_references_verified(self, _plan, response):  # type: ignore[no-untyped-def]
        return (
            _ref("RESEARCH_RESULT", response["research_result_fingerprint"][0]),
            *(_ref("RESEARCH_STATISTICS", item["statistics_result_fingerprint"][0]) for item in response["statistics"]),
        )


class _EvidenceTools:
    def __init__(self, occurrences):  # type: ignore[no-untyped-def]
        self.occurrences = tuple(occurrences)

    def budget_consumed(self, _session):  # type: ignore[no-untyped-def]
        return len(self.occurrences)

    def load_plan_by_session_ordinal_verified(self, _session, ordinal):  # type: ignore[no-untyped-def]
        return self.occurrences[ordinal][0]

    def result_exists(self, plan_fingerprint):  # type: ignore[no-untyped-def]
        return any(
            plan.tool_call_plan_fingerprint == plan_fingerprint and result is not None
            for plan, result in self.occurrences
        )

    def load_result_verified(self, plan_fingerprint):  # type: ignore[no-untyped-def]
        return next(
            result
            for plan, result in self.occurrences
            if plan.tool_call_plan_fingerprint == plan_fingerprint and result is not None
        )

    def load_plan_verified(self, plan_fingerprint):  # type: ignore[no-untyped-def]
        return next(plan for plan, _result in self.occurrences if plan.tool_call_plan_fingerprint == plan_fingerprint)

    def load_result_by_fingerprint_verified(self, result_fingerprint):  # type: ignore[no-untyped-def]
        return next(
            result
            for _plan, result in self.occurrences
            if result is not None and result.tool_call_result_fingerprint == result_fingerprint
        )


def _evidence_plan(ordinal: int, tool_class: OnlyAgentToolClass, character: str, *, inputs=()):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        agent_session_fingerprint=SESSION,
        tool_call_ordinal=ordinal,
        tool_class=tool_class,
        operation_identity=f"operation-{ordinal}",
        exact_identity_inputs=inputs,
        authorizing_agent_decision_fingerprint="a" * 64,
        tool_call_plan_fingerprint=character * 64,
    )


def _evidence_result(plan, *, response, references, result_character="f"):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        outcome=OnlyAgentToolCallOutcome.SUCCEEDED,
        canonical_validated_response=response,
        owning_authority_references=references,
        tool_call_plan_fingerprint=plan.tool_call_plan_fingerprint,
        tool_call_result_fingerprint=result_character * 64,
    )


def test_reuse_evidence_target_and_analyst_context_are_derived_from_durable_tool_prefix() -> None:
    run = OnlyAgentExactAuthorityReferenceV2(
        "RESEARCH_RUN",
        1,
        OnlyAgentReferenceLocatorKind.UUID4,
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    research_result = _ref("RESEARCH_RESULT", "7")
    statistics = _ref("RESEARCH_STATISTICS", "8")
    observation_plan = _evidence_plan(0, OnlyAgentToolClass.RESEARCH_RUN_QUERY, "1", inputs=(run,))
    observation_result = _evidence_result(
        observation_plan,
        response={"run_id": run.locator_value, "state": "COMPLETED", "result_ref": research_result.locator_value},
        references=(run,),
    )
    evidence_plan = _evidence_plan(
        1,
        OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY,
        "2",
        inputs=(research_result,),
    )
    evidence_result = _evidence_result(
        evidence_plan,
        response={
            "research_result_fingerprint": research_result.locator_value,
            "statistics": [
                {
                    "statistics_fingerprint": "9" * 64,
                    "statistics_result_fingerprint": statistics.locator_value,
                }
            ],
        },
        references=(research_result,),
    )
    tools = _EvidenceTools(((observation_plan, observation_result), (evidence_plan, evidence_result)))
    inputs = _EvidenceInputs(
        {
            ("RESEARCH_RESULT", research_result.locator_value): {
                "statistics_results": [
                    {
                        "statistics_fingerprint": "9" * 64,
                        "statistics_result_fingerprint": statistics.locator_value,
                    }
                ]
            },
            ("RESEARCH_STATISTICS", statistics.locator_value): {
                "statistics_result_fingerprint": statistics.locator_value
            },
        }
    )
    completed_run = SimpleNamespace(
        run_id=run.locator_value,
        state=SimpleNamespace(value="COMPLETED"),
        research_result_fingerprint=research_result.locator_value,
    )
    materializer = _materializer(
        decisions=_Decisions(_reuse_directive()),
        tools=tools,
        research_states=SimpleNamespace(load_research_run_verified=lambda _reference: completed_run),
        semantic_inputs=inputs,
        product_contracts=_EvidenceContracts(),
    )

    assert materializer._derive_evidence_query_reference(SESSION) == research_result
    assert materializer._derive_evidence_model_context(SESSION) == (
        _ref("RESEARCH_RUN_RESULT", "7"),
        research_result,
        statistics,
    )


def test_evidence_analyst_context_rejects_unrelated_exact_evidence_before_model_plan() -> None:
    run = OnlyAgentExactAuthorityReferenceV2(
        "RESEARCH_RUN",
        1,
        OnlyAgentReferenceLocatorKind.UUID4,
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    result_a = _ref("RESEARCH_RESULT", "7")
    result_b = _ref("RESEARCH_RESULT", "6")
    observation_plan = _evidence_plan(0, OnlyAgentToolClass.RESEARCH_RUN_QUERY, "1", inputs=(run,))
    observation_result = _evidence_result(
        observation_plan,
        response={"run_id": run.locator_value, "state": "COMPLETED", "result_ref": result_a.locator_value},
        references=(run,),
    )
    evidence_plan = _evidence_plan(1, OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY, "2", inputs=(result_b,))
    evidence_result = _evidence_result(
        evidence_plan,
        response={
            "research_result_fingerprint": result_b.locator_value,
            "statistics": [{"statistics_fingerprint": "9" * 64, "statistics_result_fingerprint": "8" * 64}],
        },
        references=(result_b, _ref("RESEARCH_STATISTICS", "8")),
    )
    role = OnlyAgentRolePolicyPayloadV1(
        "EVIDENCE_ANALYST",
        "analyst boundary",
        ("b" * 64,),
        ("c" * 64,),
        ("d" * 64,),
        (),
        "EVIDENCE",
        "PROPOSAL",
        "RETURN_OR_FAIL_CLOSED",
    )
    context = SimpleNamespace(
        research_brief=_brief(),
        ordered_role_policy_resources=(SimpleNamespace(canonical_payload=role, resource_fingerprint="e" * 64),),
    )

    class CountingModels:
        prepare_count = 0

        def budget_consumed(self, _session):  # type: ignore[no-untyped-def]
            return 3

        def prepare_model_call(self, **_kwargs):  # type: ignore[no-untyped-def]
            self.prepare_count += 1

    models = CountingModels()
    analyst_binding = OnlyAgentModelInvocationBindingV1(
        "EVIDENCE_ANALYST",
        "provider",
        "model",
        "version",
        "b" * 64,
        "c" * 64,
        "d" * 64,
        (),
    )
    materializer = _materializer(
        sessions=SimpleNamespace(load_session_manifest_verified=lambda _session: context),
        models=models,
        decisions=_Decisions(_reuse_directive()),
        tools=_EvidenceTools(((observation_plan, observation_result), (evidence_plan, evidence_result))),
        research_states=SimpleNamespace(
            load_research_run_verified=lambda _reference: SimpleNamespace(
                run_id=run.locator_value,
                state=SimpleNamespace(value="COMPLETED"),
                research_result_fingerprint=result_a.locator_value,
            )
        ),
        semantic_inputs=_EvidenceInputs(
            {
                ("RESEARCH_RESULT", result_b.locator_value): {
                    "statistics_results": [
                        {"statistics_fingerprint": "9" * 64, "statistics_result_fingerprint": "8" * 64}
                    ]
                }
            }
        ),
        invocation_bindings=OnlyStaticAgentModelInvocationBindingReaderV1((analyst_binding,)),
    )

    with pytest.raises(Exception, match="AGENT_EVIDENCE_UNAVAILABLE"):
        materializer.prepare_model_call(
            session_fingerprint=SESSION,
            action=OnlyAgentNextActionV1(
                OnlyAgentNextActionKind.PREPARE_MODEL_CALL,
                logical_role="EVIDENCE_ANALYST",
            ),
            current_workflow_manifest=object(),  # type: ignore[arg-type]
        )
    assert models.prepare_count == 0


def test_evidence_analyst_context_requires_successful_evidence_tool_result() -> None:
    run = OnlyAgentExactAuthorityReferenceV2(
        "RESEARCH_RUN",
        1,
        OnlyAgentReferenceLocatorKind.UUID4,
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    research_result = _ref("RESEARCH_RESULT", "7")
    observation_plan = _evidence_plan(0, OnlyAgentToolClass.RESEARCH_RUN_QUERY, "1", inputs=(run,))
    observation_result = _evidence_result(
        observation_plan,
        response={"run_id": run.locator_value, "state": "COMPLETED", "result_ref": research_result.locator_value},
        references=(run,),
    )
    materializer = _materializer(
        decisions=_Decisions(_reuse_directive()),
        tools=_EvidenceTools(((observation_plan, observation_result),)),
        research_states=SimpleNamespace(
            load_research_run_verified=lambda _reference: SimpleNamespace(
                run_id=run.locator_value,
                state=SimpleNamespace(value="COMPLETED"),
                research_result_fingerprint=research_result.locator_value,
            )
        ),
    )

    with pytest.raises(Exception, match="AGENT_EVIDENCE_UNAVAILABLE"):
        materializer._derive_evidence_model_context(SESSION)


@pytest.mark.parametrize("parameter", (False, True))
def test_search_evidence_context_is_derived_through_terminal_iteration_result(
    parameter: bool,
) -> None:
    child = "a" * 64
    iteration = "b" * 64
    research_result = _ref("RESEARCH_RESULT", "7")
    statistics = _ref("RESEARCH_STATISTICS", "8")
    terminal_payload = (
        {
            "selected_anchor_iteration_result_fingerprint": iteration,
            "ordered_input_iteration_result_fingerprints": (iteration,),
        }
        if parameter
        else {"enumeration": "complete"}
    )
    terminal_fact = SimpleNamespace(
        to_dict=lambda: terminal_payload,
        feedback_decision_fingerprint="c" * 64 if parameter else None,
        enumeration_result_fingerprint="c" * 64 if not parameter else None,
    )
    terminal = SimpleNamespace(
        experiment_fingerprint=child,
        method=SimpleNamespace(value="PARAMETER" if parameter else "SYMBOLIC"),
        terminal_kind=SimpleNamespace(value="TERMINAL_STOP"),
        terminal_fact=terminal_fact,
        stop_reason="SEARCH_SPACE_EXHAUSTED",
    )
    expected = SimpleNamespace(ordered_plan_states=(SimpleNamespace(result_fingerprint=iteration),))
    terminal_response = {
        "schema_version": 1,
        "experiment_fingerprint": child,
        "method": terminal.method.value,
        "terminal_kind": terminal.terminal_kind.value,
        "terminal_fact": terminal_payload,
        "stop_reason": terminal.stop_reason,
    }
    launch_plan = _evidence_plan(
        0,
        OnlyAgentToolClass.PARAMETER_SEARCH if parameter else OnlyAgentToolClass.SYMBOLIC_SEARCH,
        "0",
    )
    launch_result = _evidence_result(
        launch_plan,
        response={"experiment_fingerprint": child},
        references=(_ref("SEARCH_EXPERIMENT", "a"),),
        result_character="d",
    )
    observation_plan = _evidence_plan(
        1,
        OnlyAgentToolClass.SEARCH_QUERY,
        "1",
        inputs=(_ref("SEARCH_EXPERIMENT", "a"),),
    )
    observation_result = _evidence_result(
        observation_plan,
        response=terminal_response,
        references=(_ref("SEARCH_EXPERIMENT", "a"),),
    )
    evidence_plan = _evidence_plan(
        2,
        OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY,
        "2",
        inputs=(research_result,),
    )
    evidence_result = _evidence_result(
        evidence_plan,
        response={
            "research_result_fingerprint": research_result.locator_value,
            "statistics": [
                {
                    "statistics_fingerprint": "9" * 64,
                    "statistics_result_fingerprint": statistics.locator_value,
                }
            ],
        },
        references=(research_result,),
    )
    launches = SimpleNamespace(
        load_launch_record_by_session_verified=lambda _session: SimpleNamespace(
            agent_decision_fingerprint="a" * 64,
            tool_call_result_fingerprint="d" * 64,
            child_search_experiment_fingerprint=child,
        )
    )
    inputs = _EvidenceInputs(
        {
            ("SEARCH_ITERATION_RESULT", iteration): {
                "research_result_reference": {"result_fingerprint": research_result.locator_value}
            },
            ("RESEARCH_STATISTICS", statistics.locator_value): {
                "statistics_result_fingerprint": statistics.locator_value
            },
        }
    )
    materializer = _materializer(
        decisions=_Decisions(_directive(parameter)),
        tools=_EvidenceTools(
            (
                (launch_plan, launch_result),
                (observation_plan, observation_result),
                (evidence_plan, evidence_result),
            )
        ),
        launches=launches,
        search_states=SimpleNamespace(
            load_search_state_verified=lambda _child: SimpleNamespace(
                terminal=terminal,
                expected_state=expected,
            )
        ),
        semantic_inputs=inputs,
        product_contracts=_EvidenceContracts(),
    )

    assert materializer._derive_evidence_query_reference(SESSION) == research_result
    assert materializer._derive_evidence_model_context(SESSION) == (
        _ref("SEARCH_TERMINAL_PROJECTION", "c"),
        research_result,
        statistics,
    )


def test_search_observation_uses_exact_child_launch_identity_and_no_command_id() -> None:
    launches = SimpleNamespace(
        load_launch_record_by_session_verified=lambda _session: SimpleNamespace(
            child_search_experiment_fingerprint="a" * 64
        )
    )
    action = OnlyAgentNextActionV1(
        OnlyAgentNextActionKind.PREPARE_NEW_TOOL_OBSERVATION,
        tool_class=OnlyAgentToolClass.SEARCH_QUERY,
    )
    intent = _materializer(decisions=_Decisions(_directive()), launches=launches)._materialize_tool_intent(
        SESSION, action
    )
    assert intent.operation_identity == "get_search_terminal_v2"
    assert intent.canonical_request == {"experiment_fingerprint": "a" * 64}
    assert tuple(item.reference_kind for item in intent.exact_identity_inputs) == ("SEARCH_EXPERIMENT",)
    assert intent.product_command_id is None


def test_search_advance_binds_exact_current_expected_state_and_one_new_command_id() -> None:
    operation = SimpleNamespace(value="ADVANCE_ONE_SYMBOLIC_OCCURRENCE")
    method = SimpleNamespace(value="SYMBOLIC")
    expected = SimpleNamespace(to_dict=lambda: {"schema_version": 1, "experiment_fingerprint": "a" * 64})
    authority = SimpleNamespace(
        next_bounded_operation=operation,
        expected_state=expected,
        terminal=SimpleNamespace(method=method),
    )
    launches = SimpleNamespace(
        load_launch_record_by_session_verified=lambda _session: SimpleNamespace(
            child_search_experiment_fingerprint="a" * 64
        )
    )
    states = SimpleNamespace(load_search_state_verified=lambda _fingerprint: authority)
    action = OnlyAgentNextActionV1(
        OnlyAgentNextActionKind.PREPARE_AUTHORITY_TOOL_CALL,
        tool_class=OnlyAgentToolClass.SYMBOLIC_SEARCH,
        operation_identity=operation.value,
    )

    class CapturingOccurrenceService:
        def budget_consumed(self, _session):  # type: ignore[no-untyped-def]
            return 2

        def prepare_tool_call(self, **kwargs):  # type: ignore[no-untyped-def]
            return kwargs

    prepared = _materializer(
        decisions=_Decisions(_directive()),
        tools=CapturingOccurrenceService(),
        launches=launches,
        search_states=states,
    ).prepare_tool_call(
        session_fingerprint=SESSION,
        action=action,
        current_workflow_manifest=object(),  # type: ignore[arg-type]
    )
    assert prepared["operation_identity"] == "advance_symbolic_search_experiment_v2"
    assert prepared["canonical_request"]["expected_state"] == expected.to_dict()
    assert prepared["canonical_request"]["operation"] == operation.value
    assert prepared["product_command_id_or_idempotency_key"] == str(COMMAND_ID)
    assert tuple(item.reference_kind for item in prepared["exact_identity_inputs"]) == (
        "SEARCH_EXPERIMENT",
        "SEARCH_EXPECTED_STATE",
    )


def test_model_plan_materialization_copies_explicit_binding_not_role_allowlist_order() -> None:
    role = OnlyAgentRolePolicyPayloadV1(
        "RESEARCH_PLANNER",
        "planner boundary",
        ("a" * 64, "b" * 64),
        ("1" * 64, "c" * 64),
        ("2" * 64, "d" * 64),
        (OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,),
        "BRIEF",
        "PLAN",
        "RETURN_OR_FAIL_CLOSED",
    )
    context = SimpleNamespace(
        research_brief=_brief(),
        ordered_role_policy_resources=(SimpleNamespace(canonical_payload=role, resource_fingerprint="e" * 64),),
    )
    sessions = SimpleNamespace(load_session_manifest_verified=lambda _session: context)

    class Models:
        def budget_consumed(self, _session):  # type: ignore[no-untyped-def]
            return 0

        def prepare_model_call(self, **kwargs):  # type: ignore[no-untyped-def]
            self.kwargs = kwargs
            return kwargs

    models = Models()
    action = OnlyAgentNextActionV1(OnlyAgentNextActionKind.PREPARE_MODEL_CALL, logical_role="RESEARCH_PLANNER")
    prepared = _materializer(sessions=sessions, models=models).prepare_model_call(
        session_fingerprint=SESSION,
        action=action,
        current_workflow_manifest=object(),  # type: ignore[arg-type]
    )
    assert prepared["prompt_template_fingerprint"] == "b" * 64  # type: ignore[index]
    assert prepared["structured_output_schema_fingerprint"] == "c" * 64  # type: ignore[index]
    assert prepared["model_execution_policy_fingerprint"] == "d" * 64  # type: ignore[index]
    assert prepared["provider_id"] == "provider"  # type: ignore[index]
    assert prepared["model_id"] == "model"  # type: ignore[index]
    assert prepared["model_version"] == "version"  # type: ignore[index]
