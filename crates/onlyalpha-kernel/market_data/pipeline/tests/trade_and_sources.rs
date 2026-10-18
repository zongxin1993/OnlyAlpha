mod support;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::OnlyTradingCalendar,
    market::{OnlyBar, OnlyBarType, OnlyTradeInputType, OnlyTradeTick},
    time::OnlyTimestamp,
};
use onlyalpha_market_data_pipeline::{construction::*, delivery::*, *};
use serde_json::{Value, json};
use std::sync::Arc;
use support::*;
struct Factory;
struct Pending {
    target: OnlyBarType,
    count: u64,
}
impl OnlyConstructionFactory for Factory {
    fn create(
        &self,
        e: &OnlyConstructionEdge,
        _: Arc<OnlyTradingCalendar>,
    ) -> OnlyConstructionResult<Box<dyn OnlyConstructionExecutor>> {
        Ok(Box::new(Pending {
            target: e.target().clone(),
            count: 0,
        }))
    }
}
impl OnlyConstructionExecutor for Pending {
    fn target(&self) -> &OnlyBarType {
        &self.target
    }
    fn process(
        &mut self,
        _: &OnlyConstructionFact,
        _: &OnlyTimestamp,
    ) -> OnlyConstructionResult<Vec<Arc<OnlyBar>>> {
        self.count += 1;
        Ok(vec![])
    }
    fn capture_checkpoint(&self) -> OnlyConstructionResult<Value> {
        Ok(json!({"count":self.count}))
    }
    fn restore_checkpoint(&mut self, r: &Value) -> OnlyConstructionResult<()> {
        self.count = r["count"]
            .as_u64()
            .ok_or(OnlyConstructionError::Validation("count".into()))?;
        Ok(())
    }
}
fn trade_program() -> PipelineProgram {
    let root =
        OnlyConstructionInput::Trade(OnlyTradeInputType::new(kind(A, 1).instrument_id().clone()));
    let target = kind(A, 3);
    let recipe = OnlyConstructionRecipe::derived(
        target.semantic().clone(),
        OnlyConstructionSemantic::Trade,
        "CONTROLLED_PENDING",
        1u32.into(),
        OnlyMissingPolicy::Reject,
        OnlyIncompletePolicy::Drop,
    )
    .unwrap();
    let graph = OnlyConstructionGraph::new(
        vec![root.clone()],
        vec![OnlyConstructionEdge::new(root, target.clone(), recipe).unwrap()],
    )
    .unwrap();
    let mut registry = OnlyConstructionRegistry::default();
    registry
        .register("CONTROLLED_PENDING", 1u32.into(), Arc::new(Factory))
        .unwrap();
    let source = SourceProgram::new(
        &source(),
        calendar(),
        Arc::new(registry),
        &"e".repeat(64),
        graph.clone(),
    )
    .unwrap();
    let sub = OnlyBarSubscription::new(
        "trade-sub",
        vec![target.clone()],
        graph,
        Some(target),
        OnlyBarFreshness::LatestClosed,
    )
    .unwrap();
    PipelineProgram::new(
        owner(),
        &"a".repeat(64),
        4,
        vec![source],
        vec![ClusterProgram {
            cluster: "a".parse().unwrap(),
            subscription: sub,
        }],
        vec![],
        &"f".repeat(64),
    )
    .unwrap()
}
fn trade(sequence: u64) -> PipelineInput {
    let time = stamp(1).to_datetime_exact().unwrap().to_string();
    let tick=OnlyTradeTick::from_record(&json!({"schema_version":1,"instrument_id":kind(A,1).instrument_id().to_record(),"ts_event":time,"ts_init":time,"sequence":sequence,"source":"fixture","price":{"schema_version":1,"value":"10.00","precision":2},"quantity":{"schema_version":1,"value":"1","precision":0},"aggressor_side":null,"trade_id":{"schema_version":1,"value":format!("trade-{sequence}")}})).unwrap();
    PipelineInput {
        source: source(),
        sequence,
        fact: OnlyConstructionFact::Trade(Arc::new(tick)),
        logical_init: stamp(1),
        quality: vec![],
    }
}
#[test]
fn trade_without_closed_bar_advances_only_its_exact_input_frontier() {
    let consumer = Recorder::default();
    let calls = consumer.calls.clone();
    let mut p = MarketDataPipeline::new(trade_program(), NoCalculations, consumer).unwrap();
    let first = p.process(&trade(1)).unwrap();
    assert!(first.snapshot.is_none());
    assert!(first.receipts.is_empty());
    assert!(calls.lock().unwrap().is_empty());
    let cp = p.capture_checkpoint().unwrap();
    let mut fresh =
        MarketDataPipeline::new(trade_program(), NoCalculations, Recorder::default()).unwrap();
    restore(&mut fresh, &cp).unwrap();
    assert_eq!(
        p.process(&trade(2)).unwrap().to_record(),
        fresh.process(&trade(2)).unwrap().to_record()
    );
    assert!(p.process(&trade(2)).is_err());
    assert!(!p.is_failed());
    assert_eq!(
        p.capture_checkpoint().unwrap(),
        fresh.capture_checkpoint().unwrap()
    );
}
#[test]
fn ambiguous_same_bar_type_source_ownership_is_refused() {
    let graph =
        OnlyConstructionGraph::new(vec![OnlyConstructionInput::Bar(kind(A, 1))], vec![]).unwrap();
    let sources = ["b", "c"]
        .into_iter()
        .map(|s| {
            SourceProgram::new(
                &s.repeat(64),
                calendar(),
                Arc::new(OnlyConstructionRegistry::default()),
                &"e".repeat(64),
                graph.clone(),
            )
            .unwrap()
        })
        .collect();
    let sub = OnlyBarSubscription::new(
        "s",
        vec![kind(A, 1)],
        graph,
        Some(kind(A, 1)),
        OnlyBarFreshness::LatestClosed,
    )
    .unwrap();
    assert!(
        PipelineProgram::new(
            owner(),
            &"a".repeat(64),
            4,
            sources,
            vec![ClusterProgram {
                cluster: "a".parse().unwrap(),
                subscription: sub
            }],
            vec![],
            &"f".repeat(64)
        )
        .is_err()
    );
}
#[test]
fn independent_sources_and_instruments_do_not_share_history_or_callbacks() {
    let mut sources = vec![];
    let mut clusters = vec![];
    for (id, instrument) in [("b", A), ("c", "OTHER.XSHG")] {
        let k = kind(instrument, 1);
        let g = OnlyConstructionGraph::new(vec![OnlyConstructionInput::Bar(k.clone())], vec![])
            .unwrap();
        sources.push(
            SourceProgram::new(
                &id.repeat(64),
                calendar(),
                Arc::new(OnlyConstructionRegistry::default()),
                &"e".repeat(64),
                g.clone(),
            )
            .unwrap(),
        );
        clusters.push(ClusterProgram {
            cluster: id.parse().unwrap(),
            subscription: OnlyBarSubscription::new(
                id,
                vec![k.clone()],
                g,
                Some(k),
                OnlyBarFreshness::LatestClosed,
            )
            .unwrap(),
        });
    }
    let program = PipelineProgram::new(
        owner(),
        &"a".repeat(64),
        4,
        sources,
        clusters,
        vec![],
        &"f".repeat(64),
    )
    .unwrap();
    let mut p = MarketDataPipeline::new(program, NoCalculations, Recorder::default()).unwrap();
    for (id, instrument) in [("b", A), ("c", "OTHER.XSHG")] {
        let mut i = input(1);
        i.source = id.repeat(64);
        i.fact = OnlyConstructionFact::Bar(bar(instrument, 1, 1));
        let out = p.process(&i).unwrap();
        assert_eq!(out.receipts.len(), 1);
        assert_eq!(out.receipts[0]["cluster"], id);
    }
    let cp = p.capture_checkpoint().unwrap();
    restore(&mut p, &cp).unwrap();
}

#[test]
fn no_output_trade_executor_cannot_rewind_behind_its_input_frontier() {
    let mut p =
        MarketDataPipeline::new(trade_program(), NoCalculations, Recorder::default()).unwrap();
    p.process(&trade(1)).unwrap();
    let old = p.capture_checkpoint().unwrap();
    p.process(&trade(2)).unwrap();
    let current = p.capture_checkpoint().unwrap();
    for include_binding in [false, true] {
        let mut spliced = current.clone();
        spliced["managers"] = old["managers"].clone();
        if include_binding {
            spliced["component_bindings"] = old["component_bindings"].clone();
        }
        assert!(restore(&mut p, &spliced).is_err());
        assert_eq!(p.capture_checkpoint().unwrap(), current);
    }
}
