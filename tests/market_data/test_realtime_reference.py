from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyTradeId
from onlyalpha.domain.market import OnlyMarketReferenceKind, OnlyMarketReferenceTick
from onlyalpha.domain.value import OnlyPrice
from onlyalpha.market.models import OnlyCompiledDynamicPriceRequirement
from onlyalpha.market.realtime_reference import OnlyRealtimeMarketReferenceAuthority
from tests.domain_conformance.support.market_data import NOW, build_trade_tick


def _requirement(kind: str, minutes: int | None) -> OnlyCompiledDynamicPriceRequirement:
    return OnlyCompiledDynamicPriceRequirement(
        "rule",
        False,
        kind,
        minutes,
        (("lower", Decimal("0.8")), ("upper", Decimal("1.2"))),
        "REALTIME_MARKET_REFERENCE",
    )


def test_venue_reference_and_complete_trade_vwap_are_distinct_evidence() -> None:
    authority = OnlyRealtimeMarketReferenceAuthority()
    instrument = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    reference = OnlyMarketReferenceTick(
        instrument,
        NOW,
        NOW,
        1,
        "provider",
        OnlyMarketReferenceKind.VENUE_REFERENCE_PRICE,
        OnlyPrice(Decimal("10.00"), 2),
    )
    authority.ingest_reference(reference)
    resolved = authority.resolve(_requirement("VENUE_REFERENCE_PRICE", None), instrument, NOW)
    assert resolved.price == Decimal("10.00")
    assert resolved.evidence_kind == "VENUE_REFERENCE_PRICE"

    fallback = OnlyRealtimeMarketReferenceAuthority()
    base = build_trade_tick()
    for offset, price, quantity in ((-50, "10.00", "1"), (-10, "12.00", "3")):
        fallback.ingest_trade(
            replace(
                base,
                instrument_id=instrument,
                ts_event=NOW + timedelta(seconds=offset),
                ts_init=NOW + timedelta(seconds=offset),
                price=OnlyPrice(Decimal(price), 2),
                quantity=replace(base.quantity, value=Decimal(quantity)),
                trade_id=OnlyTradeId(f"trade-{offset}"),
            )
        )
    window = OnlyTimeRange(NOW - timedelta(minutes=1), NOW)
    assert not fallback.resolve(_requirement("VENUE_REFERENCE_PRICE_OR_TRADE_AVERAGE", 1), instrument, NOW).resolved
    fallback.prove_trade_coverage(instrument, window)
    vwap = fallback.resolve(_requirement("VENUE_REFERENCE_PRICE_OR_TRADE_AVERAGE", 1), instrument, NOW)
    assert vwap.price == Decimal("11.50")
    assert vwap.evidence_kind == "TRADE_VWAP"


def test_zero_minute_fallback_uses_previous_trade() -> None:
    authority = OnlyRealtimeMarketReferenceAuthority()
    trade = build_trade_tick()
    authority.ingest_trade(trade)
    result = authority.resolve(_requirement("VENUE_REFERENCE_PRICE_OR_TRADE_AVERAGE", 0), trade.instrument_id, NOW)
    assert result.price == trade.price.value
    assert result.evidence_kind == "PREVIOUS_TRADE"


def test_explicit_unavailable_reference_is_distinct_from_missing_fact() -> None:
    instrument = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    missing = OnlyRealtimeMarketReferenceAuthority().resolve(
        _requirement("VENUE_REFERENCE_PRICE", None), instrument, NOW
    )
    authority = OnlyRealtimeMarketReferenceAuthority()
    authority.ingest_reference(
        OnlyMarketReferenceTick(
            instrument,
            NOW,
            NOW,
            1,
            "provider",
            OnlyMarketReferenceKind.VENUE_REFERENCE_PRICE,
            None,
        )
    )
    explicit = authority.resolve(_requirement("VENUE_REFERENCE_PRICE", None), instrument, NOW)
    assert not missing.resolved and not explicit.resolved
    assert missing.reason == "venue reference fact is unavailable"
    assert explicit.reason == "venue reference explicitly reports no price"
