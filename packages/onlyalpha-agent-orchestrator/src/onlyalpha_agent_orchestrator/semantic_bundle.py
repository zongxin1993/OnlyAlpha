"""Strict bootstrap for the package-owned V1 production semantic bundle."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import cast

from onlyalpha.research.agent.model import (
    OnlyAgentModelExecutionPolicyPayloadV1,
    OnlyAgentOrchestrationResourceKind,
    OnlyAgentOrchestrationResourceV1,
    OnlyAgentPromptTemplatePayloadV1,
    OnlyAgentRolePolicyPayloadV1,
    OnlyAgentStructuredOutputSchemaPayloadV1,
    OnlyAgentToolPolicyPayloadV1,
)
from onlyalpha.research.agent.occurrence import OnlyAgentModelSettingBindingV1
from onlyalpha.research.agent.verification import OnlyAgentOrchestrationResourceReader

from .bindings import (
    OnlyAgentModelInvocationBindingV1,
    OnlyStaticAgentModelInvocationBindingReaderV1,
)

_ROLES = ("RESEARCH_PLANNER", "SEARCH_ROUTER", "FACTOR_DESIGNER", "EVIDENCE_ANALYST")


@dataclass(frozen=True, slots=True)
class OnlyAgentProductionSemanticBundleV1:
    resources: tuple[OnlyAgentOrchestrationResourceV1, ...]
    invocation_bindings: OnlyStaticAgentModelInvocationBindingReaderV1
    role_policy_fingerprints: tuple[str, ...]
    tool_policy_fingerprint: str
    model_execution_policy_fingerprint: str


def load_production_semantic_bundle_v1() -> OnlyAgentProductionSemanticBundleV1:
    raw = resources.files("onlyalpha_agent_orchestrator.resources").joinpath("v1/semantic_bundle.json").read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("AGENT_PRODUCTION_SEMANTIC_BUNDLE_INVALID") from exc
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {"bundle_schema_version", "invocation_bindings", "model_execution_policy", "roles", "tool_policy"}
        or payload["bundle_schema_version"] != 1
    ):
        raise ValueError("AGENT_PRODUCTION_SEMANTIC_BUNDLE_INVALID")
    model_policy = _resource(
        OnlyAgentOrchestrationResourceKind.MODEL_EXECUTION_POLICY,
        OnlyAgentModelExecutionPolicyPayloadV1.from_dict(_object(payload["model_execution_policy"])),
    )
    tool_policy = _resource(
        OnlyAgentOrchestrationResourceKind.TOOL_POLICY,
        OnlyAgentToolPolicyPayloadV1.from_dict(_object(payload["tool_policy"])),
    )
    role_values = payload["roles"]
    if not isinstance(role_values, list) or len(role_values) != 4:
        raise ValueError("AGENT_PRODUCTION_SEMANTIC_BUNDLE_INVALID")
    all_tools = cast(OnlyAgentToolPolicyPayloadV1, tool_policy.canonical_payload).allowed_tool_classes
    built: list[OnlyAgentOrchestrationResourceV1] = [model_policy, tool_policy]
    role_resources: list[OnlyAgentOrchestrationResourceV1] = []
    prompt_by_role: dict[str, OnlyAgentOrchestrationResourceV1] = {}
    schema_by_role: dict[str, OnlyAgentOrchestrationResourceV1] = {}
    for index, raw_role in enumerate(role_values):
        role = _object(raw_role)
        required = {
            "allowed_tool_classes",
            "input_contract",
            "logical_role_id",
            "output_contract",
            "prompt",
            "responsibility_boundary",
            "schema",
            "terminal_behavior",
            "variables",
        }
        if set(role) != required or role["logical_role_id"] != _ROLES[index]:
            raise ValueError("AGENT_PRODUCTION_SEMANTIC_BUNDLE_INVALID")
        role_id = role["logical_role_id"]
        prompt = _resource(
            OnlyAgentOrchestrationResourceKind.PROMPT_TEMPLATE,
            OnlyAgentPromptTemplatePayloadV1(
                "ONLYALPHA_TEMPLATE",
                "1.0.0",
                cast(str, role["prompt"]),
                tuple(cast(list[str], role["variables"])),
                "EXACT_DECLARED_VARIABLE_SUBSTITUTION",
            ),
        )
        schema = _resource(
            OnlyAgentOrchestrationResourceKind.STRUCTURED_OUTPUT_SCHEMA,
            OnlyAgentStructuredOutputSchemaPayloadV1(
                "ONLYALPHA_STRICT_STRUCTURED_OUTPUT",
                "1.0.0",
                _object(role["schema"]),
                "object",
                True,
                "EXACT_DECLARED_ENUMS",
                "EXACT_CONTEXT_IDENTITIES_ONLY",
            ),
        )
        allowed_values = tuple(cast(list[str], role["allowed_tool_classes"]))
        allowed_tools = tuple(item for item in all_tools if item.value in allowed_values)
        if tuple(item.value for item in allowed_tools) != tuple(sorted(allowed_values)):
            raise ValueError("AGENT_PRODUCTION_SEMANTIC_BUNDLE_INVALID")
        role_policy = _resource(
            OnlyAgentOrchestrationResourceKind.ROLE_POLICY,
            OnlyAgentRolePolicyPayloadV1(
                role_id,
                cast(str, role["responsibility_boundary"]),
                (prompt.resource_fingerprint,),
                (schema.resource_fingerprint,),
                (model_policy.resource_fingerprint,),
                allowed_tools,
                cast(str, role["input_contract"]),
                cast(str, role["output_contract"]),
                cast(str, role["terminal_behavior"]),
            ),
        )
        built.extend((prompt, schema, role_policy))
        role_resources.append(role_policy)
        prompt_by_role[role_id] = prompt
        schema_by_role[role_id] = schema
    binding_payload = _object(payload["invocation_bindings"])
    if set(binding_payload) != {"model_id", "model_version", "provider_id", "response_affecting_settings"}:
        raise ValueError("AGENT_PRODUCTION_SEMANTIC_BUNDLE_INVALID")
    settings = tuple(
        OnlyAgentModelSettingBindingV1.from_dict(_object(item))
        for item in cast(list[object], binding_payload["response_affecting_settings"])
    )
    bindings = tuple(
        OnlyAgentModelInvocationBindingV1(
            role,
            cast(str, binding_payload["provider_id"]),
            cast(str, binding_payload["model_id"]),
            cast(str, binding_payload["model_version"]),
            prompt_by_role[role].resource_fingerprint,
            schema_by_role[role].resource_fingerprint,
            model_policy.resource_fingerprint,
            settings,
        )
        for role in _ROLES
    )
    return OnlyAgentProductionSemanticBundleV1(
        tuple(built),
        OnlyStaticAgentModelInvocationBindingReaderV1(bindings),
        tuple(item.resource_fingerprint for item in role_resources),
        tool_policy.resource_fingerprint,
        model_policy.resource_fingerprint,
    )


def commit_production_semantic_bundle_v1(
    store: OnlyAgentOrchestrationResourceReader,
    bundle: OnlyAgentProductionSemanticBundleV1,
) -> None:
    commit = getattr(store, "commit_resource", None)
    if not callable(commit):
        raise ValueError("AGENT_PRODUCTION_RESOURCE_STORE_INVALID")
    for resource in bundle.resources:
        commit(resource)
        loaded = store.load_resource_verified(resource.resource_kind, resource.resource_fingerprint)
        if loaded != resource:
            raise ValueError("AGENT_PRODUCTION_RESOURCE_BOOTSTRAP_MISMATCH")


def _resource(kind: OnlyAgentOrchestrationResourceKind, payload: object) -> OnlyAgentOrchestrationResourceV1:
    return OnlyAgentOrchestrationResourceV1(kind, 1, "1.0.0", payload)  # type: ignore[arg-type]


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("AGENT_PRODUCTION_SEMANTIC_BUNDLE_INVALID")
    return cast(dict[str, object], value)


__all__ = [name for name in globals() if name.startswith(("OnlyAgent", "commit_", "load_"))]
