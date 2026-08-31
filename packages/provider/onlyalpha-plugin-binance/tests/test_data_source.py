from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from onlyalpha_plugin_binance.errors import OnlyBinanceError
from onlyalpha_plugin_binance.spot.data_source.config import OnlyBinanceSpotDataSourceConfig
from onlyalpha_plugin_binance.spot.data_source.factory import OnlyBinanceSpotDataSourceFactory
from onlyalpha_plugin_binance.spot.data_source.normalize import (
    only_normalize_reference_price,
    only_normalize_rest_kline,
    only_normalize_rest_trade,
    only_normalize_ws_kline,
    only_normalize_ws_trade,
)

from onlyalpha.cache.historical import OnlyHistoricalCacheService, OnlyParquetHistoricalCacheStore
from onlyalpha.config.models import OnlyDataSourceCoverageConfig
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.enums import OnlyMarketDataRequestStatus, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.identity import only_bar_update_id, only_trade_update_id
from onlyalpha.data.models import OnlyMarketDataSubscriptionRequest, OnlyMarketReferenceUpdate, OnlyTradeTickUpdate
from onlyalpha.domain.enums import (
    OnlyAggregationSource,
    OnlyAssetClass,
    OnlyBarAggregation,
    OnlyCurrencyType,
    OnlyInstrumentType,
    OnlyMarketType,
    OnlyPriceType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRawSymbol, OnlyRuntimeId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.value import OnlyCurrency, OnlyPrice, OnlyQuantity
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.market_data.durable import (
    OnlyDurableMarketDataRecorder,
    OnlyMarketDataIngress,
    OnlyMarketDataWal,
)
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest
from onlyalpha.plugin.lifecycle import OnlyPluginLifecycleState


def _bar_type() -> tuple[OnlyInstrument, OnlyBarType]:
    instrument_id = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    usdt = OnlyCurrency("USDT", 2, OnlyCurrencyType.CRYPTO)
    instrument = OnlyInstrument(
        instrument_id=instrument_id,
        raw_symbol=OnlyRawSymbol("BTCUSDT"),
        asset_class=OnlyAssetClass.CRYPTOCURRENCY,
        instrument_type=OnlyInstrumentType.CRYPTO_SPOT,
        market_type=OnlyMarketType.CASH,
        quote_currency=usdt,
        settlement_currency=usdt,
        base_currency=OnlyCurrency("BTC", 8, OnlyCurrencyType.CRYPTO),
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        step_size=OnlyQuantity(Decimal("1"), 0),
    )
    return instrument, OnlyBarType(
        instrument_id,
        OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )


def _request(tmp_path: Path, *, plugin_config: object | None = None) -> OnlyDataSourceCreateRequest:
    instrument, requested_bar_type = _bar_type()
    return OnlyDataSourceCreateRequest(
        OnlyMarketDataSourceId("binance"),
        OnlyBinanceSpotDataSourceConfig() if plugin_config is None else plugin_config,
        "SIM",
        OnlyDataSourceCapabilities(
            historical_bars=True,
            historical_ticks=True,
            live_bars=True,
            live_ticks=True,
            live_reconnect=True,
        ),
        OnlyBacktestClock(datetime(2026, 1, 1, tzinfo=UTC)),
        OnlyEventBus(),
        {instrument.instrument_id: instrument},
        {instrument.instrument_id: requested_bar_type},
        {},
        (),
        OnlyDataSourceCoverageConfig(instrument_ids=(instrument.instrument_id,)),
        OnlyRuntimeId("runtime"),
        OnlyDataVersion("binance-spot-v1"),
        1000,
        tmp_path,
        logging.getLogger(__name__),
        market_data_sink=lambda update: None,
        historical_cache_service=OnlyHistoricalCacheService(OnlyParquetHistoricalCacheStore(tmp_path / "cache")),
    )


def test_config_factory_and_public_resource_lifecycle_are_fail_closed(tmp_path: Path) -> None:
    factory = OnlyBinanceSpotDataSourceFactory()
    config = factory.parse_config({"timeout_seconds": "2", "rest_page_size": "250"})
    assert config.timeout_seconds == 2 and config.rest_page_size == 250
    with pytest.raises(ValueError, match="UNKNOWN_FIELDS"):
        factory.parse_config({"symbols": ["BTCUSDT"]})
    with pytest.raises(ValueError, match="RECONNECT_BOUND_INVALID"):
        factory.parse_config({"reconnect_initial_seconds": 2, "reconnect_max_seconds": 1})

    request = _request(tmp_path)
    assert factory.validate_request(request) == ()
    invalid = replace(request, plugin_config=object())
    assert {item.code for item in factory.validate_request(invalid)} == {"BINANCE_PLUGIN_CONFIG_INVALID"}
    with pytest.raises(TypeError, match="OnlyBinanceSpotDataSourceConfig"):
        factory.create(invalid)

    resource = factory.create(request)
    assert resource.state is OnlyPluginLifecycleState.CREATED
    resource.initialize()
    assert resource.connect().status is OnlyMarketDataRequestStatus.ACCEPTED
    assert resource.authenticate().status is OnlyMarketDataRequestStatus.ACCEPTED
    resource.start()
    assert resource.state is OnlyPluginLifecycleState.RUNNING
    resource.stop()
    assert resource.state is OnlyPluginLifecycleState.STOPPED


def test_factory_requires_live_sink_and_historical_cache(tmp_path: Path) -> None:
    factory = OnlyBinanceSpotDataSourceFactory()
    request = replace(_request(tmp_path), market_data_sink=None, historical_cache_service=None)
    assert {item.code for item in factory.validate_request(request)} == {
        "BINANCE_MARKET_DATA_SINK_REQUIRED",
        "BINANCE_HISTORICAL_CACHE_REQUIRED",
    }


def test_production_durable_mode_requires_and_obtains_wal_ownership(tmp_path: Path) -> None:
    factory = OnlyBinanceSpotDataSourceFactory()
    missing = replace(_request(tmp_path), durable_recording_required=True)
    assert {item.code for item in factory.validate_request(missing)} == {"DURABLE_MARKET_DATA_RECORDER_REQUIRED"}
    with pytest.raises(RuntimeError, match="DURABLE_MARKET_DATA_RECORDER_REQUIRED"):
        factory.create(missing)

    wal = OnlyMarketDataWal(tmp_path / "wal", capacity_bytes=1_000_000)
    recorder = OnlyDurableMarketDataRecorder(
        OnlyMarketDataIngress(
            wal,
            normalizer_id="binance-spot",
            normalizer_version="1",
            ingest_clock_ns=lambda: 1_767_225_600_200_000_000,
        )
    )
    request = replace(missing, provider_evidence_sink=recorder)
    assert factory.validate_request(request) == ()
    resource = factory.create(request)
    payload = b'{"e":"trade","E":1767225600124,"s":"BTCUSDT","t":123,"p":"10.00","q":"100","T":1767225600123,"m":false}'
    with pytest.raises(OnlyBinanceError, match="CONTINUITY_NOT_READY"):
        resource.ingest_websocket_message(payload)
    [segment_id] = wal.scan_uncommitted()
    [bundle] = wal.read_sealed(segment_id)
    assert bundle.evidence.payload == payload
    assert wal.load_segment(segment_id).canonical_count == 1


def test_rest_and_websocket_closed_kline_converge_and_open_kline_is_not_canonical() -> None:
    instrument, requested_bar_type = _bar_type()
    open_ms = 1_767_225_600_000
    rest = [open_ms, "10.00", "11.00", "9.00", "10.50", "100", open_ms + 59_999, "1050", 42, "0", "0"]
    ws = {
        "t": open_ms,
        "T": open_ms + 59_999,
        "s": str(instrument.raw_symbol),
        "o": "10.00",
        "h": "11.00",
        "l": "9.00",
        "c": "10.50",
        "v": "100",
        "q": "1050",
        "n": 42,
        "x": True,
    }
    rest_bar = only_normalize_rest_kline(rest, instrument, requested_bar_type)
    ws_bar = only_normalize_ws_kline(ws, instrument, requested_bar_type)
    assert ws_bar == rest_bar
    assert rest_bar.bar_end == datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    source = OnlyMarketDataSourceId("binance")
    version = OnlyDataVersion("binance-spot-v1")
    assert only_bar_update_id(
        source, instrument.instrument_id, requested_bar_type, rest_bar.bar_start, version
    ) == only_bar_update_id(
        source,
        instrument.instrument_id,
        requested_bar_type,
        ws_bar.bar_start,
        version,  # type: ignore[union-attr]
    )
    assert only_normalize_ws_kline({**ws, "x": False}, instrument, requested_bar_type) is None


def test_rest_websocket_and_recovery_raw_trade_converge() -> None:
    instrument, _ = _bar_type()
    rest = {
        "id": 123,
        "price": "10.00",
        "qty": "100",
        "time": 1_767_225_600_123,
        "isBuyerMaker": False,
    }
    ws = {
        "t": 123,
        "p": "10.00",
        "q": "100",
        "T": 1_767_225_600_123,
        "m": False,
    }
    historical = only_normalize_rest_trade(rest, instrument)
    realtime = only_normalize_ws_trade(ws, instrument)
    recovery = only_normalize_rest_trade(dict(rest), instrument)
    assert historical == realtime == recovery
    source = OnlyMarketDataSourceId("binance")
    version = OnlyDataVersion("binance-spot-v1")
    assert only_trade_update_id(source, instrument.instrument_id, historical.trade_id, version) == only_trade_update_id(
        source, instrument.instrument_id, realtime.trade_id, version
    )


def test_rest_and_websocket_reference_price_converge_and_preserve_explicit_unavailable() -> None:
    instrument, _ = _bar_type()
    timestamp = 1_767_225_600_123
    rest = only_normalize_reference_price(
        {"symbol": "BTCUSDT", "referencePrice": "10.00", "timestamp": timestamp}, instrument
    )
    websocket = only_normalize_reference_price(
        {"e": "referencePrice", "s": "BTCUSDT", "r": "10.00", "t": timestamp}, instrument
    )
    unavailable = only_normalize_reference_price(
        {"e": "referencePrice", "s": "BTCUSDT", "r": None, "t": timestamp}, instrument
    )

    assert rest == websocket
    assert unavailable.price is None
    with pytest.raises(OnlyBinanceError, match="REFERENCE_PRICE_SYMBOL_MISMATCH"):
        only_normalize_reference_price(
            {"symbol": "ETHUSDT", "referencePrice": "10.00", "timestamp": timestamp}, instrument
        )


def test_avg_price_event_cannot_become_venue_reference_price(tmp_path: Path) -> None:
    resource = OnlyBinanceSpotDataSourceFactory().create(_request(tmp_path))
    instrument, _ = _bar_type()

    streams = resource._streams(  # noqa: SLF001 -- exact provider protocol contract
        OnlyMarketDataSubscriptionRequest(
            "reference",
            resource.source_id,
            frozenset({instrument.instrument_id}),
            frozenset({OnlyMarketDataType.MARKET_REFERENCE}),
        )
    )

    assert streams == ("btcusdt@referencePrice",)
    reference = resource._normalize_event(  # noqa: SLF001 -- exact provider dispatch contract
        {
            "e": "referencePrice",
            "s": "BTCUSDT",
            "r": "10.00",
            "t": 1_767_225_600_123,
        }
    )
    assert reference is not None
    assert isinstance(reference.payload, OnlyMarketReferenceUpdate)
    assert reference.payload.reference.price is not None
    assert (
        resource.ingest_websocket_message(b'{"e":"avgPrice","s":"BTCUSDT","i":"5m","w":"10.00","T":1767225600123}')
        == ()
    )


def test_websocket_raw_evidence_is_preserved_before_canonical_delivery(tmp_path: Path) -> None:
    observed = []
    request = replace(_request(tmp_path), provider_evidence_sink=lambda raw, update: observed.append((raw, update)))
    resource = OnlyBinanceSpotDataSourceFactory().create(request)
    payload = b'{"e":"trade","E":1767225600124,"s":"BTCUSDT","t":123,"p":"10.00","q":"100","T":1767225600123,"m":false}'

    with pytest.raises(OnlyBinanceError, match="CONTINUITY_NOT_READY"):
        resource.ingest_websocket_message(payload)

    [(raw, update)] = observed
    assert raw.payload == payload
    assert raw.provider_event_id == "123"
    assert raw.ts_event_ns == 1_767_225_600_124_000_000
    assert update is not None
    assert isinstance(update.payload, OnlyTradeTickUpdate)
    assert update.update_id == only_trade_update_id(
        resource.source_id, update.instrument_id, update.payload.trade.trade_id, update.data_version
    )


@pytest.mark.parametrize(
    ("payload", "error", "stream"),
    (
        (b"not-json", "BINANCE_WEBSOCKET_FRAME_INVALID", "UNKNOWN"),
        (b"[]", "BINANCE_WEBSOCKET_FRAME_INVALID", "UNKNOWN"),
        (b'{"data":[]}', "BINANCE_WEBSOCKET_EVENT_INVALID", "UNKNOWN"),
        (
            b'{"e":"trade","E":"invalid","s":"BTCUSDT","t":"invalid"}',
            "BINANCE_WEBSOCKET_NORMALIZATION_FAILED",
            "trade",
        ),
    ),
)
def test_invalid_websocket_payload_is_preserved_as_raw_evidence(
    tmp_path: Path, payload: bytes, error: str, stream: str
) -> None:
    observed = []
    request = replace(_request(tmp_path), provider_evidence_sink=lambda raw, update: observed.append((raw, update)))
    resource = OnlyBinanceSpotDataSourceFactory().create(request)

    with pytest.raises(OnlyBinanceError, match=error):
        resource.ingest_websocket_message(payload)

    [(raw, update)] = observed
    assert raw.payload == payload
    assert raw.stream == stream
    assert raw.provider_event_type == stream
    assert update is None


def test_rest_response_raw_evidence_links_all_canonical_facts(tmp_path: Path) -> None:
    observed = []
    request = replace(_request(tmp_path), provider_evidence_sink=lambda raw, update: observed.append((raw, update)))
    resource = OnlyBinanceSpotDataSourceFactory().create(request)
    payload = b'[[1767225600000,"10.00","11.00","9.00","10.50","100",1767225659999,"1050",42,"0","0"]]'

    resource._observe_rest_response("/api/v3/klines", {"symbol": "BTCUSDT"}, payload)

    [(raw, updates)] = observed
    assert raw.payload == payload
    assert raw.provenance == "REST_BACKFILL"
    assert isinstance(updates, tuple) and len(updates) == 1
    assert updates[0].data_type is OnlyMarketDataType.BAR
