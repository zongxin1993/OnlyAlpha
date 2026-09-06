"""Deterministic projections over one verified portable Research Artifact."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from onlyalpha.research.artifact.errors import OnlyResearchArtifactStoreError
from onlyalpha.research.artifact.model import OnlyResearchArtifact, OnlyResearchArtifactStatisticsEntry
from onlyalpha.research.artifact.scientific_model import OnlyResearchScientificArtifact
from onlyalpha.research.artifact.scientific_v3_model import (
    OnlyResearchScientificArtifactV3,
    OnlyResearchScientificFactorPairSeriesCatalogEntryV3,
    OnlyResearchScientificLegacySeriesCatalogEntryV3,
    OnlyResearchScientificStatisticsCatalogEntryV3,
    OnlyResearchScientificStatisticsShapeV3,
    OnlyResearchScientificSummaryCatalogEntryV3,
)
from onlyalpha.research.evaluation.factor_pair.reference import OnlyResearchFactorPairOperand
from onlyalpha.research.evaluation.reference import (
    OnlyResearchFeatureSeriesReference,
    OnlyResearchTargetSeriesReference,
)
from onlyalpha.research.evaluation.summary.neighborhood import OnlyResearchParameterNeighborhoodCandidateBinding
from onlyalpha.research.evaluation.summary.plan import (
    OnlyResearchCoverageSummaryPlan,
    OnlyResearchEffectSummaryPlan,
    OnlyResearchFactorPairEffectSummaryPlan,
    OnlyResearchParameterNeighborhoodSummaryPlan,
    OnlyResearchTemporalStabilityPlan,
)
from onlyalpha.research.evaluation.summary.result import (
    OnlyResearchCoverageSummary,
    OnlyResearchEffectSummary,
    OnlyResearchFactorPairEffectSummary,
    OnlyResearchParameterNeighborhoodSummary,
    OnlyResearchSummary,
    OnlyResearchTemporalSliceValue,
    OnlyResearchTemporalStabilitySummary,
)
from onlyalpha.research.evaluation.summary.scalar import OnlyResearchSummaryScalar

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
from .request import (
    OnlyResearchScientificSeriesQuery,
    OnlyResearchStatisticSeriesQuery,
    OnlyResearchTypedStatisticSeriesQuery,
    OnlyResearchTypedStatisticSummaryQuery,
    only_research_query_sha256,
)
from .typed_model import (
    OnlyResearchCoverageSummaryProjection,
    OnlyResearchEffectSummaryProjection,
    OnlyResearchFactorPairEffectSummaryProjection,
    OnlyResearchParameterNeighborhoodSummaryProjection,
    OnlyResearchTemporalSliceProjection,
    OnlyResearchTemporalSliceValueProjection,
    OnlyResearchTemporalStabilitySummaryProjection,
    OnlyResearchTypedCandidateBinding,
    OnlyResearchTypedCandidateSummaryDescriptor,
    OnlyResearchTypedFactorOperand,
    OnlyResearchTypedFactorPairSeriesDescriptor,
    OnlyResearchTypedFactorPairSummaryDescriptor,
    OnlyResearchTypedLegacySeriesDescriptor,
    OnlyResearchTypedNeighborhoodSummaryDescriptor,
    OnlyResearchTypedScalar,
    OnlyResearchTypedScalarStatus,
    OnlyResearchTypedScalarValueKind,
    OnlyResearchTypedStatisticPoint,
    OnlyResearchTypedStatisticsCatalog,
    OnlyResearchTypedStatisticsDependency,
    OnlyResearchTypedStatisticsDescriptor,
    OnlyResearchTypedStatisticSeriesPage,
    OnlyResearchTypedStatisticsFamily,
    OnlyResearchTypedStatisticSummary,
    OnlyResearchTypedSummaryKind,
)


class OnlyResearchQueryService:
    def __init__(self, reader: OnlyResearchArtifactReader) -> None:
        self._reader = reader

    def get_artifact_summary(self, research_result_fingerprint: str) -> OnlyResearchArtifactSummary:
        artifact = self._load(research_result_fingerprint)
        if isinstance(artifact, OnlyResearchScientificArtifactV3):
            manifest_v3 = artifact.manifest
            series_count = sum(
                item.payload_shape is OnlyResearchScientificStatisticsShapeV3.SERIES
                for item in artifact.statistics_catalog
            )
            return OnlyResearchArtifactSummary(
                manifest_v3.research_result_plan_fingerprint,
                manifest_v3.research_result_content_fingerprint,
                manifest_v3.research_result_fingerprint,
                manifest_v3.dataset_snapshot_fingerprint,
                manifest_v3.artifact_content_fingerprint,
                manifest_v3.research_result_schema_version,
                manifest_v3.profile,
                manifest_v3.schema_version,
                len(manifest_v3.statistics_results),
                len(artifact.statistics_series_rows),
                manifest_v3.created_at,
                len(manifest_v3.plan.candidates),
                len(manifest_v3.plan.published_series),
                len(manifest_v3.plan.signals),
                len(artifact.market_rows),
                tuple(sorted({row.instrument_id for row in artifact.market_rows})),
                series_statistics_count=series_count,
                summary_statistics_count=len(artifact.statistics_catalog) - series_count,
                statistics_series_row_count=len(artifact.statistics_series_rows),
            )
        if isinstance(artifact, OnlyResearchScientificArtifact):
            manifest_v2 = artifact.manifest
            return OnlyResearchArtifactSummary(
                manifest_v2.research_result_plan_fingerprint,
                manifest_v2.research_result_content_fingerprint,
                manifest_v2.research_result_fingerprint,
                manifest_v2.dataset_snapshot_fingerprint,
                manifest_v2.artifact_content_fingerprint,
                manifest_v2.research_result_schema_version,
                manifest_v2.profile,
                manifest_v2.schema_version,
                len(manifest_v2.statistics_results),
                len(artifact.statistics_rows),
                manifest_v2.created_at,
                len(manifest_v2.plan.candidates),
                len(manifest_v2.plan.published_series),
                len(manifest_v2.plan.signals),
                len(artifact.market_rows),
                tuple(sorted({row.instrument_id for row in artifact.market_rows})),
                series_statistics_count=len(manifest_v2.statistics_results),
                statistics_series_row_count=len(artifact.statistics_rows),
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
            series_statistics_count=len(statistics_manifest.statistics_results),
            statistics_series_row_count=statistics_manifest.statistics_table.row_count,
        )

    def list_statistics(self, research_result_fingerprint: str) -> OnlyResearchStatisticsCatalog:
        artifact = self._load(research_result_fingerprint)
        if isinstance(artifact, OnlyResearchScientificArtifactV3):
            v3_catalog = tuple(
                item
                for item in artifact.statistics_catalog
                if isinstance(item, OnlyResearchScientificLegacySeriesCatalogEntryV3)
            )
            descriptors = tuple(sorted(_descriptor(item) for item in v3_catalog))
            return OnlyResearchStatisticsCatalog(artifact.manifest.research_result_fingerprint, descriptors)
        legacy_catalog = (
            artifact.manifest.statistics_catalog
            if isinstance(artifact, OnlyResearchScientificArtifact)
            else artifact.manifest.statistics_results
        )
        descriptors = tuple(sorted(_descriptor(item) for item in legacy_catalog))
        return OnlyResearchStatisticsCatalog(artifact.manifest.research_result_fingerprint, descriptors)

    def list_typed_statistics(self, research_result_fingerprint: str) -> OnlyResearchTypedStatisticsCatalog:
        artifact = self._scientific_v3(research_result_fingerprint)
        descriptors = tuple(
            sorted(
                (_typed_descriptor(item) for item in artifact.statistics_catalog),
                key=lambda item: item.statistics_fingerprint,
            )
        )
        return OnlyResearchTypedStatisticsCatalog(artifact.manifest.research_result_fingerprint, descriptors)

    def get_statistic_series(self, query: OnlyResearchStatisticSeriesQuery) -> OnlyResearchStatisticSeriesPage:
        if not isinstance(query, OnlyResearchStatisticSeriesQuery):
            raise OnlyResearchQueryError(OnlyResearchQueryErrorCode.INVALID_QUERY, "series query contract is invalid")
        artifact = self._load(query.research_result_fingerprint)
        legacy_statistics = (
            {
                item.statistics_fingerprint
                for item in artifact.statistics_catalog
                if isinstance(item, OnlyResearchScientificLegacySeriesCatalogEntryV3)
            }
            if isinstance(artifact, OnlyResearchScientificArtifactV3)
            else {item.statistics_fingerprint for item in artifact.manifest.statistics_results}
        )
        if query.statistics_fingerprint not in legacy_statistics:
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.STATISTICS_NOT_FOUND,
                "Statistics identity is not a member of the Research Artifact",
            )
        if isinstance(artifact, OnlyResearchScientificArtifactV3):
            point_values = tuple(
                (
                    row.statistics_fingerprint,
                    OnlyResearchStatisticPoint(row.ts_event_ns, row.statistic_value, row.sample_count, row.status),
                )
                for row in artifact.statistics_series_rows
            )
        else:
            legacy_rows = (
                artifact.statistics_rows if isinstance(artifact, OnlyResearchScientificArtifact) else artifact.rows
            )
            point_values = tuple(
                (
                    row.statistics_fingerprint,
                    OnlyResearchStatisticPoint(
                        row.ts_event_ns, row.statistic_value, row.sample_count, row.status.value
                    ),
                )
                for row in legacy_rows
            )
        selected = tuple(
            sorted(
                (
                    point
                    for statistics_fingerprint, point in point_values
                    if statistics_fingerprint == query.statistics_fingerprint
                    and (query.from_ts_event_ns is None or point.ts_event_ns >= query.from_ts_event_ns)
                    and (query.to_ts_event_ns is None or point.ts_event_ns < query.to_ts_event_ns)
                    and (query.after_ts_event_ns is None or point.ts_event_ns > query.after_ts_event_ns)
                ),
                key=lambda point: point.ts_event_ns,
            )
        )
        window = selected[: query.limit + 1]
        has_more = len(window) > query.limit
        points = window[: query.limit]
        return OnlyResearchStatisticSeriesPage(
            query.research_result_fingerprint,
            query.statistics_fingerprint,
            points,
            has_more,
            points[-1].ts_event_ns if has_more else None,
        )

    def get_typed_statistic_series(
        self, query: OnlyResearchTypedStatisticSeriesQuery
    ) -> OnlyResearchTypedStatisticSeriesPage:
        if not isinstance(query, OnlyResearchTypedStatisticSeriesQuery):
            raise OnlyResearchQueryError(OnlyResearchQueryErrorCode.INVALID_QUERY, "typed series query is invalid")
        artifact = self._scientific_v3(query.research_result_fingerprint)
        entry = _typed_entry(artifact, query.statistics_fingerprint)
        if entry.payload_shape is not OnlyResearchScientificStatisticsShapeV3.SERIES:
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.STATISTICS_SHAPE_MISMATCH,
                "Statistics identity does not address a Series payload",
            )
        selected = tuple(
            row
            for row in artifact.statistics_series_rows
            if row.statistics_fingerprint == query.statistics_fingerprint
            and (query.from_ts_event_ns is None or row.ts_event_ns >= query.from_ts_event_ns)
            and (query.to_ts_event_ns is None or row.ts_event_ns < query.to_ts_event_ns)
            and (query.after_ts_event_ns is None or row.ts_event_ns > query.after_ts_event_ns)
        )
        window = selected[: query.limit + 1]
        has_more = len(window) > query.limit
        points = tuple(
            OnlyResearchTypedStatisticPoint(row.ts_event_ns, row.statistic_value, row.sample_count, row.status)
            for row in window[: query.limit]
        )
        return OnlyResearchTypedStatisticSeriesPage(
            query.research_result_fingerprint,
            query.statistics_fingerprint,
            OnlyResearchTypedStatisticsFamily(entry.statistics_family.value),
            points,
            has_more,
            points[-1].ts_event_ns if has_more else None,
        )

    def get_typed_statistic_summary(
        self, query: OnlyResearchTypedStatisticSummaryQuery
    ) -> OnlyResearchTypedStatisticSummary:
        if not isinstance(query, OnlyResearchTypedStatisticSummaryQuery):
            raise OnlyResearchQueryError(OnlyResearchQueryErrorCode.INVALID_QUERY, "typed Summary query is invalid")
        artifact = self._scientific_v3(query.research_result_fingerprint)
        entry = _typed_entry(artifact, query.statistics_fingerprint)
        if entry.payload_shape is not OnlyResearchScientificStatisticsShapeV3.SUMMARY:
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.STATISTICS_SHAPE_MISMATCH,
                "Statistics identity does not address a Summary payload",
            )
        summary_entry = next(
            item
            for item in artifact.statistics_summaries
            if item.statistics_fingerprint == query.statistics_fingerprint
        )
        if not isinstance(
            entry, OnlyResearchScientificSummaryCatalogEntryV3
        ):  # pragma: no cover - verified V3 invariant
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.RESEARCH_ARTIFACT_CORRUPT, "Summary metadata is invalid"
            )
        return _summary_projection(query.research_result_fingerprint, entry, summary_entry.summary)

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

    def _scientific(
        self, research_result_fingerprint: str
    ) -> OnlyResearchScientificArtifact | OnlyResearchScientificArtifactV3:
        artifact = self._load(research_result_fingerprint)
        if not isinstance(artifact, (OnlyResearchScientificArtifact, OnlyResearchScientificArtifactV3)):
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.SCIENTIFIC_EVIDENCE_NOT_AVAILABLE,
                "Research Artifact V1 has no Scientific Evidence",
            )
        return artifact

    def _scientific_query(
        self, query: OnlyResearchScientificSeriesQuery
    ) -> OnlyResearchScientificArtifact | OnlyResearchScientificArtifactV3:
        if not isinstance(query, OnlyResearchScientificSeriesQuery):
            raise OnlyResearchQueryError(OnlyResearchQueryErrorCode.INVALID_QUERY, "scientific series query is invalid")
        return self._scientific(query.research_result_fingerprint)

    def _scientific_v3(self, research_result_fingerprint: str) -> OnlyResearchScientificArtifactV3:
        artifact = self._load(research_result_fingerprint)
        if not isinstance(artifact, OnlyResearchScientificArtifactV3):
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.SCIENTIFIC_EVIDENCE_NOT_AVAILABLE,
                "Research Artifact has no typed rich Scientific Evidence",
            )
        return artifact

    def _load(
        self, research_result_fingerprint: str
    ) -> OnlyResearchArtifact | OnlyResearchScientificArtifact | OnlyResearchScientificArtifactV3:
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


def _descriptor(
    entry: OnlyResearchArtifactStatisticsEntry | OnlyResearchScientificLegacySeriesCatalogEntryV3,
) -> OnlyResearchStatisticsDescriptor:
    plan = entry.plan
    definition = plan.definition
    output_quantum = definition.numeric.output_quantum
    if output_quantum is None:
        raise ValueError("verified Statistics numeric definition has no output quantum")
    return OnlyResearchStatisticsDescriptor(
        entry.statistics_fingerprint,
        entry.statistics_result_fingerprint,
        entry.result_content_fingerprint,
        entry.result_schema_version
        if isinstance(entry, OnlyResearchScientificLegacySeriesCatalogEntryV3)
        else entry.statistics_result_schema_version,
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


def _series_reference(
    value: OnlyResearchFeatureSeriesReference | OnlyResearchTargetSeriesReference,
) -> OnlyResearchSeriesReference:
    return OnlyResearchSeriesReference(value.calculation_fingerprint, value.node_fingerprint, value.output_name)


def _operand(value: OnlyResearchFactorPairOperand) -> OnlyResearchTypedFactorOperand:
    return OnlyResearchTypedFactorOperand(
        value.candidate_fingerprint,
        value.series.calculation_fingerprint,
        value.series.node_fingerprint,
        value.series.output_name,
    )


def _dependency(logical: str, result: str) -> OnlyResearchTypedStatisticsDependency:
    return OnlyResearchTypedStatisticsDependency(logical, result)


def _binding(value: OnlyResearchParameterNeighborhoodCandidateBinding) -> OnlyResearchTypedCandidateBinding:
    return OnlyResearchTypedCandidateBinding(
        value.candidate_fingerprint,
        tuple(sorted(value.assignment.items())),
        _dependency(value.source_statistics_fingerprint, value.source_statistics_result_fingerprint),
    )


def _typed_descriptor(
    entry: OnlyResearchScientificStatisticsCatalogEntryV3,
) -> OnlyResearchTypedStatisticsDescriptor:
    common = (
        entry.statistics_fingerprint,
        entry.statistics_result_fingerprint,
        entry.result_content_fingerprint,
        entry.dataset_snapshot_fingerprint,
        entry.result_schema_version,
    )
    if isinstance(entry, OnlyResearchScientificLegacySeriesCatalogEntryV3):
        legacy = _descriptor(entry)
        return OnlyResearchTypedLegacySeriesDescriptor(
            *common,
            entry.row_count,
            legacy.feature,
            legacy.target,
            legacy.definition,
        )
    if isinstance(entry, OnlyResearchScientificFactorPairSeriesCatalogEntryV3):
        return OnlyResearchTypedFactorPairSeriesDescriptor(
            *common,
            entry.plan.definition.method.value,
            entry.row_count,
            _operand(entry.plan.first_operand),
            _operand(entry.plan.second_operand),
        )
    plan = entry.plan
    kind = OnlyResearchTypedSummaryKind(plan.definition.summary_kind.value)
    if isinstance(
        plan, (OnlyResearchEffectSummaryPlan, OnlyResearchCoverageSummaryPlan, OnlyResearchTemporalStabilityPlan)
    ):
        return OnlyResearchTypedCandidateSummaryDescriptor(
            *common,
            kind,
            plan.subject_candidate_fingerprint,
            _series_reference(plan.subject),
            _dependency(plan.source_statistics_fingerprint, plan.source_statistics_result_fingerprint),
        )
    if isinstance(plan, OnlyResearchFactorPairEffectSummaryPlan):
        return OnlyResearchTypedFactorPairSummaryDescriptor(
            *common,
            kind,
            _operand(plan.first_operand),
            _operand(plan.second_operand),
            _dependency(plan.source_statistics_fingerprint, plan.source_statistics_result_fingerprint),
        )
    if isinstance(plan, OnlyResearchParameterNeighborhoodSummaryPlan):
        return OnlyResearchTypedNeighborhoodSummaryDescriptor(
            *common,
            kind,
            plan.source_metric_id,
            _binding(plan.focal),
            tuple(_binding(item) for item in plan.neighbors),
        )
    raise AssertionError("verified V3 Summary Plan is unsupported")  # pragma: no cover


def _typed_entry(
    artifact: OnlyResearchScientificArtifactV3, statistics_fingerprint: str
) -> OnlyResearchScientificStatisticsCatalogEntryV3:
    entry = next(
        (item for item in artifact.statistics_catalog if item.statistics_fingerprint == statistics_fingerprint), None
    )
    if entry is None:
        raise OnlyResearchQueryError(
            OnlyResearchQueryErrorCode.STATISTICS_NOT_FOUND,
            "Statistics identity is not a member of the Research Artifact",
        )
    return entry


def _scalar(value: OnlyResearchSummaryScalar) -> OnlyResearchTypedScalar:
    return OnlyResearchTypedScalar(
        value.metric_id,
        OnlyResearchTypedScalarValueKind(value.value_kind.value),
        OnlyResearchTypedScalarStatus(value.status.value),
        value.integer_value,
        value.decimal_value,
    )


def _slice_value(value: OnlyResearchTemporalSliceValue) -> OnlyResearchTemporalSliceValueProjection:
    return OnlyResearchTemporalSliceValueProjection(
        OnlyResearchTypedScalarStatus(value.status.value), value.decimal_value
    )


def _summary_projection(
    research_result_fingerprint: str,
    entry: OnlyResearchScientificSummaryCatalogEntryV3,
    summary: OnlyResearchSummary,
) -> OnlyResearchTypedStatisticSummary:
    plan = entry.plan
    identity = entry.statistics_fingerprint
    if isinstance(plan, OnlyResearchEffectSummaryPlan) and isinstance(summary, OnlyResearchEffectSummary):
        return OnlyResearchEffectSummaryProjection(
            research_result_fingerprint,
            identity,
            plan.subject_candidate_fingerprint,
            _series_reference(plan.subject),
            _dependency(plan.source_statistics_fingerprint, plan.source_statistics_result_fingerprint),
            summary.source_method.value,
            _scalar(summary.total_count),
            _scalar(summary.valid_count),
            _scalar(summary.insufficient_observations_count),
            _scalar(summary.zero_variance_feature_count),
            _scalar(summary.zero_variance_target_count),
            _scalar(summary.mean),
            _scalar(summary.stddev_sample),
            _scalar(summary.information_ratio),
            _scalar(summary.positive_count),
            _scalar(summary.negative_count),
            _scalar(summary.zero_count),
            _scalar(summary.positive_ratio),
            _scalar(summary.negative_ratio),
            _scalar(summary.zero_ratio),
        )
    if isinstance(plan, OnlyResearchCoverageSummaryPlan) and isinstance(summary, OnlyResearchCoverageSummary):
        return OnlyResearchCoverageSummaryProjection(
            research_result_fingerprint,
            identity,
            plan.subject_candidate_fingerprint,
            _series_reference(plan.subject),
            _dependency(plan.source_statistics_fingerprint, plan.source_statistics_result_fingerprint),
            summary.source_method.value,
            _scalar(summary.total_timestamp_count),
            _scalar(summary.valid_timestamp_count),
            _scalar(summary.valid_timestamp_ratio),
            _scalar(summary.insufficient_timestamp_count),
            _scalar(summary.zero_variance_feature_count),
            _scalar(summary.zero_variance_target_count),
            _scalar(summary.pair_count_total),
            _scalar(summary.pair_count_mean),
            _scalar(summary.pair_count_min),
            _scalar(summary.pair_count_max),
        )
    if isinstance(plan, OnlyResearchTemporalStabilityPlan) and isinstance(
        summary, OnlyResearchTemporalStabilitySummary
    ):
        slices = tuple(
            OnlyResearchTemporalSliceProjection(
                item.start_ts_event_ns,
                item.end_ts_event_ns,
                item.total_timestamp_count,
                item.valid_timestamp_count,
                _slice_value(item.mean),
                _slice_value(item.stddev_sample),
                _slice_value(item.information_ratio),
                _slice_value(item.valid_timestamp_ratio),
            )
            for item in summary.slices
        )
        return OnlyResearchTemporalStabilitySummaryProjection(
            research_result_fingerprint,
            identity,
            plan.subject_candidate_fingerprint,
            _series_reference(plan.subject),
            _dependency(plan.source_statistics_fingerprint, plan.source_statistics_result_fingerprint),
            summary.source_method.value,
            slices,
            _scalar(summary.slice_count),
            _scalar(summary.valid_slice_count),
            _scalar(summary.positive_mean_slice_count),
            _scalar(summary.negative_mean_slice_count),
            _scalar(summary.zero_mean_slice_count),
            _scalar(summary.positive_mean_slice_ratio),
            _scalar(summary.negative_mean_slice_ratio),
            _scalar(summary.zero_mean_slice_ratio),
            _scalar(summary.min_slice_mean),
            _scalar(summary.max_slice_mean),
            _scalar(summary.stddev_of_slice_means),
        )
    if isinstance(plan, OnlyResearchFactorPairEffectSummaryPlan) and isinstance(
        summary, OnlyResearchFactorPairEffectSummary
    ):
        return OnlyResearchFactorPairEffectSummaryProjection(
            research_result_fingerprint,
            identity,
            _operand(plan.first_operand),
            _operand(plan.second_operand),
            _dependency(plan.source_statistics_fingerprint, plan.source_statistics_result_fingerprint),
            summary.source_method.value,
            _scalar(summary.mean),
            _scalar(summary.stddev_sample),
        )
    if isinstance(plan, OnlyResearchParameterNeighborhoodSummaryPlan) and isinstance(
        summary, OnlyResearchParameterNeighborhoodSummary
    ):
        return OnlyResearchParameterNeighborhoodSummaryProjection(
            research_result_fingerprint,
            identity,
            plan.source_metric_id,
            _binding(plan.focal),
            tuple(_binding(item) for item in plan.neighbors),
            _scalar(summary.focal_value),
            _scalar(summary.neighbor_count),
            _scalar(summary.valid_neighbor_count),
            _scalar(summary.neighbor_no_valid_observations_count),
            _scalar(summary.neighbor_mean),
            _scalar(summary.neighbor_min),
            _scalar(summary.neighbor_max),
            _scalar(summary.neighbor_stddev_sample),
            _scalar(summary.local_range),
            _scalar(summary.focal_minus_neighbor_mean),
        )
    raise OnlyResearchQueryError(
        OnlyResearchQueryErrorCode.RESEARCH_ARTIFACT_CORRUPT,
        "Summary Plan and payload types do not match",
    )
