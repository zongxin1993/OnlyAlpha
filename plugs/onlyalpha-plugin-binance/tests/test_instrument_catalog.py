from __future__ import annotations

import json

import pytest
from onlyalpha_plugin_binance.spot.data_source import instrument_catalog
from onlyalpha_plugin_binance.spot.data_source.config import (
    OnlyBinanceMarketEnvironment,
    OnlyBinanceSpotDataSourceConfig,
    OnlyBinanceSpotEndpointProfile,
    only_resolve_binance_spot_endpoints,
)
from onlyalpha_plugin_binance.spot.data_source.factory import OnlyBinanceSpotDataSourceFactory
from onlyalpha_plugin_binance.spot.data_source.instrument_catalog import (
    OnlyBinanceSpotInstrumentCatalog,
    only_binance_raw_symbol,
)

from onlyalpha.application.integration_configuration import (
    only_integration_runtime_configuration_fingerprint,
    only_integration_secret_binding_fingerprint,
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


def test_symbol_search_is_bounded_to_the_w1_reference_universe_and_never_dumps_the_catalogue(
    catalog: OnlyBinanceSpotInstrumentCatalog,
) -> None:
    config = OnlyBinanceSpotDataSourceConfig()
    assert catalog.list_instruments(OnlyDataSourceInstrumentCatalogRequestV1(config, query="")) == ()
    assert _FakeHttp.calls == []

    found = catalog.list_instruments(OnlyDataSourceInstrumentCatalogRequestV1(config, query="eth"))
    assert [str(item.instrument.instrument_id) for item in found] == ["ETHUSDT.BINANCE"]
    assert found[0].instrument.status.value == "ACTIVE"

    # A symbol outside the approved W1 universe neither appears in search nor silently
    # expands the admitted instrument scope when it is requested by exact identity.
    assert catalog.list_instruments(OnlyDataSourceInstrumentCatalogRequestV1(config, query="halted")) == ()
    assert (
        catalog.list_instruments(
            OnlyDataSourceInstrumentCatalogRequestV1(config, instrument_ids=("HALTEDUSDT.BINANCE",))
        )
        == ()
    )
    for _endpoint, params in _FakeHttp.calls:
        assert set(json.loads(params["symbols"])) <= {"BTCUSDT", "ETHUSDT"}


def test_approved_symbol_status_is_projected(
    catalog: OnlyBinanceSpotInstrumentCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        _FakeHttp,
        "payload",
        {
            "timezone": "UTC",
            "exchangeFilters": [],
            "symbols": [_symbol("BTCUSDT", tick="0.01000000", step="0.00001000", status="HALT")],
        },
    )
    found = catalog.list_instruments(
        OnlyDataSourceInstrumentCatalogRequestV1(OnlyBinanceSpotDataSourceConfig(), query="btc")
    )
    assert [str(item.instrument.instrument_id) for item in found] == ["BTCUSDT.BINANCE"]
    assert found[0].instrument.status.value == "HALTED"


def test_market_identity_is_declared_without_a_provider_call() -> None:
    from onlyalpha_plugin_binance.spot.data_source.factory import (
        MARKET_SOURCE_IDS,
        OnlyBinanceSpotDataSourceFactory,
    )

    factory = OnlyBinanceSpotDataSourceFactory()
    live = factory.market_identity(OnlyBinanceSpotDataSourceConfig())
    testnet = factory.market_identity(
        OnlyBinanceSpotDataSourceConfig(
            environment=OnlyBinanceMarketEnvironment.SPOT_TESTNET,
            endpoint_profile=OnlyBinanceSpotEndpointProfile.DEFAULT,
        )
    )
    assert (live.venue, live.market, live.environment) == ("BINANCE", "SPOT", "GLOBAL")
    assert (testnet.venue, testnet.market, testnet.environment) == ("BINANCE", "SPOT", "SPOT_TESTNET")
    assert live.source_id == MARKET_SOURCE_IDS[OnlyBinanceMarketEnvironment.GLOBAL]
    assert live.source_id != testnet.source_id
    # A non-semantic runtime setting must not fork the canonical Market Source identity.
    assert factory.market_identity(OnlyBinanceSpotDataSourceConfig(timeout_seconds=3)).source_id == live.source_id
    with pytest.raises(ValueError, match="BINANCE_PLUGIN_CONFIG_INVALID"):
        factory.market_identity(object())


@pytest.mark.parametrize(
    ("environment", "profile", "rest_host"),
    [
        (
            OnlyBinanceMarketEnvironment.GLOBAL,
            OnlyBinanceSpotEndpointProfile.PUBLIC_MARKET_DATA,
            "data-api.binance.vision",
        ),
        (OnlyBinanceMarketEnvironment.GLOBAL, OnlyBinanceSpotEndpointProfile.STANDARD, "api.binance.com"),
        (OnlyBinanceMarketEnvironment.GLOBAL, OnlyBinanceSpotEndpointProfile.GCP, "api-gcp.binance.com"),
        (OnlyBinanceMarketEnvironment.GLOBAL, OnlyBinanceSpotEndpointProfile.API1, "api1.binance.com"),
        (OnlyBinanceMarketEnvironment.GLOBAL, OnlyBinanceSpotEndpointProfile.API2, "api2.binance.com"),
        (OnlyBinanceMarketEnvironment.GLOBAL, OnlyBinanceSpotEndpointProfile.API3, "api3.binance.com"),
        (OnlyBinanceMarketEnvironment.GLOBAL, OnlyBinanceSpotEndpointProfile.API4, "api4.binance.com"),
        (OnlyBinanceMarketEnvironment.US, OnlyBinanceSpotEndpointProfile.DEFAULT, "api.binance.us"),
        (OnlyBinanceMarketEnvironment.SPOT_TESTNET, OnlyBinanceSpotEndpointProfile.DEFAULT, "testnet.binance.vision"),
        (OnlyBinanceMarketEnvironment.SPOT_TESTNET, OnlyBinanceSpotEndpointProfile.GCP, "api1.testnet.binance.vision"),
    ],
)
def test_official_endpoint_catalog(
    environment: OnlyBinanceMarketEnvironment,
    profile: OnlyBinanceSpotEndpointProfile,
    rest_host: str,
) -> None:
    endpoints = only_resolve_binance_spot_endpoints(environment, profile)
    assert endpoints.rest_base_url == f"https://{rest_host}"
    assert endpoints.raw_stream_url("btcusdt@trade").endswith("/ws/btcusdt@trade")
    assert endpoints.combined_stream_url(("btcusdt@trade",)).endswith("/stream?streams=btcusdt@trade")


@pytest.mark.parametrize(
    ("environment", "profile"),
    [
        (OnlyBinanceMarketEnvironment.US, OnlyBinanceSpotEndpointProfile.API1),
        (OnlyBinanceMarketEnvironment.SPOT_TESTNET, OnlyBinanceSpotEndpointProfile.API4),
    ],
)
def test_invalid_endpoint_profile_pair_fails_closed(
    environment: OnlyBinanceMarketEnvironment, profile: OnlyBinanceSpotEndpointProfile
) -> None:
    with pytest.raises(ValueError, match="BINANCE_ENDPOINT_PROFILE_UNSUPPORTED"):
        OnlyBinanceSpotDataSourceConfig(environment=environment, endpoint_profile=profile)


def test_legacy_live_resolves_as_global_without_forking_existing_source_identity() -> None:
    factory = OnlyBinanceSpotDataSourceFactory()
    legacy = factory.parse_config({"environment": "LIVE"})
    modern = factory.parse_config({"environment": "GLOBAL", "endpoint_profile": "STANDARD"})

    assert legacy == modern
    assert legacy.endpoints.rest_base_url == "https://api.binance.com"
    assert factory.market_identity(legacy).source_id == "binance.spot.market_data.live"


def test_endpoint_profile_changes_binding_configuration_but_not_market_source_identity() -> None:
    factory = OnlyBinanceSpotDataSourceFactory()
    source_ids = {
        factory.market_identity(
            OnlyBinanceSpotDataSourceConfig(
                environment=OnlyBinanceMarketEnvironment.GLOBAL,
                endpoint_profile=profile,
            )
        ).source_id
        for profile in (
            OnlyBinanceSpotEndpointProfile.PUBLIC_MARKET_DATA,
            OnlyBinanceSpotEndpointProfile.STANDARD,
            OnlyBinanceSpotEndpointProfile.GCP,
            OnlyBinanceSpotEndpointProfile.API1,
            OnlyBinanceSpotEndpointProfile.API2,
            OnlyBinanceSpotEndpointProfile.API3,
            OnlyBinanceSpotEndpointProfile.API4,
        )
    }
    identities = {
        factory.market_identity(factory.parse_config(configuration)).source_id
        for configuration in (
            {"environment": "GLOBAL", "endpoint_profile": "PUBLIC_MARKET_DATA"},
            {"environment": "US", "endpoint_profile": "DEFAULT"},
            {"environment": "SPOT_TESTNET", "endpoint_profile": "DEFAULT"},
        )
    }

    assert source_ids == {"binance.spot.market_data.live"}
    assert len(identities) == 3
    descriptor_fingerprint = factory.integration_type.fingerprint
    empty_secrets = only_integration_secret_binding_fingerprint(())
    assert only_integration_runtime_configuration_fingerprint(
        factory.integration_type.type_id.value,
        descriptor_fingerprint,
        {"environment": "GLOBAL", "endpoint_profile": "STANDARD"},
        empty_secrets,
    ) != only_integration_runtime_configuration_fingerprint(
        factory.integration_type.type_id.value,
        descriptor_fingerprint,
        {"environment": "GLOBAL", "endpoint_profile": "PUBLIC_MARKET_DATA"},
        empty_secrets,
    )


def test_only_binance_raw_symbol_rejects_foreign_venues() -> None:
    assert only_binance_raw_symbol("btcusdt.BINANCE") == "BTCUSDT"
    with pytest.raises(Exception, match="BINANCE_INSTRUMENT_ID_INVALID"):
        only_binance_raw_symbol("600519.SH")
