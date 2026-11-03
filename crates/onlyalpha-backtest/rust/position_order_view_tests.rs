//! Compare the original retained actual Kernel projections, never a DTO grant.
use super::*;
use crate::execution_test_fixture::{configuration,original_three_facts};
fn current_view(c:&OriginalExecution<'_>)->Result<Value,Error>{
 c.position_order_view()
}
#[test]
fn original_position_order_view_borrows_actual_prepared_components_without_full_state(){
 for modern in [false,true]{
  let configuration=configuration(modern);
  let genesis=Components::new(configuration.clone()).unwrap().checkpoint().unwrap()["components"].as_array().unwrap().clone();
  let mut history=crate::Candidate::new(configuration.clone(),vec![]).unwrap();
  for input in original_three_facts(){history.apply(&input).unwrap();}
  let original=history.records().to_vec();
  for cursor in 0..=history.records().len(){
   let c=OriginalExecution{configuration:&configuration,records:history.records(),genesis:genesis.clone(),cursor,end:history.records().len()};
   let state=c.state().unwrap();let checkpoint=c.checkpoint().unwrap();
   let expected=json!({"schema_version":1,"orders":state["execution"]["orders"],"position_accounts":state["position"]["accounts"],"position_allocations":state["position"]["allocations"],"economic_version":state["account"]["snapshot"]["economic_version"],"position_checkpoint_fingerprint":onlyalpha_execution::digest(checkpoint["components"][1].to_string().as_bytes())});
   FULL_ORIGINAL_STATE_CONSTRUCTIONS.with(|n|n.set(0));
   assert_eq!(current_view(&c).unwrap(),expected);
   assert_eq!(FULL_ORIGINAL_STATE_CONSTRUCTIONS.with(std::cell::Cell::get),0,"original readonly query rebuilt all six full owner projections");
   assert_eq!(c.checkpoint().unwrap(),checkpoint);assert_eq!(history.records(),original.as_slice());
  }
  let c=OriginalExecution{configuration:&configuration,records:history.records(),genesis:genesis.clone(),cursor:history.records().len()+1,end:history.records().len()};
  assert!(current_view(&c).is_err(),"missing actual original source never becomes an empty view");
 }
}
