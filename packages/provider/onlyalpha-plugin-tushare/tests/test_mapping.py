import pytest
from onlyalpha_plugin_tushare.data_source.mapping import (
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
