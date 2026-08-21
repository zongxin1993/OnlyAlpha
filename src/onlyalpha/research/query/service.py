"""Deterministic projections over one verified portable Research Artifact."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from onlyalpha.research.artifact.errors import OnlyResearchArtifactStoreError
from onlyalpha.research.artifact.model import OnlyResearchArtifact, OnlyResearchArtifactStatisticsEntry
from onlyalpha.research.artifact.scientific_model import OnlyResearchScientificArtifact

from .errors import OnlyResearchQueryError, OnlyResearchQueryErrorCode
from .model import (
    OnlyResearchArtifactSummary,
    OnlyResearchCandidateCatalog,
    OnlyResearchCandidateDescriptor,
    OnlyResearchCandidateGraph,
    OnlyResearchMarketPoint,
    OnlyResearchNumericDescriptor,
    OnlyResearchPublishedSeriesCatalog,
    OnlyResearchPublishedSeriesDescriptor,
    OnlyResearchScientificSeriesPage,
    OnlyResearchSeriesReference,
    OnlyResearchSignalPoint,
    OnlyResearchSignalRole,
    OnlyResearchStatisticPoint,
    OnlyResearchStatisticsCatalog,
    OnlyResearchStatisticsDefinitionDescriptor,
    OnlyResearchStatisticsDescriptor,
    OnlyResearchStatisticSeriesPage,
    OnlyResearchVariablePoint,
    _calculation_scalar_type,
)
from .ports import OnlyResearchArtifactReader
from .request import OnlyResearchScientificSeriesQuery, OnlyResearchStatisticSeriesQuery, only_research_query_sha256


class OnlyResearchQueryService:
    def __init__(self, reader: OnlyResearchArtifactReader) -> None:
        self._reader = reader

    def get_artifact_summary(self, research_result_fingerprint: str) -> OnlyResearchArtifactSummary:
        artifact = self._load(research_result_fingerprint)
        if isinstance(artifact, OnlyResearchScientificArtifact):
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
                len(artifact.statistics_rows),
                manifest.created_at,
                len(manifest.plan.candidates),
                len(manifest.plan.published_series),
                len(manifest.plan.signals),
                len(artifact.market_rows),
                tuple(sorted({row.instrument_id for row in artifact.market_rows})),
            )
        statistics_manifest = artifact.manifest
        return OnlyResearchArtifactSummary(
            statistics_manifest.research_result_plan_fingerprint,
            statistics_manifest.research_result_content_fingerprint,
            statistics_manifest.research_result_fingerprint,
            statistics_manifest.dataset_snapshot_fingerprint,
            statistics_manifest.artifact_content_fingerprint,
            statistics_manifest.research_result_schema_version,
            statistics_manifest.profile,
            statistics_manifest.schema_version,
            len(statistics_manifest.statistics_results),
            statistics_manifest.statistics_table.row_count,
            statistics_manifest.created_at,
        )

    def list_statistics(self, research_result_fingerprint: str) -> OnlyResearchStatisticsCatalog:
        artifact = self._load(research_result_fingerprint)
        catalog = (
            artifact.manifest.statistics_catalog
            if isinstance(artifact, OnlyResearchScientificArtifact)
            else artifact.manifest.statistics_results
        )
        descriptors = tuple(sorted(_descriptor(item) for item in catalog))
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
        rows = artifact.statistics_rows if isinstance(artifact, OnlyResearchScientificArtifact) else artifact.rows
        selected = tuple(
            sorted(
                (
                    row
                    for row in rows
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

    def list_candidates(self, research_result_fingerprint: str) -> OnlyResearchCandidateCatalog:
        artifact = self._scientific(research_result_fingerprint)
        candidates = tuple(
            OnlyResearchCandidateDescriptor(
                item.candidate_fingerprint,
                item.candidate_calculation_id,
                item.assignment,
                tuple((name, _calculation_scalar_type(value)) for name, value in item.assignment),
                item.calculation_fingerprint,
                item.graph_fingerprint,
                item.statistics_fingerprints,
                tuple(
                    sorted(
                        cast(OnlyResearchSignalRole, signal.role)
                        for signal in artifact.manifest.plan.signals
                        if signal.candidate_fingerprint == item.candidate_fingerprint
                    )
                ),
            )
            for item in artifact.manifest.plan.candidates
        )
        return OnlyResearchCandidateCatalog(research_result_fingerprint, candidates)

    def list_published_series(self, research_result_fingerprint: str) -> OnlyResearchPublishedSeriesCatalog:
        artifact = self._scientific(research_result_fingerprint)
        graphs = {item.calculation_fingerprint: item.graph for item in artifact.graphs}
        result = []
        for item in artifact.manifest.plan.published_series:
            node = next(
                node for node in graphs[item.calculation_fingerprint].nodes if node.fingerprint == item.node_fingerprint
            )
            output = next(output for output in node.definition.outputs if output.name == item.output_name)
            result.append(
                OnlyResearchPublishedSeriesDescriptor(
                    item.candidate_fingerprint,
                    item.calculation_fingerprint,
                    item.node_fingerprint,
                    item.output_name,
                    output.data_type.value,
                )
            )
        return OnlyResearchPublishedSeriesCatalog(
            research_result_fingerprint,
            tuple(
                sorted(
                    result,
                    key=lambda item: (
                        item.candidate_fingerprint or "",
                        item.calculation_fingerprint,
                        item.node_fingerprint,
                        item.output_name,
                    ),
                )
            ),
        )

    def get_market_series(self, query: OnlyResearchScientificSeriesQuery) -> OnlyResearchScientificSeriesPage:
        artifact = self._scientific_query(query)
        if not query.instrument_id:
            raise OnlyResearchQueryError(OnlyResearchQueryErrorCode.INVALID_QUERY, "instrument_id is required")
        rows = (
            OnlyResearchMarketPoint(
                row.instrument_id,
                row.ts_event_ns,
                *(Decimal(getattr(row, name)) for name in ("open", "high", "low", "close", "volume")),
            )
            for row in artifact.market_rows
            if row.instrument_id == query.instrument_id
        )
        return _page(query, rows)

    def get_variable_series(self, query: OnlyResearchScientificSeriesQuery) -> OnlyResearchScientificSeriesPage:
        artifact = self._scientific_query(query)
        if (
            not query.instrument_id
            or not query.calculation_fingerprint
            or not query.node_fingerprint
            or not query.output_name
        ):
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.INVALID_QUERY, "exact Variable selector and instrument_id are required"
            )
        key = (query.candidate_fingerprint, query.calculation_fingerprint, query.node_fingerprint, query.output_name)
        if key not in {
            (item.candidate_fingerprint, item.calculation_fingerprint, item.node_fingerprint, item.output_name)
            for item in artifact.manifest.plan.published_series
        }:
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.SERIES_NOT_FOUND, "Published Series is not an Artifact member"
            )
        rows = (
            OnlyResearchVariablePoint(
                row.instrument_id,
                row.ts_event_ns,
                row.value_kind.value,
                row.decimal_value,
                row.integer_value,
                row.boolean_value,
                row.string_value,
            )
            for row in artifact.variable_rows
            if (row.candidate_fingerprint, row.calculation_fingerprint, row.node_fingerprint, row.output_name) == key
            and row.instrument_id == query.instrument_id
        )
        return _page(query, rows)

    def get_signal_series(self, query: OnlyResearchScientificSeriesQuery) -> OnlyResearchScientificSeriesPage:
        artifact = self._scientific_query(query)
        if not query.instrument_id or not query.candidate_fingerprint or not query.role:
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.INVALID_QUERY, "Candidate, role and instrument_id are required"
            )
        if (query.candidate_fingerprint, query.role) not in {
            (item.candidate_fingerprint, item.role) for item in artifact.manifest.plan.signals
        }:
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.SERIES_NOT_FOUND, "Signal Series is not an Artifact member"
            )
        rows = (
            OnlyResearchSignalPoint(row.instrument_id, row.ts_event_ns, row.value)
            for row in artifact.signal_rows
            if row.candidate_fingerprint == query.candidate_fingerprint
            and row.role == query.role
            and row.instrument_id == query.instrument_id
        )
        return _page(query, rows)

    def get_candidate_graph(
        self, research_result_fingerprint: str, candidate_fingerprint: str
    ) -> OnlyResearchCandidateGraph:
        artifact = self._scientific(research_result_fingerprint)
        candidate = next(
            (item for item in artifact.manifest.plan.candidates if item.candidate_fingerprint == candidate_fingerprint),
            None,
        )
        if candidate is None:
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.CANDIDATE_NOT_FOUND, "Candidate is not an Artifact member"
            )
        calculation = next(
            (
                item
                for item in artifact.manifest.plan.calculations
                if item.calculation_fingerprint == candidate.calculation_fingerprint
            ),
            None,
        )
        graph_entry = next(
            (item for item in artifact.graphs if item.calculation_fingerprint == candidate.calculation_fingerprint),
            None,
        )
        if (
            calculation is None
            or graph_entry is None
            or calculation.graph_fingerprint != candidate.graph_fingerprint
            or graph_entry.graph.fingerprint != candidate.graph_fingerprint
        ):
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.RESEARCH_ARTIFACT_CORRUPT,
                "Candidate, Calculation and exact Graph linkage mismatch",
            )
        return OnlyResearchCandidateGraph(
            research_result_fingerprint,
            candidate_fingerprint,
            candidate.calculation_fingerprint,
            candidate.graph_fingerprint,
            graph_entry.graph,
        )

    def _scientific(self, research_result_fingerprint: str) -> OnlyResearchScientificArtifact:
        artifact = self._load(research_result_fingerprint)
        if not isinstance(artifact, OnlyResearchScientificArtifact):
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.SCIENTIFIC_EVIDENCE_NOT_AVAILABLE,
                "Research Artifact V1 has no Scientific Evidence",
            )
        return artifact

    def _scientific_query(self, query: OnlyResearchScientificSeriesQuery) -> OnlyResearchScientificArtifact:
        if not isinstance(query, OnlyResearchScientificSeriesQuery):
            raise OnlyResearchQueryError(OnlyResearchQueryErrorCode.INVALID_QUERY, "scientific series query is invalid")
        return self._scientific(query.research_result_fingerprint)

    def _load(self, research_result_fingerprint: str) -> OnlyResearchArtifact | OnlyResearchScientificArtifact:
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


def _page(query: OnlyResearchScientificSeriesQuery, rows) -> OnlyResearchScientificSeriesPage:  # type: ignore[no-untyped-def]
    selected = tuple(
        row
        for row in rows
        if (query.from_ts_event_ns is None or row.ts_event_ns >= query.from_ts_event_ns)
        and (query.to_ts_event_ns is None or row.ts_event_ns < query.to_ts_event_ns)
        and (query.after_ts_event_ns is None or row.ts_event_ns > query.after_ts_event_ns)
    )
    window = selected[: query.limit + 1]
    has_more = len(window) > query.limit
    points = window[: query.limit]
    return OnlyResearchScientificSeriesPage(
        query.research_result_fingerprint, points, has_more, points[-1].ts_event_ns if has_more else None
    )


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
