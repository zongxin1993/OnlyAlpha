"""Immutable values and identities for the Agent decision-context foundation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from onlyalpha.build_provenance import OnlyPackagedBuildProvenanceV1
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload
from onlyalpha.research.experiment.model import OnlySearchEvaluationContextReferenceV1

_SHA = re.compile(r"^[0-9a-f]{64}$")
_GIT_REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_SEMVER = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}(?:[-+][0-9A-Za-z.-]+)?$")


def _exact(payload: Mapping[str, object], fields: set[str], context: str) -> None:
    if set(payload) != fields:
        raise ValueError(f"{context} fields are invalid")


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


def _sequence(value: object, context: str) -> Sequence[object]:
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


def _boolean(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context} must be a boolean")
    return value


def _sha(value: object, context: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ValueError(f"{context} must be a lower-case SHA256")
    return value


def _identifier(value: object, context: str) -> str:
    result = _string(value, context)
    if any(character.isspace() for character in result):
        raise ValueError(f"{context} must not contain whitespace")
    return result


def _semantic_version(value: object, context: str) -> str:
    result = _string(value, context)
    if _SEMVER.fullmatch(result) is None:
        raise ValueError(f"{context} is invalid")
    return result


def _strings(value: object, context: str) -> tuple[str, ...]:
    result = tuple(_string(item, context) for item in _sequence(value, context))
    if len(result) != len(set(result)):
        raise ValueError(f"{context} contains duplicates")
    return result


def _canonical_set(values: tuple[str, ...], context: str, *, non_empty: bool = False) -> tuple[str, ...]:
    if (non_empty and not values) or len(values) != len(set(values)) or values != tuple(sorted(values)):
        raise ValueError(f"{context} must be unique and canonically ordered")
    return values


def _freeze_json_object(value: Mapping[str, object], context: str) -> Mapping[str, object]:
    try:
        projected = only_canonical_payload(value)
        encoded = json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{context} is not canonical JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{context} must be an object")
    frozen = _freeze_json_value(decoded)
    if not isinstance(frozen, Mapping):  # pragma: no cover - guarded by decoded type
        raise ValueError(f"{context} must be an object")
    return frozen


def _freeze_json_value(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze_json_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json_value(item) for item in value)
    return value


def _thaw_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    return value


class OnlyAgentOrchestrationResourceKind(StrEnum):
    AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST = "AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST"
    PROMPT_TEMPLATE = "PROMPT_TEMPLATE"
    STRUCTURED_OUTPUT_SCHEMA = "STRUCTURED_OUTPUT_SCHEMA"
    TOOL_POLICY = "TOOL_POLICY"
    ROLE_POLICY = "ROLE_POLICY"
    MODEL_EXECUTION_POLICY = "MODEL_EXECUTION_POLICY"


class OnlyAgentSearchMethod(StrEnum):
    REUSE_EXISTING = "REUSE_EXISTING"
    SYMBOLIC_SEARCH = "SYMBOLIC_SEARCH"
    PARAMETER_SEARCH = "PARAMETER_SEARCH"


class OnlyAgentToolClass(StrEnum):
    EXACT_CATALOG_CONTEXT_QUERY = "EXACT_CATALOG_CONTEXT_QUERY"
    RESEARCH_DEFINITION_RESOLVE = "RESEARCH_DEFINITION_RESOLVE"
    RESEARCH_RUN_SUBMIT = "RESEARCH_RUN_SUBMIT"
    RESEARCH_RUN_QUERY = "RESEARCH_RUN_QUERY"
    RESEARCH_EVIDENCE_QUERY = "RESEARCH_EVIDENCE_QUERY"
    SYMBOLIC_SEARCH = "SYMBOLIC_SEARCH"
    PARAMETER_SEARCH = "PARAMETER_SEARCH"
    SEARCH_QUERY = "SEARCH_QUERY"


class OnlyAgentOperationClassification(StrEnum):
    QUERY = "QUERY"
    COMMAND = "COMMAND"
    PURE_RESOLVE = "PURE_RESOLVE"


class OnlyAgentModelSettingSupport(StrEnum):
    REQUIRED = "REQUIRED"
    SUPPORTED = "SUPPORTED"
    ABSENT = "ABSENT"


class OnlyAgentWorkflowResourceKind(StrEnum):
    EXECUTABLE = "EXECUTABLE"
    SOURCE = "SOURCE"
    PACKAGE_RESOURCE = "PACKAGE_RESOURCE"


@dataclass(frozen=True, slots=True)
class OnlyAgentPromptTemplatePayloadV1:
    template_format: str
    template_format_version: str
    template_content: str
    ordered_declared_variables: tuple[str, ...]
    rendering_semantics: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("AGENT_PROMPT_TEMPLATE_SCHEMA_UNSUPPORTED")
        _identifier(self.template_format, "template_format")
        _semantic_version(self.template_format_version, "template_format_version")
        _string(self.template_content, "template_content")
        if len(self.ordered_declared_variables) != len(set(self.ordered_declared_variables)):
            raise ValueError("ordered_declared_variables contains duplicates")
        for item in self.ordered_declared_variables:
            _identifier(item, "declared variable")
        _string(self.rendering_semantics, "rendering_semantics")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "template_format": self.template_format,
            "template_format_version": self.template_format_version,
            "template_content": self.template_content,
            "ordered_declared_variables": list(self.ordered_declared_variables),
            "rendering_semantics": self.rendering_semantics,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentPromptTemplatePayloadV1:
        _exact(
            payload,
            {
                "schema_version",
                "template_format",
                "template_format_version",
                "template_content",
                "ordered_declared_variables",
                "rendering_semantics",
            },
            "Prompt Template",
        )
        return cls(
            _string(payload["template_format"], "template_format"),
            _string(payload["template_format_version"], "template_format_version"),
            _string(payload["template_content"], "template_content"),
            _strings(payload["ordered_declared_variables"], "ordered_declared_variables"),
            _string(payload["rendering_semantics"], "rendering_semantics"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentStructuredOutputSchemaPayloadV1:
    schema_dialect: str
    schema_dialect_version: str
    exact_schema: Mapping[str, object]
    root_type: str
    reject_unknown_fields: bool
    enum_semantics: str
    reference_semantics: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.reject_unknown_fields:
            raise ValueError("AGENT_STRUCTURED_OUTPUT_SCHEMA_INVALID")
        _identifier(self.schema_dialect, "schema_dialect")
        _semantic_version(self.schema_dialect_version, "schema_dialect_version")
        object.__setattr__(self, "exact_schema", _freeze_json_object(self.exact_schema, "exact_schema"))
        _identifier(self.root_type, "root_type")
        _string(self.enum_semantics, "enum_semantics")
        _string(self.reference_semantics, "reference_semantics")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "schema_dialect": self.schema_dialect,
            "schema_dialect_version": self.schema_dialect_version,
            "exact_schema": _thaw_json_value(self.exact_schema),
            "root_type": self.root_type,
            "reject_unknown_fields": self.reject_unknown_fields,
            "enum_semantics": self.enum_semantics,
            "reference_semantics": self.reference_semantics,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentStructuredOutputSchemaPayloadV1:
        _exact(
            payload,
            {
                "schema_version",
                "schema_dialect",
                "schema_dialect_version",
                "exact_schema",
                "root_type",
                "reject_unknown_fields",
                "enum_semantics",
                "reference_semantics",
            },
            "Structured Output Schema",
        )
        return cls(
            _string(payload["schema_dialect"], "schema_dialect"),
            _string(payload["schema_dialect_version"], "schema_dialect_version"),
            _mapping(payload["exact_schema"], "exact_schema"),
            _string(payload["root_type"], "root_type"),
            _boolean(payload["reject_unknown_fields"], "reject_unknown_fields"),
            _string(payload["enum_semantics"], "enum_semantics"),
            _string(payload["reference_semantics"], "reference_semantics"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True, order=True)
class OnlyAgentToolOperationConstraintV1:
    operation_identity: str
    tool_class: OnlyAgentToolClass
    classification: OnlyAgentOperationClassification
    identity_requirements: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.operation_identity, "operation_identity")
        if not isinstance(self.tool_class, OnlyAgentToolClass) or not isinstance(
            self.classification, OnlyAgentOperationClassification
        ):
            raise ValueError("AGENT_TOOL_OPERATION_INVALID")
        _canonical_set(self.identity_requirements, "identity_requirements")

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_identity": self.operation_identity,
            "tool_class": self.tool_class.value,
            "classification": self.classification.value,
            "identity_requirements": list(self.identity_requirements),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentToolOperationConstraintV1:
        _exact(
            payload,
            {"operation_identity", "tool_class", "classification", "identity_requirements"},
            "Tool Operation Constraint",
        )
        return cls(
            _string(payload["operation_identity"], "operation_identity"),
            OnlyAgentToolClass(_string(payload["tool_class"], "tool_class")),
            OnlyAgentOperationClassification(_string(payload["classification"], "classification")),
            _strings(payload["identity_requirements"], "identity_requirements"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentToolPolicyPayloadV1:
    allowed_tool_classes: tuple[OnlyAgentToolClass, ...]
    operation_constraints: tuple[OnlyAgentToolOperationConstraintV1, ...]
    explicitly_forbidden_capabilities: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("AGENT_TOOL_POLICY_SCHEMA_UNSUPPORTED")
        values = tuple(item.value for item in self.allowed_tool_classes)
        _canonical_set(values, "allowed_tool_classes", non_empty=True)
        if tuple(item.operation_identity for item in self.operation_constraints) != tuple(
            sorted(item.operation_identity for item in self.operation_constraints)
        ) or len({item.operation_identity for item in self.operation_constraints}) != len(self.operation_constraints):
            raise ValueError("operation_constraints must be unique and canonically ordered")
        if any(item.tool_class not in self.allowed_tool_classes for item in self.operation_constraints):
            raise ValueError("operation constraint uses a disallowed Tool class")
        _canonical_set(self.explicitly_forbidden_capabilities, "explicitly_forbidden_capabilities", non_empty=True)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "allowed_tool_classes": [item.value for item in self.allowed_tool_classes],
            "operation_constraints": [item.to_dict() for item in self.operation_constraints],
            "explicitly_forbidden_capabilities": list(self.explicitly_forbidden_capabilities),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentToolPolicyPayloadV1:
        _exact(
            payload,
            {"schema_version", "allowed_tool_classes", "operation_constraints", "explicitly_forbidden_capabilities"},
            "Tool Policy",
        )
        return cls(
            tuple(
                OnlyAgentToolClass(_string(item, "allowed_tool_class"))
                for item in _sequence(payload["allowed_tool_classes"], "allowed_tool_classes")
            ),
            tuple(
                OnlyAgentToolOperationConstraintV1.from_dict(_mapping(item, "operation_constraint"))
                for item in _sequence(payload["operation_constraints"], "operation_constraints")
            ),
            _strings(payload["explicitly_forbidden_capabilities"], "explicitly_forbidden_capabilities"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentRolePolicyPayloadV1:
    logical_role_id: str
    responsibility_boundary: str
    allowed_prompt_template_fingerprints: tuple[str, ...]
    allowed_structured_output_schema_fingerprints: tuple[str, ...]
    allowed_model_execution_policy_fingerprints: tuple[str, ...]
    allowed_tool_classes: tuple[OnlyAgentToolClass, ...]
    input_contract: str
    output_contract: str
    terminal_behavior: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("AGENT_ROLE_POLICY_SCHEMA_UNSUPPORTED")
        _identifier(self.logical_role_id, "logical_role_id")
        for value in (self.responsibility_boundary, self.input_contract, self.output_contract, self.terminal_behavior):
            _string(value, "Role Policy semantic field")
        for values, name in (
            (self.allowed_prompt_template_fingerprints, "allowed_prompt_template_fingerprints"),
            (self.allowed_structured_output_schema_fingerprints, "allowed_structured_output_schema_fingerprints"),
            (self.allowed_model_execution_policy_fingerprints, "allowed_model_execution_policy_fingerprints"),
        ):
            _canonical_set(values, name, non_empty=True)
            for item in values:
                _sha(item, name)
        _canonical_set(tuple(item.value for item in self.allowed_tool_classes), "role allowed_tool_classes")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "logical_role_id": self.logical_role_id,
            "responsibility_boundary": self.responsibility_boundary,
            "allowed_prompt_template_fingerprints": list(self.allowed_prompt_template_fingerprints),
            "allowed_structured_output_schema_fingerprints": list(self.allowed_structured_output_schema_fingerprints),
            "allowed_model_execution_policy_fingerprints": list(self.allowed_model_execution_policy_fingerprints),
            "allowed_tool_classes": [item.value for item in self.allowed_tool_classes],
            "input_contract": self.input_contract,
            "output_contract": self.output_contract,
            "terminal_behavior": self.terminal_behavior,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentRolePolicyPayloadV1:
        _exact(
            payload,
            {
                "schema_version",
                "logical_role_id",
                "responsibility_boundary",
                "allowed_prompt_template_fingerprints",
                "allowed_structured_output_schema_fingerprints",
                "allowed_model_execution_policy_fingerprints",
                "allowed_tool_classes",
                "input_contract",
                "output_contract",
                "terminal_behavior",
            },
            "Role Policy",
        )
        return cls(
            _string(payload["logical_role_id"], "logical_role_id"),
            _string(payload["responsibility_boundary"], "responsibility_boundary"),
            _strings(payload["allowed_prompt_template_fingerprints"], "prompt fingerprints"),
            _strings(payload["allowed_structured_output_schema_fingerprints"], "schema fingerprints"),
            _strings(payload["allowed_model_execution_policy_fingerprints"], "model policy fingerprints"),
            tuple(
                OnlyAgentToolClass(_string(item, "allowed_tool_class"))
                for item in _sequence(payload["allowed_tool_classes"], "allowed_tool_classes")
            ),
            _string(payload["input_contract"], "input_contract"),
            _string(payload["output_contract"], "output_contract"),
            _string(payload["terminal_behavior"], "terminal_behavior"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True, order=True)
class OnlyAgentModelSettingRuleV1:
    setting_name: str
    support: OnlyAgentModelSettingSupport
    semantics: str

    def __post_init__(self) -> None:
        _identifier(self.setting_name, "setting_name")
        if not isinstance(self.support, OnlyAgentModelSettingSupport):
            raise ValueError("AGENT_MODEL_SETTING_RULE_INVALID")
        _string(self.semantics, "setting semantics")

    def to_dict(self) -> dict[str, object]:
        return {"setting_name": self.setting_name, "support": self.support.value, "semantics": self.semantics}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentModelSettingRuleV1:
        _exact(payload, {"setting_name", "support", "semantics"}, "Model Setting Rule")
        return cls(
            _string(payload["setting_name"], "setting_name"),
            OnlyAgentModelSettingSupport(_string(payload["support"], "support")),
            _string(payload["semantics"], "semantics"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentModelExecutionPolicyPayloadV1:
    setting_rules: tuple[OnlyAgentModelSettingRuleV1, ...]
    retry_semantics: str
    no_fallback: bool
    output_handling: str
    secret_exclusion: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.no_fallback:
            raise ValueError("AGENT_MODEL_EXECUTION_POLICY_INVALID")
        names = tuple(item.setting_name for item in self.setting_rules)
        _canonical_set(names, "setting_rules", non_empty=True)
        _string(self.retry_semantics, "retry_semantics")
        _string(self.output_handling, "output_handling")
        _canonical_set(self.secret_exclusion, "secret_exclusion", non_empty=True)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "setting_rules": [item.to_dict() for item in self.setting_rules],
            "retry_semantics": self.retry_semantics,
            "no_fallback": self.no_fallback,
            "output_handling": self.output_handling,
            "secret_exclusion": list(self.secret_exclusion),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentModelExecutionPolicyPayloadV1:
        _exact(
            payload,
            {
                "schema_version",
                "setting_rules",
                "retry_semantics",
                "no_fallback",
                "output_handling",
                "secret_exclusion",
            },
            "Model Execution Policy",
        )
        return cls(
            tuple(
                OnlyAgentModelSettingRuleV1.from_dict(_mapping(item, "setting_rule"))
                for item in _sequence(payload["setting_rules"], "setting_rules")
            ),
            _string(payload["retry_semantics"], "retry_semantics"),
            _boolean(payload["no_fallback"], "no_fallback"),
            _string(payload["output_handling"], "output_handling"),
            _strings(payload["secret_exclusion"], "secret_exclusion"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True, order=True)
class OnlyAgentWorkflowExecutableResourceV1:
    logical_resource_identity: str
    resource_kind: OnlyAgentWorkflowResourceKind
    byte_sha256: str

    def __post_init__(self) -> None:
        _identifier(self.logical_resource_identity, "logical_resource_identity")
        if not isinstance(self.resource_kind, OnlyAgentWorkflowResourceKind):
            raise ValueError("AGENT_WORKFLOW_RESOURCE_KIND_INVALID")
        _sha(self.byte_sha256, "byte_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "logical_resource_identity": self.logical_resource_identity,
            "resource_kind": self.resource_kind.value,
            "byte_sha256": self.byte_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentWorkflowExecutableResourceV1:
        _exact(payload, {"logical_resource_identity", "resource_kind", "byte_sha256"}, "Workflow Executable Resource")
        return cls(
            _string(payload["logical_resource_identity"], "logical_resource_identity"),
            OnlyAgentWorkflowResourceKind(_string(payload["resource_kind"], "resource_kind")),
            _sha(payload["byte_sha256"], "byte_sha256"),
        )


@dataclass(frozen=True, slots=True, order=True)
class OnlyAgentDistributionProvenanceV1:
    distribution_name: str
    distribution_version: str
    source_provenance_authority: str
    source_repository: str
    source_revision: str

    def __post_init__(self) -> None:
        _identifier(self.distribution_name, "distribution_name")
        _string(self.distribution_version, "distribution_version")
        _identifier(self.source_provenance_authority, "source_provenance_authority")
        _identifier(self.source_repository, "source_repository")
        if _GIT_REVISION.fullmatch(self.source_revision) is None:
            raise ValueError("source_revision is invalid")

    @classmethod
    def from_packaged(cls, value: OnlyPackagedBuildProvenanceV1) -> OnlyAgentDistributionProvenanceV1:
        if not isinstance(value, OnlyPackagedBuildProvenanceV1):
            raise ValueError("AGENT_BUILD_PROVENANCE_INVALID")
        return cls(
            value.distribution_name,
            value.distribution_version,
            value.source_provenance_authority.value,
            value.source_repository,
            value.source_revision,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "distribution_name": self.distribution_name,
            "distribution_version": self.distribution_version,
            "source_provenance_authority": self.source_provenance_authority,
            "source_repository": self.source_repository,
            "source_revision": self.source_revision,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentDistributionProvenanceV1:
        _exact(
            payload,
            {
                "distribution_name",
                "distribution_version",
                "source_provenance_authority",
                "source_repository",
                "source_revision",
            },
            "Distribution Provenance",
        )
        return cls(
            *(
                _string(payload[name], name)
                for name in (
                    "distribution_name",
                    "distribution_version",
                    "source_provenance_authority",
                    "source_repository",
                    "source_revision",
                )
            )
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentWorkflowImplementationManifestV1:
    workflow_id: str
    workflow_semantic_version: str
    source_revision: str
    ordered_executable_resources: tuple[OnlyAgentWorkflowExecutableResourceV1, ...]
    distribution_provenance: tuple[OnlyAgentDistributionProvenanceV1, ...]
    implementation_fingerprint: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("AGENT_WORKFLOW_MANIFEST_SCHEMA_UNSUPPORTED")
        _identifier(self.workflow_id, "workflow_id")
        _semantic_version(self.workflow_semantic_version, "workflow_semantic_version")
        if _GIT_REVISION.fullmatch(self.source_revision) is None:
            raise ValueError("workflow source_revision is invalid")
        resource_ids = tuple(item.logical_resource_identity for item in self.ordered_executable_resources)
        _canonical_set(resource_ids, "ordered_executable_resources", non_empty=True)
        distribution_ids = tuple(item.distribution_name for item in self.distribution_provenance)
        _canonical_set(distribution_ids, "distribution_provenance", non_empty=True)
        if any(
            item.source_revision != self.source_revision
            for item in self.distribution_provenance
            if item.source_repository == "OnlyAlpha"
        ):
            raise ValueError("AGENT_WORKFLOW_BUILD_PROVENANCE_MISMATCH")
        expected = only_canonical_fingerprint(
            {"domain": "onlyalpha.agent-workflow-implementation", **self.to_dict(include_fingerprint=False)}
        )
        if not self.implementation_fingerprint:
            object.__setattr__(self, "implementation_fingerprint", expected)
        elif self.implementation_fingerprint != expected:
            raise ValueError("AGENT_WORKFLOW_IMPLEMENTATION_FINGERPRINT_MISMATCH")

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "workflow_semantic_version": self.workflow_semantic_version,
            "source_revision": self.source_revision,
            "ordered_executable_resources": [item.to_dict() for item in self.ordered_executable_resources],
            "distribution_provenance": [item.to_dict() for item in self.distribution_provenance],
        }
        if include_fingerprint:
            result["implementation_fingerprint"] = self.implementation_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentWorkflowImplementationManifestV1:
        _exact(
            payload,
            {
                "schema_version",
                "workflow_id",
                "workflow_semantic_version",
                "source_revision",
                "ordered_executable_resources",
                "distribution_provenance",
                "implementation_fingerprint",
            },
            "Workflow Manifest",
        )
        return cls(
            _string(payload["workflow_id"], "workflow_id"),
            _string(payload["workflow_semantic_version"], "workflow_semantic_version"),
            _string(payload["source_revision"], "source_revision"),
            tuple(
                OnlyAgentWorkflowExecutableResourceV1.from_dict(_mapping(item, "executable resource"))
                for item in _sequence(payload["ordered_executable_resources"], "ordered_executable_resources")
            ),
            tuple(
                OnlyAgentDistributionProvenanceV1.from_dict(_mapping(item, "distribution provenance"))
                for item in _sequence(payload["distribution_provenance"], "distribution_provenance")
            ),
            _sha(payload["implementation_fingerprint"], "implementation_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


OnlyAgentResourcePayloadV1 = (
    OnlyAgentWorkflowImplementationManifestV1
    | OnlyAgentPromptTemplatePayloadV1
    | OnlyAgentStructuredOutputSchemaPayloadV1
    | OnlyAgentToolPolicyPayloadV1
    | OnlyAgentRolePolicyPayloadV1
    | OnlyAgentModelExecutionPolicyPayloadV1
)

_PAYLOAD_TYPES: dict[OnlyAgentOrchestrationResourceKind, type[OnlyAgentResourcePayloadV1]] = {
    OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST: OnlyAgentWorkflowImplementationManifestV1,
    OnlyAgentOrchestrationResourceKind.PROMPT_TEMPLATE: OnlyAgentPromptTemplatePayloadV1,
    OnlyAgentOrchestrationResourceKind.STRUCTURED_OUTPUT_SCHEMA: OnlyAgentStructuredOutputSchemaPayloadV1,
    OnlyAgentOrchestrationResourceKind.TOOL_POLICY: OnlyAgentToolPolicyPayloadV1,
    OnlyAgentOrchestrationResourceKind.ROLE_POLICY: OnlyAgentRolePolicyPayloadV1,
    OnlyAgentOrchestrationResourceKind.MODEL_EXECUTION_POLICY: OnlyAgentModelExecutionPolicyPayloadV1,
}


@dataclass(frozen=True, slots=True)
class OnlyAgentOrchestrationResourceV1:
    resource_kind: OnlyAgentOrchestrationResourceKind
    resource_schema_version: int
    resource_semantic_version: str
    canonical_payload: OnlyAgentResourcePayloadV1
    resource_fingerprint: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.resource_schema_version != 1:
            raise ValueError("AGENT_ORCHESTRATION_RESOURCE_SCHEMA_UNSUPPORTED")
        if not isinstance(self.resource_kind, OnlyAgentOrchestrationResourceKind) or not isinstance(
            self.canonical_payload, _PAYLOAD_TYPES[self.resource_kind]
        ):
            raise ValueError("AGENT_ORCHESTRATION_RESOURCE_PAYLOAD_MISMATCH")
        _semantic_version(self.resource_semantic_version, "resource_semantic_version")
        expected = only_canonical_fingerprint(
            {"domain": "onlyalpha.agent-orchestration-resource", **self.to_dict(include_fingerprint=False)}
        )
        if not self.resource_fingerprint:
            object.__setattr__(self, "resource_fingerprint", expected)
        elif self.resource_fingerprint != expected:
            raise ValueError("AGENT_ORCHESTRATION_RESOURCE_FINGERPRINT_MISMATCH")

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "resource_kind": self.resource_kind.value,
            "resource_schema_version": self.resource_schema_version,
            "resource_semantic_version": self.resource_semantic_version,
            "canonical_payload": self.canonical_payload.to_dict(),
        }
        if include_fingerprint:
            result["resource_fingerprint"] = self.resource_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentOrchestrationResourceV1:
        _exact(
            payload,
            {
                "schema_version",
                "resource_kind",
                "resource_schema_version",
                "resource_semantic_version",
                "canonical_payload",
                "resource_fingerprint",
            },
            "Orchestration Resource",
        )
        kind = OnlyAgentOrchestrationResourceKind(_string(payload["resource_kind"], "resource_kind"))
        typed_payload = _PAYLOAD_TYPES[kind].from_dict(_mapping(payload["canonical_payload"], "canonical_payload"))
        return cls(
            kind,
            _integer(payload["resource_schema_version"], "resource_schema_version"),
            _string(payload["resource_semantic_version"], "resource_semantic_version"),
            typed_payload,
            _sha(payload["resource_fingerprint"], "resource_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentStructuredHypothesisV1:
    hypothesis_id: str
    statement: str
    rationale: str
    expected_relationship: str
    universe_assumptions: tuple[str, ...]
    falsification_criteria: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("AGENT_HYPOTHESIS_SCHEMA_UNSUPPORTED")
        _identifier(self.hypothesis_id, "hypothesis_id")
        for value in (self.statement, self.rationale, self.expected_relationship):
            _string(value, "Hypothesis semantic field")
        _canonical_set(self.universe_assumptions, "universe_assumptions")
        _canonical_set(self.falsification_criteria, "falsification_criteria", non_empty=True)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "rationale": self.rationale,
            "expected_relationship": self.expected_relationship,
            "universe_assumptions": list(self.universe_assumptions),
            "falsification_criteria": list(self.falsification_criteria),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentStructuredHypothesisV1:
        _exact(
            payload,
            {
                "schema_version",
                "hypothesis_id",
                "statement",
                "rationale",
                "expected_relationship",
                "universe_assumptions",
                "falsification_criteria",
            },
            "Structured Hypothesis",
        )
        return cls(
            _string(payload["hypothesis_id"], "hypothesis_id"),
            _string(payload["statement"], "statement"),
            _string(payload["rationale"], "rationale"),
            _string(payload["expected_relationship"], "expected_relationship"),
            _strings(payload["universe_assumptions"], "universe_assumptions"),
            _strings(payload["falsification_criteria"], "falsification_criteria"),
            _integer(payload["schema_version"], "schema_version"),
        )


OnlyAgentEvaluationContextReferenceV1 = OnlySearchEvaluationContextReferenceV1


@dataclass(frozen=True, slots=True)
class OnlyAgentBudgetV1:
    model_call_limit: int
    tool_call_limit: int
    child_experiment_limit: int = 1
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in (self.model_call_limit, self.tool_call_limit)
            )
            or self.child_experiment_limit != 1
        ):
            raise ValueError("AGENT_BUDGET_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "model_call_limit": self.model_call_limit,
            "tool_call_limit": self.tool_call_limit,
            "child_experiment_limit": self.child_experiment_limit,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentBudgetV1:
        _exact(
            payload, {"schema_version", "model_call_limit", "tool_call_limit", "child_experiment_limit"}, "Agent Budget"
        )
        return cls(
            _integer(payload["model_call_limit"], "model_call_limit"),
            _integer(payload["tool_call_limit"], "tool_call_limit"),
            _integer(payload["child_experiment_limit"], "child_experiment_limit"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentResearchBriefV1:
    hypothesis: OnlyAgentStructuredHypothesisV1
    catalog_generation_fingerprint: str
    dataset_snapshot_fingerprint: str
    evaluation_context_reference: OnlySearchEvaluationContextReferenceV1
    allowed_search_methods: tuple[OnlyAgentSearchMethod, ...]
    agent_budget: OnlyAgentBudgetV1
    research_brief_fingerprint: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or not isinstance(self.hypothesis, OnlyAgentStructuredHypothesisV1)
            or not isinstance(self.evaluation_context_reference, OnlySearchEvaluationContextReferenceV1)
            or not isinstance(self.agent_budget, OnlyAgentBudgetV1)
        ):
            raise ValueError("AGENT_RESEARCH_BRIEF_INVALID")
        _sha(self.catalog_generation_fingerprint, "catalog_generation_fingerprint")
        _sha(self.dataset_snapshot_fingerprint, "dataset_snapshot_fingerprint")
        _canonical_set(
            tuple(item.value for item in self.allowed_search_methods), "allowed_search_methods", non_empty=True
        )
        expected = only_canonical_fingerprint(
            {"domain": "onlyalpha.agent-research-brief", **self.to_dict(include_fingerprint=False)}
        )
        if not self.research_brief_fingerprint:
            object.__setattr__(self, "research_brief_fingerprint", expected)
        elif self.research_brief_fingerprint != expected:
            raise ValueError("AGENT_RESEARCH_BRIEF_FINGERPRINT_MISMATCH")

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "hypothesis": self.hypothesis.to_dict(),
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "evaluation_context_reference": self.evaluation_context_reference.to_dict(),
            "allowed_search_methods": [item.value for item in self.allowed_search_methods],
            "agent_budget": self.agent_budget.to_dict(),
        }
        if include_fingerprint:
            result["research_brief_fingerprint"] = self.research_brief_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentResearchBriefV1:
        _exact(
            payload,
            {
                "schema_version",
                "hypothesis",
                "catalog_generation_fingerprint",
                "dataset_snapshot_fingerprint",
                "evaluation_context_reference",
                "allowed_search_methods",
                "agent_budget",
                "research_brief_fingerprint",
            },
            "Research Brief",
        )
        return cls(
            OnlyAgentStructuredHypothesisV1.from_dict(_mapping(payload["hypothesis"], "hypothesis")),
            _sha(payload["catalog_generation_fingerprint"], "catalog_generation_fingerprint"),
            _sha(payload["dataset_snapshot_fingerprint"], "dataset_snapshot_fingerprint"),
            OnlySearchEvaluationContextReferenceV1.from_dict(
                _mapping(payload["evaluation_context_reference"], "evaluation_context_reference")
            ),
            tuple(
                OnlyAgentSearchMethod(_string(item, "allowed_search_method"))
                for item in _sequence(payload["allowed_search_methods"], "allowed_search_methods")
            ),
            OnlyAgentBudgetV1.from_dict(_mapping(payload["agent_budget"], "agent_budget")),
            _sha(payload["research_brief_fingerprint"], "research_brief_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentSessionManifestV1:
    research_brief_fingerprint: str
    agent_workflow_id: str
    agent_workflow_semantic_version: str
    agent_workflow_implementation_fingerprint: str
    agent_workflow_source_revision: str
    workflow_implementation_resource_fingerprint: str
    tool_policy_fingerprint: str
    ordered_role_policy_fingerprints: tuple[str, ...]
    session_fingerprint: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("AGENT_SESSION_SCHEMA_UNSUPPORTED")
        for value, name in (
            (self.research_brief_fingerprint, "research_brief_fingerprint"),
            (self.agent_workflow_implementation_fingerprint, "agent_workflow_implementation_fingerprint"),
            (self.workflow_implementation_resource_fingerprint, "workflow_implementation_resource_fingerprint"),
            (self.tool_policy_fingerprint, "tool_policy_fingerprint"),
        ):
            _sha(value, name)
        _identifier(self.agent_workflow_id, "agent_workflow_id")
        _semantic_version(self.agent_workflow_semantic_version, "agent_workflow_semantic_version")
        if _GIT_REVISION.fullmatch(self.agent_workflow_source_revision) is None:
            raise ValueError("agent_workflow_source_revision is invalid")
        if not self.ordered_role_policy_fingerprints or len(self.ordered_role_policy_fingerprints) != len(
            set(self.ordered_role_policy_fingerprints)
        ):
            raise ValueError("ordered_role_policy_fingerprints must be non-empty and unique")
        for item in self.ordered_role_policy_fingerprints:
            _sha(item, "role_policy_fingerprint")
        expected = only_canonical_fingerprint(
            {"domain": "onlyalpha.agent-session", **self.to_dict(include_fingerprint=False)}
        )
        if not self.session_fingerprint:
            object.__setattr__(self, "session_fingerprint", expected)
        elif self.session_fingerprint != expected:
            raise ValueError("AGENT_SESSION_FINGERPRINT_MISMATCH")

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "research_brief_fingerprint": self.research_brief_fingerprint,
            "agent_workflow_id": self.agent_workflow_id,
            "agent_workflow_semantic_version": self.agent_workflow_semantic_version,
            "agent_workflow_implementation_fingerprint": self.agent_workflow_implementation_fingerprint,
            "agent_workflow_source_revision": self.agent_workflow_source_revision,
            "workflow_implementation_resource_fingerprint": self.workflow_implementation_resource_fingerprint,
            "tool_policy_fingerprint": self.tool_policy_fingerprint,
            "ordered_role_policy_fingerprints": list(self.ordered_role_policy_fingerprints),
        }
        if include_fingerprint:
            result["session_fingerprint"] = self.session_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentSessionManifestV1:
        _exact(
            payload,
            {
                "schema_version",
                "research_brief_fingerprint",
                "agent_workflow_id",
                "agent_workflow_semantic_version",
                "agent_workflow_implementation_fingerprint",
                "agent_workflow_source_revision",
                "workflow_implementation_resource_fingerprint",
                "tool_policy_fingerprint",
                "ordered_role_policy_fingerprints",
                "session_fingerprint",
            },
            "Session Manifest",
        )
        return cls(
            _sha(payload["research_brief_fingerprint"], "research_brief_fingerprint"),
            _string(payload["agent_workflow_id"], "agent_workflow_id"),
            _string(payload["agent_workflow_semantic_version"], "agent_workflow_semantic_version"),
            _sha(payload["agent_workflow_implementation_fingerprint"], "agent_workflow_implementation_fingerprint"),
            _string(payload["agent_workflow_source_revision"], "agent_workflow_source_revision"),
            _sha(payload["workflow_implementation_resource_fingerprint"], "workflow resource fingerprint"),
            _sha(payload["tool_policy_fingerprint"], "tool_policy_fingerprint"),
            _strings(payload["ordered_role_policy_fingerprints"], "ordered_role_policy_fingerprints"),
            _sha(payload["session_fingerprint"], "session_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


__all__ = [name for name in globals() if name.startswith("OnlyAgent")]
