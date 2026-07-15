"""Restricted Runtime capabilities exposed to one Cluster."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from onlyalpha.core.clock import OnlyClockView, OnlyTimerEvent, OnlyTimerHandle
from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId, OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.indicator.base import OnlyIndicatorId, OnlyIndicatorValue

if TYPE_CHECKING:
    from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot
    from onlyalpha.market_data.subscriptions import OnlyBarSubscription, OnlyBarSubscriptionId
    from onlyalpha.order.views import OnlyOrderServiceView
    from onlyalpha.position.views import OnlyPositionContextView
    from onlyalpha.risk.views import OnlyRiskSnapshotView


class OnlyRuntimeContextError(Exception):
    """A Cluster requested a capability outside its lifecycle or scope."""


class OnlyRuntimeLogger:
    """Cluster-bound logger facade which cannot replace handlers or configuration."""

    __slots__ = ("__logger", "__prefix")

    def __init__(
        self,
        logger: logging.Logger,
        runtime_id: OnlyRuntimeId,
        cluster_id: OnlyClusterId,
        mode: OnlyRuntimeMode,
    ) -> None:
        self.__logger = logger
        self.__prefix = f"runtime={runtime_id} cluster={cluster_id} mode={mode.value}"

    def debug(self, message: str, *args: object) -> None:
        self.__logger.debug("%s " + message, self.__prefix, *args)

    def info(self, message: str, *args: object) -> None:
        self.__logger.info("%s " + message, self.__prefix, *args)

    def warning(self, message: str, *args: object) -> None:
        self.__logger.warning("%s " + message, self.__prefix, *args)

    def error(self, message: str, *args: object) -> None:
        self.__logger.error("%s " + message, self.__prefix, *args)


class OnlyMarketDataView:
    """Read-only, subscription-scoped access to closed market-data facts."""

    __slots__ = ("__allowed", "__history", "__indicator", "__latest", "__snapshot")

    def __init__(
        self,
        allowed: Callable[[], frozenset[OnlyBarType]],
        latest: Callable[[OnlyBarType], OnlyBar | None],
        history: Callable[[OnlyBarType, int], tuple[OnlyBar, ...]],
        indicator: Callable[[OnlyIndicatorId], OnlyIndicatorValue | None],
        snapshot: Callable[[], OnlyMarketDataSnapshot | None],
    ) -> None:
        self.__allowed = allowed
        self.__latest = latest
        self.__history = history
        self.__indicator = indicator
        self.__snapshot = snapshot

    def latest_closed(self, bar_type: OnlyBarType) -> OnlyBar | None:
        self.__require_bar_type(bar_type)
        return self.__latest(bar_type)

    def history(self, bar_type: OnlyBarType, count: int) -> tuple[OnlyBar, ...]:
        self.__require_bar_type(bar_type)
        return self.__history(bar_type, count)

    def indicator(self, indicator_id: OnlyIndicatorId) -> OnlyIndicatorValue | None:
        return self.__indicator(indicator_id)

    def current_snapshot(self) -> OnlyMarketDataSnapshot | None:
        return self.__snapshot()

    def __require_bar_type(self, bar_type: OnlyBarType) -> None:
        if bar_type not in self.__allowed():
            raise OnlyRuntimeContextError("Cluster cannot read an unsubscribed BarType")


class OnlyInstrumentView:
    """Immutable instrument lookup facade for the first Runtime phase."""

    __slots__ = ("__instruments",)

    def __init__(self, instruments: Mapping[OnlyInstrumentId, object] | None = None) -> None:
        self.__instruments = MappingProxyType(dict(instruments or {}))

    def get(self, instrument_id: OnlyInstrumentId) -> object | None:
        return self.__instruments.get(instrument_id)

    def require(self, instrument_id: OnlyInstrumentId) -> object:
        instrument = self.get(instrument_id)
        if instrument is None:
            raise OnlyRuntimeContextError(f"unknown instrument: {instrument_id}")
        return instrument


class OnlySubscriptionService:
    """Cluster-scoped Bar subscription capability, open only during initialization."""

    __slots__ = ("__subscribe",)

    def __init__(
        self,
        subscribe: Callable[
            [OnlyBarSubscription, tuple[OnlyIndicatorId, ...]],
            OnlyBarSubscriptionId,
        ],
    ) -> None:
        self.__subscribe = subscribe

    def subscribe_bars(
        self,
        subscription: OnlyBarSubscription,
        *,
        indicator_ids: tuple[OnlyIndicatorId, ...] = (),
    ) -> OnlyBarSubscriptionId:
        return self.__subscribe(subscription, indicator_ids)


class OnlyTimerService:
    """Cluster-scoped deterministic Timer capability with automatic namespacing."""

    __slots__ = ("__cancel", "__schedule_after", "__schedule_at", "__schedule_every")

    def __init__(
        self,
        schedule_at: Callable[[str, int], OnlyTimerHandle],
        schedule_after: Callable[[str, int], OnlyTimerHandle],
        schedule_every: Callable[[str, int, int | None], OnlyTimerHandle],
        cancel: Callable[[str], bool],
    ) -> None:
        self.__schedule_at = schedule_at
        self.__schedule_after = schedule_after
        self.__schedule_every = schedule_every
        self.__cancel = cancel

    def schedule_at(self, timer_id: str, when_ns: int) -> OnlyTimerHandle:
        return self.__schedule_at(timer_id, when_ns)

    def schedule_after(self, timer_id: str, delay_ns: int) -> OnlyTimerHandle:
        return self.__schedule_after(timer_id, delay_ns)

    def schedule_every(self, timer_id: str, interval_ns: int, *, start_ns: int | None = None) -> OnlyTimerHandle:
        return self.__schedule_every(timer_id, interval_ns, start_ns)

    def cancel(self, timer_id: str) -> bool:
        return self.__cancel(timer_id)


@dataclass(frozen=True, slots=True)
class OnlyRuntimeContext:
    """Immutable facade containing only capabilities authorized for one Cluster."""

    engine_id: OnlyEngineId
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    mode: OnlyRuntimeMode
    clock: OnlyClockView
    market_data: OnlyMarketDataView
    instruments: OnlyInstrumentView
    subscriptions: OnlySubscriptionService
    timers: OnlyTimerService
    orders: OnlyOrderServiceView
    positions: OnlyPositionContextView
    risk: OnlyRiskSnapshotView
    logger: OnlyRuntimeLogger


OnlyRuntimeContextView = OnlyRuntimeContext
OnlyClusterContext = OnlyRuntimeContext


@dataclass(frozen=True, slots=True)
class OnlyTimerContext:
    """Immutable context for one Cluster Timer callback."""

    event: OnlyTimerEvent
    runtime: OnlyRuntimeContextView

    @property
    def clock(self) -> OnlyClockView:
        return self.runtime.clock
