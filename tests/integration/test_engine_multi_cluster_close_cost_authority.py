import json
from decimal import Decimal

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.execution import OnlyCommittedExecutionFact
from tests.integration.test_engine_continuous_restart import _sqlite_config


def _configs() -> tuple[OnlyClusterRunConfig, OnlyClusterRunConfig]:
    baseline = _sqlite_config()
    first = json.loads(json.dumps(dict(baseline.normalized_payload)))
    first["runtime"]["end_time"] = "2026-01-05T02:00:00Z"
    first["cluster"]["cluster_id"] = "close-a"
    first["cluster"]["capital"] = {"mode": "FIXED_CAPITAL", "amount": "500000.00", "currency": "CNY"}
    first["strategy"]["class_path"] = "tests.integration.virtual_multi_fill_support:OnlyEarlyScheduledCloseStrategy"
    first["strategy"]["extensions"]["strategy_id"] = "close-a-strategy"

    second = json.loads(json.dumps(first))
    second["cluster"]["cluster_id"] = "close-b"
    second["strategy"]["class_path"] = "tests.integration.virtual_multi_fill_support:OnlyLateScheduledCloseStrategy"
    second["strategy"]["extensions"]["strategy_id"] = "close-b-strategy"
    return (
        OnlyClusterRunConfig.from_mapping(first, source_path=baseline.source_path),
        OnlyClusterRunConfig.from_mapping(second, source_path=baseline.source_path),
    )


def _run(tmp_path, *, reverse: bool = False):  # type: ignore[no-untyped-def]
    configs = _configs()
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
    assert len({item.value for item in buy_price_by_cluster.values()}) == 2
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
