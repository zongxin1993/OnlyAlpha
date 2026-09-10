"""Immutable Model and Tool occurrence values for ADR 0123."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, cast

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload

from .model import OnlyAgentToolClass


def _exact(payload: Mapping[str, object], fields: set[str], context: str) -> None:
    if set(payload) != fields:
        raise ValueError(f"{context} fields are invalid")


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


def _array(value: object, context: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value


def _sha(value: object, context: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(item not in "0123456789abcdef" for item in value):
        raise ValueError(f"{context} must be a lower-case SHA256")
    return value


def _optional_sha(value: object, context: str) -> str | None:
    return None if value is None else _sha(value, context)


def _identifier(value: object, context: str) -> str:
    result = _string(value, context)
    if any(character.isspace() for character in result):
        raise ValueError(f"{context} must not contain whitespace")
    return result


def _reject_mutable_alias(value: str, context: str) -> None:
    mutable_aliases = {"latest", "current", "default", "auto", "best"}
    if any(part in mutable_aliases for part in re.split(r"[^a-z0-9]+", value.casefold())):
        raise ValueError(f"{context} must be an exact immutable identity")


def _freeze(value: object, context: str) -> object:
    try:
        canonical = only_canonical_payload(value)
        decoded = json.loads(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{context} must be canonical JSON") from exc
    return _freeze_decoded(decoded)


def _freeze_decoded(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze_decoded(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_decoded(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _frozen_object(value: Mapping[str, object], context: str) -> Mapping[str, object]:
    frozen = _freeze(value, context)
    if not isinstance(frozen, Mapping):  # pragma: no cover - guarded by input type
        raise ValueError(f"{context} must be an object")
    return cast(Mapping[str, object], frozen)


class OnlyAgentModelSettingState(StrEnum):
    VALUE = "VALUE"
    ABSENT = "ABSENT"
    UNSUPPORTED = "UNSUPPORTED"


class OnlyAgentModelCallOutcome(StrEnum):
    RETURNED = "RETURNED"
    FAILED = "FAILED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    RESPONSE_INVALID = "RESPONSE_INVALID"


class OnlyAgentToolRecoveryClass(StrEnum):
    IMMUTABLE_EXACT_QUERY = "IMMUTABLE_EXACT_QUERY"
    MUTABLE_OBSERVATION_QUERY = "MUTABLE_OBSERVATION_QUERY"
    PURE_RESOLVE = "PURE_RESOLVE"
    IDEMPOTENT_COMMAND = "IDEMPOTENT_COMMAND"


class OnlyAgentToolCallOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RESULT_INVALID = "RESULT_INVALID"


class OnlyAgentObservedResponseStorageKind(StrEnum):
    INLINE_CANONICAL_RESPONSE = "INLINE_CANONICAL_RESPONSE"
    EXACT_IMMUTABLE_RESPONSE_REFERENCE = "EXACT_IMMUTABLE_RESPONSE_REFERENCE"


ONLYAGENT_STRICT_SCHEMA_DIALECT = "ONLYALPHA_STRICT_STRUCTURED_OUTPUT"
ONLYAGENT_STRICT_SCHEMA_DIALECT_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True, order=True)
class OnlyAgentContextReferenceV1:
    reference_kind: str
    reference_schema_version: int
    reference_fingerprint: str

    def __post_init__(self) -> None:
        _identifier(self.reference_kind, "reference_kind")
        if (
            isinstance(self.reference_schema_version, bool)
            or not isinstance(self.reference_schema_version, int)
            or self.reference_schema_version <= 0
        ):
            raise ValueError("reference_schema_version must be positive")
        _sha(self.reference_fingerprint, "reference_fingerprint")

    def to_dict(self) -> dict[str, object]:
        return {
            "reference_kind": self.reference_kind,
            "reference_schema_version": self.reference_schema_version,
            "reference_fingerprint": self.reference_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentContextReferenceV1:
        _exact(payload, {"reference_kind", "reference_schema_version", "reference_fingerprint"}, "Context Reference")
        return cls(
            _string(payload["reference_kind"], "reference_kind"),
            _integer(payload["reference_schema_version"], "reference_schema_version"),
            _sha(payload["reference_fingerprint"], "reference_fingerprint"),
        )


@dataclass(frozen=True, slots=True, order=True)
class OnlyAgentModelSettingBindingV1:
    setting_name: str
    state: OnlyAgentModelSettingState
    value: object = None

    def __post_init__(self) -> None:
        _identifier(self.setting_name, "setting_name")
        if not isinstance(self.state, OnlyAgentModelSettingState):
            raise ValueError("AGENT_MODEL_SETTING_BINDING_INVALID")
        if self.state is OnlyAgentModelSettingState.VALUE:
            if self.value is None or isinstance(self.value, (Mapping, tuple, list, set, frozenset)):
                raise ValueError("AGENT_MODEL_SETTING_BINDING_INVALID")
            object.__setattr__(self, "value", _freeze(self.value, "model setting value"))
        elif self.value is not None:
            raise ValueError("AGENT_MODEL_SETTING_BINDING_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {"setting_name": self.setting_name, "state": self.state.value, "value": _thaw(self.value)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentModelSettingBindingV1:
        _exact(payload, {"setting_name", "state", "value"}, "Model Setting Binding")
        return cls(
            _string(payload["setting_name"], "setting_name"),
            OnlyAgentModelSettingState(_string(payload["state"], "state")),
            payload["value"],
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentModelCallPlanV1:
    agent_session_fingerprint: str
    call_ordinal: int
    logical_role: str
    role_policy_fingerprint: str
    provider_id: str
    model_id: str
    model_version: str
    prompt_template_fingerprint: str
    structured_output_schema_fingerprint: str
    tool_policy_fingerprint: str
    model_execution_policy_fingerprint: str
    response_affecting_settings: tuple[OnlyAgentModelSettingBindingV1, ...]
    ordered_context_references: tuple[OnlyAgentContextReferenceV1, ...]
    parent_agent_decision_fingerprint: str | None = None
    retry_of_plan_fingerprint: str | None = None
    model_call_plan_fingerprint: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.call_ordinal < 0:
            raise ValueError("AGENT_MODEL_CALL_PLAN_INVALID")
        for value, field in (
            (self.agent_session_fingerprint, "agent_session_fingerprint"),
            (self.role_policy_fingerprint, "role_policy_fingerprint"),
            (self.prompt_template_fingerprint, "prompt_template_fingerprint"),
            (self.structured_output_schema_fingerprint, "structured_output_schema_fingerprint"),
            (self.tool_policy_fingerprint, "tool_policy_fingerprint"),
            (self.model_execution_policy_fingerprint, "model_execution_policy_fingerprint"),
        ):
            _sha(value, field)
        for value, field in (
            (self.logical_role, "logical_role"),
            (self.provider_id, "provider_id"),
            (self.model_id, "model_id"),
            (self.model_version, "model_version"),
        ):
            _identifier(value, field)
        for value, field in (
            (self.provider_id, "provider_id"),
            (self.model_id, "model_id"),
            (self.model_version, "model_version"),
        ):
            try:
                _reject_mutable_alias(value, field)
            except ValueError as exc:
                raise ValueError("AGENT_MODEL_CALL_PLAN_INVALID") from exc
        names = tuple(item.setting_name for item in self.response_affecting_settings)
        if not names or names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("AGENT_MODEL_CALL_PLAN_INVALID")
        if not isinstance(self.ordered_context_references, tuple) or any(
            not isinstance(item, OnlyAgentContextReferenceV1) for item in self.ordered_context_references
        ):
            raise ValueError("AGENT_MODEL_CALL_PLAN_INVALID")
        _optional_sha(self.parent_agent_decision_fingerprint, "parent_agent_decision_fingerprint")
        _optional_sha(self.retry_of_plan_fingerprint, "retry_of_plan_fingerprint")
        expected = only_canonical_fingerprint(
            {"domain": "onlyalpha.agent-model-call-plan", **self.to_dict(include_fingerprint=False)}
        )
        if not self.model_call_plan_fingerprint:
            object.__setattr__(self, "model_call_plan_fingerprint", expected)
        elif self.model_call_plan_fingerprint != expected:
            raise ValueError("AGENT_MODEL_CALL_PLAN_FINGERPRINT_MISMATCH")

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "agent_session_fingerprint": self.agent_session_fingerprint,
            "call_ordinal": self.call_ordinal,
            "logical_role": self.logical_role,
            "role_policy_fingerprint": self.role_policy_fingerprint,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "prompt_template_fingerprint": self.prompt_template_fingerprint,
            "structured_output_schema_fingerprint": self.structured_output_schema_fingerprint,
            "tool_policy_fingerprint": self.tool_policy_fingerprint,
            "model_execution_policy_fingerprint": self.model_execution_policy_fingerprint,
            "response_affecting_settings": [item.to_dict() for item in self.response_affecting_settings],
            "ordered_context_references": [item.to_dict() for item in self.ordered_context_references],
            "parent_agent_decision_fingerprint": self.parent_agent_decision_fingerprint,
            "retry_of_plan_fingerprint": self.retry_of_plan_fingerprint,
        }
        if include_fingerprint:
            result["model_call_plan_fingerprint"] = self.model_call_plan_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentModelCallPlanV1:
        fields = {
            "schema_version",
            "agent_session_fingerprint",
            "call_ordinal",
            "logical_role",
            "role_policy_fingerprint",
            "provider_id",
            "model_id",
            "model_version",
            "prompt_template_fingerprint",
            "structured_output_schema_fingerprint",
            "tool_policy_fingerprint",
            "model_execution_policy_fingerprint",
            "response_affecting_settings",
            "ordered_context_references",
            "parent_agent_decision_fingerprint",
            "retry_of_plan_fingerprint",
            "model_call_plan_fingerprint",
        }
        _exact(payload, fields, "Model Call Plan")
        return cls(
            _sha(payload["agent_session_fingerprint"], "agent_session_fingerprint"),
            _integer(payload["call_ordinal"], "call_ordinal"),
            _string(payload["logical_role"], "logical_role"),
            _sha(payload["role_policy_fingerprint"], "role_policy_fingerprint"),
            _string(payload["provider_id"], "provider_id"),
            _string(payload["model_id"], "model_id"),
            _string(payload["model_version"], "model_version"),
            _sha(payload["prompt_template_fingerprint"], "prompt_template_fingerprint"),
            _sha(payload["structured_output_schema_fingerprint"], "structured_output_schema_fingerprint"),
            _sha(payload["tool_policy_fingerprint"], "tool_policy_fingerprint"),
            _sha(payload["model_execution_policy_fingerprint"], "model_execution_policy_fingerprint"),
            tuple(
                OnlyAgentModelSettingBindingV1.from_dict(_mapping(item, "setting"))
                for item in _array(payload["response_affecting_settings"], "settings")
            ),
            tuple(
                OnlyAgentContextReferenceV1.from_dict(_mapping(item, "context reference"))
                for item in _array(payload["ordered_context_references"], "context references")
            ),
            _optional_sha(payload["parent_agent_decision_fingerprint"], "parent_agent_decision_fingerprint"),
            _optional_sha(payload["retry_of_plan_fingerprint"], "retry_of_plan_fingerprint"),
            _sha(payload["model_call_plan_fingerprint"], "model_call_plan_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


_MODEL_FAILURES = {
    OnlyAgentModelCallOutcome.FAILED: "AGENT_MODEL_CALL_FAILED",
    OnlyAgentModelCallOutcome.OUTCOME_UNKNOWN: "AGENT_MODEL_CALL_OUTCOME_UNKNOWN",
    OnlyAgentModelCallOutcome.RESPONSE_INVALID: "AGENT_MODEL_RESPONSE_INVALID",
}


@dataclass(frozen=True, slots=True)
class OnlyAgentModelCallResultV1:
    model_call_plan_fingerprint: str
    outcome: OnlyAgentModelCallOutcome
    structured_output_fingerprint: str | None = None
    validated_structured_output: Mapping[str, object] | None = None
    failure_code: str | None = None
    response_digest: str | None = None
    model_call_result_fingerprint: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.outcome, OnlyAgentModelCallOutcome):
            raise ValueError("AGENT_MODEL_CALL_RESULT_INVALID")
        _sha(self.model_call_plan_fingerprint, "model_call_plan_fingerprint")
        _optional_sha(self.response_digest, "response_digest")
        if self.outcome is OnlyAgentModelCallOutcome.RETURNED:
            if self.validated_structured_output is None or self.failure_code is not None:
                raise ValueError("AGENT_MODEL_CALL_RESULT_INVALID")
            frozen = _frozen_object(self.validated_structured_output, "validated_structured_output")
            object.__setattr__(self, "validated_structured_output", frozen)
            expected_output = only_canonical_fingerprint(_thaw(frozen))
            if self.structured_output_fingerprint is None:
                object.__setattr__(self, "structured_output_fingerprint", expected_output)
            elif self.structured_output_fingerprint != expected_output:
                raise ValueError("AGENT_MODEL_CALL_RESULT_INVALID")
        elif (
            self.validated_structured_output is not None
            or self.structured_output_fingerprint is not None
            or self.failure_code != _MODEL_FAILURES[self.outcome]
        ):
            raise ValueError("AGENT_MODEL_CALL_RESULT_INVALID")
        expected = only_canonical_fingerprint(
            {"domain": "onlyalpha.agent-model-call-result", **self.to_dict(include_fingerprint=False)}
        )
        if not self.model_call_result_fingerprint:
            object.__setattr__(self, "model_call_result_fingerprint", expected)
        elif self.model_call_result_fingerprint != expected:
            raise ValueError("AGENT_MODEL_CALL_RESULT_FINGERPRINT_MISMATCH")

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "model_call_plan_fingerprint": self.model_call_plan_fingerprint,
            "outcome": self.outcome.value,
            "structured_output_fingerprint": self.structured_output_fingerprint,
            "validated_structured_output": None
            if self.validated_structured_output is None
            else _thaw(self.validated_structured_output),
            "failure_code": self.failure_code,
            "response_digest": self.response_digest,
        }
        if include_fingerprint:
            result["model_call_result_fingerprint"] = self.model_call_result_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentModelCallResultV1:
        _exact(
            payload,
            {
                "schema_version",
                "model_call_plan_fingerprint",
                "outcome",
                "structured_output_fingerprint",
                "validated_structured_output",
                "failure_code",
                "response_digest",
                "model_call_result_fingerprint",
            },
            "Model Call Result",
        )
        validated = payload["validated_structured_output"]
        return cls(
            _sha(payload["model_call_plan_fingerprint"], "model_call_plan_fingerprint"),
            OnlyAgentModelCallOutcome(_string(payload["outcome"], "outcome")),
            _optional_sha(payload["structured_output_fingerprint"], "structured_output_fingerprint"),
            None if validated is None else _mapping(validated, "validated_structured_output"),
            None if payload["failure_code"] is None else _string(payload["failure_code"], "failure_code"),
            _optional_sha(payload["response_digest"], "response_digest"),
            _sha(payload["model_call_result_fingerprint"], "model_call_result_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentToolCallPlanV1:
    agent_session_fingerprint: str
    tool_call_ordinal: int
    authorizing_agent_decision_fingerprint: str
    tool_class: OnlyAgentToolClass
    product_api_major: int
    product_api_contract_fingerprint: str
    operation_identity: str
    recovery_class: OnlyAgentToolRecoveryClass
    canonical_validated_request: Mapping[str, object]
    canonical_request_fingerprint: str = ""
    exact_identity_inputs: tuple[OnlyAgentContextReferenceV1, ...] = ()
    product_command_id_or_idempotency_key: str | None = None
    tool_policy_fingerprint: str = ""
    tool_call_plan_fingerprint: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.tool_call_ordinal < 0 or self.product_api_major <= 0:
            raise ValueError("AGENT_TOOL_CALL_PLAN_INVALID")
        for value, field in (
            (self.agent_session_fingerprint, "agent_session_fingerprint"),
            (self.authorizing_agent_decision_fingerprint, "authorizing_agent_decision_fingerprint"),
            (self.product_api_contract_fingerprint, "product_api_contract_fingerprint"),
            (self.tool_policy_fingerprint, "tool_policy_fingerprint"),
        ):
            _sha(value, field)
        _identifier(self.operation_identity, "operation_identity")
        if not isinstance(self.tool_class, OnlyAgentToolClass) or not isinstance(
            self.recovery_class, OnlyAgentToolRecoveryClass
        ):
            raise ValueError("AGENT_TOOL_CALL_PLAN_INVALID")
        if not isinstance(self.exact_identity_inputs, tuple) or any(
            not isinstance(item, OnlyAgentContextReferenceV1) for item in self.exact_identity_inputs
        ):
            raise ValueError("AGENT_TOOL_CALL_PLAN_INVALID")
        frozen = _frozen_object(self.canonical_validated_request, "canonical_validated_request")
        object.__setattr__(self, "canonical_validated_request", frozen)
        expected_request = only_canonical_fingerprint(_thaw(frozen))
        if not self.canonical_request_fingerprint:
            object.__setattr__(self, "canonical_request_fingerprint", expected_request)
        elif self.canonical_request_fingerprint != expected_request:
            raise ValueError("AGENT_TOOL_CALL_PLAN_INVALID")
        if self.product_command_id_or_idempotency_key is not None:
            OnlyProductCommandId(self.product_command_id_or_idempotency_key)
        expected = only_canonical_fingerprint(
            {"domain": "onlyalpha.agent-tool-call-plan", **self.to_dict(include_fingerprint=False)}
        )
        if not self.tool_call_plan_fingerprint:
            object.__setattr__(self, "tool_call_plan_fingerprint", expected)
        elif self.tool_call_plan_fingerprint != expected:
            raise ValueError("AGENT_TOOL_CALL_PLAN_FINGERPRINT_MISMATCH")

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "agent_session_fingerprint": self.agent_session_fingerprint,
            "tool_call_ordinal": self.tool_call_ordinal,
            "authorizing_agent_decision_fingerprint": self.authorizing_agent_decision_fingerprint,
            "tool_class": self.tool_class.value,
            "product_api_major": self.product_api_major,
            "product_api_contract_fingerprint": self.product_api_contract_fingerprint,
            "operation_identity": self.operation_identity,
            "recovery_class": self.recovery_class.value,
            "canonical_validated_request": _thaw(self.canonical_validated_request),
            "canonical_request_fingerprint": self.canonical_request_fingerprint,
            "exact_identity_inputs": [item.to_dict() for item in self.exact_identity_inputs],
            "product_command_id_or_idempotency_key": self.product_command_id_or_idempotency_key,
            "tool_policy_fingerprint": self.tool_policy_fingerprint,
        }
        if include_fingerprint:
            result["tool_call_plan_fingerprint"] = self.tool_call_plan_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentToolCallPlanV1:
        _exact(
            payload,
            {
                "schema_version",
                "agent_session_fingerprint",
                "tool_call_ordinal",
                "authorizing_agent_decision_fingerprint",
                "tool_class",
                "product_api_major",
                "product_api_contract_fingerprint",
                "operation_identity",
                "recovery_class",
                "canonical_validated_request",
                "canonical_request_fingerprint",
                "exact_identity_inputs",
                "product_command_id_or_idempotency_key",
                "tool_policy_fingerprint",
                "tool_call_plan_fingerprint",
            },
            "Tool Call Plan",
        )
        command = payload["product_command_id_or_idempotency_key"]
        return cls(
            _sha(payload["agent_session_fingerprint"], "agent_session_fingerprint"),
            _integer(payload["tool_call_ordinal"], "tool_call_ordinal"),
            _sha(payload["authorizing_agent_decision_fingerprint"], "authorizing_agent_decision_fingerprint"),
            OnlyAgentToolClass(_string(payload["tool_class"], "tool_class")),
            _integer(payload["product_api_major"], "product_api_major"),
            _sha(payload["product_api_contract_fingerprint"], "product_api_contract_fingerprint"),
            _string(payload["operation_identity"], "operation_identity"),
            OnlyAgentToolRecoveryClass(_string(payload["recovery_class"], "recovery_class")),
            _mapping(payload["canonical_validated_request"], "canonical_validated_request"),
            _sha(payload["canonical_request_fingerprint"], "canonical_request_fingerprint"),
            tuple(
                OnlyAgentContextReferenceV1.from_dict(_mapping(item, "identity input"))
                for item in _array(payload["exact_identity_inputs"], "exact_identity_inputs")
            ),
            None if command is None else _string(command, "product command ID"),
            _sha(payload["tool_policy_fingerprint"], "tool_policy_fingerprint"),
            _sha(payload["tool_call_plan_fingerprint"], "tool_call_plan_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentToolCallResultV1:
    tool_call_plan_fingerprint: str
    outcome: OnlyAgentToolCallOutcome
    observed_response_storage_kind: OnlyAgentObservedResponseStorageKind | None = None
    canonical_validated_response: Mapping[str, object] | None = None
    exact_immutable_response_reference: OnlyAgentContextReferenceV1 | None = None
    canonical_response_fingerprint: str | None = None
    owning_authority_references: tuple[OnlyAgentContextReferenceV1, ...] = ()
    failure_code: str | None = None
    tool_call_result_fingerprint: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.outcome, OnlyAgentToolCallOutcome):
            raise ValueError("AGENT_TOOL_RESULT_INVALID")
        _sha(self.tool_call_plan_fingerprint, "tool_call_plan_fingerprint")
        if not isinstance(self.owning_authority_references, tuple) or any(
            not isinstance(item, OnlyAgentContextReferenceV1) for item in self.owning_authority_references
        ):
            raise ValueError("AGENT_TOOL_RESULT_INVALID")
        if self.outcome is OnlyAgentToolCallOutcome.SUCCEEDED:
            inline = self.canonical_validated_response is not None
            referenced = self.exact_immutable_response_reference is not None
            if inline == referenced or self.failure_code is not None or self.canonical_response_fingerprint is None:
                raise ValueError("AGENT_TOOL_RESULT_INVALID")
            expected_kind = (
                OnlyAgentObservedResponseStorageKind.INLINE_CANONICAL_RESPONSE
                if inline
                else OnlyAgentObservedResponseStorageKind.EXACT_IMMUTABLE_RESPONSE_REFERENCE
            )
            if self.observed_response_storage_kind is not expected_kind:
                raise ValueError("AGENT_TOOL_RESULT_INVALID")
            if inline:
                frozen = _frozen_object(
                    cast(Mapping[str, object], self.canonical_validated_response), "canonical_validated_response"
                )
                object.__setattr__(self, "canonical_validated_response", frozen)
                if only_canonical_fingerprint(_thaw(frozen)) != self.canonical_response_fingerprint:
                    raise ValueError("AGENT_TOOL_RESULT_INVALID")
        elif (
            self.observed_response_storage_kind is not None
            or self.canonical_validated_response is not None
            or self.exact_immutable_response_reference is not None
            or self.canonical_response_fingerprint is not None
            or self.owning_authority_references
            or self.failure_code
            != (
                "AGENT_TOOL_CALL_FAILED"
                if self.outcome is OnlyAgentToolCallOutcome.FAILED
                else "AGENT_TOOL_RESULT_INVALID"
            )
        ):
            raise ValueError("AGENT_TOOL_RESULT_INVALID")
        expected = only_canonical_fingerprint(
            {"domain": "onlyalpha.agent-tool-call-result", **self.to_dict(include_fingerprint=False)}
        )
        if not self.tool_call_result_fingerprint:
            object.__setattr__(self, "tool_call_result_fingerprint", expected)
        elif self.tool_call_result_fingerprint != expected:
            raise ValueError("AGENT_TOOL_CALL_RESULT_FINGERPRINT_MISMATCH")

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "tool_call_plan_fingerprint": self.tool_call_plan_fingerprint,
            "outcome": self.outcome.value,
            "observed_response_storage_kind": None
            if self.observed_response_storage_kind is None
            else self.observed_response_storage_kind.value,
            "canonical_validated_response": None
            if self.canonical_validated_response is None
            else _thaw(self.canonical_validated_response),
            "exact_immutable_response_reference": None
            if self.exact_immutable_response_reference is None
            else self.exact_immutable_response_reference.to_dict(),
            "canonical_response_fingerprint": self.canonical_response_fingerprint,
            "owning_authority_references": [item.to_dict() for item in self.owning_authority_references],
            "failure_code": self.failure_code,
        }
        if include_fingerprint:
            result["tool_call_result_fingerprint"] = self.tool_call_result_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentToolCallResultV1:
        _exact(
            payload,
            {
                "schema_version",
                "tool_call_plan_fingerprint",
                "outcome",
                "observed_response_storage_kind",
                "canonical_validated_response",
                "exact_immutable_response_reference",
                "canonical_response_fingerprint",
                "owning_authority_references",
                "failure_code",
                "tool_call_result_fingerprint",
            },
            "Tool Call Result",
        )
        kind = payload["observed_response_storage_kind"]
        response = payload["canonical_validated_response"]
        reference = payload["exact_immutable_response_reference"]
        failure = payload["failure_code"]
        return cls(
            _sha(payload["tool_call_plan_fingerprint"], "tool_call_plan_fingerprint"),
            OnlyAgentToolCallOutcome(_string(payload["outcome"], "outcome")),
            None if kind is None else OnlyAgentObservedResponseStorageKind(_string(kind, "storage kind")),
            None if response is None else _mapping(response, "canonical_validated_response"),
            None
            if reference is None
            else OnlyAgentContextReferenceV1.from_dict(_mapping(reference, "response reference")),
            _optional_sha(payload["canonical_response_fingerprint"], "canonical_response_fingerprint"),
            tuple(
                OnlyAgentContextReferenceV1.from_dict(_mapping(item, "owning reference"))
                for item in _array(payload["owning_authority_references"], "owning references")
            ),
            None if failure is None else _string(failure, "failure_code"),
            _sha(payload["tool_call_result_fingerprint"], "tool_call_result_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


class OnlyAgentExactReferenceReader(Protocol):
    def verify_exact_reference(self, reference: OnlyAgentContextReferenceV1) -> None: ...


def validate_agent_strict_value(
    value: object,
    schema: Mapping[str, object],
    *,
    allowed_context_references: tuple[OnlyAgentContextReferenceV1, ...] = (),
) -> object:
    """Validate the deliberately narrow OnlyAlpha strict structured-output subset."""

    validate_agent_strict_schema(schema)
    return _validate_agent_strict_value(
        value,
        schema,
        allowed_context_references=allowed_context_references,
    )


def validate_agent_strict_schema(schema: Mapping[str, object], *, root_type: str | None = None) -> None:
    """Reject unsupported schema semantics before an external boundary can be crossed."""

    allowed_keywords = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "enum",
        "items",
        "x-onlyalpha-reference-kind",
    }
    if not set(schema).issubset(allowed_keywords):
        raise ValueError("AGENT_STRUCTURED_SCHEMA_UNSUPPORTED")
    expected_type = schema.get("type")
    supported_types = {"object", "array", "string", "integer", "number", "boolean", "null"}
    if not isinstance(expected_type, str) or expected_type not in supported_types:
        raise ValueError("AGENT_STRUCTURED_SCHEMA_UNSUPPORTED")
    if root_type is not None and expected_type != root_type:
        raise ValueError("AGENT_STRUCTURED_SCHEMA_UNSUPPORTED")
    if "enum" in schema:
        enum_values = schema["enum"]
        if not isinstance(enum_values, (list, tuple)) or not enum_values:
            raise ValueError("AGENT_STRUCTURED_SCHEMA_UNSUPPORTED")
    reference_kind = schema.get("x-onlyalpha-reference-kind")
    if reference_kind is not None:
        if expected_type != "string" or not isinstance(reference_kind, str) or not reference_kind:
            raise ValueError("AGENT_STRUCTURED_SCHEMA_UNSUPPORTED")
    if expected_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if (
            not isinstance(properties, Mapping)
            or not isinstance(required, (list, tuple))
            or any(not isinstance(item, str) for item in required)
            or len(required) != len(set(required))
        ):
            raise ValueError("AGENT_STRUCTURED_SCHEMA_UNSUPPORTED")
        if schema.get("additionalProperties") is not False:
            raise ValueError("AGENT_STRUCTURED_SCHEMA_UNSUPPORTED")
        if not set(required).issubset(properties) or any(not isinstance(key, str) for key in properties):
            raise ValueError("AGENT_STRUCTURED_SCHEMA_UNSUPPORTED")
        if "items" in schema or reference_kind is not None:
            raise ValueError("AGENT_STRUCTURED_SCHEMA_UNSUPPORTED")
        for key, property_schema in properties.items():
            validate_agent_strict_schema(_mapping(property_schema, f"schema property {key}"))
        return
    if expected_type == "array":
        if "items" not in schema or any(
            keyword in schema
            for keyword in ("properties", "required", "additionalProperties", "x-onlyalpha-reference-kind")
        ):
            raise ValueError("AGENT_STRUCTURED_SCHEMA_UNSUPPORTED")
        validate_agent_strict_schema(_mapping(schema["items"], "array item schema"))
        return
    if any(keyword in schema for keyword in ("properties", "required", "additionalProperties", "items")):
        raise ValueError("AGENT_STRUCTURED_SCHEMA_UNSUPPORTED")


def _validate_agent_strict_value(
    value: object,
    schema: Mapping[str, object],
    *,
    allowed_context_references: tuple[OnlyAgentContextReferenceV1, ...],
) -> object:
    expected_type = cast(str, schema["type"])
    if "enum" in schema and value not in cast(Sequence[object], schema["enum"]):
        raise ValueError("AGENT_MODEL_RESPONSE_INVALID")
    reference_kind = schema.get("x-onlyalpha-reference-kind")
    if reference_kind is not None:
        if not isinstance(value, str) or not any(
            item.reference_kind == reference_kind and item.reference_fingerprint == value
            for item in allowed_context_references
        ):
            raise ValueError("AGENT_MODEL_RESPONSE_INVALID")
    if expected_type == "object":
        if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
            raise ValueError("AGENT_MODEL_RESPONSE_INVALID")
        properties = cast(Mapping[str, object], schema.get("properties", {}))
        required = cast(Sequence[str], schema.get("required", []))
        if not set(required).issubset(value) or not set(value).issubset(properties):
            raise ValueError("AGENT_MODEL_RESPONSE_INVALID")
        result = {
            key: _validate_agent_strict_value(
                value[key],
                _mapping(properties[key], f"schema property {key}"),
                allowed_context_references=allowed_context_references,
            )
            for key in sorted(value)
        }
        return _freeze(result, "validated object")
    if expected_type == "array":
        if not isinstance(value, (list, tuple)):
            raise ValueError("AGENT_MODEL_RESPONSE_INVALID")
        item_schema = _mapping(schema["items"], "array item schema")
        return tuple(
            _validate_agent_strict_value(item, item_schema, allowed_context_references=allowed_context_references)
            for item in value
        )
    matches_type = (
        (expected_type == "string" and isinstance(value, str))
        or (expected_type == "integer" and isinstance(value, int) and not isinstance(value, bool))
        or (expected_type == "number" and isinstance(value, (int, float)) and not isinstance(value, bool))
        or (expected_type == "boolean" and isinstance(value, bool))
        or (expected_type == "null" and value is None)
    )
    if not matches_type:
        raise ValueError("AGENT_MODEL_RESPONSE_INVALID")
    return _freeze(value, "validated scalar")


__all__ = [
    name
    for name in globals()
    if name.startswith("OnlyAgent") or name.startswith("ONLYAGENT_") or name.startswith("validate_agent")
]
