"""Exact Agent Provider Integration, Model Profile, and Session binding."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import ssl
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from onlyalpha.application.integration_configuration import OnlyIntegrationId
from onlyalpha.application.integration_runtime import (
    OnlyIntegrationRuntimeBindingV1,
    OnlyIntegrationRuntimeError,
    OnlyIntegrationRuntimeResolver,
    OnlyResolvedIntegrationRuntimeConfiguration,
)
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.plugin.agent_provider import OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE
from onlyalpha.plugin.integration import OnlyIntegrationCategory, OnlyIntegrationProbeCheck
from onlyalpha.plugin.integration_probe import (
    OnlyIntegrationProbeCheckResult,
    OnlyIntegrationProbeCheckStatus,
    OnlyIntegrationProbeFailureKind,
    OnlyIntegrationProbeRequest,
    OnlyIntegrationProbeResult,
)

from .config import OnlyOpenAICompatibleEndpointConfigV1

_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class _ManifestValue(Protocol):
    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class OnlyAgentModelProfileV1:
    provider_integration_id: str
    provider_revision_fingerprint: str
    provider_runtime_configuration_fingerprint: str
    model_id: str
    model_version: str
    required_capabilities: tuple[str, ...]
    model_profile_fingerprint: str = ""
    schema_version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        try:
            OnlyIntegrationId(self.provider_integration_id)
        except Exception:
            raise ValueError("AGENT_MODEL_PROFILE_INVALID") from None
        capabilities = tuple(sorted(self.required_capabilities))
        if (
            _FINGERPRINT.fullmatch(self.provider_revision_fingerprint) is None
            or _FINGERPRINT.fullmatch(self.provider_runtime_configuration_fingerprint) is None
            or not self.model_id
            or not self.model_version
            or any(value.isspace() for value in (self.model_id, self.model_version))
            or len(capabilities) != len(set(capabilities))
            or not {"CHAT", "STRUCTURED_OUTPUT"}.issubset(capabilities)
        ):
            raise ValueError("AGENT_MODEL_PROFILE_INVALID")
        object.__setattr__(self, "required_capabilities", capabilities)
        expected = only_canonical_fingerprint(self.to_dict(include_fingerprint=False))
        if not self.model_profile_fingerprint:
            object.__setattr__(self, "model_profile_fingerprint", expected)
        elif self.model_profile_fingerprint != expected:
            raise ValueError("AGENT_MODEL_PROFILE_FINGERPRINT_MISMATCH")

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "provider_integration_id": self.provider_integration_id,
            "provider_revision_fingerprint": self.provider_revision_fingerprint,
            "provider_runtime_configuration_fingerprint": self.provider_runtime_configuration_fingerprint,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "required_capabilities": list(self.required_capabilities),
        }
        if include_fingerprint:
            payload["model_profile_fingerprint"] = self.model_profile_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentModelProfileV1:
        expected = {
            "schema_version",
            "provider_integration_id",
            "provider_revision_fingerprint",
            "provider_runtime_configuration_fingerprint",
            "model_id",
            "model_version",
            "required_capabilities",
            "model_profile_fingerprint",
        }
        capabilities = payload.get("required_capabilities")
        if set(payload) != expected or payload.get("schema_version") != 1 or not isinstance(capabilities, list):
            raise ValueError("AGENT_MODEL_PROFILE_INVALID")
        try:
            return cls(
                _strict_string(payload["provider_integration_id"]),
                _strict_string(payload["provider_revision_fingerprint"]),
                _strict_string(payload["provider_runtime_configuration_fingerprint"]),
                _strict_string(payload["model_id"]),
                _strict_string(payload["model_version"]),
                tuple(_strict_string(item) for item in capabilities),
                _strict_string(payload["model_profile_fingerprint"]),
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError("AGENT_MODEL_PROFILE_INVALID") from None


@dataclass(frozen=True, slots=True)
class OnlyAgentSessionProviderBindingV1:
    agent_session_fingerprint: str
    workflow_manifest_fingerprint: str
    product_contract_fingerprint: str
    provider_binding: OnlyIntegrationRuntimeBindingV1
    model_profile_fingerprint: str
    binding_fingerprint: str = ""
    schema_version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        if (
            any(
                _FINGERPRINT.fullmatch(value) is None
                for value in (
                    self.agent_session_fingerprint,
                    self.workflow_manifest_fingerprint,
                    self.product_contract_fingerprint,
                    self.model_profile_fingerprint,
                )
            )
            or self.provider_binding.category is not OnlyIntegrationCategory.AGENT_PROVIDER
        ):
            raise ValueError("AGENT_SESSION_PROVIDER_BINDING_INVALID")
        expected = only_canonical_fingerprint(self.to_dict(include_fingerprint=False))
        if not self.binding_fingerprint:
            object.__setattr__(self, "binding_fingerprint", expected)
        elif self.binding_fingerprint != expected:
            raise ValueError("AGENT_SESSION_PROVIDER_BINDING_MISMATCH")

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "agent_session_fingerprint": self.agent_session_fingerprint,
            "workflow_manifest_fingerprint": self.workflow_manifest_fingerprint,
            "product_contract_fingerprint": self.product_contract_fingerprint,
            "provider_binding": self.provider_binding.to_dict(),
            "model_profile_fingerprint": self.model_profile_fingerprint,
        }
        if include_fingerprint:
            payload["binding_fingerprint"] = self.binding_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentSessionProviderBindingV1:
        expected = {
            "schema_version",
            "agent_session_fingerprint",
            "workflow_manifest_fingerprint",
            "product_contract_fingerprint",
            "provider_binding",
            "model_profile_fingerprint",
            "binding_fingerprint",
        }
        raw_binding = payload.get("provider_binding")
        if set(payload) != expected or payload.get("schema_version") != 1 or not isinstance(raw_binding, Mapping):
            raise ValueError("AGENT_SESSION_PROVIDER_BINDING_INVALID")
        try:
            return cls(
                _strict_string(payload["agent_session_fingerprint"]),
                _strict_string(payload["workflow_manifest_fingerprint"]),
                _strict_string(payload["product_contract_fingerprint"]),
                OnlyIntegrationRuntimeBindingV1.from_dict(cast(Mapping[str, object], raw_binding)),
                _strict_string(payload["model_profile_fingerprint"]),
                _strict_string(payload["binding_fingerprint"]),
            )
        except (KeyError, TypeError, ValueError, OnlyIntegrationRuntimeError):
            raise ValueError("AGENT_SESSION_PROVIDER_BINDING_INVALID") from None


@dataclass(frozen=True, slots=True)
class OnlyResolvedAgentProviderRuntimeV1:
    binding: OnlyIntegrationRuntimeBindingV1
    model_profile: OnlyAgentModelProfileV1
    endpoint: OnlyOpenAICompatibleEndpointConfigV1 = field(repr=False)


class OnlyAgentProviderRuntimeAuthority(Protocol):
    def admit_new(self, profile: OnlyAgentModelProfileV1) -> OnlyResolvedAgentProviderRuntimeV1: ...

    def continue_exact(
        self,
        binding: OnlyAgentSessionProviderBindingV1,
        profile: OnlyAgentModelProfileV1,
    ) -> OnlyResolvedAgentProviderRuntimeV1: ...


class OnlyOpenAICompatibleAgentProvider:
    integration_type = OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE

    @staticmethod
    def endpoint(
        resolved: OnlyResolvedIntegrationRuntimeConfiguration,
        profile: OnlyAgentModelProfileV1,
    ) -> OnlyOpenAICompatibleEndpointConfigV1:
        public = resolved.public_configuration
        if set(public) - {
            "base_url",
            "connect_timeout_seconds",
            "read_timeout_seconds",
            "verify_tls",
        }:
            raise ValueError("AGENT_PROVIDER_CONFIGURATION_INVALID")
        if set(resolved.secrets.as_mapping()) != {"api_credential"}:
            raise ValueError("AGENT_PROVIDER_CONFIGURATION_INVALID")
        return OnlyOpenAICompatibleEndpointConfigV1(
            str(public.get("base_url", "")),
            resolved.secrets.require("api_credential"),
            OnlyOpenAICompatibleAgentProvider.integration_type.provider_id,
            profile.model_id,
            profile.model_version,
            _number(public.get("connect_timeout_seconds", 10.0)),
            _number(public.get("read_timeout_seconds", 60.0)),
            _boolean(public.get("verify_tls", True)),
        )


class OnlyAgentProviderRuntimeResolverV1:
    def __init__(
        self,
        resolver: OnlyIntegrationRuntimeResolver,
        provider: OnlyOpenAICompatibleAgentProvider | None = None,
    ) -> None:
        self._resolver = resolver
        self._provider = provider or OnlyOpenAICompatibleAgentProvider()

    def admit_new(self, profile: OnlyAgentModelProfileV1) -> OnlyResolvedAgentProviderRuntimeV1:
        resolved = self._resolver.admit_new_reference(
            profile.provider_integration_id,
            profile.provider_revision_fingerprint,
            expected_category=OnlyIntegrationCategory.AGENT_PROVIDER,
            required_capabilities=profile.required_capabilities,
            require_current_revision=True,
            require_ready_probe=True,
        )
        return self._close(resolved, profile)

    def continue_exact(
        self,
        binding: OnlyAgentSessionProviderBindingV1,
        profile: OnlyAgentModelProfileV1,
    ) -> OnlyResolvedAgentProviderRuntimeV1:
        if binding.model_profile_fingerprint != profile.model_profile_fingerprint:
            raise ValueError("AGENT_WORKFLOW_RUNTIME_MISMATCH")
        try:
            resolved = self._resolver.resolve(
                binding.provider_binding,
                expected_category=OnlyIntegrationCategory.AGENT_PROVIDER,
                required_capabilities=profile.required_capabilities,
            )
            return self._close(resolved, profile)
        except Exception:
            raise ValueError("AGENT_WORKFLOW_RUNTIME_MISMATCH") from None

    def _close(
        self,
        resolved: OnlyResolvedIntegrationRuntimeConfiguration,
        profile: OnlyAgentModelProfileV1,
    ) -> OnlyResolvedAgentProviderRuntimeV1:
        if (
            resolved.type_descriptor != self._provider.integration_type
            or resolved.binding.revision_fingerprint != profile.provider_revision_fingerprint
            or resolved.binding.runtime_configuration_fingerprint != profile.provider_runtime_configuration_fingerprint
        ):
            raise ValueError("AGENT_WORKFLOW_RUNTIME_MISMATCH")
        return OnlyResolvedAgentProviderRuntimeV1(
            resolved.binding,
            profile,
            self._provider.endpoint(resolved, profile),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentProviderRuntimeAuthorityConfigV1:
    base_url: str
    bearer_token: str = field(repr=False)
    timeout_seconds: float = 10.0
    verify_tls: bool = True

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not self.bearer_token
            or isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int | float)
            or self.timeout_seconds <= 0
            or not isinstance(self.verify_tls, bool)
        ):
            raise ValueError("AGENT_PROVIDER_AUTHORITY_CONFIG_INVALID")
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))


class OnlyAgentProviderAuthorityTransport(Protocol):
    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: bytes,
        timeout_seconds: float,
        verify_tls: bool,
    ) -> tuple[int, bytes]: ...


class OnlyHttpAgentProviderRuntimeAuthorityV1:
    def __init__(
        self,
        config: OnlyAgentProviderRuntimeAuthorityConfigV1,
        transport: OnlyAgentProviderAuthorityTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = _authority_transport if transport is None else transport

    def admit_new(self, profile: OnlyAgentModelProfileV1) -> OnlyResolvedAgentProviderRuntimeV1:
        return self._resolve("admit-new", {"model_profile": profile.to_dict()}, None, profile)

    def continue_exact(
        self,
        binding: OnlyAgentSessionProviderBindingV1,
        profile: OnlyAgentModelProfileV1,
    ) -> OnlyResolvedAgentProviderRuntimeV1:
        return self._resolve(
            "continue-exact",
            {"session_provider_binding": binding.to_dict(), "model_profile": profile.to_dict()},
            binding,
            profile,
        )

    def _resolve(
        self,
        operation: str,
        request_payload: Mapping[str, object],
        expected_binding: OnlyAgentSessionProviderBindingV1 | None,
        expected_profile: OnlyAgentModelProfileV1,
    ) -> OnlyResolvedAgentProviderRuntimeV1:
        try:
            status, body = self._transport(
                f"{self._config.base_url}/{operation}",
                {
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._config.bearer_token}",
                    "Content-Type": "application/json",
                },
                only_canonical_json({"schema_version": 1, **request_payload}).encode("utf-8"),
                self._config.timeout_seconds,
                self._config.verify_tls,
            )
            document = json.loads(body)
            if status != 200:
                error = document.get("error") if isinstance(document, dict) else None
                code = error.get("code") if isinstance(error, dict) else None
                if expected_binding is None and isinstance(code, str) and code.startswith("INTEGRATION_RUNTIME_"):
                    raise OnlyIntegrationRuntimeError(code)
                raise ValueError
            if (
                not isinstance(document, dict)
                or set(document) != {"schema_version", "provider_binding", "model_profile", "endpoint"}
                or document.get("schema_version") != 1
            ):
                raise ValueError
            binding_payload = document.get("provider_binding")
            profile_payload = document.get("model_profile")
            endpoint_payload = document.get("endpoint")
            if not all(isinstance(item, Mapping) for item in (binding_payload, profile_payload, endpoint_payload)):
                raise ValueError
            binding = OnlyIntegrationRuntimeBindingV1.from_dict(cast(Mapping[str, object], binding_payload))
            profile = OnlyAgentModelProfileV1.from_dict(cast(Mapping[str, object], profile_payload))
            endpoint_document = cast(Mapping[str, object], endpoint_payload)
            if set(endpoint_document) != {
                "base_url",
                "api_credential",
                "expected_provider_id",
                "expected_model_id",
                "expected_model_version",
                "connect_timeout_seconds",
                "read_timeout_seconds",
                "verify_tls",
            }:
                raise ValueError
            endpoint = OnlyOpenAICompatibleEndpointConfigV1(
                _strict_string(endpoint_document["base_url"]),
                _strict_string(endpoint_document["api_credential"]),
                _strict_string(endpoint_document["expected_provider_id"]),
                _strict_string(endpoint_document["expected_model_id"]),
                _strict_string(endpoint_document["expected_model_version"]),
                _number(endpoint_document["connect_timeout_seconds"]),
                _number(endpoint_document["read_timeout_seconds"]),
                _boolean(endpoint_document["verify_tls"]),
            )
            if (
                profile != expected_profile
                or binding.revision_fingerprint != profile.provider_revision_fingerprint
                or binding.runtime_configuration_fingerprint != profile.provider_runtime_configuration_fingerprint
                or endpoint.expected_model_id != profile.model_id
                or endpoint.expected_model_version != profile.model_version
                or (expected_binding is not None and binding != expected_binding.provider_binding)
            ):
                raise ValueError
            return OnlyResolvedAgentProviderRuntimeV1(binding, profile, endpoint)
        except OnlyIntegrationRuntimeError:
            raise
        except Exception:
            code = (
                "AGENT_PROVIDER_AUTHORITY_UNAVAILABLE"
                if expected_binding is None
                else "AGENT_WORKFLOW_RUNTIME_MISMATCH"
            )
            raise ValueError(code) from None


class OnlyAgentProviderProbeTransport(Protocol):
    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        verify_tls: bool,
    ) -> tuple[int, bytes]: ...


class OnlyOpenAICompatibleAgentProviderProbe:
    integration_type = OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE

    def __init__(
        self,
        transport: OnlyAgentProviderProbeTransport | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._transport = _probe_transport if transport is None else transport
        self._monotonic = monotonic
        self._utc_now = utc_now

    def probe(self, request: OnlyIntegrationProbeRequest) -> OnlyIntegrationProbeResult:
        started_at = self._utc_now()
        started = self._monotonic()
        checks: list[OnlyIntegrationProbeCheckResult] = []
        try:
            public = request.public_configuration
            if set(public) - {"base_url", "connect_timeout_seconds", "read_timeout_seconds", "verify_tls"}:
                raise ValueError
            credential = request.resolved_secrets.get("api_credential")
            base_url = str(public.get("base_url", "")).rstrip("/")
            if not credential or started >= request.deadline_monotonic:
                raise ValueError
            timeout = min(
                _number(public.get("read_timeout_seconds", 60.0)),
                request.policy.per_check_timeout_seconds,
                request.deadline_monotonic - started,
            )
            status, payload = self._transport(
                f"{base_url}/models",
                {"Accept": "application/json", "Authorization": f"Bearer {credential}"},
                timeout,
                _boolean(public.get("verify_tls", True)),
            )
            document = json.loads(payload)
            if not 200 <= status < 300 or not isinstance(document, dict) or not isinstance(document.get("data"), list):
                raise ValueError
        except Exception:
            for check in request.required_checks:
                checks.append(
                    OnlyIntegrationProbeCheckResult(
                        check,
                        OnlyIntegrationProbeCheckStatus.FAIL,
                        max(0, int((self._monotonic() - started) * 1000)),
                        OnlyIntegrationProbeFailureKind.OFFLINE
                        if check is OnlyIntegrationProbeCheck.CONNECTIVITY
                        else OnlyIntegrationProbeFailureKind.FAILED,
                        "AGENT_PROVIDER_PROBE_FAILED",
                    )
                )
        else:
            for check in request.required_checks:
                checks.append(
                    OnlyIntegrationProbeCheckResult(
                        check,
                        OnlyIntegrationProbeCheckStatus.PASS,
                        max(0, int((self._monotonic() - started) * 1000)),
                        observations=("read_only_model_catalog_visible=true",),
                    )
                )
        return OnlyIntegrationProbeResult.create(
            request,
            probe_instrument=request.probe_instrument,
            checks=tuple(checks),
            started_at=started_at,
            completed_at=self._utc_now(),
        )


class OnlyJsonAgentProviderBindingStoreV1:
    def __init__(self, durable_root: Path) -> None:
        self._root = durable_root / "research/agent-orchestration/provider-bindings"

    def commit(self, binding: OnlyAgentSessionProviderBindingV1) -> None:
        _commit_manifest(
            self._root,
            binding.agent_session_fingerprint,
            binding,
            OnlyAgentSessionProviderBindingV1.from_dict,
            "AGENT_SESSION_PROVIDER_BINDING_MISMATCH",
        )

    def load(self, session_fingerprint: str) -> OnlyAgentSessionProviderBindingV1:
        try:
            binding = _load_manifest(self._root, session_fingerprint, OnlyAgentSessionProviderBindingV1.from_dict)
            if binding.agent_session_fingerprint != session_fingerprint:
                raise ValueError
            return binding
        except Exception:
            raise ValueError("AGENT_WORKFLOW_RUNTIME_MISMATCH") from None


class OnlyJsonAgentModelProfileStoreV1:
    def __init__(self, durable_root: Path) -> None:
        self._root = durable_root / "research/agent-orchestration/model-profiles"

    def commit(self, profile: OnlyAgentModelProfileV1) -> None:
        _commit_manifest(
            self._root,
            profile.model_profile_fingerprint,
            profile,
            OnlyAgentModelProfileV1.from_dict,
            "AGENT_MODEL_PROFILE_FINGERPRINT_MISMATCH",
        )

    def load(self, fingerprint: str) -> OnlyAgentModelProfileV1:
        try:
            profile = _load_manifest(self._root, fingerprint, OnlyAgentModelProfileV1.from_dict)
            if profile.model_profile_fingerprint != fingerprint:
                raise ValueError
            return profile
        except Exception:
            raise ValueError("AGENT_WORKFLOW_RUNTIME_MISMATCH") from None


def _probe_transport(
    url: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
    verify_tls: bool,
) -> tuple[int, bytes]:
    context = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()  # noqa: SLF001
    request = Request(url, headers=dict(headers), method="GET")
    with urlopen(request, timeout=timeout_seconds, context=context) as response:  # noqa: S310
        payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise ValueError("AGENT_PROVIDER_PROBE_RESPONSE_TOO_LARGE")
        return int(response.status), payload


def _authority_transport(
    url: str,
    headers: Mapping[str, str],
    payload: bytes,
    timeout_seconds: float,
    verify_tls: bool,
) -> tuple[int, bytes]:
    context = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()  # noqa: SLF001
    request = Request(url, data=payload, headers=dict(headers), method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds, context=context) as response:  # noqa: S310
            status = int(response.status)
            body = response.read(1024 * 1024 + 1)
    except HTTPError as error:
        status = int(error.code)
        body = error.read(1024 * 1024 + 1)
    if len(body) > 1024 * 1024:
        raise ValueError("AGENT_PROVIDER_AUTHORITY_RESPONSE_TOO_LARGE")
    return status, body


def _commit_manifest(
    root: Path,
    fingerprint: str,
    value: _ManifestValue,
    parser: Callable[[Mapping[str, object]], _ManifestValue],
    mismatch_code: str,
) -> None:
    target = root / fingerprint
    target.parent.mkdir(parents=True, exist_ok=True)
    with _locked(target.parent / f".{fingerprint}.lock"):
        if target.exists():
            if _load_manifest(root, fingerprint, parser) != value:
                raise ValueError(mismatch_code)
            return
        stage = target.parent / f".{fingerprint}.{uuid.uuid4().hex}.stage"
        try:
            stage.mkdir(mode=0o700)
            manifest = stage / "manifest.json"
            payload = value.to_dict()
            manifest.write_text(only_canonical_json(payload), encoding="utf-8")
            with manifest.open("rb") as handle:
                os.fsync(handle.fileno())
            parsed = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError(mismatch_code)
            parser(parsed)
            os.replace(stage, target)
        except Exception:
            if stage.exists():
                shutil.rmtree(stage)
            raise


def _load_manifest[ManifestT](
    root: Path,
    fingerprint: str,
    parser: Callable[[Mapping[str, object]], ManifestT],
) -> ManifestT:
    path = root / fingerprint / "manifest.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError
    return parser(payload)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("AGENT_PROVIDER_CONFIGURATION_INVALID")
    return float(value)


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("AGENT_PROVIDER_CONFIGURATION_INVALID")
    return value


def _strict_string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("AGENT_PROVIDER_AUTHORITY_RESPONSE_INVALID")
    return value


__all__ = [name for name in globals() if name.startswith("Only")]
