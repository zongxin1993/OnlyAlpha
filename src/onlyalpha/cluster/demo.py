"""No-trading demonstration Cluster for Runtime lifecycle and Bar delivery."""

from dataclasses import dataclass

from onlyalpha.cluster.bar_context import OnlyBarContext
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.market_data.subscriptions import OnlyBarSubscription


@dataclass(frozen=True, slots=True)
class OnlyDemoRecord:
    ts_event_ns: int
    primary_bar_type: OnlyBarType
    updated_bar_types: frozenset[OnlyBarType]
    latest_3m: OnlyBar | None


class OnlyDemoCluster(OnlyCluster):
    """Minimal Cluster which declares Bar requirements and records immutable views."""

    def __init__(
        self,
        config: OnlyClusterConfig,
        subscription: OnlyBarSubscription | None = None,
    ) -> None:
        super().__init__(config)
        self.subscription = subscription
        self.started = False
        self.records: list[OnlyDemoRecord] = []

    def on_initialize(self) -> None:
        if self.subscription is not None:
            assert self.context is not None
            self.context.subscriptions.subscribe_bars(self.subscription)

    def on_start(self) -> None:
        self.started = True

    def on_bar(self, bar: OnlyBar, context: OnlyBarContext) -> None:
        latest_3m = next(
            (
                context.snapshot.latest_closed(bar_type)
                for bar_type in context.snapshot.bars.latest_closed_bars
                if bar_type.specification.step == 3
            ),
            None,
        )
        self.records.append(
            OnlyDemoRecord(
                context.snapshot.ts_event.unix_nanos,
                bar.bar_type,
                context.snapshot.updated_bar_types,
                latest_3m,
            )
        )

    def on_stop(self) -> None:
        self.started = False
