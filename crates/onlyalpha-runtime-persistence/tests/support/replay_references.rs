 use super::*;
 const FIXTURE:&str=include_str!("../../../../test-data/execution/domain-inputs.json");
 const SETTLEMENT_FIXTURE:&str=include_str!("../../../../test-data/settlement/common-v1.json");
 #[path="../../../../crates/onlyalpha-kernel/execution/tests/support/mod.rs"] mod support;
 use std::{fs,path::PathBuf,sync::atomic::{AtomicU64,Ordering}};
 static NEXT:AtomicU64=AtomicU64::new(0);
 struct Root(PathBuf);
 impl Root{fn new()->Self{let p=std::env::temp_dir().join(format!("oa-replay-ref-{}-{}",std::process::id(),NEXT.fetch_add(1,Ordering::Relaxed)));fs::create_dir(&p).unwrap();Self(p)}}
 impl Drop for Root{fn drop(&mut self){fs::remove_dir_all(&self.0).unwrap();}}
 fn binding()->Value{json!({"schema_version":1,"configuration":sha(&support::config()),"kernel_artifact":"b".repeat(64),"driver_artifact":"f".repeat(64),"work":"c".repeat(64),"input_pin":"d".repeat(64),"program":"e".repeat(64),"initial_state":{"cursor":0}})}
 fn step(n:u64,previous:&str)->Value{json!({"schema_version":1,"index":n,"previous":previous,"execution_start":0,"cause":{"kind":"BAR"},"inputs":[],"state":{"cursor":n,"complete_seen_history":"price-volume-history-".repeat(8192)}})}
 #[test]fn fresh_reference_verification_never_expands_prior_steps_and_exact_streams_keep_all_history(){
  let root=Root::new();let mut runtime=Runtime::create(&root.0,support::config(),&"b".repeat(64)).unwrap();runtime.bind_replay(&binding()).unwrap();let mut refs=Vec::new();let mut originals=Vec::new();
  for n in 1..=16 {let previous=refs.last().map(ReplayEntryRef::logical_fingerprint).map(str::to_owned).unwrap_or_else(||sha(&binding()));let value=step(n,&previous);let original=runtime.prepare_replay_ref(&refs,&value).unwrap();refs=runtime.complete_replay_ref(&refs,&original).unwrap();originals.push(value);}
  codec::DECODED_BYTES.with(|count|count.set(0));for _ in 0..4{runtime.verify_replay_refs(&refs).unwrap();}assert_eq!(codec::DECODED_BYTES.with(std::cell::Cell::get),0,"fresh whole-source verification expanded complete retained histories");
  for (reference,value) in refs.iter().zip(&originals){let mut encoded=Vec::new();assert_eq!(runtime.write_encoded_step(reference,&mut encoded).unwrap(),reference.encoded_size());assert_eq!(digest(&encoded),reference.physical_fingerprint());assert_eq!(runtime.read_replay_step(reference).unwrap(),*value);assert_eq!(reference.logical_fingerprint(),sha(value));}
  drop(runtime);
 }
 #[test]fn fully_resealed_pending_body_cannot_replace_original_proposal_or_write_ready(){
  let root=Root::new();let mut runtime=Runtime::create(&root.0,support::config(),&"b".repeat(64)).unwrap();runtime.bind_replay(&binding()).unwrap();let value=step(1,&sha(&binding()));let original=runtime.prepare_replay_ref(&[],&value).unwrap();
  let mut changed=value.clone();changed["state"]["cursor"]=json!(999);let raw=crate::dictionary_codec::encode(&changed,summary(&changed).unwrap(),1,None).unwrap();let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();
  db.execute("UPDATE replay_steps SET payload=?1,digest=?2 WHERE sequence=1",params![&raw,digest(raw.as_bytes())]).unwrap();db.execute("UPDATE replay_binding SET last_hash=?1",[sha(&changed)]).unwrap();drop(db);
  let bytes=fs::read(root.0.join("runtime.sqlite3")).unwrap();assert!(runtime.complete_replay_ref(&[],&original).is_err());assert_eq!(fs::read(root.0.join("runtime.sqlite3")).unwrap(),bytes);
  let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();assert_eq!(db.query_row("SELECT ready FROM replay_steps WHERE sequence=1",[],|r|r.get::<_,i64>(0)).unwrap(),0);drop(db);assert!(runtime.replay_refs().is_err());drop(runtime);
 }
 #[test]fn original_pending_reference_recovers_after_ready_readback_fault_without_new_identity(){
  let root=Root::new();let mut runtime=Runtime::create(&root.0,support::config(),&"b".repeat(64)).unwrap();runtime.bind_replay(&binding()).unwrap();let value=step(1,&sha(&binding()));let original=runtime.prepare_replay_ref(&[],&value).unwrap();
  let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();db.execute_batch("CREATE TRIGGER codec_ready_fault AFTER UPDATE OF ready ON replay_steps WHEN NEW.ready=1 BEGIN UPDATE replay_steps SET ready=0 WHERE sequence=NEW.sequence; END").unwrap();assert!(runtime.complete_replay_ref(&[],&original).is_err());db.execute_batch("DROP TRIGGER codec_ready_fault").unwrap();drop(db);
  runtime.recover().unwrap();let completed=runtime.complete_replay_ref(&[],&original).unwrap();assert_eq!(completed.len(),1);assert!(completed[0].ready());assert_eq!(completed[0].logical_fingerprint(),original.logical_fingerprint());assert_eq!(completed[0].physical_fingerprint(),original.physical_fingerprint());assert_eq!(runtime.read_replay_step(&completed[0]).unwrap(),value);drop(runtime);
 }


fn reference_history(count:u64)->(Runtime,Root,Vec<ReplayEntryRef>){
 let root=Root::new();let mut runtime=Runtime::create(&root.0,support::config(),&"b".repeat(64)).unwrap();runtime.bind_replay(&binding()).unwrap();let mut refs:Vec<ReplayEntryRef>=Vec::new();
 for n in 1..=count {let previous=refs.last().map(ReplayEntryRef::logical_fingerprint).map(str::to_owned).unwrap_or_else(||sha(&binding()));let value=step(n,&previous);let pending=runtime.prepare_replay_ref(&refs,&value).unwrap();refs=runtime.complete_replay_ref(&refs,&pending).unwrap();}
 (runtime,root,refs)
}
fn reset_reference_work(){REFERENCE_FRAME_INSPECTIONS.with(|count|count.set(0));REFERENCE_SOURCE_ROWS.with(|count|count.set(0));codec::PHYSICAL_HASHES.with(|count|count.set(0));codec::DECODED_BYTES.with(|count|count.set(0));}
#[test]
fn exact_reference_metadata_reuses_only_codec_work_and_reads_every_actual_row(){
 for count in [16,32] {
  let (runtime,root,expected)=reference_history(count);assert_eq!(runtime.replay_refs().unwrap(),expected);reset_reference_work();
  for _ in 0..4 {runtime.verify_replay_refs(&expected).unwrap();}
  assert_eq!(REFERENCE_SOURCE_ROWS.with(std::cell::Cell::get),4*count,"every actual sequence/payload/digest/Ready row must still be read");
  assert_eq!(REFERENCE_FRAME_INSPECTIONS.with(std::cell::Cell::get),0,"identical complete encoded rows repeatedly parsed their frame metadata");
  assert_eq!(codec::PHYSICAL_HASHES.with(std::cell::Cell::get),0);assert_eq!(codec::DECODED_BYTES.with(std::cell::Cell::get),0);
  // An independently valid Ready change remains visible even on a codec hit.
  let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();db.execute("UPDATE replay_steps SET ready=0 WHERE sequence=?1",[count as i64]).unwrap();drop(db);reset_reference_work();
  let changed=runtime.replay_refs().unwrap();assert!(!changed.last().unwrap().ready());assert!(runtime.verify_replay_refs(&expected).is_err());
  assert_eq!(REFERENCE_SOURCE_ROWS.with(std::cell::Cell::get),2*count);assert_eq!(REFERENCE_FRAME_INSPECTIONS.with(std::cell::Cell::get),0,"Ready is freshly observed, not cached with immutable codec metadata");
  let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();db.execute("UPDATE replay_steps SET ready=1 WHERE sequence=?1",[count as i64]).unwrap();drop(db);drop(runtime);
  let reopened=Runtime::open(&root.0,support::config(),&"b".repeat(64)).unwrap();reset_reference_work();assert_eq!(reopened.replay_refs().unwrap(),expected);
  assert_eq!(REFERENCE_FRAME_INSPECTIONS.with(std::cell::Cell::get),count,"a new Store must inspect its own actual bytes rather than inherit an earlier codec memo");drop(reopened);
 }
}
#[test]
fn warm_reference_metadata_cannot_hide_actual_source_or_resealed_body_changes(){
 for fault in ["digest","raw","invalid-ready","earlier-unready","missing-tail","head","header","index","previous","execution-start","fully-resealed-state","summary-body"] {
  let (runtime,root,expected)=reference_history(4);runtime.verify_replay_refs(&expected).unwrap();reset_reference_work();
  let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();
  match fault {
   "digest"=>{db.execute("UPDATE replay_steps SET digest=?1 WHERE sequence=2",["f".repeat(64)]).unwrap();},
   "raw"=>{db.execute("UPDATE replay_steps SET payload=payload||' ' WHERE sequence=2",[]).unwrap();},
   "invalid-ready"=>{db.execute_batch("PRAGMA ignore_check_constraints=ON; UPDATE replay_steps SET ready=2 WHERE sequence=2; PRAGMA ignore_check_constraints=OFF;").unwrap();},
   "earlier-unready"=>{db.execute("UPDATE replay_steps SET ready=0 WHERE sequence=2",[]).unwrap();},
   "missing-tail"=>{db.execute("DELETE FROM replay_steps WHERE sequence=4",[]).unwrap();},
   "head"=>{db.execute("UPDATE replay_binding SET head=head-1",[]).unwrap();},
   "header"=>{assert_eq!(db.pragma_query_value(None,"user_version",|row|row.get::<_,i64>(0)).unwrap(),4);db.pragma_update(None,"user_version",5).unwrap();},
   _=>{
    let rows:Vec<(i64,String)>=db.prepare("SELECT sequence,payload FROM replay_steps ORDER BY sequence").unwrap().query_map([],|row|Ok((row.get(0)?,row.get(1)?))).unwrap().collect::<rusqlite::Result<_>>().unwrap();
    let mut previous=sha(&binding());
    let mut old_anchor=None;let mut new_anchor=None;
    for (n,raw) in rows {
     let frame=crate::dictionary_codec::inspect(&raw,&digest(raw.as_bytes()),n as u64).unwrap();
     let mut value=if frame.basis.is_none(){let (v,a)=crate::dictionary_codec::decode_anchor(&frame).unwrap();old_anchor=Some(a);v}else{crate::dictionary_codec::decode(&frame,old_anchor.as_ref()).unwrap()};value["previous"]=json!(previous);
     if n==2 {match fault {"index"=>value["index"]=json!(999),"previous"=>value["previous"]=json!("f".repeat(64)),"execution-start"=>value["execution_start"]=json!(1),"fully-resealed-state"=>value["state"]["cursor"]=json!(999),_=>()}}
     let mut metadata=summary(&value).unwrap();if n==2&&fault=="summary-body"{metadata["execution_start"]=json!(1);}
     let anchored=crate::dictionary_codec::anchor_sequence(n as u64).unwrap()==n as u64;
     let raw=crate::dictionary_codec::encode(&value,metadata,n as u64,if anchored{None}else{new_anchor.as_ref()}).unwrap();previous=sha(&value);
     if anchored{let f=crate::dictionary_codec::inspect(&raw,&digest(raw.as_bytes()),n as u64).unwrap();new_anchor=Some(crate::dictionary_codec::decode_anchor(&f).unwrap().1);}
     db.execute("UPDATE replay_steps SET payload=?1,digest=?2 WHERE sequence=?3",params![&raw,digest(raw.as_bytes()),n]).unwrap();
    }
    db.execute("UPDATE replay_binding SET last_hash=?1",[previous]).unwrap();
   },
  }
  drop(db);let before=fs::read(root.0.join("runtime.sqlite3")).unwrap();reset_reference_work();
  assert!(runtime.verify_replay_refs(&expected).is_err(),"warm codec metadata hid actual source fault {fault}");
  if matches!(fault,"index"|"previous"|"execution-start"|"fully-resealed-state"|"summary-body") {assert!(REFERENCE_FRAME_INSPECTIONS.with(std::cell::Cell::get)>0,"changed actual bytes must pass through the original frame inspector: {fault}");}
  if fault=="fully-resealed-state" {let changed=runtime.replay_refs().unwrap();assert_ne!(changed,expected);assert_eq!(runtime.read_replay_step(&changed[1]).unwrap()["state"]["cursor"],999);}
  if fault=="summary-body" {let(raw,physical,ready):(String,String,i64)=runtime.store.connection.query_row("SELECT payload,digest,ready FROM replay_steps WHERE sequence=2",[],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?))).unwrap();let changed=from_frame(&raw,&physical,2,ready,4).unwrap();assert_eq!(runtime.read_replay_step(&changed).unwrap_err().0,"RUNTIME_REPLAY_REFERENCE_BODY");}
  assert_eq!(fs::read(root.0.join("runtime.sqlite3")).unwrap(),before,"a rejected source observation cannot repair history: {fault}");drop(runtime);
 }
}

#[test]
fn fresh_reference_relation_reuses_only_the_current_actual_immutable_input_hash(){
 let root=Root::new();let mut runtime=Runtime::create(&root.0,support::config(),&"b".repeat(64)).unwrap();runtime.bind_replay(&binding()).unwrap();
 let input=support::open(1,"BUY");let mut value=step(1,&sha(&binding()));value["inputs"]=json!([input]);
 let proposed=runtime.prepare_replay_ref(&[],&value).unwrap();runtime.apply(&input).unwrap();let refs=runtime.complete_replay_ref(&[],&proposed).unwrap();
 REFERENCE_INPUT_HASHES.with(|watch|*watch.borrow_mut()=Some((input.clone(),0)));REFERENCE_SOURCE_ROWS.with(|count|count.set(0));
 for _ in 0..4 {runtime.verify_replay_refs(&refs).unwrap();}
 let hashes=REFERENCE_INPUT_HASHES.with(|watch|watch.borrow_mut().take().unwrap().1);
 assert_eq!(REFERENCE_SOURCE_ROWS.with(std::cell::Cell::get),4,"each public observation must reread its actual retained replay source");
 assert_eq!(hashes,0,"unchanged actual Prepared input was serialized and hashed again on every fresh source relation");
 // Replace only the actual committed input with another genuinely planned
 // complete same-scope Record. Same input_id must not select the old memo.
 let mut changed=input.clone();changed["source_ref"]=json!("different-original-source");
 let mut foreign=support::Harness::new(support::config()).unwrap();let planned=foreign.prepare(&changed).unwrap();onlyalpha_execution::coordinate(&mut foreign.store,&mut foreign.components,&planned).unwrap();
 let record=foreign.store.rows[0].prepared();let body=record.record();
 let raw=crate::dictionary_codec::encode(&body,json!({"kind":"EXECUTION_PREPARED","sequence":1,"input_id":changed["input_id"]}),1,None).unwrap();let physical=digest(raw.as_bytes());
 let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();
 db.execute("UPDATE records SET payload=?1,digest=?2 WHERE sequence=1",params![&raw,&physical]).unwrap();
 db.execute("UPDATE state SET last_hash=?1",[digest(record.encode().unwrap().as_slice())]).unwrap();drop(db);
 let before=fs::read(root.0.join("runtime.sqlite3")).unwrap();let actual=runtime.store.read_records().unwrap();assert_eq!(actual[0].prepared().input(),&changed);
 assert_eq!(runtime.store.replay_refs_from_source(&actual).unwrap_err().0,"RUNTIME_REPLAY_EXECUTION_RELATION");
 assert!(runtime.verify_replay_refs(&refs).is_err());assert_eq!(fs::read(root.0.join("runtime.sqlite3")).unwrap(),before);
 drop(runtime);
}


fn execution_reference_head()->(Runtime,Root,Vec<ReplayEntryRef>){
 let root=Root::new();let mut runtime=Runtime::create(&root.0,support::config(),&"b".repeat(64)).unwrap();runtime.bind_replay(&binding()).unwrap();
 let input=support::open(1,"BUY");let mut first=step(1,&sha(&binding()));first["inputs"]=json!([input]);
 let original=runtime.prepare_replay_ref(&[],&first).unwrap();runtime.apply(&input).unwrap();
 let ready=runtime.complete_replay_ref(&[],&original).unwrap();assert_eq!(runtime.records().unwrap().len(),1);
 (runtime,root,ready)
}
fn next_at_head(prefix:&[ReplayEntryRef])->Value{let mut value=step(prefix.len() as u64+1,prefix.last().unwrap().logical_fingerprint());value["execution_start"]=json!(1);value}
fn reset_actual_source_rows(){crate::store::SOURCE_RAW_ROWS.with(|count|count.set(0));REFERENCE_SOURCE_ROWS.with(|count|count.set(0));}
#[test]
fn prepare_reference_reads_each_execution_row_once_before_and_independently_after_write(){
 let (mut runtime,root,prefix)=execution_reference_head();let value=next_at_head(&prefix);reset_actual_source_rows();
 let original=runtime.prepare_replay_ref(&prefix,&value).unwrap();
 assert_eq!(crate::store::SOURCE_RAW_ROWS.with(std::cell::Cell::get),2,"prepare repeated an actual complete Execution SQL scan within its single pre-write source cut");
 assert_eq!(REFERENCE_SOURCE_ROWS.with(std::cell::Cell::get),3,"both old Replay prefix and complete post-insert rows must be freshly visited");
 assert_eq!(original.index(),2);assert!(!original.ready());assert_eq!(runtime.read_replay_step(&original).unwrap(),value);
 assert_eq!(runtime.complete_replay_ref(&prefix,&original).unwrap().len(),2);drop(runtime);drop(root);
}
#[test]
fn complete_reference_reads_each_execution_row_once_before_and_independently_after_write(){
 let (mut runtime,root,prefix)=execution_reference_head();let value=next_at_head(&prefix);let original=runtime.prepare_replay_ref(&prefix,&value).unwrap();reset_actual_source_rows();
 let completed=runtime.complete_replay_ref(&prefix,&original).unwrap();
 assert_eq!(crate::store::SOURCE_RAW_ROWS.with(std::cell::Cell::get),2,"complete repeated an actual complete Execution SQL scan within a single pre/post source cut");
 assert_eq!(REFERENCE_SOURCE_ROWS.with(std::cell::Cell::get),4,"Ready completion must freshly read the entire actual Replay prefix before and after mutation");
 assert!(completed[1].ready());assert_eq!(completed[1].logical_fingerprint(),original.logical_fingerprint());assert_eq!(completed[1].physical_fingerprint(),original.physical_fingerprint());drop(runtime);drop(root);
}
#[test]
fn shared_prewrite_source_never_hides_a_write_trigger_changing_actual_execution_history(){
 for preparing in [true,false]{
  let (mut runtime,root,prefix)=execution_reference_head();let value=next_at_head(&prefix);
  let original=if preparing{None}else{Some(runtime.prepare_replay_ref(&prefix,&value).unwrap())};
  let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();
  let original_digest:String=db.query_row("SELECT digest FROM records WHERE sequence=1",[],|row|row.get(0)).unwrap();
  let trigger=if preparing{"CREATE TRIGGER same_cut_fault AFTER INSERT ON replay_steps WHEN NEW.sequence=2 BEGIN UPDATE records SET digest=printf('%064d',0) WHERE sequence=1; END"}else{"CREATE TRIGGER same_cut_fault AFTER UPDATE OF ready ON replay_steps WHEN NEW.sequence=2 BEGIN UPDATE records SET digest=printf('%064d',0) WHERE sequence=1; END"};
  db.execute_batch(trigger).unwrap();
  if preparing{assert!(runtime.prepare_replay_ref(&prefix,&value).is_err());}else{assert!(runtime.complete_replay_ref(&prefix,original.as_ref().unwrap()).is_err());}
  let retained:(String,String,i64)=db.query_row("SELECT payload,digest,ready FROM replay_steps WHERE sequence=2",[],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?))).unwrap();
  assert_eq!(db.query_row("SELECT COUNT(*) FROM replay_steps",[],|row|row.get::<_,i64>(0)).unwrap(),2,"the committed original operation must remain under the same identity");
  db.execute_batch("DROP TRIGGER same_cut_fault").unwrap();db.execute("UPDATE records SET digest=?1 WHERE sequence=1",[original_digest]).unwrap();
  assert!(runtime.replay_refs().is_err(),"restoring source bytes cannot bypass explicit recovery after a failed post-write cut");
  assert!(runtime.prepare_replay_ref(&prefix,&value).is_err());
  assert_eq!(db.query_row("SELECT COUNT(*) FROM replay_steps",[],|row|row.get::<_,i64>(0)).unwrap(),2);
  runtime.recover().unwrap();
  let recovered=runtime.prepare_replay_ref(&prefix,&value).unwrap();assert_eq!(recovered.physical_fingerprint(),retained.1);assert_eq!(runtime.read_replay_step(&recovered).unwrap(),value);
  let completed=runtime.complete_replay_ref(&prefix,&recovered).unwrap();assert_eq!(completed.len(),2);assert!(completed[1].ready());
  assert_eq!(db.query_row("SELECT payload,digest FROM replay_steps WHERE sequence=2",[],|row|Ok((row.get::<_,String>(0)?,row.get::<_,String>(1)?))).unwrap(),(retained.0,retained.1));
  drop(db);drop(runtime);drop(root);
 }
}


#[test]
fn replay_reference_sql_scans_borrow_complete_raw_rows_and_keep_only_one_cold_memo_copy(){
 for count in [8_u64,16]{
  let (runtime,root,expected)=reference_history(count);runtime.verify_replay_refs(&expected).unwrap();
  let bytes=fs::read(root.0.join("runtime.sqlite3")).unwrap();
  REFERENCE_SOURCE_ROWS.with(|value|value.set(0));REFERENCE_OWNED_RAW_BYTES.with(|value|value.set(0));
  for _ in 0..4{runtime.verify_replay_refs(&expected).unwrap();}
  assert_eq!(REFERENCE_SOURCE_ROWS.with(std::cell::Cell::get),4*count,"every complete actual Replay row must still be visited on each public observation");
  assert_eq!(REFERENCE_OWNED_RAW_BYTES.with(std::cell::Cell::get),0,"a warm reference scan copied complete SQL payload strings which no consumer owns");
  assert_eq!(runtime.replay_refs().unwrap(),expected);
  let retained_bytes=u64::try_from(runtime.store.connection.query_row("SELECT SUM(length(CAST(payload AS BLOB))) FROM replay_steps",[],|row|row.get::<_,i64>(0)).unwrap()).unwrap();
  assert!(retained_bytes>0);runtime.store.replay_reference_metadata.borrow_mut().clear();
  REFERENCE_SOURCE_ROWS.with(|value|value.set(0));REFERENCE_OWNED_RAW_BYTES.with(|value|value.set(0));REFERENCE_FRAME_INSPECTIONS.with(|value|value.set(0));codec::DECODED_BYTES.with(|value|value.set(0));
  assert_eq!(runtime.replay_refs().unwrap(),expected);
  assert_eq!(REFERENCE_SOURCE_ROWS.with(std::cell::Cell::get),count);
  assert_eq!(REFERENCE_FRAME_INSPECTIONS.with(std::cell::Cell::get),count,"cold actual bytes must still pass the complete frame inspector");
  assert_eq!(REFERENCE_OWNED_RAW_BYTES.with(std::cell::Cell::get),retained_bytes,"the exact immutable codec memo still owns one complete actual payload copy");
  assert_eq!(codec::DECODED_BYTES.with(std::cell::Cell::get),0,"reference inventory must not expand historical logical bodies");
  assert_eq!(fs::read(root.0.join("runtime.sqlite3")).unwrap(),bytes,"a borrowed source observation cannot write or repair history");
  drop(runtime);drop(root);
 }
}

#[test]
fn warm_replay_metadata_never_coerces_invalid_sql_text_or_utf8_into_old_source_bytes(){
 for fault in ["payload-utf8","digest-utf8","payload-blob","digest-blob"]{
  let (runtime,root,expected)=reference_history(2);runtime.verify_replay_refs(&expected).unwrap();
  let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();
  if fault.ends_with("-blob"){
   // Fault injection only: remove the STRICT storage constraint so an actual
   // BLOB can exercise the native reader's own SQL type rejection.
   db.execute_batch("PRAGMA writable_schema=ON; UPDATE sqlite_schema SET sql=replace(sql,' STRICT','') WHERE name='replay_steps'; PRAGMA writable_schema=OFF;").unwrap();
   let version:i64=db.pragma_query_value(None,"schema_version",|row|row.get(0)).unwrap();
   db.pragma_update(None,"schema_version",version+1).unwrap();
  }
  let statement=match fault{
   "payload-utf8"=>"UPDATE replay_steps SET payload=CAST(X'80' AS TEXT) WHERE sequence=1",
   "digest-utf8"=>"UPDATE replay_steps SET digest=CAST(X'80' AS TEXT) WHERE sequence=1",
   "payload-blob"=>"UPDATE replay_steps SET payload=CAST(payload AS BLOB) WHERE sequence=1",
   "digest-blob"=>"UPDATE replay_steps SET digest=CAST(digest AS BLOB) WHERE sequence=1",
   _=>unreachable!(),
  };
  db.execute_batch(statement).unwrap();
  let column=if fault.starts_with("payload-"){0}else{1};
  let types:(String,String)=db.query_row("SELECT typeof(payload),typeof(digest) FROM replay_steps WHERE sequence=1",[],|row|Ok((row.get(0)?,row.get(1)?))).unwrap();
  assert_eq!(if column==0{types.0}else{types.1},if fault.ends_with("-blob"){"blob"}else{"text"});
  drop(db);let before=fs::read(root.0.join("runtime.sqlite3")).unwrap();
  assert!(runtime.replay_refs().is_err(),"a warm codec memo hid malformed actual SQL data: {fault}");
  assert!(runtime.verify_replay_refs(&expected).is_err(),"old references cannot validate a coerced field: {fault}");
  assert_eq!(fs::read(root.0.join("runtime.sqlite3")).unwrap(),before,"malformed SQL data must be refused without repair: {fault}");
  drop(runtime);drop(root);
 }
}

#[test]
fn replay_dictionary_memos_never_replace_a_missing_foreign_or_legally_resealed_actual_base(){
 for fault in ["missing","foreign","logical","physical"] {
  let (runtime,root,expected)=reference_history(4);
  let originals=expected.iter().map(|r|runtime.read_replay_step(r).unwrap()).collect::<Vec<_>>();
  let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();
  let raw:String=db.query_row("SELECT payload FROM replay_steps WHERE sequence=1",[],|r|r.get(0)).unwrap();
  if fault=="missing"{db.execute("DELETE FROM replay_steps WHERE sequence=1",[]).unwrap();}
  else {
   let mut value=originals[0].clone();
   let replacement=if fault=="foreign"{
    let h=support::Harness::new(support::config()).unwrap();let p=h.prepare(&support::open(1,"BUY")).unwrap();
    crate::dictionary_codec::encode(p.value(),json!({"kind":"EXECUTION_PREPARED","sequence":1,"input_id":p.input()["input_id"]}),1,None).unwrap()
   }else if fault=="logical"{value["state"]["cursor"]=json!(999);crate::dictionary_codec::encode(&value,summary(&value).unwrap(),1,None).unwrap()}
   else {
    use base64::Engine;let mut frame:Value=serde_json::from_str(&raw).unwrap();let compressed=zstd::bulk::compress(&serde_json::to_vec(&value).unwrap(),9).unwrap();frame["data"]=json!(base64::engine::general_purpose::STANDARD.encode(compressed));frame.to_string()
   };
   assert_ne!(replacement,raw);
   let physical=digest(replacement.as_bytes());let frame=crate::dictionary_codec::inspect(&replacement,&physical,1).unwrap();let decoded=crate::dictionary_codec::decode_anchor(&frame).unwrap();
   if fault!="foreign"{assert_eq!(decoded.0,value);assert_eq!(frame.summary,summary(&value).unwrap());}
   db.execute("UPDATE replay_steps SET payload=?1,digest=?2 WHERE sequence=1",params![&replacement,&physical]).unwrap();
  }
  let damaged=fs::read(root.0.join("runtime.sqlite3")).unwrap();
  assert!(runtime.read_replay_step(&expected[1]).is_err(),"a warm dependent reused an old actual base: {fault}");
  assert!(runtime.replay_refs().is_err(),"fresh scan ignored actual base: {fault}");assert_eq!(fs::read(root.0.join("runtime.sqlite3")).unwrap(),damaged);
  if fault=="physical"{
   let (raw,physical):(String,String)=db.query_row("SELECT payload,digest FROM replay_steps WHERE sequence=1",[],|r|Ok((r.get(0)?,r.get(1)?))).unwrap();let f=crate::dictionary_codec::inspect(&raw,&physical,1).unwrap();let anchor=crate::dictionary_codec::decode_anchor(&f).unwrap().1;
   for (index,value) in originals.iter().enumerate().skip(1){let raw=crate::dictionary_codec::encode(value,summary(value).unwrap(),index as u64+1,Some(&anchor)).unwrap();db.execute("UPDATE replay_steps SET payload=?1,digest=?2 WHERE sequence=?3",params![&raw,digest(raw.as_bytes()),index as i64+1]).unwrap();}
   let current=runtime.replay_refs().unwrap();assert_ne!(current,expected);assert!(runtime.verify_replay_refs(&expected).is_err());
   for (r,v) in current.iter().zip(&originals){assert_eq!(runtime.read_replay_step(r).unwrap(),*v);}
  }
  drop(db);drop(runtime);
 }
}
