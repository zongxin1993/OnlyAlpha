from __future__ import annotations

from enum import StrEnum
from typing import cast

from examples.factor.time_series.macd_signal.snapshot import OnlyMacdSignalFactorSnapshot
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyOrderRequestId
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.order.views import OnlyOrderServiceView
from onlyalpha.position.views import OnlyPositionContextView
from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.context import OnlyStrategyBarContext

from .config import OnlyMacdStrategyConfig
from .result import OnlyMacdSignal


class OnlyMacdSignalState(StrEnum):
    WARMING_UP = "WARMING_UP"
    FLAT = "FLAT"
    LONG = "LONG"
    WAITING_EXIT_AVAILABILITY = "WAITING_EXIT_AVAILABILITY"


class OnlyMacdStrategy(OnlyStrategy):
    """Consumes only MACD Factor output and submits through Strategy Context."""

    def __init__(self, config: OnlyMacdStrategyConfig) -> None:
        super().__init__(config)
        self.macd_config = config
        self._signal_state = OnlyMacdSignalState.WARMING_UP
        self._signals: list[OnlyMacdSignal] = []
        self._request_sequence = 0
        self._callback_count = 0
        self._has_entered = False
        self._entry_count = 0
        self._exit_pending = False
        self._order_attempts: list[dict[str, object]] = []

    @property
    def signals(self) -> tuple[OnlyMacdSignal, ...]:
        return tuple(self._signals)

    @property
    def signal_state(self) -> OnlyMacdSignalState:
        return self._signal_state

    def on_initialize(self) -> None:
        if (
            self.macd_config.instrument_id is None
            or self.macd_config.account_id is None
            or self.macd_config.trade_quantity is None
        ):
            raise ValueError("MACD Strategy typed trading configuration is incomplete")

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        self._callback_count += 1
        factor_id = self.macd_config.required_factor_ids[0]
        factor = context.strategy.factors.require(factor_id, OnlyMacdSignalFactorSnapshot)
        instrument_id = self.macd_config.instrument_id
        if instrument_id is None:
            raise RuntimeError("MACD instrument is unavailable")
        positions = cast(OnlyPositionContextView, context.strategy.positions)
        orders = cast(OnlyOrderServiceView, context.strategy.orders)
        allocation = positions.cluster.get(instrument_id)
        quantity = None if allocation is None else allocation.total_quantity
        available = None if allocation is None else allocation.available_quantity
        has_position = quantity is not None and quantity.value > 0
        has_open_order = bool(orders.list_open())

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
            and (self.macd_config.allow_reentry or not self._has_entered)
            and self._entry_count < self.macd_config.max_entries
        ):
            assert self.macd_config.trade_quantity is not None
            self._submit(
                context,
                OnlyOrderSide.BUY,
                self.macd_config.trade_quantity,
                factor,
                "GOLDEN_CROSS",
            )
            self._has_entered = True
            self._entry_count += 1
        elif factor.signal == "DEATH_CROSS" and has_position and not has_open_order:
            if available is not None and available.value > 0:
                self._submit(context, OnlyOrderSide.SELL, available, factor, "DEATH_CROSS")
            else:
                self._exit_pending = True
                self._signal_state = OnlyMacdSignalState.WAITING_EXIT_AVAILABILITY
                self._record(context, "DEATH_CROSS_BLOCKED", factor, None)
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
        cluster_id = self.macd_config.cluster_id
        account_id = self.macd_config.account_id
        instrument_id = self.macd_config.instrument_id
        if cluster_id is None or account_id is None or instrument_id is None:
            raise RuntimeError("MACD Strategy identifiers are unavailable")
        request_id = OnlyOrderRequestId(f"{cluster_id}-macd-{self._request_sequence:06d}-{side.value.lower()}")
        result = cast(OnlyOrderServiceView, context.strategy.orders).submit(
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
        self._order_attempts.append(
            {
                "request_id": str(request_id),
                "side": side.value,
                "created": result.created,
                "submitted": result.submitted,
                "order_id": None if result.order_id is None else str(result.order_id),
                "error": result.error,
                "risk_rejection": (
                    None
                    if result.risk_rejection is None
                    else {
                        "rule_id": str(result.risk_rejection.rule_id),
                        "code": result.risk_rejection.code.value,
                        "message": result.risk_rejection.message,
                    }
                ),
            }
        )
        self._signal_state = OnlyMacdSignalState.LONG if side is OnlyOrderSide.BUY else OnlyMacdSignalState.FLAT
        self._record(context, signal_type, factor, request_id)

    def _record(
        self,
        context: OnlyStrategyBarContext,
        signal_type: str,
        factor: OnlyMacdSignalFactorSnapshot,
        request_id: OnlyOrderRequestId | None,
    ) -> None:
        timestamp = factor.ts_event
        if timestamp is None:
            raise RuntimeError("ready MACD Factor must carry ts_event")
        macd = factor.macd_snapshot
        self._signals.append(
            OnlyMacdSignal(
                len(self._signals) + 1,
                signal_type,
                timestamp,
                str(macd.dif),
                str(macd.dea),
                request_id,
            )
        )
        bar = context.primary_bar
        if not isinstance(bar, OnlyBar):
            raise TypeError("MACD signal recording requires an OnlyBar primary input")
        instrument_id = self.macd_config.instrument_id
        if instrument_id is None:
            raise RuntimeError("MACD instrument is unavailable")
        context.strategy.results.record_signal(
            signal_type=signal_type,
            instrument_id=str(instrument_id),
            factor_id=str(factor.factor_id),
            ts_event=timestamp.to_datetime(),
            trading_day=bar.trading_day,
            score=factor.trend_score,
            confidence=factor.confidence,
            related_order_request_id=None if request_id is None else str(request_id),
            payload={"dif": str(macd.dif), "dea": str(macd.dea)},
        )

    def build_result_extension(self) -> dict[str, object]:
        return {
            "signals": [item.to_dict() for item in self.signals],
            "signal_state": self.signal_state.value,
            "callback_count": self._callback_count,
            "entry_count": self._entry_count,
            "order_attempts": list(self._order_attempts),
        }
