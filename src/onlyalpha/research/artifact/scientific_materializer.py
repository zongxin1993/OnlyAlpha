"""Mechanical projection of exact V2 authorities into Scientific Artifact rows."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from onlyalpha.calculation import OnlyCalculationDataType
from onlyalpha.research.calculation.result import OnlyResearchCalculationResult
from onlyalpha.research.dataset import OnlyVerifiedResearchDataset
from onlyalpha.research.evaluation.result import OnlyResearchStatisticsResult
from onlyalpha.research.result.plan import OnlyResearchResultSeriesPlan, OnlyResearchResultSignalPlan
from onlyalpha.research.result.result import OnlyResearchResult

from .errors import OnlyResearchArtifactError
from .materializer import OnlyResearchArtifactMaterializer
from .model import OnlyResearchArtifactStatisticsEntry, OnlyResearchArtifactStatisticsRow
from .scientific_model import (
    OnlyResearchScientificGraph,
    OnlyResearchScientificMarketRow,
    OnlyResearchScientificSection,
    OnlyResearchScientificSignalRow,
    OnlyResearchScientificValueKind,
    OnlyResearchScientificVariableRow,
    only_research_scientific_artifact_content_fingerprint,
    only_research_scientific_section_fingerprint,
)


class _ResultStore(Protocol):
    def load_verified(self, fingerprint: str) -> OnlyResearchResult: ...


class _DatasetStore(Protocol):
    def load_verified_table(self, fingerprint: str) -> OnlyVerifiedResearchDataset: ...


class _CalculationStore(Protocol):
    def load_verified(self, fingerprint: str) -> OnlyResearchCalculationResult: ...


class _StatisticsStore(Protocol):
    def load_verified(self, fingerprint: str) -> OnlyResearchStatisticsResult: ...


@dataclass(frozen=True, slots=True)
class OnlyResearchScientificArtifactCandidate:
    result: OnlyResearchResult
    market_rows: tuple[OnlyResearchScientificMarketRow, ...]
    variable_rows: tuple[OnlyResearchScientificVariableRow, ...]
    signal_rows: tuple[OnlyResearchScientificSignalRow, ...]
    statistics_catalog: tuple[OnlyResearchArtifactStatisticsEntry, ...]
    statistics_rows: tuple[OnlyResearchArtifactStatisticsRow, ...]
    graphs: tuple[OnlyResearchScientificGraph, ...]
    sections: tuple[OnlyResearchScientificSection, ...]
    artifact_content_fingerprint: str


class OnlyResearchScientificArtifactMaterializer:
    def __init__(
        self,
        results: _ResultStore,
        datasets: _DatasetStore,
        calculations: _CalculationStore,
        statistics: _StatisticsStore,
    ) -> None:
        self._results = results
        self._datasets = datasets
        self._calculations = calculations
        self._statistics = statistics

    def materialize(self, result_plan_fingerprint: str) -> OnlyResearchScientificArtifactCandidate:
        try:
            result = self._results.load_verified(result_plan_fingerprint)
            manifest, plan = result.manifest, result.manifest.plan
            if manifest.schema_version != 2 or plan.schema_version != 2:
                raise ValueError("Scientific Artifact requires Research Result V2")
            dataset = self._datasets.load_verified_table(manifest.dataset_snapshot_fingerprint)
            market_rows = tuple(
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
            variable_rows = tuple(
                sorted(
                    (
                        row
                        for member in plan.published_series
                        for row in _variable_rows(member, calculations[member.calculation_fingerprint])
                    ),
                    key=_variable_key,
                )
            )
            signal_rows = tuple(
                sorted(
                    row
                    for member in plan.signals
                    for row in _signal_rows(member, calculations[member.calculation_fingerprint])
                )
            )
            catalog: list[OnlyResearchArtifactStatisticsEntry] = []
            statistic_rows: list[OnlyResearchArtifactStatisticsRow] = []
            for reference in manifest.statistics_results:
                value = self._statistics.load_verified(reference.statistics_fingerprint)
                OnlyResearchArtifactMaterializer._verify_statistics(reference.statistics_result_fingerprint, value)
                item = value.manifest
                catalog.append(
                    OnlyResearchArtifactStatisticsEntry(
                        item.statistics_fingerprint,
                        item.statistics_result_fingerprint,
                        item.result_content_fingerprint,
                        item.plan,
                        item.row_count,
                        item.schema_version,
                    )
                )
                statistic_rows.extend(
                    OnlyResearchArtifactStatisticsRow(
                        item.statistics_fingerprint, row.ts_event_ns, row.statistic_value, row.sample_count, row.status
                    )
                    for row in value.rows
                )
            statistics_catalog, statistics_rows = tuple(sorted(catalog)), tuple(sorted(statistic_rows))
            logical = {
                "graphs.json": (
                    len(graphs),
                    only_research_scientific_section_fingerprint("graphs", [item.to_dict() for item in graphs]),
                ),
                "market.parquet": (
                    len(market_rows),
                    only_research_scientific_section_fingerprint("market", [item.to_dict() for item in market_rows]),
                ),
                "signals.parquet": (
                    len(signal_rows),
                    only_research_scientific_section_fingerprint("signals", [item.to_dict() for item in signal_rows]),
                ),
                "statistics.parquet": (
                    len(statistics_rows),
                    only_research_scientific_section_fingerprint(
                        "statistics",
                        [
                            item.__dict__
                            if hasattr(item, "__dict__")
                            else {
                                "statistics_fingerprint": item.statistics_fingerprint,
                                "ts_event_ns": item.ts_event_ns,
                                "statistic_value": item.statistic_value,
                                "sample_count": item.sample_count,
                                "status": item.status.value,
                            }
                            for item in statistics_rows
                        ],
                    ),
                ),
                "variables.parquet": (
                    len(variable_rows),
                    only_research_scientific_section_fingerprint(
                        "variables", [item.to_dict() for item in variable_rows]
                    ),
                ),
            }
            sections = tuple(OnlyResearchScientificSection(path, *logical[path], "0" * 64) for path in sorted(logical))
            artifact = only_research_scientific_artifact_content_fingerprint(
                manifest.research_result_fingerprint, sections
            )
            return OnlyResearchScientificArtifactCandidate(
                result,
                market_rows,
                variable_rows,
                signal_rows,
                statistics_catalog,
                statistics_rows,
                graphs,
                sections,
                artifact,
            )
        except OnlyResearchArtifactError:
            raise
        except Exception as exc:
            raise OnlyResearchArtifactError("ARTIFACT_INVALID", str(exc)) from exc


def _variable_rows(
    member: OnlyResearchResultSeriesPlan, result: OnlyResearchCalculationResult
) -> tuple[OnlyResearchScientificVariableRow, ...]:
    graph = result.manifest.calculation_graph
    node = next(item for item in graph.nodes if item.fingerprint == member.node_fingerprint)
    output = next(item for item in node.definition.outputs if item.name == member.output_name)
    kind = OnlyResearchScientificValueKind(output.data_type.value)
    rows: list[OnlyResearchScientificVariableRow] = []
    for partition in result.outputs:
        if partition.node_fingerprint != member.node_fingerprint:
            continue
        for ts, value in zip(
            partition.table.column("ts_event_ns").to_pylist(),
            partition.table.column(member.output_name).to_pylist(),
            strict=True,
        ):
            decimal_value: str | None = None
            integer_value: str | None = None
            boolean_value: bool | None = None
            string_value: str | None = None
            if value is not None:
                if output.data_type is OnlyCalculationDataType.DECIMAL:
                    if not isinstance(value, Decimal):
                        raise ValueError("DECIMAL output value is invalid")
                    decimal_value = format(value, "f")
                elif output.data_type is OnlyCalculationDataType.INTEGER:
                    integer_value = str(value)
                elif output.data_type is OnlyCalculationDataType.BOOLEAN:
                    if not isinstance(value, bool):
                        raise ValueError("BOOLEAN output value is invalid")
                    boolean_value = value
                else:
                    if not isinstance(value, str):
                        raise ValueError("STRING output value is invalid")
                    string_value = value
            rows.append(
                OnlyResearchScientificVariableRow(
                    member.candidate_fingerprint,
                    member.calculation_fingerprint,
                    member.node_fingerprint,
                    member.output_name,
                    partition.instrument_id,
                    ts,
                    kind,
                    decimal_value,
                    integer_value,
                    boolean_value,
                    string_value,
                )
            )
    return tuple(rows)


def _signal_rows(
    member: OnlyResearchResultSignalPlan, result: OnlyResearchCalculationResult
) -> tuple[OnlyResearchScientificSignalRow, ...]:
    rows: list[OnlyResearchScientificSignalRow] = []
    for partition in result.outputs:
        if partition.node_fingerprint != member.node_fingerprint:
            continue
        for ts, value in zip(
            partition.table.column("ts_event_ns").to_pylist(),
            partition.table.column(member.output_name).to_pylist(),
            strict=True,
        ):
            if value is not None and not isinstance(value, bool):
                raise ValueError("Signal value is not nullable BOOLEAN")
            rows.append(
                OnlyResearchScientificSignalRow(
                    member.candidate_fingerprint, member.role, partition.instrument_id, ts, value
                )
            )
    return tuple(rows)


def _variable_key(item: OnlyResearchScientificVariableRow) -> tuple[object, ...]:
    return (
        item.candidate_fingerprint or "",
        item.calculation_fingerprint,
        item.node_fingerprint,
        item.output_name,
        item.instrument_id,
        item.ts_event_ns,
    )
