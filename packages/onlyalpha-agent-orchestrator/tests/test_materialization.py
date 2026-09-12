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

    def load_evidence_query_reference_verified(self, _session):  # type: ignore[no-untyped-def]
        return _ref("RESEARCH_RESULT", "e")

    def load_evidence_model_context_verified(self, _session):  # type: ignore[no-untyped-def]
        return (_ref("RESEARCH_RESULT", "e"), _ref("RESEARCH_STATISTICS", "f"))


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


def _materializer(*, sessions=None, decisions=None, models=None, launches=None, search_states=None):  # type: ignore[no-untyped-def]
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
        tools=object(),
        decisions=decisions or object(),
        launches=launches or object(),
        invocation_bindings=OnlyStaticAgentModelInvocationBindingReaderV1((binding,)),
        product_contracts=object(),
        semantic_inputs=_Inputs(),
        runtime_generations=_RuntimeGeneration(),
        search_states=search_states,
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
        return SimpleNamespace(structured_payload=self.directive, decision_fingerprint="a" * 64)


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
    intent = _materializer(launches=launches, search_states=states)._search_advance_intent(SESSION, action)
    assert intent.operation_identity == "advance_symbolic_search_experiment_v2"
    assert intent.canonical_request["expected_state"] == expected.to_dict()
    assert intent.canonical_request["operation"] == operation.value
    assert intent.product_command_id == str(COMMAND_ID)
    assert tuple(item.reference_kind for item in intent.exact_identity_inputs) == (
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
