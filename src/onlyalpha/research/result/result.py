"""Immutable Research Result composition values and manifest."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .identity import (
    RESEARCH_RESULT_SCHEMA_VERSION,
    RESEARCH_RESULT_SCIENTIFIC_SCHEMA_VERSION,
    only_research_result_content_fingerprint,
    only_research_result_fingerprint,
)
from .plan import OnlyResearchResultPlan

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchStatisticsResultReference:
    statistics_fingerprint: str
    statistics_result_fingerprint: str

    def __post_init__(self) -> None:
        for name, value in (
            ("statistics_fingerprint", self.statistics_fingerprint),
            ("statistics_result_fingerprint", self.statistics_result_fingerprint),
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError(f"Research Result reference {name} must be a lower-case SHA256")

    def to_dict(self) -> dict[str, str]:
        return {
            "statistics_fingerprint": self.statistics_fingerprint,
            "statistics_result_fingerprint": self.statistics_result_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchStatisticsResultReference:
        if set(payload) != {"statistics_fingerprint", "statistics_result_fingerprint"}:
            raise ValueError("Research Result Statistics reference fields are invalid")
        return cls(
            _string(payload, "statistics_fingerprint"),
            _string(payload, "statistics_result_fingerprint"),
        )


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchCalculationResultReference:
    calculation_fingerprint: str
    calculation_result_fingerprint: str

    def __post_init__(self) -> None:
        _require_sha(self.calculation_fingerprint, "calculation_fingerprint")
        _require_sha(self.calculation_result_fingerprint, "calculation_result_fingerprint")

    def to_dict(self) -> dict[str, str]:
        return {
            "calculation_fingerprint": self.calculation_fingerprint,
            "calculation_result_fingerprint": self.calculation_result_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchCalculationResultReference:
        if set(payload) != {"calculation_fingerprint", "calculation_result_fingerprint"}:
            raise ValueError("Research Result Calculation reference fields are invalid")
        return cls(_string(payload, "calculation_fingerprint"), _string(payload, "calculation_result_fingerprint"))


@dataclass(frozen=True, slots=True)
class OnlyResearchResultManifest:
    plan: OnlyResearchResultPlan
    research_result_plan_fingerprint: str
    dataset_snapshot_fingerprint: str
    statistics_results: tuple[OnlyResearchStatisticsResultReference, ...]
    research_result_content_fingerprint: str
    research_result_fingerprint: str
    created_at: datetime
    schema_version: int = RESEARCH_RESULT_SCHEMA_VERSION
    calculation_results: tuple[OnlyResearchCalculationResultReference, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version not in {RESEARCH_RESULT_SCHEMA_VERSION, RESEARCH_RESULT_SCIENTIFIC_SCHEMA_VERSION}:
            raise ValueError("Research Result schema is unsupported")
        if self.plan.schema_version != self.schema_version:
            raise ValueError("Research Result schema and Plan schema mismatch")
        if self.research_result_plan_fingerprint != self.plan.fingerprint:
            raise ValueError("Research Result Plan fingerprint linkage mismatch")
        _require_sha(self.dataset_snapshot_fingerprint, "dataset_snapshot_fingerprint")
        if not isinstance(self.statistics_results, tuple) or any(
            not isinstance(item, OnlyResearchStatisticsResultReference) for item in self.statistics_results
        ):
            raise ValueError("Research Result Statistics references are invalid")
        if self.statistics_results != tuple(sorted(self.statistics_results)):
            raise ValueError("Research Result Statistics references are not canonical")
        identities = tuple(item.statistics_fingerprint for item in self.statistics_results)
        if identities != self.plan.statistics_fingerprints:
            raise ValueError("Research Result Statistics references do not match Plan")
        if self.schema_version == RESEARCH_RESULT_SCHEMA_VERSION and self.calculation_results:
            raise ValueError("Research Result V1 cannot contain Calculation references")
        if self.schema_version == RESEARCH_RESULT_SCIENTIFIC_SCHEMA_VERSION:
            if not isinstance(self.calculation_results, tuple) or any(
                not isinstance(item, OnlyResearchCalculationResultReference) for item in self.calculation_results
            ):
                raise ValueError("Research Result Calculation references are invalid")
            if self.calculation_results != tuple(sorted(self.calculation_results)):
                raise ValueError("Research Result Calculation references are not canonical")
            if tuple(item.calculation_fingerprint for item in self.calculation_results) != tuple(
                item.calculation_fingerprint for item in self.plan.calculations
            ):
                raise ValueError("Research Result Calculation references do not match Plan")
        content = only_research_result_content_fingerprint(
            tuple(item.to_dict() for item in self.statistics_results),
            tuple(item.to_dict() for item in self.calculation_results),
            schema_version=self.schema_version,
        )
        if self.research_result_content_fingerprint != content:
            raise ValueError("Research Result content fingerprint linkage mismatch")
        result = only_research_result_fingerprint(
            self.research_result_plan_fingerprint, content, schema_version=self.schema_version
        )
        if self.research_result_fingerprint != result:
            raise ValueError("Research Result fingerprint linkage mismatch")
        if (
            not isinstance(self.created_at, datetime)
            or self.created_at.tzinfo is None
            or self.created_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("Research Result created_at must be timezone-aware UTC")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "plan": self.plan.to_dict(),
            "research_result_plan_fingerprint": self.research_result_plan_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "statistics_results": [item.to_dict() for item in self.statistics_results],
            "research_result_content_fingerprint": self.research_result_content_fingerprint,
            "research_result_fingerprint": self.research_result_fingerprint,
            "created_at": self.created_at.isoformat(),
        }
        if self.schema_version == RESEARCH_RESULT_SCIENTIFIC_SCHEMA_VERSION:
            payload["calculation_results"] = [item.to_dict() for item in self.calculation_results]
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchResultManifest:
        expected = {
            "schema_version",
            "plan",
            "research_result_plan_fingerprint",
            "dataset_snapshot_fingerprint",
            "statistics_results",
            "research_result_content_fingerprint",
            "research_result_fingerprint",
            "created_at",
        }
        version = _integer(payload, "schema_version")
        if version == RESEARCH_RESULT_SCIENTIFIC_SCHEMA_VERSION:
            expected.add("calculation_results")
        if set(payload) != expected:
            raise ValueError("Research Result manifest fields are invalid")
        plan = OnlyResearchResultPlan.from_dict(_mapping(payload["plan"], "plan"))
        raw_references = payload["statistics_results"]
        if not isinstance(raw_references, list):
            raise ValueError("Research Result Statistics references must be an array")
        references = tuple(
            OnlyResearchStatisticsResultReference.from_dict(_mapping(item, "statistics reference"))
            for item in raw_references
        )
        raw_calculations = payload.get("calculation_results", [])
        if not isinstance(raw_calculations, list):
            raise ValueError("Research Result Calculation references must be an array")
        return cls(
            plan,
            _sha(payload, "research_result_plan_fingerprint"),
            _sha(payload, "dataset_snapshot_fingerprint"),
            references,
            _sha(payload, "research_result_content_fingerprint"),
            _sha(payload, "research_result_fingerprint"),
            _datetime(payload, "created_at"),
            version,
            tuple(
                OnlyResearchCalculationResultReference.from_dict(_mapping(item, "calculation reference"))
                for item in raw_calculations
            ),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchResult:
    manifest: OnlyResearchResultManifest


class OnlyResearchResultDisposition(StrEnum):
    EXECUTED = "EXECUTED"
    REUSED = "REUSED"


@dataclass(frozen=True, slots=True)
class OnlyResearchResultOutcome:
    disposition: OnlyResearchResultDisposition
    research_result_plan_fingerprint: str
    research_result_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, OnlyResearchResultDisposition):
            raise ValueError("Research Result Outcome disposition is invalid")
        _require_sha(self.research_result_plan_fingerprint, "research_result_plan_fingerprint")
        _require_sha(self.research_result_fingerprint, "research_result_fingerprint")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"Research Result {name} must be an object")
    return value


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"Research Result {name} must be a string")
    return value


def _require_sha(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"Research Result {name} must be a lower-case SHA256")
    return value


def _sha(payload: Mapping[str, object], name: str) -> str:
    return _require_sha(_string(payload, name), name)


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Research Result {name} must be an integer")
    return value


def _datetime(payload: Mapping[str, object], name: str) -> datetime:
    raw = _string(payload, name)
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Research Result {name} must be an ISO datetime") from exc
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"Research Result {name} must be timezone-aware UTC")
    return value
