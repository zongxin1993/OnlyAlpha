"""Serializable pre-materialization Calculation Graph Template contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import cast

from onlyalpha.calculation import (
    OnlyCalculationScalar,
    OnlyCalculationTypeReference,
    only_calculation_scalar_from_dict,
    only_calculation_scalar_to_dict,
)

from .errors import OnlyResearchSweepError

RESEARCH_GRAPH_TEMPLATE_SCHEMA_VERSION = 1


def _identifier(value: object, context: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", f"{context} must be non-empty without whitespace")
    return value


def _scalar(value: object, context: str) -> OnlyCalculationScalar:
    if (
        value is None
        or isinstance(value, (str, bool, Decimal))
        or (isinstance(value, int) and not isinstance(value, bool))
    ):
        return value
    raise OnlyResearchSweepError("SWEEP_PARAMETER_INVALID", f"{context} must use a type-preserving Calculation scalar")


def _exact(payload: Mapping[str, object], expected: set[str], context: str) -> None:
    if set(payload) != expected:
        raise OnlyResearchSweepError(
            "SWEEP_TEMPLATE_INVALID",
            f"{context} fields are invalid; missing={sorted(expected - set(payload))}, unknown={sorted(set(payload) - expected)}",
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchTemplateReference:
    template_node_id: str | None
    output_name: str
    source: str | None = None

    def __post_init__(self) -> None:
        if (self.template_node_id is None) == (self.source is None):
            raise OnlyResearchSweepError(
                "SWEEP_TEMPLATE_DEPENDENCY_INVALID", "template reference must select exactly one node or source"
            )
        _identifier(self.output_name, "template output_name")
        if self.template_node_id is not None:
            _identifier(self.template_node_id, "template_node_id")
        if self.source is not None:
            _identifier(self.source, "template source")

    def to_dict(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "template_node_id": self.template_node_id,
                "output_name": self.output_name,
                "source": self.source,
            }
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchTemplateReference:
        _exact(payload, {"template_node_id", "output_name", "source"}, "template reference")
        node_id, output_name, source = payload["template_node_id"], payload["output_name"], payload["source"]
        if node_id is not None and not isinstance(node_id, str):
            raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", "template_node_id must be a string or null")
        if not isinstance(output_name, str) or (source is not None and not isinstance(source, str)):
            raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", "template reference scalar fields are invalid")
        return cls(node_id, output_name, source)


@dataclass(frozen=True, slots=True)
class OnlyResearchTemplateInputBinding:
    input_name: str
    reference: OnlyResearchTemplateReference

    def __post_init__(self) -> None:
        _identifier(self.input_name, "template input_name")
        if not isinstance(self.reference, OnlyResearchTemplateReference):
            raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", "template input reference is invalid")

    def to_dict(self) -> Mapping[str, object]:
        return MappingProxyType({"input_name": self.input_name, "reference": self.reference.to_dict()})

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchTemplateInputBinding:
        _exact(payload, {"input_name", "reference"}, "template input binding")
        if not isinstance(payload["input_name"], str) or not isinstance(payload["reference"], Mapping):
            raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", "template input binding fields are invalid")
        return cls(
            payload["input_name"],
            OnlyResearchTemplateReference.from_dict(cast(Mapping[str, object], payload["reference"])),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchGraphTemplateNode:
    template_node_id: str
    type_reference: OnlyCalculationTypeReference
    parameters: Mapping[str, OnlyCalculationScalar] = field(default_factory=lambda: MappingProxyType({}))
    input_bindings: tuple[OnlyResearchTemplateInputBinding, ...] = ()
    alias: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.template_node_id, "template_node_id")
        if not isinstance(self.type_reference, OnlyCalculationTypeReference):
            raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", "template node exact type reference is invalid")
        if self.alias is not None:
            _identifier(self.alias, "template alias")
        parameters = {str(name): _scalar(value, f"parameter {name}") for name, value in self.parameters.items()}
        if any(not name or any(char.isspace() for char in name) for name in parameters):
            raise OnlyResearchSweepError("SWEEP_PARAMETER_INVALID", "parameter names must be non-empty")
        names = tuple(item.input_name for item in self.input_bindings)
        if len(names) != len(set(names)):
            raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", "template node has duplicate input targets")
        object.__setattr__(self, "parameters", MappingProxyType(dict(sorted(parameters.items()))))
        object.__setattr__(self, "input_bindings", tuple(sorted(self.input_bindings, key=lambda item: item.input_name)))

    def to_dict(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "template_node_id": self.template_node_id,
                "type_reference": self.type_reference.to_dict(),
                "parameters": {name: only_calculation_scalar_to_dict(value) for name, value in self.parameters.items()},
                "input_bindings": [item.to_dict() for item in self.input_bindings],
                "alias": self.alias,
            }
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchGraphTemplateNode:
        _exact(
            payload,
            {"template_node_id", "type_reference", "parameters", "input_bindings", "alias"},
            "template node",
        )
        node_id, reference, parameters, bindings, alias = (
            payload["template_node_id"],
            payload["type_reference"],
            payload["parameters"],
            payload["input_bindings"],
            payload["alias"],
        )
        if (
            not isinstance(node_id, str)
            or not isinstance(reference, Mapping)
            or not isinstance(parameters, Mapping)
            or not isinstance(bindings, list)
            or (alias is not None and not isinstance(alias, str))
        ):
            raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", "template node fields are invalid")
        return cls(
            node_id,
            OnlyCalculationTypeReference.from_dict(cast(Mapping[str, object], reference)),
            {
                str(name): only_calculation_scalar_from_dict(value, f"template parameter {name}")
                for name, value in parameters.items()
            },
            tuple(
                OnlyResearchTemplateInputBinding.from_dict(cast(Mapping[str, object], item))
                if isinstance(item, Mapping)
                else (_raise_invalid_binding())
                for item in bindings
            ),
            alias,
        )


def _raise_invalid_binding() -> OnlyResearchTemplateInputBinding:
    raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", "template input binding must be an object")


@dataclass(frozen=True, slots=True)
class OnlyResearchGraphTemplate:
    nodes: tuple[OnlyResearchGraphTemplateNode, ...]
    schema_version: int = RESEARCH_GRAPH_TEMPLATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version != RESEARCH_GRAPH_TEMPLATE_SCHEMA_VERSION:
            raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", "unsupported Graph Template schema version")
        if not self.nodes:
            raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", "Graph Template cannot be empty")
        ids = tuple(node.template_node_id for node in self.nodes)
        if len(ids) != len(set(ids)):
            raise OnlyResearchSweepError("SWEEP_TEMPLATE_NODE_DUPLICATE", "duplicate TemplateNodeId")
        known = set(ids)
        state: dict[str, int] = {}
        by_id = {node.template_node_id: node for node in self.nodes}

        def visit(node_id: str) -> None:
            if state.get(node_id) == 1:
                raise OnlyResearchSweepError("SWEEP_TEMPLATE_DEPENDENCY_INVALID", "Graph Template contains a cycle")
            if state.get(node_id) == 2:
                return
            state[node_id] = 1
            for binding in by_id[node_id].input_bindings:
                dependency = binding.reference.template_node_id
                if dependency is None:
                    continue
                if dependency == node_id:
                    raise OnlyResearchSweepError("SWEEP_TEMPLATE_DEPENDENCY_INVALID", "self dependency is invalid")
                if dependency not in known:
                    raise OnlyResearchSweepError(
                        "SWEEP_TEMPLATE_DEPENDENCY_INVALID", f"unknown dependency node: {dependency}"
                    )
                visit(dependency)
            state[node_id] = 2

        for node_id in sorted(known):
            visit(node_id)
        object.__setattr__(self, "nodes", tuple(sorted(self.nodes, key=lambda node: node.template_node_id)))

    @property
    def ordered_nodes(self) -> tuple[OnlyResearchGraphTemplateNode, ...]:
        by_id = {node.template_node_id: node for node in self.nodes}
        result: list[OnlyResearchGraphTemplateNode] = []
        seen: set[str] = set()

        def append(node_id: str) -> None:
            if node_id in seen:
                return
            node = by_id[node_id]
            dependencies = sorted(
                binding.reference.template_node_id
                for binding in node.input_bindings
                if binding.reference.template_node_id is not None
            )
            for dependency in dependencies:
                append(dependency)
            seen.add(node_id)
            result.append(node)

        for node_id in sorted(by_id):
            append(node_id)
        return tuple(result)

    def to_dict(self) -> Mapping[str, object]:
        return MappingProxyType(
            {"schema_version": self.schema_version, "nodes": [node.to_dict() for node in self.nodes]}
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchGraphTemplate:
        _exact(payload, {"schema_version", "nodes"}, "Graph Template")
        schema_version, nodes = payload["schema_version"], payload["nodes"]
        if isinstance(schema_version, bool) or not isinstance(schema_version, int) or not isinstance(nodes, list):
            raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", "Graph Template fields are invalid")
        return cls(
            tuple(
                OnlyResearchGraphTemplateNode.from_dict(cast(Mapping[str, object], item))
                if isinstance(item, Mapping)
                else (_raise_invalid_node())
                for item in nodes
            ),
            schema_version,
        )


def _raise_invalid_node() -> OnlyResearchGraphTemplateNode:
    raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", "template node must be an object")
