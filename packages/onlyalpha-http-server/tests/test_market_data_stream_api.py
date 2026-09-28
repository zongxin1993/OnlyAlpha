import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server.market_data import create_market_data_stream_router
from onlyalpha_http_server.market_data.stream_schema import (
    MarketDataStreamSubscribeDto,
    market_data_stream_event_adapter,
)
from pydantic import ValidationError

from onlyalpha.application.market_data_stream import OnlyMarketDataStreamEventV1
from onlyalpha.domain.market import OnlyBarSemantic


def _semantic(minutes: int) -> dict[str, object]:
    return OnlyBarSemantic.fixed_duration(minutes).to_dict()


class _Session:
    def __init__(self) -> None:
        self.events = iter(
            (
                OnlyMarketDataStreamEventV1(
                    "SUBSCRIBED",
                    {
                        "stream_id": "s",
                        "source_id": "source",
                        "instrument_id": "BTCUSDT.BINANCE",
                        "resolution_mode": "PROVIDER_NATIVE",
                        "resolution_plan_fingerprint": "a" * 64,
                        "cursor_bar_stride_minutes": 15,
                    },
                ),
                OnlyMarketDataStreamEventV1("STATE", {"state": "READY"}),
                OnlyMarketDataStreamEventV1("ERROR", {"code": "DONE"}),
            )
        )
        self.closed = 0

    def next_event(self) -> OnlyMarketDataStreamEventV1:
        return next(self.events)

    def close(self) -> None:
        self.closed += 1


class _Service:
    def __init__(self) -> None:
        self.session = _Session()
        self.request = None

    def open(self, reference, **request):  # noqa: ANN001, ANN201
        self.request = (reference, request)
        return self.session


def _client(service: _Service) -> TestClient:
    app = FastAPI()
    app.include_router(create_market_data_stream_router(service))  # type: ignore[arg-type]
    return TestClient(app)


def test_stream_rejects_invalid_subscribe_message() -> None:
    service = _Service()
    with _client(service).websocket_connect("/api/v2/market-data/stream") as socket:
        socket.send_json({"operation": "SUBSCRIBE_BAR"})
        assert socket.receive_json()["code"] == "MARKET_DATA_STREAM_REQUEST_INVALID"
    assert service.request is None


def test_stream_rejects_nonzero_resume_without_plan() -> None:
    service = _Service()
    with _client(service).websocket_connect("/api/v2/market-data/stream") as socket:
        socket.send_json(
            {
                "schema_version": 2,
                "operation": "SUBSCRIBE_BAR",
                "source_reference": {
                    "integration_id": "integration",
                    "integration_revision_fingerprint": "a" * 64,
                    "expected_type_id": "binance.spot.market_data",
                },
                "instrument_id": "BTCUSDT.BINANCE",
                "bar_semantic": _semantic(15),
                "resume_after_sequence": "42",
            }
        )
        assert socket.receive_json()["code"] == "MARKET_DATA_RESUME_PLAN_MISMATCH"
    assert service.request is None


def test_zero_resume_does_not_require_plan_fingerprint() -> None:
    admitted = MarketDataStreamSubscribeDto.model_validate(
        {
            "schema_version": 2,
            "operation": "SUBSCRIBE_BAR",
            "source_reference": {
                "integration_id": "integration",
                "integration_revision_fingerprint": "a" * 64,
                "expected_type_id": "binance.spot.market_data",
            },
            "instrument_id": "BTCUSDT.BINANCE",
            "bar_semantic": _semantic(15),
            "resume_after_sequence": "0",
        }
    )
    assert admitted.resume_plan_fingerprint is None


def test_server_subscribed_event_rejects_uncontracted_fields() -> None:
    event = {
        "schema_version": 2,
        "event": "SUBSCRIBED",
        "stream_id": "s",
        "source_id": "source",
        "instrument_id": "BTCUSDT.BINANCE",
        "resolution_mode": "PROVIDER_NATIVE",
        "resolution_plan_fingerprint": "a" * 64,
        "cursor_bar_stride_minutes": 15,
    }
    assert market_data_stream_event_adapter.validate_python(event).event == "SUBSCRIBED"
    with pytest.raises(ValidationError):
        market_data_stream_event_adapter.validate_python({**event, "extra": "drift"})


def test_stream_binds_exact_source_and_cleans_up_disconnect() -> None:
    service = _Service()
    fingerprint = "a" * 64
    with _client(service).websocket_connect("/api/v2/market-data/stream") as socket:
        socket.send_json(
            {
                "schema_version": 2,
                "operation": "SUBSCRIBE_BAR",
                "source_reference": {
                    "integration_id": "integration",
                    "integration_revision_fingerprint": fingerprint,
                    "expected_type_id": "binance.spot.market_data",
                },
                "instrument_id": "BTCUSDT.BINANCE",
                "bar_semantic": _semantic(1),
                "resume_after_sequence": "42",
                "resume_plan_fingerprint": fingerprint,
            }
        )
        assert socket.receive_json()["event"] == "SUBSCRIBED"
        assert socket.receive_json() == {"schema_version": 2, "event": "STATE", "state": "READY"}
        assert socket.receive_json()["event"] == "ERROR"
    reference, request = service.request
    assert reference.integration_revision_fingerprint == fingerprint
    assert request["resume_after_sequence"] == 42
    assert request["resume_plan_fingerprint"] == fingerprint
    assert service.session.closed == 1
