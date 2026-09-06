"""Mechanical projection of verified Research authorities into Scientific Artifact V3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.research.calculation.result import OnlyResearchCalculationResult
from onlyalpha.research.dataset import OnlyVerifiedResearchDataset
from onlyalpha.research.evaluation.factor_pair.result import OnlyResearchFactorPairStatisticsResult
from onlyalpha.research.evaluation.result import OnlyResearchStatisticsResult
from onlyalpha.research.evaluation.summary.result import OnlyResearchSummaryStatisticsResult
from onlyalpha.research.result.result import OnlyResearchResult

from .errors import OnlyResearchArtifactError
from .scientific_materializer import _signal_rows, _variable_key, _variable_rows
from .scientific_model import (
    OnlyResearchScientificGraph,
    OnlyResearchScientificMarketRow,
    OnlyResearchScientificSection,
    OnlyResearchScientificSignalRow,
    OnlyResearchScientificVariableRow,
)
from .scientific_v3_model import (
    OnlyResearchScientificFactorPairSeriesCatalogEntryV3,
    OnlyResearchScientificLegacySeriesCatalogEntryV3,
    OnlyResearchScientificStatisticsCatalogEntryV3,
    OnlyResearchScientificStatisticsSeriesRowV3,
    OnlyResearchScientificStatisticsSummaryV3,
    OnlyResearchScientificSummaryCatalogEntryV3,
    only_research_scientific_artifact_v3_content_fingerprint,
    only_research_scientific_v3_section_fingerprint,
)


class _ResultStore(Protocol):
    def load_verified(self, fingerprint: str) -> OnlyResearchResult: ...


class _DatasetStore(Protocol):
    def load_verified_table(self, fingerprint: str) -> OnlyVerifiedResearchDataset: ...


class _CalculationStore(Protocol):
    def load_verified(self, fingerprint: str) -> OnlyResearchCalculationResult: ...


class _StatisticsReader(Protocol):
    def load_verified(
        self, fingerprint: str
    ) -> (
        OnlyResearchStatisticsResult | OnlyResearchFactorPairStatisticsResult | OnlyResearchSummaryStatisticsResult
    ): ...


@dataclass(frozen=True, slots=True)
class OnlyResearchScientificArtifactCandidateV3:
    result: OnlyResearchResult
    market_rows: tuple[OnlyResearchScientificMarketRow, ...]
    variable_rows: tuple[OnlyResearchScientificVariableRow, ...]
    signal_rows: tuple[OnlyResearchScientificSignalRow, ...]
    graphs: tuple[OnlyResearchScientificGraph, ...]
    statistics_catalog: tuple[OnlyResearchScientificStatisticsCatalogEntryV3, ...]
    statistics_series_rows: tuple[OnlyResearchScientificStatisticsSeriesRowV3, ...]
    statistics_summaries: tuple[OnlyResearchScientificStatisticsSummaryV3, ...]
    sections: tuple[OnlyResearchScientificSection, ...]
    artifact_content_fingerprint: str


class OnlyResearchScientificArtifactMaterializerV3:
    def __init__(
        self,
        results: _ResultStore,
        datasets: _DatasetStore,
        calculations: _CalculationStore,
        statistics: _StatisticsReader,
    ) -> None:
        self._results = results
        self._datasets = datasets
        self._calculations = calculations
        self._statistics = statistics

    def materialize(self, result_plan_fingerprint: str) -> OnlyResearchScientificArtifactCandidateV3:
        try:
            result = self._results.load_verified(result_plan_fingerprint)
            manifest, plan = result.manifest, result.manifest.plan
            if manifest.schema_version != 2 or plan.schema_version != 2:
                raise ValueError("Scientific Artifact V3 requires Research Result V2")
            dataset = self._datasets.load_verified_table(manifest.dataset_snapshot_fingerprint)
            market = tuple(
                sorted(
                    OnlyResearchScientificMarketRow(
                        row["instrument_id"],
                        row["ts_event_ns"],
                        format(row["open"], "f"),
                        format(row["high"], "f"),
                        format(row["low"], "f"),
                        format(row["close"], "f"),
                        format(row["volume"], "f"),
                    )
                    for row in dataset.table.select(
                        ["instrument_id", "ts_event_ns", "open", "high", "low", "close", "volume"]
                    ).to_pylist()
                )
            )
            calculations = {
                member.calculation_fingerprint: self._calculations.load_verified(member.calculation_fingerprint)
                for member in plan.calculations
            }
            graphs = tuple(
                OnlyResearchScientificGraph(
                    member.calculation_fingerprint,
                    calculations[member.calculation_fingerprint].manifest.calculation_graph,
                )
                for member in plan.calculations
            )
            variables = tuple(
                sorted(
                    (
                        row
                        for member in plan.published_series
                        for row in _variable_rows(member, calculations[member.calculation_fingerprint])
                    ),
                    key=_variable_key,
                )
            )
            signals = tuple(
                sorted(
                    row
                    for member in plan.signals
                    for row in _signal_rows(member, calculations[member.calculation_fingerprint])
                )
            )
            catalog: list[OnlyResearchScientificStatisticsCatalogEntryV3] = []
            series: list[OnlyResearchScientificStatisticsSeriesRowV3] = []
            summaries: list[OnlyResearchScientificStatisticsSummaryV3] = []
            for reference in manifest.statistics_results:
                value = self._statistics.load_verified(reference.statistics_fingerprint)
                if value.manifest.statistics_fingerprint != reference.statistics_fingerprint:
                    raise ValueError("Scientific V3 Statistics logical identity mismatch")
                if value.manifest.statistics_result_fingerprint != reference.statistics_result_fingerprint:
                    raise ValueError("Scientific V3 Statistics Result identity mismatch")
                if isinstance(value, OnlyResearchStatisticsResult):
                    item_legacy = value.manifest
                    catalog.append(
                        OnlyResearchScientificLegacySeriesCatalogEntryV3(
                            item_legacy.statistics_fingerprint,
                            item_legacy.statistics_result_fingerprint,
                            item_legacy.result_content_fingerprint,
                            item_legacy.dataset_snapshot_fingerprint,
                            item_legacy.plan,
                            item_legacy.feature_calculation_result_fingerprint,
                            item_legacy.target_calculation_result_fingerprint,
                            item_legacy.row_count,
                            item_legacy.schema_version,
                        )
                    )
                    series.extend(
                        OnlyResearchScientificStatisticsSeriesRowV3(
                            item_legacy.statistics_fingerprint,
                            row.ts_event_ns,
                            row.statistic_value,
                            row.sample_count,
                            row.status.value,
                        )
                        for row in value.rows
                    )
                elif isinstance(value, OnlyResearchFactorPairStatisticsResult):
                    item_pair = value.manifest
                    catalog.append(
                        OnlyResearchScientificFactorPairSeriesCatalogEntryV3(
                            item_pair.statistics_fingerprint,
                            item_pair.statistics_result_fingerprint,
                            item_pair.result_content_fingerprint,
                            item_pair.dataset_snapshot_fingerprint,
                            item_pair.plan,
                            item_pair.first_calculation_result_fingerprint,
                            item_pair.second_calculation_result_fingerprint,
                            item_pair.row_count,
                            item_pair.schema_version,
                        )
                    )
                    series.extend(
                        OnlyResearchScientificStatisticsSeriesRowV3(
                            item_pair.statistics_fingerprint,
                            row.ts_event_ns,
                            row.statistic_value,
                            row.sample_count,
                            row.status.value,
                        )
                        for row in value.rows
                    )
                elif isinstance(value, OnlyResearchSummaryStatisticsResult):
                    item_summary = value.manifest
                    catalog.append(
                        OnlyResearchScientificSummaryCatalogEntryV3(
                            item_summary.statistics_fingerprint,
                            item_summary.statistics_result_fingerprint,
                            item_summary.result_content_fingerprint,
                            item_summary.dataset_snapshot_fingerprint,
                            item_summary.plan,
                            item_summary.schema_version,
                        )
                    )
                    summaries.append(
                        OnlyResearchScientificStatisticsSummaryV3(item_summary.statistics_fingerprint, value.summary)
                    )
                else:  # pragma: no cover - reader protocol closes this branch
                    raise ValueError("Scientific V3 Statistics family is unsupported")

            canonical_catalog = tuple(sorted(catalog, key=lambda x: x.statistics_fingerprint))
            canonical_series = tuple(sorted(series))
            canonical_summaries = tuple(sorted(summaries))
            semantic: dict[str, list[object]] = {
                "graphs.json": [x.to_dict() for x in graphs],
                "market.parquet": [x.to_dict() for x in market],
                "signals.parquet": [x.to_dict() for x in signals],
                "statistics_catalog.json": [x.to_dict() for x in canonical_catalog],
                "statistics_series.parquet": [x.semantic_payload() for x in canonical_series],
                "statistics_summaries.json": [x.to_dict() for x in canonical_summaries],
                "variables.parquet": [x.to_dict() for x in variables],
            }
            sections = tuple(
                OnlyResearchScientificSection(
                    path,
                    len(rows),
                    only_research_scientific_v3_section_fingerprint(path.rsplit(".", 1)[0], rows),
                    "0" * 64,
                )
                for path, rows in semantic.items()
            )
            artifact = only_research_scientific_artifact_v3_content_fingerprint(
                manifest.research_result_fingerprint, sections
            )
            return OnlyResearchScientificArtifactCandidateV3(
                result,
                market,
                variables,
                signals,
                graphs,
                canonical_catalog,
                canonical_series,
                canonical_summaries,
                sections,
                artifact,
            )
        except OnlyResearchArtifactError:
            raise
        except Exception as exc:
            raise OnlyResearchArtifactError("ARTIFACT_INVALID", str(exc)) from exc


__all__ = ["OnlyResearchScientificArtifactCandidateV3", "OnlyResearchScientificArtifactMaterializerV3"]
