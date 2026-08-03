"""XtQuant historical calls; imported only inside the worker process."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .compatibility import OnlyMiniQmtHistoricalQueryMode
from .models import OnlyMiniQmtWorkerRequest


class OnlyMiniQmtDownloadError(RuntimeError):
    pass


class OnlyMiniQmtQueryError(RuntimeError):
    pass


def query_history(xtdata: Any, request: OnlyMiniQmtWorkerRequest) -> object:
    end = datetime.fromisoformat(request.end_time.replace("Z", "+00:00")).astimezone(UTC)
    lookback = max(10, request.required_bars // 48 + 5)
    start_text = (end - timedelta(days=lookback)).strftime("%Y%m%d%H%M%S")
    end_text = end.strftime("%Y%m%d%H%M%S")
    if request.download_before_query:
        try:
            xtdata.download_history_data(request.xt_symbol, request.period, start_text, end_text)
        except Exception as exc:
            raise OnlyMiniQmtDownloadError(str(exc)) from exc
    mode = OnlyMiniQmtHistoricalQueryMode(request.query_mode)
    count = min(request.maximum_count, request.required_bars + request.overlap_bars)
    kwargs: dict[str, object] = {
        "dividend_type": request.adjustment,
        "fill_data": request.fill_data,
    }
    if mode is OnlyMiniQmtHistoricalQueryMode.TIME_RANGE:
        kwargs.update(start_time=start_text, end_time=end_text)
    elif mode is OnlyMiniQmtHistoricalQueryMode.END_TIME_WITH_COUNT:
        kwargs.update(start_time="", end_time=end_text, count=count)
    else:
        kwargs.update(start_time="", end_time="", count=count)
    try:
        raw = xtdata.get_market_data_ex(list(request.fields), [request.xt_symbol], request.period, **kwargs)
    except Exception as exc:
        raise OnlyMiniQmtQueryError(str(exc)) from exc
    if not isinstance(raw, dict):
        raise ValueError("XtQuant historical result must be a symbol mapping")
    return raw.get(request.xt_symbol, ())


def rows(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, dict)]
    if hasattr(value, "to_dict"):
        converted = value.to_dict("records")
        return [dict(row) for row in converted if isinstance(row, dict)]
    if isinstance(value, dict):
        keys = list(value)
        columns = [value[key] for key in keys]
        return [dict(zip(keys, row, strict=True)) for row in zip(*columns, strict=True)]
    return []
