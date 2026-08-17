"""Pure canonical expansion and topological Graph materialization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import product
from types import MappingProxyType

from onlyalpha.calculation.definition import (
    OnlyCalculationScalar,
    OnlyParameterDefinition,
    only_calculation_scalar_sort_key,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.research.job import OnlyResearchJobPlan

from .definition import (
    OnlyResearchSweepDefinition,
    OnlyResearchSweepParameterDimension,
    OnlyResearchSweepParameterTarget,
)
from .errors import OnlyResearchSweepError
from .materialization import OnlyResearchGraphTemplateMaterializer


@dataclass(frozen=True, slots=True)
class OnlyResearchSweepParameterValue:
    target: OnlyResearchSweepParameterTarget
    value: OnlyCalculationScalar


@dataclass(frozen=True, slots=True)
class OnlyResearchSweepCell:
    ordinal: int
    assignment: tuple[OnlyResearchSweepParameterValue, ...]
    calculation_graph: OnlyCalculationGraphDefinition
    job_plan: OnlyResearchJobPlan

    @property
    def calculation_fingerprint(self) -> str:
        return self.job_plan.calculation_fingerprint

    @property
    def assignment_by_key(self) -> Mapping[str, OnlyCalculationScalar]:
        return MappingProxyType({item.target.key: item.value for item in self.assignment})


@dataclass(frozen=True, slots=True)
class OnlyResearchSweepPlan:
    cells: tuple[OnlyResearchSweepCell, ...]

    @property
    def cell_count(self) -> int:
        return len(self.cells)


class OnlyResearchSweepPlanner:
    def __init__(self, calculation_registry: OnlyCalculationRegistry, *, max_cells: int | None = None) -> None:
        if not isinstance(calculation_registry, OnlyCalculationRegistry):
            raise TypeError("Sweep Planner requires the Calculation Registry")
        if max_cells is not None and (isinstance(max_cells, bool) or max_cells <= 0):
            raise ValueError("max_cells must be a positive operational limit")
        self._registry = calculation_registry
        self._materializer = OnlyResearchGraphTemplateMaterializer(calculation_registry)
        self._max_cells = max_cells

    def plan(self, definition: OnlyResearchSweepDefinition) -> OnlyResearchSweepPlan:
        if not isinstance(definition, OnlyResearchSweepDefinition):
            raise OnlyResearchSweepError("SWEEP_DEFINITION_INVALID", "plan requires a Sweep Definition")
        normalized = tuple(self._normalize_dimension(definition, item) for item in definition.dimensions)
        cell_count = 1
        for _, candidates in normalized:
            cell_count *= len(candidates)
        if self._max_cells is not None and cell_count > self._max_cells:
            raise OnlyResearchSweepError(
                "SWEEP_CARDINALITY_EXCEEDED", f"Sweep has {cell_count} cells; operational limit is {self._max_cells}"
            )
        cells: list[OnlyResearchSweepCell] = []
        fingerprints: dict[str, int] = {}
        for ordinal, values in enumerate(product(*(candidates for _, candidates in normalized))):
            assignment = tuple(
                OnlyResearchSweepParameterValue(target, value)
                for (target, _), value in zip(normalized, values, strict=True)
            )
            graph = self._materializer.materialize(
                definition.graph_template, {item.target: item.value for item in assignment}
            ).graph
            job_plan = OnlyResearchJobPlan(definition.dataset_snapshot_fingerprint, graph)
            existing = fingerprints.get(job_plan.calculation_fingerprint)
            if existing is not None:
                raise OnlyResearchSweepError(
                    "SWEEP_DUPLICATE_CELL",
                    f"cells {existing} and {ordinal} materialize the same Calculation identity",
                    ordinal=ordinal,
                    assignment={item.target.key: item.value for item in assignment},
                )
            fingerprints[job_plan.calculation_fingerprint] = ordinal
            cells.append(OnlyResearchSweepCell(ordinal, assignment, graph, job_plan))
        return OnlyResearchSweepPlan(tuple(cells))

    def _normalize_dimension(
        self,
        definition: OnlyResearchSweepDefinition,
        dimension: OnlyResearchSweepParameterDimension,
    ) -> tuple[OnlyResearchSweepParameterTarget, tuple[OnlyCalculationScalar, ...]]:
        node = next(
            (
                item
                for item in definition.graph_template.nodes
                if item.template_node_id == dimension.target.template_node_id
            ),
            None,
        )
        if node is None:
            raise OnlyResearchSweepError(
                "SWEEP_TARGET_NOT_FOUND", f"unknown target node: {dimension.target.template_node_id}"
            )
        try:
            type_definition = self._registry.resolve_type(node.type_reference)
        except ValueError as exc:
            raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", str(exc)) from exc
        parameter = next(
            (item for item in type_definition.parameters.fields if item.name == dimension.target.parameter_name), None
        )
        if parameter is None:
            raise OnlyResearchSweepError("SWEEP_PARAMETER_UNKNOWN", f"unknown parameter target: {dimension.target.key}")
        normalized: list[OnlyCalculationScalar] = []
        for candidate in dimension.candidates:
            try:
                value = parameter.normalize(candidate)
            except (TypeError, ValueError) as exc:
                raise OnlyResearchSweepError("SWEEP_PARAMETER_INVALID", f"{dimension.target.key}: {exc}") from exc
            if any(_semantic_scalar_equal(value, existing) for existing in normalized):
                raise OnlyResearchSweepError(
                    "SWEEP_DUPLICATE_PARAMETER_VALUE", f"duplicate normalized value for {dimension.target.key}"
                )
            normalized.append(value)
        normalized.sort(key=lambda value: _parameter_sort_key(parameter, value))
        return dimension.target, tuple(normalized)


def _semantic_scalar_equal(left: OnlyCalculationScalar, right: OnlyCalculationScalar) -> bool:
    return type(left) is type(right) and left == right


def _parameter_sort_key(parameter: OnlyParameterDefinition, value: OnlyCalculationScalar) -> tuple[str, str]:
    scalar_type, representation = only_calculation_scalar_sort_key(value)
    if parameter.parameter_type.value == "DECIMAL" and value is not None:
        representation = format(value.normalize(), "f")  # type: ignore[union-attr]
    return scalar_type, representation
