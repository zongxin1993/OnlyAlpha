"""Pure deterministic Research Specification to existing P7 plan resolution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import NoReturn

from onlyalpha.calculation import (
    FACTOR_SCORE_SEMANTIC_TYPE,
    FACTOR_VALUE_SEMANTIC_TYPE,
    TARGET_VALUE_SEMANTIC_TYPE,
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationScalar,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.research.evaluation.plan import OnlyResearchStatisticsPlan
from onlyalpha.research.evaluation.reference import (
    OnlyResearchFeatureSeriesReference,
    OnlyResearchTargetSeriesReference,
)
from onlyalpha.research.job import OnlyResearchJobPlan
from onlyalpha.research.result.plan import OnlyResearchResultPlan
from onlyalpha.research.sweep.definition import OnlyResearchSweepDefinition
from onlyalpha.research.sweep.errors import OnlyResearchSweepError
from onlyalpha.research.sweep.materialization import OnlyResearchGraphTemplateMaterializer
from onlyalpha.research.sweep.planning import (
    OnlyResearchSweepPlan,
    OnlyResearchSweepPlanner,
)
from onlyalpha.research.workload import OnlyResearchWorkloadPlan

from .errors import OnlyResearchSpecificationError, OnlyResearchSpecificationPhase
from .model import OnlyResearchSeriesSelector, OnlyResearchSpecification, OnlyResearchStatisticsSpec


@dataclass(frozen=True, slots=True)
class OnlyResearchCandidateLineage:
    calculation_id: str
    assignment: Mapping[str, OnlyCalculationScalar]
    graph: OnlyCalculationGraphDefinition
    graph_fingerprint: str
    calculation_fingerprint: str
    node_fingerprints: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "assignment", MappingProxyType(dict(sorted(self.assignment.items()))))
        object.__setattr__(self, "node_fingerprints", MappingProxyType(dict(sorted(self.node_fingerprints.items()))))


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticsLineage:
    statistics_fingerprint: str
    feature: OnlyResearchCandidateLineage
    target: OnlyResearchCandidateLineage


@dataclass(frozen=True, slots=True)
class OnlyResearchSpecificationResolution:
    specification_fingerprint: str
    workload: OnlyResearchWorkloadPlan
    candidates: tuple[OnlyResearchCandidateLineage, ...]
    statistics: tuple[OnlyResearchStatisticsLineage, ...]


class OnlyResearchSpecificationResolver:
    def __init__(self, calculation_registry: OnlyCalculationRegistry, *, max_cells: int | None = None) -> None:
        if not isinstance(calculation_registry, OnlyCalculationRegistry):
            raise TypeError("Specification Resolver requires the Calculation Registry")
        self._registry = calculation_registry
        self._materializer = OnlyResearchGraphTemplateMaterializer(calculation_registry)
        self._sweep_planner = OnlyResearchSweepPlanner(calculation_registry, max_cells=max_cells)

    def resolve(self, specification: OnlyResearchSpecification) -> OnlyResearchSpecificationResolution:
        if not isinstance(specification, OnlyResearchSpecification):
            self._fail(
                OnlyResearchSpecificationPhase.SCHEMA,
                "RESEARCH_SPEC_INVALID",
                "resolve requires a Research Specification",
            )
        direct_jobs: list[OnlyResearchJobPlan] = []
        sweeps: list[OnlyResearchSweepPlan] = []
        candidates: dict[str, list[OnlyResearchCandidateLineage]] = {}
        for calculation in specification.calculations:
            self._admit_types(calculation.graph_template.nodes)
            if calculation.sweep_dimensions:
                definition = OnlyResearchSweepDefinition(
                    specification.dataset_snapshot_fingerprint,
                    calculation.graph_template,
                    calculation.sweep_dimensions,
                )
                try:
                    sweep = self._sweep_planner.plan(definition)
                except OnlyResearchSweepError as exc:
                    code = (
                        "RESEARCH_SPEC_SWEEP_CARDINALITY_EXCEEDED"
                        if exc.code == "SWEEP_CARDINALITY_EXCEEDED"
                        else "RESEARCH_SPEC_SWEEP_INVALID"
                    )
                    self._fail(OnlyResearchSpecificationPhase.SWEEP_RESOLUTION, code, str(exc), exc)
                sweeps.append(sweep)
                lineages = []
                for cell in sweep.cells:
                    evidence = self._materializer.materialize(
                        calculation.graph_template, {item.target: item.value for item in cell.assignment}
                    )
                    lineages.append(
                        OnlyResearchCandidateLineage(
                            calculation.calculation_id,
                            cell.assignment_by_key,
                            evidence.graph,
                            evidence.graph.fingerprint,
                            cell.calculation_fingerprint,
                            evidence.node_fingerprints,
                        )
                    )
                candidates[calculation.calculation_id] = lineages
            else:
                try:
                    evidence = self._materializer.materialize(calculation.graph_template)
                    job = OnlyResearchJobPlan(specification.dataset_snapshot_fingerprint, evidence.graph)
                except (OnlyResearchSweepError, TypeError, ValueError) as exc:
                    self._fail(
                        OnlyResearchSpecificationPhase.GRAPH_RESOLUTION,
                        "RESEARCH_SPEC_GRAPH_MATERIALIZATION_FAILED",
                        str(exc),
                        exc,
                    )
                direct_jobs.append(job)
                candidates[calculation.calculation_id] = [
                    OnlyResearchCandidateLineage(
                        calculation.calculation_id,
                        {},
                        evidence.graph,
                        evidence.graph.fingerprint,
                        job.calculation_fingerprint,
                        evidence.node_fingerprints,
                    )
                ]

        plans: list[OnlyResearchStatisticsPlan] = []
        statistics_lineage: list[OnlyResearchStatisticsLineage] = []
        for statistics_spec in specification.statistics:
            feature = self._select(candidates, statistics_spec.feature, feature=True)
            target = self._select(candidates, statistics_spec.target, feature=False)
            pairs = self._broadcast(feature, target)
            for feature_candidate, target_candidate in pairs:
                plan = self._statistics_plan(statistics_spec, feature_candidate, target_candidate)
                plans.append(plan)
                statistics_lineage.append(
                    OnlyResearchStatisticsLineage(plan.statistics_fingerprint, feature_candidate, target_candidate)
                )
        fingerprints = tuple(item.statistics_fingerprint for item in plans)
        if len(fingerprints) != len(set(fingerprints)):
            self._fail(
                OnlyResearchSpecificationPhase.STATISTICS_RESOLUTION,
                "RESEARCH_SPEC_DUPLICATE_STATISTICS",
                "multiple Statistics Specifications resolve to the same Statistics identity",
            )
        try:
            workload = OnlyResearchWorkloadPlan(
                tuple(direct_jobs), tuple(sweeps), tuple(plans), OnlyResearchResultPlan(fingerprints)
            )
        except Exception as exc:
            self._fail(
                OnlyResearchSpecificationPhase.WORKLOAD_VALIDATION,
                "RESEARCH_SPEC_WORKLOAD_INVALID",
                str(exc),
                exc,
            )
        ordered_candidates = tuple(item for key in sorted(candidates) for item in candidates[key])
        return OnlyResearchSpecificationResolution(
            specification.specification_fingerprint,
            workload,
            ordered_candidates,
            tuple(statistics_lineage),
        )

    def _admit_types(self, nodes: Iterable[object]) -> None:
        for node in nodes:
            reference = node.type_reference  # type: ignore[attr-defined]
            try:
                self._registry.resolve_type(reference)
            except ValueError as exc:
                code = (
                    "RESEARCH_SPEC_CALCULATION_VERSION_UNKNOWN"
                    if "semantic version" in str(exc)
                    else "RESEARCH_SPEC_CALCULATION_TYPE_UNKNOWN"
                )
                self._fail(OnlyResearchSpecificationPhase.TYPE_RESOLUTION, code, str(exc), exc)
            try:
                self._registry.resolve(
                    reference.kind,
                    reference.type_id,
                    reference.semantic_version,
                    OnlyCalculationBackendKind.RESEARCH,
                )
            except ValueError as exc:
                self._fail(
                    OnlyResearchSpecificationPhase.TYPE_RESOLUTION,
                    "RESEARCH_SPEC_RESEARCH_BACKEND_UNAVAILABLE",
                    str(exc),
                    exc,
                )

    def _select(
        self,
        candidates: Mapping[str, list[OnlyResearchCandidateLineage]],
        selector: OnlyResearchSeriesSelector,
        *,
        feature: bool,
    ) -> tuple[OnlyResearchCandidateLineage, ...]:
        selected = candidates.get(selector.calculation_id)
        if selected is None:
            self._fail(
                OnlyResearchSpecificationPhase.SERIES_RESOLUTION,
                "RESEARCH_SPEC_SERIES_REFERENCE_UNKNOWN",
                f"unknown calculation_id: {selector.calculation_id}",
            )
        for candidate in selected:
            node_fingerprint = candidate.node_fingerprints.get(selector.template_node_id)
            if node_fingerprint is None:
                self._fail(
                    OnlyResearchSpecificationPhase.SERIES_RESOLUTION,
                    "RESEARCH_SPEC_SERIES_REFERENCE_UNKNOWN",
                    f"unknown template_node_id: {selector.template_node_id}",
                )
            graph = candidate.graph
            node = next(item for item in graph.nodes if item.fingerprint == node_fingerprint)
            output = next((item for item in node.definition.outputs if item.name == selector.output_name), None)
            if output is None:
                self._fail(
                    OnlyResearchSpecificationPhase.SERIES_RESOLUTION,
                    "RESEARCH_SPEC_SERIES_REFERENCE_UNKNOWN",
                    f"unknown output_name: {selector.output_name}",
                )
            allowed = (
                {FACTOR_VALUE_SEMANTIC_TYPE, FACTOR_SCORE_SEMANTIC_TYPE} if feature else {TARGET_VALUE_SEMANTIC_TYPE}
            )
            expected_kind = OnlyCalculationKind.FACTOR if feature else OnlyCalculationKind.TARGET
            if node.definition.kind is not expected_kind or output.semantic_type not in allowed:
                self._fail(
                    OnlyResearchSpecificationPhase.SERIES_RESOLUTION,
                    "RESEARCH_SPEC_FEATURE_SEMANTIC_INVALID" if feature else "RESEARCH_SPEC_TARGET_SEMANTIC_INVALID",
                    f"{selector.template_node_id}.{selector.output_name} has incompatible semantics",
                )
        return tuple(selected)

    def _broadcast(
        self,
        feature: tuple[OnlyResearchCandidateLineage, ...],
        target: tuple[OnlyResearchCandidateLineage, ...],
    ) -> tuple[tuple[OnlyResearchCandidateLineage, OnlyResearchCandidateLineage], ...]:
        if len(feature) > 1 and len(target) > 1:
            self._fail(
                OnlyResearchSpecificationPhase.STATISTICS_RESOLUTION,
                "RESEARCH_SPEC_STATISTICS_EXPANSION_AMBIGUOUS",
                "BROADCAST_SINGLETON does not define many-to-many expansion",
            )
        count = max(len(feature), len(target))
        return tuple(
            (feature[0 if len(feature) == 1 else index], target[0 if len(target) == 1 else index])
            for index in range(count)
        )

    @staticmethod
    def _statistics_plan(
        spec: OnlyResearchStatisticsSpec,
        feature: OnlyResearchCandidateLineage,
        target: OnlyResearchCandidateLineage,
    ) -> OnlyResearchStatisticsPlan:
        feature_node = feature.node_fingerprints[spec.feature.template_node_id]
        target_node = target.node_fingerprints[spec.target.template_node_id]
        return OnlyResearchStatisticsPlan(
            OnlyResearchFeatureSeriesReference(feature.calculation_fingerprint, feature_node, spec.feature.output_name),
            OnlyResearchTargetSeriesReference(target.calculation_fingerprint, target_node, spec.target.output_name),
            spec.definition,
        )

    @staticmethod
    def _fail(
        phase: OnlyResearchSpecificationPhase,
        code: str,
        detail: str,
        cause: Exception | None = None,
    ) -> NoReturn:
        error = OnlyResearchSpecificationError(phase, code, detail)
        if cause is None:
            raise error
        raise error from cause
