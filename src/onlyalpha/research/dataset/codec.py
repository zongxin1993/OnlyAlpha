"""Exact OnlyBar to Arrow codec preserving decimal and precision semantics."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyCurrencyType,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity

from .schema import RESEARCH_BAR_DATASET_SCHEMA_V1, OnlyResearchBarDatasetSchema


def _ns(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def _datetime(value: int) -> datetime:
    seconds, nanoseconds = divmod(value, 1_000_000_000)
    if nanoseconds % 1000:
        raise ValueError("DATASET_INPUT_INVALID: Domain datetime cannot represent sub-microsecond timestamp")
    return datetime.fromtimestamp(seconds, UTC).replace(microsecond=nanoseconds // 1000)


def _scaled(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(Decimal("0.000000000000000001"))


def _precision(value: Decimal, precision: int) -> Decimal:
    quantum = Decimal(1).scaleb(-precision)
    return value.quantize(quantum)


def only_bars_to_table(
    bars: tuple[OnlyBar, ...], schema: OnlyResearchBarDatasetSchema = RESEARCH_BAR_DATASET_SCHEMA_V1
) -> pa.Table:
    rows: list[dict[str, object]] = []
    for bar in bars:
        turnover = bar.turnover
        rows.append(
            {
                "instrument_id": str(bar.instrument_id),
                "bar_step": bar.bar_type.specification.step,
                "bar_aggregation": bar.bar_type.specification.aggregation.value,
                "price_type": bar.bar_type.specification.price_type.value,
                "aggregation_source": bar.bar_type.aggregation_source.value,
                "bar_start_ns": _ns(bar.bar_start),
                "bar_end_ns": _ns(bar.bar_end),
                "ts_event_ns": _ns(bar.ts_event),
                "ts_init_ns": _ns(bar.ts_init),
                "trading_day": bar.trading_day,
                "session_type": bar.session_type.value,
                "open": _scaled(bar.open.value),
                "high": _scaled(bar.high.value),
                "low": _scaled(bar.low.value),
                "close": _scaled(bar.close.value),
                "price_precision": bar.open.precision,
                "volume": _scaled(bar.volume.value),
                "volume_precision": bar.volume.precision,
                "quote_volume": _scaled(bar.quote_volume.value) if bar.quote_volume else None,
                "quote_volume_precision": bar.quote_volume.precision if bar.quote_volume else None,
                "turnover_amount": _scaled(turnover.amount) if turnover else None,
                "turnover_currency": turnover.currency.code if turnover else None,
                "turnover_currency_precision": turnover.currency.precision if turnover else None,
                "turnover_currency_type": turnover.currency.currency_type.value if turnover else None,
                "trade_count": bar.trade_count,
                "open_interest": _scaled(bar.open_interest.value) if bar.open_interest else None,
                "open_interest_precision": bar.open_interest.precision if bar.open_interest else None,
                "is_closed": bar.is_closed,
                "revision": bar.revision,
                "adjustment_type": bar.adjustment_type.value,
            }
        )
    return pa.Table.from_pylist(rows, schema=schema.arrow_schema)


def only_table_to_bars(
    table: pa.Table, schema: OnlyResearchBarDatasetSchema = RESEARCH_BAR_DATASET_SCHEMA_V1
) -> tuple[OnlyBar, ...]:
    if table.schema != schema.arrow_schema:
        raise ValueError("DATASET_SCHEMA_UNSUPPORTED: Arrow schema mismatch")
    bars: list[OnlyBar] = []
    for row in table.to_pylist():
        quote = row["quote_volume"]
        interest = row["open_interest"]
        amount = row["turnover_amount"]
        money = None
        if amount is not None:
            if any(
                row[name] is None
                for name in ("turnover_currency", "turnover_currency_precision", "turnover_currency_type")
            ):
                raise ValueError("DATASET_INPUT_INVALID: incomplete turnover currency")
            money = OnlyMoney(
                _precision(amount, row["turnover_currency_precision"]),
                OnlyCurrency(
                    row["turnover_currency"],
                    row["turnover_currency_precision"],
                    OnlyCurrencyType(row["turnover_currency_type"]),
                ),
            )
        elif any(
            row[name] is not None
            for name in ("turnover_currency", "turnover_currency_precision", "turnover_currency_type")
        ):
            raise ValueError("DATASET_INPUT_INVALID: turnover metadata without amount")
        bars.append(
            OnlyBar(
                bar_type=OnlyBarType(
                    OnlyInstrumentId.parse(row["instrument_id"]),
                    OnlyBarSpecification(
                        row["bar_step"],
                        OnlyBarAggregation(row["bar_aggregation"]),
                        OnlyPriceType(row["price_type"]),
                    ),
                    OnlyAggregationSource(row["aggregation_source"]),
                ),
                open=OnlyPrice(_precision(row["open"], row["price_precision"]), row["price_precision"]),
                high=OnlyPrice(_precision(row["high"], row["price_precision"]), row["price_precision"]),
                low=OnlyPrice(_precision(row["low"], row["price_precision"]), row["price_precision"]),
                close=OnlyPrice(_precision(row["close"], row["price_precision"]), row["price_precision"]),
                volume=OnlyQuantity(_precision(row["volume"], row["volume_precision"]), row["volume_precision"]),
                quote_volume=None
                if quote is None
                else OnlyQuantity(_precision(quote, row["quote_volume_precision"]), row["quote_volume_precision"]),
                turnover=money,
                trade_count=row["trade_count"],
                open_interest=None
                if interest is None
                else OnlyQuantity(_precision(interest, row["open_interest_precision"]), row["open_interest_precision"]),
                bar_start=_datetime(row["bar_start_ns"]),
                bar_end=_datetime(row["bar_end_ns"]),
                ts_event=_datetime(row["ts_event_ns"]),
                ts_init=_datetime(row["ts_init_ns"]),
                is_closed=row["is_closed"],
                revision=row["revision"],
                adjustment_type=OnlyAdjustmentType(row["adjustment_type"]),
                trading_day=row["trading_day"],
                session_type=OnlySessionType(row["session_type"]),
            )
        )
    return tuple(bars)
