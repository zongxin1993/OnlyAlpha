from datetime import timedelta
from types import SimpleNamespace

from onlyalpha_plugin_miniqmt.data_source.live import OnlyMiniQmtLiveNormalizer
from onlyalpha_plugin_miniqmt.data_source.resource import OnlyMiniQmtDataSource

from onlyalpha.data.enums import OnlyMarketDataRequestStatus, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.models import (
    OnlyMarketDataSubscriptionRequest,
    OnlyMarketDataUnsubscriptionRequest,
)
from onlyalpha.domain.enums import OnlyAggregationSource, OnlyBarAggregation, OnlyPriceType
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType


class OnlyFakeXtData:
    def __init__(self) -> None:
        self.callback = None
        self.unsubscribed: list[int] = []
        self.subscriptions: list[tuple[str, str, int]] = []

    def subscribe_quote(self, symbol: str, period: str, count: int, callback: object) -> int:
        assert symbol == "600000.SH"
        self.subscriptions.append((symbol, period, count))
        self.callback = callback
        return 7

    def unsubscribe_quote(self, sequence: int) -> None:
        self.unsubscribed.append(sequence)


def test_standard_live_port_normalizes_into_runtime_sink() -> None:
    updates: list[object] = []
    instrument = OnlyInstrumentId.parse("600000.XSHG")
    request = SimpleNamespace(
        source_id=OnlyMarketDataSourceId("miniqmt"),
        runtime_id=OnlyRuntimeId("runtime"),
        data_version=OnlyDataVersion("live-v1"),
        market_data_sink=updates.append,
        bar_types={},
    )
    xtdata = OnlyFakeXtData()
    source = OnlyMiniQmtDataSource(request, object(), xtdata)
    subscription = source.subscribe(
        OnlyMarketDataSubscriptionRequest(
            "quote-1",
            request.source_id,
            frozenset({instrument}),
            frozenset({OnlyMarketDataType.QUOTE}),
        )
    )
    assert subscription.status is OnlyMarketDataRequestStatus.ACCEPTED
    assert xtdata.callback is not None
    assert xtdata.subscriptions == [("600000.SH", "tick", 0)]

    xtdata.callback(
        {
            "600000.SH": [
                {
                    "time": 1_767_576_600_000,
                    "bidPrice": [8.879999999999999],
                    "askPrice": [8.89],
                    "bidVol": [100],
                    "askVol": [200],
                }
            ]
        }
    )

    assert len(updates) == 1
    assert updates[0].data_type is OnlyMarketDataType.QUOTE
    assert str(updates[0].payload.quote.bid_price.value) == "8.8800"
    result = source.unsubscribe(OnlyMarketDataUnsubscriptionRequest("unsubscribe-1", subscription.subscription_id))
    assert result.status is OnlyMarketDataRequestStatus.ACCEPTED
    assert xtdata.unsubscribed == [7]


def test_stop_unsubscribes_once_and_ignores_late_sdk_callback() -> None:
    updates: list[object] = []
    instrument = OnlyInstrumentId.parse("600000.XSHG")
    request = SimpleNamespace(
        source_id=OnlyMarketDataSourceId("miniqmt"),
        runtime_id=OnlyRuntimeId("runtime"),
        data_version=OnlyDataVersion("live-v1"),
        market_data_sink=updates.append,
        bar_types={},
    )
    xtdata = OnlyFakeXtData()
    source = OnlyMiniQmtDataSource(request, object(), xtdata)
    result = source.subscribe(
        OnlyMarketDataSubscriptionRequest(
            "quote-stop",
            request.source_id,
            frozenset({instrument}),
            frozenset({OnlyMarketDataType.QUOTE}),
        )
    )
    assert result.status is OnlyMarketDataRequestStatus.ACCEPTED
    callback = xtdata.callback
    assert callback is not None

    source.stop()
    source.stop()
    source.close()
    callback(
        {
            "600000.SH": [
                {
                    "time": 1_767_576_600_000,
                    "bidPrice": [8.88],
                    "askPrice": [8.89],
                    "bidVol": [100],
                    "askVol": [200],
                }
            ]
        }
    )

    assert xtdata.unsubscribed == [7]
    assert updates == []
    rejected = source.subscribe(
        OnlyMarketDataSubscriptionRequest(
            "quote-late",
            request.source_id,
            frozenset({instrument}),
            frozenset({OnlyMarketDataType.QUOTE}),
        )
    )
    assert rejected.status is OnlyMarketDataRequestStatus.REJECTED


def test_live_bar_uses_instrument_price_precision_and_remains_open() -> None:
    updates: list[object] = []
    instrument = OnlyInstrumentId.parse("600000.XSHG")
    bar_type = OnlyBarType(
        instrument,
        OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )
    request = SimpleNamespace(
        source_id=OnlyMarketDataSourceId("miniqmt"),
        runtime_id=OnlyRuntimeId("runtime"),
        data_version=OnlyDataVersion("live-v1"),
        market_data_sink=updates.append,
        bar_types={instrument: bar_type},
        instruments={instrument: SimpleNamespace(price_precision=2)},
    )

    OnlyMiniQmtLiveNormalizer(request).publish(
        {
            "600000.SH": [
                {
                    "time": 1_767_576_600_000,
                    "open": 8.879999999999999,
                    "high": 8.9,
                    "low": 8.87,
                    "close": 8.89,
                    "volume": 100,
                }
            ]
        },
        instrument,
        "1m",
    )

    bar = updates[0].payload.bar
    assert bar.close.precision == 2
    assert str(bar.open.value) == "8.88"
    assert bar.bar_end == bar.ts_event
    assert bar.bar_start == bar.bar_end - timedelta(minutes=1)
    assert not bar.is_closed


def test_bar_subscription_explicitly_requests_xtquant_live_tail() -> None:
    instrument = OnlyInstrumentId.parse("600000.XSHG")
    bar_type = OnlyBarType(
        instrument,
        OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )
    request = SimpleNamespace(
        source_id=OnlyMarketDataSourceId("miniqmt"),
        runtime_id=OnlyRuntimeId("runtime"),
        data_version=OnlyDataVersion("live-v1"),
        market_data_sink=lambda update: None,
        bar_types={instrument: bar_type},
        instruments={instrument: SimpleNamespace(price_precision=2)},
    )
    xtdata = OnlyFakeXtData()
    source = OnlyMiniQmtDataSource(request, object(), xtdata)

    result = source.subscribe(
        OnlyMarketDataSubscriptionRequest(
            "bar-1",
            request.source_id,
            frozenset({instrument}),
            frozenset({OnlyMarketDataType.BAR}),
            frozenset({bar_type}),
        )
    )

    assert result.status is OnlyMarketDataRequestStatus.ACCEPTED
    assert xtdata.subscriptions == [("600000.SH", "1m", -1)]
