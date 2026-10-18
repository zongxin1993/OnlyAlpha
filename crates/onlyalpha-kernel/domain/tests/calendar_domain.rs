use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::*,
    enums::OnlySessionType,
    time::{OnlyTimeZone, OnlyTradingDay},
};
fn session(name: &str, opens: &str, closes: &str, offset: i8) -> OnlyTradingSession {
    OnlyTradingSession::new(OnlyTradingSessionInput {
        name: name.into(),
        opens_at: opens.parse().unwrap(),
        closes_at: closes.parse().unwrap(),
        session_type: OnlySessionType::Regular,
        belongs_to_trading_day_offset: offset,
        allows_orders: true,
        allows_market_data: true,
    })
    .unwrap()
}
fn calendar(sessions: Vec<OnlyTradingSession>) -> OnlyTradingCalendar {
    OnlyTradingCalendar::new(OnlyTradingCalendarInput {
        calendar_id: "cal".parse().unwrap(),
        venue_id: "X".parse().unwrap(),
        timezone: OnlyTimeZone::new("Asia/Shanghai").unwrap(),
        sessions,
        holidays: vec![],
        weekend_days: vec![5, 6],
        session_profile_id: None,
        special_schedules: vec![],
        calendar_version: 1.into(),
        effective_from: None,
        effective_to: None,
    })
    .unwrap()
}
#[test]
fn sessions_keep_lunch_night_and_business_day_ownership() {
    let lunch = calendar(vec![
        session("morning", "09:30:00", "11:30:00", 0),
        session("afternoon", "13:00:00", "15:00:00", 0),
    ]);
    assert!(
        lunch
            .session_at("2025-01-06T04:00:00Z".parse().unwrap())
            .unwrap()
            .is_none()
    );
    assert_eq!(
        lunch
            .next_open("2025-01-06T04:00:00Z".parse().unwrap())
            .unwrap()
            .to_string(),
        "2025-01-06T05:00:00Z"
    );
    assert_eq!(
        lunch
            .previous_close("2025-01-06T04:00:00Z".parse().unwrap())
            .unwrap()
            .to_string(),
        "2025-01-06T03:30:00Z"
    );
    let night = calendar(vec![session("night", "21:00:00", "02:30:00", 1)]);
    for timestamp in ["2025-01-06T13:30:00Z", "2025-01-06T17:30:00Z"] {
        assert_eq!(
            night
                .trading_day_at(timestamp.parse().unwrap())
                .unwrap()
                .value()
                .to_string(),
            "2025-01-07"
        );
    }
    let day = OnlyTradingDay::new("2025-01-07".parse().unwrap()).unwrap();
    let intervals = night.session_intervals_for_trading_day(day).unwrap();
    assert_eq!(intervals[0].0.to_string(), "2025-01-06T13:00:00Z");
    assert_eq!(intervals[0].1.to_string(), "2025-01-06T18:30:00Z");
    assert_eq!(
        OnlyTradingCalendar::from_json(&night.to_json().unwrap()).unwrap(),
        night
    );
}
#[test]
fn special_schedules_and_catalogs_resolve_exactly_one_version() {
    let regular = calendar(vec![session("day", "09:00:00", "17:00:00", 0)]);
    let special = regular
        .with_special_sessions(
            "2025-01-06".parse().unwrap(),
            vec![session("early", "09:00:00", "12:00:00", 0)],
        )
        .unwrap();
    assert!(
        special
            .session_at("2025-01-06T05:00:00Z".parse().unwrap())
            .unwrap()
            .is_none()
    );
    let fields = OnlyTradingCalendarCatalogInput {
        calendars: vec![special.clone()],
    };
    let catalog = OnlyTradingCalendarCatalog::new(fields).unwrap();
    assert_eq!(
        catalog
            .resolve(regular.calendar_id(), "2025-01-06".parse().unwrap())
            .unwrap(),
        &special
    );
    assert!(
        OnlyTradingCalendarCatalog::new(OnlyTradingCalendarCatalogInput {
            calendars: vec![special.clone(), special]
        })
        .is_err()
    );
}
#[test]
fn neighboring_trading_days_cannot_hide_a_closer_boundary() {
    let mut fields = calendar(vec![
        session("ordinary", "12:00:00", "13:00:00", 0),
        session("shifted", "09:00:00", "10:00:00", 1),
    ])
    .input();
    fields.timezone = OnlyTimeZone::new("UTC").unwrap();
    fields.weekend_days = vec![];
    let calendar = OnlyTradingCalendar::new(fields).unwrap();
    assert_eq!(
        calendar
            .next_open("2025-01-06T08:00:00Z".parse().unwrap())
            .unwrap()
            .to_string(),
        "2025-01-06T09:00:00Z"
    );
}

#[test]
fn valid_boundary_dates_do_not_require_unrepresentable_neighbors() {
    let mut input = calendar(vec![session("day", "09:00:00", "17:00:00", 0)]).input();
    input.timezone = OnlyTimeZone::new("UTC").unwrap();
    input.weekend_days = vec![];
    let calendar = OnlyTradingCalendar::new(input).unwrap();
    for timestamp in ["0001-01-01T10:00:00Z", "9999-12-31T10:00:00Z"] {
        assert!(
            calendar
                .session_at(timestamp.parse().unwrap())
                .unwrap()
                .is_some()
        );
    }
}

#[test]
fn local_projection_preserves_both_occurrences_of_a_fold() {
    let mut input = calendar(vec![session("all", "00:00:00", "00:00:00", 0)]).input();
    input.timezone = OnlyTimeZone::new("America/New_York").unwrap();
    let calendar = OnlyTradingCalendar::new(input).unwrap();
    for text in ["2025-11-02T05:30:00Z", "2025-11-02T06:30:00Z"] {
        let original = text.parse().unwrap();
        let local = calendar.to_local(original).unwrap();
        assert_eq!(calendar.to_utc_from_zoned(&local).unwrap(), original);
    }
}
