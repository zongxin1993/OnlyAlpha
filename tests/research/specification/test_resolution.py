from __future__ import annotations

from typing import get_type_hints

import pytest

from onlyalpha.research import (
    OnlyResearchCalculationSpec,
    OnlyResearchScientificEvidenceSpec,
    OnlyResearchSeriesSelector,
    OnlyResearchSignalEvidenceSpec,
    OnlyResearchSpecification,
    OnlyResearchSpecificationError,
    OnlyResearchSpecificationResolution,
    OnlyResearchSpecificationResolver,
    OnlyResearchStatisticsSpec,
    OnlyResearchSweepParameterDimension,
    OnlyResearchSweepParameterTarget,
    OnlyResearchWorkloadPlan,
)
from tests.research.evaluation.support import target_graph
from tests.research.factor.support import factor_graph
from tests.research.specification.support import registry, specification


def test_resolution_workload_type_is_exact_application_contract() -> None:
    hints = get_type_hints(OnlyResearchSpecificationResolution)

    assert hints["workload"] is OnlyResearchWorkloadPlan


def _swept(
    spec: OnlyResearchSpecification, calculation_id: str, node_id: str, parameter: str, values: tuple[object, ...]
):
    calculations = tuple(
        OnlyResearchCalculationSpec(
            item.calculation_id,
            item.graph_template,
            (OnlyResearchSweepParameterDimension(OnlyResearchSweepParameterTarget(node_id, parameter), values),)
            if item.calculation_id == calculation_id
            else item.sweep_dimensions,
        )
        for item in spec.calculations
    )
    return OnlyResearchSpecification(spec.dataset_snapshot_fingerprint, calculations, spec.statistics)


def _with_evidence(
    spec: OnlyResearchSpecification,
    *,
    candidate_calculation_id: str,
    published_series: tuple[OnlyResearchSeriesSelector, ...],
) -> OnlyResearchSpecification:
    return OnlyResearchSpecification(
        spec.dataset_snapshot_fingerprint,
        spec.calculations,
        spec.statistics,
        OnlyResearchScientificEvidenceSpec(
            candidate_calculation_id,
            published_series,
            OnlyResearchSignalEvidenceSpec(),
        ),
        2,
    )


def test_direct_resolution_reproduces_manual_p7_graph_job_statistics_and_result_identities() -> None:
    resolved = OnlyResearchSpecificationResolver(registry()).resolve(specification())
    feature, target = resolved.workload.direct_jobs
    assert feature.calculation_graph.fingerprint == factor_graph().fingerprint
    assert target.calculation_graph.fingerprint == target_graph().fingerprint
    assert resolved.workload.statistics_plans[0].statistics_fingerprint == resolved.statistics[0].statistics_fingerprint
    assert resolved.workload.result_plan.statistics_fingerprints == (
        resolved.workload.statistics_plans[0].statistics_fingerprint,
    )


def test_singleton_broadcast_and_candidate_lineage_are_exact() -> None:
    resolved = OnlyResearchSpecificationResolver(registry()).resolve(
        _swept(specification(), "feature", "short", "period", (1, 3, 5))
    )
    assert len(resolved.workload.sweeps) == 1
    assert len(resolved.workload.statistics_plans) == 3
    feature = [item for item in resolved.candidates if item.calculation_id == "feature"]
    assert [dict(item.assignment) for item in feature] == [
        {"short.period": 1},
        {"short.period": 3},
        {"short.period": 5},
    ]
    assert [item.feature.calculation_fingerprint for item in resolved.statistics] == [
        item.calculation_fingerprint for item in feature
    ]
    assert len({item.graph_fingerprint for item in feature}) == 3


def test_target_singleton_broadcast_and_many_to_many_ambiguity() -> None:
    target_sweep = _swept(specification(), "target", "forward_return", "exit_offset", (1, 2))
    resolved = OnlyResearchSpecificationResolver(registry()).resolve(target_sweep)
    assert len(resolved.workload.statistics_plans) == 2
    both = _swept(target_sweep, "feature", "short", "period", (1, 3))
    with pytest.raises(OnlyResearchSpecificationError) as error:
        OnlyResearchSpecificationResolver(registry()).resolve(both)
    assert error.value.code == "RESEARCH_SPEC_STATISTICS_EXPANSION_AMBIGUOUS"


def test_candidate_calculation_swept_publication_is_candidate_relative() -> None:
    swept = _swept(specification(), "feature", "short", "period", (1, 3, 5))
    resolved = OnlyResearchSpecificationResolver(registry()).resolve(
        _with_evidence(
            swept,
            candidate_calculation_id="feature",
            published_series=(OnlyResearchSeriesSelector("feature", "momentum", "factor_value"),),
        )
    )

    assert len(resolved.published_series) == 3
    assert all(item.candidate_fingerprint is not None for item in resolved.published_series)


def test_non_candidate_singleton_publication_remains_global_evidence() -> None:
    swept = _swept(specification(), "feature", "short", "period", (1, 3))
    resolved = OnlyResearchSpecificationResolver(registry()).resolve(
        _with_evidence(
            swept,
            candidate_calculation_id="feature",
            published_series=(OnlyResearchSeriesSelector("target", "forward_return", "target_value"),),
        )
    )

    assert len(resolved.published_series) == 1
    assert resolved.published_series[0].candidate_fingerprint is None


def test_non_candidate_multi_lineage_publication_fails_closed() -> None:
    target_sweep = _swept(specification(), "target", "forward_return", "exit_offset", (1, 2))
    with pytest.raises(OnlyResearchSpecificationError) as error:
        OnlyResearchSpecificationResolver(registry()).resolve(
            _with_evidence(
                target_sweep,
                candidate_calculation_id="feature",
                published_series=(OnlyResearchSeriesSelector("target", "forward_return", "target_value"),),
            )
        )

    assert error.value.code == "RESEARCH_SPEC_PUBLISHED_SERIES_AMBIGUOUS"


@pytest.mark.parametrize(
    ("selector", "code"),
    [
        (OnlyResearchSeriesSelector("missing", "momentum", "factor_value"), "RESEARCH_SPEC_SERIES_REFERENCE_UNKNOWN"),
        (OnlyResearchSeriesSelector("feature", "missing", "factor_value"), "RESEARCH_SPEC_SERIES_REFERENCE_UNKNOWN"),
        (OnlyResearchSeriesSelector("feature", "momentum", "missing"), "RESEARCH_SPEC_SERIES_REFERENCE_UNKNOWN"),
        (OnlyResearchSeriesSelector("feature", "short", "value"), "RESEARCH_SPEC_FEATURE_SEMANTIC_INVALID"),
        (
            OnlyResearchSeriesSelector("target", "forward_return", "target_value"),
            "RESEARCH_SPEC_FEATURE_SEMANTIC_INVALID",
        ),
    ],
)
def test_invalid_feature_selectors_fail_closed(selector, code: str) -> None:
    base = specification()
    stats = base.statistics[0]
    invalid = OnlyResearchSpecification(
        base.dataset_snapshot_fingerprint,
        base.calculations,
        (OnlyResearchStatisticsSpec(selector, stats.target, stats.definition),),
    )
    with pytest.raises(OnlyResearchSpecificationError) as error:
        OnlyResearchSpecificationResolver(registry()).resolve(invalid)
    assert error.value.code == code


def test_unknown_type_version_and_cardinality_are_stable_failures() -> None:
    base = specification()
    feature = next(item for item in base.calculations if item.calculation_id == "feature")
    node = feature.graph_template.nodes[0]
    from onlyalpha.calculation import OnlyCalculationTypeReference
    from onlyalpha.research import OnlyResearchGraphTemplate, OnlyResearchGraphTemplateNode

    bad_node = OnlyResearchGraphTemplateNode(
        node.template_node_id,
        OnlyCalculationTypeReference(node.type_reference.kind, node.type_reference.type_id, "999"),
        node.parameters,
        node.input_bindings,
    )
    bad_template = OnlyResearchGraphTemplate((bad_node, *feature.graph_template.nodes[1:]))
    invalid = OnlyResearchSpecification(
        base.dataset_snapshot_fingerprint,
        tuple(
            OnlyResearchCalculationSpec(item.calculation_id, bad_template if item is feature else item.graph_template)
            for item in base.calculations
        ),
        base.statistics,
    )
    with pytest.raises(OnlyResearchSpecificationError) as version:
        OnlyResearchSpecificationResolver(registry()).resolve(invalid)
    assert version.value.code == "RESEARCH_SPEC_CALCULATION_VERSION_UNKNOWN"
    swept = _swept(base, "feature", "short", "period", (1, 2))
    with pytest.raises(OnlyResearchSpecificationError) as cardinality:
        OnlyResearchSpecificationResolver(registry(), max_cells=1).resolve(swept)
    assert cardinality.value.code == "RESEARCH_SPEC_SWEEP_CARDINALITY_EXCEEDED"


def test_trading_only_exact_type_is_rejected_during_research_admission() -> None:
    from onlyalpha.calculation import OnlyCalculationKind, OnlyCalculationTypeReference
    from onlyalpha.research import OnlyResearchGraphTemplate, OnlyResearchGraphTemplateNode

    base = specification()
    trading_only = OnlyResearchCalculationSpec(
        "aaa_trading_only",
        OnlyResearchGraphTemplate(
            (
                OnlyResearchGraphTemplateNode(
                    "atr",
                    OnlyCalculationTypeReference(OnlyCalculationKind.INDICATOR, "onlyalpha.indicator.atr", "1"),
                ),
            )
        ),
    )
    invalid = OnlyResearchSpecification(
        base.dataset_snapshot_fingerprint,
        (*base.calculations, trading_only),
        base.statistics,
    )
    with pytest.raises(OnlyResearchSpecificationError) as error:
        OnlyResearchSpecificationResolver(registry()).resolve(invalid)
    assert error.value.code == "RESEARCH_SPEC_RESEARCH_BACKEND_UNAVAILABLE"


def test_resolver_boundary_duplicate_semantics_and_materialization_failure_are_stable() -> None:
    base = specification()
    resolver = OnlyResearchSpecificationResolver(registry())
    with pytest.raises(TypeError):
        OnlyResearchSpecificationResolver(object())  # type: ignore[arg-type]
    with pytest.raises(OnlyResearchSpecificationError) as invalid:
        resolver.resolve(object())  # type: ignore[arg-type]
    assert invalid.value.code == "RESEARCH_SPEC_INVALID"
    duplicate_statistics = OnlyResearchSpecification(
        base.dataset_snapshot_fingerprint,
        base.calculations,
        (base.statistics[0], base.statistics[0]),
    )
    with pytest.raises(OnlyResearchSpecificationError) as duplicate:
        resolver.resolve(duplicate_statistics)
    assert duplicate.value.code == "RESEARCH_SPEC_DUPLICATE_STATISTICS"

    feature = next(item for item in base.calculations if item.calculation_id == "feature")
    from onlyalpha.research import OnlyResearchGraphTemplate, OnlyResearchGraphTemplateNode

    broken = OnlyResearchGraphTemplateNode(
        feature.graph_template.nodes[0].template_node_id,
        feature.graph_template.nodes[0].type_reference,
        {"unknown_parameter": 1},
    )
    broken_template = OnlyResearchGraphTemplate((broken, *feature.graph_template.nodes[1:]))
    invalid_graph = OnlyResearchSpecification(
        base.dataset_snapshot_fingerprint,
        tuple(
            OnlyResearchCalculationSpec(
                item.calculation_id, broken_template if item is feature else item.graph_template
            )
            for item in base.calculations
        ),
        base.statistics,
    )
    with pytest.raises(OnlyResearchSpecificationError) as materialization:
        resolver.resolve(invalid_graph)
    assert materialization.value.code == "RESEARCH_SPEC_GRAPH_MATERIALIZATION_FAILED"


def test_duplicate_calculation_semantics_fail_at_existing_workload_boundary() -> None:
    base = specification()
    feature = next(item for item in base.calculations if item.calculation_id == "feature")
    duplicate = OnlyResearchSpecification(
        base.dataset_snapshot_fingerprint,
        (*base.calculations, OnlyResearchCalculationSpec("same_graph", feature.graph_template)),
        base.statistics,
    )
    with pytest.raises(OnlyResearchSpecificationError) as error:
        OnlyResearchSpecificationResolver(registry()).resolve(duplicate)
    assert error.value.code == "RESEARCH_SPEC_WORKLOAD_INVALID"
