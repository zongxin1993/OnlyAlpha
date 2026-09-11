"""Operational-only endpoint and secret configuration for external Agent I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def _endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("AGENT_EXTERNAL_ENDPOINT_INVALID")
    return value.rstrip("/")


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or value <= 0:
        raise ValueError("AGENT_EXTERNAL_TIMEOUT_INVALID")
    return float(value)


@dataclass(frozen=True, slots=True)
class OnlyOpenAICompatibleEndpointConfigV1:
    base_url: str
    api_credential: str = field(repr=False)
    expected_provider_id: str = ""
    expected_model_id: str = ""
    expected_model_version: str = ""
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 60.0
    verify_tls: bool = True
    ca_bundle_path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _endpoint(self.base_url))
        if not self.api_credential or not all(
            isinstance(item, str) and item and not any(character.isspace() for character in item)
            for item in (self.expected_provider_id, self.expected_model_id, self.expected_model_version)
        ):
            raise ValueError("AGENT_MODEL_ENDPOINT_CONFIG_INVALID")
        object.__setattr__(self, "connect_timeout_seconds", _timeout(self.connect_timeout_seconds))
        object.__setattr__(self, "read_timeout_seconds", _timeout(self.read_timeout_seconds))
        if not isinstance(self.verify_tls, bool):
            raise ValueError("AGENT_MODEL_ENDPOINT_CONFIG_INVALID")
        if self.ca_bundle_path is not None and not self.verify_tls:
            raise ValueError("AGENT_MODEL_ENDPOINT_CONFIG_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyProductApiEndpointConfigV1:
    base_url: str
    bearer_token: str = field(repr=False)
    contract_path: Path
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 60.0
    verify_tls: bool = True
    ca_bundle_path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _endpoint(self.base_url))
        if not self.bearer_token or not isinstance(self.contract_path, Path):
            raise ValueError("AGENT_PRODUCT_ENDPOINT_CONFIG_INVALID")
        object.__setattr__(self, "connect_timeout_seconds", _timeout(self.connect_timeout_seconds))
        object.__setattr__(self, "read_timeout_seconds", _timeout(self.read_timeout_seconds))
        if not isinstance(self.verify_tls, bool) or (self.ca_bundle_path is not None and not self.verify_tls):
            raise ValueError("AGENT_PRODUCT_ENDPOINT_CONFIG_INVALID")


__all__ = ["OnlyOpenAICompatibleEndpointConfigV1", "OnlyProductApiEndpointConfigV1"]
