//! The real planner's valuation consumer must not build historical Ledger DTOs.
use super::*;
use serde_json::{Value,json};
const FIXTURE:&str=include_str!("../../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE:&str=include_str!("../../../../test-data/settlement/common-v1.json");
#[path="../tests/support/mod.rs"] mod support;
use support::{Harness,config,open,stage,fill};
fn apply(history:&mut Harness,input:&Value){let planned=history.prepare(input).unwrap();coordinate(&mut history.store,&mut history.components,&planned).unwrap();}
#[test]
fn actual_valuation_planning_uses_current_ledger_lines_without_constructing_full_history(){
 for modern in [false,true] {
  let mut configuration=config();
  if modern {configuration["schema_version"]=json!(2);configuration["account_checkpoint_version"]=json!(5);}
  configuration["capitals"]=json!({"cluster":"500.00","second":"500.00"});
  configuration["profiles"]["second"]=configuration["profiles"]["cluster"].clone();
  let mut history=Harness::new(configuration).unwrap();
  for input in [open(1,"BUY"),stage(2,1,"UNKNOWN"),fill(3,1,"4","10.00","1.00")] {apply(&mut history,&input);}
  for n in 4..=6 {
   let before=history.state().unwrap();let old_records=history.store.rows.clone();
   let valuation=support::input(n,"VALUATION",json!({"schema_version":1,"valuation":format!("bounded-ledger-view-{n}"),"version":n,
    "position_evidence":digest(history.components.position.checkpoint().unwrap().0.as_slice()),
    "economic_version":before["account"]["snapshot"]["economic_version"],
    "marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":"12.00","source_ref":format!("bounded-ledger-mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}]}));
   crate::valuation::FULL_LEDGER_STATE_CAPTURES.with(|count|count.set(0));
   let planned=history.prepare(&valuation).unwrap();
   let captures=crate::valuation::FULL_LEDGER_STATE_CAPTURES.with(std::cell::Cell::get);
   assert_eq!(captures,0,"actual valuation planning constructed the complete Ledger timeline/receipts/aliases/entries for account format {modern} at sequence {n}");
   assert_eq!(history.store.rows,old_records,"planning reads cannot append or acknowledge source");
   coordinate(&mut history.store,&mut history.components,&planned).unwrap();let after=history.state().unwrap();
   assert_eq!(after["account"]["snapshot"]["cash"],before["account"]["snapshot"]["cash"]);
   assert_eq!(after["account"]["snapshot"]["market_value"],"48.00");
   assert_eq!(after["position"],before["position"]);
   assert_eq!(after["ledger"]["ledgers"]["second"]["snapshot"]["economic_version"],0);
   assert_eq!(after["ledger"]["ledgers"]["second"]["snapshot"]["valuation_version"],n,"the empty configured Cluster still consumes the original complete valuation command");
  }
 }
}
