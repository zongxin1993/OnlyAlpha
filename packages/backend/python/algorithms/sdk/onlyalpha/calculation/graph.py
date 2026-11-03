"""Canonical calculation DAG validation and identity."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from onlyalpha.calculation.compatibility import only_calculation_output_compatibility
from onlyalpha.calculation.definition import OnlyCalculationDefinition, OnlyCalculationKind
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload

CALCULATION_GRAPH_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class OnlyCalculationNodeDefinition:
    definition: OnlyCalculationDefinition
    alias: str | None = None

    @property
    def fingerprint(self) -> str:
        return self.definition.fingerprint


@dataclass(frozen=True, slots=True)
class OnlyCalculationGraphDefinition:
    nodes: tuple[OnlyCalculationNodeDefinition, ...]
    schema_version: int = CALCULATION_GRAPH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CALCULATION_GRAPH_SCHEMA_VERSION:
            raise ValueError(f"unsupported calculation graph schema version: {self.schema_version}")
        by_fingerprint = {node.fingerprint: node for node in self.nodes}
        if len(by_fingerprint) != len(self.nodes):
            raise ValueError("calculation graph contains duplicate semantic nodes")
        aliases = tuple(node.alias for node in self.nodes if node.alias is not None)
        if len(aliases) != len(set(aliases)):
            raise ValueError("calculation graph contains duplicate aliases")
        kinds = {node.definition.kind for node in self.nodes}
        if OnlyCalculationKind.TARGET in kinds and kinds != {OnlyCalculationKind.TARGET}:
            raise ValueError("Target and Feature calculations require separate graphs")
        state: dict[str, int] = {}

        def visit(fingerprint: str) -> None:
            marker = state.get(fingerprint, 0)
            if marker == 1:
                raise ValueError(f"calculation graph cycle detected at {fingerprint}")
            if marker == 2:
                return
            state[fingerprint] = 1
            node = by_fingerprint[fingerprint]
            contracts = {item.name: item for item in node.definition.inputs}
            for input_name, reference in node.definition.input_bindings.items():
                if reference.node_fingerprint is None:
                    continue
                dependency = by_fingerprint.get(reference.node_fingerprint)
                if dependency is None:
                    raise ValueError(f"calculation graph dependency is missing: {reference.node_fingerprint}")
                if node.definition.kind is OnlyCalculationKind.TARGET:
                    raise ValueError("Target V1 may depend only on external Dataset sources")
                if dependency.definition.kind is OnlyCalculationKind.TARGET:
                    raise ValueError("Feature calculations may not consume Target output")
                outputs = {item.name: item for item in dependency.definition.outputs}
                output = outputs.get(reference.output_name)
                if output is None:
                    raise ValueError(f"calculation graph output is missing: {reference.output_name}")
                expected = contracts[input_name]
                compatibility = only_calculation_output_compatibility(output, expected)
                if not compatibility.compatible:
                    raise ValueError(f"calculation graph input is incompatible: {input_name} ({compatibility.reason})")
                visit(reference.node_fingerprint)
            state[fingerprint] = 2

        for fingerprint in sorted(by_fingerprint):
            visit(fingerprint)

    @property
    def ordered_nodes(self) -> tuple[OnlyCalculationNodeDefinition, ...]:
        by_fingerprint = {node.fingerprint: node for node in self.nodes}
        result: list[OnlyCalculationNodeDefinition] = []
        seen: set[str] = set()

        def append(fingerprint: str) -> None:
            if fingerprint in seen:
                return
            node = by_fingerprint[fingerprint]
            for reference in sorted(
                node.definition.input_bindings.values(),
                key=lambda item: (item.node_fingerprint or "", item.output_name, item.source or ""),
            ):
                if reference.node_fingerprint is not None:
                    append(reference.node_fingerprint)
            seen.add(fingerprint)
            result.append(node)

        for fingerprint in sorted(by_fingerprint):
            append(fingerprint)
        return tuple(result)

    @property
    def fingerprint(self) -> str:
        # Aliases are presentation identity and are intentionally excluded.
        return only_canonical_fingerprint(
            {
                "schema_version": self.schema_version,
                "nodes": [node.definition.semantic_payload() for node in self.ordered_nodes],
            }
        )

    def to_dict(self) -> Mapping[str, object]:
        payload = only_canonical_payload(
            {
                "schema_version": self.schema_version,
                "nodes": [
                    {"definition": node.definition.to_dict(), "alias": node.alias} for node in self.ordered_nodes
                ],
            }
        )
        if not isinstance(payload, Mapping):
            raise TypeError("canonical calculation graph must be an object")
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyCalculationGraphDefinition:
        if set(payload) != {"schema_version", "nodes"}:
            raise ValueError("calculation graph fields are invalid")
        schema_version = payload["schema_version"]
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise ValueError("calculation graph schema_version must be an integer")
        if schema_version != CALCULATION_GRAPH_SCHEMA_VERSION:
            raise ValueError(f"unsupported calculation graph schema version: {schema_version}")
        nodes = payload["nodes"]
        if not isinstance(nodes, list):
            raise ValueError("calculation graph nodes must be an array")
        result: list[OnlyCalculationNodeDefinition] = []
        for item in nodes:
            if not isinstance(item, Mapping) or set(item) != {"definition", "alias"}:
                raise ValueError("calculation graph node fields are invalid")
            definition = item["definition"]
            alias = item["alias"]
            if not isinstance(definition, Mapping):
                raise ValueError("calculation graph node definition must be an object")
            if alias is not None and not isinstance(alias, str):
                raise ValueError("calculation graph node alias must be a string or null")
            result.append(
                OnlyCalculationNodeDefinition(
                    OnlyCalculationDefinition.from_dict(cast(Mapping[str, object], definition)), alias
                )
            )
        return cls(tuple(result), schema_version)
