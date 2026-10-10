"""Internal execution acceptance; fixtures are not customer calculation evidence."""

from contextlib import nullcontext
from dataclasses import replace
from threading import Event
from unittest.mock import Mock

import pytest

from onlyalpha.application.chart_calculation import OnlyChartCalculationError
from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationService
from onlyalpha.application.chart_calculation_run_admission import only_chart_calculation_queued_run
from tests.application.test_chart_calculation_admission import NOW
from tests.support.chart_calculation_compilation import prepared_input

pytestmark = pytest.mark.contract


def execution_system(tmp_path):
    from onlyalpha.application.chart_calculation_execution import OnlyChartCalculationExecutionService

    chart = prepared_input(tmp_path)
    compilation = OnlyChartCalculationCompilationService(
        preparations=chart.preparations,
        datasets=chart.dataset,
        materializations=chart.dataset,
        runtime_generations=chart.runtime,
        resolver=chart.resolver,
        compilations=chart.compilations,
    ).compile(chart.operation)
    chart.compilations.load_verified.return_value = compilation
    chart.compilation = compilation
    chart.operations = Mock()
    chart.operations.load_verified.return_value = chart.operation
    chart.runs = Mock()
    chart.run = only_chart_calculation_queued_run(compilation, queued_at=NOW)
    chart.runs.load_verified.return_value = chart.run
    chart.runs.hold_queued_run.side_effect = lambda *args: nullcontext(chart.runs.load_verified.return_value)
    chart.host = Mock()
    chart.execution = OnlyChartCalculationExecutionService(
        operations=chart.operations,
        preparations=chart.preparations,
        compilations=chart.compilations,
        datasets=chart.dataset,
        materializations=chart.dataset,
        runtime_generations=chart.runtime,
        runs=chart.runs,
        host=chart.host,
        dataset_store_root=str(tmp_path / "dataset"),
    )
    return chart


@pytest.mark.parametrize("missing", ["operation", "preparation", "compilation", "run"])
def test_missing_owning_fact_rejects_before_host(tmp_path, missing):
    chart = execution_system(tmp_path)
    reader = {
        "operation": chart.operations,
        "preparation": chart.preparations,
        "compilation": chart.compilations,
        "run": chart.runs,
    }[missing]
    reader.load_verified.return_value = None
    with pytest.raises(OnlyChartCalculationError):
        chart.execution.execute(chart.operation.operation_id)
    chart.host.execute_chart_calculation.assert_not_called()


@pytest.mark.parametrize("change", ["cancelled", "inactive", "retired", "wrong_owner", "wrong_generation"])
def test_no_execution_permission_from_historical_readability(tmp_path, change):
    from onlyalpha.research.run.model import OnlyResearchRunState

    chart = execution_system(tmp_path)
    if change == "cancelled":
        chart.runs.load_verified.return_value = chart.run.transition(OnlyResearchRunState.CANCELLED, at=NOW)
    elif change == "retired":
        chart.runtime.require_runtime_generation.side_effect = ValueError("RUNTIME_GENERATION_UNAVAILABLE")
    else:
        values = {
            "inactive": {"active": False},
            "wrong_owner": {"binding_owner": "SEARCH"},
            "wrong_generation": {"runtime_generation_fingerprint": "f" * 64},
        }
        chart.runtime.require_work_binding_evidence.return_value = replace(chart.binding, **values[change])
    with pytest.raises(OnlyChartCalculationError):
        chart.execution.execute(chart.operation.operation_id)
    chart.host.execute_chart_calculation.assert_not_called()


@pytest.mark.parametrize("state", ["RUNNING", "CANCEL_REQUESTED", "COMPLETED"])
@pytest.mark.parametrize("boundary", ["initial_read", "dispatch_read", "dispatch_hold"])
def test_nonqueued_chart_lifecycle_never_authorizes_e1_compute(tmp_path, state, boundary):
    from onlyalpha.application.chart_calculation_execution import _only_require_chart_execution_request
    from onlyalpha.research.run.model import OnlyResearchRunState

    chart = execution_system(tmp_path)
    successor = chart.run.transition(OnlyResearchRunState.RUNNING, at=NOW)
    if state == "CANCEL_REQUESTED":
        successor = successor.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW)
    elif state == "COMPLETED":
        successor = successor.transition(
            OnlyResearchRunState.COMPLETED,
            at=NOW,
            research_result_fingerprint="a" * 64,
            artifact_content_fingerprint="b" * 64,
            calculation_execution_evidence_fingerprints=("c" * 64,),
        )
    computation = Mock(side_effect=AssertionError("E1 computed after its queued permission was revoked"))

    def dispatch(capability, *, cancellation):
        _only_require_chart_execution_request(capability)
        if boundary == "dispatch_read":
            chart.runs.load_verified.return_value = successor
            capability.validate_dispatch()
            computation()
        else:
            chart.runs.hold_queued_run.side_effect = lambda *args: nullcontext(successor)
            with capability.hold_dispatch():
                computation()

    chart.host.execute_chart_calculation.side_effect = dispatch
    if boundary == "initial_read":
        chart.runs.load_verified.return_value = successor
    with pytest.raises(OnlyChartCalculationError, match="CHART_EXECUTION_RUN_NOT_QUEUED"):
        chart.execution.execute(chart.operation.operation_id)
    computation.assert_not_called()
    if boundary == "initial_read":
        chart.host.execute_chart_calculation.assert_not_called()
    else:
        chart.host.execute_chart_calculation.assert_called_once()
    chart.runs.commit_or_replay.assert_not_called()
    chart.runtime.release_work.assert_not_called()
    chart.runtime.bind_new_work.assert_not_called()


def test_cancelled_request_never_dispatches(tmp_path):
    chart = execution_system(tmp_path)
    cancelled = Event()
    cancelled.set()
    with pytest.raises(OnlyChartCalculationError, match="CHART_EXECUTION_CANCELLED"):
        chart.execution.execute(chart.operation.operation_id, cancellation=cancelled)
    chart.host.execute_chart_calculation.assert_not_called()


def test_serialized_or_copied_request_has_no_execution_capability():
    from onlyalpha.application.chart_calculation_execution import _only_require_chart_execution_request

    for fake in ({"seal": "serialized-python-seal", "schema_version": 1}, object()):
        with pytest.raises(OnlyChartCalculationError, match="CHART_EXECUTION_UNAUTHORIZED"):
            _only_require_chart_execution_request(fake)


def local_executor_projection(chart):
    """Contract fake for transport only; this is NOT hosted provenance evidence."""
    from onlyalpha.application.chart_calculation_execution import (
        OnlyChartCalculationExecutionProjectionV1,
        _only_require_chart_execution_request,
    )
    from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
    from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
    from tests.research.specification.test_calculation_publication import publication_registry

    def execute(capability, *, cancellation):
        request = _only_require_chart_execution_request(capability)
        capability.validate_dispatch()
        chart.last_capability = capability
        executor = OnlyResearchCalculationExecutor(
            chart.dataset, OnlyResearchCalculationBackendResolver(publication_registry())
        )
        frozen = request.compilation
        execution = executor._execute_verified_v2(
            frozen.dataset_snapshot_fingerprint,
            frozen.resolution.calculation_graph,
            frozen.resolution.job_plan.publication,
        ).execution
        return OnlyChartCalculationExecutionProjectionV1(
            request, execution.outputs[0].table, execution.readiness[0].table
        )

    chart.host.execute_chart_calculation.side_effect = execute
    return execute


def test_exact_local_projection_does_not_grant_native_seal_or_mutate_run(tmp_path):
    import copy

    from onlyalpha.application.chart_calculation_execution import _only_require_chart_execution_request
    from onlyalpha.research.calculation.errors import OnlyResearchCalculationError
    from onlyalpha.research.calculation.execution import _only_require_verified_research_calculation_execution_v2

    chart = execution_system(tmp_path)
    local_executor_projection(chart)
    projection = chart.execution.execute(chart.operation.operation_id)
    assert projection.status == "EXECUTED_UNPUBLISHED"
    assert projection.values.num_rows == 6
    assert projection.readiness.column("readiness").to_pylist() == [
        "PARTIAL",
        "PARTIAL",
        "READY",
        "READY",
        "READY",
        "READY",
    ]
    assert projection.readiness.column("reason").to_pylist() == [
        "WARMUP_INCOMPLETE",
        "WARMUP_INCOMPLETE",
        "NONE",
        "NONE",
        "NONE",
        "NONE",
    ]
    chart.runs.commit_or_replay.assert_not_called()
    chart.runtime.bind_new_work.assert_not_called()
    chart.runtime.release_work.assert_not_called()
    for fake in (projection, projection.to_dict(), copy.copy(chart.last_capability), chart.last_capability):
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED"):
            _only_require_verified_research_calculation_execution_v2(fake)
        if not isinstance(fake, (dict, type(projection))):
            with pytest.raises(OnlyChartCalculationError, match="CHART_EXECUTION_UNAUTHORIZED"):
                _only_require_chart_execution_request(fake)


@pytest.mark.parametrize("revocation", ["release", "retire", "cancel_run", "cancel_request", "dispatch_release"])
def test_revocation_discards_projection_without_run_failure(tmp_path, revocation):
    from onlyalpha.research.run.model import OnlyResearchRunState

    chart = execution_system(tmp_path)
    original = local_executor_projection(chart)
    cancellation = Event()

    def revoke():
        if revocation in {"release", "dispatch_release"}:
            chart.runtime.require_work_binding_evidence.return_value = replace(chart.binding, active=False)
        elif revocation == "retire":
            chart.runtime.require_runtime_generation.side_effect = ValueError("RUNTIME_GENERATION_UNAVAILABLE")
        elif revocation == "cancel_run":
            chart.runs.load_verified.return_value = chart.run.transition(OnlyResearchRunState.CANCELLED, at=NOW)
        else:
            cancellation.set()

    def executed(capability, *, cancellation):
        if revocation == "dispatch_release":
            revoke()
        projection = original(capability, cancellation=cancellation)
        revoke()
        return projection

    chart.host.execute_chart_calculation.side_effect = executed
    with pytest.raises(OnlyChartCalculationError):
        chart.execution.execute(chart.operation.operation_id, cancellation=cancellation)
    chart.runs.commit_or_replay.assert_not_called()


@pytest.mark.parametrize(
    "field",
    [
        "run_id",
        "operation_id",
        "compilation_fingerprint",
        "runtime_generation_fingerprint",
        "dataset_snapshot_fingerprint",
        "dataset_materialization_id",
        "input_selection_fingerprint",
        "graph_fingerprint",
        "calculation_fingerprint",
        "implementation_fingerprint",
        "node_fingerprint",
        "instrument_id",
        "publication",
        "request_fingerprint",
        "status",
        "schema_version",
    ],
)
def test_complete_different_or_missing_response_context_is_rejected(tmp_path, field):
    from onlyalpha.application.chart_calculation_execution import OnlyChartCalculationExecutionProjectionV1

    chart = execution_system(tmp_path)
    local_executor_projection(chart)
    projection = chart.execution.execute(chart.operation.operation_id)
    for change in ("missing", "different"):
        raw = projection.to_dict()
        if change == "missing":
            del raw[field]
        else:
            raw[field] = True if field == "schema_version" else "different"
        with pytest.raises((OnlyChartCalculationError, ValueError)):
            OnlyChartCalculationExecutionProjectionV1.from_dict(raw, request=projection.request)


@pytest.mark.parametrize(
    "mutation",
    [
        "reordered",
        "duplicate",
        "missing",
        "extra",
        "null",
        "wrong_output",
        "wrong_type",
        "missing_readiness",
        "duplicate_readiness",
        "contradictory",
        "undefined",
        "unknown",
    ],
)
def test_output_and_rowwise_readiness_mutations_are_rejected(tmp_path, mutation):
    import pyarrow as pa

    from onlyalpha.application.chart_calculation_execution import OnlyChartCalculationExecutionProjectionV1
    from onlyalpha.research.calculation.errors import OnlyResearchCalculationError

    chart = execution_system(tmp_path)
    local_executor_projection(chart)
    projection = chart.execution.execute(chart.operation.operation_id)
    values, readiness = projection.values, projection.readiness
    if mutation == "reordered":
        values = values.take(pa.array([1, 0, 2, 3, 4, 5]))
    elif mutation == "duplicate":
        values = values.take(pa.array([0, 0, 2, 3, 4, 5]))
    elif mutation == "missing":
        values = values.slice(1)
    elif mutation == "extra":
        values = values.append_column("extra", values.column(1))
    elif mutation == "null":
        values = values.set_column(1, values.column_names[1], pa.array([None] * 6, type=values.column(1).type))
    elif mutation == "wrong_output":
        values = values.rename_columns(["ts_event_ns", "wrong"])
    elif mutation == "wrong_type":
        values = values.set_column(1, values.column_names[1], pa.array([1.0] * 6))
    elif mutation == "missing_readiness":
        readiness = readiness.slice(1)
    elif mutation == "duplicate_readiness":
        readiness = pa.concat_tables([readiness, readiness])
    else:
        states = ["READY"] * 6
        reasons = {
            "contradictory": ["WARMUP_INCOMPLETE"] * 6,
            "undefined": ["VALUE_UNDEFINED"] * 6,
            "unknown": ["UNKNOWN"] * 6,
        }[mutation]
        readiness = readiness.set_column(2, readiness.schema.field(2), pa.array(states))
        readiness = readiness.set_column(3, readiness.schema.field(3), pa.array(reasons))
    with pytest.raises((OnlyChartCalculationError, OnlyResearchCalculationError)):
        OnlyChartCalculationExecutionProjectionV1(projection.request, values, readiness)


@pytest.mark.parametrize("limit", ["rows", "bytes"])
def test_input_resource_limits_refuse_host_dispatch(tmp_path, monkeypatch, limit):
    from onlyalpha.application import chart_calculation_execution as execution_module

    name = "CHART_CALCULATION_EXECUTION_MAX_ROWS" if limit == "rows" else "CHART_CALCULATION_EXECUTION_MAX_BYTES"
    monkeypatch.setattr(execution_module, name, 1)
    chart = execution_system(tmp_path)
    with pytest.raises(OnlyChartCalculationError):
        chart.execution.execute(chart.operation.operation_id)
    chart.host.execute_chart_calculation.assert_not_called()


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "calculation_result_schema_version",
        "execution_evidence_schema_version",
        "readiness_contract_version",
    ],
)
def test_projection_publication_boolean_versions_are_rejected(tmp_path, field):
    from onlyalpha.application.chart_calculation_execution import OnlyChartCalculationExecutionProjectionV1

    chart = execution_system(tmp_path)
    local_executor_projection(chart)
    projection = chart.execution.execute(chart.operation.operation_id)
    raw = projection.to_dict()
    raw["publication"][field] = True
    with pytest.raises(ValueError):
        OnlyChartCalculationExecutionProjectionV1.from_dict(raw, request=projection.request)


def test_projection_decoder_rejects_compression_and_budget_before_arrow_allocation(tmp_path, monkeypatch):
    from onlyalpha.application import chart_calculation_execution as module

    chart = execution_system(tmp_path)
    local_executor_projection(chart)
    projection = chart.execution.execute(chart.operation.operation_id)
    payload = projection.to_dict()
    encoded = payload["values"]

    def forbidden(*args, **kwargs):
        pytest.fail("rejected payload must not allocate Arrow columns")

    monkeypatch.setattr(module.pa, "array", forbidden)
    for raw in ("compressed-arrow-ipc", {**encoded, "compression": "zstd"}):
        with pytest.raises((ValueError, OnlyChartCalculationError)):
            module._decode_table(raw)
    monkeypatch.setattr(module, "CHART_CALCULATION_EXECUTION_MAX_BYTES", 1)
    with pytest.raises(OnlyChartCalculationError, match="CHART_EXECUTION_RESOURCE_LIMIT"):
        module._decode_table(encoded)


def test_parsed_and_native_projection_buffers_are_readonly(tmp_path):
    from onlyalpha.application.chart_calculation_execution import OnlyChartCalculationExecutionProjectionV1

    chart = execution_system(tmp_path)
    local_executor_projection(chart)
    result = chart.execution.execute(chart.operation.operation_id)
    parsed = OnlyChartCalculationExecutionProjectionV1.from_dict(result.to_dict(), request=result.request)
    for projection in (result, parsed):
        for table in (projection.values, projection.readiness):
            for column in table.columns:
                for chunk in column.chunks:
                    for buffer in chunk.buffers():
                        if buffer is not None:
                            assert buffer.is_mutable is False


@pytest.mark.parametrize("small", [False, True])
def test_nullable_fixed_width_budget_rejects_before_arrow_allocation(monkeypatch, small):
    import pyarrow as pa

    from onlyalpha.application import chart_calculation_execution as module
    from onlyalpha.canonical import only_canonical_json

    schema = pa.schema(
        [
            *(pa.field(f"decimal_{index}", pa.decimal256(76, 12)) for index in range(13)),
            *(pa.field(f"string_{index}", pa.string()) for index in range(3)),
        ]
    )
    count = 2 if small else module.CHART_CALCULATION_EXECUTION_MAX_ROWS
    if small:
        monkeypatch.setattr(module, "CHART_CALCULATION_EXECUTION_MAX_BYTES", 128)
    raw = {
        "schema": list(module.only_research_calculation_arrow_schema_payload(schema)),
        "rows": [[*([None] * 13), *(["x" * 84] * 3)] for _ in range(count)],
    }
    assert len(only_canonical_json(raw).encode()) < 32 * 1024 * 1024
    monkeypatch.setattr(
        module.pa, "array", lambda *args, **kwargs: pytest.fail("nullable over-budget payload must not allocate Arrow")
    )
    with pytest.raises(OnlyChartCalculationError, match="CHART_EXECUTION_RESOURCE_LIMIT"):
        module._decode_table(raw)


def test_values_and_readiness_share_preallocation_budget(tmp_path, monkeypatch):
    import pyarrow as pa

    from onlyalpha.application import chart_calculation_execution as module
    from onlyalpha.canonical import only_canonical_json

    chart = execution_system(tmp_path)
    local_executor_projection(chart)
    original_projection = chart.execution.execute(chart.operation.operation_id)
    schema = pa.schema([pa.field(f"value_{index}", pa.decimal256(76, 12)) for index in range(16)])
    raw_table = {
        "schema": list(module.only_research_calculation_arrow_schema_payload(schema)),
        "rows": [[None] * 16 for _ in range(module.CHART_CALCULATION_EXECUTION_MAX_ROWS)],
    }
    raw = original_projection.request.projection_context() | {"values": raw_table, "readiness": raw_table}
    assert len(only_canonical_json(raw).encode()) < 32 * 1024 * 1024
    original_array = pa.array
    allocations = []

    def allocating(column, *, type):
        allocations.append(type)
        assert len(allocations) <= 16, "second table must refuse its shared budget before Arrow allocation"
        return original_array(column, type=type)

    monkeypatch.setattr(module.pa, "array", allocating)
    with pytest.raises(OnlyChartCalculationError, match="CHART_EXECUTION_RESOURCE_LIMIT"):
        module.OnlyChartCalculationExecutionProjectionV1.from_dict(raw, request=original_projection.request)
    assert len(allocations) == 16


def test_empty_string_table_terminal_offsets_obey_preallocation_budget(monkeypatch):
    import pyarrow as pa

    from onlyalpha.application import chart_calculation_execution as module

    raw = {
        "schema": list(
            module.only_research_calculation_arrow_schema_payload(pa.schema([pa.field("value", pa.string())]))
        ),
        "rows": [],
    }
    monkeypatch.setattr(
        module.pa, "array", lambda *args, **kwargs: pytest.fail("terminal offset budget must precede allocation")
    )
    with pytest.raises(OnlyChartCalculationError, match="CHART_EXECUTION_RESOURCE_LIMIT"):
        module._decode_table(raw, byte_budget=1)
