"""Required physical read projections, derived only from full retained facts."""

from __future__ import annotations

from collections.abc import Mapping

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.calculation.result_v2 import OnlyResearchCalculationResultV2

from .calculation_v2_model import OnlyResearchCalculationArtifactManifestV2
from .scientific_materializer import _variable_key, _variable_rows
from .scientific_model import OnlyResearchScientificVariableRow
from .scientific_store import _MARKET, _SIGNALS, _STATISTICS, _VARIABLES

_READINESS = pa.schema(
    (
        pa.field("calculation_fingerprint", pa.string(), False),
        pa.field("node_fingerprint", pa.string(), False),
        pa.field("output_name", pa.string(), False),
        pa.field("instrument_id", pa.string(), False),
        pa.field("ts_event_ns", pa.int64(), False),
        pa.field("readiness", pa.string(), False),
        pa.field("reason", pa.string(), False),
    )
)


def _section_json(manifest: OnlyResearchCalculationArtifactManifestV2) -> dict[str, bytes]:
    payloads = {
        "graphs.json": [
            {"calculation_fingerprint": item.calculation_fingerprint, "graph": item.calculation_graph.to_dict()}
            for item in manifest.calculations
        ],
        "calculation_evidence.json": [item.to_dict() for item in manifest.selected_evidence],
        "sealed_input_evidence.json": manifest.sealed_input.to_dict(),
    }
    return {path: only_canonical_json(payload).encode("utf-8") for path, payload in payloads.items()}


def _section_schemas(manifest: OnlyResearchCalculationArtifactManifestV2) -> dict[str, tuple[pa.Schema, int]]:
    points = sum(manifest.dataset.row_count for _ in manifest.result.plan.published_series)
    return {
        "market.parquet": (_MARKET, manifest.dataset.row_count),
        "variables.parquet": (_VARIABLES, points),
        "readiness.parquet": (_READINESS, points),
        "signals.parquet": (_SIGNALS, 0),
        "statistics.parquet": (_STATISTICS, 0),
    }


def _section_tables(
    manifest: OnlyResearchCalculationArtifactManifestV2,
    dataset: pa.Table,
    calculations: Mapping[str, OnlyResearchCalculationResultV2],
) -> dict[str, pa.Table]:
    market = [
        {
            "instrument_id": row["instrument_id"],
            "ts_event_ns": row["ts_event_ns"],
            **{name: format(row[name], "f") for name in ("open", "high", "low", "close", "volume")},
        }
        for row in dataset.to_pylist()
    ]
    variables: list[OnlyResearchScientificVariableRow] = []
    readiness: list[dict[str, object]] = []
    for series in manifest.result.plan.published_series:
        calculation = calculations[series.calculation_fingerprint]
        variables.extend(_variable_rows(series, calculation))
        for partition in calculation.readiness:
            if partition.node_fingerprint == series.node_fingerprint:
                readiness.extend(
                    {
                        "calculation_fingerprint": series.calculation_fingerprint,
                        "node_fingerprint": series.node_fingerprint,
                        "instrument_id": partition.instrument_id,
                        **row,
                    }
                    for row in partition.table.to_pylist()
                    if row["output_name"] == series.output_name
                )
    readiness.sort(
        key=lambda row: tuple(
            row[name]
            for name in ("calculation_fingerprint", "node_fingerprint", "output_name", "instrument_id", "ts_event_ns")
        )
    )
    return {
        "market.parquet": pa.Table.from_pylist(market, schema=_MARKET),
        "variables.parquet": pa.Table.from_pylist(
            [item.to_dict() for item in sorted(variables, key=_variable_key)], schema=_VARIABLES
        ),
        "readiness.parquet": pa.Table.from_pylist(readiness, schema=_READINESS),
        "signals.parquet": pa.Table.from_pylist([], schema=_SIGNALS),
        "statistics.parquet": pa.Table.from_pylist([], schema=_STATISTICS),
    }
