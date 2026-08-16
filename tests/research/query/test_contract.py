from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from onlyalpha.research import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    OnlyResearchQueryError,
    OnlyResearchQueryErrorCode,
    OnlyResearchStatisticSeriesQuery,
)

SHA = "a" * 64


@pytest.mark.parametrize("value", ("bad", "A" * 64, "a" * 63, 1, None))
def test_query_rejects_invalid_exact_identity(value: object) -> None:
    with pytest.raises(OnlyResearchQueryError) as caught:
        OnlyResearchStatisticSeriesQuery(value, SHA)  # type: ignore[arg-type]
    assert caught.value.code is OnlyResearchQueryErrorCode.INVALID_QUERY


@pytest.mark.parametrize("start,end", ((1, 1), (2, 1)))
def test_query_rejects_empty_or_inverted_half_open_range(start: int, end: int) -> None:
    with pytest.raises(OnlyResearchQueryError) as caught:
        OnlyResearchStatisticSeriesQuery(SHA, SHA, start, end)
    assert caught.value.code is OnlyResearchQueryErrorCode.INVALID_TIME_RANGE


@pytest.mark.parametrize("limit", (0, -1, True, MAX_PAGE_SIZE + 1, 1.5))
def test_query_rejects_invalid_limit(limit: object) -> None:
    with pytest.raises(OnlyResearchQueryError) as caught:
        OnlyResearchStatisticSeriesQuery(SHA, SHA, limit=limit)  # type: ignore[arg-type]
    assert caught.value.code is OnlyResearchQueryErrorCode.INVALID_PAGE_LIMIT


@pytest.mark.parametrize("field", ("from_ts_event_ns", "to_ts_event_ns", "after_ts_event_ns"))
@pytest.mark.parametrize("value", (True, "1", 1.5))
def test_query_rejects_non_integer_timestamps(field: str, value: object) -> None:
    arguments = {field: value}
    with pytest.raises(OnlyResearchQueryError) as caught:
        OnlyResearchStatisticSeriesQuery(SHA, SHA, **arguments)  # type: ignore[arg-type]
    assert caught.value.code is OnlyResearchQueryErrorCode.INVALID_QUERY


def test_request_is_immutable_and_uses_named_default_page_size() -> None:
    query = OnlyResearchStatisticSeriesQuery(SHA, SHA)
    assert query.limit == DEFAULT_PAGE_SIZE
    with pytest.raises(FrozenInstanceError):
        query.limit = 1  # type: ignore[misc]
