from collections.abc import Mapping
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyMarketDataUpdateId
from onlyalpha.data.models import OnlyBarUpdate, OnlyHistoricalBarRequest, OnlyMarketDataInboundUpdate
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlySessionType
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest

from ..mapping.exchange import to_xt_symbol
from ..mapping.market_data import quantized_decimal, utc_from_xt, valid_ohlc

PERIODS = {1: "1m", 5: "5m", 15: "15m", 30: "30m", 60: "1h", 1440: "1d"}
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def load_bars(
    xtdata: Any,
    create_request: OnlyDataSourceCreateRequest,
    request: OnlyHistoricalBarRequest,
) -> tuple[OnlyMarketDataInboundUpdate, ...]:
    bars = load_normalized_bars(xtdata, create_request.instruments, request)
    return tuple(
        OnlyMarketDataInboundUpdate(
            update_id=OnlyMarketDataUpdateId(f"miniqmt-{sequence}"),
            runtime_id=create_request.runtime_id,
            source_id=create_request.source_id,
            source_sequence=OnlyDataSequence(sequence),
            data_version=request.data_version,
            instrument_id=bar.instrument_id,
            data_type=OnlyMarketDataType.BAR,
            payload=OnlyBarUpdate(bar),
            ts_event=OnlyTimestamp.from_datetime(bar.ts_event),
            ts_init=OnlyTimestamp.from_datetime(bar.ts_init),
        )
        for sequence, bar in enumerate(bars, start=1)
    )


def load_normalized_bars(
    xtdata: Any,
    instruments: Mapping[OnlyInstrumentId, OnlyInstrument],
    request: OnlyHistoricalBarRequest,
) -> tuple[OnlyBar, ...]:
    """Normalize vendor history without a Trading Runtime resource request."""

    records: list[OnlyBar] = []
    for bar_type in sorted(request.bar_types, key=str):
        minutes = bar_type.specification.step
        period = PERIODS.get(minutes)
        if period is None:
            raise ValueError(f"unsupported MiniQMT period: {minutes}m")
        symbol = to_xt_symbol(bar_type.instrument_id)
        start_time = request.data_range.start_time.astimezone(_SHANGHAI).strftime("%Y%m%d%H%M%S")
        end_time = request.data_range.end_time.astimezone(_SHANGHAI).strftime("%Y%m%d%H%M%S")
        xtdata.download_history_data(
            symbol,
            period,
            start_time,
            end_time,
        )
        # Request only the canonical Bar fields. Some XtQuant builds abort in
        # native BSON serialization when an empty field list expands to every
        # local field for intraday history.
        raw = xtdata.get_market_data_ex(
            ["time", "open", "high", "low", "close", "volume"],
            [symbol],
            period,
            start_time=start_time,
            end_time=end_time,
            dividend_type="none",
            fill_data=False,
        )
        rows = _rows(raw.get(symbol, ()))
        seen: set[datetime] = set()
        for row in sorted(rows, key=lambda item: int(item["time"])):
            raw_event = utc_from_xt(row["time"])
            local_trading_day = raw_event.astimezone(_SHANGHAI).date()
            event = (
                datetime.combine(local_trading_day, time(15), _SHANGHAI).astimezone(raw_event.tzinfo)
                if minutes == 1440
                else raw_event
            )
            if event in seen or not (request.data_range.start_time <= event < request.data_range.end_time):
                continue
            seen.add(event)
            if not valid_ohlc(row):
                raise ValueError(f"invalid OHLC for {symbol} at {event.isoformat()}")
            precision = instruments[bar_type.instrument_id].price_precision
            bar = OnlyBar(
                bar_type=bar_type,
                open=OnlyPrice(quantized_decimal(row["open"], precision), precision),
                high=OnlyPrice(quantized_decimal(row["high"], precision), precision),
                low=OnlyPrice(quantized_decimal(row["low"], precision), precision),
                close=OnlyPrice(quantized_decimal(row["close"], precision), precision),
                volume=OnlyQuantity(quantized_decimal(row.get("volume", 0), 0), 0),
                quote_volume=None,
                turnover=None,
                trade_count=None,
                open_interest=None,
                bar_start=(
                    datetime.combine(local_trading_day, time(9, 30), _SHANGHAI).astimezone(raw_event.tzinfo)
                    if minutes == 1440
                    else event - timedelta(minutes=minutes)
                ),
                bar_end=event,
                ts_event=event,
                ts_init=event,
                is_closed=True,
                revision=0,
                adjustment_type=OnlyAdjustmentType.RAW,
                trading_day=local_trading_day if minutes == 1440 else event.date(),
                session_type=OnlySessionType.REGULAR,
            )
            records.append(bar)
    return tuple(records)


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if hasattr(value, "to_dict"):
        rows: Any = value.to_dict("records")
        return [row for row in rows if isinstance(row, dict)]
    if isinstance(value, dict):
        keys = list(value)
        return [dict(zip(keys, values, strict=True)) for values in zip(*(value[key] for key in keys), strict=True)]
    return []
