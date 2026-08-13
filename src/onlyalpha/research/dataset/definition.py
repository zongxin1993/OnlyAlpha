"""Resolved semantic definition for Historical Closed Bar Dataset v1."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarSpecification

from .strict import (
    require_bool,
    require_exact_fields,
    require_int,
    require_mapping,
    require_optional_str,
    require_str,
    require_utc_datetime,
)


class OnlyResearchDatasetType(StrEnum):
    HISTORICAL_BAR = "HISTORICAL_BAR"


class OnlyResearchDatasetQualityPolicy(StrEnum):
    STRICT = "STRICT"


@dataclass(frozen=True, slots=True)
class OnlyResearchDatasetDefinition:
    instruments: tuple[OnlyInstrumentId, ...]
    bar_specification: OnlyBarSpecification
    aggregation_source: OnlyAggregationSource
    time_range: OnlyTimeRange
    adjustment_type: OnlyAdjustmentType = OnlyAdjustmentType.RAW
    adjustment_reference: str | None = None
    schema_version: int = 1
    dataset_type: OnlyResearchDatasetType = OnlyResearchDatasetType.HISTORICAL_BAR
    quality_policy: OnlyResearchDatasetQualityPolicy = OnlyResearchDatasetQualityPolicy.STRICT
    closed_only: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.dataset_type is not OnlyResearchDatasetType.HISTORICAL_BAR:
            raise ValueError("DATASET_SCHEMA_UNSUPPORTED")
        if self.quality_policy is not OnlyResearchDatasetQualityPolicy.STRICT or not self.closed_only:
            raise ValueError("DATASET_DEFINITION_INVALID: v1 requires STRICT closed Bars")
        canonical = tuple(sorted(self.instruments, key=str))
        if not canonical or len(canonical) != len(set(canonical)):
            raise ValueError("DATASET_DEFINITION_INVALID: instruments must be non-empty and unique")
        object.__setattr__(self, "instruments", canonical)

    def semantic_payload(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "schema_version": self.schema_version,
                "dataset_type": self.dataset_type.value,
                "instruments": [str(item) for item in self.instruments],
                "bar_specification": {
                    "step": self.bar_specification.step,
                    "aggregation": self.bar_specification.aggregation.value,
                    "price_type": self.bar_specification.price_type.value,
                },
                "aggregation_source": self.aggregation_source.value,
                "time_range": {
                    "start": self.time_range.start.isoformat(),
                    "end": self.time_range.end.isoformat(),
                },
                "adjustment_type": self.adjustment_type.value,
                "adjustment_reference": self.adjustment_reference,
                "quality_policy": self.quality_policy.value,
                "closed_only": self.closed_only,
            }
        )

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.semantic_payload())

    def to_dict(self) -> dict[str, object]:
        return dict(self.semantic_payload())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchDatasetDefinition:
        context = "dataset definition"
        require_exact_fields(
            payload,
            {
                "schema_version",
                "dataset_type",
                "instruments",
                "bar_specification",
                "aggregation_source",
                "time_range",
                "adjustment_type",
                "adjustment_reference",
                "quality_policy",
                "closed_only",
            },
            context,
        )
        instruments = payload["instruments"]
        if not isinstance(instruments, list) or any(not isinstance(item, str) for item in instruments):
            raise ValueError("dataset definition instruments must be an array of strings")
        bar = require_mapping(payload["bar_specification"], "bar specification")
        require_exact_fields(bar, {"step", "aggregation", "price_type"}, "bar specification")
        time_range = require_mapping(payload["time_range"], "time range")
        require_exact_fields(time_range, {"start", "end"}, "time range")
        schema_version = require_int(payload, "schema_version", context)
        return cls(
            tuple(OnlyInstrumentId.parse(item) for item in instruments),
            OnlyBarSpecification(
                require_int(bar, "step", "bar specification"),
                OnlyBarAggregation(require_str(bar, "aggregation", "bar specification")),
                OnlyPriceType(require_str(bar, "price_type", "bar specification")),
            ),
            OnlyAggregationSource(require_str(payload, "aggregation_source", context)),
            OnlyTimeRange(
                require_utc_datetime(time_range, "start", "time range"),
                require_utc_datetime(time_range, "end", "time range"),
            ),
            OnlyAdjustmentType(require_str(payload, "adjustment_type", context)),
            require_optional_str(payload, "adjustment_reference", context),
            schema_version,
            OnlyResearchDatasetType(require_str(payload, "dataset_type", context)),
            OnlyResearchDatasetQualityPolicy(require_str(payload, "quality_policy", context)),
            require_bool(payload, "closed_only", context),
        )
