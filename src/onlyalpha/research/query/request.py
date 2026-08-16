"""Immutable request contracts for deterministic Research queries."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import OnlyResearchQueryError, OnlyResearchQueryErrorCode

DEFAULT_PAGE_SIZE = 1000
MAX_PAGE_SIZE = 5000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def only_research_query_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise OnlyResearchQueryError(
            OnlyResearchQueryErrorCode.INVALID_QUERY,
            f"{name} must be a lower-case SHA256",
        )
    return value


def _optional_timestamp(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise OnlyResearchQueryError(OnlyResearchQueryErrorCode.INVALID_QUERY, f"{name} must be an integer")
    return value


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticSeriesQuery:
    research_result_fingerprint: str
    statistics_fingerprint: str
    from_ts_event_ns: int | None = None
    to_ts_event_ns: int | None = None
    after_ts_event_ns: int | None = None
    limit: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        only_research_query_sha256(self.research_result_fingerprint, "research_result_fingerprint")
        only_research_query_sha256(self.statistics_fingerprint, "statistics_fingerprint")
        start = _optional_timestamp(self.from_ts_event_ns, "from_ts_event_ns")
        end = _optional_timestamp(self.to_ts_event_ns, "to_ts_event_ns")
        _optional_timestamp(self.after_ts_event_ns, "after_ts_event_ns")
        if start is not None and end is not None and start >= end:
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.INVALID_TIME_RANGE,
                "from_ts_event_ns must be less than to_ts_event_ns",
            )
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or not 1 <= self.limit <= MAX_PAGE_SIZE:
            raise OnlyResearchQueryError(
                OnlyResearchQueryErrorCode.INVALID_PAGE_LIMIT,
                f"limit must be an integer between 1 and {MAX_PAGE_SIZE}",
            )
