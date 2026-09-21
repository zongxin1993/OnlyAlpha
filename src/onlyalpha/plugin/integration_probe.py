"""Provider-neutral, bounded Integration Probe SPI."""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, cast, runtime_checkable

from onlyalpha.canonical import only_canonical_fingerprint

from .integration import OnlyIntegrationProbeCheck

_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class OnlyIntegrationProbeStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    READY = "READY"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    FAILED = "FAILED"


class OnlyIntegrationProbeCheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


class OnlyIntegrationProbeFailureKind(StrEnum):
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class OnlyIntegrationProbePolicy:
    total_timeout_seconds: float = 15.0
    per_check_timeout_seconds: float = 5.0
    maximum_observation_records: int = 8

    def __post_init__(self) -> None:
        valid = (
            isinstance(self.total_timeout_seconds, int | float)
            and not isinstance(self.total_timeout_seconds, bool)
            and math.isfinite(self.total_timeout_seconds)
            and 0 < self.total_timeout_seconds <= 60
            and isinstance(self.per_check_timeout_seconds, int | float)
            and not isinstance(self.per_check_timeout_seconds, bool)
            and math.isfinite(self.per_check_timeout_seconds)
            and 0 < self.per_check_timeout_seconds <= self.total_timeout_seconds
            and isinstance(self.maximum_observation_records, int)
            and not isinstance(self.maximum_observation_records, bool)
            and 1 <= self.maximum_observation_records <= 32
        )
        if not valid:
            raise ValueError("INTEGRATION_PROBE_POLICY_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyIntegrationProbeCheckResult:
    check: OnlyIntegrationProbeCheck
    status: OnlyIntegrationProbeCheckStatus
    latency_ms: int
    failure_kind: OnlyIntegrationProbeFailureKind | None = None
    error_code: str | None = None
    detail: str = ""
    observations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        valid_latency = (
            isinstance(self.latency_ms, int) and not isinstance(self.latency_ms, bool) and self.latency_ms >= 0
        )
        if not valid_latency or len(self.detail) > 500 or any(len(item) > 200 for item in self.observations):
            raise ValueError("INTEGRATION_PROBE_RESULT_INVALID")
        if self.status is OnlyIntegrationProbeCheckStatus.FAIL:
            if self.failure_kind is None or self.error_code is None or _ERROR_CODE.fullmatch(self.error_code) is None:
                raise ValueError("INTEGRATION_PROBE_RESULT_INVALID")
        elif self.failure_kind is not None or self.error_code is not None:
            raise ValueError("INTEGRATION_PROBE_RESULT_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "check": self.check.value,
            "status": self.status.value,
            "latency_ms": self.latency_ms,
            "failure_kind": None if self.failure_kind is None else self.failure_kind.value,
            "error_code": self.error_code,
            "detail": self.detail,
            "observations": list(self.observations),
        }


class OnlyIntegrationProbeRevisionView(Protocol):
    @property
    def revision_fingerprint(self) -> str: ...

    @property
    def type_id(self) -> str: ...

    @property
    def type_descriptor_fingerprint(self) -> str: ...

    @property
    def type_descriptor_document(self) -> Mapping[str, object]: ...

    @property
    def configuration_document(self) -> Mapping[str, object]: ...

    @property
    def runtime_configuration_fingerprint(self) -> str: ...

    @property
    def probe_configuration_fingerprint(self) -> str | None: ...

    @property
    def probe_configuration_document(self) -> Mapping[str, object] | None: ...


@dataclass(frozen=True, slots=True)
class OnlyIntegrationProbeRequest:
    probe_attempt_id: str
    integration_id: str
    revision_fingerprint: str
    type_id: str
    type_descriptor_fingerprint: str
    public_configuration: Mapping[str, object]
    probe_configuration: Mapping[str, object] | None
    required_checks: tuple[OnlyIntegrationProbeCheck, ...]
    probe_instrument: str | None
    policy: OnlyIntegrationProbePolicy
    deadline_monotonic: float
    resolved_secrets: Mapping[str, str] = field(repr=False)

    @classmethod
    def create(
        cls,
        *,
        probe_attempt_id: str,
        integration_id: str,
        revision: OnlyIntegrationProbeRevisionView,
        resolved_secrets: Mapping[str, str],
        policy: OnlyIntegrationProbePolicy,
        deadline_monotonic: float,
    ) -> OnlyIntegrationProbeRequest:
        _uuid4(probe_attempt_id, "INTEGRATION_PROBE_ATTEMPT_ID_INVALID")
        _uuid4(integration_id, "INTEGRATION_ID_INVALID")
        _fingerprint(revision.revision_fingerprint)
        _fingerprint(revision.type_descriptor_fingerprint)
        if not math.isfinite(deadline_monotonic) or deadline_monotonic <= 0:
            raise ValueError("INTEGRATION_PROBE_POLICY_INVALID")
        probe_contract = revision.type_descriptor_document.get("probe_contract")
        if not isinstance(probe_contract, Mapping):
            raise ValueError("INTEGRATION_PROBE_CONFIGURATION_INVALID")
        raw_checks = probe_contract.get("probe_checks")
        if not isinstance(raw_checks, tuple):
            raise ValueError("INTEGRATION_PROBE_CONFIGURATION_INVALID")
        try:
            checks = tuple(OnlyIntegrationProbeCheck(str(item)) for item in raw_checks)
        except ValueError as exc:
            raise ValueError("INTEGRATION_PROBE_CONFIGURATION_INVALID") from exc
        probe_configuration = revision.probe_configuration_document
        instrument = (
            probe_contract.get("default_probe_instrument")
            if probe_configuration is None
            else probe_configuration.get("instrument", probe_contract.get("default_probe_instrument"))
        )
        return cls(
            probe_attempt_id,
            integration_id,
            revision.revision_fingerprint,
            revision.type_id,
            revision.type_descriptor_fingerprint,
            MappingProxyType(dict(revision.configuration_document)),
            None if probe_configuration is None else MappingProxyType(dict(probe_configuration)),
            checks,
            None if instrument is None else str(instrument),
            policy,
            deadline_monotonic,
            MappingProxyType(dict(resolved_secrets)),
        )


@dataclass(frozen=True, slots=True)
class OnlyIntegrationProbeResult:
    probe_attempt_id: str
    integration_id: str
    revision_fingerprint: str
    overall_status: OnlyIntegrationProbeStatus
    started_at: datetime
    completed_at: datetime
    probe_instrument: str | None
    checks: tuple[OnlyIntegrationProbeCheckResult, ...]

    @classmethod
    def create(
        cls,
        request: OnlyIntegrationProbeRequest,
        *,
        probe_instrument: str | None,
        checks: tuple[OnlyIntegrationProbeCheckResult, ...],
        started_at: datetime,
        completed_at: datetime,
    ) -> OnlyIntegrationProbeResult:
        _utc(started_at)
        _utc(completed_at)
        canonical = tuple(sorted(checks, key=lambda item: item.check.value))
        if (
            completed_at < started_at
            or {item.check for item in canonical} != set(request.required_checks)
            or len(canonical) != len(request.required_checks)
            or sum(len(item.observations) for item in canonical) > request.policy.maximum_observation_records
        ):
            raise ValueError("INTEGRATION_PROBE_RESULT_INVALID")
        return cls(
            request.probe_attempt_id,
            request.integration_id,
            request.revision_fingerprint,
            _status(canonical),
            started_at,
            completed_at,
            probe_instrument,
            canonical,
        )

    @classmethod
    def restore(
        cls,
        document: Mapping[str, object],
        fingerprint: str,
    ) -> OnlyIntegrationProbeResult:
        try:
            raw_checks = document["checks"]
            if not isinstance(raw_checks, list | tuple):
                raise TypeError
            checks = tuple(_restore_check(item) for item in raw_checks)
            result = cls(
                str(document["probe_attempt_id"]),
                str(document["integration_id"]),
                str(document["revision_fingerprint"]),
                OnlyIntegrationProbeStatus(str(document["overall_status"])),
                datetime.fromisoformat(str(document["started_at"])),
                datetime.fromisoformat(str(document["completed_at"])),
                None if document["probe_instrument"] is None else str(document["probe_instrument"]),
                checks,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("INTEGRATION_PROBE_RESULT_CORRUPT") from exc
        _uuid4(result.probe_attempt_id, "INTEGRATION_PROBE_RESULT_CORRUPT")
        _uuid4(result.integration_id, "INTEGRATION_PROBE_RESULT_CORRUPT")
        _fingerprint(result.revision_fingerprint)
        _utc(result.started_at)
        _utc(result.completed_at)
        if (
            result.completed_at < result.started_at
            or result.overall_status is OnlyIntegrationProbeStatus.UNKNOWN
            or _status(result.checks) is not result.overall_status
            or result.fingerprint != fingerprint
        ):
            raise ValueError("INTEGRATION_PROBE_RESULT_CORRUPT")
        return result

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "probe_attempt_id": self.probe_attempt_id,
            "integration_id": self.integration_id,
            "revision_fingerprint": self.revision_fingerprint,
            "overall_status": self.overall_status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "probe_instrument": self.probe_instrument,
            "checks": [item.to_dict() for item in self.checks],
        }


@runtime_checkable
class OnlyIntegrationProbeProvider(Protocol):
    def probe(self, request: OnlyIntegrationProbeRequest) -> OnlyIntegrationProbeResult: ...


def _status(checks: tuple[OnlyIntegrationProbeCheckResult, ...]) -> OnlyIntegrationProbeStatus:
    failures = {item.failure_kind for item in checks if item.status is OnlyIntegrationProbeCheckStatus.FAIL}
    if OnlyIntegrationProbeFailureKind.OFFLINE in failures:
        return OnlyIntegrationProbeStatus.OFFLINE
    if OnlyIntegrationProbeFailureKind.FAILED in failures:
        return OnlyIntegrationProbeStatus.FAILED
    if failures or any(item.status is OnlyIntegrationProbeCheckStatus.SKIPPED for item in checks):
        return OnlyIntegrationProbeStatus.DEGRADED
    return OnlyIntegrationProbeStatus.READY


def _restore_check(value: object) -> OnlyIntegrationProbeCheckResult:
    item = cast(Mapping[str, object], value)
    latency = item["latency_ms"]
    observations = item["observations"]
    if not isinstance(latency, int) or isinstance(latency, bool) or not isinstance(observations, list | tuple):
        raise TypeError
    failure_kind = item["failure_kind"]
    error_code = item["error_code"]
    return OnlyIntegrationProbeCheckResult(
        OnlyIntegrationProbeCheck(str(item["check"])),
        OnlyIntegrationProbeCheckStatus(str(item["status"])),
        latency,
        None if failure_kind is None else OnlyIntegrationProbeFailureKind(str(failure_kind)),
        None if error_code is None else str(error_code),
        str(item["detail"]),
        tuple(str(observation) for observation in observations),
    )


def _uuid4(value: str, code: str) -> None:
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(code) from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError(code)


def _fingerprint(value: str) -> None:
    if _FINGERPRINT.fullmatch(value) is None:
        raise ValueError("INTEGRATION_PROBE_CONFIGURATION_INVALID")


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("INTEGRATION_PROBE_RESULT_INVALID")


__all__ = [name for name in globals() if name.startswith("Only")]
