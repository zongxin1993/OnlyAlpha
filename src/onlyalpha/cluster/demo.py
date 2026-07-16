"""No-trading Strategy and Cluster container for lifecycle/Bar delivery demos."""

from dataclasses import dataclass, replace

from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot
from onlyalpha.market_data.subscriptions import OnlyBarSubscription
from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.config import OnlyStrategyConfig
from onlyalpha.strategy.context import OnlyStrategyBarContext
from onlyalpha.strategy.identifiers import OnlyStrategyId


@dataclass(frozen=True, slots=True)
class OnlyDemoRecord:
    ts_event_ns: int
    primary_bar_type: OnlyBarType
    updated_bar_types: frozenset[OnlyBarType]
    latest_3m: OnlyBar | None


class OnlyDemoStrategy(OnlyStrategy):
    def __init__(self, strategy_id: str) -> None:
        super().__init__(OnlyStrategyConfig(OnlyStrategyId(strategy_id)))
        self.started = False
        self.records: list[OnlyDemoRecord] = []

    def on_initialize(self) -> None:
        pass

    def on_start(self) -> None:
        self.started = True

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        snapshot = context.snapshot
        if not isinstance(snapshot, OnlyMarketDataSnapshot) or not isinstance(context.primary_bar, OnlyBar):
            raise TypeError("Demo Strategy requires prepared Bar and Snapshot")
        latest_3m = next(
            (
                snapshot.latest_closed(bar_type)
                for bar_type in snapshot.bars.latest_closed_bars
                if bar_type.specification.step == 3
            ),
            None,
        )
        self.records.append(
            OnlyDemoRecord(
                snapshot.ts_event.unix_nanos,
                context.primary_bar.bar_type,
                snapshot.updated_bar_types,
                latest_3m,
            )
        )

    def on_stop(self) -> None:
        self.started = False


class OnlyDemoCluster(OnlyCluster):
    """Convenience container; all callback behavior belongs to OnlyDemoStrategy."""

    def __init__(self, config: OnlyClusterConfig, subscription: OnlyBarSubscription | None = None) -> None:
        strategy = OnlyDemoStrategy(f"{config.cluster_id}-demo")
        super().__init__(replace(config, subscription=subscription), strategy)
        self.demo_strategy = strategy

    @property
    def started(self) -> bool:
        return self.demo_strategy.started

    @property
    def records(self) -> list[OnlyDemoRecord]:
        return self.demo_strategy.records
