use onlyalpha_domain::{
    base::OnlyDomainModel,
    time::{OnlyTimeZone, OnlyTimestamp, OnlyUtcDateTime},
};
#[test]
fn absolute_time_keeps_arbitrary_nanos_and_floors_negative_units() {
    let value = OnlyTimestamp::from_unix_nanos("-1".parse().unwrap());
    assert_eq!(value.to_unix_micros().to_string(), "-1");
    assert_eq!(
        value.to_datetime().unwrap().to_string(),
        "1969-12-31T23:59:59.999999Z"
    );
    let huge = OnlyTimestamp::from_unix_nanos(
        "9999999999999999999999999999999999999999999"
            .parse()
            .unwrap(),
    );
    assert_eq!(
        OnlyTimestamp::from_json(&huge.to_json().unwrap()).unwrap(),
        huge
    );
    assert!(huge.to_datetime().is_err());
    for invalid in [
        "0000-01-01T00:00:00Z",
        "2025-01-01T00:00:60Z",
        "2025-01-01T00:00:00+01:00",
    ] {
        assert!(invalid.parse::<OnlyUtcDateTime>().is_err());
    }
}
#[test]
fn pinned_timezone_requires_gap_rejection_and_explicit_fold() {
    let zone = OnlyTimeZone::new("America/New_York").unwrap();
    assert!(
        zone.to_utc("2025-03-09T02:30:00".parse().unwrap(), None)
            .is_err()
    );
    let local = "2025-11-02T01:30:00".parse().unwrap();
    assert!(zone.to_utc(local, None).is_err());
    assert_eq!(
        zone.to_utc(local, Some(0)).unwrap().to_string(),
        "2025-11-02T05:30:00Z"
    );
    assert_eq!(
        zone.to_utc(local, Some(1)).unwrap().to_string(),
        "2025-11-02T06:30:00Z"
    );
    assert!(OnlyTimeZone::new("../UTC").is_err());
    assert_eq!(
        OnlyTimeZone::from_json(&zone.to_json().unwrap()).unwrap(),
        zone
    );
}
