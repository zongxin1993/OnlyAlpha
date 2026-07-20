from types import SimpleNamespace

from onlyalpha_plugin_miniqmt.data_source.resource import OnlyMiniQmtDataSource

from onlyalpha.data.enums import OnlyMarketDataRequestStatus, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.models import (
    OnlyMarketDataSubscriptionRequest,
    OnlyMarketDataUnsubscriptionRequest,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId


class OnlyFakeXtData:
    def __init__(self) -> None:
        self.callback = None
        self.unsubscribed: list[int] = []

    def subscribe_quote(self, symbol: str, period: str, callback: object) -> int:
        assert symbol == "600000.SH"
        assert period == "tick"
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
