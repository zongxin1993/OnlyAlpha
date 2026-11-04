//! Pure owner-image codec reuse; never a Ready/source-proof cache.
use super::*;
const FIXTURE:&str=include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE:&str=include_str!("../../../test-data/settlement/common-v1.json");
#[path="../tests/support/mod.rs"] mod support;
use support::{Harness,config,open,stage,fill,terminal};
fn capture_bytes()->u64{PAYLOAD_CAPTURE_BYTES.with(std::cell::Cell::get)}
fn reset_capture(){PAYLOAD_CAPTURE_BYTES.with(|count|count.set(0));}
fn actual_images(components:&Components)->Vec<Value>{
 let mut values=Vec::new();
 for bytes in [components.order.checkpoint().unwrap().0,components.position.checkpoint().unwrap().0,components.account.checkpoint().unwrap().0,components.ledger.checkpoint().unwrap().0,components.risk.checkpoint().unwrap().0]{values.push(serde_json::from_slice(&bytes).unwrap());}
 values.push(components.meta.clone());values
}
#[test]
fn unchanged_payload_reads_share_encoding_without_recapturing_owner_history(){
 let components=Components::new(config()).unwrap();reset_capture();
 let expected=actual_images(&components);let original=components.payloads().unwrap();assert_eq!(original.iter().cloned().collect::<Vec<_>>(),expected);assert!(capture_bytes()>0);
 reset_capture();
 for _ in 0..4 {
  assert_eq!(components.payloads().unwrap().iter().cloned().collect::<Vec<_>>(),expected);
  for (index,value) in expected.iter().enumerate(){assert_eq!(components.payload_digest(index).unwrap(),hash(value));}
  let mut detached=components.checkpoint().unwrap();assert_eq!(detached["components"],Value::Array(expected.clone()));
  detached["components"][5]["last_runtime_sequence"]=json!(999);
  assert_eq!(components.payloads().unwrap()[5],expected[5],"a detached checkpoint cannot mutate the private codec image");
 }
 assert_eq!(capture_bytes(),0,"the same immutable owner image was repeatedly encoded through owner checkpoint readers");
}
#[test]
fn every_installed_owner_image_and_failed_install_attempt_discards_the_old_codec(){
 let mut history=Harness::new(config()).unwrap();
 for value in [open(1,"BUY"),stage(2,1,"UNKNOWN"),fill(3,1,"1","10.00","1.00"),terminal(4,1,"CANCELLED")] {
  let before=history.components.checkpoint().unwrap();let prepared=history.prepare(&value).unwrap();
  assert_eq!(history.components.checkpoint().unwrap(),before,"planning cannot mutate the source owner or its image");
  if value["op"]=="ADMIT" {assert_ne!(prepared.record()["projections"][0]["result"],before["components"][0],"the candidate must invalidate its inherited pre-admission image");}
  for index in 0..6 {
   let _=history.components.payloads().unwrap();history.install_projection(&prepared,index).unwrap();
   assert_eq!(history.components.payloads().unwrap().iter().cloned().collect::<Vec<_>>(),actual_images(&history.components),"owner {index}");
  }
  history.complete(&prepared).unwrap();
 }
 let expected=actual_images(&history.components);let _=history.components.payloads().unwrap();
 assert!(history.components.install_payload(6,&Value::Null).is_err());reset_capture();
 assert_eq!(history.components.payloads().unwrap().iter().cloned().collect::<Vec<_>>(),expected);assert!(capture_bytes()>0,"even a failed install attempt invalidates the codec");
 let checkpoint=history.components.checkpoint().unwrap();history.components.restore(&checkpoint,&hash(&checkpoint)).unwrap();
 assert_eq!(history.components.payloads().unwrap().iter().cloned().collect::<Vec<_>>(),expected);
 history.store.rows.clear();assert!(history.components.state(&history.store).is_err());assert!(history.components.reconcile(&history.store).is_err());
}

#[test]
fn derived_codec_sharing_preserves_components_and_prepared_send_sync(){
 fn require_send_sync<T:Send+Sync>(){}
 require_send_sync::<Components>();require_send_sync::<crate::Prepared>();
}

#[test]
fn warmed_large_owner_hash_is_not_reencoded_by_fresh_source_queries(){
 let mut history=Harness::new(config()).unwrap();
 for n in 1..=16_u64 {
  let value=match n {
   1=>open(1,"BUY"),2=>stage(2,1,"UNKNOWN"),3=>fill(3,1,"1","10.00","1.00"),4=>terminal(4,1,"CANCELLED"),
   _=>{let state=history.components.state(&history.store).unwrap();support::input(n,"VALUATION",json!({"schema_version":1,"valuation":format!("memo-valuation-{n}"),"version":n,
      "position_evidence":digest(history.components.checkpoint().unwrap()["components"][1].to_string().as_bytes()),"economic_version":state["account"]["snapshot"]["economic_version"],
      "marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":"12.00","source_ref":format!("memo-mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}]}))},
  };
  let prepared=history.prepare(&value).unwrap();crate::coordinate(&mut history.store,&mut history.components,&prepared).unwrap();
 }
 let actual=actual_images(&history.components);
 let owner=actual.iter().max_by_key(|v|v.to_string().len()).unwrap();let canonical=owner.to_string();
 assert!(canonical.len()>4096,"the watched hash input must be a real retained owner history, not a small metadata field");
 let expected=digest(canonical.as_bytes());
 crate::model::HASHED_CANONICAL_WATCH.with(|watch|*watch.borrow_mut()=Some((canonical.clone(),0)));
 assert_eq!(hash(owner),expected);
 assert_eq!(crate::model::HASHED_CANONICAL_WATCH.with(|watch|watch.borrow().as_ref().unwrap().1),1,"instrument the actual canonical hash entry point");
 crate::model::HASHED_CANONICAL_WATCH.with(|watch|*watch.borrow_mut()=Some((canonical,0)));
 for _ in 0..3 {
  history.components.ready_source(&history.store).unwrap();history.components.ready_records(&history.store).unwrap();
  history.components.state(&history.store).unwrap();history.components.reconcile(&history.store).unwrap();
  for index in 0..6 {assert_eq!(history.components.payload_digest(index).unwrap(),digest(actual[index].to_string().as_bytes()));}
 }
 let repeated=crate::model::HASHED_CANONICAL_WATCH.with(|watch|watch.borrow().as_ref().unwrap().1);
 crate::model::HASHED_CANONICAL_WATCH.with(|watch|*watch.borrow_mut()=None);
 assert_eq!(repeated,0,"fresh source checks reserialized and hashed the same already immutable large owner payload");
 let row=history.store.rows.pop().unwrap();
 assert!(history.components.state(&history.store).is_err());assert!(history.components.reconcile(&history.store).is_err());
 history.store.rows.push(row);history.components.reconcile(&history.store).unwrap();
}


#[test]
fn cold_selected_digest_captures_only_that_complete_owner_at_every_native_format(){
 for modern in [false,true]{
  let mut configuration=config();if modern{configuration["schema_version"]=json!(2);configuration["account_checkpoint_version"]=json!(5);}
  let mut history=Harness::new(configuration).unwrap();
  for input in [open(1,"BUY"),stage(2,1,"UNKNOWN"),fill(3,1,"1","10.00","1.00")]{
   let prepared=history.prepare(&input).unwrap();crate::coordinate(&mut history.store,&mut history.components,&prepared).unwrap();
  }
  let expected=actual_images(&history.components);
  let complete_bytes=expected.iter().map(|value|value.to_string().len() as u64).sum::<u64>();
  for (selected,value) in expected.iter().enumerate(){
   let bytes=serde_json::to_vec(value).unwrap();assert!(complete_bytes>bytes.len() as u64);
   history.components.invalidate_payloads();reset_capture();
   assert_eq!(history.components.payload_digest(selected).unwrap(),digest(&bytes),"format {modern}, owner {selected}");
   assert_eq!(capture_bytes(),bytes.len() as u64,"a cold selected-owner read encoded unrelated owner histories: format {modern}, owner {selected}");
   reset_capture();
   assert_eq!(history.components.payloads().unwrap().as_ref(),&expected);
   assert_eq!(capture_bytes(),complete_bytes,"a selected-owner read must not install an incomplete six-owner image");
   reset_capture();assert_eq!(history.components.payload_digest(selected).unwrap(),digest(&bytes));
   assert_eq!(capture_bytes(),0,"an existing complete immutable image must still serve a selected hash without reencoding");
  }
 }
}

#[test]
fn a_cold_selected_digest_cannot_hide_an_actually_changed_owner_before_install(){
 let mut donor=Harness::new(config()).unwrap();
 for input in [open(1,"BUY"),stage(2,1,"UNKNOWN"),fill(3,1,"1","10.00","1.00")]{
  let prepared=donor.prepare(&input).unwrap();crate::coordinate(&mut donor.store,&mut donor.components,&prepared).unwrap();
 }
 for selected in 0..6{
  let mut pending=Harness::new(config()).unwrap();let planned=pending.prepare(&open(1,"BUY")).unwrap();pending.commit_only(&planned).unwrap();
  for index in 0..selected{pending.components.install_projection(&pending.store,&planned,index).unwrap();}
  let _=pending.components.payloads().unwrap();
  match selected{
   0=>pending.components.order=donor.components.order.clone(),1=>pending.components.position=donor.components.position.clone(),
   2=>pending.components.account=donor.components.account.clone(),3=>pending.components.ledger=donor.components.ledger.clone(),
   4=>pending.components.risk=donor.components.risk.clone(),5=>pending.components.meta=donor.components.meta.clone(),_=>unreachable!(),
  }
  pending.components.invalidate_payloads();
  let before=actual_images(&pending.components);let actual=hash(&before[selected]);let record=planned.record();
  assert_ne!(record["projections"][selected]["before_hash"],actual,"owner {selected}");
  assert_ne!(record["projections"][selected]["result_hash"],actual,"owner {selected}");
  assert_eq!(pending.components.payload_digest(selected).unwrap(),actual,"the selected owner must be read after invalidation");
  let progress=pending.components.pending.clone();let source=pending.store.rows.clone();
  assert_eq!(pending.components.install_projection(&pending.store,&planned,selected).unwrap_err().0,"EXECUTION_BEFORE_CONFLICT","owner {selected}");
  assert_eq!(actual_images(&pending.components),before);assert_eq!(pending.components.pending,progress);assert_eq!(pending.store.rows,source);
 }
}

#[test]
fn completing_a_projection_batch_still_captures_all_six_actual_owners(){
 let mut history=Harness::new(config()).unwrap();
 for input in [open(1,"BUY"),stage(2,1,"UNKNOWN"),fill(3,1,"1","10.00","1.00")]{
  let prepared=history.prepare(&input).unwrap();
  for index in 0..6{history.install_projection(&prepared,index).unwrap();}
  history.components.invalidate_payloads();
  let expected=actual_images(&history.components);let all=expected.iter().map(|value|value.to_string().len() as u64).sum::<u64>();
  reset_capture();history.complete(&prepared).unwrap();
  assert_eq!(capture_bytes(),all,"completion must prove every complete actual owner, not only the last selected projection");
  assert_eq!(history.components.payloads().unwrap().as_ref(),&expected);
 }
}


#[test]
fn a_cold_account_digest_keeps_the_explicit_execution_checkpoint_format(){
 for modern in [false,true]{
  let mut configuration=config();if modern{configuration["schema_version"]=json!(2);configuration["account_checkpoint_version"]=json!(5);}
  let mut foreign=config();if !modern{foreign["schema_version"]=json!(2);foreign["account_checkpoint_version"]=json!(5);}
  let mut target=Components::new(configuration).unwrap();let _=target.payloads().unwrap();
  target.account=Components::new(foreign).unwrap().account;target.invalidate_payloads();
  assert_eq!(target.payload_digest(2).unwrap_err().0,"EXECUTION_ACCOUNT_CHECKPOINT_FORMAT");
 }
}


fn actual_encoded_owners(components:&Components)->Vec<(Vec<u8>,String)>{
 vec![components.order.checkpoint().unwrap(),components.position.checkpoint().unwrap(),components.account.checkpoint().unwrap(),components.ledger.checkpoint().unwrap(),components.risk.checkpoint().unwrap()]
}
#[test]
fn actual_owner_checkpoint_bytes_and_hashes_equal_the_original_value_codec_at_both_account_formats(){
 for modern in [false,true]{
  let mut configuration=config();if modern{configuration["schema_version"]=json!(2);configuration["account_checkpoint_version"]=json!(5);}
  let mut history=Harness::new(configuration).unwrap();
  for input in [open(1,"BUY"),stage(2,1,"UNKNOWN"),fill(3,1,"1","10.00","1.00")]{let prepared=history.prepare(&input).unwrap();crate::coordinate(&mut history.store,&mut history.components,&prepared).unwrap();}
  let owners=actual_encoded_owners(&history.components);
  history.components.invalidate_payloads();
  let actual=history.components.payloads().unwrap();let hashes=history.components.payload_hashes().unwrap();
  for (index,(bytes,fingerprint)) in owners.iter().enumerate(){
   let parsed:Value=serde_json::from_slice(bytes).unwrap();
   assert_eq!(&actual[index],&parsed,"complete owner {index} format{modern}");
   assert_eq!(serde_json::to_vec(&actual[index]).unwrap(),*bytes,"literal canonical owner bytes {index}");
   assert_eq!(digest(bytes),*fingerprint,"actual returned bytes SHA {index}");
   assert_eq!(digest(parsed.to_string().as_bytes()),*fingerprint,"unchanged original Value hash semantics {index}");
   assert_eq!(hashes[index],*fingerprint);
  }
  assert_eq!(actual[2]["schema_version"],if modern{5}else{4});
  assert_eq!(actual[5],history.components.meta);assert_eq!(hashes[5],digest(history.components.meta.to_string().as_bytes()));
 }
}
#[test]
fn cold_payload_capture_reuses_each_actual_returned_hash_but_still_hashes_complete_metadata(){
 for modern in [false,true]{
  let mut configuration=config();if modern{configuration["schema_version"]=json!(2);configuration["account_checkpoint_version"]=json!(5);}
  let mut history=Harness::new(configuration).unwrap();
  for input in [open(1,"BUY"),stage(2,1,"UNKNOWN"),fill(3,1,"1","10.00","1.00")]{let prepared=history.prepare(&input).unwrap();crate::coordinate(&mut history.store,&mut history.components,&prepared).unwrap();}
  let owners=actual_encoded_owners(&history.components);
  for (selected,(bytes,fingerprint)) in owners.iter().enumerate(){
   let mut actual=history.components.clone_data();actual.invalidate_payloads();
   let canonical=String::from_utf8(bytes.clone()).unwrap();
   crate::model::HASHED_CANONICAL_WATCH.with(|watch|*watch.borrow_mut()=Some((canonical,0)));
   let image=actual.payloads().unwrap();let actual_hash=actual.payload_hashes().unwrap()[selected].clone();
   let calls=crate::model::HASHED_CANONICAL_WATCH.with(|watch|watch.borrow_mut().take().unwrap().1);
   assert_eq!(calls,0,"owner{selected} format{modern} was serialized and hashed again after its checkpoint returned the exact hash");
   assert_eq!(actual_hash,*fingerprint);assert_eq!(serde_json::to_vec(&image[selected]).unwrap(),*bytes);
  }
  let mut actual=history.components.clone_data();actual.invalidate_payloads();
  let canonical=actual.meta.to_string();let expected=digest(canonical.as_bytes());
  crate::model::HASHED_CANONICAL_WATCH.with(|watch|*watch.borrow_mut()=Some((canonical,0)));
  let image=actual.payloads().unwrap();let fingerprint=actual.payload_hashes().unwrap()[5].clone();
  let calls=crate::model::HASHED_CANONICAL_WATCH.with(|watch|watch.borrow_mut().take().unwrap().1);
  assert_eq!(calls,1,"unencoded complete metadata still needs its original actual hash");
  assert_eq!(fingerprint,expected);assert_eq!(image[5],actual.meta);
 }
}
