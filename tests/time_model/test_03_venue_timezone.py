from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.domain.enums import OnlyMarketType
from onlyalpha.domain.identifiers import (
    OnlyCalendarId,
    OnlyInstrumentId,
    OnlyRawSymbol,
    OnlySessionProfileId,
    OnlySymbol,
    OnlyVenueId,
)
from onlyalpha.domain.instrument import OnlyEquity
from onlyalpha.domain.time import OnlyTimeZone
from onlyalpha.domain.value import OnlyCurrency, OnlyPrice, OnlyQuantity
from onlyalpha.domain.venue import OnlyVenue


def test_venue_owns_default_timezone_calendar_and_profile() -> None:
    venue = OnlyVenue(
        venue_id=OnlyVenueId("XNYS"),
        name="New York Stock Exchange",
        timezone=OnlyTimeZone("America/New_York"),
        default_calendar_id=OnlyCalendarId("XNYS"),
        default_session_profile_id=OnlySessionProfileId("XNYS-EQUITY"),
    )
    assert venue.timezone.name == "America/New_York"


def test_instrument_references_calendar_and_session_profile() -> None:
    instrument = OnlyEquity(
        instrument_id=OnlyInstrumentId(OnlySymbol("IBM"), OnlyVenueId("XNYS")),
        raw_symbol=OnlyRawSymbol("IBM"),
        market_type=OnlyMarketType.CASH,
        quote_currency=OnlyCurrency("USD", 2),
        settlement_currency=OnlyCurrency("USD", 2),
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        step_size=OnlyQuantity(Decimal("1"), 0),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        trading_calendar_id=OnlyCalendarId("XNYS"),
        session_profile_id=OnlySessionProfileId("XNYS-EQUITY"),
        timezone="America/New_York",  # Deprecated compatibility metadata.
    )
    assert instrument.venue == OnlyVenueId("XNYS")
    assert instrument.trading_calendar_id == OnlyCalendarId("XNYS")
