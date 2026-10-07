"""Append-only preparation facts; short PostgreSQL transactions own lease and fence."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from typing import cast

import psycopg
from psycopg.rows import dict_row

from onlyalpha.application.chart_calculation import OnlyChartCalculationError, OnlyChartCalculationOperationV1
from onlyalpha.application.chart_calculation_preparation import (
    OnlyChartCalculationInputPinV1,
    OnlyChartCalculationPreparationV1,
    OnlyChartCalculationRuntimeBindingReferenceV1,
)
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.runtime_generation import OnlyRuntimeWorkAdmissionClosureEvidence
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json

from .chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore
from .config import OnlyPostgresOperationalConnectionOptions
from .product_command_authority import OnlyPostgresProductCommandAuthority


def _require(condition: bool, code: str = "CHART_PREPARATION_RELATION_CORRUPT") -> None:
    if not condition:
        raise OnlyChartCalculationError(code)


def _payload(value: OnlyChartCalculationPreparationV1) -> dict[str, object]:
    result: dict[str, object] = {
        "operation_id": value.operation_id.value,
        "revision": value.revision,
        "fence": value.fence,
        "worker_id": value.worker_id.value,
        "lease_until": value.lease_until.isoformat(),
        "runtime_generation_fingerprint": value.runtime_generation_fingerprint,
        "runtime_work_id": value.runtime_work_id,
        "state": value.state,
        "input_pin": None if value.input_pin is None else value.input_pin.to_dict(),
        "input_selection_fingerprint": value.input_selection_fingerprint,
        "dataset_snapshot_fingerprint": value.dataset_snapshot_fingerprint,
        "dataset_materialization_id": value.dataset_materialization_id,
        "failure_code": value.failure_code,
    }
    if value.fact_schema_version == 2:
        result.update(
            runtime_binding_reference=None
            if value.runtime_binding_reference is None
            else value.runtime_binding_reference.to_dict(),
            runtime_closure_reference=None
            if value.runtime_closure_reference is None
            else value.runtime_closure_reference.to_dict(),
            failure_decision=value.failure_decision,
        )
    return result


def _decode(raw: dict[str, object], version: int) -> OnlyChartCalculationPreparationV1:
    pin = raw["input_pin"]
    return OnlyChartCalculationPreparationV1(
        OnlyProductCommandId(cast(str, raw["operation_id"])),
        cast(int, raw["revision"]),
        cast(int, raw["fence"]),
        OnlyProductCommandId(cast(str, raw["worker_id"])),
        datetime.fromisoformat(cast(str, raw["lease_until"])),
        cast(str, raw["runtime_generation_fingerprint"]),
        cast(str, raw["runtime_work_id"]),
        cast(str, raw["state"]),
        None if pin is None else OnlyChartCalculationInputPinV1(only_canonical_json(pin)),
        cast(str | None, raw["dataset_snapshot_fingerprint"]),
        cast(str | None, raw["dataset_materialization_id"]),
        cast(str | None, raw["failure_code"]),
        None
        if version == 1 or raw["runtime_binding_reference"] is None
        else OnlyChartCalculationRuntimeBindingReferenceV1.from_dict(
            cast(dict[str, object], raw["runtime_binding_reference"])
        ),
        None
        if version == 1 or raw["runtime_closure_reference"] is None
        else OnlyRuntimeWorkAdmissionClosureEvidence.from_dict(
            cast(dict[str, object], raw["runtime_closure_reference"])
        ),
        None if version == 1 else cast(str | None, raw["failure_decision"]),
        version,
    )


class OnlyPostgresChartCalculationPreparationStore:
    def __init__(self, dsn: str, options: OnlyPostgresOperationalConnectionOptions | None = None) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

    @staticmethod
    def _now(connection: psycopg.Connection[dict[str, object]]) -> datetime:
        row = connection.execute("SELECT clock_timestamp() AS now").fetchone()
        assert row is not None
        return cast(datetime, row["now"])

    @staticmethod
    def _lock(connection: psycopg.Connection[dict[str, object]], operation: OnlyChartCalculationOperationV1) -> None:
        OnlyPostgresProductCommandAuthority.lock_command(connection, operation.operation_id)
        _require(OnlyPostgresChartCalculationAdmissionStore._load(connection, operation.operation_id) == operation)

    @staticmethod
    def _load(
        connection: psycopg.Connection[dict[str, object]], operation: OnlyChartCalculationOperationV1
    ) -> tuple[OnlyChartCalculationPreparationV1 | None, str | None]:
        rows = connection.execute(
            "SELECT * FROM chart_calculation_preparation_fact WHERE operation_id = %s ORDER BY revision",
            (operation.operation_id.value,),
        ).fetchall()
        current = None
        previous_hash = None
        try:
            for index, row in enumerate(rows, 1):
                body = json.loads(cast(str, row["fact_json"]))
                _require(set(body) == {"schema_version", "previous_fingerprint", "kind", "preparation"})
                _require(type(body["schema_version"]) is int and body["schema_version"] in {1, 2})
                _require(body["previous_fingerprint"] == previous_hash and body["kind"] == row["kind"])
                _require(
                    only_canonical_json(body) == row["fact_json"]
                    and only_canonical_fingerprint(body) == row["fact_fingerprint"]
                )
                value = _decode(body["preparation"], body["schema_version"])
                _require(_payload(value) == body["preparation"])
                _require(
                    value.operation_id == operation.operation_id
                    and value.revision == row["revision"] == index
                    and value.fence == row["fence"]
                    and value.runtime_work_id == operation.reserved_run_id.value
                )
                _require(
                    len(value.runtime_generation_fingerprint) == 64
                    and all(c in "0123456789abcdef" for c in value.runtime_generation_fingerprint)
                )
                if value.input_pin is not None:
                    value.input_pin.verify_operation(operation, value.runtime_generation_fingerprint)
                if current is None:
                    _require(
                        body["kind"] == "CLAIM"
                        and value.revision == value.fence == 1
                        and value.state == "MATERIALIZING_INPUT"
                        and value.input_pin is None
                        and value.runtime_binding_reference is None
                        and value.runtime_closure_reference is None
                        and value.failure_decision is None
                    )
                else:
                    _require(current.state == "MATERIALIZING_INPUT")
                    _require(value.fact_schema_version >= current.fact_schema_version)
                    current = replace(current, fact_schema_version=value.fact_schema_version)
                    _require(value.runtime_generation_fingerprint == current.runtime_generation_fingerprint)
                    kind = body["kind"]
                    if kind == "CLAIM":
                        _require(
                            value
                            == replace(
                                current,
                                revision=index,
                                fence=current.fence + 1,
                                worker_id=value.worker_id,
                                lease_until=value.lease_until,
                            )
                        )
                        _require(value.lease_until > current.lease_until)
                    elif kind == "HEARTBEAT":
                        _require(
                            value == replace(current, revision=index, lease_until=value.lease_until)
                            and value.lease_until >= current.lease_until
                        )
                    elif kind == "RUNTIME_BOUND":
                        _require(
                            current.failure_decision is None
                            and current.runtime_binding_reference is None
                            and value.runtime_binding_reference is not None
                            and value
                            == replace(
                                current, revision=index, runtime_binding_reference=value.runtime_binding_reference
                            )
                        )
                    elif kind == "FAILURE_DECIDED":
                        _require(
                            current.failure_decision is None
                            and value.failure_decision is not None
                            and value == replace(current, revision=index, failure_decision=value.failure_decision)
                        )
                    elif kind == "PIN":
                        _require(
                            current.failure_decision is None
                            and current.input_pin is None
                            and value.input_pin is not None
                            and value == replace(current, revision=index, input_pin=value.input_pin)
                        )
                    elif kind == "INPUT_READY":
                        _require(
                            current.failure_decision is None
                            and current.input_pin is not None
                            and value.state == "INPUT_READY"
                            and value
                            == replace(
                                current,
                                revision=index,
                                state="INPUT_READY",
                                dataset_snapshot_fingerprint=value.dataset_snapshot_fingerprint,
                                dataset_materialization_id=value.dataset_materialization_id,
                            )
                        )
                    elif kind == "FAILED":
                        _require(
                            value.state == "FAILED"
                            and value
                            == replace(
                                current,
                                revision=index,
                                state="FAILED",
                                failure_code=value.failure_code,
                                runtime_closure_reference=value.runtime_closure_reference,
                            )
                        )
                    else:
                        _require(False)
                current, previous_hash = value, cast(str, row["fact_fingerprint"])
            return current, previous_hash
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise OnlyChartCalculationError("CHART_PREPARATION_RELATION_CORRUPT") from exc

    @staticmethod
    def _append(
        connection: psycopg.Connection[dict[str, object]],
        value: OnlyChartCalculationPreparationV1,
        kind: str,
        previous_hash: str | None,
    ) -> OnlyChartCalculationPreparationV1:
        body = {
            "schema_version": value.fact_schema_version,
            "previous_fingerprint": previous_hash,
            "kind": kind,
            "preparation": _payload(value),
        }
        connection.execute(
            "INSERT INTO chart_calculation_preparation_fact (operation_id, revision, fence, kind, fact_json, fact_fingerprint) VALUES (%s,%s,%s,%s,%s,%s)",
            (
                value.operation_id.value,
                value.revision,
                value.fence,
                kind,
                only_canonical_json(body),
                only_canonical_fingerprint(body),
            ),
        )
        return value

    def load_verified(self, operation: OnlyChartCalculationOperationV1) -> OnlyChartCalculationPreparationV1 | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            self._lock(connection, operation)
            return self._load(connection, operation)[0]

    @staticmethod
    def load_verified_in_transaction(
        connection: psycopg.Connection[dict[str, object]], operation: OnlyChartCalculationOperationV1
    ) -> OnlyChartCalculationPreparationV1 | None:
        """Verify T1 and the complete preparation chain inside the caller transaction."""
        OnlyPostgresChartCalculationPreparationStore._lock(connection, operation)
        return OnlyPostgresChartCalculationPreparationStore._load(connection, operation)[0]

    def claim(
        self,
        operation: OnlyChartCalculationOperationV1,
        worker_id: OnlyProductCommandId,
        generation: str,
        *,
        lease_duration: timedelta,
    ) -> OnlyChartCalculationPreparationV1:
        _require(timedelta(0) < lease_duration <= timedelta(minutes=2), "CHART_PREPARATION_LEASE_INVALID")
        _require(
            len(generation) == 64 and all(c in "0123456789abcdef" for c in generation),
            "CHART_EXECUTION_GENERATION_UNAVAILABLE",
        )
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            self._lock(connection, operation)
            current, previous_hash = self._load(connection, operation)
            now = self._now(connection)
            if current is None:
                value = OnlyChartCalculationPreparationV1(
                    operation.operation_id,
                    1,
                    1,
                    worker_id,
                    now + lease_duration,
                    generation,
                    operation.reserved_run_id.value,
                )
            else:
                _require(current.runtime_generation_fingerprint == generation, "CHART_EXECUTION_GENERATION_UNAVAILABLE")
                if current.state != "MATERIALIZING_INPUT":
                    return current
                if current.lease_until > now:
                    _require(current.worker_id == worker_id, "CHART_PREPARATION_BUSY")
                    return current
                value = replace(
                    current,
                    revision=current.revision + 1,
                    fence=current.fence + 1,
                    worker_id=worker_id,
                    lease_until=now + lease_duration,
                    fact_schema_version=2,
                )
            return self._append(connection, value, "CLAIM", previous_hash)

    def _progress(
        self,
        operation: OnlyChartCalculationOperationV1,
        claim: OnlyChartCalculationPreparationV1,
        kind: str,
        *,
        pin: OnlyChartCalculationInputPinV1 | None = None,
        snapshot_fingerprint: str | None = None,
        materialization_id: str | None = None,
        code: str | None = None,
        lease_duration: timedelta | None = None,
        binding_reference: OnlyChartCalculationRuntimeBindingReferenceV1 | None = None,
        closure_reference: OnlyRuntimeWorkAdmissionClosureEvidence | None = None,
    ) -> OnlyChartCalculationPreparationV1:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            self._lock(connection, operation)
            current, previous_hash = self._load(connection, operation)
            _require(current is not None, "CHART_PREPARATION_FENCE_LOST")
            assert current is not None
            _require(
                current.fence == claim.fence
                and current.worker_id == claim.worker_id
                and current.runtime_generation_fingerprint == claim.runtime_generation_fingerprint
                and current.state == "MATERIALIZING_INPUT"
                and current.lease_until > self._now(connection),
                "CHART_PREPARATION_FENCE_LOST",
            )
            value = replace(current, revision=current.revision + 1, fact_schema_version=2)
            if kind in {"PIN", "INPUT_READY", "RUNTIME_BOUND"}:
                _require(current.failure_decision is None)
            if kind == "RUNTIME_BOUND":
                assert binding_reference is not None
                _require(
                    binding_reference.work_id == current.runtime_work_id
                    and binding_reference.runtime_generation_fingerprint == current.runtime_generation_fingerprint
                )
                if current.runtime_binding_reference is not None:
                    _require(current.runtime_binding_reference == binding_reference, "CHART_RUNTIME_BINDING_CONFLICT")
                    return current
                value = replace(value, runtime_binding_reference=binding_reference)
            elif kind == "FAILURE_DECIDED":
                _require(code is not None)
                if current.failure_decision is not None:
                    _require(current.failure_decision == code)
                    return current
                value = replace(value, failure_decision=code)
            elif kind == "PIN":
                assert pin is not None
                _require(current.runtime_binding_reference is not None)
                pin.verify_operation(operation, current.runtime_generation_fingerprint)
                if current.input_pin is not None:
                    _require(current.input_pin == pin, "CHART_INPUT_PIN_CONFLICT")
                    return current
                value = replace(value, input_pin=pin)
            elif kind == "HEARTBEAT":
                assert lease_duration is not None
                _require(timedelta(0) < lease_duration <= timedelta(minutes=2), "CHART_PREPARATION_LEASE_INVALID")
                value = replace(value, lease_until=max(current.lease_until, self._now(connection) + lease_duration))
            elif kind == "INPUT_READY":
                _require(current.runtime_binding_reference is not None)
                _require(current.input_pin is not None and current.input_pin == claim.input_pin)
                _require(
                    snapshot_fingerprint is not None
                    and len(snapshot_fingerprint) == 64
                    and all(c in "0123456789abcdef" for c in snapshot_fingerprint)
                )
                _require(
                    materialization_id is not None
                    and materialization_id.startswith("dataset-materialization:")
                    and len(materialization_id) == 88
                )
                value = replace(
                    value,
                    state="INPUT_READY",
                    dataset_snapshot_fingerprint=snapshot_fingerprint,
                    dataset_materialization_id=materialization_id,
                )
            else:
                _require(kind == "FAILED" and code is not None and code.startswith("CHART_"))
                _require(current.failure_decision == code and closure_reference is not None)
                value = replace(value, state="FAILED", failure_code=code, runtime_closure_reference=closure_reference)
            return self._append(connection, value, kind, previous_hash)

    def heartbeat(
        self,
        operation: OnlyChartCalculationOperationV1,
        claim: OnlyChartCalculationPreparationV1,
        *,
        lease_duration: timedelta,
    ) -> OnlyChartCalculationPreparationV1:
        return self._progress(operation, claim, "HEARTBEAT", lease_duration=lease_duration)

    def commit_pin(
        self,
        operation: OnlyChartCalculationOperationV1,
        claim: OnlyChartCalculationPreparationV1,
        pin: OnlyChartCalculationInputPinV1,
    ) -> OnlyChartCalculationPreparationV1:
        return self._progress(operation, claim, "PIN", pin=pin)

    def input_ready(
        self,
        operation: OnlyChartCalculationOperationV1,
        claim: OnlyChartCalculationPreparationV1,
        *,
        snapshot_fingerprint: str,
        materialization_id: str,
    ) -> OnlyChartCalculationPreparationV1:
        return self._progress(
            operation,
            claim,
            "INPUT_READY",
            snapshot_fingerprint=snapshot_fingerprint,
            materialization_id=materialization_id,
        )

    def fail(
        self,
        operation: OnlyChartCalculationOperationV1,
        claim: OnlyChartCalculationPreparationV1,
        code: str,
        *,
        closure_reference: OnlyRuntimeWorkAdmissionClosureEvidence,
    ) -> OnlyChartCalculationPreparationV1:
        return self._progress(operation, claim, "FAILED", code=code, closure_reference=closure_reference)

    def begin_failure(
        self, operation: OnlyChartCalculationOperationV1, claim: OnlyChartCalculationPreparationV1, code: str
    ) -> OnlyChartCalculationPreparationV1:
        return self._progress(operation, claim, "FAILURE_DECIDED", code=code)

    def commit_runtime_binding(
        self,
        operation: OnlyChartCalculationOperationV1,
        claim: OnlyChartCalculationPreparationV1,
        reference: OnlyChartCalculationRuntimeBindingReferenceV1,
    ) -> OnlyChartCalculationPreparationV1:
        return self._progress(operation, claim, "RUNTIME_BOUND", binding_reference=reference)
