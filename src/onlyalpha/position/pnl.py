"""Pluggable Position PnL and valuation formulas."""

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Protocol

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.position.enums import OnlyPositionSide
from onlyalpha.position.models import OnlyPositionSnapshot, OnlyPositionValuation


class OnlyPnLModel(Protocol):
    def realized(
        self,
        side: OnlyPositionSide,
        entry_price: OnlyPrice,
        exit_price: OnlyPrice,
        quantity: OnlyQuantity,
        multiplier: OnlyMultiplier,
        currency: OnlyCurrency,
    ) -> OnlyMoney: ...

    def unrealized(
        self,
        side: OnlyPositionSide,
        entry_price: OnlyPrice,
        mark_price: OnlyPrice,
        quantity: OnlyQuantity,
        multiplier: OnlyMultiplier,
        currency: OnlyCurrency,
    ) -> OnlyMoney: ...


class OnlyLinearPnLModel:
    """Linear PnL with explicit contract multiplier and settlement currency."""

    @staticmethod
    def _calculate(
        side: OnlyPositionSide,
        entry_price: OnlyPrice,
        exit_price: OnlyPrice,
        quantity: OnlyQuantity,
        multiplier: OnlyMultiplier,
        currency: OnlyCurrency,
    ) -> OnlyMoney:
        if side is OnlyPositionSide.FLAT:
            raw = Decimal(0)
        elif side is OnlyPositionSide.LONG:
            raw = (exit_price.value - entry_price.value) * quantity.value * multiplier.value
        else:
            raw = (entry_price.value - exit_price.value) * quantity.value * multiplier.value
        quantum = Decimal(1).scaleb(-currency.precision)
        return OnlyMoney(raw.quantize(quantum, rounding=ROUND_HALF_EVEN), currency)

    def realized(
        self,
        side: OnlyPositionSide,
        entry_price: OnlyPrice,
        exit_price: OnlyPrice,
        quantity: OnlyQuantity,
        multiplier: OnlyMultiplier,
        currency: OnlyCurrency,
    ) -> OnlyMoney:
        return self._calculate(side, entry_price, exit_price, quantity, multiplier, currency)

    def unrealized(
        self,
        side: OnlyPositionSide,
        entry_price: OnlyPrice,
        mark_price: OnlyPrice,
        quantity: OnlyQuantity,
        multiplier: OnlyMultiplier,
        currency: OnlyCurrency,
    ) -> OnlyMoney:
        return self._calculate(side, entry_price, mark_price, quantity, multiplier, currency)


class OnlyPositionValuationService:
    def __init__(self, pnl_model: OnlyPnLModel | None = None) -> None:
        self._pnl_model = pnl_model or OnlyLinearPnLModel()

    def value(
        self,
        snapshot: OnlyPositionSnapshot,
        mark_price: OnlyPrice,
        multiplier: OnlyMultiplier,
        currency: OnlyCurrency,
        valuation_time: OnlyTimestamp,
        *,
        price_source: str,
    ) -> OnlyPositionValuation:
        if snapshot.average_open_price is None:
            raise ValueError("cannot value a Position without average open price")
        quantum = Decimal(1).scaleb(-currency.precision)
        market_value = OnlyMoney(
            (mark_price.value * snapshot.total_quantity.value * multiplier.value).quantize(quantum),
            currency,
        )
        unrealized = self._pnl_model.unrealized(
            snapshot.position_side,
            snapshot.average_open_price,
            mark_price,
            snapshot.total_quantity,
            multiplier,
            currency,
        )
        return OnlyPositionValuation(
            snapshot.position_id,
            mark_price,
            market_value,
            unrealized,
            valuation_time,
            price_source,
            currency,
        )
