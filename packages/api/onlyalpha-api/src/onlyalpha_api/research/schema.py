"""Versioned transport DTOs for the Research Query read model."""

from __future__ import annotations

from datetime import UTC

from pydantic import BaseModel, ConfigDict

from onlyalpha.research.query import (
    OnlyResearchArtifactSummary,
    OnlyResearchStatisticPoint,
    OnlyResearchStatisticsCatalog,
    OnlyResearchStatisticsDefinitionDescriptor,
    OnlyResearchStatisticsDescriptor,
    OnlyResearchStatisticSeriesPage,
)


class _ReadDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ResearchErrorDto(_ReadDto):
    schema_version: int = 1
    code: str
    detail: str


class ResearchArtifactSummaryDto(_ReadDto):
    schema_version: int
    research_result_plan_fingerprint: str
    research_result_content_fingerprint: str
    research_result_fingerprint: str
    dataset_snapshot_fingerprint: str
    artifact_content_fingerprint: str
    research_result_schema_version: int
    artifact_profile: str
    artifact_schema_version: int
    statistics_count: int
    row_count: int
    created_at: str

    @classmethod
    def from_model(cls, value: OnlyResearchArtifactSummary) -> ResearchArtifactSummaryDto:
        created_at = value.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return cls(
            schema_version=value.schema_version,
            research_result_plan_fingerprint=value.research_result_plan_fingerprint,
            research_result_content_fingerprint=value.research_result_content_fingerprint,
            research_result_fingerprint=value.research_result_fingerprint,
            dataset_snapshot_fingerprint=value.dataset_snapshot_fingerprint,
            artifact_content_fingerprint=value.artifact_content_fingerprint,
            research_result_schema_version=value.research_result_schema_version,
            artifact_profile=value.artifact_profile,
            artifact_schema_version=value.artifact_schema_version,
            statistics_count=value.statistics_count,
            row_count=value.row_count,
            created_at=created_at,
        )


class ResearchSeriesReferenceDto(_ReadDto):
    calculation_fingerprint: str
    node_fingerprint: str
    output_name: str


class ResearchNumericDefinitionDto(_ReadDto):
    representation: str
    precision: int
    output_quantum: str
    rounding: str


class ResearchStatisticsDefinitionDto(_ReadDto):
    method: str
    minimum_observations: int
    pairing_policy: str
    universe_policy: str
    rank_tie_method: str
    weighting: str
    numeric: ResearchNumericDefinitionDto

    @classmethod
    def from_model(cls, value: OnlyResearchStatisticsDefinitionDescriptor) -> ResearchStatisticsDefinitionDto:
        return cls(
            method=value.method,
            minimum_observations=value.minimum_observations,
            pairing_policy=value.pairing_policy,
            universe_policy=value.universe_policy,
            rank_tie_method=value.rank_tie_method,
            weighting=value.weighting,
            numeric=ResearchNumericDefinitionDto(
                representation=value.numeric.representation,
                precision=value.numeric.precision,
                output_quantum=format(value.numeric.output_quantum, "f"),
                rounding=value.numeric.rounding,
            ),
        )


class ResearchStatisticsDescriptorDto(_ReadDto):
    statistics_fingerprint: str
    statistics_result_fingerprint: str
    result_content_fingerprint: str
    statistics_result_schema_version: int
    row_count: int
    feature: ResearchSeriesReferenceDto
    target: ResearchSeriesReferenceDto
    definition: ResearchStatisticsDefinitionDto

    @classmethod
    def from_model(cls, value: OnlyResearchStatisticsDescriptor) -> ResearchStatisticsDescriptorDto:
        return cls(
            statistics_fingerprint=value.statistics_fingerprint,
            statistics_result_fingerprint=value.statistics_result_fingerprint,
            result_content_fingerprint=value.result_content_fingerprint,
            statistics_result_schema_version=value.statistics_result_schema_version,
            row_count=value.row_count,
            feature=ResearchSeriesReferenceDto(
                calculation_fingerprint=value.feature.calculation_fingerprint,
                node_fingerprint=value.feature.node_fingerprint,
                output_name=value.feature.output_name,
            ),
            target=ResearchSeriesReferenceDto(
                calculation_fingerprint=value.target.calculation_fingerprint,
                node_fingerprint=value.target.node_fingerprint,
                output_name=value.target.output_name,
            ),
            definition=ResearchStatisticsDefinitionDto.from_model(value.definition),
        )


class ResearchStatisticsCatalogDto(_ReadDto):
    schema_version: int
    research_result_fingerprint: str
    statistics: tuple[ResearchStatisticsDescriptorDto, ...]

    @classmethod
    def from_model(cls, value: OnlyResearchStatisticsCatalog) -> ResearchStatisticsCatalogDto:
        return cls(
            schema_version=value.schema_version,
            research_result_fingerprint=value.research_result_fingerprint,
            statistics=tuple(ResearchStatisticsDescriptorDto.from_model(item) for item in value.statistics),
        )


class ResearchStatisticPointDto(_ReadDto):
    ts_event_ns: int
    statistic_value: str | None
    sample_count: int
    status: str

    @classmethod
    def from_model(cls, value: OnlyResearchStatisticPoint) -> ResearchStatisticPointDto:
        return cls(
            ts_event_ns=value.ts_event_ns,
            statistic_value=None if value.statistic_value is None else format(value.statistic_value, "f"),
            sample_count=value.sample_count,
            status=value.status,
        )


class ResearchStatisticSeriesPageDto(_ReadDto):
    schema_version: int
    research_result_fingerprint: str
    statistics_fingerprint: str
    points: tuple[ResearchStatisticPointDto, ...]
    has_more: bool
    next_after_ts_event_ns: int | None

    @classmethod
    def from_model(cls, value: OnlyResearchStatisticSeriesPage) -> ResearchStatisticSeriesPageDto:
        return cls(
            schema_version=value.schema_version,
            research_result_fingerprint=value.research_result_fingerprint,
            statistics_fingerprint=value.statistics_fingerprint,
            points=tuple(ResearchStatisticPointDto.from_model(item) for item in value.points),
            has_more=value.has_more,
            next_after_ts_event_ns=value.next_after_ts_event_ns,
        )
