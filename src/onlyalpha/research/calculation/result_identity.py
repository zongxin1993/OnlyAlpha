"""Canonical logical identities for durable Research Calculation results."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json

RESEARCH_CALCULATION_RESULT_SCHEMA_VERSION = 1


def only_research_calculation_partition_fingerprint(
    node_fingerprint: str,
    instrument_id: str,
    table: pa.Table,
) -> str:
    """Hash one canonical logical node/instrument partition, never its Parquet bytes."""

    digest = sha256()
    header = {
        "schema_version": RESEARCH_CALCULATION_RESULT_SCHEMA_VERSION,
        "node_fingerprint": node_fingerprint,
        "instrument_id": instrument_id,
        "arrow_schema": only_research_calculation_arrow_schema_payload(table.schema),
        "row_count": table.num_rows,
    }
    _update(digest, header)
    for row in table.to_pylist():
        _update(digest, row)
    return digest.hexdigest()


def only_research_calculation_result_content_fingerprint(
    partitions: tuple[tuple[str, str, int, str, tuple[dict[str, object], ...]], ...],
) -> str:
    """Hash the canonical ordered logical partition authority."""

    ordered = tuple(sorted(partitions, key=lambda item: (item[0], item[1])))
    keys = tuple((item[0], item[1]) for item in ordered)
    if len(keys) != len(set(keys)):
        raise ValueError("RESULT_INVALID: duplicate logical partition identity")
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_CALCULATION_RESULT_SCHEMA_VERSION,
            "partitions": [
                {
                    "node_fingerprint": node,
                    "instrument_id": instrument,
                    "row_count": rows,
                    "semantic_fingerprint": semantic,
                    "arrow_schema": list(schema),
                }
                for node, instrument, rows, semantic, schema in ordered
            ],
        }
    )


def only_research_calculation_result_fingerprint(
    calculation_fingerprint: str,
    result_content_fingerprint: str,
) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_CALCULATION_RESULT_SCHEMA_VERSION,
            "calculation_fingerprint": calculation_fingerprint,
            "result_content_fingerprint": result_content_fingerprint,
        }
    )


def only_research_calculation_arrow_schema_payload(schema: pa.Schema) -> tuple[dict[str, object], ...]:
    return tuple(
        {"name": field.name, "data_type": _type_payload(field.type), "nullable": field.nullable} for field in schema
    )


def only_research_calculation_arrow_schema(payload: tuple[dict[str, object], ...]) -> pa.Schema:
    return pa.schema(
        [pa.field(str(item["name"]), _type_from_payload(item["data_type"]), bool(item["nullable"])) for item in payload]
    )


def _type_payload(data_type: pa.DataType) -> dict[str, object]:
    if pa.types.is_decimal(data_type):
        return {
            "kind": "DECIMAL",
            "bit_width": data_type.bit_width,
            "precision": data_type.precision,
            "scale": data_type.scale,
        }
    if pa.types.is_integer(data_type):
        return {"kind": "INTEGER", "bit_width": data_type.bit_width, "signed": pa.types.is_signed_integer(data_type)}
    if pa.types.is_boolean(data_type):
        return {"kind": "BOOLEAN"}
    if pa.types.is_string(data_type):
        return {"kind": "STRING"}
    raise ValueError(f"RESULT_INVALID: unsupported Arrow type {data_type}")


def _type_from_payload(value: object) -> pa.DataType:
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        raise ValueError("result Arrow data_type is invalid")
    kind = value["kind"]
    if kind == "DECIMAL" and set(value) == {"kind", "bit_width", "precision", "scale"}:
        bit_width = _plain_int(value["bit_width"])
        precision = _plain_int(value["precision"])
        scale = _plain_int(value["scale"])
        if bit_width == 128:
            return pa.decimal128(precision, scale)
        if bit_width == 256:
            return pa.decimal256(precision, scale)
    if kind == "INTEGER" and set(value) == {"kind", "bit_width", "signed"}:
        bit_width = _plain_int(value["bit_width"])
        signed = value["signed"]
        if not isinstance(signed, bool) or bit_width not in {8, 16, 32, 64}:
            raise ValueError("result Arrow integer type is invalid")
        return getattr(pa, f"{'int' if signed else 'uint'}{bit_width}")()
    if kind == "BOOLEAN" and set(value) == {"kind"}:
        return pa.bool_()
    if kind == "STRING" and set(value) == {"kind"}:
        return pa.string()
    raise ValueError("result Arrow data_type is invalid")


def _plain_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("result Arrow numeric type field must be an integer")
    return value


def _update(digest: Any, value: object) -> None:
    payload = only_canonical_json(value).encode("utf-8")
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)
