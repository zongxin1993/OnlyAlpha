mod support;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::OnlyTradingCalendar,
    market::{OnlyBar, OnlyBarType, OnlyTradeInputType, OnlyTradeTick},
    time::OnlyTimestamp,
};
use onlyalpha_market_data_construction::*;
use serde_json::{Value, json};
use std::sync::Arc;
use support::*;
struct Factory {
    mode: &'static str,
}
struct Executor {
    target: OnlyBarType,
    mode: &'static str,
}
impl OnlyConstructionFactory for Factory {
    fn create(
        &self,
        e: &OnlyConstructionEdge,
        _: Arc<OnlyTradingCalendar>,
    ) -> OnlyConstructionResult<Box<dyn OnlyConstructionExecutor>> {
        Ok(Box::new(Executor {
            target: e.target().clone(),
            mode: self.mode,
        }))
    }
}
impl OnlyConstructionExecutor for Executor {
    fn target(&self) -> &OnlyBarType {
        &self.target
    }
    fn process(
        &mut self,
        _: &OnlyConstructionFact,
        init: &OnlyTimestamp,
    ) -> OnlyConstructionResult<Vec<Arc<OnlyBar>>> {
        let mut row = bar(A, 1, 1).to_record();
        row["bar_type"] = self.target.to_record();
        row["ts_init"] = json!(init.to_datetime_exact().unwrap().to_string());
        match self.mode {
            "wrong" => row["bar_type"] = kind(A, 5).to_record(),
            "open" => row["is_closed"] = json!(false),
            "revision" => row["revision"] = json!(1),
            "event" => row["ts_event"] = json!(stamp(0).to_datetime_exact().unwrap().to_string()),
            "future" => {
                row["bar_end"] = json!(stamp(2).to_datetime_exact().unwrap().to_string());
                row["ts_event"] = row["bar_end"].clone();
            }
            "init" => row["ts_init"] = json!(stamp(3).to_datetime_exact().unwrap().to_string()),
            _ => {}
        }
        let b = Arc::new(OnlyBar::from_record(&row).unwrap());
        Ok(if self.mode == "duplicate" {
            vec![b.clone(), b]
        } else {
            vec![b]
        })
    }
    fn capture_checkpoint(&self) -> OnlyConstructionResult<Value> {
        Ok(json!({}))
    }
    fn restore_checkpoint(&mut self, _: &Value) -> OnlyConstructionResult<()> {
        Ok(())
    }
}
fn manager_for(mode: &'static str, trade: bool) -> OnlyConstructionManager {
    let target = kind(A, 3);
    let input = if trade {
        OnlyConstructionInput::Trade(OnlyTradeInputType::new(target.instrument_id().clone()))
    } else {
        OnlyConstructionInput::Bar(kind(A, 1))
    };
    let semantic = if trade {
        OnlyConstructionSemantic::Trade
    } else {
        OnlyConstructionSemantic::Bar(kind(A, 1).semantic().clone())
    };
    let recipe = OnlyConstructionRecipe::derived(
        target.semantic().clone(),
        semantic,
        "EXTENSION_TEST",
        1u32.into(),
        OnlyMissingPolicy::Reject,
        OnlyIncompletePolicy::Drop,
    )
    .unwrap();
    let edge = OnlyConstructionEdge::new(input.clone(), target, recipe).unwrap();
    let graph = OnlyConstructionGraph::new(vec![input], vec![edge]).unwrap();
    let mut registry = OnlyConstructionRegistry::default();
    registry
        .register("EXTENSION_TEST", 1u32.into(), Arc::new(Factory { mode }))
        .unwrap();
    let mut m = OnlyConstructionManager::new(
        OnlyConstructionScope::new("e".parse().unwrap(), "r".parse().unwrap(), "source").unwrap(),
        calendar(),
        Arc::new(registry),
    )
    .unwrap();
    m.register("graph", graph).unwrap();
    m
}
#[test]
fn trade_input_routes_only_through_the_registered_exact_lane() {
    let mut m = manager_for("ok", true);
    assert!(m.process("source", &fact(1), &stamp(2)).unwrap().is_empty());
    let time = stamp(1).to_datetime_exact().unwrap().to_string();
    let trade=OnlyTradeTick::from_record(&json!({"schema_version":1,"instrument_id":kind(A,1).instrument_id().to_record(),"ts_event":time,"ts_init":time,"sequence":0,"source":"provider","price":{"schema_version":1,"value":"10.00","precision":2},"quantity":{"schema_version":1,"value":"1","precision":0},"aggressor_side":null,"trade_id":{"schema_version":1,"value":"trade"}})).unwrap();
    assert_eq!(
        m.process(
            "source",
            &OnlyConstructionFact::Trade(Arc::new(trade)),
            &stamp(2)
        )
        .unwrap()
        .len(),
        1
    );
}
#[test]
fn malformed_extension_outputs_require_recovery_and_deliver_no_prefix() {
    for mode in [
        "wrong",
        "open",
        "revision",
        "event",
        "future",
        "init",
        "duplicate",
    ] {
        let mut m = manager_for(mode, false);
        let before = m.capture_checkpoint().unwrap();
        assert!(m.process("source", &fact(1), &stamp(2)).is_err(), "{mode}");
        assert!(m.is_failed());
        assert!(m.capture_checkpoint().is_err());
        m.restore_checkpoint(&before).unwrap();
        assert_eq!(m.capture_checkpoint().unwrap(), before);
    }
}
