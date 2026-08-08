from dataclasses import replace
from datetime import UTC, datetime

import pytest

from onlyalpha.data.identifiers import OnlyDataVersion
from onlyalpha.data.warmup import OnlyHistoricalWarmupRequest
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp

pytestmark = pytest.mark.contract


def _request() -> OnlyHistoricalWarmupRequest:
    instrument = OnlyInstrumentId.parse("600000.XSHG")
    return OnlyHistoricalWarmupRequest(
        "warmup-1",
        OnlyRuntimeId("paper-1"),
        instrument,
        OnlyBarType(
            instrument,
            OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.EXTERNAL,
        ),
        50,
        OnlyTimestamp.from_datetime(datetime(2026, 7, 24, 2, tzinfo=UTC)),
        OnlyTimestamp.from_datetime(datetime(2026, 8, 3, 2, tzinfo=UTC)),
        OnlyTimestamp.from_datetime(datetime(2026, 8, 3, 2, 0, 30, tzinfo=UTC)),
        OnlyDataVersion("miniqmt-v1"),
        OnlyAdjustmentType.RAW,
        30,
        "miniqmt-history-v2",
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"request_id": ""}, "request_id"),
        ({"required_bars": 0}, "positive"),
        ({"timeout_seconds": 0}, "positive"),
        ({"compatibility_profile_id": ""}, "compatibility profile"),
        ({"adjustment_type": OnlyAdjustmentType.FORWARD}, "RAW"),
    ],
)
def test_warmup_request_rejects_ambiguous_or_unsafe_values(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_request(), **changes)


def test_warmup_request_requires_external_time_bar() -> None:
    request = _request()
    internal = replace(request.bar_type, aggregation_source=OnlyAggregationSource.INTERNAL)

    with pytest.raises(ValueError, match="external"):
        replace(request, bar_type=internal)
