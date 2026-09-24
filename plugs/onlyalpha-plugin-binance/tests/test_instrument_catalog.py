from __future__ import annotations

import json

import pytest
from onlyalpha_plugin_binance.spot.data_source import instrument_catalog
from onlyalpha_plugin_binance.spot.data_source.config import OnlyBinanceSpotDataSourceConfig
from onlyalpha_plugin_binance.spot.data_source.instrument_catalog import (
    OnlyBinanceSpotInstrumentCatalog,
    only_binance_raw_symbol,
)

from onlyalpha.plugin.data_source import OnlyDataSourceInstrumentCatalogRequestV1


def _symbol(symbol: str, *, tick: str, step: str, base: str = "BTC", status: str = "TRADING") -> dict[str, object]:
    return {
        "symbol": symbol,
        "status": status,
        "baseAsset": base,
        "quoteAsset": "USDT",
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": tick},
            {"filterType": "LOT_SIZE", "stepSize": step, "minQty": step, "maxQty": "9000"},
        ],
    }


class _FakeHttp:
    payload = {
        "timezone": "UTC",
        "exchangeFilters": [],
        "symbols": [
            _symbol("BTCUSDT", tick="0.01000000", step="0.00001000"),
            _symbol("ETHUSDT", tick="0.01000000", step="0.00010000", base="ETH"),
            _symbol("HALTEDUSDT", tick="0.01000000", step="0.00010000", status="HALT"),
        ],
    }
    calls: list[tuple[str, dict[str, str]]] = []

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def get_json(self, endpoint: str, params: dict[str, str]) -> bytes:
        _FakeHttp.calls.append((endpoint, dict(params)))
        symbols = self.payload["symbols"]
        requested = params.get("symbols")
        if requested is not None:
            wanted = set(json.loads(requested))
            symbols = [item for item in symbols if item["symbol"] in wanted]
        return json.dumps({"timezone": "UTC", "exchangeFilters": [], "symbols": symbols}).encode()


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> OnlyBinanceSpotInstrumentCatalog:
    _FakeHttp.calls.clear()
    monkeypatch.setattr(instrument_catalog, "OnlyBinancePublicHttpClient", _FakeHttp)
    return OnlyBinanceSpotInstrumentCatalog()


def test_exact_instrument_lookup_projects_canonical_precision(catalog: OnlyBinanceSpotInstrumentCatalog) -> None:
    projected = catalog.list_instruments(
        OnlyDataSourceInstrumentCatalogRequestV1(
            OnlyBinanceSpotDataSourceConfig(), instrument_ids=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE")
        )
    )

    assert [str(item.instrument.instrument_id) for item in projected] == [
        "BTCUSDT.BINANCE",
        "ETHUSDT.BINANCE",
    ]
    btc = projected[0].instrument
    assert (btc.price_precision, btc.quantity_precision) == (2, 5)
    assert str(btc.tick_size.value) == "0.01" and str(btc.step_size.value) == "0.00001"
    assert projected[0].display_symbol == "BTCUSDT"
    assert (projected[0].venue, projected[0].market) == ("BINANCE", "SPOT")
    assert projected[0].market_data_capabilities == ("BAR_1M_EXTERNAL_RAW",)
    assert projected[1].instrument.base_currency.code == "ETH"
    assert json.loads(_FakeHttp.calls[0][1]["symbols"]) == ["BTCUSDT", "ETHUSDT"]


def test_symbol_search_is_bounded_and_never_dumps_the_catalogue(catalog: OnlyBinanceSpotInstrumentCatalog) -> None:
    config = OnlyBinanceSpotDataSourceConfig()
    assert catalog.list_instruments(OnlyDataSourceInstrumentCatalogRequestV1(config, query="")) == ()
    assert _FakeHttp.calls == []

    found = catalog.list_instruments(OnlyDataSourceInstrumentCatalogRequestV1(config, query="eth"))
    assert [str(item.instrument.instrument_id) for item in found] == ["ETHUSDT.BINANCE"]
    assert found[0].instrument.status.value == "ACTIVE"

    halted = catalog.list_instruments(OnlyDataSourceInstrumentCatalogRequestV1(config, query="halted"))
    assert halted[0].instrument.status.value == "HALTED"


def test_market_identity_is_declared_without_a_provider_call() -> None:
    from onlyalpha_plugin_binance.spot.data_source.factory import OnlyBinanceSpotDataSourceFactory

    factory = OnlyBinanceSpotDataSourceFactory()
    identity = factory.market_identity(OnlyBinanceSpotDataSourceConfig())
    assert (identity.venue, identity.market) == ("BINANCE", "SPOT")
    with pytest.raises(ValueError, match="BINANCE_PLUGIN_CONFIG_INVALID"):
        factory.market_identity(object())


def test_only_binance_raw_symbol_rejects_foreign_venues() -> None:
    assert only_binance_raw_symbol("btcusdt.BINANCE") == "BTCUSDT"
    with pytest.raises(Exception, match="BINANCE_INSTRUMENT_ID_INVALID"):
        only_binance_raw_symbol("600519.SH")
