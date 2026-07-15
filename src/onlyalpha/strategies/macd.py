"""Product-style MACD example Cluster with no Manager or Broker access."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.cluster.bar_context import OnlyBarContext
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId, OnlyOrderRequestId
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.indicator.base import OnlyIndicatorId
from onlyalpha.indicator.macd import OnlyMacdSnapshot
from onlyalpha.market_data.subscriptions import OnlyBarSubscription


class OnlyMacdSignalState(StrEnum):
    WARMING_UP = "WARMING_UP"
    FLAT = "FLAT"
    LONG = "LONG"
    WAITING_EXIT_AVAILABILITY = "WAITING_EXIT_AVAILABILITY"


@dataclass(frozen=True, slots=True)
class OnlyMacdExampleConfig:
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    primary_bar_type: OnlyBarType
    macd_indicator_id: OnlyIndicatorId
    trade_quantity: OnlyQuantity
    warmup_bars: int
    allow_reentry: bool = False
    exit_mode: str = "FULL_AVAILABLE"

    def __post_init__(self) -> None:
        if self.primary_bar_type.instrument_id != self.instrument_id:
            raise ValueError("MACD primary BarType must belong to the configured Instrument")
        if self.trade_quantity.value <= 0 or self.warmup_bars <= 0:
            raise ValueError("MACD trade quantity and warmup must be positive")
        if self.exit_mode != "FULL_AVAILABLE":
            raise ValueError("first-phase MACD example supports FULL_AVAILABLE exit only")


@dataclass(frozen=True, slots=True)
class OnlyMacdSignal:
    sequence: int
    signal_type: str
    ts_event: OnlyTimestamp
    dif: str
    dea: str
    order_request_id: OnlyOrderRequestId | None = None


class OnlyMacdExampleCluster(OnlyCluster):
    """Trades confirmed MACD crosses and derives sellability from its Allocation view."""

    def __init__(self, strategy_config: OnlyMacdExampleConfig) -> None:
        super().__init__(
            OnlyClusterConfig(
                str(strategy_config.cluster_id),
                {
                    "allowed_account_ids": (strategy_config.account_id,),
                    "allowed_instrument_ids": (strategy_config.instrument_id,),
                },
            )
        )
        self.strategy_config = strategy_config
        self._previous: OnlyMacdSnapshot | None = None
        self._signal_state = OnlyMacdSignalState.WARMING_UP
        self._signals: list[OnlyMacdSignal] = []
        self._macd_trace: list[OnlyMacdSnapshot] = []
        self._request_sequence = 0
        self._has_entered = False
        self._exit_pending = False

    @property
    def signal_state(self) -> OnlyMacdSignalState:
        return self._signal_state

    @property
    def signals(self) -> tuple[OnlyMacdSignal, ...]:
        return tuple(self._signals)

    @property
    def macd_trace(self) -> tuple[OnlyMacdSnapshot, ...]:
        return tuple(self._macd_trace)

    def on_initialize(self) -> None:
        if self.context is None:
            raise RuntimeError("MACD Cluster Context is unavailable")
        self.context.subscriptions.subscribe_bars(
            OnlyBarSubscription(
                (self.strategy_config.primary_bar_type,),
                primary_bar_type=self.strategy_config.primary_bar_type,
            ),
            indicator_ids=(self.strategy_config.macd_indicator_id,),
        )

    def on_bar(self, bar: OnlyBar, context: OnlyBarContext) -> None:
        del bar
        runtime = context.runtime
        value = runtime.market_data.indicator(self.strategy_config.macd_indicator_id)
        if not isinstance(value, OnlyMacdSnapshot):
            raise TypeError("MACD Cluster requires OnlyMacdSnapshot")
        self._macd_trace.append(value)
        allocation = runtime.positions.cluster.get(self.strategy_config.instrument_id)
        quantity = None if allocation is None else allocation.total_quantity
        available = None if allocation is None else allocation.available_quantity
        has_position = quantity is not None and quantity.value > 0
        has_open_order = bool(runtime.orders.list_open())

        if value.samples < self.strategy_config.warmup_bars or not value.ready:
            self._signal_state = OnlyMacdSignalState.WARMING_UP
            self._previous = value
            return

        if self._exit_pending and has_position:
            if available is not None and available.value > 0 and not has_open_order:
                self._submit(runtime, OnlyOrderSide.SELL, available, value, "PENDING_EXIT")
                self._exit_pending = False
            else:
                self._signal_state = OnlyMacdSignalState.WAITING_EXIT_AVAILABILITY
            self._previous = value
            return

        previous = self._previous
        golden_cross = previous is not None and previous.dif <= previous.dea and value.dif > value.dea
        death_cross = previous is not None and previous.dif >= previous.dea and value.dif < value.dea

        if (
            golden_cross
            and not has_position
            and not has_open_order
            and (self.strategy_config.allow_reentry or not self._has_entered)
        ):
            self._submit(runtime, OnlyOrderSide.BUY, self.strategy_config.trade_quantity, value, "GOLDEN_CROSS")
            self._has_entered = True
        elif death_cross and has_position and not has_open_order:
            if available is not None and available.value > 0:
                self._submit(runtime, OnlyOrderSide.SELL, available, value, "DEATH_CROSS")
            else:
                self._exit_pending = True
                self._signal_state = OnlyMacdSignalState.WAITING_EXIT_AVAILABILITY
                self._record("DEATH_CROSS_BLOCKED", value, None)
        else:
            self._signal_state = OnlyMacdSignalState.LONG if has_position else OnlyMacdSignalState.FLAT
        self._previous = value

    def _submit(
        self,
        runtime: object,
        side: OnlyOrderSide,
        quantity: OnlyQuantity,
        value: OnlyMacdSnapshot,
        signal_type: str,
    ) -> None:
        from onlyalpha.runtime.context import OnlyRuntimeContext

        if not isinstance(runtime, OnlyRuntimeContext):
            raise TypeError("MACD strategy requires the formal Runtime Context")
        self._request_sequence += 1
        request_id = OnlyOrderRequestId(
            f"{self.strategy_config.cluster_id}-macd-{self._request_sequence:06d}-{side.value.lower()}"
        )
        result = runtime.orders.submit(
            OnlyOrderRequest(
                request_id,
                self.strategy_config.instrument_id,
                side,
                OnlyOrderType.MARKET,
                quantity,
                account_id=self.strategy_config.account_id,
                offset=OnlyOffset.OPEN if side is OnlyOrderSide.BUY else OnlyOffset.CLOSE,
                tags=("MACD", signal_type),
            )
        )
        if result.order_id is None:
            self._record(f"{signal_type}_REJECTED", value, request_id)
            return
        self._record(signal_type, value, request_id)

    def _record(
        self,
        signal_type: str,
        value: OnlyMacdSnapshot,
        request_id: OnlyOrderRequestId | None,
    ) -> None:
        self._signals.append(
            OnlyMacdSignal(
                len(self._signals) + 1,
                signal_type,
                value.ts_event,
                str(value.dif),
                str(value.dea),
                request_id,
            )
        )
