"""Non-trading Cluster workload for lifecycle and Bar-delivery demonstrations."""

from dataclasses import dataclass, replace

from onlyalpha.cluster.bar_context import OnlyBarContext
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot
from onlyalpha.market_data.subscriptions import OnlyBarSubscription


@dataclass(frozen=True, slots=True)
class OnlyDemoRecord:
    ts_event_ns: int
    primary_bar_type: OnlyBarType
    updated_bar_types: frozenset[OnlyBarType]
    latest_3m: OnlyBar | None


class OnlyDemoCluster(OnlyCluster):
    """Explicit non-Strategy demo workload; it owns no trading semantics."""

    def __init__(self, config: OnlyClusterConfig, subscription: OnlyBarSubscription | None = None) -> None:
        super().__init__(replace(config, subscription=subscription))
        self._started = False
        self._records: list[OnlyDemoRecord] = []

    @property
    def started(self) -> bool:
        return self._started

    @property
    def records(self) -> list[OnlyDemoRecord]:
        return self._records

    def on_start(self) -> None:
        self._started = True

    def on_bar(self, bar: OnlyBar, context: OnlyBarContext) -> None:
        snapshot = context.snapshot
        if not isinstance(snapshot, OnlyMarketDataSnapshot):
            raise TypeError("Demo Cluster requires a prepared Market Data Snapshot")
        latest_3m = next(
            (
                snapshot.latest_closed(bar_type)
                for bar_type in snapshot.bars.latest_closed_bars
                if bar_type.specification.step == 3
            ),
            None,
        )
        self._records.append(
            OnlyDemoRecord(
                snapshot.ts_event.unix_nanos,
                bar.bar_type,
                snapshot.updated_bar_types,
                latest_3m,
            )
        )

    def on_stop(self) -> None:
        self._started = False


__all__ = ["OnlyDemoCluster", "OnlyDemoRecord"]
