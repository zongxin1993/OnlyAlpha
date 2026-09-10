from __future__ import annotations

import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.agent import (
    OnlyAgentCommitDisposition,
    OnlyAgentContextError,
    OnlyAgentContextReferenceV1,
    OnlyAgentDecisionAuthorizationV1,
    OnlyAgentModelCallOutcome,
    OnlyAgentModelCallPlanV1,
    OnlyAgentModelCallResultV1,
    OnlyAgentModelOccurrenceServiceV1,
    OnlyAgentModelRetryAuthorizationKind,
    OnlyAgentModelRetryAuthorizationV1,
    OnlyAgentModelSettingBindingV1,
    OnlyAgentModelSettingState,
    OnlyAgentObservedResponseStorageKind,
    OnlyAgentProductOperationContractV1,
    OnlyAgentToolCallOutcome,
    OnlyAgentToolCallPlanV1,
    OnlyAgentToolCallResultV1,
    OnlyAgentToolClass,
    OnlyAgentToolOccurrenceServiceV1,
    OnlyAgentToolRecoveryClass,
    OnlyJsonAgentOrchestrationResourceStore,
    OnlyJsonAgentResearchBriefStore,
    OnlyJsonAgentSessionManifestStore,
    validate_agent_strict_value,
)
from onlyalpha.research.agent.occurrence import validate_agent_strict_schema
from onlyalpha.research.agent.occurrence_store import (
    OnlyJsonAgentModelOccurrenceStore,
    OnlyJsonAgentToolOccurrenceStore,
)

from .support import ContextFixture, make_context

CONTRACT = "d" * 64
DECISION = "e" * 64
COMMAND_ID = str(UUID(int=100, version=4))
REQUEST_ID = "a" * 64


class ExactReferences:
    def __init__(self) -> None:
        self.values: dict[tuple[str, int, str], object] = {}

    def add(self, reference: OnlyAgentContextReferenceV1, value: object = True) -> None:
        self.values[(reference.reference_kind, reference.reference_schema_version, reference.reference_fingerprint)] = (
            value
        )

    def verify_exact_reference(self, reference: OnlyAgentContextReferenceV1) -> None:
        if (
            reference.reference_kind,
            reference.reference_schema_version,
            reference.reference_fingerprint,
        ) not in self.values:
            raise LookupError(reference)

    def load_exact_response_verified(self, reference: OnlyAgentContextReferenceV1):  # type: ignore[no-untyped-def]
        self.verify_exact_reference(reference)
        value = self.values[
            (reference.reference_kind, reference.reference_schema_version, reference.reference_fingerprint)
        ]
        if not isinstance(value, dict):
            raise LookupError(reference)
        return value


class Decisions:
    def __init__(self, context: ContextFixture) -> None:
        self.context = context
        self.retry_of_plan_fingerprint: str | None = None
        self.retry_plan_fingerprint: str | None = None
        self.retry_call_ordinal = 1
        self.retry_session_fingerprint = context.session.session_fingerprint

    def load_decision_authorization_verified(self, fingerprint: str) -> OnlyAgentDecisionAuthorizationV1:
        if fingerprint != DECISION:
            raise LookupError(fingerprint)
        return OnlyAgentDecisionAuthorizationV1(
            DECISION,
            self.context.session.session_fingerprint,
            self.context.session.agent_workflow_implementation_fingerprint,
            tuple(OnlyAgentToolClass),
            tuple(f"{item.value.lower()}.v1" for item in OnlyAgentToolClass),
        )

    def load_model_retry_authorization_verified(self, fingerprint: str) -> OnlyAgentModelRetryAuthorizationV1:
        if fingerprint != DECISION or self.retry_of_plan_fingerprint is None or self.retry_plan_fingerprint is None:
            raise LookupError(fingerprint)
        return OnlyAgentModelRetryAuthorizationV1(
            DECISION,
            self.retry_session_fingerprint,
            self.context.session.agent_workflow_implementation_fingerprint,
            self.retry_of_plan_fingerprint,
            self.retry_plan_fingerprint,
            self.retry_call_ordinal,
            self.context.resources[2].resource_fingerprint,
            OnlyAgentModelRetryAuthorizationKind.HUMAN,
        )

    def authorize_retry(
        self,
        prior: OnlyAgentModelCallPlanV1,
        *,
        retry_of_plan_fingerprint: str | None = None,
        provider_id: str | None = None,
    ) -> None:
        retry_of = retry_of_plan_fingerprint or prior.model_call_plan_fingerprint
        candidate = replace(
            prior,
            call_ordinal=self.retry_call_ordinal,
            provider_id=prior.provider_id if provider_id is None else provider_id,
            parent_agent_decision_fingerprint=DECISION,
            retry_of_plan_fingerprint=retry_of,
            model_call_plan_fingerprint="",
        )
        self.retry_of_plan_fingerprint = retry_of
        self.retry_plan_fingerprint = candidate.model_call_plan_fingerprint


RECOVERY = {
    OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY: OnlyAgentToolRecoveryClass.IMMUTABLE_EXACT_QUERY,
    OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE: OnlyAgentToolRecoveryClass.PURE_RESOLVE,
    OnlyAgentToolClass.RESEARCH_RUN_SUBMIT: OnlyAgentToolRecoveryClass.IDEMPOTENT_COMMAND,
    OnlyAgentToolClass.RESEARCH_RUN_QUERY: OnlyAgentToolRecoveryClass.MUTABLE_OBSERVATION_QUERY,
    OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY: OnlyAgentToolRecoveryClass.IMMUTABLE_EXACT_QUERY,
    OnlyAgentToolClass.SYMBOLIC_SEARCH: OnlyAgentToolRecoveryClass.IDEMPOTENT_COMMAND,
    OnlyAgentToolClass.PARAMETER_SEARCH: OnlyAgentToolRecoveryClass.IDEMPOTENT_COMMAND,
    OnlyAgentToolClass.SEARCH_QUERY: OnlyAgentToolRecoveryClass.MUTABLE_OBSERVATION_QUERY,
}


class ProductContracts:
    def __init__(
        self,
        *,
        request_schema: dict[str, object] | None = None,
        response_schema: dict[str, object] | None = None,
    ) -> None:
        self.request_schema = request_schema
        self.response_schema = response_schema

    def load_operation_verified(
        self, product_api_major: int, product_api_contract_fingerprint: str, operation_identity: str
    ) -> OnlyAgentProductOperationContractV1:
        if product_api_major != 2 or product_api_contract_fingerprint != CONTRACT:
            raise LookupError(operation_identity)
        matches = tuple(item for item in OnlyAgentToolClass if operation_identity == f"{item.value.lower()}.v1")
        if len(matches) != 1:
            raise LookupError(operation_identity)
        tool_class = matches[0]
        return OnlyAgentProductOperationContractV1(
            2,
            CONTRACT,
            operation_identity,
            tool_class,
            RECOVERY[tool_class],
            self.request_schema
            or {
                "additionalProperties": False,
                "properties": {
                    "id": {
                        "type": "string",
                        "x-onlyalpha-reference-kind": "CATALOG_GENERATION",
                        "x-onlyalpha-reference-schema-version": 1,
                    }
                },
                "required": ["id"],
                "type": "object",
            },
            self.response_schema
            or {
                "additionalProperties": False,
                "properties": {"request_id": {"type": "string"}, "result": {"type": "string"}},
                "required": ["request_id", "result"],
                "type": "object",
            },
            RECOVERY[tool_class] is OnlyAgentToolRecoveryClass.IDEMPOTENT_COMMAND,
            ("PRODUCT_FACT",),
        )

    def verify_response_binding(
        self,
        plan: OnlyAgentToolCallPlanV1,
        canonical_response,
        owning_authority_references,
    ) -> None:  # type: ignore[no-untyped-def]
        if canonical_response["request_id"] != plan.canonical_validated_request["id"]:
            raise ValueError("response/request mismatch")
        if canonical_response["result"] != "canonical":
            raise ValueError("response differs from exact owning Product fact")
        if tuple(item.reference_kind for item in owning_authority_references) != ("PRODUCT_FACT",):
            raise ValueError("owning Authority mismatch")


def _commit_context(root: Path):  # type: ignore[no-untyped-def]
    root.mkdir(parents=True, exist_ok=True)
    context = make_context(root)
    resources = OnlyJsonAgentOrchestrationResourceStore(root)
    for item in context.resources:
        resources.commit_resource(item)
    briefs = OnlyJsonAgentResearchBriefStore(root, context.readers)
    briefs.commit_research_brief(context.brief)
    sessions = OnlyJsonAgentSessionManifestStore(root, briefs=briefs, resources=resources)
    sessions.commit_session_manifest(context.session)
    return context, resources, sessions


def _services(root: Path, *, product_contracts=None):  # type: ignore[no-untyped-def]
    context, resources, sessions = _commit_context(root)
    (root / "product-contract.json").write_text(
        only_canonical_json(
            {
                "product_api_major": 2,
                "product_api_contract_fingerprint": CONTRACT,
                "operations": {
                    f"{tool_class.value.lower()}.v1": {"recovery_class": RECOVERY[tool_class].value}
                    for tool_class in OnlyAgentToolClass
                },
            }
        ),
        encoding="utf-8",
    )
    references = ExactReferences()
    context_reference = OnlyAgentContextReferenceV1(
        "CATALOG_GENERATION", 1, context.brief.catalog_generation_fingerprint
    )
    owner_reference = OnlyAgentContextReferenceV1("PRODUCT_FACT", 1, "f" * 64)
    response_reference = OnlyAgentContextReferenceV1("PRODUCT_RESPONSE", 1, "1" * 64)
    references.add(context_reference)
    references.add(OnlyAgentContextReferenceV1("CATALOG_GENERATION", 1, "2" * 64))
    references.add(OnlyAgentContextReferenceV1("CATALOG_GENERATION", 2, context_reference.reference_fingerprint))
    references.add(OnlyAgentContextReferenceV1("OTHER_AUTHORITY", 1, context_reference.reference_fingerprint))
    references.add(owner_reference)
    references.add(
        response_reference,
        {"request_id": context.brief.catalog_generation_fingerprint, "result": "canonical"},
    )
    decisions = Decisions(context)
    model_store = OnlyJsonAgentModelOccurrenceStore(root)
    tool_store = OnlyJsonAgentToolOccurrenceStore(root)
    model = OnlyAgentModelOccurrenceServiceV1(
        sessions=sessions,
        resources=resources,
        references=references,
        decisions=decisions,
        retry_authorizations=decisions,
        store=model_store,
    )
    tool = OnlyAgentToolOccurrenceServiceV1(
        sessions=sessions,
        decisions=decisions,
        product_contracts=product_contracts or ProductContracts(),
        references=references,
        response_references=references,
        store=tool_store,
    )
    return (
        context,
        model,
        tool,
        model_store,
        tool_store,
        context_reference,
        owner_reference,
        response_reference,
        decisions,
    )


def _prepare_model(model, context, context_reference, *, ordinal=0, **changes):  # type: ignore[no-untyped-def]
    role = context.resources[4]
    values = {
        "session_fingerprint": context.session.session_fingerprint,
        "current_workflow_manifest": context.resources[-1].canonical_payload,
        "call_ordinal": ordinal,
        "logical_role": "RESEARCH_PLANNER",
        "role_policy_fingerprint": role.resource_fingerprint,
        "provider_id": "provider-a",
        "model_id": "model-a",
        "model_version": "2026-09-01",
        "prompt_template_fingerprint": context.resources[0].resource_fingerprint,
        "structured_output_schema_fingerprint": context.resources[1].resource_fingerprint,
        "model_execution_policy_fingerprint": context.resources[2].resource_fingerprint,
        "response_affecting_settings": (
            OnlyAgentModelSettingBindingV1("temperature", OnlyAgentModelSettingState.VALUE, "0"),
        ),
        "ordered_context_references": (context_reference,),
    }
    values.update(changes)
    return model.prepare_model_call(**values)


def _prepare_tool(
    tool,
    context,
    tool_class,
    ordinal,
    *,
    command=None,
    request_id=REQUEST_ID,
    identity_inputs=None,
):  # type: ignore[no-untyped-def]
    identity = OnlyAgentContextReferenceV1("CATALOG_GENERATION", 1, context.brief.catalog_generation_fingerprint)
    return tool.prepare_tool_call(
        session_fingerprint=context.session.session_fingerprint,
        current_workflow_manifest=context.resources[-1].canonical_payload,
        tool_call_ordinal=ordinal,
        authorizing_agent_decision_fingerprint=DECISION,
        tool_class=tool_class,
        product_api_major=2,
        product_api_contract_fingerprint=CONTRACT,
        operation_identity=f"{tool_class.value.lower()}.v1",
        canonical_request={"id": request_id},
        exact_identity_inputs=(identity,) if identity_inputs is None else identity_inputs,
        product_command_id_or_idempotency_key=command,
    )


def test_model_plan_identity_covers_every_semantic_dimension(tmp_path) -> None:
    context, model, _, _, _, reference, _, _, _ = _services(tmp_path)
    plan = _prepare_model(model, context, reference).plan
    assert OnlyAgentModelCallPlanV1.from_dict(plan.to_dict()) == plan
    variants = (
        replace(plan, provider_id="provider-b", model_call_plan_fingerprint=""),
        replace(plan, model_id="model-b", model_call_plan_fingerprint=""),
        replace(plan, model_version="2026-09-02", model_call_plan_fingerprint=""),
        replace(plan, logical_role="OTHER", model_call_plan_fingerprint=""),
        replace(plan, call_ordinal=1, model_call_plan_fingerprint=""),
        replace(plan, prompt_template_fingerprint="1" * 64, model_call_plan_fingerprint=""),
        replace(plan, structured_output_schema_fingerprint="2" * 64, model_call_plan_fingerprint=""),
        replace(plan, tool_policy_fingerprint="3" * 64, model_call_plan_fingerprint=""),
        replace(plan, model_execution_policy_fingerprint="4" * 64, model_call_plan_fingerprint=""),
        replace(
            plan,
            response_affecting_settings=(
                OnlyAgentModelSettingBindingV1("temperature", OnlyAgentModelSettingState.VALUE, "0.1"),
            ),
            model_call_plan_fingerprint="",
        ),
        replace(plan, ordered_context_references=(), model_call_plan_fingerprint=""),
        replace(plan, parent_agent_decision_fingerprint=DECISION, model_call_plan_fingerprint=""),
        replace(plan, retry_of_plan_fingerprint="5" * 64, model_call_plan_fingerprint=""),
    )
    assert len({plan.model_call_plan_fingerprint, *(item.model_call_plan_fingerprint for item in variants)}) == 14
    assert not set(plan.to_dict()).intersection({"created_at", "host", "pid", "latency", "api_key", "token_usage"})


@pytest.mark.parametrize(
    "alias",
    ["latest", "model-current", "DEFAULT", "auto", "best", "release/latest.v1", "current@2026"],
)
def test_model_plan_rejects_mutable_model_version_aliases(alias: str) -> None:
    with pytest.raises(ValueError, match="AGENT_MODEL_CALL_PLAN_INVALID"):
        OnlyAgentModelCallPlanV1(
            "a" * 64,
            0,
            "ROLE",
            "b" * 64,
            "provider",
            "model",
            alias,
            "c" * 64,
            "d" * 64,
            "e" * 64,
            "f" * 64,
            (OnlyAgentModelSettingBindingV1("temperature", OnlyAgentModelSettingState.VALUE, 0),),
            (),
        )


def test_model_admission_exact_settings_context_budget_ordinal_and_runtime(tmp_path) -> None:
    context, model, _, store, _, reference, _, _, _ = _services(tmp_path)
    with pytest.raises(OnlyAgentContextError) as unresolved:
        _prepare_model(model, context, OnlyAgentContextReferenceV1("CATALOG_GENERATION", 1, "9" * 64))
    assert unresolved.value.code == "AGENT_MODEL_CALL_PLAN_INVALID"
    with pytest.raises(OnlyAgentContextError):
        _prepare_model(model, context, reference, response_affecting_settings=())
    with pytest.raises(OnlyAgentContextError) as mismatch:
        _prepare_model(
            model,
            context,
            reference,
            current_workflow_manifest=replace(
                context.resources[-1].canonical_payload,
                workflow_semantic_version="2.0.0",
                implementation_fingerprint="",
            ),
        )
    assert mismatch.value.code == "AGENT_WORKFLOW_RUNTIME_MISMATCH"
    first = _prepare_model(model, context, reference)
    assert store.budget_consumed(context.session.session_fingerprint) == 1
    with pytest.raises(OnlyAgentContextError) as ordinal:
        _prepare_model(model, context, reference, provider_id="different")
    assert ordinal.value.code == "AGENT_OCCURRENCE_ORDINAL_CONFLICT"
    second = _prepare_model(model, context, reference, ordinal=1)
    assert first.plan != second.plan
    with pytest.raises(OnlyAgentContextError) as budget:
        _prepare_model(model, context, reference, ordinal=2)
    assert budget.value.code == "AGENT_BUDGET_EXHAUSTED"


def test_model_admission_rejects_missing_session_and_disallowed_resource_bindings(tmp_path) -> None:
    context, model, _, _, _, reference, _, _, _ = _services(tmp_path)
    for changes, code in (
        ({"session_fingerprint": "9" * 64}, "AGENT_SESSION_INVALID"),
        ({"prompt_template_fingerprint": "9" * 64}, "AGENT_MODEL_CALL_PLAN_INVALID"),
        ({"structured_output_schema_fingerprint": "9" * 64}, "AGENT_MODEL_CALL_PLAN_INVALID"),
        ({"model_execution_policy_fingerprint": "9" * 64}, "AGENT_MODEL_CALL_PLAN_INVALID"),
        ({"role_policy_fingerprint": "9" * 64}, "AGENT_MODEL_CALL_PLAN_INVALID"),
    ):
        with pytest.raises(OnlyAgentContextError) as raised:
            _prepare_model(model, context, reference, **changes)
        assert raised.value.code == code


@pytest.mark.parametrize(
    ("response", "outcome"),
    [
        ({"action": "PLAN"}, OnlyAgentModelCallOutcome.RETURNED),
        ("not-json", OnlyAgentModelCallOutcome.RESPONSE_INVALID),
        ({"action": "ILLEGAL"}, OnlyAgentModelCallOutcome.RESPONSE_INVALID),
        ({"action": "PLAN", "unknown": True}, OnlyAgentModelCallOutcome.RESPONSE_INVALID),
        ({"action": 1}, OnlyAgentModelCallOutcome.RESPONSE_INVALID),
    ],
)
def test_model_result_strict_validation_and_no_hidden_reasoning(tmp_path, response, outcome) -> None:  # type: ignore[no-untyped-def]
    context, model, _, store, _, reference, _, _, _ = _services(tmp_path)
    prepared = _prepare_model(model, context, reference)
    result = model.record_returned(prepared, response)
    assert result.outcome is outcome
    assert OnlyAgentModelCallResultV1.from_dict(result.to_dict()) == result
    persisted = only_canonical_json(result.to_dict())
    assert not any(name in persisted for name in ("chain_of_thought", "hidden_reasoning", "scratchpad"))
    with pytest.raises(OnlyAgentContextError) as conflict:
        store.commit_result(
            OnlyAgentModelCallResultV1(
                prepared.plan.model_call_plan_fingerprint,
                OnlyAgentModelCallOutcome.FAILED,
                failure_code="AGENT_MODEL_CALL_FAILED",
            )
        )
    assert conflict.value.code == "AGENT_MODEL_CALL_RESULT_CONFLICT"


def test_strict_validator_rejects_out_of_context_typed_reference() -> None:
    schema = {
        "type": "string",
        "x-onlyalpha-reference-kind": "CANDIDATE",
        "x-onlyalpha-reference-schema-version": 1,
    }
    reference = OnlyAgentContextReferenceV1("CANDIDATE", 1, "a" * 64)
    assert validate_agent_strict_value("a" * 64, schema, allowed_context_references=(reference,)) == "a" * 64
    with pytest.raises(ValueError, match="AGENT_MODEL_RESPONSE_INVALID"):
        validate_agent_strict_value("b" * 64, schema, allowed_context_references=(reference,))
    with pytest.raises(ValueError, match="AGENT_MODEL_RESPONSE_INVALID"):
        validate_agent_strict_value(
            "a" * 64,
            schema,
            allowed_context_references=(OnlyAgentContextReferenceV1("CANDIDATE", 2, "a" * 64),),
        )


def test_strict_validator_rejects_unsupported_optional_schema_and_root_mismatch() -> None:
    hidden_unsupported_semantics = {
        "additionalProperties": False,
        "properties": {"optional": {"format": "date-time", "type": "string"}},
        "required": [],
        "type": "object",
    }
    with pytest.raises(ValueError, match="AGENT_STRUCTURED_SCHEMA_UNSUPPORTED"):
        validate_agent_strict_value({}, hidden_unsupported_semantics)
    with pytest.raises(ValueError, match="AGENT_STRUCTURED_SCHEMA_UNSUPPORTED"):
        validate_agent_strict_schema({"type": "string"}, root_type="object")


def test_strict_schema_rejects_number_and_supported_primitives_round_trip() -> None:
    with pytest.raises(ValueError, match="AGENT_STRUCTURED_SCHEMA_UNSUPPORTED"):
        validate_agent_strict_schema({"type": "number"})
    schema = {
        "additionalProperties": False,
        "properties": {
            "array": {"items": {"type": "string"}, "type": "array"},
            "boolean": {"type": "boolean"},
            "integer": {"type": "integer"},
            "null": {"type": "null"},
            "object": {
                "additionalProperties": False,
                "properties": {"value": {"enum": ["EXACT"], "type": "string"}},
                "required": ["value"],
                "type": "object",
            },
            "string": {"type": "string"},
        },
        "required": ["array", "boolean", "integer", "null", "object", "string"],
        "type": "object",
    }
    value = {
        "array": ["a", "b"],
        "boolean": True,
        "integer": 7,
        "null": None,
        "object": {"value": "EXACT"},
        "string": "value",
    }
    first = validate_agent_strict_value(value, schema)
    encoded = only_canonical_json(first)
    second = validate_agent_strict_value(json.loads(encoded), schema)
    assert first == second
    assert only_canonical_fingerprint(first) == only_canonical_fingerprint(second)


def test_model_unknown_recovery_requires_current_runtime_but_history_remains_readable(tmp_path) -> None:
    context, model, _, store, _, reference, _, _, _ = _services(tmp_path)
    prepared = _prepare_model(model, context, reference)
    mismatched = replace(
        context.resources[-1].canonical_payload,
        workflow_semantic_version="2.0.0",
        implementation_fingerprint="",
    )
    assert model.load_plan_verified(prepared.plan.model_call_plan_fingerprint) == prepared.plan
    with pytest.raises(OnlyAgentContextError) as blocked:
        model.recover_outcome_unknown(
            prepared.plan.model_call_plan_fingerprint,
            current_workflow_manifest=mismatched,
        )
    assert blocked.value.code == "AGENT_WORKFLOW_RUNTIME_MISMATCH"
    assert not store.result_exists(prepared.plan.model_call_plan_fingerprint)
    result = model.recover_outcome_unknown(
        prepared.plan.model_call_plan_fingerprint,
        current_workflow_manifest=context.resources[-1].canonical_payload,
    )
    assert result.outcome is OnlyAgentModelCallOutcome.OUTCOME_UNKNOWN


def test_model_unknown_is_terminal_and_retry_is_new_occurrence(tmp_path) -> None:
    context, model, _, store, _, reference, _, _, authorizations = _services(tmp_path)
    first = _prepare_model(model, context, reference)
    unknown = model.recover_outcome_unknown(
        first.plan.model_call_plan_fingerprint,
        current_workflow_manifest=context.resources[-1].canonical_payload,
    )
    assert unknown.outcome is OnlyAgentModelCallOutcome.OUTCOME_UNKNOWN
    with pytest.raises(OnlyAgentContextError) as resend:
        _prepare_model(model, context, reference)
    assert resend.value.code == "AGENT_MODEL_CALL_PLAN_CONFLICT"
    with pytest.raises(OnlyAgentContextError):
        model.record_failed(first)
    with pytest.raises(OnlyAgentContextError) as unauthorized:
        _prepare_model(
            model,
            context,
            reference,
            ordinal=1,
            retry_of_plan_fingerprint=first.plan.model_call_plan_fingerprint,
        )
    assert unauthorized.value.code == "AGENT_POLICY_VIOLATION"
    authorizations.authorize_retry(first.plan)
    retry = _prepare_model(
        model,
        context,
        reference,
        ordinal=1,
        parent_agent_decision_fingerprint=DECISION,
        retry_of_plan_fingerprint=first.plan.model_call_plan_fingerprint,
    )
    assert retry.plan.call_ordinal == 1
    assert retry.plan.retry_of_plan_fingerprint == first.plan.model_call_plan_fingerprint
    assert retry.plan.model_call_plan_fingerprint != first.plan.model_call_plan_fingerprint
    assert store.budget_consumed(context.session.session_fingerprint) == 2


def test_model_retry_missing_cross_session_and_tampered_cycle_fail_closed(tmp_path) -> None:
    context, model, _, store, _, reference, _, _, authorizations = _services(tmp_path)
    first = _prepare_model(model, context, reference)
    model.recover_outcome_unknown(
        first.plan.model_call_plan_fingerprint,
        current_workflow_manifest=context.resources[-1].canonical_payload,
    )
    authorizations.authorize_retry(first.plan, retry_of_plan_fingerprint="9" * 64)
    with pytest.raises(OnlyAgentContextError):
        _prepare_model(
            model,
            context,
            reference,
            ordinal=1,
            parent_agent_decision_fingerprint=DECISION,
            retry_of_plan_fingerprint="9" * 64,
        )

    cross = replace(
        first.plan,
        agent_session_fingerprint="8" * 64,
        model_call_plan_fingerprint="",
    )
    store.commit_plan(cross)
    store.commit_result(
        OnlyAgentModelCallResultV1(
            cross.model_call_plan_fingerprint,
            OnlyAgentModelCallOutcome.FAILED,
            failure_code="AGENT_MODEL_CALL_FAILED",
        )
    )
    with pytest.raises(OnlyAgentContextError) as cross_session:
        authorizations.authorize_retry(first.plan, retry_of_plan_fingerprint=cross.model_call_plan_fingerprint)
        _prepare_model(
            model,
            context,
            reference,
            ordinal=1,
            parent_agent_decision_fingerprint=DECISION,
            retry_of_plan_fingerprint=cross.model_call_plan_fingerprint,
        )
    assert cross_session.value.code == "AGENT_MODEL_CALL_PLAN_INVALID"

    path = _manifest(tmp_path, "model-calls/plans", first.plan.model_call_plan_fingerprint)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["retry_of_plan_fingerprint"] = first.plan.model_call_plan_fingerprint
    path.write_text(only_canonical_json(payload), encoding="utf-8")
    with pytest.raises(OnlyAgentContextError):
        store.load_plan_verified(first.plan.model_call_plan_fingerprint)


def test_model_retry_authorization_must_bind_session_prior_plan_ordinal_and_policy(tmp_path) -> None:
    context, model, _, _, _, reference, _, _, authorizations = _services(tmp_path)
    first = _prepare_model(model, context, reference)
    model.recover_outcome_unknown(
        first.plan.model_call_plan_fingerprint,
        current_workflow_manifest=context.resources[-1].canonical_payload,
    )
    authorizations.authorize_retry(first.plan)
    attempts = (
        ("retry_session_fingerprint", "8" * 64),
        ("retry_of_plan_fingerprint", "9" * 64),
        ("retry_call_ordinal", 2),
    )
    for field, wrong_value in attempts:
        original = getattr(authorizations, field)
        setattr(authorizations, field, wrong_value)
        with pytest.raises(OnlyAgentContextError) as blocked:
            _prepare_model(
                model,
                context,
                reference,
                ordinal=1,
                parent_agent_decision_fingerprint=DECISION,
                retry_of_plan_fingerprint=first.plan.model_call_plan_fingerprint,
            )
        assert blocked.value.code == "AGENT_POLICY_VIOLATION"
        setattr(authorizations, field, original)
    with pytest.raises(OnlyAgentContextError) as different_occurrence:
        _prepare_model(
            model,
            context,
            reference,
            ordinal=1,
            provider_id="provider-b",
            parent_agent_decision_fingerprint=DECISION,
            retry_of_plan_fingerprint=first.plan.model_call_plan_fingerprint,
        )
    assert different_occurrence.value.code == "AGENT_POLICY_VIOLATION"


def test_model_known_failure_is_distinct_from_unknown(tmp_path) -> None:
    context, model, _, _, _, reference, _, _, _ = _services(tmp_path)
    failed = model.record_failed(_prepare_model(model, context, reference))
    assert failed.outcome is OnlyAgentModelCallOutcome.FAILED
    assert failed.failure_code == "AGENT_MODEL_CALL_FAILED"
    assert failed.validated_structured_output is None


@pytest.mark.parametrize("tool_class", tuple(OnlyAgentToolClass))
def test_every_allowed_tool_class_requires_exact_durable_plan(tmp_path, tool_class: OnlyAgentToolClass) -> None:
    context, _, tool, _, store, _, _, _, _ = _services(tmp_path)
    command = COMMAND_ID if RECOVERY[tool_class] is OnlyAgentToolRecoveryClass.IDEMPOTENT_COMMAND else None
    prepared = _prepare_tool(tool, context, tool_class, 0, command=command)
    assert store.load_plan_verified(prepared.plan.tool_call_plan_fingerprint) == prepared.plan
    assert prepared.recovery_class is RECOVERY[tool_class]
    assert "recovery_class" not in prepared.plan.to_dict()
    assert "http" not in only_canonical_json(prepared.plan.to_dict()).casefold()
    assert tool.budget_consumed(context.session.session_fingerprint) == 1


def test_tool_plan_identity_binds_contract_operation_request_command_policy_and_decision(tmp_path) -> None:
    context, _, tool, _, _, _, _, _, _ = _services(tmp_path)
    tool_class = OnlyAgentToolClass.RESEARCH_RUN_SUBMIT
    plan = _prepare_tool(tool, context, tool_class, 0, command=COMMAND_ID).plan
    variants = (
        replace(plan, authorizing_agent_decision_fingerprint="1" * 64, tool_call_plan_fingerprint=""),
        replace(plan, product_api_major=3, tool_call_plan_fingerprint=""),
        replace(plan, product_api_contract_fingerprint="2" * 64, tool_call_plan_fingerprint=""),
        replace(plan, operation_identity="other.v1", tool_call_plan_fingerprint=""),
        replace(
            plan,
            canonical_validated_request={"id": "other"},
            canonical_request_fingerprint="",
            tool_call_plan_fingerprint="",
        ),
        replace(
            plan, product_command_id_or_idempotency_key=str(UUID(int=101, version=4)), tool_call_plan_fingerprint=""
        ),
        replace(plan, tool_policy_fingerprint="3" * 64, tool_call_plan_fingerprint=""),
    )
    assert len({plan.tool_call_plan_fingerprint, *(item.tool_call_plan_fingerprint for item in variants)}) == 8
    assert tool_class is OnlyAgentToolClass.RESEARCH_RUN_SUBMIT
    assert not set(plan.to_dict()).intersection(
        {"url", "host", "port", "http_method", "headers", "transport_request_id"}
    )


def test_tool_plan_rejects_contract_decision_request_command_budget_and_ordinal(tmp_path) -> None:
    context, _, tool, _, store, _, _, _, _ = _services(tmp_path)
    with pytest.raises(OnlyAgentContextError) as command:
        _prepare_tool(tool, context, OnlyAgentToolClass.RESEARCH_RUN_SUBMIT, 0)
    assert command.value.code == "AGENT_TOOL_CALL_PLAN_INVALID"
    with pytest.raises(OnlyAgentContextError) as unexpected:
        _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 0, command=COMMAND_ID)
    assert unexpected.value.code == "AGENT_TOOL_CALL_PLAN_INVALID"
    prepared = _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 0)
    conflicting = replace(prepared.plan, operation_identity="other.v1", tool_call_plan_fingerprint="")
    with pytest.raises(OnlyAgentContextError) as ordinal:
        store.commit_plan(conflicting)
    assert ordinal.value.code == "AGENT_OCCURRENCE_ORDINAL_CONFLICT"
    for ordinal_value in range(1, context.brief.agent_budget.tool_call_limit):
        _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, ordinal_value)
    with pytest.raises(OnlyAgentContextError) as budget:
        _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 6)
    assert budget.value.code == "AGENT_BUDGET_EXHAUSTED"


def test_tool_plan_rejects_missing_decision_wrong_contract_operation_request_and_reference(tmp_path) -> None:
    context, _, tool, _, _, _, _, _, _ = _services(tmp_path)
    base = {
        "session_fingerprint": context.session.session_fingerprint,
        "current_workflow_manifest": context.resources[-1].canonical_payload,
        "tool_call_ordinal": 0,
        "authorizing_agent_decision_fingerprint": DECISION,
        "tool_class": OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
        "product_api_major": 2,
        "product_api_contract_fingerprint": CONTRACT,
        "operation_identity": "exact_catalog_context_query.v1",
        "canonical_request": {"id": REQUEST_ID},
        "exact_identity_inputs": (OnlyAgentContextReferenceV1("CATALOG_GENERATION", 1, REQUEST_ID),),
        "product_command_id_or_idempotency_key": None,
    }
    for changes, code in (
        ({"authorizing_agent_decision_fingerprint": "9" * 64}, "AGENT_DECISION_REFERENCE_INVALID"),
        ({"product_api_contract_fingerprint": "9" * 64}, "AGENT_PRODUCT_API_CONTRACT_MISMATCH"),
        ({"operation_identity": "research_run_query.v1"}, "AGENT_TOOL_OPERATION_NOT_ALLOWED"),
        ({"canonical_request": {"id": "x", "unknown": True}}, "AGENT_TOOL_CALL_PLAN_INVALID"),
        (
            {"exact_identity_inputs": (OnlyAgentContextReferenceV1("MISSING", 1, "9" * 64),)},
            "AGENT_TOOL_CALL_PLAN_INVALID",
        ),
    ):
        values = {**base, **changes}
        with pytest.raises((OnlyAgentContextError, ValueError)) as raised:
            tool.prepare_tool_call(**values)
        observed = getattr(raised.value, "code", str(raised.value))
        assert code in observed


def test_tool_request_identity_exactly_matches_typed_reference_closure(tmp_path) -> None:
    context, _, tool, _, _, exact, owner, _, _ = _services(tmp_path)
    cases = (
        (REQUEST_ID, (OnlyAgentContextReferenceV1("CATALOG_GENERATION", 1, "2" * 64),)),
        (REQUEST_ID, ()),
        (REQUEST_ID, (exact, owner)),
        (REQUEST_ID, (OnlyAgentContextReferenceV1("OTHER_AUTHORITY", 1, REQUEST_ID),)),
        (REQUEST_ID, (OnlyAgentContextReferenceV1("CATALOG_GENERATION", 2, REQUEST_ID),)),
    )
    for request_id, identity_inputs in cases:
        with pytest.raises(OnlyAgentContextError) as blocked:
            _prepare_tool(
                tool,
                context,
                OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
                0,
                request_id=request_id,
                identity_inputs=identity_inputs,
            )
        assert blocked.value.code == "AGENT_TOOL_CALL_PLAN_INVALID"
    prepared = _prepare_tool(
        tool,
        context,
        OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
        0,
        request_id=REQUEST_ID,
        identity_inputs=(exact,),
    )
    assert prepared.plan.exact_identity_inputs == (exact,)


def test_tool_prepare_rejects_unsupported_response_schema_before_plan_commit(tmp_path) -> None:
    contracts = ProductContracts(response_schema={"type": "number"})
    context, _, tool, _, store, _, _, _, _ = _services(tmp_path, product_contracts=contracts)
    with pytest.raises(OnlyAgentContextError) as blocked:
        _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 0)
    assert blocked.value.code == "AGENT_PRODUCT_API_CONTRACT_MISMATCH"
    assert store.budget_consumed(context.session.session_fingerprint) == 0


def test_product_operation_contract_freezes_structured_schemas() -> None:
    request_schema: dict[str, object] = {
        "additionalProperties": False,
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
        "type": "object",
    }
    response_schema: dict[str, object] = {
        "additionalProperties": False,
        "properties": {"result": {"type": "string"}},
        "required": ["result"],
        "type": "object",
    }
    contract = OnlyAgentProductOperationContractV1(
        2,
        CONTRACT,
        "operation.v1",
        OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
        OnlyAgentToolRecoveryClass.IMMUTABLE_EXACT_QUERY,
        request_schema,
        response_schema,
        False,
        (),
    )
    request_schema["type"] = "number"
    response_schema["required"] = []
    assert contract.request_schema["type"] == "object"
    assert contract.response_schema["required"] == ("result",)
    with pytest.raises(TypeError):
        contract.request_schema["type"] = "number"  # type: ignore[index]


def test_tool_result_strict_one_of_exact_reference_and_conflict(tmp_path) -> None:
    context, _, tool, _, store, _, owner, response_reference, _ = _services(tmp_path)
    inline_plan = _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 0)
    inline = tool.record_inline_success(inline_plan, {"request_id": REQUEST_ID, "result": "canonical"}, (owner,))
    assert inline.observed_response_storage_kind is OnlyAgentObservedResponseStorageKind.INLINE_CANONICAL_RESPONSE
    referenced_plan = _prepare_tool(tool, context, OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY, 1)
    referenced = tool.record_exact_reference_success(referenced_plan, response_reference, (owner,))
    assert (
        referenced.observed_response_storage_kind
        is OnlyAgentObservedResponseStorageKind.EXACT_IMMUTABLE_RESPONSE_REFERENCE
    )
    assert OnlyAgentToolCallResultV1.from_dict(referenced.to_dict()) == referenced
    with pytest.raises(ValueError, match="AGENT_TOOL_RESULT_INVALID"):
        OnlyAgentToolCallResultV1(
            referenced_plan.plan.tool_call_plan_fingerprint,
            OnlyAgentToolCallOutcome.SUCCEEDED,
            OnlyAgentObservedResponseStorageKind.INLINE_CANONICAL_RESPONSE,
            {"request_id": REQUEST_ID, "result": "x"},
            response_reference,
            only_canonical_fingerprint({"request_id": REQUEST_ID, "result": "x"}),
            (owner,),
        )
    with pytest.raises(ValueError, match="AGENT_TOOL_RESULT_INVALID"):
        OnlyAgentToolCallResultV1(
            referenced_plan.plan.tool_call_plan_fingerprint,
            OnlyAgentToolCallOutcome.SUCCEEDED,
            OnlyAgentObservedResponseStorageKind.INLINE_CANONICAL_RESPONSE,
            {"request_id": REQUEST_ID, "result": "x"},
            canonical_response_fingerprint="9" * 64,
            owning_authority_references=(owner,),
        )
    with pytest.raises(OnlyAgentContextError) as conflict:
        store.commit_result(
            OnlyAgentToolCallResultV1(
                inline_plan.plan.tool_call_plan_fingerprint,
                OnlyAgentToolCallOutcome.FAILED,
                failure_code="AGENT_TOOL_CALL_FAILED",
            )
        )
    assert conflict.value.code == "AGENT_TOOL_CALL_RESULT_CONFLICT"


def test_tool_invalid_result_and_owning_reference_mismatch_fail_closed(tmp_path) -> None:
    context, _, tool, _, _, _, _, _, _ = _services(tmp_path)
    invalid_plan = _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 0)
    invalid = tool.record_invalid(invalid_plan)
    assert invalid.outcome is OnlyAgentToolCallOutcome.RESULT_INVALID
    assert invalid.failure_code == "AGENT_TOOL_RESULT_INVALID"
    next_plan = _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 1)
    mismatched = tool.record_inline_success(next_plan, {"request_id": REQUEST_ID, "result": "x"}, ())
    assert mismatched.outcome is OnlyAgentToolCallOutcome.RESULT_INVALID


def test_immutable_query_recovery_rejects_response_from_different_request(tmp_path) -> None:
    context, _, tool, _, _, _, owner, _, _ = _services(tmp_path)
    prepared = _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 0)
    recovered = tool.prepare_recovery(
        prepared.plan.tool_call_plan_fingerprint,
        current_workflow_manifest=context.resources[-1].canonical_payload,
    )
    result = tool.record_inline_success(recovered, {"request_id": "different", "result": "x"}, (owner,))
    assert result.outcome is OnlyAgentToolCallOutcome.RESULT_INVALID


def test_tool_recovery_requires_current_runtime_but_historical_plan_loads(tmp_path) -> None:
    context, _, tool, _, store, _, _, _, _ = _services(tmp_path)
    prepared = _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 0)
    mismatched = replace(
        context.resources[-1].canonical_payload,
        workflow_semantic_version="2.0.0",
        implementation_fingerprint="",
    )
    assert tool.load_plan_verified(prepared.plan.tool_call_plan_fingerprint) == prepared.plan
    with pytest.raises(OnlyAgentContextError) as blocked:
        tool.prepare_recovery(
            prepared.plan.tool_call_plan_fingerprint,
            current_workflow_manifest=mismatched,
        )
    assert blocked.value.code == "AGENT_WORKFLOW_RUNTIME_MISMATCH"
    assert not store.result_exists(prepared.plan.tool_call_plan_fingerprint)


def test_immutable_query_recovery_rejects_different_canonical_response(tmp_path) -> None:
    context, _, tool, _, _, _, owner, _, _ = _services(tmp_path)
    prepared = _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 0)
    recovered = tool.prepare_recovery(
        prepared.plan.tool_call_plan_fingerprint,
        current_workflow_manifest=context.resources[-1].canonical_payload,
    )
    result = tool.record_inline_success(recovered, {"request_id": REQUEST_ID, "result": "different"}, (owner,))
    assert result.outcome is OnlyAgentToolCallOutcome.RESULT_INVALID


@pytest.mark.parametrize(
    "tool_class",
    [
        OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
        OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE,
        OnlyAgentToolClass.RESEARCH_RUN_SUBMIT,
    ],
)
def test_legal_same_occurrence_tool_recovery_uses_no_new_budget(tmp_path, tool_class: OnlyAgentToolClass) -> None:
    context, _, tool, _, _, _, owner, _, _ = _services(tmp_path)
    command = COMMAND_ID if tool_class is OnlyAgentToolClass.RESEARCH_RUN_SUBMIT else None
    prepared = _prepare_tool(tool, context, tool_class, 0, command=command)
    before = tool.budget_consumed(context.session.session_fingerprint)
    with pytest.raises(OnlyAgentContextError) as duplicate_prepare:
        _prepare_tool(tool, context, tool_class, 0, command=command)
    assert duplicate_prepare.value.code == "AGENT_TOOL_CALL_PLAN_CONFLICT"
    recovered = tool.prepare_recovery(
        prepared.plan.tool_call_plan_fingerprint,
        current_workflow_manifest=context.resources[-1].canonical_payload,
    )
    assert recovered.recovery
    assert recovered.plan.product_command_id_or_idempotency_key == command
    tool.record_inline_success(recovered, {"request_id": REQUEST_ID, "result": "canonical"}, (owner,))
    assert tool.budget_consumed(context.session.session_fingerprint) == before


def test_mutable_observation_recovery_requires_new_plan_and_budget(tmp_path) -> None:
    context, _, tool, _, _, _, _, _, _ = _services(tmp_path)
    old = _prepare_tool(tool, context, OnlyAgentToolClass.RESEARCH_RUN_QUERY, 0)
    with pytest.raises(OnlyAgentContextError) as raised:
        tool.prepare_recovery(
            old.plan.tool_call_plan_fingerprint,
            current_workflow_manifest=context.resources[-1].canonical_payload,
        )
    assert raised.value.code == "AGENT_TOOL_MUTABLE_OBSERVATION_REQUIRES_NEW_PLAN"
    fresh = _prepare_tool(tool, context, OnlyAgentToolClass.RESEARCH_RUN_QUERY, 1)
    assert fresh.plan.tool_call_plan_fingerprint != old.plan.tool_call_plan_fingerprint
    assert tool.budget_consumed(context.session.session_fingerprint) == 2


def _manifest(root: Path, category: str, fingerprint: str) -> Path:
    return (
        root
        / "research"
        / "agent-orchestration"
        / category
        / "sha256"
        / fingerprint[:2]
        / fingerprint
        / "manifest.json"
    )


def _assert_formal_roundtrip(value, parser, fingerprint_field: str | None = None) -> None:  # type: ignore[no-untyped-def]
    reconstructed = parser(json.loads(only_canonical_json(value.to_dict())))
    assert reconstructed == value
    if fingerprint_field is not None:
        assert getattr(reconstructed, fingerprint_field) == getattr(value, fingerprint_field)


def test_formal_occurrence_values_are_closed_under_canonical_round_trip(tmp_path) -> None:
    context, model, tool, _, _, reference, owner, _, _ = _services(tmp_path)
    model_prepared = _prepare_model(model, context, reference)
    model_plan = model_prepared.plan
    model_result = model.record_returned(model_prepared, {"action": "PLAN"})
    tool_prepared = _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 0)
    tool_result = tool.record_inline_success(
        tool_prepared,
        {"request_id": REQUEST_ID, "result": "canonical"},
        (owner,),
    )
    setting = OnlyAgentModelSettingBindingV1("temperature", OnlyAgentModelSettingState.VALUE, "0")
    for value, parser, fingerprint_field in (
        (reference, OnlyAgentContextReferenceV1.from_dict, None),
        (setting, OnlyAgentModelSettingBindingV1.from_dict, None),
        (model_plan, OnlyAgentModelCallPlanV1.from_dict, "model_call_plan_fingerprint"),
        (model_result, OnlyAgentModelCallResultV1.from_dict, "model_call_result_fingerprint"),
        (tool_prepared.plan, OnlyAgentToolCallPlanV1.from_dict, "tool_call_plan_fingerprint"),
        (tool_result, OnlyAgentToolCallResultV1.from_dict, "tool_call_result_fingerprint"),
    ):
        _assert_formal_roundtrip(value, parser, fingerprint_field)


def test_occurrence_store_tamper_noncanonical_and_missing_object_fail_closed(tmp_path) -> None:
    context, model, _, store, _, reference, _, _, _ = _services(tmp_path)
    prepared = _prepare_model(model, context, reference)
    path = _manifest(tmp_path, "model-calls/plans", prepared.plan.model_call_plan_fingerprint)
    path.write_text(json.dumps(json.loads(path.read_text()), indent=2), encoding="utf-8")
    with pytest.raises(OnlyAgentContextError):
        store.load_plan_verified(prepared.plan.model_call_plan_fingerprint)


def test_tool_occurrence_store_tamper_and_symlink_fail_closed(tmp_path) -> None:
    context, _, tool, _, store, _, _, _, _ = _services(tmp_path)
    prepared = _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 0)
    path = _manifest(tmp_path, "tool-calls/plans", prepared.plan.tool_call_plan_fingerprint)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["operation_identity"] = "tampered.v1"
    path.write_text(only_canonical_json(payload), encoding="utf-8")
    with pytest.raises(OnlyAgentContextError):
        store.load_plan_verified(prepared.plan.tool_call_plan_fingerprint)

    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(OnlyAgentContextError) as raised:
        OnlyJsonAgentToolOccurrenceStore(linked).commit_plan(prepared.plan)
    assert raised.value.code == "AGENT_CONTEXT_UNSAFE_PATH"


def test_occurrence_wrong_locator_and_missing_object_fail_closed(tmp_path) -> None:
    context, model, _, store, _, reference, _, _, _ = _services(tmp_path)
    _prepare_model(model, context, reference)
    locator_fingerprint = only_canonical_fingerprint(
        {
            "domain": "onlyalpha.agent-occurrence-locator",
            "schema_version": 1,
            "locator_kind": "MODEL_PLAN_BY_SESSION_ORDINAL",
            "owner_fingerprint": context.session.session_fingerprint,
            "ordinal": 0,
        }
    )
    locator = _manifest(tmp_path, "model-calls/by-session-ordinal", locator_fingerprint)
    payload = json.loads(locator.read_text(encoding="utf-8"))
    payload["target_fingerprint"] = "9" * 64
    locator.write_text(only_canonical_json(payload), encoding="utf-8")
    with pytest.raises(OnlyAgentContextError):
        store.load_plan_by_session_ordinal_verified(context.session.session_fingerprint, 0)

    other_root = tmp_path / "missing"
    other_context, other_model, _, other_store, _, other_reference, _, _, _ = _services(other_root)
    other = _prepare_model(other_model, other_context, other_reference)
    object_dir = _manifest(other_root, "model-calls/plans", other.plan.model_call_plan_fingerprint).parent
    shutil.rmtree(object_dir)
    with pytest.raises(OnlyAgentContextError):
        other_store.budget_consumed(other_context.session.session_fingerprint)


def test_occurrence_identical_concurrency_converges_and_conflicts_have_one_locator(tmp_path) -> None:
    context, model, _, _, _, reference, _, _, _ = _services(tmp_path / "source")
    plan = _prepare_model(model, context, reference).plan
    race_root = tmp_path / "race"

    def commit_same(_index: int):  # type: ignore[no-untyped-def]
        return OnlyJsonAgentModelOccurrenceStore(race_root).commit_plan(plan).disposition

    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = tuple(executor.map(commit_same, range(8)))
    assert outcomes.count(OnlyAgentCommitDisposition.CREATED) == 1
    assert outcomes.count(OnlyAgentCommitDisposition.REUSED) == 7
    winner = OnlyJsonAgentModelOccurrenceStore(race_root)
    assert winner.load_plan_by_session_ordinal_verified(plan.agent_session_fingerprint, 0) == plan
    with pytest.raises(OnlyAgentContextError) as conflict:
        winner.commit_plan(replace(plan, provider_id="other", model_call_plan_fingerprint=""))
    assert conflict.value.code == "AGENT_OCCURRENCE_ORDINAL_CONFLICT"


def test_fresh_process_exact_loads_model_and_tool_plans_and_budget(tmp_path) -> None:
    context, model, tool, _, _, reference, _, _, _ = _services(tmp_path)
    model_plan = _prepare_model(model, context, reference).plan
    tool_plan = _prepare_tool(tool, context, OnlyAgentToolClass.RESEARCH_RUN_SUBMIT, 0, command=COMMAND_ID).plan
    script = """
import json, sys
from pathlib import Path
from onlyalpha.research.agent import OnlyAgentResearchBriefReferenceReadersV1, OnlyJsonAgentOrchestrationResourceStore, OnlyJsonAgentResearchBriefStore, OnlyJsonAgentSessionManifestStore
from onlyalpha.research.agent.occurrence_store import OnlyJsonAgentModelOccurrenceStore, OnlyJsonAgentToolOccurrenceStore
root = Path(sys.argv[1])
class Value:
    def __init__(self, **values): self.__dict__.update(values)
    @property
    def snapshot(self): return self
class External:
    def load(self): return json.loads((root / "external-authorities.json").read_text())
    def generation(self, fingerprint):
        if self.load()["catalog"] != fingerprint: raise LookupError(fingerprint)
        return Value(generation_fingerprint=fingerprint)
    def load_verified_table(self, fingerprint):
        if self.load()["dataset"] != fingerprint: raise LookupError(fingerprint)
        return Value(snapshot_fingerprint=fingerprint)
    def load_evaluation_context_verified(self, reference):
        if self.load()["evaluation"] != reference.to_dict(): raise LookupError(reference.evaluation_fingerprint)
        return Value(evaluation_kind=reference.evaluation_kind, evaluation_schema_version=reference.evaluation_schema_version, evaluation_fingerprint=reference.evaluation_fingerprint)
models = OnlyJsonAgentModelOccurrenceStore(root)
tools = OnlyJsonAgentToolOccurrenceStore(root)
model = models.load_plan_verified(sys.argv[2])
tool = tools.load_plan_verified(sys.argv[3])
external = External()
readers = OnlyAgentResearchBriefReferenceReadersV1(external, external, external)
resources = OnlyJsonAgentOrchestrationResourceStore(root)
briefs = OnlyJsonAgentResearchBriefStore(root, readers)
sessions = OnlyJsonAgentSessionManifestStore(root, briefs=briefs, resources=resources)
session = sessions.load_session_manifest_verified(model.agent_session_fingerprint)
contract = json.loads((root / "product-contract.json").read_text())
if contract["product_api_major"] != tool.product_api_major or contract["product_api_contract_fingerprint"] != tool.product_api_contract_fingerprint: raise RuntimeError("contract mismatch")
if "recovery_class" in tool.to_dict(): raise RuntimeError("Tool Plan duplicates Product recovery semantics")
recovery = contract["operations"][tool.operation_identity]["recovery_class"]
print(json.dumps({"contract": contract["product_api_contract_fingerprint"], "model": model.model_call_plan_fingerprint, "models_used": models.budget_consumed(model.agent_session_fingerprint), "recovery": recovery, "session": session.session.session_fingerprint, "tool": tool.tool_call_plan_fingerprint, "tools_used": tools.budget_consumed(tool.agent_session_fingerprint)}, sort_keys=True))
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            str(tmp_path),
            model_plan.model_call_plan_fingerprint,
            tool_plan.tool_call_plan_fingerprint,
        ],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "contract": CONTRACT,
        "model": model_plan.model_call_plan_fingerprint,
        "models_used": 1,
        "recovery": "IDEMPOTENT_COMMAND",
        "session": context.session.session_fingerprint,
        "tool": tool_plan.tool_call_plan_fingerprint,
        "tools_used": 1,
    }


def test_fresh_process_model_unknown_recovery_admits_exact_runtime_only(tmp_path) -> None:
    context, model, _, store, _, reference, _, _, _ = _services(tmp_path)
    same_runtime_plan = _prepare_model(model, context, reference, ordinal=0).plan
    mismatched_runtime_plan = _prepare_model(model, context, reference, ordinal=1).plan
    script = """
import json, sys
from dataclasses import replace
from pathlib import Path
from onlyalpha.research.agent import OnlyAgentContextReferenceV1, OnlyAgentModelOccurrenceServiceV1, OnlyAgentResearchBriefReferenceReadersV1, OnlyJsonAgentOrchestrationResourceStore, OnlyJsonAgentResearchBriefStore, OnlyJsonAgentSessionManifestStore
from onlyalpha.research.agent.occurrence_store import OnlyJsonAgentModelOccurrenceStore
root = Path(sys.argv[1])
class Value:
    def __init__(self, **values): self.__dict__.update(values)
    @property
    def snapshot(self): return self
class External:
    def load(self): return json.loads((root / "external-authorities.json").read_text())
    def generation(self, fingerprint):
        if self.load()["catalog"] != fingerprint: raise LookupError(fingerprint)
        return Value(generation_fingerprint=fingerprint)
    def load_verified_table(self, fingerprint):
        if self.load()["dataset"] != fingerprint: raise LookupError(fingerprint)
        return Value(snapshot_fingerprint=fingerprint)
    def load_evaluation_context_verified(self, reference):
        if self.load()["evaluation"] != reference.to_dict(): raise LookupError(reference.evaluation_fingerprint)
        return Value(evaluation_kind=reference.evaluation_kind, evaluation_schema_version=reference.evaluation_schema_version, evaluation_fingerprint=reference.evaluation_fingerprint)
class References:
    def verify_exact_reference(self, reference):
        if reference != OnlyAgentContextReferenceV1("CATALOG_GENERATION", 1, "a" * 64): raise LookupError(reference)
class Decisions:
    def load_decision_authorization_verified(self, fingerprint): raise LookupError(fingerprint)
    def load_model_retry_authorization_verified(self, fingerprint): raise LookupError(fingerprint)
external = External()
readers = OnlyAgentResearchBriefReferenceReadersV1(external, external, external)
resources = OnlyJsonAgentOrchestrationResourceStore(root)
briefs = OnlyJsonAgentResearchBriefStore(root, readers)
sessions = OnlyJsonAgentSessionManifestStore(root, briefs=briefs, resources=resources)
plan_store = OnlyJsonAgentModelOccurrenceStore(root)
same_plan = plan_store.load_plan_verified(sys.argv[2])
mismatched_plan = plan_store.load_plan_verified(sys.argv[3])
context = sessions.load_session_manifest_verified(same_plan.agent_session_fingerprint)
manifest = context.workflow_resource.canonical_payload
decisions = Decisions()
service = OnlyAgentModelOccurrenceServiceV1(sessions=sessions, resources=resources, references=References(), decisions=decisions, retry_authorizations=decisions, store=plan_store)
try:
    service.recover_outcome_unknown(mismatched_plan.model_call_plan_fingerprint, current_workflow_manifest=replace(manifest, workflow_semantic_version="2.0.0", implementation_fingerprint=""))
except Exception as exc:
    if getattr(exc, "code", None) != "AGENT_WORKFLOW_RUNTIME_MISMATCH": raise
else:
    raise RuntimeError("mismatched runtime published a Result")
result = service.recover_outcome_unknown(same_plan.model_call_plan_fingerprint, current_workflow_manifest=manifest)
print(result.model_call_result_fingerprint)
"""
    recovered = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            str(tmp_path),
            same_runtime_plan.model_call_plan_fingerprint,
            mismatched_runtime_plan.model_call_plan_fingerprint,
        ],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        capture_output=True,
        check=False,
    )
    assert recovered.returncode == 0, recovered.stderr
    assert not store.result_exists(mismatched_runtime_plan.model_call_plan_fingerprint)
    exact = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "from pathlib import Path; from onlyalpha.research.agent.occurrence_store import OnlyJsonAgentModelOccurrenceStore; import sys; print(OnlyJsonAgentModelOccurrenceStore(Path(sys.argv[1])).load_result_for_plan_verified(sys.argv[2]).model_call_result_fingerprint)",
            str(tmp_path),
            same_runtime_plan.model_call_plan_fingerprint,
        ],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        capture_output=True,
        check=False,
    )
    assert exact.returncode == 0, exact.stderr
    assert exact.stdout.strip() == recovered.stdout.strip()


def test_hermetic_plan_before_boundary_and_result_after_boundary(tmp_path) -> None:
    context, model, tool, model_store, tool_store, reference, owner, _, _ = _services(tmp_path)
    model_prepared = _prepare_model(model, context, reference)
    assert model_store.load_plan_verified(model_prepared.plan.model_call_plan_fingerprint) == model_prepared.plan
    model_result = model.record_returned(model_prepared, {"action": "PLAN"})
    assert model_store.load_result_for_plan_verified(model_prepared.plan.model_call_plan_fingerprint) == model_result
    tool_prepared = _prepare_tool(tool, context, OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY, 0)
    assert tool_store.load_plan_verified(tool_prepared.plan.tool_call_plan_fingerprint) == tool_prepared.plan
    tool_result = tool.record_inline_success(
        tool_prepared,
        {"request_id": REQUEST_ID, "result": "canonical"},
        (owner,),
    )
    assert tool_store.load_result_for_plan_verified(tool_prepared.plan.tool_call_plan_fingerprint) == tool_result
    assert not hasattr(tool_result, "catalog_authority")


def test_fresh_service_exact_verifies_complete_historical_occurrences(tmp_path) -> None:
    context, model, tool, _, _, reference, owner, response_reference, _ = _services(tmp_path)
    model_prepared = _prepare_model(model, context, reference)
    model_result = model.record_returned(model_prepared, {"action": "STOP"})
    tool_prepared = _prepare_tool(tool, context, OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY, 0)
    tool_result = tool.record_exact_reference_success(tool_prepared, response_reference, (owner,))

    _, fresh_model, fresh_tool, _, _, _, _, _, _ = _services(tmp_path)
    assert fresh_model.load_plan_verified(model_prepared.plan.model_call_plan_fingerprint) == model_prepared.plan
    assert fresh_model.load_result_verified(model_prepared.plan.model_call_plan_fingerprint) == model_result
    assert fresh_tool.load_plan_verified(tool_prepared.plan.tool_call_plan_fingerprint) == tool_prepared.plan
    assert fresh_tool.load_result_verified(tool_prepared.plan.tool_call_plan_fingerprint) == tool_result
