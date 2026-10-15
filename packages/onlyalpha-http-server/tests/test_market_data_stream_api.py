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
                OnlyMarketDataStreamEventV1("BASE_CURSOR", {"sequence": "43"}),
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
        assert socket.receive_json() == {"schema_version": 2, "event": "BASE_CURSOR", "sequence": "43"}
        assert socket.receive_json() == {"schema_version": 2, "event": "ERROR", "code": "DONE"}
    reference, request = service.request
    assert reference.integration_revision_fingerprint == fingerprint
    assert request["resume_after_sequence"] == 42
    assert request["resume_plan_fingerprint"] == fingerprint
    assert service.session.closed == 1


@pytest.mark.parametrize(
    "timing",
    [
        None,
        {"stream_id": "s", "provider_event_ns": None, "ingress_received_ns": "0"},
        {"stream_id": "s", "provider_event_ns": "3", "ingress_received_ns": "2"},
        {"stream_id": "s", "provider_event_ns": "3", "ingress_received_ns": None},
    ],
)
@pytest.mark.parametrize("event_name", ["BAR_PREVIEW", "BAR_CLOSED"])
def test_stream_bar_timing_is_strict_nullable_operational_metadata(timing: object, event_name: str) -> None:
    event = {
        "schema_version": 2,
        "event": event_name,
        **({"sequence": "1"} if event_name == "BAR_CLOSED" else {}),
        "source_id": "source",
        "instrument_id": "BTCUSDT.BINANCE",
        "bar_semantic": _semantic(1),
        "bar": {
            "bar_start_ns": "0",
            "bar_end_ns": "60000000000",
            "open": "1",
            "high": "1",
            "low": "1",
            "close": "1",
            "volume": "1",
            "closed": event_name == "BAR_CLOSED",
        },
        "timing": timing,
    }
    assert market_data_stream_event_adapter.validate_python(event).model_dump()["timing"] == timing
    service = _Service()
    service.session.events = iter(
        (
            OnlyMarketDataStreamEventV1(
                event_name, {key: value for key, value in event.items() if key not in {"schema_version", "event"}}
            ),
            OnlyMarketDataStreamEventV1("ERROR", {"code": "DONE"}),
        )
    )
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
                "bar_semantic": _semantic(1),
                "resume_after_sequence": "0",
            }
        )
        assert socket.receive_json() == event
        assert socket.receive_json()["event"] == "ERROR"
    assert service.session.closed == 1
    without = {key: value for key, value in event.items() if key != "timing"}
    with pytest.raises(ValidationError):
        market_data_stream_event_adapter.validate_python(without)
    for invalid in (
        {"stream_id": "s", "provider_event_ns": 1, "ingress_received_ns": "2"},
        {"stream_id": "s", "ingress_received_ns": "2"},
        {"stream_id": "s", "provider_event_ns": "1", "ingress_received_ns": "2", "extra": 0},
    ):
        with pytest.raises(ValidationError):
            market_data_stream_event_adapter.validate_python({**event, "timing": invalid})


@pytest.mark.parametrize("detail", [None, "diagnostic"])
def test_stream_preserves_explicit_optional_error_detail(detail: str | None) -> None:
    service = _Service()
    service.session.events = iter((OnlyMarketDataStreamEventV1("ERROR", {"code": "DONE", "detail": detail}),))
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
                "bar_semantic": _semantic(1),
                "resume_after_sequence": "0",
            }
        )
        assert socket.receive_json() == {"schema_version": 2, "event": "ERROR", "code": "DONE", "detail": detail}
    assert service.session.closed == 1
