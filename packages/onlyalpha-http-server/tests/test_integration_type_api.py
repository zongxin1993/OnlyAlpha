from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server.integration_types.routes import (
    INTEGRATION_TYPE_ROUTE_TAG,
    create_integration_type_router,
)
from onlyalpha_plugin_binance.spot.broker_factory import OnlyBinanceSpotBrokerFactory
from onlyalpha_plugin_binance.spot.data_source.factory import OnlyBinanceSpotDataSourceFactory
from onlyalpha_plugin_tushare.data_source.factory import OnlyTushareDataSourceFactory

from onlyalpha.application.integration_type_catalog import OnlyIntegrationTypeCatalog
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry


def _app() -> FastAPI:
    data_sources = OnlyDataSourceFactoryRegistry()
    brokers = OnlyBrokerFactoryRegistry()
    data_sources.register(OnlyBinanceSpotDataSourceFactory())
    data_sources.register(OnlyTushareDataSourceFactory())
    brokers.register(OnlyBinanceSpotBrokerFactory())
    app = FastAPI()
    app.include_router(create_integration_type_router(OnlyIntegrationTypeCatalog(data_sources, brokers)))
    return app


def test_integration_type_http_list_filter_and_exact_read_are_deterministic() -> None:
    client = TestClient(_app())

    listed = client.get("/api/v2/integration-types")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [item["type_id"] for item in items] == [
        "binance.spot.broker",
        "binance.spot.market_data",
        "tushare.daily.market_data",
    ]
    filtered = client.get("/api/v2/integration-types", params={"category": "BROKER"})
    assert [item["type_id"] for item in filtered.json()["items"]] == ["binance.spot.broker"]
    invalid = client.get("/api/v2/integration-types", params={"category": "broker"})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INTEGRATION_TYPE_CONTRACT_INVALID"
    exact = client.get("/api/v2/integration-types/binance.spot.broker")
    assert exact.status_code == 200
    assert exact.json() == items[0]


def test_integration_type_http_hides_secret_values_and_rejects_inexact_lookup() -> None:
    client = TestClient(_app())

    broker = client.get("/api/v2/integration-types/binance.spot.broker").json()
    secret_fields = [field for field in broker["configuration_contract"]["fields"] if field["secret"]]
    assert [(field["field_id"], field["default"]) for field in secret_fields] == [
        ("api_key", None),
        ("api_secret", None),
    ]
    missing = client.get("/api/v2/integration-types/BINANCE.SPOT.BROKER")
    assert missing.status_code == 404
    assert missing.json() == {
        "error": {
            "code": "INTEGRATION_TYPE_NOT_FOUND",
            "detail": "Integration Type is not available",
        }
    }


def test_integration_type_http_surface_is_read_only() -> None:
    app = _app()
    paths = app.openapi()["paths"]
    methods = {
        method.upper()
        for path, operations in paths.items()
        if path.startswith("/api/v2/integration-types")
        for method, operation in operations.items()
        if INTEGRATION_TYPE_ROUTE_TAG in operation.get("tags", ())
    }

    assert methods == {"GET"}
    assert TestClient(app).post("/api/v2/integration-types", json={}).status_code == 405


def test_integration_type_openapi_preserves_bounded_vocabularies() -> None:
    schemas = _app().openapi()["components"]["schemas"]

    assert schemas["OnlyIntegrationCategory"]["enum"] == ["DATA_SOURCE", "BROKER", "AGENT_PROVIDER"]
    assert schemas["OnlyIntegrationValueKind"]["enum"] == [
        "STRING",
        "INTEGER",
        "NUMBER",
        "BOOLEAN",
        "ENUM",
        "DURATION",
        "PATH",
        "STRING_INTEGER_MAP",
    ]
    assert schemas["OnlyIntegrationProbeMode"]["enum"] == ["DEFAULT_INSTRUMENT"]
    assert schemas["OnlyIntegrationProbeCheck"]["enum"] == [
        "CONNECTIVITY",
        "AUTHENTICATION",
        "REFERENCE_DATA",
        "HISTORICAL_DATA",
        "REALTIME_DATA",
        "MODEL_DISCOVERY",
    ]
