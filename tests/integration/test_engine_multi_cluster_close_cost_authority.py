from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from onlyalpha.config import (
    OnlyClusterCapitalConfig,
    OnlyClusterCapitalMode,
    OnlyClusterRunConfig,
    OnlyRuntimeCheckpointConfig,
    OnlyRuntimePersistenceBackend,
    OnlyRuntimePersistenceConfig,
)
from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.execution import OnlyCommittedExecutionFact
from tests.runtime_runner import only_migrate_cluster_to_strategy


def _configs(user_data_root: Path) -> tuple[OnlyClusterRunConfig, OnlyClusterRunConfig]:
    baseline = only_migrate_cluster_to_strategy(
        OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json"), user_data_root
    )
    capital = OnlyClusterCapitalConfig(
        OnlyClusterCapitalMode.FIXED_CAPITAL,
        OnlyMoney(Decimal("500000.00"), baseline.accounts[0].initial_cash.currency),
    )

    def actions(entry: int, exit_: int, quantity: str) -> tuple[dict[str, object], ...]:
        return (
            {
                "action_id": "OPEN",
                "sequence": entry,
                "type": "SUBMIT_ORDER",
                "instrument_id": "TESTETF.XSHG",
                "side": "BUY",
                "order_type": "LIMIT",
                "quantity": quantity,
                "price": "10.00",
                "offset": "OPEN",
            },
            {
                "action_id": "CLOSE",
                "sequence": exit_,
                "type": "SUBMIT_ORDER",
                "instrument_id": "TESTETF.XSHG",
                "side": "SELL",
                "order_type": "LIMIT",
                "quantity": quantity,
                "price": "0.01",
                "offset": "CLOSE",
            },
        )

    runtime = replace(
        baseline.runtime,
        end_time=baseline.runtime.start_time.replace(minute=0, hour=2),  # type: ignore[union-attr]
        persistence=OnlyRuntimePersistenceConfig(
            OnlyRuntimePersistenceBackend.SQLITE,
            checkpoint=OnlyRuntimeCheckpointConfig(True),
        ),
    )
    first = replace(
        baseline,
        runtime=runtime,
        cluster=replace(
            baseline.cluster,
            cluster_id=type(baseline.cluster.cluster_id)("close-a"),
            capital=capital,
            scenario_actions=actions(1, 18, "1000"),
        ),  # type: ignore[arg-type]
    )
    second = replace(
        baseline,
        runtime=runtime,
        cluster=replace(
            baseline.cluster,
            cluster_id=type(baseline.cluster.cluster_id)("close-b"),
            capital=capital,
            scenario_actions=actions(15, 20, "2000"),
        ),  # type: ignore[arg-type]
    )
    return first, second


def _run(tmp_path, *, reverse: bool = False):  # type: ignore[no-untyped-def]
    configs = _configs(tmp_path)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("multi-cluster-close-authority"), tmp_path))
    for config in reversed(configs) if reverse else configs:
        engine.add_cluster(config)
    result = engine.run()
    return engine, result


def test_engine_multi_cluster_close_uses_cluster_allocation_cost(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, result = _run(tmp_path)

    assert result.status == "COMPLETED", result.failures
    runtime_result = result.runtime_results[0]
    facts = tuple(item for item in runtime_result.trades if isinstance(item, OnlyCommittedExecutionFact))
    buys = tuple(item for item in facts if item.order_side is OnlyOrderSide.BUY)
    close_facts = tuple(item for item in facts if item.order_side is OnlyOrderSide.SELL)
    assert len(buys) == len(close_facts) == 2
    buy_price_by_cluster = {item.cluster_id: item.fill_price for item in buys}
    close_by_cluster = {item.cluster_id: item for item in close_facts}
    assert len({item.fill_quantity.value for item in buys}) == 2
    for fact in close_facts:
        expected_cost = buy_price_by_cluster[fact.cluster_id].value * fact.fill_quantity.value
        assert fact.released_open_price_quantity == expected_cost
        assert fact.realized_pnl_delta.amount == (
            close_by_cluster[fact.cluster_id].fill_price.value * fact.fill_quantity.value - expected_cost
        ).quantize(Decimal("0.01"))
    assert runtime_result.final_positions == ()
    assert runtime_result.final_allocations == ()
    assert runtime_result.final_account.realized_pnl.amount == sum(
        (item.pnl.realized_pnl.amount for item in runtime_result.final_ledgers), Decimal(0)
    )
    assert runtime_result.reconciliation.status == "MATCHED"
