"""Pure offline semantic verification for Scientific Artifact V3."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from onlyalpha.calculation import OnlyCalculationScalar
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.evaluation.factor_pair.identity import (
    only_research_factor_pair_result_content_fingerprint,
    only_research_factor_pair_result_fingerprint,
)
from onlyalpha.research.evaluation.factor_pair.plan import OnlyResearchFactorPairStatisticsPlan
from onlyalpha.research.evaluation.factor_pair.result import (
    OnlyResearchFactorPairStatisticRow,
    OnlyResearchFactorPairStatisticStatus,
)
from onlyalpha.research.evaluation.plan import OnlyResearchStatisticsPlan
from onlyalpha.research.evaluation.reference import OnlyResearchFeatureSeriesReference
from onlyalpha.research.evaluation.result import OnlyResearchStatisticRow, OnlyResearchStatisticStatus
from onlyalpha.research.evaluation.result_identity import (
    only_research_statistics_result_content_fingerprint,
    only_research_statistics_result_fingerprint,
)
from onlyalpha.research.evaluation.summary.family import OnlyResearchStatisticsFamily
from onlyalpha.research.evaluation.summary.identity import (
    only_research_parameter_neighborhood_result_content_fingerprint,
    only_research_summary_result_content_fingerprint,
    only_research_summary_result_fingerprint,
)
from onlyalpha.research.evaluation.summary.plan import (
    OnlyResearchCoverageSummaryPlan,
    OnlyResearchEffectSummaryPlan,
    OnlyResearchFactorPairEffectSummaryPlan,
    OnlyResearchParameterNeighborhoodSummaryPlan,
    OnlyResearchTemporalStabilityPlan,
)
from onlyalpha.research.result.plan import OnlyResearchResultCandidatePlan
from onlyalpha.research.result.result import OnlyResearchCalculationResultReference

from .scientific_model import OnlyResearchScientificGraph
from .scientific_v3_model import (
    OnlyResearchScientificArtifactManifestV3,
    OnlyResearchScientificFactorPairSeriesCatalogEntryV3,
    OnlyResearchScientificLegacySeriesCatalogEntryV3,
    OnlyResearchScientificStatisticsCatalogEntryV3,
    OnlyResearchScientificStatisticsSeriesRowV3,
    OnlyResearchScientificStatisticsShapeV3,
    OnlyResearchScientificStatisticsSummaryV3,
    OnlyResearchScientificSummaryCatalogEntryV3,
)


def verify_scientific_artifact_v3_statistics(
    manifest: OnlyResearchScientificArtifactManifestV3,
    catalog: tuple[OnlyResearchScientificStatisticsCatalogEntryV3, ...],
    series_rows: tuple[OnlyResearchScientificStatisticsSeriesRowV3, ...],
    summaries: tuple[OnlyResearchScientificStatisticsSummaryV3, ...],
    graphs: tuple[OnlyResearchScientificGraph, ...],
) -> None:
    """Recompute every portable Statistics identity and its composition closure."""

    if catalog != tuple(sorted(catalog, key=lambda x: x.statistics_fingerprint)):
        raise ValueError("Scientific V3 Catalog is not canonical")
    if len({x.statistics_fingerprint for x in catalog}) != len(catalog):
        raise ValueError("Scientific V3 Catalog contains duplicate identities")
    by_fp = {x.statistics_fingerprint: x for x in catalog}
    references = {x.statistics_fingerprint: x.statistics_result_fingerprint for x in manifest.statistics_results}
    if set(by_fp) != set(references) or any(
        references[x.statistics_fingerprint] != x.statistics_result_fingerprint for x in catalog
    ):
        raise ValueError("Scientific V3 Catalog does not match Research Result membership")

    series_entries = {
        x.statistics_fingerprint: x
        for x in catalog
        if isinstance(
            x,
            (OnlyResearchScientificLegacySeriesCatalogEntryV3, OnlyResearchScientificFactorPairSeriesCatalogEntryV3),
        )
    }
    summary_entries = {
        x.statistics_fingerprint: x for x in catalog if isinstance(x, OnlyResearchScientificSummaryCatalogEntryV3)
    }
    groups: dict[str, list[OnlyResearchScientificStatisticsSeriesRowV3]] = {}
    for row in series_rows:
        groups.setdefault(row.statistics_fingerprint, []).append(row)
    summary_by_fp: dict[str, OnlyResearchScientificStatisticsSummaryV3] = {}
    for value in summaries:
        if value.statistics_fingerprint in summary_by_fp:
            raise ValueError("Scientific V3 Summary payload is duplicated")
        summary_by_fp[value.statistics_fingerprint] = value
    if set(groups) - set(series_entries):
        raise ValueError("Scientific V3 Series payload exists outside Catalog")
    if set(summary_by_fp) != set(summary_entries):
        raise ValueError("Scientific V3 Summary payload membership mismatch")

    calculations = {x.calculation_fingerprint: x for x in manifest.calculation_results}
    graph_by_calculation = {x.calculation_fingerprint: x.graph for x in graphs}
    if tuple((x.calculation_fingerprint, x.graph.fingerprint) for x in graphs) != tuple(
        (x.calculation_fingerprint, x.graph_fingerprint) for x in manifest.plan.calculations
    ):
        raise ValueError("Scientific V3 Graph membership/linkage mismatch")

    candidates = {x.candidate_fingerprint: x for x in manifest.plan.candidates}
    memberships: dict[str, set[str]] = {x: set() for x in by_fp}
    for candidate in manifest.plan.candidates:
        for fingerprint in candidate.statistics_fingerprints:
            memberships[fingerprint].add(candidate.candidate_fingerprint)

    for fingerprint, entry in by_fp.items():
        if entry.dataset_snapshot_fingerprint != manifest.dataset_snapshot_fingerprint:
            raise ValueError("Scientific V3 Statistics Dataset linkage mismatch")
        if isinstance(entry, OnlyResearchScientificLegacySeriesCatalogEntryV3):
            if (
                entry.statistics_family is not OnlyResearchStatisticsFamily.FEATURE_TARGET_CORRELATION_SERIES_V1
                or entry.payload_shape is not OnlyResearchScientificStatisticsShapeV3.SERIES
                or not isinstance(entry.plan, OnlyResearchStatisticsPlan)
            ):
                raise ValueError("Scientific V3 legacy Catalog variant mismatch")
            rows = groups.get(fingerprint, [])
            if len(rows) != entry.row_count:
                raise ValueError("Scientific V3 legacy Series row membership mismatch")
            legacy_typed = tuple(
                OnlyResearchStatisticRow(
                    x.ts_event_ns, x.statistic_value, x.sample_count, OnlyResearchStatisticStatus(x.status)
                )
                for x in rows
            )
            content = only_research_statistics_result_content_fingerprint(
                tuple(x.semantic_payload() for x in legacy_typed)
            )
            _verify_result_identity(entry, content, only_research_statistics_result_fingerprint)
            _verify_calculation_result_if_composed(
                entry.plan.feature.calculation_fingerprint,
                entry.feature_calculation_result_fingerprint,
                calculations,
            )
            _verify_calculation_result_if_composed(
                entry.plan.target.calculation_fingerprint,
                entry.target_calculation_result_fingerprint,
                calculations,
            )
        elif isinstance(entry, OnlyResearchScientificFactorPairSeriesCatalogEntryV3):
            if (
                entry.statistics_family is not OnlyResearchStatisticsFamily.FACTOR_PAIR_CORRELATION_SERIES_V1
                or entry.payload_shape is not OnlyResearchScientificStatisticsShapeV3.SERIES
                or not isinstance(entry.plan, OnlyResearchFactorPairStatisticsPlan)
            ):
                raise ValueError("Scientific V3 Factor-Pair Catalog variant mismatch")
            if entry.plan.dataset_snapshot_fingerprint != entry.dataset_snapshot_fingerprint:
                raise ValueError("Scientific V3 Factor-Pair Plan Dataset linkage mismatch")
            rows = groups.get(fingerprint, [])
            if len(rows) != entry.row_count:
                raise ValueError("Scientific V3 Factor-Pair Series row membership mismatch")
            pair_typed = tuple(
                OnlyResearchFactorPairStatisticRow(
                    x.ts_event_ns, x.statistic_value, x.sample_count, OnlyResearchFactorPairStatisticStatus(x.status)
                )
                for x in rows
            )
            content = only_research_factor_pair_result_content_fingerprint(
                entry.first_calculation_result_fingerprint,
                entry.second_calculation_result_fingerprint,
                tuple(x.semantic_payload() for x in pair_typed),
            )
            _verify_result_identity(entry, content, only_research_factor_pair_result_fingerprint)
            operands = (entry.plan.first_operand, entry.plan.second_operand)
            _verify_pair_membership(fingerprint, memberships[fingerprint], *(x.candidate_fingerprint for x in operands))
            for operand, result_fp in zip(
                operands,
                (entry.first_calculation_result_fingerprint, entry.second_calculation_result_fingerprint),
                strict=True,
            ):
                _verify_factor_series(operand.candidate_fingerprint, operand.series, candidates, graph_by_calculation)
                _verify_calculation_result(operand.series.calculation_fingerprint, result_fp, calculations)
        else:
            if (
                entry.statistics_family is not OnlyResearchStatisticsFamily.SUMMARY_STATISTICS_V1
                or entry.payload_shape is not OnlyResearchScientificStatisticsShapeV3.SUMMARY
                or not isinstance(
                    entry.plan,
                    (
                        OnlyResearchEffectSummaryPlan,
                        OnlyResearchCoverageSummaryPlan,
                        OnlyResearchTemporalStabilityPlan,
                        OnlyResearchFactorPairEffectSummaryPlan,
                        OnlyResearchParameterNeighborhoodSummaryPlan,
                    ),
                )
            ):
                raise ValueError("Scientific V3 Summary Catalog variant mismatch")
            if entry.plan.dataset_snapshot_fingerprint != entry.dataset_snapshot_fingerprint:
                raise ValueError("Scientific V3 Summary Plan Dataset linkage mismatch")
            summary = summary_by_fp[fingerprint].summary
            plan = entry.plan
            if summary.summary_kind is not plan.definition.summary_kind:
                raise ValueError("Scientific V3 Summary Plan/payload kind mismatch")
            if isinstance(plan, OnlyResearchParameterNeighborhoodSummaryPlan):
                content = only_research_parameter_neighborhood_result_content_fingerprint(
                    plan.focal.source_statistics_fingerprint,
                    plan.focal.source_statistics_result_fingerprint,
                    tuple(
                        (x.source_statistics_fingerprint, x.source_statistics_result_fingerprint)
                        for x in plan.neighbors
                    ),
                    summary.to_dict(),
                )
                dependencies = tuple(
                    (x.source_statistics_fingerprint, x.source_statistics_result_fingerprint)
                    for x in (plan.focal, *plan.neighbors)
                )
                _verify_single_owner(fingerprint, memberships[fingerprint], plan.focal.candidate_fingerprint)
                _verify_assignment(plan.focal.assignment, _candidate(plan.focal.candidate_fingerprint, candidates))
                for neighbor in plan.neighbors:
                    _verify_assignment(neighbor.assignment, _candidate(neighbor.candidate_fingerprint, candidates))
            else:
                content = only_research_summary_result_content_fingerprint(
                    plan.source_statistics_fingerprint,
                    plan.source_statistics_result_fingerprint,
                    summary.to_dict(),
                )
                dependencies = ((plan.source_statistics_fingerprint, plan.source_statistics_result_fingerprint),)
                if isinstance(
                    plan,
                    (OnlyResearchEffectSummaryPlan, OnlyResearchCoverageSummaryPlan, OnlyResearchTemporalStabilityPlan),
                ):
                    _verify_single_owner(fingerprint, memberships[fingerprint], plan.subject_candidate_fingerprint)
                    _verify_factor_series(
                        plan.subject_candidate_fingerprint, plan.subject, candidates, graph_by_calculation
                    )
                elif isinstance(plan, OnlyResearchFactorPairEffectSummaryPlan):
                    operands = (plan.first_operand, plan.second_operand)
                    _verify_pair_membership(
                        fingerprint, memberships[fingerprint], *(x.candidate_fingerprint for x in operands)
                    )
                    for operand in operands:
                        _verify_factor_series(
                            operand.candidate_fingerprint, operand.series, candidates, graph_by_calculation
                        )
            _verify_result_identity(entry, content, only_research_summary_result_fingerprint)
            for logical, result_fp in dependencies:
                dependency = by_fp.get(logical)
                if dependency is None or dependency.statistics_result_fingerprint != result_fp:
                    raise ValueError("Scientific V3 Statistics dependency closure mismatch")


def _verify_result_identity(
    entry: OnlyResearchScientificStatisticsCatalogEntryV3,
    content: str,
    constructor: Callable[[str, str], str],
) -> None:
    if content != entry.result_content_fingerprint:
        raise ValueError("Scientific V3 Statistics result-content identity mismatch")
    expected = constructor(entry.statistics_fingerprint, content)
    if expected != entry.statistics_result_fingerprint:
        raise ValueError("Scientific V3 Statistics Result identity mismatch")


def _verify_calculation_result(
    logical: str,
    result_fp: str,
    calculations: Mapping[str, OnlyResearchCalculationResultReference],
) -> None:
    value = calculations.get(logical)
    if value is None or value.calculation_result_fingerprint != result_fp:
        raise ValueError("Scientific V3 Calculation dependency mismatch")


def _verify_calculation_result_if_composed(
    logical: str,
    result_fp: str,
    calculations: Mapping[str, OnlyResearchCalculationResultReference],
) -> None:
    if logical in calculations:
        _verify_calculation_result(logical, result_fp, calculations)


def _candidate(
    fingerprint: str, candidates: Mapping[str, OnlyResearchResultCandidatePlan]
) -> OnlyResearchResultCandidatePlan:
    try:
        return candidates[fingerprint]
    except KeyError as exc:
        raise ValueError("Scientific V3 Candidate is absent from Result Plan") from exc


def _verify_single_owner(fingerprint: str, actual: set[str], expected: str) -> None:
    if actual != {expected}:
        raise ValueError(f"Scientific V3 Statistics {fingerprint} has invalid Candidate membership")


def _verify_pair_membership(fingerprint: str, actual: set[str], first: str, second: str) -> None:
    if not actual or not actual <= {first, second}:
        raise ValueError(f"Scientific V3 Pair Statistics {fingerprint} has invalid Candidate membership")


def _verify_factor_series(
    candidate_fp: str,
    series: OnlyResearchFeatureSeriesReference,
    candidates: Mapping[str, OnlyResearchResultCandidatePlan],
    graphs: Mapping[str, OnlyCalculationGraphDefinition],
) -> None:
    candidate = _candidate(candidate_fp, candidates)
    calculation_fp = series.calculation_fingerprint
    if calculation_fp != candidate.calculation_fingerprint:
        raise ValueError("Scientific V3 Factor series Candidate Calculation mismatch")
    graph = graphs.get(calculation_fp)
    if graph is None or graph.fingerprint != candidate.graph_fingerprint:
        raise ValueError("Scientific V3 Factor series Candidate Graph mismatch")
    node = next((x for x in graph.nodes if x.fingerprint == series.node_fingerprint), None)
    if node is None or not any(x.name == series.output_name for x in node.definition.outputs):
        raise ValueError("Scientific V3 Factor series node/output mismatch")


def _verify_assignment(actual: Mapping[str, OnlyCalculationScalar], candidate: OnlyResearchResultCandidatePlan) -> None:
    if only_canonical_json(dict(actual)) != only_canonical_json(dict(candidate.assignment)):
        raise ValueError("Scientific V3 Neighborhood assignment mismatch")


__all__ = ["verify_scientific_artifact_v3_statistics"]
