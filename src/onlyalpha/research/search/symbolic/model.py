"""Immutable deterministic symbolic Factor-search authority values."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from onlyalpha.calculation import (
    FACTOR_SCORE_SEMANTIC_TYPE,
    FACTOR_VALUE_SEMANTIC_TYPE,
    OnlyCalculationDataType,
    OnlyCalculationKind,
    OnlyCalculationScalar,
    OnlyCalculationTypeReference,
    OnlyOutputDefinition,
    only_calculation_scalar_from_dict,
    only_calculation_scalar_to_dict,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.canonical import only_canonical_fingerprint

SYMBOLIC_SEARCH_SPACE_SCHEMA_VERSION = 1
SYMBOLIC_SEARCH_SPACE_CONTEXT_SCHEMA_VERSION = 2
SYMBOLIC_PROPOSAL_SCHEMA_VERSION = 1
SYMBOLIC_SEARCH_SPACE_KIND = "ONLY_SYMBOLIC_FACTOR_SEARCH_SPACE"
SYMBOLIC_PROPOSAL_KIND = "ONLY_SYMBOLIC_GRAPH_PROPOSAL"
DETERMINISTIC_ENUMERATION_ALGORITHM_ID = "DETERMINISTIC_ENUMERATION"
DETERMINISTIC_ENUMERATION_ALGORITHM_SEMANTIC_VERSION = "1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha(value: object, context: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{context} must be a lower-case SHA256")
    return value


def _identifier(value: object, context: str) -> str:
    if not isinstance(value, str) or not value or any(character.isspace() for character in value):
        raise ValueError(f"{context} must be non-empty without whitespace")
    return value


def _positive(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{context} must be a positive integer")
    return value


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


def _array(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    return value


def _exact(payload: Mapping[str, object], expected: set[str], context: str) -> None:
    if set(payload) != expected:
        raise ValueError(
            f"{context} fields are invalid; missing={sorted(expected - set(payload))}, "
            f"unknown={sorted(set(payload) - expected)}"
        )


def _output_to_dict(output: OnlyOutputDefinition) -> dict[str, object]:
    return {
        "name": output.name,
        "data_type": output.data_type.value,
        "nullable": output.nullable,
        "dimensions": list(output.dimensions),
        "semantic_type": output.semantic_type,
        "unit": output.unit,
    }


def _output_from_dict(payload: Mapping[str, object]) -> OnlyOutputDefinition:
    _exact(payload, {"name", "data_type", "nullable", "dimensions", "semantic_type", "unit"}, "terminal output")
    dimensions = payload["dimensions"]
    nullable = payload["nullable"]
    unit = payload["unit"]
    if (
        not isinstance(payload["name"], str)
        or not isinstance(payload["data_type"], str)
        or not isinstance(nullable, bool)
        or not isinstance(dimensions, list)
        or any(not isinstance(item, str) for item in dimensions)
        or not isinstance(payload["semantic_type"], str)
        or (unit is not None and not isinstance(unit, str))
    ):
        raise ValueError("terminal output fields are invalid")
    return OnlyOutputDefinition(
        payload["name"],
        OnlyCalculationDataType(payload["data_type"]),
        nullable,
        tuple(dimensions),
        payload["semantic_type"],
        unit,
    )


@dataclass(frozen=True, slots=True)
class OnlySymbolicComponentInstanceV1:
    type_reference: OnlyCalculationTypeReference
    normalized_parameters: Mapping[str, OnlyCalculationScalar] = field(default_factory=lambda: MappingProxyType({}))
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.type_reference, OnlyCalculationTypeReference):
            raise ValueError("SEARCH_COMPONENT_INSTANCE_INVALID")
        parameters: dict[str, OnlyCalculationScalar] = {}
        for name, value in self.normalized_parameters.items():
            _identifier(name, "component parameter name")
            # Round-trip through the Calculation scalar authority validates exact scalar types.
            parameters[name] = only_calculation_scalar_from_dict(
                only_calculation_scalar_to_dict(value), "component parameter"
            )
        object.__setattr__(self, "normalized_parameters", MappingProxyType(dict(sorted(parameters.items()))))

    @property
    def component_instance_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.symbolic-component-instance", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "type_reference": dict(self.type_reference.to_dict()),
            "normalized_parameters": {
                name: dict(only_calculation_scalar_to_dict(value)) for name, value in self.normalized_parameters.items()
            },
        }
        if include_fingerprint:
            payload["component_instance_fingerprint"] = self.component_instance_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySymbolicComponentInstanceV1:
        _exact(
            payload,
            {"schema_version", "type_reference", "normalized_parameters", "component_instance_fingerprint"},
            "Symbolic Component Instance",
        )
        parameters = _mapping(payload["normalized_parameters"], "normalized_parameters")
        value = cls(
            OnlyCalculationTypeReference.from_dict(_mapping(payload["type_reference"], "type_reference")),
            {
                name: only_calculation_scalar_from_dict(item, f"component parameter {name}")
                for name, item in parameters.items()
            },
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["component_instance_fingerprint"] != value.component_instance_fingerprint:
            raise ValueError("Symbolic Component Instance identity differs")
        return value


@dataclass(frozen=True, slots=True)
class OnlySymbolicExternalSourceTerminalV1:
    source: str
    output: OnlyOutputDefinition
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.output, OnlyOutputDefinition):
            raise ValueError("SEARCH_EXTERNAL_TERMINAL_INVALID")
        _identifier(self.source, "external source")

    @property
    def terminal_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.symbolic-terminal", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "source": self.source,
            "output": _output_to_dict(self.output),
        }
        if include_fingerprint:
            payload["terminal_fingerprint"] = self.terminal_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySymbolicExternalSourceTerminalV1:
        _exact(payload, {"schema_version", "source", "output", "terminal_fingerprint"}, "external terminal")
        value = cls(
            _identifier(payload["source"], "source"),
            _output_from_dict(_mapping(payload["output"], "output")),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["terminal_fingerprint"] != value.terminal_fingerprint:
            raise ValueError("external terminal identity differs")
        return value


@dataclass(frozen=True, slots=True, order=True)
class OnlySymbolicExternalSourceReferenceV1:
    source_id: str
    source_contract_fingerprint: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("SEARCH_EXTERNAL_SOURCE_REFERENCE_INVALID")
        _identifier(self.source_id, "source_id")
        _sha(self.source_contract_fingerprint, "source_contract_fingerprint")

    @property
    def terminal_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.symbolic-source-reference", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "source_contract_fingerprint": self.source_contract_fingerprint,
        }
        if include_fingerprint:
            payload["terminal_fingerprint"] = self.terminal_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySymbolicExternalSourceReferenceV1:
        _exact(
            payload,
            {"schema_version", "source_id", "source_contract_fingerprint", "terminal_fingerprint"},
            "external source reference",
        )
        value = cls(
            _identifier(payload["source_id"], "source_id"),
            _sha(payload["source_contract_fingerprint"], "source_contract_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["terminal_fingerprint"] != value.terminal_fingerprint:
            raise ValueError("external source reference identity differs")
        return value


@dataclass(frozen=True, slots=True)
class OnlySymbolicCandidateOutputContractV1:
    component_instance_fingerprint: str
    output_name: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("SEARCH_CANDIDATE_OUTPUT_INVALID")
        _sha(self.component_instance_fingerprint, "candidate component instance fingerprint")
        _identifier(self.output_name, "candidate output name")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "component_instance_fingerprint": self.component_instance_fingerprint,
            "output_name": self.output_name,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySymbolicCandidateOutputContractV1:
        _exact(payload, {"schema_version", "component_instance_fingerprint", "output_name"}, "candidate output")
        return cls(
            _sha(payload["component_instance_fingerprint"], "component_instance_fingerprint"),
            _identifier(payload["output_name"], "output_name"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlySymbolicComplexityConstraintsV1:
    max_nodes: int
    max_depth: int
    max_occurrences_per_component: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("SEARCH_COMPLEXITY_INVALID")
        _positive(self.max_nodes, "max_nodes")
        _positive(self.max_depth, "max_depth")
        _positive(self.max_occurrences_per_component, "max_occurrences_per_component")

    def to_dict(self) -> dict[str, int]:
        return {
            "schema_version": self.schema_version,
            "max_nodes": self.max_nodes,
            "max_depth": self.max_depth,
            "max_occurrences_per_component": self.max_occurrences_per_component,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySymbolicComplexityConstraintsV1:
        _exact(
            payload,
            {"schema_version", "max_nodes", "max_depth", "max_occurrences_per_component"},
            "complexity constraints",
        )
        return cls(
            _integer(payload["max_nodes"], "max_nodes"),
            _integer(payload["max_depth"], "max_depth"),
            _integer(payload["max_occurrences_per_component"], "max_occurrences_per_component"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlySymbolicFactorSearchSpaceV1:
    catalog_generation_fingerprint: str
    component_instances: tuple[OnlySymbolicComponentInstanceV1, ...]
    external_source_terminals: tuple[OnlySymbolicExternalSourceTerminalV1, ...]
    candidate_output_contract: OnlySymbolicCandidateOutputContractV1
    complexity_constraints: OnlySymbolicComplexityConstraintsV1
    schema_version: int = SYMBOLIC_SEARCH_SPACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SYMBOLIC_SEARCH_SPACE_SCHEMA_VERSION:
            raise ValueError("SEARCH_SPACE_SCHEMA_UNSUPPORTED")
        _sha(self.catalog_generation_fingerprint, "Catalog Generation fingerprint")
        if not self.component_instances or any(
            not isinstance(item, OnlySymbolicComponentInstanceV1) for item in self.component_instances
        ):
            raise ValueError("SEARCH_SPACE_COMPONENTS_INVALID")
        if not self.external_source_terminals or any(
            not isinstance(item, OnlySymbolicExternalSourceTerminalV1) for item in self.external_source_terminals
        ):
            raise ValueError("SEARCH_SPACE_TERMINALS_INVALID")
        if not isinstance(self.candidate_output_contract, OnlySymbolicCandidateOutputContractV1) or not isinstance(
            self.complexity_constraints, OnlySymbolicComplexityConstraintsV1
        ):
            raise ValueError("SEARCH_SPACE_INVALID")
        components = tuple(sorted(self.component_instances, key=lambda item: item.component_instance_fingerprint))
        terminals = tuple(sorted(self.external_source_terminals, key=lambda item: item.terminal_fingerprint))
        if len({item.component_instance_fingerprint for item in components}) != len(components):
            raise ValueError("SEARCH_SPACE_COMPONENT_DUPLICATE")
        if len({item.terminal_fingerprint for item in terminals}) != len(terminals):
            raise ValueError("SEARCH_SPACE_TERMINAL_DUPLICATE")
        if self.candidate_output_contract.component_instance_fingerprint not in {
            item.component_instance_fingerprint for item in components
        }:
            raise ValueError("SEARCH_CANDIDATE_OUTPUT_INVALID")
        object.__setattr__(self, "component_instances", components)
        object.__setattr__(self, "external_source_terminals", terminals)

    @property
    def search_space_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.symbolic-factor-search-space", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "component_instances": [item.to_dict() for item in self.component_instances],
            "external_source_terminals": [item.to_dict() for item in self.external_source_terminals],
            "candidate_output_contract": self.candidate_output_contract.to_dict(),
            "complexity_constraints": self.complexity_constraints.to_dict(),
        }
        if include_fingerprint:
            payload["search_space_fingerprint"] = self.search_space_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySymbolicFactorSearchSpaceV1:
        _exact(
            payload,
            {
                "schema_version",
                "catalog_generation_fingerprint",
                "component_instances",
                "external_source_terminals",
                "candidate_output_contract",
                "complexity_constraints",
                "search_space_fingerprint",
            },
            "Symbolic Search Space",
        )
        value = cls(
            _sha(payload["catalog_generation_fingerprint"], "catalog_generation_fingerprint"),
            tuple(
                OnlySymbolicComponentInstanceV1.from_dict(_mapping(item, "component instance"))
                for item in _array(payload["component_instances"], "component_instances")
            ),
            tuple(
                OnlySymbolicExternalSourceTerminalV1.from_dict(_mapping(item, "external terminal"))
                for item in _array(payload["external_source_terminals"], "external_source_terminals")
            ),
            OnlySymbolicCandidateOutputContractV1.from_dict(
                _mapping(payload["candidate_output_contract"], "candidate_output_contract")
            ),
            OnlySymbolicComplexityConstraintsV1.from_dict(
                _mapping(payload["complexity_constraints"], "complexity_constraints")
            ),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["search_space_fingerprint"] != value.search_space_fingerprint:
            raise ValueError("Symbolic Search Space identity differs")
        return value


@dataclass(frozen=True, slots=True)
class OnlySymbolicFactorSearchSpaceV2:
    """Search Space with exact references to the Dataset Source Authority."""

    catalog_generation_fingerprint: str
    component_instances: tuple[OnlySymbolicComponentInstanceV1, ...]
    external_source_terminals: tuple[OnlySymbolicExternalSourceReferenceV1, ...]
    candidate_output_contract: OnlySymbolicCandidateOutputContractV1
    complexity_constraints: OnlySymbolicComplexityConstraintsV1
    schema_version: int = SYMBOLIC_SEARCH_SPACE_CONTEXT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SYMBOLIC_SEARCH_SPACE_CONTEXT_SCHEMA_VERSION:
            raise ValueError("SEARCH_SPACE_SCHEMA_UNSUPPORTED")
        _sha(self.catalog_generation_fingerprint, "Catalog Generation fingerprint")
        if not self.component_instances or any(
            not isinstance(item, OnlySymbolicComponentInstanceV1) for item in self.component_instances
        ):
            raise ValueError("SEARCH_SPACE_COMPONENTS_INVALID")
        if not self.external_source_terminals or any(
            not isinstance(item, OnlySymbolicExternalSourceReferenceV1) for item in self.external_source_terminals
        ):
            raise ValueError("SEARCH_SPACE_TERMINALS_INVALID")
        if not isinstance(self.candidate_output_contract, OnlySymbolicCandidateOutputContractV1) or not isinstance(
            self.complexity_constraints, OnlySymbolicComplexityConstraintsV1
        ):
            raise ValueError("SEARCH_SPACE_INVALID")
        components = tuple(sorted(self.component_instances, key=lambda item: item.component_instance_fingerprint))
        terminals = tuple(sorted(self.external_source_terminals, key=lambda item: item.terminal_fingerprint))
        if len({item.component_instance_fingerprint for item in components}) != len(components):
            raise ValueError("SEARCH_SPACE_COMPONENT_DUPLICATE")
        if len({item.source_id for item in terminals}) != len(terminals):
            raise ValueError("SEARCH_SPACE_TERMINAL_DUPLICATE")
        if self.candidate_output_contract.component_instance_fingerprint not in {
            item.component_instance_fingerprint for item in components
        }:
            raise ValueError("SEARCH_CANDIDATE_OUTPUT_INVALID")
        object.__setattr__(self, "component_instances", components)
        object.__setattr__(self, "external_source_terminals", terminals)

    @property
    def search_space_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.symbolic-factor-search-space", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "component_instances": [item.to_dict() for item in self.component_instances],
            "external_source_terminals": [item.to_dict() for item in self.external_source_terminals],
            "candidate_output_contract": self.candidate_output_contract.to_dict(),
            "complexity_constraints": self.complexity_constraints.to_dict(),
        }
        if include_fingerprint:
            payload["search_space_fingerprint"] = self.search_space_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySymbolicFactorSearchSpaceV2:
        _exact(
            payload,
            {
                "schema_version",
                "catalog_generation_fingerprint",
                "component_instances",
                "external_source_terminals",
                "candidate_output_contract",
                "complexity_constraints",
                "search_space_fingerprint",
            },
            "Symbolic Search Space V2",
        )
        value = cls(
            _sha(payload["catalog_generation_fingerprint"], "catalog_generation_fingerprint"),
            tuple(
                OnlySymbolicComponentInstanceV1.from_dict(_mapping(item, "component instance"))
                for item in _array(payload["component_instances"], "component_instances")
            ),
            tuple(
                OnlySymbolicExternalSourceReferenceV1.from_dict(_mapping(item, "external source reference"))
                for item in _array(payload["external_source_terminals"], "external_source_terminals")
            ),
            OnlySymbolicCandidateOutputContractV1.from_dict(
                _mapping(payload["candidate_output_contract"], "candidate_output_contract")
            ),
            OnlySymbolicComplexityConstraintsV1.from_dict(
                _mapping(payload["complexity_constraints"], "complexity_constraints")
            ),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["search_space_fingerprint"] != value.search_space_fingerprint:
            raise ValueError("Symbolic Search Space V2 identity differs")
        return value


OnlySymbolicFactorSearchSpace = OnlySymbolicFactorSearchSpaceV1 | OnlySymbolicFactorSearchSpaceV2


def only_symbolic_search_space_from_dict(payload: Mapping[str, object]) -> OnlySymbolicFactorSearchSpace:
    version = _integer(payload.get("schema_version"), "schema_version")
    if version == SYMBOLIC_SEARCH_SPACE_SCHEMA_VERSION:
        return OnlySymbolicFactorSearchSpaceV1.from_dict(payload)
    if version == SYMBOLIC_SEARCH_SPACE_CONTEXT_SCHEMA_VERSION:
        return OnlySymbolicFactorSearchSpaceV2.from_dict(payload)
    raise ValueError("SEARCH_SPACE_SCHEMA_UNSUPPORTED")


@dataclass(frozen=True, slots=True, order=True)
class OnlySymbolicCandidateOutputReferenceV1:
    node_fingerprint: str
    output_name: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("SEARCH_CANDIDATE_OUTPUT_INVALID")
        _sha(self.node_fingerprint, "candidate node fingerprint")
        _identifier(self.output_name, "candidate output name")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "node_fingerprint": self.node_fingerprint,
            "output_name": self.output_name,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySymbolicCandidateOutputReferenceV1:
        _exact(payload, {"schema_version", "node_fingerprint", "output_name"}, "candidate output reference")
        return cls(
            _sha(payload["node_fingerprint"], "node_fingerprint"),
            _identifier(payload["output_name"], "output_name"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlySymbolicGraphProposalV1:
    search_space_fingerprint: str
    graph: OnlyCalculationGraphDefinition
    candidate_output_reference: OnlySymbolicCandidateOutputReferenceV1
    schema_version: int = SYMBOLIC_PROPOSAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SYMBOLIC_PROPOSAL_SCHEMA_VERSION:
            raise ValueError("SEARCH_PROPOSAL_SCHEMA_UNSUPPORTED")
        _sha(self.search_space_fingerprint, "Search Space fingerprint")
        if not isinstance(self.graph, OnlyCalculationGraphDefinition) or not isinstance(
            self.candidate_output_reference, OnlySymbolicCandidateOutputReferenceV1
        ):
            raise ValueError("SEARCH_PROPOSAL_INVALID")
        node = next(
            (item for item in self.graph.nodes if item.fingerprint == self.candidate_output_reference.node_fingerprint),
            None,
        )
        output = (
            None
            if node is None
            else next(
                (item for item in node.definition.outputs if item.name == self.candidate_output_reference.output_name),
                None,
            )
        )
        if (
            node is None
            or node.definition.kind is not OnlyCalculationKind.FACTOR
            or output is None
            or output.semantic_type not in {FACTOR_VALUE_SEMANTIC_TYPE, FACTOR_SCORE_SEMANTIC_TYPE}
        ):
            raise ValueError("SEARCH_CANDIDATE_OUTPUT_INVALID")

    @property
    def proposal_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.symbolic-graph-proposal", **self.to_dict(include_fingerprint=False)}
        )

    @property
    def graph_fingerprint(self) -> str:
        return self.graph.fingerprint

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "search_space_fingerprint": self.search_space_fingerprint,
            "graph": dict(self.graph.to_dict()),
            "candidate_output_reference": self.candidate_output_reference.to_dict(),
        }
        if include_fingerprint:
            payload["proposal_fingerprint"] = self.proposal_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySymbolicGraphProposalV1:
        _exact(
            payload,
            {
                "schema_version",
                "search_space_fingerprint",
                "graph",
                "candidate_output_reference",
                "proposal_fingerprint",
            },
            "Symbolic Graph Proposal",
        )
        value = cls(
            _sha(payload["search_space_fingerprint"], "search_space_fingerprint"),
            OnlyCalculationGraphDefinition.from_dict(_mapping(payload["graph"], "graph")),
            OnlySymbolicCandidateOutputReferenceV1.from_dict(
                _mapping(payload["candidate_output_reference"], "candidate_output_reference")
            ),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["proposal_fingerprint"] != value.proposal_fingerprint:
            raise ValueError("Symbolic Graph Proposal identity differs")
        return value


__all__ = [name for name in globals() if name.startswith(("OnlySymbolic", "SYMBOLIC_", "DETERMINISTIC_"))]
