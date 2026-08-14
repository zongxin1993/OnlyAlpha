"""Finite explicit parameter-space contract for one Research Sweep."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from onlyalpha.calculation import (
    OnlyCalculationScalar,
    only_calculation_scalar_from_dict,
    only_calculation_scalar_sort_key,
    only_calculation_scalar_to_dict,
)
from onlyalpha.research.dataset.strict import require_sha256

from .errors import OnlyResearchSweepError
from .template import OnlyResearchGraphTemplate, _exact, _identifier, _scalar

RESEARCH_SWEEP_DEFINITION_SCHEMA_VERSION = 1


@dataclass(frozen=True, order=True, slots=True)
class OnlyResearchSweepParameterTarget:
    template_node_id: str
    parameter_name: str

    def __post_init__(self) -> None:
        _identifier(self.template_node_id, "parameter target template_node_id")
        _identifier(self.parameter_name, "parameter target parameter_name")

    @property
    def key(self) -> str:
        return f"{self.template_node_id}.{self.parameter_name}"

    def to_dict(self) -> Mapping[str, object]:
        return MappingProxyType({"template_node_id": self.template_node_id, "parameter_name": self.parameter_name})

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchSweepParameterTarget:
        _exact(payload, {"template_node_id", "parameter_name"}, "Sweep parameter target")
        if not isinstance(payload["template_node_id"], str) or not isinstance(payload["parameter_name"], str):
            raise OnlyResearchSweepError("SWEEP_DEFINITION_INVALID", "Sweep parameter target fields are invalid")
        return cls(payload["template_node_id"], payload["parameter_name"])


@dataclass(frozen=True, slots=True)
class OnlyResearchSweepParameterDimension:
    target: OnlyResearchSweepParameterTarget
    candidates: tuple[OnlyCalculationScalar, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.target, OnlyResearchSweepParameterTarget):
            raise OnlyResearchSweepError("SWEEP_DEFINITION_INVALID", "Sweep parameter target is invalid")
        if not self.candidates:
            raise OnlyResearchSweepError("SWEEP_PARAMETER_INVALID", "Sweep parameter candidates cannot be empty")
        candidates = tuple(_scalar(value, f"candidate for {self.target.key}") for value in self.candidates)
        object.__setattr__(self, "candidates", tuple(sorted(candidates, key=only_calculation_scalar_sort_key)))

    def to_dict(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "target": self.target.to_dict(),
                "candidates": [only_calculation_scalar_to_dict(value) for value in self.candidates],
            }
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchSweepParameterDimension:
        _exact(payload, {"target", "candidates"}, "Sweep parameter dimension")
        target, candidates = payload["target"], payload["candidates"]
        if not isinstance(target, Mapping) or not isinstance(candidates, list):
            raise OnlyResearchSweepError("SWEEP_DEFINITION_INVALID", "Sweep parameter dimension fields are invalid")
        return cls(
            OnlyResearchSweepParameterTarget.from_dict(cast(Mapping[str, object], target)),
            tuple(only_calculation_scalar_from_dict(item, "Sweep candidate") for item in candidates),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchSweepDefinition:
    dataset_snapshot_fingerprint: str
    graph_template: OnlyResearchGraphTemplate
    dimensions: tuple[OnlyResearchSweepParameterDimension, ...]
    schema_version: int = RESEARCH_SWEEP_DEFINITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        try:
            require_sha256(
                {"dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint},
                "dataset_snapshot_fingerprint",
                "Research Sweep Definition",
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyResearchSweepError("SWEEP_DEFINITION_INVALID", str(exc)) from exc
        if not isinstance(self.graph_template, OnlyResearchGraphTemplate):
            raise OnlyResearchSweepError("SWEEP_DEFINITION_INVALID", "Sweep Graph Template is invalid")
        if isinstance(self.schema_version, bool) or self.schema_version != RESEARCH_SWEEP_DEFINITION_SCHEMA_VERSION:
            raise OnlyResearchSweepError("SWEEP_DEFINITION_INVALID", "unsupported Sweep Definition schema version")
        if not self.dimensions:
            raise OnlyResearchSweepError("SWEEP_DEFINITION_INVALID", "Sweep requires at least one parameter dimension")
        targets = tuple(dimension.target for dimension in self.dimensions)
        if len(targets) != len(set(targets)):
            raise OnlyResearchSweepError("SWEEP_DUPLICATE_PARAMETER_TARGET", "duplicate Sweep parameter target")
        object.__setattr__(self, "dimensions", tuple(sorted(self.dimensions, key=lambda item: item.target)))

    def to_dict(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "schema_version": self.schema_version,
                "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
                "graph_template": self.graph_template.to_dict(),
                "dimensions": [dimension.to_dict() for dimension in self.dimensions],
            }
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchSweepDefinition:
        _exact(
            payload,
            {"schema_version", "dataset_snapshot_fingerprint", "graph_template", "dimensions"},
            "Sweep Definition",
        )
        schema_version, dataset, template, dimensions = (
            payload["schema_version"],
            payload["dataset_snapshot_fingerprint"],
            payload["graph_template"],
            payload["dimensions"],
        )
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or not isinstance(dataset, str)
            or not isinstance(template, Mapping)
            or not isinstance(dimensions, list)
        ):
            raise OnlyResearchSweepError("SWEEP_DEFINITION_INVALID", "Sweep Definition fields are invalid")
        return cls(
            dataset,
            OnlyResearchGraphTemplate.from_dict(cast(Mapping[str, object], template)),
            tuple(
                OnlyResearchSweepParameterDimension.from_dict(cast(Mapping[str, object], item))
                if isinstance(item, Mapping)
                else (_raise_invalid_dimension())
                for item in dimensions
            ),
            schema_version,
        )


def _raise_invalid_dimension() -> OnlyResearchSweepParameterDimension:
    raise OnlyResearchSweepError("SWEEP_DEFINITION_INVALID", "Sweep dimension must be an object")
