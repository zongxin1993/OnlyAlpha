"""Stable bounded contract for Search computation inside one exact Runtime Generation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

from onlyalpha.canonical import only_canonical_fingerprint

ONLYALPHA_SEARCH_GENERATION_EXECUTION_SCHEMA_VERSION = 1
ONLYALPHA_SEARCH_GENERATION_EXECUTION_CONTRACT_VERSION = "ONLYALPHA_SEARCH_GENERATION_EXECUTION_V1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class OnlySearchGenerationOperationV1(StrEnum):
    DERIVE_SYMBOLIC_ENUMERATION = "DERIVE_SYMBOLIC_ENUMERATION"
    DERIVE_PARAMETER_DECISION = "DERIVE_PARAMETER_DECISION"
    RESOLVE_SYMBOLIC_RESEARCH = "RESOLVE_SYMBOLIC_RESEARCH"
    RESOLVE_PARAMETER_RESEARCH = "RESOLVE_PARAMETER_RESEARCH"
    RESOLVE_RESEARCH_ADMISSION = "RESOLVE_RESEARCH_ADMISSION"


class OnlyHistoricalGenerationExecutionError(RuntimeError):
    code = "HISTORICAL_GENERATION_UNAVAILABLE"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(f"{self.code}: {detail}" if detail else self.code)


class OnlyHistoricalGenerationNotFound(OnlyHistoricalGenerationExecutionError):
    code = "HISTORICAL_GENERATION_NOT_FOUND"


class OnlyHistoricalGenerationUnavailable(OnlyHistoricalGenerationExecutionError):
    code = "HISTORICAL_GENERATION_UNAVAILABLE"


class OnlyHistoricalGenerationArtifactMissing(OnlyHistoricalGenerationExecutionError):
    code = "HISTORICAL_GENERATION_ARTIFACT_MISSING"


class OnlyHistoricalGenerationCorrupt(OnlyHistoricalGenerationExecutionError):
    code = "HISTORICAL_GENERATION_CORRUPT"


class OnlyHistoricalGenerationHostMismatch(OnlyHistoricalGenerationExecutionError):
    code = "HISTORICAL_GENERATION_HOST_MISMATCH"


class OnlyHistoricalGenerationProtocolMismatch(OnlyHistoricalGenerationExecutionError):
    code = "HISTORICAL_GENERATION_PROTOCOL_MISMATCH"


class OnlyHistoricalGenerationCapabilityUnsupported(OnlyHistoricalGenerationExecutionError):
    code = "HISTORICAL_GENERATION_CAPABILITY_UNSUPPORTED"


class OnlyHistoricalGenerationExecutionMismatch(OnlyHistoricalGenerationExecutionError):
    code = "HISTORICAL_GENERATION_EXECUTION_MISMATCH"


class OnlyHistoricalGenerationWorkerUnavailable(OnlyHistoricalGenerationExecutionError):
    code = "HISTORICAL_GENERATION_WORKER_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class OnlySearchGenerationExecutionRequestV1:
    runtime_generation_fingerprint: str
    operation_kind: OnlySearchGenerationOperationV1
    request_payload: Mapping[str, object]
    schema_version: int = ONLYALPHA_SEARCH_GENERATION_EXECUTION_SCHEMA_VERSION
    execution_contract_version: str = ONLYALPHA_SEARCH_GENERATION_EXECUTION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _contract(self.schema_version, self.execution_contract_version)
        _sha(self.runtime_generation_fingerprint)
        if not isinstance(self.operation_kind, OnlySearchGenerationOperationV1):
            raise OnlyHistoricalGenerationCapabilityUnsupported(str(self.operation_kind))
        object.__setattr__(self, "request_payload", _mapping(self.request_payload))

    @property
    def request_fingerprint(self) -> str:
        """Deterministic correlation value; it is not a Search semantic identity."""

        return only_canonical_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "execution_contract_version": self.execution_contract_version,
            "runtime_generation_fingerprint": self.runtime_generation_fingerprint,
            "operation_kind": self.operation_kind.value,
            "request_payload": dict(self.request_payload),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchGenerationExecutionRequestV1:
        _exact(
            payload,
            {
                "schema_version",
                "execution_contract_version",
                "runtime_generation_fingerprint",
                "operation_kind",
                "request_payload",
            },
        )
        try:
            operation = OnlySearchGenerationOperationV1(_string(payload, "operation_kind"))
        except ValueError as exc:
            raise OnlyHistoricalGenerationCapabilityUnsupported(str(payload.get("operation_kind"))) from exc
        return cls(
            _string(payload, "runtime_generation_fingerprint"),
            operation,
            _mapping(payload["request_payload"]),
            _integer(payload, "schema_version"),
            _string(payload, "execution_contract_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlySearchGenerationExecutionResponseV1:
    runtime_generation_fingerprint: str
    operation_kind: OnlySearchGenerationOperationV1
    result_payload: Mapping[str, object]
    result_fingerprint: str | None = None
    schema_version: int = ONLYALPHA_SEARCH_GENERATION_EXECUTION_SCHEMA_VERSION
    execution_contract_version: str = ONLYALPHA_SEARCH_GENERATION_EXECUTION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _contract(self.schema_version, self.execution_contract_version)
        _sha(self.runtime_generation_fingerprint)
        if not isinstance(self.operation_kind, OnlySearchGenerationOperationV1):
            raise OnlyHistoricalGenerationCapabilityUnsupported(str(self.operation_kind))
        canonical = _mapping(self.result_payload)
        fingerprint = only_canonical_fingerprint(canonical)
        if self.result_fingerprint is not None and self.result_fingerprint != fingerprint:
            raise OnlyHistoricalGenerationExecutionMismatch("result fingerprint differs")
        object.__setattr__(self, "result_payload", canonical)
        object.__setattr__(self, "result_fingerprint", fingerprint)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "execution_contract_version": self.execution_contract_version,
            "runtime_generation_fingerprint": self.runtime_generation_fingerprint,
            "operation_kind": self.operation_kind.value,
            "result_payload": dict(self.result_payload),
            "result_fingerprint": self.result_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchGenerationExecutionResponseV1:
        _exact(
            payload,
            {
                "schema_version",
                "execution_contract_version",
                "runtime_generation_fingerprint",
                "operation_kind",
                "result_payload",
                "result_fingerprint",
            },
        )
        try:
            operation = OnlySearchGenerationOperationV1(_string(payload, "operation_kind"))
        except ValueError as exc:
            raise OnlyHistoricalGenerationCapabilityUnsupported(str(payload.get("operation_kind"))) from exc
        return cls(
            _string(payload, "runtime_generation_fingerprint"),
            operation,
            _mapping(payload["result_payload"]),
            _string(payload, "result_fingerprint"),
            _integer(payload, "schema_version"),
            _string(payload, "execution_contract_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlySearchGenerationExecutionFailureV1:
    runtime_generation_fingerprint: str
    error_code: str
    error_detail: str
    schema_version: int = ONLYALPHA_SEARCH_GENERATION_EXECUTION_SCHEMA_VERSION
    execution_contract_version: str = ONLYALPHA_SEARCH_GENERATION_EXECUTION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _contract(self.schema_version, self.execution_contract_version)
        _sha(self.runtime_generation_fingerprint)
        if self.error_code not in _ERROR_TYPES or not isinstance(self.error_detail, str):
            raise OnlyHistoricalGenerationProtocolMismatch("worker failure vocabulary differs")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "execution_contract_version": self.execution_contract_version,
            "runtime_generation_fingerprint": self.runtime_generation_fingerprint,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchGenerationExecutionFailureV1:
        _exact(
            payload,
            {
                "schema_version",
                "execution_contract_version",
                "runtime_generation_fingerprint",
                "error_code",
                "error_detail",
            },
        )
        return cls(
            _string(payload, "runtime_generation_fingerprint"),
            _string(payload, "error_code"),
            _string(payload, "error_detail"),
            _integer(payload, "schema_version"),
            _string(payload, "execution_contract_version"),
        )

    def raise_error(self) -> None:
        raise _ERROR_TYPES[self.error_code](self.error_detail)


@dataclass(frozen=True, slots=True)
class OnlySearchGenerationWorkerHandshakeV1:
    runtime_generation_fingerprint: str
    core_execution_fingerprint: str
    catalog_generation_fingerprint: str
    validation_evidence_fingerprint: str
    supported_capabilities: tuple[OnlySearchGenerationOperationV1, ...]
    schema_version: int = ONLYALPHA_SEARCH_GENERATION_EXECUTION_SCHEMA_VERSION
    execution_contract_version: str = ONLYALPHA_SEARCH_GENERATION_EXECUTION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _contract(self.schema_version, self.execution_contract_version)
        for value in (
            self.runtime_generation_fingerprint,
            self.core_execution_fingerprint,
            self.catalog_generation_fingerprint,
            self.validation_evidence_fingerprint,
        ):
            _sha(value)
        capabilities = tuple(sorted(set(self.supported_capabilities), key=lambda item: item.value))
        if not capabilities or len(capabilities) != len(self.supported_capabilities):
            raise OnlyHistoricalGenerationCapabilityUnsupported("worker advertises no exact capability set")
        object.__setattr__(self, "supported_capabilities", capabilities)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "execution_contract_version": self.execution_contract_version,
            "runtime_generation_fingerprint": self.runtime_generation_fingerprint,
            "core_execution_fingerprint": self.core_execution_fingerprint,
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "validation_evidence_fingerprint": self.validation_evidence_fingerprint,
            "supported_capabilities": [item.value for item in self.supported_capabilities],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchGenerationWorkerHandshakeV1:
        _exact(
            payload,
            {
                "schema_version",
                "execution_contract_version",
                "runtime_generation_fingerprint",
                "core_execution_fingerprint",
                "catalog_generation_fingerprint",
                "validation_evidence_fingerprint",
                "supported_capabilities",
            },
        )
        raw = payload["supported_capabilities"]
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            raise OnlyHistoricalGenerationProtocolMismatch("capability list is invalid")
        try:
            capabilities = tuple(OnlySearchGenerationOperationV1(item) for item in cast(list[str], raw))
        except ValueError as exc:
            raise OnlyHistoricalGenerationCapabilityUnsupported("unknown worker capability") from exc
        return cls(
            _string(payload, "runtime_generation_fingerprint"),
            _string(payload, "core_execution_fingerprint"),
            _string(payload, "catalog_generation_fingerprint"),
            _string(payload, "validation_evidence_fingerprint"),
            capabilities,
            _integer(payload, "schema_version"),
            _string(payload, "execution_contract_version"),
        )


class OnlySearchGenerationExecutionPort(Protocol):
    def execute(
        self,
        request: OnlySearchGenerationExecutionRequestV1,
    ) -> OnlySearchGenerationExecutionResponseV1: ...


_ERROR_TYPES: dict[str, type[OnlyHistoricalGenerationExecutionError]] = {
    item.code: item
    for item in (
        OnlyHistoricalGenerationNotFound,
        OnlyHistoricalGenerationUnavailable,
        OnlyHistoricalGenerationArtifactMissing,
        OnlyHistoricalGenerationCorrupt,
        OnlyHistoricalGenerationHostMismatch,
        OnlyHistoricalGenerationProtocolMismatch,
        OnlyHistoricalGenerationCapabilityUnsupported,
        OnlyHistoricalGenerationExecutionMismatch,
        OnlyHistoricalGenerationWorkerUnavailable,
    )
}


def _contract(schema: object, version: object) -> None:
    if schema != ONLYALPHA_SEARCH_GENERATION_EXECUTION_SCHEMA_VERSION or (
        version != ONLYALPHA_SEARCH_GENERATION_EXECUTION_CONTRACT_VERSION
    ):
        raise OnlyHistoricalGenerationProtocolMismatch("execution contract version differs")


def _sha(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise OnlyHistoricalGenerationProtocolMismatch("runtime identity is invalid")
    return value


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise OnlyHistoricalGenerationProtocolMismatch("protocol payload must be an object")
    return cast(Mapping[str, object], value)


def _exact(payload: Mapping[str, object], expected: set[str]) -> None:
    if set(payload) != expected:
        raise OnlyHistoricalGenerationProtocolMismatch("protocol fields differ")


def _string(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise OnlyHistoricalGenerationProtocolMismatch(f"{key} must be a string")
    return value


def _integer(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise OnlyHistoricalGenerationProtocolMismatch(f"{key} must be an integer")
    return value


__all__ = [name for name in globals() if name.startswith(("ONLYALPHA_", "Only"))]
