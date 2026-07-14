from collections.abc import Callable

from onlyalpha.cluster.base import OnlyClusterConfig
from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.market_data.subscriptions import OnlyBarSubscription
from onlyalpha.runtime.runtime import OnlyBacktestRuntime


def _replay(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
    make_bar: Callable[[int, str], OnlyBar],
    bar_types: tuple[OnlyBarType, OnlyBarType],
    runtime_id: str,
    close: str,
) -> tuple[tuple[object, ...], int, tuple[int, ...]]:
    runtime = make_runtime(runtime_id)
    cluster = OnlyDemoCluster(OnlyClusterConfig("demo"), OnlyBarSubscription(bar_types))
    runtime.add_cluster("engine", cluster)
    runtime.start()
    results = [runtime.process_bar(make_bar(index, close)) for index in range(3)]
    records = tuple(
        (
            item.ts_event_ns,
            item.primary_bar_type.to_json(),
            tuple(sorted(bar_type.to_json() for bar_type in item.updated_bar_types)),
            None if item.latest_3m is None else item.latest_3m.to_json(),
        )
        for item in cluster.records
    )
    sequences = tuple(result.update.sequence for result in results)
    return records, runtime.status().clock_time_ns, sequences


def test_two_runtimes_are_isolated(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
    make_runtime_bar: Callable[[int, str], OnlyBar],
    runtime_types: tuple[OnlyBarType, OnlyBarType],
) -> None:
    first = _replay(make_runtime, make_runtime_bar, runtime_types, "first", "10.00")
    second = _replay(make_runtime, make_runtime_bar, runtime_types, "second", "20.00")
    assert first[0] != second[0]
    assert first[1:] == second[1:]


def test_replay_is_identical_one_hundred_times(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
    make_runtime_bar: Callable[[int, str], OnlyBar],
    runtime_types: tuple[OnlyBarType, OnlyBarType],
) -> None:
    expected = _replay(make_runtime, make_runtime_bar, runtime_types, "runtime-0", "10.00")
    for index in range(1, 100):
        assert _replay(make_runtime, make_runtime_bar, runtime_types, f"runtime-{index}", "10.00") == expected
