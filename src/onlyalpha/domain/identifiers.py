"""Strong identifiers which prevent accidental cross-entity substitution."""

from dataclasses import dataclass
from typing import Self

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.errors import OnlyValidationError


@dataclass(frozen=True, slots=True)
class OnlyIdentifier(OnlyDomainModel):
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized or len(normalized) > 128:
            raise OnlyValidationError(f"{type(self).__name__} must contain 1 to 128 characters")
        if any(character.isspace() for character in normalized):
            raise OnlyValidationError(f"{type(self).__name__} cannot contain whitespace")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value

    @classmethod
    def parse(cls, value: str) -> Self:
        return cls(value)


@dataclass(frozen=True, slots=True)
class OnlySymbol(OnlyIdentifier):
    """Normalized system symbol."""


@dataclass(frozen=True, slots=True)
class OnlyRawSymbol(OnlyIdentifier):
    """Venue-native symbol retained without inference."""


@dataclass(frozen=True, slots=True)
class OnlyVenueId(OnlyIdentifier):
    """Trading venue identity independent from exchange enums."""


@dataclass(frozen=True, slots=True)
class OnlyCalendarId(OnlyIdentifier):
    """Version-independent trading calendar identity."""


@dataclass(frozen=True, slots=True)
class OnlySessionProfileId(OnlyIdentifier):
    """Reusable set of trading-session rules."""


@dataclass(frozen=True, slots=True)
class OnlyInstrumentId(OnlyDomainModel):
    symbol: OnlySymbol
    venue: OnlyVenueId

    def __str__(self) -> str:
        return f"{self.symbol}.{self.venue}"

    @classmethod
    def parse(cls, value: str) -> Self:
        symbol, separator, venue = value.rpartition(".")
        if not separator:
            raise OnlyValidationError("instrument id must use SYMBOL.VENUE format")
        return cls(OnlySymbol(symbol), OnlyVenueId(venue))


@dataclass(frozen=True, slots=True)
class OnlyOrderId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyVenueOrderId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyTradeId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyPositionId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyAccountId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyClusterId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyRuntimeId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyEngineId(OnlyIdentifier):
    pass
