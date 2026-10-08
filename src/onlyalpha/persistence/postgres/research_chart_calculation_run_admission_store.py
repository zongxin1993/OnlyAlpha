"""Research authority transfers a reserved Chart identity into its existing queue."""

from __future__ import annotations

from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from onlyalpha.application.chart_calculation import OnlyChartCalculationError, OnlyChartCalculationOperationV1
from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationV1
from onlyalpha.application.chart_calculation_run_admission import (
    only_chart_calculation_queued_run,
    only_require_chart_calculation_new_admission,
    only_verify_chart_calculation_run,
)
from onlyalpha.application.product_command_authority import OnlyProductCommandAuthorityUnavailableError
from onlyalpha.application.runtime_generation import OnlyRuntimeGenerationWorkAuthority
from onlyalpha.research.run.model import OnlyResearchRun

from .chart_calculation_compilation_store import OnlyPostgresChartCalculationCompilationStore
from .chart_calculation_preparation_store import OnlyPostgresChartCalculationPreparationStore
from .chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore
from .config import OnlyPostgresOperationalConnectionOptions
from .research_run_store import OnlyPostgresResearchRunStore, _insert_run_query

_CORRUPT = "CHART_RUN_ADMISSION_RELATION_CORRUPT"
_CONFLICT = "CHART_RUN_ADMISSION_CONFLICT"


def _require(condition: bool, code: str = _CORRUPT) -> None:
    if not condition:
        raise OnlyChartCalculationError(code)


def only_verify_chart_run_consumption_in_transaction(
    connection: psycopg.Connection[dict[str, object]], operation: OnlyChartCalculationOperationV1
) -> OnlyResearchRun | None:
    """T1 supplies the verified whole Operation. Raw owning T2/D2 validators avoid recursion.

    Missing relation with an existing Run, or a relation without its Run, is corruption,
    never absence or permission to write. The original reservation has been consumed.
    """
    rows = connection.execute(
        "SELECT * FROM chart_calculation_run_admission WHERE operation_id = %s OR run_id = %s",
        (operation.operation_id.value, operation.reserved_run_id.value),
    ).fetchall()
    row = connection.execute(
        "SELECT * FROM research_run WHERE run_id = %s", (operation.reserved_run_id.value,)
    ).fetchone()
    if not rows and row is None:
        return None
    _require(len(rows) == 1 and row is not None)
    assert row is not None
    preparation = OnlyPostgresChartCalculationPreparationStore._load(connection, operation)[0]
    compilation = OnlyPostgresChartCalculationCompilationStore._load(connection, operation, preparation)
    _require(compilation is not None)
    assert compilation is not None
    try:
        run = OnlyPostgresResearchRunStore._decode(row)
        only_verify_chart_calculation_run(run, compilation)
        _require(run.queued_at >= operation.accepted_at)
        relation = {**rows[0], "operation_id": str(rows[0]["operation_id"]), "run_id": str(rows[0]["run_id"])}
        _require(
            relation
            == {
                "operation_id": operation.operation_id.value,
                "run_id": operation.reserved_run_id.value,
                "compilation_fingerprint": compilation.compilation_fingerprint,
                "queued_at": run.queued_at,
                "schema_version": 1,
            }
        )
        _require(
            connection.execute(
                "SELECT 1 FROM research_run_id_reservation WHERE run_id = %s OR owner_id = %s",
                (operation.reserved_run_id.value, operation.operation_id.value),
            ).fetchone()
            is None
        )
        return run
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise OnlyChartCalculationError(_CORRUPT) from exc


class OnlyPostgresChartCalculationRunAdmissionStore:
    def __init__(
        self,
        dsn: str,
        options: OnlyPostgresOperationalConnectionOptions | None = None,
        *,
        runtime_generations: OnlyRuntimeGenerationWorkAuthority,
    ) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)
        self._runtime = runtime_generations

    @staticmethod
    def _context(
        connection: psycopg.Connection[dict[str, object]], operation: OnlyChartCalculationOperationV1
    ) -> OnlyChartCalculationCompilationV1:
        _require(
            OnlyPostgresChartCalculationAdmissionStore.load_verified_in_transaction(connection, operation.operation_id)
            == operation,
            "CHART_OPERATION_RELATION_CORRUPT",
        )
        preparation = OnlyPostgresChartCalculationPreparationStore._load(connection, operation)[0]
        _require(preparation is not None and preparation.state == "INPUT_READY", "CHART_INPUT_NOT_READY")
        frozen = OnlyPostgresChartCalculationCompilationStore._load(connection, operation, preparation)
        _require(frozen is not None, "CHART_COMPILATION_NOT_READY")
        assert frozen is not None
        return frozen

    def load_verified(self, operation: OnlyChartCalculationOperationV1) -> OnlyResearchRun | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                self._context(connection, operation)
                return only_verify_chart_run_consumption_in_transaction(connection, operation)
        except psycopg.Error as exc:
            raise OnlyProductCommandAuthorityUnavailableError(operation.operation_id.value) from exc

    def commit_or_replay(
        self,
        operation: OnlyChartCalculationOperationV1,
        compilation: OnlyChartCalculationCompilationV1,
        *,
        queued_at: datetime,
    ) -> OnlyResearchRun:
        _require(type(operation) is OnlyChartCalculationOperationV1)
        _require(type(compilation) is OnlyChartCalculationCompilationV1)
        expected = only_chart_calculation_queued_run(compilation, queued_at=queued_at)
        _require(expected.run_id == operation.reserved_run_id and queued_at >= operation.accepted_at, _CONFLICT)
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                frozen = self._context(connection, operation)
                _require(frozen == compilation and frozen.to_dict() == compilation.to_dict(), _CONFLICT)
                existing = only_verify_chart_run_consumption_in_transaction(connection, operation)
                if existing is not None:
                    # Retry time is not a second queue occurrence; the durable queue timestamp wins.
                    return existing
                # T1 holds SHARE on this table before writing source history. Take the
                # compatible-writer table lock before the frontier, never the inverse.
                # ROW EXCLUSIVE remains compatible with ordinary Research writers.
                connection.execute("LOCK TABLE research_run IN ROW EXCLUSIVE MODE")
                # Frontier still precedes reservation uniqueness, as in generic admission.
                _require(
                    connection.execute(
                        "SELECT last_index FROM research_source_history_frontier WHERE singleton = TRUE FOR UPDATE"
                    ).fetchone()
                    is not None
                )
                # Hold the owning Runtime lifecycle lock through the actual PostgreSQL COMMIT.
                # Shared proof and external release/retirement cannot interleave at the handoff boundary.
                with self._runtime.hold_work_binding_evidence(operation.reserved_run_id.value) as binding:
                    frozen.runtime_binding_reference.verifies(binding, require_active=True)
                    only_require_chart_calculation_new_admission(self._runtime, operation, frozen)
                    removed = connection.execute(
                        "DELETE FROM research_run_id_reservation WHERE run_id = %s AND owner_id = %s "
                        "AND owner_kind = 'CHART_CALCULATION' AND reserved_at = %s AND schema_version = 1",
                        (operation.reserved_run_id.value, operation.operation_id.value, operation.accepted_at),
                    )
                    _require(removed.rowcount == 1)
                    connection.execute(_insert_run_query(), OnlyPostgresResearchRunStore._values(expected))
                    connection.execute(
                        "INSERT INTO chart_calculation_run_admission "
                        "(operation_id, run_id, compilation_fingerprint, queued_at, schema_version) VALUES (%s,%s,%s,%s,1)",
                        (
                            operation.operation_id.value,
                            expected.run_id.value,
                            frozen.compilation_fingerprint,
                            queued_at,
                        ),
                    )
                    _require(only_verify_chart_run_consumption_in_transaction(connection, operation) == expected)
                    connection.commit()
        except psycopg.Error as exc:
            # Never release/rebind Runtime work or blindly retry after unknown acknowledgement.
            existing = self.load_verified(operation)
            if (
                existing is not None
                and existing.admission_resolution_fingerprint == compilation.compilation_fingerprint
            ):
                return existing
            raise OnlyProductCommandAuthorityUnavailableError(operation.operation_id.value) from exc
        # Success is a durable, post-commit read, not merely a clean transaction-context exit.
        verified = self.load_verified(operation)
        _require(verified is not None, "CHART_RUN_ADMISSION_COMMIT_UNKNOWN")
        assert verified is not None
        _require(verified.admission_resolution_fingerprint == compilation.compilation_fingerprint, _CONFLICT)
        return verified
