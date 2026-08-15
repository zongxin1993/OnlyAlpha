"""Immutable Statistics rows, manifest, result, and invocation outcome."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

import pyarrow as pa  # type: ignore[import-untyped]

from .plan import OnlyResearchStatisticsPlan
from .result_identity import (
    RESEARCH_STATISTICS_RESULT_SCHEMA_VERSION,
    only_research_statistics_result_fingerprint,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class OnlyResearchStatisticStatus(StrEnum):
    VALID = "VALID"
    INSUFFICIENT_OBSERVATIONS = "INSUFFICIENT_OBSERVATIONS"
    ZERO_VARIANCE_FEATURE = "ZERO_VARIANCE_FEATURE"
    ZERO_VARIANCE_TARGET = "ZERO_VARIANCE_TARGET"


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticRow:
    ts_event_ns: int
    statistic_value: Decimal | None
    sample_count: int
    status: OnlyResearchStatisticStatus

    def __post_init__(self) -> None:
        if isinstance(self.ts_event_ns, bool) or not isinstance(self.ts_event_ns, int):
            raise ValueError("Statistics timestamp must be an integer")
        if isinstance(self.sample_count, bool) or not isinstance(self.sample_count, int) or self.sample_count < 0:
            raise ValueError("Statistics sample_count must be a non-negative integer")
        if self.statistic_value is not None and (
            not isinstance(self.statistic_value, Decimal) or not self.statistic_value.is_finite()
        ):
            raise ValueError("Statistics value must be finite Decimal or null")
        if self.status is OnlyResearchStatisticStatus.VALID:
            if self.statistic_value is None or not Decimal(-1) <= self.statistic_value <= Decimal(1):
                raise ValueError("VALID Statistics row requires value in [-1, 1]")
        elif self.statistic_value is not None:
            raise ValueError("non-VALID Statistics row requires a null value")

    def semantic_payload(self) -> dict[str, object]:
        return {
            "ts_event_ns": self.ts_event_ns,
            "statistic_value": self.statistic_value,
            "sample_count": self.sample_count,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticsResultManifest:
    statistics_fingerprint: str
    plan: OnlyResearchStatisticsPlan
    feature_calculation_result_fingerprint: str
    target_calculation_result_fingerprint: str
    dataset_snapshot_fingerprint: str
    result_content_fingerprint: str
    statistics_result_fingerprint: str
    row_count: int
    arrow_schema: tuple[dict[str, object], ...]
    data_byte_sha256: str
    created_at: datetime
    schema_version: int = RESEARCH_STATISTICS_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "statistics_fingerprint": self.statistics_fingerprint,
            "plan": self.plan.to_dict(),
            "feature_calculation_result_fingerprint": self.feature_calculation_result_fingerprint,
            "target_calculation_result_fingerprint": self.target_calculation_result_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "result_content_fingerprint": self.result_content_fingerprint,
            "statistics_result_fingerprint": self.statistics_result_fingerprint,
            "row_count": self.row_count,
            "arrow_schema": list(self.arrow_schema),
            "data_byte_sha256": self.data_byte_sha256,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchStatisticsResultManifest:
        expected = {
            "schema_version",
            "statistics_fingerprint",
            "plan",
            "feature_calculation_result_fingerprint",
            "target_calculation_result_fingerprint",
            "dataset_snapshot_fingerprint",
            "result_content_fingerprint",
            "statistics_result_fingerprint",
            "row_count",
            "arrow_schema",
            "data_byte_sha256",
            "created_at",
        }
        if set(payload) != expected:
            raise ValueError("Statistics Result manifest fields are invalid")
        version = _integer(payload, "schema_version")
        if version != RESEARCH_STATISTICS_RESULT_SCHEMA_VERSION:
            raise ValueError("Statistics Result schema is unsupported")
        plan = OnlyResearchStatisticsPlan.from_dict(_mapping(payload["plan"], "plan"))
        statistics = _sha(payload, "statistics_fingerprint")
        if statistics != plan.statistics_fingerprint:
            raise ValueError("Statistics fingerprint linkage mismatch")
        content = _sha(payload, "result_content_fingerprint")
        result = _sha(payload, "statistics_result_fingerprint")
        if only_research_statistics_result_fingerprint(statistics, content) != result:
            raise ValueError("Statistics Result fingerprint linkage mismatch")
        row_count = _integer(payload, "row_count")
        if row_count < 0:
            raise ValueError("Statistics Result row_count is invalid")
        raw_schema = payload["arrow_schema"]
        if not isinstance(raw_schema, list) or any(not isinstance(item, dict) for item in raw_schema):
            raise ValueError("Statistics Result arrow_schema is invalid")
        created = _datetime(payload, "created_at")
        return cls(
            statistics,
            plan,
            _sha(payload, "feature_calculation_result_fingerprint"),
            _sha(payload, "target_calculation_result_fingerprint"),
            _sha(payload, "dataset_snapshot_fingerprint"),
            content,
            result,
            row_count,
            tuple(dict(item) for item in raw_schema),
            _sha(payload, "data_byte_sha256"),
            created,
            version,
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticsResult:
    manifest: OnlyResearchStatisticsResultManifest
    rows: tuple[OnlyResearchStatisticRow, ...]
    table: pa.Table


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticsResultVerification:
    valid: bool
    statistics_fingerprint: str
    statistics_result_fingerprint: str
    row_count: int


class OnlyResearchStatisticsDisposition(StrEnum):
    EXECUTED = "EXECUTED"
    REUSED = "REUSED"


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticsOutcome:
    disposition: OnlyResearchStatisticsDisposition
    statistics_fingerprint: str
    statistics_result_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, OnlyResearchStatisticsDisposition):
            raise ValueError("Statistics Outcome disposition is invalid")
        if _SHA256.fullmatch(self.statistics_fingerprint) is None:
            raise ValueError("Statistics Outcome identity is invalid")
        if _SHA256.fullmatch(self.statistics_result_fingerprint) is None:
            raise ValueError("Statistics Outcome result identity is invalid")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"Statistics Result {name} must be an object")
    return value


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"Statistics Result {name} must be a string")
    return value


def _sha(payload: Mapping[str, object], name: str) -> str:
    value = _string(payload, name)
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"Statistics Result {name} must be a lower-case SHA256")
    return value


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Statistics Result {name} must be an integer")
    return value


def _datetime(payload: Mapping[str, object], name: str) -> datetime:
    raw = _string(payload, name)
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Statistics Result {name} must be an ISO datetime") from exc
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"Statistics Result {name} must be timezone-aware UTC")
    return value
