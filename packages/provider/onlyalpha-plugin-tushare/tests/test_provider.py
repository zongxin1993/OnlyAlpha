from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha_plugin_tushare.data_source.provider import (
    OnlyTushareHistoricalDataProvider,
)

from onlyalpha.cache.historical.models import OnlyHistoricalDataRequest
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.domain.enums import OnlyAdjustmentType

from .support import OnlyFakeFrame, row


class OnlyFakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def pro_bar(self, **parameters: object) -> object:
        self.calls.append(parameters)
        return OnlyFakeFrame([row(trade_date="20250103")])


def test_provider_parameters_time_units_and_session_semantics(instrument, calendar, bar_type) -> None:
    client = OnlyFakeClient()
    provider = OnlyTushareHistoricalDataProvider("tushare-history", instrument, calendar, lambda: client)
    requested = OnlyTimeRange(datetime(2024, 12, 31, 16, tzinfo=UTC), datetime(2025, 4, 1, 16, tzinfo=UTC))
    request = OnlyHistoricalDataRequest(instrument.instrument_id, bar_type, requested)

    result = provider.fetch(request, requested)

    assert client.calls == [
        {
            "ts_code": "600000.SH",
            "start_date": "20250101",
            "end_date": "20250401",
            "asset": "E",
            "freq": "D",
            "adj": None,
        }
    ]
    bar = result.records[0]
    assert bar.trading_day.isoformat() == "2025-01-03"
    assert bar.ts_event == datetime(2025, 1, 3, 7, tzinfo=UTC)
    assert bar.volume.value == Decimal("12345")
    assert bar.turnover is not None and bar.turnover.amount == Decimal("127777")
    assert result.resolved_ranges == (requested,)
    assert result.observed_ranges == (OnlyTimeRange(bar.bar_start, bar.bar_end),)


def test_adjustment_and_anchor_are_cache_identity(instrument, calendar, bar_type) -> None:
    provider = OnlyTushareHistoricalDataProvider("tushare-history", instrument, calendar, OnlyFakeClient)
    requested = OnlyTimeRange(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC))
    raw = provider.build_cache_key(OnlyHistoricalDataRequest(instrument.instrument_id, bar_type, requested))
    qfq_a = provider.build_cache_key(
        OnlyHistoricalDataRequest(
            instrument.instrument_id,
            bar_type,
            requested,
            OnlyAdjustmentType.FORWARD,
            "20250131",
        )
    )
    qfq_b = provider.build_cache_key(
        OnlyHistoricalDataRequest(
            instrument.instrument_id,
            bar_type,
            requested,
            OnlyAdjustmentType.FORWARD,
            "20250228",
        )
    )
    hfq = provider.build_cache_key(
        OnlyHistoricalDataRequest(instrument.instrument_id, bar_type, requested, OnlyAdjustmentType.BACKWARD)
    )
    assert len({raw, qfq_a, qfq_b, hfq}) == 4
