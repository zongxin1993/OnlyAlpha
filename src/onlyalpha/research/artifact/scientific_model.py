"""Portable self-contained Scientific Research Artifact V2 values."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.result.identity import (
    only_research_result_content_fingerprint,
    only_research_result_fingerprint,
)
from onlyalpha.research.result.plan import OnlyResearchResultPlan
from onlyalpha.research.result.result import (
    OnlyResearchCalculationResultReference,
    OnlyResearchStatisticsResultReference,
)

from .model import OnlyResearchArtifactStatisticsEntry, OnlyResearchArtifactStatisticsRow

RESEARCH_SCIENTIFIC_ARTIFACT_PROFILE = "RESEARCH_SCIENTIFIC_V2"
RESEARCH_SCIENTIFIC_ARTIFACT_SCHEMA_VERSION = 2
_SHA = re.compile(r"^[0-9a-f]{64}$")


class OnlyResearchScientificValueKind(StrEnum):
    DECIMAL = "DECIMAL"
    INTEGER = "INTEGER"
    BOOLEAN = "BOOLEAN"
    STRING = "STRING"


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchScientificMarketRow:
    instrument_id: str
    ts_event_ns: int
    open: str
    high: str
    low: str
    close: str
    volume: str

    def to_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchScientificVariableRow:
    candidate_fingerprint: str | None
    calculation_fingerprint: str
    node_fingerprint: str
    output_name: str
    instrument_id: str
    ts_event_ns: int
    value_kind: OnlyResearchScientificValueKind
    decimal_value: str | None = None
    integer_value: str | None = None
    boolean_value: bool | None = None
    string_value: str | None = None

    def __post_init__(self) -> None:
        populated = sum(
            item is not None for item in (self.decimal_value, self.integer_value, self.boolean_value, self.string_value)
        )
        if populated not in {0, 1}:
            raise ValueError("Scientific Variable row has multiple typed values")
        expected = {
            OnlyResearchScientificValueKind.DECIMAL: self.decimal_value,
            OnlyResearchScientificValueKind.INTEGER: self.integer_value,
            OnlyResearchScientificValueKind.BOOLEAN: self.boolean_value,
            OnlyResearchScientificValueKind.STRING: self.string_value,
        }[self.value_kind]
        if populated == 1 and expected is None:
            raise ValueError("Scientific Variable value does not match value_kind")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_fingerprint": self.candidate_fingerprint,
            "calculation_fingerprint": self.calculation_fingerprint,
            "node_fingerprint": self.node_fingerprint,
            "output_name": self.output_name,
            "instrument_id": self.instrument_id,
            "ts_event_ns": self.ts_event_ns,
            "value_kind": self.value_kind.value,
            "decimal_value": self.decimal_value,
            "integer_value": self.integer_value,
            "boolean_value": self.boolean_value,
            "string_value": self.string_value,
        }


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchScientificSignalRow:
    candidate_fingerprint: str
    role: str
    instrument_id: str
    ts_event_ns: int
    value: bool | None

    def to_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchScientificGraph:
    calculation_fingerprint: str
    graph: OnlyCalculationGraphDefinition

    def to_dict(self) -> dict[str, object]:
        return {"calculation_fingerprint": self.calculation_fingerprint, "graph": dict(self.graph.to_dict())}


@dataclass(frozen=True, slots=True)
class OnlyResearchScientificSection:
    relative_path: str
    row_count: int
    logical_fingerprint: str
    byte_sha256: str
    arrow_schema: tuple[dict[str, object], ...] | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "logical_fingerprint": self.logical_fingerprint,
            "byte_sha256": self.byte_sha256,
        }
        if self.arrow_schema is not None:
            payload["arrow_schema"] = list(self.arrow_schema)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchScientificSection:
        expected = {"relative_path", "row_count", "logical_fingerprint", "byte_sha256"}
        if "arrow_schema" in payload:
            expected.add("arrow_schema")
        if set(payload) != expected:
            raise ValueError("Scientific Artifact section fields are invalid")
        schema = payload.get("arrow_schema")
        if schema is not None and (not isinstance(schema, list) or any(not isinstance(item, dict) for item in schema)):
            raise ValueError("Scientific Artifact section schema is invalid")
        return cls(
            _string(payload["relative_path"]),
            _integer(payload["row_count"]),
            _sha(payload["logical_fingerprint"]),
            _sha(payload["byte_sha256"]),
            None if schema is None else tuple(dict(item) for item in schema),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchScientificArtifactManifest:
    plan: OnlyResearchResultPlan
    research_result_plan_fingerprint: str
    research_result_content_fingerprint: str
    research_result_fingerprint: str
    dataset_snapshot_fingerprint: str
    calculation_results: tuple[OnlyResearchCalculationResultReference, ...]
    statistics_results: tuple[OnlyResearchStatisticsResultReference, ...]
    statistics_catalog: tuple[OnlyResearchArtifactStatisticsEntry, ...]
    sections: tuple[OnlyResearchScientificSection, ...]
    artifact_content_fingerprint: str
    created_at: datetime
    profile: str = RESEARCH_SCIENTIFIC_ARTIFACT_PROFILE
    schema_version: int = RESEARCH_SCIENTIFIC_ARTIFACT_SCHEMA_VERSION
    research_result_schema_version: int = 2

    def __post_init__(self) -> None:
        if self.profile != RESEARCH_SCIENTIFIC_ARTIFACT_PROFILE or self.schema_version != 2:
            raise ValueError("Scientific Artifact profile/schema is unsupported")
        if self.plan.schema_version != 2 or self.plan.fingerprint != self.research_result_plan_fingerprint:
            raise ValueError("Scientific Artifact Result Plan linkage mismatch")
        if tuple(item.calculation_fingerprint for item in self.calculation_results) != tuple(
            item.calculation_fingerprint for item in self.plan.calculations
        ):
            raise ValueError("Scientific Artifact Calculation membership mismatch")
        if tuple(item.statistics_fingerprint for item in self.statistics_results) != self.plan.statistics_fingerprints:
            raise ValueError("Scientific Artifact Statistics membership mismatch")
        if self.dataset_snapshot_fingerprint != self.plan.dataset_snapshot_fingerprint:
            raise ValueError("Scientific Artifact Dataset linkage mismatch")
        content = only_research_result_content_fingerprint(
            tuple(item.to_dict() for item in self.statistics_results),
            tuple(item.to_dict() for item in self.calculation_results),
            schema_version=2,
        )
        if content != self.research_result_content_fingerprint:
            raise ValueError("Scientific Artifact Research Result content linkage mismatch")
        if (
            only_research_result_fingerprint(self.plan.fingerprint, content, schema_version=2)
            != self.research_result_fingerprint
        ):
            raise ValueError("Scientific Artifact Research Result identity linkage mismatch")
        if tuple(item.relative_path for item in self.sections) != (
            "graphs.json",
            "market.parquet",
            "signals.parquet",
            "statistics.parquet",
            "variables.parquet",
        ):
            raise ValueError("Scientific Artifact section set/order is invalid")
        expected = only_research_scientific_artifact_content_fingerprint(
            self.research_result_fingerprint, self.sections
        )
        if expected != self.artifact_content_fingerprint:
            raise ValueError("Scientific Artifact content fingerprint linkage mismatch")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("Scientific Artifact created_at must be timezone-aware UTC")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "research_result_schema_version": self.research_result_schema_version,
            "plan": self.plan.to_dict(),
            "research_result_plan_fingerprint": self.research_result_plan_fingerprint,
            "research_result_content_fingerprint": self.research_result_content_fingerprint,
            "research_result_fingerprint": self.research_result_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "calculation_results": [item.to_dict() for item in self.calculation_results],
            "statistics_results": [item.to_dict() for item in self.statistics_results],
            "statistics_catalog": [item.to_dict() for item in self.statistics_catalog],
            "sections": [item.to_dict() for item in self.sections],
            "artifact_content_fingerprint": self.artifact_content_fingerprint,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchScientificArtifactManifest:
        expected = {
            "schema_version",
            "profile",
            "research_result_schema_version",
            "plan",
            "research_result_plan_fingerprint",
            "research_result_content_fingerprint",
            "research_result_fingerprint",
            "dataset_snapshot_fingerprint",
            "calculation_results",
            "statistics_results",
            "statistics_catalog",
            "sections",
            "artifact_content_fingerprint",
            "created_at",
        }
        if set(payload) != expected:
            raise ValueError("Scientific Artifact manifest fields are invalid")

        def array(name: str) -> list[object]:
            value = payload[name]
            if not isinstance(value, list):
                raise ValueError(f"Scientific Artifact {name} must be an array")
            return value

        def mapping(value: object) -> Mapping[str, object]:
            if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
                raise ValueError("Scientific Artifact member must be an object")
            return value

        created = datetime.fromisoformat(_string(payload["created_at"]).replace("Z", "+00:00"))
        return cls(
            OnlyResearchResultPlan.from_dict(mapping(payload["plan"])),
            _sha(payload["research_result_plan_fingerprint"]),
            _sha(payload["research_result_content_fingerprint"]),
            _sha(payload["research_result_fingerprint"]),
            _sha(payload["dataset_snapshot_fingerprint"]),
            tuple(
                OnlyResearchCalculationResultReference.from_dict(mapping(item)) for item in array("calculation_results")
            ),
            tuple(
                OnlyResearchStatisticsResultReference.from_dict(mapping(item)) for item in array("statistics_results")
            ),
            tuple(OnlyResearchArtifactStatisticsEntry.from_dict(mapping(item)) for item in array("statistics_catalog")),
            tuple(OnlyResearchScientificSection.from_dict(mapping(item)) for item in array("sections")),
            _sha(payload["artifact_content_fingerprint"]),
            created,
            _string(payload["profile"]),
            _integer(payload["schema_version"]),
            _integer(payload["research_result_schema_version"]),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchScientificArtifact:
    manifest: OnlyResearchScientificArtifactManifest
    market_rows: tuple[OnlyResearchScientificMarketRow, ...]
    variable_rows: tuple[OnlyResearchScientificVariableRow, ...]
    signal_rows: tuple[OnlyResearchScientificSignalRow, ...]
    statistics_rows: tuple[OnlyResearchArtifactStatisticsRow, ...]
    graphs: tuple[OnlyResearchScientificGraph, ...]
    tables: Mapping[str, pa.Table]


def only_research_scientific_section_fingerprint(name: str, rows: object) -> str:
    return only_canonical_fingerprint({"schema_version": 1, "section": name, "rows": rows})


def only_research_scientific_artifact_content_fingerprint(
    research_result_fingerprint: str, sections: tuple[OnlyResearchScientificSection, ...]
) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": 2,
            "profile": RESEARCH_SCIENTIFIC_ARTIFACT_PROFILE,
            "research_result_fingerprint": research_result_fingerprint,
            "sections": [
                {
                    "relative_path": item.relative_path,
                    "row_count": item.row_count,
                    "logical_fingerprint": item.logical_fingerprint,
                }
                for item in sections
            ],
        }
    )


def _sha(value: object) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ValueError("value must be a lower-case SHA256")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("value must be a non-empty string")
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("value must be a non-negative integer")
    return value
