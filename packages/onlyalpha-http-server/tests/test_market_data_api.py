from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from onlyalpha_http_server.market_data import (
    create_market_data_router,
    market_data_error_response,
    market_data_request_validation_error_response,
)

from onlyalpha.application.market_data_product import (
    OnlyMarketDataAcquisitionProjectionV1,
    OnlyMarketDataBarsProjectionV1,
    OnlyMarketDataBarV1,
    OnlyMarketDataCoverageGapV1,
    OnlyMarketDataCoverageProjectionV1,
    OnlyMarketDataInstrumentProjectionV1,
    OnlyMarketDataProductError,
    OnlyMarketDataSourceSelectionV1,
)

INTEGRATION_ID = "00000000-0000-4000-8000-000000000301"
REVISION_FINGERPRINT = "a" * 64
TYPE_ID = "binance.spot.market_data"
SOURCE_ID = TYPE_ID
INSTRUMENT_ID = "BTCUSDT.BINANCE"
START_NS = 1_767_225_600_000_000_000
MINUTE_NS = 60_000_000_000
ACQUISITION_ID = "acquisition:" + "b" * 64


def _coverage(status: str = "COMPLETE") -> OnlyMarketDataCoverageProjectionV1:
    gaps = () if status == "COMPLETE" else (OnlyMarketDataCoverageGapV1(START_NS, START_NS + 2 * MINUTE_NS),)
    return OnlyMarketDataCoverageProjectionV1(
        status,
        "manifest:" + "c" * 64,
        "c" * 64,
        2,
        2 if status == "COMPLETE" else 0,
        (),
        gaps,
        () if status == "COMPLETE" else gaps,
    )


def _selection() -> OnlyMarketDataSourceSelectionV1:
    return OnlyMarketDataSourceSelectionV1(INTEGRATION_ID, REVISION_FINGERPRINT, TYPE_ID, SOURCE_ID)


class _Service:
    def __init__(self) -> None:
        self.bar_queries: list[tuple[str, int, int, str]] = []
        self.acquisitions: list[tuple[str, int, int, str]] = []
        self.status_queries: list[str] = []
        self.bar_status = "COMPLETE"
        self.acquisition_state = "COMPLETE"
        self.failure: OnlyMarketDataProductError | None = None

    def _raise(self) -> None:
        if self.failure is not None:
            raise self.failure

    def list_instruments(
        self, selection: OnlyMarketDataSourceSelectionV1, *, instrument_ids=(), query: str = "", limit: int = 25
    ) -> tuple[OnlyMarketDataInstrumentProjectionV1, ...]:
        self._raise()
        return (
            OnlyMarketDataInstrumentProjectionV1(
                INSTRUMENT_ID,
                "BTCUSDT",
                "BINANCE",
                "SPOT",
                "CRYPTOCURRENCY",
                "CRYPTO_SPOT",
                "ACTIVE",
                ("BAR_1M_EXTERNAL_RAW",),
                selection.source_id,
                selection.type_id,
                selection.integration_id,
                selection.integration_revision_fingerprint,
            ),
        )

    def query_bars(
        self,
        selection: OnlyMarketDataSourceSelectionV1,
        *,
        instrument_id: str,
        start_ns: int,
        end_ns: int,
        bar_specification: str = "1m",
    ) -> OnlyMarketDataBarsProjectionV1:
        self._raise()
        self.bar_queries.append((instrument_id, start_ns, end_ns, bar_specification))
        coverage = _coverage(self.bar_status)
        bars = (
            (
                OnlyMarketDataBarV1(
                    START_NS,
                    START_NS + MINUTE_NS,
                    "100.00",
                    "102.00",
                    "99.00",
                    "101.00",
                    "2.00000",
                    True,
                ),
            )
            if coverage.complete
            else ()
        )
        return OnlyMarketDataBarsProjectionV1(
            1,
            selection,
            instrument_id,
            "BTCUSDT",
            "BINANCE",
            "SPOT",
            bar_specification,
            "EXTERNAL",
            "RAW",
            True,
            start_ns,
            end_ns,
            coverage,
            "market-data-revision:" + "d" * 64 if coverage.complete else None,
            "d" * 64 if coverage.complete else None,
            "seal:" + "e" * 64 if coverage.complete else None,
            bars,
        )

    def acquire_bars(
        self,
        selection: OnlyMarketDataSourceSelectionV1,
        *,
        instrument_id: str,
        start_ns: int,
        end_ns: int,
        bar_specification: str = "1m",
    ) -> OnlyMarketDataAcquisitionProjectionV1:
        self._raise()
        self.acquisitions.append((instrument_id, start_ns, end_ns, bar_specification))
        return _acquisition(self.acquisition_state)

    def acquisition_status(
        self, selection: OnlyMarketDataSourceSelectionV1, acquisition_id: str
    ) -> OnlyMarketDataAcquisitionProjectionV1:
        self._raise()
        self.status_queries.append(acquisition_id)
        return _acquisition(self.acquisition_state)


def _acquisition(status: str) -> OnlyMarketDataAcquisitionProjectionV1:
    coverage = _coverage("COMPLETE" if status == "COMPLETE" else "INCOMPLETE")
    return OnlyMarketDataAcquisitionProjectionV1(
        1,
        ACQUISITION_ID,
        status,
        SOURCE_ID,
        "f" * 64,
        INSTRUMENT_ID,
        "1m",
        START_NS,
        START_NS + 2 * MINUTE_NS,
        "REST_BACKFILL",
        coverage,
        "market-data-revision:" + "d" * 64 if coverage.complete else None,
        "d" * 64 if coverage.complete else None,
        "seal:" + "e" * 64 if coverage.complete else None,
        None if status != "FAILED" else "PROVIDER_UNAVAILABLE",
    )


def _client(service: _Service) -> TestClient:
    app = FastAPI()
    app.include_router(create_market_data_router(service))  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, lambda *_: market_data_request_validation_error_response())
    app.add_exception_handler(OnlyMarketDataProductError, lambda *args: market_data_error_response(args[1]))
    return TestClient(app)


def _selection_params(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "integration_id": INTEGRATION_ID,
        "integration_revision_fingerprint": REVISION_FINGERPRINT,
        "type_id": TYPE_ID,
        "source_id": SOURCE_ID,
    }
    values.update(overrides)
    return values


def test_instrument_query_projects_canonical_instruments_and_source_selection() -> None:
    client = _client(_Service())
    response = client.get("/api/v2/market/instruments", params=_selection_params(query="BTC"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == 1
    assert body["source_selection"] == {
        "integration_id": INTEGRATION_ID,
        "integration_revision_fingerprint": REVISION_FINGERPRINT,
        "type_id": TYPE_ID,
        "source_id": SOURCE_ID,
    }
    assert body["instruments"] == [
        {
            "instrument_id": INSTRUMENT_ID,
            "display_symbol": "BTCUSDT",
            "venue": "BINANCE",
            "market": "SPOT",
            "asset_class": "CRYPTOCURRENCY",
            "instrument_type": "CRYPTO_SPOT",
            "status": "ACTIVE",
            "market_data_capabilities": ["BAR_1M_EXTERNAL_RAW"],
        }
    ]


def test_bars_query_is_db_first_and_reports_gap_projection_without_bars() -> None:
    service = _Service()
    service.bar_status = "INCOMPLETE"
    client = _client(service)
    response = client.get(
        "/api/v2/market-data/bars",
        params=_selection_params(instrument_id=INSTRUMENT_ID, start_ns=START_NS, end_ns=START_NS + 2 * MINUTE_NS),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coverage"]["status"] == "INCOMPLETE"
    assert body["bars"] == []
    assert body["revision_id"] is None
    assert body["coverage"]["planned_acquisition_ranges"] == [
        {"start_ns": START_NS, "end_ns": START_NS + 2 * MINUTE_NS}
    ]
    assert body["aggregation_source"] == "EXTERNAL" and body["adjustment"] == "RAW"
    assert service.bar_queries == [(INSTRUMENT_ID, START_NS, START_NS + 2 * MINUTE_NS, "1m")]

    service.bar_status = "COMPLETE"
    complete = client.get(
        "/api/v2/market-data/bars",
        params=_selection_params(instrument_id=INSTRUMENT_ID, start_ns=START_NS, end_ns=START_NS + 2 * MINUTE_NS),
    )
    assert complete.status_code == 200
    assert complete.json()["coverage"]["status"] == "COMPLETE"
    assert complete.json()["bars"][0]["close"] == "101.00"
    assert complete.json()["revision_fingerprint"] == "d" * 64


def test_acquisition_command_and_status_query_are_thin_projections() -> None:
    service = _Service()
    client = _client(service)
    created = client.post(
        "/api/v2/market-data/acquisitions",
        json={
            "source_selection": {
                "integration_id": INTEGRATION_ID,
                "integration_revision_fingerprint": REVISION_FINGERPRINT,
                "type_id": TYPE_ID,
                "source_id": SOURCE_ID,
            },
            "instrument_id": INSTRUMENT_ID,
            "start_ns": START_NS,
            "end_ns": START_NS + 2 * MINUTE_NS,
            "bar_specification": "1m",
            "provenance": "REST_BACKFILL",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "COMPLETE"
    assert created.json()["integration_binding_fingerprint"] == "f" * 64
    assert service.acquisitions == [(INSTRUMENT_ID, START_NS, START_NS + 2 * MINUTE_NS, "1m")]

    service.acquisition_state = "FAILED"
    status = client.get(
        f"/api/v2/market-data/acquisitions/{ACQUISITION_ID}",
        params=_selection_params(),
    )
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "FAILED"
    assert status.json()["failure_detail"] == "PROVIDER_UNAVAILABLE"
    assert status.json()["coverage"]["status"] == "INCOMPLETE"
    assert service.status_queries == [ACQUISITION_ID]


def test_market_data_errors_map_to_explicit_http_status() -> None:
    service = _Service()
    client = _client(service)
    params = _selection_params(instrument_id=INSTRUMENT_ID, start_ns=START_NS, end_ns=START_NS + 2 * MINUTE_NS)

    service.failure = OnlyMarketDataProductError("MARKET_DATA_ACQUISITION_NOT_FOUND", "no such acquisition")
    assert client.get("/api/v2/market-data/bars", params=params).status_code == 404

    service.failure = OnlyMarketDataProductError("MARKET_DATA_SOURCE_SELECTION_UNRESOLVED", "stale revision")
    assert client.get("/api/v2/market-data/bars", params=params).status_code == 503

    service.failure = OnlyMarketDataProductError("MARKET_DATA_BAR_SPECIFICATION_UNSUPPORTED", "1m only")
    assert client.get("/api/v2/market-data/bars", params=params).status_code == 400

    service.failure = OnlyMarketDataProductError("MARKET_DATA_ACQUISITION_PROVENANCE_CONFLICT", "different binding")
    assert client.get("/api/v2/market-data/bars", params=params).status_code == 409

    service.failure = None
    invalid = client.get("/api/v2/market-data/bars", params=_selection_params(instrument_id=INSTRUMENT_ID))
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "MARKET_DATA_REQUEST_INVALID"
