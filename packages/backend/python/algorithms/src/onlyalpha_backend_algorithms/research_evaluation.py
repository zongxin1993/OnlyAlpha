"""Pure finite graph arithmetic inside the managed OS sandbox; no business grants."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Protocol, cast

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation.definition import OnlyCalculationBackendKind, OnlyCalculationDefinition, OnlyCalculationKind
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.calculation.registry import OnlyTradingBackendFactory
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha_backend_algorithms.research_resolution import registry_for_sources
from onlyalpha_backend_algorithms.sdk.private_factor_execution import (
    OnlyPrivateFactorIsolatedProgramHost,
    OnlyPrivateFactorSourceArtifactManifestV1,
    only_execute_private_factor_program,
)


class ManagedProgramHost(OnlyPrivateFactorIsolatedProgramHost):
    """The owning process installs seccomp/rlimits before calling this host."""

    def execute(
        self,
        manifest: OnlyPrivateFactorSourceArtifactManifestV1,
        source: bytes,
        inputs: Mapping[str, object],
        parameters: Mapping[str, object],
    ) -> object:
        return only_execute_private_factor_program(manifest, source, inputs, parameters)


class ResearchBackend(Protocol):
    def execute(
        self, definition: OnlyCalculationDefinition, inputs: Mapping[str, pa.Array]
    ) -> Mapping[str, pa.Array]: ...


class TradingBackend(Protocol):
    def update(self, inputs: Mapping[str, object]) -> Mapping[str, object]: ...


class CalculationGraphEvaluator:
    def __init__(self, sources: list[dict[str, Any]], graph_record: dict[str, Any]) -> None:
        self.graph = OnlyCalculationGraphDefinition.from_dict(graph_record)
        if not 1 <= len(self.graph.nodes) <= 128:
            raise ValueError("RESEARCH_EVALUATION_BUDGET_EXCEEDED")
        self.registry, _ = registry_for_sources(sources, ManagedProgramHost())
        pa.array([Decimal("1")], type=pa.decimal128(38, 18))

    def evaluate(self, rows: list[dict[str, Any]], *, include_trading: bool = False) -> dict[str, Any]:
        if not 1 <= len(rows) <= 8192:
            raise ValueError("RESEARCH_EVALUATION_BUDGET_EXCEEDED")
        graph, registry = self.graph, self.registry
        times = []
        for row in rows:
            if set(row) != {"at_ns", "values"} or type(row["at_ns"]) is not int or row["at_ns"] < 0:
                raise ValueError("RESEARCH_EVALUATION_AXIS_INVALID")
            if type(row["values"]) is not dict or set(row["values"]) - {"open", "high", "low", "close", "volume"}:
                raise ValueError("RESEARCH_EVALUATION_INPUT_INVALID")
            times.append(row["at_ns"])
        if len(times) > 1:
            stride = times[1] - times[0]
            if stride <= 0 or any(b - a != stride for a, b in zip(times, times[1:], strict=False)):
                raise ValueError("RESEARCH_EVALUATION_AXIS_INVALID")
        workspace: dict[str, Mapping[str, pa.Array]] = {}
        implementations = {}
        streaming: dict[str, dict[str, list[object]]] = {}
        trading_implementations = {}
        for node in graph.ordered_nodes:
            definition = node.definition
            registration = registry.resolve(
                definition.kind, definition.type_id, definition.semantic_version, OnlyCalculationBackendKind.RESEARCH
            )
            if registration.definition_resolver is None or registration.implementation_manifest is None:
                raise ValueError("RESEARCH_IMPLEMENTATION_UNAVAILABLE")
            if registration.definition_resolver.resolve(definition.parameters, definition.input_bindings) != definition:
                raise ValueError("RESEARCH_DEFINITION_MISMATCH")
            inputs = {}
            for name, reference in definition.input_bindings.items():
                if reference.node_fingerprint is not None:
                    inputs[name] = workspace[reference.node_fingerprint][reference.output_name]
                else:
                    values = [row["values"][str(reference.source).removeprefix("bar.")] for row in rows]
                    if any(
                        v is not None
                        and (
                            type(v) is not str
                            or len(v) > 40
                            or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", v) is None
                        )
                        for v in values
                    ):
                        raise ValueError("RESEARCH_EVALUATION_DECIMAL_INVALID")
                    decimals = [None if v is None else Decimal(v) for v in values]
                    if any(v is not None and not v.is_finite() for v in decimals):
                        raise ValueError("RESEARCH_EVALUATION_DECIMAL_INVALID")
                    inputs[name] = pa.array(decimals, type=pa.decimal128(38, 18))
            workspace[node.fingerprint] = cast(ResearchBackend, registration.provider).execute(definition, inputs)
            implementations[node.fingerprint] = registration.implementation_manifest.implementation_fingerprint
            if include_trading and definition.kind is not OnlyCalculationKind.TARGET:
                trading = registry.resolve(
                    definition.kind, definition.type_id, definition.semantic_version, OnlyCalculationBackendKind.TRADING
                )
                if trading.implementation_manifest is None or trading.definition_resolver is None:
                    raise ValueError("RESEARCH_IMPLEMENTATION_UNAVAILABLE")
                if trading.definition_resolver.resolve(definition.parameters, definition.input_bindings) != definition:
                    raise ValueError("RESEARCH_DEFINITION_MISMATCH")
                backend = cast(
                    TradingBackend, cast(OnlyTradingBackendFactory, trading.provider).create(definition, None)
                )
                columns = {
                    name: streaming[reference.node_fingerprint][reference.output_name]
                    if reference.node_fingerprint is not None
                    else inputs[name].to_pylist()
                    for name, reference in definition.input_bindings.items()
                }
                observed: dict[str, list[object]] = {port.name: [] for port in definition.outputs}
                for index in range(len(rows)):
                    observed_row = backend.update({name: column[index] for name, column in columns.items()})
                    if set(observed_row) != set(observed):
                        raise ValueError("RESEARCH_EVALUATION_OUTPUT_INVALID")
                    for name, value in observed_row.items():
                        observed[name].append(value)
                streaming[node.fingerprint] = observed
                trading_implementations[node.fingerprint] = trading.implementation_manifest.implementation_fingerprint
        outputs = [
            {
                "node_fingerprint": key,
                "implementation_fingerprint": implementations[key],
                "values": {
                    name: [None if v is None else format(v, "f") for v in column.to_pylist()]
                    for name, column in workspace[key].items()
                },
            }
            for key in sorted(workspace)
        ]
        result = {
            "schema_version": 1,
            "graph_fingerprint": graph.fingerprint,
            "input_fingerprint": only_canonical_fingerprint(rows),
            "axis": times,
            "outputs": outputs,
        }
        if include_trading:
            result["trading_outputs"] = [
                {
                    "node_fingerprint": key,
                    "implementation_fingerprint": trading_implementations[key],
                    "values": {
                        name: [None if v is None else format(v, "f") for v in column]
                        for name, column in streaming[key].items()
                    },
                }
                for key in sorted(streaming)
            ]
        return result


class GraphEvaluator:
    """Existing single Factor output projection over the shared finite graph math."""

    def __init__(self, source_record: dict[str, Any], graph_record: dict[str, Any], root: str) -> None:
        self.program = CalculationGraphEvaluator([source_record], graph_record)
        node = next((n for n in self.program.graph.nodes if n.fingerprint == root), None)
        if (
            node is None
            or node.definition.type_id != source_record["factor_id"]
            or {p.name for p in node.definition.outputs} != {"value"}
        ):
            raise ValueError("RESEARCH_EVALUATION_ROOT_MISMATCH")
        self.root = root

    def evaluate(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        result = self.program.evaluate(rows)
        result["feature"] = next(
            row["values"]["value"] for row in result["outputs"] if row["node_fingerprint"] == self.root
        )
        return result


def evaluate_graph(
    source_record: dict[str, Any], graph_record: dict[str, Any], rows: list[dict[str, Any]], root: str
) -> dict[str, Any]:
    return GraphEvaluator(source_record, graph_record, root).evaluate(rows)


class NodeProfileEvaluator:
    """Bounded typed factory observations; certification belongs to the Rust owner.

    Import/preflight precedes confinement. Actual source-backed factories and all
    mathematical calls are created/executed only by evaluate after confinement.
    Original Definition references remain exact; inputs here are direct node
    operands, not invented Dataset fields or Kernel facts.
    """

    def __init__(self, sources: list[dict[str, Any]], requests: object, resolved_nodes: object) -> None:
        from onlyalpha.calculation.definition import only_calculation_scalar_from_dict
        from onlyalpha_backend_algorithms.trading_session import TradingGraphSession, _json, _values

        self._factory = TradingGraphSession
        self._validate = _values
        self._encode = _json
        self._sources = sources
        self._entries: list[tuple[OnlyCalculationDefinition, list[tuple[str, list[dict[str, object]], object]]]] = []
        _json(requests)
        if type(requests) is not list or not 1 <= len(requests) <= 128 or type(resolved_nodes) is not list:
            raise ValueError("RESEARCH_NODE_PROFILE_INPUT_INVALID")
        available = {
            row["definition_fingerprint"]: row["definition"]
            for row in resolved_nodes
            if type(row) is dict and type(row.get("definition_fingerprint")) is str
        }
        seen: set[str] = set()
        work = 0
        for request in requests:
            if type(request) is not dict or set(request) != {"definition", "cases"}:
                raise ValueError("RESEARCH_NODE_PROFILE_INPUT_INVALID")
            definition = OnlyCalculationDefinition.from_dict(request["definition"])
            if (
                definition.fingerprint in seen
                or available.get(definition.fingerprint) != request["definition"]
                or _json(dict(definition.to_dict())) != _json(request["definition"])
                or not (
                    definition.kind is OnlyCalculationKind.FACTOR
                    or definition.kind is OnlyCalculationKind.INDICATOR
                    and definition.type_id.startswith("onlyalpha.operator.")
                )
            ):
                raise ValueError("RESEARCH_NODE_PROFILE_DEFINITION_MISMATCH")
            seen.add(definition.fingerprint)
            cases = request["cases"]
            if type(cases) is not list or not 1 <= len(cases) <= 32:
                raise ValueError("RESEARCH_NODE_PROFILE_BUDGET_EXCEEDED")
            names: set[str] = set()
            prepared: list[tuple[str, list[dict[str, object]], object]] = []
            for case in cases:
                if type(case) is not dict or set(case) != {"case_id", "inputs"}:
                    raise ValueError("RESEARCH_NODE_PROFILE_INPUT_INVALID")
                name, rows = case["case_id"], case["inputs"]
                if (
                    type(name) is not str
                    or not name
                    or len(name) > 255
                    or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in name)
                    or name in names
                ):
                    raise ValueError("RESEARCH_NODE_PROFILE_CASE_INVALID")
                names.add(name)
                if type(rows) is not list or not 1 <= len(rows) <= 8192:
                    raise ValueError("RESEARCH_NODE_PROFILE_BUDGET_EXCEEDED")
                work += len(rows)
                if work > 8192:
                    raise ValueError("RESEARCH_NODE_PROFILE_BUDGET_EXCEEDED")
                decoded: list[dict[str, object]] = []
                for row in rows:
                    if type(row) is not dict:
                        raise ValueError("RESEARCH_NODE_PROFILE_INPUT_INVALID")
                    native: dict[str, object] = {
                        key: only_calculation_scalar_from_dict(value) for key, value in row.items()
                    }
                    _values(native, definition.inputs)
                    decoded.append(native)
                prepared.append((name, decoded, rows))
            self._entries.append((definition, sorted(prepared, key=lambda item: item[0])))
        self._entries.sort(key=lambda item: item[0].fingerprint)

    def evaluate(self) -> dict[str, object]:
        from decimal import localcontext

        registry, _ = registry_for_sources(self._sources, ManagedProgramHost())
        result: list[dict[str, object]] = []
        for definition, cases in self._entries:
            research = registry.resolve(
                definition.kind, definition.type_id, definition.semantic_version, OnlyCalculationBackendKind.RESEARCH
            )
            trading = registry.resolve(
                definition.kind, definition.type_id, definition.semantic_version, OnlyCalculationBackendKind.TRADING
            )
            for registration in (research, trading):
                if (
                    registration.definition_resolver is None
                    or registration.implementation_manifest is None
                    or registration.definition_resolver.resolve(definition.parameters, definition.input_bindings)
                    != definition
                ):
                    raise ValueError("RESEARCH_NODE_PROFILE_DEFINITION_MISMATCH")
            actual: list[dict[str, object]] = []
            for name, rows, encoded in cases:
                # Every case starts fresh, including checkpointable delay/rolling
                # factories. No state leaks between controlled mathematical cases.
                session = self._factory(self._sources, {"node": dict(definition.to_dict())})
                arrow_types = {
                    "DECIMAL": pa.decimal128(38, 18),
                    "INTEGER": pa.int64(),
                    "BOOLEAN": pa.bool_(),
                    "STRING": pa.string(),
                }
                columns = {
                    port.name: pa.array([row[port.name] for row in rows], type=arrow_types[port.data_type.value])
                    for port in definition.inputs
                }
                with localcontext(session._context("node")):
                    outputs = cast(ResearchBackend, research.provider).execute(definition, columns)
                if set(outputs) != {port.name for port in definition.outputs} or any(
                    len(column) != len(rows) for column in outputs.values()
                ):
                    raise ValueError("RESEARCH_NODE_PROFILE_OUTPUT_INVALID")
                columns_by_name = {key: column.to_pylist() for key, column in outputs.items()}
                research_rows: list[dict[str, object]] = []
                trading_rows: list[dict[str, object]] = []
                for index, row in enumerate(rows):
                    observed = {key: values[index] for key, values in columns_by_name.items()}
                    self._validate(observed, definition.outputs)
                    research_rows.append({key: _profile_scalar(value) for key, value in observed.items()})
                    updated = session.update("node", row)
                    trading_rows.append({key: _profile_scalar(value) for key, value in updated.items()})
                actual.append(
                    {
                        "case_id": name,
                        "inputs": encoded,
                        "research_outputs": research_rows,
                        "trading_outputs": trading_rows,
                    }
                )
            if research.implementation_manifest is None or trading.implementation_manifest is None:
                raise ValueError("RESEARCH_IMPLEMENTATION_UNAVAILABLE")
            result.append(
                {
                    "node_fingerprint": definition.fingerprint,
                    "research_implementation_fingerprint": research.implementation_manifest.implementation_fingerprint,
                    "trading_implementation_fingerprint": trading.implementation_manifest.implementation_fingerprint,
                    "cases": actual,
                }
            )
        observation = {
            "schema_version": 1,
            "contract": "ONLYALPHA_CALCULATION_NODE_PROFILE_OBSERVATION_V1",
            "nodes": result,
        }
        self._encode(observation)
        return observation


def _profile_scalar(value: object) -> dict[str, object]:
    from onlyalpha.calculation.definition import OnlyCalculationScalar, only_calculation_scalar_to_dict

    result = dict(only_calculation_scalar_to_dict(cast(OnlyCalculationScalar, value)))
    if type(value) is Decimal:
        # Remove representational scale without arithmetic or ambient context.
        # This private observation codec does not change public Definition identity.
        decimal = format(value, "f")
        if "." in decimal:
            decimal = decimal.rstrip("0").rstrip(".")
        result["value"] = "0" if decimal in ("", "-0") else decimal
    return result
