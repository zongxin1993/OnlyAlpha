"""Atomic immutable self-contained Scientific Research Artifact V2 store."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.evaluation.result import OnlyResearchStatisticStatus

from .errors import OnlyResearchArtifactStoreError
from .model import OnlyResearchArtifactDisposition, OnlyResearchArtifactOutcome, OnlyResearchArtifactStatisticsRow
from .scientific_materializer import OnlyResearchScientificArtifactCandidate
from .scientific_model import (
    RESEARCH_SCIENTIFIC_ARTIFACT_PROFILE,
    OnlyResearchScientificArtifact,
    OnlyResearchScientificArtifactManifest,
    OnlyResearchScientificGraph,
    OnlyResearchScientificMarketRow,
    OnlyResearchScientificSection,
    OnlyResearchScientificSignalRow,
    OnlyResearchScientificValueKind,
    OnlyResearchScientificVariableRow,
    only_research_scientific_artifact_content_fingerprint,
    only_research_scientific_section_fingerprint,
)
from .store import _verify_groups

_MARKET = pa.schema(
    (
        pa.field("instrument_id", pa.string(), False),
        pa.field("ts_event_ns", pa.int64(), False),
        *(pa.field(name, pa.string(), False) for name in ("open", "high", "low", "close", "volume")),
    )
)
_VARIABLES = pa.schema(
    (
        pa.field("candidate_fingerprint", pa.string(), True),
        pa.field("calculation_fingerprint", pa.string(), False),
        pa.field("node_fingerprint", pa.string(), False),
        pa.field("output_name", pa.string(), False),
        pa.field("instrument_id", pa.string(), False),
        pa.field("ts_event_ns", pa.int64(), False),
        pa.field("value_kind", pa.string(), False),
        pa.field("decimal_value", pa.string(), True),
        pa.field("integer_value", pa.string(), True),
        pa.field("boolean_value", pa.bool_(), True),
        pa.field("string_value", pa.string(), True),
    )
)
_SIGNALS = pa.schema(
    (
        pa.field("candidate_fingerprint", pa.string(), False),
        pa.field("role", pa.string(), False),
        pa.field("instrument_id", pa.string(), False),
        pa.field("ts_event_ns", pa.int64(), False),
        pa.field("value", pa.bool_(), True),
    )
)
_STATISTICS = pa.schema(
    (
        pa.field("statistics_fingerprint", pa.string(), False),
        pa.field("ts_event_ns", pa.int64(), False),
        pa.field("statistic_value", pa.decimal128(38, 12), True),
        pa.field("sample_count", pa.int64(), False),
        pa.field("status", pa.string(), False),
    )
)


class OnlyParquetResearchScientificArtifactStore:
    def __init__(
        self,
        root: Path,
        *,
        compression: str = "zstd",
        row_group_size: int | None = None,
        audit_time: Callable[[], datetime] | None = None,
    ) -> None:
        self._root, self._compression, self._row_group_size, self._audit_time = (
            root,
            compression,
            row_group_size,
            audit_time,
        )

    def exists(self, fingerprint: str) -> bool:
        return self._target(fingerprint).exists()

    def commit(self, candidate: OnlyResearchScientificArtifactCandidate) -> OnlyResearchArtifactOutcome:
        if not isinstance(candidate, OnlyResearchScientificArtifactCandidate):
            raise OnlyResearchArtifactStoreError("ARTIFACT_INVALID", "Scientific candidate is invalid")
        target = self._target(candidate.result.manifest.research_result_fingerprint)
        if target.exists():
            existing = self.load_verified(candidate.result.manifest.research_result_fingerprint)
            if existing.manifest.artifact_content_fingerprint != candidate.artifact_content_fingerprint:
                raise OnlyResearchArtifactStoreError("DETERMINISTIC_ARTIFACT_CONFLICT", target.name)
            return OnlyResearchArtifactOutcome(
                OnlyResearchArtifactDisposition.REUSED, target.name, candidate.artifact_content_fingerprint
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        stage.mkdir()
        try:
            tables = _candidate_tables(candidate)
            sections = []
            for path in ("market.parquet", "signals.parquet", "statistics.parquet", "variables.parquet"):
                pq.write_table(
                    tables[path], stage / path, compression=self._compression, row_group_size=self._row_group_size
                )
            (stage / "graphs.json").write_text(
                only_canonical_json([item.to_dict() for item in candidate.graphs]), encoding="utf-8"
            )
            logical = {item.relative_path: item for item in candidate.sections}
            for path in sorted(logical):
                schema = None if path == "graphs.json" else _schema_payload(tables[path].schema)
                sections.append(
                    OnlyResearchScientificSection(
                        path, logical[path].row_count, logical[path].logical_fingerprint, _sha(stage / path), schema
                    )
                )
            manifest = candidate.result.manifest
            created = self._audit_timestamp()
            scientific = OnlyResearchScientificArtifactManifest(
                manifest.plan,
                manifest.research_result_plan_fingerprint,
                manifest.research_result_content_fingerprint,
                manifest.research_result_fingerprint,
                manifest.dataset_snapshot_fingerprint,
                manifest.calculation_results,
                manifest.statistics_results,
                candidate.statistics_catalog,
                tuple(sections),
                candidate.artifact_content_fingerprint,
                created,
            )
            (stage / "artifact_manifest.json").write_text(only_canonical_json(scientific.to_dict()), encoding="utf-8")
            self._read_verified(stage, manifest.research_result_fingerprint)
            os.rename(stage, target)
            loaded = self.load_verified(manifest.research_result_fingerprint)
            return OnlyResearchArtifactOutcome(
                OnlyResearchArtifactDisposition.EXECUTED,
                manifest.research_result_fingerprint,
                loaded.manifest.artifact_content_fingerprint,
            )
        except OnlyResearchArtifactStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchArtifactStoreError("ARTIFACT_COMMIT_FAILED", str(exc)) from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def load_verified(self, research_result_fingerprint: str) -> OnlyResearchScientificArtifact:
        return self._read_verified(self._target(research_result_fingerprint), research_result_fingerprint)

    def _read_verified(self, root: Path, expected: str) -> OnlyResearchScientificArtifact:
        if not root.is_dir():
            raise OnlyResearchArtifactStoreError("ARTIFACT_NOT_FOUND", expected)
        try:
            names = {item.name for item in root.iterdir()}
            required = {
                "artifact_manifest.json",
                "graphs.json",
                "market.parquet",
                "variables.parquet",
                "signals.parquet",
                "statistics.parquet",
            }
            if (
                root.is_symlink()
                or names != required
                or any(item.is_symlink() or not item.is_file() for item in root.iterdir())
            ):
                raise ValueError("Scientific Artifact file set is invalid")
            payload = json.loads((root / "artifact_manifest.json").read_text(encoding="utf-8"))
            manifest = OnlyResearchScientificArtifactManifest.from_dict(payload)
            if manifest.research_result_fingerprint != expected:
                raise ValueError("Scientific Artifact path identity mismatch")
            descriptors = {item.relative_path: item for item in manifest.sections}
            tables = {
                path: pq.read_table(root / path)
                for path in ("market.parquet", "variables.parquet", "signals.parquet", "statistics.parquet")
            }
            expected_schemas = {
                "market.parquet": _MARKET,
                "variables.parquet": _VARIABLES,
                "signals.parquet": _SIGNALS,
                "statistics.parquet": _STATISTICS,
            }
            for path, descriptor in descriptors.items():
                if _sha(root / path) != descriptor.byte_sha256:
                    raise ValueError("Scientific Artifact byte hash mismatch")
                if path != "graphs.json" and (
                    tables[path].schema != expected_schemas[path]
                    or descriptor.arrow_schema != _schema_payload(tables[path].schema)
                ):
                    raise ValueError("Scientific Artifact Arrow schema mismatch")
            market = tuple(OnlyResearchScientificMarketRow(**row) for row in tables["market.parquet"].to_pylist())
            variables = tuple(_variable(row) for row in tables["variables.parquet"].to_pylist())
            signals = tuple(OnlyResearchScientificSignalRow(**row) for row in tables["signals.parquet"].to_pylist())
            statistics = tuple(
                OnlyResearchArtifactStatisticsRow(
                    row["statistics_fingerprint"],
                    row["ts_event_ns"],
                    row["statistic_value"],
                    row["sample_count"],
                    OnlyResearchStatisticStatus(row["status"]),
                )
                for row in tables["statistics.parquet"].to_pylist()
            )
            raw_graphs = json.loads((root / "graphs.json").read_text(encoding="utf-8"))
            graphs = tuple(
                OnlyResearchScientificGraph(
                    item["calculation_fingerprint"],
                    __import__(
                        "onlyalpha.calculation.graph", fromlist=["OnlyCalculationGraphDefinition"]
                    ).OnlyCalculationGraphDefinition.from_dict(item["graph"]),
                )
                for item in raw_graphs
            )
            for values in (market, signals, statistics, graphs):
                if values != tuple(sorted(values)):
                    raise ValueError("Scientific Artifact rows are not canonical")
            if variables != tuple(
                sorted(
                    variables,
                    key=lambda item: (
                        item.candidate_fingerprint or "",
                        item.calculation_fingerprint,
                        item.node_fingerprint,
                        item.output_name,
                        item.instrument_id,
                        item.ts_event_ns,
                    ),
                )
            ):
                raise ValueError("Scientific Artifact rows are not canonical")
            semantic: dict[str, list[dict[str, object]]] = {
                "graphs.json": [item.to_dict() for item in graphs],
                "market.parquet": [item.to_dict() for item in market],
                "signals.parquet": [item.to_dict() for item in signals],
                "statistics.parquet": [
                    {
                        "statistics_fingerprint": item.statistics_fingerprint,
                        "ts_event_ns": item.ts_event_ns,
                        "statistic_value": item.statistic_value,
                        "sample_count": item.sample_count,
                        "status": item.status.value,
                    }
                    for item in statistics
                ],
                "variables.parquet": [item.to_dict() for item in variables],
            }
            for path, rows in semantic.items():
                name = path.split(".", 1)[0]
                descriptor = descriptors[path]
                if descriptor.row_count != len(
                    rows
                ) or descriptor.logical_fingerprint != only_research_scientific_section_fingerprint(name, rows):
                    raise ValueError("Scientific Artifact logical section mismatch")
            _verify_groups(manifest.statistics_catalog, statistics)
            if tuple((item.calculation_fingerprint, item.graph.fingerprint) for item in graphs) != tuple(
                (item.calculation_fingerprint, item.graph_fingerprint) for item in manifest.plan.calculations
            ):
                raise ValueError("Scientific Artifact Graph membership mismatch")
            if {
                (item.candidate_fingerprint, item.calculation_fingerprint, item.node_fingerprint, item.output_name)
                for item in variables
            } != {
                (item.candidate_fingerprint, item.calculation_fingerprint, item.node_fingerprint, item.output_name)
                for item in manifest.plan.published_series
            }:
                raise ValueError("Scientific Artifact published membership mismatch")
            if {(item.candidate_fingerprint, item.role) for item in signals} != {
                (item.candidate_fingerprint, item.role) for item in manifest.plan.signals
            }:
                raise ValueError("Scientific Artifact Signal membership mismatch")
            if (
                only_research_scientific_artifact_content_fingerprint(
                    manifest.research_result_fingerprint, manifest.sections
                )
                != manifest.artifact_content_fingerprint
            ):
                raise ValueError("Scientific Artifact identity mismatch")
            return OnlyResearchScientificArtifact(manifest, market, variables, signals, statistics, graphs, tables)
        except OnlyResearchArtifactStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchArtifactStoreError("ARTIFACT_CORRUPT", str(exc)) from exc

    def _target(self, fingerprint: str) -> Path:
        if len(fingerprint) != 64:
            raise OnlyResearchArtifactStoreError("ARTIFACT_NOT_FOUND", fingerprint)
        return (
            self._root
            / RESEARCH_SCIENTIFIC_ARTIFACT_PROFILE.lower().replace("_", "-")
            / "sha256"
            / fingerprint[:2]
            / fingerprint
        )

    def _audit_timestamp(self) -> datetime:
        if self._audit_time is None:
            raise ValueError("audit time authority is required")
        value = self._audit_time()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("audit time must be timezone-aware UTC")
        return value


def _candidate_tables(candidate: OnlyResearchScientificArtifactCandidate) -> dict[str, pa.Table]:
    return {
        "market.parquet": pa.Table.from_pylist([item.to_dict() for item in candidate.market_rows], schema=_MARKET),
        "variables.parquet": pa.Table.from_pylist(
            [item.to_dict() for item in candidate.variable_rows], schema=_VARIABLES
        ),
        "signals.parquet": pa.Table.from_pylist([item.to_dict() for item in candidate.signal_rows], schema=_SIGNALS),
        "statistics.parquet": pa.Table.from_pylist(
            [
                {
                    "statistics_fingerprint": item.statistics_fingerprint,
                    "ts_event_ns": item.ts_event_ns,
                    "statistic_value": item.statistic_value,
                    "sample_count": item.sample_count,
                    "status": item.status.value,
                }
                for item in candidate.statistics_rows
            ],
            schema=_STATISTICS,
        ),
    }


def _variable(row: dict[str, object]) -> OnlyResearchScientificVariableRow:
    candidate = row["candidate_fingerprint"]
    boolean_value = row["boolean_value"]
    if candidate is not None and not isinstance(candidate, str):
        raise ValueError("candidate_fingerprint is invalid")
    if boolean_value is not None and not isinstance(boolean_value, bool):
        raise ValueError("boolean_value is invalid")
    ts = row["ts_event_ns"]
    if isinstance(ts, bool) or not isinstance(ts, int):
        raise ValueError("ts_event_ns is invalid")
    return OnlyResearchScientificVariableRow(
        candidate,
        _required_string(row["calculation_fingerprint"]),
        _required_string(row["node_fingerprint"]),
        _required_string(row["output_name"]),
        _required_string(row["instrument_id"]),
        ts,
        OnlyResearchScientificValueKind(_required_string(row["value_kind"])),
        _optional_string(row["decimal_value"]),
        _optional_string(row["integer_value"]),
        boolean_value,
        _optional_string(row["string_value"]),
    )


def _required_string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Scientific Artifact value must be a string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _required_string(value)


def _schema_payload(schema: pa.Schema) -> tuple[dict[str, object], ...]:
    return tuple({"name": field.name, "type": str(field.type), "nullable": field.nullable} for field in schema)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
