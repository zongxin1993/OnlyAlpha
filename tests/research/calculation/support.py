from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
from onlyalpha.research.dataset.identity import only_content_fingerprint, only_snapshot_fingerprint
from onlyalpha.research.dataset.manifest import OnlyResearchDatasetSnapshot
from onlyalpha.research.dataset.schema import RESEARCH_BAR_DATASET_SCHEMA_V1


def bars() -> tuple[OnlyBar, ...]:
    result = []
    for instrument, values in (("B.XNAS", ("100", "90", "80", "70")), ("A.XNAS", ("1", "2", "4", "8"))):
        bar_type = OnlyBarType(
            OnlyInstrumentId.parse(instrument),
            OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.EXTERNAL,
        )
        for index, close in enumerate(values):
            start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC) + timedelta(minutes=index)
            value = Decimal(close)
            result.append(
                OnlyBar(
                    bar_type=bar_type,
                    open=OnlyPrice(value, 2),
                    high=OnlyPrice(value + 1, 2),
                    low=OnlyPrice(value - 1, 2),
                    close=OnlyPrice(value, 2),
                    volume=OnlyQuantity(Decimal(100 + index), 0),
                    quote_volume=None,
                    turnover=None,
                    trade_count=index,
                    open_interest=None,
                    bar_start=start,
                    bar_end=start + timedelta(minutes=1),
                    ts_event=start + timedelta(minutes=1),
                    ts_init=start + timedelta(minutes=1),
                    is_closed=True,
                    revision=0,
                    adjustment_type=OnlyAdjustmentType.RAW,
                    trading_day=date(2026, 1, 5),
                    session_type=OnlySessionType.CONTINUOUS,
                )
            )
    return tuple(result)


def snapshot(
    values: tuple[OnlyBar, ...] | None = None,
) -> tuple[OnlyResearchDatasetSnapshot, tuple[tuple[OnlyBar, ...], ...]]:
    values = bars() if values is None else values
    first = values[0]
    instruments = tuple(dict.fromkeys(item.instrument_id for item in values))
    definition = OnlyResearchDatasetDefinition(
        instruments,
        first.bar_type.specification,
        first.bar_type.aggregation_source,
        OnlyTimeRange(
            min(item.bar_start for item in values), max(item.ts_event for item in values) + timedelta(seconds=1)
        ),
    )
    canonical = tuple(sorted(values, key=lambda item: (str(item.instrument_id), item.ts_event)))
    content = only_content_fingerprint(canonical)
    fingerprint = only_snapshot_fingerprint(definition, RESEARCH_BAR_DATASET_SCHEMA_V1, content, len(canonical))
    return (
        OnlyResearchDatasetSnapshot(
            definition,
            RESEARCH_BAR_DATASET_SCHEMA_V1,
            content,
            len(canonical),
            fingerprint,
            (),
            (),
            datetime(2026, 1, 1, tzinfo=UTC),
        ),
        (canonical,),
    )


def reordered_snapshot() -> tuple[OnlyResearchDatasetSnapshot, tuple[tuple[OnlyBar, ...], ...]]:
    return snapshot(tuple(reversed(bars())))
