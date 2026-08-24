from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from onlyalpha.calculation import OnlyCalculationBackendKind, OnlyCalculationRegistry
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyAggregationSource
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.value import OnlyPrice
from onlyalpha.research import OnlyResearchCalculationBackendResolver, OnlyResearchCalculationExecutor
from onlyalpha.strategy import (
    OnlyFrozenStrategyRevisionStore,
    OnlyStrategyExecutionResolver,
    OnlyStrategyResolutionError,
    only_strategy_observation_fingerprint,
    only_strategy_observation_key,
)
from onlyalpha.strategy.adapter import OnlyRevisionStrategyAdapter
from tests.strategy.p9_support import p9_strategy_case, publish_frozen_strategy_for_execution_test


def test_research_batch_and_trading_incremental_decisions_are_exactly_equivalent(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    research = OnlyResearchCalculationExecutor(
        case.dataset_store,
        OnlyResearchCalculationBackendResolver(case.registry),
    ).execute(case.dataset_fingerprint, case.revision.decision_graph)
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", case.revision)
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


def test_revision_adapter_returns_exact_decision_synchronously_without_private_decision_log(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", case.revision)
    plan = OnlyStrategyExecutionResolver(store, case.registry).resolve(case.revision.strategy_fingerprint)
    adapter = OnlyRevisionStrategyAdapter(plan)

    decision = adapter.on_bar(case.bars[0])

    assert decision.strategy_fingerprint == str(case.revision.strategy_fingerprint)
    assert adapter.on_bar(case.bars[0]) == decision
    assert not hasattr(adapter, "decisions")


def test_observation_key_content_and_final_admission_are_distinct(tmp_path) -> None:
    bar = p9_strategy_case(tmp_path / "case").bars[0]
    corrected = replace(bar, close=OnlyPrice(bar.close.value + Decimal("0.50"), bar.close.precision))
    transported = replace(bar, ts_init=bar.ts_init + timedelta(seconds=3))

    assert only_strategy_observation_key(corrected) == only_strategy_observation_key(bar)
    assert only_strategy_observation_fingerprint(corrected) != only_strategy_observation_fingerprint(bar)
    assert only_strategy_observation_fingerprint(transported) == only_strategy_observation_fingerprint(bar)

    case = p9_strategy_case(tmp_path / "second")
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", case.revision)
    executor = (
        OnlyStrategyExecutionResolver(store, case.registry).resolve(case.revision.strategy_fingerprint).new_executor()
    )
    with pytest.raises(OnlyStrategyResolutionError) as error:
        executor.execute(replace(case.bars[0], is_closed=False))
    assert error.value.code == "STRATEGY_OBSERVATION_NOT_FINAL"


def test_corrected_final_bar_fails_without_implicit_state_rollback(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", case.revision)
    executor = (
        OnlyStrategyExecutionResolver(store, case.registry).resolve(case.revision.strategy_fingerprint).new_executor()
    )
    bar = case.bars[0]
    executor.execute(bar)

    with pytest.raises(OnlyStrategyResolutionError) as error:
        executor.execute(replace(bar, close=OnlyPrice(bar.close.value + Decimal("0.50"), bar.close.precision)))
    assert error.value.code == "CORRECTED_FINAL_BAR_UNSUPPORTED"


@pytest.mark.parametrize("mismatch", ("instrument", "bar_specification", "aggregation_source", "adjustment"))
def test_market_input_contract_mismatches_fail_closed(tmp_path, mismatch) -> None:
    case = p9_strategy_case(tmp_path / "case")
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", case.revision)
    executor = (
        OnlyStrategyExecutionResolver(store, case.registry).resolve(case.revision.strategy_fingerprint).new_executor()
    )
    bar = case.bars[0]
    if mismatch == "instrument":
        bar = replace(
            bar,
            bar_type=OnlyBarType(
                OnlyInstrumentId.parse("OTHER.XNAS"),
                bar.bar_type.specification,
                bar.bar_type.aggregation_source,
            ),
        )
    elif mismatch == "bar_specification":
        specification = bar.bar_type.specification
        bar = replace(
            bar,
            bar_type=OnlyBarType(
                bar.instrument_id,
                OnlyBarSpecification(
                    specification.step + 1,
                    specification.aggregation,
                    specification.price_type,
                ),
                bar.bar_type.aggregation_source,
            ),
        )
    elif mismatch == "aggregation_source":
        source = (
            OnlyAggregationSource.INTERNAL
            if bar.bar_type.aggregation_source is OnlyAggregationSource.EXTERNAL
            else OnlyAggregationSource.EXTERNAL
        )
        bar = replace(bar, bar_type=OnlyBarType(bar.instrument_id, bar.bar_type.specification, source))
    else:
        bar = replace(bar, adjustment_type=OnlyAdjustmentType.FORWARD)

    with pytest.raises(OnlyStrategyResolutionError) as error:
        executor.execute(bar)
    assert error.value.code == "STRATEGY_OBSERVATION_NOT_ADMITTED"


def test_out_of_order_final_bar_fails_closed(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", case.revision)
    executor = (
        OnlyStrategyExecutionResolver(store, case.registry).resolve(case.revision.strategy_fingerprint).new_executor()
    )
    same_instrument = [bar for bar in case.bars if bar.instrument_id == case.bars[0].instrument_id]
    executor.execute(same_instrument[1])

    with pytest.raises(OnlyStrategyResolutionError) as error:
        executor.execute(same_instrument[0])
    assert error.value.code == "STRATEGY_OBSERVATION_OUT_OF_ORDER"


def test_checkpoint_restores_last_observation_and_incremental_state(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", case.revision)
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
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", case.revision)
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


@pytest.mark.parametrize("field", ("participant_fingerprint", "schema_version"))
def test_checkpoint_rejects_tampered_participant_identity(tmp_path, field) -> None:
    case = p9_strategy_case(tmp_path / "case")
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", case.revision)
    plan = OnlyStrategyExecutionResolver(store, case.registry).resolve(case.revision.strategy_fingerprint)
    executor = plan.new_executor()
    executor.execute(case.bars[0])
    checkpoint = dict(executor.capture_checkpoint())
    instances = dict(checkpoint["instances"])
    participant = next(iter(instances))
    raw = dict(instances[participant])
    raw[field] = "0" * 64 if field == "participant_fingerprint" else int(raw[field]) + 1
    instances[participant] = raw
    checkpoint["instances"] = instances

    with pytest.raises(OnlyStrategyResolutionError) as error:
        plan.new_executor().restore_checkpoint(checkpoint)
    assert error.value.code == "STRATEGY_CHECKPOINT_CORRUPT"


@pytest.mark.parametrize("raw_authority", ({"strategy": "arbitrary"}, "tests.example:PythonStrategy"))
def test_execution_resolver_accepts_only_committed_strategy_fingerprint(tmp_path, raw_authority) -> None:
    case = p9_strategy_case(tmp_path / "case")
    resolver = OnlyStrategyExecutionResolver(OnlyFrozenStrategyRevisionStore(tmp_path / "semantic"), case.registry)

    with pytest.raises(OnlyStrategyResolutionError) as error:
        resolver.resolve(raw_authority)
    assert error.value.code == "STRATEGY_RESOLUTION_FAILED"


def test_trading_resolution_requires_no_research_backend_runtime(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    trading_only = OnlyCalculationRegistry()
    seen = set()
    for node in case.revision.decision_graph.nodes:
        key = (node.definition.kind, node.definition.type_id, node.definition.semantic_version)
        if key in seen:
            continue
        seen.add(key)
        trading_only.register(case.registry.resolve(*key, OnlyCalculationBackendKind.TRADING))
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", case.revision)

    executor = (
        OnlyStrategyExecutionResolver(store, trading_only).resolve(case.revision.strategy_fingerprint).new_executor()
    )

    assert executor.execute(case.bars[0]).strategy_fingerprint == str(case.revision.strategy_fingerprint)


def test_checkpointable_registration_without_restore_fails_closed(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")

    class _BrokenFactory:
        def create(self, definition, request):
            del definition, request
            return object()

    broken = OnlyCalculationRegistry()
    first = next(
        node
        for node in case.revision.decision_graph.ordered_nodes
        if case.registry.resolve(
            node.definition.kind,
            node.definition.type_id,
            node.definition.semantic_version,
            OnlyCalculationBackendKind.TRADING,
        ).checkpoint_schema_version
        is not None
    )
    seen = set()
    for node in case.revision.decision_graph.nodes:
        key = (node.definition.kind, node.definition.type_id, node.definition.semantic_version)
        if key in seen:
            continue
        seen.add(key)
        registration = case.registry.resolve(*key, OnlyCalculationBackendKind.TRADING)
        if key == (first.definition.kind, first.definition.type_id, first.definition.semantic_version):
            registration = replace(registration, provider=_BrokenFactory())
        broken.register(registration)
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", case.revision)
    executor = OnlyStrategyExecutionResolver(store, broken).resolve(case.revision.strategy_fingerprint).new_executor()

    with pytest.raises(OnlyStrategyResolutionError) as error:
        executor.execute(case.bars[0])
    assert error.value.code == "STRATEGY_CHECKPOINT_UNSUPPORTED"
