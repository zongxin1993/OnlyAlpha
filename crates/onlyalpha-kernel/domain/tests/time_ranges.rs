use onlyalpha_domain::{
    ranges::{OnlyTimeRange, only_merge_ranges, only_missing_ranges},
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use serde_json::{Value, json};

#[test]
fn shared_exact_and_lossy_instant_conversion_vectors() {
    for line in include_str!("../../../../test-data/domain/instant-conversion-v1.tsv").lines() {
        if line.starts_with('#') {
            continue;
        }
        let row: Vec<_> = line.split('\t').collect();
        let stamp = OnlyTimestamp::from_unix_nanos(row[1].parse().unwrap());
        for (result, expected) in [
            (stamp.to_datetime_exact(), row[2]),
            (stamp.to_datetime(), row[3]),
        ] {
            if expected == "ERROR" {
                assert!(result.is_err(), "{}", row[0]);
            } else {
                assert_eq!(result.unwrap().to_string(), expected, "{}", row[0]);
            }
        }
        if row[2] != "ERROR" {
            let datetime: OnlyUtcDateTime = row[2].parse().unwrap();
            assert_eq!(OnlyTimestamp::from_datetime(datetime), stamp, "{}", row[0]);
        }
    }
}
fn instant(micros: i64) -> OnlyUtcDateTime {
    OnlyTimestamp::from_unix_micros(micros.into())
        .to_datetime_exact()
        .unwrap()
}
fn range(value: &Value) -> OnlyTimeRange {
    OnlyTimeRange::new(
        instant(value[0].as_i64().unwrap()),
        instant(value[1].as_i64().unwrap()),
    )
    .unwrap()
}
fn encode(values: Vec<OnlyTimeRange>) -> Value {
    json!(
        values
            .iter()
            .map(|value| [
                OnlyTimestamp::from_datetime(value.start())
                    .to_unix_micros()
                    .to_string()
                    .parse::<i64>()
                    .unwrap(),
                OnlyTimestamp::from_datetime(value.end())
                    .to_unix_micros()
                    .to_string()
                    .parse::<i64>()
                    .unwrap(),
            ])
            .collect::<Vec<_>>()
    )
}
#[test]
fn shared_half_open_range_operations() {
    for line in include_str!("../../../../test-data/domain/time-ranges-v1.jsonl").lines() {
        let row: Value = serde_json::from_str(line).unwrap();
        let op = row["op"].as_str().unwrap();
        if op == "create" {
            assert!(
                OnlyTimeRange::new(
                    instant(row["range"][0].as_i64().unwrap()),
                    instant(row["range"][1].as_i64().unwrap())
                )
                .is_err()
            );
            continue;
        }
        let inputs: Vec<_> = row["ranges"]
            .as_array()
            .map(|items| items.iter().map(range).collect())
            .unwrap_or_default();
        let actual = match op {
            "merge" => encode(only_merge_ranges(&inputs)),
            "missing" => encode(only_missing_ranges(range(&row["range"]), &inputs)),
            "contains" => {
                json!(range(&row["range"]).contains(instant(row["point"].as_i64().unwrap())))
            }
            "overlaps" => json!(range(&row["range"]).overlaps(range(&row["other"]))),
            "intersection" => encode(
                range(&row["range"])
                    .intersection(range(&row["other"]))
                    .into_iter()
                    .collect(),
            ),
            "subtract" => encode(range(&row["range"]).subtract(range(&row["other"]))),
            _ => panic!("unknown operation"),
        };
        assert_eq!(actual, row["expected"], "{}", row["id"]);
    }
}
#[test]
fn ranges_preserve_full_datetime_boundaries() {
    let start = "0001-01-01T00:00:00Z".parse().unwrap();
    let end = "9999-12-31T23:59:59.999999Z".parse().unwrap();
    let value = OnlyTimeRange::new(start, end).unwrap();
    assert!(value.contains(start));
    assert!(!value.contains(end));
    assert_eq!(value.intersection(value), Some(value));
    assert!(value.subtract(value).is_empty());
}
