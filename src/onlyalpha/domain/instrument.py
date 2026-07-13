"""Minimal versioned instrument hierarchy; market rules remain external."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from onlyalpha.core.errors import OnlyValidationError
from onlyalpha.domain.value import OnlyCurrency


@dataclass(frozen=True, slots=True)
class OnlyInstrumentId:
    """Strong identifier composed of a raw symbol and venue."""

    symbol: str
    venue: str

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.venue.strip():
            raise OnlyValidationError("instrument symbol and venue are required")

    def __str__(self) -> str:
        return f"{self.symbol}.{self.venue}"


@dataclass(frozen=True, slots=True)
class OnlyInstrument:
    """Common immutable instrument specification."""

    instrument_id: OnlyInstrumentId
    quote_currency: OnlyCurrency
    settlement_currency: OnlyCurrency
    price_precision: int
    quantity_precision: int
    price_increment: Decimal
    quantity_increment: Decimal
    version: int = 1
    effective_from: datetime | None = None
    effective_to: datetime | None = None

    def __post_init__(self) -> None:
        if min(self.price_precision, self.quantity_precision) < 0:
            raise OnlyValidationError("instrument precision cannot be negative")
        if self.price_increment <= 0 or self.quantity_increment <= 0 or self.version < 1:
            raise OnlyValidationError("instrument increments and version must be positive")


@dataclass(frozen=True, slots=True)
class OnlyEquity(OnlyInstrument):
    """Tradable company equity; distinct from account equity."""


@dataclass(frozen=True, slots=True)
class OnlyEtf(OnlyInstrument):
    """Exchange-traded fund instrument."""


@dataclass(frozen=True, slots=True)
class OnlyFuture(OnlyInstrument):
    """Future specification with an explicit contract multiplier."""

    contract_multiplier: Decimal = Decimal("1")


@dataclass(frozen=True, slots=True)
class OnlyOption(OnlyInstrument):
    """Option placeholder with explicitly represented strike."""

    strike_price: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class OnlyFxPair(OnlyInstrument):
    """Foreign exchange pair."""


@dataclass(frozen=True, slots=True)
class OnlyCryptoSpot(OnlyInstrument):
    """Crypto spot instrument."""


@dataclass(frozen=True, slots=True)
class OnlyCryptoFuture(OnlyInstrument):
    """Dated crypto future."""


@dataclass(frozen=True, slots=True)
class OnlyCryptoPerpetual(OnlyInstrument):
    """Crypto perpetual contract."""


@dataclass(frozen=True, slots=True)
class OnlyAccountEquity:
    """Account net liquidation value, not a tradable Equity."""

    amount: Decimal
    currency: OnlyCurrency
