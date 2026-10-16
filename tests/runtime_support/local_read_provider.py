"""Importable controlled read-only Provider for the local Browser fixture.

Only test provider facts live here. No HTTP application/startup or Store is loaded,
and the Factory identity stays importable when the service is launched with -m.
"""

from datetime import timedelta
from typing import cast

from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.enums import OnlyMarketDataRequestStatus
from onlyalpha.data.models import OnlyMarketDataSubscriptionResult, OnlyRealtimeBarPreviewV1
from onlyalpha.domain.market import OnlyBarSemantic, OnlyBarType
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest
from tests.application.test_market_data_product import (
    BASE,
    INSTRUMENT,
    MINUTE_NS,
    _FakeFactory,
    _FakeSource,
)


class _ReadBrowserPreviewSource(_FakeSource):
    def subscribe(self, request: object) -> OnlyMarketDataSubscriptionResult:
        creation = cast(OnlyDataSourceCreateRequest, self._request)
        assert creation.market_data_preview_sink is not None
        end = (OnlyBacktestClock(BASE + timedelta(hours=1)).timestamp_ns() // MINUTE_NS) * MINUTE_NS
        creation.market_data_preview_sink(
            OnlyRealtimeBarPreviewV1(
                creation.source_id,
                INSTRUMENT,
                OnlyBarType(INSTRUMENT, OnlyBarSemantic.fixed_duration(1)),
                end,
                end + MINUTE_NS,
                "100.00",
                "102.00",
                "99.00",
                "101.00",
                "2.00000",
                end,
                end,
            )
        )
        return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, "preview")

    def unsubscribe(self, request: object) -> None:
        return None


class _ReadBrowserFactory(_FakeFactory):
    """Serializable controlled test Provider; no production or real-market evidence."""

    def create(self, request: object) -> _ReadBrowserPreviewSource:
        return _ReadBrowserPreviewSource(request, provider=self._provider)
