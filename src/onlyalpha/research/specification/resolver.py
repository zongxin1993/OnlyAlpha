"""Pure deterministic Research Specification to existing P7 plan resolution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import NoReturn

from onlyalpha.calculation import (
    FACTOR_SCORE_SEMANTIC_TYPE,
    FACTOR_VALUE_SEMANTIC_TYPE,
    TARGET_VALUE_SEMANTIC_TYPE,
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationScalar,
    OnlyOutputDefinition,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.research.evaluation.plan import OnlyResearchStatisticsPlan
from onlyalpha.research.evaluation.reference import (
    OnlyResearchFeatureSeriesReference,
    OnlyResearchTargetSeriesReference,
)
from onlyalpha.research.job import OnlyResearchJobPlan
from onlyalpha.research.result.identity import RESEARCH_RESULT_SCIENTIFIC_PLAN_SCHEMA_VERSION
from onlyalpha.research.result.plan import (
    OnlyResearchResultCalculationPlan,
    OnlyResearchResultCandidatePlan,
    OnlyResearchResultPlan,
    OnlyResearchResultSeriesPlan,
    OnlyResearchResultSignalPlan,
)
from onlyalpha.research.sweep.definition import OnlyResearchSweepDefinition
from onlyalpha.research.sweep.errors import OnlyResearchSweepError
from onlyalpha.research.sweep.materialization import OnlyResearchGraphTemplateMaterializer
from onlyalpha.research.sweep.planning import (
    OnlyResearchSweepPlan,
    OnlyResearchSweepPlanner,
)
from onlyalpha.research.workload import OnlyResearchWorkloadPlan

from .errors import OnlyResearchSpecificationError, OnlyResearchSpecificationPhase
from .identity import only_research_candidate_fingerprint
from .model import (
    OnlyResearchScientificEvidenceSpec,
    OnlyResearchSeriesSelector,
    OnlyResearchSpecification,
    OnlyResearchStatisticsSpec,
)


@dataclass(frozen=True, slots=True)
class OnlyResearchCandidateLineage:
    calculation_id: str
    assignment: Mapping[str, OnlyCalculationScalar]
    graph: OnlyCalculationGraphDefinition
    graph_fingerprint: str
    calculation_fingerprint: str
    node_fingerprints: Mapping[str, str]
    candidate_fingerprint: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "assignment", MappingProxyType(dict(sorted(self.assignment.items()))))
        object.__setattr__(self, "node_fingerprints", MappingProxyType(dict(sorted(self.node_fingerprints.items()))))


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticsLineage:
    statistics_fingerprint: str
    feature: OnlyResearchCandidateLineage
    target: OnlyResearchCandidateLineage


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchPublishedSeriesLineage:
    candidate_fingerprint: str | None
    calculation_fingerprint: str
    node_fingerprint: str
    output_name: str


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchSignalLineage:
    role: str
    candidate_fingerprint: str
    calculation_fingerprint: str
    node_fingerprint: str
    output_name: str


@dataclass(frozen=True, slots=True)
class OnlyResearchSpecificationResolution:
    specification_fingerprint: str
    workload: OnlyResearchWorkloadPlan
    candidates: tuple[OnlyResearchCandidateLineage, ...]
    statistics: tuple[OnlyResearchStatisticsLineage, ...]
    published_series: tuple[OnlyResearchPublishedSeriesLineage, ...] = ()
    signals: tuple[OnlyResearchSignalLineage, ...] = ()


class OnlyResearchSpecificationResolver:
    def __init__(self, calculation_registry: OnlyCalculationRegistry, *, max_cells: int | None = None) -> None:
        if not isinstance(calculation_registry, OnlyCalculationRegistry):
            raise TypeError("Specification Resolver requires the Calculation Registry")
        # Exact persisted Specifications containing internal Predicate nodes must
        # be resolvable in a fresh process without Definition-Resolver side effects.
        from onlyalpha.research.definition.primitives import only_register_research_predicate_primitives

        only_register_research_predicate_primitives(calculation_registry)
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

        published_series: tuple[OnlyResearchPublishedSeriesLineage, ...] = ()
        signals: tuple[OnlyResearchSignalLineage, ...] = ()
        if specification.evidence is not None:
            scientific_evidence = specification.evidence
            selected = candidates.get(scientific_evidence.candidate_calculation_id)
            if selected is None:
                self._fail(
                    OnlyResearchSpecificationPhase.SERIES_RESOLUTION,
                    "RESEARCH_SPEC_CANDIDATE_CALCULATION_UNKNOWN",
                    f"unknown candidate_calculation_id: {scientific_evidence.candidate_calculation_id}",
                )
            candidates[scientific_evidence.candidate_calculation_id] = [
                replace(
                    item,
                    candidate_fingerprint=only_research_candidate_fingerprint(
                        specification.specification_fingerprint,
                        scientific_evidence.candidate_calculation_id,
                        item.assignment,
                        item.calculation_fingerprint,
                    ),
                )
                for item in selected
            ]
            published_series = self._resolve_published_series(candidates, scientific_evidence.published_series)
            signals = self._resolve_signals(candidates, scientific_evidence)

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
            result_plan = OnlyResearchResultPlan(fingerprints)
            if specification.evidence is not None:
                calculation_members = tuple(
                    sorted(
                        {
                            OnlyResearchResultCalculationPlan(item.calculation_fingerprint, item.graph_fingerprint)
                            for values in candidates.values()
                            for item in values
                        }
                    )
                )
                candidate_members = []
                for candidate in candidates[specification.evidence.candidate_calculation_id]:
                    assert candidate.candidate_fingerprint is not None
                    member_statistics = tuple(
                        sorted(
                            item.statistics_fingerprint
                            for item in statistics_lineage
                            if item.feature.calculation_fingerprint == candidate.calculation_fingerprint
                            or item.target.calculation_fingerprint == candidate.calculation_fingerprint
                        )
                    )
                    candidate_members.append(
                        OnlyResearchResultCandidatePlan(
                            candidate.candidate_fingerprint,
                            candidate.calculation_id,
                            tuple(candidate.assignment.items()),
                            candidate.calculation_fingerprint,
                            candidate.graph_fingerprint,
                            member_statistics,
                        )
                    )
                result_plan = OnlyResearchResultPlan(
                    fingerprints,
                    RESEARCH_RESULT_SCIENTIFIC_PLAN_SCHEMA_VERSION,
                    specification.dataset_snapshot_fingerprint,
                    calculation_members,
                    tuple(sorted(candidate_members)),
                    tuple(
                        sorted(
                            (
                                OnlyResearchResultSeriesPlan(
                                    item.candidate_fingerprint,
                                    item.calculation_fingerprint,
                                    item.node_fingerprint,
                                    item.output_name,
                                )
                                for item in published_series
                            ),
                            key=lambda item: (
                                item.candidate_fingerprint or "",
                                item.calculation_fingerprint,
                                item.node_fingerprint,
                                item.output_name,
                            ),
                        )
                    ),
                    tuple(
                        sorted(
                            OnlyResearchResultSignalPlan(
                                item.role,
                                item.candidate_fingerprint,
                                item.calculation_fingerprint,
                                item.node_fingerprint,
                                item.output_name,
                            )
                            for item in signals
                        )
                    ),
                )
            workload = OnlyResearchWorkloadPlan(tuple(direct_jobs), tuple(sweeps), tuple(plans), result_plan)
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
            published_series,
            signals,
        )

    def _resolve_published_series(
        self,
        candidates: Mapping[str, list[OnlyResearchCandidateLineage]],
        selectors: tuple[OnlyResearchSeriesSelector, ...],
    ) -> tuple[OnlyResearchPublishedSeriesLineage, ...]:
        result: list[OnlyResearchPublishedSeriesLineage] = []
        for selector in selectors:
            for candidate, node_fingerprint, _ in self._resolve_selector(candidates, selector):
                result.append(
                    OnlyResearchPublishedSeriesLineage(
                        candidate.candidate_fingerprint,
                        candidate.calculation_fingerprint,
                        node_fingerprint,
                        selector.output_name,
                    )
                )
        canonical = tuple(
            sorted(
                result,
                key=lambda item: (
                    item.candidate_fingerprint or "",
                    item.calculation_fingerprint,
                    item.node_fingerprint,
                    item.output_name,
                ),
            )
        )
        if len(canonical) != len(set(canonical)):
            self._fail(
                OnlyResearchSpecificationPhase.SERIES_RESOLUTION,
                "RESEARCH_SPEC_DUPLICATE_PUBLISHED_SERIES",
                "published series resolve to duplicate exact members",
            )
        return canonical

    def _resolve_signals(
        self,
        candidates: Mapping[str, list[OnlyResearchCandidateLineage]],
        evidence: OnlyResearchScientificEvidenceSpec,
    ) -> tuple[OnlyResearchSignalLineage, ...]:
        result: list[OnlyResearchSignalLineage] = []
        for role, selector in (
            ("ELIGIBILITY", evidence.signals.eligibility),
            ("ENTRY_SIGNAL", evidence.signals.entry),
            ("EXIT_SIGNAL", evidence.signals.exit),
        ):
            if selector is None:
                continue
            if selector.calculation_id != evidence.candidate_calculation_id:
                self._fail(
                    OnlyResearchSpecificationPhase.SERIES_RESOLUTION,
                    "RESEARCH_SPEC_SIGNAL_CANDIDATE_MISMATCH",
                    f"{role} must reference candidate_calculation_id",
                )
            for candidate, node_fingerprint, output in self._resolve_selector(candidates, selector):
                if candidate.candidate_fingerprint is None or output.semantic_type != role:
                    self._fail(
                        OnlyResearchSpecificationPhase.SERIES_RESOLUTION,
                        "RESEARCH_SPEC_SIGNAL_ROLE_MISMATCH",
                        f"{selector.template_node_id}.{selector.output_name} is not {role}",
                    )
                result.append(
                    OnlyResearchSignalLineage(
                        role,
                        candidate.candidate_fingerprint,
                        candidate.calculation_fingerprint,
                        node_fingerprint,
                        selector.output_name,
                    )
                )
        return tuple(sorted(result))

    def _resolve_selector(
        self,
        candidates: Mapping[str, list[OnlyResearchCandidateLineage]],
        selector: OnlyResearchSeriesSelector,
    ) -> tuple[tuple[OnlyResearchCandidateLineage, str, OnlyOutputDefinition], ...]:
        selected = candidates.get(selector.calculation_id)
        if selected is None:
            self._fail(
                OnlyResearchSpecificationPhase.SERIES_RESOLUTION,
                "RESEARCH_SPEC_SERIES_REFERENCE_UNKNOWN",
                f"unknown calculation_id: {selector.calculation_id}",
            )
        result: list[tuple[OnlyResearchCandidateLineage, str, OnlyOutputDefinition]] = []
        for candidate in selected:
            node_fingerprint = candidate.node_fingerprints.get(selector.template_node_id)
            if node_fingerprint is None:
                self._fail(
                    OnlyResearchSpecificationPhase.SERIES_RESOLUTION,
                    "RESEARCH_SPEC_SERIES_REFERENCE_UNKNOWN",
                    f"unknown template_node_id: {selector.template_node_id}",
                )
            node = next(item for item in candidate.graph.nodes if item.fingerprint == node_fingerprint)
            output = next((item for item in node.definition.outputs if item.name == selector.output_name), None)
            if output is None:
                self._fail(
                    OnlyResearchSpecificationPhase.SERIES_RESOLUTION,
                    "RESEARCH_SPEC_SERIES_REFERENCE_UNKNOWN",
                    f"unknown output_name: {selector.output_name}",
                )
            result.append((candidate, node_fingerprint, output))
        return tuple(result)

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
