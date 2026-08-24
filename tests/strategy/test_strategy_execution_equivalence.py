from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from onlyalpha.domain.value import OnlyPrice
from onlyalpha.research import OnlyResearchCalculationBackendResolver, OnlyResearchCalculationExecutor
from onlyalpha.strategy import (
    OnlyStrategyExecutionResolver,
    OnlyStrategyResolutionError,
    OnlyStrategyRevisionStore,
    only_strategy_observation_fingerprint,
    only_strategy_observation_key,
)
from tests.strategy.p9_support import p9_strategy_case


def test_research_batch_and_trading_incremental_decisions_are_exactly_equivalent(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    research = OnlyResearchCalculationExecutor(
        case.dataset_store,
        OnlyResearchCalculationBackendResolver(case.registry),
    ).execute(case.dataset_fingerprint, case.revision.decision_graph)
    store = OnlyStrategyRevisionStore(tmp_path / "semantic")
    store.commit(case.revision)
    trading = (
        OnlyStrategyExecutionResolver(store, case.registry).resolve(case.revision.strategy_fingerprint).new_executor()
    )
    decisions = [trading.execute(bar) for bar in case.bars]

    definitions = {item.fingerprint: item.definition for item in case.revision.decision_graph.nodes}
    research_signals = {
        (definitions[item.node_fingerprint].outputs[0].semantic_type, item.instrument_id): tuple(
            False if value is None else value for value in item.table.column("value").to_pylist()
        )
        for item in research.outputs
        if definitions[item.node_fingerprint].type_id.startswith("onlyalpha.predicate.internal.terminal")
    }
    trading_signals = {
        (role, instrument): tuple(getattr(item, attribute) for item in decisions if item.instrument_id == instrument)
        for role, attribute in (
            ("ELIGIBILITY", "eligibility"),
            ("ENTRY_SIGNAL", "entry"),
            ("EXIT_SIGNAL", "exit"),
        )
        for instrument in sorted({item.instrument_id for item in decisions})
    }

    assert trading_signals == research_signals


def test_observation_key_content_and_final_admission_are_distinct(tmp_path) -> None:
    bar = p9_strategy_case(tmp_path / "case").bars[0]
    corrected = replace(bar, close=OnlyPrice(bar.close.value + Decimal("0.50"), bar.close.precision))
    transported = replace(bar, ts_init=bar.ts_init + timedelta(seconds=3))

    assert only_strategy_observation_key(corrected) == only_strategy_observation_key(bar)
    assert only_strategy_observation_fingerprint(corrected) != only_strategy_observation_fingerprint(bar)
    assert only_strategy_observation_fingerprint(transported) == only_strategy_observation_fingerprint(bar)

    case = p9_strategy_case(tmp_path / "second")
    store = OnlyStrategyRevisionStore(tmp_path / "semantic")
    store.commit(case.revision)
    executor = (
        OnlyStrategyExecutionResolver(store, case.registry).resolve(case.revision.strategy_fingerprint).new_executor()
    )
    with pytest.raises(OnlyStrategyResolutionError) as error:
        executor.execute(replace(case.bars[0], is_closed=False))
    assert error.value.code == "STRATEGY_OBSERVATION_NOT_FINAL"


def test_corrected_final_bar_fails_without_implicit_state_rollback(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    store = OnlyStrategyRevisionStore(tmp_path / "semantic")
    store.commit(case.revision)
    executor = (
        OnlyStrategyExecutionResolver(store, case.registry).resolve(case.revision.strategy_fingerprint).new_executor()
    )
    bar = case.bars[0]
    executor.execute(bar)

    with pytest.raises(OnlyStrategyResolutionError) as error:
        executor.execute(replace(bar, close=OnlyPrice(bar.close.value + Decimal("0.50"), bar.close.precision)))
    assert error.value.code == "CORRECTED_FINAL_BAR_UNSUPPORTED"


def test_checkpoint_restores_last_observation_and_incremental_state(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    store = OnlyStrategyRevisionStore(tmp_path / "semantic")
    store.commit(case.revision)
    plan = OnlyStrategyExecutionResolver(store, case.registry).resolve(case.revision.strategy_fingerprint)
    continuous = plan.new_executor()
    resumed = plan.new_executor()
    split = len(case.bars) // 2

    before = [resumed.execute(bar) for bar in case.bars[:split]]
    checkpoint = resumed.capture_checkpoint()
    restored = plan.new_executor()
    restored.restore_checkpoint(checkpoint)
    repeated = restored.execute(case.bars[split - 1])
    after = [restored.execute(bar) for bar in case.bars[split:]]
    expected = [continuous.execute(bar) for bar in case.bars]

    assert repeated == before[-1]
    assert before + after == expected
    assert restored.last_decisions == continuous.last_decisions


def test_checkpoint_rejects_tampered_strategy_identity(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    store = OnlyStrategyRevisionStore(tmp_path / "semantic")
    store.commit(case.revision)
    executor = (
        OnlyStrategyExecutionResolver(store, case.registry).resolve(case.revision.strategy_fingerprint).new_executor()
    )
    executor.execute(case.bars[0])
    checkpoint = dict(executor.capture_checkpoint())
    decisions = dict(checkpoint["last_decisions"])
    instrument = next(iter(decisions))
    decision = dict(decisions[instrument])
    decision["strategy_fingerprint"] = "0" * 64
    decisions[instrument] = decision
    checkpoint["last_decisions"] = decisions

    with pytest.raises(OnlyStrategyResolutionError) as error:
        executor.restore_checkpoint(checkpoint)
    assert error.value.code == "STRATEGY_CHECKPOINT_CORRUPT"


@pytest.mark.parametrize("raw_authority", ({"strategy": "arbitrary"}, "tests.example:PythonStrategy"))
def test_execution_resolver_accepts_only_committed_strategy_fingerprint(tmp_path, raw_authority) -> None:
    case = p9_strategy_case(tmp_path / "case")
    resolver = OnlyStrategyExecutionResolver(OnlyStrategyRevisionStore(tmp_path / "semantic"), case.registry)

    with pytest.raises(OnlyStrategyResolutionError) as error:
        resolver.resolve(raw_authority)
    assert error.value.code == "STRATEGY_RESOLUTION_FAILED"
