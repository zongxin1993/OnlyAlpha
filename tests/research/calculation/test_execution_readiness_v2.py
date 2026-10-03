from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pyarrow as pa
import pytest
from onlyalpha_plugin_indicators.registration import TYPES, registrations, resolve_definition

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationBackendRegistration,
    OnlyCalculationGraphDefinition,
    OnlyCalculationKind,
    OnlyCalculationNodeDefinition,
    OnlyCalculationRegistry,
    OnlyCalculationTypeReference,
    OnlyFactorKind,
    only_implementation_manifest_from_bytes,
)
from onlyalpha.research.calculation.backend import (
    OnlyResearchCalculationBackendExecutionV2,
    OnlyResearchCalculationBackendResolver,
)
from onlyalpha.research.calculation.errors import OnlyResearchCalculationError
from onlyalpha.research.calculation.execution import (
    OnlyResearchCalculationExecutionV2,
    OnlyResearchCalculationExecutor,
    _immutable_arrow_array,
    _only_require_verified_research_calculation_execution,
    _only_require_verified_research_calculation_execution_v2,
    _OnlyVerifiedResearchCalculationExecutionV2,
)
from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationContract
from onlyalpha.research.calculation.readiness import OnlyResearchOutputReadiness
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from tests.research.calculation.support import bars, snapshot

SMA = next(item for item in TYPES if item.type_id == "onlyalpha.indicator.sma")
PUBLICATION = OnlyResearchCalculationPublicationContract()


class _StoreSpy:
    def __init__(self, store):
        self.store = store
        self.loads = 0

    def load_verified_table(self, fingerprint):
        self.loads += 1
        return self.store.load_verified_table(fingerprint)


class _AtomicBackend:
    def __init__(self, mutation=None):
        self.calls = 0
        self.legacy_calls = 0
        self.mutation = mutation

    def execute(self, definition, inputs):
        self.legacy_calls += 1
        raise AssertionError("V2 must never execute legacy values")

    def execute_with_readiness(self, definition, inputs):
        self.calls += 1
        outputs = {item.name: inputs["value"] for item in definition.outputs}
        readiness = {
            name: OnlyResearchOutputReadiness(pa.array(["READY"] * len(values)), pa.array(["NONE"] * len(values)))
            for name, values in outputs.items()
        }
        if self.mutation is not None:
            self.mutation(outputs, readiness, self.calls)
        return OnlyResearchCalculationBackendExecutionV2(outputs, readiness)


def _registry(provider=None, versions=(1,), type_definition=SMA):
    registry = OnlyCalculationRegistry()
    if provider is None:
        for registration in registrations():
            registry.register(registration)
        return registry
    manifest = only_implementation_manifest_from_bytes(
        calculation_type_reference=OnlyCalculationTypeReference(
            type_definition.kind, type_definition.type_id, type_definition.semantic_version
        ),
        backend_kind=OnlyCalculationBackendKind.RESEARCH,
        entrypoint_identity=f"{type(provider).__module__}:{type(provider).__qualname__}",
        resources={"backend.py": type(provider).__qualname__.encode()},
    )
    registry.register(
        OnlyCalculationBackendRegistration(
            type_definition,
            OnlyCalculationBackendKind.RESEARCH,
            provider,
            implementation_manifest=manifest,
            readiness_contract_versions=versions,
        )
    )
    return registry


def _graph(period=3, type_definition=SMA):
    return OnlyCalculationGraphDefinition(
        (OnlyCalculationNodeDefinition(resolve_definition(type_definition, {"period": period})),)
    )


def _setup(tmp_path, registry=None):
    source = bars()
    source = tuple(
        replace(bar, close=replace(bar.close, value=Decimal("0")))
        if str(bar.instrument_id) == "A.XNAS" and bar.close.value == Decimal("1")
        else bar
        for bar in source
    )
    candidate, partitions = snapshot(source)
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    committed = store.commit(candidate, partitions)
    spy = _StoreSpy(store)
    executor = OnlyResearchCalculationExecutor(spy, OnlyResearchCalculationBackendResolver(registry or _registry()))
    return executor, spy, committed.snapshot_fingerprint


def test_v2_executor_calls_only_atomic_readiness_method(tmp_path) -> None:
    backend = _AtomicBackend()
    executor, spy, fingerprint = _setup(tmp_path, _registry(backend))
    graph = _graph()
    verified = executor._execute_verified_v2(fingerprint, graph, PUBLICATION)
    execution = _only_require_verified_research_calculation_execution_v2(verified)
    assert isinstance(execution, OnlyResearchCalculationExecutionV2)
    assert spy.loads == 1
    assert backend.calls == 2
    assert backend.legacy_calls == 0
    assert tuple(item.instrument_id for item in execution.outputs) == ("A.XNAS", "B.XNAS")
    assert execution.dataset_snapshot_fingerprint == fingerprint
    assert execution.calculation_graph_fingerprint == graph.fingerprint
    (binding,) = execution.research_implementation_bindings
    assert binding.node_fingerprint == graph.nodes[0].fingerprint
    assert (
        binding.research_implementation_fingerprint
        == executor._resolver.resolve_readiness(
            graph.nodes[0].definition, PUBLICATION
        ).implementation_manifest.implementation_fingerprint
    )


def test_v2_executor_materializes_canonical_long_readiness_table(tmp_path) -> None:
    type_definition = replace(SMA, outputs=(replace(SMA.outputs[0], name="z"), replace(SMA.outputs[0], name="a")))
    executor, _, fingerprint = _setup(tmp_path, _registry(_AtomicBackend(), type_definition=type_definition))
    graph = _graph(type_definition=type_definition)
    execution = executor._execute_verified_v2(fingerprint, graph, PUBLICATION).execution
    assert len(execution.outputs) == len(execution.readiness) == 2
    schema = pa.schema(
        [
            pa.field("ts_event_ns", pa.int64(), nullable=False),
            pa.field("output_name", pa.string(), nullable=False),
            pa.field("readiness", pa.string(), nullable=False),
            pa.field("reason", pa.string(), nullable=False),
        ]
    )
    for values, readiness in zip(execution.outputs, execution.readiness, strict=True):
        assert (values.node_fingerprint, values.instrument_id) == (readiness.node_fingerprint, readiness.instrument_id)
        assert values.table.column_names == ["ts_event_ns", "a", "z"]
        assert readiness.table.schema == schema
        axis = values.table["ts_event_ns"].to_pylist()
        assert readiness.table.to_pylist() == [
            {"ts_event_ns": timestamp, "output_name": name, "readiness": "READY", "reason": "NONE"}
            for name in ("a", "z")
            for timestamp in axis
        ]


@pytest.mark.parametrize("period", (1, 3))
def test_v2_sma_zero_period_one_and_exact_v1_numeric_parity(tmp_path, period) -> None:
    executor, spy, fingerprint = _setup(tmp_path)
    graph = _graph(period)
    before = spy.store.load_verified_table(fingerprint).table
    execution = executor._execute_verified_v2(fingerprint, graph, PUBLICATION).execution
    legacy = executor.execute(fingerprint, graph)
    assert execution.calculation_fingerprint == legacy.calculation_fingerprint
    assert execution.research_implementation_bindings == legacy.research_implementation_bindings
    assert all(left.table.equals(right.table) for left, right in zip(execution.outputs, legacy.outputs, strict=True))
    expected = [
        Decimal(value)
        for value in (
            ("0.000000000000", "2.000000000000", "4.000000000000", "8.000000000000")
            if period == 1
            else ("0.000000000000", "1.000000000000", "2.000000000000", "4.666666666667")
        )
    ]
    assert execution.outputs[0].table["value"].to_pylist() == expected
    assert execution.readiness[0].table["readiness"].to_pylist() == (
        ["READY"] * 4 if period == 1 else ["PARTIAL", "PARTIAL", "READY", "READY"]
    )
    assert execution.readiness[0].table["reason"].to_pylist() == (
        ["NONE"] * 4 if period == 1 else ["WARMUP_INCOMPLETE", "WARMUP_INCOMPLETE", "NONE", "NONE"]
    )
    repeated = executor._execute_verified_v2(fingerprint, graph, PUBLICATION).execution
    assert all(
        left.table.equals(right.table) for left, right in zip(execution.readiness, repeated.readiness, strict=True)
    )
    assert spy.store.load_verified_table(fingerprint).table.equals(before)


@pytest.mark.parametrize(
    "kind", ("multi", "cross-section", "undeclared", "missing-method", "unregistered", "publication")
)
def test_v2_executor_rejects_unsupported_requests_before_dataset_load(kind) -> None:
    backend = _AtomicBackend()
    graph = _graph()
    registry = _registry(backend)
    publication = PUBLICATION
    if kind == "multi":
        graph = OnlyCalculationGraphDefinition(graph.nodes + _graph(1).nodes)
    elif kind == "cross-section":
        definition = replace(
            graph.nodes[0].definition, kind=OnlyCalculationKind.FACTOR, factor_kind=OnlyFactorKind.CROSS_SECTION
        )
        graph = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),))
    elif kind == "undeclared":
        registry = _registry(backend, versions=())
    elif kind == "missing-method":
        registry = _registry(object())
    elif kind == "unregistered":
        registry = OnlyCalculationRegistry()
    elif kind == "publication":
        publication = None
    spy = _StoreSpy(None)
    executor = OnlyResearchCalculationExecutor(spy, OnlyResearchCalculationBackendResolver(registry))
    with pytest.raises(OnlyResearchCalculationError):
        executor._execute_verified_v2("f" * 64, graph, publication)
    assert spy.loads == backend.calls == backend.legacy_calls == 0


@pytest.mark.parametrize(
    "field",
    (
        "schema_version",
        "calculation_result_schema_version",
        "execution_evidence_schema_version",
        "readiness_contract_version",
    ),
)
@pytest.mark.parametrize("version", (True, 99))
def test_v2_executor_revalidates_exact_publication_before_dataset_load(field, version) -> None:
    publication = replace(PUBLICATION)
    object.__setattr__(publication, field, version)
    spy = _StoreSpy(None)
    backend = _AtomicBackend()
    executor = OnlyResearchCalculationExecutor(spy, OnlyResearchCalculationBackendResolver(_registry(backend)))
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_PUBLICATION_INVALID"):
        executor._execute_verified_v2("f" * 64, _graph(), publication)
    assert spy.loads == backend.calls == backend.legacy_calls == 0


def test_v2_dataset_verification_failure_precedes_backend_execution(tmp_path) -> None:
    backend = _AtomicBackend()
    executor, spy, fingerprint = _setup(tmp_path, _registry(backend))
    root = tmp_path / "sha256" / fingerprint[:2] / fingerprint
    manifest = root / "manifest.json"
    manifest.write_text("{}")
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_DATASET_VERIFICATION_FAILED"):
        executor._execute_verified_v2(fingerprint, _graph(), PUBLICATION)
    assert spy.loads == 1
    assert backend.calls == backend.legacy_calls == 0


@pytest.mark.parametrize("mutation", ("pair", "missing", "extra", "axis", "type", "null", "backend-error"))
def test_v2_executor_rejects_invalid_second_instrument_without_sealing(tmp_path, monkeypatch, mutation) -> None:
    def mutate(outputs, readiness, calls):
        if calls != 2:
            return
        if mutation == "backend-error":
            raise ValueError("injected")
        if mutation == "missing":
            readiness.clear()
        elif mutation == "extra":
            readiness["extra"] = readiness["value"]
        elif mutation == "axis":
            readiness["value"] = OnlyResearchOutputReadiness(pa.array(["READY"]), pa.array(["NONE"]))
        elif mutation == "type":
            outputs["value"] = pa.array([1, 2, 3, 4])
        elif mutation == "null":
            outputs["value"] = pa.array([None] * 4, type=outputs["value"].type)
        else:
            readiness["value"] = OnlyResearchOutputReadiness(pa.array(["PARTIAL"] * 4), pa.array(["NONE"] * 4))

    backend = _AtomicBackend(mutate)
    executor, spy, fingerprint = _setup(tmp_path, _registry(backend))
    seals = []
    monkeypatch.setattr(
        "onlyalpha.research.calculation.execution._OnlyVerifiedResearchCalculationExecutionV2",
        lambda *args: seals.append(args),
    )
    with pytest.raises(OnlyResearchCalculationError):
        executor._execute_verified_v2(fingerprint, _graph(), PUBLICATION)
    assert seals == []
    assert spy.loads == 1
    assert backend.calls == 2
    assert backend.legacy_calls == 0


def test_v2_executor_preserves_explicit_null_readiness_reasons(tmp_path) -> None:
    def mutate(outputs, readiness, calls):
        outputs["value"] = pa.array([None] * 4, type=outputs["value"].type)
        readiness["value"] = OnlyResearchOutputReadiness(
            pa.array(["PARTIAL", "READY", "UNAVAILABLE", "UNAVAILABLE"]),
            pa.array(["WARMUP_INCOMPLETE", "VALUE_UNDEFINED", "INPUT_UNAVAILABLE", "DEPENDENCY_UNAVAILABLE"]),
        )

    executor, _, fingerprint = _setup(tmp_path, _registry(_AtomicBackend(mutate)))
    execution = executor._execute_verified_v2(fingerprint, _graph(), PUBLICATION).execution
    assert execution.outputs[0].table["value"].to_pylist() == [None] * 4
    assert execution.readiness[0].table["reason"].to_pylist() == [
        "WARMUP_INCOMPLETE",
        "VALUE_UNDEFINED",
        "INPUT_UNAVAILABLE",
        "DEPENDENCY_UNAVAILABLE",
    ]


@pytest.mark.parametrize(
    "mutation",
    (
        "context",
        "missing-context",
        "copied-seal",
        "seal",
        "owner",
        "source",
        "graph",
        "bindings",
        "producer",
        "readiness",
        "node",
        "instrument",
        "axis",
        "duplicate",
        "value",
        "forged-valid-values",
        "publication",
        "wrong-family",
        "complete-different",
    ),
)
def test_v2_seal_rejects_projection_and_identity_substitution(tmp_path, mutation) -> None:
    executor, _, fingerprint = _setup(tmp_path)
    verified = executor._execute_verified_v2(fingerprint, _graph(), PUBLICATION)
    execution = verified.execution
    if mutation == "context":
        candidate = execution
    elif mutation == "missing-context":
        candidate = None
    elif mutation == "copied-seal":
        candidate = replace(verified)
    elif mutation == "seal":
        candidate = _OnlyVerifiedResearchCalculationExecutionV2(execution, object())
    elif mutation == "wrong-family":
        candidate = executor._execute_verified(fingerprint, _graph())
    else:
        changes = {
            "owner": {"calculation_fingerprint": "0" * 64},
            "source": {"dataset_snapshot_fingerprint": "0" * 64},
            "graph": {"calculation_graph_fingerprint": "0" * 64},
            "bindings": {"research_implementation_bindings": ()},
            "producer": {
                "research_implementation_bindings": (
                    replace(
                        execution.research_implementation_bindings[0], research_implementation_fingerprint="0" * 64
                    ),
                )
            },
            "readiness": {"readiness": ()},
            "node": {"readiness": (replace(execution.readiness[0], node_fingerprint="0" * 64),)},
            "instrument": {"readiness": (replace(execution.readiness[0], instrument_id="C.XNAS"),)},
            "axis": {"readiness": (replace(execution.readiness[0], table=execution.readiness[0].table.slice(1)),)},
            "duplicate": {"outputs": execution.outputs + execution.outputs},
            "value": {"outputs": (replace(execution.outputs[0], table=pa.table({"other": [0]})),)},
            "forged-valid-values": {
                "outputs": (
                    replace(
                        execution.outputs[0],
                        table=execution.outputs[0].table.set_column(
                            1,
                            execution.outputs[0].table.schema.field(1),
                            pa.array([Decimal("0")] * 4, type=execution.outputs[0].table["value"].type),
                        ),
                    ),
                    execution.outputs[1],
                )
            },
            "publication": {"publication": None},
            "complete-different": {
                "outputs": executor._execute_verified_v2(fingerprint, _graph(1), PUBLICATION).execution.outputs
            },
        }
        candidate = replace(verified, execution=replace(execution, **changes[mutation]))
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED"):
        _only_require_verified_research_calculation_execution_v2(candidate)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED"):
        _only_require_verified_research_calculation_execution(verified)
    assert _only_require_verified_research_calculation_execution_v2(verified) is execution


class _WritableBufferBackend:
    def __init__(self, *, chunked=False):
        self.calls = 0
        self.legacy_calls = 0
        self.chunked = chunked
        self.value_validity = bytearray([0b1111])
        self.value_data = bytearray(4 * 16)
        self.state_validity = bytearray([0b1111])
        self.state_offsets = bytearray(pa.array(["READY"] * 4).buffers()[1].to_pybytes())
        self.state_data = bytearray(b"READY" * 4)
        self.reason_validity = bytearray([0b1111])
        self.reason_offsets = bytearray(pa.array(["NONE"] * 4).buffers()[1].to_pybytes())
        self.reason_data = bytearray(b"NONE" * 4)

    def execute(self, definition, inputs):
        self.legacy_calls += 1
        raise AssertionError("legacy call is forbidden")

    def execute_with_readiness(self, definition, inputs):
        self.calls += 1
        decimal_type = pa.decimal128(38, 12)
        values = pa.array([Decimal(self.calls)] * 4, type=decimal_type)
        self.value_data[:] = values.buffers()[1].to_pybytes()
        value_array = pa.Array.from_buffers(
            decimal_type, 4, [pa.py_buffer(self.value_validity), pa.py_buffer(self.value_data)], null_count=-1
        )
        states = pa.Array.from_buffers(
            pa.string(),
            4,
            [pa.py_buffer(self.state_validity), pa.py_buffer(self.state_offsets), pa.py_buffer(self.state_data)],
            null_count=-1,
        )
        reasons = pa.Array.from_buffers(
            pa.string(),
            4,
            [pa.py_buffer(self.reason_validity), pa.py_buffer(self.reason_offsets), pa.py_buffer(self.reason_data)],
            null_count=-1,
        )
        if self.chunked:
            value_array = pa.chunked_array([value_array.slice(0, 2), value_array.slice(2)])
            states = pa.chunked_array([states.slice(0, 2), states.slice(2)])
            reasons = pa.chunked_array([reasons.slice(0, 2), reasons.slice(2)])
        return OnlyResearchCalculationBackendExecutionV2(
            {"value": value_array}, {"value": OnlyResearchOutputReadiness(states, reasons)}
        )


@pytest.mark.parametrize("chunked", (False, True))
def test_v2_detaches_shared_decimal_buffer_before_next_instrument_call(tmp_path, chunked) -> None:
    backend = _WritableBufferBackend(chunked=chunked)
    executor, spy, fingerprint = _setup(tmp_path, _registry(backend))
    verified = executor._execute_verified_v2(fingerprint, _graph(), PUBLICATION)
    execution = _only_require_verified_research_calculation_execution_v2(verified)
    assert [item.table["value"].to_pylist() for item in execution.outputs] == [
        [Decimal("1.000000000000")] * 4,
        [Decimal("2.000000000000")] * 4,
    ]
    assert all(item.table["value"].type == pa.decimal128(38, 12) for item in execution.outputs)
    assert all(item.table["value"].num_chunks == (2 if chunked else 1) for item in execution.outputs)
    assert spy.loads == 1
    assert backend.calls == 2
    assert backend.legacy_calls == 0


@pytest.mark.parametrize("buffer_name", ("value_data", "value_validity"))
def test_v2_sealed_values_are_immutable_after_provider_buffer_mutation(tmp_path, buffer_name) -> None:
    backend = _WritableBufferBackend()
    executor, _, fingerprint = _setup(tmp_path, _registry(backend))
    verified = executor._execute_verified_v2(fingerprint, _graph(), PUBLICATION)
    before = [item.table.to_pydict() for item in verified.execution.outputs]
    buffer = getattr(backend, buffer_name)
    buffer[:] = bytes(len(buffer))
    execution = _only_require_verified_research_calculation_execution_v2(verified)
    assert [item.table.to_pydict() for item in execution.outputs] == before
    assert all(
        not buffer.is_mutable
        for item in execution.outputs
        for column in item.table.columns
        for chunk in column.chunks
        for buffer in chunk.buffers()
        if buffer is not None
    )


@pytest.mark.parametrize(
    "buffer_name",
    (
        "state_validity",
        "state_offsets",
        "state_data",
        "reason_validity",
        "reason_offsets",
        "reason_data",
    ),
)
def test_v2_sealed_readiness_is_immutable_after_provider_pairing_corruption(tmp_path, buffer_name) -> None:
    backend = _WritableBufferBackend(chunked=True)
    executor, _, fingerprint = _setup(tmp_path, _registry(backend))
    verified = executor._execute_verified_v2(fingerprint, _graph(), PUBLICATION)
    before = [item.table.to_pydict() for item in verified.execution.readiness]
    buffer = getattr(backend, buffer_name)
    buffer[:] = bytes(len(buffer))
    execution = _only_require_verified_research_calculation_execution_v2(verified)
    assert [item.table.to_pydict() for item in execution.readiness] == before
    for item in execution.readiness:
        assert item.table["readiness"].to_pylist() == ["READY"] * 4
        assert item.table["reason"].to_pylist() == ["NONE"] * 4
        assert all(
            not buffer.is_mutable
            for column in item.table.columns
            for chunk in column.chunks
            for buffer in chunk.buffers()
            if buffer is not None
        )


def test_v2_detaches_reused_readiness_buffers_before_next_instrument_call(tmp_path) -> None:
    class _ReusedReadinessBackend(_WritableBufferBackend):
        def __init__(self):
            super().__init__()
            self.state_data = bytearray(4 * len("PARTIAL"))
            self.reason_data = bytearray(4 * len("WARMUP_INCOMPLETE"))

        def execute_with_readiness(self, definition, inputs):
            state, reason = ("PARTIAL", "WARMUP_INCOMPLETE") if self.calls == 0 else ("READY", "NONE")
            for text, offsets, data in (
                (state, self.state_offsets, self.state_data),
                (reason, self.reason_offsets, self.reason_data),
            ):
                array = pa.array([text] * 4)
                offsets[:] = array.buffers()[1].to_pybytes()
                data[:] = array.buffers()[2].to_pybytes().ljust(len(data), b"\x00")
            return super().execute_with_readiness(definition, inputs)

    backend = _ReusedReadinessBackend()
    executor, _, fingerprint = _setup(tmp_path, _registry(backend))
    execution = executor._execute_verified_v2(fingerprint, _graph(), PUBLICATION).execution
    assert execution.readiness[0].table["readiness"].to_pylist() == ["PARTIAL"] * 4
    assert execution.readiness[0].table["reason"].to_pylist() == ["WARMUP_INCOMPLETE"] * 4
    assert execution.readiness[1].table["readiness"].to_pylist() == ["READY"] * 4
    assert execution.readiness[1].table["reason"].to_pylist() == ["NONE"] * 4
    assert backend.calls == 2
    assert backend.legacy_calls == 0


@pytest.mark.parametrize("kind", ("array", "sliced", "chunked", "empty", "empty-chunked"))
def test_immutable_arrow_copy_preserves_decimal_type_nulls_and_chunk_boundaries(kind) -> None:
    array = pa.array([Decimal("1.000000000000"), None, Decimal("0.000000000000")], type=pa.decimal128(38, 12))
    buffers = [None if buffer is None else bytearray(buffer.to_pybytes()) for buffer in array.buffers()]
    value = pa.Array.from_buffers(
        array.type, 3, [None if buffer is None else pa.py_buffer(buffer) for buffer in buffers]
    )
    if kind == "sliced":
        value = value.slice(1)
    elif kind == "chunked":
        value = pa.chunked_array([value.slice(0, 1), value.slice(1)])
    elif kind == "empty":
        value = value.slice(0, 0)
    elif kind == "empty-chunked":
        value = pa.chunked_array([], type=value.type)
    expected = value.to_pylist()
    copied = _immutable_arrow_array(value)
    assert type(copied) is type(value)
    assert copied.type == value.type
    if isinstance(value, pa.ChunkedArray):
        assert [len(chunk) for chunk in copied.chunks] == [len(chunk) for chunk in value.chunks]
    for buffer in buffers:
        if buffer is not None:
            buffer[:] = bytes(len(buffer))
    assert copied.to_pylist() == expected
    chunks = copied.chunks if isinstance(copied, pa.ChunkedArray) else (copied,)
    assert all(not buffer.is_mutable for chunk in chunks for buffer in chunk.buffers() if buffer is not None)
