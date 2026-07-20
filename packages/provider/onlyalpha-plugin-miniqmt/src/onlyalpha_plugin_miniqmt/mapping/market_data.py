from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal


def decimal_value(value: object) -> Decimal:
    return Decimal(str(value))


def quantized_decimal(value: object, precision: int) -> Decimal:
    quantum = Decimal(1).scaleb(-precision)
    return decimal_value(value).quantize(quantum, rounding=ROUND_HALF_UP)


def utc_from_xt(value: object) -> datetime:
    timestamp = int(value)
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    return datetime.fromtimestamp(timestamp, tz=UTC)


def valid_ohlc(row: dict[str, object]) -> bool:
    opened, high, low, closed = (quantized_decimal(row[key], 4) for key in ("open", "high", "low", "close"))
    return high >= max(opened, low, closed) and low <= min(opened, high, closed)
