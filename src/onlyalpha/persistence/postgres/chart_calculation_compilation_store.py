"""Immutable chart compilation consequence under the global Product Command lock."""

from __future__ import annotations

import json
from typing import cast

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from onlyalpha.application.chart_calculation import OnlyChartCalculationError, OnlyChartCalculationOperationV1
from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationV1
from onlyalpha.application.chart_calculation_preparation import OnlyChartCalculationPreparationV1
from onlyalpha.application.product_command_authority import OnlyProductCommandAuthorityUnavailableError
from onlyalpha.canonical import only_canonical_json

from .chart_calculation_preparation_store import OnlyPostgresChartCalculationPreparationStore
from .chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore
from .config import OnlyPostgresOperationalConnectionOptions

_CORRUPT = "CHART_COMPILATION_RELATION_CORRUPT"
_CONFLICT = "CHART_SPECIFICATION_COMPILATION_CONFLICT"


def _require(condition: bool, code: str = _CORRUPT) -> None:
    if not condition:
        raise OnlyChartCalculationError(code)


def _columns(value: OnlyChartCalculationCompilationV1) -> dict[str, object]:
    """The exact wire payload is authority; every SQL reference is a checked projection."""
    return {
        "operation_id": value.operation_id.value,
        "input_preparation_revision": value.input_preparation_revision,
        "input_preparation_fence": value.input_preparation_fence,
        "input_selection_fingerprint": value.input_selection_fingerprint,
        "dataset_snapshot_fingerprint": value.dataset_snapshot_fingerprint,
        "dataset_materialization_id": value.dataset_materialization_id,
        "runtime_generation_fingerprint": value.runtime_generation_fingerprint,
        "runtime_work_id": value.runtime_work_id,
        "runtime_binding_event_fingerprint": value.runtime_binding_reference.binding_event_fingerprint,
        "catalog_witness_fingerprint": value.catalog_witness_fingerprint,
        "catalog_implementation_fingerprint": value.catalog_implementation_fingerprint,
        "specification_fingerprint": value.specification_fingerprint,
        "result_plan_fingerprint": value.result_plan_fingerprint,
        "graph_fingerprint": value.graph_fingerprint,
        "calculation_fingerprint": value.calculation_fingerprint,
        "implementation_fingerprint": value.implementation_fingerprint,
        "compilation_json": only_canonical_json(value.to_dict()),
        "compilation_fingerprint": value.compilation_fingerprint,
        "schema_version": value.schema_version,
    }


class OnlyPostgresChartCalculationCompilationStore:
    def __init__(self, dsn: str, options: OnlyPostgresOperationalConnectionOptions | None = None) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

    @staticmethod
    def _context(
        connection: psycopg.Connection[dict[str, object]], operation: OnlyChartCalculationOperationV1
    ) -> OnlyChartCalculationPreparationV1 | None:
        _require(type(operation) is OnlyChartCalculationOperationV1, "CHART_OPERATION_RELATION_CORRUPT")
        # Owning whole validators include the lock, admission/receipt/reservation, and full fact chain.
        # Never replace them with a smaller reconstruction of selected SQL fields.
        admitted = OnlyPostgresChartCalculationAdmissionStore.load_verified_in_transaction(
            connection, operation.operation_id
        )
        _require(admitted == operation, "CHART_OPERATION_RELATION_CORRUPT")
        return OnlyPostgresChartCalculationPreparationStore.load_verified_in_transaction(connection, operation)

    @staticmethod
    def _load(
        connection: psycopg.Connection[dict[str, object]],
        operation: OnlyChartCalculationOperationV1,
        preparation: OnlyChartCalculationPreparationV1 | None,
    ) -> OnlyChartCalculationCompilationV1 | None:
        row = connection.execute(
            "SELECT * FROM chart_calculation_compilation WHERE operation_id = %s", (operation.operation_id.value,)
        ).fetchone()
        if row is None:
            return None
        try:
            _require(preparation is not None and preparation.state == "INPUT_READY")
            assert preparation is not None
            raw = json.loads(cast(str, row["compilation_json"]))
            value = OnlyChartCalculationCompilationV1.from_dict(raw)
            _require(value.to_dict() == raw)
            projected = dict(row)
            for column in ("operation_id", "runtime_work_id"):
                projected[column] = str(projected[column])
            _require(projected == _columns(value))
            value.verify_operation_preparation(operation, preparation)
            return value
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            # A stored occurrence with another context is corrupt authority, not an insert permit.
            # T1/T2 errors are outside this decoder and retain their owning error taxonomy.
            raise OnlyChartCalculationError(_CORRUPT) from exc

    def load_verified(self, operation: OnlyChartCalculationOperationV1) -> OnlyChartCalculationCompilationV1 | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                preparation = self._context(connection, operation)
                return self._load(connection, operation, preparation)
        except psycopg.Error as exc:
            raise OnlyProductCommandAuthorityUnavailableError(operation.operation_id.value) from exc

    def commit_or_replay(
        self,
        operation: OnlyChartCalculationOperationV1,
        preparation: OnlyChartCalculationPreparationV1,
        compilation: OnlyChartCalculationCompilationV1,
    ) -> OnlyChartCalculationCompilationV1:
        _require(type(compilation) is OnlyChartCalculationCompilationV1)
        _require(OnlyChartCalculationCompilationV1.from_dict(compilation.to_dict()) == compilation)
        compilation.verify_operation_preparation(operation, preparation)
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                current = self._context(connection, operation)
                existing = self._load(connection, operation, current)
                _require(current is not None and current.state == "INPUT_READY", "CHART_INPUT_NOT_READY")
                assert current is not None
                compilation.verify_operation_preparation(operation, current)
                _require(current == preparation, _CONFLICT)
                if existing is not None:
                    _require(existing == compilation and existing.to_dict() == compilation.to_dict(), _CONFLICT)
                    return existing
                values = _columns(compilation)
                connection.execute(
                    sql.SQL(
                        "INSERT INTO chart_calculation_compilation ({}) VALUES ({}) ON CONFLICT (operation_id) DO NOTHING"
                    ).format(
                        sql.SQL(", ").join(map(sql.Identifier, values)),
                        sql.SQL(", ").join(sql.Placeholder() for _ in values),
                    ),
                    tuple(values.values()),
                )
                # A uniqueness loser is never success until complete strict equality is proved.
                verified = self._load(connection, operation, current)
                _require(verified is not None)
                assert verified is not None
                _require(verified == compilation and verified.to_dict() == compilation.to_dict(), _CONFLICT)
            return verified
        except psycopg.Error as exc:
            # Unknown acknowledgement is observation-only recovery: no new write or lifecycle change.
            existing = self.load_verified(operation)
            if existing is not None and existing == compilation and existing.to_dict() == compilation.to_dict():
                return existing
            raise OnlyProductCommandAuthorityUnavailableError(operation.operation_id.value) from exc
