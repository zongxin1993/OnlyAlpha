"""Internal exact-host diagnostic execution; no Run or publication mutation authority."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from threading import Event
from typing import Protocol, cast
from weakref import WeakValueDictionary

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.application.chart_calculation import OnlyChartCalculationError
from onlyalpha.application.chart_calculation_compilation import (
    OnlyChartCalculationCompilationV1,
    OnlyChartCalculationInputVerifier,
    _verified_ready_pin,
)
from onlyalpha.application.chart_calculation_compilation_ports import (
    OnlyChartCalculationCompilationStore,
    OnlyChartCalculationPreparationReader,
)
from onlyalpha.application.chart_calculation_ports import OnlyChartCalculationAdmissionStore
from onlyalpha.application.chart_calculation_run_admission import (
    OnlyChartCalculationRunAdmissionStore,
    only_require_chart_calculation_new_admission,
    only_verify_chart_calculation_run,
)
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.runtime_generation import OnlyRuntimeGenerationWorkAuthority
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.calculation.execution import _immutable_arrow_array, _validate_outputs
from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationContract
from onlyalpha.research.calculation.readiness import (
    OnlyResearchOutputReadiness,
    only_validate_research_output_readiness,
)
from onlyalpha.research.calculation.result_identity import (
    only_research_calculation_arrow_schema,
    only_research_calculation_arrow_schema_payload,
)
from onlyalpha.research.dataset.lineage import OnlyDatasetMaterializationStore
from onlyalpha.research.dataset.ports import OnlyBoundedResearchDatasetSnapshotStore, OnlyVerifiedResearchDataset
from onlyalpha.research.dataset.strict import require_exact_fields, require_int, require_mapping, require_str
from onlyalpha.research.run.model import OnlyResearchRunState

CHART_CALCULATION_EXECUTION_MAX_ROWS = 100_000
CHART_CALCULATION_EXECUTION_MAX_BYTES = 64 * 1024 * 1024
_CONTEXT = "Chart Calculation execution"


def _require(condition: bool, code: str = "CHART_EXECUTION_PROJECTION_INVALID") -> None:
    if not condition:
        raise OnlyChartCalculationError(code)


def only_require_chart_execution_not_cancelled(cancellation: Event | None) -> None:
    _require(cancellation is None or not cancellation.is_set(), "CHART_EXECUTION_CANCELLED")


@dataclass(frozen=True, slots=True)
class OnlyChartCalculationExecutionRequestV1:
    """Structural wire request, not an execution capability or caller authoring API."""

    compilation_json: str
    instrument_id: str
    timestamps: tuple[int, ...]
    dataset_store_root: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        import json

        _require(type(self.schema_version) is int and self.schema_version == 1)
        _require(type(self.compilation_json) is str)
        frozen = OnlyChartCalculationCompilationV1.from_dict(json.loads(self.compilation_json))
        _require(only_canonical_json(frozen.to_dict()) == self.compilation_json)
        _require(type(self.instrument_id) is str and bool(self.instrument_id.strip()))
        _require(type(self.dataset_store_root) is str and bool(self.dataset_store_root.strip()))
        _require(type(self.timestamps) is tuple and 0 < len(self.timestamps) <= CHART_CALCULATION_EXECUTION_MAX_ROWS)
        _require(all(type(item) is int and -(2**63) <= item < 2**63 for item in self.timestamps))
        _require(self.timestamps == tuple(sorted(set(self.timestamps))))

    @property
    def compilation(self) -> OnlyChartCalculationCompilationV1:
        import json

        return OnlyChartCalculationCompilationV1.from_dict(json.loads(self.compilation_json))

    @property
    def request_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "compilation": self.compilation.to_dict(),
            "instrument_id": self.instrument_id,
            "timestamps": list(self.timestamps),
            "dataset_store_root": self.dataset_store_root,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> OnlyChartCalculationExecutionRequestV1:
        raw = require_mapping(raw, _CONTEXT)
        require_exact_fields(
            raw, {"schema_version", "compilation", "instrument_id", "timestamps", "dataset_store_root"}, _CONTEXT
        )
        axis = raw["timestamps"]
        _require(type(axis) is list and all(type(item) is int for item in axis))
        return cls(
            only_canonical_json(
                OnlyChartCalculationCompilationV1.from_dict(require_mapping(raw["compilation"], _CONTEXT)).to_dict()
            ),
            require_str(raw, "instrument_id", _CONTEXT),
            tuple(cast(list[int], axis)),
            require_str(raw, "dataset_store_root", _CONTEXT),
            require_int(raw, "schema_version", _CONTEXT),
        )

    def projection_context(self) -> dict[str, object]:
        frozen = self.compilation
        assert frozen.resolution.job_plan.publication is not None
        return {
            "schema_version": 1,
            "status": "EXECUTED_UNPUBLISHED",
            "request_fingerprint": self.request_fingerprint,
            "run_id": frozen.runtime_work_id,
            "operation_id": frozen.operation_id.value,
            "compilation_fingerprint": frozen.compilation_fingerprint,
            "runtime_generation_fingerprint": frozen.runtime_generation_fingerprint,
            "dataset_snapshot_fingerprint": frozen.dataset_snapshot_fingerprint,
            "dataset_materialization_id": frozen.dataset_materialization_id,
            "input_selection_fingerprint": frozen.input_selection_fingerprint,
            "graph_fingerprint": frozen.graph_fingerprint,
            "calculation_fingerprint": frozen.calculation_fingerprint,
            "implementation_fingerprint": frozen.implementation_fingerprint,
            "node_fingerprint": frozen.resolution.calculation_graph.nodes[0].fingerprint,
            "instrument_id": self.instrument_id,
            "publication": frozen.resolution.job_plan.publication.to_dict(),
        }


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _OnlyIssuedChartCalculationExecutionRequest:
    request: OnlyChartCalculationExecutionRequestV1
    validate_dispatch: Callable[[], None]
    hold_dispatch: Callable[[], AbstractContextManager[None]]


_ISSUED: WeakValueDictionary[int, _OnlyIssuedChartCalculationExecutionRequest] = WeakValueDictionary()


def _only_require_chart_execution_request(value: object) -> OnlyChartCalculationExecutionRequestV1:
    _require(
        type(value) is _OnlyIssuedChartCalculationExecutionRequest and _ISSUED.get(id(value)) is value,
        "CHART_EXECUTION_UNAUTHORIZED",
    )
    assert isinstance(value, _OnlyIssuedChartCalculationExecutionRequest)
    return value.request


def _only_consume_chart_execution_request(value: object) -> OnlyChartCalculationExecutionRequestV1:
    request = _only_require_chart_execution_request(value)
    _require(_ISSUED.pop(id(value), None) is value, "CHART_EXECUTION_UNAUTHORIZED")
    return request


@dataclass(frozen=True, slots=True)
class OnlyChartCalculationExecutionProjectionV1:
    """Read-only diagnostic, explicitly incapable of satisfying native publication seals."""

    request: OnlyChartCalculationExecutionRequestV1
    values: pa.Table
    readiness: pa.Table

    def __post_init__(self) -> None:
        _require(type(self.request) is OnlyChartCalculationExecutionRequestV1)
        self.request.__post_init__()
        node = self.request.compilation.resolution.calculation_graph.nodes[0]
        _require(isinstance(self.values, pa.Table) and isinstance(self.readiness, pa.Table))
        _require(self.values.nbytes + self.readiness.nbytes <= CHART_CALCULATION_EXECUTION_MAX_BYTES)
        for name in ("values", "readiness"):
            table = getattr(self, name)
            if any(
                buffer is not None and buffer.is_mutable
                for column in table.columns
                for chunk in column.chunks
                for buffer in chunk.buffers()
            ):
                object.__setattr__(
                    self,
                    name,
                    pa.Table.from_arrays(
                        [_immutable_arrow_array(column) for column in table.columns],
                        schema=table.schema,
                    ),
                )
        _require(
            self.values.column_names == ["ts_event_ns", *sorted(output.name for output in node.definition.outputs)]
        )
        _require(self.values.column("ts_event_ns").type == pa.int64())
        _require(tuple(self.values.column("ts_event_ns").to_pylist()) == self.request.timestamps)
        outputs = {output.name: self.values.column(output.name) for output in node.definition.outputs}
        _validate_outputs(node.definition, outputs, len(self.request.timestamps))
        schema = pa.schema(
            [
                pa.field("ts_event_ns", pa.int64(), nullable=False),
                pa.field("output_name", pa.string(), nullable=False),
                pa.field("readiness", pa.string(), nullable=False),
                pa.field("reason", pa.string(), nullable=False),
            ]
        )
        _require(self.readiness.schema == schema)
        names = sorted(outputs)
        count = len(self.request.timestamps)
        _require(self.readiness.num_rows == count * len(names))
        evidence = {}
        for index, name in enumerate(names):
            section = self.readiness.slice(index * count, count)
            _require(tuple(section.column("ts_event_ns").to_pylist()) == self.request.timestamps)
            _require(section.column("output_name").to_pylist() == [name] * count)
            evidence[name] = OnlyResearchOutputReadiness(section.column("readiness"), section.column("reason"))
        only_validate_research_output_readiness(node.definition, outputs, evidence, row_count=count)

    @property
    def status(self) -> str:
        return "EXECUTED_UNPUBLISHED"

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        return self.request.projection_context() | {
            "values": _encode_table(self.values),
            "readiness": _encode_table(self.readiness),
        }

    @classmethod
    def from_dict(
        cls, raw: Mapping[str, object], *, request: OnlyChartCalculationExecutionRequestV1
    ) -> OnlyChartCalculationExecutionProjectionV1:
        raw = require_mapping(raw, _CONTEXT)
        context = request.projection_context()
        require_exact_fields(raw, set(context) | {"values", "readiness"}, _CONTEXT)
        _require(type(raw["schema_version"]) is int)
        OnlyResearchCalculationPublicationContract.from_dict(require_mapping(raw["publication"], _CONTEXT))
        _require({name: raw[name] for name in context} == context)
        values = _decode_table(raw["values"])
        readiness = _decode_table(raw["readiness"], byte_budget=CHART_CALCULATION_EXECUTION_MAX_BYTES - values.nbytes)
        return cls(request, values, readiness)


def _encode_table(table: pa.Table) -> dict[str, object]:
    from decimal import Decimal

    return {
        "schema": list(only_research_calculation_arrow_schema_payload(table.schema)),
        "rows": [
            [str(value) if isinstance(value, Decimal) else value for value in row]
            for row in zip(*(column.to_pylist() for column in table.columns), strict=True)
        ],
    }


def _decode_table(raw: object, *, byte_budget: int | None = None) -> pa.Table:
    from decimal import Decimal

    raw = require_mapping(raw, _CONTEXT)
    budget = CHART_CALCULATION_EXECUTION_MAX_BYTES if byte_budget is None else byte_budget
    _require(type(budget) is int and 0 <= budget <= CHART_CALCULATION_EXECUTION_MAX_BYTES)
    require_exact_fields(raw, {"schema", "rows"}, _CONTEXT)
    fields, rows = raw["schema"], raw["rows"]
    _require(type(fields) is list and 0 < len(fields) <= 16)
    _require(type(rows) is list and len(rows) <= CHART_CALCULATION_EXECUTION_MAX_ROWS)
    assert isinstance(fields, list) and isinstance(rows, list)
    descriptors = []
    for item in fields:
        item = require_mapping(item, _CONTEXT)
        require_exact_fields(item, {"name", "data_type", "nullable"}, _CONTEXT)
        _require(type(item["name"]) is str and 0 < len(item["name"]) <= 64 and type(item["nullable"]) is bool)
        descriptors.append(dict(item))
    schema = only_research_calculation_arrow_schema(tuple(descriptors))
    _require(len(set(schema.names)) == len(schema))
    columns: list[list[object]] = [[] for _ in schema]
    # Null fixed-width cells still allocate value slots. Include validity bitmaps
    # and terminal string offsets before checking individual cell values.
    size = ((len(rows) + 7) // 8) * len(schema) + 4 * sum(pa.types.is_string(field.type) for field in schema)
    _require(size <= budget, "CHART_EXECUTION_RESOURCE_LIMIT")
    for row in rows:
        _require(type(row) is list and len(row) == len(schema))
        for index, (value, field) in enumerate(zip(row, schema, strict=True)):
            if pa.types.is_decimal(field.type) or pa.types.is_integer(field.type):
                size += field.type.bit_width // 8
            elif pa.types.is_string(field.type):
                size += 4
            elif pa.types.is_boolean(field.type):
                size += 1  # Conservative whole-byte bound for bit-packed values.
            else:
                _require(False)
            if value is not None:
                if pa.types.is_decimal(field.type):
                    _require(type(value) is str and len(value) <= 128)
                    value = Decimal(value)
                    _require(value.is_finite())
                elif pa.types.is_integer(field.type):
                    _require(type(value) is int)
                elif pa.types.is_string(field.type):
                    _require(type(value) is str and len(value) <= 128)
                    size += len(value.encode("utf-8"))
                elif pa.types.is_boolean(field.type):
                    _require(type(value) is bool)
                else:
                    _require(False)
            _require(size <= budget, "CHART_EXECUTION_RESOURCE_LIMIT")
            columns[index].append(value)
    try:
        table = pa.Table.from_arrays(
            [
                _immutable_arrow_array(pa.array(column, type=field.type))
                for column, field in zip(columns, schema, strict=True)
            ],
            schema=schema,
        )
        _require(table.nbytes <= budget, "CHART_EXECUTION_RESOURCE_LIMIT")
        _require(_encode_table(table) == raw)
        return table
    except (ValueError, pa.ArrowException) as exc:
        raise OnlyChartCalculationError("CHART_EXECUTION_PROJECTION_INVALID") from exc


class OnlyChartCalculationExecutionHost(Protocol):
    def execute_chart_calculation(
        self, capability: object, *, cancellation: Event | None = None
    ) -> OnlyChartCalculationExecutionProjectionV1: ...


class OnlyChartCalculationExecutionService:
    def __init__(
        self,
        *,
        operations: OnlyChartCalculationAdmissionStore,
        preparations: OnlyChartCalculationPreparationReader,
        compilations: OnlyChartCalculationCompilationStore,
        datasets: OnlyBoundedResearchDatasetSnapshotStore,
        materializations: OnlyDatasetMaterializationStore,
        runtime_generations: OnlyRuntimeGenerationWorkAuthority,
        runs: OnlyChartCalculationRunAdmissionStore,
        host: OnlyChartCalculationExecutionHost,
        dataset_store_root: str,
    ) -> None:
        self._operations, self._preparations, self._compilations = operations, preparations, compilations
        self._datasets = datasets.bounded(CHART_CALCULATION_EXECUTION_MAX_ROWS, CHART_CALCULATION_EXECUTION_MAX_BYTES)
        self._runtime, self._runs, self._host = runtime_generations, runs, host
        self._dataset_store_root = dataset_store_root
        self._inputs = OnlyChartCalculationInputVerifier(
            datasets=self._datasets, materializations=materializations, runtime_generations=runtime_generations
        )

    def _load(
        self, operation_id: OnlyProductCommandId
    ) -> tuple[OnlyChartCalculationCompilationV1, OnlyVerifiedResearchDataset]:
        operation = self._operations.load_verified(operation_id)
        _require(operation is not None, "CHART_EXECUTION_OPERATION_NOT_FOUND")
        assert operation is not None
        _require(operation.operation_id == operation_id)
        preparation = self._preparations.load_verified(operation)
        _verified_ready_pin(operation, preparation)
        assert preparation is not None
        frozen = self._compilations.load_verified(operation)
        _require(type(frozen) is OnlyChartCalculationCompilationV1, "CHART_COMPILATION_NOT_READY")
        assert frozen is not None
        verified = self._inputs.verify_frozen(operation, preparation, frozen)
        _require(
            0 < verified.snapshot.row_count <= CHART_CALCULATION_EXECUTION_MAX_ROWS, "CHART_EXECUTION_RESOURCE_LIMIT"
        )
        run = self._runs.load_verified(operation)
        _require(run is not None, "CHART_EXECUTION_RUN_NOT_FOUND")
        assert run is not None
        only_verify_chart_calculation_run(run, frozen)
        _require(run.state is OnlyResearchRunState.QUEUED, "CHART_EXECUTION_RUN_NOT_QUEUED")
        only_require_chart_calculation_new_admission(self._runtime, operation, frozen)
        return frozen, verified

    def execute(
        self, operation_id: OnlyProductCommandId, *, cancellation: Event | None = None
    ) -> OnlyChartCalculationExecutionProjectionV1:
        only_require_chart_execution_not_cancelled(cancellation)
        frozen, verified = self._load(operation_id)
        _require(verified.table.nbytes <= CHART_CALCULATION_EXECUTION_MAX_BYTES, "CHART_EXECUTION_RESOURCE_LIMIT")
        _require(len(verified.snapshot.definition.instruments) == 1)
        instrument = str(verified.snapshot.definition.instruments[0])
        _require(set(verified.table.column("instrument_id").to_pylist()) == {instrument})
        request = OnlyChartCalculationExecutionRequestV1(
            only_canonical_json(frozen.to_dict()),
            instrument,
            tuple(verified.table.column("ts_event_ns").to_pylist()),
            self._dataset_store_root,
        )

        def validate_dispatch() -> None:
            _require(self._load(operation_id)[0] == frozen, "CHART_EXECUTION_FROZEN_RELATION_CHANGED")
            only_require_chart_execution_not_cancelled(cancellation)

        @contextmanager
        def hold_dispatch() -> Iterator[None]:
            operation = self._operations.load_verified(operation_id)
            _require(operation is not None, "CHART_EXECUTION_OPERATION_NOT_FOUND")
            assert operation is not None
            with self._runtime.hold_work_binding_evidence(frozen.runtime_work_id) as binding:
                frozen.runtime_binding_reference.verifies(binding, require_active=True)
                only_require_chart_calculation_new_admission(self._runtime, operation, frozen)
                with self._runs.hold_queued_run(operation, frozen) as run:
                    only_verify_chart_calculation_run(run, frozen)
                    _require(run.state is OnlyResearchRunState.QUEUED, "CHART_EXECUTION_RUN_NOT_QUEUED")
                    only_require_chart_execution_not_cancelled(cancellation)
                    yield

        capability = _OnlyIssuedChartCalculationExecutionRequest(request, validate_dispatch, hold_dispatch)
        _ISSUED[id(capability)] = capability
        try:
            only_require_chart_execution_not_cancelled(cancellation)
            projection = self._host.execute_chart_calculation(capability, cancellation=cancellation)
            _require(type(projection) is OnlyChartCalculationExecutionProjectionV1)
            _require(projection.request == request)
            projection.__post_init__()
            _require(self._load(operation_id)[0] == frozen, "CHART_EXECUTION_FROZEN_RELATION_CHANGED")
            only_require_chart_execution_not_cancelled(cancellation)
            return projection
        finally:
            _ISSUED.pop(id(capability), None)
