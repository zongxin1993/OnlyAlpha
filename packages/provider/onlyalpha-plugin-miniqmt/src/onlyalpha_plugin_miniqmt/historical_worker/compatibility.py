"""Explicit, immutable XtQuant historical query compatibility profiles."""

from dataclasses import dataclass
from enum import StrEnum


class OnlyMiniQmtHistoricalQueryMode(StrEnum):
    TIME_RANGE = "TIME_RANGE"
    END_TIME_WITH_COUNT = "END_TIME_WITH_COUNT"
    COUNT_ONLY = "COUNT_ONLY"


@dataclass(frozen=True, slots=True)
class OnlyMiniQmtHistoricalCompatibilityProfile:
    profile_id: str
    download_before_query: bool
    query_mode: OnlyMiniQmtHistoricalQueryMode
    explicit_fields: tuple[str, ...]
    fill_data: bool
    adjustment: str
    overlap_bars: int
    maximum_count: int

    def __post_init__(self) -> None:
        if not self.profile_id or self.overlap_bars < 0 or self.maximum_count <= 0:
            raise ValueError("invalid MiniQMT historical compatibility profile")
        if self.adjustment != "none":
            raise ValueError("MiniQMT historical warmup currently supports adjustment=none only")


MINIQMT_HISTORY_V2 = OnlyMiniQmtHistoricalCompatibilityProfile(
    profile_id="miniqmt-history-v2",
    download_before_query=True,
    query_mode=OnlyMiniQmtHistoricalQueryMode.END_TIME_WITH_COUNT,
    explicit_fields=("time", "open", "high", "low", "close", "volume"),
    fill_data=False,
    adjustment="none",
    overlap_bars=10,
    maximum_count=2_000,
)

_PROFILES = {MINIQMT_HISTORY_V2.profile_id: MINIQMT_HISTORY_V2}


def resolve_profile(profile_id: str) -> OnlyMiniQmtHistoricalCompatibilityProfile:
    try:
        return _PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown MiniQMT historical compatibility profile: {profile_id}") from exc


def compatibility_profiles() -> tuple[OnlyMiniQmtHistoricalCompatibilityProfile, ...]:
    return tuple(_PROFILES[key] for key in sorted(_PROFILES))
