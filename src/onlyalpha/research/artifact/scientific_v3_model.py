"""Portable typed Scientific Research Artifact V3 contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.evaluation.factor_pair.plan import OnlyResearchFactorPairStatisticsPlan
from onlyalpha.research.evaluation.plan import OnlyResearchStatisticsPlan
from onlyalpha.research.evaluation.summary.family import OnlyResearchStatisticsFamily
from onlyalpha.research.evaluation.summary.plan import (
    OnlyResearchSummaryPlan,
    only_research_summary_plan_from_dict,
)
from onlyalpha.research.evaluation.summary.result import OnlyResearchSummary
from onlyalpha.research.result.identity import (
    only_research_result_content_fingerprint,
    only_research_result_fingerprint,
)
from onlyalpha.research.result.plan import OnlyResearchResultPlan
from onlyalpha.research.result.result import (
    OnlyResearchCalculationResultReference,
    OnlyResearchStatisticsResultReference,
)

from .scientific_model import (
    OnlyResearchScientificGraph,
    OnlyResearchScientificMarketRow,
    OnlyResearchScientificSection,
    OnlyResearchScientificSignalRow,
    OnlyResearchScientificVariableRow,
)

RESEARCH_SCIENTIFIC_ARTIFACT_V3_PROFILE = "RESEARCH_SCIENTIFIC_V3"
RESEARCH_SCIENTIFIC_ARTIFACT_V3_SCHEMA_VERSION = 3
RESEARCH_SCIENTIFIC_ARTIFACT_V3_SECTION_PATHS = (
    "graphs.json",
    "market.parquet",
    "signals.parquet",
    "statistics_catalog.json",
    "statistics_series.parquet",
    "statistics_summaries.json",
    "variables.parquet",
)
_SHA = re.compile(r"^[0-9a-f]{64}$")


class OnlyResearchScientificStatisticsShapeV3(StrEnum):
    SERIES = "SERIES"
    SUMMARY = "SUMMARY"


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchScientificStatisticsSeriesRowV3:
    statistics_fingerprint: str
    ts_event_ns: int
    statistic_value: Decimal | None
    sample_count: int
    status: str

    def __post_init__(self) -> None:
        _sha(self.statistics_fingerprint)
        if isinstance(self.ts_event_ns, bool) or not isinstance(self.ts_event_ns, int):
            raise ValueError("Scientific V3 Series timestamp must be an integer")
        if isinstance(self.sample_count, bool) or not isinstance(self.sample_count, int) or self.sample_count < 0:
            raise ValueError("Scientific V3 Series sample_count is invalid")
        if self.statistic_value is not None and (
            not isinstance(self.statistic_value, Decimal) or not self.statistic_value.is_finite()
        ):
            raise ValueError("Scientific V3 Series value is invalid")
        if not isinstance(self.status, str) or not self.status:
            raise ValueError("Scientific V3 Series status is invalid")

    def semantic_payload(self) -> dict[str, object]:
        return {
            "statistics_fingerprint": self.statistics_fingerprint,
            "ts_event_ns": self.ts_event_ns,
            "statistic_value": self.statistic_value,
            "sample_count": self.sample_count,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchScientificStatisticsSummaryV3:
    statistics_fingerprint: str
    summary: OnlyResearchSummary

    def __post_init__(self) -> None:
        _sha(self.statistics_fingerprint)

    def to_dict(self) -> dict[str, object]:
        return {"statistics_fingerprint": self.statistics_fingerprint, "summary": self.summary.to_dict()}


@dataclass(frozen=True, slots=True)
class OnlyResearchScientificLegacySeriesCatalogEntryV3:
    statistics_fingerprint: str
    statistics_result_fingerprint: str
    result_content_fingerprint: str
    dataset_snapshot_fingerprint: str
    plan: OnlyResearchStatisticsPlan
    feature_calculation_result_fingerprint: str
    target_calculation_result_fingerprint: str
    row_count: int
    result_schema_version: int = 1
    statistics_family: OnlyResearchStatisticsFamily = OnlyResearchStatisticsFamily.FEATURE_TARGET_CORRELATION_SERIES_V1
    payload_shape: OnlyResearchScientificStatisticsShapeV3 = OnlyResearchScientificStatisticsShapeV3.SERIES

    def __post_init__(self) -> None:
        _catalog_common(self)
        if self.statistics_family is not OnlyResearchStatisticsFamily.FEATURE_TARGET_CORRELATION_SERIES_V1:
            raise ValueError("Scientific V3 legacy Catalog family mismatch")
        if self.plan.statistics_fingerprint != self.statistics_fingerprint:
            raise ValueError("Scientific V3 legacy Plan identity mismatch")
        _sha(self.feature_calculation_result_fingerprint)
        _sha(self.target_calculation_result_fingerprint)
        _row_count(self.row_count)

    def to_dict(self) -> dict[str, object]:
        return _catalog_dict(self) | {
            "feature_calculation_result_fingerprint": self.feature_calculation_result_fingerprint,
            "target_calculation_result_fingerprint": self.target_calculation_result_fingerprint,
            "row_count": self.row_count,
        }


@dataclass(frozen=True, slots=True)
class OnlyResearchScientificFactorPairSeriesCatalogEntryV3:
    statistics_fingerprint: str
    statistics_result_fingerprint: str
    result_content_fingerprint: str
    dataset_snapshot_fingerprint: str
    plan: OnlyResearchFactorPairStatisticsPlan
    first_calculation_result_fingerprint: str
    second_calculation_result_fingerprint: str
    row_count: int
    result_schema_version: int = 1
    statistics_family: OnlyResearchStatisticsFamily = OnlyResearchStatisticsFamily.FACTOR_PAIR_CORRELATION_SERIES_V1
    payload_shape: OnlyResearchScientificStatisticsShapeV3 = OnlyResearchScientificStatisticsShapeV3.SERIES

    def __post_init__(self) -> None:
        _catalog_common(self)
        if self.statistics_family is not OnlyResearchStatisticsFamily.FACTOR_PAIR_CORRELATION_SERIES_V1:
            raise ValueError("Scientific V3 Factor-Pair Catalog family mismatch")
        if self.plan.statistics_fingerprint != self.statistics_fingerprint:
            raise ValueError("Scientific V3 Factor-Pair Plan identity mismatch")
        _sha(self.first_calculation_result_fingerprint)
        _sha(self.second_calculation_result_fingerprint)
        _row_count(self.row_count)

    def to_dict(self) -> dict[str, object]:
        return _catalog_dict(self) | {
            "first_calculation_result_fingerprint": self.first_calculation_result_fingerprint,
            "second_calculation_result_fingerprint": self.second_calculation_result_fingerprint,
            "row_count": self.row_count,
        }


@dataclass(frozen=True, slots=True)
class OnlyResearchScientificSummaryCatalogEntryV3:
    statistics_fingerprint: str
    statistics_result_fingerprint: str
    result_content_fingerprint: str
    dataset_snapshot_fingerprint: str
    plan: OnlyResearchSummaryPlan
    result_schema_version: int = 1
    statistics_family: OnlyResearchStatisticsFamily = OnlyResearchStatisticsFamily.SUMMARY_STATISTICS_V1
    payload_shape: OnlyResearchScientificStatisticsShapeV3 = OnlyResearchScientificStatisticsShapeV3.SUMMARY

    def __post_init__(self) -> None:
        _catalog_common(self)
        if self.statistics_family is not OnlyResearchStatisticsFamily.SUMMARY_STATISTICS_V1:
            raise ValueError("Scientific V3 Summary Catalog family mismatch")
        if self.plan.statistics_fingerprint != self.statistics_fingerprint:
            raise ValueError("Scientific V3 Summary Plan identity mismatch")

    def to_dict(self) -> dict[str, object]:
        return _catalog_dict(self)


OnlyResearchScientificStatisticsCatalogEntryV3 = (
    OnlyResearchScientificLegacySeriesCatalogEntryV3
    | OnlyResearchScientificFactorPairSeriesCatalogEntryV3
    | OnlyResearchScientificSummaryCatalogEntryV3
)


def only_research_scientific_catalog_entry_v3_from_dict(
    payload: Mapping[str, object],
) -> OnlyResearchScientificStatisticsCatalogEntryV3:
    family = OnlyResearchStatisticsFamily(_string(payload, "statistics_family"))
    shape = OnlyResearchScientificStatisticsShapeV3(_string(payload, "payload_shape"))
    logical = _string(payload, "statistics_fingerprint")
    result = _string(payload, "statistics_result_fingerprint")
    content = _string(payload, "result_content_fingerprint")
    dataset = _string(payload, "dataset_snapshot_fingerprint")
    version = _integer(payload, "result_schema_version")
    raw_plan = _mapping(payload, "plan")
    if family is OnlyResearchStatisticsFamily.FEATURE_TARGET_CORRELATION_SERIES_V1:
        _exact_fields(
            payload,
            _COMMON_FIELDS
            | {"feature_calculation_result_fingerprint", "target_calculation_result_fingerprint", "row_count"},
        )
        return OnlyResearchScientificLegacySeriesCatalogEntryV3(
            logical,
            result,
            content,
            dataset,
            plan=OnlyResearchStatisticsPlan.from_dict(raw_plan),
            feature_calculation_result_fingerprint=_string(payload, "feature_calculation_result_fingerprint"),
            target_calculation_result_fingerprint=_string(payload, "target_calculation_result_fingerprint"),
            row_count=_integer(payload, "row_count"),
            result_schema_version=version,
            statistics_family=family,
            payload_shape=shape,
        )
    if family is OnlyResearchStatisticsFamily.FACTOR_PAIR_CORRELATION_SERIES_V1:
        _exact_fields(
            payload,
            _COMMON_FIELDS
            | {"first_calculation_result_fingerprint", "second_calculation_result_fingerprint", "row_count"},
        )
        return OnlyResearchScientificFactorPairSeriesCatalogEntryV3(
            logical,
            result,
            content,
            dataset,
            plan=OnlyResearchFactorPairStatisticsPlan.from_dict(raw_plan),
            first_calculation_result_fingerprint=_string(payload, "first_calculation_result_fingerprint"),
            second_calculation_result_fingerprint=_string(payload, "second_calculation_result_fingerprint"),
            row_count=_integer(payload, "row_count"),
            result_schema_version=version,
            statistics_family=family,
            payload_shape=shape,
        )
    if family is OnlyResearchStatisticsFamily.SUMMARY_STATISTICS_V1:
        _exact_fields(payload, _COMMON_FIELDS)
        return OnlyResearchScientificSummaryCatalogEntryV3(
            logical,
            result,
            content,
            dataset,
            only_research_summary_plan_from_dict(raw_plan),
            version,
            family,
            shape,
        )
    raise ValueError("Scientific V3 Statistics family is unsupported")  # pragma: no cover


@dataclass(frozen=True, slots=True)
class OnlyResearchScientificArtifactManifestV3:
    plan: OnlyResearchResultPlan
    research_result_plan_fingerprint: str
    research_result_content_fingerprint: str
    research_result_fingerprint: str
    dataset_snapshot_fingerprint: str
    calculation_results: tuple[OnlyResearchCalculationResultReference, ...]
    statistics_results: tuple[OnlyResearchStatisticsResultReference, ...]
    sections: tuple[OnlyResearchScientificSection, ...]
    artifact_content_fingerprint: str
    created_at: datetime
    profile: str = RESEARCH_SCIENTIFIC_ARTIFACT_V3_PROFILE
    schema_version: int = RESEARCH_SCIENTIFIC_ARTIFACT_V3_SCHEMA_VERSION
    research_result_schema_version: int = 2

    def __post_init__(self) -> None:
        if self.profile != RESEARCH_SCIENTIFIC_ARTIFACT_V3_PROFILE or self.schema_version != 3:
            raise ValueError("Scientific Artifact V3 profile/schema is unsupported")
        if self.research_result_schema_version != 2 or self.plan.schema_version != 2:
            raise ValueError("Scientific Artifact V3 requires Research Result V2")
        if self.plan.fingerprint != self.research_result_plan_fingerprint:
            raise ValueError("Scientific Artifact V3 Result Plan linkage mismatch")
        if self.dataset_snapshot_fingerprint != self.plan.dataset_snapshot_fingerprint:
            raise ValueError("Scientific Artifact V3 Dataset linkage mismatch")
        if tuple(x.calculation_fingerprint for x in self.calculation_results) != tuple(
            x.calculation_fingerprint for x in self.plan.calculations
        ):
            raise ValueError("Scientific Artifact V3 Calculation membership mismatch")
        if tuple(x.statistics_fingerprint for x in self.statistics_results) != self.plan.statistics_fingerprints:
            raise ValueError("Scientific Artifact V3 Statistics membership mismatch")
        content = only_research_result_content_fingerprint(
            tuple(x.to_dict() for x in self.statistics_results),
            tuple(x.to_dict() for x in self.calculation_results),
            schema_version=2,
        )
        if content != self.research_result_content_fingerprint:
            raise ValueError("Scientific Artifact V3 Research Result content mismatch")
        if (
            only_research_result_fingerprint(self.plan.fingerprint, content, schema_version=2)
            != self.research_result_fingerprint
        ):
            raise ValueError("Scientific Artifact V3 Research Result identity mismatch")
        if tuple(x.relative_path for x in self.sections) != RESEARCH_SCIENTIFIC_ARTIFACT_V3_SECTION_PATHS:
            raise ValueError("Scientific Artifact V3 section set/order is invalid")
        if (
            only_research_scientific_artifact_v3_content_fingerprint(self.research_result_fingerprint, self.sections)
            != self.artifact_content_fingerprint
        ):
            raise ValueError("Scientific Artifact V3 content fingerprint mismatch")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("Scientific Artifact V3 created_at must be timezone-aware UTC")

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
            "calculation_results": [x.to_dict() for x in self.calculation_results],
            "statistics_results": [x.to_dict() for x in self.statistics_results],
            "sections": [x.to_dict() for x in self.sections],
            "artifact_content_fingerprint": self.artifact_content_fingerprint,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchScientificArtifactManifestV3:
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
            "sections",
            "artifact_content_fingerprint",
            "created_at",
        }
        _exact_fields(payload, expected)
        plan = OnlyResearchResultPlan.from_dict(_mapping(payload, "plan"))
        created = datetime.fromisoformat(_string(payload, "created_at").replace("Z", "+00:00"))
        return cls(
            plan,
            _string(payload, "research_result_plan_fingerprint"),
            _string(payload, "research_result_content_fingerprint"),
            _string(payload, "research_result_fingerprint"),
            _string(payload, "dataset_snapshot_fingerprint"),
            tuple(
                OnlyResearchCalculationResultReference.from_dict(x)
                for x in _mapping_array(payload, "calculation_results")
            ),
            tuple(
                OnlyResearchStatisticsResultReference.from_dict(x)
                for x in _mapping_array(payload, "statistics_results")
            ),
            tuple(OnlyResearchScientificSection.from_dict(x) for x in _mapping_array(payload, "sections")),
            _string(payload, "artifact_content_fingerprint"),
            created,
            _string(payload, "profile"),
            _integer(payload, "schema_version"),
            _integer(payload, "research_result_schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchScientificArtifactV3:
    manifest: OnlyResearchScientificArtifactManifestV3
    market_rows: tuple[OnlyResearchScientificMarketRow, ...]
    variable_rows: tuple[OnlyResearchScientificVariableRow, ...]
    signal_rows: tuple[OnlyResearchScientificSignalRow, ...]
    graphs: tuple[OnlyResearchScientificGraph, ...]
    statistics_catalog: tuple[OnlyResearchScientificStatisticsCatalogEntryV3, ...]
    statistics_series_rows: tuple[OnlyResearchScientificStatisticsSeriesRowV3, ...]
    statistics_summaries: tuple[OnlyResearchScientificStatisticsSummaryV3, ...]
    tables: Mapping[str, pa.Table]


def only_research_scientific_v3_section_fingerprint(name: str, rows: object) -> str:
    return only_canonical_fingerprint({"schema_version": 1, "section": name, "rows": rows})


def only_research_scientific_artifact_v3_content_fingerprint(
    research_result_fingerprint: str, sections: tuple[OnlyResearchScientificSection, ...]
) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": 3,
            "profile": RESEARCH_SCIENTIFIC_ARTIFACT_V3_PROFILE,
            "research_result_fingerprint": research_result_fingerprint,
            "sections": [
                {
                    "relative_path": x.relative_path,
                    "row_count": x.row_count,
                    "logical_fingerprint": x.logical_fingerprint,
                }
                for x in sections
            ],
        }
    )


_COMMON_FIELDS = {
    "statistics_family",
    "payload_shape",
    "statistics_fingerprint",
    "statistics_result_fingerprint",
    "result_content_fingerprint",
    "dataset_snapshot_fingerprint",
    "result_schema_version",
    "plan",
}


def _catalog_common(value: OnlyResearchScientificStatisticsCatalogEntryV3) -> None:
    for name in (
        "statistics_fingerprint",
        "statistics_result_fingerprint",
        "result_content_fingerprint",
        "dataset_snapshot_fingerprint",
    ):
        _sha(getattr(value, name))
    if value.result_schema_version != 1:
        raise ValueError("Scientific V3 Statistics Result schema is unsupported")


def _catalog_dict(value: OnlyResearchScientificStatisticsCatalogEntryV3) -> dict[str, object]:
    return {
        "statistics_family": value.statistics_family.value,
        "payload_shape": value.payload_shape.value,
        "statistics_fingerprint": value.statistics_fingerprint,
        "statistics_result_fingerprint": value.statistics_result_fingerprint,
        "result_content_fingerprint": value.result_content_fingerprint,
        "dataset_snapshot_fingerprint": value.dataset_snapshot_fingerprint,
        "result_schema_version": value.result_schema_version,
        "plan": value.plan.to_dict(),
    }


def _exact_fields(payload: Mapping[str, object], expected: set[str]) -> None:
    if set(payload) != expected:
        raise ValueError("Scientific Artifact V3 fields are invalid")


def _mapping(payload: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = payload[name]
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise ValueError(f"Scientific Artifact V3 {name} must be an object")
    return value


def _mapping_array(payload: Mapping[str, object], name: str) -> tuple[Mapping[str, object], ...]:
    value = payload[name]
    if not isinstance(value, list) or any(
        not isinstance(x, Mapping) or any(not isinstance(k, str) for k in x) for x in value
    ):
        raise ValueError(f"Scientific Artifact V3 {name} must be an array of objects")
    return tuple(value)


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str) or not value:
        raise ValueError(f"Scientific Artifact V3 {name} must be a non-empty string")
    return value


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Scientific Artifact V3 {name} must be an integer")
    return value


def _sha(value: object) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ValueError("Scientific Artifact V3 identity must be a lower-case SHA256")
    return value


def _row_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Scientific Artifact V3 row_count is invalid")
    return value


__all__ = [
    name
    for name in globals()
    if name.startswith("OnlyResearch") or name.startswith("RESEARCH_") or name.startswith("only_research")
]
