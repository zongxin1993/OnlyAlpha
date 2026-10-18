use onlyalpha_domain::{
    base::OnlyDomainModel, calendar::OnlyTradingSession, market::OnlyReferencePriceFact,
    time::OnlyTradingDay,
};
use serde_json::{Value, json};
#[test]
fn shared_temporal_records_keep_full_range_and_explicit_precision() {
    let template: Value = include_str!("../../../../test-data/domain/fact-records-v1.jsonl")
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .find(|row| row["id"] == "reference")
        .unwrap()["record"]
        .clone();
    for line in include_str!("../../../../test-data/domain/temporal-records-v1.jsonl").lines() {
        let row: Value = serde_json::from_str(line).unwrap();
        let result=match row["kind"].as_str().unwrap(){
   "utc"=>{let mut record=template.clone();record["ts_event"]=row["input"].clone();record["ts_init"]="9999-12-31T23:59:59.999999Z".into();OnlyReferencePriceFact::from_record(&record).map(|value|value.ts_event().to_string())}
   "date"=>OnlyTradingDay::from_record(&json!({"schema_version":1,"value":row["input"]})).map(|value|value.value().to_string()),
   "wall"=>OnlyTradingSession::from_record(&json!({"schema_version":1,"name":"day","opens_at":row["input"],"closes_at":"17:00:00","session_type":"REGULAR","belongs_to_trading_day_offset":0,"allows_orders":true,"allows_market_data":true})).map(|value|value.to_record()["opens_at"].as_str().unwrap().to_owned()),
   _=>panic!("unrecognized temporal vector"),
  };
        if row.get("error").is_some() {
            assert!(result.is_err(), "{}", row["id"]);
        } else {
            assert_eq!(
                result.unwrap(),
                row["expected"].as_str().unwrap(),
                "{}",
                row["id"]
            );
        }
    }
}
#[test]
fn shared_zone_conversions_cover_gaps_folds_range_and_rule_history() {
    use onlyalpha_domain::time::OnlyTimeZone;
    for line in include_str!("../../../../test-data/domain/timezone-v1.jsonl").lines() {
        let row: Value = serde_json::from_str(line).unwrap();
        let zone = OnlyTimeZone::new(row["zone"].as_str().unwrap()).unwrap();
        let result = if row["op"] == "to_utc" {
            let fold = row["fold"]
                .as_u64()
                .map(|value| u8::try_from(value).unwrap());
            zone.to_utc(row["input"].as_str().unwrap().parse().unwrap(), fold)
                .map(|value| json!(value.to_string()))
        } else {
            zone.to_local(row["input"].as_str().unwrap().parse().unwrap())
                .map(|value| {
                    json!([
                        value.year(),
                        i16::from(value.month()),
                        i16::from(value.month_day()),
                        i16::from(value.hour()),
                        i16::from(value.minute()),
                        i16::from(value.second()),
                        value.nanoseconds() / 1000
                    ])
                })
        };
        if row.get("error").is_some() {
            assert!(result.is_err(), "{}", row["id"]);
        } else {
            assert_eq!(result.unwrap(), row["expected"], "{}", row["id"]);
        }
    }
}

#[test]
fn shared_calendar_boundary_direction_vectors() {
    use onlyalpha_domain::calendar::OnlyTradingCalendar;
    for line in include_str!("../../../../test-data/domain/calendar-boundaries-v1.jsonl").lines() {
        let row: Value = serde_json::from_str(line).unwrap();
        let walls = row
            .get("walls")
            .map(|value| value.as_array().unwrap().clone())
            .unwrap_or_else(|| vec![row["wall"].clone()]);
        let sessions:Vec<Value> = walls.iter().enumerate().map(|(index,wall)|json!({
            "schema_version":1,"name":format!("day-{index}"),"opens_at":wall,"closes_at":"04:00:00",
            "session_type":"REGULAR","belongs_to_trading_day_offset":0,"allows_orders":true,"allows_market_data":true
        })).collect();
        let calendar = OnlyTradingCalendar::from_record(&json!({
            "schema_version":1,"calendar_id":{"schema_version":1,"value":"test"},"venue_id":{"schema_version":1,"value":"test"},
            "timezone":{"schema_version":1,"name":"America/New_York"},
            "sessions":sessions,
            "holidays":[],"weekend_days":[],"session_profile_id":null,"special_schedules":[],"calendar_version":1,"effective_from":null,"effective_to":null
        })).unwrap();
        let query = row["query"].as_str().unwrap().parse().unwrap();
        let result = match row["method"].as_str().unwrap() {
            "next_open" => calendar.next_open(query),
            "previous_open" => calendar.previous_open(query),
            _ => panic!("unknown boundary method"),
        };
        if row.get("error").is_some() {
            assert!(result.is_err(), "{}", row["id"]);
        } else {
            assert_eq!(
                result.unwrap().to_string(),
                row["expected"].as_str().unwrap(),
                "{}",
                row["id"]
            );
        }
    }
}
