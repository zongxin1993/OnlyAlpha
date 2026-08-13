"""Deterministic, instrument-isolated Calculation DAG execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation.definition import (
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyOutputDefinition,
    OnlyTimestampSemantic,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.research.dataset import OnlyResearchDatasetSnapshotStore

from .backend import OnlyResearchCalculationBackendResolver
from .binding import only_bind_research_dataset_source
from .errors import OnlyResearchCalculationError
from .identity import only_research_calculation_fingerprint


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationNodeOutput:
    node_fingerprint: str
    instrument_id: str
    table: pa.Table


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationExecution:
    calculation_fingerprint: str
    dataset_snapshot_fingerprint: str
    calculation_graph_fingerprint: str
    outputs: tuple[OnlyResearchCalculationNodeOutput, ...]


class OnlyResearchCalculationExecutor:
    def __init__(
        self, store: OnlyResearchDatasetSnapshotStore, resolver: OnlyResearchCalculationBackendResolver
    ) -> None:
        self._store = store
        self._resolver = resolver

    def execute(
        self, snapshot_fingerprint: str, graph: OnlyCalculationGraphDefinition
    ) -> OnlyResearchCalculationExecution:
        try:
            verified = self._store.load_verified_table(snapshot_fingerprint)
        except Exception as exc:
            raise OnlyResearchCalculationError("RESEARCH_DATASET_VERIFICATION_FAILED", str(exc)) from exc
        snapshot, table = verified.snapshot, verified.table
        results: list[OnlyResearchCalculationNodeOutput] = []
        for instrument_id in sorted(set(table.column("instrument_id").to_pylist())):
            instrument_table = table.filter(pa.compute.equal(table.column("instrument_id"), instrument_id))
            _validate_instrument_rows(instrument_table)
            node_outputs: dict[str, Mapping[str, pa.Array | pa.ChunkedArray]] = {}
            for node in graph.ordered_nodes:
                definition = node.definition
                inputs = self._resolve_inputs(definition, instrument_table, snapshot.dataset_schema, node_outputs)
                backend = self._resolver.resolve(definition)
                try:
                    raw = backend.execute(definition, MappingProxyType(inputs))
                except OnlyResearchCalculationError:
                    raise
                except Exception as exc:
                    raise OnlyResearchCalculationError(
                        "RESEARCH_EXECUTION_FAILED", f"{definition.type_id}@{definition.semantic_version}"
                    ) from exc
                outputs = _validate_outputs(definition, raw, instrument_table.num_rows)
                node_outputs[node.fingerprint] = outputs
                timestamp = _timestamp_column(definition, instrument_table)
                results.append(
                    OnlyResearchCalculationNodeOutput(
                        node.fingerprint,
                        instrument_id,
                        pa.table({"ts_event_ns": timestamp, **outputs}),
                    )
                )
        return OnlyResearchCalculationExecution(
            only_research_calculation_fingerprint(snapshot.snapshot_fingerprint, graph.fingerprint),
            snapshot.snapshot_fingerprint,
            graph.fingerprint,
            tuple(results),
        )

    @staticmethod
    def _resolve_inputs(
        definition: OnlyCalculationDefinition,
        table: pa.Table,
        schema: object,
        node_outputs: Mapping[str, Mapping[str, pa.Array | pa.ChunkedArray]],
    ) -> dict[str, pa.Array | pa.ChunkedArray]:
        from onlyalpha.research.dataset.schema import OnlyResearchBarDatasetSchema

        if not isinstance(schema, OnlyResearchBarDatasetSchema):
            raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", "unsupported Dataset schema")
        contracts = {item.name: item for item in definition.inputs}
        result: dict[str, pa.Array | pa.ChunkedArray] = {}
        for name in sorted(definition.input_bindings):
            reference = definition.input_bindings[name]
            if reference.source is not None:
                result[name] = only_bind_research_dataset_source(reference.source, contracts[name], table, schema)
                continue
            dependency = node_outputs.get(str(reference.node_fingerprint))
            if dependency is None or reference.output_name not in dependency:
                raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"missing node input {name}")
            result[name] = dependency[reference.output_name]
        return result


def _validate_instrument_rows(table: pa.Table) -> None:
    events = table.column("ts_event_ns").to_pylist()
    if events != sorted(events) or len(events) != len(set(events)):
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", "instrument rows are not canonical")


def _timestamp_column(definition: OnlyCalculationDefinition, table: pa.Table) -> pa.ChunkedArray:
    if definition.timestamp is not OnlyTimestampSemantic.EVENT_TIME:
        raise OnlyResearchCalculationError("RESEARCH_OUTPUT_INVALID", f"unsupported timestamp {definition.timestamp}")
    return table.column("ts_event_ns")


def _validate_outputs(
    definition: OnlyCalculationDefinition,
    raw: Mapping[str, pa.Array | pa.ChunkedArray],
    row_count: int,
) -> Mapping[str, pa.Array | pa.ChunkedArray]:
    expected = {item.name: item for item in definition.outputs}
    if set(raw) != set(expected):
        raise OnlyResearchCalculationError("RESEARCH_OUTPUT_INVALID", "output names")
    result: dict[str, pa.Array | pa.ChunkedArray] = {}
    for name in sorted(expected):
        value = raw[name]
        if not isinstance(value, (pa.Array, pa.ChunkedArray)) or len(value) != row_count:
            raise OnlyResearchCalculationError("RESEARCH_OUTPUT_INVALID", f"{name} row count")
        contract = expected[name]
        if not _output_type_matches(value.type, contract):
            raise OnlyResearchCalculationError("RESEARCH_OUTPUT_INVALID", f"{name} data_type")
        if value.null_count and not contract.nullable:
            raise OnlyResearchCalculationError("RESEARCH_OUTPUT_INVALID", f"{name} nullability")
        result[name] = value
    return MappingProxyType(result)


def _output_type_matches(data_type: pa.DataType, contract: OnlyOutputDefinition) -> bool:
    return (
        contract.data_type is OnlyCalculationDataType.DECIMAL
        and pa.types.is_decimal(data_type)
        or contract.data_type is OnlyCalculationDataType.INTEGER
        and pa.types.is_integer(data_type)
        or contract.data_type is OnlyCalculationDataType.BOOLEAN
        and pa.types.is_boolean(data_type)
        or contract.data_type is OnlyCalculationDataType.STRING
        and pa.types.is_string(data_type)
    )
