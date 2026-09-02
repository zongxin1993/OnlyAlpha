"""Plugin-owned exact-price slippage models."""

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.value import OnlyPrice


class OnlySlippageModel(Protocol):
    def apply(self, side: OnlyOrderSide, price: OnlyPrice) -> OnlyPrice: ...


class OnlyNoSlippageModel:
    def apply(self, side: OnlyOrderSide, price: OnlyPrice) -> OnlyPrice:
        del side
        return price


@dataclass(frozen=True, slots=True)
class OnlyFixedSlippageModel:
    price_offset: OnlyPrice

    def apply(self, side: OnlyOrderSide, price: OnlyPrice) -> OnlyPrice:
        value = (
            price.value + self.price_offset.value
            if side is OnlyOrderSide.BUY
            else price.value - self.price_offset.value
        )
        if value <= 0:
            raise ValueError("slippage cannot produce a non-positive price")
        return OnlyPrice(value, max(price.precision, self.price_offset.precision))
