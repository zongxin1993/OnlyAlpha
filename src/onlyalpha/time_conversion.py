"""Presentation-safe time conversion and explicit legacy migration helpers."""

from dataclasses import dataclass
from datetime import UTC, datetime

from onlyalpha.domain.enums import OnlyTimeDisplayMode
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone


@dataclass(frozen=True, slots=True)
class OnlyTimeDisplayValue:
    timestamp_utc: datetime
    display_time: datetime
    display_timezone: str

    def to_dict(self) -> dict[str, str]:
        utc_text = self.timestamp_utc.isoformat().replace("+00:00", "Z")
        return {
            "timestamp_utc": utc_text,
            "display_time": self.display_time.isoformat(),
            "display_timezone": self.display_timezone,
        }


class OnlyTimeConversionService:
    """Convert for display without mutating the source UTC instant."""

    def convert(
        self,
        timestamp: OnlyTimestamp,
        mode: OnlyTimeDisplayMode,
        *,
        market_timezone: OnlyTimeZone | None = None,
        user_timezone: OnlyTimeZone | None = None,
    ) -> OnlyTimeDisplayValue:
        utc = timestamp.to_datetime()
        if mode is OnlyTimeDisplayMode.UTC:
            zone = OnlyTimeZone("UTC")
        elif mode is OnlyTimeDisplayMode.MARKET:
            if market_timezone is None:
                raise OnlyValidationError("MARKET display requires market_timezone")
            zone = market_timezone
        else:
            if user_timezone is None:
                raise OnlyValidationError("USER_LOCAL display requires user_timezone")
            zone = user_timezone
        return OnlyTimeDisplayValue(utc, utc.astimezone(zone.zone_info), zone.name)


def migrate_legacy_datetime(
    value: datetime,
    *,
    source_timezone: OnlyTimeZone | None = None,
    fold: int | None = None,
) -> datetime:
    """Convert legacy datetime without guessing the timezone of a naive value."""
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    if source_timezone is None:
        raise OnlyValidationError("naive legacy datetime requires an explicit source timezone")
    candidates: dict[int, datetime] = {}
    for candidate_fold in (0, 1):
        aware = value.replace(tzinfo=source_timezone.zone_info, fold=candidate_fold)
        utc = aware.astimezone(UTC)
        if utc.astimezone(source_timezone.zone_info).replace(tzinfo=None) == value:
            candidates[candidate_fold] = utc
    if not candidates:
        raise OnlyValidationError("legacy local datetime does not exist in source timezone")
    if len(set(candidates.values())) > 1 and fold is None:
        raise OnlyValidationError("legacy local datetime is ambiguous; fold is required")
    selected = 0 if fold is None else fold
    if selected not in candidates:
        raise OnlyValidationError("invalid fold for legacy local datetime")
    return candidates[selected]
