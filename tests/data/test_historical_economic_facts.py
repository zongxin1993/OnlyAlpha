from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.historical.models import OnlyHistoricalFactRequest
from onlyalpha.data.identifiers import (
    OnlyDataSequence,
    OnlyDataVersion,
    OnlyMarketDataSourceId,
    OnlyMarketDataUpdateId,
)
from onlyalpha.data.models import (
    OnlyFundingRateUpdate,
    OnlyMarketDataInboundUpdate,
    OnlyReferencePriceUpdate,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyFundingRateFact, OnlyReferencePriceFact
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.domain.value import OnlyPrice

INSTRUMENT = OnlyInstrumentId.parse("TEST.FUT")
START = datetime(2026, 9, 1, tzinfo=UTC)
END = datetime(2026, 9, 2, tzinfo=UTC)


def test_reference_and_funding_facts_have_stable_cross_family_order() -> None:
    mark = OnlyReferencePriceFact(
        "mark-1", INSTRUMENT, OnlyReferencePriceKind.MARK, OnlyPrice(Decimal("100"), 2), START, START, "TEST", 2, "v1"
    )
    funding = OnlyFundingRateFact("fund-1", INSTRUMENT, Decimal("0.001"), START, START, "TEST", 1, "v1")

    assert sorted((funding, mark), key=lambda item: item.stable_order) == [mark, funding]


def test_historical_fact_request_is_canonical_and_fail_closed() -> None:
    request = OnlyHistoricalFactRequest(
        INSTRUMENT,
        OnlyMarketDataType.REFERENCE_PRICE,
        OnlyTimeRange(START, END),
        OnlyDataVersion("v1"),
        OnlyReferencePriceKind.MARK,
    )
    assert request.reference_price_kind is OnlyReferencePriceKind.MARK

    with pytest.raises(ValueError, match="REFERENCE_PRICE_KIND_REQUIRED"):
        OnlyHistoricalFactRequest(
            INSTRUMENT,
            OnlyMarketDataType.REFERENCE_PRICE,
            OnlyTimeRange(START, END),
            OnlyDataVersion("v1"),
        )


def test_reference_and_funding_envelopes_round_trip_without_provider_semantics() -> None:
    mark = OnlyReferencePriceFact(
        "mark-1",
        INSTRUMENT,
        OnlyReferencePriceKind.MARK,
        OnlyPrice(Decimal("100"), 2),
        START,
        START,
        "TEST",
        1,
        "v1",
    )
    funding = OnlyFundingRateFact("fund-1", INSTRUMENT, Decimal("0.001"), START, START, "TEST", 2, "v1")
    timestamp = OnlyTimestamp.from_datetime(START)
    common = {
        "runtime_id": OnlyRuntimeId("runtime"),
        "source_id": OnlyMarketDataSourceId("source"),
        "data_version": OnlyDataVersion("v1"),
        "instrument_id": INSTRUMENT,
        "ts_event": timestamp,
        "ts_init": timestamp,
    }
    updates = (
        OnlyMarketDataInboundUpdate(
            update_id=OnlyMarketDataUpdateId("mark-update"),
            source_sequence=OnlyDataSequence(1),
            data_type=OnlyMarketDataType.REFERENCE_PRICE,
            payload=OnlyReferencePriceUpdate(mark),
            **common,
        ),
        OnlyMarketDataInboundUpdate(
            update_id=OnlyMarketDataUpdateId("fund-update"),
            source_sequence=OnlyDataSequence(2),
            data_type=OnlyMarketDataType.FUNDING_RATE,
            payload=OnlyFundingRateUpdate(funding),
            **common,
        ),
    )

    assert tuple(OnlyMarketDataInboundUpdate.from_dict(item.to_dict()) for item in updates) == updates
    assert all(item.to_dict()["schema_version"] == 3 for item in updates)
