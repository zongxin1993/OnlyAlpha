"""Exact-revision Integration Probe execution and operational projection."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from onlyalpha.plugin.integration_probe import (
    OnlyIntegrationProbePolicy,
    OnlyIntegrationProbeRequest,
    OnlyIntegrationProbeResult,
    OnlyIntegrationProbeStatus,
)

from .integration_configuration import (
    OnlyIntegration,
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationRevision,
    OnlyIntegrationSecretBinding,
)
from .integration_type_catalog import OnlyIntegrationProbeCatalog, OnlyIntegrationTypeCatalogError

_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class OnlyIntegrationProbeAttempt:
    probe_attempt_id: str
    integration_id: OnlyIntegrationId
    revision_fingerprint: str
    type_id: str
    type_descriptor_fingerprint: str
    probe_contract_fingerprint: str
    probe_configuration_fingerprint: str | None
    runtime_configuration_fingerprint: str
    started_at: datetime
    completed_at: datetime
    overall_status: OnlyIntegrationProbeStatus
    result_fingerprint: str
    result_document: Mapping[str, object]

    def __post_init__(self) -> None:
        values = (
            self.revision_fingerprint,
            self.type_descriptor_fingerprint,
            self.probe_contract_fingerprint,
            self.runtime_configuration_fingerprint,
            self.result_fingerprint,
        )
        if any(_FINGERPRINT.fullmatch(value) is None for value in values) or (
            self.probe_configuration_fingerprint is not None
            and _FINGERPRINT.fullmatch(self.probe_configuration_fingerprint) is None
        ):
            raise OnlyIntegrationError("INTEGRATION_PROBE_RESULT_CORRUPT")
        try:
            result = OnlyIntegrationProbeResult.restore(self.result_document, self.result_fingerprint)
        except ValueError as exc:
            raise OnlyIntegrationError("INTEGRATION_PROBE_RESULT_CORRUPT") from exc
        if (
            result.probe_attempt_id != self.probe_attempt_id
            or result.integration_id != self.integration_id.value
            or result.revision_fingerprint != self.revision_fingerprint
            or result.started_at != self.started_at
            or result.completed_at != self.completed_at
            or result.overall_status is not self.overall_status
        ):
            raise OnlyIntegrationError("INTEGRATION_PROBE_RESULT_CORRUPT")

    @classmethod
    def from_result(
        cls,
        result: OnlyIntegrationProbeResult,
        revision: OnlyIntegrationRevision,
    ) -> OnlyIntegrationProbeAttempt:
        probe_contract = revision.type_descriptor_document.get("probe_contract")
        if not isinstance(probe_contract, Mapping) or not isinstance(probe_contract.get("fingerprint"), str):
            raise OnlyIntegrationError("INTEGRATION_PROBE_CONFIGURATION_INVALID")
        if (
            result.integration_id != revision.integration_id.value
            or result.revision_fingerprint != revision.revision_fingerprint
        ):
            raise OnlyIntegrationError("INTEGRATION_PROBE_RESULT_CORRUPT")
        return cls(
            result.probe_attempt_id,
            revision.integration_id,
            revision.revision_fingerprint,
            revision.type_id,
            revision.type_descriptor_fingerprint,
            str(probe_contract["fingerprint"]),
            revision.probe_configuration_fingerprint,
            revision.runtime_configuration_fingerprint,
            result.started_at,
            result.completed_at,
            result.overall_status,
            result.fingerprint,
            result.to_dict(),
        )

    @classmethod
    def restore(
        cls,
        *,
        probe_attempt_id: str,
        integration_id: OnlyIntegrationId,
        revision_fingerprint: str,
        type_id: str,
        type_descriptor_fingerprint: str,
        probe_contract_fingerprint: str,
        probe_configuration_fingerprint: str | None,
        runtime_configuration_fingerprint: str,
        started_at: datetime,
        completed_at: datetime,
        overall_status: OnlyIntegrationProbeStatus,
        result_fingerprint: str,
        result_document: Mapping[str, object],
    ) -> OnlyIntegrationProbeAttempt:
        return cls(
            probe_attempt_id,
            integration_id,
            revision_fingerprint,
            type_id,
            type_descriptor_fingerprint,
            probe_contract_fingerprint,
            probe_configuration_fingerprint,
            runtime_configuration_fingerprint,
            started_at,
            completed_at,
            overall_status,
            result_fingerprint,
            result_document,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "probe_attempt_id": self.probe_attempt_id,
            "integration_id": self.integration_id.value,
            "revision_fingerprint": self.revision_fingerprint,
            "type_id": self.type_id,
            "type_descriptor_fingerprint": self.type_descriptor_fingerprint,
            "probe_contract_fingerprint": self.probe_contract_fingerprint,
            "probe_configuration_fingerprint": self.probe_configuration_fingerprint,
            "runtime_configuration_fingerprint": self.runtime_configuration_fingerprint,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "overall_status": self.overall_status.value,
            "result_fingerprint": self.result_fingerprint,
            "result_document": dict(self.result_document),
        }


@dataclass(frozen=True, slots=True)
class OnlyIntegrationOperationalStatus:
    integration_id: OnlyIntegrationId
    revision_fingerprint: str | None
    status: OnlyIntegrationProbeStatus
    probe_attempt_id: str | None
    checked_at: datetime | None
    probe_supported: bool


class OnlyIntegrationProbeStateStore(Protocol):
    def load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration: ...

    def load_revision(self, revision_fingerprint: str) -> OnlyIntegrationRevision: ...

    def load_revision_secret_bindings(self, revision_fingerprint: str) -> tuple[OnlyIntegrationSecretBinding, ...]: ...


class OnlyIntegrationProbeAttemptStore(Protocol):
    def insert_probe_attempt(self, attempt: OnlyIntegrationProbeAttempt) -> None: ...

    def get_probe_attempt(self, probe_attempt_id: str) -> OnlyIntegrationProbeAttempt: ...

    def list_probe_attempts(self, integration_id: OnlyIntegrationId) -> tuple[OnlyIntegrationProbeAttempt, ...]: ...

    def latest_probe_attempt(
        self, integration_id: OnlyIntegrationId, revision_fingerprint: str
    ) -> OnlyIntegrationProbeAttempt | None: ...


class OnlyIntegrationProbeCredentialReader(Protocol):
    def read_secret(self, credential_id: str, credential_generation: int) -> str: ...


class OnlyIntegrationProbeService:
    def __init__(
        self,
        state_store: OnlyIntegrationProbeStateStore,
        attempt_store: OnlyIntegrationProbeAttemptStore,
        credentials: OnlyIntegrationProbeCredentialReader,
        catalog: OnlyIntegrationProbeCatalog,
        *,
        attempt_id_factory: Callable[[], uuid.UUID] = uuid.uuid4,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._state = state_store
        self._attempts = attempt_store
        self._credentials = credentials
        self._catalog = catalog
        self._attempt_id_factory = attempt_id_factory
        self._monotonic = monotonic

    def probe(
        self,
        integration_id: OnlyIntegrationId,
        expected_revision_fingerprint: str,
        *,
        policy: OnlyIntegrationProbePolicy | None = None,
    ) -> OnlyIntegrationProbeAttempt:
        integration = self._state.load_integration(integration_id)
        if integration.lifecycle_state is OnlyIntegrationLifecycleState.ARCHIVED:
            raise OnlyIntegrationError("INTEGRATION_ARCHIVED")
        if (
            integration.current_revision_fingerprint is None
            or integration.current_revision_fingerprint != expected_revision_fingerprint
        ):
            raise OnlyIntegrationError("INTEGRATION_CURRENT_REVISION_CONFLICT")
        revision = self._state.load_revision(expected_revision_fingerprint)
        if revision.integration_id != integration_id or revision.type_id != integration.type_id:
            raise OnlyIntegrationError("INTEGRATION_PROBE_CONFIGURATION_INVALID")
        try:
            require_compatible = getattr(self._catalog, "require_compatible", None)
            provider = (
                require_compatible(revision.type_id, revision.type_descriptor_fingerprint)
                if callable(require_compatible)
                else self._catalog.require(revision.type_id)
            )
            if not callable(require_compatible):
                provider_descriptor = getattr(provider, "integration_type", None)
                if (
                    provider_descriptor is None
                    or provider_descriptor.fingerprint != revision.type_descriptor_fingerprint
                ):
                    raise OnlyIntegrationError("INTEGRATION_PROBE_CONFIGURATION_INVALID")
        except OnlyIntegrationTypeCatalogError as exc:
            raise OnlyIntegrationError(exc.code) from exc
        secrets: dict[str, str] = {}
        try:
            for binding in self._state.load_revision_secret_bindings(revision.revision_fingerprint):
                secrets[binding.field_id] = self._credentials.read_secret(
                    binding.credential_id, binding.credential_generation
                )
        except Exception as exc:
            raise OnlyIntegrationError("INTEGRATION_PROBE_SECRET_UNAVAILABLE") from exc
        bounded_policy = policy or OnlyIntegrationProbePolicy()
        request = OnlyIntegrationProbeRequest.create(
            probe_attempt_id=str(self._attempt_id_factory()),
            integration_id=integration_id.value,
            revision=revision,
            resolved_secrets=secrets,
            policy=bounded_policy,
            deadline_monotonic=self._monotonic() + bounded_policy.total_timeout_seconds,
        )
        provider_error: OnlyIntegrationError | None = None
        try:
            result = provider.probe(request)
        except TimeoutError:
            provider_error = OnlyIntegrationError("INTEGRATION_PROBE_TIMEOUT")
        except ValueError:
            provider_error = OnlyIntegrationError("INTEGRATION_PROBE_RESULT_CORRUPT")
        except Exception:
            provider_error = OnlyIntegrationError("INTEGRATION_PROBE_PROVIDER_UNAVAILABLE")
        if provider_error is not None:
            raise provider_error
        if self._monotonic() > request.deadline_monotonic:
            raise OnlyIntegrationError("INTEGRATION_PROBE_TIMEOUT")
        try:
            if (
                result.probe_attempt_id != request.probe_attempt_id
                or result.integration_id != request.integration_id
                or result.revision_fingerprint != request.revision_fingerprint
                or result.probe_instrument != request.probe_instrument
            ):
                raise ValueError("INTEGRATION_PROBE_RESULT_INVALID")
            provider_fingerprint = result.fingerprint
            result = OnlyIntegrationProbeResult.create(
                request,
                probe_instrument=result.probe_instrument,
                checks=result.checks,
                started_at=result.started_at,
                completed_at=result.completed_at,
            )
            if result.fingerprint != provider_fingerprint:
                raise ValueError("INTEGRATION_PROBE_RESULT_INVALID")
        except (AttributeError, TypeError, ValueError) as exc:
            raise OnlyIntegrationError("INTEGRATION_PROBE_RESULT_CORRUPT") from exc
        if _contains_secret(result.to_dict(), secrets.values()):
            raise OnlyIntegrationError("INTEGRATION_PROBE_RESULT_CORRUPT")
        attempt = OnlyIntegrationProbeAttempt.from_result(result, revision)
        self._attempts.insert_probe_attempt(attempt)
        return attempt


class OnlyIntegrationOperationalQueryService:
    def __init__(
        self,
        state_store: OnlyIntegrationProbeStateStore,
        attempt_store: OnlyIntegrationProbeAttemptStore,
        catalog: OnlyIntegrationProbeCatalog | None = None,
    ) -> None:
        self._state = state_store
        self._attempts = attempt_store
        self._catalog = catalog

    def get_operational_status(self, integration_id: OnlyIntegrationId) -> OnlyIntegrationOperationalStatus:
        for _ in range(3):
            integration = self._state.load_integration(integration_id)
            fingerprint = integration.current_revision_fingerprint
            latest = None if fingerprint is None else self._attempts.latest_probe_attempt(integration_id, fingerprint)
            confirmed = self._state.load_integration(integration_id)
            if confirmed.current_revision_fingerprint == fingerprint and confirmed.type_id == integration.type_id:
                supported = self._catalog is not None and self._catalog.supports(confirmed.type_id)
                if latest is None:
                    return OnlyIntegrationOperationalStatus(
                        integration_id, fingerprint, OnlyIntegrationProbeStatus.UNKNOWN, None, None, supported
                    )
                return OnlyIntegrationOperationalStatus(
                    integration_id,
                    fingerprint,
                    latest.overall_status,
                    latest.probe_attempt_id,
                    latest.completed_at,
                    supported,
                )
        raise OnlyIntegrationError("INTEGRATION_PROBE_PERSISTENCE_UNAVAILABLE")

    def get_probe_attempt(self, probe_attempt_id: str) -> OnlyIntegrationProbeAttempt:
        return self._attempts.get_probe_attempt(probe_attempt_id)

    def list_probe_attempts(self, integration_id: OnlyIntegrationId) -> tuple[OnlyIntegrationProbeAttempt, ...]:
        return self._attempts.list_probe_attempts(integration_id)[:50]


def _contains_secret(value: object, secrets: Iterable[str]) -> bool:
    secret_values = tuple(secret for secret in secrets if isinstance(secret, str) and secret)

    def visit(item: object) -> bool:
        if isinstance(item, str):
            return any(secret in item for secret in secret_values)
        if isinstance(item, Mapping):
            return any(visit(key) or visit(nested) for key, nested in item.items())
        if isinstance(item, list | tuple):
            return any(visit(nested) for nested in item)
        return False

    return visit(value)


__all__ = [name for name in globals() if name.startswith("Only")]
