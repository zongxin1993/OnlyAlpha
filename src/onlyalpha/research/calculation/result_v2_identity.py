"""Version-separated logical identities; physical encoding is never identity."""

from __future__ import annotations

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.canonical import only_canonical_fingerprint

from .result_identity import (
    only_research_calculation_arrow_schema_payload,
    only_research_calculation_partition_fingerprint,
)

RESEARCH_CALCULATION_RESULT_V2_SCHEMA_VERSION = 2

_Descriptor = tuple[str, str, int, str, tuple[dict[str, object], ...]]


def only_research_calculation_readiness_partition_fingerprint(
    node_fingerprint: str, instrument_id: str, table: pa.Table
) -> str:
    return only_canonical_fingerprint(
        {
            "domain": "onlyalpha.research.calculation.readiness-partition",
            "schema_version": 2,
            "readiness_contract_version": 1,
            "node_fingerprint": node_fingerprint,
            "instrument_id": instrument_id,
            "arrow_schema": only_research_calculation_arrow_schema_payload(table.schema),
            "row_count": table.num_rows,
            "rows": table.to_pylist(),
        }
    )


def _descriptors(partitions: tuple[_Descriptor, ...]) -> list[dict[str, object]]:
    ordered = sorted(partitions, key=lambda item: (item[0], item[1]))
    keys = [(item[0], item[1]) for item in ordered]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate logical partition identity")
    return [
        {
            "node_fingerprint": node,
            "instrument_id": instrument,
            "row_count": rows,
            "semantic_fingerprint": semantic,
            "arrow_schema": list(schema),
        }
        for node, instrument, rows, semantic, schema in ordered
    ]


def only_research_calculation_value_projection_fingerprint(partitions: tuple[_Descriptor, ...]) -> str:
    # The leaves are the unchanged canonical V1 value-partition hashes, not V1 Result IDs.
    return only_canonical_fingerprint(
        {
            "domain": "onlyalpha.research.calculation.value-projection",
            "schema_version": 2,
            "partitions": _descriptors(partitions),
        }
    )


def only_research_calculation_result_content_fingerprint_v2(
    values: tuple[_Descriptor, ...], readiness: tuple[_Descriptor, ...]
) -> str:
    return only_canonical_fingerprint(
        {
            "domain": "onlyalpha.research.calculation.result-content",
            "schema_version": 2,
            "readiness_contract_version": 1,
            "value_partitions": _descriptors(values),
            "readiness_partitions": _descriptors(readiness),
        }
    )


def only_research_calculation_result_fingerprint_v2(calculation_fingerprint: str, content_fingerprint: str) -> str:
    return only_canonical_fingerprint(
        {
            "domain": "onlyalpha.research.calculation.result",
            "schema_version": 2,
            "calculation_fingerprint": calculation_fingerprint,
            "result_content_fingerprint": content_fingerprint,
        }
    )


def _descriptor(node: str, instrument: str, table: pa.Table, *, readiness: bool = False) -> _Descriptor:
    fingerprint = (
        only_research_calculation_readiness_partition_fingerprint
        if readiness
        else only_research_calculation_partition_fingerprint
    )(node, instrument, table)
    return node, instrument, table.num_rows, fingerprint, only_research_calculation_arrow_schema_payload(table.schema)
