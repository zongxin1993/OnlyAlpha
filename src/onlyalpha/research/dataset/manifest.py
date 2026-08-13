"""Immutable Dataset Snapshot manifest and exact persisted reader."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from .definition import OnlyResearchDatasetDefinition
from .identity import only_snapshot_fingerprint
from .schema import RESEARCH_BAR_DATASET_SCHEMA_V1, OnlyResearchBarDatasetSchema
from .strict import (
    require_exact_fields,
    require_int,
    require_list,
    require_mapping,
    require_sha256,
    require_str,
    require_utc_datetime,
)


@dataclass(frozen=True, slots=True)
class OnlyResearchDatasetProvenance:
    instrument_id: str
    source_id: str
    plugin_id: str
    plugin_version: str
    data_version: str | None
    cache_content_fingerprint: str | None
    resolved_ranges: tuple[tuple[str, str], ...]
    observed_ranges: tuple[tuple[str, str], ...]
    source_metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class OnlyResearchDatasetPartitionManifest:
    partition_id: str
    row_count: int
    semantic_fingerprint: str
    relative_path: str
    byte_sha256: str


@dataclass(frozen=True, slots=True)
class OnlyResearchDatasetSnapshot:
    definition: OnlyResearchDatasetDefinition
    dataset_schema: OnlyResearchBarDatasetSchema
    content_fingerprint: str
    row_count: int
    snapshot_fingerprint: str
    partitions: tuple[OnlyResearchDatasetPartitionManifest, ...]
    provenance: tuple[OnlyResearchDatasetProvenance, ...]
    created_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "snapshot_fingerprint": self.snapshot_fingerprint,
            "definition": self.definition.to_dict(),
            "definition_fingerprint": self.definition.fingerprint,
            "dataset_schema": dict(self.dataset_schema.semantic_payload()),
            "dataset_schema_fingerprint": self.dataset_schema.fingerprint,
            "content_fingerprint": self.content_fingerprint,
            "row_count": self.row_count,
            "partitions": [
                {
                    "partition_id": item.partition_id,
                    "row_count": item.row_count,
                    "semantic_fingerprint": item.semantic_fingerprint,
                    "relative_path": item.relative_path,
                    "byte_sha256": item.byte_sha256,
                }
                for item in self.partitions
            ],
            "provenance": [
                {
                    "instrument_id": item.instrument_id,
                    "source_id": item.source_id,
                    "plugin_id": item.plugin_id,
                    "plugin_version": item.plugin_version,
                    "data_version": item.data_version,
                    "cache_content_fingerprint": item.cache_content_fingerprint,
                    "resolved_ranges": [list(value) for value in item.resolved_ranges],
                    "observed_ranges": [list(value) for value in item.observed_ranges],
                    "source_metadata": dict(item.source_metadata),
                }
                for item in self.provenance
            ],
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchDatasetSnapshot:
        context = "dataset manifest"
        require_exact_fields(
            payload,
            {
                "schema_version",
                "snapshot_fingerprint",
                "definition",
                "definition_fingerprint",
                "dataset_schema",
                "dataset_schema_fingerprint",
                "content_fingerprint",
                "row_count",
                "partitions",
                "provenance",
                "created_at",
            },
            context,
        )
        if require_int(payload, "schema_version", context) != 1:
            raise ValueError("DATASET_SCHEMA_UNSUPPORTED")
        definition = OnlyResearchDatasetDefinition.from_dict(require_mapping(payload["definition"], "definition"))
        if require_sha256(payload, "definition_fingerprint", context) != definition.fingerprint:
            raise ValueError("DATASET_SNAPSHOT_CORRUPT: definition fingerprint")
        schema_payload = require_mapping(payload["dataset_schema"], "dataset schema")
        if schema_payload != RESEARCH_BAR_DATASET_SCHEMA_V1.semantic_payload():
            raise ValueError("DATASET_SCHEMA_UNSUPPORTED")
        schema = RESEARCH_BAR_DATASET_SCHEMA_V1
        if require_sha256(payload, "dataset_schema_fingerprint", context) != schema.fingerprint:
            raise ValueError("DATASET_SNAPSHOT_CORRUPT: schema fingerprint")
        partitions = tuple(_partition(item) for item in require_list(payload["partitions"], "partitions"))
        provenance = tuple(_provenance(item) for item in require_list(payload["provenance"], "provenance"))
        result = cls(
            definition,
            schema,
            require_sha256(payload, "content_fingerprint", context),
            require_int(payload, "row_count", context),
            require_sha256(payload, "snapshot_fingerprint", context),
            partitions,
            provenance,
            require_utc_datetime(payload, "created_at", context),
        )
        if result.row_count < 0:
            raise ValueError("DATASET_SNAPSHOT_CORRUPT: negative row count")
        if (
            only_snapshot_fingerprint(
                result.definition, result.dataset_schema, result.content_fingerprint, result.row_count
            )
            != result.snapshot_fingerprint
        ):
            raise ValueError("DATASET_SNAPSHOT_CORRUPT: snapshot fingerprint")
        return result


def _partition(value: object) -> OnlyResearchDatasetPartitionManifest:
    payload = require_mapping(value, "partition")
    require_exact_fields(
        payload, {"partition_id", "row_count", "semantic_fingerprint", "relative_path", "byte_sha256"}, "partition"
    )
    relative = require_str(payload, "relative_path", "partition")
    if relative.startswith("/") or ".." in relative.split("/"):
        raise ValueError("partition relative_path is invalid")
    result = OnlyResearchDatasetPartitionManifest(
        require_str(payload, "partition_id", "partition"),
        require_int(payload, "row_count", "partition"),
        require_sha256(payload, "semantic_fingerprint", "partition"),
        relative,
        require_sha256(payload, "byte_sha256", "partition"),
    )
    if result.row_count < 0:
        raise ValueError("partition row_count must be non-negative")
    return result


def _provenance(value: object) -> OnlyResearchDatasetProvenance:
    payload = require_mapping(value, "provenance")
    expected = {
        "instrument_id",
        "source_id",
        "plugin_id",
        "plugin_version",
        "data_version",
        "cache_content_fingerprint",
        "resolved_ranges",
        "observed_ranges",
        "source_metadata",
    }
    require_exact_fields(payload, expected, "provenance")
    data_version = payload["data_version"]
    cache_fp = payload["cache_content_fingerprint"]
    if data_version is not None and not isinstance(data_version, str):
        raise ValueError("provenance data_version must be a string or null")
    if cache_fp is not None and (not isinstance(cache_fp, str) or len(cache_fp) != 64):
        raise ValueError("provenance cache fingerprint must be SHA256 or null")
    return OnlyResearchDatasetProvenance(
        require_str(payload, "instrument_id", "provenance"),
        require_str(payload, "source_id", "provenance"),
        require_str(payload, "plugin_id", "provenance"),
        require_str(payload, "plugin_version", "provenance"),
        data_version,
        cache_fp,
        _ranges(payload["resolved_ranges"], "resolved_ranges"),
        _ranges(payload["observed_ranges"], "observed_ranges"),
        require_mapping(payload["source_metadata"], "source metadata"),
    )


def _ranges(value: object, context: str) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for item in require_list(value, context):
        if not isinstance(item, list) or len(item) != 2 or any(not isinstance(part, str) for part in item):
            raise ValueError(f"{context} must contain [start, end] string pairs")
        result.append((item[0], item[1]))
    return tuple(result)
