"""Verified atomic immutable Parquet Research Calculation Result Store."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from onlyalpha.calculation.definition import (
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyTimestampSemantic,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.research.dataset import OnlyResearchDatasetSnapshotStore

from .errors import OnlyResearchCalculationResultStoreError
from .execution import OnlyResearchCalculationExecution, OnlyResearchCalculationNodeOutput
from .identity import only_research_calculation_fingerprint
from .result import (
    OnlyResearchCalculationResult,
    OnlyResearchCalculationResultManifest,
    OnlyResearchCalculationResultPartitionManifest,
    OnlyResearchCalculationResultVerification,
)
from .result_identity import (
    RESEARCH_CALCULATION_RESULT_SCHEMA_VERSION,
    only_research_calculation_arrow_schema_payload,
    only_research_calculation_partition_fingerprint,
    only_research_calculation_result_content_fingerprint,
    only_research_calculation_result_fingerprint,
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    execution: OnlyResearchCalculationExecution
    graph: OnlyCalculationGraphDefinition
    outputs: tuple[OnlyResearchCalculationNodeOutput, ...]
    result_content_fingerprint: str
    calculation_result_fingerprint: str


class OnlyParquetResearchCalculationResultStore:
    def __init__(
        self,
        root: Path,
        dataset_store: OnlyResearchDatasetSnapshotStore,
        *,
        compression: str = "zstd",
        row_group_size: int | None = None,
        audit_time: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = root
        self._dataset_store = dataset_store
        self._compression = compression
        self._row_group_size = row_group_size
        self._audit_time = audit_time

    def exists(self, calculation_fingerprint: str) -> bool:
        return self._target(calculation_fingerprint).exists()

    def commit(
        self,
        execution: OnlyResearchCalculationExecution,
        graph: OnlyCalculationGraphDefinition,
    ) -> OnlyResearchCalculationResult:
        created_at = self._audit_timestamp()
        candidate = self._admit(execution, graph)
        target = self._target(execution.calculation_fingerprint)
        if target.exists():
            return self._resolve_existing(candidate)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        stage.mkdir()
        try:
            (stage / "data").mkdir()
            partitions: list[OnlyResearchCalculationResultPartitionManifest] = []
            for index, output in enumerate(candidate.outputs):
                relative = f"data/p-{index:06d}.parquet"
                path = stage / relative
                pq.write_table(
                    output.table,
                    path,
                    compression=self._compression,
                    row_group_size=self._row_group_size,
                )
                restored = pq.read_table(path)
                if not _tables_equal(restored, output.table):
                    raise OnlyResearchCalculationResultStoreError(
                        "RESULT_COMMIT_FAILED", "Parquet logical round-trip mismatch"
                    )
                partitions.append(
                    OnlyResearchCalculationResultPartitionManifest(
                        output.node_fingerprint,
                        output.instrument_id,
                        output.table.num_rows,
                        only_research_calculation_arrow_schema_payload(output.table.schema),
                        only_research_calculation_partition_fingerprint(
                            output.node_fingerprint, output.instrument_id, output.table
                        ),
                        relative,
                        _sha(path),
                    )
                )
            manifest = OnlyResearchCalculationResultManifest(
                execution.calculation_fingerprint,
                execution.dataset_snapshot_fingerprint,
                execution.calculation_graph_fingerprint,
                graph,
                candidate.result_content_fingerprint,
                candidate.calculation_result_fingerprint,
                len(partitions),
                sum(item.row_count for item in partitions),
                tuple(partitions),
                created_at,
                RESEARCH_CALCULATION_RESULT_SCHEMA_VERSION,
            )
            (stage / "manifest.json").write_text(
                json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            try:
                self._read_verified(stage, execution.calculation_fingerprint)
            except OnlyResearchCalculationResultStoreError as exc:
                raise OnlyResearchCalculationResultStoreError(
                    "RESULT_COMMIT_FAILED", "staged Result verification failed"
                ) from exc
            try:
                os.rename(stage, target)
            except OSError:
                if not target.exists():
                    raise
                return self._resolve_existing(candidate)
            return self.load_verified(execution.calculation_fingerprint)
        except OnlyResearchCalculationResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchCalculationResultStoreError("RESULT_COMMIT_FAILED", "atomic publication failed") from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def load_verified(self, calculation_fingerprint: str) -> OnlyResearchCalculationResult:
        return self._read_verified(self._target(calculation_fingerprint), calculation_fingerprint)

    def verify(self, calculation_fingerprint: str) -> OnlyResearchCalculationResultVerification:
        result = self.load_verified(calculation_fingerprint)
        manifest = result.manifest
        return OnlyResearchCalculationResultVerification(
            True,
            manifest.calculation_fingerprint,
            manifest.calculation_result_fingerprint,
            manifest.partition_count,
            manifest.total_row_count,
        )

    def _resolve_existing(self, candidate: _Candidate) -> OnlyResearchCalculationResult:
        existing = self.load_verified(candidate.execution.calculation_fingerprint)
        if existing.manifest.result_content_fingerprint != candidate.result_content_fingerprint:
            raise OnlyResearchCalculationResultStoreError(
                "DETERMINISTIC_RESULT_CONFLICT",
                candidate.execution.calculation_fingerprint,
            )
        return existing

    def _admit(
        self,
        execution: OnlyResearchCalculationExecution,
        graph: OnlyCalculationGraphDefinition,
    ) -> _Candidate:
        try:
            if execution.calculation_graph_fingerprint != graph.fingerprint:
                raise ValueError("Calculation Graph fingerprint mismatch")
            expected_calculation = only_research_calculation_fingerprint(
                execution.dataset_snapshot_fingerprint, graph.fingerprint
            )
            if execution.calculation_fingerprint != expected_calculation:
                raise ValueError("Calculation fingerprint mismatch")
            verified = self._dataset_store.load_verified_table(execution.dataset_snapshot_fingerprint)
            expected = _expected_axes(verified.table)
            outputs = _canonical_outputs(execution.outputs, graph, expected)
            content = _result_content_fingerprint(outputs)
            return _Candidate(
                execution,
                graph,
                outputs,
                content,
                only_research_calculation_result_fingerprint(execution.calculation_fingerprint, content),
            )
        except OnlyResearchCalculationResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchCalculationResultStoreError("RESULT_INVALID", str(exc)) from exc

    def _read_verified(self, root: Path, expected_fingerprint: str) -> OnlyResearchCalculationResult:
        if not root.is_dir():
            raise OnlyResearchCalculationResultStoreError("RESULT_NOT_FOUND", expected_fingerprint)
        try:
            if root.is_symlink() or (root / "data").is_symlink() or (root / "manifest.json").is_symlink():
                raise ValueError("Result authority may not contain symlink roots")
            entries = {item.name for item in root.iterdir()}
            if entries != {"data", "manifest.json"} or not (root / "data").is_dir():
                raise ValueError("unexpected Result root entries")
            payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("manifest must be an object")
            manifest = OnlyResearchCalculationResultManifest.from_dict(payload)
            if manifest.calculation_fingerprint != expected_fingerprint:
                raise ValueError("Result path identity mismatch")
            expected_calculation = only_research_calculation_fingerprint(
                manifest.dataset_snapshot_fingerprint, manifest.calculation_graph_fingerprint
            )
            if expected_calculation != manifest.calculation_fingerprint:
                raise ValueError("Calculation fingerprint linkage mismatch")
            verified_dataset = self._dataset_store.load_verified_table(manifest.dataset_snapshot_fingerprint)
            axes = _expected_axes(verified_dataset.table)
            expected_keys = _expected_partition_keys(manifest.calculation_graph, axes)
            actual_keys = tuple((item.node_fingerprint, item.instrument_id) for item in manifest.partitions)
            if actual_keys != expected_keys:
                raise ValueError("Result partition set mismatch")
            expected_paths = {item.relative_path for item in manifest.partitions}
            actual_paths = {item.relative_to(root).as_posix() for item in (root / "data").iterdir() if item.is_file()}
            if actual_paths != expected_paths or any(item.is_dir() for item in (root / "data").iterdir()):
                raise ValueError("unexpected or missing Result partition")
            nodes = {node.fingerprint: node.definition for node in manifest.calculation_graph.ordered_nodes}
            outputs: list[OnlyResearchCalculationNodeOutput] = []
            descriptors: list[tuple[str, str, int, str, tuple[dict[str, object], ...]]] = []
            for partition in manifest.partitions:
                path = root / partition.relative_path
                if path.is_symlink() or not path.is_file() or _sha(path) != partition.byte_sha256:
                    raise ValueError("Result partition byte hash mismatch")
                table = pq.read_table(path)
                schema_payload = only_research_calculation_arrow_schema_payload(table.schema)
                if schema_payload != partition.arrow_schema:
                    raise ValueError("Result partition Arrow schema mismatch")
                canonical = _canonical_table(nodes[partition.node_fingerprint], table, axes[partition.instrument_id])
                if not _tables_equal(canonical, table):
                    raise ValueError("Result partition logical contract mismatch")
                if table.num_rows != partition.row_count:
                    raise ValueError("Result partition row count mismatch")
                semantic = only_research_calculation_partition_fingerprint(
                    partition.node_fingerprint, partition.instrument_id, table
                )
                if semantic != partition.semantic_fingerprint:
                    raise ValueError("Result partition semantic fingerprint mismatch")
                descriptors.append(
                    (
                        partition.node_fingerprint,
                        partition.instrument_id,
                        partition.row_count,
                        semantic,
                        schema_payload,
                    )
                )
                outputs.append(
                    OnlyResearchCalculationNodeOutput(partition.node_fingerprint, partition.instrument_id, table)
                )
            content = only_research_calculation_result_content_fingerprint(tuple(descriptors))
            if content != manifest.result_content_fingerprint:
                raise ValueError("Result Content fingerprint mismatch")
            result_fingerprint = only_research_calculation_result_fingerprint(expected_fingerprint, content)
            if result_fingerprint != manifest.calculation_result_fingerprint:
                raise ValueError("Calculation Result fingerprint mismatch")
            return OnlyResearchCalculationResult(manifest, tuple(outputs))
        except OnlyResearchCalculationResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchCalculationResultStoreError("RESULT_CORRUPT", str(exc)) from exc

    def _target(self, fingerprint: str) -> Path:
        if not _valid_sha(fingerprint):
            raise OnlyResearchCalculationResultStoreError("RESULT_NOT_FOUND", "invalid Calculation fingerprint")
        return self._root / "sha256" / fingerprint[:2] / fingerprint

    def _audit_timestamp(self) -> datetime:
        if self._audit_time is None:
            raise OnlyResearchCalculationResultStoreError(
                "RESULT_INVALID", "audit time authority is required for commit"
            )
        value = self._audit_time()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise OnlyResearchCalculationResultStoreError("RESULT_INVALID", "audit time must be timezone-aware UTC")
        return value


def _expected_axes(table: pa.Table) -> dict[str, tuple[int, ...]]:
    result: dict[str, tuple[int, ...]] = {}
    instruments = sorted(set(table.column("instrument_id").to_pylist()))
    for instrument in instruments:
        selected = table.filter(pa.compute.equal(table.column("instrument_id"), instrument))
        timestamps = tuple(selected.column("ts_event_ns").to_pylist())
        if timestamps != tuple(sorted(timestamps)) or len(timestamps) != len(set(timestamps)):
            raise ValueError("Dataset timestamp axis is not canonical")
        result[str(instrument)] = timestamps
    return result


def _expected_partition_keys(
    graph: OnlyCalculationGraphDefinition,
    axes: dict[str, tuple[int, ...]],
) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((node.fingerprint, instrument) for node in graph.ordered_nodes for instrument in axes))


def _canonical_outputs(
    raw: tuple[OnlyResearchCalculationNodeOutput, ...],
    graph: OnlyCalculationGraphDefinition,
    axes: dict[str, tuple[int, ...]],
) -> tuple[OnlyResearchCalculationNodeOutput, ...]:
    nodes = {node.fingerprint: node.definition for node in graph.ordered_nodes}
    values: dict[tuple[str, str], OnlyResearchCalculationNodeOutput] = {}
    for output in raw:
        key = (output.node_fingerprint, output.instrument_id)
        if key in values:
            raise ValueError("duplicate Result partition")
        if output.node_fingerprint not in nodes or output.instrument_id not in axes:
            raise ValueError("unexpected Result partition")
        values[key] = OnlyResearchCalculationNodeOutput(
            output.node_fingerprint,
            output.instrument_id,
            _canonical_table(nodes[output.node_fingerprint], output.table, axes[output.instrument_id]),
        )
    expected = _expected_partition_keys(graph, axes)
    if tuple(sorted(values)) != expected:
        raise ValueError("missing Result partition")
    return tuple(values[key] for key in expected)


def _canonical_table(
    definition: OnlyCalculationDefinition,
    table: pa.Table,
    expected_timestamps: tuple[int, ...],
) -> pa.Table:
    if not isinstance(table, pa.Table):
        raise ValueError("Result partition must be an Arrow Table")
    expected_outputs = {item.name: item for item in definition.outputs}
    expected_names = {"ts_event_ns", *expected_outputs}
    if len(table.column_names) != len(set(table.column_names)) or set(table.column_names) != expected_names:
        raise ValueError("Result output column names are invalid")
    timestamp = table.column("ts_event_ns")
    if definition.timestamp is not OnlyTimestampSemantic.EVENT_TIME:
        raise ValueError("unsupported Result timestamp semantic")
    if timestamp.type != pa.int64() or timestamp.null_count or tuple(timestamp.to_pylist()) != expected_timestamps:
        raise ValueError("Result timestamp axis is invalid")
    arrays: list[pa.ChunkedArray] = [timestamp]
    fields = [pa.field("ts_event_ns", pa.int64(), nullable=False)]
    for name in sorted(expected_outputs):
        contract = expected_outputs[name]
        values = table.column(name)
        if not _output_type_matches(values.type, contract.data_type):
            raise ValueError(f"Result output {name} data type is invalid")
        if values.null_count and not contract.nullable:
            raise ValueError(f"Result output {name} nullability is invalid")
        arrays.append(values)
        fields.append(pa.field(name, values.type, nullable=contract.nullable))
    if table.num_rows != len(expected_timestamps):
        raise ValueError("Result output row count is invalid")
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def _output_type_matches(data_type: pa.DataType, expected: OnlyCalculationDataType) -> bool:
    return (
        expected is OnlyCalculationDataType.DECIMAL
        and pa.types.is_decimal(data_type)
        or expected is OnlyCalculationDataType.INTEGER
        and pa.types.is_integer(data_type)
        or expected is OnlyCalculationDataType.BOOLEAN
        and pa.types.is_boolean(data_type)
        or expected is OnlyCalculationDataType.STRING
        and pa.types.is_string(data_type)
    )


def _result_content_fingerprint(outputs: tuple[OnlyResearchCalculationNodeOutput, ...]) -> str:
    return only_research_calculation_result_content_fingerprint(
        tuple(
            (
                output.node_fingerprint,
                output.instrument_id,
                output.table.num_rows,
                only_research_calculation_partition_fingerprint(
                    output.node_fingerprint, output.instrument_id, output.table
                ),
                only_research_calculation_arrow_schema_payload(output.table.schema),
            )
            for output in outputs
        )
    )


def _tables_equal(first: pa.Table, second: pa.Table) -> bool:
    return bool(first.schema == second.schema and first.equals(second, check_metadata=True))


def _valid_sha(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(item in "0123456789abcdef" for item in value)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
