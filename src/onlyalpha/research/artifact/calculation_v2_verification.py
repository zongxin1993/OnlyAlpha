"""Pure full-content checks for retained Dataset and Calculation V2 facts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.domain.market import OnlyBar
from onlyalpha.research.calculation.execution import (
    OnlyResearchCalculationExecutor,
    OnlyResearchCalculationNodeOutput,
    OnlyResearchCalculationNodeReadiness,
)
from onlyalpha.research.calculation.result_store import _canonical_outputs, _expected_axes, _tables_equal
from onlyalpha.research.calculation.result_v2 import OnlyResearchCalculationResultV2
from onlyalpha.research.calculation.result_v2_identity import _descriptor
from onlyalpha.research.calculation.result_v2_store import _canonical_readiness
from onlyalpha.research.dataset.codec import only_bars_to_table, only_table_to_bars
from onlyalpha.research.dataset.identity import only_canonical_bars, only_content_fingerprint
from onlyalpha.research.dataset.validation import only_validate_dataset_bars
from onlyalpha.research.result.readiness_verification import only_verify_readiness_composition

from .calculation_v2_model import OnlyResearchCalculationArtifactManifestV2
from .scientific_model import OnlyResearchScientificMarketRow


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationArtifactV2:
    manifest: OnlyResearchCalculationArtifactManifestV2
    dataset_table: pa.Table
    calculations: Mapping[str, OnlyResearchCalculationResultV2]

    @property
    def market_rows(self) -> tuple[OnlyResearchScientificMarketRow, ...]:
        """Mechanical OHLCV projection of the fully verified retained Dataset."""
        return tuple(
            sorted(
                OnlyResearchScientificMarketRow(
                    row["instrument_id"],
                    row["ts_event_ns"],
                    *(format(row[name], "f") for name in ("open", "high", "low", "close", "volume")),
                )
                for row in self.dataset_table.to_pylist()
            )
        )


def only_verify_calculation_artifact_tables_v2(
    manifest: OnlyResearchCalculationArtifactManifestV2,
    tables: Mapping[str, pa.Table],
) -> OnlyResearchCalculationArtifactV2:
    if set(tables) != set(manifest.partition_descriptors):
        raise ValueError("retained partition table coverage differs")
    dataset_tables = []
    bars: list[OnlyBar] = []
    for dataset_partition in manifest.dataset.partitions:
        table = tables[f"dataset/{dataset_partition.relative_path}"]
        if (
            table.schema != manifest.dataset.dataset_schema.arrow_schema
            or table.num_rows != dataset_partition.row_count
        ):
            raise ValueError("retained Dataset Arrow schema/count differs")
        restored = only_table_to_bars(table)
        if not table.equals(only_bars_to_table(restored), check_metadata=True):
            raise ValueError("retained Dataset table differs from canonical lossless Bar representation")
        if (
            restored != only_canonical_bars(restored)
            or only_content_fingerprint(restored) != dataset_partition.semantic_fingerprint
        ):
            raise ValueError("retained Dataset partition logical content differs")
        bars.extend(restored)
        dataset_tables.append(table)
    if (
        len(bars) != manifest.dataset.row_count
        or only_content_fingerprint(tuple(bars)) != manifest.dataset.content_fingerprint
    ):
        raise ValueError("retained complete Dataset content differs")
    only_validate_dataset_bars(manifest.dataset.definition, tuple(bars))
    dataset = (
        pa.concat_tables(dataset_tables)
        if dataset_tables
        else pa.Table.from_pylist([], schema=manifest.dataset.dataset_schema.arrow_schema)
    )
    axes = _expected_axes(dataset)
    calculations = {}
    for calculation in manifest.calculations:
        graph = calculation.calculation_graph
        if len(graph.nodes) != 1:
            raise ValueError("Calculation Artifact V2 requires the admitted one-node shape")
        OnlyResearchCalculationExecutor._resolve_instrument_inputs(
            graph.nodes[0].definition, dataset, manifest.dataset.dataset_schema, {}, ""
        )
        outputs, readiness = [], []
        for family, partitions in (
            ("values", calculation.value_partitions),
            ("readiness", calculation.readiness_partitions),
        ):
            for partition in partitions:
                table = tables[f"calculations/{calculation.calculation_fingerprint}/{partition.relative_path}"]
                expected = (
                    partition.node_fingerprint,
                    partition.instrument_id,
                    partition.row_count,
                    partition.semantic_fingerprint,
                    partition.arrow_schema,
                )
                if (
                    _descriptor(
                        partition.node_fingerprint, partition.instrument_id, table, readiness=family == "readiness"
                    )
                    != expected
                ):
                    raise ValueError("retained Calculation partition content/schema/count differs")
                if family == "values":
                    outputs.append(
                        OnlyResearchCalculationNodeOutput(partition.node_fingerprint, partition.instrument_id, table)
                    )
                else:
                    readiness.append(
                        OnlyResearchCalculationNodeReadiness(partition.node_fingerprint, partition.instrument_id, table)
                    )
        canonical_outputs = _canonical_outputs(tuple(outputs), graph, axes)
        if any(
            not _tables_equal(raw.table, canonical.table)
            for raw, canonical in zip(outputs, canonical_outputs, strict=True)
        ):
            raise ValueError("retained Calculation values are noncanonical")
        canonical_readiness = _canonical_readiness(tuple(readiness), tuple(outputs), graph, axes)
        calculations[calculation.calculation_fingerprint] = OnlyResearchCalculationResultV2(
            calculation, canonical_outputs, canonical_readiness
        )
    only_verify_readiness_composition(manifest.result.plan, calculations)
    return OnlyResearchCalculationArtifactV2(manifest, dataset, MappingProxyType(calculations))
