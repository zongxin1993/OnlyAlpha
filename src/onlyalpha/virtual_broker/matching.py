"""Minimal deterministic matching engines separate from the Gateway."""

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.broker.models import OnlyBrokerOrderSnapshot
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity


@dataclass(frozen=True, slots=True)
class OnlyMatchingResult(OnlyDomainModel):
    matched: bool
    price: OnlyPrice | None = None
    quantity: OnlyQuantity | None = None
    reason: str = ""


class OnlyMatchingEngine(Protocol):
    def match(self, order: OnlyBrokerOrderSnapshot, bar: OnlyBar) -> OnlyMatchingResult: ...


class OnlyNextBarMatchingEngine:
    """Uses Bar N+1 OHLC and executes at the explicit limit price."""

    def __init__(self, maximum_fill_quantity: OnlyQuantity | None = None) -> None:
        self._maximum = maximum_fill_quantity

    def match(self, order: OnlyBrokerOrderSnapshot, bar: OnlyBar) -> OnlyMatchingResult:
        if order.instrument_id != bar.instrument_id:
            return OnlyMatchingResult(False, reason="different instrument")
        if order.order_type is OnlyOrderType.MARKET:
            price = bar.open
        elif order.price is not None and (
            (order.side is OnlyOrderSide.BUY and bar.low.value <= order.price.value)
            or (order.side is OnlyOrderSide.SELL and bar.high.value >= order.price.value)
        ):
            price = order.price
        else:
            return OnlyMatchingResult(False, reason="limit not crossed")
        quantity = order.remaining_quantity
        if self._maximum is not None and self._maximum.value < quantity.value:
            quantity = OnlyQuantity(self._maximum.value, quantity.precision)
        return OnlyMatchingResult(True, price, quantity)


class OnlyImmediateMatchingEngine(OnlyNextBarMatchingEngine):
    """Same deterministic price rule; caller supplies the current reference Bar."""
