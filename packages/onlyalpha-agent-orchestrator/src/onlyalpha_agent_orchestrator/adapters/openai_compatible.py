"""One exact OpenAI-compatible chat-completions structured-output adapter."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, cast

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.agent.model import (
    OnlyAgentOrchestrationResourceKind,
    OnlyAgentPromptTemplatePayloadV1,
    OnlyAgentStructuredOutputSchemaPayloadV1,
)
from onlyalpha.research.agent.occurrence import (
    OnlyAgentContextReferenceV1,
    OnlyAgentModelCallPlanV1,
    OnlyAgentModelSettingState,
)
from onlyalpha.research.agent.verification import OnlyAgentOrchestrationResourceReader

from ..config import OnlyOpenAICompatibleEndpointConfigV1
from ..runtime import OnlyAgentExternalIoPermit, assert_external_io_permit
from .transport import (
    OnlyHttpDispatchClassification,
    OnlyHttpRequestV1,
    OnlyRawHttpTransportV1,
)


class OnlyModelAdapterOutcomeKind(StrEnum):
    RETURNED = "RETURNED"
    RESPONSE_INVALID = "RESPONSE_INVALID"
    FAILED = "FAILED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


@dataclass(frozen=True, slots=True)
class OnlyModelAdapterOutcomeV1:
    kind: OnlyModelAdapterOutcomeKind
    structured_response: bytes | None = None

    def __post_init__(self) -> None:
        if (self.kind is OnlyModelAdapterOutcomeKind.RETURNED) != (self.structured_response is not None):
            raise ValueError("AGENT_MODEL_ADAPTER_OUTCOME_INVALID")


class OnlyAgentModelContextProjectionReader(Protocol):
    def load_model_context_projection_verified(
        self, reference: OnlyAgentContextReferenceV1
    ) -> Mapping[str, object]: ...


class OnlyOpenAICompatibleModelAdapterV1:
    def __init__(
        self,
        *,
        config: OnlyOpenAICompatibleEndpointConfigV1,
        resources: OnlyAgentOrchestrationResourceReader,
        contexts: OnlyAgentModelContextProjectionReader,
        transport: OnlyRawHttpTransportV1,
    ) -> None:
        self._config = config
        self._resources = resources
        self._contexts = contexts
        self._transport = transport

    def invoke(
        self,
        plan: OnlyAgentModelCallPlanV1,
        permit: OnlyAgentExternalIoPermit,
    ) -> OnlyModelAdapterOutcomeV1:
        assert_external_io_permit(permit, agent_session_fingerprint=plan.agent_session_fingerprint)
        request = self.project_request_verified(plan)
        outcome = self._transport.send(request, permit)
        if outcome.classification is OnlyHttpDispatchClassification.DEFINITE_NOT_DISPATCHED:
            return OnlyModelAdapterOutcomeV1(OnlyModelAdapterOutcomeKind.FAILED)
        if outcome.classification is OnlyHttpDispatchClassification.POSSIBLY_DISPATCHED_RESPONSE_UNAVAILABLE:
            return OnlyModelAdapterOutcomeV1(OnlyModelAdapterOutcomeKind.OUTCOME_UNKNOWN)
        assert outcome.response is not None
        if not 200 <= outcome.response.status_code < 300:
            return OnlyModelAdapterOutcomeV1(OnlyModelAdapterOutcomeKind.FAILED)
        try:
            envelope = json.loads(outcome.response.body)
            if not isinstance(envelope, dict) or set(envelope).isdisjoint({"choices"}):
                raise ValueError("response envelope")
            choices = envelope.get("choices")
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                raise ValueError("response choices")
            if "message" not in choices[0] or not isinstance(choices[0]["message"], dict):
                raise ValueError("response message")
            message = choices[0]["message"]
            if message.get("refusal") not in {None, ""}:
                return OnlyModelAdapterOutcomeV1(OnlyModelAdapterOutcomeKind.FAILED)
            content = message.get("content")
            if not isinstance(content, str):
                raise ValueError("response content")
            structured = content.encode("utf-8")
            json.loads(structured)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return OnlyModelAdapterOutcomeV1(OnlyModelAdapterOutcomeKind.RESPONSE_INVALID)
        return OnlyModelAdapterOutcomeV1(OnlyModelAdapterOutcomeKind.RETURNED, structured)

    def project_request_verified(self, plan: OnlyAgentModelCallPlanV1) -> OnlyHttpRequestV1:
        if (
            plan.provider_id != self._config.expected_provider_id
            or plan.model_id != self._config.expected_model_id
            or plan.model_version != self._config.expected_model_version
        ):
            raise ValueError("AGENT_MODEL_BINDING_MISMATCH")
        prompt_resource = self._resources.load_resource_verified(
            OnlyAgentOrchestrationResourceKind.PROMPT_TEMPLATE,
            plan.prompt_template_fingerprint,
        )
        schema_resource = self._resources.load_resource_verified(
            OnlyAgentOrchestrationResourceKind.STRUCTURED_OUTPUT_SCHEMA,
            plan.structured_output_schema_fingerprint,
        )
        prompt = prompt_resource.canonical_payload
        schema = schema_resource.canonical_payload
        if not isinstance(prompt, OnlyAgentPromptTemplatePayloadV1) or not isinstance(
            schema, OnlyAgentStructuredOutputSchemaPayloadV1
        ):
            raise ValueError("AGENT_MODEL_RESOURCE_MISMATCH")
        rendered = _render_prompt(prompt, plan, self._contexts)
        body: dict[str, object] = {
            "messages": [{"content": rendered, "role": "system"}],
            "model": plan.model_id,
            "response_format": {
                "json_schema": {
                    "name": f"onlyalpha_{plan.structured_output_schema_fingerprint[:16]}",
                    "schema": json.loads(only_canonical_json(schema.exact_schema)),
                    "strict": True,
                },
                "type": "json_schema",
            },
        }
        for setting in plan.response_affecting_settings:
            if setting.state is OnlyAgentModelSettingState.VALUE:
                body[setting.setting_name] = setting.value
        headers = MappingProxyType(
            {
                "Accept": "application/json",
                "Authorization": f"Bearer {self._config.api_credential}",
                "Content-Type": "application/json",
            }
        )
        return OnlyHttpRequestV1(
            "POST",
            f"{self._config.base_url}/chat/completions",
            headers,
            only_canonical_json(body).encode("utf-8"),
        )


def _render_prompt(
    prompt: OnlyAgentPromptTemplatePayloadV1,
    plan: OnlyAgentModelCallPlanV1,
    contexts: OnlyAgentModelContextProjectionReader,
) -> str:
    if (
        prompt.template_format != "ONLYALPHA_TEMPLATE"
        or prompt.template_format_version != "1.0.0"
        or prompt.rendering_semantics != "EXACT_DECLARED_VARIABLE_SUBSTITUTION"
    ):
        raise ValueError("AGENT_PROMPT_TEMPLATE_UNSUPPORTED")
    values: dict[str, object] = {}
    for reference in plan.ordered_context_references:
        projection = contexts.load_model_context_projection_verified(reference)
        for key, value in projection.items():
            if key in values:
                raise ValueError("AGENT_MODEL_CONTEXT_AMBIGUOUS")
            values[key] = value
    if set(values) != set(prompt.ordered_declared_variables):
        raise ValueError("AGENT_MODEL_CONTEXT_MISMATCH")
    rendered = prompt.template_content
    for name in prompt.ordered_declared_variables:
        token = re.compile(r"{{\s*" + re.escape(name) + r"\s*}}")
        replacement = values[name] if isinstance(values[name], str) else only_canonical_json(values[name])
        rendered, count = token.subn(cast(str, replacement), rendered)
        if count != 1:
            raise ValueError("AGENT_PROMPT_TEMPLATE_MISMATCH")
    if re.search(r"{{.*?}}", rendered):
        raise ValueError("AGENT_PROMPT_TEMPLATE_MISMATCH")
    return rendered


__all__ = [name for name in globals() if name.startswith("Only")]
