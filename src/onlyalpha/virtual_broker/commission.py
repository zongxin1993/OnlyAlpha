"""Independent deterministic commission models."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity, OnlyRate


class OnlyCommissionModel(Protocol):
    def calculate(
        self,
        side: OnlyOrderSide,
        price: OnlyPrice,
        quantity: OnlyQuantity,
        currency: OnlyCurrency,
    ) -> OnlyMoney: ...


@dataclass(frozen=True, slots=True)
class OnlyFixedCommissionModel:
    amount: OnlyMoney

    def calculate(
        self,
        side: OnlyOrderSide,
        price: OnlyPrice,
        quantity: OnlyQuantity,
        currency: OnlyCurrency,
    ) -> OnlyMoney:
        del side, price, quantity
        if currency != self.amount.currency:
            raise ValueError("fixed commission currency mismatch")
        return self.amount


@dataclass(frozen=True, slots=True)
class OnlyCnEquityCommissionModel:
    commission_rate: OnlyRate
    minimum_commission: OnlyMoney
    stamp_duty_rate: OnlyRate
    transfer_fee_rate: OnlyRate

    def calculate(
        self,
        side: OnlyOrderSide,
        price: OnlyPrice,
        quantity: OnlyQuantity,
        currency: OnlyCurrency,
    ) -> OnlyMoney:
        if self.minimum_commission.currency != currency:
            raise ValueError("commission currency mismatch")
        notional = price.value * quantity.value
        commission = max(notional * self.commission_rate.value, self.minimum_commission.amount)
        transfer = notional * self.transfer_fee_rate.value
        stamp = notional * self.stamp_duty_rate.value if side is OnlyOrderSide.SELL else Decimal(0)
        quantum = Decimal(1).scaleb(-currency.precision)
        return OnlyMoney((commission + transfer + stamp).quantize(quantum), currency)
