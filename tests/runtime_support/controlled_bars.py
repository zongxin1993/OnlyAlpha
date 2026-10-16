"""Canonical controlled Bar facts for SIM/Authority tests; no vendor protocol."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from typing import cast

from onlyalpha.data.enums import OnlyMarketDataConnectionState, OnlyMarketDataRequestStatus
from onlyalpha.data.identifiers import OnlyMarketDataGatewayId
from onlyalpha.data.identity import only_provisional_bar_update_id
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyMarketDataConnectionResult,
    OnlyMarketDataConnectionSnapshot,
    OnlyMarketDataSubscriptionResult,
)
from onlyalpha.data.warmup import OnlyHistoricalWarmupResult, OnlyHistoricalWarmupStatus
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.plugin.capabilities import OnlyCheckpointCapability, OnlyDataSourceCapabilities
from onlyalpha.plugin.data_source import OnlyDataSource, OnlyDataSourceCreateRequest
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.scenario.data_source import (
    ONLY_SCENARIO_DATA_PLUGIN,
    OnlyScenarioDataSourceFactory,
    OnlyScenarioHistoricalDataSource,
)

DESCRIPTOR = replace(
    ONLY_SCENARIO_DATA_PLUGIN,
    plugin_id="controlled-bars",
    capabilities=OnlyDataSourceCapabilities(
        historical_bars=True,
        live_bars=True,
        live_ticks=True,
        live_reconnect=True,
        supports_runtime_checkpoint=OnlyCheckpointCapability.STATELESS,
    ),
)


class ControlledBarFeed:
    def __init__(self, ends: tuple[datetime, ...] = ()) -> None:
        self.ends = ends
        self.subscriptions: list[int] = []
        self.callbacks: list[Callable[[datetime], None]] = []

    def publish_bar(self, end: datetime) -> None:
        for callback in tuple(self.callbacks):
            callback(end)


class ControlledBarSource(OnlyScenarioHistoricalDataSource):
    def __init__(self, request: OnlyDataSourceCreateRequest, feed: ControlledBarFeed) -> None:
        self._request = request
        self.feed = feed
        self._connected = False
        self._sequence = 0
        super().__init__(request, tuple(self._update(end, index + 1) for index, end in enumerate(feed.ends)))

    @property
    def plugin_descriptor(self):
        return DESCRIPTOR

    def _update(self, end: datetime, sequence: int):
        return OnlyScenarioDataSourceFactory._update(
            self._request,
            {
                "instrument_id": str(next(iter(self._request.instruments))),
                "ts_event_ns": OnlyTimestamp.from_datetime(end).unix_nanos,
                "ts_init_ns": OnlyTimestamp.from_datetime(end).unix_nanos,
                "sequence": sequence,
                "open": "10.00",
                "high": "10.10",
                "low": "9.90",
                "close": "10.05",
                "volume": "100",
            },
        )

    def connect(self):
        super().connect()
        self._connected = True
        return OnlyMarketDataConnectionResult(OnlyMarketDataRequestStatus.ACCEPTED, self.connection_snapshot())

    def authenticate(self):
        return OnlyMarketDataConnectionResult(OnlyMarketDataRequestStatus.ACCEPTED, self.connection_snapshot())

    def connection_snapshot(self):
        return OnlyMarketDataConnectionSnapshot(
            OnlyMarketDataGatewayId(str(self.source_id)),
            OnlyMarketDataConnectionState.READY if self._connected else OnlyMarketDataConnectionState.DISCONNECTED,
        )

    def disconnect(self):
        self._connected = False
        self.feed.subscriptions.clear()
        self.feed.callbacks.clear()
        return OnlyMarketDataConnectionResult(OnlyMarketDataRequestStatus.ACCEPTED, self.connection_snapshot())

    def stop(self):
        self.disconnect()
        super().stop()

    close = stop

    def set_live_sequence_floor(self, sequence: int) -> None:
        self._sequence = max(self._sequence, sequence)

    def subscribe(self, request):
        del request
        self.feed.subscriptions.append(1)
        self.feed.callbacks.append(self._publish)
        return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, "controlled-bars")

    def unsubscribe(self, request):
        del request
        self.feed.subscriptions.clear()
        self.feed.callbacks.clear()
        return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, "controlled-bars")

    def _publish(self, end: datetime) -> None:
        self._sequence += 1
        update = self._update(end, self._sequence)
        bar = replace(update.payload.bar, is_closed=False)
        assert self._request.market_data_sink is not None
        self._request.market_data_sink(
            replace(
                update,
                payload=OnlyBarUpdate(bar),
                update_id=only_provisional_bar_update_id(self.source_id, bar, self._request.data_version),
            )
        )

    def load_warmup(self, request):
        # Explicitly controlled two-session history includes the opening boundary.
        end = request.end_time.to_datetime()
        previous_close = end - timedelta(hours=18, minutes=36)
        ends = tuple(previous_close - timedelta(minutes=offset) for offset in range(5, -1, -1))
        ends += tuple(end - timedelta(minutes=offset) for offset in range(6, -1, -1))
        bars = tuple(self._update(item, index + 1).payload.bar for index, item in enumerate(ends))[
            -request.required_bars :
        ]
        first, last = (OnlyTimestamp.from_datetime(item.bar_end) for item in (bars[0], bars[-1]))
        return OnlyHistoricalWarmupResult(
            status=OnlyHistoricalWarmupStatus.SUCCESS,
            bars=bars,
            request_fingerprint=sha256(repr(request).encode()).hexdigest(),
            content_fingerprint=sha256("\n".join(bar.to_json() for bar in bars).encode()).hexdigest(),
            first_bar_end=first,
            last_bar_end=last,
            bootstrap_observed_at=request.bootstrap_observed_at,
            requested_start=request.requested_start,
            requested_end=request.end_time,
            provider_raw_bar_count=len(bars),
            accepted_bar_count=len(bars),
            rejected_out_of_range_count=0,
            provider_raw_last_bar_end=last,
            accepted_last_bar_end=last,
            provider="controlled",
            provider_version="1",
            compatibility_profile_id=request.compatibility_profile_id,
            diagnostic=None,
        )


class ControlledBarSourceFactory:
    descriptor = DESCRIPTOR

    def __init__(self, feed: ControlledBarFeed | None = None) -> None:
        self.feed = feed or ControlledBarFeed()

    def parse_config(self, extensions):
        return extensions

    def validate_request(self, request):
        return ()

    def create(self, request: OnlyDataSourceCreateRequest) -> OnlyDataSource:
        return cast(OnlyDataSource, ControlledBarSource(request, self.feed))


def controlled_engine_services(feed: ControlledBarFeed | None = None, **kwargs):
    services = only_default_engine_services(**kwargs)
    services.assembler.components.data_sources.register(ControlledBarSourceFactory(feed))
    return services
