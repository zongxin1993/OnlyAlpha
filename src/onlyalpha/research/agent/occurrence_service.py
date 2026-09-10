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


class OnlyAgentDecisionOccurrenceReader(Protocol):
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
            or any(
                not item or any(character.isspace() for character in item)
                for item in self.allowed_owning_reference_kinds
            )
        ):
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")


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


class OnlyAgentExactResponseReferenceReader(Protocol):
    def load_exact_response_verified(self, reference: OnlyAgentContextReferenceV1) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class OnlyPreparedAgentModelCallV1:
    plan: OnlyAgentModelCallPlanV1
    _service_token: object


@dataclass(frozen=True, slots=True)
class OnlyPreparedAgentToolCallV1:
    plan: OnlyAgentToolCallPlanV1
    recovery: bool
    _service_token: object


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
        context = self._sessions.load_session_manifest_verified(session_fingerprint)
        admit_agent_workflow_runtime(context.workflow_resource, current_workflow_manifest)
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
        if not isinstance(policy, OnlyAgentModelExecutionPolicyPayloadV1) or not policy.no_fallback:
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
        if retry_of_plan_fingerprint is not None:
            self._verify_retry(session_fingerprint, retry_of_plan_fingerprint, policy)
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
        return OnlyPreparedAgentModelCallV1(exact, self._token)

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

    def recover_outcome_unknown(self, plan_fingerprint: str) -> OnlyAgentModelCallResultV1:
        plan = self.load_plan_verified(plan_fingerprint)
        if self._store.result_exists(plan_fingerprint):
            return self._store.load_result_for_plan_verified(plan_fingerprint)
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
        if not isinstance(policy, OnlyAgentModelExecutionPolicyPayloadV1):
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", plan_fingerprint)
        self._verify_settings(policy, plan.response_affecting_settings)
        for reference in plan.ordered_context_references:
            self._references.verify_exact_reference(reference)
        if plan.parent_agent_decision_fingerprint is not None:
            _verify_decision(self._decisions, plan.parent_agent_decision_fingerprint, context.session)
        if plan.retry_of_plan_fingerprint is not None:
            self._verify_retry(plan.agent_session_fingerprint, plan.retry_of_plan_fingerprint, policy)
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

    def _require_prepared(self, prepared: OnlyPreparedAgentModelCallV1) -> OnlyAgentModelCallPlanV1:
        if not isinstance(prepared, OnlyPreparedAgentModelCallV1) or prepared._service_token is not self._token:
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Invocation was not prepared by this service")
        exact = self._store.load_plan_verified(prepared.plan.model_call_plan_fingerprint)
        if exact != prepared.plan or self._store.result_exists(exact.model_call_plan_fingerprint):
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_CONFLICT", exact.model_call_plan_fingerprint)
        return exact

    def _verify_retry(
        self, session_fingerprint: str, retry_of: str, policy: OnlyAgentModelExecutionPolicyPayloadV1
    ) -> None:
        if policy.retry_semantics == "FORBIDDEN":
            raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Retry is forbidden")
        seen: set[str] = set()
        current: str | None = retry_of
        while current is not None:
            if current in seen:
                raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Retry lineage cycle")
            seen.add(current)
            prior = self._store.load_plan_verified(current)
            if prior.agent_session_fingerprint != session_fingerprint or not self._store.result_exists(current):
                raise OnlyAgentContextError("AGENT_MODEL_CALL_PLAN_INVALID", "Retry lineage is not terminal in Session")
            self._store.load_result_for_plan_verified(current)
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
        context = self._sessions.load_session_manifest_verified(session_fingerprint)
        admit_agent_workflow_runtime(context.workflow_resource, current_workflow_manifest)
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
        try:
            contract = self._contracts.load_operation_verified(
                product_api_major, product_api_contract_fingerprint, operation_identity
            )
        except Exception as exc:
            raise OnlyAgentContextError("AGENT_PRODUCT_API_CONTRACT_MISMATCH", operation_identity) from exc
        if (
            contract.product_api_major != product_api_major
            or contract.product_api_contract_fingerprint != product_api_contract_fingerprint
            or contract.operation_identity != operation_identity
            or contract.tool_class is not tool_class
        ):
            raise OnlyAgentContextError("AGENT_PRODUCT_API_CONTRACT_MISMATCH", operation_identity)
        if contract.requires_product_command_id != (product_command_id_or_idempotency_key is not None):
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", "Product Command identity requirement differs")
        try:
            validated = validate_agent_strict_value(canonical_request, contract.request_schema)
        except Exception as exc:
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", "Request is not canonical") from exc
        if not isinstance(validated, Mapping):
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", "Request root must be an object")
        for requirement in constraints[0].identity_requirements:
            if requirement not in validated:
                raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", f"Missing identity input {requirement}")
        for reference in exact_identity_inputs:
            try:
                self._references.verify_exact_reference(reference)
            except Exception as exc:
                raise OnlyAgentContextError(
                    "AGENT_TOOL_CALL_PLAN_INVALID", "Exact identity input is unresolved"
                ) from exc
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
            contract.recovery_class,
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
            self._store.load_plan_verified(plan.tool_call_plan_fingerprint), False, self._token
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
        context = self._sessions.load_session_manifest_verified(plan.agent_session_fingerprint)
        admit_agent_workflow_runtime(context.workflow_resource, current_workflow_manifest)
        if plan.recovery_class is OnlyAgentToolRecoveryClass.MUTABLE_OBSERVATION_QUERY:
            raise OnlyAgentContextError("AGENT_TOOL_MUTABLE_OBSERVATION_REQUIRES_NEW_PLAN", plan_fingerprint)
        if (
            plan.recovery_class is OnlyAgentToolRecoveryClass.IDEMPOTENT_COMMAND
            and plan.product_command_id_or_idempotency_key is None
        ):
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", "Command identity is absent")
        contract = self._contracts.load_operation_verified(
            plan.product_api_major, plan.product_api_contract_fingerprint, plan.operation_identity
        )
        if contract.recovery_class is not plan.recovery_class:
            raise OnlyAgentContextError("AGENT_PRODUCT_API_CONTRACT_MISMATCH", plan.operation_identity)
        return OnlyPreparedAgentToolCallV1(plan, True, self._token)

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
        contract = self._contracts.load_operation_verified(
            plan.product_api_major, plan.product_api_contract_fingerprint, plan.operation_identity
        )
        if contract.tool_class is not plan.tool_class or contract.recovery_class is not plan.recovery_class:
            raise OnlyAgentContextError("AGENT_PRODUCT_API_CONTRACT_MISMATCH", plan.operation_identity)
        validated = validate_agent_strict_value(plan.canonical_validated_request, contract.request_schema)
        if only_canonical_fingerprint(validated) != plan.canonical_request_fingerprint:
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", plan_fingerprint)
        for reference in plan.exact_identity_inputs:
            self._references.verify_exact_reference(reference)
        return plan

    def load_result_verified(self, plan_fingerprint: str) -> OnlyAgentToolCallResultV1:
        plan = self.load_plan_verified(plan_fingerprint)
        result = self._store.load_result_for_plan_verified(plan_fingerprint)
        contract = self._contracts.load_operation_verified(
            plan.product_api_major, plan.product_api_contract_fingerprint, plan.operation_identity
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

    def _require_prepared(
        self, prepared: OnlyPreparedAgentToolCallV1
    ) -> tuple[OnlyAgentToolCallPlanV1, OnlyAgentProductOperationContractV1]:
        if not isinstance(prepared, OnlyPreparedAgentToolCallV1) or prepared._service_token is not self._token:
            raise OnlyAgentContextError("AGENT_TOOL_CALL_PLAN_INVALID", "Invocation was not prepared by this service")
        plan = self._store.load_plan_verified(prepared.plan.tool_call_plan_fingerprint)
        if plan != prepared.plan or self._store.result_exists(plan.tool_call_plan_fingerprint):
            raise OnlyAgentContextError("AGENT_TOOL_CALL_RESULT_CONFLICT", plan.tool_call_plan_fingerprint)
        contract = self._contracts.load_operation_verified(
            plan.product_api_major, plan.product_api_contract_fingerprint, plan.operation_identity
        )
        if contract.recovery_class is not plan.recovery_class or contract.tool_class is not plan.tool_class:
            raise OnlyAgentContextError("AGENT_PRODUCT_API_CONTRACT_MISMATCH", plan.operation_identity)
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
