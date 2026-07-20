from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation

from onlyalpha.cache.historical.models import (
    OnlyDataQualityIssue,
    OnlyDataQualitySeverity,
)

from ..errors import OnlyTushareError

REQUIRED_COLUMNS = frozenset({"ts_code", "trade_date", "open", "high", "low", "close", "vol"})


def _decimal(value: object, code: str) -> Decimal:
    if value is None:
        raise OnlyTushareError(code, "required numeric field is empty")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OnlyTushareError(code, "numeric field is invalid") from exc
    if not result.is_finite():
        raise OnlyTushareError(code, "numeric field must be finite")
    return result


def only_validate_response(
    raw: object, expected_symbol: str
) -> tuple[tuple[Mapping[str, object], ...], tuple[OnlyDataQualityIssue, ...]]:
    if raw is None:
        raise OnlyTushareError("TUSHARE_EMPTY_RESPONSE", "provider returned no response")
    columns = getattr(raw, "columns", None)
    to_dict = getattr(raw, "to_dict", None)
    if columns is None or not callable(to_dict):
        raise OnlyTushareError("TUSHARE_RESPONSE_TYPE_INVALID", "provider response is not tabular")
    missing = REQUIRED_COLUMNS - set(str(item) for item in columns)
    if missing:
        raise OnlyTushareError(
            "TUSHARE_REQUIRED_COLUMN_MISSING",
            f"required columns missing: {sorted(missing)}",
        )
    values = to_dict("records")
    if not isinstance(values, list):
        raise OnlyTushareError("TUSHARE_RESPONSE_TYPE_INVALID", "provider rows are invalid")
    by_day: dict[str, Mapping[str, object]] = {}
    issues: list[OnlyDataQualityIssue] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise OnlyTushareError("TUSHARE_RESPONSE_TYPE_INVALID", "provider row is invalid")
        if str(value.get("ts_code")) != expected_symbol:
            raise OnlyTushareError("TUSHARE_SYMBOL_MISMATCH", "response symbol differs from request")
        day = str(value.get("trade_date"))
        try:
            datetime.strptime(day, "%Y%m%d")
        except ValueError as exc:
            raise OnlyTushareError("TUSHARE_TRADE_DATE_INVALID", "trade_date is invalid") from exc
        prices = tuple(_decimal(value.get(name), "TUSHARE_PRICE_INVALID") for name in ("open", "high", "low", "close"))
        open_price, high, low, close = prices
        if min(prices) <= 0 or high < max(open_price, close) or low > min(open_price, close):
            raise OnlyTushareError("TUSHARE_PRICE_INVALID", "OHLC invariants failed")
        if _decimal(value.get("vol"), "TUSHARE_VOLUME_INVALID") < 0:
            raise OnlyTushareError("TUSHARE_VOLUME_INVALID", "volume cannot be negative")
        if value.get("amount") is not None and _decimal(value.get("amount"), "TUSHARE_AMOUNT_INVALID") < 0:
            raise OnlyTushareError("TUSHARE_AMOUNT_INVALID", "amount cannot be negative")
        previous = by_day.get(day)
        if previous is not None:
            if dict(previous) != dict(value):
                raise OnlyTushareError("TUSHARE_DUPLICATE_BAR", "conflicting duplicate trade_date")
            issues.append(
                OnlyDataQualityIssue(
                    "TUSHARE_DUPLICATE_IDENTICAL",
                    OnlyDataQualitySeverity.WARNING,
                    "identical duplicate removed",
                )
            )
            continue
        by_day[day] = value
    return tuple(by_day[key] for key in sorted(by_day)), tuple(issues)


def only_exact_decimal(value: object) -> Decimal:
    return _decimal(value, "TUSHARE_PRICE_INVALID")
