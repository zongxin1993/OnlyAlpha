mod support;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use onlyalpha_market_data_state::*;
use serde_json::Value;
use std::sync::Arc;
use support::*;
fn k(row: &Value) -> onlyalpha_domain::market::OnlyBarType {
    kind(row[0].as_str().unwrap(), row[1].as_u64().unwrap() as u32)
}
#[test]
fn independent_operations_and_common_queries() {
    for line in
        include_str!("../../../../../test-data/market-data-state/operations-v1.jsonl").lines()
    {
        let row: Value = serde_json::from_str(line).unwrap();
        let mut s = state(row["history_limit"].as_u64().unwrap() as usize);
        let mut snapshot = None;
        for op in row["operations"].as_array().unwrap() {
            if op.get("restore").is_some() {
                let checkpoint = s.capture_checkpoint();
                s.restore_checkpoint(&checkpoint).unwrap();
            } else if let Some(version) = op.get("seed_version") {
                let kind = k(&op["kind"]);
                let mut checkpoint = s.capture_checkpoint();
                let series = checkpoint["series"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|s| s["bar_type"] == kind.to_record())
                    .unwrap();
                series["version"] = version.clone();
                s.restore_checkpoint(&checkpoint).unwrap();
            } else {
                let bars: Vec<_> = op["bars"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|b| {
                        bar(
                            b[0].as_str().unwrap(),
                            b[1].as_u64().unwrap() as u32,
                            b[2].as_u64().unwrap() as u32,
                        )
                    })
                    .collect();
                let primary = k(&op["primary"]);
                let end = bars
                    .iter()
                    .find(|b| b.bar_type() == &primary)
                    .unwrap()
                    .bar_end();
                let init = OnlyTimestamp::from_datetime(*end);
                snapshot = Some(s.apply_closed(&bars, &primary, init, vec![]).unwrap());
            }
        }
        for expected in row["expected"].as_array().unwrap() {
            let kind = k(expected);
            let ends = expected[2].as_array().unwrap();
            let bars: Vec<_> = ends
                .iter()
                .map(|n| {
                    bar(
                        expected[0].as_str().unwrap(),
                        expected[1].as_u64().unwrap() as u32,
                        n.as_u64().unwrap() as u32,
                    )
                })
                .collect();
            assert_eq!(s.history(&kind, 99).unwrap(), bars, "{}", row["id"]);
            assert_eq!(s.version(&kind).to_string(), expected[3].to_string());
            assert_eq!(s.latest_closed(&kind), bars.last().map(|b| b.as_ref()));
            assert!(s.current_partial(&kind).is_none());
        }
        if let Some(filter) = row.get("filter") {
            let primary = k(&row["primary"]);
            let allowed: Vec<_> = filter.as_array().unwrap().iter().map(k).collect();
            let view = snapshot
                .unwrap()
                .restrict("c".parse().unwrap(), &allowed, &primary)
                .unwrap();
            assert_eq!(
                view.ts_event(),
                &stamp(row["event_minute"].as_u64().unwrap() as u32)
            );
            for kind in &allowed {
                assert_eq!(
                    view.history(kind, 99).unwrap(),
                    s.history(kind, 99).unwrap()
                );
                assert_eq!(view.version(kind).unwrap(), s.version(kind));
            }
            assert_eq!(view.visible_bar_types().len(), allowed.len());
        }
    }
}
#[test]
fn independent_full_current_records() {
    for line in include_str!("../../../../../test-data/market-data-state/records-v2.jsonl").lines()
    {
        let row: Value = serde_json::from_str(line).unwrap();
        let expected = &row["record"];
        if row["family"] == "checkpoint" {
            let mut s = state(2);
            s.restore_checkpoint(expected).unwrap();
            assert_eq!(s.capture_checkpoint(), *expected);
            let mut fresh = state(2);
            if let Some(bars) = row.get("bars") {
                let bars: Vec<_> = bars
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|b| Arc::new(OnlyBar::from_record(b).unwrap()))
                    .collect();
                apply(&mut fresh, &bars, bars[0].bar_type(), 1);
            }
            assert_eq!(fresh.capture_checkpoint(), *expected);
        } else {
            let decoded = OnlyMarketDataSnapshot::from_record(expected).unwrap();
            assert_eq!(decoded.to_record(), *expected);
            let mut fresh = state(2);
            let bars: Vec<_> = row["bars"]
                .as_array()
                .unwrap()
                .iter()
                .map(|b| Arc::new(OnlyBar::from_record(b).unwrap()))
                .collect();
            let root = fresh
                .apply_closed(
                    &bars,
                    bars[0].bar_type(),
                    OnlyTimestamp::from_unix_nanos("1767576660000000017".parse().unwrap()),
                    vec!["verified".into(), "explicit".into()],
                )
                .unwrap();
            let primary = kind(A, 1);
            let view = root
                .restrict(
                    "c".parse().unwrap(),
                    &[primary.clone(), kind(A, 3)],
                    &primary,
                )
                .unwrap();
            assert_eq!(view.to_record(), *expected);
        }
    }
}
