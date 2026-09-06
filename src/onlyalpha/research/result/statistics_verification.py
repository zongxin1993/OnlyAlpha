"""Pure rich Statistics composition verification for Scientific Result V2."""

from __future__ import annotations

from collections.abc import Mapping

from onlyalpha.calculation import OnlyCalculationScalar
from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.calculation.result import OnlyResearchCalculationResult
from onlyalpha.research.evaluation.factor_pair.result import OnlyResearchFactorPairStatisticsResult
from onlyalpha.research.evaluation.reference import OnlyResearchFeatureSeriesReference
from onlyalpha.research.evaluation.result import OnlyResearchStatisticsResult
from onlyalpha.research.evaluation.summary.plan import (
    OnlyResearchCoverageSummaryPlan,
    OnlyResearchEffectSummaryPlan,
    OnlyResearchFactorPairEffectSummaryPlan,
    OnlyResearchParameterNeighborhoodSummaryPlan,
    OnlyResearchTemporalStabilityPlan,
)
from onlyalpha.research.evaluation.summary.result import OnlyResearchSummaryStatisticsResult

from .plan import OnlyResearchResultCandidatePlan, OnlyResearchResultPlan

OnlyResearchComposableStatisticsResult = (
    OnlyResearchStatisticsResult | OnlyResearchFactorPairStatisticsResult | OnlyResearchSummaryStatisticsResult
)


def verify_rich_statistics_composition(
    plan: OnlyResearchResultPlan,
    statistics_by_fingerprint: Mapping[str, OnlyResearchComposableStatisticsResult],
    calculations_by_fingerprint: Mapping[str, OnlyResearchCalculationResult],
) -> None:
    """Verify dependency, Candidate, Graph, and assignment closure without calculating values."""

    if not any(
        isinstance(result, (OnlyResearchFactorPairStatisticsResult, OnlyResearchSummaryStatisticsResult))
        for result in statistics_by_fingerprint.values()
    ):
        return
    if set(statistics_by_fingerprint) != set(plan.statistics_fingerprints):
        raise ValueError("Rich Statistics verified membership does not match Result Plan")

    candidates = {candidate.candidate_fingerprint: candidate for candidate in plan.candidates}
    memberships: dict[str, set[str]] = {fingerprint: set() for fingerprint in plan.statistics_fingerprints}
    for candidate in plan.candidates:
        for fingerprint in candidate.statistics_fingerprints:
            memberships[fingerprint].add(candidate.candidate_fingerprint)

    global_membership = set(plan.statistics_fingerprints)
    for fingerprint in plan.statistics_fingerprints:
        result = statistics_by_fingerprint[fingerprint]
        if result.manifest.dataset_snapshot_fingerprint != plan.dataset_snapshot_fingerprint:
            raise ValueError("Rich Statistics Dataset linkage mismatch")
        if isinstance(result, OnlyResearchStatisticsResult):
            continue
        if isinstance(result, OnlyResearchFactorPairStatisticsResult):
            pair_plan = result.manifest.plan
            operands = (pair_plan.first_operand, pair_plan.second_operand)
            _verify_pair_membership(
                fingerprint,
                memberships[fingerprint],
                operands[0].candidate_fingerprint,
                operands[1].candidate_fingerprint,
            )
            for operand in operands:
                _verify_factor_series(
                    operand.candidate_fingerprint, operand.series, candidates, calculations_by_fingerprint, plan
                )
            continue
        if not isinstance(result, OnlyResearchSummaryStatisticsResult):
            raise ValueError("Rich Statistics result family is unsupported")

        summary_plan = result.manifest.plan
        direct_dependencies: tuple[str, ...]
        if isinstance(
            summary_plan,
            (OnlyResearchEffectSummaryPlan, OnlyResearchCoverageSummaryPlan, OnlyResearchTemporalStabilityPlan),
        ):
            direct_dependencies = (summary_plan.source_statistics_fingerprint,)
            _verify_single_owner(fingerprint, memberships[fingerprint], summary_plan.subject_candidate_fingerprint)
            _verify_factor_series(
                summary_plan.subject_candidate_fingerprint,
                summary_plan.subject,
                candidates,
                calculations_by_fingerprint,
                plan,
            )
        elif isinstance(summary_plan, OnlyResearchFactorPairEffectSummaryPlan):
            direct_dependencies = (summary_plan.source_statistics_fingerprint,)
            operands = (summary_plan.first_operand, summary_plan.second_operand)
            _verify_pair_membership(
                fingerprint,
                memberships[fingerprint],
                operands[0].candidate_fingerprint,
                operands[1].candidate_fingerprint,
            )
            for operand in operands:
                _verify_factor_series(
                    operand.candidate_fingerprint,
                    operand.series,
                    candidates,
                    calculations_by_fingerprint,
                    plan,
                )
        elif isinstance(summary_plan, OnlyResearchParameterNeighborhoodSummaryPlan):
            direct_dependencies = tuple(
                item.source_statistics_fingerprint for item in (summary_plan.focal, *summary_plan.neighbors)
            )
            owner = _candidate(summary_plan.focal.candidate_fingerprint, candidates)
            _verify_single_owner(fingerprint, memberships[fingerprint], owner.candidate_fingerprint)
            _verify_assignment(summary_plan.focal.assignment, owner)
            for neighbor in summary_plan.neighbors:
                _verify_assignment(neighbor.assignment, _candidate(neighbor.candidate_fingerprint, candidates))
        else:  # pragma: no cover - the typed Result contract closes this branch
            raise ValueError("Summary Statistics Plan kind is unsupported")

        missing = set(direct_dependencies) - global_membership
        if missing:
            raise ValueError(f"Rich Statistics dependency is absent from global membership: {sorted(missing)}")


def _verify_single_owner(fingerprint: str, actual: set[str], expected: str) -> None:
    if actual != {expected}:
        raise ValueError(f"Rich Statistics {fingerprint} must belong only to its exact Candidate")


def _verify_pair_membership(fingerprint: str, actual: set[str], first: str, second: str) -> None:
    allowed = {first, second}
    if not actual or not actual <= allowed:
        raise ValueError(f"Factor-Pair Statistics {fingerprint} membership is not an exact operand subset")


def _candidate(
    fingerprint: str, candidates: Mapping[str, OnlyResearchResultCandidatePlan]
) -> OnlyResearchResultCandidatePlan:
    try:
        return candidates[fingerprint]
    except KeyError as exc:
        raise ValueError("Rich Statistics Candidate is absent from Scientific Result Plan") from exc


def _verify_factor_series(
    candidate_fingerprint: str,
    series: OnlyResearchFeatureSeriesReference,
    candidates: Mapping[str, OnlyResearchResultCandidatePlan],
    calculations: Mapping[str, OnlyResearchCalculationResult],
    result_plan: OnlyResearchResultPlan,
) -> None:
    candidate = _candidate(candidate_fingerprint, candidates)
    if series.calculation_fingerprint != candidate.calculation_fingerprint:
        raise ValueError("Rich Factor series Calculation does not match exact Candidate Calculation")
    try:
        calculation = calculations[candidate.calculation_fingerprint]
    except KeyError as exc:  # pragma: no cover - Scientific Plan normally closes this first
        raise ValueError("Rich Candidate Calculation is absent from verified Result membership") from exc
    manifest = calculation.manifest
    if manifest.dataset_snapshot_fingerprint != result_plan.dataset_snapshot_fingerprint:
        raise ValueError("Rich Candidate Calculation Dataset linkage mismatch")
    if manifest.calculation_graph_fingerprint != candidate.graph_fingerprint:
        raise ValueError("Rich Candidate Graph does not match exact Calculation Result Graph")
    node = next(
        (item for item in manifest.calculation_graph.nodes if item.fingerprint == series.node_fingerprint), None
    )
    if node is None:
        raise ValueError("Rich Factor series node is absent from exact Candidate Graph")
    if not any(output.name == series.output_name for output in node.definition.outputs):
        raise ValueError("Rich Factor series output is absent from exact Candidate Graph")


def _verify_assignment(actual: Mapping[str, OnlyCalculationScalar], candidate: OnlyResearchResultCandidatePlan) -> None:
    # Scientific Plan V2 historically persists Candidate assignments through the
    # repository canonical JSON projection.  Reuse that exact authority here so
    # in-memory admission and fresh-process verified load cannot disagree.
    if only_canonical_json(dict(actual)) != only_canonical_json(dict(candidate.assignment)):
        raise ValueError("Parameter Neighborhood assignment does not match exact Candidate assignment")


__all__ = ["OnlyResearchComposableStatisticsResult", "verify_rich_statistics_composition"]
