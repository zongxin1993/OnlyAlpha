from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyParquetResearchScientificArtifactStoreV3,
    OnlyParquetResearchStatisticsResultStore,
    OnlyResearchCoverageSummaryDefinition,
    OnlyResearchCoverageSummaryExecutor,
    OnlyResearchCoverageSummaryPlan,
    OnlyResearchEffectSummaryDefinition,
    OnlyResearchEffectSummaryExecutor,
    OnlyResearchEffectSummaryPlan,
    OnlyResearchParameterNeighborhoodCandidateBinding,
    OnlyResearchParameterNeighborhoodSummaryDefinition,
    OnlyResearchParameterNeighborhoodSummaryExecutor,
    OnlyResearchParameterNeighborhoodSummaryPlan,
    OnlyResearchResultAssembler,
    OnlyResearchResultCalculationPlan,
    OnlyResearchResultCandidatePlan,
    OnlyResearchResultPlan,
    OnlyResearchScientificArtifactMaterializerV3,
    OnlyResearchStatisticsDefinition,
    OnlyResearchStatisticsExecutor,
    OnlyResearchStatisticsMethod,
    OnlyResearchStatisticsPlan,
    OnlyResearchStatisticsResultReader,
    OnlyResearchTemporalSlice,
    OnlyResearchTemporalStabilityDefinition,
    OnlyResearchTemporalStabilityExecutor,
    OnlyResearchTemporalStabilityPlan,
)
from tests.research.evaluation.support import factor_pair_effect_case


def test_scientific_v3_complete_mixed_rich_product_verifies_offline(tmp_path) -> None:
    case = factor_pair_effect_case(tmp_path)
    pair_plan, pair_store = case[9], case[10]
    pair_effect_plan, summaries, pair_effect_executor = case[13], case[14], case[15]
    pair_effect_executor.execute(pair_effect_plan)
    legacy = OnlyParquetResearchStatisticsResultStore(
        tmp_path / "statistics-results",
        case[2],
        audit_time=lambda: datetime(2026, 9, 6, tzinfo=UTC),
    )
    legacy_executor = OnlyResearchStatisticsExecutor(case[2], legacy)
    ic_plan = case[6]
    rank_plan = OnlyResearchStatisticsPlan(
        ic_plan.feature,
        ic_plan.target,
        OnlyResearchStatisticsDefinition(OnlyResearchStatisticsMethod.RANK_IC),
    )
    legacy_executor.execute(ic_plan)
    legacy_executor.execute(rank_plan)
    source = legacy.load_verified(ic_plan.statistics_fingerprint)
    factor = pair_plan.first_operand.series
    focal_id, neighbor_ids = pair_plan.first_operand.candidate_fingerprint, ("d" * 64, "e" * 64)

    def make_effect(candidate_id: str) -> OnlyResearchEffectSummaryPlan:
        return OnlyResearchEffectSummaryPlan(
            source.manifest.dataset_snapshot_fingerprint,
            candidate_id,
            factor,
            source.manifest.statistics_fingerprint,
            source.manifest.statistics_result_fingerprint,
            OnlyResearchEffectSummaryDefinition(OnlyResearchStatisticsMethod.IC),
        )

    effects = (make_effect(focal_id), *(make_effect(x) for x in neighbor_ids))
    effect_executor = OnlyResearchEffectSummaryExecutor(legacy, summaries)
    for effect in effects:
        effect_executor.execute(effect)
    coverage = OnlyResearchCoverageSummaryPlan(
        source.manifest.dataset_snapshot_fingerprint,
        focal_id,
        factor,
        source.manifest.statistics_fingerprint,
        source.manifest.statistics_result_fingerprint,
        OnlyResearchCoverageSummaryDefinition(OnlyResearchStatisticsMethod.IC),
    )
    OnlyResearchCoverageSummaryExecutor(legacy, summaries).execute(coverage)
    stability = OnlyResearchTemporalStabilityPlan(
        source.manifest.dataset_snapshot_fingerprint,
        focal_id,
        factor,
        source.manifest.statistics_fingerprint,
        source.manifest.statistics_result_fingerprint,
        OnlyResearchTemporalStabilityDefinition(OnlyResearchStatisticsMethod.IC),
        (
            OnlyResearchTemporalSlice(1767576600000000000, 1767576800000000000),
            OnlyResearchTemporalSlice(1767576800000000000, 1767576900000000000),
        ),
    )
    OnlyResearchTemporalStabilityExecutor(legacy, summaries).execute(stability)
    assignments = (
        {"threshold": Decimal("0.1"), "window": 5},
        {"threshold": Decimal("0.2"), "window": 6},
        {"threshold": Decimal("0.3"), "window": 7},
    )
    bindings = tuple(
        OnlyResearchParameterNeighborhoodCandidateBinding(
            effect.subject_candidate_fingerprint,
            assignment,
            effect.statistics_fingerprint,
            summaries.load_verified(effect.statistics_fingerprint).manifest.statistics_result_fingerprint,
        )
        for effect, assignment in zip(effects, assignments, strict=True)
    )
    metric = "research.factor.ic.mean@1"
    neighborhood = OnlyResearchParameterNeighborhoodSummaryPlan(
        source.manifest.dataset_snapshot_fingerprint,
        metric,
        bindings[0],
        bindings[1:],
        OnlyResearchParameterNeighborhoodSummaryDefinition(metric),
    )
    OnlyResearchParameterNeighborhoodSummaryExecutor(summaries).execute(neighborhood)
    members = tuple(
        sorted(
            OnlyResearchResultCalculationPlan(
                operand.series.calculation_fingerprint,
                case[2].load_verified(operand.series.calculation_fingerprint).manifest.calculation_graph_fingerprint,
            )
            for operand in (pair_plan.first_operand, pair_plan.second_operand)
        )
    )
    by_calculation = {x.calculation_fingerprint: x for x in members}
    pair_membership = (pair_plan.statistics_fingerprint, pair_effect_plan.statistics_fingerprint)
    candidates = [
        OnlyResearchResultCandidatePlan(
            focal_id,
            "factor",
            tuple(sorted(assignments[0].items())),
            factor.calculation_fingerprint,
            by_calculation[factor.calculation_fingerprint].graph_fingerprint,
            (
                *pair_membership,
                effects[0].statistics_fingerprint,
                coverage.statistics_fingerprint,
                stability.statistics_fingerprint,
                neighborhood.statistics_fingerprint,
            ),
        ),
        OnlyResearchResultCandidatePlan(
            pair_plan.second_operand.candidate_fingerprint,
            "factor",
            (),
            pair_plan.second_operand.series.calculation_fingerprint,
            by_calculation[pair_plan.second_operand.series.calculation_fingerprint].graph_fingerprint,
            pair_membership,
        ),
    ]
    candidates.extend(
        OnlyResearchResultCandidatePlan(
            candidate_id,
            "factor",
            tuple(sorted(assignment.items())),
            factor.calculation_fingerprint,
            by_calculation[factor.calculation_fingerprint].graph_fingerprint,
            (effect.statistics_fingerprint,),
        )
        for candidate_id, assignment, effect in zip(neighbor_ids, assignments[1:], effects[1:], strict=True)
    )
    global_statistics = (
        ic_plan.statistics_fingerprint,
        rank_plan.statistics_fingerprint,
        pair_plan.statistics_fingerprint,
        pair_effect_plan.statistics_fingerprint,
        *(x.statistics_fingerprint for x in effects),
        coverage.statistics_fingerprint,
        stability.statistics_fingerprint,
        neighborhood.statistics_fingerprint,
    )
    result_plan = OnlyResearchResultPlan(
        global_statistics,
        2,
        source.manifest.dataset_snapshot_fingerprint,
        members,
        tuple(sorted(candidates)),
    )
    reader = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", legacy, summaries, pair_store)
    result = OnlyResearchResultAssembler(
        reader,
        calculation_result_store=case[2],
        audit_time=lambda: datetime(2026, 9, 6, tzinfo=UTC),
    ).assemble(result_plan)
    results = OnlyJsonResearchResultStore(tmp_path / "research-results", reader, case[2])
    results.commit(result)
    candidate = OnlyResearchScientificArtifactMaterializerV3(results, case[7], case[2], reader).materialize(
        result_plan.fingerprint
    )
    store = OnlyParquetResearchScientificArtifactStoreV3(tmp_path / "mixed-artifacts")
    store.commit(candidate)
    loaded = store.load_verified(result.manifest.research_result_fingerprint)

    assert {x.statistics_fingerprint for x in loaded.statistics_catalog} == set(global_statistics)
    assert len(loaded.statistics_summaries) == 7
    rich_entries = [x for x in loaded.statistics_catalog if hasattr(x.plan, "dataset_snapshot_fingerprint")]
    assert rich_entries
    assert all(
        entry.plan.dataset_snapshot_fingerprint
        == entry.dataset_snapshot_fingerprint
        == loaded.manifest.dataset_snapshot_fingerprint
        for entry in rich_entries
    )
