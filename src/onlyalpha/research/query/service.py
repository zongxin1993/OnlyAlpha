"""Deterministic projections over one verified portable Research Artifact."""

from __future__ import annotations

from onlyalpha.research.artifact.errors import OnlyResearchArtifactStoreError
from onlyalpha.research.artifact.model import OnlyResearchArtifact, OnlyResearchArtifactStatisticsEntry

from .errors import OnlyResearchQueryError, OnlyResearchQueryErrorCode
from .model import (
    OnlyResearchArtifactSummary,
    OnlyResearchNumericDescriptor,
    OnlyResearchSeriesReference,
    OnlyResearchStatisticPoint,
    OnlyResearchStatisticsCatalog,
    OnlyResearchStatisticsDefinitionDescriptor,
    OnlyResearchStatisticsDescriptor,
    OnlyResearchStatisticSeriesPage,
)
from .ports import OnlyResearchArtifactReader
from .request import OnlyResearchStatisticSeriesQuery, only_research_query_sha256


class OnlyResearchQueryService:
    def __init__(self, reader: OnlyResearchArtifactReader) -> None:
        self._reader = reader

    def get_artifact_summary(self, research_result_fingerprint: str) -> OnlyResearchArtifactSummary:
        artifact = self._load(research_result_fingerprint)
        manifest = artifact.manifest
        return OnlyResearchArtifactSummary(
            manifest.research_result_plan_fingerprint,
            manifest.research_result_content_fingerprint,
            manifest.research_result_fingerprint,
            manifest.dataset_snapshot_fingerprint,
            manifest.artifact_content_fingerprint,
            manifest.research_result_schema_version,
            manifest.profile,
            manifest.schema_version,
            len(manifest.statistics_results),
            manifest.statistics_table.row_count,
            manifest.created_at,
        )

    def list_statistics(self, research_result_fingerprint: str) -> OnlyResearchStatisticsCatalog:
        artifact = self._load(research_result_fingerprint)
        descriptors = tuple(sorted(_descriptor(item) for item in artifact.manifest.statistics_results))
        return OnlyResearchStatisticsCatalog(artifact.manifest.research_result_fingerprint, descriptors)

    def get_statistic_series(self, query: OnlyResearchStatisticSeriesQuery) -> OnlyResearchStatisticSeriesPage:
        if not isinstance(query, OnlyResearchStatisticSeriesQuery):
            raise OnlyResearchQueryError(OnlyResearchQueryErrorCode.INVALID_QUERY, "series query contract is invalid")
        artifact = self._load(query.research_result_fingerprint)
        if query.statistics_fingerprint not in {
            item.statistics_fingerprint for item in artifact.manifest.statistics_results
        }:
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.STATISTICS_NOT_FOUND,
                "Statistics identity is not a member of the Research Artifact",
            )
        selected = tuple(
            sorted(
                (
                    row
                    for row in artifact.rows
                    if row.statistics_fingerprint == query.statistics_fingerprint
                    and (query.from_ts_event_ns is None or row.ts_event_ns >= query.from_ts_event_ns)
                    and (query.to_ts_event_ns is None or row.ts_event_ns < query.to_ts_event_ns)
                    and (query.after_ts_event_ns is None or row.ts_event_ns > query.after_ts_event_ns)
                ),
                key=lambda row: row.ts_event_ns,
            )
        )
        window = selected[: query.limit + 1]
        has_more = len(window) > query.limit
        points = tuple(
            OnlyResearchStatisticPoint(row.ts_event_ns, row.statistic_value, row.sample_count, row.status.value)
            for row in window[: query.limit]
        )
        return OnlyResearchStatisticSeriesPage(
            query.research_result_fingerprint,
            query.statistics_fingerprint,
            points,
            has_more,
            points[-1].ts_event_ns if has_more else None,
        )

    def _load(self, research_result_fingerprint: str) -> OnlyResearchArtifact:
        identity = only_research_query_sha256(research_result_fingerprint, "research_result_fingerprint")
        try:
            return self._reader.load_verified(identity)
        except OnlyResearchArtifactStoreError as exc:
            if exc.code == "ARTIFACT_NOT_FOUND":
                code = OnlyResearchQueryErrorCode.RESEARCH_ARTIFACT_NOT_FOUND
                detail = "Research Artifact was not found"
            else:
                code = OnlyResearchQueryErrorCode.RESEARCH_ARTIFACT_CORRUPT
                detail = "Research Artifact verification failed"
            raise OnlyResearchQueryError(code, detail) from exc


def _descriptor(entry: OnlyResearchArtifactStatisticsEntry) -> OnlyResearchStatisticsDescriptor:
    plan = entry.plan
    definition = plan.definition
    output_quantum = definition.numeric.output_quantum
    if output_quantum is None:
        raise ValueError("verified Statistics numeric definition has no output quantum")
    return OnlyResearchStatisticsDescriptor(
        entry.statistics_fingerprint,
        entry.statistics_result_fingerprint,
        entry.result_content_fingerprint,
        entry.statistics_result_schema_version,
        entry.row_count,
        OnlyResearchSeriesReference(
            plan.feature.calculation_fingerprint,
            plan.feature.node_fingerprint,
            plan.feature.output_name,
        ),
        OnlyResearchSeriesReference(
            plan.target.calculation_fingerprint,
            plan.target.node_fingerprint,
            plan.target.output_name,
        ),
        OnlyResearchStatisticsDefinitionDescriptor(
            definition.method.value,
            definition.minimum_observations,
            definition.pairing_policy.value,
            definition.universe_policy.value,
            definition.rank_tie_method.value,
            definition.weighting.value,
            OnlyResearchNumericDescriptor(
                definition.numeric.representation,
                definition.numeric.precision,
                output_quantum,
                definition.numeric.rounding,
            ),
        ),
    )
