"""Narrow durable-before-side-effect services for Agent occurrences."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json

from .errors import OnlyAgentContextError
from .model import (
    OnlyAgentModelExecutionPolicyPayloadV1,
    OnlyAgentModelSettingSupport,
    OnlyAgentOrchestrationResourceKind,
    OnlyAgentRolePolicyPayloadV1,
    OnlyAgentSessionManifestV1,
    OnlyAgentStructuredOutputSchemaPayloadV1,
    OnlyAgentToolClass,
    OnlyAgentToolPolicyPayloadV1,
    OnlyAgentWorkflowImplementationManifestV1,
)
from .occurrence import (
    ONLYAGENT_STRICT_SCHEMA_DIALECT,
    ONLYAGENT_STRICT_SCHEMA_DIALECT_VERSION,
    OnlyAgentContextReferenceV1,
    OnlyAgentExactReferenceReader,
    OnlyAgentModelCallOutcome,
    OnlyAgentModelCallPlanV1,
    OnlyAgentModelCallResultV1,
    OnlyAgentModelSettingBindingV1,
    OnlyAgentModelSettingState,
    OnlyAgentObservedResponseStorageKind,
    OnlyAgentToolCallOutcome,
    OnlyAgentToolCallPlanV1,
    OnlyAgentToolCallResultV1,
    OnlyAgentToolRecoveryClass,
    _frozen_object,
    validate_agent_strict_schema,
    validate_agent_strict_value,
)
from .occurrence_store import OnlyJsonAgentModelOccurrenceStore, OnlyJsonAgentToolOccurrenceStore
from .store import OnlyAgentCommitDisposition
from .verification import OnlyAgentOrchestrationResourceReader, OnlyVerifiedAgentDecisionContextV1
from .workflow import admit_agent_workflow_runtime


class OnlyAgentSessionContextReader(Protocol):
    def load_session_manifest_verified(self, session_fingerprint: str) -> OnlyVerifiedAgentDecisionContextV1: ...


@dataclass(frozen=True, slots=True)
class OnlyAgentDecisionAuthorizationV1:
    decision_fingerprint: str
    agent_session_fingerprint: str
    workflow_implementation_fingerprint: str
    permitted_tool_classes: tuple[OnlyAgentToolClass, ...]
    permitted_operation_identities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OnlyAgentProductRequestSemanticProjectionV1:
    """Transient Product-owned projection used only for Tool-intent authorization."""

    operation_identity: str
    semantic_bindings: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.operation_identity or any(character.isspace() for character in self.operation_identity):
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        object.__setattr__(
            self,
            "semantic_bindings",
            _frozen_object(self.semantic_bindings, "semantic_bindings"),
        )


class OnlyAgentDecisionToolIntentVerifier(Protocol):
    def verify_historical_tool_intent(
        self,
        *,
        decision_fingerprint: str,
        tool_class: OnlyAgentToolClass,
        operation_identity: str,
        semantic_projection: OnlyAgentProductRequestSemanticProjectionV1,
        exact_identity_inputs: tuple[OnlyAgentContextReferenceV1, ...],
        tool_call_ordinal: int,
    ) -> None: ...

    def admit_new_tool_intent(
        self,
        *,
        decision_fingerprint: str,
        tool_class: OnlyAgentToolClass,
        operation_identity: str,
        semantic_projection: OnlyAgentProductRequestSemanticProjectionV1,
        exact_identity_inputs: tuple[OnlyAgentContextReferenceV1, ...],
        tool_call_ordinal: int,
    ) -> None: ...


class OnlyAgentDecisionOccurrenceReader(OnlyAgentDecisionToolIntentVerifier, Protocol):
    def load_decision_authorization_verified(self, decision_fingerprint: str) -> OnlyAgentDecisionAuthorizationV1: ...


@dataclass(frozen=True, slots=True)
class OnlyAgentProductOperationContractV1:
    product_api_major: int
    product_api_contract_fingerprint: str
    operation_identity: str
    tool_class: OnlyAgentToolClass
    recovery_class: OnlyAgentToolRecoveryClass
    request_schema: Mapping[str, object]
    response_schema: Mapping[str, object]
    requires_product_command_id: bool
    allowed_owning_reference_kinds: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.product_api_major, bool)
            or not isinstance(self.product_api_major, int)
            or self.product_api_major <= 0
            or len(self.product_api_contract_fingerprint) != 64
            or any(item not in "0123456789abcdef" for item in self.product_api_contract_fingerprint)
            or not self.operation_identity
            or any(item.isspace() for item in self.operation_identity)
            or not isinstance(self.tool_class, OnlyAgentToolClass)
            or not isinstance(self.recovery_class, OnlyAgentToolRecoveryClass)
            or not isinstance(self.request_schema, Mapping)
            or not isinstance(self.response_schema, Mapping)
            or not isinstance(self.requires_product_command_id, bool)
            or not isinstance(self.allowed_owning_reference_kinds, tuple)
            or any(
                not isinstance(item, str) or not item or any(character.isspace() for character in item)
                for item in self.allowed_owning_reference_kinds
            )
        ):
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        object.__setattr__(self, "request_schema", _frozen_object(self.request_schema, "request_schema"))
        object.__setattr__(self, "response_schema", _frozen_object(self.response_schema, "response_schema"))


class OnlyAgentProductApiContractReader(Protocol):
    def load_operation_verified(
        self,
        product_api_major: int,
        product_api_contract_fingerprint: str,
        operation_identity: str,
    ) -> OnlyAgentProductOperationContractV1: ...

    def verify_response_binding(
        self,
        plan: OnlyAgentToolCallPlanV1,
        canonical_response: Mapping[str, object],
        owning_authority_references: tuple[OnlyAgentContextReferenceV1, ...],
    ) -> None: ...

    def project_request_semantics_verified(
        self,
        *,
        product_api_major: int,
        product_api_contract_fingerprint: str,
        operation_identity: str,
        canonical_validated_request: Mapping[str, object],
    ) -> OnlyAgentProductRequestSemanticProjectionV1: ...


class OnlyAgentExactResponseReferenceReader(Protocol):
    def load_exact_response_verified(self, reference: OnlyAgentContextReferenceV1) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class OnlyPreparedAgentModelCallV1:
    plan: OnlyAgentModelCallPlanV1
    _current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1
    _service_token: object


@dataclass(frozen=True, slots=True)
class OnlyPreparedAgentToolCallV1:
    plan: OnlyAgentToolCallPlanV1
    recovery_class: OnlyAgentToolRecoveryClass
    recovery: bool
    _current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1
    _service_token: object


def _admit_occurrence_mutation(
    sessions: OnlyAgentSessionContextReader,
    *,
    session_fingerprint: str,
    current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1,
) -> OnlyVerifiedAgentDecisionContextV1:
    """Verify immutable Session history and exact current runtime before any new fact."""

    context = sessions.load_session_manifest_verified(session_fingerprint)
    admit_agent_workflow_runtime(context.workflow_resource, current_workflow_manifest)
    return context


def _role(
    context: OnlyVerifiedAgentDecisionContextV1, role_fingerprint: str, logical_role: str
) -> OnlyAgentRolePolicyPayloadV1:
    for resource in context.ordered_role_policy_resources:
        if resource.resource_fingerprint == role_fingerprint:
            role = resource.canonical_payload
            if isinstance(role, OnlyAgentRolePolicyPayloadV1) and role.logical_role_id == logical_role:
                return role
    raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Role Policy is not Session-bound")


def _verify_decision(
    reader: OnlyAgentDecisionOccurrenceReader,
    fingerprint: str,
    session: OnlyAgentSessionManifestV1,
) -> OnlyAgentDecisionAuthorizationV1:
    try:
        decision = reader.load_decision_authorization_verified(fingerprint)
    except Exception as exc:
        raise OnlyAgentContextError("AGENT_DECISION_REFERENCE_INVALID", fingerprint) from exc
    if (
        decision.decision_fingerprint != fingerprint
        or decision.agent_session_fingerprint != session.session_fingerprint
        or decision.workflow_implementation_fingerprint != session.agent_workflow_implementation_fingerprint
    ):
        raise OnlyAgentContextError("AGENT_DECISION_REFERENCE_INVALID", fingerprint)
    return decision


def _verify_supported_model_schema(resource: object) -> OnlyAgentStructuredOutputSchemaPayloadV1:
    if not isinstance(resource, OnlyAgentStructuredOutputSchemaPayloadV1):
        raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Schema resource payload is invalid")
    if (
        resource.schema_dialect != ONLYAGENT_STRICT_SCHEMA_DIALECT
        or resource.schema_dialect_version != ONLYAGENT_STRICT_SCHEMA_DIALECT_VERSION
        or resource.enum_semantics != "EXACT_DECLARED_ENUMS"
        or resource.reference_semantics != "EXACT_CONTEXT_IDENTITIES_ONLY"
    ):
        raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Structured schema dialect is unsupported")
    try:
        validate_agent_strict_schema(resource.exact_schema, root_type=resource.root_type)
    except Exception as exc:
        raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Structured schema is unsupported") from exc
    return resource


def _request_reference_closure(value: object, schema: Mapping[str, object]) -> tuple[OnlyAgentContextReferenceV1, ...]:
    reference_kind = schema.get("x-onlyalpha-reference-kind")
    if isinstance(reference_kind, str):
        return (
            OnlyAgentContextReferenceV1(
                reference_kind,
                cast(int, schema["x-onlyalpha-reference-schema-version"]),
                cast(str, value),
            ),
        )
    if schema["type"] == "object":
        request = cast(Mapping[str, object], value)
        properties = cast(Mapping[str, object], schema.get("properties", {}))
        return tuple(
            reference
            for key in sorted(request)
            for reference in _request_reference_closure(request[key], cast(Mapping[str, object], properties[key]))
        )
    if schema["type"] == "array":
        return tuple(
            reference
            for item in cast(tuple[object, ...], value)
            for reference in _request_reference_closure(item, cast(Mapping[str, object], schema["items"]))
        )
    return ()


def _verify_tool_request_identity_closure(
    *,
    validated_request: Mapping[str, object],
    request_schema: Mapping[str, object],
    identity_requirements: tuple[str, ...],
    exact_identity_inputs: tuple[OnlyAgentContextReferenceV1, ...],
) -> None:
    properties = cast(Mapping[str, object], request_schema.get("properties", {}))
    for requirement in identity_requirements:
        property_schema = properties.get(requirement)
        if requirement not in validated_request or not isinstance(property_schema, Mapping):
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", f"Missing identity input {requirement}")
        if (
            "x-onlyalpha-reference-kind" not in property_schema
            or "x-onlyalpha-reference-schema-version" not in property_schema
        ):
            raise OnlyAgentContextError(
                "AGENT_PRODUCT_API_CONTRACT_MISMATCH",
                f"Identity input {requirement} lacks typed Authority semantics",
            )
    derived = _request_reference_closure(validated_request, request_schema)
    if derived != exact_identity_inputs:
        raise OnlyAgentContextError(
            "AGENT_TOOL_CALL_PLAN_INVALID", "Request identity and exact reference closure differ"
        )


def _load_product_operation_contract(
    reader: OnlyAgentProductApiContractReader,
    *,
    product_api_major: int,
    product_api_contract_fingerprint: str,
    operation_identity: str,
    tool_class: OnlyAgentToolClass,
) -> OnlyAgentProductOperationContractV1:
    try:
        contract = reader.load_operation_verified(
            product_api_major, product_api_contract_fingerprint, operation_identity
        )
    except Exception as exc:
        raise OnlyAgentContextError("AGENT_PRODUCT_API_CONTRACT_MISMATCH", operation_identity) from exc
    if (
        not isinstance(contract, OnlyAgentProductOperationContractV1)
        or contract.product_api_major != product_api_major
        or contract.product_api_contract_fingerprint != product_api_contract_fingerprint
        or contract.operation_identity != operation_identity
        or contract.tool_class is not tool_class
    ):
        raise OnlyAgentContextError("AGENT_PRODUCT_API_CONTRACT_MISMATCH", operation_identity)
    return contract


class OnlyAgentModelOccurrenceServiceV1:
    def __init__(
        self,
        *,
        sessions: OnlyAgentSessionContextReader,
        resources: OnlyAgentOrchestrationResourceReader,
        references: OnlyAgentExactReferenceReader,
        decisions: OnlyAgentDecisionOccurrenceReader,
        store: OnlyJsonAgentModelOccurrenceStore,
    ) -> None:
        self._sessions = sessions
        self._resources = resources
        self._references = references
        self._decisions = decisions
        self._store = store
        self._token = object()

    def prepare_model_call(
        self,
        *,
        session_fingerprint: str,
        current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1,
        call_ordinal: int,
        logical_role: str,
        role_policy_fingerprint: str,
        provider_id: str,
        model_id: str,
        model_version: str,
        prompt_template_fingerprint: str,
        structured_output_schema_fingerprint: str,
        model_execution_policy_fingerprint: str,
        response_affecting_settings: tuple[OnlyAgentModelSettingBindingV1, ...],
        ordered_context_references: tuple[OnlyAgentContextReferenceV1, ...],
        parent_agent_decision_fingerprint: str | None = None,
        retry_of_plan_fingerprint: str | None = None,
    ) -> OnlyPreparedAgentModelCallV1:
        context = _admit_occurrence_mutation(
            self._sessions,
            session_fingerprint=session_fingerprint,
            current_workflow_manifest=current_workflow_manifest,
        )
        if retry_of_plan_fingerprint is not None:
            raise OnlyAgentContextError(
                "AGENT_POLICY_VIOLATION",
                "B3.4 V1 defines NO_AUTOMATIC_RETRY and no independent retry-authorization Authority is admitted",
            )
        role = _role(context, role_policy_fingerprint, logical_role)
        if prompt_template_fingerprint not in role.allowed_prompt_template_fingerprints:
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Prompt is not allowed by Role Policy")
        if structured_output_schema_fingerprint not in role.allowed_structured_output_schema_fingerprints:
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Schema is not allowed by Role Policy")
        if model_execution_policy_fingerprint not in role.allowed_model_execution_policy_fingerprints:
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Model Policy is not allowed by Role Policy")
        self._resources.load_resource_verified(
            OnlyAgentOrchestrationResourceKind.PROMPT_TEMPLATE, prompt_template_fingerprint
        )
        schema_resource = self._resources.load_resource_verified(
            OnlyAgentOrchestrationResourceKind.STRUCTURED_OUTPUT_SCHEMA, structured_output_schema_fingerprint
        )
        _verify_supported_model_schema(schema_resource.canonical_payload)
        policy_resource = self._resources.load_resource_verified(
            OnlyAgentOrchestrationResourceKind.MODEL_EXECUTION_POLICY, model_execution_policy_fingerprint
        )
        policy = policy_resource.canonical_payload
        if (
            not isinstance(policy, OnlyAgentModelExecutionPolicyPayloadV1)
            or not policy.no_fallback
            or policy.retry_semantics != "NO_AUTOMATIC_RETRY"
        ):
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Model Policy is invalid")
        self._verify_settings(policy, response_affecting_settings)
        if context.session.tool_policy_fingerprint != context.tool_policy_resource.resource_fingerprint:
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Session Tool Policy differs")
        for reference in ordered_context_references:
            try:
                self._references.verify_exact_reference(reference)
            except Exception as exc:
                raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Context reference is unresolved") from exc
        if parent_agent_decision_fingerprint is not None:
            _verify_decision(self._decisions, parent_agent_decision_fingerprint, context.session)
        if self._store.budget_consumed(session_fingerprint) >= context.research_brief.agent_budget.model_call_limit:
            raise OnlyAgentContextError("AGENT_BUDGET_EXHAUSTED", "Model call budget")
        plan = OnlyAgentModelCallPlanV1(
            session_fingerprint,
            call_ordinal,
            logical_role,
            role_policy_fingerprint,
            provider_id,
            model_id,
            model_version,
            prompt_template_fingerprint,
            structured_output_schema_fingerprint,
            context.session.tool_policy_fingerprint,
            model_execution_policy_fingerprint,
            response_affecting_settings,
            ordered_context_references,
            parent_agent_decision_fingerprint,
            retry_of_plan_fingerprint,
        )
        outcome = self._store.commit_plan(plan)
        if outcome.disposition is OnlyAgentCommitDisposition.REUSED:
            raise OnlyAgentContextError(
                "AGENT_MODEL_CALL_PLAN_CONFLICT",
                "Existing Model Plan must be recovered, never prepared for re-invocation",
            )
        exact = self._store.load_plan_verified(plan.model_call_plan_fingerprint)
        return OnlyPreparedAgentModelCallV1(exact, current_workflow_manifest, self._token)

    def record_returned(self, prepared: OnlyPreparedAgentModelCallV1, response: object) -> OnlyAgentModelCallResultV1:
        plan = self._require_prepared(prepared)
        schema_resource = self._resources.load_resource_verified(
            OnlyAgentOrchestrationResourceKind.STRUCTURED_OUTPUT_SCHEMA,
            plan.structured_output_schema_fingerprint,
        )
        schema = schema_resource.canonical_payload
        schema = _verify_supported_model_schema(schema)
        try:
            candidate = response
            raw: bytes
            if isinstance(response, bytes):
                raw = response
                candidate = json.loads(response)
            elif isinstance(response, str):
                raw = response.encode("utf-8")
                candidate = json.loads(response)
            else:
                raw = only_canonical_json(response).encode("utf-8")
            validated = validate_agent_strict_value(
                candidate,
                schema.exact_schema,
                allowed_context_references=plan.ordered_context_references,
            )
            if not isinstance(validated, Mapping):
                raise ValueError("Root output is not an object")
            result = OnlyAgentModelCallResultV1(
                plan.model_call_plan_fingerprint,
                OnlyAgentModelCallOutcome.RETURNED,
                validated_structured_output=cast(Mapping[str, object], validated),
            )
        except Exception:
            digest = hashlib.sha256(raw if "raw" in locals() else repr(response).encode("utf-8")).hexdigest()
            result = OnlyAgentModelCallResultV1(
                plan.model_call_plan_fingerprint,
                OnlyAgentModelCallOutcome.RESPONSE_INVALID,
                failure_code="AGENT_MODEL_RESPONSE_INVALID",
                response_digest=digest,
            )
        self._store.commit_result(result)
        return self._store.load_result_for_plan_verified(plan.model_call_plan_fingerprint)

    def record_failed(self, prepared: OnlyPreparedAgentModelCallV1) -> OnlyAgentModelCallResultV1:
        plan = self._require_prepared(prepared)
        result = OnlyAgentModelCallResultV1(
            plan.model_call_plan_fingerprint,
            OnlyAgentModelCallOutcome.FAILED,
            failure_code="AGENT_MODEL_CALL_FAILED",
        )
        self._store.commit_result(result)
        return result

    def recover_outcome_unknown(
        self,
        plan_fingerprint: str,
        *,
        current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1,
    ) -> OnlyAgentModelCallResultV1:
        plan = self.load_plan_verified(plan_fingerprint)
        if self._store.result_exists(plan_fingerprint):
            return self._store.load_result_for_plan_verified(plan_fingerprint)
        _admit_occurrence_mutation(
            self._sessions,
            session_fingerprint=plan.agent_session_fingerprint,
            current_workflow_manifest=current_workflow_manifest,
        )
        result = OnlyAgentModelCallResultV1(
            plan.model_call_plan_fingerprint,
            OnlyAgentModelCallOutcome.OUTCOME_UNKNOWN,
            failure_code="AGENT_MODEL_CALL_OUTCOME_UNKNOWN",
        )
        self._store.commit_result(result)
        return result

    def budget_consumed(self, session_fingerprint: str) -> int:
        return self._store.budget_consumed(session_fingerprint)

    def load_plan_verified(self, plan_fingerprint: str) -> OnlyAgentModelCallPlanV1:
        plan = self._store.load_plan_verified(plan_fingerprint)
        context = self._sessions.load_session_manifest_verified(plan.agent_session_fingerprint)
        role = _role(context, plan.role_policy_fingerprint, plan.logical_role)
        if (
            plan.prompt_template_fingerprint not in role.allowed_prompt_template_fingerprints
            or plan.structured_output_schema_fingerprint not in role.allowed_structured_output_schema_fingerprints
            or plan.model_execution_policy_fingerprint not in role.allowed_model_execution_policy_fingerprints
            or plan.tool_policy_fingerprint != context.session.tool_policy_fingerprint
        ):
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", plan_fingerprint)
        for kind, fingerprint in (
            (OnlyAgentOrchestrationResourceKind.PROMPT_TEMPLATE, plan.prompt_template_fingerprint),
            (OnlyAgentOrchestrationResourceKind.STRUCTURED_OUTPUT_SCHEMA, plan.structured_output_schema_fingerprint),
            (OnlyAgentOrchestrationResourceKind.MODEL_EXECUTION_POLICY, plan.model_execution_policy_fingerprint),
        ):
            self._resources.load_resource_verified(kind, fingerprint)
        schema_resource = self._resources.load_resource_verified(
            OnlyAgentOrchestrationResourceKind.STRUCTURED_OUTPUT_SCHEMA,
            plan.structured_output_schema_fingerprint,
        )
        _verify_supported_model_schema(schema_resource.canonical_payload)
        policy_resource = self._resources.load_resource_verified(
            OnlyAgentOrchestrationResourceKind.MODEL_EXECUTION_POLICY, plan.model_execution_policy_fingerprint
        )
        policy = policy_resource.canonical_payload
        if (
            not isinstance(policy, OnlyAgentModelExecutionPolicyPayloadV1)
            or policy.retry_semantics != "NO_AUTOMATIC_RETRY"
        ):
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", plan_fingerprint)
        self._verify_settings(policy, plan.response_affecting_settings)
        for reference in plan.ordered_context_references:
            self._references.verify_exact_reference(reference)
        if plan.parent_agent_decision_fingerprint is not None:
            _verify_decision(self._decisions, plan.parent_agent_decision_fingerprint, context.session)
        if plan.retry_of_plan_fingerprint is not None:
            self._verify_retry_lineage(
                plan.agent_session_fingerprint,
                plan.retry_of_plan_fingerprint,
            )
        return plan

    def load_result_verified(self, plan_fingerprint: str) -> OnlyAgentModelCallResultV1:
        plan = self.load_plan_verified(plan_fingerprint)
        result = self._store.load_result_for_plan_verified(plan_fingerprint)
        if result.outcome is OnlyAgentModelCallOutcome.RETURNED:
            schema_resource = self._resources.load_resource_verified(
                OnlyAgentOrchestrationResourceKind.STRUCTURED_OUTPUT_SCHEMA,
                plan.structured_output_schema_fingerprint,
            )
            schema = schema_resource.canonical_payload
            schema = _verify_supported_model_schema(schema)
            validated = validate_agent_strict_value(
                result.validated_structured_output,
                schema.exact_schema,
                allowed_context_references=plan.ordered_context_references,
            )
            if only_canonical_fingerprint(validated) != result.structured_output_fingerprint:
                raise OnlyAgentContextError("AGENT_MODEL_RESPONSE_INVALID", plan_fingerprint)
        return result

    def load_result_by_fingerprint_verified(self, result_fingerprint: str) -> OnlyAgentModelCallResultV1:
        result = self._store.load_result_verified(result_fingerprint)
        exact = self.load_result_verified(result.model_call_plan_fingerprint)
        if exact.model_call_result_fingerprint != result_fingerprint:
            raise OnlyAgentContextError("AGENT_MODEL_CALL_RESULT_INVALID", result_fingerprint)
        return exact

    def load_plan_by_session_ordinal_verified(self, session_fingerprint: str, ordinal: int) -> OnlyAgentModelCallPlanV1:
        plan = self._store.load_plan_by_session_ordinal_verified(session_fingerprint, ordinal)
        return self.load_plan_verified(plan.model_call_plan_fingerprint)

    def result_exists(self, plan_fingerprint: str) -> bool:
        return self._store.result_exists(plan_fingerprint)

    def _require_prepared(self, prepared: OnlyPreparedAgentModelCallV1) -> OnlyAgentModelCallPlanV1:
        if not isinstance(prepared, OnlyPreparedAgentModelCallV1) or prepared._service_token is not self._token:
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Invocation was not prepared by this service")
        exact = self._store.load_plan_verified(prepared.plan.model_call_plan_fingerprint)
        if exact != prepared.plan or self._store.result_exists(exact.model_call_plan_fingerprint):
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_CONFLICT", exact.model_call_plan_fingerprint)
        _admit_occurrence_mutation(
            self._sessions,
            session_fingerprint=exact.agent_session_fingerprint,
            current_workflow_manifest=prepared._current_workflow_manifest,
        )
        return exact

    def _verify_retry_lineage(
        self,
        session_fingerprint: str,
        retry_of: str,
    ) -> None:
        seen: set[str] = set()
        current: str | None = retry_of
        while current is not None:
            if current in seen:
                raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Retry lineage cycle")
            seen.add(current)
            prior = self._store.load_plan_verified(current)
            if prior.agent_session_fingerprint != session_fingerprint or not self._store.result_exists(current):
                raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Retry lineage is not terminal in Session")
            result = self._store.load_result_for_plan_verified(current)
            if current == retry_of and result.outcome is not OnlyAgentModelCallOutcome.OUTCOME_UNKNOWN:
                raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Prior outcome is not retry-eligible")
            current = prior.retry_of_plan_fingerprint

    @staticmethod
    def _verify_settings(
        policy: OnlyAgentModelExecutionPolicyPayloadV1,
        settings: tuple[OnlyAgentModelSettingBindingV1, ...],
    ) -> None:
        by_name = {item.setting_name: item for item in settings}
        if len(by_name) != len(settings) or set(by_name) != {item.setting_name for item in policy.setting_rules}:
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Model setting closure differs")
        for rule in policy.setting_rules:
            state = by_name[rule.setting_name].state
            legal = {
                OnlyAgentModelSettingSupport.REQUIRED: {OnlyAgentModelSettingState.VALUE},
                OnlyAgentModelSettingSupport.SUPPORTED: {
                    OnlyAgentModelSettingState.VALUE,
                    OnlyAgentModelSettingState.ABSENT,
                },
                OnlyAgentModelSettingSupport.ABSENT: {OnlyAgentModelSettingState.UNSUPPORTED},
            }[rule.support]
            if state not in legal:
                raise OnlyAgentContextError(
                    "AGENT_MODEL_CALL_PLAN_INVALID", f"Setting {rule.setting_name} state differs"
                )


class OnlyAgentToolOccurrenceServiceV1:
    def __init__(
        self,
        *,
        sessions: OnlyAgentSessionContextReader,
        decisions: OnlyAgentDecisionOccurrenceReader,
        product_contracts: OnlyAgentProductApiContractReader,
        references: OnlyAgentExactReferenceReader,
        response_references: OnlyAgentExactResponseReferenceReader,
        store: OnlyJsonAgentToolOccurrenceStore,
    ) -> None:
        self._sessions = sessions
        self._decisions = decisions
        self._contracts = product_contracts
        self._references = references
        self._response_references = response_references
        self._store = store
        self._token = object()

    def prepare_tool_call(
        self,
        *,
        session_fingerprint: str,
        current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1,
        tool_call_ordinal: int,
        authorizing_agent_decision_fingerprint: str,
        tool_class: OnlyAgentToolClass,
        product_api_major: int,
        product_api_contract_fingerprint: str,
        operation_identity: str,
        canonical_request: Mapping[str, object],
        exact_identity_inputs: tuple[OnlyAgentContextReferenceV1, ...],
        product_command_id_or_idempotency_key: str | None,
    ) -> OnlyPreparedAgentToolCallV1:
        context = _admit_occurrence_mutation(
            self._sessions,
            session_fingerprint=session_fingerprint,
            current_workflow_manifest=current_workflow_manifest,
        )
        decision = _verify_decision(self._decisions, authorizing_agent_decision_fingerprint, context.session)
        if (
            tool_class not in decision.permitted_tool_classes
            or operation_identity not in decision.permitted_operation_identities
        ):
            raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
        policy = context.tool_policy_resource.canonical_payload
        if not isinstance(policy, OnlyAgentToolPolicyPayloadV1):
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", "Tool Policy is invalid")
        constraints = tuple(
            item for item in policy.operation_constraints if item.operation_identity == operation_identity
        )
        if (
            tool_class not in policy.allowed_tool_classes
            or len(constraints) != 1
            or constraints[0].tool_class is not tool_class
        ):
            raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)
        contract = _load_product_operation_contract(
            self._contracts,
            product_api_major=product_api_major,
            product_api_contract_fingerprint=product_api_contract_fingerprint,
            operation_identity=operation_identity,
            tool_class=tool_class,
        )
        try:
            validate_agent_strict_schema(contract.request_schema, root_type="object")
            validate_agent_strict_schema(contract.response_schema, root_type="object")
        except Exception as exc:
            raise OnlyAgentContextError(
                "AGENT_PRODUCT_API_CONTRACT_MISMATCH", "Product request/response schema is unsupported"
            ) from exc
        if contract.requires_product_command_id != (product_command_id_or_idempotency_key is not None):
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", "Product Command identity requirement differs")
        try:
            validated = validate_agent_strict_value(
                canonical_request,
                contract.request_schema,
                allowed_context_references=exact_identity_inputs,
            )
        except Exception as exc:
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", "Request is not canonical") from exc
        if not isinstance(validated, Mapping):
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", "Request root must be an object")
        _verify_tool_request_identity_closure(
            validated_request=cast(Mapping[str, object], validated),
            request_schema=contract.request_schema,
            identity_requirements=constraints[0].identity_requirements,
            exact_identity_inputs=exact_identity_inputs,
        )
        for reference in exact_identity_inputs:
            try:
                self._references.verify_exact_reference(reference)
            except Exception as exc:
                raise OnlyAgentContextError(
                    "AGENT_TOOL_CALL_PLAN_INVALID", "Exact identity input is unresolved"
                ) from exc
        try:
            projection = self._contracts.project_request_semantics_verified(
                product_api_major=product_api_major,
                product_api_contract_fingerprint=product_api_contract_fingerprint,
                operation_identity=operation_identity,
                canonical_validated_request=cast(Mapping[str, object], validated),
            )
            self._decisions.admit_new_tool_intent(
                decision_fingerprint=decision.decision_fingerprint,
                tool_class=tool_class,
                operation_identity=operation_identity,
                semantic_projection=projection,
                exact_identity_inputs=exact_identity_inputs,
                tool_call_ordinal=tool_call_ordinal,
            )
        except OnlyAgentContextError:
            raise
        except Exception as exc:
            raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity) from exc
        if self._store.budget_consumed(session_fingerprint) >= context.research_brief.agent_budget.tool_call_limit:
            raise OnlyAgentContextError("AGENT_BUDGET_EXHAUSTED", "Tool call budget")
        plan = OnlyAgentToolCallPlanV1(
            session_fingerprint,
            tool_call_ordinal,
            authorizing_agent_decision_fingerprint,
            tool_class,
            product_api_major,
            product_api_contract_fingerprint,
            operation_identity,
            cast(Mapping[str, object], validated),
            exact_identity_inputs=exact_identity_inputs,
            product_command_id_or_idempotency_key=product_command_id_or_idempotency_key,
            tool_policy_fingerprint=context.session.tool_policy_fingerprint,
        )
        outcome = self._store.commit_plan(plan)
        if outcome.disposition is OnlyAgentCommitDisposition.REUSED:
            raise OnlyAgentContextError(
                "AGENT_TOOL_CALL_PLAN_CONFLICT",
                "Existing Tool Plan must use its recovery classification",
            )
        return OnlyPreparedAgentToolCallV1(
            self._store.load_plan_verified(plan.tool_call_plan_fingerprint),
            contract.recovery_class,
            False,
            current_workflow_manifest,
            self._token,
        )

    def prepare_recovery(
        self,
        plan_fingerprint: str,
        *,
        current_workflow_manifest: OnlyAgentWorkflowImplementationManifestV1,
    ) -> OnlyPreparedAgentToolCallV1:
        plan = self.load_plan_verified(plan_fingerprint)
        if self._store.result_exists(plan_fingerprint):
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_CONFLICT", "Tool occurrence is terminal")
        _admit_occurrence_mutation(
            self._sessions,
            session_fingerprint=plan.agent_session_fingerprint,
            current_workflow_manifest=current_workflow_manifest,
        )
        contract = _load_product_operation_contract(
            self._contracts,
            product_api_major=plan.product_api_major,
            product_api_contract_fingerprint=plan.product_api_contract_fingerprint,
            operation_identity=plan.operation_identity,
            tool_class=plan.tool_class,
        )
        recovery_class = contract.recovery_class
        if recovery_class is OnlyAgentToolRecoveryClass.MUTABLE_OBSERVATION_QUERY:
            raise OnlyAgentContextError("AGENT_TOOL_MUTABLE_OBSERVATION_REQUIRES_NEW_PLAN", plan_fingerprint)
        if (
            recovery_class is OnlyAgentToolRecoveryClass.IDEMPOTENT_COMMAND
            and plan.product_command_id_or_idempotency_key is None
        ):
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", "Command identity is absent")
        return OnlyPreparedAgentToolCallV1(plan, recovery_class, True, current_workflow_manifest, self._token)

    def record_inline_success(
        self,
        prepared: OnlyPreparedAgentToolCallV1,
        response: Mapping[str, object],
        owning_authority_references: tuple[OnlyAgentContextReferenceV1, ...],
    ) -> OnlyAgentToolCallResultV1:
        plan, contract = self._require_prepared(prepared)
        try:
            validated = validate_agent_strict_value(response, contract.response_schema)
            if not isinstance(validated, Mapping):
                raise ValueError("Response root must be an object")
            self._verify_owning_references(contract, owning_authority_references)
            self._contracts.verify_response_binding(
                plan,
                cast(Mapping[str, object], validated),
                owning_authority_references,
            )
        except Exception:
            return self._commit_invalid(plan)
        fingerprint = only_canonical_fingerprint(validated)
        result = OnlyAgentToolCallResultV1(
            plan.tool_call_plan_fingerprint,
            OnlyAgentToolCallOutcome.SUCCEEDED,
            OnlyAgentObservedResponseStorageKind.INLINE_CANONICAL_RESPONSE,
            cast(Mapping[str, object], validated),
            canonical_response_fingerprint=fingerprint,
            owning_authority_references=owning_authority_references,
        )
        self._store.commit_result(result)
        return result

    def record_exact_reference_success(
        self,
        prepared: OnlyPreparedAgentToolCallV1,
        response_reference: OnlyAgentContextReferenceV1,
        owning_authority_references: tuple[OnlyAgentContextReferenceV1, ...],
    ) -> OnlyAgentToolCallResultV1:
        plan, contract = self._require_prepared(prepared)
        try:
            response = self._response_references.load_exact_response_verified(response_reference)
            validated = validate_agent_strict_value(response, contract.response_schema)
            if not isinstance(validated, Mapping):
                raise ValueError("Response root must be an object")
            self._verify_owning_references(contract, owning_authority_references)
            self._contracts.verify_response_binding(plan, validated, owning_authority_references)
        except Exception:
            return self._commit_invalid(plan)
        result = OnlyAgentToolCallResultV1(
            plan.tool_call_plan_fingerprint,
            OnlyAgentToolCallOutcome.SUCCEEDED,
            OnlyAgentObservedResponseStorageKind.EXACT_IMMUTABLE_RESPONSE_REFERENCE,
            exact_immutable_response_reference=response_reference,
            canonical_response_fingerprint=only_canonical_fingerprint(response),
            owning_authority_references=owning_authority_references,
        )
        self._store.commit_result(result)
        return result

    def record_failed(self, prepared: OnlyPreparedAgentToolCallV1) -> OnlyAgentToolCallResultV1:
        plan, _ = self._require_prepared(prepared)
        result = OnlyAgentToolCallResultV1(
            plan.tool_call_plan_fingerprint,
            OnlyAgentToolCallOutcome.FAILED,
            failure_code="AGENT_TOOL_CALL_FAILED",
        )
        self._store.commit_result(result)
        return result

    def record_invalid(self, prepared: OnlyPreparedAgentToolCallV1) -> OnlyAgentToolCallResultV1:
        plan, _ = self._require_prepared(prepared)
        return self._commit_invalid(plan)

    def _commit_invalid(self, plan: OnlyAgentToolCallPlanV1) -> OnlyAgentToolCallResultV1:
        result = OnlyAgentToolCallResultV1(
            plan.tool_call_plan_fingerprint,
            OnlyAgentToolCallOutcome.RESULT_INVALID,
            failure_code="AGENT_TOOL_RESULT_INVALID",
        )
        self._store.commit_result(result)
        return result

    def budget_consumed(self, session_fingerprint: str) -> int:
        return self._store.budget_consumed(session_fingerprint)

    def recovery_class(self, plan_fingerprint: str) -> OnlyAgentToolRecoveryClass:
        plan = self.load_plan_verified(plan_fingerprint)
        return _load_product_operation_contract(
            self._contracts,
            product_api_major=plan.product_api_major,
            product_api_contract_fingerprint=plan.product_api_contract_fingerprint,
            operation_identity=plan.operation_identity,
            tool_class=plan.tool_class,
        ).recovery_class

    def load_plan_verified(self, plan_fingerprint: str) -> OnlyAgentToolCallPlanV1:
        plan = self._store.load_plan_verified(plan_fingerprint)
        context = self._sessions.load_session_manifest_verified(plan.agent_session_fingerprint)
        decision = _verify_decision(self._decisions, plan.authorizing_agent_decision_fingerprint, context.session)
        policy = context.tool_policy_resource.canonical_payload
        if (
            not isinstance(policy, OnlyAgentToolPolicyPayloadV1)
            or plan.tool_policy_fingerprint != context.session.tool_policy_fingerprint
        ):
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", plan_fingerprint)
        constraints = tuple(
            item for item in policy.operation_constraints if item.operation_identity == plan.operation_identity
        )
        if (
            plan.tool_class not in decision.permitted_tool_classes
            or plan.operation_identity not in decision.permitted_operation_identities
            or len(constraints) != 1
            or constraints[0].tool_class is not plan.tool_class
        ):
            raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", plan.operation_identity)
        contract = _load_product_operation_contract(
            self._contracts,
            product_api_major=plan.product_api_major,
            product_api_contract_fingerprint=plan.product_api_contract_fingerprint,
            operation_identity=plan.operation_identity,
            tool_class=plan.tool_class,
        )
        try:
            validate_agent_strict_schema(contract.request_schema, root_type="object")
            validate_agent_strict_schema(contract.response_schema, root_type="object")
            validated = validate_agent_strict_value(
                plan.canonical_validated_request,
                contract.request_schema,
                allowed_context_references=plan.exact_identity_inputs,
            )
        except Exception as exc:
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", plan_fingerprint) from exc
        if only_canonical_fingerprint(validated) != plan.canonical_request_fingerprint:
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", plan_fingerprint)
        _verify_tool_request_identity_closure(
            validated_request=cast(Mapping[str, object], validated),
            request_schema=contract.request_schema,
            identity_requirements=constraints[0].identity_requirements,
            exact_identity_inputs=plan.exact_identity_inputs,
        )
        for reference in plan.exact_identity_inputs:
            self._references.verify_exact_reference(reference)
        try:
            projection = self._contracts.project_request_semantics_verified(
                product_api_major=plan.product_api_major,
                product_api_contract_fingerprint=plan.product_api_contract_fingerprint,
                operation_identity=plan.operation_identity,
                canonical_validated_request=cast(Mapping[str, object], validated),
            )
            self._decisions.verify_historical_tool_intent(
                decision_fingerprint=decision.decision_fingerprint,
                tool_class=plan.tool_class,
                operation_identity=plan.operation_identity,
                semantic_projection=projection,
                exact_identity_inputs=plan.exact_identity_inputs,
                tool_call_ordinal=plan.tool_call_ordinal,
            )
        except OnlyAgentContextError:
            raise
        except Exception as exc:
            raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", plan.operation_identity) from exc
        return plan

    def load_result_verified(self, plan_fingerprint: str) -> OnlyAgentToolCallResultV1:
        plan = self.load_plan_verified(plan_fingerprint)
        result = self._store.load_result_for_plan_verified(plan_fingerprint)
        contract = _load_product_operation_contract(
            self._contracts,
            product_api_major=plan.product_api_major,
            product_api_contract_fingerprint=plan.product_api_contract_fingerprint,
            operation_identity=plan.operation_identity,
            tool_class=plan.tool_class,
        )
        if result.outcome is OnlyAgentToolCallOutcome.SUCCEEDED:
            self._verify_owning_references(contract, result.owning_authority_references)
            if result.exact_immutable_response_reference is not None:
                response = self._response_references.load_exact_response_verified(
                    result.exact_immutable_response_reference
                )
            else:
                response = cast(Mapping[str, object], result.canonical_validated_response)
            validated = validate_agent_strict_value(response, contract.response_schema)
            if not isinstance(validated, Mapping):
                raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", plan_fingerprint)
            try:
                self._contracts.verify_response_binding(plan, validated, result.owning_authority_references)
            except Exception as exc:
                raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", "Product response binding differs") from exc
            if only_canonical_fingerprint(validated) != result.canonical_response_fingerprint:
                raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", plan_fingerprint)
        return result

    def load_result_by_fingerprint_verified(self, result_fingerprint: str) -> OnlyAgentToolCallResultV1:
        result = self._store.load_result_verified(result_fingerprint)
        exact = self.load_result_verified(result.tool_call_plan_fingerprint)
        if exact.tool_call_result_fingerprint != result_fingerprint:
            raise OnlyAgentContextError("AGENT_TOOL_CALL_RESULT_INVALID", result_fingerprint)
        return exact

    def load_plan_by_session_ordinal_verified(self, session_fingerprint: str, ordinal: int) -> OnlyAgentToolCallPlanV1:
        plan = self._store.load_plan_by_session_ordinal_verified(session_fingerprint, ordinal)
        return self.load_plan_verified(plan.tool_call_plan_fingerprint)

    def result_exists(self, plan_fingerprint: str) -> bool:
        return self._store.result_exists(plan_fingerprint)

    def _require_prepared(
        self, prepared: OnlyPreparedAgentToolCallV1
    ) -> tuple[OnlyAgentToolCallPlanV1, OnlyAgentProductOperationContractV1]:
        if not isinstance(prepared, OnlyPreparedAgentToolCallV1) or prepared._service_token is not self._token:
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", "Invocation was not prepared by this service")
        plan = self._store.load_plan_verified(prepared.plan.tool_call_plan_fingerprint)
        if plan != prepared.plan or self._store.result_exists(plan.tool_call_plan_fingerprint):
            raise OnlyAgentContextError("AGENT_TOOL_CALL_RESULT_CONFLICT", plan.tool_call_plan_fingerprint)
        contract = _load_product_operation_contract(
            self._contracts,
            product_api_major=plan.product_api_major,
            product_api_contract_fingerprint=plan.product_api_contract_fingerprint,
            operation_identity=plan.operation_identity,
            tool_class=plan.tool_class,
        )
        if contract.recovery_class is not prepared.recovery_class or contract.tool_class is not plan.tool_class:
            raise OnlyAgentContextError("AGENT_PRODUCT_API_CONTRACT_MISMATCH", plan.operation_identity)
        _admit_occurrence_mutation(
            self._sessions,
            session_fingerprint=plan.agent_session_fingerprint,
            current_workflow_manifest=prepared._current_workflow_manifest,
        )
        return plan, contract

    def _verify_owning_references(
        self,
        contract: OnlyAgentProductOperationContractV1,
        references: tuple[OnlyAgentContextReferenceV1, ...],
    ) -> None:
        if tuple(item.reference_kind for item in references) != contract.allowed_owning_reference_kinds:
            raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", "Owning Authority reference closure differs")
        for reference in references:
            try:
                self._references.verify_exact_reference(reference)
            except Exception as exc:
                raise OnlyAgentContextError(
                    "AGENT_TOOL_RESULT_INVALID", "Owning Authority reference is unresolved"
                ) from exc


__all__ = [name for name in globals() if name.startswith(("OnlyAgent", "OnlyPreparedAgent"))]
