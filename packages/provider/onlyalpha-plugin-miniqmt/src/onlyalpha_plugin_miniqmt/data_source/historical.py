from datetime import timedelta
from zoneinfo import ZoneInfo

from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyMarketDataUpdateId
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlySessionType
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity

from ..mapping.exchange import to_xt_symbol
from ..mapping.market_data import quantized_decimal, utc_from_xt, valid_ohlc

PERIODS = {1: "1m", 5: "5m", 15: "15m", 30: "30m", 60: "1h", 1440: "1d"}
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def load_bars(xtdata, create_request, request):
    records = []
    sequence = 0
    for bar_type in sorted(request.bar_types, key=str):
        minutes = bar_type.specification.step
        period = PERIODS.get(minutes)
        if period is None:
            raise ValueError(f"unsupported MiniQMT period: {minutes}m")
        symbol = to_xt_symbol(bar_type.instrument_id)
        start_time = request.data_range.start_time.astimezone(_SHANGHAI).strftime(
            "%Y%m%d%H%M%S"
        )
        end_time = request.data_range.end_time.astimezone(_SHANGHAI).strftime(
            "%Y%m%d%H%M%S"
        )
        xtdata.download_history_data(
            symbol,
            period,
            start_time,
            end_time,
        )
        raw = xtdata.get_market_data_ex(
            [],
            [symbol],
            period,
            start_time=start_time,
            end_time=end_time,
            dividend_type="none",
            fill_data=False,
        )
        rows = _rows(raw.get(symbol, ()))
        seen = set()
        for row in sorted(rows, key=lambda item: int(item["time"])):
            event = utc_from_xt(row["time"])
            if event in seen or not (
                request.data_range.start_time <= event < request.data_range.end_time
            ):
                continue
            seen.add(event)
            if not valid_ohlc(row):
                raise ValueError(f"invalid OHLC for {symbol} at {event.isoformat()}")
            sequence += 1
            precision = 4
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
                bar_start=event,
                bar_end=event + timedelta(minutes=minutes),
                ts_event=event,
                ts_init=event,
                is_closed=True,
                revision=0,
                adjustment_type=OnlyAdjustmentType.RAW,
                trading_day=event.date(),
                session_type=OnlySessionType.REGULAR,
            )
            records.append(
                OnlyMarketDataInboundUpdate(
                    update_id=OnlyMarketDataUpdateId(f"miniqmt-{sequence}"),
                    runtime_id=create_request.runtime_id,
                    source_id=create_request.source_id,
                    source_sequence=OnlyDataSequence(sequence),
                    data_version=request.data_version,
                    instrument_id=bar.instrument_id,
                    data_type=OnlyMarketDataType.BAR,
                    payload=OnlyBarUpdate(bar),
                    ts_event=bar.ts_event_obj
                    if hasattr(bar, "ts_event_obj")
                    else __import__(
                        "onlyalpha.domain.time", fromlist=["OnlyTimestamp"]
                    ).OnlyTimestamp.from_datetime(event),
                    ts_init=__import__(
                        "onlyalpha.domain.time", fromlist=["OnlyTimestamp"]
                    ).OnlyTimestamp.from_datetime(event),
                )
            )
    return tuple(records)


def _rows(value):
    if isinstance(value, list):
        return value
    if hasattr(value, "to_dict"):
        return list(value.to_dict("records"))
    if isinstance(value, dict):
        keys = list(value)
        return [
            dict(zip(keys, values, strict=True))
            for values in zip(*(value[key] for key in keys), strict=True)
        ]
    return []
