"""Verified atomic immutable Parquet Factor-Pair Statistics authority."""

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
from typing import Protocol

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from onlyalpha.research.calculation.result import OnlyResearchCalculationResult

from ..errors import OnlyResearchStatisticsResultStoreError
from .execution import OnlyResearchFactorPairStatisticsExecution, _validate_factor_pair_upstream
from .identity import only_research_factor_pair_result_content_fingerprint, only_research_factor_pair_result_fingerprint
from .result import (
    OnlyResearchFactorPairStatisticRow,
    OnlyResearchFactorPairStatisticsResult,
    OnlyResearchFactorPairStatisticsResultManifest,
    OnlyResearchFactorPairStatisticsResultVerification,
    OnlyResearchFactorPairStatisticStatus,
)

_DECIMAL = pa.decimal128(38, 12)
_SCHEMA = pa.schema(
    (
        pa.field("ts_event_ns", pa.int64(), nullable=False),
        pa.field("statistic_value", _DECIMAL, nullable=True),
        pa.field("sample_count", pa.int64(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
    )
)


class _CalculationResultStore(Protocol):
    def load_verified(self, calculation_fingerprint: str) -> OnlyResearchCalculationResult: ...


@dataclass(frozen=True, slots=True)
class _Candidate:
    execution: OnlyResearchFactorPairStatisticsExecution
    table: pa.Table
    result_content_fingerprint: str
    statistics_result_fingerprint: str


class OnlyParquetResearchFactorPairStatisticsResultStore:
    def __init__(
        self,
        root: Path,
        calculation_result_store: _CalculationResultStore,
        *,
        compression: str = "zstd",
        row_group_size: int | None = None,
        audit_time: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = root
        self._calculation_result_store = calculation_result_store
        self._compression = compression
        self._row_group_size = row_group_size
        self._audit_time = audit_time

    def exists(self, statistics_fingerprint: str) -> bool:
        return self._target(statistics_fingerprint).exists()

    def commit(self, execution: OnlyResearchFactorPairStatisticsExecution) -> OnlyResearchFactorPairStatisticsResult:
        created_at = self._audit_timestamp()
        candidate = self._admit(execution)
        target = self._target(execution.plan.statistics_fingerprint)
        if target.exists():
            return self._resolve_existing(candidate)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        stage.mkdir()
        try:
            data_path = stage / "data.parquet"
            pq.write_table(
                candidate.table,
                data_path,
                compression=self._compression,
                row_group_size=self._row_group_size,
            )
            restored = pq.read_table(data_path)
            if restored.schema != candidate.table.schema or not restored.equals(candidate.table, check_metadata=True):
                raise OnlyResearchStatisticsResultStoreError(
                    "FACTOR_PAIR_STATISTICS_RESULT_COMMIT_FAILED", "Parquet logical round-trip mismatch"
                )
            manifest = OnlyResearchFactorPairStatisticsResultManifest(
                execution.plan.statistics_fingerprint,
                execution.plan,
                execution.first_calculation_result_fingerprint,
                execution.second_calculation_result_fingerprint,
                execution.dataset_snapshot_fingerprint,
                candidate.result_content_fingerprint,
                candidate.statistics_result_fingerprint,
                len(execution.rows),
                _schema_payload(candidate.table.schema),
                _sha(data_path),
                created_at,
            )
            (stage / "manifest.json").write_text(
                json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            try:
                self._read_verified(stage, execution.plan.statistics_fingerprint)
            except OnlyResearchStatisticsResultStoreError as exc:
                raise OnlyResearchStatisticsResultStoreError(
                    "FACTOR_PAIR_STATISTICS_RESULT_COMMIT_FAILED", "staged round-trip verification failed"
                ) from exc
            try:
                os.rename(stage, target)
            except OSError:
                if not target.exists():
                    raise
                return self._resolve_existing(candidate)
            return self.load_verified(execution.plan.statistics_fingerprint)
        except OnlyResearchStatisticsResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchStatisticsResultStoreError(
                "FACTOR_PAIR_STATISTICS_RESULT_COMMIT_FAILED", "atomic publication failed"
            ) from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchFactorPairStatisticsResult:
        return self._read_verified(self._target(statistics_fingerprint), statistics_fingerprint)

    def verify(self, statistics_fingerprint: str) -> OnlyResearchFactorPairStatisticsResultVerification:
        result = self.load_verified(statistics_fingerprint)
        return OnlyResearchFactorPairStatisticsResultVerification(
            True,
            result.manifest.statistics_fingerprint,
            result.manifest.statistics_result_fingerprint,
            result.manifest.row_count,
        )

    def _admit(self, execution: OnlyResearchFactorPairStatisticsExecution) -> _Candidate:
        if not isinstance(execution, OnlyResearchFactorPairStatisticsExecution):
            raise OnlyResearchStatisticsResultStoreError(
                "FACTOR_PAIR_STATISTICS_RESULT_INVALID", "execution contract is invalid"
            )
        try:
            first = self._calculation_result_store.load_verified(
                execution.plan.first_operand.series.calculation_fingerprint
            )
            second = self._calculation_result_store.load_verified(
                execution.plan.second_operand.series.calculation_fingerprint
            )
            dataset = _validate_factor_pair_upstream(execution.plan, first, second)
            if dataset != execution.dataset_snapshot_fingerprint:
                raise ValueError("Dataset linkage mismatch")
            if first.manifest.calculation_result_fingerprint != execution.first_calculation_result_fingerprint:
                raise ValueError("first Calculation Result linkage mismatch")
            if second.manifest.calculation_result_fingerprint != execution.second_calculation_result_fingerprint:
                raise ValueError("second Calculation Result linkage mismatch")
            rows = _canonical_rows(execution.rows)
            table = _table(rows)
            content = _content(execution, rows)
            return _Candidate(
                execution,
                table,
                content,
                only_research_factor_pair_result_fingerprint(execution.plan.statistics_fingerprint, content),
            )
        except OnlyResearchStatisticsResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchStatisticsResultStoreError("FACTOR_PAIR_STATISTICS_RESULT_INVALID", str(exc)) from exc

    def _resolve_existing(self, candidate: _Candidate) -> OnlyResearchFactorPairStatisticsResult:
        existing = self.load_verified(candidate.execution.plan.statistics_fingerprint)
        if existing.manifest.result_content_fingerprint != candidate.result_content_fingerprint:
            raise OnlyResearchStatisticsResultStoreError(
                "DETERMINISTIC_RESULT_CONFLICT", candidate.execution.plan.statistics_fingerprint
            )
        return existing

    def _read_verified(self, root: Path, expected_fingerprint: str) -> OnlyResearchFactorPairStatisticsResult:
        if not root.is_dir():
            raise OnlyResearchStatisticsResultStoreError(
                "FACTOR_PAIR_STATISTICS_RESULT_NOT_FOUND", expected_fingerprint
            )
        try:
            manifest_path = root / "manifest.json"
            data_path = root / "data.parquet"
            if root.is_symlink() or manifest_path.is_symlink() or data_path.is_symlink():
                raise ValueError("Factor-Pair authority may not contain symlinks")
            if {item.name for item in root.iterdir()} != {"manifest.json", "data.parquet"}:
                raise ValueError("unexpected Factor-Pair Result files")
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Factor-Pair manifest must be an object")
            manifest = OnlyResearchFactorPairStatisticsResultManifest.from_dict(payload)
            if manifest.statistics_fingerprint != expected_fingerprint:
                raise ValueError("Factor-Pair path identity mismatch")
            first = self._calculation_result_store.load_verified(
                manifest.plan.first_operand.series.calculation_fingerprint
            )
            second = self._calculation_result_store.load_verified(
                manifest.plan.second_operand.series.calculation_fingerprint
            )
            dataset = _validate_factor_pair_upstream(manifest.plan, first, second)
            if dataset != manifest.dataset_snapshot_fingerprint:
                raise ValueError("Factor-Pair Dataset linkage mismatch")
            if first.manifest.calculation_result_fingerprint != manifest.first_calculation_result_fingerprint:
                raise ValueError("Factor-Pair first Calculation Result linkage mismatch")
            if second.manifest.calculation_result_fingerprint != manifest.second_calculation_result_fingerprint:
                raise ValueError("Factor-Pair second Calculation Result linkage mismatch")
            if not data_path.is_file() or _sha(data_path) != manifest.data_byte_sha256:
                raise ValueError("Factor-Pair data byte hash mismatch")
            table = pq.read_table(data_path)
            if table.schema != _SCHEMA or _schema_payload(table.schema) != manifest.arrow_schema:
                raise ValueError("Factor-Pair Arrow schema mismatch")
            rows = _rows(table)
            if len(rows) != manifest.row_count:
                raise ValueError("Factor-Pair row count mismatch")
            content = only_research_factor_pair_result_content_fingerprint(
                manifest.first_calculation_result_fingerprint,
                manifest.second_calculation_result_fingerprint,
                tuple(row.semantic_payload() for row in rows),
            )
            if content != manifest.result_content_fingerprint:
                raise ValueError("Factor-Pair content fingerprint mismatch")
            result = only_research_factor_pair_result_fingerprint(expected_fingerprint, content)
            if result != manifest.statistics_result_fingerprint:
                raise ValueError("Factor-Pair Result fingerprint mismatch")
            return OnlyResearchFactorPairStatisticsResult(manifest, rows, table)
        except OnlyResearchStatisticsResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchStatisticsResultStoreError("FACTOR_PAIR_STATISTICS_RESULT_CORRUPT", str(exc)) from exc

    def _target(self, fingerprint: str) -> Path:
        if not _valid_sha(fingerprint):
            raise OnlyResearchStatisticsResultStoreError(
                "FACTOR_PAIR_STATISTICS_RESULT_NOT_FOUND", "invalid Statistics fingerprint"
            )
        return self._root / "sha256" / fingerprint[:2] / fingerprint

    def _audit_timestamp(self) -> datetime:
        if self._audit_time is None:
            raise OnlyResearchStatisticsResultStoreError(
                "FACTOR_PAIR_STATISTICS_RESULT_INVALID", "audit time authority is required for commit"
            )
        value = self._audit_time()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise OnlyResearchStatisticsResultStoreError(
                "FACTOR_PAIR_STATISTICS_RESULT_INVALID", "audit time must be timezone-aware UTC"
            )
        return value


def _canonical_rows(
    rows: tuple[OnlyResearchFactorPairStatisticRow, ...],
) -> tuple[OnlyResearchFactorPairStatisticRow, ...]:
    if any(not isinstance(row, OnlyResearchFactorPairStatisticRow) for row in rows):
        raise ValueError("Factor-Pair rows are invalid")
    timestamps = tuple(row.ts_event_ns for row in rows)
    if timestamps != tuple(sorted(timestamps)) or len(timestamps) != len(set(timestamps)):
        raise ValueError("Factor-Pair timestamps are not canonical")
    return rows


def _table(rows: tuple[OnlyResearchFactorPairStatisticRow, ...]) -> pa.Table:
    return pa.Table.from_arrays(
        (
            pa.array((row.ts_event_ns for row in rows), type=pa.int64()),
            pa.array((row.statistic_value for row in rows), type=_DECIMAL),
            pa.array((row.sample_count for row in rows), type=pa.int64()),
            pa.array((row.status.value for row in rows), type=pa.string()),
        ),
        schema=_SCHEMA,
    )


def _rows(table: pa.Table) -> tuple[OnlyResearchFactorPairStatisticRow, ...]:
    try:
        rows = tuple(
            OnlyResearchFactorPairStatisticRow(
                item["ts_event_ns"],
                item["statistic_value"],
                item["sample_count"],
                OnlyResearchFactorPairStatisticStatus(item["status"]),
            )
            for item in table.to_pylist()
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Factor-Pair logical row is invalid") from exc
    return _canonical_rows(rows)


def _content(
    execution: OnlyResearchFactorPairStatisticsExecution,
    rows: tuple[OnlyResearchFactorPairStatisticRow, ...],
) -> str:
    return only_research_factor_pair_result_content_fingerprint(
        execution.first_calculation_result_fingerprint,
        execution.second_calculation_result_fingerprint,
        tuple(row.semantic_payload() for row in rows),
    )


def _schema_payload(schema: pa.Schema) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    for field in schema:
        if pa.types.is_decimal(field.type):
            data_type: dict[str, object] = {
                "kind": "DECIMAL",
                "bit_width": field.type.bit_width,
                "precision": field.type.precision,
                "scale": field.type.scale,
            }
        elif pa.types.is_integer(field.type):
            data_type = {"kind": "INTEGER", "bit_width": field.type.bit_width, "signed": True}
        elif pa.types.is_string(field.type):
            data_type = {"kind": "STRING"}
        else:
            raise ValueError("Factor-Pair Arrow type is unsupported")
        result.append({"name": field.name, "data_type": data_type, "nullable": field.nullable})
    return tuple(result)


def _valid_sha(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
