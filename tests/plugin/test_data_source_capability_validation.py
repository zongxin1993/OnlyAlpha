import logging
from pathlib import Path

from onlyalpha_test_plugin.data_source import OnlyExternalTestDataSourceFactory

from onlyalpha.config.models import OnlyDataSourceCoverageConfig
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId, OnlySymbol, OnlyVenueId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.plugin import OnlyDataSourceCapabilities
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest


def test_data_source_capability_reports_missing_requirement() -> None:
    actual = OnlyDataSourceCapabilities(historical_bars=True)
    required = OnlyDataSourceCapabilities(historical_bars=True, live_ticks=True)
    assert actual.missing(required) == ("live_ticks",)


def test_data_source_factory_validates_requested_capabilities_before_create() -> None:
    factory = OnlyExternalTestDataSourceFactory()
    instrument_id = OnlyInstrumentId(OnlySymbol("TEST"), OnlyVenueId("XSHG"))
    request = OnlyDataSourceCreateRequest(
        OnlyMarketDataSourceId("limited"),
        factory.parse_config({"market_config": "synthetic_market.yaml"}),
        "LIVE",
        OnlyDataSourceCapabilities(live_ticks=True),
        OnlyBacktestClock(OnlyTimestamp(0).to_datetime()),
        OnlyEventBus(),
        {},
        {},
        {},
        (),
        OnlyDataSourceCoverageConfig(instrument_ids=(instrument_id,)),
        OnlyRuntimeId("runtime"),
        OnlyDataVersion("v1"),
        1,
        Path("tests/fixtures/legacy_macd"),
        logging.getLogger(__name__),
    )
    issues = factory.validate_request(request)
    assert issues[0].code == "PLUGIN_CAPABILITY_NOT_SUPPORTED"
    assert issues[0].field == "live_ticks"
