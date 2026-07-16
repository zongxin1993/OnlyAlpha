from __future__ import annotations

from enum import StrEnum

from examples.factors.macd_signal.snapshot import OnlyMacdSignalFactorSnapshot
from examples.strategies.macd.config import OnlyMacdStrategyConfig
from examples.strategies.macd.result import OnlyMacdSignal
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyOrderRequestId
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.context import OnlyStrategyBarContext


class OnlyMacdSignalState(StrEnum):
    WARMING_UP = "WARMING_UP"
    FLAT = "FLAT"
    LONG = "LONG"
    WAITING_EXIT_AVAILABILITY = "WAITING_EXIT_AVAILABILITY"


class OnlyMacdStrategy(OnlyStrategy):
    """Consumes only MACD Factor output and submits through Strategy Context."""

    def __init__(self, config: OnlyMacdStrategyConfig) -> None:
        super().__init__(config)
        self.config = config
        self._signal_state = OnlyMacdSignalState.WARMING_UP
        self._signals: list[OnlyMacdSignal] = []
        self._request_sequence = 0
        self._callback_count = 0
        self._has_entered = False
        self._exit_pending = False

    @property
    def signals(self) -> tuple[OnlyMacdSignal, ...]:
        return tuple(self._signals)

    @property
    def signal_state(self) -> OnlyMacdSignalState:
        return self._signal_state

    def on_initialize(self) -> None:
        if self.config.instrument_id is None or self.config.account_id is None or self.config.trade_quantity is None:
            raise ValueError("MACD Strategy typed trading configuration is incomplete")

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        self._callback_count += 1
        factor_id = self.config.required_factor_ids[0]
        factor = context.strategy.factors.require(factor_id, OnlyMacdSignalFactorSnapshot)
        instrument_id = self.config.instrument_id
        if instrument_id is None:
            raise RuntimeError("MACD instrument is unavailable")
        positions = context.strategy.positions
        orders = context.strategy.orders
        allocation = positions.cluster.get(instrument_id)  # type: ignore[union-attr]
        quantity = None if allocation is None else allocation.total_quantity
        available = None if allocation is None else allocation.available_quantity
        has_position = quantity is not None and quantity.value > 0
        has_open_order = bool(orders.list_open())  # type: ignore[union-attr]

        if self._exit_pending and has_position:
            if available is not None and available.value > 0 and not has_open_order:
                self._submit(context, OnlyOrderSide.SELL, available, factor, "PENDING_EXIT")
                self._exit_pending = False
            else:
                self._signal_state = OnlyMacdSignalState.WAITING_EXIT_AVAILABILITY
            return
        if (
            factor.signal == "GOLDEN_CROSS"
            and not has_position
            and not has_open_order
            and (self.config.allow_reentry or not self._has_entered)
        ):
            assert self.config.trade_quantity is not None
            self._submit(context, OnlyOrderSide.BUY, self.config.trade_quantity, factor, "GOLDEN_CROSS")
            self._has_entered = True
        elif factor.signal == "DEATH_CROSS" and has_position and not has_open_order:
            if available is not None and available.value > 0:
                self._submit(context, OnlyOrderSide.SELL, available, factor, "DEATH_CROSS")
            else:
                self._exit_pending = True
                self._signal_state = OnlyMacdSignalState.WAITING_EXIT_AVAILABILITY
                self._record("DEATH_CROSS_BLOCKED", factor, None)
        else:
            self._signal_state = OnlyMacdSignalState.LONG if has_position else OnlyMacdSignalState.FLAT

    def _submit(
        self,
        context: OnlyStrategyBarContext,
        side: OnlyOrderSide,
        quantity: OnlyQuantity,
        factor: OnlyMacdSignalFactorSnapshot,
        signal_type: str,
    ) -> None:
        self._request_sequence += 1
        cluster_id = self.config.cluster_id
        account_id = self.config.account_id
        instrument_id = self.config.instrument_id
        if cluster_id is None or account_id is None or instrument_id is None:
            raise RuntimeError("MACD Strategy identifiers are unavailable")
        request_id = OnlyOrderRequestId(f"{cluster_id}-macd-{self._request_sequence:06d}-{side.value.lower()}")
        context.strategy.orders.submit(  # type: ignore[union-attr]
            OnlyOrderRequest(
                request_id,
                instrument_id,
                side,
                OnlyOrderType.MARKET,
                quantity,
                account_id=account_id,
                offset=OnlyOffset.OPEN if side is OnlyOrderSide.BUY else OnlyOffset.CLOSE,
                tags=("MACD", signal_type),
            )
        )
        self._signal_state = OnlyMacdSignalState.LONG if side is OnlyOrderSide.BUY else OnlyMacdSignalState.FLAT
        self._record(signal_type, factor, request_id)

    def _record(
        self,
        signal_type: str,
        factor: OnlyMacdSignalFactorSnapshot,
        request_id: OnlyOrderRequestId | None,
    ) -> None:
        timestamp = factor.ts_event
        if timestamp is None:
            raise RuntimeError("ready MACD Factor must carry ts_event")
        macd = factor.macd_snapshot
        self._signals.append(
            OnlyMacdSignal(len(self._signals) + 1, signal_type, timestamp, str(macd.dif), str(macd.dea), request_id)
        )

    def build_result_extension(self) -> dict[str, object]:
        return {
            "signals": [item.to_dict() for item in self.signals],
            "signal_state": self.signal_state.value,
            "callback_count": self._callback_count,
        }
