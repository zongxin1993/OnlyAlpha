//! A borrowed configuration must retain actual Runtime source/context checks.
use super::*;
use crate::execution_test_fixture::{configuration,original_three_facts};
use std::{fs,path::PathBuf,sync::atomic::{AtomicU64,Ordering}};
static NEXT:AtomicU64=AtomicU64::new(0);
struct Root(PathBuf);
impl Root{
 fn new()->Self{let root=std::env::temp_dir().join(format!("oa-candidate-config-{}-{}",std::process::id(),NEXT.fetch_add(1,Ordering::Relaxed)));fs::create_dir(&root).unwrap();Self(root)}
}
impl Drop for Root{fn drop(&mut self){fs::remove_dir_all(&self.0).unwrap();}}
fn runtime(root:&Root,configuration:&Value)->Runtime{
 let mut runtime=Runtime::create(&root.0,configuration.clone(),&"e".repeat(64)).unwrap();
 for input in original_three_facts(){runtime.apply(&input).unwrap();}
 assert_eq!(runtime.records().unwrap().iter().map(|record|record.prepared().input()["op"].as_str().unwrap()).collect::<Vec<_>>(),["ADMIT","SUBMISSION","FILL"]);
 runtime
}
#[test]
fn native_candidate_keeps_full_configuration_equality_and_original_economic_head(){
 for modern in [false,true]{
  let root=Root::new();let original=configuration(modern);let runtime=runtime(&root,&original);
  let before=runtime.state().unwrap();let records=runtime.records().unwrap();assert_eq!(records.len(),3);
  let candidate=Candidate::from_runtime_head(&runtime,original.clone()).unwrap();
  assert_eq!(candidate.configuration(),&original);assert_eq!(candidate.state().unwrap(),before);assert_eq!(candidate.records(),records);
  let mut detached=candidate.configuration().clone();detached["capitals"]["cluster"]=json!("0.00");
  assert_eq!(candidate.configuration(),&original,"a caller owns no mutable configuration alias");
  let mut changes=vec![
   ("/engine",json!("other-engine")),("/runtime",json!("other-runtime")),("/account",json!("other-account")),("/gateway",json!("other-gateway")),
   ("/generation",json!("b".repeat(64))),("/runtime_kind",json!("SIM")),("/currency/precision",json!(3)),("/currency/code",json!("USD")),
   ("/initial_cash",json!("999.00")),("/capitals/cluster",json!("999.00")),("/profiles/cluster/revision",json!("other-revision")),
   ("/profiles/cluster/instruments/0",json!("OTHER.X")),("/profiles/cluster/rules",json!([{"rule":"unrecognized"}])),("/instruments/0/quantity_precision",json!(2)),
  ];
  if modern{changes.push(("/account_checkpoint_version",json!(4)));}
  for (field,replacement) in changes{
   let mut foreign=original.clone();*foreign.pointer_mut(field).unwrap()=replacement;assert_ne!(foreign,original);
   assert_eq!(Candidate::from_runtime_head(&runtime,foreign).err().unwrap().0,"BACKTEST_REPLAY_EXECUTION_CONTEXT","the full configuration includes {field}");
  }
  let mut extra=original.clone();extra["unexpected_context"]=json!(true);
  assert_eq!(Candidate::from_runtime_head(&runtime,extra).err().unwrap().0,"BACKTEST_REPLAY_EXECUTION_CONTEXT");
  let mut missing=original.clone();missing.as_object_mut().unwrap().remove("capitals");
  assert_eq!(Candidate::from_runtime_head(&runtime,missing).err().unwrap().0,"BACKTEST_REPLAY_EXECUTION_CONTEXT");
  assert_eq!(runtime.state().unwrap(),before);assert_eq!(runtime.records().unwrap(),records);drop(runtime);
 }
}
#[test]
fn native_candidate_configuration_read_cannot_replace_the_fresh_full_runtime_source_check(){
 let root=Root::new();let original=configuration(false);let runtime=runtime(&root,&original);
 let before=runtime.state().unwrap();let records=runtime.records().unwrap();
 assert!(Candidate::from_runtime_head(&runtime,original.clone()).is_ok());
 let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();
 let digest:String=db.query_row("SELECT digest FROM records WHERE sequence=1",[],|row|row.get(0)).unwrap();
 db.execute("UPDATE records SET digest=?1 WHERE sequence=1",["0".repeat(64)]).unwrap();
 assert!(Candidate::from_runtime_head(&runtime,original.clone()).is_err(),"a matching configuration and earlier good candidate cannot authenticate an altered old source row");
 assert_eq!(db.query_row("SELECT digest FROM records WHERE sequence=1",[],|row|row.get::<_,String>(0)).unwrap(),"0".repeat(64),"a read must not repair the source");
 db.execute("UPDATE records SET digest=?1 WHERE sequence=1",[digest]).unwrap();
 let candidate=Candidate::from_runtime_head(&runtime,original).unwrap();assert_eq!(candidate.records(),records);assert_eq!(candidate.state().unwrap(),before);
 drop(db);drop(runtime);
}


#[test]
fn actual_memory_ready_record_copies_cannot_author_a_second_candidate_commit(){
    let configuration=configuration(false);let mut original=Candidate::new(configuration.clone(),vec![]).unwrap();
    original.apply(&original_three_facts()[0]).unwrap();let before=original.checkpoint().unwrap();
    let ready=original.records()[0].clone();assert!(ready.ready());assert!(!ready.delivered());
    let wire=ready.record();
    for passive in [ready.clone(),Record::decode(&wire).unwrap()]{
        assert_eq!(passive.record(),wire);
        let mut foreign=Candidate::new(configuration.clone(),vec![]).unwrap();let empty=foreign.checkpoint().unwrap();
        assert!(coordinate(&mut foreign.store,&mut foreign.components,passive.prepared()).is_err(),"Memory.mark_ready retained the original planner marker in a passive record");
        assert!(foreign.records().is_empty());assert_eq!(foreign.checkpoint().unwrap(),empty);
    }
    assert_eq!(original.records()[0].record(),wire);assert_eq!(original.checkpoint().unwrap(),before);
    original.store.records[0] = ready.with_observed_flags(true, true).unwrap();
    original.store.mark_ready(1).unwrap();
    let mut delivered = wire;
    delivered["delivered"] = json!(true);
    assert_eq!(original.records()[0].record(), delivered);
    assert_eq!(original.checkpoint().unwrap(), before);
}
