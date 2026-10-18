mod support;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use onlyalpha_market_data_construction::*;
use serde_json::Value;
use std::sync::Arc;
use support::*;
#[test]
fn independent_current_records_hashes_and_lanes() {
    for line in
        include_str!("../../../../test-data/market-data-construction/models-v1.jsonl").lines()
    {
        let row: Value = serde_json::from_str(line).unwrap();
        let r = &row["record"];
        let decoded = match row["family"].as_str().unwrap() {
            "recipe" => {
                let v = OnlyConstructionRecipe::from_record(r).unwrap();
                assert_eq!(v.fingerprint(), row["sha256"].as_str().unwrap());
                v.to_record()
            }
            "requirement" => OnlyConstructionRequirement::from_record(r)
                .unwrap()
                .to_record(),
            "graph" => {
                let v = OnlyConstructionGraph::from_record(r).unwrap();
                assert_eq!(v.fingerprint(), row["sha256"].as_str().unwrap());
                v.to_record()
            }
            "plan" => OnlyConstructionResolutionPlan::from_record(r)
                .unwrap()
                .to_record(),
            "identity" => OnlyConstructionIdentity::from_record(r)
                .unwrap()
                .to_record(),
            "compiled" => {
                let graph = OnlyConstructionGraph::from_record(r).unwrap();
                let plan =
                    OnlyConstructionPlan::compile(&graph, row["source"].as_str().unwrap()).unwrap();
                assert_eq!(
                    plan.providers()[0].lane_id(),
                    row["provider"].as_str().unwrap()
                );
                for (actual, expected) in plan.lanes().iter().zip(row["lanes"].as_array().unwrap())
                {
                    assert_eq!(actual.lane_id(), expected["lane_id"].as_str().unwrap());
                    assert_eq!(
                        actual.source_lane_id(),
                        expected["source_lane_id"].as_str().unwrap()
                    );
                    assert_eq!(actual.level(), expected["level"].as_u64().unwrap() as usize);
                }
                assert_eq!(plan.lanes().len(), row["lanes"].as_array().unwrap().len());
                graph.to_record()
            }
            _ => panic!("unknown family"),
        };
        assert_eq!(decoded, *r, "{}", row["id"]);
    }
}
#[test]
fn independent_aggregation_records_and_fresh_executor_replay() {
    for line in
        include_str!("../../../../test-data/market-data-construction/operations-v1.jsonl").lines()
    {
        let row: Value = serde_json::from_str(line).unwrap();
        let edge = OnlyConstructionEdge::from_record(&row["edge"]).unwrap();
        let mut executor = OnlyTimeBarExecutor::new(edge.clone(), calendar()).unwrap();
        let mut restored = OnlyTimeBarExecutor::new(edge, calendar()).unwrap();
        let mut actual = vec![];
        for (index, record) in row["inputs"].as_array().unwrap().iter().enumerate() {
            let bar = Arc::new(OnlyBar::from_record(record).unwrap());
            let init = OnlyTimestamp::from_datetime(*bar.bar_end());
            let fact = OnlyConstructionFact::Bar(bar);
            let produced = executor.process(&fact, &init).unwrap();
            assert_eq!(restored.process(&fact, &init).unwrap(), produced);
            actual.extend(produced.into_iter().map(|b| b.to_record()));
            if index + 1 == row["restore_after"].as_u64().unwrap() as usize {
                let checkpoint = executor.capture_checkpoint().unwrap();
                let mut fresh = OnlyTimeBarExecutor::new(
                    OnlyConstructionEdge::from_record(&row["edge"]).unwrap(),
                    calendar(),
                )
                .unwrap();
                fresh.restore_checkpoint(&checkpoint).unwrap();
                restored = fresh;
            }
        }
        assert_eq!(Value::Array(actual), row["expected"], "{}", row["id"]);
    }
}
