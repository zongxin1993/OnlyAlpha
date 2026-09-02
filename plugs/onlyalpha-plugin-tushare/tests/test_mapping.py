from decimal import Decimal

import pytest
from onlyalpha_plugin_tushare.data_source.mapping import (
    only_ashare_reference,
    only_to_tushare_asset,
    only_to_tushare_symbol,
)
from onlyalpha_plugin_tushare.errors import OnlyTushareError

from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlySymbol, OnlyVenueId


def test_symbol_and_equity_mapping(instrument) -> None:
    assert only_to_tushare_symbol(instrument.instrument_id) == "600000.SH"
    assert only_to_tushare_symbol(OnlyInstrumentId(OnlySymbol("000001"), OnlyVenueId("XSHE"))) == "000001.SZ"
    assert only_to_tushare_asset(instrument) == "E"


def test_unknown_venue_fails() -> None:
    with pytest.raises(OnlyTushareError):
        only_to_tushare_symbol(OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XHKG")))


def test_frozen_joined_reference_maps_to_canonical_authority() -> None:
    reference = only_ashare_reference(
        {
            "ts_code": "600000.SH",
            "exchange": "SSE",
            "security_type": "COMMON_STOCK",
            "market": "主板",
            "lot_size": "100",
            "price_tick": "0.01",
            "st_status": False,
            "suspended": False,
            "pre_close": "10.00",
            "trade_date": "2025-01-02",
            "effective_to": "2025-01-03",
            "source_version": "tushare-fixture-v1",
            "data_version": "reference-v1",
        }
    )
    assert str(reference.instrument_id) == "600000.XSHG"
    assert reference.previous_close == Decimal("10.00")


def test_reference_never_defaults_missing_historical_status() -> None:
    with pytest.raises(OnlyTushareError, match="TUSHARE_REFERENCE_INVALID"):
        only_ashare_reference(
            {
                "ts_code": "600000.SH",
                "exchange": "SSE",
                "security_type": "COMMON_STOCK",
                "market": "主板",
                "lot_size": "100",
                "price_tick": "0.01",
                "pre_close": "10.00",
                "trade_date": "2025-01-02",
                "source_version": "fixture-v1",
                "data_version": "reference-v1",
            }
        )
