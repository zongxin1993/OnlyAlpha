//! Actual SQL work and physical faults of the existing public owning query.
use super::*;
#[test]
fn sqlite_prefix_queries_read_actual_rows_once_instead_of_revisiting_head_and_anchor(){
 for count in [16,32,0] {
  let h=if count==0{dictionary_history()}else{source_history(count)};
  let count=h.inputs.len() as u64;let expected=h.reference.components.position_order_view(&h.reference.store).unwrap();
  h.components.position_order_view(&h.store).unwrap();let before=fs::read(h.root.db()).unwrap();
  for _ in 0..2 {
   reset_source_work();assert_eq!(h.components.position_order_view(&h.store).unwrap(),expected);
   assert_eq!(SOURCE_HEAD_AGGREGATES.with(std::cell::Cell::get),1,"a prefix repeated the full SQL head aggregate for {count} records");
   let actual=SOURCE_RAW_ROWS.with(std::cell::Cell::get);assert!((count..=count+2).contains(&actual),"prefix needs every actual row plus only its original outer head/base observation, got {actual} at {count}");
  }
  assert_eq!(fs::read(h.root.db()).unwrap(),before,"read-only source batching cannot write or repair history");
 }
}
#[test]
fn sqlite_warm_prefix_queries_reject_actual_old_rows_flags_identity_and_head_without_repair(){
 let h=dictionary_history();let expected=h.components.position_order_view(&h.store).unwrap();let checkpoint=h.components.checkpoint().unwrap();let records=h.store.read_records().unwrap();
 let (meta,meta_sha):(String,String)=h.store.connection.query_row("SELECT payload,digest FROM meta",[],|row|Ok((row.get(0)?,row.get(1)?))).unwrap();
 let head:String=h.store.connection.query_row("SELECT last_hash FROM state",[],|row|row.get(0)).unwrap();let (raw,physical)=dictionary_raw(&h.store,2);
 for fault in ["old-lineage","old-flags","index","identity","head","version","application"] {
  h.components.position_order_view(&h.store).unwrap();
  match fault {
   "old-lineage"=>{let mut p=records[1].prepared().record();p["projections"][0]["before_hash"]=json!("f".repeat(64));rehash_prepared(&mut p);replace_prepared_source(&h.store,2,&p,true,false);},
   "old-flags"=>{h.store.connection.execute("UPDATE records SET ready=0,delivered=0 WHERE sequence=2",[]).unwrap();},
   "index"=>{h.store.connection.execute("UPDATE records SET input_id='foreign-index' WHERE sequence=2",[]).unwrap();},
   "identity"=>{let mut p:Value=serde_json::from_str(&meta).unwrap();p["configuration"]["generation"]=json!("f".repeat(64));h.store.connection.execute("UPDATE meta SET payload=?1,digest=?2",params![p.to_string(),hash(&p)]).unwrap();},
   "head"=>{h.store.connection.execute("UPDATE state SET last_hash=?1",["f".repeat(64)]).unwrap();},
   "version"=>h.store.connection.pragma_update(None,"user_version",3_i64).unwrap(),
   _=>h.store.connection.pragma_update(None,"application_id",0_i64).unwrap(),
  }
  let actual=fs::read(h.root.db()).unwrap();assert!(h.components.position_order_view(&h.store).is_err(),"warm prefix hid actual {fault}");assert_eq!(fs::read(h.root.db()).unwrap(),actual,"{fault} must not be repaired");assert_eq!(h.components.checkpoint().unwrap(),checkpoint);
  h.store.connection.pragma_update(None,"user_version",4_i64).unwrap();h.store.connection.pragma_update(None,"application_id",APPLICATION).unwrap();
  h.store.connection.execute("UPDATE records SET input_id=?1,payload=?2,digest=?3,ready=1,delivered=0 WHERE sequence=2",params![records[1].prepared().input()["input_id"].as_str().unwrap(),&raw,&physical]).unwrap();
  h.store.connection.execute("UPDATE meta SET payload=?1,digest=?2",params![&meta,&meta_sha]).unwrap();h.store.connection.execute("UPDATE state SET last_hash=?1",[&head]).unwrap();
  assert_eq!(h.components.position_order_view(&h.store).unwrap(),expected);
 }
}
#[test]
fn a_legal_pending_tail_is_not_a_ready_prefix_and_still_recovers_the_original_transaction(){
 struct Unknown<'a>(&'a mut SqliteStore);
 impl Store for Unknown<'_> {
  fn head(&self)->Result<u64,Error>{self.0.head()}
  fn get(&self,n:u64)->Result<Option<Record>,Error>{self.0.get(n)}
  fn commit(&mut self,intent:&CommitIntent)->Result<Record,Error>{self.0.commit(intent)?;Err(Error("ORIGINAL_COMMIT_UNKNOWN".into()))}
  fn mark_ready(&mut self,n:u64)->Result<(),Error>{self.0.mark_ready(n)}
  fn acknowledge(&mut self,n:u64)->Result<(),Error>{self.0.acknowledge(n)}
 }
 let mut h=history(4,"12.00");let state=h.components.state(&h.store).unwrap();let checkpoint=h.components.checkpoint().unwrap();
 let value=input(5,"VALUATION",json!({"schema_version":1,"valuation":"prefix-pending","version":5,"position_evidence":hash(&checkpoint["components"][1]),"economic_version":state["account"]["snapshot"]["economic_version"],"marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":"12.00","source_ref":"prefix-pending-mark","family":"CLOSED_BAR","version":5,"time":5,"as_of_sequence":5}]}));
 let planned=h.components.prepare(&h.store,&value).unwrap();let original=planned.encode().unwrap();let error=coordinate(&mut Unknown(&mut h.store),&mut h.components,&planned).unwrap_err();assert_eq!(error.0,"ORIGINAL_COMMIT_UNKNOWN");assert_eq!(h.components.checkpoint().unwrap(),checkpoint);
 assert!(!h.store.get(5).unwrap().unwrap().ready());assert!(h.components.position_order_view(&h.store).is_err());let before=fs::read(h.root.db()).unwrap();assert!(h.store.save_checkpoint(&h.components).is_err());assert_eq!(fs::read(h.root.db()).unwrap(),before);
 let reference=h.reference.prepare(&value).unwrap();coordinate(&mut h.reference.store,&mut h.reference.components,&reference).unwrap();
 recover(&mut h.store,&mut h.components).unwrap();assert_eq!(h.store.get(5).unwrap().unwrap().prepared().encode().unwrap(),original);assert!(h.store.get(5).unwrap().unwrap().ready());assert_eq!(h.store.head().unwrap(),5);
 assert_eq!(h.components.checkpoint().unwrap(),h.reference.components.checkpoint().unwrap());assert_eq!(h.components.position_order_view(&h.store).unwrap(),h.reference.components.position_order_view(&h.reference.store).unwrap());
}

#[test]
fn sqlite_zero_prefix_still_observes_every_actual_row_header_identity_and_head(){
 let h=dictionary_history();let count=h.inputs.len() as u64;reset_source_work();
 assert!(h.store.read_prefix(0).unwrap().unwrap().is_empty());assert_eq!(SOURCE_RAW_ROWS.with(std::cell::Cell::get),count);
 assert!(h.store.read_prefix(count+1).is_err(),"an absent requested prefix is not partial success");
 let (meta,physical):(String,String)=h.store.connection.query_row("SELECT payload,digest FROM meta",[],|row|Ok((row.get(0)?,row.get(1)?))).unwrap();
 let head:String=h.store.connection.query_row("SELECT last_hash FROM state",[],|row|row.get(0)).unwrap();
 for fault in ["version","application","identity","head","old-flags"] {
  match fault {
   "version"=>h.store.connection.pragma_update(None,"user_version",3_i64).unwrap(),
   "application"=>h.store.connection.pragma_update(None,"application_id",0_i64).unwrap(),
   "identity"=>{h.store.connection.execute("UPDATE meta SET digest=?1",["f".repeat(64)]).unwrap();},
   "head"=>{h.store.connection.execute("UPDATE state SET last_hash=?1",["f".repeat(64)]).unwrap();},
   _=>{h.store.connection.execute("UPDATE records SET ready=0,delivered=0 WHERE sequence=1",[]).unwrap();},
  }
  let before=fs::read(h.root.db()).unwrap();assert!(h.store.read_prefix(0).is_err(),"a zero request bypassed actual {fault}");assert_eq!(fs::read(h.root.db()).unwrap(),before);
  h.store.connection.pragma_update(None,"user_version",4_i64).unwrap();h.store.connection.pragma_update(None,"application_id",APPLICATION).unwrap();
  h.store.connection.execute("UPDATE meta SET payload=?1,digest=?2",params![&meta,&physical]).unwrap();h.store.connection.execute("UPDATE state SET last_hash=?1",[&head]).unwrap();h.store.connection.execute("UPDATE records SET ready=1 WHERE sequence=1",[]).unwrap();
  assert!(h.store.read_prefix(0).unwrap().unwrap().is_empty());
 }
}
