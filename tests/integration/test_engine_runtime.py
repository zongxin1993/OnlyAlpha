from datetime import UTC, datetime

from onlyalpha.cache.memory import OnlyMemoryCache
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.engine.engine import OnlyEngine, OnlyEngineState
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.runtime import OnlyRuntimeState
from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.config import OnlyStrategyConfig
from onlyalpha.strategy.context import OnlyStrategyBarContext
from onlyalpha.strategy.identifiers import OnlyStrategyId


class OnlyFailingStrategy(OnlyStrategy):
    def on_initialize(self) -> None:
        pass

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        del context

    def on_start(self) -> None:
        raise RuntimeError("expected isolated failure")


def test_engine_manages_multiple_runtimes_and_isolates_clusters() -> None:
    engine = OnlyEngine("engine")
    runtimes = [
        OnlyBacktestRuntime(
            f"runtime-{index}",
            OnlyBacktestClock(datetime(2026, 1, index + 1, tzinfo=UTC)),
            OnlyEventBus(),
            OnlyMemoryCache(),
        )
        for index in range(2)
    ]
    healthy = OnlyDemoCluster(OnlyClusterConfig("healthy"))
    runtimes[0].add_cluster(
        engine.engine_id,
        OnlyCluster(
            OnlyClusterConfig("failing"),
            OnlyFailingStrategy(OnlyStrategyConfig(OnlyStrategyId("failing-strategy"))),
        ),
    )
    runtimes[0].add_cluster(engine.engine_id, healthy)
    for runtime in runtimes:
        engine.register_runtime(runtime)

    engine.initialize()
    engine.start()
    assert engine.state is OnlyEngineState.RUNNING
    assert all(runtime.state is OnlyRuntimeState.RUNNING for runtime in runtimes)
    assert healthy.started
    engine.stop()
    engine.stop()
    assert engine.state is OnlyEngineState.STOPPED
