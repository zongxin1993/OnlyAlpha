"""Immutable Paper real-product acceptance models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from onlyalpha.domain.time import OnlyTimestamp


class OnlyAcceptanceVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_EXECUTED = "NOT_EXECUTED"


class OnlyAcceptanceExecutionStage(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    ENGINE_ASSEMBLY = "ENGINE_ASSEMBLY"
    ENGINE_INITIALIZE = "ENGINE_INITIALIZE"
    ENGINE_START = "ENGINE_START"
    HISTORICAL_WORKER = "HISTORICAL_WORKER"
    HISTORICAL_PARENT_VALIDATION = "HISTORICAL_PARENT_VALIDATION"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    HISTORICAL_WATERMARK = "HISTORICAL_WATERMARK"
    HISTORICAL_OBSERVATION = "HISTORICAL_OBSERVATION"
    CATCH_UP = "CATCH_UP"
    LIVE_COLLECTION = "LIVE_COLLECTION"
    LIVE_ASSERTION = "LIVE_ASSERTION"
    SHUTDOWN = "SHUTDOWN"


class OnlyAcceptanceFailureKind(StrEnum):
    PRODUCT_CONTRACT_FAILURE = "PRODUCT_CONTRACT_FAILURE"
    ACCEPTANCE_HARNESS_FAILURE = "ACCEPTANCE_HARNESS_FAILURE"
    EXTERNAL_PROVIDER_BLOCKED = "EXTERNAL_PROVIDER_BLOCKED"
    NOT_EXECUTED = "NOT_EXECUTED"


class OnlyAcceptanceCase(StrEnum):
    AUTOMATED_CONTRACT = "AUTOMATED_CONTRACT"
    REAL_HISTORICAL_SNAPSHOT = "REAL_HISTORICAL_SNAPSHOT"
    REAL_LIVE_HANDOFF = "REAL_LIVE_HANDOFF"
    ORDERED_SHUTDOWN = "ORDERED_SHUTDOWN"
    STOP_WITH_PENDING_BAR = "STOP_WITH_PENDING_BAR"
    KNOWN_BAD_NATIVE_ABORT = "KNOWN_BAD_NATIVE_ABORT"


@dataclass(frozen=True, slots=True)
class OnlyAcceptanceEvidence:
    evidence_id: str
    case_id: str
    category: str
    verdict: OnlyAcceptanceVerdict
    reason_code: str
    started_at: OnlyTimestamp
    completed_at: OnlyTimestamp
    expected: Mapping[str, object] = field(default_factory=dict)
    actual: Mapping[str, object] = field(default_factory=dict)
    artifact_paths: tuple[str, ...] = ()
    required: bool = True

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.case_id.strip() or not self.category.strip():
            raise ValueError("acceptance evidence identifiers cannot be blank")
        if self.completed_at < self.started_at:
            raise ValueError("acceptance evidence completion precedes its start")
        if any(_unsafe_artifact_path(path) for path in self.artifact_paths):
            raise ValueError("acceptance artifact paths must be relative and remain below the run root")
        object.__setattr__(self, "expected", MappingProxyType(dict(self.expected)))
        object.__setattr__(self, "actual", MappingProxyType(dict(self.actual)))
        object.__setattr__(self, "artifact_paths", tuple(self.artifact_paths))


def _unsafe_artifact_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return (
        not normalized
        or normalized.startswith("/")
        or ":" in normalized.split("/", 1)[0]
        or ".." in normalized.split("/")
    )
