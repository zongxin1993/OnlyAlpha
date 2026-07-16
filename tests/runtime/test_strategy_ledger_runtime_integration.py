from collections.abc import Callable
from decimal import Decimal

from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.domain.identifiers import OnlyClusterId
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime


def test_each_runtime_owns_manager_and_context_is_cluster_scoped(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
) -> None:
    first = make_runtime("ledger-one")
    second = make_runtime("ledger-two")
    assert first.strategy_ledger_manager is not second.strategy_ledger_manager
    cluster_a = OnlyCluster(OnlyClusterConfig("ledger-cluster-a", {"strategy_initial_capital": "12345.67"}))
    cluster_b = OnlyCluster(OnlyClusterConfig("ledger-cluster-b"))
    first.add_cluster("engine", cluster_a)
    first.add_cluster("engine", cluster_b)
    assert cluster_a.context is not None and cluster_b.context is not None
    assert cluster_a.context.ledger.snapshot().key.cluster_id == OnlyClusterId("ledger-cluster-a")
    assert cluster_a.context.ledger.cash_balance.amount == Decimal("12345.67")
    assert cluster_b.context.ledger.snapshot().key.cluster_id == OnlyClusterId("ledger-cluster-b")
