"""Immutable public values for the portable Research Artifact boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.research.evaluation.plan import OnlyResearchStatisticsPlan
from onlyalpha.research.evaluation.result import OnlyResearchStatisticRow, OnlyResearchStatisticStatus
from onlyalpha.research.evaluation.result_identity import (
    RESEARCH_STATISTICS_RESULT_SCHEMA_VERSION,
    only_research_statistics_result_fingerprint,
)
from onlyalpha.research.result.identity import (
    RESEARCH_RESULT_SCHEMA_VERSION,
    only_research_result_content_fingerprint,
    only_research_result_fingerprint,
)
from onlyalpha.research.result.plan import OnlyResearchResultPlan

from .identity import (
    RESEARCH_ARTIFACT_PROFILE,
    RESEARCH_ARTIFACT_SCHEMA_VERSION,
    only_research_artifact_content_fingerprint,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
RESEARCH_ARTIFACT_STATISTICS_PATH = "statistics.parquet"
RESEARCH_ARTIFACT_STATISTICS_SCHEMA: tuple[dict[str, object], ...] = (
    {"name": "statistics_fingerprint", "data_type": {"kind": "STRING"}, "nullable": False},
    {"name": "ts_event_ns", "data_type": {"kind": "INTEGER", "bit_width": 64, "signed": True}, "nullable": False},
    {
        "name": "statistic_value",
        "data_type": {"kind": "DECIMAL", "bit_width": 128, "precision": 38, "scale": 12},
        "nullable": True,
    },
    {"name": "sample_count", "data_type": {"kind": "INTEGER", "bit_width": 64, "signed": True}, "nullable": False},
    {"name": "status", "data_type": {"kind": "STRING"}, "nullable": False},
)


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchArtifactStatisticsEntry:
    statistics_fingerprint: str
    statistics_result_fingerprint: str
    result_content_fingerprint: str
    plan: OnlyResearchStatisticsPlan
    row_count: int
    statistics_result_schema_version: int = RESEARCH_STATISTICS_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.statistics_result_schema_version != RESEARCH_STATISTICS_RESULT_SCHEMA_VERSION:
            raise ValueError("Research Artifact Statistics Result schema is unsupported")
        _require_sha(self.statistics_fingerprint, "statistics_fingerprint")
        _require_sha(self.statistics_result_fingerprint, "statistics_result_fingerprint")
        _require_sha(self.result_content_fingerprint, "result_content_fingerprint")
        if not isinstance(self.plan, OnlyResearchStatisticsPlan):
            raise ValueError("Research Artifact Statistics Plan is invalid")
        if self.plan.statistics_fingerprint != self.statistics_fingerprint:
            raise ValueError("Research Artifact Statistics Plan linkage mismatch")
        expected = only_research_statistics_result_fingerprint(
            self.statistics_fingerprint, self.result_content_fingerprint
        )
        if expected != self.statistics_result_fingerprint:
            raise ValueError("Research Artifact Statistics Result linkage mismatch")
        if isinstance(self.row_count, bool) or not isinstance(self.row_count, int) or self.row_count < 0:
            raise ValueError("Research Artifact Statistics row_count is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "statistics_result_schema_version": self.statistics_result_schema_version,
            "statistics_fingerprint": self.statistics_fingerprint,
            "statistics_result_fingerprint": self.statistics_result_fingerprint,
            "result_content_fingerprint": self.result_content_fingerprint,
            "plan": self.plan.to_dict(),
            "row_count": self.row_count,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchArtifactStatisticsEntry:
        expected = {
            "statistics_result_schema_version",
            "statistics_fingerprint",
            "statistics_result_fingerprint",
            "result_content_fingerprint",
            "plan",
            "row_count",
        }
        if set(payload) != expected:
            raise ValueError("Research Artifact Statistics catalog fields are invalid")
        return cls(
            _sha(payload, "statistics_fingerprint"),
            _sha(payload, "statistics_result_fingerprint"),
            _sha(payload, "result_content_fingerprint"),
            OnlyResearchStatisticsPlan.from_dict(_mapping(payload["plan"], "Statistics Plan")),
            _integer(payload, "row_count"),
            _integer(payload, "statistics_result_schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchArtifactStatisticsTable:
    row_count: int
    data_byte_sha256: str
    relative_path: str = RESEARCH_ARTIFACT_STATISTICS_PATH
    arrow_schema: tuple[dict[str, object], ...] = RESEARCH_ARTIFACT_STATISTICS_SCHEMA

    def __post_init__(self) -> None:
        if self.relative_path != RESEARCH_ARTIFACT_STATISTICS_PATH:
            raise ValueError("Research Artifact Statistics path is unsupported")
        if isinstance(self.row_count, bool) or not isinstance(self.row_count, int) or self.row_count < 0:
            raise ValueError("Research Artifact table row_count is invalid")
        if self.arrow_schema != RESEARCH_ARTIFACT_STATISTICS_SCHEMA:
            raise ValueError("Research Artifact Statistics schema is unsupported")
        _require_sha(self.data_byte_sha256, "data_byte_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "arrow_schema": list(self.arrow_schema),
            "data_byte_sha256": self.data_byte_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchArtifactStatisticsTable:
        if set(payload) != {"relative_path", "row_count", "arrow_schema", "data_byte_sha256"}:
            raise ValueError("Research Artifact Statistics table fields are invalid")
        raw_schema = payload["arrow_schema"]
        if not isinstance(raw_schema, list) or any(not isinstance(item, dict) for item in raw_schema):
            raise ValueError("Research Artifact Statistics table schema is invalid")
        return cls(
            _integer(payload, "row_count"),
            _sha(payload, "data_byte_sha256"),
            _string(payload, "relative_path"),
            tuple(dict(item) for item in raw_schema),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchArtifactManifest:
    research_result_plan_fingerprint: str
    research_result_content_fingerprint: str
    research_result_fingerprint: str
    dataset_snapshot_fingerprint: str
    statistics_results: tuple[OnlyResearchArtifactStatisticsEntry, ...]
    statistics_table: OnlyResearchArtifactStatisticsTable
    artifact_content_fingerprint: str
    created_at: datetime
    research_result_schema_version: int = RESEARCH_RESULT_SCHEMA_VERSION
    profile: str = RESEARCH_ARTIFACT_PROFILE
    schema_version: int = RESEARCH_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_ARTIFACT_SCHEMA_VERSION or self.profile != RESEARCH_ARTIFACT_PROFILE:
            raise ValueError("Research Artifact schema/profile is unsupported")
        if self.research_result_schema_version != RESEARCH_RESULT_SCHEMA_VERSION:
            raise ValueError("Research Artifact Research Result schema is unsupported")
        for name, value in (
            ("research_result_plan_fingerprint", self.research_result_plan_fingerprint),
            ("research_result_content_fingerprint", self.research_result_content_fingerprint),
            ("research_result_fingerprint", self.research_result_fingerprint),
            ("dataset_snapshot_fingerprint", self.dataset_snapshot_fingerprint),
            ("artifact_content_fingerprint", self.artifact_content_fingerprint),
        ):
            _require_sha(value, name)
        if (
            not isinstance(self.statistics_results, tuple)
            or not self.statistics_results
            or any(not isinstance(item, OnlyResearchArtifactStatisticsEntry) for item in self.statistics_results)
        ):
            raise ValueError("Research Artifact Statistics catalog is invalid")
        if self.statistics_results != tuple(sorted(self.statistics_results)):
            raise ValueError("Research Artifact Statistics catalog is not canonical")
        identities = tuple(item.statistics_fingerprint for item in self.statistics_results)
        if len(identities) != len(set(identities)):
            raise ValueError("Research Artifact Statistics catalog contains duplicates")
        plan = OnlyResearchResultPlan(identities)
        if plan.fingerprint != self.research_result_plan_fingerprint:
            raise ValueError("Research Artifact Research Result Plan linkage mismatch")
        references = tuple(
            {
                "statistics_fingerprint": item.statistics_fingerprint,
                "statistics_result_fingerprint": item.statistics_result_fingerprint,
            }
            for item in self.statistics_results
        )
        content = only_research_result_content_fingerprint(references)
        if content != self.research_result_content_fingerprint:
            raise ValueError("Research Artifact Research Result content linkage mismatch")
        result = only_research_result_fingerprint(plan.fingerprint, content)
        if result != self.research_result_fingerprint:
            raise ValueError("Research Artifact Research Result linkage mismatch")
        if not isinstance(self.statistics_table, OnlyResearchArtifactStatisticsTable):
            raise ValueError("Research Artifact Statistics table is invalid")
        if self.statistics_table.row_count != sum(item.row_count for item in self.statistics_results):
            raise ValueError("Research Artifact table/catalog row count mismatch")
        artifact = only_research_artifact_content_fingerprint(
            self.research_result_fingerprint,
            self.dataset_snapshot_fingerprint,
            tuple(item.to_dict() for item in self.statistics_results),
        )
        if artifact != self.artifact_content_fingerprint:
            raise ValueError("Research Artifact content fingerprint linkage mismatch")
        if (
            not isinstance(self.created_at, datetime)
            or self.created_at.tzinfo is None
            or self.created_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("Research Artifact created_at must be timezone-aware UTC")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "research_result_schema_version": self.research_result_schema_version,
            "research_result_plan_fingerprint": self.research_result_plan_fingerprint,
            "research_result_content_fingerprint": self.research_result_content_fingerprint,
            "research_result_fingerprint": self.research_result_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "statistics_results": [item.to_dict() for item in self.statistics_results],
            "statistics_table": self.statistics_table.to_dict(),
            "artifact_content_fingerprint": self.artifact_content_fingerprint,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchArtifactManifest:
        expected = {
            "schema_version",
            "profile",
            "research_result_schema_version",
            "research_result_plan_fingerprint",
            "research_result_content_fingerprint",
            "research_result_fingerprint",
            "dataset_snapshot_fingerprint",
            "statistics_results",
            "statistics_table",
            "artifact_content_fingerprint",
            "created_at",
        }
        if set(payload) != expected:
            raise ValueError("Research Artifact manifest fields are invalid")
        raw_catalog = payload["statistics_results"]
        if not isinstance(raw_catalog, list):
            raise ValueError("Research Artifact Statistics catalog must be an array")
        return cls(
            _sha(payload, "research_result_plan_fingerprint"),
            _sha(payload, "research_result_content_fingerprint"),
            _sha(payload, "research_result_fingerprint"),
            _sha(payload, "dataset_snapshot_fingerprint"),
            tuple(
                OnlyResearchArtifactStatisticsEntry.from_dict(_mapping(item, "Statistics catalog entry"))
                for item in raw_catalog
            ),
            OnlyResearchArtifactStatisticsTable.from_dict(_mapping(payload["statistics_table"], "Statistics table")),
            _sha(payload, "artifact_content_fingerprint"),
            _datetime(payload, "created_at"),
            _integer(payload, "research_result_schema_version"),
            _string(payload, "profile"),
            _integer(payload, "schema_version"),
        )


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchArtifactStatisticsRow:
    statistics_fingerprint: str
    ts_event_ns: int
    statistic_value: Decimal | None
    sample_count: int
    status: OnlyResearchStatisticStatus

    def __post_init__(self) -> None:
        _require_sha(self.statistics_fingerprint, "statistics_fingerprint")
        OnlyResearchStatisticRow(self.ts_event_ns, self.statistic_value, self.sample_count, self.status)


@dataclass(frozen=True, slots=True)
class OnlyResearchArtifact:
    manifest: OnlyResearchArtifactManifest
    rows: tuple[OnlyResearchArtifactStatisticsRow, ...]
    table: pa.Table


class OnlyResearchArtifactDisposition(StrEnum):
    EXECUTED = "EXECUTED"
    REUSED = "REUSED"


@dataclass(frozen=True, slots=True)
class OnlyResearchArtifactOutcome:
    disposition: OnlyResearchArtifactDisposition
    research_result_fingerprint: str
    artifact_content_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, OnlyResearchArtifactDisposition):
            raise ValueError("Research Artifact disposition is invalid")
        _require_sha(self.research_result_fingerprint, "research_result_fingerprint")
        _require_sha(self.artifact_content_fingerprint, "artifact_content_fingerprint")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"Research Artifact {name} must be an object")
    return value


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"Research Artifact {name} must be a string")
    return value


def _require_sha(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"Research Artifact {name} must be a lower-case SHA256")
    return value


def _sha(payload: Mapping[str, object], name: str) -> str:
    return _require_sha(_string(payload, name), name)


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Research Artifact {name} must be an integer")
    return value


def _datetime(payload: Mapping[str, object], name: str) -> datetime:
    raw = _string(payload, name)
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Research Artifact {name} must be an ISO datetime") from exc
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"Research Artifact {name} must be timezone-aware UTC")
    return value
