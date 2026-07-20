"""Order lifecycle adapter for compiled-rule margin instructions."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.domain.enums import OnlyOffset
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyInstrumentId, OnlyOrderId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyPrice
from onlyalpha.margin.manager import OnlyMarginManager
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.market.runtime_rules import OnlyMarginInstruction, OnlyMarketRuleEngine, OnlyTradeApplicationRequest


class OnlyOrderMarginReservationAdapter:
    """Reserves and releases margin without exposing Manager state to Order."""

    def __init__(
        self,
        manager: OnlyMarginManager,
        accounts: OnlyAccountManager,
        rules: OnlyMarketRuleEngine | None,
        instruments: Mapping[OnlyInstrumentId, OnlyInstrument],
        trading_day: Callable[[OnlyTimestamp], OnlyTradingDay],
        reference_price: Callable[[OnlyOrderSnapshot], OnlyPrice | None],
    ) -> None:
        self._manager = manager
        self._accounts = accounts
        self._rules = rules
        self._instruments = instruments
        self._trading_day = trading_day
        self._reference_price = reference_price

    def reserve(self, order: OnlyOrderSnapshot, timestamp: OnlyTimestamp) -> None:
        if self._rules is None or order.offset is not OnlyOffset.OPEN:
            return
        price = order.price or self._reference_price(order)
        if price is None:
            raise ValueError("margin order requires a deterministic reference price")
        instruction = self._rules.build_order_margin_instruction(
            OnlyTradeApplicationRequest(
                str(order.instrument_id),
                str(order.order_id),
                "",
                str(order.account_id),
                order.side,
                order.quantity.value,
                price.value,
                timestamp.to_datetime(),
                self._trading_day(timestamp),
                OnlyPositionEffect.OPEN,
            )
        )
        if instruction is None:
            return
        self._manager.apply(instruction)
        self._accounts.apply_margin_change(
            order.account_id,
            reserved_delta=instruction.amount,
            timestamp=timestamp,
        )

    def sent(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        del order_id, timestamp

    def release(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        reservation = self._manager.get(str(order_id))
        if reservation is None or reservation.reserved == 0:
            return
        instruction = OnlyMarginInstruction(
            "RELEASE",
            reservation.account_id,
            reservation.instrument_id,
            reservation.currency,
            reservation.reserved,
            reservation.maintenance_required,
            reservation.source_order_id,
            "",
        )
        self._manager.apply(instruction)
        self._accounts.apply_margin_change(
            OnlyAccountId(reservation.account_id),
            reserved_delta=-reservation.reserved,
            released_delta=reservation.reserved,
            timestamp=timestamp,
        )
