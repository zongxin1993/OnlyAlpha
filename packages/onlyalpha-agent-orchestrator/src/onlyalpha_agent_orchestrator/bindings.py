"""Explicit non-secret semantic bindings used to materialize new Model Plans."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from onlyalpha.research.agent.occurrence import OnlyAgentModelSettingBindingV1

_FORBIDDEN_SETTING_NAMES = {
    "api_key",
    "apikey",
    "credential",
    "credentials",
    "secret",
    "secret_locator",
    "token",
    "access_token",
    "bearer_token",
    "base_url",
    "proxy",
    "timeout",
    "connect_timeout",
    "read_timeout",
    "tls",
    "ca_bundle",
    "ca_bundle_path",
}


def _semantic_identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or not value or any(character.isspace() for character in value):
        raise ValueError(f"AGENT_MODEL_INVOCATION_BINDING_INVALID:{field}")


@dataclass(frozen=True, slots=True)
class OnlyAgentModelInvocationBindingV1:
    """One explicit current semantic choice; operational endpoint data is absent."""

    logical_role: str
    provider_id: str
    model_id: str
    model_version: str
    prompt_template_fingerprint: str
    structured_output_schema_fingerprint: str
    model_execution_policy_fingerprint: str
    response_affecting_settings: tuple[OnlyAgentModelSettingBindingV1, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("AGENT_MODEL_INVOCATION_BINDING_INVALID:schema_version")
        for field in ("logical_role", "provider_id", "model_id", "model_version"):
            _semantic_identifier(getattr(self, field), field)
        for field in (
            "prompt_template_fingerprint",
            "structured_output_schema_fingerprint",
            "model_execution_policy_fingerprint",
        ):
            value = getattr(self, field)
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"AGENT_MODEL_INVOCATION_BINDING_INVALID:{field}")
        if not isinstance(self.response_affecting_settings, tuple) or any(
            not isinstance(item, OnlyAgentModelSettingBindingV1) for item in self.response_affecting_settings
        ):
            raise ValueError("AGENT_MODEL_INVOCATION_BINDING_INVALID:settings")
        names = tuple(item.setting_name for item in self.response_affecting_settings)
        if len(names) != len(set(names)) or any(name.lower() in _FORBIDDEN_SETTING_NAMES for name in names):
            raise ValueError("AGENT_MODEL_INVOCATION_BINDING_SECRET_FORBIDDEN")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "logical_role": self.logical_role,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "prompt_template_fingerprint": self.prompt_template_fingerprint,
            "structured_output_schema_fingerprint": self.structured_output_schema_fingerprint,
            "model_execution_policy_fingerprint": self.model_execution_policy_fingerprint,
            "response_affecting_settings": [item.to_dict() for item in self.response_affecting_settings],
        }


class OnlyAgentModelInvocationBindingReader(Protocol):
    def load_model_invocation_binding_verified(self, logical_role: str) -> OnlyAgentModelInvocationBindingV1: ...


class OnlyStaticAgentModelInvocationBindingReaderV1:
    """Exact role-keyed binding set; no default, ordering choice, or fallback."""

    def __init__(self, bindings: tuple[OnlyAgentModelInvocationBindingV1, ...]) -> None:
        by_role = {binding.logical_role: binding for binding in bindings}
        if not bindings or len(by_role) != len(bindings):
            raise ValueError("AGENT_MODEL_INVOCATION_BINDING_INVALID:role_set")
        self._bindings: Mapping[str, OnlyAgentModelInvocationBindingV1] = MappingProxyType(by_role)

    def load_model_invocation_binding_verified(self, logical_role: str) -> OnlyAgentModelInvocationBindingV1:
        try:
            binding = self._bindings[logical_role]
        except KeyError as exc:
            raise ValueError("AGENT_MODEL_INVOCATION_BINDING_MISSING") from exc
        if binding.logical_role != logical_role:
            raise ValueError("AGENT_MODEL_INVOCATION_BINDING_INVALID:role")
        return binding


__all__ = [name for name in globals() if name.startswith("OnlyAgent") or name.startswith("OnlyStatic")]
