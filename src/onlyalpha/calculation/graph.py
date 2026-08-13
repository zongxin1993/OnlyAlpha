"""Canonical calculation DAG validation and identity."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.calculation.definition import OnlyCalculationDataType, OnlyCalculationDefinition
from onlyalpha.canonical import only_canonical_fingerprint


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
    schema_version: int = 1

    def __post_init__(self) -> None:
        by_fingerprint = {node.fingerprint: node for node in self.nodes}
        if len(by_fingerprint) != len(self.nodes):
            raise ValueError("calculation graph contains duplicate semantic nodes")
        aliases = tuple(node.alias for node in self.nodes if node.alias is not None)
        if len(aliases) != len(set(aliases)):
            raise ValueError("calculation graph contains duplicate aliases")
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
                outputs = {item.name: item for item in dependency.definition.outputs}
                output = outputs.get(reference.output_name)
                if output is None:
                    raise ValueError(f"calculation graph output is missing: {reference.output_name}")
                expected = contracts[input_name]
                if not _compatible(expected.data_type, expected.nullable, output.data_type, output.nullable):
                    raise ValueError(f"calculation graph input is incompatible: {input_name}")
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


def _compatible(
    expected_type: OnlyCalculationDataType,
    expected_nullable: bool,
    actual_type: OnlyCalculationDataType,
    actual_nullable: bool,
) -> bool:
    return expected_type is actual_type and (expected_nullable or not actual_nullable)
