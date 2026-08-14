"""Exact immutable manifest and verified Result models."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PurePosixPath

from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition

from .execution import OnlyResearchCalculationNodeOutput
from .result_identity import (
    RESEARCH_CALCULATION_RESULT_SCHEMA_VERSION,
    only_research_calculation_arrow_schema,
    only_research_calculation_result_fingerprint,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationResultPartitionManifest:
    node_fingerprint: str
    instrument_id: str
    row_count: int
    arrow_schema: tuple[dict[str, object], ...]
    semantic_fingerprint: str
    relative_path: str
    byte_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "node_fingerprint": self.node_fingerprint,
            "instrument_id": self.instrument_id,
            "row_count": self.row_count,
            "arrow_schema": list(self.arrow_schema),
            "semantic_fingerprint": self.semantic_fingerprint,
            "relative_path": self.relative_path,
            "byte_sha256": self.byte_sha256,
        }


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationResultManifest:
    calculation_fingerprint: str
    dataset_snapshot_fingerprint: str
    calculation_graph_fingerprint: str
    calculation_graph: OnlyCalculationGraphDefinition
    result_content_fingerprint: str
    calculation_result_fingerprint: str
    partition_count: int
    total_row_count: int
    partitions: tuple[OnlyResearchCalculationResultPartitionManifest, ...]
    created_at: datetime
    schema_version: int = RESEARCH_CALCULATION_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "calculation_fingerprint": self.calculation_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "calculation_graph_fingerprint": self.calculation_graph_fingerprint,
            "calculation_graph": dict(self.calculation_graph.to_dict()),
            "result_content_fingerprint": self.result_content_fingerprint,
            "calculation_result_fingerprint": self.calculation_result_fingerprint,
            "partition_count": self.partition_count,
            "total_row_count": self.total_row_count,
            "partitions": [item.to_dict() for item in self.partitions],
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchCalculationResultManifest:
        context = "calculation result manifest"
        _exact(
            payload,
            {
                "schema_version",
                "calculation_fingerprint",
                "dataset_snapshot_fingerprint",
                "calculation_graph_fingerprint",
                "calculation_graph",
                "result_content_fingerprint",
                "calculation_result_fingerprint",
                "partition_count",
                "total_row_count",
                "partitions",
                "created_at",
            },
            context,
        )
        version = _int(payload, "schema_version", context)
        if version != RESEARCH_CALCULATION_RESULT_SCHEMA_VERSION:
            raise ValueError("RESULT_SCHEMA_UNSUPPORTED")
        graph_payload = _mapping(payload["calculation_graph"], "calculation graph")
        graph = OnlyCalculationGraphDefinition.from_dict(graph_payload)
        graph_fingerprint = _sha(payload, "calculation_graph_fingerprint", context)
        if graph.fingerprint != graph_fingerprint:
            raise ValueError("RESULT_CORRUPT: Calculation Graph fingerprint")
        raw_partitions = payload["partitions"]
        if not isinstance(raw_partitions, list):
            raise ValueError("calculation result partitions must be an array")
        partitions = tuple(_partition(item) for item in raw_partitions)
        keys = tuple((item.node_fingerprint, item.instrument_id) for item in partitions)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("RESULT_CORRUPT: partition identity order or uniqueness")
        paths = tuple(item.relative_path for item in partitions)
        if len(paths) != len(set(paths)):
            raise ValueError("RESULT_CORRUPT: duplicate partition path")
        partition_count = _int(payload, "partition_count", context)
        total_row_count = _int(payload, "total_row_count", context)
        if partition_count < 0 or total_row_count < 0:
            raise ValueError("RESULT_CORRUPT: negative count")
        if partition_count != len(partitions) or total_row_count != sum(item.row_count for item in partitions):
            raise ValueError("RESULT_CORRUPT: aggregate count")
        calculation_fingerprint = _sha(payload, "calculation_fingerprint", context)
        content_fingerprint = _sha(payload, "result_content_fingerprint", context)
        result_fingerprint = _sha(payload, "calculation_result_fingerprint", context)
        if (
            only_research_calculation_result_fingerprint(calculation_fingerprint, content_fingerprint)
            != result_fingerprint
        ):
            raise ValueError("RESULT_CORRUPT: Calculation Result fingerprint")
        return cls(
            calculation_fingerprint,
            _sha(payload, "dataset_snapshot_fingerprint", context),
            graph_fingerprint,
            graph,
            content_fingerprint,
            result_fingerprint,
            partition_count,
            total_row_count,
            partitions,
            _utc_datetime(payload, "created_at", context),
            version,
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationResult:
    manifest: OnlyResearchCalculationResultManifest
    outputs: tuple[OnlyResearchCalculationNodeOutput, ...]


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationResultVerification:
    valid: bool
    calculation_fingerprint: str
    calculation_result_fingerprint: str
    partition_count: int
    total_row_count: int


def _partition(value: object) -> OnlyResearchCalculationResultPartitionManifest:
    payload = _mapping(value, "result partition")
    _exact(
        payload,
        {
            "node_fingerprint",
            "instrument_id",
            "row_count",
            "arrow_schema",
            "semantic_fingerprint",
            "relative_path",
            "byte_sha256",
        },
        "result partition",
    )
    relative = _str(payload, "relative_path", "result partition")
    relative_path = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or relative_path.is_absolute()
        or ".." in relative_path.parts
        or relative_path.as_posix() != relative
    ):
        raise ValueError("result partition relative_path is invalid")
    raw_schema = payload["arrow_schema"]
    if not isinstance(raw_schema, list):
        raise ValueError("result partition arrow_schema must be an array")
    schema = tuple(_schema_field(item) for item in raw_schema)
    only_research_calculation_arrow_schema(schema)
    row_count = _int(payload, "row_count", "result partition")
    if row_count < 0:
        raise ValueError("result partition row_count must be non-negative")
    return OnlyResearchCalculationResultPartitionManifest(
        _sha(payload, "node_fingerprint", "result partition"),
        _str(payload, "instrument_id", "result partition"),
        row_count,
        schema,
        _sha(payload, "semantic_fingerprint", "result partition"),
        relative,
        _sha(payload, "byte_sha256", "result partition"),
    )


def _schema_field(value: object) -> dict[str, object]:
    payload = _mapping(value, "result Arrow field")
    _exact(payload, {"name", "data_type", "nullable"}, "result Arrow field")
    name = _str(payload, "name", "result Arrow field")
    nullable = payload["nullable"]
    if not isinstance(nullable, bool):
        raise ValueError("result Arrow field nullable must be a boolean")
    data_type = payload["data_type"]
    if not isinstance(data_type, dict) or any(not isinstance(key, str) for key in data_type):
        raise ValueError("result Arrow field data_type must be an object")
    return {"name": name, "data_type": dict(data_type), "nullable": nullable}


def _exact(value: Mapping[str, object], expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{context} fields are invalid; missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}"
        )


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return value


def _str(value: Mapping[str, object], name: str, context: str) -> str:
    item = value[name]
    if not isinstance(item, str):
        raise ValueError(f"{context} {name} must be a string")
    return item


def _sha(value: Mapping[str, object], name: str, context: str) -> str:
    item = _str(value, name, context)
    if _SHA256.fullmatch(item) is None:
        raise ValueError(f"{context} {name} must be a lower-case SHA256")
    return item


def _int(value: Mapping[str, object], name: str, context: str) -> int:
    item = value[name]
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"{context} {name} must be an integer")
    return item


def _utc_datetime(value: Mapping[str, object], name: str, context: str) -> datetime:
    raw = _str(value, name, context)
    try:
        result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} {name} must be an ISO datetime") from exc
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError(f"{context} {name} must be timezone-aware UTC")
    return result
