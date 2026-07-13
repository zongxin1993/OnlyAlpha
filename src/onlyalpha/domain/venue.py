"""Trading venue identity and its default market-time policy."""

from dataclasses import dataclass

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlySessionProfileId, OnlyVenueId
from onlyalpha.domain.time import OnlyTimeZone


@dataclass(frozen=True, slots=True)
class OnlyVenue(OnlyDomainModel):
    venue_id: OnlyVenueId
    name: str
    timezone: OnlyTimeZone
    default_calendar_id: OnlyCalendarId
    default_session_profile_id: OnlySessionProfileId

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise OnlyValidationError("venue name is required")
