"""Instrument-economics authority for normalized fee calculation bases."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Protocol

from onlyalpha.domain.instrument import OnlyFuture, OnlyInstrument
from onlyalpha.domain.value import OnlyMoney, OnlyPrice
from onlyalpha.fee.models import OnlyFeeBasisValues


class OnlyFeeBasisProvider(Protocol):
    def supports(self, instrument: OnlyInstrument) -> bool: ...

    def resolve(
        self,
        *,
        instrument: OnlyInstrument,
        price: OnlyPrice,
        quantity: Decimal,
    ) -> OnlyFeeBasisValues: ...


class OnlyGenericCashFeeBasisProvider:
    def supports(self, instrument: OnlyInstrument) -> bool:
        return not isinstance(instrument, OnlyFuture)

    def resolve(
        self,
        *,
        instrument: OnlyInstrument,
        price: OnlyPrice,
        quantity: Decimal,
    ) -> OnlyFeeBasisValues:
        if not self.supports(instrument) or instrument.contract_multiplier.value != Decimal(1):
            raise ValueError("FEE_BASIS_UNSUPPORTED")
        return OnlyFeeBasisValues(_notional(instrument, price, quantity), quantity, Decimal(0))


class OnlyGenericFuturesFeeBasisProvider:
    """Generic Futures conformance: instrument quantity explicitly means contracts."""

    def supports(self, instrument: OnlyInstrument) -> bool:
        return isinstance(instrument, OnlyFuture)

    def resolve(
        self,
        *,
        instrument: OnlyInstrument,
        price: OnlyPrice,
        quantity: Decimal,
    ) -> OnlyFeeBasisValues:
        if not self.supports(instrument):
            raise ValueError("FEE_BASIS_UNSUPPORTED")
        return OnlyFeeBasisValues(_notional(instrument, price, quantity), quantity, quantity)


class OnlyFeeBasisProviderRegistry:
    def __init__(self, providers: tuple[OnlyFeeBasisProvider, ...] = ()) -> None:
        self._providers = providers

    def require(self, instrument: OnlyInstrument) -> OnlyFeeBasisProvider:
        matches = tuple(provider for provider in self._providers if provider.supports(instrument))
        if len(matches) != 1:
            raise ValueError("FEE_BASIS_UNSUPPORTED")
        return matches[0]


def only_default_fee_basis_provider_registry() -> OnlyFeeBasisProviderRegistry:
    return OnlyFeeBasisProviderRegistry((OnlyGenericCashFeeBasisProvider(), OnlyGenericFuturesFeeBasisProvider()))


def _notional(instrument: OnlyInstrument, price: OnlyPrice, quantity: Decimal) -> OnlyMoney:
    currency = instrument.settlement_currency
    quantum = Decimal(1).scaleb(-currency.precision)
    amount = (price.value * quantity * instrument.contract_multiplier.value).quantize(quantum, ROUND_HALF_EVEN)
    return OnlyMoney(amount, currency)


__all__ = [
    "OnlyFeeBasisProvider",
    "OnlyFeeBasisProviderRegistry",
    "OnlyGenericCashFeeBasisProvider",
    "OnlyGenericFuturesFeeBasisProvider",
    "only_default_fee_basis_provider_registry",
]
