//! Venue identity and explicit default references. No venue-specific policy execution.
use crate::{
    base::{domain_model, invalid, whitespace},
    errors::OnlyDomainError,
    identifiers::{OnlyCalendarId, OnlySessionProfileId, OnlyVenueId},
    time::OnlyTimeZone,
};

domain_model!(OnlyVenue, OnlyVenueInput, 1, None, {
    venue_id: OnlyVenueId,
    name: String,
    timezone: OnlyTimeZone,
    default_calendar_id: OnlyCalendarId,
    default_session_profile_id: OnlySessionProfileId,
});

impl OnlyVenue {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if self.name().trim_matches(whitespace).is_empty() {
            return Err(invalid("venue name is required"));
        }
        Ok(())
    }
}
