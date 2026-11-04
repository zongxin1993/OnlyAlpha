//! Pure calendars over explicit, pinned timezone rules and immutable schedules.
use crate::{
    base::{domain_model, invalid, whitespace},
    enums::OnlySessionType,
    errors::OnlyDomainError,
    identifiers::{OnlyCalendarId, OnlySessionProfileId, OnlyVenueId},
    time::{OnlyTimeZone, OnlyTimestamp, OnlyTradingDay, OnlyUtcDateTime, time_error},
};
use bigdecimal::num_bigint::BigInt;
use jiff::{
    Span,
    civil::{Date, DateTime, Time},
};
use std::collections::HashSet;

domain_model!(OnlyTradingSession,OnlyTradingSessionInput,1,None,{
 name:String,opens_at:Time,closes_at:Time,session_type:OnlySessionType,belongs_to_trading_day_offset:i8,allows_orders:bool,allows_market_data:bool,
});
impl OnlyTradingSession {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if self.name().trim_matches(whitespace).is_empty()
            || !(-1..=1).contains(self.belongs_to_trading_day_offset())
        {
            return Err(invalid(
                "session requires a name and trading-day offset -1..1",
            ));
        }
        Ok(())
    }
    pub fn crosses_midnight(&self) -> bool {
        self.opens_at() > self.closes_at()
    }
    pub fn is_full_day(&self) -> bool {
        self.opens_at() == self.closes_at()
    }
    pub fn contains(&self, local_time: Time) -> bool {
        if self.is_full_day() {
            true
        } else if self.crosses_midnight() {
            local_time >= *self.opens_at() || local_time < *self.closes_at()
        } else {
            local_time >= *self.opens_at() && local_time < *self.closes_at()
        }
    }
    pub fn anchor_date(&self, local: DateTime) -> Result<Date, OnlyDomainError> {
        if self.crosses_midnight() && local.time() < *self.closes_at() {
            shift_date(local.date(), -1)
        } else {
            supported_date(local.date())
        }
    }
}
domain_model!(OnlySessionSchedule,OnlySessionScheduleInput,1,None,{trading_day:OnlyTradingDay,sessions:Vec<OnlyTradingSession>,is_closed:bool});
impl OnlySessionSchedule {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if *self.is_closed() != self.sessions().is_empty() {
            return Err(invalid(
                "closed schedule must be empty and open schedule must have sessions",
            ));
        }
        Ok(())
    }
}
domain_model!(OnlySessionProfile,OnlySessionProfileInput,1,None,{profile_id:OnlySessionProfileId,sessions:Vec<OnlyTradingSession>});
impl OnlySessionProfile {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if self.sessions().is_empty() {
            return Err(invalid("session profile requires sessions"));
        }
        Ok(())
    }
}
domain_model!(OnlyTradingCalendar,OnlyTradingCalendarInput,1,None,{
 calendar_id:OnlyCalendarId,venue_id:OnlyVenueId,timezone:OnlyTimeZone,sessions:Vec<OnlyTradingSession>,holidays:Vec<Date>,weekend_days:Vec<i8>,
 session_profile_id:Option<OnlySessionProfileId>,special_schedules:Vec<OnlySessionSchedule>,calendar_version:BigInt,effective_from:Option<Date>,effective_to:Option<Date>,
});
impl OnlyTradingCalendar {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if self.sessions().is_empty() || self.calendar_version() < &BigInt::from(1) {
            return Err(invalid("calendar requires sessions and positive version"));
        }
        if matches!((self.effective_from(),self.effective_to()),(Some(start),Some(end)) if start>=end)
        {
            return Err(invalid("calendar effective interval must be increasing"));
        }
        if self.weekend_days().iter().any(|day| !(0..=6).contains(day)) {
            return Err(invalid("weekend day must be 0..6"));
        }
        let mut holidays = HashSet::new();
        let mut special = HashSet::new();
        if self.holidays().iter().any(|day| !holidays.insert(day))
            || self
                .special_schedules()
                .iter()
                .any(|schedule| !special.insert(schedule.trading_day()))
        {
            return Err(invalid("holiday and special-schedule days must be unique"));
        }
        Ok(())
    }
    fn special_schedule(&self, day: OnlyTradingDay) -> Option<&OnlySessionSchedule> {
        self.special_schedules()
            .iter()
            .find(|schedule| *schedule.trading_day() == day)
    }
    pub fn is_trading_day(&self, day: OnlyTradingDay) -> bool {
        if let Some(schedule) = self.special_schedule(day) {
            return !schedule.is_closed();
        }
        !self
            .weekend_days()
            .contains(&day.value().weekday().to_monday_zero_offset())
            && !self.holidays().contains(&day.value())
    }
    pub fn sessions_for_trading_day(&self, day: OnlyTradingDay) -> &[OnlyTradingSession] {
        if let Some(schedule) = self.special_schedule(day) {
            schedule.sessions()
        } else if self.is_trading_day(day) {
            self.sessions()
        } else {
            &[]
        }
    }
    pub fn to_local(&self, timestamp: OnlyUtcDateTime) -> Result<tz::DateTime, OnlyDomainError> {
        self.timezone().to_local(timestamp)
    }
    pub fn to_local_timestamp(
        &self,
        timestamp: &OnlyTimestamp,
    ) -> Result<tz::DateTime, OnlyDomainError> {
        self.to_local(timestamp.to_datetime()?)
    }
    pub fn to_utc(
        &self,
        local: DateTime,
        fold: Option<u8>,
    ) -> Result<OnlyUtcDateTime, OnlyDomainError> {
        self.timezone().to_utc(local, fold)
    }
    pub fn to_utc_from_zoned(
        &self,
        local: &tz::DateTime,
    ) -> Result<OnlyUtcDateTime, OnlyDomainError> {
        OnlyUtcDateTime::from_zoned(local)
    }
    pub fn session_at(
        &self,
        timestamp: OnlyUtcDateTime,
    ) -> Result<Option<&OnlyTradingSession>, OnlyDomainError> {
        let local = self.timezone().to_civil(timestamp)?;
        let mut candidates: Vec<_> = self.sessions().iter().collect();
        for offset in [-1, 0, 1] {
            let Ok(day) = shift_date(local.date(), offset) else {
                continue;
            };
            if let Some(schedule) = self.special_schedule(OnlyTradingDay::new(day)?) {
                for session in schedule.sessions() {
                    if !candidates.contains(&session) {
                        candidates.push(session);
                    }
                }
            }
        }
        for session in candidates {
            if !session.contains(local.time()) {
                continue;
            }
            let day = OnlyTradingDay::new(shift_date(
                session.anchor_date(local)?,
                i64::from(*session.belongs_to_trading_day_offset()),
            )?)?;
            if let Some(matched) = self
                .sessions_for_trading_day(day)
                .iter()
                .find(|configured| *configured == session)
            {
                return Ok(Some(matched));
            }
        }
        Ok(None)
    }
    pub fn session_at_timestamp(
        &self,
        timestamp: &OnlyTimestamp,
    ) -> Result<Option<&OnlyTradingSession>, OnlyDomainError> {
        self.session_at(timestamp.to_datetime()?)
    }
    pub fn trading_day_at(
        &self,
        timestamp: OnlyUtcDateTime,
    ) -> Result<OnlyTradingDay, OnlyDomainError> {
        let local = self.timezone().to_civil(timestamp)?;
        let session = self
            .session_at(timestamp)?
            .ok_or_else(|| invalid("timestamp is outside a trading session"))?;
        OnlyTradingDay::new(shift_date(
            session.anchor_date(local)?,
            i64::from(*session.belongs_to_trading_day_offset()),
        )?)
    }
    pub fn trading_day_at_timestamp(
        &self,
        timestamp: &OnlyTimestamp,
    ) -> Result<OnlyTradingDay, OnlyDomainError> {
        self.trading_day_at(timestamp.to_datetime()?)
    }
    pub fn is_trading_time(&self, timestamp: OnlyUtcDateTime) -> Result<bool, OnlyDomainError> {
        Ok(self.session_at(timestamp)?.is_some())
    }
    pub fn is_trading_time_timestamp(
        &self,
        timestamp: &OnlyTimestamp,
    ) -> Result<bool, OnlyDomainError> {
        self.is_trading_time(timestamp.to_datetime()?)
    }
    pub fn with_special_sessions(
        &self,
        day: Date,
        sessions: Vec<OnlyTradingSession>,
    ) -> Result<Self, OnlyDomainError> {
        let day = OnlyTradingDay::new(day)?;
        let schedule = OnlySessionSchedule::new(OnlySessionScheduleInput {
            trading_day: day,
            sessions,
            is_closed: false,
        })?;
        let mut fields = self.input();
        fields
            .special_schedules
            .retain(|item| *item.trading_day() != day);
        fields.special_schedules.push(schedule);
        Self::new(fields)
    }
    pub fn is_effective_on(&self, day: OnlyTradingDay) -> bool {
        self.effective_from()
            .is_none_or(|start| day.value() >= start)
            && self.effective_to().is_none_or(|end| day.value() < end)
    }
    pub fn session_intervals_for_trading_day(
        &self,
        day: OnlyTradingDay,
    ) -> Result<Vec<(OnlyUtcDateTime, OnlyUtcDateTime)>, OnlyDomainError> {
        let mut intervals = Vec::new();
        for session in self.sessions_for_trading_day(day) {
            let anchor = shift_date(
                day.value(),
                -i64::from(*session.belongs_to_trading_day_offset()),
            )?;
            let close = if session.crosses_midnight() || session.is_full_day() {
                shift_date(anchor, 1)?
            } else {
                anchor
            };
            intervals.push((
                self.to_utc(DateTime::from_parts(anchor, *session.opens_at()), None)?,
                self.to_utc(DateTime::from_parts(close, *session.closes_at()), None)?,
            ));
        }
        Ok(intervals)
    }
    fn local_boundaries_for_day(&self, day: OnlyTradingDay, opening: bool) -> Vec<DateTime> {
        let mut boundaries = Vec::new();
        for session in self.sessions_for_trading_day(day) {
            let Ok(mut date) = shift_date(
                day.value(),
                -i64::from(*session.belongs_to_trading_day_offset()),
            ) else {
                continue;
            };
            if !opening && (session.crosses_midnight() || session.is_full_day()) {
                let Ok(close) = shift_date(date, 1) else {
                    continue;
                };
                date = close;
            }
            boundaries.push(DateTime::from_parts(
                date,
                if opening {
                    *session.opens_at()
                } else {
                    *session.closes_at()
                },
            ));
        }
        boundaries
    }
    fn boundary(
        &self,
        timestamp: OnlyUtcDateTime,
        forward: bool,
        opening: bool,
    ) -> Result<OnlyUtcDateTime, OnlyDomainError> {
        let local_day = self.timezone().to_civil(timestamp)?.date();
        let mut best: Option<OnlyUtcDateTime> = None;
        let mut unresolved = Vec::new();
        let query_nanos = timestamp.0.total_nanoseconds();
        for distance in -2_i64..370 {
            let Ok(date) = shift_date(local_day, distance * if forward { 1 } else { -1 }) else {
                continue;
            };
            let day = OnlyTradingDay::new(date)?;
            for local in self.local_boundaries_for_day(day, opening) {
                let projections = self.timezone().boundary_projections(local)?;
                if projections.iter().all(|value| {
                    if forward {
                        *value <= query_nanos
                    } else {
                        *value >= query_nanos
                    }
                }) {
                    continue;
                }
                if let Some(current) = best {
                    let limit = current.0.total_nanoseconds();
                    if projections.iter().all(|value| {
                        if forward {
                            *value >= limit
                        } else {
                            *value <= limit
                        }
                    }) {
                        continue;
                    }
                }
                let boundary = match self.to_utc(local, None) {
                    Ok(value) => value,
                    Err(error @ OnlyDomainError::Validation(_)) => {
                        unresolved.push((projections, error));
                        continue;
                    }
                    Err(error) => return Err(error),
                };
                if (if forward {
                    boundary > timestamp
                } else {
                    boundary < timestamp
                }) && best.is_none_or(|current| {
                    if forward {
                        boundary < current
                    } else {
                        boundary > current
                    }
                }) {
                    best = Some(boundary);
                }
            }
            if let Some(current) = best {
                let best_day = self.timezone().to_civil(current)?.date();
                if if forward {
                    best_day < date
                } else {
                    shift_date(date, 2).is_ok_and(|upper| best_day >= upper)
                } {
                    return boundary_result(best, unresolved, forward);
                }
            }
        }
        boundary_result(best, unresolved, forward)
    }
    pub fn next_open(
        &self,
        timestamp: OnlyUtcDateTime,
    ) -> Result<OnlyUtcDateTime, OnlyDomainError> {
        self.boundary(timestamp, true, true)
    }
    pub fn next_close(
        &self,
        timestamp: OnlyUtcDateTime,
    ) -> Result<OnlyUtcDateTime, OnlyDomainError> {
        self.boundary(timestamp, true, false)
    }
    pub fn previous_open(
        &self,
        timestamp: OnlyUtcDateTime,
    ) -> Result<OnlyUtcDateTime, OnlyDomainError> {
        self.boundary(timestamp, false, true)
    }
    pub fn previous_close(
        &self,
        timestamp: OnlyUtcDateTime,
    ) -> Result<OnlyUtcDateTime, OnlyDomainError> {
        self.boundary(timestamp, false, false)
    }
}
domain_model!(OnlyTradingCalendarCatalog,OnlyTradingCalendarCatalogInput,1,None,{calendars:Vec<OnlyTradingCalendar>});
impl OnlyTradingCalendarCatalog {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        let mut keys = HashSet::new();
        if self
            .calendars()
            .iter()
            .any(|calendar| !keys.insert((calendar.calendar_id(), calendar.calendar_version())))
        {
            return Err(invalid("duplicate calendar version"));
        }
        Ok(())
    }
    pub fn resolve(
        &self,
        id: &OnlyCalendarId,
        day: Date,
    ) -> Result<&OnlyTradingCalendar, OnlyDomainError> {
        let day = OnlyTradingDay::new(day)?;
        let mut matches = self
            .calendars()
            .iter()
            .filter(|calendar| calendar.calendar_id() == id && calendar.is_effective_on(day));
        let calendar = matches
            .next()
            .ok_or_else(|| invalid("no effective calendar version"))?;
        if matches.next().is_some() {
            return Err(invalid("ambiguous effective calendar version"));
        }
        Ok(calendar)
    }
}
// Unresolved mappings remain errors only if their bounds can beat the final valid answer.
fn boundary_result(
    best: Option<OnlyUtcDateTime>,
    unresolved: Vec<(Vec<i128>, OnlyDomainError)>,
    forward: bool,
) -> Result<OnlyUtcDateTime, OnlyDomainError> {
    for (projections, error) in unresolved {
        if let Some(current) = best {
            let limit = current.0.total_nanoseconds();
            if projections.iter().all(|value| {
                if forward {
                    *value >= limit
                } else {
                    *value <= limit
                }
            }) {
                continue;
            }
        }
        return Err(error);
    }
    best.ok_or_else(|| invalid("no calendar boundary found within 370 days"))
}
fn supported_date(date: Date) -> Result<Date, OnlyDomainError> {
    if date.year() < 1 {
        return Err(invalid("date requires year 1..9999"));
    }
    Ok(date)
}
fn shift_date(date: Date, days: i64) -> Result<Date, OnlyDomainError> {
    supported_date(
        date.checked_add(Span::new().days(days))
            .map_err(time_error)?,
    )
}
