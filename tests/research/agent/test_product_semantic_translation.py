from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from onlyalpha.application.search_product import (
    OnlySubmitParameterSearchExperimentV2,
    OnlySubmitSymbolicSearchExperimentV2,
    only_project_search_product_request_semantics,
)
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.agent import (
    OnlyAgentContextError,
    OnlyAgentContextReferenceV1,
    OnlyAgentDecisionApplicationServiceV1,
    OnlyAgentEvaluationContextReferenceV1,
    OnlyAgentParameterSearchDirectiveV1,
    OnlyAgentProductOperationContractV1,
    OnlyAgentProductRequestSemanticProjectionV1,
    OnlyAgentRouterAction,
    OnlyAgentSearchDirectiveV1,
    OnlyAgentSymbolicSearchDirectiveV1,
    OnlyAgentToolClass,
    OnlyAgentToolOccurrenceServiceV1,
    OnlyAgentToolRecoveryClass,
    OnlyVerifiedAgentDecisionContextV1,
    expected_agent_search_submit_semantics,
    translate_agent_hypothesis_to_search_hypothesis,
)
from onlyalpha.research.agent.decision_store import OnlyJsonAgentDecisionStore
from onlyalpha.research.agent.occurrence_store import OnlyJsonAgentToolOccurrenceStore
from onlyalpha.research.experiment import (
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchHypothesisSourceKind,
    OnlySearchHypothesisSourceReferenceV1,
    OnlySearchHypothesisV1,
    OnlySearchWorkflowBindingV1,
)
from tests.research.search.parameter.test_search_product_adapter import _product_case
from tests.research.search.symbolic.test_search_product_adapter import _case

from .support import make_context, packaged_provenance
from .test_decision_application_recovery import (
    Models,
    References,
    Sessions,
    Tools,
    decision_context,
    derive_directive,
)


def _ref(kind: str, fingerprint: str) -> OnlyAgentContextReferenceV1:
    return OnlyAgentContextReferenceV1(kind, 1, fingerprint)


def _context_for(command, root: Path):  # type: ignore[no-untyped-def]
    root.mkdir()
    fixture = make_context(root)
    brief = replace(
        fixture.brief,
        catalog_generation_fingerprint=command.catalog_generation_fingerprint,
        dataset_snapshot_fingerprint=command.dataset_snapshot_fingerprint,
        evaluation_context_reference=OnlyAgentEvaluationContextReferenceV1(
            "ONLY_SYMBOLIC_RESEARCH_EVALUATION_CONTRACT",
            1,
            command.evaluation_contract.evaluation_contract_fingerprint,
        ),
        research_brief_fingerprint="",
    )
    session = replace(
        fixture.session,
        research_brief_fingerprint=brief.research_brief_fingerprint,
        session_fingerprint="",
    )
    return OnlyVerifiedAgentDecisionContextV1(
        session,
        brief,
        fixture.resources[-1],
        fixture.resources[3],
        (fixture.resources[4],),
        fixture.resources[:3],
    )


def _directive(command):  # type: ignore[no-untyped-def]
    common = (
        _ref(
            "SYMBOLIC_SEARCH_SPACE"
            if isinstance(command, OnlySubmitSymbolicSearchExperimentV2)
            else "PARAMETER_SEARCH_SPACE",
            command.search_space.search_space_fingerprint,
        ),
        _ref("RESEARCH_EVALUATION", command.evaluation_contract.evaluation_contract_fingerprint),
    )
    suffix = (
        _ref("SEARCH_ALGORITHM", command.algorithm_manifest.implementation_fingerprint),
        _ref("SEARCH_BUDGET", only_canonical_fingerprint(command.search_budget.to_dict())),
    )
    if isinstance(command, OnlySubmitSymbolicSearchExperimentV2):
        payload = OnlyAgentSymbolicSearchDirectiveV1(*common, *suffix)
        action = OnlyAgentRouterAction.SYMBOLIC_SEARCH
    else:
        payload = OnlyAgentParameterSearchDirectiveV1(
            *common,
            _ref("SEARCH_POLICY", command.search_policy.policy_fingerprint),
            *suffix,
        )
        action = OnlyAgentRouterAction.PARAMETER_SEARCH
    return OnlyAgentSearchDirectiveV1(action, "a" * 64, payload)


class _RuntimeGenerationAuthority:
    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint

    def require_new_work_generation(self, runtime_generation_fingerprint: str) -> object:
        if runtime_generation_fingerprint != self.fingerprint:
            raise LookupError(runtime_generation_fingerprint)
        return object()


@dataclass(frozen=True)
class _FingerprintResource:
    attribute: str
    fingerprint: str

    def __getattr__(self, name: str) -> str:
        if name == self.attribute:
            return self.fingerprint
        raise AttributeError(name)

    def to_dict(self) -> dict[str, object]:
        return {self.attribute: self.fingerprint}


class _RealSearchProductContractAdapter:
    """Hermetic adapter over the production DTO projector and Product service."""

    contract_fingerprint = "d" * 64

    def __init__(self, *, command, product_service, exact):  # type: ignore[no-untyped-def]
        self._template = command
        self._product_service = product_service
        self._exact = exact
        self._projected_command = None
        self._outcome = None
        self.product_invocations = 0
        reference_properties = {
            "id" if index == 0 else f"identity_{index}": {
                "type": "string",
                "x-onlyalpha-reference-kind": reference.reference_kind,
                "x-onlyalpha-reference-schema-version": reference.reference_schema_version,
            }
            for index, reference in enumerate(exact)
        }
        semantic_properties = {
            "method": {"type": "string"},
            "hypothesis_statement": {"type": "string"},
            "hypothesis_source_fingerprint": {"type": "string"},
            "search_space_semantic_fingerprint": {"type": "string"},
            "evaluation_semantic_fingerprint": {"type": "string"},
            "algorithm_semantic_fingerprint": {"type": "string"},
            "search_budget_semantic_fingerprint": {"type": "string"},
            "search_policy_semantic_fingerprint": {"type": "string"},
            "workflow_id": {"type": "string"},
            "workflow_semantic_version": {"type": "string"},
            "decision_mode": {"type": "string"},
            "parent_experiment_fingerprint": {"type": "string"},
            "runtime_generation_fingerprint": {"type": "string"},
        }
        properties = {**reference_properties, **semantic_properties}
        self._request_schema = {
            "additionalProperties": False,
            "properties": properties,
            "required": list(properties),
            "type": "object",
        }

    @staticmethod
    def _resource(request: Mapping[str, object], key: str, actual: object, attribute: str) -> object:
        requested = request[key]
        if requested == getattr(actual, attribute):
            return actual
        assert isinstance(requested, str)
        return _FingerprintResource(attribute, requested)

    def load_operation_verified(self, major: int, fingerprint: str, operation: str):  # type: ignore[no-untyped-def]
        if major != 2 or fingerprint != self.contract_fingerprint:
            raise LookupError(operation)
        tool_class = (
            OnlyAgentToolClass.SYMBOLIC_SEARCH
            if isinstance(self._template, OnlySubmitSymbolicSearchExperimentV2)
            else OnlyAgentToolClass.PARAMETER_SEARCH
        )
        return OnlyAgentProductOperationContractV1(
            2,
            fingerprint,
            operation,
            tool_class,
            OnlyAgentToolRecoveryClass.IDEMPOTENT_COMMAND,
            self._request_schema,
            {
                "additionalProperties": False,
                "properties": {"experiment_fingerprint": {"type": "string"}},
                "required": ["experiment_fingerprint"],
                "type": "object",
            },
            True,
            ("SEARCH_EXPERIMENT",),
        )

    def project_request_semantics_verified(self, **kwargs):  # type: ignore[no-untyped-def]
        request = kwargs["canonical_validated_request"]
        assert isinstance(request, Mapping)
        hypothesis = OnlySearchHypothesisV1(
            request["hypothesis_statement"],
            (
                OnlySearchHypothesisSourceReferenceV1(
                    OnlySearchHypothesisSourceKind.RESEARCH_NOTE,
                    request["hypothesis_source_fingerprint"],
                ),
            ),
        )
        changes: dict[str, object] = {
            "hypothesis": hypothesis,
            "search_space": self._resource(
                request, "search_space_semantic_fingerprint", self._template.search_space, "search_space_fingerprint"
            ),
            "evaluation_contract": self._resource(
                request,
                "evaluation_semantic_fingerprint",
                self._template.evaluation_contract,
                "evaluation_contract_fingerprint",
            ),
            "algorithm_manifest": self._resource(
                request,
                "algorithm_semantic_fingerprint",
                self._template.algorithm_manifest,
                "implementation_fingerprint",
            ),
            "workflow_binding": OnlySearchWorkflowBindingV1(
                request["workflow_id"], request["workflow_semantic_version"]
            ),
            "decision_engine_binding": OnlySearchDecisionEngineBindingV1(
                OnlySearchDecisionMode(request["decision_mode"])
            ),
            "parent_experiment_fingerprint": request["parent_experiment_fingerprint"] or None,
            "runtime_generation_fingerprint": request["runtime_generation_fingerprint"],
        }
        if isinstance(self._template, OnlySubmitParameterSearchExperimentV2):
            changes["search_policy"] = self._resource(
                request,
                "search_policy_semantic_fingerprint",
                self._template.search_policy,
                "policy_fingerprint",
            )
        self._projected_command = replace(self._template, **changes)
        return OnlyAgentProductRequestSemanticProjectionV1(
            kwargs["operation_identity"],
            only_project_search_product_request_semantics(self._projected_command),
        )

    def submit_projected(self):  # type: ignore[no-untyped-def]
        assert self._projected_command is not None
        self.product_invocations += 1
        self._outcome = self._product_service.submit(self._projected_command)
        return self._outcome

    def verify_response_binding(self, plan, response, references):  # type: ignore[no-untyped-def]
        del plan
        assert self._outcome is not None
        fingerprint = self._outcome.experiment.experiment_fingerprint
        assert response == {"experiment_fingerprint": fingerprint}
        assert references == (_ref("SEARCH_EXPERIMENT", fingerprint),)


def _agent_product_case(command, root: Path, product_service):  # type: ignore[no-untyped-def]
    root.mkdir()
    fixture, original_context = decision_context(root)
    brief = replace(
        original_context.research_brief,
        catalog_generation_fingerprint=command.catalog_generation_fingerprint,
        dataset_snapshot_fingerprint=command.dataset_snapshot_fingerprint,
        evaluation_context_reference=OnlyAgentEvaluationContextReferenceV1(
            "ONLYALPHA_SEARCH_EVALUATION",
            1,
            command.evaluation_contract.evaluation_contract_fingerprint,
        ),
        research_brief_fingerprint="",
    )
    session = replace(
        original_context.session,
        research_brief_fingerprint=brief.research_brief_fingerprint,
        session_fingerprint="",
    )
    context = OnlyVerifiedAgentDecisionContextV1(
        session,
        brief,
        original_context.workflow_resource,
        original_context.tool_policy_resource,
        original_context.ordered_role_policy_resources,
        original_context.supporting_resources,
    )
    command = replace(
        command,
        hypothesis=translate_agent_hypothesis_to_search_hypothesis(context.research_brief.hypothesis),
    )
    models = Models()
    tools = Tools()
    application = OnlyAgentDecisionApplicationServiceV1(
        sessions=Sessions(context),
        models=models,
        tools=tools,
        references=References(),
        store=OnlyJsonAgentDecisionStore(root / "decisions"),
        runtime_generations=_RuntimeGenerationAuthority(command.runtime_generation_fingerprint),
    )
    directive_payload = _directive(command).action_payload
    action = (
        OnlyAgentRouterAction.SYMBOLIC_SEARCH
        if isinstance(command, OnlySubmitSymbolicSearchExperimentV2)
        else OnlyAgentRouterAction.PARAMETER_SEARCH
    )
    decision, _ = derive_directive(
        fixture,
        context,
        models,
        tools,
        application,
        action,
        directive_payload=directive_payload,
    )
    exact = (
        directive_payload.search_space_reference,
        directive_payload.evaluation_reference,
        *(
            (directive_payload.search_policy_reference,)
            if isinstance(directive_payload, OnlyAgentParameterSearchDirectiveV1)
            else ()
        ),
        directive_payload.algorithm_reference,
        directive_payload.search_budget_reference,
        _ref("CATALOG_GENERATION", command.catalog_generation_fingerprint),
        _ref("DATASET_SNAPSHOT", command.dataset_snapshot_fingerprint),
        _ref("RUNTIME_GENERATION", command.runtime_generation_fingerprint),
    )
    contracts = _RealSearchProductContractAdapter(command=command, product_service=product_service, exact=exact)
    occurrences = OnlyAgentToolOccurrenceServiceV1(
        sessions=Sessions(context),
        decisions=application,
        product_contracts=contracts,
        references=References(),
        response_references=References(),
        store=OnlyJsonAgentToolOccurrenceStore(root / "tools"),
    )
    expected = expected_agent_search_submit_semantics(
        operation_identity=f"{command.method.value.lower()}_search.v1",
        context=context,
        directive=decision.structured_payload,
        runtime_generation_fingerprint=command.runtime_generation_fingerprint,
    )
    bindings = expected.semantic_bindings
    request: dict[str, object] = {
        "method": bindings["method"],
        "hypothesis_statement": command.hypothesis.statement,
        "hypothesis_source_fingerprint": command.hypothesis.source_references[0].source_fingerprint,
        "search_space_semantic_fingerprint": bindings["search_space_fingerprint"],
        "evaluation_semantic_fingerprint": bindings["evaluation_fingerprint"],
        "algorithm_semantic_fingerprint": bindings["algorithm_fingerprint"],
        "search_budget_semantic_fingerprint": bindings["search_budget_fingerprint"],
        "search_policy_semantic_fingerprint": bindings["search_policy_fingerprint"] or "NONE",
        "workflow_id": bindings["workflow_binding"]["workflow_id"],
        "workflow_semantic_version": bindings["workflow_binding"]["workflow_semantic_version"],
        "decision_mode": bindings["decision_engine_binding"]["mode"],
        "parent_experiment_fingerprint": "",
        "runtime_generation_fingerprint": bindings["runtime_generation_fingerprint"],
    }
    request.update(
        {
            "id" if index == 0 else f"identity_{index}": reference.reference_fingerprint
            for index, reference in enumerate(exact)
        }
    )
    return fixture, context, decision, exact, contracts, occurrences, request


@pytest.mark.parametrize("method", ["symbolic", "parameter"])
def test_real_agent_tool_admission_projects_and_submits_exact_product_dto(
    tmp_path: Path, method: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    product_root = tmp_path / f"{method}-product"
    product_root.mkdir()
    if method == "symbolic":
        product_service, _queries, _authority, _runs, command = _case(product_root)
    else:
        from onlyalpha.research.search.parameter import algorithm as parameter_algorithm

        monkeypatch.setattr(parameter_algorithm, "only_packaged_build_provenance", packaged_provenance)
        hypothesis_root = tmp_path / "parameter-hypothesis"
        hypothesis_root.mkdir()
        translated = translate_agent_hypothesis_to_search_hypothesis(make_context(hypothesis_root).brief.hypothesis)
        product_service, _queries, _authority, _runs, _research, command, _adapter = _product_case(
            product_root, hypothesis=translated
        )
    fixture, context, decision, exact, contracts, occurrences, request = _agent_product_case(
        command, tmp_path / f"{method}-agent", product_service
    )
    operation = f"{method}_search.v1"
    tool_class = OnlyAgentToolClass.SYMBOLIC_SEARCH if method == "symbolic" else OnlyAgentToolClass.PARAMETER_SEARCH
    prepared = occurrences.prepare_tool_call(
        session_fingerprint=context.session.session_fingerprint,
        current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
        tool_call_ordinal=0,
        authorizing_agent_decision_fingerprint=decision.decision_fingerprint,
        tool_class=tool_class,
        product_api_major=2,
        product_api_contract_fingerprint=contracts.contract_fingerprint,
        operation_identity=operation,
        canonical_request=request,
        exact_identity_inputs=exact,
        product_command_id_or_idempotency_key="00000000-0000-4000-8000-000000000001",
    )
    outcome = contracts.submit_projected()
    owner = _ref("SEARCH_EXPERIMENT", outcome.experiment.experiment_fingerprint)
    result = occurrences.record_inline_success(
        prepared,
        {"experiment_fingerprint": outcome.experiment.experiment_fingerprint},
        (owner,),
    )
    assert result.outcome.value == "SUCCEEDED"
    assert contracts.product_invocations == 1

    variants = []
    for field, value in (
        ("workflow_id", "caller.selected"),
        ("hypothesis_statement", "Caller-selected semantic statement."),
        ("runtime_generation_fingerprint", "c" * 64),
        ("parent_experiment_fingerprint", "c" * 64),
        ("decision_mode", OnlySearchDecisionMode.HUMAN.value),
    ):
        changed = dict(request)
        changed[field] = value
        variants.append(changed)
    if method == "parameter":
        changed = dict(request)
        changed["search_policy_semantic_fingerprint"] = "c" * 64
        variants.append(changed)

    for changed in variants:
        with pytest.raises(OnlyAgentContextError, match="AGENT_TOOL_OPERATION_NOT_ALLOWED"):
            occurrences.prepare_tool_call(
                session_fingerprint=context.session.session_fingerprint,
                current_workflow_manifest=fixture.resources[-1].canonical_payload,  # type: ignore[arg-type]
                tool_call_ordinal=1,
                authorizing_agent_decision_fingerprint=decision.decision_fingerprint,
                tool_class=tool_class,
                product_api_major=2,
                product_api_contract_fingerprint=contracts.contract_fingerprint,
                operation_identity=operation,
                canonical_request=changed,
                exact_identity_inputs=exact,
                product_command_id_or_idempotency_key="00000000-0000-4000-8000-000000000002",
            )
        assert occurrences.budget_consumed(context.session.session_fingerprint) == 1
        assert contracts.product_invocations == 1


@pytest.mark.parametrize("method", ["symbolic", "parameter"])
def test_real_search_product_submit_semantics_equal_frozen_agent_translation(
    tmp_path: Path, method: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    product_root = tmp_path / method
    product_root.mkdir()
    if method == "symbolic":
        commands, _queries, _authority, _runs, original = _case(product_root)
    else:
        from onlyalpha.research.search.parameter import algorithm as parameter_algorithm

        monkeypatch.setattr(parameter_algorithm, "only_packaged_build_provenance", packaged_provenance)
        commands, _queries, _authority, _runs, _research, original, _adapter = _product_case(product_root)
    context = _context_for(original, tmp_path / f"{method}-agent")
    translated = translate_agent_hypothesis_to_search_hypothesis(context.research_brief.hypothesis)
    command = replace(original, hypothesis=translated)
    directive = _directive(command)

    actual = only_project_search_product_request_semantics(command)
    expected = expected_agent_search_submit_semantics(
        operation_identity=f"{method}_search.v2",
        context=context,
        directive=directive,
        runtime_generation_fingerprint=command.runtime_generation_fingerprint,
    )
    assert actual == expected.semantic_bindings
    submitted = command if method == "symbolic" else original
    assert commands.submit(submitted).experiment.hypothesis == submitted.hypothesis

    mismatches = (
        replace(command, workflow_binding=OnlySearchWorkflowBindingV1("caller.selected", "1")),
        replace(command, runtime_generation_fingerprint="d" * 64),
        replace(command, hypothesis=replace(translated, statement="Different semantic statement.")),
        replace(
            command,
            decision_engine_binding=OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.HUMAN),
        ),
        replace(command, parent_experiment_fingerprint="c" * 64),
    )
    assert all(only_project_search_product_request_semantics(item) != expected.semantic_bindings for item in mismatches)


def test_agent_hypothesis_translation_is_pure_and_all_agent_context_is_identity_bearing(
    tmp_path: Path,
) -> None:
    hypothesis = make_context(tmp_path).brief.hypothesis
    first = translate_agent_hypothesis_to_search_hypothesis(hypothesis)
    assert translate_agent_hypothesis_to_search_hypothesis(hypothesis) == first
    for field, value in (
        ("hypothesis_id", "another_hypothesis"),
        ("statement", "Another statement."),
        ("rationale", "Another rationale."),
        ("expected_relationship", "Another expected relationship."),
        ("universe_assumptions", ("another universe",)),
        ("falsification_criteria", ("another falsification criterion",)),
    ):
        changed = replace(hypothesis, **{field: value})
        assert translate_agent_hypothesis_to_search_hypothesis(changed).hypothesis_fingerprint != (
            first.hypothesis_fingerprint
        )
