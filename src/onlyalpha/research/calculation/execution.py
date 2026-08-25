"""Deterministic semantic-node-first Calculation DAG execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation.definition import (
    FACTOR_SCORE_SEMANTIC_TYPE,
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyFactorKind,
    OnlyOutputDefinition,
    OnlyTimestampSemantic,
    only_calculation_execution_shape,
    only_calculation_semantic_bounds,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.research.dataset import OnlyResearchDatasetSnapshotStore

from .backend import (
    OnlyResearchCalculationBackend,
    OnlyResearchCalculationBackendResolver,
    OnlyResolvedResearchCalculationBackend,
)
from .binding import only_bind_research_dataset_source
from .errors import OnlyResearchCalculationError
from .identity import only_research_calculation_fingerprint


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationNodeOutput:
    node_fingerprint: str
    instrument_id: str
    table: pa.Table


@dataclass(frozen=True, order=True, slots=True)
class OnlyResearchCalculationImplementationBinding:
    node_fingerprint: str
    research_implementation_fingerprint: str

    def __post_init__(self) -> None:
        _sha(self.node_fingerprint, "node fingerprint")
        _sha(self.research_implementation_fingerprint, "Research implementation fingerprint")


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationExecutionPlanBinding:
    node_fingerprint: str
    backend: OnlyResolvedResearchCalculationBackend

    @property
    def implementation_binding(self) -> OnlyResearchCalculationImplementationBinding:
        return OnlyResearchCalculationImplementationBinding(
            self.node_fingerprint,
            self.backend.implementation_manifest.implementation_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationExecutionPlan:
    calculation_graph_fingerprint: str
    bindings: tuple[OnlyResearchCalculationExecutionPlanBinding, ...]

    def __post_init__(self) -> None:
        _sha(self.calculation_graph_fingerprint, "Calculation Graph fingerprint")
        keys = tuple(item.node_fingerprint for item in self.bindings)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("Research Calculation execution bindings must be canonical and unique")

    @property
    def implementation_bindings(self) -> tuple[OnlyResearchCalculationImplementationBinding, ...]:
        return tuple(item.implementation_binding for item in self.bindings)


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationExecution:
    calculation_fingerprint: str
    dataset_snapshot_fingerprint: str
    calculation_graph_fingerprint: str
    outputs: tuple[OnlyResearchCalculationNodeOutput, ...]
    research_implementation_bindings: tuple[OnlyResearchCalculationImplementationBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class _OnlyVerifiedResearchCalculationExecution:
    """Module-sealed proof that the enclosed projection came from this executor."""

    execution: OnlyResearchCalculationExecution
    seal: object


_VERIFIED_EXECUTION_SEAL = object()


def _only_require_verified_research_calculation_execution(
    value: object,
) -> OnlyResearchCalculationExecution:
    if not isinstance(value, _OnlyVerifiedResearchCalculationExecution) or value.seal is not _VERIFIED_EXECUTION_SEAL:
        raise OnlyResearchCalculationError(
            "RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED",
            "Execution Evidence requires an actual sealed Research execution",
        )
    return value.execution


class OnlyResearchCalculationExecutor:
    def __init__(
        self, store: OnlyResearchDatasetSnapshotStore, resolver: OnlyResearchCalculationBackendResolver
    ) -> None:
        self._store = store
        self._resolver = resolver

    def execute(
        self, snapshot_fingerprint: str, graph: OnlyCalculationGraphDefinition
    ) -> OnlyResearchCalculationExecution:
        """Return a public execution projection without Evidence minting authority."""

        return self._execute_verified(snapshot_fingerprint, graph).execution

    def _execute_verified(
        self, snapshot_fingerprint: str, graph: OnlyCalculationGraphDefinition
    ) -> _OnlyVerifiedResearchCalculationExecution:
        plan = self.plan(graph)
        try:
            verified = self._store.load_verified_table(snapshot_fingerprint)
        except Exception as exc:
            raise OnlyResearchCalculationError("RESEARCH_DATASET_VERIFICATION_FAILED", str(exc)) from exc
        snapshot, table = verified.snapshot, verified.table
        instrument_ids = tuple(sorted(set(table.column("instrument_id").to_pylist())))
        instrument_tables: dict[str, pa.Table] = {}
        for instrument_id in instrument_ids:
            instrument_table = table.filter(pa.compute.equal(table.column("instrument_id"), instrument_id))
            _validate_instrument_rows(instrument_table)
            instrument_tables[instrument_id] = instrument_table
        workspace: dict[str, dict[str, pa.Table]] = {}
        resolved = {item.node_fingerprint: item.backend.provider for item in plan.bindings}
        for node in graph.ordered_nodes:
            if only_calculation_execution_shape(node.definition) is OnlyFactorKind.TIME_SERIES:
                workspace[node.fingerprint] = self._execute_time_series_node(
                    node.definition,
                    instrument_ids,
                    instrument_tables,
                    snapshot.dataset_schema,
                    workspace,
                    resolved[node.fingerprint],
                )
            else:
                workspace[node.fingerprint] = self._execute_cross_section_node(
                    node.definition,
                    instrument_ids,
                    instrument_tables,
                    snapshot.dataset_schema,
                    workspace,
                    resolved[node.fingerprint],
                )
        results = tuple(
            OnlyResearchCalculationNodeOutput(
                node.fingerprint, instrument_id, workspace[node.fingerprint][instrument_id]
            )
            for instrument_id in instrument_ids
            for node in graph.ordered_nodes
        )
        return _OnlyVerifiedResearchCalculationExecution(
            OnlyResearchCalculationExecution(
                only_research_calculation_fingerprint(snapshot.snapshot_fingerprint, graph.fingerprint),
                snapshot.snapshot_fingerprint,
                graph.fingerprint,
                results,
                plan.implementation_bindings,
            ),
            _VERIFIED_EXECUTION_SEAL,
        )

    def plan(self, graph: OnlyCalculationGraphDefinition) -> OnlyResearchCalculationExecutionPlan:
        bindings = tuple(
            sorted(
                (
                    OnlyResearchCalculationExecutionPlanBinding(
                        node.fingerprint,
                        self._resolver.resolve(node.definition),
                    )
                    for node in graph.ordered_nodes
                ),
                key=lambda item: item.node_fingerprint,
            )
        )
        if {item.node_fingerprint for item in bindings} != {item.fingerprint for item in graph.nodes}:
            raise OnlyResearchCalculationError(
                "RESEARCH_IMPLEMENTATION_IDENTITY_UNRESOLVED",
                "Calculation Graph node set differs from resolved implementation bindings",
            )
        return OnlyResearchCalculationExecutionPlan(graph.fingerprint, bindings)

    def _execute_time_series_node(
        self,
        definition: OnlyCalculationDefinition,
        instrument_ids: tuple[str, ...],
        instrument_tables: Mapping[str, pa.Table],
        schema: object,
        workspace: Mapping[str, Mapping[str, pa.Table]],
        backend: OnlyResearchCalculationBackend,
    ) -> dict[str, pa.Table]:
        result: dict[str, pa.Table] = {}
        for instrument_id in instrument_ids:
            table = instrument_tables[instrument_id]
            inputs = self._resolve_instrument_inputs(definition, table, schema, workspace, instrument_id)
            outputs = self._run_backend(definition, inputs, table.num_rows, backend)
            result[instrument_id] = pa.table({"ts_event_ns": _timestamp_column(definition, table), **outputs})
        return result

    def _execute_cross_section_node(
        self,
        definition: OnlyCalculationDefinition,
        instrument_ids: tuple[str, ...],
        instrument_tables: Mapping[str, pa.Table],
        schema: object,
        workspace: Mapping[str, Mapping[str, pa.Table]],
        backend: OnlyResearchCalculationBackend,
    ) -> dict[str, pa.Table]:
        if not instrument_ids:
            raise OnlyResearchCalculationError(
                "RESEARCH_CROSS_SECTION_ALIGNMENT_FAILED", "cross-section instrument axis is empty"
            )
        axes = {
            instrument_id: tuple(instrument_tables[instrument_id].column("ts_event_ns").to_pylist())
            for instrument_id in instrument_ids
        }
        canonical_axis = axes[instrument_ids[0]]
        if any(axis != canonical_axis for axis in axes.values()):
            raise OnlyResearchCalculationError(
                "RESEARCH_CROSS_SECTION_ALIGNMENT_FAILED", "instrument event-time axes differ"
            )
        inputs_by_instrument = {
            instrument_id: self._resolve_instrument_inputs(
                definition, instrument_tables[instrument_id], schema, workspace, instrument_id
            )
            for instrument_id in instrument_ids
        }
        materialized: dict[str, dict[str, list[object]]] = {
            instrument_id: {output.name: [] for output in definition.outputs} for instrument_id in instrument_ids
        }
        output_types: dict[str, pa.DataType] = {}
        for row_index, _timestamp in enumerate(canonical_axis):
            inputs = {
                name: pa.array(
                    [inputs_by_instrument[instrument_id][name][row_index].as_py() for instrument_id in instrument_ids],
                    type=inputs_by_instrument[instrument_ids[0]][name].type,
                )
                for name in sorted(definition.input_bindings)
            }
            outputs = self._run_backend(definition, inputs, len(instrument_ids), backend)
            for output_name, output in outputs.items():
                previous_type = output_types.setdefault(output_name, output.type)
                if output.type != previous_type:
                    raise OnlyResearchCalculationError(
                        "RESEARCH_OUTPUT_INVALID", f"{output_name} Arrow type changed across timestamps"
                    )
                for instrument_index, instrument_id in enumerate(instrument_ids):
                    materialized[instrument_id][output_name].append(output[instrument_index].as_py())
        return {
            instrument_id: pa.table(
                {
                    "ts_event_ns": instrument_tables[instrument_id].column("ts_event_ns"),
                    **{
                        output.name: pa.array(materialized[instrument_id][output.name], type=output_types[output.name])
                        for output in definition.outputs
                    },
                }
            )
            for instrument_id in instrument_ids
        }

    @staticmethod
    def _resolve_instrument_inputs(
        definition: OnlyCalculationDefinition,
        table: pa.Table,
        schema: object,
        workspace: Mapping[str, Mapping[str, pa.Table]],
        instrument_id: str,
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
            dependency = workspace.get(str(reference.node_fingerprint), {}).get(instrument_id)
            if dependency is None or dependency.schema.get_field_index(reference.output_name) < 0:
                raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"missing node input {name}")
            result[name] = dependency.column(reference.output_name)
        return result

    def _run_backend(
        self,
        definition: OnlyCalculationDefinition,
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
        row_count: int,
        backend: OnlyResearchCalculationBackend,
    ) -> Mapping[str, pa.Array | pa.ChunkedArray]:
        try:
            raw = backend.execute(definition, MappingProxyType(dict(inputs)))
        except OnlyResearchCalculationError:
            raise
        except Exception as exc:
            raise OnlyResearchCalculationError(
                "RESEARCH_EXECUTION_FAILED", f"{definition.type_id}@{definition.semantic_version}"
            ) from exc
        return _validate_outputs(definition, raw, row_count)


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
        bounds = only_calculation_semantic_bounds(contract.semantic_type)
        if contract.semantic_type == FACTOR_SCORE_SEMANTIC_TYPE and bounds is not None:
            values = value.to_pylist()
            if any(item is not None and not bounds[0] <= item <= bounds[1] for item in values):
                raise OnlyResearchCalculationError("RESEARCH_SCORE_OUT_OF_RANGE", name)
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


def _sha(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")
