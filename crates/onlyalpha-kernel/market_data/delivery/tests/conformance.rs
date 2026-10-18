mod support;
use onlyalpha_market_data_delivery::*;
use serde_json::Value;
use support::*;
fn configured(row: &Value) -> OnlyMarketDataDelivery {
    let mut owner = delivery();
    for sub in row["subscriptions"].as_array().unwrap() {
        let kinds: Vec<_> = sub["types"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| kind(A, v.as_u64().unwrap() as u32))
            .collect();
        let primary = sub["primary"].as_u64().map(|v| kind(A, v as u32));
        let subscription = OnlyBarSubscription::new(
            sub["id"].as_str().unwrap(),
            kinds.clone(),
            graph(&kinds),
            primary,
            OnlyBarFreshness::LatestClosed,
        )
        .unwrap();
        owner
            .register(
                sub["cluster"].as_str().unwrap().parse().unwrap(),
                subscription,
            )
            .unwrap();
    }
    owner
}
#[test]
fn independent_real_routing_and_fresh_owner_replay() {
    for line in
        include_str!("../../../../../test-data/market-data-delivery/routing-v1.jsonl").lines()
    {
        let row: Value = serde_json::from_str(line).unwrap();
        let mut owner = configured(&row);
        let mut replay = configured(&row);
        let mut state = state(2);
        for (index, (operation, expected)) in row["operations"]
            .as_array()
            .unwrap()
            .iter()
            .zip(row["expected"].as_array().unwrap())
            .enumerate()
        {
            let window = operation[0].as_u64().unwrap() as u32;
            let end = operation[1].as_u64().unwrap() as u32;
            let snapshot = apply(&mut state, &[bar(A, window, end)], &kind(A, window), end);
            let plans = owner.route(&snapshot).unwrap();
            assert_eq!(replay.route(&snapshot).unwrap(), plans);
            let actual: Vec<_> = plans
                .iter()
                .map(|p| Value::from(p.cluster_id().value()))
                .collect();
            assert_eq!(Value::Array(actual), *expected);
            if index + 1 == row["restore_after"].as_u64().unwrap() as usize {
                let mut fresh = configured(&row);
                fresh
                    .restore_checkpoint(&owner.capture_checkpoint())
                    .unwrap();
                replay = fresh;
            }
        }
        assert_eq!(owner.capture_checkpoint(), replay.capture_checkpoint());
    }
}
