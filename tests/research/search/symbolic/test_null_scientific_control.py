from __future__ import annotations

import json
import random
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

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

_KNOWN_NULL_SEED = 3_309_2026
_KNOWN_NULL_INSTRUMENTS = ("A.XNAS", "B.XNAS", "C.XNAS", "D.XNAS", "E.XNAS")
_KNOWN_NULL_OBSERVATIONS = 64


def _known_null_innovations(seed: int = _KNOWN_NULL_SEED) -> tuple[tuple[int, ...], ...]:
    """Return a finite IID random-walk DGP with an explicit fixed seed.

    Each return innovation is one independent draw from the same symmetric
    distribution.  The candidate sees only price history through the normal
    causal Calculation graph, while the one-step Target consumes the next
    innovation.  The no-edge property therefore follows from construction,
    rather than from an observed finite-sample IC threshold.
    """

    generator = random.Random(seed)  # noqa: S311 - deterministic scientific fixture, not security randomness
    support = (-3, -2, -1, 1, 2, 3)
    return tuple(
        tuple(generator.choice(support) for _ in range(_KNOWN_NULL_OBSERVATIONS - 1))
        for _instrument in _KNOWN_NULL_INSTRUMENTS
    )


def _known_null_bars(seed: int = _KNOWN_NULL_SEED) -> tuple[OnlyBar, ...]:
    innovations = _known_null_innovations(seed)
    result = []
    base = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    for instrument_index, instrument in enumerate(_KNOWN_NULL_INSTRUMENTS):
        bar_type = OnlyBarType(
            OnlyInstrumentId.parse(instrument),
            OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.EXTERNAL,
        )
        closes = [10_000 + instrument_index * 100]
        for innovation in innovations[instrument_index]:
            closes.append(closes[-1] + innovation)
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


def _execute_known_null(root: Path, engine_id: str) -> dict[str, object]:
    """Execute the null world through the canonical Dataset→Research path."""

    layout = OnlyUserDataLayout(root)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    candidate_dataset, partitions = snapshot(_known_null_bars())
    dataset = datasets.commit(candidate_dataset, partitions)
    generation, search_space = space(max_nodes=1)
    symbolic = OnlyJsonSymbolicSearchStore(root)
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
    proposal = enumerate_symbolic_factor_proposals(context.verified_search_space, proposal_limit=1).proposals[0]
    verified = verify_symbolic_proposal_reconstruction(proposal, context)
    registry = generation.calculation_registry()
    for registration in target_registrations():
        registry.register(registration)
    resolved = resolve_symbolic_research_candidate(verified, OnlyResearchSpecificationResolver(registry))
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId(engine_id), root))
    runtime_id = engine.add_research_workload(resolved.resolution.workload)
    engine.initialize()
    engine.start()
    execution = engine.run_runtime(runtime_id)
    engine.stop()
    assert execution.status is OnlyRuntimeResultStatus.COMPLETED

    calculations = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calculations)
    results = OnlyJsonResearchResultStore(layout.research_result_root, statistics, calculations)
    loaded = results.load_verified(resolved.resolution.workload.result_plan.fingerprint)
    assert len(loaded.manifest.statistics_results) == 1
    reference = loaded.manifest.statistics_results[0]
    authoritative_statistics = statistics.load_verified(reference.statistics_fingerprint)
    valid = tuple(row.statistic_value for row in authoritative_statistics.rows if row.statistic_value is not None)
    assert valid
    return {
        "dataset_fingerprint": dataset.snapshot_fingerprint,
        "proposal_fingerprint": proposal.proposal_fingerprint,
        "candidate_fingerprint": resolved.candidate.candidate_fingerprint,
        "research_result_fingerprint": loaded.manifest.research_result_fingerprint,
        "statistics_fingerprint": reference.statistics_fingerprint,
        "statistics_values": [str(value) for value in valid],
    }


def test_known_null_dgp_is_fixed_seed_iid_and_identity_stable() -> None:
    first = _known_null_innovations()
    assert first == _known_null_innovations()
    assert first != _known_null_innovations(_KNOWN_NULL_SEED + 1)
    assert len(first) == len(_KNOWN_NULL_INSTRUMENTS)
    assert all(len(path) == _KNOWN_NULL_OBSERVATIONS - 1 for path in first)
    assert {innovation for path in first for innovation in path} <= {-3, -2, -1, 1, 2, 3}
    assert _known_null_bars() == _known_null_bars()


def test_deterministic_known_null_search_exact_replays_in_fresh_process(tmp_path) -> None:
    first = _execute_known_null(tmp_path, "symbolic-known-null")
    program = (
        "import json,sys; "
        "from pathlib import Path; "
        "from tests.research.search.symbolic.test_null_scientific_control "
        "import _execute_known_null; "
        "print(json.dumps(_execute_known_null(Path(sys.argv[1]), sys.argv[2]), sort_keys=True))"
    )
    repeated = json.loads(
        subprocess.check_output(
            [sys.executable, "-c", program, str(tmp_path), "symbolic-known-null-fresh-process"],
            text=True,
        )
    )
    assert repeated == first


def test_deterministic_known_null_search_uses_normal_research_without_outcome_threshold(tmp_path) -> None:
    first = _execute_known_null(tmp_path, "symbolic-known-null-normal-path")
    repeated = _execute_known_null(tmp_path, "symbolic-known-null-normal-path-replay")
    assert repeated == first


def test_symbolic_evaluation_candidate_slot_cannot_be_the_target() -> None:
    template = _scientific_template("a" * 64)
    with pytest.raises(ValueError, match="SEARCH_EVALUATION_CANDIDATE_CANNOT_BE_TARGET"):
        OnlySymbolicResearchEvaluationContractV1.from_specification(template, "target")
