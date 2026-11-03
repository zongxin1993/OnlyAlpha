//! Actual new-work storage boundaries; no Product admission or synthetic grant.
const FIXTURE:&str=include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE:&str=include_str!("../../../test-data/settlement/common-v1.json");
#[path="../../../crates/onlyalpha-kernel/execution/tests/support/mod.rs"] mod support;
use onlyalpha_runtime_persistence::Runtime;
use onlyalpha_execution::digest;
use serde_json::{Value,json};
use std::{fs,path::PathBuf,sync::atomic::{AtomicU64,Ordering}};
static NEXT:AtomicU64=AtomicU64::new(0);
struct Root(PathBuf);
impl Root {fn new()->Self{let path=std::env::temp_dir().join(format!("oa-storage3-{}-{}",std::process::id(),NEXT.fetch_add(1,Ordering::Relaxed)));fs::create_dir(&path).unwrap();Self(path)}}
impl Drop for Root {fn drop(&mut self){fs::remove_dir_all(&self.0).unwrap();}}
fn hash(v:&Value)->String{digest(v.to_string().as_bytes())}
fn binding()->Value{json!({"schema_version":1,"configuration":hash(&support::config()),"kernel_artifact":"b".repeat(64),"driver_artifact":"f".repeat(64),"work":"c".repeat(64),"input_pin":"d".repeat(64),"program":"e".repeat(64),"initial_state":{"cursor":0}})}
fn step(state:Value)->Value{json!({"schema_version":1,"index":1,"previous":hash(&binding()),"execution_start":0,"cause":{"kind":"BAR"},"inputs":[],"state":state})}
// Test-only empty historical format: no existing fact is converted.
fn selected_runtime(root:&Root,version:u32)->Runtime {
 let runtime=Runtime::create(&root.0,support::config(),&"b".repeat(64)).unwrap();
 assert_eq!(rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap().pragma_query_value(None,"user_version",|row|row.get::<_,i64>(0)).unwrap(),4,"new Work selects storage4");
 if version==4{return runtime;}
 assert_eq!(version,3);drop(runtime);
 let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();db.pragma_update(None,"user_version",3).unwrap();drop(db);
 Runtime::open(&root.0,support::config(),&"b".repeat(64)).unwrap()
}
#[test]
fn new_work_selects_storage4_and_retained_storage3_preserves_logical_step_identity() {
 for selected in [3_u32,4] {
 let root=Root::new();let mut runtime=selected_runtime(&root,selected);runtime.bind_replay(&binding()).unwrap();
 let original=step(json!({"cursor":1,"retained_history":"price-volume-".repeat(8192)}));runtime.prepare_replay(&original).unwrap();runtime.complete_replay(1).unwrap();
 assert_eq!(runtime.replay_steps().unwrap()[0],json!({"step":original,"ready":true}));
 let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();let version:i64=db.pragma_query_value(None,"user_version",|r|r.get(0)).unwrap();assert_eq!(version,i64::from(selected),"a new Work must explicitly select its new physical codec");
 let (raw,physical,last):(String,String,String)=db.query_row("SELECT s.payload,s.digest,b.last_hash FROM replay_steps s,replay_binding b WHERE s.sequence=1",[],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).unwrap();
 assert_eq!(physical,digest(raw.as_bytes()));assert_eq!(last,hash(&original));assert_ne!(physical,last);
 let frame:Value=serde_json::from_str(&raw).unwrap();assert_eq!(frame["codec"],if selected==3{"ZLIB_CANONICAL_JSON_V1"}else{"ZSTD_CANONICAL_JSON_DICTIONARY_V1"});assert_eq!(frame["logical_sha256"],last);assert!(raw.len()<original.to_string().len()/4);
 drop(db);drop(runtime);

 }
}
#[test]
fn new_logical_entry_limit_is_enforced_before_any_replay_write() {
 let root=Root::new();let mut runtime=Runtime::create(&root.0,support::config(),&"b".repeat(64)).unwrap();runtime.bind_replay(&binding()).unwrap();
 let oversized=step(json!({"retained_history":"x".repeat(8*1024*1024+1)}));let bytes=fs::read(root.0.join("runtime.sqlite3")).unwrap();
 assert!(runtime.prepare_replay(&oversized).is_err(),"a tiny compressed representation cannot bypass the eight-MiB logical entry bound");
 assert_eq!(fs::read(root.0.join("runtime.sqlite3")).unwrap(),bytes);drop(runtime);
}
#[test]
fn execution_prepared_frames_preserve_economics_and_keep_flags_fresh() {
 for selected in [3_u32,4] {
 let root=Root::new();let mut runtime=selected_runtime(&root,selected);
 for value in [support::open(1,"BUY"),support::stage(2,1,"UNKNOWN"),support::fill(3,1,"1","10.00","1.00"),support::terminal(4,1,"CANCELLED")] {runtime.apply(&value).unwrap();}
 let state=runtime.state().unwrap();let originals=runtime.records().unwrap();let events=runtime.pending_events().unwrap();assert_eq!(events.len(),4);
 let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();let version:i64=db.pragma_query_value(None,"user_version",|r|r.get(0)).unwrap();assert_eq!(version,i64::from(selected));
 let (raw,ready,delivered):(String,i64,i64)=db.query_row("SELECT payload,ready,delivered FROM records WHERE sequence=4",[],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).unwrap();
 let frame:Value=serde_json::from_str(&raw).unwrap();assert_eq!(frame["codec"],if selected==3{"ZLIB_CANONICAL_JSON_V1"}else{"ZSTD_CANONICAL_JSON_DICTIONARY_V1"});assert_eq!(frame["logical_sha256"],hash(&originals[3].prepared().record()));assert_eq!((ready,delivered),(1,0));drop(db);
 runtime.acknowledge(4).unwrap();assert_eq!(runtime.pending_events().unwrap().len(),3);assert_eq!(runtime.state().unwrap(),state);
 assert_eq!(runtime.records().unwrap()[3].record()["delivered"],true);drop(runtime);
 let reopened=Runtime::open(&root.0,support::config(),&"b".repeat(64)).unwrap();assert_eq!(reopened.state().unwrap(),state);assert_eq!(reopened.pending_events().unwrap().len(),3);drop(reopened);

 }
}

#[test]
fn warm_readers_refuse_changed_actual_sqlite_header_without_reselecting_a_codec() {
 for field in ["application_id","user_version"] {
  let root=Root::new();let mut runtime=Runtime::create(&root.0,support::config(),&"b".repeat(64)).unwrap();runtime.bind_replay(&binding()).unwrap();runtime.state().unwrap();runtime.records().unwrap();runtime.replay_steps().unwrap();
  let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();
  if field=="application_id" {db.pragma_update(None,field,12345_i64).unwrap();}else{let old:i64=db.pragma_query_value(None,field,|r|r.get(0)).unwrap();db.pragma_update(None,field,if old==3{2_i64}else{3_i64}).unwrap();}drop(db);
  let bytes=fs::read(root.0.join("runtime.sqlite3")).unwrap();assert!(runtime.state().is_err(),"{field}");assert!(runtime.records().is_err(),"{field}");assert!(runtime.replay_steps().is_err(),"{field}");assert_eq!(fs::read(root.0.join("runtime.sqlite3")).unwrap(),bytes);drop(runtime);
 }
}

#[test]
fn storage4_replay_steps_bind_fixed_actual_dictionary_anchors(){
 let root=Root::new();let mut runtime=selected_runtime(&root,4);runtime.bind_replay(&binding()).unwrap();let mut previous=hash(&binding());let mut expected=Vec::new();
 for index in 1..=18 {
  let mut body=step(json!({"cursor":index,"history":"retained canonical history".repeat(512)}));body["index"]=json!(index);body["previous"]=json!(previous);previous=hash(&body);
  runtime.prepare_replay(&body).unwrap();if index==17{let refs=runtime.replay_refs().unwrap();assert!(!refs.last().unwrap().ready());assert_eq!(runtime.read_replay_step(refs.last().unwrap()).unwrap(),body);}
  runtime.complete_replay(index).unwrap();expected.push(json!({"step":body,"ready":true}));
 }
 let original=runtime.replay_refs().unwrap();let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();
 for index in 1..=18 {
  let (raw,physical):(String,String)=db.query_row("SELECT payload,digest FROM replay_steps WHERE sequence=?1",[index],|r|Ok((r.get(0)?,r.get(1)?))).unwrap();let f:Value=serde_json::from_str(&raw).unwrap();assert_eq!(f["codec"],"ZSTD_CANONICAL_JSON_DICTIONARY_V1");assert_eq!(digest(raw.as_bytes()),physical);
  let base=(index-1)/16*16+1;
  if index==base {assert!(f["basis"].is_null());}else{
   let (raw,physical):(String,String)=db.query_row("SELECT payload,digest FROM replay_steps WHERE sequence=?1",[base],|r|Ok((r.get(0)?,r.get(1)?))).unwrap();let anchor:Value=serde_json::from_str(&raw).unwrap();assert_eq!(f["basis"],json!({"sequence":base,"physical_sha256":physical,"logical_sha256":anchor["logical_sha256"]}));
  }
 }
 assert_eq!(runtime.replay_steps().unwrap(),expected);
 db.execute("UPDATE replay_steps SET ready=0 WHERE sequence=1",[]).unwrap();assert!(runtime.verify_replay_refs(&original).is_err());assert!(runtime.read_replay_step(&original[1]).is_err());db.execute("UPDATE replay_steps SET ready=1 WHERE sequence=1",[]).unwrap();assert_eq!(runtime.replay_steps().unwrap(),expected);
 let (raw,physical):(String,String)=db.query_row("SELECT payload,digest FROM replay_steps WHERE sequence=1",[],|r|Ok((r.get(0)?,r.get(1)?))).unwrap();db.execute("UPDATE replay_steps SET digest=?1 WHERE sequence=1",["f".repeat(64)]).unwrap();assert!(runtime.read_replay_step(&original[1]).is_err());db.execute("UPDATE replay_steps SET payload=?1,digest=?2 WHERE sequence=1",rusqlite::params![raw,physical]).unwrap();assert_eq!(runtime.replay_steps().unwrap(),expected);drop(db);
}

fn retained_zlib_step(value:&Value)->String{
 use base64::Engine;use std::io::Write;
 let bytes=serde_json::to_vec(value).unwrap();let mut encoder=flate2::write::ZlibEncoder::new(Vec::new(),flate2::Compression::fast());encoder.write_all(&bytes).unwrap();
 let summary=json!({"kind":"REPLAY_STEP","index":value["index"],"previous":value["previous"],"execution_start":value["execution_start"],"input_fingerprints":value["inputs"].as_array().unwrap().iter().map(hash).collect::<Vec<_>>()});
 json!({"schema_version":1,"codec":"ZLIB_CANONICAL_JSON_V1","logical_sha256":digest(&bytes),"logical_size":bytes.len(),"summary":summary,"data":base64::engine::general_purpose::STANDARD.encode(encoder.finish().unwrap())}).to_string()
}
#[test]
fn storage4_reads_retained_zlib_and_new_dictionary_blocks_without_rewriting_original_bytes(){
 let root=Root::new();let mut runtime=selected_runtime(&root,4);runtime.bind_replay(&binding()).unwrap();let mut previous=hash(&binding());let mut expected=Vec::new();
 for index in 1..=18{let mut v=step(json!({"cursor":index}));v["index"]=json!(index);v["previous"]=json!(previous);previous=hash(&v);runtime.prepare_replay(&v).unwrap();runtime.complete_replay(index).unwrap();expected.push(v);}
 let old=runtime.replay_refs().unwrap();let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();
 for (index,v) in expected[..16].iter().enumerate(){let raw=retained_zlib_step(v);db.execute("UPDATE replay_steps SET payload=?1,digest=?2 WHERE sequence=?3",rusqlite::params![&raw,digest(raw.as_bytes()),index as i64+1]).unwrap();}drop(db);
 assert!(runtime.verify_replay_refs(&old).is_err());let refs=runtime.replay_refs().unwrap();
 for (i,r) in refs.iter().enumerate(){assert_eq!(runtime.read_replay_step(r).unwrap(),expected[i]);}
 runtime.save_checkpoint().unwrap();
 let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();let encoded=db.prepare("SELECT payload FROM replay_steps ORDER BY sequence").unwrap().query_map([],|r|r.get::<_,String>(0)).unwrap().collect::<rusqlite::Result<Vec<_>>>().unwrap();drop(db);
 drop(runtime);let before=fs::read(root.0.join("runtime.sqlite3")).unwrap();let reader=onlyalpha_runtime_persistence::VerifiedReplaySnapshot::read(&root.0,support::config(),&"b".repeat(64)).unwrap();
 let mut n=0;reader.for_each_step(|v,r|{assert!(r.ready());assert_eq!(v,&expected[n]);n+=1;Ok(())}).unwrap();assert_eq!(n,18);for (i,raw) in encoded.iter().enumerate(){let mut archive=Vec::new();reader.write_encoded_step(&reader.refs()[i],&mut archive).unwrap();assert_eq!(archive,raw.as_bytes());}reader.verify_cut().unwrap();assert_eq!(fs::read(root.0.join("runtime.sqlite3")).unwrap(),before);
}
#[test]
fn storage3_refuses_new_dictionary_tag_without_reselecting_its_physical_format(){
 let source=Root::new();let mut modern=selected_runtime(&source,4);modern.bind_replay(&binding()).unwrap();let v=step(json!({"cursor":1}));modern.prepare_replay(&v).unwrap();modern.complete_replay(1).unwrap();
 let db=rusqlite::Connection::open(source.0.join("runtime.sqlite3")).unwrap();let raw:String=db.query_row("SELECT payload FROM replay_steps",[],|r|r.get(0)).unwrap();drop(db);drop(modern);
 let root=Root::new();let mut old=selected_runtime(&root,3);old.bind_replay(&binding()).unwrap();old.prepare_replay(&v).unwrap();old.complete_replay(1).unwrap();let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();db.execute("UPDATE replay_steps SET payload=?1,digest=?2",rusqlite::params![&raw,digest(raw.as_bytes())]).unwrap();drop(db);
 let before=fs::read(root.0.join("runtime.sqlite3")).unwrap();assert!(old.replay_refs().is_err());assert!(old.replay_steps().is_err());assert_eq!(fs::read(root.0.join("runtime.sqlite3")).unwrap(),before);
}
