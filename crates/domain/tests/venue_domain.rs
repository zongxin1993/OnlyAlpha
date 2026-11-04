use onlyalpha_domain::{
    base::OnlyDomainModel,
    venue::{OnlyVenue, OnlyVenueInput},
};

#[test]
fn venue_keeps_explicit_calendar_identity_and_strict_record() {
    let fields = OnlyVenueInput {
        venue_id: "XTEST".parse().unwrap(),
        name: "Test venue".into(),
        timezone: onlyalpha_domain::time::OnlyTimeZone::new("UTC").unwrap(),
        default_calendar_id: "calendar".parse().unwrap(),
        default_session_profile_id: "sessions".parse().unwrap(),
    };
    let venue = OnlyVenue::new(fields).unwrap();
    assert_eq!(
        OnlyVenue::from_json(&venue.to_json().unwrap()).unwrap(),
        venue
    );
    let mut invalid = venue.input();
    invalid.name = " \t".into();
    assert!(OnlyVenue::new(invalid).is_err());
    let mut record = venue.to_record();
    record
        .as_object_mut()
        .unwrap()
        .insert("provider".into(), "vendor".into());
    assert!(OnlyVenue::from_record(&record).is_err());
}
