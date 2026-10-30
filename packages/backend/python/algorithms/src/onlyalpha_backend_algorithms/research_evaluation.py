"""Pure finite graph arithmetic inside the managed OS sandbox; no business grants."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
from onlyalpha_plugin_operators.registration import registrations
from onlyalpha_plugin_operators.research import OnlyOfficialResearchOperatorBackend

from onlyalpha.calculation.definition import OnlyCalculationBackendKind
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha_backend_algorithms.sdk.private_factor_execution import (
    _ADAPTER_FINGERPRINTS,
    OnlyPrivateFactorAdapterV1,
    OnlyPrivateFactorIsolatedProgramHost,
    OnlyPrivateFactorResearchBackendV1,
    OnlyPrivateFactorSourceArtifactManifestV1,
    only_execute_private_factor_program,
    only_private_factor_backend_registrations,
    only_validate_private_factor_revision,
)
from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1


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


class GraphEvaluator:
    def __init__(self, source_record: dict[str, Any], graph_record: dict[str, Any], root: str) -> None:
        source = OnlyPrivateFactorExecutableSourceRecordV1.from_dict(source_record)
        validation = only_validate_private_factor_revision(source)
        manifest, code = OnlyPrivateFactorSourceArtifactManifestV1.materialize(source, validation)
        graph = OnlyCalculationGraphDefinition.from_dict(graph_record)
        if not 1 <= len(graph.nodes) <= 128:
            raise ValueError("RESEARCH_EVALUATION_BUDGET_EXCEEDED")
        if root not in {n.fingerprint for n in graph.nodes}:
            raise ValueError("RESEARCH_EVALUATION_ROOT_MISMATCH")
        registry = OnlyCalculationRegistry()
        for registration in (
            *registrations(),
            *only_private_factor_backend_registrations(
                source,
                manifest,
                code,
                OnlyPrivateFactorAdapterV1("RESEARCH", _ADAPTER_FINGERPRINTS["RESEARCH"], ManagedProgramHost()),
                OnlyPrivateFactorAdapterV1("TRADING", _ADAPTER_FINGERPRINTS["TRADING"], ManagedProgramHost()),
            ),
        ):
            registry.register(registration)
        self.source, self.graph, self.registry, self.root = source, graph, registry, root
        pa.array([Decimal("1")], type=pa.decimal128(38, 18))

    def evaluate(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not 1 <= len(rows) <= 8192:
            raise ValueError("RESEARCH_EVALUATION_BUDGET_EXCEEDED")
        source, graph, registry, root = self.source, self.graph, self.registry, self.root
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
                    values = [row["values"][reference.source] for row in rows]
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
            workspace[node.fingerprint] = cast(
                OnlyOfficialResearchOperatorBackend | OnlyPrivateFactorResearchBackendV1, registration.provider
            ).execute(definition, inputs)
            implementations[node.fingerprint] = registration.implementation_manifest.implementation_fingerprint
        root_node = next(n for n in graph.nodes if n.fingerprint == root)
        if root_node.definition.type_id != source.factor_id or set(workspace[root]) != {"value"}:
            raise ValueError("RESEARCH_EVALUATION_ROOT_MISMATCH")
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
        return {
            "schema_version": 1,
            "graph_fingerprint": graph.fingerprint,
            "input_fingerprint": only_canonical_fingerprint(rows),
            "axis": times,
            "feature": [None if v is None else format(v, "f") for v in workspace[root]["value"].to_pylist()],
            "outputs": outputs,
        }


def evaluate_graph(
    source_record: dict[str, Any], graph_record: dict[str, Any], rows: list[dict[str, Any]], root: str
) -> dict[str, Any]:
    return GraphEvaluator(source_record, graph_record, root).evaluate(rows)
