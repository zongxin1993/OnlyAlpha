from collections.abc import Callable

import pytest

from onlyalpha.cluster.base import OnlyClusterConfig
from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.market_data.subscriptions import OnlyBarSubscription
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime


def test_backtest_runtime_closes_1m_3m_snapshot_loop(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
    make_runtime_bar: Callable[[int, str], OnlyBar],
    runtime_types: tuple[OnlyBarType, OnlyBarType],
) -> None:
    runtime = make_runtime("runtime")
    cluster = OnlyDemoCluster(OnlyClusterConfig("demo"), OnlyBarSubscription(runtime_types))
    runtime.add_cluster("engine", cluster)
    runtime.start()
    results = [runtime.process_bar(make_runtime_bar(index, "10.00")) for index in range(3)]

    assert len(cluster.records) == 3
    assert [record.updated_bar_types for record in cluster.records] == [
        frozenset({runtime_types[0]}),
        frozenset({runtime_types[0]}),
        frozenset(runtime_types),
    ]
    assert cluster.records[-1].latest_3m is not None
    assert results[-1].update.barrier.is_ready
    assert results[-1].advance.current_timestamp_ns == results[-1].update.snapshot.ts_event.unix_nanos
    with pytest.raises(AttributeError):
        cluster.records[-1].latest_3m = None  # type: ignore[misc]


def test_explicit_3m_primary_calls_once_with_latest_1m(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
    make_runtime_bar: Callable[[int, str], OnlyBar],
    runtime_types: tuple[OnlyBarType, OnlyBarType],
) -> None:
    runtime = make_runtime("runtime")
    cluster = OnlyDemoCluster(
        OnlyClusterConfig("demo"),
        OnlyBarSubscription(runtime_types, primary_bar_type=runtime_types[1]),
    )
    runtime.add_cluster("engine", cluster)
    runtime.start()
    results = [runtime.process_bar(make_runtime_bar(index, "10.00")) for index in range(3)]

    assert len(cluster.records) == 1
    assert cluster.records[0].primary_bar_type == runtime_types[1]
    assert results[-1].update.snapshot.latest_closed(runtime_types[0]) == make_runtime_bar(2, "10.00")
