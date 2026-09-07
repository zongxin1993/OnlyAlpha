from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from onlyalpha_plugin_targets.registration import registrations as target_registrations

from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyEngineId, OnlyInstrumentId
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.quant_assets import OnlyQuantAssetCatalogManager
from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyParquetResearchStatisticsResultStore,
)
from onlyalpha.research.search.symbolic import (
    OnlyJsonSymbolicSearchStore,
    OnlySymbolicResearchEvaluationContractV1,
    OnlySymbolicSearchContextResolver,
    enumerate_symbolic_factor_proposals,
    only_deterministic_enumeration_implementation,
    resolve_symbolic_research_candidate,
    verify_symbolic_proposal_reconstruction,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from onlyalpha.runtime.result import OnlyRuntimeResultStatus
from tests.research.calculation.support import snapshot
from tests.research.specification.support import registry as specification_registry

from .support import space
from .test_research_and_provenance_integration import _evaluation, _experiment, _scientific_template


def _known_null_bars() -> tuple[OnlyBar, ...]:
    paths = {
        "A.XNAS": ("100", "101", "103", "102", "104", "107", "106"),
        "B.XNAS": ("97", "99", "98", "101", "100", "102", "101"),
        "C.XNAS": ("103", "102", "104", "101", "105", "103", "106"),
        "D.XNAS": ("99", "98", "100", "97", "101", "100", "102"),
        "E.XNAS": ("101", "103", "101", "104", "102", "105", "103"),
    }
    result = []
    base = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    for instrument, closes in paths.items():
        bar_type = OnlyBarType(
            OnlyInstrumentId.parse(instrument),
            OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.EXTERNAL,
        )
        for index, raw in enumerate(closes):
            value = Decimal(raw)
            start = base + timedelta(minutes=index)
            result.append(
                OnlyBar(
                    bar_type=bar_type,
                    open=OnlyPrice(value, 2),
                    high=OnlyPrice(value + 1, 2),
                    low=OnlyPrice(value - 1, 2),
                    close=OnlyPrice(value, 2),
                    volume=OnlyQuantity(Decimal(100 + index), 0),
                    quote_volume=None,
                    turnover=None,
                    trade_count=index,
                    open_interest=None,
                    bar_start=start,
                    bar_end=start + timedelta(minutes=1),
                    ts_event=start + timedelta(minutes=1),
                    ts_init=start + timedelta(minutes=1),
                    is_closed=True,
                    revision=0,
                    adjustment_type=OnlyAdjustmentType.RAW,
                    trading_day=date(2026, 1, 5),
                    session_type=OnlySessionType.CONTINUOUS,
                )
            )
    return tuple(result)


def test_deterministic_known_null_search_uses_normal_research_without_perfect_prediction(tmp_path) -> None:
    layout = OnlyUserDataLayout(tmp_path)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    candidate_dataset, partitions = snapshot(_known_null_bars())
    dataset = datasets.commit(candidate_dataset, partitions)
    generation, search_space = space(max_nodes=1)
    symbolic = OnlyJsonSymbolicSearchStore(tmp_path)
    evaluation = _evaluation(dataset.snapshot_fingerprint)
    symbolic.commit_search_space(search_space)
    symbolic.commit_evaluation_contract(evaluation)
    symbolic.commit_algorithm_implementation_manifest(only_deterministic_enumeration_implementation())
    experiment = _experiment(
        search_space.search_space_fingerprint,
        generation.generation_fingerprint,
        dataset.snapshot_fingerprint,
        evaluation.evaluation_contract_fingerprint,
    )
    context = OnlySymbolicSearchContextResolver(
        symbolic_store=symbolic,
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=datasets,
        research_calculation_registry=specification_registry(),
    ).resolve_verified_context(experiment)
    first = enumerate_symbolic_factor_proposals(context.verified_search_space, proposal_limit=1).proposals[0]
    repeated = enumerate_symbolic_factor_proposals(context.verified_search_space, proposal_limit=1).proposals[0]
    assert repeated == first

    verified = verify_symbolic_proposal_reconstruction(first, context)
    registry = generation.calculation_registry()
    for registration in target_registrations():
        registry.register(registration)
    resolved = resolve_symbolic_research_candidate(verified, OnlyResearchSpecificationResolver(registry))
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("symbolic-known-null"), tmp_path))
    runtime_id = engine.add_research_workload(resolved.resolution.workload)
    engine.initialize()
    engine.start()
    first_execution = engine.run_runtime(runtime_id)
    engine.stop()
    assert first_execution.status is OnlyRuntimeResultStatus.COMPLETED

    calculations = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calculations)
    results = OnlyJsonResearchResultStore(layout.research_result_root, statistics, calculations)
    loaded = results.load_verified(resolved.resolution.workload.result_plan.fingerprint)
    assert loaded.manifest.research_result_fingerprint == first_execution.research_result_fingerprint
    assert len(loaded.manifest.statistics_results) == 1
    reference = loaded.manifest.statistics_results[0]
    authoritative_statistics = statistics.load_verified(reference.statistics_fingerprint)
    valid = tuple(row.statistic_value for row in authoritative_statistics.rows if row.statistic_value is not None)
    assert valid
    assert all(abs(value) < Decimal("0.95") for value in valid)

    replay = OnlyEngine(OnlyEngineConfig(OnlyEngineId("symbolic-known-null-replay"), tmp_path))
    replay_id = replay.add_research_workload(resolved.resolution.workload)
    replay.initialize()
    replay.start()
    repeated_execution = replay.run_runtime(replay_id)
    replay.stop()
    assert repeated_execution.research_result_fingerprint == first_execution.research_result_fingerprint
    assert statistics.load_verified(reference.statistics_fingerprint) == authoritative_statistics


def test_symbolic_evaluation_candidate_slot_cannot_be_the_target() -> None:
    template = _scientific_template("a" * 64)
    with pytest.raises(ValueError, match="SEARCH_EVALUATION_CANDIDATE_CANNOT_BE_TARGET"):
        OnlySymbolicResearchEvaluationContractV1.from_specification(template, "target")
