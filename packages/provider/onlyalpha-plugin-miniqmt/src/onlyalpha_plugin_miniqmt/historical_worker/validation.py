"""Worker/parent shared validation for normalized transport Bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from zoneinfo import ZoneInfo

from .models import OnlyMiniQmtWorkerRequest

_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class OnlyNormalizedHistoricalRows:
    records: tuple[dict[str, object], ...]
    provider_raw_bar_count: int
    rejected_out_of_range_count: int
    provider_raw_last_bar_end_ns: int | None


def normalize_rows(
    raw_rows: list[dict[str, object]], request: OnlyMiniQmtWorkerRequest
) -> OnlyNormalizedHistoricalRows:
    minutes = _period_minutes(request.period)
    records: list[dict[str, object]] = []
    raw_ends: list[int] = []
    rejected_out_of_range_count = 0
    for row in raw_rows:
        missing = {"time", "open", "high", "low", "close", "volume"} - row.keys()
        if missing:
            raise ValueError(f"XtQuant historical row missing fields: {sorted(missing)}")
        timestamp = int(str(row["time"]))
        if timestamp > 10_000_000_000:
            timestamp //= 1_000
        event = datetime.fromtimestamp(timestamp, tz=UTC)
        if minutes == 1_440:
            trading_day = event.astimezone(_SHANGHAI).date()
            start = datetime.combine(trading_day, time(9, 30), _SHANGHAI).astimezone(UTC)
            end = datetime.combine(trading_day, time(15), _SHANGHAI).astimezone(UTC)
        else:
            # XtQuant historical minute timestamps identify the closed Bar's
            # end boundary (for example 13:01 is the 13:00-13:01 Bar).
            # Live callbacks have separate, evolving-Bar semantics.
            end = event
            start = event - timedelta(minutes=minutes)
        raw_ends.append(_nanos(end))
        record = {
            "instrument_id": request.instrument_id,
            "bar_type": request.period,
            "bar_start_ns": _nanos(start),
            "bar_end_ns": _nanos(end),
            "ts_event_ns": _nanos(end),
            "open": _decimal_text(row["open"], request.price_precision),
            "high": _decimal_text(row["high"], request.price_precision),
            "low": _decimal_text(row["low"], request.price_precision),
            "close": _decimal_text(row["close"], request.price_precision),
            "volume": _decimal_text(row["volume"], request.quantity_precision),
        }
        if int(str(record["bar_end_ns"])) <= request.end_time_ns:
            records.append(record)
        else:
            rejected_out_of_range_count += 1
    records.sort(key=lambda item: int(str(item["bar_end_ns"])))
    selected = tuple(records[-request.required_bars :])
    validate_records(selected, request, require_count=True)
    return OnlyNormalizedHistoricalRows(
        selected,
        len(raw_rows),
        rejected_out_of_range_count,
        max(raw_ends, default=None),
    )


def validate_records(
    records: tuple[dict[str, object], ...],
    request: OnlyMiniQmtWorkerRequest,
    *,
    require_count: bool,
) -> None:
    if require_count and len(records) < request.required_bars:
        raise ValueError(f"historical result has {len(records)} Bars; {request.required_bars} required")
    previous_end: int | None = None
    identities: set[tuple[str, str, int]] = set()
    minutes = _period_minutes(request.period)
    for record in records:
        if record.get("instrument_id") != request.instrument_id or record.get("bar_type") != request.period:
            raise ValueError("historical Bar instrument or period mismatch")
        start, end = int(str(record["bar_start_ns"])), int(str(record["bar_end_ns"]))
        if previous_end is not None and previous_end >= end:
            raise ValueError("historical Bar ends must be strictly increasing")
        previous_end = end
        identity = (request.instrument_id, request.period, start)
        if identity in identities:
            raise ValueError("duplicate historical Bar identity")
        identities.add(identity)
        if minutes != 1_440 and end - start != minutes * 60 * 1_000_000_000:
            raise ValueError("historical Bar interval does not match its period")
        if end > request.end_time_ns:
            raise ValueError("historical result contains an unclosed Bar")
        opened, high, low, closed = (Decimal(str(record[key])) for key in ("open", "high", "low", "close"))
        volume = Decimal(str(record["volume"]))
        if min(opened, high, low, closed) <= 0 or volume < 0:
            raise ValueError("historical Bar prices must be positive and volume non-negative")
        if high < max(opened, closed) or low > min(opened, closed) or high < low:
            raise ValueError("historical Bar OHLC is invalid")
        quantum = Decimal(1).scaleb(-request.price_precision)
        if any(value != value.quantize(quantum) for value in (opened, high, low, closed)):
            raise ValueError("historical Bar price precision mismatch")


def _period_minutes(period: str) -> int:
    if period == "1d":
        return 1_440
    if period.endswith("m") and period[:-1].isdigit() and int(period[:-1]) > 0:
        return int(period[:-1])
    if period.endswith("h") and period[:-1].isdigit() and int(period[:-1]) > 0:
        return int(period[:-1]) * 60
    raise ValueError(f"unsupported historical Bar period: {period}")


def _decimal_text(value: object, precision: int) -> str:
    with localcontext() as context:
        context.prec = 34
        context.rounding = ROUND_HALF_EVEN
        quantized = Decimal(str(value)).quantize(Decimal(1).scaleb(-precision))
    return format(quantized, f".{precision}f")


def _nanos(value: datetime) -> int:
    return int(value.timestamp()) * 1_000_000_000 + value.microsecond * 1_000
